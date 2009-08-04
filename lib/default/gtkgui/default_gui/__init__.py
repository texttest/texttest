"""
The default configuration's worth of action GUIs, implementing the interfaces in guiplugins
"""


import gtk, helpdialogs, adminactions, plugins, os, sys, shutil, operator, logging
from default.gtkgui import guiplugins, guiutils # from .. import guiplugins, guiutils when we drop Python 2.4 support
from copy import deepcopy
from ndict import seqdict

# For backwards compatibility, don't require derived modules to know the internal structure here
from adminactions import *
from fileviewers import *

class Quit(guiplugins.BasicActionGUI):
    def __init__(self, *args):
        guiplugins.BasicActionGUI.__init__(self, *args)
        self.annotation = ""
    def _getStockId(self):
        return "quit"
    def _getTitle(self):
        return "_Quit"
    def isActiveOnCurrent(self, *args):
        return True
    def getSignalsSent(self):
        return [ "Quit" ]
    def performOnCurrent(self):
        self.notify("Quit")
    def notifyAnnotate(self, annotation):
        self.annotation = annotation
    def messageAfterPerform(self):
        pass # GUI isn't there to show it
    def getConfirmationMessage(self):
        message = ""
        if self.annotation:
            message = "You annotated this GUI, using the following message : \n" + self.annotation + "\n"
        runningProcesses = guiplugins.processMonitor.listRunningProcesses()
        if len(runningProcesses) > 0:
            message += "\nThese processes are still running, and will be terminated when quitting: \n\n   + " + \
                       "\n   + ".join(runningProcesses) + "\n"
        if message:
            message += "\nQuit anyway?\n"
        return message


# Plugin for saving tests (standard)
class SaveTests(guiplugins.ActionDialogGUI):
    def __init__(self, allApps, *args):
        guiplugins.ActionDialogGUI.__init__(self, allApps, *args)
        self.directAction = gtk.Action("Save", "_Save", \
                                       self.getDirectTooltip(), self.getStockId())
        guiutils.scriptEngine.connect(self.getDirectTooltip(), "activate", self.directAction, self._respond)
        self.directAction.set_property("sensitive", False)
        self.addOption("v", "Version to save")
        self.addOption("old", "Version to save previous results as")
        self.addSwitch("over", "Replace successfully compared files also", 0)
        if self.hasPerformance(allApps):
            self.addSwitch("ex", "Save", 1, ["Average performance", "Exact performance"])

    def getDialogTitle(self):
        stemsToSave = self.getStemsToSave()
        saveDesc = "Saving " + str(len(self.currTestSelection)) + " tests"
        if len(stemsToSave) > 0:
            saveDesc += ", only files " + ",".join(stemsToSave)
        return saveDesc

    def _getStockId(self):
        return "save"
    def _getTitle(self):
        return "Save _As..."
    def getTooltip(self):
        return "Save results with non-default settings"
    def getDirectTooltip(self):
        return "Save results for selected tests"
    def messageAfterPerform(self):
        pass # do it in the method

    def addToGroups(self, actionGroup, accelGroup):
        self.directAccel = self._addToGroups("Save", self.directAction, actionGroup, accelGroup)
        guiplugins.ActionDialogGUI.addToGroups(self, actionGroup, accelGroup)

    def setSensitivity(self, newValue):
        self._setSensitivity(self.directAction, newValue)
        self._setSensitivity(self.gtkAction, newValue)
        if newValue:
            self.updateOptions()

    def getConfirmationMessage(self):
        testsForWarn = filter(lambda test: test.stateInGui.warnOnSave(), self.currTestSelection)
        if len(testsForWarn) == 0:
            return ""
        message = "You have selected tests whose results are partial or which are registered as bugs:\n"
        for test in testsForWarn:
            message += "  Test '" + test.uniqueName + "' " + test.stateInGui.categoryRepr() + "\n"
        message += "Are you sure you want to do this?\n"
        return message

    def getSaveableTests(self):
        return filter(lambda test: test.stateInGui.isSaveable(), self.currTestSelection)
    def updateOptions(self):
        defaultSaveOption = self.getDefaultSaveOption()
        versionOption = self.optionGroup.getOption("v")
        currOption = versionOption.defaultValue
        newVersions = self.getPossibleVersions()
        currVersions = versionOption.possibleValues
        if defaultSaveOption == currOption and newVersions == currVersions:
            return False
        self.optionGroup.setOptionValue("v", defaultSaveOption)
        self.diag.info("Setting default save version to " + defaultSaveOption)
        self.optionGroup.setPossibleValues("v", newVersions)
        return True
    def getDefaultSaveOption(self):
        saveVersions = self.getSaveVersions()
        if saveVersions.find(",") != -1:
            return "<default> - " + saveVersions
        else:
            return saveVersions
    def getPossibleVersions(self):
        extensions = []
        for app in self.currAppSelection:
            for ext in app.getSaveableVersions():
                if not ext in extensions:
                    extensions.append(ext)
        # Include the default version always
        extensions.append("")
        return extensions
    def getSaveVersions(self):
        if self.isAllNew():
            return ""

        saveVersions = []
        for app in self.currAppSelection:
            ver = self.getDefaultSaveVersion(app)
            if not ver in saveVersions:
                saveVersions.append(ver)
        return ",".join(saveVersions)
    def getDefaultSaveVersion(self, app):
        return app.getFullVersion(forSave = 1)
    def hasPerformance(self, apps):
        for app in apps:
            if app.hasPerformance():
                return True
        return False
    def getExactness(self):
        return int(self.optionGroup.getSwitchValue("ex", 1))
    def isAllNew(self):
        for test in self.getSaveableTests():
            if not test.stateInGui.isAllNew():
                return False
        return True
    def getVersion(self, test):
        versionString = self.optionGroup.getOptionValue("v")
        if versionString.startswith("<default>"):
            return self.getDefaultSaveVersion(test.app)
        else:
            return versionString
    def isActiveOnCurrent(self, test=None, state=None):
        if state and state.isSaveable():
            return True
        for seltest in self.currTestSelection:
            if seltest is not test and seltest.stateInGui.isSaveable():
                return True
        return False
    def getStemsToSave(self):
        return [ os.path.basename(fileName).split(".")[0] for fileName, comparison in self.currFileSelection ]
    def performOnCurrent(self):
        backupVersion = self.optionGroup.getOptionValue("old")
        if backupVersion and backupVersion == self.optionGroup.getOptionValue("v"):
            raise plugins.TextTestError, "Cannot backup to the same version we're trying to save! Choose another name."
        
        saveDesc = ", exactness " + str(self.getExactness())
        stemsToSave = self.getStemsToSave()
        if len(stemsToSave) > 0:
            saveDesc += ", only " + ",".join(stemsToSave)
        overwriteSuccess = self.optionGroup.getSwitchValue("over")
        if overwriteSuccess:
            saveDesc += ", overwriting both failed and succeeded files"

        tests = self.getSaveableTests()
        # Calculate the versions beforehand, as saving tests can change the selection,
        # which can affect the default version calculation...
        testsWithVersions = [ (test, self.getVersion(test)) for test in tests ]
        testDesc = str(len(tests)) + " tests"
        self.notify("Status", "Saving " + testDesc + " ...")
        try:
            for test, version in testsWithVersions:
                testComparison = test.stateInGui
                testComparison.setObservers(self.observers)
                testComparison.save(test, self.getExactness(), version, overwriteSuccess, stemsToSave, backupVersion)
                newState = testComparison.makeNewState(test.app, "saved")
                test.changeState(newState)

            self.notify("Status", "Saved " + testDesc + ".")
        except OSError, e:
            self.notify("Status", "Failed to save " + testDesc + ".")
            errorStr = str(e)
            if errorStr.find("Permission") != -1:
                raise plugins.TextTestError, "Failed to save " + testDesc + \
                      " : didn't have sufficient write permission to the test files"
            else:
                raise plugins.TextTestError, errorStr


class MarkTest(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("brief", "Brief text", "Checked")
        self.addOption("free", "Free text", "Checked at " + plugins.localtime())
    def _getTitle(self):
        return "_Mark"
    def getTooltip(self):
        return "Mark the selected tests"
    def performOnCurrent(self):
        for test in self.currTestSelection:
            oldState = test.stateInGui
            if oldState.isComplete():
                if test.stateInGui.isMarked():
                    oldState = test.stateInGui.oldState # Keep the old state so as not to build hierarchies ...
                newState = plugins.MarkedTestState(self.optionGroup.getOptionValue("free"),
                                                   self.optionGroup.getOptionValue("brief"), oldState)
                test.changeState(newState)
                self.notify("ActionProgress", "") # Just to update gui ...
    def isActiveOnCurrent(self, test=None, state=None):
        if state and state.isComplete():
            return True
        for seltest in self.currTestSelection:
            if seltest is not test and seltest.stateInGui.isComplete():
                return True
        return False

class UnmarkTest(guiplugins.ActionGUI):
    def _getTitle(self):
        return "_Unmark"
    def getTooltip(self):
        return "Unmark the selected tests"
    def performOnCurrent(self):
        for test in self.currTestSelection:
            if test.stateInGui.isMarked():
                test.stateInGui.oldState.lifecycleChange = "unmarked" # To avoid triggering completion ...
                test.changeState(test.stateInGui.oldState)
                self.notify("ActionProgress", "") # Just to update gui ...
    def isActiveOnCurrent(self, *args):
        for test in self.currTestSelection:
            if test.stateInGui.isMarked():
                return True
        return False


class KillTests(guiplugins.ActionGUI):
    def _getStockId(self):
        return "stop"
    def _getTitle(self):
        return "_Kill"
    def getTooltip(self):
        return "Kill selected tests"
    def isActiveOnCurrent(self, test=None, state=None):
        for seltest in self.currTestSelection:
            if seltest is test:
                if not state.isComplete():
                    return True
            else:
                if not seltest.stateInGui.isComplete():
                    return True
        return False
    def getSignalsSent(self):
        return [ "Kill" ]
    def performOnCurrent(self):
        tests = filter(lambda test: not test.stateInGui.isComplete(), self.currTestSelection)
        tests.reverse() # best to cut across the action thread rather than follow it and disturb it excessively
        testDesc = str(len(tests)) + " tests"
        self.notify("Status", "Killing " + testDesc + " ...")
        for test in tests:
            self.notify("ActionProgress", "")
            guiutils.guilog.info("Killing " + repr(test))
            test.notify("Kill")

        self.notify("Status", "Killed " + testDesc + ".")


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
        guiutils.scriptEngine.connect(self.getFilterTooltip(), "activate", self.filterAction, self.filterTests)
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
        return [ "SetTestSelection", "Visibility" ]
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

            guiutils.guilog.info("Selected " + str(len(newTests)) + " out of a possible " + str(suite.size()))
            selectedTests += newTests
        return selectedTests

    def performOnCurrent(self):
        newSelection = self.makeNewSelection()
        criteria = " ".join(self.optionGroup.getCommandLines(onlyKeys=self.appKeys))
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


class ResetGroups(guiplugins.BasicActionGUI):
    def isActiveOnCurrent(self, *args):
        return True
    def _getStockId(self):
        return "revert-to-saved"
    def _getTitle(self):
        return "R_eset"
    def messageAfterPerform(self):
        return "All options reset to default values."
    def getTooltip(self):
        return "Reset running options"
    def getSignalsSent(self):
        return [ "Reset" ]
    def performOnCurrent(self):
        self.notify("Reset")

class AnnotateGUI(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("desc", "\nDescription of this run")
    def isActiveOnCurrent(self, *args):
        return True
    def _getStockId(self):
        return "index"
    def _getTitle(self):
        return "Annotate"
    def messageAfterPerform(self):
        pass
    def getDialogTitle(self):
        return "Annotate this run"
    def getTooltip(self):
        return "Provide an annotation for this run and warn before closing it"
    def getSignalsSent(self):
        return [ "Annotate" ]
    def performOnCurrent(self):
        description = self.optionGroup.getOptionValue("desc")
        self.notify("Annotate", description)
        self.notify("Status", "Annotated GUI as '" + description + "'")

class SaveSelection(guiplugins.ActionDialogGUI):
    def __init__(self, allApps, dynamic):
        guiplugins.ActionDialogGUI.__init__(self, allApps, dynamic)
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
            guiutils.guilog.info("Loaded " + str(len(newSelection)) + " tests from " + fileName)
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

class RunningAction:
    runNumber = 1
    def getGroupTabTitle(self):
        return "Running"
    def messageAfterPerform(self):
        return self.performedDescription() + " " + self.describeTests() + " at " + plugins.localtime() + "."

    def performOnCurrent(self):
        self.startTextTestProcess(self.getUseCaseName(), [ "-g" ])
    def startTextTestProcess(self, usecase, runModeOptions):
        app = self.currAppSelection[0]
        writeDir = os.path.join(app.writeDirectory, "dynamic_run" + str(self.runNumber))
        plugins.ensureDirectoryExists(writeDir)
        filterFile = self.writeFilterFile(writeDir)
        ttOptions = runModeOptions + self.getTextTestOptions(filterFile, app, usecase)
        guiutils.guilog.info("Starting " + usecase + " run of TextTest with arguments " + repr(ttOptions))
        logFile = os.path.join(writeDir, "output.log")
        errFile = os.path.join(writeDir, "errors.log")
        RunningAction.runNumber += 1
        description = "Dynamic GUI started at " + plugins.localtime()
        cmdArgs = self.getTextTestArgs() + ttOptions
        env = self.getNewUseCaseEnvironment(usecase)
        guiplugins.processMonitor.startProcess(cmdArgs, description, env=env,
                                               stdout=open(logFile, "w"), stderr=open(errFile, "w"),
                                               exitHandler=self.checkTestRun,
                                               exitHandlerArgs=(errFile,self.currTestSelection,usecase))

    def getNewUseCaseEnvironment(self, usecase):
        environ = deepcopy(os.environ)
        recScript = os.getenv("USECASE_RECORD_SCRIPT")
        if recScript:
            environ["USECASE_RECORD_SCRIPT"] = plugins.addLocalPrefix(recScript, usecase)
        repScript = os.getenv("USECASE_REPLAY_SCRIPT")
        if repScript:
            # Dynamic GUI might not record anything (it might fail) - don't try to replay files that
            # aren't there...
            dynRepScript = plugins.addLocalPrefix(repScript, usecase)
            if os.path.isfile(dynRepScript):
                environ["USECASE_REPLAY_SCRIPT"] = dynRepScript
            else:
                del environ["USECASE_REPLAY_SCRIPT"]
        return environ
    def getSignalsSent(self):
        return [ "SaveSelection" ]
    def writeFilterFile(self, writeDir):
        # Because the description of the selection can be extremely long, we write it in a file and refer to it
        # This avoids too-long command lines which are a problem at least on Windows XP
        filterFileName = os.path.join(writeDir, "gui_select")
        self.notify("SaveSelection", filterFileName)
        return filterFileName
    def getTextTestArgs(self):
        extraArgs = plugins.splitcmd(os.getenv("TEXTTEST_DYNAMIC_GUI_PYARGS", "")) # Additional python arguments for dynamic GUI : mostly useful for coverage
        return [ sys.executable ] + extraArgs + [ sys.argv[0] ]
    def getOptionGroups(self):
        return [ self.optionGroup ]
    def getTextTestOptions(self, filterFile, app, usecase):
        ttOptions = self.getCmdlineOptionForApps()
        for group in self.getOptionGroups():
            ttOptions += group.getCommandLines(self.getCommandLineKeys(usecase))
        # May be slow to calculate for large test suites, cache it
        self.testCount = len(self.getTestCaseSelection())
        ttOptions += [ "-count", str(self.testCount * self.getCountMultiplier()) ]
        ttOptions += [ "-f", filterFile ]
        ttOptions += [ "-fd", self.getTmpFilterDir(app) ]
        return ttOptions
    def getCommandLineKeys(self, usecase):
        # assume everything by default
        return []
    def getCountMultiplier(self):
        return 1
    
    def getTmpFilterDir(self, app):
        return os.path.join(app.writeDirectory, "temporary_filter_files")
    def getCmdlineOptionForApps(self):
        appNames = set([ app.name for app in self.currAppSelection ])
        return [ "-a", ",".join(sorted(list(appNames))) ]
    def checkTestRun(self, errFile, testSel, usecase):
        if self.checkErrorFile(errFile, testSel, usecase):
            self.handleCompletion(testSel, usecase)
            if len(self.currTestSelection) >= 1 and self.currTestSelection[0] in testSel:
                self.currTestSelection[0].filesChanged()

        testSel[0].notify("CloseDynamic", usecase)

    def readAndFilter(self, errFile, testSel):
        errText = ""
        triggerGroup = plugins.TextTriggerGroup(testSel[0].getConfigValue("suppress_stderr_popup"))
        for line in open(errFile).xreadlines():
            if not triggerGroup.stringContainsText(line):
                errText += line
        return errText
    def checkErrorFile(self, errFile, testSel, usecase):
        if os.path.isfile(errFile):
            errText = self.readAndFilter(errFile, testSel)
            if len(errText):
                self.notify("Status", usecase.capitalize() + " run failed for " + repr(testSel[0]))
                self.showErrorDialog(usecase.capitalize() + " run failed, with the following errors:\n" + errText)
                return False
        return True

    def handleCompletion(self, *args):
        pass # only used when recording

    def getConfirmationMessage(self):
        # For extra speed we check the selection first before we calculate all the test cases again...
        if len(self.currTestSelection) > 1 or len(self.getTestCaseSelection()) > 1:
            multiTestWarning = self.getMultipleTestWarning()
            if multiTestWarning:
                return "You are trying to " + multiTestWarning + ".\nThis will mean lots of target application GUIs " + \
                       "popping up and may be hard to follow.\nAre you sure you want to do this?"
        return ""

    def getMultipleTestWarning(self):
        pass


class ReconnectToTests(RunningAction,guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("v", "Version to reconnect to")
        self.addOption("reconnect", "Temporary result directory", os.getenv("TEXTTEST_TMP", ""), selectDir=True, description="Specify a directory containing temporary texttest results. The reconnection will use a random subdirectory matching the version used.")
        self.addSwitch("reconnfull", "Recomputation", 0, ["Display results exactly as they were in the original run", "Use raw data from the original run, but recompute run-dependent text, known bug information etc."])
    def _getStockId(self):
        return "connect"
    def _getTitle(self):
        return "Re_connect"
    def getTooltip(self):
        return "Reconnect to previously run tests"
    def getTabTitle(self):
        return "Reconnect"
    def performedDescription(self):
        return "Reconnected to"
    def getUseCaseName(self):
        return "reconnect"

class RunTests(RunningAction,guiplugins.ActionTabGUI):
    optionGroups = []
    def __init__(self, allApps, *args):
        guiplugins.ActionTabGUI.__init__(self, allApps)
        self.optionGroups.append(self.optionGroup)
        self.addApplicationOptions(allApps)

    def _getTitle(self):
        return "_Run"
    def _getStockId(self):
        return "execute"
    def getTooltip(self):
        return "Run selected tests"
    def getOptionGroups(self):
        return self.optionGroups
    def getCountMultiplier(self):
        return self.getCopyCount() * self.getVersionCount()
    def getCopyCount(self):
        return int(self.optionGroups[0].getOptionValue("cp"))
    def getVersionCount(self):
        return self.optionGroups[0].getOptionValue("v").count(",") + 1
    def performedDescription(self):
        timesToRun = self.getCopyCount()
        numberOfTests = self.testCount
        if timesToRun != 1:
            if numberOfTests > 1:
                return "Started " + str(timesToRun) + " copies each of"
            else:
                return "Started " + str(timesToRun) + " copies of"
        else:
            return "Started"
    def getUseCaseName(self):
        return "dynamic"
    def getMultipleTestWarning(self):
        app = self.currTestSelection[0].app
        for group in self.optionGroups:
            for switchName, desc in app.getInteractiveReplayOptions():
                if group.getSwitchValue(switchName, False):
                    return "run " + self.describeTests() + " with " + desc + " replay enabled"

class RunTestsBasic(RunTests):
    def getTabTitle(self):
        return "Basic"

class RunTestsAdvanced(RunTests):
    def getTabTitle(self):
        return "Advanced"

class RecordTest(RunningAction,guiplugins.ActionTabGUI):
    def __init__(self, allApps, *args):
        guiplugins.ActionTabGUI.__init__(self, allApps, *args)
        self.currentApp = None
        self.recordTime = None
        defaultVersion, defaultCheckout = "", ""
        if len(allApps) > 0:
            self.currentApp = allApps[0]
            defaultVersion = self.currentApp.getFullVersion(forSave=1)
            defaultCheckout = self.currentApp.checkout
        self.addOption("v", "Version to record", defaultVersion)
        self.addOption("c", "Checkout to use for recording", defaultCheckout)
        self.addSwitch("rectraffic", "Also record command-line or client-server traffic", 1)
        self.addSwitch("rep", "Automatically replay test after recording it", 1)
        self.addSwitch("repgui", options = ["Auto-replay invisible", "Auto-replay in dynamic GUI"])
    def correctTestClass(self):
        return "test-case"
    def _getStockId(self):
        return "media-record"
    def getTabTitle(self):
        return "Recording"
    def messageAfterPerform(self):
        return "Started record session for " + self.describeTests()
    def performOnCurrent(self):
        self.updateRecordTime(self.currTestSelection[0])
        self.startTextTestProcess("record", [ "-g", "-record" ])
    def shouldShowCurrent(self, *args):
        return len(self.validApps) > 0 and guiplugins.ActionTabGUI.shouldShowCurrent(self, *args) # override the default so it's disabled if there are no apps
    def isValidForApp(self, app):
        return app.getConfigValue("use_case_record_mode") != "disabled" and \
               app.getConfigValue("use_case_recorder") != "none"
    def updateOptions(self):
        if self.currentApp is not self.currAppSelection[0]:
            self.currentApp = self.currAppSelection[0]
            self.optionGroup.setOptionValue("v", self.currentApp.getFullVersion(forSave=1))
            self.optionGroup.setOptionValue("c", self.currentApp.checkout)
            return True
        else:
            return False
    def getUseCaseFile(self, test):
        return test.getFileName("usecase", self.optionGroup.getOptionValue("v"))
    def updateRecordTime(self, test):
        file = self.getUseCaseFile(test)
        if file:
            self._updateRecordTime(file)
    def _updateRecordTime(self, file):
        newTime = plugins.modifiedTime(file)
        if newTime != self.recordTime:
            self.recordTime = newTime
            outerRecord = os.getenv("USECASE_RECORD_SCRIPT")
            if outerRecord:
                # If we have an "outer" record going on, provide the result as a target recording...
                target = plugins.addLocalPrefix(outerRecord, "target_record")
                shutil.copyfile(file, target)
            return True
        else:
            return False
    def getChangedUseCaseVersion(self, test):
        test.refreshFiles() # update cache after record run
        file = self.getUseCaseFile(test)
        if not file or not self._updateRecordTime(file):
            return

        parts = os.path.basename(file).split(".")
        return ".".join(parts[2:])
    def getMultipleTestWarning(self):
        return "record " + self.describeTests() + " simultaneously"

    def handleCompletion(self, testSel, usecase):
        test = testSel[0]
        if usecase == "record":
            changedUseCaseVersion = self.getChangedUseCaseVersion(test)
            if changedUseCaseVersion is not None and self.optionGroup.getSwitchValue("rep"):
                self.startTextTestProcess("replay", self.getReplayRunModeOptions(changedUseCaseVersion))
                message = "Recording completed for " + repr(test) + \
                          ". Auto-replay of test now started. Don't submit the test manually!"
                self.notify("Status", message)
            else:
                self.notify("Status", "Recording completed for " + repr(test) + ", not auto-replaying")
        else:
            self.notify("Status", "Recording and auto-replay completed for " + repr(test))

    def getCommandLineKeys(self, usecase):
        keys = [ "v", "c" ]
        if usecase == "record":
            keys.append("rectraffic")
        return keys

    def getReplayRunModeOptions(self, overwriteVersion):
        if self.optionGroup.getSwitchValue("repgui"):
            return [ "-autoreplay", "-g" ]
        else:
            return [ "-autoreplay", "-o", overwriteVersion ]

    def _getTitle(self):
        return "Record _Use-Case"


class ReportBugs(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("search_string", "Text or regexp to match")
        self.addOption("search_file", "File to search in")
        self.addOption("version", "\nVersion to report for")
        self.addOption("execution_hosts", "Trigger only when run on machine(s)")
        self.addOption("bug_system", "\nExtract info from bug system", "<none>", [ "bugzilla", "bugzillav2" ])
        self.addOption("bug_id", "Bug ID (only if bug system given)")
        self.addOption("full_description", "\nFull description (no bug system)")
        self.addOption("brief_description", "Few-word summary (no bug system)")
        self.addSwitch("trigger_on_absence", "Trigger if given text is NOT present")
        self.addSwitch("ignore_other_errors", "Trigger even if other files differ")
        self.addSwitch("trigger_on_success", "Trigger even if test would otherwise succeed")
        self.addSwitch("internal_error", "Report as 'internal error' rather than 'known bug' (no bug system)")
    def _getStockId(self):
        return "info"
    def singleTestOnly(self):
        return True
    def _getTitle(self):
        return "Enter Failure Information"
    def getDialogTitle(self):
        return "Enter information for automatic interpretation of test failures"
    def updateOptions(self):
        self.optionGroup.setOptionValue("search_file", self.currTestSelection[0].app.getConfigValue("log_file"))
        self.optionGroup.setPossibleValues("search_file", self.getPossibleFileStems())
        self.optionGroup.setOptionValue("version", self.currTestSelection[0].app.getFullVersion())
        return False
    def getPossibleFileStems(self):
        stems = []
        for test in self.currTestSelection[0].testCaseList():
            for stem in test.dircache.findAllStems(self.currTestSelection[0].defFileStems()):
                if not stem in stems:
                    stems.append(stem)
        # use for unrunnable tests...
        stems.append("free_text")
        return stems
    def checkSanity(self):
        if len(self.optionGroup.getOptionValue("search_string")) == 0:
            raise plugins.TextTestError, "Must fill in the field 'text or regexp to match'"
        if self.optionGroup.getOptionValue("bug_system") == "<none>":
            if len(self.optionGroup.getOptionValue("full_description")) == 0 or \
                   len(self.optionGroup.getOptionValue("brief_description")) == 0:
                raise plugins.TextTestError, "Must either provide a bug system or fill in both description and summary fields"
        else:
            if len(self.optionGroup.getOptionValue("bug_id")) == 0:
                raise plugins.TextTestError, "Must provide a bug ID if bug system is given"
    def versionSuffix(self):
        version = self.optionGroup.getOptionValue("version")
        if len(version) == 0:
            return ""
        else:
            return "." + version
    def getFileName(self):
        name = "knownbugs." + self.currTestSelection[0].app.name + self.versionSuffix()
        return os.path.join(self.currTestSelection[0].getDirectory(), name)
    def getResizeDivisors(self):
        # size of the dialog
        return 1.4, 1.7
    def performOnCurrent(self):
        self.checkSanity()
        fileName = self.getFileName()
        writeFile = open(fileName, "a")
        writeFile.write("\n[Reported by " + os.getenv("USER", "Windows") + " at " + plugins.localtime() + "]\n")
        for name, option in self.optionGroup.options.items():
            value = option.getValue()
            if name != "version" and value and value != "<none>":
                writeFile.write(name + ":" + str(value) + "\n")
        writeFile.close()
        self.currTestSelection[0].filesChanged()

class RecomputeTests(guiplugins.ActionGUI):
    def __init__(self, *args):
        guiplugins.ActionGUI.__init__(self, *args)
        self.latestNumberOfRecomputations = 0
    def isActiveOnCurrent(self, test=None, state=None):
        for currTest in self.currTestSelection:
            if currTest is test:
                if state.hasStarted():
                    return True
            elif currTest.stateInGui.hasStarted():
                return True
        return False
    def _getTitle(self):
        return "Recompute Status"
    def _getStockId(self):
        return "refresh"
    def getTooltip(self):
        return "Recompute test status, including progress information if appropriate"
    def getSignalsSent(self):
        return [ "Recomputed" ]
    def messageAfterPerform(self):
        if self.latestNumberOfRecomputations == 0:
            return "No test needed recomputation."
        else:
            return "Recomputed status of " + self.pluralise(self.latestNumberOfRecomputations, "test") + "."
    def performOnCurrent(self):
        self.latestNumberOfRecomputations = 0
        for app in self.currAppSelection:
            self.notify("Status", "Rereading configuration for " + repr(app) + " ...")
            self.notify("ActionProgress", "")
            app.setUpConfiguration()

        for test in self.currTestSelection:
            self.latestNumberOfRecomputations += 1
            self.notify("Status", "Recomputing status of " + repr(test) + " ...")
            self.notify("ActionProgress", "")
            test.app.recomputeProgress(test, test.stateInGui, self.observers)
            self.notify("Recomputed", test)


class RefreshAll(guiplugins.BasicActionGUI):
    def __init__(self, *args):
        guiplugins.BasicActionGUI.__init__(self, *args)
        self.rootTestSuites = []
    def _getTitle(self):
        return "Refresh"
    def _getStockId(self):
        return "refresh"
    def getTooltip(self):
        return "Refresh the whole test suite so that it reflects file changes"
    def messageBeforePerform(self):
        return "Refreshing the whole test suite..."
    def messageAfterPerform(self):
        return "Refreshed the test suite from the files"
    def addSuites(self, suites):
        self.rootTestSuites += suites
    def performOnCurrent(self):
        for suite in self.rootTestSuites:
            self.notify("ActionProgress", "")
            suite.app.setUpConfiguration()
            self.notify("ActionProgress", "")
            filters = suite.app.getFilterList(self.rootTestSuites)
            suite.refresh(filters)


class ShowFileProperties(guiplugins.ActionResultDialogGUI):
    def __init__(self, allApps, dynamic):
        self.dynamic = dynamic
        guiplugins.ActionGUI.__init__(self, allApps)
    def _getStockId(self):
        return "properties"
    def isActiveOnCurrent(self, *args):
        return ((not self.dynamic) or len(self.currTestSelection) == 1) and \
               len(self.currFileSelection) > 0
    def _getTitle(self):
        return "_File Properties"
    def getTooltip(self):
        return "Show properties of selected files"
    def describeTests(self):
        return str(len(self.currFileSelection)) + " files"
    def getAllProperties(self):
        errors, properties = [], []
        for file, comp in self.currFileSelection:
            if self.dynamic and comp:
                self.processFile(comp.tmpFile, properties, errors)
            self.processFile(file, properties, errors)

        if len(errors):
            self.showErrorDialog("Failed to get file properties:\n" + "\n".join(errors))

        return properties
    def processFile(self, file, properties, errors):
        try:
            prop = plugins.FileProperties(file)
            properties.append(prop)
        except Exception, e:
            errors.append(plugins.getExceptionString())

    # xalign = 1.0 means right aligned, 0.0 means left aligned
    def justify(self, text, xalign = 0.0):
        alignment = gtk.Alignment()
        alignment.set(xalign, 0.0, 0.0, 0.0)
        label = gtk.Label(text)
        alignment.add(label)
        return alignment

    def addContents(self):
        dirToProperties = seqdict()
        props = self.getAllProperties()
        for prop in props:
            dirToProperties.setdefault(prop.dir, []).append(prop)
        vbox = self.createVBox(dirToProperties)
        self.dialog.vbox.pack_start(vbox, expand=True, fill=True)

    def createVBox(self, dirToProperties):
        vbox = gtk.VBox()
        for dir, properties in dirToProperties.items():
            expander = gtk.Expander()
            expander.set_label_widget(self.justify(dir))
            table = gtk.Table(len(properties), 7)
            table.set_col_spacings(5)
            row = 0
            for prop in properties:
                values = prop.getUnixRepresentation()
                table.attach(self.justify(values[0] + values[1], 1.0), 0, 1, row, row + 1)
                table.attach(self.justify(values[2], 1.0), 1, 2, row, row + 1)
                table.attach(self.justify(values[3], 0.0), 2, 3, row, row + 1)
                table.attach(self.justify(values[4], 0.0), 3, 4, row, row + 1)
                table.attach(self.justify(values[5], 1.0), 4, 5, row, row + 1)
                table.attach(self.justify(values[6], 1.0), 5, 6, row, row + 1)
                table.attach(self.justify(prop.filename, 0.0), 6, 7, row, row + 1)
                row += 1
            hbox = gtk.HBox()
            hbox.pack_start(table, expand=False, fill=False)
            innerBorder = gtk.Alignment()
            innerBorder.set_padding(5, 0, 0, 0)
            innerBorder.add(hbox)
            expander.add(innerBorder)
            expander.set_expanded(True)
            border = gtk.Alignment()
            border.set_padding(5, 5, 5, 5)
            border.add(expander)
            vbox.pack_start(border, expand=False, fill=False)
        return vbox


class InteractiveActionConfig(guiplugins.InteractiveActionConfig):
    def getMenuNames(self):
        return [ "file", "edit", "view", "actions", "reorder", "help" ]

    def getInteractiveActionClasses(self, dynamic):
        classes = [ Quit, ShowFileProperties ]
        if dynamic:
            classes += [ SaveTests, SaveSelection, KillTests, AnnotateGUI,
                         MarkTest, UnmarkTest, RecomputeTests ] # must keep RecomputeTests at the end!
        else:
            classes += [ ReportBugs, SelectTests,
                         RefreshAll, HideUnselected, HideSelected, ShowAll,
                         RunTestsBasic, RunTestsAdvanced, RecordTest, ResetGroups, 
                         ReconnectToTests, LoadSelection, SaveSelection ]
            classes += adminactions.getInteractiveActionClasses()
        classes += helpdialogs.getInteractiveActionClasses()
        classes += fileviewers.getInteractiveActionClasses(dynamic)
        return classes


    
