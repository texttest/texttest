
import plugins, os, sys, shutil, string, types, time
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
    def listRunning(self, processesToCheck):
        running = []
        if len(processesToCheck) == 0:
            return running
        for process in self.processes:
            if not process.hasTerminated():
                for processToCheck in processesToCheck:
                    if plugins.isRegularExpression(processToCheck):
                        if plugins.findRegularExpression(processToCheck, process.description):
                            running.append("PID " + str(process.processId) + " : " + process.description)
                            break
                    elif processToCheck.lower() == "all" or process.description.find(processToCheck) != -1:
                            running.append("PID " + str(process.processId) + " : " + process.description)
                            break

        return running
    def killAll(self):
        # Don't leak processes
        for process in self.processes:
            if not process.hasTerminated():
                guilog.info("Killing '" + process.description.split()[0] + "' interactive process")
                process.killAll()

processTerminationMonitor = ProcessTerminationMonitor()
       
class InteractiveAction(plugins.Observable):
    def __init__(self):
        plugins.Observable.__init__(self)
        self.optionGroup = None
        optionName = self.getTabTitle()
        if optionName:
            self.optionGroup = plugins.OptionGroup(optionName, self.getConfigValue("gui_entry_overrides"), \
                                                   self.getConfigValue("gui_entry_options"))
    def __repr__(self):
        if self.optionGroup != None:
            return self.optionGroup.name
        else:
            return self.getSecondaryTitle()
    def getConfigValue(self, entryName):
        pass
    def getOptionGroups(self):
        if self.optionGroup:
            return [ self.optionGroup ]
        else:
            return []
    def isActive(self):
        return True
    def canPerform(self):
        return True # do we activate this via performOnCurrent() ?
    def getInterfaceDescription(self):
        return ""
    def getAccelerator(self):        
        pass
    def getStockId(self):
        pass
    def getTitle(self):
        pass
    def getSecondaryTitle(self):
        return self.getTitle()
    def getTooltip(self):
        return self.getScriptTitle(False)
    def messageBeforePerform(self):
        return "Performing '" + self.getSecondaryTitle() + "' on " + self.describeTests() + " ..."
    def messageAfterPerform(self):
        return "Done performing '" + self.getSecondaryTitle() + "' on " + self.describeTests() + "."
    def isFrequentUse(self):
        # Decides how accessible to make it...
        return False
    def getDoubleCheckMessage(self):
        return ""
    def inToolBar(self):
        return self.isFrequentUse() or len(self.getOptionGroups()) == 0
    def getTabTitle(self):
        return ""
    def getGroupTabTitle(self):
        # Default behaviour is not to create a group tab, override to get one...
        return "Test"
    def getScriptTitle(self, tab):
        baseTitle = self._getScriptTitle().replace("_", "")
        if tab and self.isFrequentUse():
            return baseTitle + " from tab"
        else:
            return baseTitle
    def _getScriptTitle(self):
        return self.getTitle()
    def addOption(self, oldOptionGroups, key, name, value = "", possibleValues = []):
        for oldOptionGroup in oldOptionGroups:
            if oldOptionGroup.options.has_key(key):
                return self.optionGroup.addOption(key, name, oldOptionGroup.getOptionValue(key), possibleValues)
        self.optionGroup.addOption(key, name, value, possibleValues)
    def addSwitch(self, oldOptionGroups, key, name, defaultValue = 0, options = []):
        for oldOptionGroup in oldOptionGroups:
            if oldOptionGroup.switches.has_key(key):
                return self.optionGroup.addSwitch(key, name, oldOptionGroup.getSwitchValue(key), options)
        self.optionGroup.addSwitch(key, name, defaultValue, options)
    def startExternalProgram(self, commandLine, description = "", shellTitle = None, holdShell = 0, exitHandler=None, exitHandlerArgs=()):
        process = plugins.BackgroundProcess(commandLine, description=description, shellTitle=shellTitle, \
                                            holdShell=holdShell, exitHandler=exitHandler, exitHandlerArgs=exitHandlerArgs)
        processTerminationMonitor.addMonitoring(process)
        return process
    def startExtProgramNewUsecase(self, commandLine, usecase, \
                                  exitHandler, exitHandlerArgs, shellTitle=None, holdShell=0, description = ""): 
        recScript = os.getenv("USECASE_RECORD_SCRIPT")
        if recScript:
            os.environ["USECASE_RECORD_SCRIPT"] = plugins.addLocalPrefix(recScript, usecase)
        repScript = os.getenv("USECASE_REPLAY_SCRIPT")
        if repScript:
            # Dynamic GUI might not record anything (it might fail) - don't try to replay files that
            # aren't there...
            dynRepScript = plugins.addLocalPrefix(repScript, usecase)
            if os.path.isfile(dynRepScript):
                os.environ["USECASE_REPLAY_SCRIPT"] = dynRepScript
            else:
                del os.environ["USECASE_REPLAY_SCRIPT"]
        process = self.startExternalProgram(commandLine, description, shellTitle, holdShell, exitHandler, exitHandlerArgs)
        if recScript:
            os.environ["USECASE_RECORD_SCRIPT"] = recScript
        if repScript:
            os.environ["USECASE_REPLAY_SCRIPT"] = repScript
        return process
    def describe(self, testObj, postText = ""):
        guilog.info(testObj.getIndent() + repr(self) + " " + repr(testObj) + postText)
    def perform(self):
        message = self.messageBeforePerform()
        if message != None:
            self.notify("Status", message)
        self.performOnCurrent()
        message = self.messageAfterPerform()
        if message != None:
            self.notify("Status", message)
    
class SelectionAction(InteractiveAction):
    def __init__(self, rootTestSuites):
        self.rootTestSuites = rootTestSuites
        self.apps = map(lambda suite: suite.app, self.rootTestSuites)
        self.currTestSelection = []
        InteractiveAction.__init__(self)
    def getConfigValue(self, entryName):
        prevValue = None
        for app in self.apps:
            currValue = app.getConfigValue(entryName)
            if not prevValue is None and currValue != prevValue:
                print "WARNING - GUI configuration differs between applications, ignoring that from", app
            else:
                prevValue = currValue
        return prevValue
    def addFilterFile(self, fileName):
        selectionGroups = interactiveActionHandler.optionGroupMap.get(SelectTests)
        if selectionGroups:
            filterFileOption = selectionGroups[0].options["f"]
            filterFileOption.addPossibleValue(os.path.basename(fileName))
    def notifyNewTestSelection(self, tests):
        self.currTestSelection = tests
    def describeTests(self):
        return str(len(self.currTestSelection)) + " tests"
    def getAnyApp(self):
        if len(self.currTestSelection) > 0:
            return self.currTestSelection[0].app
    def isSelected(self, test):
        return test in self.currTestSelection
    def isNotSelected(self, test):
        return not self.isSelected(test)
    def getCmdlineOption(self):
        selTestPaths = []
        for test in self.currTestSelection:
            relPath = test.getRelPath()
            if not relPath in selTestPaths:
                selTestPaths.append(relPath)
        return "-tp " + string.join(selTestPaths, ",")
    def getCmdlineOptionForApps(self):
        apps = []
        for test in self.currTestSelection:
            if not test.app.name in apps:
                apps.append(test.app.name)
        return "-a " + string.join(apps, ",")


# The class to inherit from if you want test-based actions that can run from the GUI
class InteractiveTestAction(InteractiveAction):
    def __init__(self, test):
        self.currentTest = test
        InteractiveAction.__init__(self)
    def describeTests(self):
        return repr(self.currentTest)
    def getConfigValue(self, entryName):
        return self.currentTest.getConfigValue(entryName)
    def getViewCommand(self, fileName):
        stem = os.path.basename(fileName).split(".")[0]
        viewProgram = self.currentTest.getCompositeConfigValue("view_program", stem)
        if not plugins.canExecute(viewProgram):
            raise plugins.TextTestError, "Cannot find file editing program '" + viewProgram + \
                  "'\nPlease install it somewhere on your PATH or point the view_program setting at a different tool"
        cmd = viewProgram + " \"" + fileName + "\"" + plugins.nullRedirect()
        if os.name == "posix":
            cmd = "exec " + cmd # best to avoid shell messages etc.
        return cmd, viewProgram
    def getRelativeFilename(self, filename):
        # Trim the absolute filename to be relative to the application home dir
        # (TEXTTEST_HOME is more difficult to obtain, see testmodel.OptionFinder.getDirectoryName)
        if self.currentTest.classId() == "test-app":
            return os.path.basename(filename)
        else:
            return os.path.join(self.currentTest.getRelPath(), os.path.basename(filename))
    def notifyViewTest(self, test):
        self.currentTest = test
    def viewFile(self, fileName, refreshContents=False, refreshFiles=False):
        exitHandler = None
        if refreshFiles:
            exitHandler = self.currentTest.filesChanged
        elif refreshContents:
            exitHandler = self.currentTest.contentChanged

        commandLine, descriptor = self.getViewCommand(fileName)
        description = descriptor + " " + self.getRelativeFilename(fileName)
        refresh = str(int(refreshContents or refreshFiles))
        guilog.info("Viewing file " + fileName.replace(os.sep, "/") + " using '" + descriptor + "', refresh set to " + str(refresh))
        process = self.startExternalProgram(commandLine, description=description, exitHandler=exitHandler)
        scriptEngine.monitorProcess("views and edits test files", process, [ fileName ])
    
# Plugin for saving tests (standard)
class SaveTests(SelectionAction):
    def __init__(self, rootTestSuites, oldOptionGroups):
        SelectionAction.__init__(self, rootTestSuites)
        self.addOption(oldOptionGroups, "v", "Version to save", self.getDefaultSaveOption(), self.getPossibleVersions())
        self.addSwitch(oldOptionGroups, "over", "Replace successfully compared files also", 0)
        self.currFileSelection = []
        if self.hasPerformance():
            self.addSwitch(oldOptionGroups, "ex", "Save: ", 1, ["Average performance", "Exact performance"])
    def isFrequentUse(self):
        return True
    def getStockId(self):
        return "save"
    def getTabTitle(self):
        return "Saving"
    def getInterfaceDescription(self):
        description = "<menubar>\n<menu action=\"actionmenu\">\n<menuitem action=\"" + self.getSecondaryTitle() + "\"/>\n</menu>\n</menubar>\n"
        description += "<toolbar>\n<toolitem action=\"" + self.getSecondaryTitle() + "\"/>\n</toolbar>\n"
        return description
    def getAccelerator(self):
        return "<control>s"
    def getTitle(self):
        return "_Save"
    def getSecondaryTitle(self):
        return "Save"
    def messageBeforePerform(self):
        return "Saving " + self.describeTests() + " ..."
    def messageAfterPerform(self):
        return "Saved " + self.describeTests() + " tests."
    def getDefaultSaveOption(self):
        saveVersions = self.getSaveVersions()
        if saveVersions.find(",") != -1:
            return "<default> - " + saveVersions
        else:
            return saveVersions
    def getPossibleVersions(self):
        extensions = []
        for app in self.apps:
            for ext in app.getSaveableVersions():
                if not ext in extensions:
                    extensions.append(ext)
        # Include the default version always
        extensions.append("")
        return extensions
    def getSaveVersions(self):
        saveVersions = []
        for app in self.apps:
            ver = self.getDefaultSaveVersion(app)
            if not ver in saveVersions:
                saveVersions.append(ver)
        return string.join(saveVersions, ",")
    def getDefaultSaveVersion(self, app):
        return app.getFullVersion(forSave = 1)
    def hasPerformance(self):
        for app in self.apps:
            if app.hasPerformance():
                return True
        return False
    def getExactness(self):
        return int(self.optionGroup.getSwitchValue("ex", 1))
    def getVersion(self, test):
        versionString = self.optionGroup.getOptionValue("v")
        if versionString.startswith("<default>"):
            return self.getDefaultSaveVersion(test.app)
        else:
            return versionString
    def notifyNewFileSelection(self, files):
        self.currFileSelection = files
    def performOnCurrent(self):
        saveDesc = ", exactness " + str(self.getExactness())
        if len(self.currFileSelection) > 0:
            saveDesc += ", only " + string.join(self.currFileSelection, ",")
        overwriteSuccess = self.optionGroup.getSwitchValue("over")
        if overwriteSuccess:
            saveDesc += ", overwriting both failed and succeeded files"

        for test in self.currTestSelection:
            if not test.state.isSaveable():
                continue
            version = self.getVersion(test)
            fullDesc = " - version " + version + saveDesc
            self.describe(test, fullDesc)
            testComparison = test.state
            if testComparison:
                if len(self.currFileSelection) > 0:
                    testComparison.savePartial(self.currFileSelection, test, self.getExactness(), version)
                else:
                    testComparison.save(test, self.getExactness(), version, overwriteSuccess)
                newState = testComparison.makeNewState(test.app)
                test.changeState(newState)
          
# Plugin for viewing files (non-standard). In truth, the GUI knows a fair bit about this action,
# because it's special and plugged into the tree view. Don't use this as a generic example!
class ViewFile(InteractiveTestAction):
    def __init__(self, dynamic, test, oldOptionGroups):
        InteractiveTestAction.__init__(self, test)
        if dynamic and test.classId() == "test-case":
            self.addSwitch(oldOptionGroups, "rdt", "Include Run-dependent Text", 0)
            self.addSwitch(oldOptionGroups, "nf", "Show differences where present", 1)
            if not test.state.isComplete():
                self.addSwitch(oldOptionGroups, "f", "Follow file rather than view it", 1)
    def getTabTitle(self):
        return "Viewing"
    def canPerform(self):
        return False # activate when a file is viewed, not via the performOnCurrent method
    def hasButton(self):
        return False
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
        followProgram = self.currentTest.app.getConfigValue("follow_program")
        if not plugins.canExecute(followProgram):
            raise plugins.TextTestError, "Cannot find file-following program '" + followProgram + \
                  "'\nPlease install it somewhere on your PATH or point the follow_program setting at a different tool"
        guilog.info("Following file " + fileName + " using '" + followProgram + "'")
        description = followProgram + " " + self.getRelativeFilename(fileName)
        baseName = os.path.basename(fileName)
        title = self.currentTest.name + " (" + baseName + ")"
        process = self.startExternalProgram(followProgram + " " + fileName, description=description, shellTitle=title)
        scriptEngine.monitorProcess("follows progress of test files", process)
    def notifyViewFile(self, comparison, fileName):
        if self.optionGroup.getSwitchValue("f"):
            return self.followFile(comparison.tmpFile)
        if not comparison:
            baseName = os.path.basename(fileName)
            refreshContents = baseName.startswith("testsuite.") # re-read which tests we have
            refreshFiles = baseName.startswith("options.") # options file can change appearance of test (environment refs etc.)
            return self.viewFile(fileName, refreshContents, refreshFiles)
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
        diffProgram = self.currentTest.app.getConfigValue("diff_program")
        if not plugins.canExecute(diffProgram):
            raise plugins.TextTestError, "Cannot find graphical difference program '" + diffProgram + \
                  "'\nPlease install it somewhere on your PATH or point the diff_program setting at a different tool"
        stdFile = self.stdFile(comparison)
        tmpFile = self.tmpFile(comparison)
        description = diffProgram + " " + stdFile + "\n                                   " + tmpFile
        guilog.info("Comparing file " + os.path.basename(tmpFile) + " with previous version using '" + diffProgram + "'")
        process = self.startExternalProgram(diffProgram + " '" + stdFile + "' '" + tmpFile + "' " + plugins.nullRedirect(), description=description)
        scriptEngine.monitorProcess("shows graphical differences in test files", process)

# And a generic import test. Note acts on test suites
class ImportTest(InteractiveTestAction):
    def __init__(self, suite, oldOptionGroups):
        InteractiveTestAction.__init__(self, suite)
        self.optionGroup.addOption("name", self.getNameTitle(), self.getDefaultName(suite))
        self.optionGroup.addOption("desc", self.getDescTitle(), self.getDefaultDesc(suite))
    def getNameTitle(self):
        return self.testType() + " Name"
    def getDescTitle(self):
        return self.testType() + " Description"
    def notifyViewTest(self, test):
        InteractiveTestAction.notifyViewTest(self, test)
        if test.classId() == "test-suite":
            self.optionGroup.setOptionValue("name", self.getDefaultName(test))
            self.optionGroup.setOptionValue("desc", self.getDefaultDesc(test))
    def getDefaultName(self, suite):
        return ""
    def getDefaultDesc(self, suite):
        return ""
    def getTabTitle(self):
        return "Adding " + self.testType()
    def getTitle(self):
        return "Add " + self.testType()
    def testType(self):
        return ""
    def getNewTestName(self):
        # Overwritten in subclasses - occasionally it can be inferred
        return self.optionGroup.getOptionValue("name").strip()
    def performOnCurrent(self):
        testName = self.getNewTestName()
        if len(testName) == 0:
            raise plugins.TextTestError, "No name given for new " + self.testType() + "!" + "\n" + \
                  "Fill in the 'Adding " + self.testType() + "' tab below."
        if testName.find(" ") != -1:
            raise plugins.TextTestError, "The new " + self.testType() + " name is not permitted to contain spaces, please specify another"
        suite = self.currentTest
        for test in suite.testCaseList():
            if test.name == testName:
                raise plugins.TextTestError, "A " + self.testType() + " with the name '" + testName + "' already exists, please choose another name"
        guilog.info("Adding " + self.testType() + " " + testName + " under test suite " + repr(suite))
        testDir = suite.writeNewTest(testName, self.optionGroup.getOptionValue("desc"))
        self.createTestContents(suite, testDir)
    def createTestContents(self, suite, testDir):
        pass

class RecordTest(InteractiveTestAction):
    def __init__(self, test, oldOptionGroups):
        InteractiveTestAction.__init__(self, test)
        self.recordMode = self.currentTest.getConfigValue("use_case_record_mode")
        self.recordTime = None
        if self.isActive():
            self.addOption(oldOptionGroups, "v", "Version to record", test.app.getFullVersion(forSave=1))
            self.addOption(oldOptionGroups, "c", "Checkout to use for recording", test.app.checkout) 
            self.addSwitch(oldOptionGroups, "rep", "Automatically replay test after recording it", 1)
            self.addSwitch(oldOptionGroups, "repgui", "", defaultValue = 0, options = ["Auto-replay invisible", "Auto-replay in dynamic GUI"])
        if self.recordMode == "console":
            self.addSwitch(oldOptionGroups, "hold", "Hold record shell after recording")
    def getTabTitle(self):
        return "Recording"
    def performOnCurrent(self):
        guilog.info("Starting dynamic GUI in record mode...")
        self.updateRecordTime(self.currentTest)
        self.startTextTestProcess(self.currentTest, "record")
    def updateRecordTime(self, test):
        if self.updateRecordTimeForFile(test, "usecase", "USECASE_RECORD_SCRIPT", "target_record"):
            return True
        if self.recordMode == "console" and self.updateRecordTimeForFile(test, "input", "USECASE_RECORD_STDIN", "target"):
            return True
        return False
    def updateRecordTimeForFile(self, test, stem, envVar, prefix):
        file = test.getFileName(stem, self.optionGroup.getOptionValue("v"))
        if not file:
            return False
        newTime = plugins.modifiedTime(file)
        if newTime != self.recordTime:
            self.recordTime = newTime
            if os.environ.has_key(envVar):
                # If we have an "outer" record going on, provide the result as a target recording...
                target = plugins.addLocalPrefix(os.getenv(envVar), prefix)
                shutil.copyfile(file, target)
            return True
        return False
    def startTextTestProcess(self, test, usecase):
        ttOptions = self.getRunOptions(test, usecase)
        guilog.info("Starting " + usecase + " run of TextTest with arguments " + ttOptions)
        commandLine = plugins.textTestName + " " + ttOptions
        writeDir = self.getWriteDir(test)
        plugins.ensureDirectoryExists(writeDir)
        logFile = self.getLogFile(writeDir, usecase, "output")
        errFile = self.getLogFile(writeDir, usecase)
        commandLine +=  " < " + plugins.nullFileName() + " > " + logFile + " 2> " + errFile
        process = self.startExtProgramNewUsecase(commandLine, usecase, \
                                                 exitHandler=self.textTestCompleted, exitHandlerArgs=(test,usecase))
    def getLogFile(self, writeDir, usecase, type="errors"):
        return os.path.join(writeDir, usecase + "_" + type + ".log")
    def isActive(self):
        return self.recordMode != "disabled"
    def textTestCompleted(self, test, usecase):
        scriptEngine.applicationEvent(usecase + " texttest to complete")
        # Refresh the files before changed the data
        test.refreshFiles()
        if usecase == "record":
            self.setTestRecorded(test, usecase)
        else:
            self.setTestReady(test, usecase)
        test.filesChanged()
    def getWriteDir(self, test):
        return os.path.join(test.app.writeDirectory, "record")
    def setTestRecorded(self, test, usecase):
        writeDir = self.getWriteDir(test)
        errFile = self.getLogFile(writeDir, usecase)
        if os.path.isfile(errFile):
            errText = open(errFile).read()
            if len(errText):
                raise plugins.TextTestError, "Recording use-case failed, with the following errors:\n" + errText
 
        if self.updateRecordTime(test) and self.optionGroup.getSwitchValue("rep"):
            self.startTextTestProcess(test, usecase="replay")
            test.state.freeText = "Recorded use case - now attempting to replay in the background to collect standard files" + \
                                  "\n" + "These will appear shortly. You do not need to submit the test manually."
        else:
            self.setTestReady(test)
    def setTestReady(self, test, usecase=""):
        test.state.freeText = "Recorded use case and collected all standard files"
    def getRunOptions(self, test, usecase):
        version = self.optionGroup.getOptionValue("v")
        checkout = self.optionGroup.getOptionValue("c")
        basicOptions = self.getRunModeOption(usecase) + " -tp " + test.getRelPath() + \
                       " " + test.app.getRunOptions(version, checkout)
        if usecase == "record":
            basicOptions += " -record"
            if self.optionGroup.getSwitchValue("hold"):
                basicOptions += " -holdshell"
        return basicOptions
    def getRunModeOption(self, usecase):
        if usecase == "record" or self.optionGroup.getSwitchValue("repgui"):
            return "-g"
        else:
            return "-o"
    def getTitle(self):
        return "Record _Use-Case"
    
class ImportTestCase(ImportTest):
    def __init__(self, suite, oldOptionGroups):
        ImportTest.__init__(self, suite, oldOptionGroups)
        self.addDefinitionFileOption(suite, oldOptionGroups)
    def testType(self):
        return "Test"
    def addDefinitionFileOption(self, suite, oldOptionGroups):
        self.addOption(oldOptionGroups, "opt", "Command line options")
    def createTestContents(self, suite, testDir):
        self.writeDefinitionFiles(suite, testDir)
        self.writeEnvironmentFile(suite, testDir)
        self.writeResultsFiles(suite, testDir)
        suite.addTestCase(os.path.basename(testDir))
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
        if len(optionString):
            guilog.info("Using option string : " + optionString)
            optionFile = self.getWriteFile("options", suite, testDir)
            optionFile.write(optionString + "\n")
        else:
            guilog.info("Not creating options file")
        return optionString
    def getOptions(self, suite):
        return self.optionGroup.getOptionValue("opt")
    def getEnvironment(self, suite):
        return {}
    def writeResultsFiles(self, suite, testDir):
        # Cannot do anything in general
        pass

class ImportTestSuite(ImportTest):
    def __init__(self, suite, oldOptionGroups):
        ImportTest.__init__(self, suite, oldOptionGroups)
        self.addEnvironmentFileOptions(oldOptionGroups)
    def testType(self):
        return "Suite"
    def createTestContents(self, suite, testDir):
        self.writeEnvironmentFiles(suite, testDir)
        suite.addTestSuite(os.path.basename(testDir))
    def addEnvironmentFileOptions(self, oldOptionGroups):
        self.addSwitch(oldOptionGroups, "env", "Add environment file")
    def writeEnvironmentFiles(self, suite, testDir):
        if self.optionGroup.getSwitchValue("env"):
            envFile = os.path.join(testDir, "environment")
            file = open(envFile, "w")
            file.write("# Dictionary of environment to variables to set in test suite" + "\n")

class SelectTests(SelectionAction):
    def __init__(self, rootSuites, oldOptionGroups):
        SelectionAction.__init__(self, rootSuites)
        self.diag = plugins.getDiagnostics("Select Tests")
        self.addOption(oldOptionGroups, "vs", "Tests for version", "", self.getPossibleVersions())
        self.addSwitch(oldOptionGroups, "select_in_collapsed_suites", "Select in collapsed suites", 0)
        self.addSwitch(oldOptionGroups, "current_selection", "Current selection:", options = [ "Discard", "Refine", "Extend", "Exclude"])
        
        self.appSelectGroup = self.findSelectGroup()
        self.optionGroup.options += self.appSelectGroup.options
        self.optionGroup.switches += self.appSelectGroup.switches
    def getPossibleVersions(self):
        versions = []
        for app in self.apps:
            appVer = app.getFullVersion()
            if len(appVer) == 0:
                appVer = "<default>"
            if not appVer in versions:
                versions.append(appVer)
        return versions
    def findSelectGroup(self):
        for group in self.apps[0].optionGroups:
            if group.name.startswith("Select"):
                return group
    def getInterfaceDescription(self):
        description = "<menubar>\n<menu action=\"actionmenu\">\n<menuitem action=\"" + self.getSecondaryTitle() + "\"/>\n</menu>\n</menubar>\n"
        description += "<toolbar>\n<toolitem action=\"" + self.getSecondaryTitle() + "\"/>\n</toolbar>\n"
        return description
    def getAccelerator(self):
        return "<control>s"
    def getStockId(self):
        return "refresh"
    def getTitle(self):
        return "_Select"
    def getSecondaryTitle(self):
        return "Select"
    def _getScriptTitle(self):
        return "Select indicated tests"
    def getTabTitle(self):
        return "Select Tests"
    def getGroupTabTitle(self):
        return "Selection"
    def messageBeforePerform(self):
        return "Selecting tests ..."
    def messageAfterPerform(self):
        return None    
    # No messageAfterPerform necessary - we update the status bar when the selection changes inside TextTestGUI
    def isFrequentUse(self):
        return True
    def getFilterList(self, app):
        app.configObject.updateOptions(self.appSelectGroup)
        return app.configObject.getFilterList(app)
    def performOnCurrent(self):
        # Get strategy. 0 = discard, 1 = refine, 2 = extend, 3 = exclude
        strategy = self.optionGroup.getSwitchValue("current_selection")
        selectedTests = []                
        for suite in self.getSuitesToTry():
            filters = self.getFilterList(suite.app)
            for filter in filters:
                if not filter.acceptsApplication(suite.app):
                    continue
                
            reqTests = self.getRequestedTests(suite, filters)
            newTests = self.combineWithPrevious(reqTests, strategy)
            guilog.info("Selected " + str(len(newTests)) + " out of a possible " + str(suite.size()))
            selectedTests += newTests
        self.notify("NewTestSelection", selectedTests, self.optionGroup.getSwitchValue("select_in_collapsed_suites"))
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
        if not suite.isAcceptedByAll(filters):
            return []
        if suite.classId() == "test-suite":
            tests = []
            for subSuite in self.findTestCaseList(suite):
                tests += self.getRequestedTests(subSuite, filters)
            return tests
        else:
            return [ suite ]
    def combineWithPrevious(self, reqTests, strategy):
        # Strategies: 0 - discard, 1 - refine, 2 - extend, 3 - exclude
        # If we want to extend selection, we include test if it was previsouly selected,
        # even if it doesn't fit the current criterion
        if strategy == 0:
            return reqTests
        elif strategy == 1:
            return filter(self.isSelected, reqTests)
        elif strategy == 2:
            return reqTests + self.currTestSelection
        elif strategy == 3:
            return filter(self.isNotSelected, reqTests)
    def findTestCaseList(self, suite):
        testcases = suite.testcases
        version = self.optionGroup.getOptionValue("vs")
        if len(version) == 0:
            return testcases

        if version == "<default>":
            version = ""
        fullVersion = suite.app.getFullVersion()
        self.diag.info("Trying to get test cases for version " + fullVersion)
        if len(fullVersion) > 0 and len(version) > 0:
            parts = version.split(".")
            for appVer in suite.app.versions:
                if not appVer in parts:
                    version += "." + appVer

        self.diag.info("Finding test case list for " + repr(suite) + ", version " + version)
        versionFile = suite.getFileName("testsuite", version)        
        self.diag.info("Reading test cases from " + versionFile)
        newTestNames = plugins.readList(versionFile)
        newTestList = []
        for testCase in testcases:
            if testCase.name in newTestNames:
                newTestList.append(testCase)
        return newTestList

class ResetGroups(SelectionAction):
    def __init__(self, rootSuites, oldOptionGroups):
        SelectionAction.__init__(self, rootSuites)
    def getStockId(self):
        return "revert-to-saved"
    def getInterfaceDescription(self):
        description = "<menubar>\n<menu action=\"actionmenu\">\n<menuitem action=\"" + self.getSecondaryTitle() + "\"/>\n</menu>\n</menubar>\n"
        description += "<toolbar>\n<toolitem action=\"" + self.getSecondaryTitle() + "\"/>\n<separator/></toolbar>\n"
        return description
    def getAccelerator(self):
        return '<control>e'
    def getTitle(self):
        return "R_eset"
    def messageBeforePerform(self):
        return "Resetting options ..."
    def messageAfterPerform(self):
        return "All options reset to default values."
    def getScriptTitle(self, tab):
        return "Reset running options"
    def performOnCurrent(self):
        for optionGroups in interactiveActionHandler.optionGroupMap.values():
            for group in optionGroups:
                group.reset()

class SaveSelection(SelectionAction):
    def __init__(self, dynamic, rootSuites, oldOptionGroups):
        self.dynamic = dynamic
        SelectionAction.__init__(self, rootSuites)
        self.addOption(oldOptionGroups, "name", "Name to give selection")
        if not dynamic:
            self.addSwitch(oldOptionGroups, "tests", "Store actual tests selected", 1)
            for group in self.apps[0].optionGroups:
                if group.name.startswith("Select"):
                    self.selectionGroup = group
    def getTitle(self):
        return "S_ave Selection"
    def getScriptTitle(self, tab):
        return "Save selection"
    def getTabTitle(self):
        if self.dynamic:
            return "Save Selection"
        else:
            return "Saving"
    def getGroupTabTitle(self):
        if self.dynamic:
            return "Test" # 'Test' gives us no group tab ...
        else:
            return "Selection"
    def getFileName(self):
        localName = self.optionGroup.getOptionValue("name")
        if not localName:
            raise plugins.TextTestError, "Please provide a file name to save the selection to."
        if len(self.currTestSelection) == 0:
            raise plugins.TextTestError, "No tests are selected, cannot save the selection."

        app = self.getAnyApp()
        return app.configObject.getFilterFilePath(app, localName, True)
    def saveActualTests(self):
        return self.dynamic or self.optionGroup.getSwitchValue("tests")
    def getTextToSave(self):
        actualTests = self.saveActualTests()
        if actualTests:
            return self.getCmdlineOption()
        else:
            commandLines = self.selectionGroup.getCommandLines()
            return string.join(commandLines)
    def performOnCurrent(self):
        fileName = self.getFileName()
        toWrite = self.getTextToSave()
        file = open(fileName, "w")
        file.write(toWrite + "\n")
        file.close()
        self.addFilterFile(fileName)
    def messageAfterPerform(self):
        return "Saved " + self.describeTests() + " in file '" + self.getFileName() + "'."
                  
class RunTests(SelectionAction):
    runNumber = 1
    def __init__(self, rootSuites, oldOptionGroups):
        SelectionAction.__init__(self, rootSuites)
        self.optionGroups = []
        for group in self.apps[0].optionGroups:
            if group.name.startswith("Invisible"):
                self.invisibleGroup = group
            elif not group.name.startswith("Select"):
                self.optionGroups.append(group)
    def getOptionGroups(self):
        return self.optionGroups
    def getTitle(self):
        return "_Run Tests"
    def getStockId(self):
        return "execute"
    def getInterfaceDescription(self):
        description = "<menubar>\n<menu action=\"actionmenu\">\n<menuitem action=\"" + self.getSecondaryTitle() + "\"/>\n</menu>\n</menubar>\n"
        description += "<toolbar>\n<toolitem action=\"" + self.getSecondaryTitle() + "\"/>\n</toolbar>\n"
        return description
    def getAccelerator(self):
        return "<control>r"
    def getScriptTitle(self, tab):
        return "Run selected tests"
    def getGroupTabTitle(self):
        return "Running"
    def messageBeforePerform(self):
        return "Starting tests at " + plugins.localtime() + " ..."
    def messageAfterPerform(self):
        return "Started " + self.describeTests() + " at " + plugins.localtime() + "."
    def isFrequentUse(self):
        return True
    def performOnCurrent(self):
        if len(self.currTestSelection) == 0:
            raise plugins.TextTestError, "No tests selected - cannot run!"
        writeDir = os.path.join(self.apps[0].writeDirectory, "dynamic_run" + str(self.runNumber))
        plugins.ensureDirectoryExists(writeDir)
        filterFile = self.writeFilterFile(writeDir)
        ttOptions = self.getTextTestOptions(filterFile)
        logFile = os.path.join(writeDir, "output.log")
        errFile = os.path.join(writeDir, "errors.log")
        self.runNumber += 1
        description = "Dynamic GUI started at " + plugins.localtime()
        commandLine = plugins.textTestName + " " + ttOptions + " < " + plugins.nullFileName() + " > " + logFile + " 2> " + errFile
        self.startExtProgramNewUsecase(commandLine, usecase="dynamic", exitHandler=self.checkTestRun, exitHandlerArgs=(errFile,self.currTestSelection), description = description)
    def writeFilterFile(self, writeDir):
        # Because the description of the selection can be extremely long, we write it in a file and refer to it
        # This avoids too-long command lines which are a problem at least on Windows XP
        filterFileName = os.path.join(writeDir, "gui_select")
        writeFile = open(filterFileName, "w")
        writeFile.write(self.getCmdlineOption() + "\n")
        writeFile.close()
        return filterFileName
    def getTextTestOptions(self, filterFile):
        ttOptions = [ self.getCmdlineOptionForApps() ]
        ttOptions += self.invisibleGroup.getCommandLines()
        for group in self.optionGroups:
            ttOptions += group.getCommandLines()
        filterDir, filterFileName = os.path.split(filterFile)
        ttOptions.append("-f " + filterFileName)
        ttOptions.append("-fd " + filterDir)
        return string.join(ttOptions)
    def checkTestRun(self, errFile, testSel):
        for test in testSel:
            test.filesChanged()
        scriptEngine.applicationEvent("dynamic GUI to be closed")
        if os.path.isfile(errFile):
            errText = open(errFile).read()
            if len(errText):
                raise plugins.TextTestError, "Dynamic run failed, with the following errors:\n" + errText

        writeDir, local = os.path.split(errFile)
        prelist = [ "output.log", "errors.log", "gui_select" ]
        for fileName in os.listdir(writeDir):
            if not fileName in prelist:
                self.addFilterFile(fileName)

class EnableDiagnostics(InteractiveTestAction):
    def __init__(self, test, oldOptionGroups):
        InteractiveTestAction.__init__(self, test)
        configDir = test.getConfigValue("diagnostics")
        self.configFile = None
        if configDir.has_key("configuration_file"):
            self.configFile = configDir["configuration_file"]
    def getTitle(self):
        return "New _Diagnostics"
    def getScriptTitle(self, tab):
        return "Enable diagnostics"
    def isActive(self):
        return self.configFile
    def performOnCurrent(self):
        diagDir = self.currentTest.makeSubDirectory("Diagnostics")
        diagFile = os.path.join(self.currentTest.app.getDirectory(), self.configFile)
        targetDiagFile = os.path.join(diagDir, self.configFile)
        shutil.copyfile(diagFile, targetDiagFile)
        self.viewFile(targetDiagFile, refreshFiles=True)

class RemoveTest(InteractiveTestAction):
    def __init__(self, test, oldOptionGroups):
        InteractiveTestAction.__init__(self, test)
    def getTitle(self):
        return "Remove"
    def getScriptTitle(self, tab):
        return "Remove Test"
    def getDoubleCheckMessage(self):
        if self.currentTest.classId() == "test-case":
            return "You are about to remove the test '" + self.currentTest.name + \
                   "' and all associated files.\nAre you sure you wish to proceed?"
        else:
            return "You are about to remove the entire test suite '" + self.currentTest.name + \
                   "' and all " + str(self.currentTest.size()) + " tests that it contains!\nAre you VERY sure you wish to proceed??"
    def performOnCurrent(self):
        plugins.rmtree(self.currentTest.getDirectory())
        suite = self.currentTest.parent
        self.removeFromTestFile(suite, self.currentTest.name)
        suite.removeTest(self.currentTest)
    def removeFromTestFile(self, suite, testName):
        newFileName = os.path.join(suite.app.writeDirectory, "tmptestsuite")
        newFile = plugins.openForWrite(newFileName)
        description = ""
        contentFileName = suite.getContentFileName()
        for line in open(contentFileName).xreadlines():
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
            diffInfo = os.popen(difftool + " " + contentFileName + " " + newFileName).read()
            guilog.info("Changes made to testcase file : \n" + diffInfo)
            guilog.info("") # blank line
        plugins.movefile(newFileName, contentFileName)

class CopyTest(ImportTest):
    def __init__(self, test, oldOptionGroups):
        ImportTest.__init__(self, test, oldOptionGroups)
        self.currentTest = test.parent
        self.testToCopy = test
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
    def getScriptTitle(self, tab):
        return "Copy test"
    def notifyViewTest(self, test):
        # apply to parent of where we're viewing!
        self.currentTest = test.parent
    def createTestContents(self, suite, testDir):
        stdFiles, defFiles = self.testToCopy.listStandardFiles(allVersions=True)
        for sourceFile in stdFiles + defFiles:
            dirname, local = os.path.split(sourceFile)
            if dirname == self.testToCopy.getDirectory():
                targetFile = os.path.join(testDir, local)
                shutil.copyfile(sourceFile, targetFile)
        dataFiles = self.testToCopy.listDataFiles()
        for sourcePath in dataFiles:
            if os.path.isdir(sourcePath):
                continue
            targetPath = sourcePath.replace(self.testToCopy.getDirectory(), testDir)
            plugins.ensureDirExistsForFile(targetPath)
            shutil.copyfile(sourcePath, targetPath)
        suite.addTestCase(os.path.basename(testDir))

class ReportBugs(InteractiveTestAction):
    def __init__(self, test, oldOptionGroups):
        InteractiveTestAction.__init__(self, test)
        self.addOption(oldOptionGroups, "search_string", "Text or regexp to match")
        self.addOption(oldOptionGroups, "search_file", "File to search in", test.app.getConfigValue("log_file"),
                       self.getPossibleFileStems())
        self.addOption(oldOptionGroups, "version", "Version to report for", test.app.getFullVersion())
        self.addOption(oldOptionGroups, "execution_hosts", "Trigger only when run on machine(s)")
        self.addOption(oldOptionGroups, "bug_system", "Extract info from bug system", "<none>", [ "bugzilla" ])
        self.addOption(oldOptionGroups, "bug_id", "Bug ID (only if bug system given)")
        self.addOption(oldOptionGroups, "full_description", "Full description (no bug system)")
        self.addOption(oldOptionGroups, "brief_description", "Few-word summary (no bug system)")
        self.addSwitch(oldOptionGroups, "trigger_on_absence", "Trigger if given text is NOT present")
        self.addSwitch(oldOptionGroups, "internal_error", "Trigger even if other files differ (report as internal error)")
        self.addSwitch(oldOptionGroups, "trigger_on_success", "Trigger even if test would otherwise succeed")
    def getTitle(self):
        return "Report"
    def getScriptTitle(self, tab):
        return "report described bugs"
    def getTabTitle(self):
        return "Bugs"
    def getPossibleFileStems(self):
        stems = []
        for test in self.currentTest.testCaseList():
            resultFiles, defFiles = test.listStandardFiles(allVersions=False)
            for fileName in resultFiles:
                stem = os.path.basename(fileName).split(".")[0]
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
        name = "knownbugs." + self.currentTest.app.name + self.versionSuffix()
        return os.path.join(self.currentTest.getDirectory(), name)
    def write(self, writeFile, message):
        writeFile.write(message)
        guilog.info(message)
    def performOnCurrent(self):
        self.checkSanity()
        fileName = self.getFileName()
        guilog.info("Recording known bugs to " + fileName + " : ")
        writeFile = open(fileName, "a")
        self.write(writeFile, "\n[Reported by " + os.getenv("USER", "Windows") + " at " + plugins.localtime() + "]\n")
        for name, option in self.optionGroup.options.items():
            value = option.getValue()
            if name != "version" and len(value) != 0 and value != "<none>":
                self.write(writeFile, name + ":" + value + "\n")
        for name, switch in self.optionGroup.switches.items():
            if switch.getValue():
                self.write(writeFile, name + ":1\n")
        writeFile.close()
        self.currentTest.filesChanged()
    
# Placeholder for all classes. Remember to add them!
class InteractiveActionHandler:
    def __init__(self):
        self.appClasses = [ ViewFile ]
        self.appDynamicClasses = []
        self.appStaticClasses = []
        self.testClasses = [ ViewFile ]
        self.testDynamicClasses =  []
        self.testStaticClasses =  [ RecordTest, EnableDiagnostics, CopyTest, RemoveTest, ReportBugs ]
        self.suiteClasses = [ ViewFile ]
        self.suiteDynamicClasses = []
        self.suiteStaticClasses = [ ImportTestCase, ImportTestSuite, RemoveTest, ReportBugs ]
        self.selectionClasses = [ SaveSelection ]
        self.selectionDynamicClasses = [ SaveTests ]
        self.selectionStaticClasses = [ SelectTests, RunTests, ResetGroups ]
        self.optionGroupMap = {}
        self.diag = plugins.getDiagnostics("Interactive Actions")
    def storeOptionGroup(self, className, instance):
        self.optionGroupMap[className] = instance.getOptionGroups()
    def getMode(self, dynamic):
        if dynamic:
            return "Dynamic"
        else:
            return "Static"
    def getInstances(self, dynamic, actionType, *args):
        instances = []
        mode = self.getMode(dynamic)
        for intvActionClass in eval("self." + actionType + mode + "Classes"):
            instance = self.makeInstance(intvActionClass, *args)
            if instance:
                instances.append(instance)
        for intvActionClass in eval("self." + actionType + "Classes"):
            instance = self.makeInstance(intvActionClass, dynamic, *args)
            if instance:
                instances.append(instance)
        return instances
    def makeInstance(self, intvActionClass, *args):
        instance = self.makeInstanceObject(intvActionClass, *args)
        if instance.isActive():
            self.storeOptionGroup(intvActionClass, instance)
            return instance
    def makeInstanceObject(self, intvActionClass, *args):
        oldOptionGroups = self.optionGroupMap.get(intvActionClass, [])
        args += (oldOptionGroups,)
        self.diag.info("Trying to create action for " + intvActionClass.__name__)
        basicInstance = intvActionClass(*args)
        module = basicInstance.getConfigValue("interactive_action_module")
        command = "from " + module + " import " + intvActionClass.__name__ + " as realClassName"
        try:
            exec command
            self.diag.info("Used derived version from module " + module)
            return realClassName(*args)
        except ImportError:
            self.diag.info("Used basic version")
            return basicInstance
        except:
            # If some invalid interactive action is provided, need to know which
            print "Error with interactive action", intvActionClass.__name__
            raise sys.exc_type, sys.exc_value
        
interactiveActionHandler = InteractiveActionHandler()
guilog = None

def setUpGuiLog(dynamic):
    global guilog
    if dynamic:
        guilog = plugins.getDiagnostics("dynamic GUI behaviour")
    else:
        guilog = plugins.getDiagnostics("static GUI behaviour")
