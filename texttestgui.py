#!/usr/bin/env python

# GUI for TextTest written with PyGTK

import guiplugins, plugins, comparetest, gtk, gobject, os, string, time, sys
from threading import Thread, currentThread
from gtkusecase import ScriptEngine
from Queue import Queue, Empty
from ndict import seqdict

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
    def __init__(self, dynamic, replayScriptName, recordScriptName, stdinScriptName):
        guiplugins.setUpGuiLog()
        global guilog, scriptEngine
        from guiplugins import guilog
        scriptEngine = ScriptEngine(replayScriptName, recordScriptName, stdinScriptName, guilog)
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT,\
                                   gobject.TYPE_STRING, gobject.TYPE_STRING)
        self.dynamic = dynamic
        self.performanceColumn = 0
        self.itermap = seqdict()
        self.actionThread = None
        self.rightWindowGUI = None
        self.contents = None
        self.workQueue = Queue()
    def createTopWindow(self, testWins):
        # Create toplevel window to show it all.
        win = gtk.Window(gtk.WINDOW_TOPLEVEL)
        win.set_title("TextTest functional tests")
        scriptEngine.connect("close", "delete_event", win, self.quit)
        vbox = self.createWindowContents(testWins)
        win.add(vbox)
        win.show()
        win.resize(self.getWindowWidth(), self.getWindowHeight())
        return win
    def getWindowHeight(self):
        return (gtk.gdk.screen_height() * 4) / 5
    def getWindowWidth(self):
        screenWidth = gtk.gdk.screen_width()
        if self.performanceColumn:
            return (screenWidth * 5) / 11
        else:
            return (screenWidth * 2) / 5
    def createIterMap(self):
        guilog.info("Mapping tests in tree view...")
        iter = self.model.get_iter_root()
        self.createSubIterMap(iter)
        guilog.info("")
    def createSubIterMap(self, iter):
        test = self.model.get_value(iter, 2)
        guilog.info("-> " + test.getIndent() + "Added " + repr(test) + " to test tree view.")
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
        colour = app.getConfigValue("test_colours")["app_static"]
        iter = self.model.insert_before(None, None)
        self.model.set_value(iter, 0, "Application " + app.fullName)
        self.model.set_value(iter, 1, colour)
        self.model.set_value(iter, 2, app)
    def addSuite(self, suite):
        if not self.dynamic:
            self.addApplication(suite.app)
        if self.dynamic and suite.app.hasPerformanceComparison():
            self.performanceColumn = 1
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
        self.updateStateInModel(suite, iter)
        try:
            for test in suite.testcases:
                self.addSuiteWithParent(test, iter)
        except:
            pass
        return iter
    def getTypeBreakdown(self, test):
        try:
            return test.stateDetails.getTypeBreakdown()
        except AttributeError:
            return "failure", "success"
    def updateStateInModel(self, test, iter, state = None):
        colours = test.getConfigValue("test_colours")
        if not self.dynamic:
            return self.modelUpdate(iter, colours["static"])
        if state == test.FAILED or state == test.UNRUNNABLE:
            behaviourType, performanceType = self.getTypeBreakdown(test)
            if performanceType == "success":
                return self.modelUpdate(iter, colours[behaviourType])
            else:
                return self.modelUpdate(iter, colours[behaviourType], performanceType, colours["failure"])
        if state == test.SUCCEEDED:
            return self.modelUpdate(iter, colours["success"])
        if state == test.RUNNING:
            return self.modelUpdate(iter, colours["running"])
        return self.modelUpdate(iter, colours["not_started"])
    def modelUpdate(self, iter, colour, details="", colour2=None):
        if not colour2:
            colour2 = colour
        self.model.set_value(iter, 1, colour)
        if self.performanceColumn:
            self.model.set_value(iter, 3, details)
            self.model.set_value(iter, 4, colour2)
    def stateChangeDescription(self, test, state):
        if state == test.RUNNING:
            return "start"
        if state == test.FAILED or state == test.UNRUNNABLE or state == test.SUCCEEDED:
            return "complete"
        return "finish preprocessing"
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
        if self.performanceColumn:
            perfColumn = gtk.TreeViewColumn("Performance", renderer, text=3, background=4)
            view.append_column(perfColumn)
        view.expand_all()
        scriptEngine.monitorTreeSelection("add to test selection", "remove from test selection", self.selection, argumentParseData=(column, 0))
        scriptEngine.connect("select test", "row_activated", view, self.viewTest, argumentParseData=(column, 0))
        view.show()

        # Create scrollbars around the view.
        scrolled = gtk.ScrolledWindow()
        scrolled.add(view)
        scrolled.show()    
        return scrolled
    def takeControl(self, actionRunner):
        # We've got everything and are ready to go
        self.createIterMap()
        testWins = self.createTestWindows()
        self.createDefaultRightGUI()
        topWindow = self.createTopWindow(testWins)
        if self.dynamic:
            self.actionThread = ActionThread(actionRunner)
            self.actionThread.start()
            gtk.idle_add(self.pickUpChange)
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
    def testChanged(self, test, state, byAction):
        if test.classId() == "test-case":
            self.redrawTest(test, state)
            if byAction:
                test.stateChangeEvent(state)
        else:
            self.redrawSuite(test)
        if self.rightWindowGUI and self.rightWindowGUI.test == test:
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
        if self.performanceColumn:
            guilog.info("(Second column '" + self.model.get_value(iter, 3) + "' coloured " + self.model.get_value(iter, 4) + ")")
    def redrawSuite(self, suite):
        newTest = suite.testcases[-1]
        suiteIter = self.itermap[suite]
        iter = self.addSuiteWithParent(newTest, suiteIter)
        self.itermap[newTest] = iter.copy()
        newTest.observers.append(self)
        scriptEngine.setSelection(self.selection, [ iter ]) 
        guilog.info("Viewing new test " + newTest.name)
        self.recreateTestView(newTest)
    def quit(self, *args):
        gtk.main_quit()
        self.rightWindowGUI.killProcesses()
        if self.actionThread:
            self.actionThread.terminate()
    def saveAll(self, *args):
        saveTestAction = self.rightWindowGUI.getSaveTestAction()
        for test in self.itermap.keys():
            if test.state == test.FAILED:
                if not saveTestAction:
                    saveTestAction = guiplugins.SaveTest(test)
                saveTestAction(test)
    def viewApp(self, *args):
        self.selection.selected_foreach(self.viewAppFromTest)
    def viewAppFromTest(self, model, path, iter, *args):
        test = model.get_value(iter, 2)
        if test.classId() != "test-app":
            app = test.app
            if self.rightWindowGUI.object != app:
                guilog.info("Viewing app " + repr(app))
                self.recreateTestView(app)
    def viewTest(self, view, path, column, *args):
        iter = self.model.get_iter(path)
        scriptEngine.setSelection(self.selection, [ iter ])
        self.viewTestAtIter(iter)
    def viewTestAtIter(self, iter):
        test = self.model.get_value(iter, 2)
        guilog.info("Viewing test " + repr(test))
        self.recreateTestView(test)
    def recreateTestView(self, test):
        if self.rightWindowGUI:
            self.contents.remove(self.rightWindowGUI.getWindow())
        if test.classId() == "test-app":
            self.rightWindowGUI = ApplicationGUI(test, self.selection, self.itermap)
        else:
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
        scriptEngine.connect("select file", "row_activated", view, self.displayDifferences, (column, 0))
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
        guilog.info("Adding file " + baseName + " under heading '" + heading + "', coloured " + colour) 
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
                    guilog.info("") # blank line
                    guilog.info("Creating notebook page for '" + optionGroup.name + "'")
                    display = self.createDisplay(optionGroup)
                    pages.append((display, optionGroup.name))
        notebook = scriptEngine.createNotebook("notebook", pages)
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
    def createDisplay(self, optionGroup):
        vbox = gtk.VBox()
        for option in optionGroup.options.values():
            hbox = gtk.HBox()
            guilog.info("Creating entry for option '" + option.name + "'")
            label = gtk.Label(option.name + "  ")
            entry = scriptEngine.createEntry(option.name, option.getValue())
            option.setMethods(entry.get_text, entry.set_text)
            hbox.pack_start(label, expand=gtk.FALSE, fill=gtk.TRUE)
            hbox.pack_start(entry, expand=gtk.TRUE, fill=gtk.TRUE)
            label.show()
            entry.show()
            hbox.show()
            vbox.pack_start(hbox, expand=gtk.FALSE, fill=gtk.FALSE)
        for switch in optionGroup.switches.values():
            guilog.info("Creating check button for switch '" + switch.name + "'")
            checkButton = scriptEngine.createCheckButton(switch.name, switch.getValue())
            switch.setMethods(checkButton.get_active, checkButton.set_active)
            checkButton.show()
            vbox.pack_start(checkButton, expand=gtk.FALSE, fill=gtk.FALSE)
        vbox.show()    
        return vbox

class ApplicationGUI(RightWindowGUI):
    def __init__(self, app, selection, itermap):
        self.app = app
        RightWindowGUI.__init__(self, app, 1)
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
        colour = self.app.getConfigValue("file_colours")["app_static"]
        for file in configFiles:
            fullPath = os.path.join(self.app.abspath, file)
            self.addFileToModel(confiter, fullPath, None, colour)
    def runInteractive(self, button, action, *args):
        newSuite = action.performOn(self.app, self.getSelectedTests())
        if newSuite:
            # Disable recording of selection changes: they're happening programatically
            iterlist = self.getSelectedIters(newSuite)
            scriptEngine.setSelection(self.selection, iterlist)
            self.selection.get_tree_view().grab_focus()
    def getSelectedIters(self, suite):
        iters = []
        try:
            for test in suite.testcases:
                iters += self.getSelectedIters(test)
            return iters
        except AttributeError:
            return [ self.itermap[suite.abspath] ]    
    def getSelectedTests(self):
        tests = []
        self.selection.selected_foreach(self.addSelTest, tests)
        return tests
    def addSelTest(self, model, path, iter, tests, *args):
        tests.append(model.get_value(iter, 0))

    
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
        colour = self.colours["static"]
        if self.dynamic:
            colour = self.colours["not_started"]
        for file in files:
            if dir:
                fullPath = os.path.join(dir, file)
            else:
                fullPath = file
            newiter = self.addFileToModel(iter, fullPath, None, colour)
    def isDefinitionFile(self, file):
        definitions = [ "options.", "input.", "usecase.", "environment", "testsuite" ]
        for defin in definitions:
            if file.startswith(defin):
                return 1
        return 0
    def getSuccessColour(self):
        if self.test.state == self.test.RUNNING:
            return self.colours["running"]
        else:
            return self.colours["success"]
    def getFailureColour(self):
        if self.test.state == self.test.RUNNING:
            return self.colours["running"]
        else:
            return self.colours["failure"]
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
        self.test.performAction(action)

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
                              
