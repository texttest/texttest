#!/usr/bin/env python

# GUI for TextTest written with PyGTK

import guiplugins, plugins, comparetest, gtk, gobject, os, string, time, sys
from gobject import idle_add
from threading import Thread, currentThread
from gtkusecase import ScriptEngine, TreeModelIndexer
from ndict import seqdict
from respond import ThreadedResponder

def destroyDialog(dialog, *args):
    dialog.destroy()

def showError(message):
    guilog.info("ERROR : " + message)
    dialog = gtk.Dialog("TextTest Message", buttons=(gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
    dialog.set_modal(True)
    label = gtk.Label(message)
    dialog.vbox.pack_start(label, expand=True, fill=True)
    label.show()
    scriptEngine.connect("agree to texttest message", "response", dialog, destroyDialog, gtk.RESPONSE_ACCEPT)
    dialog.show()

class TextTestGUI(ThreadedResponder):
    def __init__(self, optionMap):
        self.dynamic = not optionMap.has_key("gx")
        ThreadedResponder.__init__(self, optionMap)
        scriptEngine = self.scriptEngine
        guiplugins.scriptEngine = self.scriptEngine
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT,\
                                   gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_STRING)
        self.itermap = seqdict()
        self.topWindow = self.createTopWindow()
        self.rightWindowGUI = None
        self.actionThread = None
        self.contents = None
    def setUpScriptEngine(self):
        guiplugins.setUpGuiLog(self.dynamic)
        global guilog, scriptEngine
        from guiplugins import guilog
        scriptEngine = ScriptEngine(guilog, enableShortcuts=1)
        self.scriptEngine = scriptEngine
    def needsTestRuns(self):
        return self.dynamic
    def readAllVersions(self):
        return not self.dynamic
    def createTopWindow(self):
        # Create toplevel window to show it all.
        win = gtk.Window(gtk.WINDOW_TOPLEVEL)
        if self.dynamic:
            win.set_title("TextTest dynamic GUI (tests started at " + plugins.startTimeString() + ")")
        else:
            win.set_title("TextTest static GUI : management of tests")
        scriptEngine.connect("close window", "delete_event", win, self.exit)
        return win
    def fillTopWindow(self, testWins):
        mainWindow = self.createWindowContents(testWins)
        shortcutBar = scriptEngine.createShortcutBar()
        if shortcutBar:
            vbox = gtk.VBox()
            vbox.pack_start(mainWindow, expand=True, fill=True)
            vbox.pack_start(shortcutBar, expand=False, fill=False)
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
        app = suite.app
        if app.getConfigValue("add_shortcut_bar"):
            scriptEngine.enableShortcuts = 1
        if not self.dynamic:
            self.addApplication(app)
        if not self.dynamic or suite.size() > 0:
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
        self.contents = gtk.HBox(homogeneous=True)
        testCaseWin = self.rightWindowGUI.getWindow()
        self.contents.pack_start(testWins, expand=True, fill=True)
        self.contents.pack_start(testCaseWin, expand=True, fill=True)
        self.contents.show()
        return self.contents
    def createTestWindows(self):
        # Create some command buttons.
        buttons = [("_Quit", self.quit)]
        if self.dynamic:
            buttons.append(("Save _All", self.saveAll))
            buttons.append(("Save _Selected", self.saveSelected))
        else:
            buttons.append(("_View App", self.viewApp))
        buttonbox = self.makeButtons(buttons)
        window = self.createTreeWindow()

        # Create a vertical box to hold the above stuff.
        vbox = gtk.VBox()
        vbox.pack_start(buttonbox, expand=False, fill=False)
        vbox.pack_start(window, expand=True, fill=True)
        vbox.show()
        return vbox
    def createDisplayWindows(self):
        hbox = gtk.HBox()
        treeWin = self.createTreeWindow()
        detailWin = self.createDetailWindow()
        hbox.pack_start(treeWin, expand=True, fill=True)
        hbox.pack_start(detailWin, expand=True, fill=True)
        hbox.show()
        return hbox
    def createTreeWindow(self):
        view = gtk.TreeView(self.model)
        self.selection = view.get_selection()
        self.selection.set_mode(gtk.SELECTION_MULTIPLE)
        self.selection.connect("changed", self.selectionChanged)
        renderer = gtk.CellRendererText()
        self.testsColumn = gtk.TreeViewColumn("Tests: 0 selected", renderer, text=0, background=1)
        view.append_column(self.testsColumn)
        if self.dynamic:
            perfColumn = gtk.TreeViewColumn("Details", renderer, text=4, background=5)
            view.append_column(perfColumn)
        view.expand_all()
        modelIndexer = TreeModelIndexer(self.model, self.testsColumn, 3)
        # This does not interact with TextTest at all, so don't bother to connect to PyUseCase
        view.connect("row_expanded", self.expandSuite)
        # The order of these two is vital!
        scriptEngine.connect("select test", "row_activated", view, self.viewTest, modelIndexer)
        scriptEngine.monitor("set test selection to", self.selection, modelIndexer)
        view.show()

        # Create scrollbars around the view.
        scrolled = gtk.ScrolledWindow()
        scrolled.add(view)
        scrolled.show()    
        return scrolled
    def selectionChanged(self, selection):
        self.nofSelectedTests = 0
        self.selection.selected_foreach(self.countSelected)
        self.testsColumn.set_title("Tests: " + str(self.nofSelectedTests) + " selected")
        guilog.info(str(self.nofSelectedTests) + " tests selected")
    def countSelected(self, model, path, iter):
        if self.model.get_value(iter, 2).classId() == "test-case":
            self.nofSelectedTests = self.nofSelectedTests + 1
    def expandSuite(self, view, iter, path, *args):
        # Make sure expanding expands everything, better than just one level as default...
        view.expand_row(path, open_all=True)
    def setUpGui(self):
        self.createIterMap()
        testWins = self.createTestWindows()
        self.createDefaultRightGUI()
        self.fillTopWindow(testWins)
    def runMain(self):
        guilog.info("Top Window title set to " + self.topWindow.get_title())
        # Run the Gtk+ main loop.
        gtk.main()
    def runWithActionThread(self, actionThread):
        self.actionThread = actionThread
        self.setUpGui()
        idle_add(self.pickUpChange)
        self.runMain()
    def runAlone(self):
        self.setUpGui()
        self.expandTitle()
        idle_add(self.pickUpProcess)
        self.runMain()
    def findAllAppNames(self):
        apps = []
        iter = self.model.get_iter_root()
        while iter:
            test = self.model.get_value(iter, 2)
            if test.classId() == "test-app":
                name = test.getConfigValue("full_name")
                if not name in apps:
                    apps.append(name)
            iter = self.model.iter_next(iter)
        return apps
    def expandTitle(self):
        allApps = self.findAllAppNames()
        self.topWindow.set_title(self.topWindow.get_title() + " for " + string.join(allApps, ","))
    def createDefaultRightGUI(self):
        iter = self.model.get_iter_root()
        self.viewTestAtIter(iter)
    def pickUpChange(self):
        response = self.processChangesMainThread()
        # We must sleep for a bit, or we use the whole CPU (busy-wait)
        time.sleep(0.1)
        return response
    def pickUpProcess(self):
        process = guiplugins.processTerminationMonitor.getTerminatedProcess()
        if process:
            try:
                process.runExitHandler()
            except plugins.TextTestError, e:
                showError(str(e))
        
        # We must sleep for a bit, or we use the whole CPU (busy-wait)
        time.sleep(0.1)
        return True
    def notifyChangeMainThread(self, test, state):
        # May have already closed down, don't crash if so
        if not self.selection.get_tree_view():
            return
        if test.classId() == "test-case":            
            # Working around python bug 853411: main thread must do all forking
            if state:
                state.notifyInMainThread()
                self.redrawTest(test, state)
            else:
                self.redrawTest(test, test.state)
        else:
            self.redrawSuite(test)
        if self.rightWindowGUI and self.rightWindowGUI.object is test:
            self.recreateTestView(test)
    # We assume that test-cases have changed state, while test suites have changed contents
    def redrawTest(self, test, state):
        iter = self.itermap[test]
        self.updateStateInModel(test, iter, state)
        guilog.info("Redrawing test " + test.name + " coloured " + self.model.get_value(iter, 1))
        secondColumnText = self.model.get_value(iter, 4)
        if self.dynamic and secondColumnText:
            guilog.info("(Second column '" + secondColumnText + "' coloured " + self.model.get_value(iter, 5) + ")")

        if state.isComplete() and test.getConfigValue("auto_collapse_successful") == 1:
            self.collapseIfAllComplete(self.model.iter_parent(iter))               
    def redrawSuite(self, suite):
        if len(suite.testcases) == 0:
            return
        maybeNewTest = suite.testcases[-1]
        suiteIter = self.itermap[suite]
        if self.itermap.has_key(maybeNewTest):
            # There wasn't a new test: assume something disappeared or changed order and regenerate the model...
            self.recreateSuiteModel(suite, suiteIter)
            # If we're viewing a test that isn't there any more, view the suite instead!
            if self.rightWindowGUI.object.classId() == "test-case":
                viewedTest = self.rightWindowGUI.object
                if not os.path.isdir(viewedTest.abspath):
                    self.recreateTestView(suite)
        else:
            self.addNewTestToModel(suiteIter, maybeNewTest, suiteIter)
        self.selection.get_tree_view().grab_focus()
        
    def collapseIfAllComplete(self, iter):
        # Collapse if all child tests are complete and successful
        if iter == None or not self.model.iter_has_child(iter): 
            return

        successColor = self.model.get_value(iter, 2).getConfigValue("test_colours")["success"]
        nofChildren = 0
        childIters = []
        childIter = self.model.iter_children(iter)

        # Put all children in list to be treated
        while childIter != None:
            childIters.append(childIter)
            childIter = self.model.iter_next(childIter)

        while len(childIters) > 0:
            childIter = childIters[0]
            if (not self.model.iter_has_child(childIter)):
                nofChildren = nofChildren + 1
            childTest = self.model.get_value(childIter, 2)

            # If this iter has children, add these to the list to be treated
            if self.model.iter_has_child(childIter):                            
                subChildIter = self.model.iter_children(childIter)
                while subChildIter != None:
                    childIters.append(subChildIter)
                    subChildIter = self.model.iter_next(subChildIter)
            # For now, we determine if a test is complete by checking whether
            # it is colored in the success color rather than checking isComplete()
            # The reason is that checking isComplete() will sometimes collapse suites
            # before all tests have been colored by the GUI update function, which
            # doesn't look good.
            elif not self.model.get_value(childIter, 5) == successColor:
                return
            childIters = childIters[1:len(childIters)]

        # By now, we know that all tests were successful:
        # Print how many tests succeeded, color details column in success color,
        # collapse row, and try to collapse parent suite.
        guilog.info("All " + str(nofChildren) + " tests successful in suite " + repr(self.model.get_value(iter, 2)) + ", collapsing row.")
        self.model.set_value(iter, 4, "All " + str(nofChildren) + " tests successful")
        self.model.set_value(iter, 5, successColor) 
        self.selection.get_tree_view().collapse_row(self.model.get_path(iter))
        self.collapseIfAllComplete(self.model.iter_parent(iter))

    def addNewTestToModel(self, suite, newTest, suiteIter):
        iter = self.addSuiteWithParent(newTest, suiteIter)
        self.itermap[newTest] = iter.copy()
        guilog.info("Viewing new test " + newTest.name)
        self.recreateTestView(newTest)
        self.markAndExpand(iter)
    def markAndExpand(self, iter):
        self.selection.get_tree_view().expand_all()
        self.selection.unselect_all()
        self.selection.select_iter(iter)
    def recreateSuiteModel(self, suite, suiteIter):
        iter = self.model.iter_children(suiteIter)
        for i in range(self.model.iter_n_children(suiteIter)):
            self.model.remove(iter)
        for test in suite.testcases:
            iter = self.addSuiteWithParent(test, suiteIter)
        self.createSubIterMap(suiteIter, newTest=0)
        self.markAndExpand(suiteIter)
    def exit(self, *args):
        gtk.main_quit()
        sys.stdout.flush()
        if self.actionThread:
            self.actionThread.terminate()
        guiplugins.processTerminationMonitor.killAll()
    def quit(self, *args):
        # Generate a window closedown, so that the quit button behaves the same as closing the window
        self.topWindow.destroy()
        self.exit()
    def saveAll(self, *args):
        self.selection.select_all()
        self.saveSelected(args)
    def saveSelected(self, *args):
        saveActionFromWindow = self.rightWindowGUI.getSaveTestAction()
        windowVersion = None
        if saveActionFromWindow:
            windowVersion = saveActionFromWindow.test.app.getFullVersion()
            saveTestAction = saveActionFromWindow

        for test in self.itermap.keys():
            if not self.selection.iter_is_selected(self.itermap[test]):
                continue
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
                cmpAction = comparetest.MakeComparisons()
                if cmpAction.defaultComparisonClass:
                    guilog.info("Recalculating result info for test: result file changed since created")
                    # Not present for fast reconnect, don't crash...
                    cmpAction.setUpApplication(test.app)
                    cmpAction(test)
            self.rightWindowGUI = TestCaseGUI(test, self.dynamic)
        if self.contents:
            self.contents.pack_start(self.rightWindowGUI.getWindow(), expand=True, fill=True)
            self.contents.show()
    def makeButtons(self, list):
        buttonbox = gtk.HBox()
        for label, func in list:
            button = gtk.Button()
            button.set_use_underline(1)
            button.set_label(label)            
            scriptEngine.connect(label.replace("_", ""), "clicked", button, func)
            button.show()
            buttonbox.pack_start(button, expand=False, fill=False)
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
        vbox.pack_start(buttons, expand=False, fill=False)
        vbox.pack_start(fileWin, expand=True, fill=True)
        vbox.pack_start(notebook, expand=True, fill=True)
        fileWin.show()
        vbox.show()    
        return vbox
    def displayDifferences(self, view, path, column, *args):
        iter = self.model.get_iter(path)
        fileName = self.model.get_value(iter, 2)
        if not fileName:
            # Don't crash on double clicking the header lines...
            return
        comparison = self.model.get_value(iter, 3)
        try:
            self.fileViewAction.view(comparison, fileName)
        except plugins.TextTestError, e:
            showError(str(e))
    def addButton(self, method, buttonbox, label, scriptTitle, option):
        button = gtk.Button()
        button.set_use_underline(1)
        button.set_label(label)
        scriptEngine.connect(scriptTitle.replace("_", ""), "clicked", button, method, None, option)
        button.show()
        buttonbox.pack_start(button, expand=False, fill=False)
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
        vboxWindow = gtk.ScrolledWindow()
        vbox = gtk.VBox()
        for option in optionGroup.options.values():
            hbox = self.createOptionBox(option)
            vbox.pack_start(hbox, expand=False, fill=False)
        for switch in optionGroup.switches.values():
            hbox = self.createSwitchBox(switch)
            vbox.pack_start(hbox, expand=False, fill=False)
        vboxWindow.add_with_viewport(vbox)
        vbox.show()
        vboxWindow.show()
        return vboxWindow
    def createOptionBox(self, option):
        hbox = gtk.HBox()
        self.diagnoseOption(option)
        label = gtk.Label(option.name + "  ")
        hbox.pack_start(label, expand=False, fill=True)
        if len(option.possibleValues) > 1:
            combobox = gtk.Combo()
            entry = combobox.entry
            option.setPossibleValuesUpdateMethod(combobox.set_popdown_strings)
            hbox.pack_start(combobox, expand=True, fill=True)
            combobox.show()
        else:
            entry = gtk.Entry()
            entry.show()
            hbox.pack_start(entry, expand=True, fill=True)
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
                radioButton1.set_active(True)
            else:
                radioButton2.set_active(True)
            scriptEngine.registerToggleButton(radioButton1, "choose " + switch.name)
            scriptEngine.registerToggleButton(radioButton2, "choose " + switch.nameForOff)
            switch.setMethods(radioButton1.get_active, radioButton1.set_active)
            switch.resetMethod = radioButton2.set_active
            hbox = gtk.HBox()
            hbox.pack_start(radioButton1, expand=True, fill=True)
            hbox.pack_start(radioButton2, expand=True, fill=True)
            radioButton1.show()
            radioButton2.show()
            hbox.show()
            return hbox
        else:
            checkButton = gtk.CheckButton(switch.name)
            if switch.getValue():
                checkButton.set_active(True)
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
        if self.app.getConfigValue("auto_scroll_to_first_selected"):
            first = self.getFirstSelectedTest()
            if first != None:
                self.selection.get_tree_view().scroll_to_cell(first, None, True, 0.1)
        guilog.info("Marking " + str(len(self.getSelectedTests())) + " tests as selected")
    def getFirstSelectedTest(self):
        firstTest = []
        self.selection.selected_foreach(self.findFirstTest, firstTest)
        if len(firstTest) != 0:
            return firstTest[0]
        else:
            return None
    def findFirstTest(self, model, path, iter, firstTest, *args):
        if len(firstTest) == 0:
            firstTest.append(path)    
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
            try:
                self.addDynamicFilesToModel(self.test)
            except AttributeError:
                # The above code assumes we have failed on comparison: if not, don't display things
                pass
        else:
            self.addStaticFilesToModel(self.test)
    def createHeader(self, list, title):
        if len(list) > 0:
            iter = self.model.insert_before(None, None)
            self.model.set_value(iter, 0, title)
            return iter
    def addDynamicFilesToModel(self, test):
        self.testComparison = test.state
        if not test.state.isComplete():
            self.testComparison = comparetest.TestComparison(test.state, test.app)
            self.testComparison.makeComparisons(test, makeNew = 1)
        compiter = self.createHeader(self.testComparison.correctResults + self.testComparison.changedResults, "Comparison Files")
        newiter = self.createHeader(self.testComparison.newResults, "New Files")
        missingiter = self.createHeader(self.testComparison.missingResults, "Missing Files")
        diagComps = []
        hasNewDiags, hasOldDiags = 0, 0
        for fileComparison in self.testComparison.allResults:
            if fileComparison.isDiagnostic():
                if fileComparison.newResult():
                    hasNewDiags = 1
                else:
                    hasOldDiags = 1
                diagComps.append(fileComparison)
            else:
                self.addDynamicComparisonToModel(newiter, compiter, missingiter, fileComparison)

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
            self.addDynamicComparisonToModel(diagnewiter, diagcompiter, missingiter, diagComp)
    def addDynamicComparisonToModel(self, newiter, compiter, missingiter, fileComparison):
        if fileComparison.newResult():
            self.addDynamicFileToModel(newiter, fileComparison, self.getFailureColour())
        elif fileComparison.missingResult():
            self.addDynamicFileToModel(missingiter, fileComparison, self.getFailureColour())
        elif fileComparison.hasDifferences():
            self.addDynamicFileToModel(compiter, fileComparison, self.getFailureColour())
        else:
            self.addDynamicFileToModel(compiter, fileComparison, self.getSuccessColour())
    def addDynamicFileToModel(self, iter, comparison, colour):
        if comparison.missingResult():
            self.addFileToModel(iter, comparison.stdFile, comparison, colour)
        else:
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
    def getDataFileList(self, test):
        dataFileList = []
        filesToSearch = test.app.configObject.extraReadFiles(test).items()
        for name, filelist in filesToSearch:
            existingFileList = filter(lambda file: os.path.exists(file), filelist)
            if len(existingFileList) > 0:
                dataFileList.append((name, existingFileList))
        return dataFileList
    def addStaticDataFilesToModel(self, test):
        dataFileList = self.getDataFileList(test)
        if len(dataFileList) == 0:
            return
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
        if not test or test.classId() != "test-case":
            return ""
        return test.app.configObject.getTextualInfo(test)
    def performInteractiveAction(self, action):
        self.test.callAction(action)
    
# Class for importing self tests
class ImportTestCase(guiplugins.ImportTestCase):
    def addDefinitionFileOption(self, suite, oldOptionGroup):
        guiplugins.ImportTestCase.addDefinitionFileOption(self, suite, oldOptionGroup)
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
                              
