
"""
Module for the various widgets that keep an overall view of the status or progress
of the current run/setup
"""
from gi.repository import Gtk, GObject, Pango, GdkPixbuf
from . import guiutils
import os
import logging
from texttestlib import plugins
from collections import OrderedDict
from copy import copy

#
# A class responsible for putting messages in the status bar.
# It is also responsible for keeping the throbber rotating
# while actions are under way.
#


class StatusMonitorGUI(guiutils.SubGUI):
    def __init__(self, initialMessage):
        guiutils.SubGUI.__init__(self)
        self.throbber = None
        self.animation = None
        self.pixbuf = None
        self.label = None
        self.closing = False
        self.initialMessage = plugins.convertForMarkup(initialMessage)

    def getWidgetName(self):
        return "_Status bar"

    def notifyActionStart(self, lock=True):
        if self.throbber:
            if self.pixbuf:  # pragma: no cover : Only occurs if some code forgot to do ActionStop ...
                self.notifyActionStop(lock)
            self.pixbuf = self.throbber.get_pixbuf()
            self.throbber.set_from_animation(self.animation)
            if lock:
                self.throbber.grab_add()

    def notifyWindowClosed(self, *args):
        self.closing = True

    def notifyActionProgress(self, *args):
        if not self.closing:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)

    def notifyActionStop(self, lock=True):
        if self.throbber:
            self.throbber.set_from_pixbuf(self.pixbuf)
            self.pixbuf = None
            if lock:
                self.throbber.grab_remove()

    def notifyStatus(self, message):
        if self.label:
            self.label.set_markup(plugins.convertForMarkup(message))

    def createView(self):
        hbox = Gtk.HBox()
        self.label = Gtk.Label()
        self.label.set_name("GUI status")
        self.label.set_ellipsize(Pango.EllipsizeMode.END)
        # It seems difficult to say 'ellipsize when you'd otherwise need
        # to enlarge the window', so we'll have to settle for a fixed number
        # of max char's ... The current setting (90) is just a good choice
        # based on my preferred window size, on the test case I used to
        # develop this code. (since different chars have different widths,
        # the optimal number depends on the string to display) \ Mattias++
        self.label.set_max_width_chars(90)
        self.label.set_use_markup(True)
        self.label.set_markup(self.initialMessage)
        hbox.pack_start(self.label, False, False, 0)
        imageDir = plugins.installationDir("images")
        try:
            staticIcon = os.path.join(imageDir, "throbber_inactive.png")
            temp = GdkPixbuf.Pixbuf.new_from_file(staticIcon)
            self.throbber = Gtk.Image.new_from_pixbuf(temp)
            animationIcon = os.path.join(imageDir, "throbber_active.gif")
            self.animation = GdkPixbuf.PixbufAnimation.new_from_file(animationIcon)
            hbox.pack_end(self.throbber, False, False, 0)
        except Exception as e:
            plugins.printWarning("Failed to create icons for the status throbber:\n" + str(e) +
                                 "\nAs a result, the throbber will be disabled.", stdout=True)
            self.throbber = None
        self.widget = Gtk.Frame()
        self.widget.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        self.widget.add(hbox)
        self.widget.show_all()
        return self.widget


class ProgressBarGUI(guiutils.SubGUI):
    def __init__(self, dynamic, testCount):
        guiutils.SubGUI.__init__(self)
        self.dynamic = dynamic
        self.totalNofTests = testCount
        self.addedCount = 0
        self.nofCompletedTests = 0
        self.widget = None

    def shouldShow(self):
        return self.dynamic

    def createView(self):
        self.widget = Gtk.ProgressBar()
        self.widget.set_show_text(True)
        self.resetBar()
        self.widget.show()
        return self.widget

    def notifyAdd(self, test, initial):
        if test.classId() == "test-case":
            self.addedCount += 1
            if self.addedCount > self.totalNofTests:
                self.totalNofTests += 1
                self.resetBar()

    def notifyAllRead(self, *args):
        # The initial number was told be the static GUI, treat it as a guess
        # Can be wrong in case versions are defined by testsuite files.
        if self.totalNofTests != self.addedCount:
            self.totalNofTests = self.addedCount
            self.resetBar()

    def notifyLifecycleChange(self, test, dummyState, changeDesc):
        if changeDesc == "complete" and test.classId() == "test-case":
            self.nofCompletedTests += 1
            self.resetBar()

    def computeFraction(self):
        if self.totalNofTests > 0:
            return float(self.nofCompletedTests) / float(self.totalNofTests)
        else:
            return 0  # No tests yet, haven't read them in

    def resetBar(self):
        if self.widget:
            self.widget.set_text(self.getFractionMessage())
            self.widget.set_fraction(self.computeFraction())

    def getFractionMessage(self):
        if self.nofCompletedTests >= self.totalNofTests:
            completionTime = plugins.localtime()
            return "All " + str(self.totalNofTests) + " tests completed at " + completionTime
        else:
            return str(self.nofCompletedTests) + " of " + str(self.totalNofTests) + " tests completed"


class ClassificationTree(OrderedDict):
    def addClassification(self, path):
        prevElementName = None
        for element in path:
            if isinstance(element, tuple):
                elementName = element[0]
                elementTuple = element
            else:
                elementName = element
                elementTuple = element, None
            if elementName not in self:
                self[elementName] = []
            if prevElementName and elementTuple not in self[prevElementName]:
                self[prevElementName].append(elementTuple)
            prevElementName = elementName

# Class that keeps track of (and possibly shows) the progress of
# pending/running/completed tests


class TestProgressMonitor(guiutils.SubGUI):
    def __init__(self, dynamic, testCount):
        guiutils.SubGUI.__init__(self)
        self.classifications = {}  # map from test to list of iterators where it exists

        # Each row has 'type', 'number', 'show', 'tests'
        self.treeModel = Gtk.TreeStore(GObject.TYPE_STRING, GObject.TYPE_INT, GObject.TYPE_BOOLEAN,
                                       GObject.TYPE_STRING, GObject.TYPE_STRING, GObject.TYPE_PYOBJECT,
                                       GObject.TYPE_STRING)
        self.diag = logging.getLogger("Progress Monitor")
        self.progressReport = None
        self.treeView = None
        self.dynamic = dynamic
        self.testCount = testCount
        self.diffStore = {}
        self.groupNames = {}
        if self.shouldShow():
            # It isn't really a gui configuration, and this could cause bugs when several apps
            # using differnt diff tools are run together. However, this isn't very likely and we prefer not
            # to recalculate all the time...
            diffTool = guiutils.guiConfig.getValue("text_diff_program")
            self.diffFilterGroup = plugins.TextTriggerGroup(
                guiutils.guiConfig.getCompositeValue("text_diff_program_filters", diffTool))
            self.maxLengthForGrouping = guiutils.guiConfig.getValue("lines_of_text_difference")
            if testCount > 0:
                colour = guiutils.guiConfig.getTestColour("not_started")
                visibility = guiutils.guiConfig.showCategoryByDefault("not_started")
                self.addNewIter("Not started", None, colour, visibility, testCount)

    def getTabTitle(self):
        return "Status"

    def shouldShow(self):
        return self.dynamic

    def createView(self):
        self.treeView = Gtk.TreeView(self.treeModel)
        self.treeView.set_name("Test Status View")
        self.treeView.set_enable_search(False)
        selection = self.treeView.get_selection()
        selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        selection.set_select_function(self.canSelect, None)
        selection.connect("changed", self.selectionChanged)
        textRenderer = Gtk.CellRendererText()
        textRenderer.set_property('wrap-width', 350)
        textRenderer.set_property('wrap-mode', Pango.WrapMode.WORD_CHAR)
        numberRenderer = Gtk.CellRendererText()
        numberRenderer.set_property('xalign', 1)
        statusColumn = Gtk.TreeViewColumn("Status", textRenderer, text=0, background=3, font=4)
        numberColumn = Gtk.TreeViewColumn("Number", numberRenderer, text=1, background=3, font=4)
        statusColumn.set_resizable(True)
        numberColumn.set_resizable(True)
        self.treeView.append_column(statusColumn)
        self.treeView.append_column(numberColumn)
        toggle = Gtk.CellRendererToggle()
        toggle.set_property('activatable', True)
        toggle.connect("toggled", self.showToggled)
        toggleColumn = Gtk.TreeViewColumn("Visible", toggle, active=2)
        toggleColumn.set_resizable(True)
        toggleColumn.set_alignment(0.5)
        self.treeView.append_column(toggleColumn)
        self.treeView.show()
        return self.addScrollBars(self.treeView, hpolicy=Gtk.PolicyType.NEVER)

    @staticmethod
    def canSelect(selection, model, path, is_selected, user_data):
        pathIter = model.get_iter(path)
        return model.get_value(pathIter, 2)

    def notifyAdd(self, test, initial):
        if self.dynamic and test.classId() == "test-case":
            incrementCount = self.testCount == 0
            self.insertTest(test, test.stateInGui, "add", incrementCount)

    def notifyAllRead(self, *args):
        # Fix the not started count in case the initial guess was wrong
        if self.testCount > 0:
            self.diag.info("Reading complete, updating not-started count to actual answer")
            iter = self.treeModel.get_iter_first()
            actualTestCount = len(self.treeModel.get_value(iter, 5))
            measuredTestCount = self.treeModel.get_value(iter, 1)
            if actualTestCount != measuredTestCount:
                self.treeModel.set_value(iter, 1, actualTestCount)

    def selectionChanged(self, selection):
        if hasattr(selection, "unseen_changes"):
            return  # hack in StoryText so we can reproduce manual behaviour

        # For each selected row, select the corresponding rows in the test treeview
        # and the corresponding files in the test fileview
        tests, fileStems = [], []

        def addSelected(treemodel, dummyPath, iter, *args):
            for test in treemodel.get_value(iter, 5):
                if test not in tests:
                    tests.append(test)
            fileStem = treemodel.get_value(iter, 6)
            if fileStem:
                fileStems.append(fileStem)

        selection.selected_foreach(addSelected)
        self.notify("SetTestSelection", tests)
        if len(fileStems) > 0:
            self.notify("SetFileSelection", fileStems)

    def findTestIterators(self, test):
        return self.classifications.get(test, [])

    def getCategoryDescription(self, state, categoryName=None):
        if not categoryName:
            categoryName = state.category
        briefDesc, _ = state.categoryDescriptions.get(categoryName, (categoryName, categoryName))
        return briefDesc.replace("_", " ").capitalize()

    def filterDiff(self, diff):
        filteredDiff = ""
        for line in diff.splitlines():
            if self.diffFilterGroup.stringContainsText(line):
                filteredDiff += line + "\n"
        return filteredDiff or diff  # If we filter it all away, should assume it was a new file and return it unchanged

    def getDifferenceType(self, fileComp):
        if fileComp.missingResult():
            return "Missing"
        elif fileComp.newResult():
            return "New"
        else:
            return "Differences"

    def getCategoryDescriptionClassifier(self, state, changeDesc):
        catDesc = self.getCategoryDescription(state)
        if state.isMarked():
            briefText = "Marked as Marked" if state.briefText == catDesc else state.briefText
            return [catDesc, briefText]

        if not state.isComplete() or not state.hasFailed():
            classification = [catDesc]
            if "approve" in changeDesc:
                classification.append("Approved")
            elif not state.isComplete() and state.briefText:
                subState = state.briefText.split()[0]
                if subState != state.defaultBriefText:
                    classification.append(subState)
            return classification

        if not state.isSaveable() or state.warnOnSave():  # If it's not saveable, don't classify it by the files
            details = state.getTypeBreakdown()[1]
            self.diag.info("Adding unsaveable : " + catDesc + " " + details)
            return ["Failed", catDesc, details]

    def getClassifiers(self, test, state, changeDesc):
        classifiers = ClassificationTree()
        catDescClassifier = self.getCategoryDescriptionClassifier(state, changeDesc)
        if catDescClassifier:
            classifiers.addClassification(catDescClassifier)
        else:
            self.addComparisonClassifiers(classifiers, test, state)
        return classifiers

    def addComparisonClassifiers(self, classifiers, test, state):
        failureComparisons, perfComparisons = [], []
        for c in state.getComparisons():
            l = failureComparisons if c.getType() == "failure" else perfComparisons
            l.append(c)

        for fileComp in failureComparisons:
            self.addFailureComparisonClassifiers(classifiers, test, state, fileComp)

        for fileComp in perfComparisons:
            fileClass = self.getPerformanceComparisonClassifier(test, state, fileComp)
            classifiers.addClassification(fileClass)

    def addFailureComparisonClassifiers(self, classifiers, test, state, fileComp):
        summary = self.getFileSummary(fileComp)
        fileClass = ["Failed", self.getDifferenceType(fileComp), (summary, fileComp.stem)]

        filteredDiff = self.getFilteredDiff(fileComp)
        extraGroupName = None
        if filteredDiff is not None:
            groupNames, summaryDiffs, ungrouped = self.diffStore.setdefault(summary, ({}, OrderedDict(), []))
            hasGroups = len(groupNames) > 0
            testList, groupName = summaryDiffs.setdefault(filteredDiff, ([], None))
            if test not in testList:
                testList.append(test)
            if groupName is None:
                onlyIfRepeated = len(testList) == 1
                groupName, extraGroupName = self.setGroupName(groupNames, summaryDiffs, filteredDiff, onlyIfRepeated)
            if groupName:
                fileClass.append(("Group " + groupName, fileComp.stem))
            else:
                ungrouped.append(test)
                if groupNames:
                    fileClass.append(("Ungrouped", fileComp.stem))

        if extraGroupName:
            extraFileClass = copy(fileClass[:-1])
            extraFileClass.append(("Group " + extraGroupName, fileComp.stem))
            self.diag.info("Adding extra file classification for " + repr(fileComp) + " = " + repr(extraFileClass))
            classifiers.addClassification(extraFileClass)
        self.diag.info("Adding file classification for " + repr(fileComp) + " = " + repr(fileClass))
        classifiers.addClassification(fileClass)
        if filteredDiff is not None and groupName and not hasGroups:
            for _ in ungrouped:
                extraFileClass = copy(fileClass[:-1])
                extraFileClass.append(("Ungrouped", fileComp.stem))
                self.diag.info("Adding extra ungrouped category for " + repr(fileComp) + " = " + repr(extraFileClass))
                classifiers.addClassification(extraFileClass)

    def getPerformanceComparisonClassifier(self, test, state, fileComp):
        summary = fileComp.getSummary(includeNumbers=False)
        desc = self.getCategoryDescription(state, summary)
        stem = fileComp.stem
        fileClass = ["Failed", "Performance differences", (desc, stem)]
        toleranceRange = fileComp.getToleranceMultipleRange(test)
        if toleranceRange:
            fileClass.append((toleranceRange, stem))
        self.diag.info("Adding file classification for " + repr(fileComp) + " = " + repr(fileClass))
        return fileClass

    def extractRepeats(self, filteredDiff):
        size = len(filteredDiff)
        smallPrimes = [2, 3, 5, 7, 11, 13, 17, 19]  # Surely we won't repeat stuff more than 20 times :)
        for prime in smallPrimes:
            if size > prime and size % prime == 0:
                chunkSize = size // prime
                firstPart = filteredDiff[:chunkSize]
                if filteredDiff == firstPart * prime:
                    return firstPart, prime
        return None, None

    def setGroupName(self, groupNames, summaryDiffs, filteredDiff, onlyIfRepeated):
        groupName, extraGroupName = self.getGroupName(groupNames, summaryDiffs, filteredDiff, onlyIfRepeated)
        if not groupName:
            return None, None

        groupNames[groupName] = filteredDiff
        tests = summaryDiffs[filteredDiff][0] if filteredDiff in summaryDiffs else []
        summaryDiffs[filteredDiff] = (tests, groupName)
        return groupName, extraGroupName

    def getGroupName(self, groupNames, summaryDiffs, filteredDiff, onlyIfRepeated):
        self.diag.info("Getting group name for " + repr(filteredDiff))
        singleVersion, timesRepeated = self.extractRepeats(filteredDiff)
        if singleVersion:
            self.diag.info("Extracted repeats of " + repr(singleVersion))
            _, group = summaryDiffs.get(singleVersion, (None, None))
            if group is None:
                group, _ = self.setGroupName(groupNames, summaryDiffs, singleVersion, False)
                self.diag.info("Created group " + repr(group))
                tests, _ = summaryDiffs.get(singleVersion, (None, None))
                extraGroupName = group if len(tests) == 1 else None
            else:
                extraGroupName = None
                self.diag.info("Found group " + repr(group))

            if "*" in group:
                core, timeStr = group.split("*")
                return core + "*" + str(timesRepeated * int(timeStr)), None
            else:
                return str(group) + "*" + str(timesRepeated), extraGroupName
        elif not onlyIfRepeated:
            group = len(groupNames) + 1
            return str(group), None
        return None, None

    def notifySelectInGroup(self, fileComp):
        summary = self.getFileSummary(fileComp)
        _, summaryDiffs, _ = self.diffStore.get(summary, {})
        filteredDiff = self.getFilteredDiff(fileComp)
        testList, groupName = summaryDiffs.get(filteredDiff, ([], False))
        if groupName:
            self.notify("SetTestSelection", testList)

    def getFileSummary(self, fileComp):
        return fileComp.getSummary(includeNumbers=False)

    def getFilteredDiff(self, fileComp):
        freeText = fileComp.getFreeTextBody()
        if freeText.count("\n") < self.maxLengthForGrouping:
            return self.filterDiff(freeText)

    def removeFromModel(self, test):
        for iter in self.findTestIterators(test):
            self.removeFromIter(iter, test)

    def removeFromIter(self, iter, test):
        allTests = self.treeModel.get_value(iter, 5)
        if test in allTests:
            testCount = self.treeModel.get_value(iter, 1)
            self.treeModel.set_value(iter, 1, testCount - 1)
            if testCount == 1:
                self.treeModel.set_value(iter, 3, None)
                self.treeModel.set_value(iter, 4, "")
            allTests.remove(test)
            self.diag.info("Removing test " + repr(test) + " from node " + self.treeModel.get_value(iter, 0))
            self.treeModel.set_value(iter, 5, allTests)

    def removeFromDiffStore(self, test):
        for _, fileInfo, ungrouped in list(self.diffStore.values()):
            for testList, _ in list(fileInfo.values()):
                if test in testList:
                    testList.remove(test)
            if test in ungrouped:
                ungrouped.remove(test)

    def insertTest(self, test, state, changeDesc, incrementCount):
        self.classifications[test] = []
        classifiers = self.getClassifiers(test, state, changeDesc)
        nodeClassifier = list(classifiers.keys())[0]
        defaultColour, defaultVisibility = self.getCategorySettings(state.category, nodeClassifier, classifiers)
        return self.addTestForNode(test, defaultColour, defaultVisibility, nodeClassifier, classifiers, incrementCount)

    def getCategorySettings(self, category, nodeClassifier, classifiers):
        # Use the category description if there is only one level, otherwise rely on the status names
        if len(classifiers.get(nodeClassifier)) == 0 or category in ["failure", "success", "bug"]:
            return guiutils.guiConfig.getTestColour(category), guiutils.guiConfig.showCategoryByDefault(category)
        else:
            return None, True

    def updateTestAppearance(self, test, state, changeDesc, colour):
        resultType, summary = state.getTypeBreakdown()
        catDesc = self.getCategoryDescription(state, resultType)
        mainColour = guiutils.guiConfig.getTestColour(catDesc, guiutils.guiConfig.getTestColour(resultType))
        self.notify("TestAppearance", test, summary, mainColour, colour, "approve" in changeDesc)
        self.notify("Visibility", [test], self.shouldBeVisible(test))

    def removeFromUngroupedNode(self, test, parentIter):
        self.diag.info("Removing previously ungrouped " + repr(test))
        ungroupedIter = self.findIter("Ungrouped", parentIter)
        if ungroupedIter is not None:
            self.removeFromIter(ungroupedIter, test)

    def getInitialTestsForNode(self, test, parentIter, nodeClassifier):
        if nodeClassifier.startswith("Group "):
            groupName = nodeClassifier[6:]
            parentName = self.treeModel.get_value(parentIter, 0)
            groupNames, summaryDiffs, ungrouped = self.diffStore.get(parentName)
            filteredDiff = groupNames.get(groupName)
            if filteredDiff is not None:
                testList = summaryDiffs[filteredDiff][0]
                for test in testList:
                    if test in ungrouped:
                        self.removeFromUngroupedNode(test, parentIter)
                        ungrouped.remove(test)
                return copy(testList)
        elif nodeClassifier == "Ungrouped":
            parentName = self.treeModel.get_value(parentIter, 0)
            _, _, ungrouped = self.diffStore.get(parentName)
            return copy(ungrouped)
        return [test]

    def addTestForNode(self, test, defaultColour, defaultVisibility, nodeClassifier,
                       classifiers, incrementCount, parentIter=None, fileStem=None):
        nodeIter = self.findIter(nodeClassifier, parentIter)
        colour = guiutils.guiConfig.getTestColour(nodeClassifier, defaultColour)
        if nodeIter:
            visibility = self.treeModel.get_value(nodeIter, 2)
            self.diag.info("Adding " + repr(test) + " for node " + nodeClassifier + ", visible = " + repr(visibility))
            self.insertTestAtIter(nodeIter, test, colour, incrementCount)
            self.classifications[test].append(nodeIter)
        else:
            visibility = guiutils.guiConfig.showCategoryByDefault(nodeClassifier, parentShown=defaultVisibility)
            initialTests = self.getInitialTestsForNode(test, parentIter, nodeClassifier)
            if len(initialTests):
                nodeIter = self.addNewIter(nodeClassifier, parentIter, colour, visibility,
                                           len(initialTests), initialTests, fileStem)
                for initTest in initialTests:
                    self.diag.info("New node " + nodeClassifier + ", colour = " + repr(colour) +
                                   ", visible = " + repr(visibility) + " : add " + repr(initTest))
                    self.classifications[initTest].append(nodeIter)
            else:
                self.diag.info("Not adding new node for " + repr(test) + " for node " +
                               nodeClassifier + ", no tests in category initially")
        subColours = []
        for subNodeClassifier, fileStem in classifiers[nodeClassifier]:
            subColour = self.addTestForNode(test, colour, visibility, subNodeClassifier,
                                            classifiers, incrementCount, nodeIter, fileStem)
            subColours.append(subColour)

        if len(subColours) > 0:
            return subColours[0]
        else:
            return colour

    def insertTestAtIter(self, iter, test, colour, incrementCount):
        allTests = self.treeModel.get_value(iter, 5)
        testCount = self.treeModel.get_value(iter, 1)
        if testCount == 0:
            self.treeModel.set_value(iter, 3, colour)
            self.treeModel.set_value(iter, 4, "bold")
        if incrementCount:
            self.treeModel.set_value(iter, 1, testCount + 1)
        allTests.append(test)

    def addNewIter(self, classifier, parentIter, colour, visibility, testCount, tests=[], fileStem=None):
        modelAttributes = [classifier, testCount, visibility, colour, "bold", tests, fileStem]
        newIter = self.insertIntoModel(parentIter, modelAttributes)
        if parentIter:
            self.treeView.expand_row(self.treeModel.get_path(parentIter), open_all=0)
        return newIter

    def insertIntoModel(self, parentIter, modelAttributes):
        if parentIter:
            paddedClassifier = plugins.padNumbersWithZeroes(modelAttributes[0])
            follower = self.findChildIter(
                parentIter, lambda name: plugins.padNumbersWithZeroes(name) > paddedClassifier)
            return self.treeModel.insert_before(parentIter, follower, modelAttributes)
        else:
            return self.treeModel.append(parentIter, modelAttributes)

    def findChildIter(self, parentIter, predicate):
        iter = self.treeModel.iter_children(parentIter)
        while iter != None:
            name = self.treeModel.get_value(iter, 0)
            if predicate(name):
                return iter
            else:
                iter = self.treeModel.iter_next(iter)

    def findIter(self, classifier, startIter):
        return self.findChildIter(startIter, lambda name: name == classifier)

    def notifyLifecycleChange(self, test, state, changeDesc):
        self.removeFromModel(test)
        if "approve" in changeDesc or "marked" in changeDesc or "recalculated" in changeDesc:
            self.removeFromDiffStore(test)
        colourInserted = self.insertTest(test, state, changeDesc, incrementCount=True)
        self.updateTestAppearance(test, state, changeDesc, colourInserted)

    def removeParentIters(self, iters):
        noParents = []
        for iter1 in iters:
            if not self.isParent(iter1, iters):
                noParents.append(iter1)
        return noParents

    def isParent(self, iter1, iters):
        path1 = self.treeModel.get_path(iter1)
        for iter2 in iters:
            parent = self.treeModel.iter_parent(iter2)
            if parent is not None and self.treeModel.get_path(parent) == path1:
                return True
        return False

    def shouldBeVisible(self, test):
        iters = self.findTestIterators(test)
        # ignore the parent nodes where visibility is concerned
        visibilityIters = self.removeParentIters(iters)
        self.diag.info("Visibility for " + repr(test) + " : iters " +
                       repr(list(map(self.treeModel.get_path, visibilityIters))))
        for nodeIter in visibilityIters:
            visible = self.treeModel.get_value(nodeIter, 2)
            if visible:
                return True
        return False

    def getAllChildIters(self, iter):
        # Toggle all children too
        childIters = []
        childIter = self.treeModel.iter_children(iter)
        while childIter != None:
            childIters.append(childIter)
            childIters += self.getAllChildIters(childIter)
            childIter = self.treeModel.iter_next(childIter)
        return childIters

    def showToggled(self, dummyWidget, path):
        # Toggle the toggle button
        newValue = not self.treeModel[path][2]
        self.treeModel[path][2] = newValue
        iter = self.treeModel.get_iter_from_string(path)
        categoryName = self.treeModel.get_value(iter, 0)
        for childIter in self.getAllChildIters(iter):
            self.treeModel.set_value(childIter, 2, newValue)

        if categoryName == "Not started":
            self.notify("DefaultVisibility", newValue)

        changedTests = []
        for test in self.treeModel.get_value(iter, 5):
            if self.shouldBeVisible(test) == newValue:
                changedTests.append(test)
        self.notify("Visibility", changedTests, newValue)
        if newValue is False:
            selection = self.treeView.get_selection()

            if selection.path_is_selected(Gtk.TreePath(path)):
                # WORKAROUND: selection.unselect_path(path) Doesn't seem to work here
                selection.set_mode(Gtk.SelectionMode.SINGLE)
                selection.set_mode(Gtk.SelectionMode.MULTIPLE)

    def notifyResetVisibility(self, tests, show):
        self.diag.info("Resetting visibility from current status")
        testsForReset = []

        def resetNodeVisibility(model, dummyPath, iter):
            if model.get_value(iter, 2) == show and not model.iter_has_child(iter):
                for test in model.get_value(iter, 5):
                    if test in tests:
                        testsForReset.append(test)

        self.treeModel.foreach(resetNodeVisibility)
        self.notify("Visibility", testsForReset, show)
