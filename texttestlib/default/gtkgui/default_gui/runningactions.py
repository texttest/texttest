
"""
The various ways to launch the dynamic GUI from the static GUI
"""
from gi.repository import Gtk, GObject
import os
import sys
import stat
from texttestlib import plugins
from .. import guiplugins
from copy import copy, deepcopy
from io import StringIO

# Runs the dynamic GUI, but not necessarily with all the options available from the configuration


class BasicRunningAction:
    runNumber = 1

    def __init__(self, inputOptions):
        self.inputOptions = inputOptions
        self.testCount = 0

    def getTabTitle(self):
        return "Running"

    def messageAfterPerform(self):
        return self.performedDescription() + " " + self.describeTestsWithCount() + " at " + plugins.localtime() + "."

    def describeTestsWithCount(self):
        if self.testCount == 1:
            return "test " + self.getTestCaseSelection()[0].getRelPath()
        else:
            return str(self.testCount) + " tests"

    def performOnCurrent(self):
        self.startTextTestProcess(self.getUseCaseName(), ["-g"])

    def getTestsAffected(self, testSelOverride):
        if testSelOverride:
            return testSelOverride
        else:
            # Take a copy so we aren't fooled by selection changes
            return copy(self.currTestSelection)

    def getRunWriteDirectory(self, app):
        return os.path.join(self.getLogRootDirectory(app), "dynamic_run" + str(self.runNumber))

    def startTextTestProcess(self, usecase, runModeOptions, testSelOverride=None, filterFileOverride=None):
        app = self.getCurrentApplication()
        writeDir = self.getRunWriteDirectory(app)
        plugins.ensureDirectoryExists(writeDir)
        filterFile = self.createFilterFile(writeDir, filterFileOverride)
        ttOptions = runModeOptions + self.getTextTestOptions(filterFile, app, usecase)
        self.diag.info("Starting " + usecase + " run of TextTest with arguments " + repr(ttOptions))
        logFile = os.path.join(writeDir, "output.log")
        errFile = os.path.join(writeDir, "errors.log")
        BasicRunningAction.runNumber += 1
        description = "Dynamic GUI started at " + plugins.localtime()
        cmdArgs = self.getInterpreterArgs() + [sys.argv[0]] + ttOptions
        env = self.getNewUseCaseEnvironment(usecase)
        testsAffected = self.getTestsAffected(testSelOverride)
        guiplugins.processMonitor.startProcess(cmdArgs, description, env=env, killOnTermination=self.killOnTermination(),
                                               stdout=open(logFile, "w"), stderr=open(errFile, "w"),
                                               exitHandler=self.checkTestRun,
                                               exitHandlerArgs=(errFile, testsAffected, filterFile, usecase))

    def getCurrentApplication(self):
        return self.currAppSelection[0] if self.currAppSelection else self.validApps[0]

    def getLogRootDirectory(self, app):
        return app.writeDirectory

    def killOnTermination(self):
        return True

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
        return ["SaveSelection"]

    def createFilterFile(self, writeDir, filterFileOverride):
        # Because the description of the selection can be extremely long, we write it in a file and refer to it
        # This avoids too-long command lines which are a problem at least on Windows XP
        if filterFileOverride is None:
            filterFileName = os.path.join(writeDir, "gui_select")
            self.notify("SaveSelection", filterFileName)
            return filterFileName
        elif filterFileOverride is not NotImplemented:
            return filterFileOverride

    def getInterpreterArgs(self):
        if getattr(sys, 'frozen', False):
            return []
        interpreterArg = os.getenv("TEXTTEST_DYNAMIC_GUI_INTERPRETER", "") # Alternative interpreter for the dynamic GUI : mostly useful for coverage / testing
        if interpreterArg:
            return plugins.splitcmd(interpreterArg.replace("ttpython", sys.executable))
        else:  # pragma: no cover - cannot test without StoryText on dynamic GUI
            return [sys.executable]

    def getOptionGroups(self):
        return [self.optionGroup]

    def getTextTestOptions(self, filterFile, app, usecase):
        ttOptions = self.getCmdlineOptionForApps(filterFile)
        for group in self.getOptionGroups():
            ttOptions += self.getCommandLineArgs(group, self.getCommandLineKeys(usecase),
                                                 self.getCommandLineExcludeKeys())
        # May be slow to calculate for large test suites, cache it
        self.testCount = len(self.getTestCaseSelection())
        ttOptions += ["-count", str(self.testCount * self.getCountMultiplier())]
        if filterFile:
            ttOptions += ["-f", filterFile]
        tmpFilterDir = self.getTmpFilterDir(app)
        if tmpFilterDir:
            ttOptions += ["-fd", tmpFilterDir]
        return ttOptions

    def getCommandLineKeys(self, *args):
        # assume everything by default
        return []

    def getCommandLineExcludeKeys(self):
        return []

    def getCountMultiplier(self):
        return 1

    def getVanillaOption(self):
        options = []
        if "vanilla" in self.inputOptions:
            options.append("-vanilla")
            value = self.inputOptions.get("vanilla")
            if value:
                options.append(value)
        return options

    def getTmpFilterDir(self, app):
        return os.path.join(app.writeDirectory, "temporary_filter_files")

    def getAppIdentifier(self, app):
        return app.name + app.versionSuffix()

    def getCmdlineOptionForApps(self, filterFile):
        if not filterFile:
            return []

        apps = sorted(self.currAppSelection, key=self.validApps.index)
        appNames = list(map(self.getAppIdentifier, apps))
        return ["-a", ",".join(appNames)]

    def checkTestRun(self, errFile, testSel, filterFile, usecase):
        if not testSel:
            return
        if self.checkErrorFile(errFile, testSel, usecase):
            self.handleCompletion(testSel, filterFile, usecase)
            if len(self.currTestSelection) >= 1 and self.currTestSelection[0] in testSel:
                self.currTestSelection[0].filesChanged()

        testSel[0].notify("CloseDynamic", usecase)

    def checkErrorFile(self, errFile, testSel, usecase):
        if os.path.isfile(errFile) and len(testSel) > 0:
            errText = testSel[0].app.filterErrorText(errFile)
            if len(errText):
                self.notify("Status", usecase.capitalize() + " run failed for " + repr(testSel[0]))
                lines = errText.splitlines()
                maxLength = testSel[0].getConfigValue("lines_of_text_difference")
                if len(lines) > maxLength:
                    errText = "\n".join(lines[:maxLength])
                    errText += "\n(Very long message truncated. Full details can be seen in the file at\n" + errFile + ")"
                self.showErrorDialog(usecase.capitalize() + " run failed, with the following errors:\n" + errText)
                return False
        return True

    def handleCompletion(self, *args):
        pass  # only used when recording

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


class ReconnectToTests(BasicRunningAction, guiplugins.ActionDialogGUI):
    def __init__(self, allApps, dynamic, inputOptions):
        guiplugins.ActionDialogGUI.__init__(self, allApps, dynamic)
        BasicRunningAction.__init__(self, inputOptions)
        self.addOption("v", "Version to reconnect to")
        self.addOption("reconnect", "Temporary result directory", os.getenv("TEXTTEST_TMP", ""), selectDir=True,
                       description="Specify a directory containing temporary texttest results. The reconnection will use a random subdirectory matching the version used.")
        appGroup = plugins.OptionGroup("Invisible")
        self.addApplicationOptions(allApps, appGroup, inputOptions)
        self.addSwitch("reconnfull", "Recomputation", options=appGroup.getOption("reconnfull").options)

    def _getStockId(self):
        return "connect"

    def _getTitle(self):
        return "Re_connect..."

    def getTooltip(self):
        return "Reconnect to previously run tests"

    def performedDescription(self):
        return "Reconnected to"

    def getUseCaseName(self):
        return "reconnect"

    def performOnCurrent(self):
        self.startTextTestProcess(self.getUseCaseName(), ["-g"] + self.getVanillaOption())

    def getAppIdentifier(self, app):
        # Don't send version data, we have our own field with that info and it has a slightly different meaning
        return app.name

    def getSizeAsWindowFraction(self):
        return 0.8, 0.7


class ReloadTests(BasicRunningAction, guiplugins.ActionDialogGUI):
    def __init__(self, allApps, dynamic, inputOptions):
        guiplugins.ActionDialogGUI.__init__(self, allApps, dynamic)
        BasicRunningAction.__init__(self, inputOptions)
        self.appGroup = plugins.OptionGroup("Invisible")
        # We don't think reconnect can handle multiple roots currently
        # Can be a limitation of this for the moment.
        self.addApplicationOptions(allApps, self.appGroup, inputOptions)
        self.addSwitch("reconnfull", "Recomputation", options=self.appGroup.getOption("reconnfull").options)

    def getTmpDirectory(self):
        return self.currAppSelection[0].writeDirectory

    def _getStockId(self):
        return "connect"

    def _getTitle(self):
        return "Re_load tests..."

    def getTooltip(self):
        return "Reload current results into new dynamic GUI"

    def performedDescription(self):
        return "Reloaded"

    def getUseCaseName(self):
        return "reload"

    def performOnCurrent(self):
        if self.appGroup.getOptionValue("reconnfull") == 0:
            # We want to reload the results exactly as they are currently
            # This will only be possible if we make sure to save the teststate files first
            self.saveTestStates()
        self.startTextTestProcess(self.getUseCaseName(), [
                                  "-g", "-reconnect", self.getTmpDirectory()] + self.getVanillaOption())

    def saveTestStates(self):
        for test in self.currTestSelection:
            if test.state.isComplete():  # might look weird but this notification also comes in scripts etc.
                test.saveState()

    def getAppIdentifier(self, app):
        # Don't send version data, we have our own field with that info and it has a slightly different meaning
        return app.name


# base class for RunTests and RerunTests, i.e. all the options are available
class RunningAction(BasicRunningAction):
    originalVersion = ""

    def __init__(self, allApps, inputOptions):
        BasicRunningAction.__init__(self, inputOptions)
        self.optionGroups = []
        self.disablingInfo = {}
        self.disableWidgets = {}
        for groupName, disablingOption, disablingOptionValue in self.getGroupNames(allApps):
            group = plugins.OptionGroup(groupName)
            self.addApplicationOptions(allApps, group, inputOptions)
            self.optionGroups.append(group)
            if disablingOption:
                self.disablingInfo[self.getOption(disablingOption)] = disablingOptionValue, group

        self.temporaryGroup = plugins.OptionGroup("Temporary Settings")
        self.temporaryGroup.addOption("filetype", "File Type", "environment", possibleValues=self.getFileTypes(allApps))
        self.temporaryGroup.addOption("contents", "Contents", multilineEntry=True)

        RunningAction.originalVersion = self.getVersionString()

    def getFileTypes(self, allApps):
        ignoreTypes = ["testsuite", "knownbugs", "stdin", "input", "testcustomize.py"]
        fileTypes = []
        for app in allApps:
            for ft in app.defFileStems("builtin") + app.defFileStems("default"):
                if ft not in fileTypes and ft not in ignoreTypes:
                    fileTypes.append(ft)
        return fileTypes

    def getTextTestOptions(self, filterFile, app, *args):
        ret = BasicRunningAction.getTextTestOptions(self, filterFile, app, *args)
        contents = self.temporaryGroup.getValue("contents")
        if contents:
            fileType = self.temporaryGroup.getValue("filetype")
            writeDir = os.path.dirname(filterFile)
            tmpDir = self.makeTemporarySettingsDir(writeDir, app, fileType, contents)
            ret += ["-td", tmpDir]
        return ret

    def makeTemporarySettingsDir(self, writeDir, app, fileType, contents):
        tmpDir = os.path.join(writeDir, "temporary_settings")
        plugins.ensureDirectoryExists(tmpDir)
        fileName = os.path.join(tmpDir, fileType + "." + app.name + app.versionSuffix())
        with open(fileName, "w") as f:
            f.write(contents)
        return tmpDir

    def getGroupNames(self, allApps):
        if len(allApps) > 0:
            return allApps[0].getAllRunningGroupNames(allApps)
        else:
            configObject = self.makeDefaultConfigObject(self.inputOptions)
            return configObject.getAllRunningGroupNames(allApps)

    def createCheckBox(self, switch, *args):
        widget = guiplugins.OptionGroupGUI.createCheckBox(self, switch, *args)
        self.storeSwitch(switch, [widget])
        return widget

    def createRadioButtons(self, switch, *args):
        buttons = guiplugins.OptionGroupGUI.createRadioButtons(self, switch, *args)
        self.storeSwitch(switch, buttons)
        return buttons

    def storeSwitch(self, switch, widgets):
        if switch in self.disablingInfo:
            disablingOptionValue, group = self.disablingInfo[switch]
            if disablingOptionValue < len(widgets):
                self.disableWidgets[widgets[disablingOptionValue]] = switch, disablingOptionValue, group

    def getOption(self, optName):
        for group in self.optionGroups:
            opt = group.getOption(optName)
            if opt:
                return opt

    def getOptionGroups(self):
        return self.optionGroups

    def getCountMultiplier(self):
        return self.getCopyCount() * self.getVersionCount()

    def getCopyCount(self):
        return self.getOption("cp").getValue()

    def getVersionString(self):
        vOption = self.getOption("v")
        if vOption:
            versionString = vOption.getValue()
            return "" if versionString.startswith("<default>") else versionString
        else:
            return ""

    def getVersionCount(self):
        return self.getVersionString().count(",") + 1

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

    def getMultipleTestWarning(self):
        app = self.currTestSelection[0].app
        for group in self.getOptionGroups():
            for switchName, desc in app.getInteractiveReplayOptions():
                if group.getSwitchValue(switchName, False):
                    return "run " + self.describeTests() + " with " + desc + " replay enabled"

    def getConfirmationMessage(self):
        runVersion = self.getVersionString()
        if self.originalVersion and self.originalVersion not in runVersion:
            return "You have tried to run a version ('" + runVersion + \
                   "') which is not based on the version you started with ('" + self.originalVersion + "').\n" + \
                   "This will result in an attempt to amalgamate the versions, i.e. to run version '" + \
                   self.originalVersion + "." + runVersion + "'.\n" + \
                   "If this isn't what you want, you will need to restart the static GUI with a different '-v' flag.\n\n" + \
                   "Are you sure you want to continue?"
        else:
            return BasicRunningAction.getConfirmationMessage(self)

    def createNotebook(self):
        notebook = Gtk.Notebook()
        notebook.set_name("sub-notebook for running")
        tabNames = ["Basic", "Advanced"]
        frames = []
        for group in self.optionGroups:
            if group.name in tabNames:
                label = Gtk.Label(label=group.name)
                tab = self.createTab(group, frames)
                notebook.append_page(tab, label)
            elif len(list(group.keys())) > 0:
                frames.append(self.createFrame(group, group.name))
        self.connectDisablingSwitches()
        notebook.show_all()
        self.widget = notebook
        return notebook

    def createTab(self, group, frames):
        tabBox = Gtk.VBox()
        if frames:
            frames.append(self.createFrame(group, "Miscellaneous"))
            frames.append(self.createFrame(self.temporaryGroup,  self.temporaryGroup.name))
            for frame in frames:
                tabBox.pack_start(frame, False, False, 8)
        else:
            self.fillVBox(tabBox, group)
        if isinstance(self, guiplugins.ActionTabGUI):
            # In a tab, we need to duplicate the buttons for each subtab
            # In a dialog we should not do this
            self.createButtons(tabBox)
        widget = self.addScrollBars(tabBox, hpolicy=Gtk.PolicyType.AUTOMATIC)
        widget.set_name(group.name + " Tab")
        return widget

    def updateSensitivity(self, widget, data):
        switch, disablingOptionValue, group = data
        sensitive = switch.getValue() != disablingOptionValue
        self.setGroupSensitivity(group, sensitive, ignoreWidget=widget)

    def connectDisablingSwitches(self):
        for widget, data in list(self.disableWidgets.items()):
            self.updateSensitivity(widget, data)
            widget.connect("toggled", self.updateSensitivity, data)
        self.disableWidgets = {}  # not needed any more

    def notifyReset(self, *args):
        for optionGroup in self.optionGroups:
            optionGroup.reset()
        self.temporaryGroup.reset()

    def _getStockId(self):
        return "media-play"


class RunTests(RunningAction, guiplugins.ActionTabGUI):
    def __init__(self, allApps, dummy, inputOptions):
        guiplugins.ActionTabGUI.__init__(self, allApps)
        RunningAction.__init__(self, allApps, inputOptions)

    def _getTitle(self):
        return "_Run"

    def getTooltip(self):
        return "Run selected tests"

    def getUseCaseName(self):
        return "dynamic"

    def createView(self):
        return self.createNotebook()

    def updateName(self, nameOption, name):
        if name:
            nameOption.setValue("Tests started from " + repr(name) + " at <time>")

    def notifySetRunName(self, name):
        nameOption = self.getOption("name")
        self.updateName(nameOption, name)

    def addApplicationOptions(self, allApps, group, inputOptions):
        guiplugins.ActionTabGUI.addApplicationOptions(self, allApps, group, inputOptions)
        nameOption = group.getOption("name")
        if nameOption:
            self.updateName(nameOption, nameOption.getValue())


class RerunTests(RunningAction, guiplugins.ActionDialogGUI):
    def __init__(self, allApps, dummy, inputOptions):
        guiplugins.ActionDialogGUI.__init__(self, allApps)
        RunningAction.__init__(self, allApps, inputOptions)
        self.rerunTests = []
        for group in self.optionGroups:
            if group.name == "Basic":
                group.addSwitch("mark", "Mark test as rerun in current window", 1, description="Test will be automatically marked as having a newer result elsewhere." +
                                "It will also be possible to import this result here in future.")
                return

    def updateOptions(self):
        checkouts = []
        for app in self.currAppSelection:
            path = app.getGivenCheckoutPath(app)
            if path and path not in checkouts and not app.isAutogeneratedFromCwd(path):
                checkouts.append(path)
        if checkouts:
            self.getOption("c").setValue(",".join(checkouts))

    def _getTitle(self):
        return "_Rerun"

    def getTooltip(self):
        return "Rerun selected tests"

    def getUseCaseName(self):
        return "rerun"

    def getSignalsSent(self):
        return RunningAction.getSignalsSent(self) + ["Mark"]

    def killOnTermination(self):
        return False  # don't want rerun GUIs to disturb each other like this

    def getCommandLineExcludeKeys(self):
        return ["mark"]

    def getTmpFilterDir(self, app):
        return ""  # don't want selections returned here, send them to the static GUI

    def getConfirmationMessage(self):
        return BasicRunningAction.getConfirmationMessage(self)

    def getTextTestOptions(self, filterFile, app, usecase):
        rerunId = str(self.runNumber)
        if not self.getOption("name").getValue():
            rerunId += " from " + plugins.startTimeString()
        return RunningAction.getTextTestOptions(self, filterFile, app, usecase) + ["-rerun", rerunId]

    def getLogRootDirectory(self, app):
        if "f" in self.inputOptions:
            logRootDir = os.path.dirname(self.inputOptions["f"])
            if os.path.basename(logRootDir).startswith("dynamic_run"):
                return logRootDir
        return BasicRunningAction.getLogRootDirectory(self, app)

    def getRunWriteDirectory(self, app):
        fromDynamic = self.startedFromDynamicGui(app)
        if fromDynamic:
            return os.path.join(os.getenv("TEXTTEST_TMP"), "dynamic_run" + str(self.runNumber) + "_" + plugins.startTimeString().replace(":", ""))
        else:
            return RunningAction.getRunWriteDirectory(self, app)

    def startedFromDynamicGui(self, app):
        return not app.useStaticGUI() and not "dynamic_run" in os.path.basename(self.getLogRootDirectory(app))

    def getExtraParent(self, app):
        for other in self.validApps:
            if app in other.extras:
                return other

    def getExtraVersions(self, app):
        if app.extras or any((v.startswith("copy_") for v in app.versions)):
            return []
        extraParent = self.getExtraParent(app)
        if extraParent:
            return [v for v in app.versions if v not in extraParent.versions]
        else:
            extrasGiven = app.getConfigValue("extra_version")
            return [v for v in app.versions if v in extrasGiven]

    def getAppIdentifier(self, app):
        parts = [app.name] + self.getExtraVersions(app)
        return ".".join(parts)

    def checkTestRun(self, errFile, testSel, filterFile, usecase):
        # Don't do anything with the files, but do produce popups on failures and notify when complete
        self.checkErrorFile(errFile, testSel, usecase)
        if len(testSel) > 0:
            app = testSel[0].app
            if not app.keepTemporaryDirectories() and self.startedFromDynamicGui(app):
                writeDir = os.path.dirname(errFile)
                plugins.rmtree(writeDir)
            testSel[0].notify("CloseDynamic", usecase)

    def getOrderedOptions(self, optionGroup):
        options, switches = self.extractSwitches(optionGroup)
        return options + switches

    def fillVBox(self, vbox, optionGroup):
        if optionGroup is self.optionGroup:
            notebook = self.createNotebook()
            vbox.pack_start(notebook, True, True, 0)
            return None, None  # no file chooser info
        else:
            return guiplugins.ActionDialogGUI.fillVBox(self, vbox, optionGroup, includeOverrides=False)

    def performOnCurrent(self):
        RunningAction.performOnCurrent(self)
        if self.getOption("mark").getValue():
            lastRunText = str(self.runNumber - 1)
            self.rerunTests = copy(self.currTestSelection)
            for test in self.currTestSelection:
                self.notify("Mark", test, "Test is being rerun in another window, numbered " +
                            lastRunText, "Rerun " + lastRunText)

    def getTestCaseSelection(self):
        if self.rerunTests:
            tests = self.rerunTests
            self.rerunTests = []
            return tests
        else:
            return guiplugins.ActionDialogGUI.getTestCaseSelection(self)

    def getSizeAsWindowFraction(self):
        return 0.8, 0.9


class RecordTest(BasicRunningAction, guiplugins.ActionDialogGUI):
    def __init__(self, allApps, dynamic, inputOptions):
        guiplugins.ActionDialogGUI.__init__(self, allApps, dynamic)
        BasicRunningAction.__init__(self, inputOptions)
        self.recordTime = None
        self.currentApp = None
        if len(allApps) > 0:
            self.currentApp = allApps[0]
        self.addOptions()
        self.addSwitches()

    def addOptions(self):
        defaultVersion, defaultCheckout = "", ""
        if self.currentApp:
            defaultVersion = self.currentApp.getFullVersion()
            defaultCheckout = self.currentApp.getCheckoutForDisplay()

        self.addOption("v", "Version to record", defaultVersion)
        self.addOption("c", self.getCheckoutLabel(), defaultCheckout)
        self.addOption("m", "Record on machine")

    def getCheckoutLabel(self):
        # Sometimes configurations might want to use their own term in place of "checkout"
        return "Checkout to use for recording"

    def addSwitches(self):
        if self.currentApp and self.currentApp.usesCaptureMock():
            self.currentApp.addCaptureMockSwitch(self.optionGroup, value=1)  # record new by default
        self.addSwitch("rep", "Automatically replay test after recording it", 2,
                       options=["Disabled", "In background", "Using dynamic GUI"])
        if self.currentApp and self.currentApp.getConfigValue("extra_test_process_postfix"):
            self.addSwitch("mult", "Record multiple runs of system")

    def correctTestClass(self):
        return "test-case"

    def _getStockId(self):
        return "media-record"

    def messageAfterPerform(self):
        return "Started record session for " + self.describeTests()

    def touchFiles(self, test):
        for postfix in test.getConfigValue("extra_test_process_postfix"):
            if not test.getFileName("usecase" + postfix):
                fileName = os.path.join(test.getDirectory(), "usecase" + postfix + "." + test.app.name)
                with open(fileName, "w") as f:
                    f.write("Dummy file to indicate we should record multiple runs\n")

    def performOnCurrent(self):
        test = self.currTestSelection[0]
        if self.optionGroup.getSwitchValue("mult"):
            self.touchFiles(test)
        self.updateRecordTime(test)
        self.startTextTestProcess("record", ["-g", "-record"] + self.getVanillaOption())

    def shouldShowCurrent(self, *args):
        # override the default so it's disabled if there are no apps
        return len(self.validApps) > 0 and guiplugins.ActionDialogGUI.shouldShowCurrent(self, *args)

    def isValidForApp(self, app):
        return app.getConfigValue("use_case_record_mode") != "disabled" and \
            app.getConfigValue("use_case_recorder") != "none"

    def updateOptions(self):
        if self.currentApp is not self.currAppSelection[0]:
            self.currentApp = self.currAppSelection[0]
            self.optionGroup.setOptionValue("v", self.currentApp.getFullVersion())
            self.optionGroup.setOptionValue("c", self.currentApp.getCheckoutForDisplay())
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
            return True
        else:
            return False

    def getChangedUseCaseVersion(self, test):
        test.refreshFiles()  # update cache after record run
        file = self.getUseCaseFile(test)
        if not file or not self._updateRecordTime(file):
            return

        parts = os.path.basename(file).split(".")
        return ".".join(parts[2:])

    def getMultipleTestWarning(self):
        return "record " + self.describeTests() + " simultaneously"

    def handleCompletion(self, testSel, filterFile, usecase):
        test = testSel[0]
        if usecase == "record":
            changedUseCaseVersion = self.getChangedUseCaseVersion(test)
            replay = self.optionGroup.getSwitchValue("rep")
            if changedUseCaseVersion is not None and replay:
                replayOptions = self.getVanillaOption() + self.getReplayRunModeOptions(changedUseCaseVersion)
                self.startTextTestProcess("replay", replayOptions, testSel, filterFile)
                message = "Recording completed for " + repr(test) + \
                          ". Auto-replay of test now started. Don't submit the test manually!"
                self.notify("Status", message)
            else:
                self.notify("Status", "Recording completed for " + repr(test) + ", not auto-replaying")
        else:
            self.notify("Status", "Recording and auto-replay completed for " + repr(test))

    def getCommandLineKeys(self, usecase):
        keys = ["v", "c", "m"]
        if usecase == "record":
            keys.append("rectraffic")
        return keys

    def getReplayRunModeOptions(self, overwriteVersion):
        if self.optionGroup.getSwitchValue("rep") == 2:
            return ["-autoreplay", "-g"]
        else:
            return ["-autoreplay", "-o", overwriteVersion]

    def _getTitle(self):
        return "Record _Use-Case"

    def getSizeAsWindowFraction(self):
        return 0.5, 0.5


class RunScriptAction(BasicRunningAction):
    def getUseCaseName(self):
        return "script"

    def performOnCurrent(self, **kw):
        self.startTextTestProcess(self.getUseCaseName(), ["-g"] + self.getVanillaOption(), **kw)

    def getCommandLineArgs(self, optionGroup, *args):
        args = [self.scriptName()]
        for key, option in list(optionGroup.options.items()):
            args.append(key + "=" + str(option.getValue()))

        return ["-s", " ".join(args)]


class ReplaceText(RunScriptAction, guiplugins.ActionDialogGUI):
    def __init__(self, allApps, dynamic, inputOptions):
        RunScriptAction.__init__(self, inputOptions)
        guiplugins.ActionDialogGUI.__init__(self, allApps, dynamic)
        self.addSwitch("regexp", "Enable regular expressions", 1)
        self.addOption("old", "Text or regular expression to search for", multilineEntry=True)
        self.addOption("new", "Text to replace it with (may contain regexp back references)", multilineEntry=True)
        self.addOption("file", "File stem(s) to perform replacement in", allocateNofValues=2)
        self.storytextDirs = {}

    def getCmdlineOptionForApps(self, filterFile):
        options = RunScriptAction.getCmdlineOptionForApps(self, filterFile)
        if self.shouldAddShortcuts():
            options[1] = options[1] + ",shortcut"
            directoryStr = os.path.dirname(filterFile) + os.pathsep + os.pathsep.join(self.inputOptions.rootDirectories)
            options += ["-d", directoryStr]
        return options

    def createFilterFile(self, writeDir, filterFileOverride):
        filterFileName = RunScriptAction.createFilterFile(self, writeDir, filterFileOverride)
        if self.shouldAddShortcuts():
            storytextDir = self.storytextDirs[self.currAppSelection[0]]
            self.createShortcutApps(writeDir)
            with open(filterFileName, "a") as filterFile:
                filterFile.write("appdata=shortcut\n")
                filterFile.write(os.path.basename(storytextDir) + "\n")
        return filterFileName

    def notifyAllStems(self, allStems, defaultTestFile):
        self.optionGroup.setValue("file", defaultTestFile)
        self.optionGroup.setPossibleValues("file", allStems)

    def notifyNewTestSelection(self, *args):
        guiplugins.ActionDialogGUI.notifyNewTestSelection(self, *args)
        if len(self.storytextDirs) > 0:
            self.addSwitch("includeShortcuts", "Replace text in shortcut files", 0)

    def shouldAddShortcuts(self):
        return len(self.storytextDirs) > 0 and self.optionGroup.getOptionValue("includeShortcuts") > 0

    def notifyUsecaseRename(self, argstr, *args):
        self.showQueryDialog(self.getParentWindow(), "Usecase names were renamed. Would you like to update them in all usecases now?",
                             Gtk.STOCK_DIALOG_WARNING, "Confirmation", self.respondUsecaseRename, respondData=(argstr, False, "*usecase*,stdout"))

    def notifyShortcutRename(self, argstr, *args):
        self.showQueryDialog(self.getParentWindow(), "Shortcuts were renamed. Would you like to update all usecases now?",
                             Gtk.STOCK_DIALOG_WARNING, "Confirmation", self.respondUsecaseRename, respondData=(argstr, True, "*usecase*"))

    def notifyShortcutRemove(self, argstr, *args):
        self.showQueryDialog(self.getParentWindow(), "Shortcuts were removed. Would you like to update all usecases now?",
                             Gtk.STOCK_DIALOG_WARNING, "Confirmation", self.respondUsecaseRename, respondData=(argstr, True, "*usecase*"))

    def respondUsecaseRename(self, dialog, ans, args):
        if ans == Gtk.ResponseType.YES:
            oldName, newName = args[0].split(" renamed to ")
            if args[1]:
                self.optionGroup.setValue("regexp", 1)
                self.addSwitch("argsReplacement", "", 1)
            self.optionGroup.setValue("file", args[2])
            self.optionGroup.setValue("old", oldName.strip("'"))
            self.optionGroup.setValue("new", newName.strip("'"))
            self.performOnCurrent(filterFileOverride=NotImplemented)
        dialog.hide()

    def createShortcutApps(self, writeDir):
        for app, storyTextHome in list(self.storytextDirs.items()):
            self.createConfigFile(app, writeDir)
            self.createTestSuiteFile(app, storyTextHome, writeDir)

    def createConfigFile(self, app, writeDir):
        configFileName = os.path.join(writeDir, "config.shortcut")
        with open(configFileName, "w") as configFile:
            configFile.write("executable:None\n")
            configFile.write("filename_convention_scheme:standard\n")
            configFile.write("use_case_record_mode:GUI\n")
            configFile.write("use_case_recorder:storytext")
        return configFileName

    def createTestSuiteFile(self, app, storyTextHome, writeDir):
        suiteFileName = os.path.join(writeDir, "testsuite.shortcut")
        with open(suiteFileName, "w") as suiteFile:
            suiteFile.write(storyTextHome + "\n")
        return suiteFileName

    def scriptName(self):
        return "default.ReplaceText"

    def _getTitle(self):
        return "Replace Text in Files"

    def getTooltip(self):
        return "Replace text in multiple test files"

    def performedDescription(self):
        return "Replaced text in files for"

    def getSizeAsWindowFraction(self):
        # size of the dialog
        return 0.5, 0.5

    def notifyUsecaseHome(self, suite, usecaseHome):
        self.storytextDirs[suite.app] = usecaseHome

    def _respond(self, saidOK=True, dialog=None, fileChooserOption=None):
        if saidOK and not self.optionGroup.getValue("old"):
            self.showWarningDialog("Text or regular expression to search for cannot be empty")
        else:
            guiplugins.ActionDialogGUI._respond(self, saidOK, dialog, fileChooserOption)


class TestFileFilterHelper:
    def showTextInFile(self, text):
        test = self.currTestSelection[0]
        fileName = self.currFileSelection[0][0]
        root = test.getEnvironment("TEXTTEST_SANDBOX_ROOT")
        plugins.ensureDirectoryExists(root)
        tmpFileNameLocal = os.path.basename(fileName) + " (FILTERED)"
        tmpFileName = os.path.join(root, tmpFileNameLocal)
        bakFileName = tmpFileName + ".bak"
        if os.path.isfile(bakFileName):
            os.remove(bakFileName)
        if os.path.isfile(tmpFileName):
            os.rename(tmpFileName, bakFileName)
        with open(tmpFileName, "w") as tmpFile:
            tmpFile.write(text)

        # Don't want people editing by mistake, remove write permissions
        os.chmod(tmpFileName, stat.S_IREAD)
        self.notify("ViewReadonlyFile", tmpFileName)

    def getSignalsSent(self):
        return ["ViewReadonlyFile"]


class TestFileFiltering(TestFileFilterHelper, guiplugins.ActionGUI):
    def _getTitle(self):
        return "Test Filtering"

    def isActiveOnCurrent(self, *args):
        return guiplugins.ActionGUI.isActiveOnCurrent(self) and len(self.currFileSelection) == 1

    def getTextToShow(self, test, fileName):
        return test.app.applyFiltering(test, fileName)

    def performOnCurrent(self):
        self.reloadConfigForSelected()  # Always make sure we're up to date here
        text = self.getTextToShow(self.currTestSelection[0], self.currFileSelection[0][0])
        self.showTextInFile(text)


class ShowFilters(TestFileFilterHelper, guiplugins.ActionResultDialogGUI):
    def __init__(self, *args, **kw):
        guiplugins.ActionResultDialogGUI.__init__(self, *args, **kw)
        self.textBuffer = None
        self.filtersWithModels = []
        self.toRemove = {}

    def _getTitle(self):
        return "Show Filters"

    def isActiveOnCurrent(self):
        return len(self.currFileSelection) == 1 and len(self.currTestSelection) == 1

    def addContents(self):
        self.reloadConfigForSelected()  # Always make sure we're up to date here
        fileName = self.currFileSelection[0][0]
        test = self.currTestSelection[0]
        allFilters, versionApp = test.app.getAllFilters(test, fileName)
        if allFilters:
            self.addFilterBoxes(allFilters, fileName, test, versionApp)
        else:
            messageBox = self.createDialogMessage(
                "No run_dependent_text filters defined for file '" + os.path.basename(fileName) + "' for this test.", Gtk.STOCK_DIALOG_INFO)
            self.dialog.vbox.pack_start(messageBox, True, True, 0)

    def editFilter(self, cell, path, newText, model):
        lineFilter = model[path][0]
        model[path][0] = lineFilter.makeNew(newText)

    def showToggled(self, cell, path, model):
        # Toggle the toggle button
        newValue = not model[path][1]
        model[path][1] = newValue

    def setText(self, column, cell, model, iter):
        cell.set_property('text', model.get_value(iter, 0).originalText)

    def getStem(self, fileName):
        return os.path.basename(fileName).split(".")[0]

    def addRow(self, menuItem, model, selection, configKey):
        iter = self.getSelectedIters(selection)[-1]
        lineFilter, relpath, stem = model.get(iter, 0, 2, 3)
        newIter = model.insert_after(iter, [lineFilter.makeNew(""), True, relpath, stem, ""])
        path = model.get_path(newIter)
        column = selection.get_tree_view().get_column(0)
        selection.get_tree_view().set_cursor(path, column, start_editing=True)

    def getSelectedIters(self, selection):
        iters = []

        def addSelIter(model, path, iter):
            iters.append(iter)

        selection.selected_foreach(addSelIter)
        return iters

    def removeRow(self, menuItem, model, selection, configKey):
        for iter in self.getSelectedIters(selection):
            self.addChangeData(model, iter, configKey, self.toRemove)
            model.remove(iter)

    def makePopup(self, *args):
        menu = Gtk.Menu()
        menuItem = Gtk.MenuItem("Add Row")
        menu.append(menuItem)
        menuItem.connect("activate", self.addRow, *args)
        menuItem.show()
        menuItem = Gtk.MenuItem("Remove")
        menu.append(menuItem)
        menuItem.connect("activate", self.removeRow, *args)
        menuItem.show()
        return menu

    def showPopup(self, treeview, event, popupMenu):
        if event.button == 3:
            pathInfo = treeview.get_path_at_pos(int(event.x), int(event.y))
            if pathInfo is not None:
                treeview.grab_focus()
                popupMenu.popup(None, None, None, event.button, event.time)

    def addFilterBoxes(self, allFilters, fileName, test, versionApp):
        filterFrame = Gtk.Frame.new("Filters to apply")
        filterFrame.set_border_width(1)
        vbox = Gtk.VBox()
        for filterObj in allFilters:
            listStore = Gtk.ListStore(GObject.TYPE_PYOBJECT, bool, str, str, str)
            for lineFilter in filterObj.lineFilters:
                lineFilterFile, stem = test.getConfigFileDefining(
                    versionApp, filterObj.configKey, self.getStem(fileName), lineFilter.originalText)
                relPath = plugins.relpath(lineFilterFile, test.app.getDirectory()) if lineFilterFile else "???"
                listStore.append([lineFilter, True, relPath, stem, lineFilter.originalText])
            treeView = Gtk.TreeView(listStore)
            treeView.set_name(filterObj.configKey + " Tree View")

            cell = Gtk.CellRendererText()
            cell.set_property('editable', True)
            cell.connect('edited', self.editFilter, listStore)
            column = Gtk.TreeViewColumn(filterObj.configKey.replace("_", "__"))
            column.pack_start(cell, True)
            column.set_cell_data_func(cell, self.setText)
            treeView.append_column(column)

            toggleCell = Gtk.CellRendererToggle()
            toggleCell.set_property('activatable', True)
            toggleCell.connect("toggled", self.showToggled, listStore)
            column = Gtk.TreeViewColumn("Enabled", toggleCell, active=1)
            treeView.append_column(column)

            cell = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn("Config File", cell, text=2)
            treeView.append_column(column)

            selection = treeView.get_selection()
            selection.set_mode(Gtk.SelectionMode.MULTIPLE)

            popup = self.makePopup(listStore, selection, filterObj.configKey)
            treeView.connect("button_press_event", self.showPopup, popup)

            frame = Gtk.Frame()
            frame.set_border_width(1)
            frame.add(treeView)
            vbox.pack_start(frame, True, True, 0)
            self.filtersWithModels.append((filterObj, listStore))
        filterFrame.add(vbox)
        self.dialog.vbox.pack_start(filterFrame, False, True, 0)
        self.dialog.vbox.pack_start(Gtk.Separator.new(Gtk.Orientation.HORIZONTAL), False, True, 0)
        frame, self.textBuffer = self.createTextWidget("Filter Text View", scroll=True)
        frame.set_label("Text to filter (copied from " + os.path.basename(fileName) + ")")
        with open(fileName) as f:
            self.textBuffer.set_text(f.read())
        self.dialog.vbox.pack_start(frame, True, True, 0)

    def testFiltering(self, *args):
        filteredText = self.getFilteredText()
        self.showTextInFile(filteredText)

    def getText(self):
        return self.textBuffer.get_text(self.textBuffer.get_start_iter(), self.textBuffer.get_end_iter(), True)

    def updateFilter(self, fileFilter, model):
        enabledFilters = []

        def addFilter(model, path, iter):
            if model.get_value(iter, 1):
                enabledFilters.append(model.get_value(iter, 0))
        model.foreach(addFilter)
        fileFilter.lineFilters = enabledFilters

    def getFilteredText(self):
        inFile = StringIO()
        inFile.write(self.getText())
        inFile.seek(0)
        for fileFilter, model in self.filtersWithModels:
            self.updateFilter(fileFilter, model)
            outFile = StringIO()
            fileFilter.filterFile(inFile, outFile)
            inFile.close()
            inFile = outFile
            inFile.seek(0)
        value = outFile.getvalue()
        outFile.close()
        return value

    def addChangeData(self, model, iter, configKey, changes):
        fileName, stem, origText = model.get(iter, 2, 3, 4)
        oldLine = stem + ":" + origText
        newLine = None if changes is self.toRemove else stem + ":" + model.get_value(iter, 0).originalText
        changes.setdefault(fileName, {}).setdefault(configKey, []).append((oldLine, newLine))

    def getChanges(self):
        changes = {}

        def addChange(model, path, iter, configKey):
            text = model.get_value(iter, 0).originalText
            oldText = model.get_value(iter, 4)
            if text != oldText:
                self.addChangeData(model, iter, configKey, changes)
        for fileFilter, model in self.filtersWithModels:
            model.foreach(addChange, fileFilter.configKey)
        for fileName, removeData in list(self.toRemove.items()):
            for removeKey, removeLines in list(removeData.items()):
                changes.setdefault(fileName, {}).setdefault(removeKey, []).extend(removeLines)
        self.toRemove = {}
        return changes

    def getSectionName(self, line):
        pos = line.find("]")
        return line[1:pos]

    def applyChanges(self, line, changeList):
        for oldText, newText in changeList:
            if line.startswith(oldText):
                if oldText.endswith(":") and newText.startswith(oldText):
                    # Adding a new row
                    return line, newText
                else:
                    return line.replace(oldText, newText, 1) if newText else None, None
        return line, None

    def saveChanges(self):
        changesByFile = self.getChanges()
        if changesByFile:
            app = self.currAppSelection[0]
            for fileName, changes in list(changesByFile.items()):
                newFileLines = []
                fullPath = os.path.join(app.getDirectory(), fileName)
                currSection = None
                currNewLines = []
                with open(fullPath) as f:
                    for line in f:
                        if line.startswith("["):
                            currSection = self.getSectionName(line)
                        elif currSection in changes:
                            line, newLine = self.applyChanges(line, changes.get(currSection))
                            if newLine:
                                currNewLines.append(newLine)
                        if line is not None:
                            if currNewLines and not line.startswith(currNewLines[0].split(":")[0]):
                                for newLine in currNewLines:
                                    newFileLines.append(newLine + "\n")
                                currNewLines = []
                            newFileLines.append(line)

                with open(fullPath, "w") as f:
                    for line in newFileLines:
                        f.write(line)

    def createButtons(self):
        button = self.dialog.add_button('Test Filtering', Gtk.ResponseType.NONE)
        button.connect("clicked", self.testFiltering)
        self.dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        self.dialog.add_button("Apply and Close", Gtk.ResponseType.ACCEPT)
        self.dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        self.dialog.connect("response", self.respond)

    def respond(self, dialog, responseId):
        if responseId == Gtk.ResponseType.ACCEPT:
            self.saveChanges()
        guiplugins.ActionResultDialogGUI.respond(self, dialog, responseId)

    def getSizeAsWindowFraction(self):
        return 0.8, 0.9


class InsertShortcuts(RunScriptAction, guiplugins.OptionGroupGUI):
    def __init__(self, allApps, dynamic, inputOptions):
        guiplugins.OptionGroupGUI.__init__(self, allApps, dynamic)
        RunScriptAction.__init__(self, inputOptions)

    def scriptName(self):
        return "default.InsertShortcuts"

    def _getTitle(self):
        return "Insert Shortcuts into Usecases"

    def getTootip(self):
        return self._getTitle()

    def notifyShortcut(self, *args):
        self.showQueryDialog(self.getParentWindow(), "New shortcuts were created. Would you like to insert them into all usecases now?",
                             Gtk.STOCK_DIALOG_WARNING, "Confirmation", self.respondShortcut)

    def respondShortcut(self, dialog, ans, *args):
        if ans == Gtk.ResponseType.YES:
            self.performOnCurrent(filterFileOverride=NotImplemented)
        dialog.hide()

    def performedDescription(self):
        return "Inserted shortcuts into usecases for"

    def isValidForApp(self, app):
        return app.getConfigValue("use_case_record_mode") != "disabled" and \
            app.getConfigValue("use_case_recorder") != "none"


def getInteractiveActionClasses(dynamic):
    if dynamic:
        return [RerunTests, ReloadTests]
    else:
        return [RunTests, RecordTest, ReconnectToTests, ReplaceText, ShowFilters, TestFileFiltering, InsertShortcuts]
