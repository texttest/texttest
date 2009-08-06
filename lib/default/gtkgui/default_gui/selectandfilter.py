
"""
Actions for managing selections and filterings of the test tree
"""

import gtk, plugins, os, operator, logging
from default.gtkgui import guiplugins # from .. import guiplugins when we drop Python 2.4 support

class AllTestsHandler:
    def __init__(self):
        self.rootTestSuites = []
    def addSuites(self, suites):
        self.rootTestSuites += suites
    def findAllTests(self):
        return reduce(operator.add, (suite.testCaseList() for suite in self.rootTestSuites), [])
    def findTestsNotIn(self, tests):
        return filter(lambda test: test not in tests, self.findAllTests())


class SelectTests(guiplugins.ActionTabGUI, AllTestsHandler):
    def __init__(self, allApps, *args):
        guiplugins.ActionTabGUI.__init__(self, allApps)
        AllTestsHandler.__init__(self)
        self.filterAction = gtk.Action("Filter", "Filter", \
                                       self.getFilterTooltip(), self.getStockId())
        guiplugins.scriptEngine.connect(self.getFilterTooltip(), "activate", self.filterAction, self.filterTests)
        self.selectDiag = logging.getLogger("Select Tests")
        self.addOption("vs", "Tests for version", description="Select tests for a specific version.",
                       possibleValues=self.getPossibleVersions(allApps))
        self.selectionGroup = plugins.OptionGroup(self.getTabTitle())
        self.selectionGroup.addSwitch("select_in_collapsed_suites", "Select in collapsed suites", 0, description="Select in currently collapsed suites as well?")
        currSelectDesc = ["Unselect all currently selected tests before applying the new selection criteria.",
                          "Apply the new selection criteria only to the currently selected tests, to obtain a subselection.",
                          "Keep the currently selected tests even if they do not match the new criteria, and extend the selection with all other tests which meet the new criteria.",
                          "After applying the new selection criteria to all tests, unselect the currently selected tests, to exclude them from the new selection." ]
        self.selectionGroup.addSwitch("current_selection", options = [ "Discard", "Refine", "Extend", "Exclude"],
                                      description=currSelectDesc)
        self.filteringGroup = plugins.OptionGroup(self.getTabTitle())
        currFilterDesc = ["Show all tests which match the criteria, and hide all those that do not.",
                          "Hide all tests which do not match the criteria. Do not show any tests that aren't already shown.",
                          "Show all tests which match the criteria. Do not hide any tests that are currently shown." ]
        self.filteringGroup.addSwitch("current_filtering", options = [ "Discard", "Refine", "Extend" ], description=currFilterDesc)
        excludeKeys = set(self.optionGroup.keys()) # remember these so we don't try and save them to selections
        self.addApplicationOptions(allApps)
        self.appKeys = set(self.optionGroup.keys())
        self.appKeys.difference_update(excludeKeys)

    def addToGroups(self, actionGroup, accelGroup):
        guiplugins.ActionTabGUI.addToGroups(self, actionGroup, accelGroup)
        self.filterAccel = self._addToGroups("Filter", self.filterAction, actionGroup, accelGroup)

    def notifyAllRead(self, *args):
        allStems = self.findAllStems()
        defaultTestFile = self.findDefaultTestFile(allStems)
        self.notify("AllStems", allStems, defaultTestFile)
        self.optionGroup.setValue("grepfile", defaultTestFile)
        self.optionGroup.setPossibleValues("grepfile", allStems)

    def findDefaultTestFile(self, allStems):
        if len(allStems) == 0:
            return "output"
        for app in self.validApps:
            logFile = app.getConfigValue("log_file")
            if logFile in allStems:
                return logFile
        return allStems[0]

    def findAllStems(self):
        stems = {}
        for suite in self.rootTestSuites:
            exclude = suite.app.getDataFileNames() + [ "file_edits" ]
            for test in suite.testCaseList():
                for stem in test.dircache.findAllStems(exclude):
                    if stem in stems:
                        stems[stem] += 1
                    else:
                        stems[stem] = 1
        return sorted(stems.keys(), lambda x,y: cmp(stems.get(y), stems.get(x)))
    def getPossibleVersions(self, allApps):
        possVersions = []
        for app in allApps:
            for possVersion in self._getPossibleVersions(app):
                if possVersion not in possVersions:
                    possVersions.append(possVersion)
        return possVersions
    def _getPossibleVersions(self, app):
        fullVersion = app.getFullVersion()
        extraVersions = app.getExtraVersions()
        if len(fullVersion) == 0:
            return [ "<default>" ] + extraVersions
        else:
            return [ fullVersion ] + [ fullVersion + "." + extra for extra in extraVersions ]
    def isActiveOnCurrent(self, *args):
        return True
    def getSignalsSent(self):
        return [ "SetTestSelection", "Visibility", "AllStems" ]
    def _getStockId(self):
        return "find"
    def _getTitle(self):
        return "_Select"
    def getTooltip(self):
        return "Select indicated tests"
    def getTabTitle(self):
        return "Selection"
    def getGroupTabTitle(self):
        return "Selection"
    def messageBeforePerform(self):
        return "Selecting tests ..."
    def messageAfterPerform(self):
        return "Selected " + self.describeTests() + "."
    # No messageAfterPerform necessary - we update the status bar when the selection changes inside TextTestGUI
    def getFilterList(self, app):
        return app.getFilterList(self.rootTestSuites, self.optionGroup.getOptionValueMap())
    def makeNewSelection(self):
        # Get strategy. 0 = discard, 1 = refine, 2 = extend, 3 = exclude
        strategy = self.selectionGroup.getSwitchValue("current_selection")
        return self._makeNewSelection(strategy)

    def notifyReset(self):
        self.optionGroup.reset()
        self.selectionGroup.reset()
        self.filteringGroup.reset()

    def _makeNewSelection(self, strategy=0):
        selectedTests = []
        suitesToTry = self.getSuitesToTry()
        for suite in self.rootTestSuites:
            if suite in suitesToTry:
                filters = self.getFilterList(suite.app)
                reqTests = self.getRequestedTests(suite, filters)
                newTests = self.combineWithPrevious(reqTests, suite.app, strategy)
            else:
                newTests = self.combineWithPrevious([], suite.app, strategy)

            guiplugins.guilog.info("Selected " + str(len(newTests)) + " out of a possible " + str(suite.size()))
            selectedTests += newTests
        return selectedTests

    def performOnCurrent(self):
        newSelection = self.makeNewSelection()
        criteria = " ".join(self.getCommandLineArgs(self.optionGroup, onlyKeys=self.appKeys))
        self.notify("SetTestSelection", newSelection, criteria, self.selectionGroup.getSwitchValue("select_in_collapsed_suites"))

    def getSuitesToTry(self):
        # If only some of the suites present match the version selection, only consider them.
        # If none of them do, try to filter them all
        versionSelection = self.optionGroup.getOptionValue("vs")
        if len(versionSelection) == 0:
            return self.rootTestSuites
        versions = versionSelection.split(".")
        toTry = []
        for suite in self.rootTestSuites:
            if self.allVersionsMatch(versions, suite.app.versions):
                toTry.append(suite)
        if len(toTry) == 0:
            return self.rootTestSuites
        else:
            return toTry
    def allVersionsMatch(self, versions, appVersions):
        for version in versions:
            if version == "<default>":
                if len(appVersions) > 0:
                    return False
            else:
                if not version in appVersions:
                    return False
        return True
    def getRequestedTests(self, suite, filters):
        self.notify("ActionProgress", "") # Just to update gui ...
        if not suite.isAcceptedByAll(filters):
            return []
        if suite.classId() == "test-suite":
            tests = []
            for subSuite in self.findTestCaseList(suite):
                tests += self.getRequestedTests(subSuite, filters)
            return tests
        else:
            return [ suite ]
    def combineWithPrevious(self, reqTests, app, strategy):
        # Strategies: 0 - discard, 1 - refine, 2 - extend, 3 - exclude
        # If we want to extend selection, we include test if it was previsouly selected,
        # even if it doesn't fit the current criterion
        if strategy == 0:
            return reqTests
        elif strategy == 1:
            return filter(lambda test: test in self.currTestSelection, reqTests)
        else:
            extraRequested = filter(lambda test: test not in self.currTestSelection, reqTests)
            if strategy == 2:
                selectedThisApp = filter(lambda test: test.app is app, self.currTestSelection)
                return extraRequested + selectedThisApp
            elif strategy == 3:
                return extraRequested
    def findTestCaseList(self, suite):
        version = self.optionGroup.getOptionValue("vs")
        if len(version) == 0:
            return suite.testcases

        if version == "<default>":
            version = ""

        fullVersion = suite.app.getFullVersion()
        versionToUse = self.findCombinedVersion(version, fullVersion)
        self.selectDiag.info("Trying to get test cases for " + repr(suite) + ", version " + versionToUse)
        return suite.findTestCases(versionToUse)

    def findCombinedVersion(self, version, fullVersion):
        combined = version
        if len(fullVersion) > 0 and len(version) > 0:
            parts = version.split(".")
            for appVer in fullVersion.split("."):
                if not appVer in parts:
                    combined += "." + appVer
        return combined

    def filterTests(self, *args):
        self.notify("Status", "Filtering tests ...")
        self.notify("ActionStart")
        newSelection = self._makeNewSelection()
        strategy = self.filteringGroup.getSwitchValue("current_filtering")
        toShow = self.findTestsToShow(newSelection, strategy)
        self.notify("Visibility", toShow, True)
        self.notify("ActionProgress", "")
        toHide = self.findTestsToHide(newSelection, strategy)
        self.notify("Visibility", toHide, False)
        self.notify("ActionStop")
        self.notify("Status", "Changed filtering by showing " + str(len(toShow)) +
                    " tests and hiding " + str(len(toHide)) + ".")

    def findTestsToShow(self, newSelection, strategy):
        if strategy == 0 or strategy == 2:
            return newSelection
        else:
            return []

    def findTestsToHide(self, newSelection, strategy):
        if strategy == 0 or strategy == 1:
            return self.findTestsNotIn(newSelection)
        else:
            return []

    def getFilterTooltip(self):
        return "filter tests to show only those indicated"

    def createFilterButton(self):
        button = gtk.Button()
        self.filterAction.connect_proxy(button)
        button.set_image(gtk.image_new_from_stock(self.getStockId(), gtk.ICON_SIZE_BUTTON))
        self.tooltips.set_tip(button, self.getFilterTooltip())
        return button

    def createFrame(self, name, group, button):
        frame = gtk.Frame(name)
        frame.set_label_align(0.5, 0.5)
        frame.set_shadow_type(gtk.SHADOW_IN)
        frameBox = gtk.VBox()
        self.fillVBox(frameBox, group)
        self.addCentralButton(frameBox, button)
        frame.add(frameBox)
        return frame

    def getNewSwitchName(self, switchName, optionGroup):
        if len(switchName):
            return switchName
        elif optionGroup is self.selectionGroup:
            return "Current selection"
        elif optionGroup is self.filteringGroup:
            return "Current filtering"
        else:
            return switchName

    def getNaming(self, switchName, cleanOption, optionGroup):
        return guiplugins.ActionTabGUI.getNaming(self, self.getNewSwitchName(switchName, optionGroup), cleanOption, optionGroup)

    def createButtons(self, vbox):
        selFrame = self.createFrame("Selection", self.selectionGroup, self.createButton())
        vbox.pack_start(selFrame, fill=False, expand=False, padding=8)
        filterFrame = self.createFrame("Filtering", self.filteringGroup, self.createFilterButton())
        vbox.pack_start(filterFrame, fill=False, expand=False, padding=8)


class HideSelected(guiplugins.ActionGUI,AllTestsHandler):
    def __init__(self, *args):
        guiplugins.ActionGUI.__init__(self, *args)
        AllTestsHandler.__init__(self)
    def _getTitle(self):
        return "Hide selected"
    def messageBeforePerform(self):
        return "Hiding all tests that are currently selected ..."
    def getTooltip(self):
        return "Hide all tests that are currently selected"
    def getSignalsSent(self):
        return [ "Visibility" ]
    def performOnCurrent(self):
        self.notify("Visibility", self.currTestSelection, False)


class HideUnselected(guiplugins.ActionGUI,AllTestsHandler):
    def __init__(self, *args):
        guiplugins.ActionGUI.__init__(self, *args)
        AllTestsHandler.__init__(self)
    def _getTitle(self):
        return "Show only selected"
    def messageBeforePerform(self):
        return "Showing only tests that are currently selected ..."
    def getTooltip(self):
        return "Show only tests that are currently selected"
    def getSignalsSent(self):
        return [ "Visibility" ]
    def performOnCurrent(self):
        self.notify("Visibility", self.findTestsNotIn(self.currTestSelection), False)


class ShowAll(guiplugins.BasicActionGUI,AllTestsHandler):
    def __init__(self, *args):
        guiplugins.BasicActionGUI.__init__(self, *args)
        AllTestsHandler.__init__(self)
    def _getTitle(self):
        return "Show all"
    def messageBeforePerform(self):
        return "Showing all tests..."
    def getTooltip(self):
        return "Show all tests"
    def getSignalsSent(self):
        return [ "Visibility" ]
    def performOnCurrent(self):
        self.notify("Visibility", self.findAllTests(), True)


class SaveSelection(guiplugins.ActionDialogGUI):
    def __init__(self, allApps, dynamic, *args):
        guiplugins.ActionDialogGUI.__init__(self, allApps, dynamic, *args)
        self.addOption("f", "enter filter-file name =", possibleDirs=self.getFilterFileDirs(allApps), saveFile=True)
        if not dynamic:
            # In the static GUI case, we also want radiobuttons specifying
            # whether we want to save the actual tests, or the selection criteria.
            self.addSwitch("tests", "Save", options= [ "_List of selected tests", "C_riteria entered in the Selection tab\n(Might not match current selection, if it has been modified)" ])
        self.selectionCriteria = ""
        self.dynamic = dynamic
        self.rootTestSuites = []
    def addSuites(self, suites):
        self.rootTestSuites += suites
    def _getStockId(self):
        return "save-as"
    def _getTitle(self):
        return "S_ave Selection..."
    def getTooltip(self):
        return "Save selected tests in file"
    def getSignalsSent(self):
        return [ "WriteTestIfSelected" ]

    def writeTestList(self, file):
        file.write("-tp ")
        for suite in self.rootTestSuites:
            file.write("appdata=" + suite.app.name + suite.app.versionSuffix() + "\n")
            for test in suite.testCaseList():
                self.notify("WriteTestIfSelected", test, file)
    
    def notifySetTestSelection(self, tests, criteria="", *args):
        self.selectionCriteria = criteria
    
    def getConfirmationMessage(self):
        fileName = self.optionGroup.getOptionValue("f")
        if fileName and os.path.isfile(fileName):
            return "\nThe file \n" + fileName + "\nalready exists.\n\nDo you want to overwrite it?\n"

    def getConfirmationDialogSettings(self):
        return gtk.STOCK_DIALOG_QUESTION, "Query"

    def notifySaveSelection(self, fileName, writeCriteria=False):
        try:
            file = open(fileName, "w")
            if writeCriteria:
                file.write(self.selectionCriteria + "\n")
            else:
                self.writeTestList(file)
            file.close()
        except IOError, e:
            raise plugins.TextTestError, "\nFailed to save selection:\n" + str(e) + "\n"
       
    def getFileName(self):
        fileName = self.optionGroup.getOptionValue("f")
        if not fileName:
            raise plugins.TextTestError, "Cannot save selection - no file name specified"
        elif os.path.isdir(fileName):
            raise plugins.TextTestError, "Cannot save selection - existing directory specified"
        else:
            return fileName
        
    def performOnCurrent(self):
        fileName = self.getFileName()
        writeCriteria = not self.dynamic and self.optionGroup.getSwitchValue("tests")
        self.notifySaveSelection(fileName, writeCriteria)        

    def messageAfterPerform(self):
        return "Saved " + self.describeTests() + " in file '" + self.optionGroup.getOptionValue("f") + "'."


class LoadSelection(guiplugins.ActionDialogGUI):
    def __init__(self, allApps, *args):
        guiplugins.ActionDialogGUI.__init__(self, allApps, *args)
        self.addOption("f", "select filter-file", possibleDirs=self.getFilterFileDirs(allApps), selectFile=True)
        self.rootTestSuites = []

    def addSuites(self, suites):
        self.rootTestSuites += suites
    def isActiveOnCurrent(self, *args):
        return True
    def getSignalsSent(self):
        return [ "SetTestSelection" ]
    def _getStockId(self):
        return "open"
    def _getTitle(self):
        return "_Load Selection..."
    def getTooltip(self):
        return "Load test selection from file"
    def performOnCurrent(self):
        fileName = self.optionGroup.getOptionValue("f")
        if fileName:
            newSelection = self.makeNewSelection(fileName)
            guiplugins.guilog.info("Loaded " + str(len(newSelection)) + " tests from " + fileName)
            self.notify("SetTestSelection", newSelection, "-f " + fileName, True)
            self.notify("Status", "Loaded test selection from file '" + fileName + "'.")
        else:
            self.notify("Status", "No test selection loaded.")

    def makeNewSelection(self, fileName):
        tests = []
        for suite in self.rootTestSuites:
            filters = suite.app.getFiltersFromFile(fileName, self.rootTestSuites)
            tests += suite.testCaseList(filters)
        return tests
    def getResizeDivisors(self):
        # size of the dialog
        return 1.2, 1.7

    def messageBeforePerform(self):
        return "Loading test selection ..."
    def messageAfterPerform(self):
        pass


def getInteractiveActionClasses(dynamic):
    classes = [ SaveSelection ]
    if not dynamic:
        classes += [ SelectTests, HideUnselected, HideSelected, ShowAll,
                     LoadSelection ]
    return classes
