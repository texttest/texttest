#!/usr/bin/env python

# GUI for TextTest written with PyGTK

import guiplugins, comparetest, gtk, gobject, os, string, time, sys
from threading import Thread, currentThread
from gtkscript import eventHandler
from Queue import Queue, Empty

class TextTestGUI:
    def __init__(self, replayScriptName, recordScriptName):
        eventHandler.setScripts(replayScriptName, recordScriptName)
        if replayScriptName:
            guiplugins.InteractiveAction.allowExternalPrograms = 0
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT)
        self.instructions = []
        self.postponedInstructions = []
        self.postponedTests = []
        self.allTests = []
        self.itermap = {}
        self.quitGUI = 0
        self.workQueue = Queue()
    def createTopWindow(self):
        # Create toplevel window to show it all.
        win = gtk.Window(gtk.WINDOW_TOPLEVEL)
        win.set_title("TextTest functional tests")
        eventHandler.connect("close", "delete_event", win, self.quit)
        vbox = self.createWindowContents()
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
        self.itermap[test] = iter.copy()
        childIter = self.model.iter_children(iter)
        if childIter:
            self.createSubIterMap(childIter)
        if test.classId() == "test-case":
            test.observers.append(self)
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
            self.allTests.append(suite)
            self.model.set_value(iter, 1, self.getTestColour(suite))
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
        buttonbox = self.makeButtons([("Quit", self.quit), ("Save All", self.saveAll)])
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
        self.actionThread = Thread(None, self.runActionThread, "action", ())
        self.actionThread.start()
        eventHandler.addIdle("test actions", self.pickUpChange)
        # Run the Gtk+ main loop.
        gtk.main()
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
        self.redrawTest(test)
        if self.testCaseGUI and self.testCaseGUI.test == test:
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
        if test in self.postponedTests:
            self.postponedInstructions.append((test, action))
        else:
            retValue = test.callAction(action)
            if retValue != None:
                self.postponedTests.append(test)
                self.postponedInstructions.append((test, action))
    def notifyChange(self, test):
        if currentThread() == self.actionThread:
            self.workQueue.put(test)
        else:
            self.testChanged(test)
    def redrawTest(self, test):
        iter = self.itermap[test]
        self.model.set_value(iter, 1, self.getTestColour(test))
        self.model.row_changed(self.model.get_path(iter), iter)
    def quit(self, *args):
        self.quitGUI = 1
        self.actionThread.join()
        gtk.main_quit()
    def saveAll(self, *args):
        saveTestAction = self.testCaseGUI.getSaveTestAction()
        for test in self.allTests:
            if test.state == test.FAILED:
                if not saveTestAction:
                    saveTestAction = guiplugins.SaveTest(test)
                saveTestAction(test)
    def viewTest(self, view, path, column, *args):
        test = self.model.get_value(self.model.get_iter(path), 2)
        print "Viewing test", test
        self.recreateTestView(test)
    def recreateTestView(self, test):
        self.contents.remove(self.testCaseGUI.getWindow())
        self.testCaseGUI = TestCaseGUI(test)
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
    def __init__(self, test = None):
        self.test = test
        self.testComparison = None
        self.fileViewAction = guiplugins.ViewFile(test)
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT)
        self.addFilesToModel(test)
        view = self.createView(self.createTitle(test))
        self.actionInstances = self.makeActionInstances(test)
        buttons = self.makeButtons(self.actionInstances)
        textview = self.createTextView(test)
        notebook = self.createNotebook(textview, self.actionInstances)
        self.window = self.createWindow(buttons, view, notebook)
    def addFilesToModel(self, test):
        compiter = self.model.insert_before(None, None)
        self.model.set_value(compiter, 0, "Comparison Files")
        newiter = self.model.insert_before(None, None)
        self.model.set_value(newiter, 0, "New Files")
        if not test or test.state < test.RUNNING:
            return
        
        self.testComparison = test.stateDetails
        if test.state == test.RUNNING:
            self.testComparison = comparetest.TestComparison(test, 0)
            self.testComparison.makeComparisons(test, test.getDirectory(temporary = 1), makeNew = 1)
        try:
            for fileName in self.testComparison.attemptedComparisons:
                fileComparison = self.testComparison.findFileComparison(fileName)
                if not fileComparison:
                    self.addComparison(compiter, fileName, fileComparison, self.getSuccessColour())
                elif not fileComparison.newResult():
                    self.addComparison(compiter, fileName, fileComparison, self.getFailureColour())
            for fc in self.testComparison.newResults:
                self.addComparison(newiter, fc.tmpFile, fc, self.getFailureColour())
        except AttributeError:
            pass
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
    def addComparison(self, iter, name, comp, colour):
        fciter = self.model.insert_before(iter, None)
        self.model.set_value(fciter, 0, os.path.basename(name))
        self.model.set_value(fciter, 1, colour)
        self.model.set_value(fciter, 2, name)
        if comp:
            self.model.set_value(fciter, 3, comp)
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
    def getWindow(self):
        return self.window
    def createTitle(self, test):
        if not test:
            return "Test-case info"
        return repr(test).replace("_", "__")
    def displayDifferences(self, view, path, column, *args):
        iter = self.model.get_iter(path)
        fileName = self.model.get_value(iter, 2)
        comparison = self.model.get_value(iter, 3)
        self.fileViewAction.view(comparison, fileName)
    def makeActionInstances(self, test):
        instances = []
        if not test:
            return instances
        # A special one that we "hardcode" so we can find it...
        instances.append(self.fileViewAction)
        for intvActionClass in guiplugins.interactiveActionClasses:
            instance = intvActionClass(test)
            instances.append(instance)
        return instances
    def makeButtons(self, interactiveActions):
        executeButtons = gtk.HBox()
        for instance in interactiveActions:
            buttonTitle = instance.getTitle()
            if instance.canPerformOnTest():
                self.addButton(self.runInteractive, executeButtons, buttonTitle, instance)
        executeButtons.show()
        return executeButtons
    def createNotebook(self, textview, interactiveActions):
        pages = []
        pages.append((textview, "Text Info"))
        for instance in interactiveActions:
            if instance.options or instance.switches:
                display = createDisplay(instance.options.values(), instance.switches.values())
                pages.append((display, instance.getOptionTitle()))
        notebook = eventHandler.createNotebook("notebook", pages)
        notebook.show()
        return notebook
    def addButton(self, method, buttonbox, label, option):
        button = gtk.Button()
        button.set_label(label)
        eventHandler.connect(label, "clicked", button, method, None, option)
        button.show()
        buttonbox.pack_start(button, expand=gtk.FALSE, fill=gtk.FALSE)
    def runInteractive(self, button, action, *args):
        self.test.callAction(action)

def createDisplay(options, switches):
    vbox = gtk.VBox()
    for option in options:
        hbox = gtk.HBox()
        label = gtk.Label(option.name + "  ")
        entry = eventHandler.createEntry(option.name, option.defaultValue)
        option.valueMethod = entry.get_text
        hbox.pack_start(label, expand=gtk.FALSE, fill=gtk.TRUE)
        hbox.pack_start(entry, expand=gtk.TRUE, fill=gtk.TRUE)
        label.show()
        entry.show()
        hbox.show()
        vbox.pack_start(hbox, expand=gtk.FALSE, fill=gtk.FALSE)
    for switch in switches:
        checkButton = eventHandler.createCheckButton(switch.name, switch.defaultValue)
        switch.valueMethod = checkButton.get_active
        checkButton.show()
        vbox.pack_start(checkButton, expand=gtk.FALSE, fill=gtk.FALSE)
    vbox.show()    
    return vbox

