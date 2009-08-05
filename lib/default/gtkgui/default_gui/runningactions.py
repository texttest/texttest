
"""
The various ways to launch the dynamic GUI from the static GUI
"""

import plugins, os, sys, shutil 
from default.gtkgui import guiplugins # from .. import guiplugins, guiutils when we drop Python 2.4 support
from copy import deepcopy

class RunningAction:
    runNumber = 1
    def __init__(self, inputOptions):
        self.inputOptions = inputOptions
        
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
        guiplugins.guilog.info("Starting " + usecase + " run of TextTest with arguments " + repr(ttOptions))
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

    def getVanillaOption(self):
        options = []
        if self.inputOptions.has_key("vanilla"):
            options.append("-vanilla")
            value = self.inputOptions.get("vanilla")
            if value:
                options.append(value)
        return options
    
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
    def __init__(self, allApps, dynamic, inputOptions):
        guiplugins.ActionDialogGUI.__init__(self, allApps, dynamic)
        RunningAction.__init__(self, inputOptions)
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
    def performOnCurrent(self):
        self.startTextTestProcess(self.getUseCaseName(), [ "-g" ] + self.getVanillaOption())
    

class RunTests(RunningAction,guiplugins.ActionTabGUI):
    optionGroups = []
    def __init__(self, allApps, dynamic, inputOptions):
        guiplugins.ActionTabGUI.__init__(self, allApps)
        RunningAction.__init__(self, inputOptions)
        self.optionGroups.append(self.optionGroup)
        self.addApplicationOptions(allApps, inputOptions)

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
    def __init__(self, allApps, dynamic, inputOptions):
        guiplugins.ActionTabGUI.__init__(self, allApps, dynamic)
        RunningAction.__init__(self, inputOptions)
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
        self.startTextTestProcess("record", [ "-g", "-record" ] + self.getVanillaOption())
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
                self.startTextTestProcess("replay", self.getVanillaOption() + self.getReplayRunModeOptions(changedUseCaseVersion))
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


def getInteractiveActionClasses():
    return [ RunTestsBasic, RunTestsAdvanced, RecordTest, ReconnectToTests ]
