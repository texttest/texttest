
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

class ActivateEvent(usecase.UserEvent):
    def __init__(self, name, widget, active = gtk.TRUE):
        usecase.UserEvent.__init__(self, name, widget)
        self.active = active
    def widgetHasChanged(self):
        return self.widget.get_active() == self.active
    def generate(self, argumentString):
        self.widget.set_active(self.active)

class EntryEvent(usecase.UserEvent):
    def __init__(self, name, widget):
        usecase.UserEvent.__init__(self, name, widget)
        self.oldText = ""
    def widgetHasChanged(self):
        text = self.widget.get_text()
        return text != self.oldText
    def outputForScript(self, *args):
        text = self.widget.get_text()
        self.oldText = text
        return self.name + " " + text
    def generate(self, argumentString):
        self.widget.set_text(argumentString)

class SignalEvent(usecase.UserEvent):
    def __init__(self, name, widget, signalName):
        usecase.UserEvent.__init__(self, name, widget)
        self.signalName = signalName
    def generate(self, argumentString):
        self.widget.emit(self.signalName, *argumentString)

class NotebookPageChangeEvent(SignalEvent):
    def __init__(self, name, widget):
        SignalEvent.__init__(self, name, widget, "switch-page")
    def outputForScript(self, page, page_num, *args):
        newPage = self.widget.get_nth_page(page_num)
        return self.name + " " + self.widget.get_tab_label_text(newPage)
    def generate(self, argumentString):
        for i in range(len(self.widget.get_children())):
            page = self.widget.get_nth_page(i)
            if self.widget.get_tab_label_text(page) == argumentString:
                self.widget.set_current_page(i)
                return
        raise GtkScriptError, "Could not find page " + argumentString + " in '" + self.name + "'"

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
            raise GtkScriptError, "Could not find row '" + argumentString + "' in Tree View"
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
    def outputForScript(self, path, *args):
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
    def getModel(self):
        return self.widget.get_tree_view().get_model()
    def widgetHasChanged(self):
        self.newSelectedPaths = self.findSelectedPaths()
        if self.sense > 0 and len(self.newSelectedPaths) > len(self.oldSelectedPaths):
            return 1
        elif self.sense < 0 and len(self.newSelectedPaths) < len(self.oldSelectedPaths):
            return 1
        self.oldSelectedPaths = self.newSelectedPaths
        return 0
    def outputForScript(self, *args):
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
    def connect(self, eventName, signalName, widget, method = None, argumentParseData = None, sense = 1, *data):
        if method:
            widget.connect(signalName, method, *data)
        if self.hasScript():
            stdName = self.standardName(eventName)
            signalEvent = self._createSignalEvent(signalName, stdName, widget, sense, argumentParseData)
            self._addEventToScripts(signalEvent, signalName)
    def createEntry(self, description, defaultValue):
        entry = gtk.Entry()
        entry.set_text(defaultValue)
        if self.hasScript():
            stateChangeName = "enter " + self.standardName(description) + " ="
            entryEvent = EntryEvent(stateChangeName, entry)
            self._addEventToScripts(entryEvent, "focus-out-event")
        return entry
    def createNotebook(self, description, pages):
        notebook = gtk.Notebook()
        for page, tabText in pages:
            label = gtk.Label(tabText)
            notebook.append_page(page, label)
        if self.hasScript():
            stateChangeName = "page " + self.standardName(description) + " to"
            event = NotebookPageChangeEvent(stateChangeName, notebook)
            self._addEventToScripts(event, event.signalName)
        return notebook
    def createCheckButton(self, description, defaultValue):
        button = gtk.CheckButton(description)
        if defaultValue:
            button.set_active(gtk.TRUE)

        if self.hasScript():
            checkChangeName = "check " + self.standardName(description)
            uncheckChangeName = "uncheck " + self.standardName(description)
            checkEvent = ActivateEvent(checkChangeName, button)
            uncheckEvent = ActivateEvent(uncheckChangeName, button, gtk.FALSE)
            self._addEventToScripts(checkEvent, "toggled")
            self._addEventToScripts(uncheckEvent, "toggled")
        return button
#private
    def createReplayScript(self, scriptName, logger):
        return ReplayScript(scriptName, logger)
    def _addEventToScripts(self, event, signalName):
        if self.replayScript:
            self.replayScript.addEvent(event)
        if self.recordScript:
            self.recordScript.addEvent(event)
            event.widget.connect(signalName, self.recordScript.writeEvent, event)
    def _createSignalEvent(self, signalName, eventName, widget, sense, argumentParseData):
        if isinstance(widget, gtk.TreeView):
            return TreeViewSignalEvent(eventName, widget, signalName, argumentParseData)
        elif isinstance(widget, gtk.TreeSelection):
            return TreeSelectionSignalEvent(eventName, widget, signalName, sense, argumentParseData)
        else:
            return SignalEvent(eventName, widget, signalName)

# Use the GTK idle handlers instead of a separate thread for replay execution
class ReplayScript(usecase.ReplayScript):
     def executeCommandsInBackground(self):
         gtk.idle_add(self.runNextCommand)
     def runNextCommand(self):
         retValue = usecase.ReplayScript.runNextCommand(self)
         if retValue:
             return gtk.TRUE
         else:
             return gtk.FALSE
