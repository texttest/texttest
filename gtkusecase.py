
"""
The idea of this module is to implement a generic record/playback tool for GTK GUIs that
will create scripts in terms of the domain language. These will then be much more stable
than traditional such tools that create complicated Tcl scripts with lots of references
to pixel positions etc., which tend to be extremely brittle if the GUI is updated.

It is based on the generic usecase.py, read the documentation there too.

(1) For user actions such as clicking a button, selecting a list item etc., the general idea
is to add an extra argument to the call to 'connect', so that instead of writing

button.connect("clicked", myMethod)

you would write

scriptEngine.connect("save changes", "clicked", button, myMethod)

thus tying the user action to the script command "save changes". If you set up a record
script, then the module will write "save changes" to the script whenever the button is clicked.
Conversely, if you set up a replay script, then on finding the command "save changes", the
module will emit the "clicked" signal for said button, effectively clicking it programatically.

This means that, so long as my GUI has a concept of "save changes", I can redesign the GUI totally,
making the user choose to do this via a totally different widget, but all my scripts wiill
remaing unchanged.

(2) Some GUI widgets have "state" rather than relying on signals (for example text entries, toggle buttons),
so that the GUI itself may not necessarily make any calls to 'connect'. But you still want to generate
script commands when they change state, and be able to change them programatically. I have done this
by wrapping the constructor for such widgets, so that instead of

entry = gtk.Entry()

you would write

entry = scriptEngine.createEntry("file name")

which would tie the "focus-out-event" to the script command "enter file name = ".

(3) There are also composite widgets like the TreeView where you need to be able to specify an argument.
In this case the application has to provide extra information as to how the text is to be translated
into selecting an item in the tree. So, for example:

treeView.connect("row_activated", myMethod)

might become

scriptEngine.connect("select file", "row_activated", treeView, myMethod, (column, dataIndex))

(column, dataIndex) is a tuple to tell it which data in the tree view we are looking for. So that
the command "select file foobar.txt" will search the tree's column <column> and data index <dataIndex>
for the text "foobar.txt" and select that row accordingly.
"""

import usecase, gtk, os, string

# Base class for all GTK events due to widget signals
class SignalEvent(usecase.UserEvent):
    anyEvent = None
    def __init__(self, name, widget, signalName):
        usecase.UserEvent.__init__(self, name)
        self.widget = widget
        self.signalName = signalName
        # Signals often need to be emitted with a corresponding event.
        # This is very hard to fake. The only way I've found is to seize a random event
        # and use that... this is not foolproof...
        if not self.anyEvent:
            try:
                self.anyEventHandler = self.widget.connect("event", self.storeEvent)
            except TypeError:
                pass
    def storeEvent(self, widget, event, *args):
        SignalEvent.anyEvent = event
        self.widget.disconnect(self.anyEventHandler)
    def outputForScript(self, widget, *args):
        return self._outputForScript(*args)
    def _outputForScript(self, *args):
        return self.name
    def generate(self, argumentString):
        try:
            self.widget.emit(self.signalName)
        except TypeError:
            # The simplest way I could find to fake a gtk.gdk.Event
            self.widget.emit(self.signalName, self.anyEvent)
            
class ActivateEvent(SignalEvent):
    def __init__(self, name, widget, active = gtk.TRUE):
        SignalEvent.__init__(self, name, widget, "toggled")
        self.active = active
    def shouldRecord(self, *args):
        return self.widget.get_active() == self.active
    def generate(self, argumentString):
        self.widget.set_active(self.active)
        
class EntryEvent(SignalEvent):
    def __init__(self, name, widget):
        SignalEvent.__init__(self, name, widget, "focus-out-event")
        self.oldText = widget.get_text()
    def shouldRecord(self, *args):
        text = self.widget.get_text()
        return text != self.oldText
    def _outputForScript(self, *args):
        text = self.widget.get_text()
        self.oldText = text
        return self.name + " " + text
    def generate(self, argumentString):
        self.widget.set_text(argumentString)
        self.widget.emit(self.signalName, self.anyEvent)

class ResponseEvent(SignalEvent):
    def __init__(self, name, widget, responseId):
        SignalEvent.__init__(self, name, widget, "response")
        self.responseId = responseId
    def shouldRecord(self, widget, responseId, *args):
        return self.responseId == responseId
    def generate(self, argumentString):
        self.widget.emit(self.signalName, self.responseId)

class NotebookPageChangeEvent(SignalEvent):
    def __init__(self, name, widget):
        SignalEvent.__init__(self, name, widget, "switch-page")
    def _outputForScript(self, page, page_num, *args):
        newPage = self.widget.get_nth_page(page_num)
        return self.name + " " + self.widget.get_tab_label_text(newPage)
    def generate(self, argumentString):
        for i in range(len(self.widget.get_children())):
            page = self.widget.get_nth_page(i)
            if self.widget.get_tab_label_text(page) == argumentString:
                self.widget.set_current_page(i)
                return
        raise usecase.UseCaseScriptError, "Could not find page " + argumentString + " in '" + self.name + "'"

class TreeSignalEvent(SignalEvent):
    def __init__(self, name, widget, signalName, argumentParseData):
        SignalEvent.__init__(self, name, widget, signalName)
        self.column, self.valueId = argumentParseData
        self.model = self.getModel()
    def getOutput(self, path):
        return self.name + " " + self.model.get_value(self.model.get_iter(path), self.valueId)
    def getPathData(self, argumentString):
        path = self.findTreePath(self.model.get_iter_root(), argumentString)
        if not path:
            raise usecase.UseCaseScriptError, "Could not find row '" + argumentString + "' in Tree View"
        return path
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
    def pathHasText(self, iter, argumentText):
        return self.model.get_value(iter, self.valueId) == argumentText

class TreeViewSignalEvent(TreeSignalEvent):
    def getModel(self):
        return self.widget.get_model()
    def _outputForScript(self, path, *args):
        return self.getOutput(path)
    def generate(self, argumentString):
        path = self.getPathData(argumentString)
        self.widget.emit(self.signalName, path, self.column)

class TreeSelectionSignalEvent(TreeSignalEvent):
    def __init__(self, name, widget, signalName, sense, argumentParseData):
        TreeSignalEvent.__init__(self, name, widget, signalName, argumentParseData)
        self.oldSelectedPaths = self.findSelectedPaths()
        self.newSelectedPaths = self.oldSelectedPaths
        self.sense = sense
        self.skipNextRecord = 0
        self.recordActive = 1
        if self.sense > 0:
            widget.get_tree_view().connect("row_activated", self.disableNext)
    def getModel(self):
        return self.widget.get_tree_view().get_model()
    def disableNext(self, *args):
        self.skipNextRecord = 1
    def setMonitoring(self, active):
        self.recordActive = active
        if active:
            self.oldSelectedPaths = self.newSelectedPaths
    def reenableRecord(self):
        if not self.recordActive:
            return 0
        if self.skipNextRecord:
            self.skipNextRecord = 0
            self.oldSelectedPaths = self.newSelectedPaths
            return 0
        return 1
    def shouldRecord(self, *args):
        self.newSelectedPaths = self.findSelectedPaths()
        if self.sense > 0 and len(self.newSelectedPaths) > len(self.oldSelectedPaths):
            return self.reenableRecord()
        elif self.sense < 0 and len(self.newSelectedPaths) < len(self.oldSelectedPaths):
            return self.reenableRecord()
        self.oldSelectedPaths = self.newSelectedPaths
        return 0
    def _outputForScript(self, *args):
        extraPaths = self.extraPaths()
        self.oldSelectedPaths = self.newSelectedPaths
        outputList = map(self.getOutput, extraPaths)
        return string.join(outputList, os.linesep)
    def extraPaths(self):
        if self.sense > 0:
            return self._extraPaths(self.newSelectedPaths, self.oldSelectedPaths)
        else:
            return self._extraPaths(self.oldSelectedPaths, self.newSelectedPaths)
    def _extraPaths(self, longPaths, shortPaths):
        extraPaths = []
        for path in longPaths:
            if not path in shortPaths:
                extraPaths.append(path)
        return extraPaths
    def findSelectedPaths(self):
        paths = []
        self.widget.selected_foreach(self.addSelPath, paths)
        return paths
    def addSelPath(self, model, path, iter, paths):
        paths.append(path)
    def generate(self, argumentString):
        path = self.getPathData(argumentString)
        if self.sense > 0:
            self.widget.select_path(path)
        else:
            self.widget.unselect_path(path)

class ScriptEngine(usecase.ScriptEngine):
    def __init__(self, logger = None, enableShortcuts = 0):
        usecase.ScriptEngine.__init__(self, logger, enableShortcuts)
        self.commandButtons = []
    def connect(self, eventName, signalName, widget, method = None, argumentParseData = None, *data):
        if self.active():
            stdName = self.standardName(eventName)
            signalEvent = self._createSignalEvent(signalName, stdName, widget, argumentParseData)
            self._addEventToScripts(signalEvent)
        if method:
            widget.connect(signalName, method, *data)
    def monitorTreeSelection(self, additionName, removalName, selection, argumentParseData):
        if self.active():
            addEvent = TreeSelectionSignalEvent(self.standardName(additionName), selection, "changed", 1, argumentParseData)
            remEvent = TreeSelectionSignalEvent(self.standardName(removalName), selection, "changed", -1, argumentParseData)
            self._addEventToScripts(addEvent)
            self._addEventToScripts(remEvent)
    def setSelection(self, selection, iters):
        # Disable recording of changes while we set the selection programatically
        self._setMonitoring(selection, 0)
        selection.unselect_all()
        for iter in iters:
            selection.select_iter(iter)
        self._setMonitoring(selection, 1)
    def createEntry(self, description, defaultValue):
        entry = gtk.Entry()
        entry.set_text(defaultValue)
        if self.active():
            stateChangeName = self.standardName(description)
            entryEvent = EntryEvent(stateChangeName, entry)
            if self.recorderActive():
                entryEvent.widget.connect("activate", self.recorder.writeEvent, entryEvent)
            self._addEventToScripts(entryEvent)
        return entry
    def createNotebook(self, description, pages):
        notebook = gtk.Notebook()
        for page, tabText in pages:
            label = gtk.Label(tabText)
            notebook.append_page(page, label)
        if self.active():
            stateChangeName = self.standardName(description)
            event = NotebookPageChangeEvent(stateChangeName, notebook)
            self._addEventToScripts(event)
        return notebook
    def createCheckButton(self, description, defaultValue):
        button = gtk.CheckButton(description)
        if defaultValue:
            button.set_active(gtk.TRUE)

        if self.active():
            checkChangeName = "check " + self.standardName(description)
            uncheckChangeName = "uncheck " + self.standardName(description)
            checkEvent = ActivateEvent(checkChangeName, button)
            uncheckEvent = ActivateEvent(uncheckChangeName, button, gtk.FALSE)
            self._addEventToScripts(checkEvent)
            self._addEventToScripts(uncheckEvent)
        return button
    def createShortcutBar(self):
        if not self.enableShortcuts:
            return None
        # Standard thing to add at the bottom of the GUI...
        buttonbox = gtk.HBox()
        existingbox = self.createExistingShortcutBox()
        buttonbox.pack_start(existingbox, expand=gtk.FALSE, fill=gtk.FALSE)
        newbox = gtk.HBox()
        self.addNewButton(newbox)
        self.addStopControls(newbox, existingbox)
        buttonbox.pack_start(newbox, expand=gtk.FALSE, fill=gtk.FALSE)
        existingbox.show()
        newbox.show()
        return buttonbox
#private
    def getShortcutFiles(self):
        files = []
        usecaseDir = os.environ["USECASE_HOME"]
        if not os.path.isdir(usecaseDir):
            return files
        for fileName in os.listdir(usecaseDir):
            if fileName.endswith(".shortcut"):
                files.append(os.path.join(os.environ["USECASE_HOME"], fileName))
        return files
    def createExistingShortcutBox(self):
        buttonbox = gtk.HBox()
        files = self.getShortcutFiles()
        label = gtk.Label("Shortcuts:")
        buttonbox.pack_start(label, expand=gtk.FALSE, fill=gtk.FALSE)
        for fileName in files:
            buttonName = self.getShortcutButtonName(fileName)
            self.addShortcutButton(buttonbox, buttonName, fileName)
        label.show()
        return buttonbox
    def addNewButton(self, buttonbox):
        newButton = gtk.Button()
        newButton.set_label("New")
        self.connect("create new shortcut", "clicked", newButton, self.createShortcut, None, buttonbox)
        newButton.show()
        buttonbox.pack_start(newButton, expand=gtk.FALSE, fill=gtk.FALSE)
    def addShortcutButton(self, buttonbox, buttonName, fileName):
        button = gtk.Button()
        button.set_label(buttonName)
        replayScript = usecase.ReplayScript(fileName)
        self.connect(buttonName.lower(), "clicked", button, self.replayShortcut, None, replayScript)
        firstCommand = replayScript.commands[0]
        if self.replayer.findCommandName(firstCommand):
            button.show()
        self.commandButtons.append((firstCommand, button))
        buttonbox.pack_start(button, expand=gtk.FALSE, fill=gtk.FALSE)
    def addStopControls(self, buttonbox, existingbox):
        label = gtk.Label("Recording shortcut named:")
        buttonbox.pack_start(label, expand=gtk.FALSE, fill=gtk.FALSE)
        entry = self.createEntry("set shortcut name to", "")
        buttonbox.pack_start(entry, expand=gtk.FALSE, fill=gtk.FALSE)
        stopButton = gtk.Button()
        stopButton.set_label("Stop")
        self.connect("stop recording", "clicked", stopButton, self.stopRecording, None, label, entry, buttonbox, existingbox)
        self.recorder.blockTopLevel("stop recording")
        self.recorder.blockTopLevel("set shortcut name to")
        buttonbox.pack_start(stopButton, expand=gtk.FALSE, fill=gtk.FALSE)
    def createShortcut(self, button, buttonbox, *args):
        buttonbox.show_all()
        button.hide()
        tmpFileName = self.getTmpShortcutName()
        self.recorder.addScript(tmpFileName)
    def stopRecording(self, button, label, entry, buttonbox, existingbox, *args):
        self.recorder.terminateScript()
        buttonbox.show_all()
        button.hide()
        label.hide()
        entry.hide()
        buttonName = entry.get_text()
        newScriptName = self.getShortcutFileName(buttonName)
        scriptExistedPreviously = os.path.isfile(newScriptName)
        os.rename(self.getTmpShortcutName(), newScriptName)
        if not scriptExistedPreviously:
            self.addShortcutButton(existingbox, buttonName, newScriptName)
    def replayShortcut(self, button, script, *args):
        self.replayer.addScript(script)
        if len(self.recorder.scripts):
            self.recorder.suspended = 1
            script.addExitObserver(self.recorder)
    def getTmpShortcutName(self):
        return os.path.join(os.environ["USECASE_HOME"], "new_shortcut")
    def getShortcutButtonName(self, fileName):
        return os.path.basename(fileName).split(".")[0].replace("_", " ")
    def getShortcutFileName(self, buttonName):
        return os.path.join(os.environ["USECASE_HOME"], buttonName.replace(" ", "_") + ".shortcut")
    def createReplayer(self, logger):
        return UseCaseReplayer(logger)
    def showShortcutButtons(self, event):
        for command, button in self.commandButtons:
            if command.startswith(event.name):
                button.show()
    def _addEventToScripts(self, event):
        if self.enableShortcuts:
            self.showShortcutButtons(event)
        if self.replayerActive():
            self.replayer.addEvent(event)
        if self.recorderActive():
            self.recorder.addEvent(event)
            event.widget.connect(event.signalName, self.recorder.writeEvent, event)
    def _createSignalEvent(self, signalName, eventName, widget, argumentParseData):
        if signalName == "response":
            return ResponseEvent(eventName, widget, argumentParseData)
        elif isinstance(widget, gtk.TreeView):
            return TreeViewSignalEvent(eventName, widget, signalName, argumentParseData)
        else:
            return SignalEvent(eventName, widget, signalName)
    def _setMonitoring(self, selection, active):
        # Allow disabling and enabling of the tree selection monitoring. This to avoid recording changes made programatically
        if self.recorderActive():
            for event in self.recorder.events:
                if event.widget == selection:
                    event.setMonitoring(active)

# Use the GTK idle handlers instead of a separate thread for replay execution
class UseCaseReplayer(usecase.UseCaseReplayer):
     def executeCommandsInBackground(self):
         gtk.idle_add(self.runNextCommand)
     def runNextCommand(self):
         retValue = usecase.UseCaseReplayer.runNextCommand(self)
         if retValue:
             return gtk.TRUE
         else:
             return gtk.FALSE
