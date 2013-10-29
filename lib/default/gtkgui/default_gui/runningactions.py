
"""
The various ways to launch the dynamic GUI from the static GUI
"""

import gtk, plugins, os, sys, stat
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
        return self.performedDescription() + " " + self.describeTestsWithCount() + " at " + plugins.localtime() + "."

    def describeTestsWithCount(self):
        if self.testCount == 1:
            return "test " + self.getTestCaseSelection()[0].getRelPath()
        else:
            return str(self.testCount) + " tests"

    def performOnCurrent(self):
        self.startTextTestProcess(self.getUseCaseName(), [ "-g" ])

    def getTestsAffected(self, testSelOverride):
        if testSelOverride:
            return testSelOverride
        else:
            # Take a copy so we aren't fooled by selection changes
            return copy(self.currTestSelection)
        
    def startTextTestProcess(self, usecase, runModeOptions, testSelOverride=None, filterFileOverride=None):
        app = self.getCurrentApplication()
        writeDir = os.path.join(self.getLogRootDirectory(app), "dynamic_run" + str(self.runNumber))
        plugins.ensureDirectoryExists(writeDir)
        filterFile = self.createFilterFile(writeDir, filterFileOverride)
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
        return [ "SaveSelection" ]

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
        interpreterArg = os.getenv("TEXTTEST_DYNAMIC_GUI_INTERPRETER", "") # Alternative interpreter for the dynamic GUI : mostly useful for coverage / testing
        if interpreterArg:
            return plugins.splitcmd(interpreterArg.replace("ttpython", sys.executable))
        else: # pragma: no cover - cannot test without StoryText on dynamic GUI
            return [ sys.executable ]

    def getOptionGroups(self):
        return [ self.optionGroup ]

    def getTextTestOptions(self, filterFile, app, usecase):
        ttOptions = self.getCmdlineOptionForApps(filterFile)
        for group in self.getOptionGroups():
            ttOptions += self.getCommandLineArgs(group, self.getCommandLineKeys(usecase))
        # May be slow to calculate for large test suites, cache it
        self.testCount = len(self.getTestCaseSelection())
        ttOptions += [ "-count", str(self.testCount * self.getCountMultiplier()) ]
        if filterFile:
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
        
    def getCmdlineOptionForApps(self, filterFile):
        if not filterFile:
            return []
        
        apps = sorted(self.currAppSelection, key=self.validApps.index)
        appNames = map(self.getAppIdentifier, apps)
        return [ "-a", ",".join(appNames) ]

    def checkTestRun(self, errFile, testSel, filterFile, usecase):
        if not testSel:
            return
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
    
    
class ReloadTests(BasicRunningAction,guiplugins.ActionDialogGUI):
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
        self.startTextTestProcess(self.getUseCaseName(), [ "-g", "-reconnect", self.getTmpDirectory() ] + self.getVanillaOption())
    
    def saveTestStates(self):
        for test in self.currTestSelection:
            if test.state.isComplete(): # might look weird but this notification also comes in scripts etc.
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
        notebook = gtk.Notebook()
        notebook.set_name("sub-notebook for running")
        tabNames = [ "Basic", "Advanced" ]
        frames = []
        for group in self.optionGroups:
            if group.name in tabNames:
                label = gtk.Label(group.name)
                tab = self.createTab(group, frames)
                notebook.append_page(tab, label)
            elif len(group.keys()) > 0:
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
    
    def getConfirmationMessage(self):
        return BasicRunningAction.getConfirmationMessage(self)
    
    def getLogRootDirectory(self, app):
        if self.inputOptions.has_key("f"):
            logRootDir = os.path.dirname(self.inputOptions["f"])
            if os.path.basename(logRootDir).startswith("dynamic_run"):
                return logRootDir
        return BasicRunningAction.getLogRootDirectory(self, app)
    
    def getExtraParent(self, app):
        for other in self.validApps:
            if app in other.extras:
                return other
    
    def getExtraVersions(self, app):
        if app.extras or any((v.startswith("copy_") for v in app.versions)):
            return []
        extraParent = self.getExtraParent(app)
        if extraParent:
            return filter(lambda v: v not in extraParent.versions, app.versions)
        else:
            extrasGiven = app.getConfigValue("extra_version")
            return filter(lambda v: v in extrasGiven, app.versions)

    def getAppIdentifier(self, app):
        parts = [ app.name ] + self.getExtraVersions(app)
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
        self.addOption("m", "Record on machine")

    def getCheckoutLabel(self):
        # Sometimes configurations might want to use their own term in place of "checkout"
        return "Checkout to use for recording"

    def addSwitches(self):
        if self.currentApp and self.currentApp.usesCaptureMock():
            self.currentApp.addCaptureMockSwitch(self.optionGroup, value=1) # record new by default
        self.addSwitch("rep", "Automatically replay test after recording it", 1,
                       options = [ "Disabled", "In background", "Using dynamic GUI" ])
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
        self.startTextTestProcess("record", [ "-g", "-record" ] + self.getVanillaOption())

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
        keys = [ "v", "c", "m" ]
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


class RunScriptAction(BasicRunningAction):
    def getUseCaseName(self):
        return "script"

    def performOnCurrent(self, **kw):
        self.startTextTestProcess(self.getUseCaseName(), [ "-g" ] + self.getVanillaOption(), **kw)

    def getCommandLineArgs(self, optionGroup, *args):
        args = [ self.scriptName() ]
        for key, option in optionGroup.options.items():
            args.append(key + "=" + str(option.getValue()))

        return [ "-s", " ".join(args) ]


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
            options += [ "-d", directoryStr ]
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
                             gtk.STOCK_DIALOG_WARNING, "Confirmation", self.respondUsecaseRename, respondData=(argstr, False, "*usecase*,stdout"))
        
    def notifyShortcutRename(self, argstr, *args):
        self.showQueryDialog(self.getParentWindow(), "Shortcuts were renamed. Would you like to update all usecases now?",
                             gtk.STOCK_DIALOG_WARNING, "Confirmation", self.respondUsecaseRename, respondData=(argstr, True, "*usecase*"))

    def notifyShortcutRemove(self, argstr, *args):
        self.showQueryDialog(self.getParentWindow(), "Shortcuts were removed. Would you like to update all usecases now?",
                             gtk.STOCK_DIALOG_WARNING, "Confirmation", self.respondUsecaseRename, respondData=(argstr, True, "*usecase*"))

    def respondUsecaseRename(self, dialog, ans, args):
        if ans == gtk.RESPONSE_YES:
            oldName, newName =  args[0].split(" renamed to ")
            if args[1]:
                self.optionGroup.setValue("regexp", 1)
                self.addSwitch("argsReplacement", "", 1)
            self.optionGroup.setValue("file", args[2])
            self.optionGroup.setValue("old", oldName.strip("'"))
            self.optionGroup.setValue("new", newName.strip("'"))
            self.performOnCurrent(filterFileOverride=NotImplemented)
        dialog.hide()

    def createShortcutApps(self, writeDir):
        for app, storyTextHome in self.storytextDirs.items():
            self.createConfigFile(app, writeDir)
            self.createTestSuiteFile(app, storyTextHome, writeDir)
    
    def createConfigFile(self, app, writeDir):
        configFileName = os.path.join(writeDir, "config.shortcut")
        with  open(configFileName, "w") as configFile:
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

class TestFileFiltering(guiplugins.ActionGUI):
    def _getTitle(self):
        return "Test Filtering"

    def isActiveOnCurrent(self, *args):
        return guiplugins.ActionGUI.isActiveOnCurrent(self) and len(self.currFileSelection) == 1

    def getVersion(self, test, fileName):
        fileVersions = set(os.path.basename(fileName).split(".")[1:])
        testVersions = set(test.app.versions + [ test.app.name ])
        additionalVersions = fileVersions.difference(testVersions)
        return ".".join(additionalVersions)

    def getTextToShow(self, test, fileName):
        version = self.getVersion(test, fileName)
        return test.app.applyFiltering(test, fileName, version)
    
    def performOnCurrent(self):
        self.reloadConfigForSelected() # Always make sure we're up to date here
        test = self.currTestSelection[0]
        fileName = self.currFileSelection[0][0]
        text = self.getTextToShow(test, fileName)
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
        return [ "ViewReadonlyFile" ]


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
                             gtk.STOCK_DIALOG_WARNING, "Confirmation", self.respondShortcut)
        
    def respondShortcut(self, dialog, ans, *args):
        if ans == gtk.RESPONSE_YES:
            self.performOnCurrent(filterFileOverride=NotImplemented)
        dialog.hide()
        
    def performedDescription(self):
        return "Inserted shortcuts into usecases for"
    
    def isValidForApp(self, app):
        return app.getConfigValue("use_case_record_mode") != "disabled" and \
               app.getConfigValue("use_case_recorder") != "none"

def getInteractiveActionClasses(dynamic):
    if dynamic:
        return [ RerunTests, ReloadTests ]
    else:
        return [ RunTests, RecordTest, ReconnectToTests, ReplaceText, TestFileFiltering, InsertShortcuts ]
