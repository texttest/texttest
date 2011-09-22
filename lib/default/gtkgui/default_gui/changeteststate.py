
"""
The actions in the dynamic GUI that affect the state of a test
"""

import gtk, plugins, os
from .. import guiplugins

class SaveTests(guiplugins.ActionDialogGUI):
    defaultVersionStr = "<existing version>"
    fullVersionStr = "<full version>"
    def __init__(self, allApps, *args):
        guiplugins.ActionDialogGUI.__init__(self, allApps, *args)
        self.directAccel = None
        self.directAction = gtk.Action("Save", "_Save", \
                                       self.getDirectTooltip(), self.getStockId())
        self.directAction.connect("activate", self._respond)
        self.directAction.set_property("sensitive", False)
        self.addOption("v", "Version to save", self.defaultVersionStr)
        self.addOption("old", "Version(s) to save previous results as")
        self.addSwitch("over", "Replace successfully compared files also", 0)
        if self.hasPerformance(allApps):
            self.addSwitch("ex", "Save", 1, ["Average performance", "Exact performance"])
        # Must do this in the constructor, so that "Save" also takes account of them
        for option in self.optionGroup.options.values():
            self.addValuesFromConfig(option)

    def createDialog(self):
        dialog = guiplugins.ActionDialogGUI.createDialog(self)
        dialog.set_name("Save As")
        return dialog

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
        versionOption = self.optionGroup.getOption("v")
        currOption = versionOption.defaultValue
        newVersions = self.getPossibleVersions()
        currVersions = versionOption.possibleValues
        if self.defaultVersionStr == currOption and newVersions == currVersions:
            return False
        self.optionGroup.setOptionValue("v", versionOption.defaultValue)
        self.diag.info("Setting default save version to " + self.defaultVersionStr)
        self.optionGroup.setPossibleValues("v", newVersions)
        return True
    
    def getPossibleVersions(self):
        extensions = [ self.defaultVersionStr, self.fullVersionStr ]
        for app in self.currAppSelection:
            for ext in app.getSaveableVersions():
                if not ext in extensions:
                    extensions.append(ext)
        # Include the default version always
        extensions.append("")
        return extensions
    
    def getExactness(self):
        return int(self.optionGroup.getSwitchValue("ex", 1))
        
    def isActiveOnCurrent(self, test=None, state=None):
        if state and state.isSaveable():
            return True
        for seltest in self.currTestSelection:
            if seltest is not test and seltest.stateInGui.isSaveable():
                return True
        return False

    def getStemsToSave(self):
        return [ os.path.basename(fileName).split(".")[0] for fileName, _ in self.currFileSelection ]

    def getBackupVersions(self):
        versionString = self.optionGroup.getOptionValue("old")
        if versionString:
            return plugins.commasplit(versionString)
        else:
            return []

    def getVersion(self, test):
        versionString = self.optionGroup.getOptionValue("v")
        if versionString == self.fullVersionStr:
            return test.app.getFullVersion(forSave=1)
        elif versionString != self.defaultVersionStr:
            return versionString

    def performOnCurrent(self):
        backupVersions = self.getBackupVersions()
        if self.optionGroup.getOptionValue("v") in backupVersions:
            raise plugins.TextTestError, "Cannot backup to the same version we're trying to save! Choose another name."
        
        stemsToSave = self.getStemsToSave()
        overwriteSuccess = self.optionGroup.getSwitchValue("over")
        tests = self.getSaveableTests()
        # Calculate the versions beforehand, as saving tests can change the selection,
        # which can affect the default version calculation...
        testsWithVersions = [ (test, self.getVersion(test)) for test in tests ]
        testDesc = str(len(tests)) + " tests"
        self.notify("Status", "Saving " + testDesc + " ...")
        try:
            for test, versionString in testsWithVersions:
                testComparison = test.stateInGui
                testComparison.setObservers(self.observers)
                testComparison.save(test, self.getExactness(), versionString, overwriteSuccess, stemsToSave, backupVersions)
                newState = testComparison.makeNewState(test, "saved")
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
            return "Recomputed status of " + plugins.pluralise(self.latestNumberOfRecomputations, "test") + "."
        
    def performOnCurrent(self):
        self.latestNumberOfRecomputations = 0
        if any((test.stateInGui.isComplete() for test in self.currTestSelection)):
            for appOrTest in self.currAppSelection + self.currTestSelection:
                self.notify("Status", "Rereading configuration for " + repr(appOrTest) + " ...")
                self.notify("ActionProgress")
                appOrTest.reloadConfiguration()

        for test in self.currTestSelection:
            self.latestNumberOfRecomputations += 1
            self.notify("Status", "Recomputing status of " + repr(test) + " ...")
            self.notify("ActionProgress")
            test.app.recomputeProgress(test, test.stateInGui, self.observers)
            self.notify("Recomputed", test)


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
                self.notify("ActionProgress") # Just to update gui ...
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
                self.notify("ActionProgress") # Just to update gui ...
    def isActiveOnCurrent(self, *args):
        for test in self.currTestSelection:
            if test.stateInGui.isMarked():
                return True
        return False

class SuspendTests(guiplugins.ActionGUI):
    def _getTitle(self):
        return "Suspend"
    def getTooltip(self):
        return "Suspend the selected tests"
    def performOnCurrent(self):
        from queuesystem.masterprocess import QueueSystemServer
        QueueSystemServer.instance.setSuspendStateForTests(self.currTestSelection, True)
    def isActiveOnCurrent(self, *args):
        return any((not test.stateInGui.isComplete() for test in self.currTestSelection))

class UnsuspendTests(guiplugins.ActionGUI):
    def _getTitle(self):
        return "Unsuspend"
    def getTooltip(self):
        return "Unsuspend the selected tests"
    def performOnCurrent(self):
        from queuesystem.masterprocess import QueueSystemServer
        QueueSystemServer.instance.setSuspendStateForTests(self.currTestSelection, False)
    def isActiveOnCurrent(self, *args):
        return any((not test.stateInGui.isComplete() for test in self.currTestSelection))



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
            self.notify("ActionProgress")
            test.notify("Kill")

        self.notify("Status", "Killed " + testDesc + ".")


def getInteractiveActionClasses():
    return [ SaveTests, KillTests, MarkTest, UnmarkTest, RecomputeTests, SuspendTests, UnsuspendTests ]
 
