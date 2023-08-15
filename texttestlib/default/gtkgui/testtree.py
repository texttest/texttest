
"""
Code associated with the left-hand tree view for tests 
"""
from gi.repository import Gtk, GObject, Pango
from . import guiutils
import logging
from texttestlib import plugins
from collections import OrderedDict


class TestColumnGUI(guiutils.SubGUI):
    def __init__(self, dynamic, testCount):
        guiutils.SubGUI.__init__(self)
        self.addedCount = 0
        self.totalNofTests = testCount
        self.totalNofDistinctTests = testCount
        self.nofSelectedTests = 0
        self.nofDistinctSelectedTests = 0
        self.totalNofTestsShown = 0
        self.versionString = ""
        self.column = None
        self.dynamic = dynamic
        self.testSuiteSelection = False
        self.diag = logging.getLogger("Test Column GUI")
        self.allSuites = []

    def addSuites(self, suites):
        self.allSuites = suites

    def createView(self):
        testRenderer = Gtk.CellRendererText()
        self.column = Gtk.TreeViewColumn(self.getTitle(), testRenderer, text=0, background=1, foreground=7)
        self.column.name = "Test Name"  # Not a widget, so we can't set a name, do this instead
        self.column.set_resizable(True)
        self.column.set_cell_data_func(testRenderer, self.renderSuitesBold)
        if not self.dynamic:
            self.column.set_clickable(True)
            self.column.connect("clicked", self.columnClicked)
        if guiutils.guiConfig.getValue("auto_sort_test_suites") == 1:
            self.column.set_sort_indicator(True)
            self.column.set_sort_order(Gtk.SortType.ASCENDING)
        elif guiutils.guiConfig.getValue("auto_sort_test_suites") == -1:
            self.column.set_sort_indicator(True)
            self.column.set_sort_order(Gtk.SortType.DESCENDING)
        return self.column

    def renderSuitesBold(self, dummy, cell, model, iter, data):
        if model.get_value(iter, 2)[0].classId() == "test-case":
            cell.set_property('font', "")
        else:
            cell.set_property('font', "bold")

    def columnClicked(self, *args):
        if not self.column.get_sort_indicator():
            self.column.set_sort_indicator(True)
            self.column.set_sort_order(Gtk.SortType.ASCENDING)
            order = 1
        else:
            order = self.column.get_sort_order()
            if order == Gtk.SortType.ASCENDING:
                self.column.set_sort_order(Gtk.SortType.DESCENDING)
                order = -1
            else:
                self.column.set_sort_indicator(False)
                order = 0

        self.notify("ActionStart")
        self.setSortingOrder(order)
        if order == 1:
            self.notify("Status", "Tests sorted in alphabetical order.")
        elif order == -1:
            self.notify("Status", "Tests sorted in descending alphabetical order.")
        else:
            self.notify("Status", "Tests sorted according to testsuite file.")
        self.notify("RefreshTestSelection")
        self.notify("ActionStop")

    def setSortingOrder(self, order, suite=None):
        if not suite:
            for suite in self.allSuites:
                self.setSortingOrder(order, suite)
        else:
            self.notify("Status", "Sorting suite " + suite.name + " ...")
            self.notify("ActionProgress")
            suite.autoSortOrder = order
            suite.updateOrder()
            for test in suite.testcases:
                if test.classId() == "test-suite":
                    self.setSortingOrder(order, test)

    def getTitle(self):
        title = "Tests: "
        if self.versionString and len(self.versionString) > 40:
            reducedVersionString = self.versionString[:40] + "..."
        else:
            reducedVersionString = self.versionString

        if self.testSuiteSelection:
            # We don't care about totals with test suites
            title += plugins.pluralise(self.nofSelectedTests, "suite") + " selected"
            if self.versionString:
                title += ", " + reducedVersionString
            elif self.nofDistinctSelectedTests != self.nofSelectedTests:
                title += ", " + str(self.nofDistinctSelectedTests) + " distinct"
            return title

        if self.nofSelectedTests == self.totalNofTests:
            title += "All " + str(self.totalNofTests) + " selected"
        else:
            title += str(self.nofSelectedTests) + "/" + str(self.totalNofTests) + " selected"

        if not self.dynamic:
            if self.versionString:
                title += ", " + reducedVersionString
            elif self.totalNofDistinctTests != self.totalNofTests:
                if self.nofDistinctSelectedTests == self.totalNofDistinctTests:
                    title += ", all " + str(self.totalNofDistinctTests) + " distinct"
                else:
                    title += ", " + str(self.nofDistinctSelectedTests) + "/" + \
                        str(self.totalNofDistinctTests) + " distinct"

        if self.totalNofTestsShown == self.totalNofTests:
            if self.dynamic and self.totalNofTests > 0:
                title += ", none hidden"
        elif self.totalNofTestsShown == 0:
            title += ", all hidden"
        else:
            title += ", " + str(self.totalNofTests - self.totalNofTestsShown) + " hidden"

        return title

    def updateTitle(self, initial=False):
        if self.column:
            self.column.set_title(self.getTitle())

    def notifyTestTreeCounters(self, totalDelta, totalShownDelta, totalRowsDelta, initial=False):
        self.addedCount += totalDelta
        if not initial or self.totalNofTests < self.addedCount:
            self.totalNofTests += totalDelta
            self.totalNofDistinctTests += totalRowsDelta
        self.totalNofTestsShown += totalShownDelta
        self.updateTitle(initial)

    def notifyAllRead(self):
        if self.addedCount != self.totalNofTests:
            self.totalNofTests = self.addedCount
            self.updateTitle()

    def countTests(self, tests):
        if self.dynamic:
            return len(tests), False

        testCount, suiteCount = 0, 0
        for test in tests:
            if test.classId() == "test-case":
                testCount += 1
            else:
                suiteCount += 1
        if suiteCount and not testCount:
            return suiteCount, True
        else:
            return testCount, False

    def getVersionString(self, tests, distinctTestCount):
        if not self.dynamic and distinctTestCount == 1 and self.totalNofTests != self.totalNofDistinctTests:
            versions = [test.app.getFullVersion().replace("_", "__") or "<default>" for test in tests]
            return "version" + ("s" if len(versions) > 1 else "") + " " + ",".join(versions)
        else:
            return ""

    def notifyNewTestSelection(self, tests, dummyApps, distinctTestCount, *args, **kw):
        if self.dynamic:
            tests = [t for t in tests if t.classId() == "test-case"]
        self.updateTestInfo(tests, distinctTestCount)

    def updateTestInfo(self, tests, distinctTestCount):
        newCount, suitesOnly = self.countTests(tests)
        if distinctTestCount > newCount:
            distinctTestCount = newCount
        newVersionStr = self.getVersionString(tests, distinctTestCount)
        if self.nofSelectedTests != newCount or newVersionStr != self.versionString or \
                self.nofDistinctSelectedTests != distinctTestCount or suitesOnly != self.testSuiteSelection:
            self.diag.info("New selection count = " + repr(newCount) + ", distinct = " +
                           str(distinctTestCount) + ", test suites only = " + repr(suitesOnly))
            self.nofSelectedTests = newCount
            self.nofDistinctSelectedTests = distinctTestCount
            self.testSuiteSelection = suitesOnly
            self.versionString = newVersionStr
            self.updateTitle()

    def notifyVisibility(self, tests, newValue):
        testCount = sum((int(test.classId() == "test-case") for test in tests))
        if newValue:
            self.totalNofTestsShown += testCount
        else:
            self.totalNofTestsShown -= testCount
        self.updateTitle()


class TestIteratorMap:
    def __init__(self, dynamic, allApps):
        self.dict = OrderedDict()
        self.dynamic = dynamic
        self.parentApps = {}
        for app in allApps:
            for extra in [app] + app.extras:
                self.parentApps[extra] = app

    def getKey(self, test):
        if self.dynamic:
            return test
        elif test is not None:
            return self.parentApps.get(test.app, test.app), test.getRelPath()

    def store(self, test, iter):
        self.dict[self.getKey(test)] = iter

    def updateIterator(self, test, oldRelPath):
        # relative path of test has changed
        key = self.parentApps.get(test.app, test.app), oldRelPath
        iter = self.dict.get(key)
        if iter is not None:
            self.store(test, iter)
            del self.dict[key]
            return iter
        else:
            return self.getIterator(test)

    def getIterator(self, test):
        return self.dict.get(self.getKey(test))

    def remove(self, test):
        key = self.getKey(test)
        if key in self.dict:
            del self.dict[key]


class TestTreeGUI(guiutils.ContainerGUI):
    def __init__(self, dynamic, allApps, popupGUI, subGUI):
        guiutils.ContainerGUI.__init__(self, [subGUI])
        self.model = Gtk.TreeStore(GObject.TYPE_STRING, GObject.TYPE_STRING, GObject.TYPE_PYOBJECT,
                                   GObject.TYPE_STRING, GObject.TYPE_STRING, GObject.TYPE_BOOLEAN,
                                   GObject.TYPE_STRING, GObject.TYPE_STRING)
        self.popupGUI = popupGUI
        self.itermap = TestIteratorMap(dynamic, allApps)
        self.selection = None
        self.selecting = False
        self.selectedTests = []
        self.clipboardTests = set()
        self.dynamic = dynamic
        self.collapseStatic = 100 if dynamic else guiutils.guiConfig.getValue("static_collapse_suites")
        self.filteredModel = None
        self.treeView = None
        self.newTestsVisible = guiutils.guiConfig.showCategoryByDefault("not_started")
        self.diag = logging.getLogger("Test Tree")
        self.longActionRunning = False
        self.recreateOnActionStop = False
        self.testSuitesWithResults = set()

    def notifyDefaultVisibility(self, newValue):
        self.newTestsVisible = newValue

    def isExpanded(self, iter):
        parentIter = self.filteredModel.iter_parent(iter)
        return not parentIter or self.treeView.row_expanded(self.filteredModel.get_path(parentIter))

    def notifyAllRead(self, *args):
        if not self.dynamic:
            self.newTestsVisible = True
            self.model.foreach(self.makeRowVisible)
            if self.collapseStatic != -1:
                self.expandLevel(self.treeView, self.filteredModel.get_iter_first(), self.collapseStatic)
            else:
                self.treeView.expand_all()
        self.notify("AllRead")

    def makeRowVisible(self, model, dummyPath, iter):
        model.set_value(iter, 5, True)

    def getNodeName(self, suite, parent):
        nodeName = suite.name
        if parent == None:
            appName = suite.app.name + suite.app.versionSuffix()
            if appName != nodeName:
                nodeName += " (" + appName + ")"
        return nodeName

    def addSuiteWithParent(self, suite, parent, follower=None):
        nodeName = self.getNodeName(suite, parent)
        self.diag.info("Adding node with name " + nodeName)
        colour = guiutils.guiConfig.getTestColour("not_started")
        row = [nodeName, colour, [suite], "", colour, self.newTestsVisible, "", None]
        iter = self.model.insert_before(parent, follower, row)
        storeIter = iter.copy()
        self.itermap.store(suite, storeIter)
        path = self.model.get_path(iter)
        if self.newTestsVisible and parent is not None:
            filterPath = self.filteredModel.convert_child_path_to_path(path)
            self.treeView.expand_to_path(filterPath)
        return iter

    def createView(self):
        self.filteredModel = self.model.filter_new()
        self.filteredModel.set_visible_column(5)
        self.treeView = Gtk.TreeView(self.filteredModel)
        self.treeView.set_search_column(0)
        self.treeView.set_name("Test Tree")
        self.treeView.expand_all()

        self.selection = self.treeView.get_selection()
        self.selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        if self.dynamic:
            self.selection.set_select_function(self.canSelect, self)

        testsColumn = self.subguis[0].createView()
        self.treeView.append_column(testsColumn)
        if self.dynamic:
            detailsRenderer = Gtk.CellRendererText()
            detailsRenderer.set_property('wrap-width', 350)
            detailsRenderer.set_property('wrap-mode', Pango.WrapMode.WORD_CHAR)
            recalcRenderer = Gtk.CellRendererPixbuf()
            detailsColumn = Gtk.TreeViewColumn("Details")
            detailsColumn.pack_start(detailsRenderer, True)
            detailsColumn.pack_start(recalcRenderer, False)
            detailsColumn.add_attribute(detailsRenderer, 'text', 3)
            detailsColumn.add_attribute(detailsRenderer, 'background', 4)
            detailsColumn.add_attribute(recalcRenderer, 'stock_id', 6)
            detailsColumn.set_resizable(True)
            guiutils.addRefreshTips(self.treeView, "test", recalcRenderer, detailsColumn, 6)
            self.treeView.append_column(detailsColumn)

        self.treeView.connect('row-expanded', self.rowExpanded)
        self.expandLevel(self.treeView, self.filteredModel.get_iter_first())
        self.treeView.connect("button_press_event", self.popupGUI.showMenu)
        self.selection.connect("changed", self.userChangedSelection)

        self.treeView.show()

        self.popupGUI.createView()
        return self.addScrollBars(self.treeView, hpolicy=Gtk.PolicyType.NEVER)

    def notifyTopWindow(self, *args):
        # avoid the quit button getting initial focus, give it to the tree view (why not?)
        self.treeView.grab_focus()

    @staticmethod
    def canSelect(selection, model, path, is_selected, user_data):
        pathIter = user_data.filteredModel.get_iter(path)
        test = user_data.filteredModel.get_value(pathIter, 2)[0]
        return test.classId() == "test-case" or test in user_data.testSuitesWithResults

    def rowExpanded(self, treeview, iter, path):
        self.expandLevel(treeview, self.filteredModel.iter_children(iter), self.collapseStatic - len(path))

    def userChangedSelection(self, *args):
        if not self.selecting and not hasattr(self.selection, "unseen_changes"):
            self.selectionChanged(direct=True)

    def selectionChanged(self, direct):
        newSelection = self.getSelected()
        if newSelection != self.selectedTests:
            self.sendSelectionNotification(newSelection, direct)
            if direct:
                self.updateRecalculationMarkers()

    def notifyRefreshTestSelection(self):
        # The selection hasn't changed, but we want to e.g.
        # recalculate the action sensitiveness and make sure we can still see the selected tests.
        self.sendSelectionNotification(self.selectedTests)
        self.scrollToFirstTest()

    def notifyRecomputed(self, test):
        iter = self.itermap.getIterator(test)
        # If we've recomputed, clear the recalculation icons
        self.setNewRecalculationStatus(iter, test, [])

    def getSortedSelectedTests(self, suite):
        appTests = [test for test in self.selectedTests if test.app is suite.app]
        allTests = suite.allTestsAndSuites()
        appTests.sort(key=allTests.index)
        return appTests

    def notifyWriteTestsIfSelected(self, suite, file):
        for test in self.getSortedSelectedTests(suite):
            self.writeSelectedTest(test, file)

    def shouldListSubTests(self, test):
        if test.parent is None or not all((self.isVisible(test) for test in test.testCaseList())):
            return True

        filters = test.app.getFilterList([test])
        return len(filters) > 0

    def writeSelectedTest(self, test, file):
        if test.classId() == "test-suite":
            if self.shouldListSubTests(test):
                for subTest in test.testcases:
                    if self.isVisible(subTest):
                        self.writeSelectedTest(subTest, file)
                return
        file.write(test.getRelPath() + "\n")

    def updateRecalculationMarker(self, model, dummy, iter):
        tests = model.get_value(iter, 2)
        if not tests[0].stateInGui.isComplete():
            return

        recalcComparisons = tests[0].stateInGui.getComparisonsForRecalculation()
        childIter = self.filteredModel.convert_iter_to_child_iter(iter)
        self.setNewRecalculationStatus(childIter, tests[0], recalcComparisons)

    def setNewRecalculationStatus(self, iter, test, recalcComparisons):
        oldVal = self.model.get_value(iter, 6)
        newVal = self.getRecalculationIcon(recalcComparisons)
        if newVal != oldVal:
            self.model.set_value(iter, 6, newVal)
        self.notify("Recalculation", test, recalcComparisons, newVal)

    def getRecalculationIcon(self, recalc):
        if recalc:
            return "gtk-refresh"
        else:
            return ""

    def checkRelatedForRecalculation(self, test):
        self.filteredModel.foreach(self.checkRecalculationIfMatches, test)

    def checkRecalculationIfMatches(self, model, path, iter, test):
        tests = model.get_value(iter, 2)
        if tests[0] is not test and tests[0].getRelPath() == test.getRelPath():
            self.updateRecalculationMarker(model, path, iter)

    def getSelectedApps(self, tests):
        apps = []
        for test in tests:
            if test.app not in apps:
                apps.append(test.app)
        return apps

    def notifyActionStart(self, foreground=True):
        if not foreground:
            self.longActionRunning = True

    def notifyActionStop(self, foreground=True):
        if not foreground:
            if self.longActionRunning and self.recreateOnActionStop:
                self.sendActualSelectionNotification(direct=False)
            self.longActionRunning = False
            self.recreateOnActionStop = False

    def sendActualSelectionNotification(self, direct):
        apps = self.getSelectedApps(self.selectedTests)
        self.notify("NewTestSelection", self.selectedTests, apps, self.selection.count_selected_rows(), direct)

    def sendSelectionNotification(self, tests, direct=True):
        if len(tests) < 10:
            self.diag.info("Selection now changed to " + repr(tests))
        else:
            self.diag.info("Selection now of size " + str(len(tests)))
        self.selectedTests = tests
        if self.longActionRunning:
            self.recreateOnActionStop = True
            self.subguis[0].updateTestInfo(tests, self.selection.count_selected_rows())
        else:
            self.sendActualSelectionNotification(direct)

    def updateRecalculationMarkers(self):
        if self.dynamic:
            self.selection.selected_foreach(self.updateRecalculationMarker)

    def getSelected(self):
        allSelected = []
        prevSelected = set(self.selectedTests)

        def addSelTest(model, dummy, iter, selected):
            selected += self.getNewSelected(model.get_value(iter, 2), prevSelected)

        self.selection.selected_foreach(addSelTest, allSelected)
        return allSelected

    def getNewSelected(self, tests, prevSelected):
        intersection = prevSelected.intersection(set(tests))
        if len(intersection) == 0 or len(intersection) == len(tests) or len(intersection) == len(prevSelected):
            return tests
        else:
            return list(intersection)

    def findIter(self, test):
        try:
            childIter = self.itermap.getIterator(test)
            if childIter:
                return self.filteredModel.convert_child_iter_to_iter(childIter)
        except RuntimeError:
            # convert_child_iter_to_iter throws RunTimeError if the row is hidden in the TreeModelFilter
            self.diag.info("Could not find iterator for " + repr(test) + ", possibly row is hidden.")

    def notifySetTestSelection(self, selTests, criteria="", selectCollapsed=True, direct=False):
        actualSelection = self.selectTestRows(selTests, selectCollapsed)
        # Here it's been set via some indirect mechanism, might want to behave differently
        self.sendSelectionNotification(actualSelection, direct=direct)
        self.updateRecalculationMarkers()

    def selectTestRows(self, selTests, selectCollapsed=True):
        self.selecting = True  # don't respond to each individual programmatic change here
        self.selection.unselect_all()
        treeView = self.selection.get_tree_view()
        firstPath = None
        actuallySelected = []
        for test in selTests:
            iterValid, iter = self.findIter(test)
            if not iterValid or (not selectCollapsed and not self.isExpanded(iter)):
                continue

            actuallySelected.append(test)
            path = self.filteredModel.get_path(iter)
            if not firstPath:
                firstPath = path
            if selectCollapsed:
                treeView.expand_to_path(path)
            self.selection.select_iter(iter)
        treeView.grab_focus()
        if firstPath is not None and treeView.get_property("visible"):
            self.scrollToPath(firstPath)
        self.selecting = False
        return actuallySelected

    def scrollToFirstTest(self):
        if len(self.selectedTests) > 0:
            test = self.selectedTests[0]
            iterValid, iter = self.findIter(test)
            path = self.filteredModel.get_path(iter)
            self.scrollToPath(path)

    def scrollToPath(self, path):
        treeView = self.selection.get_tree_view()
        cellArea = treeView.get_cell_area(path, treeView.get_columns()[0])
        visibleArea = treeView.get_visible_rect()
        if cellArea.y < 0 or cellArea.y > visibleArea.height:
            treeView.scroll_to_cell(path, use_align=True, row_align=0.1)

    def expandLevel(self, view, iter, recurseLevel=100):
        # Make sure expanding expands everything, better than just one level as default...
        # Avoid using view.expand_row(path, open_all=True), as the open_all flag
        # doesn't seem to send the correct 'row-expanded' signal for all rows ...
        # This way, the signals are generated one at a time and we call back into here.
        model = view.get_model()
        while iter is not None:
            if recurseLevel > 0:
                view.expand_row(model.get_path(iter), open_all=False)
            iter = view.get_model().iter_next(iter)

    def notifyTestAppearance(self, test, detailText, colour1, colour2, approved):
        iter = self.itermap.getIterator(test)
        self.model.set_value(iter, 1, colour1)
        self.model.set_value(iter, 3, detailText)
        self.model.set_value(iter, 4, colour2)
        if test.classId() == "test-suite":  # Happens with Replace Text sometimes
            self.testSuitesWithResults.add(test)
        if approved:
            self.checkRelatedForRecalculation(test)

    def notifyLifecycleChange(self, test, *args):
        if test in self.selectedTests:
            self.notify("LifecycleChange", test, *args)

    def notifyFileChange(self, test, *args):
        if test in self.selectedTests:
            self.notify("FileChange", test, *args)

    def notifyDescriptionChange(self, test, *args):
        if test in self.selectedTests:
            self.notify("DescriptionChange", test, *args)

    def notifyRefreshFilePreviews(self, test, *args):
        if test in self.selectedTests:
            self.notify("RefreshFilePreviews", test, *args)

    def isVisible(self, test):
        iterValid, filteredIter = self.findIter(test)
        if iterValid:
            return True
        else:
            self.diag.info("No iterator found for " + repr(test))
            return False

    def findAllTests(self):
        tests = []
        self.model.foreach(self.appendTest, tests)
        return tests

    def appendTest(self, model, dummy, iter, tests):
        for test in model.get_value(iter, 2):
            if test.classId() == "test-case":
                tests.append(test)

    def getTestForAutoSelect(self):
        allTests = self.findAllTests()
        if len(allTests) == 1:
            test = allTests[0]
            if self.isVisible(test):
                return test

    def notifyAllComplete(self):
        # Window may already have been closed...
        if self.selection.get_tree_view():
            test = self.getTestForAutoSelect()
            if test:
                actualSelection = self.selectTestRows([test])
                self.sendSelectionNotification(actualSelection)

    def notifyAdd(self, test, initial):
        if test.classId() == "test-case":
            self.notify("TestTreeCounters", initial=initial, totalDelta=1,
                        totalShownDelta=self.getTotalShownDelta(), totalRowsDelta=self.getTotalRowsDelta(test))
        elif self.dynamic and test.isEmpty():
            return  # don't show empty suites in the dynamic GUI

        self.diag.info("Adding test " + repr(test))
        self.tryAddTest(test, initial)
        if test.parent is None and not initial:
            # We've added a new suite, we should also select it as it's likely the user wants to add stuff under it
            # Also include the knock-on effects, i.e. selecting the test tab etc
            self.notifySetTestSelection([test], direct=True)

    def notifyClipboard(self, tests, cut=False):
        if cut:
            colourKey = "clipboard_cut"
        else:
            colourKey = "clipboard_copy"
        colour = guiutils.guiConfig.getTestColour(colourKey)
        toRemove = self.clipboardTests.difference(set(tests))
        self.clipboardTests = set(tests)
        for test in tests:
            iter = self.itermap.getIterator(test)
            self.model.set_value(iter, 7, colour)
        for test in toRemove:
            iter = self.itermap.getIterator(test)
            if iter:
                self.model.set_value(iter, 7, "black")

    def getTotalRowsDelta(self, test):
        if self.itermap.getIterator(test):
            return 0
        else:
            return 1

    def getTotalShownDelta(self):
        if self.dynamic:
            return int(self.newTestsVisible)
        else:
            return 1  # we hide them temporarily for performance reasons, so can't do as above

    def tryAddTest(self, test, initial=False):
        iter = self.itermap.getIterator(test)
        if iter:
            self.addAdditional(iter, test)
            return iter
        suite = test.parent
        suiteIter = None
        if suite:
            suiteIter = self.tryAddTest(suite, initial)
        followIter = self.findFollowIter(suite, test, initial)
        return self.addSuiteWithParent(test, suiteIter, followIter)

    def findFollowIter(self, suite, test, initial):
        if not initial and suite:
            follower = suite.getFollower(test)
            if follower:
                return self.itermap.getIterator(follower)

    def addAdditional(self, iter, test):
        currTests = self.model.get_value(iter, 2)
        if not test in currTests:
            self.diag.info("Adding additional test to node " + self.model.get_value(iter, 0))
            currTests.append(test)

    def notifyRemove(self, test):
        delta = -test.size()
        iter = self.itermap.getIterator(test)
        allTests = self.model.get_value(iter, 2)
        if len(allTests) == 1:
            self.notify("TestTreeCounters", totalDelta=delta, totalShownDelta=delta, totalRowsDelta=delta)
            self.removeTest(test, iter)
        else:
            self.notify("TestTreeCounters", totalDelta=delta, totalShownDelta=delta, totalRowsDelta=0)
            allTests.remove(test)

    def removeTest(self, test, iter):
        self.diag.info("Removing test " + self.model.get_value(iter, 0))
        iterValid, filteredIter = self.findIter(test)
        self.selecting = True
        if self.selection.iter_is_selected(filteredIter):
            self.selection.unselect_iter(filteredIter)
        self.selecting = False
        self.selectionChanged(direct=False)
        self.model.remove(iter)
        self.itermap.remove(test)

    def notifyNameChange(self, test, origRelPath):
        iter = self.itermap.updateIterator(test, origRelPath)
        oldName = self.model.get_value(iter, 0)
        if test.name != oldName:
            self.model.set_value(iter, 0, test.name)

        iterValid, filteredIter = self.filteredModel.convert_child_iter_to_iter(iter)
        if self.selection.iter_is_selected(filteredIter):
            self.notify("NameChange", test, origRelPath)

    def notifyContentChange(self, *args):
        col_id, _ = self.model.get_sort_column_id()
        if col_id is None:
            self.model.set_default_sort_func(self.sortByTestCases)
        self.model.set_sort_column_id(Gtk.TREE_SORTABLE_DEFAULT_SORT_COLUMN_ID, Gtk.SortType.ASCENDING)

    def sortByTestCases(self, model, iter1, iter2, *args):
        test1 = self.model.get_value(iter1, 2)[0]
        test2 = self.model.get_value(iter2, 2)[0]
        if test1.parent is None or test2.parent is None:
            return 0
        index1 = test1.parent.testcases.index(test1)
        index2 = test2.parent.testcases.index(test2)
        return -1 if index1 < index2 else 1

    def notifyVisibility(self, tests, newValue):
        self.diag.info("Visibility change for " + repr(tests) + " to " + repr(newValue))
        if not newValue:
            self.selecting = True
        changedTests = []
        for test in tests:
            if self.updateVisibilityWithParents(test, newValue):
                changedTests.append(test)

        self.selecting = False
        if len(changedTests) > 0:
            self.diag.info("Actually changed tests " + repr(changedTests))
            self.notify("Visibility", changedTests, newValue)
            if self.treeView:
                self.updateVisibilityInViews(newValue)

    def updateVisibilityInViews(self, newValue):
        if newValue:  # if things have become visible, expand everything
            self.treeView.expand_all()
            GObject.idle_add(self.scrollToFirstTest)
        else:
            self.selectionChanged(direct=False)

    def updateVisibilityWithParents(self, test, newValue):
        changed = False
        if test.parent and newValue:
            changed |= self.updateVisibilityWithParents(test.parent, newValue)

        changed |= self.updateVisibilityInModel(test, newValue)
        if test.parent and not newValue and not self.hasVisibleChildren(test.parent) and not test.parent.state.hasStarted():
            self.diag.info("No visible children : hiding parent " + repr(test.parent))
            changed |= self.updateVisibilityWithParents(test.parent, newValue)
        return changed

    def isMarkedVisible(self, test):
        testIter = self.itermap.getIterator(test)
        # Can get None here when using queue systems, so that some tests in a suite
        # start processing when others have not yet notified the GUI that they have been read.
        return testIter is not None and self.model.get_value(testIter, 5) and test in self.model.get_value(testIter, 2)

    def updateVisibilityInModel(self, test, newValue):
        testIter = self.itermap.getIterator(test)
        if testIter is None:
            # Tests are not necessarily loaded yet in the GUI (for example if we do show only selected), don't stacktrace
            return False
        visibleTests = self.model.get_value(testIter, 2)
        isVisible = test in visibleTests
        changed = False
        if newValue and not isVisible:
            visibleTests.append(test)
            changed = True
        elif not newValue and isVisible:
            visibleTests.remove(test)
            changed = True

        if (newValue and len(visibleTests) > 1) or (not newValue and len(visibleTests) > 0):
            self.diag.info("No row visibility change : " + repr(test))
            return changed
        else:
            return self.setVisibility(testIter, newValue)

    def setVisibility(self, iter, newValue):
        oldValue = self.model.get_value(iter, 5)
        if oldValue == newValue:
            return False

        self.model.set_value(iter, 5, newValue)
        return True

    def hasVisibleChildren(self, suite):
        return any((self.isMarkedVisible(test) for test in suite.testcases))
