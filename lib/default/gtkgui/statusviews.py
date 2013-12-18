
"""
Module for the various widgets that keep an overall view of the status or progress
of the current run/setup
"""

import gtk, gobject, pango, guiutils, plugins, os, logging
from ordereddict import OrderedDict
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
            if self.pixbuf: # pragma: no cover : Only occurs if some code forgot to do ActionStop ...
                self.notifyActionStop(lock)
            self.pixbuf = self.throbber.get_pixbuf()
            self.throbber.set_from_animation(self.animation)
            if lock:
                self.throbber.grab_add()
                
    def notifyWindowClosed(self, *args):
        self.closing = True

    def notifyActionProgress(self, *args):
        if not self.closing:
            while gtk.events_pending():
                gtk.main_iteration(False)

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
        hbox = gtk.HBox()
        self.label = gtk.Label()
        self.label.set_name("GUI status")
        self.label.set_ellipsize(pango.ELLIPSIZE_END)
        # It seems difficult to say 'ellipsize when you'd otherwise need
        # to enlarge the window', so we'll have to settle for a fixed number
        # of max char's ... The current setting (90) is just a good choice
        # based on my preferred window size, on the test case I used to
        # develop this code. (since different chars have different widths,
        # the optimal number depends on the string to display) \ Mattias++
        self.label.set_max_width_chars(90)
        self.label.set_use_markup(True)
        self.label.set_markup(self.initialMessage)
        hbox.pack_start(self.label, expand=False, fill=False)
        imageDir = plugins.installationDir("images")
        try:
            staticIcon = os.path.join(imageDir, "throbber_inactive.png")
            temp = gtk.gdk.pixbuf_new_from_file(staticIcon)
            self.throbber = gtk.Image()
            self.throbber.set_from_pixbuf(temp)
            animationIcon = os.path.join(imageDir, "throbber_active.gif")
            self.animation = gtk.gdk.PixbufAnimation(animationIcon)
            hbox.pack_end(self.throbber, expand=False, fill=False)
        except Exception, e:
            plugins.printWarning("Failed to create icons for the status throbber:\n" + str(e) + \
                                 "\nAs a result, the throbber will be disabled.", stdout=True)
            self.throbber = None
        self.widget = gtk.Frame()
        self.widget.set_shadow_type(gtk.SHADOW_ETCHED_IN)
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
        self.widget = gtk.ProgressBar()
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

    def notifyLifecycleChange(self, dummyTest, dummyState, changeDesc):
        if changeDesc == "complete":
            self.nofCompletedTests += 1
            self.resetBar()

    def computeFraction(self):
        if self.totalNofTests > 0:
            return float(self.nofCompletedTests) / float(self.totalNofTests)
        else:
            return 0 # No tests yet, haven't read them in

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
            if not self.has_key(elementName):
                self[elementName] = []
            if prevElementName and elementTuple not in self[prevElementName]:
                self[prevElementName].append(elementTuple)
            prevElementName = elementName

# Class that keeps track of (and possibly shows) the progress of
# pending/running/completed tests
class TestProgressMonitor(guiutils.SubGUI):
    def __init__(self, dynamic, testCount):
        guiutils.SubGUI.__init__(self)
        self.classifications = {} # map from test to list of iterators where it exists

        # Each row has 'type', 'number', 'show', 'tests'
        self.treeModel = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_INT, gobject.TYPE_BOOLEAN, 
                                       gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT,
                                       gobject.TYPE_STRING)
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
            self.diffFilterGroup = plugins.TextTriggerGroup(guiutils.guiConfig.getCompositeValue("text_diff_program_filters", diffTool))
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
        self.treeView = gtk.TreeView(self.treeModel)
        self.treeView.set_name("Test Status View")
        self.treeView.set_enable_search(False)
        selection = self.treeView.get_selection()
        selection.set_mode(gtk.SELECTION_MULTIPLE)
        selection.set_select_function(self.canSelect)
        selection.connect("changed", self.selectionChanged)
        textRenderer = gtk.CellRendererText()
        textRenderer.set_property('wrap-width', 350)
        textRenderer.set_property('wrap-mode', pango.WRAP_WORD_CHAR)
        numberRenderer = gtk.CellRendererText()
        numberRenderer.set_property('xalign', 1)
        statusColumn = gtk.TreeViewColumn("Status", textRenderer, text=0, background=3, font=4)
        numberColumn = gtk.TreeViewColumn("Number", numberRenderer, text=1, background=3, font=4)
        statusColumn.set_resizable(True)
        numberColumn.set_resizable(True)
        self.treeView.append_column(statusColumn)
        self.treeView.append_column(numberColumn)
        toggle = gtk.CellRendererToggle()
        toggle.set_property('activatable', True)
        toggle.connect("toggled", self.showToggled)
        toggleColumn = gtk.TreeViewColumn("Visible", toggle, active=2)
        toggleColumn.set_resizable(True)
        toggleColumn.set_alignment(0.5)
        self.treeView.append_column(toggleColumn)
        self.treeView.show()
        return self.addScrollBars(self.treeView, hpolicy=gtk.POLICY_NEVER)

    def canSelect(self, path):
        pathIter = self.treeModel.get_iter(path)
        return self.treeModel.get_value(pathIter, 2)

    def notifyAdd(self, test, initial):
        if self.dynamic and test.classId() == "test-case":
            incrementCount = self.testCount == 0
            self.insertTest(test, test.stateInGui, "add", incrementCount)

    def notifyAllRead(self, *args):
        # Fix the not started count in case the initial guess was wrong
        if self.testCount > 0:
            self.diag.info("Reading complete, updating not-started count to actual answer")
            iter = self.treeModel.get_iter_root()
            actualTestCount = len(self.treeModel.get_value(iter, 5))
            measuredTestCount = self.treeModel.get_value(iter, 1)
            if actualTestCount != measuredTestCount:
                self.treeModel.set_value(iter, 1, actualTestCount)

    def selectionChanged(self, selection):
        if hasattr(selection, "unseen_changes"):
            return # hack in StoryText so we can reproduce manual behaviour

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
        return filteredDiff or diff # If we filter it all away, should assume it was a new file and return it unchanged

    def getDifferenceType(self, fileComp):
        if fileComp.missingResult():
            return "Missing"
        elif fileComp.newResult():
            return "New"
        else:
            return "Differences"

    def getClassifiers(self, test, state, changeDesc):
        classifiers = ClassificationTree()
        catDesc = self.getCategoryDescription(state)
        if state.isMarked():
            if state.briefText == catDesc:
                # Just in case - otherwise we get an infinite loop...
                classifiers.addClassification([ catDesc, "Marked as Marked" ])
            else:
                classifiers.addClassification([ catDesc, state.briefText ])
            return classifiers

        if not state.isComplete() or not state.hasFailed():
            classification = [ catDesc ]
            if "save" in changeDesc:
                classification.append("Saved")
            elif state.hasStarted() and not state.isComplete() and state.briefText:
                subState = state.briefText.split()[0]
                if subState != "RUN":
                    classification.append(subState)
            classifiers.addClassification(classification)
            return classifiers

        if not state.isSaveable() or state.warnOnSave(): # If it's not saveable, don't classify it by the files
            details = state.getTypeBreakdown()[1]
            self.diag.info("Adding unsaveable : " + catDesc + " " + details)
            classifiers.addClassification([ "Failed", catDesc, details ])
            return classifiers

        comparisons = state.getComparisons()
        for fileComp in filter(lambda c: c.getType() == "failure", comparisons):
            summary = self.getFileSummary(fileComp)
            fileClass = [ "Failed", self.getDifferenceType(fileComp), (summary, fileComp.stem) ]

            filteredDiff = self.getFilteredDiff(fileComp)
            if filteredDiff is not None:
                groupNames, summaryDiffs = self.diffStore.setdefault(summary, ({}, OrderedDict()))
                testList, groupName = summaryDiffs.setdefault(filteredDiff, ([], None))
                if test not in testList:
                    testList.append(test)
                if len(testList) > 1 and groupName is None:
                    groupName = self.setGroupName(groupNames, summaryDiffs, filteredDiff)
                if groupName:
                    fileClass.append(("Group " + groupName, fileComp.stem))

            self.diag.info("Adding file classification for " + repr(fileComp) + " = " + repr(fileClass))
            classifiers.addClassification(fileClass)

        for fileComp in filter(lambda c: c.getType() != "failure", comparisons):
            summary = fileComp.getSummary(includeNumbers=False)
            desc = self.getCategoryDescription(state, summary)
            stem = fileComp.stem
            fileClass = [ "Failed", "Performance differences", (desc, stem) ]
            toleranceRange = fileComp.getToleranceMultipleRange(test)
            if toleranceRange:
                fileClass.append((toleranceRange, stem))
            self.diag.info("Adding file classification for " + repr(fileComp) + " = " + repr(fileClass))
            classifiers.addClassification(fileClass)

        return classifiers

    def extractRepeats(self, filteredDiff):
        size = len(filteredDiff)
        smallPrimes = [ 2, 3, 5, 7, 11, 13, 17, 19 ] # Surely we won't repeat stuff more than 20 times :)
        for prime in smallPrimes:
            if size > prime and size % prime == 0:
                chunkSize = size / prime
                firstPart = filteredDiff[:chunkSize]
                if filteredDiff == firstPart * prime:
                    return firstPart, prime
        return None, None

    def setGroupName(self, groupNames, summaryDiffs, filteredDiff):
        groupName = self.getGroupName(groupNames, summaryDiffs, filteredDiff)
        groupNames[groupName] = filteredDiff
        tests = summaryDiffs[filteredDiff][0] if filteredDiff in summaryDiffs else []
        summaryDiffs[filteredDiff] = (tests, groupName)
        return groupName
                    
    def getGroupName(self, groupNames, summaryDiffs, filteredDiff):
        self.diag.info("Getting group name for " + repr(filteredDiff))
        singleVersion, timesRepeated = self.extractRepeats(filteredDiff)
        if singleVersion:
            _, group = summaryDiffs.get(singleVersion, (None, None))
            if group is None:
                group = self.setGroupName(groupNames, summaryDiffs, singleVersion)
            if "*" in group:
                core, timeStr = group.split("*")
                return core + "*" + str(timesRepeated * int(timeStr))
            else:
                return str(group) + "*" + str(timesRepeated)
        else:
            group = len(groupNames) + 1
            return str(group)
    
    def notifySelectInGroup(self, fileComp):
        summary = self.getFileSummary(fileComp)
        _, summaryDiffs = self.diffStore.get(summary, {})
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
            testCount = self.treeModel.get_value(iter, 1)
            self.treeModel.set_value(iter, 1, testCount - 1)
            if testCount == 1:
                self.treeModel.set_value(iter, 3, "white")
                self.treeModel.set_value(iter, 4, "")
            allTests = self.treeModel.get_value(iter, 5)
            allTests.remove(test)
            self.diag.info("Removing test " + repr(test) + " from node " + self.treeModel.get_value(iter, 0))
            self.treeModel.set_value(iter, 5, allTests)

    def removeFromDiffStore(self, test):
        for _, fileInfo in self.diffStore.values():
            for testList, _ in fileInfo.values():
                if test in testList:
                    testList.remove(test)

    def insertTest(self, test, state, changeDesc, incrementCount):
        self.classifications[test] = []
        classifiers = self.getClassifiers(test, state, changeDesc)
        nodeClassifier = classifiers.keys()[0]
        defaultColour, defaultVisibility = self.getCategorySettings(state.category, nodeClassifier, classifiers)
        return self.addTestForNode(test, defaultColour, defaultVisibility, nodeClassifier, classifiers, incrementCount)

    def getCategorySettings(self, category, nodeClassifier, classifiers):
        # Use the category description if there is only one level, otherwise rely on the status names
        if len(classifiers.get(nodeClassifier)) == 0 or category in [ "failure", "success" ]:
            return guiutils.guiConfig.getTestColour(category), guiutils.guiConfig.showCategoryByDefault(category)
        else:
            return None, True

    def updateTestAppearance(self, test, state, changeDesc, colour):
        resultType, summary = state.getTypeBreakdown()
        catDesc = self.getCategoryDescription(state, resultType)
        mainColour = guiutils.guiConfig.getTestColour(catDesc, guiutils.guiConfig.getTestColour(resultType))
        # Don't change suite states when unmarking tests
        updateSuccess = state.hasSucceeded() and changeDesc != "unmarked"
        self.notify("TestAppearance", test, summary, mainColour, colour, updateSuccess, "save" in changeDesc)
        self.notify("Visibility", [ test ], self.shouldBeVisible(test))

    def getInitialTestsForNode(self, test, parentIter, nodeClassifier):
        if nodeClassifier.startswith("Group "):
            groupName = nodeClassifier[6:]
            parentName = self.treeModel.get_value(parentIter, 0)
            groupNames, summaryDiffs = self.diffStore.get(parentName)
            filteredDiff = groupNames.get(groupName)
            if filteredDiff is not None:
                testList = summaryDiffs[filteredDiff][0]
                return copy(testList)
        return [ test ]

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
            visibility = guiutils.guiConfig.showCategoryByDefault(nodeClassifier, parentHidden=not defaultVisibility)
            initialTests = self.getInitialTestsForNode(test, parentIter, nodeClassifier)
            nodeIter = self.addNewIter(nodeClassifier, parentIter, colour, visibility, len(initialTests), initialTests, fileStem)
            for initTest in initialTests:
                self.diag.info("New node " + nodeClassifier + ", colour = " + repr(colour) + ", visible = " + repr(visibility) + " : add " + repr(initTest))
                self.classifications[initTest].append(nodeIter)

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
            follower = self.findChildIter(parentIter, lambda name: plugins.padNumbersWithZeroes(name) > paddedClassifier)
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
        if "save" in changeDesc or "marked" in changeDesc or "recalculated" in changeDesc:
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
        self.diag.info("Visibility for " + repr(test) + " : iters " + repr(map(self.treeModel.get_path, visibilityIters)))
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
            
            if selection.path_is_selected(path):
                #WORKAROUND: selection.unselect_path(path) Doesn't seem to work here
                selection.set_mode(gtk.SELECTION_SINGLE)
                selection.set_mode(gtk.SELECTION_MULTIPLE)

    def notifyResetVisibility(self):
        self.diag.info("Resetting visibility from current status")
        testsForReset = []
        self.treeModel.foreach(self.resetNodeVisibility, testsForReset)
        self.notify("Visibility", testsForReset, True)

    def resetNodeVisibility(self, model, dummyPath, iter, testsForReset):
        if model.get_value(iter, 2) and not model.iter_has_child(iter):
            testsForReset += model.get_value(iter, 5)
