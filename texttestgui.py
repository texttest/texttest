#!/usr/bin/env python

# GUI for TextTest written with PyGTK

import guiplugins, plugins, comparetest, gtk, gobject, os, string, time, sys
from threading import Thread, currentThread
from gtkusecase import ScriptEngine, TreeModelIndexer
from Queue import Queue, Empty
from ndict import seqdict

def destroyDialog(dialog, *args):
    dialog.destroy()

def showError(message):
    guilog.info("ERROR : " + message)
    dialog = gtk.Dialog("TextTest Message", buttons=(gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
    dialog.set_modal(gtk.TRUE)
    label = gtk.Label(message)
    dialog.vbox.pack_start(label, expand=gtk.TRUE, fill=gtk.TRUE)
    label.show()
    scriptEngine.connect("agree to texttest message", "response", dialog, destroyDialog, gtk.RESPONSE_ACCEPT)
    dialog.show()


class ActionThread(Thread):
    def __init__(self, actionRunner):
        Thread.__init__(self)
        self.actionRunner = actionRunner
    def run(self):
        try:
            self.actionRunner.run()
        except KeyboardInterrupt:
            print "Terminated before tests complete: cleaning up..." 
    def terminate(self):
        self.actionRunner.interrupt()
        self.join()

class TextTestGUI:
    def __init__(self, dynamic, startTime):
        guiplugins.setUpGuiLog()
        global guilog, scriptEngine
        from guiplugins import guilog
        scriptEngine = ScriptEngine(guilog)
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT,\
                                   gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_STRING)
        self.dynamic = dynamic
        self.itermap = seqdict()
        self.actionThread = None
        self.topWindow = self.createTopWindow(startTime)
        self.rightWindowGUI = None
        self.contents = None
        self.workQueue = Queue()
    def createTopWindow(self, startTime):
        # Create toplevel window to show it all.
        win = gtk.Window(gtk.WINDOW_TOPLEVEL)
        if self.dynamic:
            win.set_title("TextTest dynamic GUI (tests started at " + startTime + ")")
        else:
            win.set_title("TextTest static GUI (test management)")
        scriptEngine.connect("close window", "delete_event", win, self.exit)
        return win
    def fillTopWindow(self, testWins):
        mainWindow = self.createWindowContents(testWins)
        shortcutBar = scriptEngine.createShortcutBar()
        if shortcutBar:
            vbox = gtk.VBox()
            vbox.pack_start(mainWindow, expand=gtk.TRUE, fill=gtk.TRUE)
            vbox.pack_start(shortcutBar, expand=gtk.FALSE, fill=gtk.FALSE)
            shortcutBar.show()
            vbox.show()
            self.topWindow.add(vbox)
        else:
            self.topWindow.add(mainWindow)
        self.topWindow.show()
        self.topWindow.resize(self.getWindowWidth(), self.getWindowHeight())
    def getWindowHeight(self):
        return (gtk.gdk.screen_height() * 5) / 6
    def getWindowWidth(self):
        screenWidth = gtk.gdk.screen_width()
        if self.dynamic:
            return (screenWidth) / 2
        else:
            return (screenWidth * 2) / 5
    def createIterMap(self):
        guilog.info("Mapping tests in tree view...")
        iter = self.model.get_iter_root()
        self.createSubIterMap(iter)
        guilog.info("")
    def createSubIterMap(self, iter, newTest=1):
        test = self.model.get_value(iter, 2)
        guilog.info("-> " + test.getIndent() + "Added " + repr(test) + " to test tree view.")
        childIter = self.model.iter_children(iter)
        if test.classId() != "test-app":
            self.itermap[test] = iter.copy()
            if newTest:
                test.observers.append(self)
        if childIter:
            self.createSubIterMap(childIter, newTest)
        nextIter = self.model.iter_next(iter)
        if nextIter:
            self.createSubIterMap(nextIter, newTest)
    def addApplication(self, app):
        colour = app.getConfigValue("test_colours")["app_static"]
        iter = self.model.insert_before(None, None)
        nodeName = "Application " + app.fullName
        self.model.set_value(iter, 0, nodeName)
        self.model.set_value(iter, 1, colour)
        self.model.set_value(iter, 2, app)
        self.model.set_value(iter, 3, nodeName)
    def addSuite(self, suite):
        if suite.app.getConfigValue("add_shortcut_bar"):
            scriptEngine.enableShortcuts = 1
        if not self.dynamic:
            self.addApplication(suite.app)
        self.addSuiteWithParent(suite, None)
    def addSuiteWithParent(self, suite, parent):
        iter = self.model.insert_before(parent, None)
        nodeName = suite.name
        if parent == None:
            appName = suite.app.name + suite.app.versionSuffix()
            if appName != nodeName:
                nodeName += " (" + appName + ")"
        self.model.set_value(iter, 0, nodeName)
        self.model.set_value(iter, 2, suite)
        self.model.set_value(iter, 3, suite.uniqueName)
        self.updateStateInModel(suite, iter, suite.state)
        try:
            for test in suite.testcases:
                self.addSuiteWithParent(test, iter)
        except:
            pass
        return iter
    def updateStateInModel(self, test, iter, state):
        if not self.dynamic:
            return self.modelUpdate(iter, self.getTestColour(test, "static"))

        resultType, summary = state.getTypeBreakdown()
        return self.modelUpdate(iter, self.getTestColour(test, resultType), summary, self.getTestColour(test, state.category))
    def getTestColour(self, test, category):
        colours = test.getConfigValue("test_colours")
        if colours.has_key(category):
            return colours[category]
        else:
            # Everything unknown is assumed to be a new type of failure...
            return colours["failure"]
    def modelUpdate(self, iter, colour, details="", colour2=None):
        if not colour2:
            colour2 = colour
        self.model.set_value(iter, 1, colour)
        if self.dynamic:
            self.model.set_value(iter, 4, details)
            self.model.set_value(iter, 5, colour2)
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
        else:
            buttons.append(("View App", self.viewApp))
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
        column = gtk.TreeViewColumn("Test Behaviour", renderer, text=0, background=1)
        view.append_column(column)
        if self.dynamic:
            perfColumn = gtk.TreeViewColumn("Details", renderer, text=4, background=5)
            view.append_column(perfColumn)
        view.expand_all()
        modelIndexer = TreeModelIndexer(self.model, column, 3)
        # This does not interact with TextTest at all, so don't bother to connect to PyUseCase
        view.connect("row_expanded", self.expandSuite)
        # The order of these two is vital!
        scriptEngine.connect("select test", "row_activated", view, self.viewTest, modelIndexer)
        if not self.dynamic:
            scriptEngine.monitor("set test selection to", self.selection, modelIndexer)
        view.show()

        # Create scrollbars around the view.
        scrolled = gtk.ScrolledWindow()
        scrolled.add(view)
        scrolled.show()    
        return scrolled
    def expandSuite(self, view, iter, path, *args):
        # Make sure expanding expands everything, better than just one level as default...
        view.expand_row(path, open_all=gtk.TRUE)
    def takeControl(self, actionRunner):
        # We've got everything and are ready to go
        self.createIterMap()
        testWins = self.createTestWindows()
        self.createDefaultRightGUI()
        self.fillTopWindow(testWins)
        if self.dynamic:
            self.actionThread = ActionThread(actionRunner)
            self.actionThread.start()
            gtk.idle_add(self.pickUpChange)
        else:
            gtk.idle_add(self.monitorBackgroundProcesses)
        # Run the Gtk+ main loop.
        gtk.main()
    def createDefaultRightGUI(self):
        iter = self.model.get_iter_root()
        self.viewTestAtIter(iter)
    def pickUpChange(self):
        try:
            test, state = self.workQueue.get_nowait()
            if test:
                self.testChanged(test, state, byAction = 1)
            return gtk.TRUE
        except Empty:
            # Maybe it's empty because the action thread has terminated
            if not self.actionThread.isAlive():
                self.actionThread.join()
                scriptEngine.applicationEvent("completion of test actions")
                return gtk.FALSE
            # We must sleep for a bit, or we use the whole CPU (busy-wait)
            time.sleep(0.1)
            return gtk.TRUE
    def monitorBackgroundProcesses(self):
        termProcesses = []
        for process in guiplugins.InteractiveAction.processes:
            try:
                if process.checkTermination():
                    termProcesses.append(process)
            except plugins.TextTestError, e:
                showError(str(e))
                termProcesses.append(process)
        for process in termProcesses:
            guiplugins.InteractiveAction.processes.remove(process)
        # We must sleep for a bit, or we use the whole CPU (busy-wait)
        time.sleep(0.1)
        return gtk.TRUE
    def testChanged(self, test, state, byAction):
        if test.classId() == "test-case":
            # Working around python bug 853411: main thread must do all forking
            state.notifyInMainThread()
            self.redrawTest(test, state)
            if byAction:
                test.stateChangeEvent(state)
        else:
            self.redrawSuite(test)
        if self.rightWindowGUI and self.rightWindowGUI.object == test:
            self.recreateTestView(test)
    def notifyChange(self, test):
        if currentThread() == self.actionThread:
            self.workQueue.put((test, test.state))
        else:
            self.testChanged(test, test.state, byAction = 0)
    # We assume that test-cases have changed state, while test suites have changed contents
    def redrawTest(self, test, state):
        iter = self.itermap[test]
        self.updateStateInModel(test, iter, state)
        guilog.info("Redrawing test " + test.name + " coloured " + self.model.get_value(iter, 1))
        secondColumnText = self.model.get_value(iter, 4)
        if self.dynamic and secondColumnText:
            guilog.info("(Second column '" + secondColumnText + "' coloured " + self.model.get_value(iter, 5) + ")")
    def redrawSuite(self, suite):
        if len(suite.testcases) == 0:
            return
        maybeNewTest = suite.testcases[-1]
        suiteIter = self.itermap[suite]
        if self.itermap.has_key(maybeNewTest):
            self.redoOrder(suite, suiteIter)
        else:
            self.addNewTestToModel(suiteIter, maybeNewTest, suiteIter)
        self.selection.get_tree_view().grab_focus()
    def addNewTestToModel(self, suite, newTest, suiteIter):
        iter = self.addSuiteWithParent(newTest, suiteIter)
        self.itermap[newTest] = iter.copy()
        newTest.observers.append(self)
        guilog.info("Viewing new test " + newTest.name)
        self.recreateTestView(newTest)
        self.markAndExpand(iter)
    def markAndExpand(self, iter):
        self.selection.get_tree_view().expand_all()
        self.selection.unselect_all()
        self.selection.select_iter(iter)
    def redoOrder(self, suite, suiteIter):
        iter = self.model.iter_children(suiteIter)
        for i in range(len(suite.testcases)):
            self.model.remove(iter)
        for test in suite.testcases:
            iter = self.addSuiteWithParent(test, suiteIter)
        self.createSubIterMap(suiteIter, newTest=0)
        self.markAndExpand(suiteIter)
    def exit(self, *args):
        gtk.main_quit()
        sys.stdout.flush()
        self.killInteractiveProcesses()
        if self.actionThread:
            self.actionThread.terminate()
    def quit(self, *args):
        # Generate a window closedown, so that the quit button behaves the same as closing the window
        self.topWindow.destroy()
        self.exit()
    def killInteractiveProcesses(self):
        # Don't leak processes
        for process in guiplugins.InteractiveAction.processes:
            if not process.hasTerminated():
                guilog.info("Killing '" + repr(process) + "' interactive process")
                process.kill()
    def saveAll(self, *args):
        saveActionFromWindow = self.rightWindowGUI.getSaveTestAction()
        windowVersion = None
        if saveActionFromWindow:
            windowVersion = saveActionFromWindow.test.app.getFullVersion()
            saveTestAction = saveActionFromWindow

        for test in self.itermap.keys():
            currFullVersion = test.app.getFullVersion()
            if currFullVersion == windowVersion:
                saveTestAction = saveActionFromWindow
            else:
                saveTestAction = self.getDefaultSaveAction(test)
            if saveTestAction.isSaveable(test):
                saveTestAction(test)
    def getDefaultSaveAction(self, test):
        return guiplugins.interactiveActionHandler.getInstance(test, guiplugins.SaveTest)
    def viewApp(self, *args):
        self.selection.selected_foreach(self.viewAppFromTest)
    def viewAppFromTest(self, model, path, iter, *args):
        test = model.get_value(iter, 2)
        if test.classId() != "test-app":
            app = test.app
            if not self.rightWindowGUI.object is app:
                guilog.info("Viewing app " + repr(app))
                self.recreateTestView(app)
    def viewTest(self, view, path, column, *args):
        iter = self.model.get_iter(path)
        self.selection.select_iter(iter)
        self.viewTestAtIter(iter)
    def viewTestAtIter(self, iter):
        test = self.model.get_value(iter, 2)
        guilog.info("Viewing test " + repr(test))
        self.recreateTestView(test, checkUpToDate=1)
    def recreateTestView(self, test, checkUpToDate=0):
        if self.rightWindowGUI:
            self.contents.remove(self.rightWindowGUI.getWindow())
            self.rightWindowGUI = None
        if test.classId() == "test-app":
            self.rightWindowGUI = ApplicationGUI(test, self.selection, self.itermap)
        else:
            if checkUpToDate and test.state.isComplete() and test.state.needsRecalculation():
                guilog.info("Recalculating result info for test: result file changed since created")
                cmpAction = comparetest.MakeComparisons()
                cmpAction(test)
            self.rightWindowGUI = TestCaseGUI(test, self.dynamic)
        if self.contents:
            self.contents.pack_start(self.rightWindowGUI.getWindow(), expand=gtk.TRUE, fill=gtk.TRUE)
            self.contents.show()
    def makeButtons(self, list):
        buttonbox = gtk.HBox()
        for label, func in list:
            button = gtk.Button()
            button.set_label(label)
            scriptEngine.connect(label, "clicked", button, func)
            button.show()
            buttonbox.pack_start(button, expand=gtk.FALSE, fill=gtk.FALSE)
        buttonbox.show()
        return buttonbox

class RightWindowGUI:
    def __init__(self, object, dynamic):
        self.object = object
        self.dynamic = dynamic
        self.fileViewAction = guiplugins.interactiveActionHandler.getInstance(object, guiplugins.ViewFile)
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT, gobject.TYPE_STRING)
        self.addFilesToModel()
        view = self.createView()
        self.actionInstances = self.makeActionInstances()
        buttons = self.makeButtons(self.actionInstances)
        notebook = self.createNotebook(self.actionInstances)
        self.window = self.createWindow(buttons, view, notebook)
    def getWindow(self):
        return self.window
    def createView(self):
        view = gtk.TreeView(self.model)
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn(self.object.name.replace("_", "__"), renderer, text=0, background=1)
        view.append_column(column)
        if self.dynamic:
            perfColumn = gtk.TreeViewColumn("Details", renderer, text=4)
            view.append_column(perfColumn)
        view.expand_all()
        indexer = TreeModelIndexer(self.model, column, 0)
        scriptEngine.connect("select file", "row_activated", view, self.displayDifferences, indexer)
        view.show()
        return view
    def makeActionInstances(self):
        # The file view action is a special one that we "hardcode" so we can find it...
        return [ self.fileViewAction ] + guiplugins.interactiveActionHandler.getInstances(self.object, self.dynamic)
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
        self.model.set_value(fciter, 0, baseName)
        self.model.set_value(fciter, 1, colour)
        self.model.set_value(fciter, 2, name)
        guilog.info("Adding file " + baseName + " under heading '" + heading + "', coloured " + colour)
        if comp:
            self.model.set_value(fciter, 3, comp)
            details = comp.getDetails()
            if len(details) > 0:
                self.model.set_value(fciter, 4, details)
                guilog.info("(Second column '" + details + "' coloured " + colour + ")")
        return fciter
    def createNotebook(self, interactiveActions):
        pages = self.getHardcodedNotebookPages()
        for instance in interactiveActions:
            for optionGroup in instance.getOptionGroups():
                if optionGroup.switches or optionGroup.options:
                    guilog.info("") # blank line
                    guilog.info("Creating notebook page for '" + optionGroup.name + "'")
                    display = self.createDisplay(optionGroup)
                    pages.append((display, optionGroup.name))
        notebook = scriptEngine.createNotebook("view options for", pages)
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
        scriptEngine.connect(scriptTitle, "clicked", button, method, None, option)
        button.show()
        buttonbox.pack_start(button, expand=gtk.FALSE, fill=gtk.FALSE)
    def diagnoseOption(self, option):
        value = option.getValue()
        text = "Creating entry for option '" + option.name + "'"
        if len(value) > 0:
            text += " (set to '" + value + "')"
        if len(option.possibleValues) > 1:
            text += " (drop-down list containing " + repr(option.possibleValues) + ")"
        guilog.info(text)
    def diagnoseSwitch(self, switch):
        value = switch.getValue()
        if switch.nameForOff:
            text = "Creating radio button for switch '" + switch.name + "/" + switch.nameForOff + "'"
        else:
            text = "Creating check button for switch '" + switch.name + "'"
        if value:
            text += " (checked)"
        guilog.info(text)        
    def createDisplay(self, optionGroup):
        vbox = gtk.VBox()
        for option in optionGroup.options.values():
            hbox = self.createOptionBox(option)
            vbox.pack_start(hbox, expand=gtk.FALSE, fill=gtk.FALSE)
        for switch in optionGroup.switches.values():
            hbox = self.createSwitchBox(switch)
            vbox.pack_start(hbox, expand=gtk.FALSE, fill=gtk.FALSE)
        vbox.show()    
        return vbox
    def createOptionBox(self, option):
        hbox = gtk.HBox()
        self.diagnoseOption(option)
        label = gtk.Label(option.name + "  ")
        hbox.pack_start(label, expand=gtk.FALSE, fill=gtk.TRUE)
        if len(option.possibleValues) > 1:
            combobox = gtk.Combo()
            entry = combobox.entry
            combobox.set_popdown_strings(option.possibleValues)
            hbox.pack_start(combobox, expand=gtk.TRUE, fill=gtk.TRUE)
            combobox.show()
        else:
            entry = gtk.Entry()
            entry.show()
            hbox.pack_start(entry, expand=gtk.TRUE, fill=gtk.TRUE)
        entry.set_text(option.getValue())
        scriptEngine.registerEntry(entry, "enter " + option.name + " =")
        option.setMethods(entry.get_text, entry.set_text)
        label.show()
        hbox.show()
        return hbox
    def createSwitchBox(self, switch):
        self.diagnoseSwitch(switch)
        if switch.nameForOff:
            radioButton1 = gtk.RadioButton(None, switch.name)
            radioButton2 = gtk.RadioButton(radioButton1, switch.nameForOff)
            if switch.getValue():
                radioButton1.set_active(gtk.TRUE)
            else:
                radioButton2.set_active(gtk.TRUE)
            scriptEngine.registerToggleButton(radioButton1, "choose " + switch.name)
            scriptEngine.registerToggleButton(radioButton2, "choose " + switch.nameForOff)
            switch.setMethods(radioButton1.get_active, radioButton1.set_active)
            switch.resetMethod = radioButton2.set_active
            hbox = gtk.HBox()
            hbox.pack_start(radioButton1, expand=gtk.TRUE, fill=gtk.TRUE)
            hbox.pack_start(radioButton2, expand=gtk.TRUE, fill=gtk.TRUE)
            radioButton1.show()
            radioButton2.show()
            hbox.show()
            return hbox
        else:
            checkButton = gtk.CheckButton(switch.name)
            if switch.getValue():
                checkButton.set_active(gtk.TRUE)
            scriptEngine.registerToggleButton(checkButton, "check " + switch.name, "uncheck " + switch.name)
            switch.setMethods(checkButton.get_active, checkButton.set_active)
            checkButton.show()
            return checkButton
    def runInteractive(self, button, action, *args):
        try:
            self.performInteractiveAction(action)
        except plugins.TextTestError, e:
            showError(str(e))

class ApplicationGUI(RightWindowGUI):
    def __init__(self, app, selection, itermap):
        self.app = app
        RightWindowGUI.__init__(self, app, 1)
        self.selection = selection
        self.itermap = {}
        for test, iter in itermap.items():
            if not self.itermap.has_key(test.app):
                self.itermap[test.app] = {}
            self.itermap[test.app][test] = iter
    def addFilesToModel(self):
        confiter = self.model.insert_before(None, None)
        self.model.set_value(confiter, 0, "Configuration Files")
        configFiles = []
        for file in os.listdir(self.app.abspath):
            if self.app.ownsFile(file) and file.startswith("config."):
                configFiles.append(file)
        configFiles.sort()
        colour = self.app.getConfigValue("file_colours")["app_static"]
        for file in configFiles:
            fullPath = os.path.join(self.app.abspath, file)
            self.addFileToModel(confiter, fullPath, None, colour)
    def performInteractiveAction(self, action):
        if isinstance(action, guiplugins.SelectTests):
            self.selectTests(action)
        else:
            action.performOn(self.app, self.getSelectedTests())
    def selectTests(self, action):
        selectedTests = action.getSelectedTests(self.getRootSuites())
        self.selection.unselect_all()
        for test in selectedTests:
            iter = self.itermap[test.app][test]
            self.selection.select_iter(iter)
        self.selection.get_tree_view().grab_focus()
        guilog.info("Marking " + str(len(self.getSelectedTests())) + " tests as selected")
    def getRootSuites(self):
        suites = [ self.getRootSuite(self.app) ]
        for extraApp in self.app.extras:
            suites.append(self.getRootSuite(extraApp))
        return suites
    def getRootSuite(self, app):
        sampleTest = self.itermap[app].keys()[0]
        return self.getRoot(sampleTest)
    def getRoot(self, test):
        if test.parent:
            return self.getRoot(test.parent)
        else:
            return test
    def getSelectedTests(self):
        tests = []
        self.selection.selected_foreach(self.addSelTest, tests)
        return tests
    def addSelTest(self, model, path, iter, tests, *args):
        tests.append(model.get_value(iter, 2))

    
class TestCaseGUI(RightWindowGUI):
    def __init__(self, test, dynamic):
        self.test = test
        self.colours = test.getConfigValue("file_colours")
        RightWindowGUI.__init__(self, test, dynamic)
        self.testComparison = None
    def getHardcodedNotebookPages(self):
        textview = self.createTextView(self.test)
        return [(textview, "Text Info")]
    def addFilesToModel(self):
        if self.test.state.hasStarted():
            self.addDynamicFilesToModel(self.test)
        else:
            self.addStaticFilesToModel(self.test)
    def addDynamicFilesToModel(self, test):
        compiter = self.model.insert_before(None, None)
        self.model.set_value(compiter, 0, "Comparison Files")
        newiter = self.model.insert_before(None, None)
        self.model.set_value(newiter, 0, "New Files")

        self.testComparison = test.state
        if not test.state.isComplete():
            self.testComparison = comparetest.TestComparison(test.state, test.app.abspath)
            self.testComparison.makeComparisons(test, makeNew = 1)
        diagComps = []
        hasNewDiags, hasOldDiags = 0, 0
        try:
            for fileComparison in self.testComparison.allResults:
                if fileComparison.isDiagnostic():
                    if fileComparison.newResult():
                        hasNewDiags = 1
                    else:
                        hasOldDiags = 1
                    diagComps.append(fileComparison)
                else:
                    self.addDynamicComparisonToModel(newiter, compiter, fileComparison)
        except AttributeError:
            # The above code assumes we have failed on comparison: if not, don't display things
            pass
        diagcompiter, diagnewiter = None, None
        if hasOldDiags:
            guilog.info("Adding subtree for diagnostic comparisons") 
            diagcompiter = self.model.insert_before(compiter, None)
            self.model.set_value(diagcompiter, 0, "Diagnostics")
        if hasNewDiags:
            guilog.info("Adding subtree for new diagnostic files") 
            diagnewiter = self.model.insert_before(newiter, None)
            self.model.set_value(diagnewiter, 0, "Diagnostics")
        for diagComp in diagComps:
            self.addDynamicComparisonToModel(diagnewiter, diagcompiter, diagComp)
    def addDynamicComparisonToModel(self, newiter, compiter, fileComparison):
        if fileComparison.newResult():
            self.addDynamicFileToModel(newiter, fileComparison, self.getFailureColour())
        elif fileComparison.hasDifferences():
            self.addDynamicFileToModel(compiter, fileComparison, self.getFailureColour())
        else:
            self.addDynamicFileToModel(compiter, fileComparison, self.getSuccessColour())
    def addDynamicFileToModel(self, iter, comparison, colour):
        self.addFileToModel(iter, comparison.tmpFile, comparison, colour)
    def addStaticFilesToModel(self, test):
        if test.classId() == "test-case":
            stditer = self.model.insert_before(None, None)
            self.model.set_value(stditer, 0, "Standard Files")
        defiter = self.model.insert_before(None, None)
        self.model.set_value(defiter, 0, "Definition Files")
        stdFiles = []
        defFiles = []
        diagConfigFileName = self.getDiagDefinitionFile(test.app)
        for file in os.listdir(test.abspath):
            if test.app.ownsFile(file):
                if self.isDefinitionFile(file, test.app):
                    defFiles.append(file)
                elif test.classId() == "test-case":
                    stdFiles.append(file)
            elif file == diagConfigFileName:
                defFiles.append(file)
        self.addFilesUnderIter(defiter, defFiles, test.abspath)
        if len(stdFiles):
            self.addFilesUnderIter(stditer, stdFiles, test.abspath)
            self.addStaticDiagFilesToModel(test, diagConfigFileName, stditer, defiter)
        self.addStaticDataFilesToModel(test)
    def addStaticDiagFilesToModel(self, test, diagConfigFileName, stditer, defiter):
        diagDir = os.path.join(test.abspath, "Diagnostics")
        configPath = os.path.join(diagDir, diagConfigFileName)
        if os.path.isfile(configPath):
            defdiagiter = self.model.insert_before(defiter, None)
            self.model.set_value(defdiagiter, 0, "Diagnostics")
            self.addFilesUnderIter(defdiagiter, [ configPath ])
        diagFiles = []
        if os.path.isdir(diagDir):
            for diagFile in os.listdir(diagDir):
                fullPath = os.path.join(diagDir, diagFile)
                if os.path.isfile(fullPath) and diagFile != diagConfigFileName:
                    diagFiles.append(fullPath)
        if len(diagFiles):
            exiter = self.model.insert_before(stditer, None)
            self.model.set_value(exiter, 0, "Diagnostics")
            self.addFilesUnderIter(exiter, diagFiles)
    def addStaticDataFilesToModel(self, test):
        dataFileList = test.extraReadFiles().items()
        if len(dataFileList) > 0:
            datiter = self.model.insert_before(None, None)
            self.model.set_value(datiter, 0, "Data Files")            
            for name, filelist in dataFileList:
                if len(name) > 0:
                    exiter = self.model.insert_before(datiter, None)
                    self.model.set_value(exiter, 0, name)
                    self.addFilesUnderIter(exiter, filelist)
                else:
                    self.addFilesUnderIter(datiter, filelist)
    def getDiagDefinitionFile(self, app):
        diagDict = app.getConfigValue("diagnostics")
        if diagDict.has_key("configuration_file"):
            return diagDict["configuration_file"]
        return ""
    def addFilesUnderIter(self, iter, files, dir = None):
        files.sort()
        colour = self.colours["static"]
        if self.dynamic:
            colour = self.colours["not_started"]
        dirs = []
        for file in files:
            if file == "CVS":
                continue
            if dir:
                fullPath = os.path.join(dir, file)
            else:
                fullPath = file
            if os.path.isdir(fullPath):
                dirs.append(fullPath)
            else:
                self.addFileToModel(iter, fullPath, None, colour)
        for subdir in dirs:
            newiter = self.addFileToModel(iter, subdir, None, colour)
            self.addFilesUnderIter(newiter, os.listdir(subdir), subdir)
    def isDefinitionFile(self, file, app):
        stem = file.split(".")[0]
        return stem in app.getConfigValue("definition_file_stems")
    def getSuccessColour(self):
        if self.test.state.isComplete():
            return self.colours["success"]
        else:
            return self.colours["running"]
    def getFailureColour(self):
        if self.test.state.isComplete():
            return self.colours["failure"]
        else:
            return self.colours["running"]
    def getSaveTestAction(self):
        for instance in self.actionInstances:
            if isinstance(instance, guiplugins.SaveTest) and instance.canPerformOnTest():
                return instance
        return None
    def createTextView(self, test):
        textViewWindow = gtk.ScrolledWindow()
        textview = gtk.TextView()
        textview.set_wrap_mode(gtk.WRAP_WORD)
        textbuffer = textview.get_buffer()
        testInfo = self.getTestInfo(test)
        if len(testInfo):
            guilog.info("---------- Text Info Window ----------")
            guilog.info(testInfo)
            guilog.info("--------------------------------------")
        # Need to convert to utf-8 for display...
        unicodeInfo = unicode(testInfo, "utf-8", errors="replace")
        textbuffer.set_text(unicodeInfo.encode("utf-8"))
        textViewWindow.add(textview)
        textview.show()
        textViewWindow.show()
        return textViewWindow
    def getTestInfo(self, test):
        if not test:
            return ""
        info = ""
        if test.state.isComplete():
            info = "Test " + repr(test.state) + "\n"
        if len(test.state.freeText) > 0:
            return info + str(test.state.freeText)
        else:
            return info.replace(" :", "")
    def performInteractiveAction(self, action):
        self.test.callAction(action)
    
# Class for importing self tests
class ImportTestCase(guiplugins.ImportTestCase):
    def addOptionsFileOption(self, oldOptionGroup):
        guiplugins.ImportTestCase.addOptionsFileOption(self, oldOptionGroup)
        self.addSwitch(oldOptionGroup, "GUI", "Use TextTest GUI", 1)
        self.addSwitch(oldOptionGroup, "sGUI", "Use TextTest Static GUI", 0)
        targetApp = self.test.makePathName("TargetApp", self.test.abspath)
        root, local = os.path.split(targetApp)
        self.defaultTargetApp = plugins.samefile(root, self.test.app.abspath)
        if self.defaultTargetApp:
            self.addSwitch(oldOptionGroup, "sing", "Only run test A03", 1)
            self.addSwitch(oldOptionGroup, "fail", "Include test failures", 1)
            self.addSwitch(oldOptionGroup, "version", "Run with Version 2.4")
    def getOptions(self, suite):
        options = guiplugins.ImportTestCase.getOptions(self, suite)
        if self.optionGroup.getSwitchValue("sGUI"):
            options += " -gx"
        elif self.optionGroup.getSwitchValue("GUI"):
            options += " -g"
        if self.defaultTargetApp:
            if self.optionGroup.getSwitchValue("sing"):
                options += " -t A03"
            if self.optionGroup.getSwitchValue("fail"):
                options += " -c CodeFailures"
            if self.optionGroup.getSwitchValue("version"):
                options += " -v 2.4"
        return options
        
class UpdateScripts(plugins.Action):
    def __call__(self, test):
        fileName = os.path.join(test.abspath, "gui_script")
        if os.path.isfile(fileName):
            newFile = open(fileName + ".new", "w")
            for line in open(fileName).xreadlines():
                newFile.write(line.replace("test actions", "completion of test actions"))
            newFile.close()
            os.rename(fileName + ".new", fileName)
                              
