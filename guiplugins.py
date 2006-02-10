
import plugins, os, sys, shutil, string
from testmodel import TestCase
from threading import Thread
from glob import glob
from Queue import Queue, Empty
global scriptEngine
global processTerminationMonitor
from log4py import LOGLEVEL_NORMAL

# The purpose of this class is to provide a means to monitor externally
# started process, so that (a) code can be called when they exit, and (b)
# they can be terminated when TextTest is terminated.
class ProcessTerminationMonitor:
    def __init__(self):
        self.processes = []
        self.termQueue = Queue()
    def addMonitoring(self, process):
        self.processes.append(process)
        newThread = Thread(target=self.monitor, args=(process,))
        newThread.start()
    def monitor(self, process):
        process.waitForTermination()
        self.termQueue.put(process)
    def getTerminatedProcess(self):
        try:
            process = self.termQueue.get_nowait()
            self.processes.remove(process)
            return process
        except Empty:
            return None
    def killAll(self):
        # Don't leak processes
        for process in self.processes:
            if not process.hasTerminated():
                guilog.info("Killing '" + repr(process) + "' interactive process")
                process.killAll()

processTerminationMonitor = ProcessTerminationMonitor()

# The class to inherit from if you want test-based actions that can run from the GUI
class InteractiveAction(plugins.Action):
    def __init__(self, test, oldOptionGroup, optionName = ""):
        self.test = test
        self.optionGroup = plugins.OptionGroup(optionName, test.getConfigValue("gui_entry_overrides"), test.getConfigValue("gui_entry_options"))
    def getOptionGroups(self):
        return [ self.optionGroup ]
    def addOption(self, oldOptionGroup, key, name, value = "", possibleValues = []):
        if oldOptionGroup and oldOptionGroup.options.has_key(key):
            self.optionGroup.addOption(key, name, oldOptionGroup.getOptionValue(key), possibleValues)
        else:
            self.optionGroup.addOption(key, name, value, possibleValues)
    def addSwitch(self, oldOptionGroup, key, name, value = 0, nameForOff = None):
        if oldOptionGroup and oldOptionGroup.switches.has_key(key):
            self.optionGroup.addSwitch(key, name, oldOptionGroup.getSwitchValue(key), nameForOff)
        else:
            self.optionGroup.addSwitch(key, name, value, nameForOff)
    def canPerformOnTest(self):
        return self.test
    def getTitle(self):
        return None
    def matchesMode(self, dynamic):
        return 1
    def getScriptTitle(self):
        return self.getTitle()
    def startExternalProgram(self, commandLine, shellTitle = None, holdShell = 0, exitHandler=None, exitHandlerArgs=()):
        process = plugins.BackgroundProcess(commandLine, shellTitle=shellTitle, \
                                            holdShell=holdShell, exitHandler=exitHandler, exitHandlerArgs=exitHandlerArgs)
        processTerminationMonitor.addMonitoring(process)
        return process
    def startExtProgramNewUsecase(self, commandLine, usecase, \
                                  exitHandler, exitHandlerArgs, shellTitle=None, holdShell=0): 
        recScript = os.getenv("USECASE_RECORD_SCRIPT")
        if recScript:
            os.environ["USECASE_RECORD_SCRIPT"] = self.getNewUsecase(recScript, usecase)
        repScript = os.getenv("USECASE_REPLAY_SCRIPT")
        if repScript:
            # Dynamic GUI might not record anything (it might fail) - don't try to replay files that
            # aren't there...
            dynRepScript = self.getNewUsecase(repScript, usecase)
            if os.path.isfile(dynRepScript):
                os.environ["USECASE_REPLAY_SCRIPT"] = dynRepScript
            else:
                del os.environ["USECASE_REPLAY_SCRIPT"]
        process = self.startExternalProgram(commandLine, shellTitle, holdShell, exitHandler, exitHandlerArgs)
        if recScript:
            os.environ["USECASE_RECORD_SCRIPT"] = recScript
        if repScript:
            os.environ["USECASE_REPLAY_SCRIPT"] = repScript
        return process
    def getNewUsecase(self, script, usecase):
        dir, file = os.path.split(script)
        return os.path.join(dir, usecase + "_" + file)
    def getViewCommand(self, fileName):
        viewProgram = self.test.getConfigValue("view_program")
        if not plugins.canExecute(viewProgram):
            raise plugins.TextTestError, "Cannot find file editing program '" + viewProgram + \
                  "'\nPlease install it somewhere on your PATH or point the view_program setting at a different tool"
        return viewProgram + " " + fileName + plugins.nullRedirect(), viewProgram
    def viewFile(self, fileName, refresh=0):
        exitHandler = None
        if refresh:
            exitHandler = self.test.filesChanged
        commandLine, descriptor = self.getViewCommand(fileName)
        guilog.info("Viewing file " + fileName.replace(os.sep, "/") + " using '" + descriptor + "', refresh set to " + str(refresh))
        process = self.startExternalProgram(commandLine, exitHandler=exitHandler)
        scriptEngine.monitorProcess("views and edits test files", process, [ fileName ])
    def getTextTestName(self):
        return "python " + sys.argv[0]
    def describe(self, testObj, postText = ""):
        guilog.info(testObj.getIndent() + repr(self) + " " + repr(testObj) + postText)
    
# Plugin for saving tests (standard)
class SaveTest(InteractiveAction):
    def __init__(self, test, oldOptionGroup):
        InteractiveAction.__init__(self, test, oldOptionGroup, "Saving")
        self.comparisons = []
        if self.canPerformOnTest():
            extensions = test.app.getVersionFileExtensions(forSave = 1)
            # Include the default version always
            extensions.append("")
            self.addOption(oldOptionGroup, "v", "Version to save", test.app.getFullVersion(forSave = 1), extensions)
            self.addSwitch(oldOptionGroup, "over", "Replace successfully compared files also", 0)
            self.comparisons = test.state.getComparisons()
            multipleComparisons = (len(self.comparisons) > 1)
            if self.hasPerformance():
                self.addSwitch(oldOptionGroup, "ex", "Exact Performance", multipleComparisons, "Average Performance")
            if multipleComparisons:
                failedStems = [ comp.stem for comp in self.comparisons]
                self.addOption(oldOptionGroup, "sinf", "Save single file", possibleValues=failedStems)
    def __repr__(self):
        return "Saving"
    def canPerformOnTest(self):
        return self.isSaveable(self.test)
    def isSaveable(self, test):
        return test and test.state.isSaveable()
    def getTitle(self):
        return "Save"
    def matchesMode(self, dynamic):
        return dynamic
    def hasPerformance(self):
        for comparison in self.comparisons:
            if comparison.getType() != "failure" and comparison.hasDifferences():
                return 1
        return 0
    def getExactness(self):
        return int(self.optionGroup.getSwitchValue("ex", 1))
    def __call__(self, test):
        version = self.optionGroup.getOptionValue("v")
        saveDesc = " - version " + version + ", exactness " + str(self.getExactness())
        singleFile = self.optionGroup.getOptionValue("sinf")
        if singleFile:
            saveDesc += ", only file with stem " + singleFile
        overwriteSuccess = self.optionGroup.getSwitchValue("over")
        if overwriteSuccess:
            saveDesc += ", overwriting both failed and succeeded files"
        self.describe(test, saveDesc)
        testComparison = test.state
        if testComparison:
            if singleFile:
                testComparison.saveSingle(singleFile, self.getExactness(), version)
            else:
                testComparison.save(self.getExactness(), version, overwriteSuccess)
            test.notifyChanged()

# Plugin for viewing files (non-standard). In truth, the GUI knows a fair bit about this action,
# because it's special and plugged into the tree view. Don't use this as a generic example!
class ViewFile(InteractiveAction):
    def __init__(self, test, oldOptionGroup):
        InteractiveAction.__init__(self, test, oldOptionGroup, "Viewing")
        try:
            if test.state.hasStarted():
                self.addSwitch(oldOptionGroup, "rdt", "Include Run-dependent Text", 0)
                self.addSwitch(oldOptionGroup, "nf", "Show differences where present", 1)
                if not test.state.isComplete():
                    self.addSwitch(oldOptionGroup, "f", "Follow file rather than view it", 1)
        except AttributeError:
            # Will get given applications too, don't need options there
            pass
    def __repr__(self):
        return "Viewing file"
    def canPerformOnTest(self):
        return 0
    def tmpFile(self, comparison):
        if self.optionGroup.getSwitchValue("rdt"):
            return comparison.tmpFile
        else:
            return comparison.tmpCmpFile
    def stdFile(self, comparison):
        if self.optionGroup.getSwitchValue("rdt"):
            return comparison.stdFile
        else:
            return comparison.stdCmpFile
    def followFile(self, fileName):
        baseName = os.path.basename(fileName)
        title = self.test.name + " (" + baseName + ")"
        followProgram = self.test.app.getConfigValue("follow_program")
        if not plugins.canExecute(followProgram.split()[0]):
            raise plugins.TextTestError, "Cannot find file-following program '" + followProgram + \
                  "'\nPlease install it somewhere on your PATH or point the follow_program setting at a different tool"
        guilog.info("Following file " + title + " using '" + followProgram + "'")
        process = self.startExternalProgram(followProgram + " " + fileName, shellTitle=title)
        scriptEngine.monitorProcess("follows progress of test files", process)
    def view(self, comparison, fileName):
        if self.optionGroup.getSwitchValue("f"):
            return self.followFile(fileName)
        if not comparison:
            baseName = os.path.basename(fileName)
            refresh = int(baseName.startswith("testsuite.") or baseName.startswith("options."))
            return self.viewFile(fileName, refresh=refresh)
        if self.shouldTakeDiff(comparison):
            self.takeDiff(comparison)
        elif comparison.missingResult():
            self.viewFile(self.stdFile(comparison))
        else:
            self.viewFile(self.tmpFile(comparison))
    def shouldTakeDiff(self, comparison):
        if comparison.newResult() or comparison.missingResult() or not self.optionGroup.getSwitchValue("nf"):
            return 0
        if comparison.hasDifferences():
            return 1
        # Take diff on succeeded tests if they want run-dependent text
        return self.optionGroup.getSwitchValue("rdt")
    def takeDiff(self, comparison):
        diffProgram = self.test.app.getConfigValue("diff_program")
        if not plugins.canExecute(diffProgram):
            raise plugins.TextTestError, "Cannot find graphical difference program '" + diffProgram + \
                  "'\nPlease install it somewhere on your PATH or point the diff_program setting at a different tool"
        stdFile = self.stdFile(comparison)
        tmpFile = self.tmpFile(comparison)
        guilog.info("Comparing file " + os.path.basename(tmpFile) + " with previous version using '" + diffProgram + "'")
        process = self.startExternalProgram(diffProgram + " " + stdFile + " " + tmpFile + plugins.nullRedirect())
        scriptEngine.monitorProcess("shows graphical differences in test files", process)

# And a generic import test. Note acts on test suites
class ImportTest(InteractiveAction):
    def __init__(self, suite, oldOptionGroup):
        InteractiveAction.__init__(self, suite, oldOptionGroup, self.getTabTitle())
        if self.canPerformOnTest():
            self.optionGroup.addOption("name", self.getNameTitle(), self.getDefaultName(suite))
            self.optionGroup.addOption("desc", self.getDescTitle(), self.getDefaultDesc(suite))
    def getNameTitle(self):
        return self.testType() + " Name"
    def getDescTitle(self):
        return self.testType() + " Description"
    def getDefaultName(self, suite):
        return ""
    def getDefaultDesc(self, suite):
        return ""
    def getTabTitle(self):
        return "Adding " + self.testType()
    def getTitle(self):
        return "Add _" + self.testType()
    def testType(self):
        return ""
    def getNewTestName(self):
        # Overwritten in subclasses - occasionally it can be inferred
        return self.optionGroup.getOptionValue("name")
    def setUpSuite(self, suite):
        testName = self.getNewTestName()
        if len(testName) == 0:
            raise plugins.TextTestError, "No name given for new " + self.testType() + "!" + "\n" + \
                  "Fill in the 'Adding " + self.testType() + "' tab below."
        if testName.find(" ") != -1:
            raise plugins.TextTestError, "The new " + self.testType() + " name is not permitted to contain spaces, please specify another"
        guilog.info("Adding " + self.testType() + " " + testName + " under test suite " + repr(suite))
        testDir = self.createTest(suite, testName, self.optionGroup.getOptionValue("desc"))
        self.createTestContents(suite, testDir)
        newTest = suite.addTest(testName, testDir)
    def matchesMode(self, dynamic):
        return not dynamic
    def createTestContents(self, suite, testDir):
        pass
    def createTest(self, suite, testName, description):
        file = open(suite.testCaseFile, "a")
        file.write("\n")
        file.write("# " + description + "\n")
        file.write(testName + "\n")
        testDir = os.path.join(suite.abspath, testName.strip())
        if os.path.isdir(testDir):
            return testDir
        try:
            os.mkdir(testDir)
        except OSError:
            raise plugins.TextTestError, "Cannot create test - problems creating directory named " + testName.strip()
        return testDir

class RecordTest(InteractiveAction):
    def __init__(self, test, oldOptionGroup):
        InteractiveAction.__init__(self, test, oldOptionGroup, "Recording")
        self.recordMode = self.test.getConfigValue("use_case_record_mode")
        if self.canPerformOnTest():
            self.addSwitch(oldOptionGroup, "rep", "Automatically replay test after recording it", 1)
            self.addSwitch(oldOptionGroup, "repgui", "Auto-replay in dynamic GUI", nameForOff="Auto-replay invisible")
        if self.recordMode == "console":
            self.addSwitch(oldOptionGroup, "hold", "Hold record shell after recording")
    def __call__(self, test):
        description = "Running " + test.app.fullName + " in order to capture user actions..."
        guilog.info(description)
        recordUseCase = os.path.join(test.abspath, "usecase." + test.app.name + test.app.versionSuffix())
        if os.path.isfile(recordUseCase):
            os.remove(recordUseCase)
        self.startTextTestProcess(test, "record", description)
    def startTextTestProcess(self, test, usecase, shellDescription=""):
        shellTitle, holdShell = self.getShellInfo(shellDescription)
        ttOptions = self.getRunOptions(test, usecase)
        commandLine = self.getTextTestName() + " " + ttOptions
        if not shellTitle:
            if not os.path.isfile(test.app.writeDirectory):
                test.app.makeWriteDirectory()
            logFile = self.getLogFile(test, usecase, "run")
            errFile = self.getLogFile(test, usecase)
            commandLine +=  " > " + logFile + " 2> " + errFile
        process = self.startExtProgramNewUsecase(commandLine, usecase, \
                                                 exitHandler=self.textTestCompleted, exitHandlerArgs=(test,usecase),
                                                 shellTitle=shellTitle, holdShell=holdShell)
        if shellTitle:
            scriptEngine.monitorProcess("records use cases in a shell", process, [ test.inputFile, test.useCaseFile ])
    def getLogFile(self, test, usecase, type="errors"):
        return os.path.join(test.app.writeDirectory, usecase + "_" + type + ".log")
    def getShellInfo(self, description):
        if self.recordMode == "console" and description:
            return description, self.optionGroup.getSwitchValue("hold")
        else:
            return None, 0
    def canPerformOnTest(self):
        return self.recordMode != "disabled"
    def textTestCompleted(self, test, usecase):
        scriptEngine.applicationEvent(usecase + " texttest to complete")
        if usecase == "record":
            self.setTestRecorded(test, usecase)
        else:
            self.setTestReady(test, usecase)
        test.notifyChanged()
    def setTestRecorded(self, test, usecase):
        if not os.path.isfile(test.useCaseFile) and not os.path.isfile(test.inputFile):
            message = "Recording did not produce any results (no usecase or input file)"
            errFile = self.getLogFile(test, usecase)
            if os.path.isfile(errFile):
                errors = open(errFile).read()
                if len(errors) > 0:
                    message += " - details follow:\n" + errors
            raise plugins.TextTestError, message

        if self.optionGroup.getSwitchValue("rep"):
            self.startTextTestProcess(test, usecase="replay")
            test.state.freeText = "Recorded use case - now attempting to replay in the background to collect standard files" + \
                                  "\n" + "These will appear shortly. You do not need to submit the test manually."
        else:
            self.setTestReady(test)
    def setTestReady(self, test, usecase=""):
        test.state.freeText = "Recorded use case and collected all standard files"
    def getRunOptions(self, test, usecase):
        basicOptions = "-o -tp " + self.test.getRelPath() + " " + test.app.getRunOptions()
        if usecase == "record":
            return "-actrep " + basicOptions
        elif self.optionGroup.getSwitchValue("repgui"):
            return basicOptions.replace("-o ", "-g ")
        return basicOptions
    def matchesMode(self, dynamic):
        return not dynamic
    def __repr__(self):
        return "Recording"
    def getTitle(self):
        return "Record _Use-Case"
    
class ImportTestCase(ImportTest):
    def __init__(self, suite, oldOptionGroup):
        ImportTest.__init__(self, suite, oldOptionGroup)
        if self.canPerformOnTest():
            self.addDefinitionFileOption(suite, oldOptionGroup)
    def testType(self):
        return "Test"
    def addDefinitionFileOption(self, suite, oldOptionGroup):
        self.addOption(oldOptionGroup, "opt", "Command line options")
    def createTestContents(self, suite, testDir):
        self.writeDefinitionFiles(suite, testDir)
        self.writeEnvironmentFile(suite, testDir)
        self.writeResultsFiles(suite, testDir)
    def getWriteFileName(self, name, suite, testDir):
        fileName = os.path.join(testDir, name + "." + suite.app.name)
        if os.path.isfile(fileName):
            raise plugins.TextTestError, "Test already exists for application " + suite.app.fullName + " : " + os.path.basename(testDir)
        return fileName
    def getWriteFile(self, name, suite, testDir):
        return open(self.getWriteFileName(name, suite, testDir), "w")
    def writeEnvironmentFile(self, suite, testDir):
        envDir = self.getEnvironment(suite)
        if len(envDir) == 0:
            return
        envFile = self.getWriteFile("environment", suite, testDir)
        for var, value in envDir.items():
            guilog.info("Setting test env: " + var + " = " + value)
            envFile.write(var + ":" + value + "\n")
        envFile.close()
    def writeDefinitionFiles(self, suite, testDir):
        optionString = self.getOptions(suite)
        guilog.info("Using option string : " + optionString)
        optionFile = self.getWriteFile("options", suite, testDir)
        optionFile.write(optionString + "\n")
        return optionString
    def getOptions(self, suite):
        return self.optionGroup.getOptionValue("opt")
    def getEnvironment(self, suite):
        return {}
    def writeResultsFiles(self, suite, testDir):
        # Cannot do anything in general
        pass

class ImportTestSuite(ImportTest):
    def __init__(self, suite, oldOptionGroup):
        ImportTest.__init__(self, suite, oldOptionGroup)
        if self.canPerformOnTest():
            self.addEnvironmentFileOptions(oldOptionGroup)
    def testType(self):
        return "Suite"
    def createTestContents(self, suite, testDir):
        self.writeTestcasesFile(suite, testDir)
        self.writeEnvironmentFiles(suite, testDir)
    def writeTestcasesFile(self, suite, testDir):
        testCasesFile = os.path.join(testDir, "testsuite." + suite.app.name)        
        file = open(testCasesFile, "w")
        file.write("# Ordered list of tests in test suite. Add as appropriate" + "\n" + "\n")
    def addEnvironmentFileOptions(self, oldOptionGroup):
        self.addSwitch(oldOptionGroup, "env", "Add environment file")
    def writeEnvironmentFiles(self, suite, testDir):
        if self.optionGroup.getSwitchValue("env"):
            envFile = os.path.join(testDir, "environment")
            file = open(envFile, "w")
            file.write("# Dictionary of environment to variables to set in test suite" + "\n")

class InteractiveAppAction(InteractiveAction):
    def canPerformOnTest(self):
        return 1
    def getSelectionOption(self, selTests):
        selTestPaths = []
        for test in selTests:
            relPath = test.getRelPath()
            if not relPath in selTestPaths:
                selTestPaths.append(relPath)
        return "-tp " + string.join(selTestPaths, ",")
    
class SelectTests(InteractiveAppAction):
    def __init__(self, app, oldOptionGroup):
        self.app = app
        self.test = app
        for group in app.optionGroups:
            if group.name.startswith("Select"):
                self.optionGroup = group
    def __repr__(self):
        return "Selecting"
    def getTitle(self):
        return "_Select"
    def getScriptTitle(self):
        return "Select indicated tests"
    def getFilterList(self):
        self.app.configObject.updateOptions(self.optionGroup)
        return self.app.configObject.getFilterList(self.app)
    def getSelectedTests(self, rootTestSuites):
        selectedTests = []
        filters = self.getFilterList()
        for suite in rootTestSuites:
            for filter in filters:
                if not filter.acceptsApplication(suite.app):
                    continue
                
            newTests = self.getTestsFromSuite(suite, filters)
            guilog.info("Selected " + str(len(newTests)) + " out of a possible " + str(suite.size()))
            selectedTests += newTests
        return selectedTests
    def getTestsFromSuite(self, suite, filters):
        if not suite.isAcceptedByAll(filters):
            return []
        try:
            tests = []
            for subSuite in self.findTestCaseList(suite):
                tests += self.getTestsFromSuite(subSuite, filters)
            return tests
        except AttributeError:
            return [ suite ]
    def findTestCaseList(self, suite):
        testcases = suite.testcases
        testCaseFiles = glob(os.path.join(suite.abspath, "testsuite.*"))
        if len(testCaseFiles) < 2:
            return testcases
        
        version = self.optionGroup.getOptionValue("vs")
        fullVersion = suite.app.getFullVersion()
        if len(fullVersion) > 0 and len(version) > 0:
            version += "." + fullVersion

        versionFile = suite.makeFileName("testsuite", version)
        newTestNames = plugins.readList(versionFile)
        newTestList = []
        for testCase in testcases:
            if testCase.name in newTestNames:
                newTestList.append(testCase)
        return newTestList

class ResetGroups(InteractiveAppAction):
    def getTitle(self):
        return "R_eset"
    def getScriptTitle(self):
        return "Reset running options"
    def performOn(self, app, selTests):
        for group in app.optionGroups:
            group.reset()

class SaveSelection(InteractiveAppAction):
    def __init__(self, app, oldOptionGroup):
        self.app = app
        InteractiveAction.__init__(self, app, oldOptionGroup, "Saving")
        self.addOption(oldOptionGroup, "name", "Name to give selection")
        self.addSwitch(oldOptionGroup, "tests", "Store actual tests selected", 1)
        for group in app.optionGroups:
            if group.name.startswith("Select"):
                self.selectionGroup = group
    def __repr__(self):
        return "Saving"
    def getTitle(self):
        return "S_ave Selection"
    def getScriptTitle(self):
        return "Save Selection"
    def getFileName(self, app):
        localName = self.optionGroup.getOptionValue("name")
        if not localName:
            raise plugins.TextTestError, "Must provide a file name to save, fill in the 'Saving' tab"
        dir = os.path.join(app.abspath, app.getConfigValue("test_list_files_directory")[0])
        plugins.ensureDirectoryExists(dir)
        return os.path.join(dir, localName)
    def getTextToSave(self, app, selTests):
        if len(selTests) == 0:
            raise plugins.TextTestError, "No tests are selected, cannot save selection!"
        actualTests = self.optionGroup.getSwitchValue("tests")
        if actualTests:
            return self.getSelectionOption(selTests)
        else:
            commandLines = self.selectionGroup.getCommandLines()
            return string.join(commandLines)
    def performOn(self, app, selTests):
        fileName = self.getFileName(app)
        toWrite = self.getTextToSave(app, selTests)
        file = open(fileName, "w")
        file.write(toWrite + "\n")
        file.close()
        filterFileOption = self.selectionGroup.options["f"]
        filterFileOption.addPossibleValue(os.path.basename(fileName))
    
class RunTests(InteractiveAppAction):
    runNumber = 1
    def __init__(self, app, oldOptionGroup):
        self.app = app
        self.test = app
        self.optionGroups = []
        for group in app.optionGroups:
            if group.name.startswith("Invisible"):
                self.invisibleGroup = group
            elif not group.name.startswith("Select"):
                self.optionGroups.append(group)
    def getOptionGroups(self):
        return self.optionGroups
    def __repr__(self):
        return "Running"
    def getTitle(self):
        return "_Run Tests"
    def getScriptTitle(self):
        return "Run selected tests"
    def performOn(self, app, selTests):
        selTestCases = filter(self.isTestCase, selTests)
        if len(selTestCases) == 0:
            raise plugins.TextTestError, "No tests selected - cannot run!"
        ttOptions = string.join(self.getTextTestOptions(app, selTestCases))
        app.makeWriteDirectory()
        logFile = os.path.join(app.writeDirectory, "dynamic_run" + str(self.runNumber) + ".log")
        errFile = os.path.join(app.writeDirectory, "dynamic_errors" + str(self.runNumber) + ".log")
        self.runNumber += 1
        commandLine = self.getTextTestName() + " " + ttOptions + " > " + logFile + " 2> " + errFile
        self.startExtProgramNewUsecase(commandLine, usecase="dynamic", exitHandler=self.checkTestRun, exitHandlerArgs=(errFile,))
    def isTestCase(self, test):
        return isinstance(test, TestCase)
    def checkTestRun(self, errFile):
        scriptEngine.applicationEvent("dynamic GUI to be closed")
        if os.path.isfile(errFile):
            errText = open(errFile).read()
            if len(errText):
                raise plugins.TextTestError, "Dynamic run failed, with the following errors:\n" + errText
    def getTextTestOptions(self, app, selTests):
        ttOptions = [ "-a " + app.name ]
        ttOptions += self.invisibleGroup.getCommandLines()
        for group in self.optionGroups:
            ttOptions += group.getCommandLines()
        ttOptions.append(self.getSelectionOption(selTests))
        return ttOptions

class EnableDiagnostics(InteractiveAction):
    def __init__(self, test, oldOptionGroup):
        InteractiveAction.__init__(self, test, oldOptionGroup)
        configDir = test.app.getConfigValue("diagnostics")
        self.configFile = None
        if configDir.has_key("configuration_file"):
            self.configFile = configDir["configuration_file"]
    def __repr__(self):
        return "Diagnostics"
    def getTitle(self):
        return "New _Diagnostics"
    def getScriptTitle(self):
        return "Enable Diagnostics"
    def matchesMode(self, dynamic):
        return not dynamic
    def canPerformOnTest(self):
        return self.test and self.configFile
    def __call__(self, test):
        diagDir = os.path.join(test.abspath, "Diagnostics")
        if not os.path.isdir(diagDir):
            os.mkdir(diagDir)
        diagFile = os.path.join(test.app.abspath, self.configFile)
        targetDiagFile = os.path.join(diagDir, self.configFile)
        shutil.copyfile(diagFile, targetDiagFile)
        self.viewFile(targetDiagFile, refresh=1)

class RemoveTest(InteractiveAction):
    def getTitle(self):
        return "Remove"
    def getScriptTitle(self):
        return "Remove Test"
    def matchesMode(self, dynamic):
        return not dynamic
    def __call__(self, test):
        plugins.rmtree(test.abspath)
        suite = test.parent
        self.removeFromTestFile(suite, test.name)
        suite.removeTest(test)
    def setUpSuite(self, suite):
        self(suite)
    def removeFromTestFile(self, suite, testName):
        newFileName = os.path.join(suite.app.writeDirectory, "tmptestsuite")
        newFile = plugins.openForWrite(newFileName)
        description = ""
        for line in open(suite.testCaseFile).xreadlines():
            stripLine = line.strip()
            description += line
            if line.startswith("#") or len(stripLine) == 0:
                continue
            
            if stripLine != testName:
                newFile.write(description)
            description = ""
        newFile.close()
        if guilog.get_loglevel() >= LOGLEVEL_NORMAL:
            difftool = suite.getConfigValue("text_diff_program")
            diffInfo = os.popen(difftool + " " + suite.testCaseFile + " " + newFileName).read()
            guilog.info("Changes made to testcase file : \n" + diffInfo)
            guilog.info("") # blank line
        plugins.movefile(newFileName, suite.testCaseFile)

class CopyTest(ImportTest):
    def __repr__(self):
        return "Copy"
    def testType(self):
        return "Test"
    def getTabTitle(self):
        return "Copying"
    def getNameTitle(self):
        return "Name of copied test"
    def getDescTitle(self):
        return "Description of new test"
    def getDefaultName(self, test):
        return test.name + "_copy"
    def getDefaultDesc(self, test):
        return "Copy of " + test.name
    def getTitle(self):
        return "_Copy"
    def getScriptTitle(self):
        return "Copy Test"
    def __call__(self, test):
        suite = test.parent
        self.setUpSuite(suite)
    def createTestContents(self, suite, testDir):
        for file in os.listdir(self.test.abspath):
            if suite.app.ownsFile(file):
                sourceFile = os.path.join(self.test.abspath, file)
                targetFile = os.path.join(testDir, file)
                shutil.copyfile(sourceFile, targetFile)
    
# Placeholder for all classes. Remember to add them!
class InteractiveActionHandler:
    def __init__(self):
        self.testClasses =  [ SaveTest, RecordTest, EnableDiagnostics, CopyTest, RemoveTest ]
        self.suiteClasses = [ ImportTestCase, ImportTestSuite, RemoveTest ]
        self.appClasses = [ SelectTests, RunTests, ResetGroups, SaveSelection ]
        self.optionGroupMap = {}
    def getInstance(self, test, className):
        instance = self.makeInstance(className, test)
        self.storeOptionGroup(className, instance)
        return instance
    def storeOptionGroup(self, className, instance):
        if len(instance.getOptionGroups()) == 1:
            self.optionGroupMap[className] = instance.getOptionGroups()[0]
    def getInstances(self, test, dynamic):
        instances = []
        classList = self.getClassList(test)
        for intvActionClass in classList:
            instance = self.makeInstance(intvActionClass, test)
            if instance.matchesMode(dynamic):
                self.storeOptionGroup(intvActionClass, instance)
                instances.append(instance)
        return instances
    def getClassList(self, test):
        if test.classId() == "test-case":
            return self.testClasses
        elif test.classId() == "test-suite":
            return self.suiteClasses
        else:
            return self.appClasses
    def makeInstance(self, className, test):
        module = test.getConfigValue("interactive_action_module")
        command = "from " + module + " import " + className.__name__ + " as realClassName"
        oldOptionGroup = []
        if self.optionGroupMap.has_key(className):
            oldOptionGroup = self.optionGroupMap[className]
        try:
            exec command
            return realClassName(test, oldOptionGroup)
        except ImportError:
            return className(test, oldOptionGroup)
        except:
            # If some invalid interactive action is provided, need to know which
            print "Error with interactive action", className.__name__
            raise sys.exc_type, sys.exc_value
        
interactiveActionHandler = InteractiveActionHandler()
guilog = None

def setUpGuiLog(dynamic):
    global guilog
    if dynamic:
        guilog = plugins.getDiagnostics("dynamic GUI behaviour")
    else:
        guilog = plugins.getDiagnostics("static GUI behaviour")
