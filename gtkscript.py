
import gtk, os, string, sys

# Exception to throw when scripts go wrong
class GtkScriptError(RuntimeError):
    pass

class Event:
    def __init__(self, name, widget):
        self.name = name
        self.widget = widget
    def hasChanged(self):
        return 1
    def outputForScript(self, *args):
        return self.name
    def generate(self, argumentString):
        return 1

class ActivateEvent(Event):
    def __init__(self, name, widget, active = gtk.TRUE):
        Event.__init__(self, name, widget)
        self.active = active
    def hasChanged(self):
        return self.widget.get_active() == self.active
    def generate(self, argumentString):
        self.widget.set_active(self.active)
        return 1

class EntryEvent(Event):
    def __init__(self, name, widget):
        Event.__init__(self, name, widget)
        self.oldText = ""
    def hasChanged(self):
        text = self.widget.get_text()
        return text != self.oldText
    def outputForScript(self, *args):
        text = self.widget.get_text()
        self.oldText = text
        return self.name + " " + text
    def generate(self, argumentString):
        self.widget.set_text(argumentString)
        return 1
        
class SignalEvent(Event):
    def __init__(self, name, widget, signalName):
        Event.__init__(self, name, widget)
        self.signalName = signalName
    def generate(self, argumentString):
        self.widget.emit(self.signalName, *argumentString)
        return 1

class TreeViewSignalEvent(SignalEvent):
    def __init__(self, name, widget, signalName, argumentParseData):
        SignalEvent.__init__(self, name, widget, signalName)
        self.column, self.valueId = argumentParseData
        self.model = widget.get_model()
    def outputForScript(self, path, *args):
        nodeLabel = self.model.get_value(self.model.get_iter(path), self.valueId)
        return self.name + " " + nodeLabel
    def generate(self, argumentString):
        arguments = argumentString.split(" ")
        rowText = arguments[0]
        path = self.findTreePath(self.model.get_iter_root(), rowText)
        if not path:
            raise GtkScriptError, "Could not find row '" + rowText + "' in Tree View"
        userArgs = argumentString.replace(rowText, "").strip()
        self.widget.emit(self.signalName, path, self.column, *userArgs)
        return 1
    def pathHasText(self, iter, argumentText):
        return self.model.get_value(iter, self.valueId) == argumentText
    def findTreePath(self, iter, argumentText):
        if self.pathHasText(iter, argumentText):
            return self.model.get_path(iter)
        childIter = self.model.iter_children(iter)
        if childIter:
            childPath = self.findTreePath(childIter, argumentText)
            if childPath:
                return childPath
        nextIter = self.model.iter_next(iter)
        if nextIter:
            return self.findTreePath(nextIter, argumentText)
        return None

class IdleHandler(Event):
    def __init__(self, name, callback):
        Event.__init__(self, "wait for " + name, None)
        self.callback = callback
        self.exited = 0
        self.observers = []
        gtk.idle_add(self.runCallback)
    def addObserver(self, observer):
        self.observers.append(observer)
    def runCallback(self):
        retValue = self.callback()        
        if retValue == gtk.FALSE:
            self.exited = 1
            for observer in self.observers:
                observer.idleHandlerExited(self)
        return retValue
    def generate(self, argumentString):
        return self.exited

class EventHandler:
    def __init__(self):
        self.replayScript = None
        self.recordScript = None
    def hasScript(self):
        return self.replayScript or self.recordScript
    def setScripts(self, replayScriptName, recordScriptName):
        if replayScriptName and replayScriptName == recordScriptName:
            raise GtkScriptError, "Cannot record to the same script we are replaying"
        if replayScriptName:
            self.replayScript = ReplayScript(replayScriptName)
        if recordScriptName:
            self.recordScript = RecordScript(recordScriptName)
    def connect(self, eventName, signalName, widget, method, argumentParseData = None, *data):
        widget.connect(signalName, method, *data)
        if self.hasScript():
            stdName = self.standardName(eventName)
            signalEvent = self.createSignalEvent(signalName, stdName, widget, argumentParseData)
            self.addEventToScripts(signalEvent, signalName)
    def addEventToScripts(self, event, signalName):
        if self.replayScript:
            self.replayScript.addEvent(event)
        if self.recordScript:
            self.recordScript.addEvent(event, signalName)
    def createSignalEvent(self, signalName, eventName, widget, argumentParseData):
        if isinstance(widget, gtk.TreeView):
            return TreeViewSignalEvent(eventName, widget, signalName, argumentParseData)
        else:
            return SignalEvent(eventName, widget, signalName)
    def standardName(self, name):
        firstIndex = None
        lastIndex = len(name)
        for i in range(len(name)):
            if name[i] in string.letters or name[i] in string.digits:
                if firstIndex is None:
                    firstIndex = i
                lastIndex = i
        return name[firstIndex:lastIndex + 1].lower()
    def addIdle(self, handlerName, method):
        if self.hasScript():
            handler = IdleHandler(handlerName, method)
            if self.replayScript:
                self.replayScript.addEvent(handler)
                handler.addObserver(self.replayScript)
            if self.recordScript:
                handler.addObserver(self.recordScript)
        else:
            gtk.idle_add(method)
    def createEntry(self, description):
        entry = gtk.Entry()
        if self.hasScript():
            stateChangeName = "enter " + self.standardName(description) + " ="
            entryEvent = EntryEvent(stateChangeName, entry)
            self.addEventToScripts(entryEvent, "focus-out-event")
        return entry
    def createCheckButton(self, description):
        button = gtk.CheckButton(description)
        if self.hasScript():
            checkChangeName = "check " + self.standardName(description)
            uncheckChangeName = "uncheck " + self.standardName(description)
            checkEvent = ActivateEvent(checkChangeName, button)
            uncheckEvent = ActivateEvent(uncheckChangeName, button, gtk.FALSE)
            self.addEventToScripts(checkEvent, "toggled")
            self.addEventToScripts(uncheckEvent, "toggled")
        return button

eventHandler = EventHandler()

class ReplayScript:
    def __init__(self, scriptName):
        self.events = {}
        self.commands = []
        self.pointer = 0
        if not os.path.isfile(scriptName):
            raise GtkScriptError, "Cannot replay script " + scriptName + ", no such file or directory"
        for line in open(scriptName).xreadlines():
            if line != "" and line[0] != "#":
                self.commands.append(line.strip())
        self.enableReading()
    def addEvent(self, event):
        self.events[event.name] = event
    def enableReading(self):
        # If events fail, we store them and wait for the relevant handler
        self.waitingForHandler = None
        gtk.idle_add(self.runCommands)
    def isFinished(self):
        return self.pointer >= len(self.commands)
    def runCommands(self):
        if self.isFinished():
            return gtk.FALSE

        nextCommand = self.commands[self.pointer]
        # Filter blank lines and comments
        self.pointer += 1
        try:
            return self.generateEvent(nextCommand)
        except GtkScriptError:
            print "Script terminated due to exception : "
            type, value, traceback = sys.exc_info()
            sys.excepthook(type, value, traceback)
            return gtk.FALSE
        return gtk.TRUE
    def generateEvent(self, scriptCommand):
        eventName = self.findEvent(scriptCommand)
        if not eventName:
            raise GtkScriptError, "Could not parse script command '" + scriptCommand + "'"
        argumentString = scriptCommand.replace(eventName, "").strip()
        print "'" + eventName + "' event created with arguments '" + argumentString + "'"
        event = self.events[eventName]
        if event.generate(argumentString):
            return gtk.TRUE
        else:
            self.waitingForHandler = event
            return gtk.FALSE
    def findEvent(self, command):
        for eventName in self.events.keys():
            if command.startswith(eventName):
                return eventName
        return None
    def idleHandlerExited(self, idleHandler):
        if self.waitingForHandler == idleHandler:
            self.enableReading()

            

class RecordScript:
    def __init__(self, scriptName):
        self.fileForAppend = open(scriptName, "w")
        self.events = []
    def addEvent(self, event, signalName):
        self.events.append(event)
        event.widget.connect(signalName, self.writeEvent, event)
    def writeEvent(self, widget, *args):
        event = self.findEvent(*args)
        if event.hasChanged():
            self.fileForAppend.write(event.outputForScript(*args) + os.linesep)
    def findEvent(self, *args):
        for arg in args:
            if isinstance(arg, Event):
                return arg
    def idleHandlerExited(self, idleHandler):
        self.writeEvent(None, idleHandler)

            

