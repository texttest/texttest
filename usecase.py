
"""
The idea of this module is to implement a generic record/playback tool, independent of
particular GUIs or anything. Objects of class "ScriptEngine" may be constructed.

scriptEngine = ScriptEngine(recordScript, replayScript, stdinScript, logger = None)

These will then be capable of

(1) Recording standard input for later replay
    - This is acheived by calling scriptEngine.readStdin() instead of sys.stdin.readline()
    directly.
    
(2) Record and replaying external signals received by the process
    - This will just happen, whether you like it or not...
    
(3) Recording specified 'application events'
    - These are events that are not caused by the user doing something, generally the
    application enters a certain state. 

    scriptEngine.applicationEvent("idle handler exit")

    Recording will take the form of recording a "wait" command in the script, in this
    case as "wait for idle handler exit". When replaying, the script will suspend and
    wait to be told that this application event has occurred before proceeding.

    By default, these will overwrite each other, so that only the last one before any other event
    is recorded in the script.

    To override this, you can provide an optional second argument as a 'category', meaning that
    only events in the same category will overwrite each other. Events with no category will
    overwrite all events in all categories.

(4) Being extended to be able to deal with GUI events.
    - This is necessarily specific to particular GUI libraries. One such extension is currently
    available for PyGTK (gtkusecase.py)
"""

import os, string, sys
from threading import Thread
from ndict import seqdict

# Hard coded commands
waitCommandName = "wait for"

# Exception to throw when scripts go wrong
class UseCaseScriptError(RuntimeError):
    pass

# Base class for events caused by the action of a user on a GUI. Generally assumed
# to be doing something on a particular widget, and being named explicitly by the
# programmer in some language domain.

# Record scripts will call widgetHasChanged and will not record anything if this
# returns false: this is mainly for widgets with state. They will then call outputForScript
# and write this to the script

# Replay scripts will call generate in order to simulate the event over again.
class UserEvent:
    def __init__(self, name, widget):
        self.name = name
        self.widget = widget
    def widgetHasChanged(self):
        return 1
    def outputForScript(self, *args):
        return self.name
    def generate(self, argumentString):
        pass

class ScriptEngine:
    def __init__(self, replayScriptName, recordScriptName, logger = None):
        self.replayScript = None
        self.recordScript = None
        if replayScriptName and replayScriptName == recordScriptName:
            raise UseCaseScriptError, "Cannot record to the same script we are replaying"
        if replayScriptName:
            self.replayScript = self.createReplayScript(replayScriptName, logger)
        if recordScriptName:
            self.recordScript = RecordScript(recordScriptName)
    def hasScript(self):
        return self.replayScript or self.recordScript
    def createReplayScript(self, scriptName, logger):
        return ReplayScript(scriptName, logger)
    def standardName(self, name):
        firstIndex = None
        lastIndex = len(name)
        for i in range(len(name)):
            if name[i] in string.letters or name[i] in string.digits:
                if firstIndex is None:
                    firstIndex = i
                lastIndex = i
        return name[firstIndex:lastIndex + 1].lower()
    def applicationEvent(self, name, category = None):
        if self.replayScript:
            self.replayScript.registerApplicationEvent(name)
        if self.recordScript:
            self.recordScript.registerApplicationEvent(name, category)

class ReplayScript:
    def __init__(self, scriptName, logger):
        self.events = {}
        self.applicationEventNames = []
        self.commands = []
        self.pointer = 0
        self.logger = logger
        if not os.path.isfile(scriptName):
            raise UseCaseScriptError, "Cannot replay script " + scriptName + ", no such file or directory"
        for line in open(scriptName).xreadlines():
            if line != "" and line[0] != "#":
                self.commands.append(line.strip())
        self.enableReading()
    def addEvent(self, event):
        self.events[event.name] = event
    def enableReading(self):
        # If events fail, we store them and wait for the relevant handler
        self.waitingForEvent = None
        self.executeCommandsInBackground()
    def executeCommandsInBackground(self):
        # By default, we create a separate thread for background execution
        # GUIs will want to do this as idle handlers
        thread = Thread(target=self.runCommands)
        thread.start()
        #gtk.idle_add(method)
    def registerApplicationEvent(self, eventName):
        if self.waitingForEvent == eventName:
            self.write("Expected application event '" + eventName + "' occurred, proceeding.")
            self.enableReading()
        self.applicationEventNames.append(eventName)
    def isFinished(self):
        return self.pointer >= len(self.commands)
    def runCommands(self):
        while self.runNextCommand():
            pass
    def runNextCommand(self):
        if self.isFinished():
            return 0

        nextCommand = self.commands[self.pointer]
        # Filter blank lines and comments
        self.pointer += 1
        try:
            return self.processCommand(nextCommand)
        except UseCaseScriptError:
            type, value, traceback = sys.exc_info()
            self.write("ERROR: " + value)
            # We don't terminate scripts if they contain errors
        return 1
    def write(self, line):
        if self.logger:
            self.logger.info(line)
        else:
            print line
    def processCommand(self, scriptCommand):
        commandName, argumentString = self.parseCommand(scriptCommand)
        # Blank line... to make clear what belongs to what script command
        self.write("")
        if commandName == waitCommandName:
            return self.processWaitCommand(argumentString)
        else:
            self.generateEvent(commandName, argumentString)
            return 1
    def parseCommand(self, scriptCommand):
        commandName = self.findCommandName(scriptCommand)
        if not commandName:
            raise UseCaseScriptError, "Could not parse script command '" + scriptCommand + "'"
        argumentString = scriptCommand.replace(commandName, "").strip()
        return commandName, argumentString
    def findCommandName(self, command):
        if command.startswith(waitCommandName):
            return waitCommandName
        for eventName in self.events.keys():
            if command.startswith(eventName):
                return eventName
        return None            
    def generateEvent(self, eventName, argumentString):
        self.write("'" + eventName + "' event created with arguments '" + argumentString + "'")
        event = self.events[eventName]
        event.generate(argumentString)
        # Can be useful to uncomment if you want a slow-motion replay...
        #import time
        #time.sleep(2)
    def processWaitCommand(self, applicationEventName):
        if applicationEventName in self.applicationEventNames:
            self.write("Application event '" + applicationEventName + "' already occurred, not waiting.")
            return 1
        else:
            self.waitingForEvent = applicationEventName
            self.write("Waiting for application event '" + applicationEventName + "' to occur.")
            return 0

class RecordScript:
    def __init__(self, scriptName):
        self.fileForAppend = open(scriptName, "w")
        self.events = []
        self.applicationEvents = seqdict()
    def addEvent(self, event):
        self.events.append(event)
    def writeEvent(self, widget, *args):
        event = self.findEvent(*args)
        if event.widgetHasChanged():
            self.writeApplicationEventDetails()
            self.fileForAppend.write(event.outputForScript(*args) + os.linesep)
    def findEvent(self, *args):
        for arg in args:
            if isinstance(arg, UserEvent):
                return arg
    def registerApplicationEvent(self, eventName, category):
        if category:
            self.applicationEvents[category] = eventName
        else:
            # Non-categorised event makes all previous ones irrelevant
            self.applicationEvents = seqdict()
            self.applicationEvents["gtkscript_DEFAULT"] = eventName
    def writeApplicationEventDetails(self):
        for eventName in self.applicationEvents.values():
            self.fileForAppend.write(waitCommandName + " " + eventName + os.linesep)
        self.applicationEvents = seqdict()

            

