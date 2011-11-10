
"""
The various ways to launch the dynamic GUI from the static GUI
"""

import gtk, plugins, os, sys
from .. import guiplugins
from copy import copy, deepcopy

# Runs the dynamic GUI, but not necessarily with all the options available from the configuration
class BasicRunningAction:
    runNumber = 1
    def __init__(self, inputOptions):
        self.inputOptions = inputOptions
        self.testCount = 0
        
    def getTabTitle(self):
        return "Running"

    def messageAfterPerform(self):
        return self.performedDescription() + " " + self.describeTests() + " at " + plugins.localtime() + "."

    def performOnCurrent(self):
        self.startTextTestProcess(self.getUseCaseName(), [ "-g" ])

    def getTestsAffected(self, testSelOverride):
        if testSelOverride:
            return testSelOverride
        else:
            # Take a copy so we aren't fooled by selection changes
            return copy(self.currTestSelection)
        
    def startTextTestProcess(self, usecase, runModeOptions, testSelOverride=None, filterFileOverride=None):
        app = self.currAppSelection[0]
        writeDir = os.path.join(self.getLogRootDirectory(app), "dynamic_run" + str(self.runNumber))
        plugins.ensureDirectoryExists(writeDir)
        filterFile = filterFileOverride or self.getFilterFile(writeDir)
        ttOptions = runModeOptions + self.getTextTestOptions(filterFile, app, usecase)
        self.diag.info("Starting " + usecase + " run of TextTest with arguments " + repr(ttOptions))
        logFile = os.path.join(writeDir, "output.log")
        errFile = os.path.join(writeDir, "errors.log")
        BasicRunningAction.runNumber += 1
        description = "Dynamic GUI started at " + plugins.localtime()
        cmdArgs = self.getInterpreterArgs() + [ sys.argv[0] ] + ttOptions
        env = self.getNewUseCaseEnvironment(usecase)
        testsAffected = self.getTestsAffected(testSelOverride)
        guiplugins.processMonitor.startProcess(cmdArgs, description, env=env, killOnTermination=self.killOnTermination(),
                                               stdout=open(logFile, "w"), stderr=open(errFile, "w"),
                                               exitHandler=self.checkTestRun,
                                               exitHandlerArgs=(errFile,testsAffected,filterFile,usecase))

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
        return [ "SaveSelection" ]

    def getFilterFile(self, writeDir):
        # Because the description of the selection can be extremely long, we write it in a file and refer to it
        # This avoids too-long command lines which are a problem at least on Windows XP
        filterFileName = os.path.join(writeDir, "gui_select")
        self.notify("SaveSelection", filterFileName)
        return filterFileName
    
    def getInterpreterArgs(self):
        interpreterArg = os.getenv("TEXTTEST_DYNAMIC_GUI_INTERPRETER", "") # Alternative interpreter for the dynamic GUI : mostly useful for coverage / testing
        if interpreterArg:
            return plugins.splitcmd(interpreterArg.replace("ttpython", sys.executable))
        else: # pragma: no cover - cannot test without StoryText on dynamic GUI
            return [ sys.executable ]

    def getOptionGroups(self):
        return [ self.optionGroup ]

    def getTextTestOptions(self, filterFile, app, usecase):
        ttOptions = self.getCmdlineOptionForApps()
        for group in self.getOptionGroups():
            ttOptions += self.getCommandLineArgs(group, self.getCommandLineKeys(usecase))
        # May be slow to calculate for large test suites, cache it
        self.testCount = len(self.getTestCaseSelection())
        ttOptions += [ "-count", str(self.testCount * self.getCountMultiplier()) ]
        ttOptions += [ "-f", filterFile ]
        tmpFilterDir = self.getTmpFilterDir(app)
        if tmpFilterDir:
            ttOptions += [ "-fd", tmpFilterDir ]
        return ttOptions

    def getCommandLineKeys(self, *args):
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

    def getAppIdentifier(self, app):
        return app.name + app.versionSuffix()
        
    def getCmdlineOptionForApps(self):
        apps = sorted(self.currAppSelection, key=self.validApps.index)
        appNames = map(self.getAppIdentifier, apps)
        return [ "-a", ",".join(appNames) ]

    def checkTestRun(self, errFile, testSel, filterFile, usecase):
        if self.checkErrorFile(errFile, testSel, usecase):
            self.handleCompletion(testSel, filterFile, usecase)
            if len(self.currTestSelection) >= 1 and self.currTestSelection[0] in testSel:
                self.currTestSelection[0].filesChanged()

        testSel[0].notify("CloseDynamic", usecase)
    
    def checkErrorFile(self, errFile, testSel, usecase):
        if os.path.isfile(errFile):
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


class ReconnectToTests(BasicRunningAction,guiplugins.ActionDialogGUI):
    def __init__(self, allApps, dynamic, inputOptions):
        guiplugins.ActionDialogGUI.__init__(self, allApps, dynamic)
        BasicRunningAction.__init__(self, inputOptions)
        self.addOption("v", "Version to reconnect to")
        self.addOption("reconnect", "Temporary result directory", os.getenv("TEXTTEST_TMP", ""), selectDir=True, description="Specify a directory containing temporary texttest results. The reconnection will use a random subdirectory matching the version used.")
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
        self.startTextTestProcess(self.getUseCaseName(), [ "-g" ] + self.getVanillaOption())
    def getAppIdentifier(self, app):
        # Don't send version data, we have our own field with that info and it has a slightly different meaning
        return app.name
    def getSizeAsWindowFraction(self):
        return 0.8, 0.7

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
        ignoreTypes = [ "testsuite", "knownbugs", "stdin", "input", "testcustomize.py" ]
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
            ret += [ "-td", tmpDir ]
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

    def createCheckBox(self, switch):
        widget = guiplugins.OptionGroupGUI.createCheckBox(self, switch)
        self.storeSwitch(switch, [ widget ])
        return widget

    def createRadioButtons(self, switch, *args):
        buttons = guiplugins.OptionGroupGUI.createRadioButtons(self, switch, *args)
        self.storeSwitch(switch, buttons)
        return buttons

    def storeSwitch(self, switch, widgets):
        if self.disablingInfo.has_key(switch):
            disablingOptionValue, group = self.disablingInfo[switch]
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

    def getLowerBoundForSpinButtons(self):
        return 1

    def checkValid(self, app):
        if app.getConfigValue("use_case_record_mode") == "disabled" and app not in self.validApps:
            switch = self.getOption("actrep")
            if switch:
                self.hideChildWithLabel(self.widget, switch.name)
        return guiplugins.ActionTabGUI.checkValid(self, app)

    def hideChildWithLabel(self, widget, label):
        if hasattr(widget, "get_label") and widget.get_label() == label:
            widget.hide()
        elif hasattr(widget, "get_children"):
            for child in widget.get_children():
                self.hideChildWithLabel(child, label)

    def createNotebook(self):
        notebook = gtk.Notebook()
        notebook.set_name("sub-notebook for running")
        tabNames = [ "Basic", "Advanced" ]
        frames = []
        for group in self.optionGroups:
            if group.name in tabNames:
                label = gtk.Label(group.name)
                tab = self.createTab(group, frames)
                notebook.append_page(tab, label)
            else:
                frames.append(self.createFrame(group, group.name))
        self.connectDisablingSwitches()
        notebook.show_all()
        self.widget = notebook
        return notebook

    def createTab(self, group, frames):
        tabBox = gtk.VBox()
        if frames:
            frames.append(self.createFrame(group, "Miscellaneous"))
            frames.append(self.createFrame(self.temporaryGroup,  self.temporaryGroup.name))
            for frame in frames:
                tabBox.pack_start(frame, fill=False, expand=False, padding=8)
        else:
            self.fillVBox(tabBox, group)
        if isinstance(self, guiplugins.ActionTabGUI):
            # In a tab, we need to duplicate the buttons for each subtab
            # In a dialog we should not do this
            self.createButtons(tabBox)
        widget = self.addScrollBars(tabBox, hpolicy=gtk.POLICY_AUTOMATIC)
        widget.set_name(group.name + " Tab")
        return widget

    def updateSensitivity(self, widget, data):
        switch, disablingOptionValue, group = data
        sensitive = switch.getValue() != disablingOptionValue
        self.setGroupSensitivity(group, sensitive, ignoreWidget=widget)

    def connectDisablingSwitches(self):
        for widget, data in self.disableWidgets.items():
            self.updateSensitivity(widget, data)
            widget.connect("toggled", self.updateSensitivity, data)
        self.disableWidgets = {} # not needed any more

    def notifyReset(self, *args):
        for optionGroup in self.optionGroups:
            optionGroup.reset()

    def _getStockId(self):
        return "execute"


class RunTests(RunningAction,guiplugins.ActionTabGUI):
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


class RerunTests(RunningAction,guiplugins.ActionDialogGUI):
    def __init__(self, allApps, dummy, inputOptions):
        guiplugins.ActionDialogGUI.__init__(self, allApps)
        RunningAction.__init__(self, allApps, inputOptions)

    def _getTitle(self):
        return "_Rerun"

    def getTooltip(self):
        return "Rerun selected tests"

    def getUseCaseName(self):
        return "rerun"

    def killOnTermination(self):
        return False # don't want rerun GUIs to disturb each other like this

    def getTmpFilterDir(self, app):
        return "" # don't want selections returned here, send them to the static GUI
    
    def getLogRootDirectory(self, app):
        if self.inputOptions.has_key("f"):
            logRootDir = os.path.dirname(self.inputOptions["f"])
            if os.path.basename(logRootDir).startswith("dynamic_run"):
                return logRootDir
        return BasicRunningAction.getLogRootDirectory(self, app)

    def getAppIdentifier(self, app):
        parts = filter(lambda part: not part.startswith("copy_"), [ app.name ] + app.versions)
        return ".".join(parts)

    def checkTestRun(self, errFile, testSel, filterFile, usecase):
        # Don't do anything with the files, but do produce popups on failures and notify when complete
        self.checkErrorFile(errFile, testSel, usecase)
        testSel[0].notify("CloseDynamic", usecase)

    def fillVBox(self, vbox, optionGroup):
        if optionGroup is self.optionGroup:
            notebook = self.createNotebook()
            vbox.pack_start(notebook)
            return None, None # no file chooser info
        else:
            return guiplugins.ActionDialogGUI.fillVBox(self, vbox, optionGroup, includeOverrides=False)

    def getSizeAsWindowFraction(self):
        return 0.8, 0.9


class RecordTest(BasicRunningAction,guiplugins.ActionDialogGUI):
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
            defaultCheckout = self.currentApp.checkout

        self.addOption("v", "Version to record", defaultVersion)
        self.addOption("c", self.getCheckoutLabel(), defaultCheckout)

    def getCheckoutLabel(self):
        # Sometimes configurations might want to use their own term in place of "checkout"
        return "Checkout to use for recording"

    def addSwitches(self):
        if self.currentApp and self.currentApp.usesCaptureMock():
            self.currentApp.addCaptureMockSwitch(self.optionGroup, value=1) # record new by default
        self.addSwitch("rep", "Automatically replay test after recording it", 1,
                       options = [ "Disabled", "In background", "Using dynamic GUI" ])

    def correctTestClass(self):
        return "test-case"

    def _getStockId(self):
        return "media-record"

    def messageAfterPerform(self):
        return "Started record session for " + self.describeTests()

    def performOnCurrent(self):
        self.updateRecordTime(self.currTestSelection[0])
        self.startTextTestProcess("record", [ "-g", "-record" ] + self.getVanillaOption())

    def shouldShowCurrent(self, *args):
        # override the default so it's disabled if there are no apps
        return len(self.validApps) > 0 and guiplugins.ActionDialogGUI.shouldShowCurrent(self, *args) 

    def isValidForApp(self, app):
        return app.getConfigValue("use_case_record_mode") != "disabled" and \
               app.getConfigValue("use_case_recorder") != "none"

    def checkValid(self, app):
        guiplugins.ActionDialogGUI.checkValid(self, app)
        if self.widget and len(self.validApps) == 0:
            self.widget.hide()

    def updateOptions(self):
        if self.currentApp is not self.currAppSelection[0]:
            self.currentApp = self.currAppSelection[0]
            self.optionGroup.setOptionValue("v", self.currentApp.getFullVersion())
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
        keys = [ "v", "c" ]
        if usecase == "record":
            keys.append("rectraffic")
        return keys

    def getReplayRunModeOptions(self, overwriteVersion):
        if self.optionGroup.getSwitchValue("rep") == 2:
            return [ "-autoreplay", "-g" ]
        else:
            return [ "-autoreplay", "-o", overwriteVersion ]

    def _getTitle(self):
        return "Record _Use-Case"

    def getSizeAsWindowFraction(self):
        return 0.5, 0.5



class RunScriptAction(BasicRunningAction,guiplugins.ActionDialogGUI):
    def __init__(self, allApps, dynamic, inputOptions):
        guiplugins.ActionDialogGUI.__init__(self, allApps, dynamic)
        BasicRunningAction.__init__(self, inputOptions)
        
    def getUseCaseName(self):
        return "script"

    def performOnCurrent(self):
        self.startTextTestProcess(self.getUseCaseName(), [ "-g" ] + self.getVanillaOption())

    def getCommandLineArgs(self, optionGroup, *args):
        args = [ self.scriptName() ]
        for key, option in optionGroup.options.items():
            args.append(key + "=" + option.getValue())
            
        return [ "-s", " ".join(args) ]


class ReplaceText(RunScriptAction):
    def __init__(self, *args):
        RunScriptAction.__init__(self, *args)
        self.addOption("old", "Text or regular expression to search for")
        self.addOption("new", "Text to replace it with (may contain regexp back references)")
        self.addOption("file", "File stem(s) to perform replacement in", allocateNofValues=2)

    def notifyAllStems(self, allStems, defaultTestFile):
        self.optionGroup.setValue("file", defaultTestFile)
        self.optionGroup.setPossibleValues("file", allStems)

    def scriptName(self):
        return "default.ReplaceText"

    def _getTitle(self):
        return "Replace Text in Files"

    def getTooltip(self):
        return "Replace text in multiple test files"

    def performedDescription(self):
        return "Replaced text in files for"


class TestFileFiltering(guiplugins.ActionResultDialogGUI):
    def _getTitle(self):
        return "Test Filtering"

    def getDialogTitle(self):
        return "Filtered contents of " + os.path.basename(self.currFileSelection[0][0])

    def isActiveOnCurrent(self, *args):
        return guiplugins.ActionResultDialogGUI.isActiveOnCurrent(self) and len(self.currFileSelection) == 1

    def getVersion(self, test, fileName):
        fileVersions = set(fileName.split(".")[1:])
        testVersions = set(test.app.versions + [ test.app.name ])
        additionalVersions = fileVersions.difference(testVersions)
        return ".".join(additionalVersions)

    def getTextToShow(self):
        fileName = self.currFileSelection[0][0]
        test = self.currTestSelection[0]
        version = self.getVersion(test, fileName)
        return test.app.applyFiltering(test, fileName, version)
    
    def addContents(self):
        self.dialog.set_name("Test Filtering Window")
        text = self.getTextToShow()
        buffer = gtk.TextBuffer()
        buffer.set_text(text)
        
        textView = gtk.TextView(buffer)
        textView.set_editable(False)
        textView.set_cursor_visible(False)
        textView.set_left_margin(5)
        textView.set_right_margin(5)
        window = gtk.ScrolledWindow()
        window.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        window.add(textView)
        parentSize = self.topWindow.get_size()
        self.dialog.resize(int(parentSize[0] * 0.9), int(parentSize[1] * 0.7))
        self.dialog.vbox.pack_start(window, expand=True, fill=True)


    
def getInteractiveActionClasses(dynamic):
    if dynamic:
        return [ RerunTests ]
    else:
        return [ RunTests, RecordTest, ReconnectToTests, ReplaceText, TestFileFiltering ]
