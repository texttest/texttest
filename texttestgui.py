#!/usr/bin/env python

# GUI for TextTest written with PyGTK

import guiplugins, plugins, comparetest, gtk, gobject, os, string, time, sys
from threading import Thread, currentThread
from gtkscript import eventHandler
from Queue import Queue, Empty
from ndict import seqdict

class TextTestGUI:
    def __init__(self, dynamic, replayScriptName, recordScriptName):
        eventHandler.setScripts(replayScriptName, recordScriptName)
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT)
        self.dynamic = dynamic
        self.instructions = []
        self.postponedInstructions = []
        self.postponedTests = []
        self.itermap = seqdict()
        self.actionThread = None
        self.quitGUI = 0
        self.rightWindowGUI = None
        self.contents = None
        self.workQueue = Queue()
    def createTopWindow(self, testWins):
        # Create toplevel window to show it all.
        win = gtk.Window(gtk.WINDOW_TOPLEVEL)
        win.set_title("TextTest functional tests")
        eventHandler.connect("close", "delete_event", win, self.quit)
        vbox = self.createWindowContents(testWins)
        win.add(vbox)
        win.show()
        screenWidth = gtk.gdk.screen_width()
        screenHeight = gtk.gdk.screen_height()
        win.resize((screenWidth * 2) / 5, (screenHeight * 4) / 5)
        return win
    def createIterMap(self):
        iter = self.model.get_iter_root()
        self.createSubIterMap(iter)
    def createSubIterMap(self, iter):
        test = self.model.get_value(iter, 2)
        childIter = self.model.iter_children(iter)
        try:
            self.itermap[test] = iter.copy()
            test.observers.append(self)
        except TypeError:
            # Applications aren't hashable, but they don't change state anyway
            pass
        if childIter:
            self.createSubIterMap(childIter)
        nextIter = self.model.iter_next(iter)
        if nextIter:
            self.createSubIterMap(nextIter)
    def addApplication(self, app):
        iter = self.model.insert_before(None, None)
        self.model.set_value(iter, 0, "Application " + app.fullName)
        self.model.set_value(iter, 1, "purple")
        self.model.set_value(iter, 2, app)
    def addSuite(self, suite):
        if not self.dynamic:
            self.addApplication(suite.app)
        self.addSuiteWithParent(suite, None)
    def addSuiteWithParent(self, suite, parent):
        iter = self.model.insert_before(parent, None)
        self.model.set_value(iter, 0, suite.name)
        self.model.set_value(iter, 2, suite)
        try:
            for test in suite.testcases:
                self.addSuiteWithParent(test, iter)
        except:
            pass
        self.model.set_value(iter, 1, self.getTestColour(suite))
        return iter
    def getTestColour(self, test):
        if test.state == test.FAILED or test.state == test.UNRUNNABLE:
            return "red"
        if test.state == test.SUCCEEDED:
            return "green"
        if test.state == test.RUNNING:
            return "yellow"
        return self.staticColour()
    def staticColour(self):
        if self.dynamic:
            return "white"
        else:
            return "pale green"
    def createWindowContents(self, testWins):
        self.contents = gtk.HBox(homogeneous=gtk.TRUE)
        testCaseWin = self.rightWindowGUI.getWindow()
        self.contents.pack_start(testWins, expand=gtk.TRUE, fill=gtk.TRUE)
        self.contents.pack_start(testCaseWin, expand=gtk.TRUE, fill=gtk.TRUE)
        self.contents.show()
        return self.contents
    def createTestWindows(self):
        # Create some command buttons.
        buttons = [("Quit", self.quit)]
        if self.dynamic:
            buttons.append(("Save All", self.saveAll))
        buttonbox = self.makeButtons(buttons)
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
        self.selection = view.get_selection()
        if not self.dynamic:
            self.selection.set_mode(gtk.SELECTION_MULTIPLE)
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn("All Tests", renderer, text=0, background=1)
        view.append_column(column)
        view.expand_all()
        eventHandler.connect("select test", "row_activated", view, self.viewTest, argumentParseData=(column, 0))
        eventHandler.connect("add to test selection", "changed", self.selection, sense=1, argumentParseData=(column, 0))
        eventHandler.connect("remove from test selection", "changed", self.selection, sense=-1, argumentParseData=(column, 0))
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
        testWins = self.createTestWindows()
        self.createDefaultRightGUI()
        topWindow = self.createTopWindow(testWins)
        if self.dynamic:
            self.actionThread = Thread(None, self.runActionThread, "action", ())
            self.actionThread.start()
            eventHandler.addIdle("test actions", self.pickUpChange)
        # Run the Gtk+ main loop.
        gtk.main()
    def createDefaultRightGUI(self):
        iter = self.model.get_iter_root()
        self.viewTestAtIter(iter)
    def pickUpChange(self):
        try:
            test = self.workQueue.get_nowait()
            if test == "actions finished":
                self.actionThread.join()
                return gtk.FALSE
            if test:
                self.testChanged(test)
            return gtk.TRUE
        except Empty:
            # We must sleep for a bit, or we use the whole CPU (busy-wait)
            time.sleep(0.1)
            return gtk.TRUE
    def testChanged(self, test):
        if test.classId() == "test-case":
            self.redrawTest(test)
        else:
            self.redrawSuite(test)
        if self.rightWindowGUI and self.rightWindowGUI.test == test:
            self.recreateTestView(test)
    def runActionThread(self):
        while len(self.instructions):
            for test, action in self.instructions:
                if self.quitGUI:
                    return
                self.performAction(test, action)
            self.instructions = self.postponedInstructions
            self.postponedTests = []
            self.postponedInstructions = []
        self.workQueue.put("actions finished")
    def performAction(self, test, action):
        while 1:
            if self.quitGUI:
                return 0

            if test in self.postponedTests:
                self.postponedInstructions.append((test, action))
                return 1
            else:
                retValue = test.callAction(action)
                if retValue == "retry":
                    # Don't busy-wait
                    time.sleep(0.1)
                    continue
                elif retValue == "wait":
                    self.postponedTests.append(test)
                    self.postponedInstructions.append((test, action))
            return 1
    def notifyChange(self, test):
        if currentThread() == self.actionThread:
            self.workQueue.put(test)
        else:
            self.testChanged(test)
    # We assume that test-cases have changed state, while test suites have changed contents
    def redrawTest(self, test):
        iter = self.itermap[test]
        self.model.set_value(iter, 1, self.getTestColour(test))
    def redrawSuite(self, suite):
        newTest = suite.testcases[-1]
        suiteIter = self.itermap[suite]
        iter = self.addSuiteWithParent(newTest, suiteIter)
        self.itermap[newTest] = iter.copy()
        newTest.observers.append(self)
    def quit(self, *args):
        self.quitGUI = 1
        gtk.main_quit()
        self.rightWindowGUI.killProcesses()
        if self.actionThread:
            self.actionThread.join()
    def saveAll(self, *args):
        saveTestAction = self.rightWindowGUI.getSaveTestAction()
        for test in self.itermap.keys():
            if test.state == test.FAILED:
                if not saveTestAction:
                    saveTestAction = guiplugins.SaveTest(test)
                saveTestAction(test)
    def viewTest(self, view, path, column, *args):
        self.viewTestAtIter(self.model.get_iter(path))
    def viewTestAtIter(self, iter):
        test = self.model.get_value(iter, 2)
        print "Viewing test", test
        colour = self.model.get_value(iter, 1)
        self.recreateTestView(test, colour)
    def recreateTestView(self, test, colour = ""):
        if self.rightWindowGUI:
            self.contents.remove(self.rightWindowGUI.getWindow())
        if colour == "purple":
            self.rightWindowGUI = ApplicationGUI(test, self.selection, self.itermap)
        else:
            self.rightWindowGUI = TestCaseGUI(test, self.staticColour())
        if self.contents:
            self.contents.pack_start(self.rightWindowGUI.getWindow(), expand=gtk.TRUE, fill=gtk.TRUE)
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

class RightWindowGUI:
    def __init__(self, object):
        self.object = object
        self.fileViewAction = guiplugins.ViewFile(object)
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT)
        self.addFilesToModel()
        view = self.createView(self.createTitle())
        self.actionInstances = self.makeActionInstances()
        buttons = self.makeButtons(self.actionInstances)
        notebook = self.createNotebook(self.actionInstances)
        self.window = self.createWindow(buttons, view, notebook)
    def createTitle(self):
        return repr(self.object).replace("_", "__")
    def getWindow(self):
        return self.window
    def createView(self, title):
        view = gtk.TreeView(self.model)
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn(title, renderer, text=0, background=1)
        view.append_column(column)
        view.expand_all()
        eventHandler.connect("select file", "row_activated", view, self.displayDifferences, (column, 0))
        view.show()
        return view
    def makeActionInstances(self):
        # The file view action is a special one that we "hardcode" so we can find it...
        return [ self.fileViewAction ] + guiplugins.interactiveActionHandler.getInstances(self.object)
    def makeButtons(self, interactiveActions):
        executeButtons = gtk.HBox()
        for instance in interactiveActions:
            buttonTitle = instance.getTitle()
            if instance.canPerformOnTest():
                self.addButton(self.runInteractive, executeButtons, buttonTitle, instance.getScriptTitle(), instance)
        executeButtons.show()
        return executeButtons
    def addFileToModel(self, iter, name, comp, colour):
        fciter = self.model.insert_before(iter, None)
        baseName = os.path.basename(name)
        heading = self.model.get_value(iter, 0)
        print "Adding file", baseName, "under heading '" + heading + "', coloured", colour 
        self.model.set_value(fciter, 0, baseName)
        self.model.set_value(fciter, 1, colour)
        self.model.set_value(fciter, 2, name)
        if comp:
            self.model.set_value(fciter, 3, comp)
        return fciter
    def killProcesses(self):
        for instance in self.actionInstances:
            instance.killProcesses()
    def createNotebook(self, interactiveActions):
        pages = self.getHardcodedNotebookPages()
        for instance in interactiveActions:
            for optionGroup in instance.getOptionGroups():
                if optionGroup.switches or optionGroup.options:
                    print os.linesep + "Creating notebook page for '" + optionGroup.name + "'"
                    display = self.createDisplay(optionGroup)
                    pages.append((display, optionGroup.name))
        notebook = eventHandler.createNotebook("notebook", pages)
        notebook.show()
        return notebook
    def getHardcodedNotebookPages(self):
        return []
    def createWindow(self, buttons, view, notebook):
        fileWin = gtk.ScrolledWindow()
        fileWin.add(view)
        vbox = gtk.VBox()
        vbox.pack_start(buttons, expand=gtk.FALSE, fill=gtk.FALSE)
        vbox.pack_start(fileWin, expand=gtk.TRUE, fill=gtk.TRUE)
        vbox.pack_start(notebook, expand=gtk.TRUE, fill=gtk.TRUE)
        fileWin.show()
        vbox.show()    
        return vbox
    def displayDifferences(self, view, path, column, *args):
        iter = self.model.get_iter(path)
        fileName = self.model.get_value(iter, 2)
        comparison = self.model.get_value(iter, 3)
        self.fileViewAction.view(comparison, fileName)
    def addButton(self, method, buttonbox, label, scriptTitle, option):
        button = gtk.Button()
        button.set_label(label)
        eventHandler.connect(scriptTitle, "clicked", button, method, None, 1, option)
        button.show()
        buttonbox.pack_start(button, expand=gtk.FALSE, fill=gtk.FALSE)
    def createDisplay(self, optionGroup):
        vbox = gtk.VBox()
        for option in optionGroup.options.values():
            hbox = gtk.HBox()
            print "Creating entry for option '" + option.name + "'"
            label = gtk.Label(option.name + "  ")
            entry = eventHandler.createEntry(option.name, option.defaultValue)
            option.valueMethod = entry.get_text
            hbox.pack_start(label, expand=gtk.FALSE, fill=gtk.TRUE)
            hbox.pack_start(entry, expand=gtk.TRUE, fill=gtk.TRUE)
            label.show()
            entry.show()
            hbox.show()
            vbox.pack_start(hbox, expand=gtk.FALSE, fill=gtk.FALSE)
        for switch in optionGroup.switches.values():
            print "Creating check button for switch '" + switch.name + "'"
            checkButton = eventHandler.createCheckButton(switch.name, switch.defaultValue)
            switch.valueMethod = checkButton.get_active
            checkButton.show()
            vbox.pack_start(checkButton, expand=gtk.FALSE, fill=gtk.FALSE)
        vbox.show()    
        return vbox

class ApplicationGUI(RightWindowGUI):
    def __init__(self, app, selection, itermap):
        self.app = app
        RightWindowGUI.__init__(self, app)
        self.selection = selection
        self.itermap = {}
        for test, iter in itermap.items():
            self.itermap[test.abspath] = iter
    def addFilesToModel(self):
        confiter = self.model.insert_before(None, None)
        self.model.set_value(confiter, 0, "Configuration Files")
        configFiles = []
        for file in os.listdir(self.app.abspath):
            if self.app.ownsFile(file) and file.startswith("config."):
                configFiles.append(file)
        configFiles.sort()
        for file in configFiles:
            fullPath = os.path.join(self.app.abspath, file)
            self.addFileToModel(confiter, fullPath, None, "purple")
    def runInteractive(self, button, action, *args):
        newSuite = action.performOn(self.app, self.getSelectedTests())
        if newSuite:
            self.selection.unselect_all()
            self.selectionChanged(newSuite)
            self.selection.get_tree_view().grab_focus()
    def selectionChanged(self, suite):
        try:
            for test in suite.testcases:
                self.selectionChanged(test)
        except AttributeError:
            self.selection.select_iter(self.itermap[suite.abspath])
    def getSelectedTests(self):
        tests = []
        self.selection.selected_foreach(self.addSelTest, tests)
        return tests
    def addSelTest(self, model, path, iter, tests, *args):
        tests.append(model.get_value(iter, 0))
            
class TestCaseGUI(RightWindowGUI):
    def __init__(self, test, staticColour):
        self.test = test
        self.staticColour = staticColour
        RightWindowGUI.__init__(self, test)
        self.testComparison = None
    def getHardcodedNotebookPages(self):
        textview = self.createTextView(self.test)
        return [(textview, "Text Info")]
    def addFilesToModel(self):
        if self.test.state >= self.test.RUNNING:
            self.addDynamicFilesToModel(self.test)
        else:
            self.addStaticFilesToModel(self.test)
    def addDynamicFilesToModel(self, test):
        compiter = self.model.insert_before(None, None)
        self.model.set_value(compiter, 0, "Comparison Files")
        newiter = self.model.insert_before(None, None)
        self.model.set_value(newiter, 0, "New Files")

        self.testComparison = test.stateDetails
        if test.state == test.RUNNING:
            self.testComparison = comparetest.TestComparison(test, 0)
            self.testComparison.makeComparisons(test, makeNew = 1)
        try:
            for fileName in self.testComparison.attemptedComparisons:
                fileComparison = self.testComparison.findFileComparison(fileName)
                if not fileComparison:
                    self.addFileToModel(compiter, fileName, fileComparison, self.getSuccessColour())
                elif not fileComparison.newResult():
                    self.addFileToModel(compiter, fileName, fileComparison, self.getFailureColour())
            for fc in self.testComparison.newResults:
                self.addFileToModel(newiter, fc.tmpFile, fc, self.getFailureColour())
        except AttributeError:
            pass
    def addStaticFilesToModel(self, test):
        if test.classId() == "test-case":
            stditer = self.model.insert_before(None, None)
            self.model.set_value(stditer, 0, "Standard Files")
        defiter = self.model.insert_before(None, None)
        self.model.set_value(defiter, 0, "Definition Files")
        stdFiles = []
        defFiles = []
        for file in os.listdir(test.abspath):
            if test.app.ownsFile(file):
                if self.isDefinitionFile(file):
                    defFiles.append(file)
                elif test.classId() == "test-case":
                    stdFiles.append(file)
        self.addFilesUnderIter(defiter, defFiles, test.abspath)
        if len(stdFiles):
            self.addFilesUnderIter(stditer, stdFiles, test.abspath)
        for name, filelist in test.extraReadFiles().items():
            exiter = self.model.insert_before(None, None)
            self.model.set_value(exiter, 0, name + " Files")
            self.addFilesUnderIter(exiter, filelist)
    def addFilesUnderIter(self, iter, files, dir = None):
        files.sort()
        for file in files:
            if dir:
                fullPath = os.path.join(dir, file)
            else:
                fullPath = file
            newiter = self.addFileToModel(iter, fullPath, None, self.staticColour)
    def isDefinitionFile(self, file):
        definitions = [ "options.", "input.", "environment", "testsuite" ]
        for defin in definitions:
            if file.startswith(defin):
                return 1
        return 0
    def getSuccessColour(self):
        if self.test.state == self.test.RUNNING:
            return "yellow"
        else:
            return "green"
    def getFailureColour(self):
        if self.test.state == self.test.RUNNING:
            return "yellow"
        else:
            return "red"
    def getSaveTestAction(self):
        for instance in self.actionInstances:
            if isinstance(instance, guiplugins.SaveTest):
                return instance
        return None
    def createTextView(self, test):
        textViewWindow = gtk.ScrolledWindow()
        textview = gtk.TextView()
        textview.set_wrap_mode(gtk.WRAP_WORD)
        textbuffer = textview.get_buffer()
        textbuffer.set_text(self.getTestInfo(test))
        textViewWindow.add(textview)
        textview.show()
        textViewWindow.show()
        return textViewWindow
    def getTestInfo(self, test):
        if not test:
            return ""
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
    def runInteractive(self, button, action, *args):
        self.test.callAction(action)

# Class for importing self tests
class ImportTestCase(guiplugins.ImportTestCase):
    def addOptionsFileOption(self):
        guiplugins.ImportTestCase.addOptionsFileOption(self)
        self.optionGroup.addSwitch("GUI", "Use TextTest GUI", 1)
        self.optionGroup.addSwitch("sGUI", "Use TextTest Static GUI", 0)
        targetApp = self.test.makePathName("TargetApp", self.test.abspath)
        root, local = os.path.split(targetApp)
        self.defaultTargetApp = plugins.samefile(root, self.test.app.abspath)
        if self.defaultTargetApp:
            self.optionGroup.addSwitch("sing", "Only run test A03", 1)
            self.optionGroup.addSwitch("fail", "Include test failures", 1)
            self.optionGroup.addSwitch("version", "Run with Version 2.4")
    def getOptions(self):
        options = guiplugins.ImportTestCase.getOptions(self)
        if self.optionGroup.getSwitchValue("sGUI"):
            options += " -gx"
        elif self.appIsGUI():
            options += " -g"
        if self.defaultTargetApp:
            if self.optionGroup.getSwitchValue("sing"):
                options += " -t A03"
            if self.optionGroup.getSwitchValue("fail"):
                options += " -c CodeFailures"
            if self.optionGroup.getSwitchValue("version"):
                options += " -v 2.4"
        return options
    def appIsGUI(self):
        return self.optionGroup.getSwitchValue("GUI")
        
