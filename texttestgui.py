#!/usr/bin/env python

# GUI for TextTest written with PyGTK

import plugins, gtk, gobject, os, string, time, sys

class ActivateEvent:
    def __init__(self, widget, active = gtk.TRUE):
        self.widget = widget
        self.active = active
    def writeEventToScript(self, activeWidget, eventName):
        global appendToScript
        if appendToScript and activeWidget.get_active() == self.active:
            appendToScript.write(eventName + os.linesep)
    def generate(self, argumentString):
        self.widget.set_active(self.active)
        return 1

class EntryEvent:
    def __init__(self, widget):
        self.widget = widget
        self.oldText = ""
    def writeEventToScript(self, entryWidget, event, eventName):
        global appendToScript
        if appendToScript:
            text = entryWidget.get_text()
            if text != self.oldText:
                appendToScript.write(eventName + " " + text + os.linesep)
                self.oldText = text
    def generate(self, argumentString):
        self.widget.set_text(argumentString)
        return 1
        
class SignalEvent:
    def __init__(self, signalName, widget):
        self.signalName = signalName
        self.widget = widget
    def writeEventToScript(self, widget, eventName, *args):
        global appendToScript
        if appendToScript:
            appendToScript.write(eventName + os.linesep)
    def generate(self, argumentString):
        self.widget.emit(self.signalName, *argumentString)
        return 1

class TreeViewSignalEvent(SignalEvent):
    def __init__(self, signalName, widget, argumentParseData):
        SignalEvent.__init__(self, signalName, widget)
        self.column, self.valueId = argumentParseData
        self.model = widget.get_model()
    def writeEventToScript(self, view, path, column, eventName, *args):
        nodeLabel = self.model.get_value(self.model.get_iter(path), self.valueId)
        if appendToScript:
            appendToScript.write(eventName + " " + nodeLabel + os.linesep)
    def generate(self, argumentString):
        arguments = argumentString.split(" ")
        rowText = arguments[0]
        path = self.findTreePath(self.model.get_iter_root(), rowText)
        if not path:
            print "Could not find row '" + rowText + "' in Tree View"
            return 0
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

class EventHandler:
    def __init__(self):
        self.events = {}
    def connect(self, eventName, signalName, widget, method, argumentParseData = None, *data):
        stdName = self.standardName(eventName)
        signalEvent = self.createSignalEvent(signalName, widget, argumentParseData)
        self.events[stdName] = signalEvent
        widget.connect(signalName, method, *data)
        widget.connect(signalName, signalEvent.writeEventToScript, stdName)
    def createSignalEvent(self, signalName, widget, argumentParseData):
        if isinstance(widget, gtk.TreeView):
            return TreeViewSignalEvent(signalName, widget, argumentParseData)
        else:
            return SignalEvent(signalName, widget)
    def standardName(self, name):
        firstIndex = None
        lastIndex = len(name)
        for i in range(len(name)):
            if name[i] in string.letters or name[i] in string.digits:
                if firstIndex is None:
                    firstIndex = i
                lastIndex = i
        return name[firstIndex:lastIndex + 1].lower()
    def generateEvent(self, scriptCommand):
        eventName = self.findEvent(scriptCommand)
        if not eventName:
            raise plugins.TextTestError, "Could not parse script command '" + scriptCommand + "'"
        argumentString = scriptCommand.replace(eventName, "").strip()
        print "'" + eventName + "' event created with arguments '" + argumentString + "'"
        event = self.events[eventName]
        return event.generate(argumentString)
    def createEntry(self, description):
        entry = gtk.Entry()
        stateChangeName = "enter " + self.standardName(description) + " ="
        entryEvent = EntryEvent(entry)
        self.events[stateChangeName] = entryEvent
        entry.connect("focus-out-event", entryEvent.writeEventToScript, stateChangeName)
        return entry
    def createCheckButton(self, description):
        button = gtk.CheckButton(description)
        checkChangeName = "check " + self.standardName(description)
        uncheckChangeName = "uncheck " + self.standardName(description)
        checkEvent = ActivateEvent(button)
        uncheckEvent = ActivateEvent(button, gtk.FALSE)
        self.events[checkChangeName] = checkEvent
        self.events[uncheckChangeName] = uncheckEvent
        button.connect("toggled", checkEvent.writeEventToScript, checkChangeName)
        button.connect("toggled", uncheckEvent.writeEventToScript, uncheckChangeName)
        return button
    def findEvent(self, command):
        for eventName in self.events.keys():
            if command.startswith(eventName):
                return eventName
        return None
            
eventHandler = EventHandler()



class TextTestGUI:
    def __init__(self, scriptName):
        global appendToScript
        appendToScript = None
        self.scriptCommands = []
        self.scriptPointer = 0
        if scriptName:
            if os.path.isfile(scriptName):
                self.scriptCommands = map(string.strip, open(scriptName).readlines())
            if len(self.scriptCommands) == 0:
                appendToScript = open(scriptName, "a")
        self.scriptName = scriptName
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT)
        self.instructions = []
        self.postponedInstructions = []
        self.postponedTests = []
        self.interactiveActions = []
        self.itermap = {}
    def createTopWindow(self):
        # Create toplevel window to show it all.
        win = gtk.Window(gtk.WINDOW_TOPLEVEL)
        win.set_title("TextTest functional tests")
        eventHandler.connect("close", "delete_event", win, self.quit)
        vbox = self.createWindowContents()
        win.add(vbox)
        win.show()
        win.resize(600, 500)
        return win
    def createIterMap(self):
        iter = self.model.get_iter_root()
        self.createSubIterMap(iter)
    def createSubIterMap(self, iter):
        test = self.model.get_value(iter, 2)
        self.itermap[test] = iter.copy()
        childIter = self.model.iter_children(iter)
        if childIter:
            self.createSubIterMap(childIter)
        nextIter = self.model.iter_next(iter)
        if nextIter:
            self.createSubIterMap(nextIter)
    def addSuite(self, suite, parent=None):
        iter = self.model.insert_before(parent, None)
        self.model.set_value(iter, 0, suite.name)
        self.model.set_value(iter, 2, suite)
        try:
            for test in suite.testcases:
                self.addSuite(test, iter)
            self.model.set_value(iter, 1, "white")
        except:
            self.model.set_value(iter, 1, self.getTestColour(suite))
    def addInteractiveActions(self, actions):
        self.interactiveActions = actions
    def getTestColour(self, test):
        if test.state == test.FAILED or test.state == test.UNRUNNABLE:
            return "red"
        if test.state == test.SUCCEEDED:
            return "green"
        if test.state == test.RUNNING:
            return "yellow"
        return "white"
    def createWindowContents(self):
        self.contents = gtk.HBox(homogeneous=gtk.TRUE)
        testWins = self.createTestWindows()
        testCaseWin = self.testCaseGUI.getWindow()
        self.contents.pack_start(testWins, expand=gtk.TRUE, fill=gtk.TRUE)
        self.contents.pack_start(testCaseWin, expand=gtk.TRUE, fill=gtk.TRUE)
        self.contents.show()
        return self.contents
    def createTestWindows(self):
        # Create some command buttons.
        buttonbox = self.makeButtons([("Quit", self.quit)])
        window = self.createTreeWindow()

        # Create a vertical box to hold the above stuff.
        vbox = gtk.VBox()
        vbox.pack_start(buttonbox, expand=gtk.FALSE, fill=gtk.FALSE)
        vbox.pack_start(window, expand=gtk.TRUE, fill=gtk.TRUE)
        vbox.show()
        return vbox
    def createDisplayWindows(self):
        hbox = gtk.HBox()
        treeWin = self.createTreeWindow()
        detailWin = self.createDetailWindow()
        hbox.pack_start(treeWin, expand=gtk.TRUE, fill=gtk.TRUE)
        hbox.pack_start(detailWin, expand=gtk.TRUE, fill=gtk.TRUE)
        hbox.show()
        return hbox
    def createTreeWindow(self):
        view = gtk.TreeView(self.model)
        
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn("All Tests", renderer, text=0, background=1)
        view.append_column(column)
        view.expand_all()
        eventHandler.connect("select test", "row_activated", view, self.viewTest, (column, 0))
        view.show()

        # Create scrollbars around the view.
        scrolled = gtk.ScrolledWindow()
        scrolled.add(view)
        scrolled.show()    
        return scrolled
    def storeInstructions(self, instructions):
        self.instructions += instructions
    def takeControl(self):
        # We've got everything and are ready to go
        self.createIterMap()
        self.testCaseGUI = TestCaseGUI(None)
        topWindow = self.createTopWindow()
        # Run the Gtk+ main loop.
        if len(self.scriptCommands):
            gtk.idle_add(self.runScriptCommands)
        gtk.idle_add(self.doNextAction)
        gtk.main()
    def doNextAction(self):
        if len(self.instructions) == 0:
            self.instructions = self.postponedInstructions
            self.postponedTests = []
            self.postponedInstructions = []
            if len(self.instructions) == 0:
                return gtk.FALSE
        test, action = self.instructions[0]
        del self.instructions[0]
        
        if test in self.postponedTests:
            self.postponedInstructions.append((test, action))
        else:
            oldState = test.state
            retValue = test.callAction(action)
            if retValue != None:
                self.postponedTests.append(test)
                self.postponedInstructions.append((test, action))
            if test.state != oldState:
                iter = self.itermap[test]
                self.model.set_value(iter, 1, self.getTestColour(test))
                self.model.row_changed(self.model.get_path(iter), iter)
        return gtk.TRUE
    def runScriptCommands(self):
        global appendToScript
        if self.scriptPointer >= len(self.scriptCommands):
            appendToScript = open(self.scriptName, "a")
            return gtk.FALSE
        nextCommand = self.scriptCommands[self.scriptPointer]
        try:
            if nextCommand == "" or eventHandler.generateEvent(nextCommand):
                self.scriptPointer += 1
            elif self.scriptPointer > 0:
                self.scriptPointer -= 1
        except:
            print "Script terminated due to exception : "
            type, value, traceback = sys.exc_info()
            sys.excepthook(type, value, traceback)
            return gtk.FALSE
        return gtk.TRUE
    def quit(self, *args):
        gtk.main_quit()
    def viewTest(self, view, path, column, *args):
        test = self.model.get_value(self.model.get_iter(path), 2)
        print "Viewing test", test
        self.contents.remove(self.testCaseGUI.getWindow())
        self.testCaseGUI = TestCaseGUI(test, self.interactiveActions)
        self.contents.pack_start(self.testCaseGUI.getWindow(), expand=gtk.TRUE, fill=gtk.TRUE)
        self.contents.show()
    def makeButtons(self, list):
        buttonbox = gtk.HBox()
        for label, func in list:
            button = gtk.Button()
            button.set_label(label)
            eventHandler.connect(label, "clicked", button, func)
            button.show()
            buttonbox.pack_start(button, expand=gtk.FALSE, fill=gtk.FALSE)
        buttonbox.show()
        return buttonbox
        
class TestCaseGUI:
    def __init__(self, test = None, interactiveActions = []):
        self.exactButton = None
        self.optionChooser = None
        self.test = test
        self.interactiveDialogue = None
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT)
        self.addFilesToModel(test)
        view = self.createView(self.createTitle(test))
        buttonbox = self.makeButtons(test, interactiveActions)
        radioButtonBox = self.makeRadioButtons(test)
        textview = self.createTextView(test)
        self.window = self.createWindow(buttonbox, radioButtonBox, view, textview)
    def addFilesToModel(self, test):
        compiter = self.model.insert_before(None, None)
        self.model.set_value(compiter, 0, "Comparison Files")
        newiter = self.model.insert_before(None, None)
        self.model.set_value(newiter, 0, "New Files")
        if not test:
            return
        try:
            os.chdir(test.abspath)
            testComparison = test.stateDetails
            for name in testComparison.attemptedComparisons:
                fileComparison = testComparison.findFileComparison(name)
                if not fileComparison:
                    self.addComparison(compiter, name, fileComparison, "green")
                elif not fileComparison.newResult():
                    self.addComparison(compiter, name, fileComparison, "red")
            for fc in testComparison.newResults:
                self.addComparison(newiter, fc.stdFile, fc, "red")
        except AttributeError:
            pass
    def addComparison(self, iter, name, comp, colour):
        fciter = self.model.insert_before(iter, None)
        self.model.set_value(fciter, 0, name)
        self.model.set_value(fciter, 1, colour)
        if comp:
            self.model.set_value(fciter, 2, comp)
    def createWindow(self, buttonbox, radioButtonBox, view, textView):
        fileWin = gtk.ScrolledWindow()
        fileWin.add(view)
        self.dataWindow = gtk.ScrolledWindow()
        if textView:
            self.dataWindow.add(textView)
        vbox = gtk.VBox()
        vbox.pack_start(buttonbox, expand=gtk.FALSE, fill=gtk.FALSE)
        if radioButtonBox:
            vbox.pack_start(radioButtonBox, expand=gtk.FALSE, fill=gtk.FALSE)
        vbox.pack_start(fileWin, expand=gtk.TRUE, fill=gtk.TRUE)
        vbox.pack_start(self.dataWindow, expand=gtk.TRUE, fill=gtk.TRUE)
        fileWin.show()
        self.dataWindow.show()
        vbox.show()    
        return vbox
    def createView(self, title):
        view = gtk.TreeView(self.model)
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn(title, renderer, text=0, background=1)
        view.append_column(column)
        view.expand_all()
        eventHandler.connect("select file", "row_activated", view, self.displayDifferences, (column, 0))
        view.show()
        return view
    def createTextView(self, test):
        if not test:
            return None
        textview = gtk.TextView()
        textview.set_wrap_mode(gtk.WRAP_WORD)
        textbuffer = textview.get_buffer()
        textbuffer.set_text(self.getTestInfo(test))
        textview.show()
        return textview
    def getTestInfo(self, test):
        if test.state == test.UNRUNNABLE:
            return str(test.stateDetails).split(os.linesep)[0]
        elif test.state == test.FAILED:
            try:
                if test.stateDetails.failedPrediction:
                    return test.stateDetails.failedPrediction
            except AttributeError:
                return test.stateDetails
        elif test.state != test.SUCCEEDED and test.stateDetails:
            return test.stateDetails
        return ""
    def getWindow(self):
        return self.window
    def createTitle(self, test):
        if not test:
            return "Test-case info"
        return repr(test).replace("_", "__")
    def displayDifferences(self, view, path, column, *args):
        os.chdir(self.test.abspath)
        comparison = self.model.get_value(self.model.get_iter(path), 2)
        if comparison:
            if comparison.newResult():
                os.system("xemacs " + comparison.tmpCmpFile + " &")
            else:
                os.system("tkdiff " + comparison.stdCmpFile + " " + comparison.tmpCmpFile + " &")
    def makeButtons(self, test, interactiveActions):
        buttonbox = gtk.HBox()
        if not test:
            return buttonbox
        if test.state == test.FAILED:
            options = test.app.getVersionFileExtensions()
            self.addButton(self.save, buttonbox, "Save...", "")
            for option in options:     
                self.addButton(self.save, buttonbox, option, option)
        for intvAction in interactiveActions:
            instance = intvAction()
            self.addButton(self.runInteractive, buttonbox, instance.getTitle() + "...", instance)
        buttonbox.show()
        return buttonbox
    def hasPerformance(self, comparisonList):
        for comparison in comparisonList:
            if comparison.getType() != "difference" and comparison.hasDifferences():
                return 1
        return 0
    def makeRadioButtons(self, test):
        if not test or test.state != test.FAILED:
            return None
        try:
            comparisonList = test.stateDetails.getComparisons()
            if not self.hasPerformance(comparisonList):
                return None
        except AttributeError:
            return None
        buttonbox = gtk.HBox()
        averageButton = gtk.RadioButton(None)
        averageButton.set_label("Average Performance")
        self.exactButton = gtk.RadioButton(averageButton)
        self.exactButton.set_label("Exact Performance")
        if len(comparisonList) != 1:
            self.exactButton.set_active(gtk.TRUE)
        buttonbox.pack_start(averageButton, expand=gtk.FALSE, fill=gtk.TRUE)
        buttonbox.pack_start(self.exactButton, expand=gtk.FALSE, fill=gtk.TRUE)
        averageButton.show()
        self.exactButton.show()
        buttonbox.show()
        return buttonbox
    def addButton(self, method, buttonbox, label, option):
        button = gtk.Button()
        button.set_label(label)
        eventHandler.connect(label, "clicked", button, method, None, option)
        button.show()
        buttonbox.pack_start(button, expand=gtk.FALSE, fill=gtk.FALSE)
    def getSaveExactness(self):
        if self.exactButton:
            return self.exactButton.get_active() == gtk.TRUE
        else:
            return 1
    def save(self, button, option, *args):
        os.chdir(self.test.abspath)
        print "Saving", self.test, "version", option
        testComparison = self.test.stateDetails
        if testComparison:
            testComparison.save(self.getSaveExactness(), option)
    def runInteractive(self, button, action, *args):
        if self.optionChooser and self.optionChooser.button == button:
            action.__init__(self.optionChooser.getOptions())
            self.test.callAction(action)
            return
        action.describe(self.test)
        self.dataWindow.remove(self.dataWindow.get_child())
        self.optionChooser = OptionChooser(button, action, self.test)
        self.dataWindow.add_with_viewport(self.optionChooser.display)
        self.dataWindow.show()
        button.set_label(action.getTitle())
        button.show()


class OptionChooser:
    def __init__(self, button, action, test):
        self.entries = []
        self.checkButtons = []
        self.button = button
        self.display = self.createDisplay(action)
    def createDisplay(self, action):
        vbox = gtk.VBox()
        for key, description in action.getArgumentOptions().items():
            hbox = gtk.HBox()
            label = gtk.Label(description + "  ")
            entry = eventHandler.createEntry(description)
            hbox.pack_start(label, expand=gtk.FALSE, fill=gtk.TRUE)
            hbox.pack_start(entry, expand=gtk.TRUE, fill=gtk.TRUE)
            label.show()
            entry.show()
            hbox.show()
            self.entries.append((entry, key))
            vbox.pack_start(hbox, expand=gtk.FALSE, fill=gtk.FALSE)
        for key, description in action.getSwitches().items():
            checkButton = eventHandler.createCheckButton(description)
            checkButton.show()
            self.checkButtons.append((checkButton, key))
            vbox.pack_start(checkButton, expand=gtk.FALSE, fill=gtk.FALSE)
        vbox.show()    
        return vbox
    def getOptions(self):
        options = []
        for entry, option in self.entries:
            text = entry.get_text()
            if len(text):
                options.append(option + "=" + text)
        for button, option in self.checkButtons:
            if button.get_active():
                options.append(option)
        return options

