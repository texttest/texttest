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

class DoubleCheckDialog:
    def __init__(self, message, yesMethod, yesMethodArgs=()):        
        self.dialog = gtk.Dialog("TextTest Query", flags=gtk.DIALOG_MODAL)
        self.yesMethod = yesMethod
        self.yesMethodArgs = yesMethodArgs
        guilog.info("QUERY : " + message)
        noButton = self.dialog.add_button(gtk.STOCK_NO, gtk.RESPONSE_NO)
        yesButton = self.dialog.add_button(gtk.STOCK_YES, gtk.RESPONSE_YES)
        self.dialog.set_modal(True)
        label = gtk.Label(message)
        self.dialog.vbox.pack_start(label, expand=True, fill=True)
        label.show()
        # ScriptEngine cannot handle different signals for the same event (e.g. response
        # from gtk.Dialog), so we connect the individual buttons instead ...
        scriptEngine.connect("answer no to texttest query", "clicked", noButton, self.respond, gtk.RESPONSE_NO, False)
        scriptEngine.connect("answer yes to texttest query", "clicked", yesButton, self.respond, gtk.RESPONSE_YES, True)
        self.dialog.show()
    def respond(self, button, saidYes, *args):
        if saidYes:
            self.yesMethod(*self.yesMethodArgs)
        self.dialog.destroy()

def renderParentsBold(column, cell, model, iter):
    if model.iter_has_child(iter):
        cell.set_property('font', "bold")
    else:
        cell.set_property('font', "")

class QuitGUI(guiplugins.SelectionAction):
    def __init__(self, rootSuites, dynamic, topWindow, actionThread):
        guiplugins.SelectionAction.__init__(self, rootSuites)
        self.dynamic = dynamic
        self.topWindow = topWindow
        self.actionThread = actionThread
        scriptEngine.connect("close window", "delete_event", topWindow, self.exit)
    def getTitle(self):
        return "_Quit"
    def performOn(self, tests, selCmd):
        processesToReport = self.processesToReport()
        runningProcesses = guiplugins.processTerminationMonitor.listRunning(processesToReport)
        if len(runningProcesses) == 0:
            # Generate a window closedown, so that the quit button behaves the same as closing the window
            self.exit()
        else:
            message = "\nThese processes are still running, and will be terminated when quitting: \n\n   + " + string.join(runningProcesses, "\n   + ") + "\n\nQuit anyway?\n"
            self.dialog = DoubleCheckDialog(message, self.exit)
    def processesToReport(self):
        queryValues = self.getConfigValue("query_kill_processes")
        processes = []
        if queryValues.has_key("default"):
            processes += queryValues["default"]
        if self.dynamic and queryValues.has_key("dynamic"):
            processes += queryValues["dynamic"]
        elif queryValues.has_key("static"):        
            processes += queryValues["static"]
        return processes
    def exit(self, *args):
        self.topWindow.destroy()
        gtk.main_quit()
        sys.stdout.flush()
        if self.actionThread:
            self.actionThread.terminate()
        guiplugins.processTerminationMonitor.killAll()    

class TextTestGUI(ThreadedResponder):
    def __init__(self, optionMap):
        self.readGtkRCFile()
        self.dynamic = not optionMap.has_key("gx")
        ThreadedResponder.__init__(self, optionMap)
        guiplugins.scriptEngine = self.scriptEngine
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT,\
                                   gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_STRING)
        self.itermap = seqdict()
        self.rightWindowGUI = None
        self.selectionActionGUI = None
        self.contents = None
        self.totalNofTests = 0
        self.progressMonitor = None
        self.rootSuites = []
    def readGtkRCFile(self):
        configDir = plugins.getPersonalConfigDir()
        if not configDir:
            return

        file = os.path.join(configDir, ".texttest_gtk")
        if os.path.isfile(file):
            gtk.rc_add_default_file(file)
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
            win.set_title("TextTest static GUI : management of tests for " + self.getAppNames())
            
        guilog.info("Top Window title set to " + win.get_title())
        return win
    def getAppNames(self):
        names = []
        for suite in self.rootSuites:
            if not suite.app.fullName in names:
                names.append(suite.app.fullName)
        return string.join(names, ",")
    def fillTopWindow(self, topWindow, testWins):
        mainWindow = self.createWindowContents(testWins)
        shortcutBar = scriptEngine.createShortcutBar()

        vbox = gtk.VBox()
        vbox.pack_start(self.selectionActionGUI.buttons, expand=False, fill=False)
                
        # Should we monitor progress? Must be checked after
        # addSuiteWithParents has counted all tests ...
        if self.dynamic:
            for app in self.rootSuites:
                testProgressOptions = app.getConfigValue("test_progress")
                if testProgressOptions.has_key("show") and testProgressOptions["show"][0] == "1":
                    self.progressMonitor = TestProgressMonitor(self.totalNofTests, self.rootSuites)
                    progressBar = self.progressMonitor.createProgressBar()
                    progressBar.show()
                    vbox.pack_start(progressBar, expand=False, fill=True)
                    break

        vbox.pack_start(mainWindow, expand=True, fill=True)
        if shortcutBar:
            vbox.pack_start(shortcutBar, expand=False, fill=False)
            shortcutBar.show()
        vbox.show()
        topWindow.add(vbox)
        topWindow.show()
        topWindow.resize(self.getWindowWidth(), self.getWindowHeight())
    def getWindowHeight(self):
        return (gtk.gdk.screen_height() * 5) / 6
    def getWindowWidth(self):
        return gtk.gdk.screen_width() / 2
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
        self.rootSuites.append(suite)
        if suite.app.getConfigValue("add_shortcut_bar"):
            scriptEngine.enableShortcuts = 1
        if not self.dynamic:
            self.addApplication(suite.app)
        if not self.dynamic or suite.size() > 0:
            self.addSuiteWithParent(suite, None)
    def addSuiteWithParent(self, suite, parent):
        if suite.classId() == "test-case":
            self.totalNofTests += 1        
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
    def createSelectionActionGUI(self, topWindow, actionThread):
        actions = [ QuitGUI(self.rootSuites, self.dynamic, topWindow, actionThread) ]
        actions += guiplugins.interactiveActionHandler.getSelectionInstances(self.rootSuites, self.dynamic)
        return SelectionActionGUI(actions, self.selection, self.itermap)
    def createTestWindows(self, treeWindow):
        # Create a vertical box to hold the above stuff.
        vbox = gtk.VBox()
        vbox.pack_start(treeWindow, expand=True, fill=True)
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
        testRenderer = gtk.CellRendererText()
        self.testsColumn = gtk.TreeViewColumn("Tests: 0 selected", testRenderer, text=0, background=1)
        self.testsColumn.set_cell_data_func(testRenderer, renderParentsBold)
        view.append_column(self.testsColumn)
        if self.dynamic:
            detailsRenderer = gtk.CellRendererText()
            perfColumn = gtk.TreeViewColumn("Details", detailsRenderer, text=4, background=5)
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
    def setUpGui(self, actionThread=None):
        self.createIterMap()
        topWindow = self.createTopWindow()
        treeWindow = self.createTreeWindow()
        self.selectionActionGUI = self.createSelectionActionGUI(topWindow, actionThread) 
        testWins = self.createTestWindows(treeWindow)
        self.createDefaultRightGUI()
        self.fillTopWindow(topWindow, testWins)
    def runWithActionThread(self, actionThread):
        self.setUpGui(actionThread)
        idle_add(self.pickUpChange)
        gtk.main()
    def runAlone(self):
        self.setUpGui()
        idle_add(self.pickUpProcess)
        gtk.main()
    def createDefaultRightGUI(self):
        rootSuite = self.rootSuites[0]
        guilog.info("Viewing test " + repr(rootSuite))
        self.recreateTestView(rootSuite)
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

        if self.progressMonitor != None and test.classId() == "test-case":
            self.progressMonitor.update(test, state)
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
            self.rightWindowGUI = ApplicationGUI(test, self.selectionActionGUI)
        else:
            if checkUpToDate and test.state.isComplete() and test.state.needsRecalculation():
                cmpAction = comparetest.MakeComparisons()
                if cmpAction.defaultComparisonClass:
                    guilog.info("Recalculating result info for test: result file changed since created")
                    # Not present for fast reconnect, don't crash...
                    cmpAction.setUpApplication(test.app)
                    cmpAction(test)
            self.rightWindowGUI = TestCaseGUI(test, self.dynamic, self.selectionActionGUI)
        if self.contents:
            self.contents.pack_start(self.rightWindowGUI.getWindow(), expand=True, fill=True)
            self.contents.show()

class InteractiveActionGUI:
    def __init__(self, actions, test = None):
        self.actions = actions
        self.test = test
        self.buttons = self.makeButtons()
        self.pageDescriptions = { "Test" : {} }
    def makeButtons(self):
        executeButtons = gtk.HBox()
        buttonInstances = filter(lambda instance : instance.inToolBar(), self.actions)
        for instance in buttonInstances:
            button = self.createButton(self.runInteractive, instance.getTitle(), instance.getScriptTitle(tab=False), instance)
            executeButtons.pack_start(button, expand=False, fill=False)
        if len(buttonInstances) > 0:
            buttonTitles = map(lambda b: b.getTitle(), buttonInstances)
            guilog.info("Creating tool bar with buttons : " + string.join(buttonTitles, ", "))
        executeButtons.show()
        return executeButtons
    def createButton(self, method, label, scriptTitle, option):
        button = gtk.Button(label)
        scriptEngine.connect(scriptTitle.replace("_", ""), "clicked", button, method, None, option)
        button.show()
        return button
    def runInteractive(self, button, action, *args):
        message = "This action can remove a lot of data. Are you sure you wish to proceed?"
        if action.performDoubleCheck():
            self.dialog = DoubleCheckDialog(message, self._runInteractive, (action,))
        else:
            self._runInteractive(action)
    def _runInteractive(self, action):
        try:
            self.performInteractiveAction(action)
        except plugins.TextTestError, e:
            showError(str(e))
    def getPageDescription(self, pageName, subPageName = ""):
        if subPageName:
            return self.pageDescriptions.get(pageName).get(subPageName)
        else:
            return self.pageDescriptions.get("Test").get(pageName)
    def createOptionGroupPages(self):
        pages = seqdict()
        pages["Test"] = []
        for instance in self.actions:
            instanceTab = instance.getGroupTabTitle()
            optionGroups = instance.getOptionGroups()
            hasButton = len(optionGroups) == 1 and instance.canPerform()
            for optionGroup in optionGroups:
                if optionGroup.switches or optionGroup.options:
                    display, displayDesc = self.createDisplay(optionGroup, hasButton, instance)
                    pageDesc = "Viewing notebook page for '" + optionGroup.name + "'\n" + displayDesc
                    if not pages.has_key(instanceTab):
                        pages[instanceTab] = []
                        self.pageDescriptions[instanceTab] = {}
                    self.pageDescriptions[instanceTab][optionGroup.name] = pageDesc
                    pages[instanceTab].append((display, optionGroup.name))
        return pages
    def createDisplay(self, optionGroup, hasButton, instance):
        vboxWindow = gtk.ScrolledWindow()
        vbox = gtk.VBox()
        displayDesc = ""
        for option in optionGroup.options.values():
            hbox = self.createOptionBox(option)
            displayDesc += self.diagnoseOption(option) + "\n"
            vbox.pack_start(hbox, expand=False, fill=False)
        for switch in optionGroup.switches.values():
            hbox = self.createSwitchBox(switch)
            displayDesc += self.diagnoseSwitch(switch) + "\n"
            vbox.pack_start(hbox, expand=False, fill=False)
        if hasButton:
            button = self.createButton(self.runInteractive, instance.getSecondaryTitle(), instance.getScriptTitle(tab=True), instance)
            buttonbox = gtk.HBox()
            buttonbox.pack_start(button, expand=True, fill=False)
            buttonbox.show()
            vbox.pack_start(buttonbox, expand=False, fill=False, padding=8)
            displayDesc += "Viewing button with title '" + instance.getTitle() + "'"
        vboxWindow.add_with_viewport(vbox)
        vbox.show()
        vboxWindow.show()
        return vboxWindow, displayDesc
    def createOptionBox(self, option):
        hbox = gtk.HBox()
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
    def diagnoseOption(self, option):
        value = option.getValue()
        text = "Viewing entry for option '" + option.name + "'"
        if len(value) > 0:
            text += " (set to '" + value + "')"
        if len(option.possibleValues) > 1:
            text += " (drop-down list containing " + repr(option.possibleValues) + ")"
        return text
    def diagnoseSwitch(self, switch):
        value = switch.getValue()
        if switch.nameForOff:
            text = "Viewing radio button for switch '" + switch.name + "/" + switch.nameForOff + "'"
        else:
            text = "Viewing check button for switch '" + switch.name + "'"
        if value:
            text += " (checked)"
        return text
    def performInteractiveAction(self, action):
        self.test.callAction(action)

class SelectionActionGUI(InteractiveActionGUI):
    def __init__(self, actions, selection, itermap):
        InteractiveActionGUI.__init__(self, actions)
        self.selection = selection
        self.lastSelectionTests = []
        self.lastSelectionCmd = ""
        self.itermap = {}
        for test, iter in itermap.items():
            if not self.itermap.has_key(test.app):
                self.itermap[test.app] = {}
            self.itermap[test.app][test] = iter
    def performInteractiveAction(self, action):
        selTests = self.getSelectedTests()
        selCmd = None
        # Selection with versions doesn't work from the command line right now, work around...
        if selTests == self.lastSelectionTests and self.lastSelectionCmd and self.lastSelectionCmd.find("-vs") == -1:
            selCmd = self.lastSelectionCmd
        returnVal = action.performOn(selTests, selCmd)
        if returnVal:
            # selection changed by action
            self.lastSelectionTests, self.lastSelectionCmd = returnVal
            self.selectInGUI()
    def getSelectedTests(self):
        tests = []
        self.selection.selected_foreach(self.addSelTest, tests)
        return tests
    def addSelTest(self, model, path, iter, tests, *args):
        tests.append(model.get_value(iter, 2))
    def selectInGUI(self):
        self.selection.unselect_all()
        for test in self.lastSelectionTests:
            iter = self.itermap[test.app][test]
            self.selection.select_iter(iter)
        self.selection.get_tree_view().grab_focus()
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

class RightWindowGUI:
    def __init__(self, object, dynamic, selectionActionGUI):
        self.object = object
        self.dynamic = dynamic
        self.fileViewAction = guiplugins.interactiveActionHandler.getInstance(object, guiplugins.ViewFile)
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT, gobject.TYPE_STRING)
        self.addFilesToModel()
        view = self.createView()
        hardcodedPages = self.getHardcodedNotebookPages()
        self.intvActionGUI = InteractiveActionGUI(self.makeActionInstances(), object)
        self.selectionActionGUI = selectionActionGUI
        self.notebook = self.createNotebook(hardcodedPages, selectionActionGUI)
        self.describeNotebook(self.notebook, None, 0)
        self.window = self.createWindow(view, self.notebook)
    def describeNotebook(self, notebook, pagePtr, pageNum, *args):
        outerPageNum, innerPageNum = self.getPageNumbers(notebook, pageNum)
        currentPage, currentPageText = self.getPageText(self.notebook, outerPageNum)
        subPageText = ""
        if isinstance(currentPage, gtk.Notebook):
            subPage, subPageText = self.getPageText(currentPage, innerPageNum)
        pageDesc = self.getPageDescription(currentPageText, subPageText)
        if pageDesc:
            guilog.info("")
            guilog.info(pageDesc)
        # Can get here viewing text info window ...
    def getPageNumbers(self, notebook, pageNum):
        if notebook is self.notebook:
            return pageNum, None
        else:
            return None, pageNum
    def getPageText(self, notebook, pageNum = None):
        if pageNum is None:
            pageNum = notebook.get_current_page()
        page = notebook.get_nth_page(pageNum)
        return page, notebook.get_tab_label_text(page)
    def getPageDescription(self, currentPageText, subPageText):
        selectionDesc = self.selectionActionGUI.getPageDescription(currentPageText, subPageText)
        if selectionDesc:
            return selectionDesc
        else:
            return self.intvActionGUI.getPageDescription(currentPageText, subPageText)
    def getWindow(self):
        return self.window
    def createView(self):
        view = gtk.TreeView(self.model)
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn(self.object.name.replace("_", "__"), renderer, text=0, background=1)
        column.set_cell_data_func(renderer, renderParentsBold)
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
    def createNotebook(self, hardcodedPages, selectionActionGUI):
        testCasePageDir = self.intvActionGUI.createOptionGroupPages()
        pageDir = selectionActionGUI.createOptionGroupPages()
        pageDir["Test"] = hardcodedPages + testCasePageDir["Test"] + pageDir["Test"]
        if len(pageDir) == 1:
            pages = pageDir["Test"]
        else:
            pages = []
            for groupTab, tabPages in pageDir.items():
                if len(tabPages) > 0:
                    tabNotebook = scriptEngine.createNotebook("view sub-options for " + groupTab + " :", tabPages)
                    tabNotebook.show()
                    tabNotebook.connect("switch-page", self.describeNotebook)
                    pages.append((tabNotebook, groupTab))
                
        notebook = scriptEngine.createNotebook("view options for", pages)
        notebook.connect("switch-page", self.describeNotebook)
        notebook.show()
        return notebook
    def getHardcodedNotebookPages(self):
        return []
    def createWindow(self, view, notebook):
        fileWin = gtk.ScrolledWindow()
        fileWin.add(view)
        vbox = gtk.VBox()
        vbox.pack_start(self.intvActionGUI.buttons, expand=False, fill=False)
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
    
class ApplicationGUI(RightWindowGUI):
    def __init__(self, app, selectionActionGUI):
        self.app = app
        RightWindowGUI.__init__(self, app, 1, selectionActionGUI)
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
    
class TestCaseGUI(RightWindowGUI):
    def __init__(self, test, dynamic, selectionActionGUI):
        self.test = test
        self.colours = test.getConfigValue("file_colours")
        RightWindowGUI.__init__(self, test, dynamic, selectionActionGUI)
        self.testComparison = None
    def getHardcodedNotebookPages(self):
        testInfo = self.getTestInfo(self.test)
        if testInfo:
            textview = self.createTextView(testInfo)
            return [(textview, "Text Info")]
        else:
            return []
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
    def getTestInfo(self, test):
        if not test or test.classId() != "test-case":
            return ""
        return test.app.configObject.getTextualInfo(test)
    def createTextView(self, testInfo):
        textViewWindow = gtk.ScrolledWindow()
        textview = gtk.TextView()
        textview.set_wrap_mode(gtk.WRAP_WORD)
        textbuffer = textview.get_buffer()
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

# Class that keeps track of (and possibly shows) the progress of
# pending/running/completed tests
class TestProgressMonitor:
    def __init__(self, totalNofTests, applications):
        # If we get here, we know that we want to show progress
        self.completedTests = {}
        self.totalNofTests = totalNofTests
        self.nofCompletedTests = 0
        self.nofPendingTests = 0
        self.nofRunningTests = 0
        self.nofSuccessfulTests = 0
        self.nofFasterTests = 0
        self.nofSlowerTests = 0
        self.nofSmallerTests = 0
        self.nofLargerTests = 0
        self.nofUnrunnableTests = 0
        self.nofCrashedTests = 0
        self.nofBetterTests = 0
        self.nofWorseTests = 0
        self.nofDifferentTests = 0
        self.nofMissingFilesTests = 0
        self.nofNewFilesTests = 0
        self.nofFailedTests = 0
        self.nofNoResultTests = 0
        self.nofKilledTests = 0
        self.nofUnreportedBugsTests = 0
        self.nofKnownBugsTests = 0
        
        # Where we print the progress report
        self.tooltips = gtk.Tooltips()
        
        # Read custom error types from configuration
        self.customErrorTypes = {}
        self.customErrorMessages = {}
        self.customUnrunnableTypes = {}
        self.customUnrunnableMessages = {}
        self.customCrashTypes = {}
        self.customCrashMessages = {}
        for app in applications:
            testProgressOptions = app.getConfigValue("test_progress")
            if testProgressOptions.has_key("custom_errors"):
                for t in testProgressOptions["custom_errors"]:
                    self.collectTypeAndMessage(t, self.customErrorTypes, self.customErrorMessages)
            if testProgressOptions.has_key("custom_unrunnable_errors"):
                for t in testProgressOptions["custom_unrunnable_errors"]:
                    self.collectTypeAndMessage(t, self.customUnrunnableTypes, self.customUnrunnableMessages)
            if testProgressOptions.has_key("custom_crash_errors"):
                for t in testProgressOptions["custom_crash_errors"]:
                    self.collectTypeAndMessage(t, self.customCrashTypes, self.customCrashMessages)

    def collectTypeAndMessage(self, typeAndMessage, types, messages):
        # typeAndMessage _might_ be of the form 'type{message}', or
        # of the form 'type'. In the former case insert 0 in types
        # and 'message' in messages. In the latter case, insert 0 in types
        # and 'type' in messages.
        t = typeAndMessage.strip("}").split("{")
        types[t[0]] = 0
        if len(t) > 1:
            messages[t[0]] = t[1]
        else:
            messages[t[0]] = t[0]        
    def createProgressBar(self):
        self.progressBar = gtk.ProgressBar()
        self.progressBar.set_text("No tests completed")
        self.progressBar.show()
        self.progressBarEventBox = gtk.EventBox()
        self.progressBarEventBox.add(self.progressBar)
        self.tooltips.set_tip(self.progressBarEventBox, "Nothing has happened.")
        return self.progressBarEventBox
            
    def adjustCount(self, count, increase):
        if increase:
            return count + 1
        else:
            return count - 1

    def analyzeFailure(self, category, increase = True):
        if category[1].find("no results") != -1:
            self.nofNoResultTests = self.adjustCount(self.nofNoResultTests, increase)                 
        if category[1].find("slower") != -1:
            self.nofSlowerTests = self.adjustCount(self.nofSlowerTests, increase)
        if category[1].find("faster") != -1:
            self.nofFasterTests = self.adjustCount(self.nofFasterTests, increase)
        if category[1].find("smaller") != -1:
            self.nofSmallerTests = self.adjustCount(self.nofSmallerTests, increase)
        if category[1].find("larger") != -1:
            self.nofLargerTests = self.adjustCount(self.nofLargerTests, increase)                    
        if category[1].find("new") != -1:
            self.nofNewFilesTests = self.adjustCount(self.nofNewFilesTests, increase)                    
        if category[1].find("missing") != -1:
            self.nofMissingFilesTests = self.adjustCount(self.nofMissingFilesTests, increase)                    
        for (type, count) in self.customErrorTypes.items():
            if category[1].find(type) != -1:
                self.customErrorTypes[type] = self.adjustCount(self.customErrorTypes[type], increase)                    
        if category[1].find("different") != -1:
            self.nofDifferentTests = self.adjustCount(self.nofDifferentTests, increase)                    
        if category[1].find("unreported bug") != -1:
            self.nofUnreportedBugsTests = self.adjustCount(self.nofUnreportedBugsTests, increase)                    
        elif category[1].find(" bug") != -1:
            self.nofKnownBugsTests = self.adjustCount(self.nofKnownBugsTests, increase) 
        if category[1].find("killed") != -1:
            self.nofKilledTests = self.adjustCount(self.nofKilledTests, increase)                    
        if category[0] == "crash":
            self.nofCrashedTests = self.adjustCount(self.nofCrashedTests, increase)
            for (type, count) in self.customCrashTypes.items():
                if category[1].find(type) != -1:
                    self.customCrashTypes[type] = self.adjustCount(self.customCrashTypes[type], increase)    
        if category[0] == "unrunnable":
            self.nofUnrunnableTests = self.adjustCount(self.nofUnrunnableTests, increase)            
            for (type, count) in self.customUnrunnableTypes.items():
                if category[1].find(type) != -1:
                    self.customUnrunnableTypes[type] = self.adjustCount(self.customUnrunnableTypes[type], increase)                    
        self.nofFailedTests = self.adjustCount(self.nofFailedTests, increase)

    def getReport(self):
        indentation = 5
        extraIndentation = 9
        extraExtraIndentation = 13
        if self.nofCompletedTests >= self.totalNofTests:
            summary = "Test summary:           \n" 
        else:
            summary = "Test progress:           \n"        
            summary += "%s are pending\n" % plugins.adjustText(str(self.nofPendingTests), indentation, "right")
            summary += "%s are running\n" % plugins.adjustText(str(self.nofRunningTests), indentation, "right")
        summary += "%s were successful\n" % plugins.adjustText(str(self.nofSuccessfulTests), indentation, "right")
        summary += "%s failed:\n" % plugins.adjustText(str(self.nofFailedTests), indentation, "right")
        summary += "%s were faster\n" % plugins.adjustText(str(self.nofFasterTests), extraIndentation, "right")
        summary += "%s were slower\n" % plugins.adjustText(str(self.nofSlowerTests), extraIndentation, "right")
        summary += "%s used less memory\n" % plugins.adjustText(str(self.nofSmallerTests), extraIndentation, "right")
        summary += "%s used more memory\n" % plugins.adjustText(str(self.nofLargerTests), extraIndentation, "right")
        # Put the custom error types here, before the different count
        for (type, count) in self.customErrorTypes.items():
            summary += "%s %s\n" % (plugins.adjustText(str(count), extraIndentation, "right"), self.customErrorMessages[type])
        summary += "%s produced different result\n" % plugins.adjustText(str(self.nofDifferentTests), extraIndentation, "right")
        summary += "%s were missing file(s)\n" % plugins.adjustText(str(self.nofMissingFilesTests), extraIndentation, "right")
        summary += "%s produced new file(s)\n" % plugins.adjustText(str(self.nofNewFilesTests), extraIndentation, "right")
        summary += "%s encountered a known bug\n" % plugins.adjustText(str(self.nofKnownBugsTests), extraIndentation, "right")
        summary += "%s encountered an unreported bug\n" % plugins.adjustText(str(self.nofUnreportedBugsTests), extraIndentation, "right")

        summary += "%s crashed:\n" % plugins.adjustText(str(self.nofCrashedTests), extraIndentation, "right")
        for (type, count) in self.customCrashTypes.items():
            summary += "%s %s\n" % (plugins.adjustText(str(count), extraExtraIndentation, "right"), self.customCrashMessages[type])

        summary += "%s were unrunnable:\n" % plugins.adjustText(str(self.nofUnrunnableTests), extraIndentation, "right")
        # Put the custom error types here, before the unrunnable count
        for (type, count) in self.customUnrunnableTypes.items():
            summary += "%s %s\n" % (plugins.adjustText(str(count), extraExtraIndentation, "right"), self.customUnrunnableMessages[type])
        summary += "%s produced no result\n" % plugins.adjustText(str(self.nofNoResultTests), extraExtraIndentation, "right")
        summary += "%s were killed" % plugins.adjustText(str(self.nofKilledTests), extraExtraIndentation, "right")

        return summary

    def update(self, test, state):
        if state.isComplete():
            if self.completedTests.has_key(test):
                # First decrease counts from last time ...
                self.analyzeFailure(self.completedTests[test], False)
                # ... then set new category.
                self.completedTests[test] = state.getTypeBreakdown()
            else:
                self.nofCompletedTests += 1
                self.nofRunningTests -= 1
                self.completedTests[test] = state.getTypeBreakdown()
        elif state.hasStarted():
            self.nofRunningTests += 1
            self.nofPendingTests -= 1
        elif state.category == "pending":
            self.nofPendingTests += 1

        if state.hasSucceeded():
            self.nofSuccessfulTests += 1
        if state.hasFailed():
            self.analyzeFailure(state.getTypeBreakdown(), True)

        if self.nofPendingTests < 0:
            self.nofPendingTests = 0
        if self.nofRunningTests < 0:
            self.nofRunningTests = 0
            
        if self.nofCompletedTests >= self.totalNofTests:
            self.progressBar.set_text("All " + str(self.totalNofTests) + " tests completed")
            self.progressBar.set_fraction(1.0)
        else:
            self.progressBar.set_text(str(self.nofCompletedTests) + " of " + str(self.totalNofTests) + " tests completed")
            self.progressBar.set_fraction(float(self.nofCompletedTests) / float(self.totalNofTests))

        report = self.getReport()
        if self.nofRunningTests == 0 and self.nofPendingTests == 0:
            guilog.info(report)
        self.tooltips.set_tip(self.progressBarEventBox, report)        
