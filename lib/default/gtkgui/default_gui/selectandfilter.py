
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
    def __init__(self, allApps, dynamic, *args):
        guiplugins.ActionTabGUI.__init__(self, allApps)
        AllTestsHandler.__init__(self)
        self.dynamic = dynamic
        self.filterAction = gtk.Action("Filter", "Filter", \
                                       self.getFilterTooltip(), self.getStockId())
        self.filterAction.connect("activate", self.filterTests)
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
        self.filteringGroup = plugins.OptionGroup("Filtering")
        currFilterDesc = ["Show all tests which match the criteria, and hide all those that do not.",
                          "Hide all tests which do not match the criteria. Do not show any tests that aren't already shown.",
                          "Show all tests which match the criteria. Do not hide any tests that are currently shown." ]
        self.filteringGroup.addSwitch("current_filtering", options = [ "Discard", "Refine", "Extend" ], description=currFilterDesc)
        excludeKeys = set(self.optionGroup.keys()) # remember these so we don't try and save them to selections
        self.addApplicationOptions(allApps, self.optionGroup)
        if self.dynamic:
            self.addSwitch("std", options = [ "Use test-files from current run", "Use stored test-files" ], description = [ "When searching using 'test-files containing', look in the results of tests in the current run", "When searching using 'test-files containing', look in the stored results, i.e. the same search as would be done in the static GUI" ])
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

    def setRadioButtonName(self, radioButton, option, optionGroup):
        radioButton.set_name(option + " for " + optionGroup.name)

    def findDefaultTestFile(self, allStems):
        if len(allStems) == 0:
            return "output"
        for app in self.validApps:
            logFile = app.getConfigValue("log_file")
            if logFile in allStems:
                return logFile
        return allStems[0]

    def findAllStems(self):
        stems = set()
        defStems = set()
        importantStems = set()
        for suite in self.rootTestSuites:
            defStems.update(suite.defFileStems())
            importantStems.update(suite.getCompositeConfigValue("gui_entry_options", "test-file_to_search"))
            exclude = suite.app.getDataFileNames() + [ "file_edits" ]
            predicate = lambda stem, vset: stem not in exclude and (stem in defStems or len(vset) > 0)
            for test in suite.testCaseList():
                stems.update(test.dircache.findAllStems(predicate))
        defStems.intersection_update(stems)
        stems.difference_update(defStems)
        self.selectDiag.info("Found important stems " + repr(importantStems))
        stems.difference_update(importantStems)
        subLists = [ importantStems, defStems, stems ]
        if self.dynamic:
            subLists.insert(0, [ "free_text" ])
        return self.makeStemList(subLists)

    def makeStemList(self, subLists):
        separator = "-" * 10
        allStems = sorted(subLists[0])
        for extraList in subLists[1:]:
            if len(allStems) and len(extraList):
                allStems.append(separator)
            allStems += sorted(extraList)
        return allStems
    
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
        optionMap = self.optionGroup.getOptionValueMap()
        useTmpFiles = self.optionGroup.getOption("std") and not optionMap.has_key("std")
        return app.getFilterList(self.rootTestSuites, optionMap, useTmpFiles=useTmpFiles)
    
    def makeNewSelection(self):
        # Get strategy. 0 = discard, 1 = refine, 2 = extend, 3 = exclude
        strategy = self.selectionGroup.getSwitchValue("current_selection")
        return self._makeNewSelection(strategy)

    def notifyReset(self, *args):
        self.optionGroup.reset()
        self.selectionGroup.reset()
        self.filteringGroup.reset()

    def _makeNewSelection(self, strategy=0):
        selectedTests = []
        suitesToTry = self.getSuitesToTry()
        for suite in self.rootTestSuites:
            if suite in suitesToTry:
                filters = self.getFilterList(suite.app)
                reqTests = self.getRequestedTests(suite, filters, strategy)
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

    def matchesVersions(self, test):
        versionSelection = self.optionGroup.getOptionValue("vs")
        if len(versionSelection) == 0:
            return True
        
        versions = versionSelection.split(".")
        return self.allVersionsMatch(versions, test.app.versions)        

    def getSuitesToTry(self):
        # If only some of the suites present match the version selection, only consider them.
        # If none of them do, try to filter them all
        toTry = filter(self.matchesVersions, self.rootTestSuites)
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
    
    def getRequestedTests(self, suite, filters, strategy):
        self.notify("ActionProgress", "") # Just to update gui ...
        if strategy == 1: # refine, don't check the whole suite
            return filter(lambda test: test.app is suite.app and test.isAcceptedByAll(filters), self.currTestSelection)
        else:
            return self.getRequestedTestsFromSuite(suite, filters)
        
    def getRequestedTestsFromSuite(self, suite, filters):
        if not suite.isAcceptedByAll(filters):
            return []
        else:
            if suite.classId() == "test-suite":
                tests = []
                for subSuite in self.findTestCaseList(suite):
                    self.notify("ActionProgress", "") # Just to update gui ...
                    tests += self.getRequestedTestsFromSuite(subSuite, filters)
                return tests
            else:
                return [ suite ]

    def combineWithPrevious(self, reqTests, app, strategy):
        # Strategies: 0 - discard, 1 - refine, 2 - extend, 3 - exclude
        # If we want to extend selection, we include test if it was previsouly selected,
        # even if it doesn't fit the current criterion
        if strategy < 2:
            return reqTests
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
        self.setTooltipText(button, self.getFilterTooltip())
        return button

    def createFrame(self, name, group, button):
        frame = gtk.Frame(name)
        frame.set_label_align(0.5, 0.5)
        frame.set_shadow_type(gtk.SHADOW_IN)
        frameBox = gtk.VBox()
        self.fillVBox(frameBox, group)
        self.addCentralButton(frameBox, button, padding=8)
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
        self.addCentralButton(vbox, self.createResetButton(), padding=16)


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
    def __init__(self, allApps, dynamic, *args):
        guiplugins.BasicActionGUI.__init__(self, allApps, dynamic, *args)
        AllTestsHandler.__init__(self)
        self.dynamic = dynamic
        
    def _getTitle(self):
        return "Show all"

    def messageBeforePerform(self):
        return "Showing all tests..."

    def getTooltip(self):
        return "Show all tests"

    def getSignalsSent(self):
        return [ "Visibility", "ResetVisibility" ]

    def performOnCurrent(self):
        if self.dynamic:
            self.notify("ResetVisibility")
        else:
            self.notify("Visibility", self.findAllTests(), True)


class SaveSelection(guiplugins.ActionDialogGUI):
    def __init__(self, allApps, dynamic, *args):
        guiplugins.ActionDialogGUI.__init__(self, allApps, dynamic, *args)
        possibleDirs = self.getFilterFileDirs(allApps, useOwnTmpDir=False)
        self.addOption("f", "enter filter-file name =", possibleDirs=possibleDirs, saveFile=True)
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
        possibleDirs = self.getFilterFileDirs(allApps, useOwnTmpDir=True)
        self.addOption("f", "select filter-file", possibleDirs=possibleDirs, selectFile=True)
        self.rootTestSuites = []

    def addSuites(self, suites):
        self.rootTestSuites += suites
    def isActiveOnCurrent(self, *args):
        return not self.noApps
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
    return [ SaveSelection, SelectTests, HideUnselected, HideSelected, ShowAll, LoadSelection ]
