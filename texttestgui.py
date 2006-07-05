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
        # Generate a window closedown, so that the quit button behaves the same as closing the window
        self.exit()
    def getDoubleCheckMessage(self, test):
        processesToReport = self.processesToReport()
        runningProcesses = guiplugins.processTerminationMonitor.listRunning(processesToReport)
        if len(runningProcesses) == 0:
            return ""
        else:
            return "\nThese processes are still running, and will be terminated when quitting: \n\n   + " + string.join(runningProcesses, "\n   + ") + "\n\nQuit anyway?\n"
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

def getGtkRcFile():
    configDir = plugins.getPersonalConfigDir()
    if not configDir:
        return
    
    file = os.path.join(configDir, ".texttest_gtk")
    if os.path.isfile(file):
        return file

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
        self.selection = None
        self.selectionActionGUI = None
        self.contents = None
        self.totalNofTests = 0
        self.nofFailedSetupTests = 0
        self.progressMonitor = None
        self.toolTips = gtk.Tooltips()
        self.rootSuites = []
        self.status = GUIStatusMonitor()
    def readGtkRCFile(self):
        file = getGtkRcFile()
        if file:
            gtk.rc_add_default_file(file)
    def setUpScriptEngine(self):
        guiplugins.setUpGuiLog(self.dynamic)
        global guilog, scriptEngine
        from guiplugins import guilog
        scriptEngine = ScriptEngine(guilog, enableShortcuts=1)
        self.scriptEngine = scriptEngine
    def needsTestRuns(self):
        return self.dynamic
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
    def fillTopWindow(self, topWindow, testWins, rightWindow):
        mainWindow = self.createWindowContents(testWins, rightWindow)
        shortcutBar = scriptEngine.createShortcutBar()

        vbox = gtk.VBox()
        vbox.pack_start(self.selectionActionGUI.buttons, expand=False, fill=False)
                
        if self.dynamic:            
            progressBar = self.progressMonitor.createProgressBar()
            progressBar.show()
            vbox.pack_start(progressBar, expand=False, fill=True)

        vbox.pack_start(mainWindow, expand=True, fill=True)
        if shortcutBar:
            vbox.pack_start(shortcutBar, expand=False, fill=False)
            shortcutBar.show()
        vbox.pack_start(self.status.createStatusbar(), expand=False, fill=False)
        vbox.show()
        topWindow.add(vbox)
        topWindow.show()
        width = self.getWindowWidth()
        height = self.getWindowHeight()
        topWindow.resize(width, height)
        self.contents.set_position(int(self.contents.allocation.width / 2))
        self.rightWindowGUI.notifySizeChange(width, height)
    def getWindowHeight(self):
        defaultHeight = (gtk.gdk.screen_height() * 5) / 6
        height = defaultHeight

        for app in self.rootSuites:
            windowSizeOptions = app.getConfigValue("window_size")
            if not self.dynamic:
                if windowSizeOptions.has_key("static_height_pixels"):
                    height = int(windowSizeOptions["static_height_pixels"][0])
                if windowSizeOptions.has_key("static_height_screen"):
                    height = gtk.gdk.screen_height() * float(windowSizeOptions["static_height_screen"][0])
            else:
                if windowSizeOptions.has_key("dynamic_height_pixels"):
                    height = int(windowSizeOptions["dynamic_height_pixels"][0])
                if windowSizeOptions.has_key("dynamic_height_screen"):
                    height = gtk.gdk.screen_height() * float(windowSizeOptions["dynamic_height_screen"][0])                

        return int(height)
    def getWindowWidth(self):
        if self.dynamic:
            defaultWidth = gtk.gdk.screen_width() * 0.5
        else:
            defaultWidth = gtk.gdk.screen_width() * 0.6
        width = defaultWidth        

        for app in self.rootSuites:
            windowSizeOptions = app.getConfigValue("window_size")
            if not self.dynamic:
                if windowSizeOptions.has_key("static_width_pixels"):
                    width = int(windowSizeOptions["static_width_pixels"][0])
                if windowSizeOptions.has_key("static_width_screen"):
                    width = gtk.gdk.screen_width() * float(windowSizeOptions["static_width_screen"][0])
            else:
                if windowSizeOptions.has_key("dynamic_width_pixels"):
                    width = int(windowSizeOptions["dynamic_width_pixels"][0])
                if windowSizeOptions.has_key("dynamic_width_screen"):
                    width = gtk.gdk.screen_width() * float(windowSizeOptions["dynamic_width_screen"][0])                

        return int(width)
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
            storeIter = iter.copy()
            self.itermap[test] = storeIter
            self.selectionActionGUI.addNewTest(test, storeIter) 
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
            if suite.state.category == "unrunnable":
                self.nofFailedSetupTests += 1
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
    def createWindowContents(self, testWins, testCaseWin):
        self.contents = gtk.HPaned()
        self.contents.connect('notify', self.paneHasChanged)
        self.contents.pack1(testWins, resize=True)
        self.contents.pack2(testCaseWin, resize=True)
        self.contents.show()
        return self.contents
    def paneHasChanged(self, pane, gparamspec):
        pos = pane.get_position()
        size = pane.allocation.width
        self.toolTips.set_tip(pane, "Position: " + str(pos) + "/" + str(size) + " (" + str(100 * pos / size) + "% from the left edge)")
    def createSelectionActionGUI(self, topWindow, actionThread):
        actions = [ QuitGUI(self.rootSuites, self.dynamic, topWindow, actionThread) ]
        actions += guiplugins.interactiveActionHandler.getSelectionInstances(self.rootSuites, self.dynamic)
        return SelectionActionGUI(actions, self.selection, self.status)
    def createTestWindows(self, treeWindow):
        # Create a vertical box to hold the above stuff.
        vbox = gtk.VBox()
        vbox.pack_start(treeWindow, expand=True, fill=True)
        vbox.show()
        return vbox
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
        view.connect("row_expanded", self.expandFullSuite)
        # The order of these two is vital!
        scriptEngine.connect("select test", "row_activated", view, self.viewTest, modelIndexer)
        scriptEngine.monitor("set test selection to", self.selection, modelIndexer)
        view.show()

        # Create scrollbars around the view.
        scrolled = gtk.ScrolledWindow()
        scrolled.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        scrolled.add(view)
        framed = gtk.Frame()
        framed.set_shadow_type(gtk.SHADOW_IN)
        framed.add(scrolled)        
        framed.show_all()
        return framed
    def selectionChanged(self, selection):
        self.nofSelectedTests = 0
        self.selection.selected_foreach(self.countSelected)
        self.testsColumn.set_title("Tests: " + str(self.nofSelectedTests) + " selected")
        guilog.info(str(self.nofSelectedTests) + " tests selected")
    def countSelected(self, model, path, iter):
        if self.model.get_value(iter, 2).classId() == "test-case":
            self.nofSelectedTests = self.nofSelectedTests + 1
    def expandFullSuite(self, view, iter, path, *args):
        # Make sure expanding expands everything, better than just one level as default...
        view.expand_row(path, open_all=True)
    def setUpGui(self, actionThread=None):
        topWindow = self.createTopWindow()
        treeWindow = self.createTreeWindow()
        self.selectionActionGUI = self.createSelectionActionGUI(topWindow, actionThread)
        self.createIterMap()
        testWins = self.createTestWindows(treeWindow)

        # Must be created after addSuiteWithParents has counted all tests ...
        # (but before RightWindowGUI, as that wants in on progress)
        if self.dynamic:            
            self.progressMonitor = TestProgressMonitor(self.totalNofTests, self.nofFailedSetupTests, self.rootSuites, self.status, self.rootSuites[0].getConfigValue("test_colours"))

        self.rightWindowGUI = self.createDefaultRightGUI()
        self.fillTopWindow(topWindow, testWins, self.rightWindowGUI.getWindow())
        treeWindow.grab_focus() # To avoid the Quit button getting the initial focus, causing unwanted quit event
        self.checkGtkVersion()
    def checkGtkVersion(self):
        major, minor, debug = gtk.gtk_version
        if major < 2 or minor < 4:
            showError("DEPRECATION WARNING!!\nTextTest GUI support for PyGTK " + \
                      str(major) + "." + str(minor) + " is being phased out\nUse at least PyGTK 2.4 where possible")
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
        return RightWindowGUI(rootSuite, self.dynamic, self.selectionActionGUI, self.status, self.progressMonitor)
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
        # May have already closed down or not started yet, don't crash if so
        if not self.selection or not self.selection.get_tree_view():
            return

        if state:
            # Working around python bug 853411: main thread must do all forking
            state.notifyInMainThread()
        else:
            state = test.state

        self.notifyTreeView(test, state)
        self.rightWindowGUI.notifyChange(test)
        if self.progressMonitor:
            self.progressMonitor.notifyChange(test, state)
    def notifyTreeView(self, test, state):
        if test.classId() == "test-suite":
            return self.redrawSuite(test)

        if not self.dynamic:
            # In the static GUI there is nothing to update in the tree view window for test cases
            return
        self.redrawTest(test, state)
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
        testJustAdded = self.findTestJustAdded(suite)
        suiteIter = self.itermap[suite]
        if testJustAdded:
            self.addNewTestToModel(suiteIter, testJustAdded, suiteIter)
        else:
            # There wasn't a new test: assume something disappeared or changed order and regenerate the model...
            self.recreateSuiteModel(suite, suiteIter)
            self.rightWindowGUI.checkForDeletion()
        self.selection.get_tree_view().grab_focus()
    def findTestJustAdded(self, suite):
        if len(suite.testcases) == 0:
            return
        maybeNewTest = suite.testcases[-1]
        if not self.itermap.has_key(maybeNewTest):
            return maybeNewTest
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
        storeIter = iter.copy()
        self.itermap[newTest] = storeIter
        self.selectionActionGUI.addNewTest(newTest, storeIter)
        guilog.info("Viewing new test " + newTest.name)
        self.rightWindowGUI.view(newTest)
        self.expandSuite(suiteIter)
        self.selectOnlyRow(iter)
    def expandSuite(self, iter):
        self.selection.get_tree_view().expand_row(self.model.get_path(iter), open_all=0)
    def selectOnlyRow(self, iter):
        self.selection.unselect_all()
        self.selection.select_iter(iter)
    def recreateSuiteModel(self, suite, suiteIter):
        oldSize = self.model.iter_n_children(suiteIter)
        if oldSize == 0 and len(suite.testcases) == 0:
            return
        
        iter = self.model.iter_children(suiteIter)
        for i in range(oldSize):
            self.model.remove(iter)
        for test in suite.testcases:
            self.removeIter(test)
            iter = self.addSuiteWithParent(test, suiteIter)
        self.createSubIterMap(suiteIter, newTest=0)
        self.expandSuite(suiteIter)
        self.selectOnlyRow(suiteIter)
    def removeIter(self, test):
        del self.itermap[test]
        self.selectionActionGUI.removeTest(test)
    def viewTest(self, view, path, column, *args):
        iter = self.model.get_iter(path)
        self.selection.select_iter(iter)
        self.viewTestAtIter(iter)
    def viewTestAtIter(self, iter):
        test = self.model.get_value(iter, 2)
        guilog.info("Viewing test " + repr(test))
        if test.classId() == "test-case":
            self.checkUpToDate(test)
        self.rightWindowGUI.view(test)
    def checkUpToDate(self, test):
        if test.state.isComplete() and test.state.needsRecalculation():
            cmpAction = comparetest.MakeComparisons()
            if cmpAction.defaultComparisonClass:
                guilog.info("Recalculating result info for test: result file changed since created")
                # Not present for fast reconnect, don't crash...
                cmpAction.setUpApplication(test.app)
                cmpAction(test)
    
class InteractiveActionGUI:
    def __init__(self, actions, status, test = None):
        self.actions = actions
        self.test = test
        self.buttons = self.makeButtons()
        self.pageDescriptions = { "Test" : {} }
        self.indexers = [] # Utility list for getting the values from multi-valued radio button groups :-(
        self.status = status
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
        doubleCheckMessage = action.getDoubleCheckMessage(self.test)
        if doubleCheckMessage:
            self.dialog = DoubleCheckDialog(doubleCheckMessage, self._runInteractive, (action,))
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
        vbox.show()
        return vbox, displayDesc
    def createComboBox(self, option):
        if "ComboBoxEntry" in dir(gtk):
            # PyGTK 2.4 and above
            combobox = gtk.combo_box_entry_new_text()
            entry = combobox.child
            option.setPossibleValuesAppendMethod(combobox.append_text)
            return combobox, entry
        else:
            # PyGTK 2.0. Remove one day when we don't have to support RHEL3 any more.
            combobox = gtk.Combo()
            entry = combobox.entry
            option.setPossibleValuesUpdateMethod(combobox.set_popdown_strings)
            return combobox, entry
    def createOptionWidget(self, option):
        if len(option.possibleValues) > 1:
            return self.createComboBox(option)
        else:
            entry = gtk.Entry()
            return entry, entry
    def createOptionBox(self, option):
        hbox = gtk.HBox()
        label = gtk.Label(option.name + "  ")
        hbox.pack_start(label, expand=False, fill=True)
        widget, entry = self.createOptionWidget(option)
        hbox.pack_start(widget, expand=True, fill=True)
        widget.show()
        entry.set_text(option.getValue())
        scriptEngine.registerEntry(entry, "enter " + option.name + " =")
        option.setMethods(entry.get_text, entry.set_text)
        label.show()
        hbox.show()
        return hbox
    def createSwitchBox(self, switch):
        self.diagnoseSwitch(switch)
        if len(switch.options) >= 1:
            hbox = gtk.HBox()
            hbox.pack_start(gtk.Label(switch.name), expand=False, fill=False)
            count = 0
            buttons = []
            for option in switch.options:
                if count == 0:
                    firstRadioButton = gtk.RadioButton(None, option)
                    radioButton = firstRadioButton
                else:
                    radioButton = gtk.RadioButton(firstRadioButton, option)
                if count == switch.getValue():
                    radioButton.set_active(True)
                    switch.resetMethod = radioButton.set_active
                else:
                    radioButton.set_active(False)
                buttons.append(radioButton)
                scriptEngine.registerToggleButton(radioButton, "choose " + option)
                hbox.pack_start(radioButton, expand=True, fill=True)
                count = count + 1
            indexer = RadioGroupIndexer(buttons)
            self.indexers.append(indexer)
            switch.setMethods(indexer.getActiveIndex, indexer.setActiveIndex)
            hbox.show_all()
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
        if len(switch.options) >= 1:
            text = "Viewing radio button for switch '" + switch.name + "', options "
            for option in switch.options:
                text += option + "/"
            text = text[0:len(text) - 1] # Remove last '/'
            text += "'. Default value " + str(value) + "."
        else:
            text = "Viewing check button for switch '" + switch.name + "'"
            if value:
                text += " (checked)"
        return text
    def performInteractiveAction(self, action):
        message = action.messageAfterPerform(None, None, self.test)
        if message != None:
            self.status.output(message)
        self.test.callAction(action)
        message = action.messageAfterPerform(None, None, self.test)
        if message != None:
            self.status.output(message)

class SelectionActionGUI(InteractiveActionGUI):
    def __init__(self, actions, selection, status):
        InteractiveActionGUI.__init__(self, actions, status)
        self.selection = selection
        self.lastSelectionTests = []
        self.lastSelectionCmd = ""
        self.itermap = {}
    def addNewTest(self, test, iter):
        if not self.itermap.has_key(test.app):
            self.itermap[test.app] = {}
        self.itermap[test.app][test] = iter
    def removeTest(self, test):
        toRemove = self.itermap[test.app]
        del toRemove[test]
    def performInteractiveAction(self, action):
        selTests = self.getSelectedTests()
        selCmd = None
        # Selection with versions doesn't work from the command line right now, work around...
        if selTests == self.lastSelectionTests and self.lastSelectionCmd and self.lastSelectionCmd.find("-vs") == -1:
            selCmd = self.lastSelectionCmd

        self.status.output(action.messageBeforePerform(selTests, selCmd))
        returnVal = action.performOn(selTests, selCmd)
        if returnVal:
            # selection changed by action
            self.lastSelectionTests, self.lastSelectionCmd = returnVal
            self.selectInGUI()
            message = action.messageAfterPerform(self.lastSelectionTests, self.lastSelectionCmd)
            if message != None:
                self.status.output(message)
        elif not isinstance(action, QuitGUI):
            message = action.messageAfterPerform(selTests, selCmd)
            if message != None:
                self.status.output(message)
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
    def __init__(self, object, dynamic, selectionActionGUI, status, progressMonitor):
        self.dynamic = dynamic
        self.selectionActionGUI = selectionActionGUI
        self.progressMonitor = progressMonitor
        self.status = status
        self.window = gtk.VBox()
        self.vpaned = gtk.VPaned()
        self.vpaned.connect('notify', self.paneHasChanged)
        self.panedTooltips = gtk.Tooltips()
        self.topFrame = gtk.Frame()
        self.topFrame.set_shadow_type(gtk.SHADOW_IN)
        self.bottomFrame = gtk.Frame()
        self.bottomFrame.set_shadow_type(gtk.SHADOW_IN)
        self.vpaned.pack1(self.topFrame, resize=True)
        self.vpaned.pack2(self.bottomFrame, resize=True)
        self.currentObject = object
        buttonBar, fileView, objectPages = self.makeObjectDependentContents(object)
        self.diag = plugins.getDiagnostics("GUI notebook")
        self.notebook = self.createNotebook(objectPages, self.selectionActionGUI)
        self.oldObjectPageNames = self.makeDictionary(objectPages).keys()
        self.describeNotebook(self.notebook, pageNum=0)
        self.bottomFrame.add(self.notebook)
        self.fillWindow(buttonBar, fileView)
    def paneHasChanged(self, pane, gparamspec):
        pos = pane.get_position()
        size = pane.allocation.height
        self.panedTooltips.set_tip(pane, "Position: " + str(pos) + "/" + str(size) + " (" + str(100 * pos / size) + "% from the top)")
    def makeDictionary(self, objectPages):
        dict = seqdict()
        for page, name in objectPages:
            dict[name] = page
        return dict
    def notifySizeChange(self, width, height):
        self.vpaned.set_position(int(self.vpaned.allocation.height * 0.46))        
    def notifyChange(self, object):
        # Test has changed state, regenerate if we're currently viewing it
        if self.currentObject is object:
            self.view(object, resetNotebook=False)
    def view(self, object, resetNotebook=True):
        # Triggered by user double-clicking the test, called from notifyChange
        for child in self.window.get_children():
            if not child is self.notebook:
                self.window.remove(child)
        if not self.topFrame.get_child() is self.notebook:
            self.topFrame.remove(self.topFrame.get_child())
        if not self.bottomFrame.get_child() is self.notebook:
            self.bottomFrame.remove(self.bottomFrame.get_child())
        self.currentObject = object
        buttonBar, fileView, objectPages = self.makeObjectDependentContents(object)
        self.updateNotebook(objectPages, resetNotebook)
        self.fillWindow(buttonBar, fileView)
    def checkForDeletion(self):
        # If we're viewing a test that isn't there any more, view the suite (its parent) instead!
        if self.currentObject.classId() == "test-case":
            if not os.path.isdir(self.currentObject.getDirectory()):
                self.view(self.currentObject.parent)
    def makeObjectDependentContents(self, object):
        self.fileViewGUI = self.createFileViewGUI(object)
        buttonBar, objectPages = self.makeActionElements(object)
        fileView = self.fileViewGUI.createView()
        return buttonBar, fileView, objectPages
    def makeActionElements(self, object):
        self.intvActionGUI = InteractiveActionGUI(self.makeActionInstances(object), self.status, object)
        objectPages = self.getObjectNotebookPages(object, self.intvActionGUI)
        return self.intvActionGUI.buttons, objectPages    
    def fillWindow(self, buttonBar, fileView):
        self.window.pack_start(buttonBar, expand=False, fill=False)
        self.topFrame.add(fileView)
        self.window.pack_start(self.vpaned, expand=True, fill=True)
        self.vpaned.show_all()
        self.window.show_all()    
    def createFileViewGUI(self, object):
        if object.classId() == "test-app":
            return ApplicationFileGUI(object, self.dynamic)
        else:
            return TestFileGUI(object, self.dynamic)
    def describePageSwitch(self, notebook, pagePtr, pageNum, *args):
        self.describeNotebook(notebook, pageNum)
    def isVisible(self, notebook):
        if notebook is self.notebook:
            return True
        pageNum = self.notebook.get_current_page()
        page = self.notebook.get_nth_page(pageNum)
        return page is notebook
    def describeAllTabs(self, notebook):
        tabTexts = map(notebook.get_tab_label_text, notebook.get_children())
        guilog.info("")
        guilog.info("Tabs showing : " + string.join(tabTexts, ", "))
    def describeNotebook(self, notebook, pageNum=None):
        if not self.isVisible(notebook):
            return
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
        if page:
            return page, notebook.get_tab_label_text(page)
        else:
            return None, ""
    def getPageDescription(self, currentPageText, subPageText):
        if currentPageText == "Text Info" or subPageText == "Text Info":
            if len(self.testInfo):
                return "---------- Text Info Window ----------\n" + self.testInfo.strip() + "\n" + \
                       "--------------------------------------"
            else:
                return ""
        selectionDesc = self.selectionActionGUI.getPageDescription(currentPageText, subPageText)
        if selectionDesc:
            return selectionDesc
        else:
            return self.intvActionGUI.getPageDescription(currentPageText, subPageText)
    def getWindow(self):
        return self.window
    def makeActionInstances(self, object):
        # File view GUI also has a tab, provide that also...
        return [ self.fileViewGUI.fileViewAction ] + guiplugins.interactiveActionHandler.getInstances(object, self.dynamic)
    def createNotebook(self, objectPages, selectionActionGUI):
        pageDir = selectionActionGUI.createOptionGroupPages()
        pageDir["Test"] = objectPages + pageDir["Test"]
        if len(pageDir) == 1:
            pages = self.addScrollBars(pageDir["Test"])
        else:
            pages = []
            for groupTab, tabPages in pageDir.items():
                if len(tabPages) > 0:
                    scriptTitle = "view sub-options for " + groupTab + " :"
                    tabNotebook = scriptEngine.createNotebook(scriptTitle, self.addScrollBars(tabPages))
                    tabNotebook.show()
                    tabNotebook.connect("switch-page", self.describePageSwitch)
                    pages.append((tabNotebook, groupTab))
                
        notebook = scriptEngine.createNotebook("view options for", pages)
        notebook.connect("switch-page", self.describePageSwitch)
        notebook.show()
        return notebook
    def addScrollBars(self, pages):
        newPages = []
        for widget, name in pages:
            window = self.makeScrolledWindow(widget)
            newPages.append((window, name))
        return newPages
    def makeScrolledWindow(self, widget):
        window = gtk.ScrolledWindow()
        window.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.addToScrolledWindow(window, widget)
        window.show()
        return window
    def addToScrolledWindow(self, window, widget):
        if isinstance(widget, gtk.TextView) or isinstance(widget, gtk.Viewport):
            window.add(widget)
        elif isinstance(widget, gtk.VBox):
            # Nasty hack (!?) to avoid progress report (which is so far our only persistent widget) from having the previous window as a parent - remove this and watch TextTest crash when switching between Suite and Test views!
            #if widget.get_parent() != None:
            #    widget.get_parent().remove(widget)
            window.add_with_viewport(widget)
        else:
            raise plugins.TextTestError, "Could not decide how to add scrollbars to " + repr(widget)
    def findTestNotebook(self):
        page = self.findNotebookPage(self.notebook, "Test")
        if page:
            return page
        else:
            return self.notebook
    def findNotebookPage(self, notebook, name):
        for child in notebook.get_children():
            text = notebook.get_tab_label_text(child)
            if text == name:
                return child
    def findChanges(self, newList, oldList):
        created, updated, removed = [], [], []
        for item in newList:
            if item in oldList:
                updated.append(item)
            else:
                created.append(item)
        for item in oldList:
            if not item in newList:
                removed.append(item)
        return created, updated, removed
    def updateNotebook(self, newObjectPages, reset):
        notebook = self.findTestNotebook()
        newPageDir = self.makeDictionary(newObjectPages)
        newObjectPageNames = newPageDir.keys()
        self.diag.info("Updating notebook for " + repr(newObjectPageNames) + " from " + repr(self.oldObjectPageNames))
        currentPage, currentPageName = self.getPageText(notebook)
        pageNamesCreated, pageNamesUpdated, pageNamesRemoved = self.findChanges(newObjectPageNames, self.oldObjectPageNames)
        self.prependNewPages(notebook, pageNamesCreated, newPageDir)
        self.updatePages(notebook, pageNamesUpdated, newPageDir)
        # Must reset if we're viewing a removed page
        reset |= currentPageName in pageNamesRemoved
        # If Text Info is new, it's generally interesting, reset the notebook to view it
        reset |= "Text Info" in pageNamesCreated
        newCurrentPageNum = self.findNewCurrentPageNum(newObjectPageNames, pageNamesRemoved)
        if reset and notebook.get_current_page() != newCurrentPageNum:
            self.diag.info("Resetting for current page " + currentPageName)
            notebook.set_current_page(newCurrentPageNum)
            self.diag.info("Resetting done.")
        elif currentPageName in pageNamesUpdated:
            # describe the current page, we reloaded it...
            self.describeNotebook(notebook)
        self.removePages(notebook, pageNamesRemoved)
        if newObjectPageNames != self.oldObjectPageNames:
            self.oldObjectPageNames = newObjectPageNames
            self.describeAllTabs(notebook)
    def findNewCurrentPageNum(self, newPageNames, pageNamesRemoved):
        for index in range(len(newPageNames)):
            name = newPageNames[index]
            if not name in pageNamesRemoved:
                return index
        return 0
    def prependNewPages(self, notebook, pageNamesCreated, newPageDir):
        # Prepend the pages, hence in reverse order...
        pageNamesCreated.reverse()
        for name in pageNamesCreated:
            self.diag.info("Adding new page " + name)
            newPage = self.makeScrolledWindow(newPageDir[name])
            label = gtk.Label(name)
            notebook.prepend_page(newPage, label)
    def updatePages(self, notebook, pageNamesUpdated, newPageDir):
        for name in pageNamesUpdated:
            self.diag.info("Replacing contents of page " + name)
            # oldPage is a gtk.ScrolledWindow object, newPage either a gtk.VBox or a gtk.TextView
            oldPage = self.findNotebookPage(notebook, name)
            newContents = newPageDir[name]
            self.replaceContents(oldPage, newContents)
    def replaceContents(self, oldPage, newContents):
        oldContents = oldPage.get_child()
        if isinstance(oldContents, gtk.Viewport):
            oldPage = oldContents
            oldContents = oldContents.get_child()
        self.diag.info("Removing old contents " + repr(oldContents))
        oldPage.remove(oldContents)
        oldPage.add(newContents)
        oldPage.show()                
    def removePages(self, notebook, pageNamesRemoved):     
        for name in pageNamesRemoved:
            self.diag.info("Removing page " + name)
            oldPage = self.findNotebookPage(notebook, name)
            notebook.remove(oldPage)
    def getObjectNotebookPages(self, object, intvActionGUI):
        testCasePageDir = intvActionGUI.createOptionGroupPages()["Test"]
        self.testInfo = self.getTestInfo(object)
        if self.testInfo:
            textview = self.createTextView(self.testInfo)
            testCasePageDir = [(textview, "Text Info")] + testCasePageDir
        progressView = self.createProgressView()
        if progressView != None:
            testCasePageDir = [(progressView, "Progress")] + testCasePageDir
        return testCasePageDir
    def getTestInfo(self, test):
        if not test or test.classId() != "test-case":
            return ""
        return test.app.configObject.getTextualInfo(test)
    def createTextView(self, testInfo):
        textview = gtk.TextView()
        textview.set_wrap_mode(gtk.WRAP_WORD)
        textbuffer = textview.get_buffer()
        # Need to convert to utf-8 for display...
        unicodeInfo = unicode(testInfo, "utf-8", errors="replace")
        textbuffer.set_text(unicodeInfo.encode("utf-8"))
        textview.show()
        return textview
    def createProgressView(self):
        if self.progressMonitor != None:
            return self.progressMonitor.getProgressView()
        else:
            return None
        
class FileViewGUI:
    def __init__(self, object, dynamic):
        self.fileViewAction = guiplugins.interactiveActionHandler.getFileViewer(object, dynamic)
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_STRING,\
                                   gobject.TYPE_PYOBJECT, gobject.TYPE_STRING)
        self.name = object.name.replace("_", "__")
        self.dynamic = dynamic
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
    def createView(self):
        # blank line for demarcation
        guilog.info("")
        # defined in subclasses
        self.addFilesToModel()
        fileWin = gtk.ScrolledWindow()
        fileWin.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        view = gtk.TreeView(self.model)
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn(self.name, renderer, text=0, background=1)
        column.set_cell_data_func(renderer, renderParentsBold)
        view.append_column(column)
        if self.dynamic:
            perfColumn = gtk.TreeViewColumn("Details", renderer, text=4)
            view.append_column(perfColumn)
        view.expand_all()
        indexer = TreeModelIndexer(self.model, column, 0)
        scriptEngine.connect("select file", "row_activated", view, self.displayFile, indexer)
        view.show()
        fileWin.add(view)
        fileWin.show()
        return fileWin 
    def displayFile(self, view, path, column, *args):
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

class ApplicationFileGUI(FileViewGUI):
    def __init__(self, app, dynamic):
        FileViewGUI.__init__(self, app, dynamic)
        self.app = app
    def addFilesToModel(self):
        confiter = self.model.insert_before(None, None)
        self.model.set_value(confiter, 0, "Application Files")
        colour = self.app.getConfigValue("file_colours")["app_static"]
        for file in self.getConfigFiles():
            self.addFileToModel(confiter, file, None, colour)

        personalFiles = self.getPersonalFiles()
        if len(personalFiles) > 0:
            persiter = self.model.insert_before(None, None)
            self.model.set_value(persiter, 0, "Personal Files")
            for file in personalFiles:
                self.addFileToModel(persiter, file, None, colour)
    def getConfigFiles(self):
        configFiles = self.app.dircache.findAllFiles("config", [ self.app.name ])
        configFiles.sort()
        return configFiles
    def getPersonalFiles(self):
        personalFiles = []
        personalFile = self.app.getPersonalConfigFile()
        if personalFile:
            personalFiles.append(personalFile)
        gtkRcFile = getGtkRcFile()
        if gtkRcFile:
            personalFiles.append(gtkRcFile)
        return personalFiles
    
class TestFileGUI(FileViewGUI):
    def __init__(self, test, dynamic):
        FileViewGUI.__init__(self, test, dynamic)
        self.test = test
        self.colours = test.getConfigValue("file_colours")
        test.refreshFiles()
        self.testComparison = None
    def addFilesToModel(self):
        if self.test.state.hasStarted():
            try:
                self.addDynamicFilesToModel(self.test)
            except AttributeError:
                # The above code assumes we have failed on comparison: if not, don't display things
                pass
        else:
            self.addStaticFilesToModel(self.test)
    def addDynamicFilesToModel(self, test):
        self.testComparison = test.state
        if not test.state.isComplete():
            self.testComparison = comparetest.TestComparison(test.state, test.app)
            self.testComparison.makeComparisons(test, testInProgress=1)

        self.addDynamicComparisons(self.testComparison.correctResults + self.testComparison.changedResults, "Comparison Files")
        self.addDynamicComparisons(self.testComparison.newResults, "New Files")
        self.addDynamicComparisons(self.testComparison.missingResults, "Missing Files")
    def addDynamicComparisons(self, compList, title):
        if len(compList) == 0:
            return
        iter = self.model.insert_before(None, None)
        self.model.set_value(iter, 0, title)
        filelist = []
        fileCompMap = {}
        for comp in compList:
            file = comp.getDisplayFileName()
            fileCompMap[file] = comp
            filelist.append(file)
        filelist.sort()
        self.addStandardFilesUnderIter(iter, filelist, fileCompMap)
    def addStandardFilesUnderIter(self, iter, files, compMap = {}):
        for relDir, relDirFiles in self.classifyByRelDir(files).items():
            iterToUse = iter
            if relDir:
                iterToUse = self.addFileToModel(iter, relDir, None, self.getStaticColour())
            for file in relDirFiles:
                comparison = compMap.get(file)
                colour = self.getComparisonColour(comparison)
                self.addFileToModel(iterToUse, file, comparison, colour)
    def classifyByRelDir(self, files):
        dict = {}
        for file in files:
            relDir = self.getRelDir(file)
            if not dict.has_key(relDir):
                dict[relDir] = []
            dict[relDir].append(file)
        return dict
    def getRelDir(self, file):
        relPath = self.test.getTestRelPath(file)
        if relPath.find(os.sep) != -1:
            dir, local = os.path.split(relPath)
            return dir
        else:
            return ""
    def getComparisonColour(self, fileComp):
        if not fileComp:
            return self.getStaticColour()
        if not self.test.state.isComplete():
            return self.colours["running"]
        if fileComp.hasSucceeded():
            return self.colours["success"]
        else:
            return self.colours["failure"]
    def getStaticColour(self):
        if self.dynamic:
            return self.colours["not_started"]
        else:
            return self.colours["static"]
    def addStaticFilesToModel(self, test):
        stdFiles, defFiles = test.listStandardFiles(allVersions=True)
        if test.classId() == "test-case":
            stditer = self.model.insert_before(None, None)
            self.model.set_value(stditer, 0, "Standard Files")
            if len(stdFiles):
                self.addStandardFilesUnderIter(stditer, stdFiles)

        defiter = self.model.insert_before(None, None)
        self.model.set_value(defiter, 0, "Definition Files")
        self.addStandardFilesUnderIter(defiter, defFiles)
        self.addStaticDataFilesToModel(test)
    def getDisplayDataFiles(self, test):
        return test.app.configObject.extraReadFiles(test).items()
    def addStaticDataFilesToModel(self, test):
        dataFiles = test.listDataFiles()
        displayDataFiles = self.getDisplayDataFiles(test)
        if len(dataFiles) == 0 and len(displayDataFiles) == 0:
            return
        datiter = self.model.insert_before(None, None)
        self.model.set_value(datiter, 0, "Data Files")
        colour = self.getStaticColour()
        self.addDataFilesUnderIter(test, datiter, dataFiles, colour)
        for name, filelist in displayDataFiles:
            exiter = self.model.insert_before(datiter, None)
            self.model.set_value(exiter, 0, name)
            for file in filelist:
                self.addFileToModel(exiter, file, None, colour)
    def addDataFilesUnderIter(self, test, iter, files, colour):
        dirIters = { test.getDirectory() : iter }
        parentIter = iter
        for file in files:
            parent, local = os.path.split(file)
            parentIter = dirIters[parent]
            newiter = self.addFileToModel(parentIter, file, None, colour)
            if os.path.isdir(file):
                dirIters[file] = newiter
    
# Class for importing self tests
class ImportTestCase(guiplugins.ImportTestCase):
    def addDefinitionFileOption(self, suite, oldOptionGroup):
        guiplugins.ImportTestCase.addDefinitionFileOption(self, suite, oldOptionGroup)
        self.addSwitch(oldOptionGroup, "GUI", "Use TextTest GUI", 1)
        self.addSwitch(oldOptionGroup, "sGUI", "Use TextTest Static GUI", 0)
        targetApp = self.test.makePathName("TargetApp")
        root, local = os.path.split(targetApp)
        self.defaultTargetApp = plugins.samefile(root, self.test.app.getDirectory())
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

# A utility class to set and get the indices of options in radio button groups.
class RadioGroupIndexer:
    def __init__(self, listOfButtons):
        self.buttons = listOfButtons
    def getActiveIndex(self):
        for i in xrange(0, len(self.buttons)):
            if self.buttons[i].get_active():
                return i
    def setActiveIndex(self, index):
        self.buttons[index].set_active(True)
        
#
# A simple wrapper class around a gtk.StatusBar, simplifying
# logging messages/changing the status bar implementation.
# 
class GUIStatusMonitor:
    def __init__(self):
        self.statusBar = gtk.Statusbar()
        self.diag = plugins.getDiagnostics("GUI status monitor")
        self.output("TextTest started at " + plugins.localtime() + ".")

    def output(self, message):
        self.diag.info("Changing GUI status to: '" + message + "'")
        self.statusBar.push(0, message)
        
    def createStatusbar(self):
        self.statusBar.show()
        self.statusBarEventBox = gtk.EventBox()
        self.statusBarEventBox.add(self.statusBar)
        self.statusBarEventBox.show()
        return self.statusBarEventBox
                   

# Class that keeps track of (and possibly shows) the progress of
# pending/running/completed tests
class TestProgressMonitor:
    def __init__(self, totalNofTests, nofFailedSetupTests, applications, status, colors):
        # If we get here, we know that we want to show progress
        self.completedTests = {}
        self.testToIter = {}
        self.completionTime = ""
        self.totalNofTests = totalNofTests
        self.nofFailedSetupTests = nofFailedSetupTests
        self.nofCompletedTests = nofFailedSetupTests
        self.nofPendingTests = 0
        self.nofRunningTests = 0
        self.nofPerformanceDiffTests = 0
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
        self.nofDifferentPlusTests = 0
        self.nofMissingFilesTests = 0
        self.nofNewFilesTests = 0
        self.nofFailedTests = 0
        self.nofNoResultTests = 0
        self.nofKilledTests = 0
        self.nofUnreportedBugsTests = 0
        self.nofKnownBugsTests = 0
        
        self.status = status
        
        # Read custom error types from configuration
        self.customErrorTypes = {}
        self.customErrorMessages = {}
        self.customUnrunnableTypes = {}
        self.customUnrunnableMessages = {}
        self.customCrashTypes = {}
        self.customCrashMessages = {}
        showView = False
        for app in applications:
            testProgressOptions = app.getConfigValue("test_progress")
            if testProgressOptions.has_key("show") and testProgressOptions["show"][0] == "1":
                showView = True
            if testProgressOptions.has_key("custom_errors"):
                for t in testProgressOptions["custom_errors"]:
                    self.collectTypeAndMessage(t, self.customErrorTypes, self.customErrorMessages)
            if testProgressOptions.has_key("custom_unrunnable_errors"):
                for t in testProgressOptions["custom_unrunnable_errors"]:
                    self.collectTypeAndMessage(t, self.customUnrunnableTypes, self.customUnrunnableMessages)
            if testProgressOptions.has_key("custom_crash_errors"):
                for t in testProgressOptions["custom_crash_errors"]:
                    self.collectTypeAndMessage(t, self.customCrashTypes, self.customCrashMessages)

        self.colors = colors
        self.setupTreeView(showView)

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
        return self.progressBar   

    def adjustCount(self, count, increase):
        if increase:
            return count + 1
        else:
            return count - 1

    def analyzeFailure(self, category, test, increase = True):
        errorCaught = 0
        crashCaught = 0
        unrunnableCaught = 0
        diffCaught = 0
        if category[1].find("no results") != -1:
            self.nofNoResultTests = self.adjustCount(self.nofNoResultTests, increase)
            self.treeModel.set_value(self.noResultIter, 1, self.nofNoResultTests)
            self.testToIter[test] = self.noResultIter
            errorCaught = 1
            unrunnableCaught = 1
        if category[1].find("slower") != -1:
            self.nofPerformanceDiffTests = self.adjustCount(self.nofPerformanceDiffTests, increase)
            self.treeModel.set_value(self.performanceIter, 1, self.nofPerformanceDiffTests)
            self.nofSlowerTests = self.adjustCount(self.nofSlowerTests, increase)
            self.treeModel.set_value(self.slowerIter, 1, self.nofSlowerTests)
            self.testToIter[test] = self.slowerIter
            errorCaught = 1
        if category[1].find("faster") != -1:
            self.nofPerformanceDiffTests = self.adjustCount(self.nofPerformanceDiffTests, increase)
            self.treeModel.set_value(self.performanceIter, 1, self.nofPerformanceDiffTests)
            self.nofFasterTests = self.adjustCount(self.nofFasterTests, increase)
            self.treeModel.set_value(self.fasterIter, 1, self.nofFasterTests)
            self.testToIter[test] = self.fasterIter
            errorCaught = 1
        if category[1].find("smaller") != -1:
            self.nofPerformanceDiffTests = self.adjustCount(self.nofPerformanceDiffTests, increase)
            self.treeModel.set_value(self.performanceIter, 1, self.nofPerformanceDiffTests)
            self.nofSmallerTests = self.adjustCount(self.nofSmallerTests, increase)
            self.treeModel.set_value(self.smallerIter, 1, self.nofSmallerTests)
            self.testToIter[test] = self.smallerIter
            errorCaught = 1
        if category[1].find("larger") != -1:
            self.nofPerformanceDiffTests = self.adjustCount(self.nofPerformanceDiffTests, increase)
            self.treeModel.set_value(self.performanceIter, 1, self.nofPerformanceDiffTests)
            self.nofLargerTests = self.adjustCount(self.nofLargerTests, increase)                    
            self.treeModel.set_value(self.largerIter, 1, self.nofLargerTests)
            self.testToIter[test] = self.largerIter
            errorCaught = 1
        if category[1].find("new") != -1:
            self.nofNewFilesTests = self.adjustCount(self.nofNewFilesTests, increase)                    
            self.treeModel.set_value(self.newIter, 1, self.nofNewFilesTests)
            self.testToIter[test] = self.newIter
            errorCaught = 1
        if category[1].find("missing") != -1:
            self.nofMissingFilesTests = self.adjustCount(self.nofMissingFilesTests, increase)                    
            self.treeModel.set_value(self.missingIter, 1, self.nofMissingFilesTests)
            self.testToIter[test] = self.missingIter
            errorCaught = 1
        i = -1
        for (type, count) in self.customErrorTypes.items():
            i += 1
            if category[1].find(type) != -1:
                self.customErrorTypes[type] = self.adjustCount(self.customErrorTypes[type], increase)                    
                self.treeModel.set_value(self.customErrorIters[i], 1, self.customErrorTypes[type])
                self.testToIter[test] = self.customErrorIters[i]
                errorCaught = 1
        if category[1].find("different(+)") != -1:
            self.nofDifferentPlusTests = self.adjustCount(self.nofDifferentPlusTests, increase)                    
            self.treeModel.set_value(self.diffPlusIter, 1, self.nofDifferentPlusTests)
            self.testToIter[test] = self.diffPlusIter
            errorCaught = 1
        elif category[1].find("different") != -1:
            self.nofDifferentTests = self.adjustCount(self.nofDifferentTests, increase)                    
            self.treeModel.set_value(self.diffIter, 1, self.nofDifferentTests)
            self.testToIter[test] = self.diffIter
            errorCaught = 1
        if category[1].find("unreported bug") != -1:
            self.nofUnreportedBugsTests = self.adjustCount(self.nofUnreportedBugsTests, increase)                    
            self.treeModel.set_value(self.unreportedBugIter, 1, self.nofUnreportedBugTests)
            self.testToIter[test] = self.unreportedBugIter
            errorCaught = 1
        elif category[1].find("bug") != -1:
            self.nofKnownBugsTests = self.adjustCount(self.nofKnownBugsTests, increase) 
            self.treeModel.set_value(self.knownBugIter, 1, self.nofKnownBugsTests)
            self.testToIter[test] = self.knownBugIter
            errorCaught = 1
        if category[1].find("killed") != -1:
            self.nofKilledTests = self.adjustCount(self.nofKilledTests, increase)                    
            self.treeModel.set_value(self.killedIter, 1, self.nofKilledTests)
            self.testToIter[test] = self.killedIter
            errorCaught = 1
            unrunnableCaught = 1
        if category[0] == "crash":
            self.nofCrashedTests = self.adjustCount(self.nofCrashedTests, increase)
            self.treeModel.set_value(self.crashedIter, 1, self.nofCrashedTests)
            errorCaught = 1
            i = -1
            for (type, count) in self.customCrashTypes.items():
                i += 1
                if category[1].find(type) != -1:
                    self.customCrashTypes[type] = self.adjustCount(self.customCrashTypes[type], increase)    
                    self.treeModel.set_value(self.customCrashIters[i], 1, self.customCrashTypes[type])
                    self.testToIter[test] = self.customCrashIters[i]
                    errorCaught = 1
                    crashCaught = 1
            if crashCaught == 0:
                self.testToIter[test] = self.crashedIter
        if category[0] == "unrunnable":
            self.nofUnrunnableTests = self.adjustCount(self.nofUnrunnableTests, increase)            
            self.treeModel.set_value(self.unrunnableIter, 1, self.nofUnrunnableTests)
            errorCaught = 1
            i = -1
            for (type, count) in self.customUnrunnableTypes.items():
                i += 1
                if category[1].find(type) != -1:
                    self.customUnrunnableTypes[type] = self.adjustCount(self.customUnrunnableTypes[type], increase)
                    self.treeModel.set_value(self.customUnrunnableIters[i], 1, self.customUnrunnableTypes[type])
                    self.testToIter[test] = self.customUnrunnableIters[i]
                    errorCaught = 1
                    unrunnableCaught = 1
            if unrunnableCaught == 0:
                self.testToIter[test] = self.unrunnableIter
          
        self.nofFailedTests = self.adjustCount(self.nofFailedTests, increase)
        self.treeModel.set_value(self.failedIter, 1, self.nofFailedTests)
        if errorCaught == 0:
            self.testToIter[test] = self.failedIter
        
    def setupTreeView(self, showView):
        # Each row has 'type', 'number', 'show'
        self.treeModel = gtk.TreeStore(str, int, int)
        self.pendIter    = self.treeModel.append(None, ["Pending", 0, 1])
        self.runIter     = self.treeModel.append(None, ["Running", 0, 1])
        self.successIter = self.treeModel.append(None, ["Succeeded", 0, 1])
        self.setupIter   = self.treeModel.append(None, ["Failed in setup", self.nofFailedSetupTests, 1])
        self.failedIter  = self.treeModel.append(None, ["Failed", 0, 1])
        self.performanceIter = self.treeModel.append(self.failedIter, ["Performance differences", 0, 1])
        self.fasterIter  = self.treeModel.append(self.performanceIter, ["Faster", 0, 1])
        self.slowerIter  = self.treeModel.append(self.performanceIter, ["Slower", 0, 1])
        self.smallerIter = self.treeModel.append(self.performanceIter, ["Less memory", 0, 1])
        self.largerIter  = self.treeModel.append(self.performanceIter, ["More memory", 0, 1])

        # Custom errors
        self.customErrorIters = []
        for (type, count) in self.customErrorTypes.items():
            self.customErrorIters.append(self.treeModel.append(self.failedIter, [self.customErrorMessages[type], 0, 1]))
            
        self.diffIter        = self.treeModel.append(self.failedIter, ["One different file", 0, 1])
        self.diffPlusIter    = self.treeModel.append(self.failedIter, ["Multiple different files", 0, 1])
        self.missingIter     = self.treeModel.append(self.failedIter, ["Missed file(s)", 0, 1])
        self.newIter         = self.treeModel.append(self.failedIter, ["New file(s)", 0, 1])
        self.knownBugIter    = self.treeModel.append(self.failedIter, ["Known bug", 0, 1])
        self.unreportedIter  = self.treeModel.append(self.failedIter, ["Unreported bug", 0, 1])
        self.crashedIter     = self.treeModel.append(self.failedIter, ["Crashed", 0, 1])

        # Custom crashes
        self.customCrashIters = []
        for (type, count) in self.customCrashTypes.items():
            self.customCrashIters.append(self.treeModel.append(self.crashedIter, [self.customCrashMessages[type], 0, 1]))
                                         
        self.unrunnableIter  = self.treeModel.append(self.failedIter, ["Unrunnable", 0, 1])

        # Custom unrunnables
        self.customUnrunnableIters = []
        for (type, count) in self.customUnrunnableTypes.items():
            self.customUnrunnableIters.append(self.treeModel.append(self.crashedIter, [self.customUnrunnableMessages[type], 0, 1]))
            
        self.noResultIter    = self.treeModel.append(self.unrunnableIter, ["No result", 0, 1])
        self.killedIter      = self.treeModel.append(self.unrunnableIter, ["Killed", 0, 1])

        self.treeView = gtk.TreeView(self.treeModel)
        self.treeView.get_selection().set_mode(gtk.SELECTION_NONE)
        textRenderer = gtk.CellRendererText()
        statusColumn = gtk.TreeViewColumn("Status", textRenderer, text=0)
        numberColumn = gtk.TreeViewColumn("Number", textRenderer, text=1)
        statusColumn.set_cell_data_func(textRenderer, self.renderPositive)
        numberColumn.set_cell_data_func(textRenderer, self.renderPositive)
        self.treeView.append_column(statusColumn)
        self.treeView.append_column(numberColumn)
        toggle = gtk.CellRendererToggle()
        toggle.set_active(False) # For now, disable toggling
        if gtk.pygtk_version[0] >= 2 and gtk.pygtk_version[1] >= 6: # This probably looks nicer ...
            toggle.set_property('sensitive', False)
        #toggle.set_property('activatable', True)
        #toggle.connect('toggled', self.showToggled)
        #self.treeView.append_column(gtk.TreeViewColumn("Show", toggle, active=2)) # Don't show this column until the checkboxes are clickable.
        self.treeView.expand_all()

        if showView:
            self.progressReport = gtk.VBox()
            self.progressReport.pack_start(self.treeView, expand=False, fill=True)
            self.progressReport.show_all()
        else:
            self.progressReport = None
        
    def notifyChange(self, test, state):
        if state.isComplete():
            if self.completedTests.has_key(test):
                # First decrease counts from last time ...
                self.analyzeFailure(self.completedTests[test], test, False)
                # ... then set new category.
                self.completedTests[test] = state.getTypeBreakdown()
            else:
                self.nofCompletedTests += 1
                self.nofRunningTests -= 1
                self.completedTests[test] = state.getTypeBreakdown()
        elif state.hasStarted():
            self.nofRunningTests += 1
            self.nofPendingTests -= 1
            self.testToIter[test] = self.runIter
        elif state.category == "pending":
            self.nofPendingTests += 1
            self.testToIter[test] = self.pendIter

        if state.hasSucceeded():
            self.nofSuccessfulTests += 1
            self.testToIter[test] = self.successIter
        if state.hasFailed():
            self.analyzeFailure(state.getTypeBreakdown(), test, True)

        if self.nofPendingTests < 0:
            self.nofPendingTests = 0
        if self.nofRunningTests < 0:
            self.nofRunningTests = 0

        self.treeModel.set_value(self.pendIter, 1, self.nofPendingTests)
        self.treeModel.set_value(self.runIter, 1, self.nofRunningTests)
        self.treeModel.set_value(self.successIter, 1, self.nofSuccessfulTests)

        if self.nofCompletedTests >= self.totalNofTests:
            if self.completionTime == "":
                self.completionTime = plugins.localtime()
            if self.nofFailedTests != 0:
                self.progressBar.set_text("All " + str(self.totalNofTests) + " tests completed at " + self.completionTime + " (" + str(self.nofFailedTests) + " tests failed)")
            else:
                self.progressBar.set_text("All " + str(self.totalNofTests) + " tests completed at " + self.completionTime)
            self.progressBar.set_fraction(1.0)
        else:
            if self.nofFailedTests != 0:
                self.progressBar.set_text(str(self.nofCompletedTests) + " of " + str(self.totalNofTests) + " tests completed (" + str(self.nofFailedTests) + " tests failed)")
            else:
                self.progressBar.set_text(str(self.nofCompletedTests) + " of " + str(self.totalNofTests) + " tests completed")
            self.progressBar.set_fraction(float(self.nofCompletedTests) / float(self.totalNofTests))
            
        if self.progressReport != None:
            self.diagnoseTree()

        # Output the tree in textual format
    def diagnoseTree(self):
        guilog.info("Test progress:")
        childIters = []
        childIter = self.treeModel.get_iter_root()

        # Put all children in list to be treated
        while childIter != None:
            childIters.append(childIter)
            childIter = self.treeModel.iter_next(childIter)

        while len(childIters) > 0:
            childIter = childIters[0]
            # If this iter has children, add these to the list to be treated
            if self.treeModel.iter_has_child(childIter):                            
                subChildIter = self.treeModel.iter_children(childIter)
                pos = 1
                while subChildIter != None:
                    childIters.insert(pos, subChildIter)
                    pos = pos + 1
                    subChildIter = self.treeModel.iter_next(subChildIter)
            # Print the iter
            guilog.info("  " + self.treeModel.get_value(childIter, 0) + " : " + str(self.treeModel.get_value(childIter, 1)))
            childIters = childIters[1:len(childIters)]

    def showRow(self, model, iter):
        test = model.get_value(iter, 2)        
        if test.classId() == "test-suite":
            return True
        elif test.classId() == "test-case":
            # In what category (iter) does the test get caught?
            if self.testToIter.has_key(test):
                statusIter = self.testToIter[test]
                # Is column 2 checked?
                if self.treeModel.get_value(statusIter, 2) == 1:
                    return True
                else:
                    return False
            else:
                return True
        else:
            return True
    
    def renderPositive(self, column, cell, model, iter):
        if model.get_value(iter, 1) > 0:
            cell.set_property('font', 'bold')
            if model.get_value(iter, 0) == "Succeeded":
                cell.set_property('background', self.colors["success"])
            elif model.get_value(iter, 0) == "Pending":
                cell.set_property('background', self.colors["pending"])
            elif model.get_value(iter, 0) == "Running":
                cell.set_property('background', self.colors["running"])
            else:
                cell.set_property('background', self.colors["failure"])                
        else:
            cell.set_property('font', '')
            cell.set_property('background', 'white')

    def showToggled(self, cell, path):
        self.treeModel[path][2] = not self.treeModel[path][2]
        childIters = []
        childIter = self.treeModel.iter_children(self.treeModel.get_iter_from_string(path))

        # Put all children in list to be treated
        while childIter != None:
            childIters.append(childIter)
            childIter = self.treeModel.iter_next(childIter)

        while len(childIters) > 0:
            childIter = childIters[0]

            # If this iter has children, add these to the list to be treated
            if self.treeModel.iter_has_child(childIter):                            
                subChildIter = self.treeModel.iter_children(childIter)
                while subChildIter != None:
                    childIters.append(subChildIter)
                    subChildIter = self.treeModel.iter_next(subChildIter)

            self.treeModel.set_value(childIter, 2, self.treeModel[path][2])
            childIters = childIters[1:len(childIters)]

    def getProgressView(self):
       return self.progressReport
