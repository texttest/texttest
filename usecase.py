
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

import os, string, sys, signal, time
from threading import Thread, currentThread
from ndict import seqdict

# Hard coded commands
waitCommandName = "wait for"
signalCommandName = "receive signal"

# Exception to throw when scripts go wrong
class UseCaseScriptError(RuntimeError):
    pass

# Base class for events caused by the action of a user on a GUI. Generally assumed
# to be doing something on a particular widget, and being named explicitly by the
# programmer in some language domain.

# Record scripts will call shouldRecord and will not record anything if this
# returns false: this is to allow for widgets with state which may not necessarily
# have changed in an appopriate way just because of the signal. They will then call outputForScript
# and write this to the script

# Replay scripts will call generate in order to simulate the event over again.
class UserEvent:
    def __init__(self, name):
        self.name = name
    def shouldRecord(self, *args):
        return 1
    def outputForScript(self, *args):
        return self.name
    def generate(self, argumentString):
        pass

# Behaves as a singleton...
class ScriptEngine:
    instance = None
    def __init__(self, logger = None):
        self.replayScript = None
        self.recordScript = None
        self.stdinScript = None
        prevArg = ""
        for arg in sys.argv[1:]:
            if prevArg.find("-replay") != -1:
                self.replayScript = self.createReplayScript(arg, logger)
            if prevArg.find("-record") != -1:
                self.recordScript = UseCaseRecordScript(arg)
            if prevArg.find("-recinp") != -1:
                self.stdinScript = RecordScript(arg)
            prevArg = arg
        self.thread = currentThread()
        ScriptEngine.instance = self
    def hasScript(self):
        return self.replayScript or self.recordScript
    def createReplayScript(self, scriptName, logger):
        return ReplayScript(scriptName, logger)
    def applicationEvent(self, name, category = None, timeDelay = 0):
        if currentThread() != self.thread:
            raise UseCaseScriptError, "Can only register application events in the same thread as the script engine"
        if self.recordScript:
            self.recordScript.registerApplicationEvent(name, category)
        if self.replayScript:
            self.replayScript.registerApplicationEvent(name, timeDelay)
    def readStdin(self):
        line = sys.stdin.readline().strip()
        if self.stdinScript:
            self.stdinScript.record(line)
        return line
    def standardName(self, name):
        return name.strip().lower()

class ReplayScript:
    def __init__(self, scriptName, logger):
        self.events = {}
        self.applicationEventNames = []
        self.commands = []
        self.pointer = 0
        self.logger = logger
        self.processId = os.getpid() # So we can generate signals for ourselves...
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
    def registerApplicationEvent(self, eventName, timeDelay = 0):
        if self.waitingForEvent == eventName:
            self.write("Expected application event '" + eventName + "' occurred, proceeding.")
            if timeDelay:
                time.sleep(timeDelay)
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
            self.write("ERROR: " + str(value))
            # We don't terminate scripts if they contain errors
        return 1
    def write(self, line):
        if self.logger:
            try:
                self.logger.info(line)
            except OSError:
                # Can get interrupted system call here as it tries to close the file
                # This isn't worth crashing over!
                pass
        else:
            print line
    def processCommand(self, scriptCommand):
        commandName, argumentString = self.parseCommand(scriptCommand)
        # Blank line... to make clear what belongs to what script command
        self.write("")
        if commandName == waitCommandName:
            return self.processWaitCommand(argumentString)
        elif commandName == signalCommandName:
            return self.processSignalCommand(argumentString)
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
        if command.startswith(signalCommandName):
            return signalCommandName
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
        self.write("Waiting for application event '" + applicationEventName + "' to occur.")
        if applicationEventName in self.applicationEventNames:
            self.write("Expected application event '" + applicationEventName + "' occurred, proceeding.")
            return 1
        else:
            self.waitingForEvent = applicationEventName
            return 0
    def processSignalCommand(self, signalArg):
        exec "signalNum = signal." + signalArg
        self.write("Generating signal " + signalArg)
        os.kill(self.processId, signalNum)
        return 1

# Take care not to record empty files...
class RecordScript:
    def __init__(self, scriptName):
        self.scriptName = scriptName
        self.fileForAppend = None
    def record(self, line):
        if not self.fileForAppend:
            self.fileForAppend = open(self.scriptName, "w")
        self.fileForAppend.write(line + os.linesep)

class UseCaseRecordScript(RecordScript):
    def __init__(self, scriptName):
        RecordScript.__init__(self, scriptName)
        self.events = []
        self.processId = os.getpid()
        self.applicationEvents = seqdict()
        self.realSignalHandlers = {}
        self.signalNames = {}
        for entry in dir(signal):
            if entry.startswith("SIG") and not entry.startswith("SIG_"):
                exec "number = signal." + entry
                self.signalNames[number] = entry
        for signum in range(signal.NSIG):
            try:
                # Don't record SIGCHLD unless told to, these are generally ignored
                # Also don't record SIGCONT, which is sent by LSF when suspension resumed
                if signum != signal.SIGCHLD and signum != signal.SIGCONT:
                    self.realSignalHandlers[signum] = signal.signal(signum, self.recordSignal)
            except:
                # Various signals aren't really valid here...
                pass
    def recordSignal(self, signum, stackFrame):
        self.writeApplicationEventDetails()
        self.record(signalCommandName + " " + self.signalNames[signum])
        # Reset the handler and send the signal to ourselves again...
        realHandler = self.realSignalHandlers[signum]
        # If there was no handler-override installed, resend the signal with the handler reset
        if realHandler == signal.SIG_DFL:
            signal.signal(signum, self.realSignalHandlers[signum])
            print "Killing process", self.processId
            os.kill(self.processId, signum)
            # If we're still alive, set the signal handler back again to record future signals
            signal.signal(signum, self.recordSignal)
        else:
            # If there was a handler, just call it
            realHandler(signum, stackFrame)
    def addEvent(self, event):
        self.events.append(event)
    def writeEvent(self, *args):
        event = self.findEvent(*args)
        if event.shouldRecord(*args):
            self.writeApplicationEventDetails()
            self.record(event.outputForScript(*args))
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
            self.record(waitCommandName + " " + eventName)
        self.applicationEvents = seqdict()
