#!/usr/local/bin/python

helpDescription = """
The default configuration is the simplest and most portable. It is intended to run on
any architecture. Therefore, differences in results are displayed using Python's ndiff
module, the most portable differencing tool I can find, anyway.

Its default behaviour is to run all tests on the local machine.
"""

helpOptions = """
-o         - run in overwrite mode. This means that the interactive dialogue is replaced by simply
             overwriting all previous results with new ones.

-n         - run in new-file mode. Tests that succeed will still overwrite the standard file, rather than
             leaving it, as is the deafult behaviour.

-reconnect <user>
            - Reconnect to already run tests, optionally takes a user from which to
              fetch temporary files. If not provided, will look for calling user.

-reconnfull - Only has an effect with reconnect. Essentially, recompute all filtering rather than trusting the run
              you are reconnecting to.

-keeptmp   - Keep any temporary directories where test(s) write files. Note that once you run the test again the old
             temporary dirs will be removed.       

-t <text>   - only run tests whose names contain <text> as a substring. Note that <text> may be a comma-separated
              list

-ts <text>  - only run test suites whose full relative paths contain <text> as a substring. As above this may be
              a comma-separated list.

-f <file>   - only run tests whose names appear in the file <file>
-grep <tx>  - only run tests whose log file (according to the config file entry "log_file") contains <tx>. Note that
              this can also be a comma-separated list
"""

helpScripts = """
default.CountTest          - produce a brief report on the number of tests in the chosen selection, by application

default.ExtractMemory      - update the memory files from the standard log files
"""

import os, shutil, plugins, respond, performance, comparetest, string, predict, sys, bugzilla
from glob import glob
from cPickle import Unpickler

def getConfig(optionMap):
    return Config(optionMap)

class Config(plugins.Configuration):
    def addToOptionGroups(self, app, groups):
        for group in groups:
            if group.name.startswith("Select"):
                group.addOption("t", "Test names containing")
                group.addOption("f", "Tests listed in file")
                group.addOption("ts", "Suite names containing")
                group.addOption("grep", "Log files containing")
            elif group.name.startswith("What"):
                group.addOption("reconnect", "Reconnect to previous run")
                group.addSwitch("reconnfull", "Recompute file filters when reconnecting")
            elif group.name.startswith("How"):
                group.addSwitch("noperf", "Disable any performance testing")
            elif group.name.startswith("Invisible"):
                # Only relevant without the GUI
                group.addSwitch("o", "Overwrite all failures")
                group.addOption("tp", "Tests with exact path") # use for internal communication
                group.addSwitch("n", "Create new results files (overwrite everything)")
            elif group.name.startswith("Side"):
                group.addSwitch("keeptmp", "Keep temporary write-directories")
    def getActionSequence(self):
        return self._getActionSequence(makeDirs=1)
    def _getActionSequence(self, makeDirs):
        actions = [ self.getWriteDirectoryPreparer(), self.tryGetTestRunner(), self.getTestEvaluator() ]
        if makeDirs:
            actions = [ self.getWriteDirectoryMaker() ] + actions
        return actions
    def getFilterList(self):
        filters = []
        self.addFilter(filters, "t", TestNameFilter)
        self.addFilter(filters, "tp", TestPathFilter)
        self.addFilter(filters, "ts", TestSuiteFilter)
        self.addFilter(filters, "f", FileFilter)
        self.addFilter(filters, "grep", GrepFilter)
        return filters
    def getCleanMode(self):
        if self.isReconnectingFast():
            return self.CLEAN_NONE
        if self.optionMap.has_key("keeptmp"):
            if self.optionMap.slaveRun():
                return self.CLEAN_NONE
            else:
                return self.CLEAN_PREVIOUS
        
        if self.optionMap.slaveRun():
            return self.CLEAN_NONBASIC # only clean extra directories that we create...
        
        return self.CLEAN_NONBASIC | self.CLEAN_BASIC
    def isReconnecting(self):
        return self.optionMap.has_key("reconnect")
    def getWriteDirectoryMaker(self):
        if self.isReconnectingFast():
            return None
        else:
            return self._getWriteDirectoryMaker()
    def getWriteDirectoryPreparer(self):
        if self.isReconnectingFast():
            return None
        else:
            return PrepareWriteDirectory()
    def _getWriteDirectoryMaker(self):
        return MakeWriteDirectory()
    def tryGetTestRunner(self):
        if self.isReconnecting():
            return None
        else:
            return self.getTestRunner()
    def getTestRunner(self):
        return RunTest()
    def isReconnectingFast(self):
        return self.isReconnecting() and not self.optionMap.has_key("reconnfull")
    def getTestEvaluator(self):
        actions = [ self.getFileExtractor() ]
        if not self.isReconnectingFast():
            actions += [ self.getCatalogueCreator(), self.getTestPredictionChecker(), \
                         self.getTestComparator(), self.getFailureExplainer(), SaveState() ]
        if not self.optionMap.useGUI() and not self.optionMap.slaveRun():
            actions.append(self.getTestResponder())
        return actions
    def getFileExtractor(self):
        if self.isReconnecting():
            return ReconnectTest(self.optionValue("reconnect"), self.optionMap.has_key("reconnfull"))
        else:
            if self.optionMap.has_key("noperf"):
                return self.getTestCollator()
            elif self.optionMap.has_key("diag"):
                print "Note: Running with Diagnostics on, so performance checking is disabled!"
                return [ self.getTestCollator(), self.getMemoryFileMaker() ] 
            else:
                return [ self.getTestCollator(), self.getPerformanceFileMaker(), self.getMemoryFileMaker() ] 
    def getCatalogueCreator(self):
        return CreateCatalogue()
    def getTestCollator(self):
        return CollateFiles()
    def getMemoryFileMaker(self):
        return MakeMemoryFile()
    def getPerformanceFileMaker(self):
        return None
    def getTestPredictionChecker(self):
        return predict.CheckPredictions()
    def getFailureExplainer(self):
        if self.bugzillaInstalled():
            return bugzilla.CheckForBugs()
        else:
            return None
    def bugzillaInstalled(self):
        return os.system("which bugcli > /dev/null 2>&1") == 0
    def getTestComparator(self):
        comparetest.MakeComparisons.testComparisonClass = performance.PerformanceTestComparison
        return comparetest.MakeComparisons()
    def getTestResponder(self):
        overwriteSuccess = self.optionMap.has_key("n")
        if self.optionMap.has_key("o"):
            return respond.OverwriteOnFailures(overwriteSuccess)
        else:
            return respond.InteractiveResponder(overwriteSuccess)
    # Utilities, which prove useful in many derived classes
    def optionValue(self, option):
        if self.optionMap.has_key(option):
            return self.optionMap[option]
        else:
            return ""
    def addFilter(self, list, optionName, filterObj):
        if self.optionMap.has_key(optionName):
            list.append(filterObj(self.optionMap[optionName]))
    def printHelpScripts(self):
        print helpScripts, predict.helpScripts
    def printHelpDescription(self):
        print helpDescription, predict.helpDescription, performance.helpDescription, respond.helpDescription
    def printHelpOptions(self, builtInOptions):
        print helpOptions, builtInOptions
    def printHelpText(self, builtInOptions):
        self.printHelpDescription()
        print "Command line options supported :"
        print "--------------------------------"
        self.printHelpOptions(builtInOptions)
        print "Python scripts: (as given to -s <module>.<class> [args])"
        print "--------------------------------------------------------"
        self.printHelpScripts()
    def defaultTextDiffTool(self):
        for dir in sys.path:
            fullPath = os.path.join(dir, "ndiff.py")
            if os.path.isfile(fullPath):
                return sys.executable + " " + fullPath + " -q"
        return None
    def defaultSeverities(self):
        severities = {}
        severities["output"] = 1
        severities["usecase"] = 2
        severities["catalogue"] = 2
        severities["memory"] = 3
        return severities
    def setApplicationDefaults(self, app):
        app.setConfigDefault("log_file", "output")
        app.setConfigDefault("failure_severity", self.defaultSeverities())
        app.setConfigDefault("text_diff_program", self.defaultTextDiffTool())
        app.setConfigDefault("lines_of_text_difference", 30)
        app.setConfigDefault("max_width_text_difference", 900)
        app.setConfigDefault("collate_file", {})
        app.setConfigDefault("run_dependent_text", { "" : [] })
        app.setConfigDefault("unordered_text", { "" : [] })
        app.setConfigDefault("string_before_memory", "")
        app.setConfigDefault("create_catalogues", "false")
        app.setConfigDefault("internal_error_text", [])
        app.setConfigDefault("internal_compulsory_text", [])
        app.setConfigDefault("memory_variation_%", 5)
        app.setConfigDefault("minimum_memory_for_test", 5)
        app.setConfigDefault("use_standard_input", 1)
        app.setConfigDefault("collect_standard_output", 1)
        if self.bugzillaInstalled():
            app.addConfigEntry("definition_file_stems", "bugzilla")
        
class MakeWriteDirectory(plugins.Action):
    def __call__(self, test):
        test.makeBasicWriteDirectory()
        os.chdir(test.writeDirs[0])
    def __repr__(self):
        return "Make write directory for"
    def setUpApplication(self, app):
        app.makeWriteDirectory()

class PrepareWriteDirectory(plugins.Action):
    def __call__(self, test):
        test.prepareBasicWriteDirectory()
    def __repr__(self):
        return "Prepare write directory for"

class SaveState(plugins.Action):
    def __call__(self, test):
        test.saveState()

class CollateFiles(plugins.Action):
    def __init__(self):
        self.collations = {}
        self.diag = plugins.getDiagnostics("Collate Files")
    def setUpApplication(self, app):
        self.collations.update(app.getConfigValue("collate_file"))
    def __call__(self, test):
        if test.state.isComplete():
            return

        errorWrites = []
        for targetStem, sourcePattern in self.collations.items():
            targetFile = test.makeFileName(targetStem, temporary=1)
            fullpath = self.findPath(test, sourcePattern)
            if fullpath:
                self.diag.info("Extracting " + fullpath + " to " + targetFile) 
                self.extract(fullpath, targetFile)
                self.transformToText(targetFile, test)
            elif os.path.isfile(test.makeFileName(targetStem)):
                errorWrites.append((sourcePattern, targetFile))

        # Don't write collation failures if there aren't any files anyway : the point
        # is to highlight partial failure to collect files
        if self.hasAnyFiles(test):
            for sourcePattern, targetFile in errorWrites:
                errText = self.getErrorText(sourcePattern)
                open(targetFile, "w").write(errText + os.linesep)
    def hasAnyFiles(self, test):
        for file in os.listdir(test.getDirectory(temporary=1)):
            if os.path.isfile(file) and test.app.ownsFile(file):
                return 1
        return 0
    def getErrorText(self, sourcePattern):
        return "Expected file '" + sourcePattern + "' not created by test"
    def findPath(self, test, sourcePattern):
        for writeDir in test.writeDirs:
            self.diag.info("Looking for pattern " + sourcePattern + " in " + writeDir)
            pattern = os.path.join(writeDir, sourcePattern)
            paths = glob(pattern)
            if len(paths):
                return paths[0]
    def transformToText(self, path, test):
        # By default assume it is text
        pass
    def extract(self, sourcePath, targetFile):
        shutil.copyfile(sourcePath, targetFile)
    
class TextFilter(plugins.Filter):
    def __init__(self, filterText):
        self.texts = plugins.commasplit(filterText)
        self.textTriggers = [ plugins.TextTrigger(text) for text in self.texts ]
        self.allTestCaseNames = []
    def containsText(self, test):
        return self.stringContainsText(test.name)
    def stringContainsText(self, searchString):
        for trigger in self.textTriggers:
            if trigger.matches(searchString):
                if searchString == trigger.text or not trigger.text in self.allTestCaseNames:
                    return 1
        return 0
    def equalsText(self, test):
        return test.name in self.texts

class TestPathFilter(TextFilter):
    def acceptsTestCase(self, test):
        return test.getRelPath() in self.texts
    def acceptsTestSuite(self, suite):
        for relPath in self.texts:
            if relPath.startswith(suite.getRelPath()):
                return 1
        return 0
    
class TestNameFilter(TextFilter):
    def acceptsTestCase(self, test):
        if self.containsText(test):
            if not test.name in self.allTestCaseNames:
                self.allTestCaseNames.append(test.name)
            return 1
        return 0

class TestSuiteFilter(TextFilter):
    def acceptsTestCase(self, test):
        pathComponents = test.getRelPath().split(os.sep)
        for path in pathComponents:
            if len(path) and path != test.name:
                for trigger in self.textTriggers:
                    if trigger.matches(path):
                        return 1
        return 0

class GrepFilter(TextFilter):
    def __init__(self, filterText):
        TextFilter.__init__(self, filterText)
        self.logFileStem = None
    def acceptsTestCase(self, test):
        logFile = test.makeFileName(self.logFileStem)
        for line in open(logFile).xreadlines():
            if self.stringContainsText(line):
                return 1
        return 0
    def acceptsApplication(self, app):
        self.logFileStem = app.getConfigValue("log_file")
        return 1

class FileFilter(TextFilter):
    def __init__(self, filterFile):
        self.filename = filterFile
        self.texts = [] 
    def acceptsTestCase(self, test):
        return self.equalsText(test)
    def acceptsApplication(self, app):
        fullPath = app.makePathName(self.filename)
        if not fullPath:
            print "File", self.filename, "not found for application", app
            return 0
        self.texts = map(string.strip, open(fullPath).readlines())
        return 1

# Standard error redirect is difficult on windows, don't try...
class RunTest(plugins.Action):
    def __init__(self):
        self.diag = plugins.getDiagnostics("run test")
    def __repr__(self):
        return "Running"
    def __call__(self, test):
        if test.state.isComplete():
            return
        retValue = self.runTest(test)
        # Change state after we've started running!
        self.changeState(test)
        return retValue
    def changeState(self, test):
        test.changeState(plugins.TestState("running", "Running on local machine", started=1))
    def runTest(self, test):
        testCommand = self.getExecuteCommand(test)
        self.runCommand(test, testCommand)
    def getExecuteCommand(self, test):
        testCommand = test.getExecuteCommand() + " < " + self.getInputFile(test)
        outfile = test.makeFileName("output", temporary=1)
        return testCommand + " > " + outfile
    def runCommand(self, test, command, jobNameFunction = None, options = ""):
        if jobNameFunction:
            print test.getIndent() + "Running", jobNameFunction(test), "locally"
        else:
            self.describe(test)
        self.diag.info("Running test with command '" + command + "'")
        os.system(command)
    def getInputFile(self, test):
        inputFileName = test.inputFile
        if os.path.isfile(inputFileName):
            return inputFileName
        if os.name == "posix":
            return "/dev/null"
        else:
            return "nul"
    def setUpSuite(self, suite):
        self.describe(suite)
    def setUpApplication(self, app):
        app.checkBinaryExists()

class CreateCatalogue(plugins.Action):
    def __call__(self, test):
        if test.app.getConfigValue("create_catalogues") != "true":
            return
        fileName = test.makeFileName("catalogue", temporary=1)
        file = open(fileName, "w")
        currDir = os.getcwd()
        for writeDir in test.writeDirs:
            if os.path.isdir(writeDir):
                os.chdir(writeDir)
                realWriteDir = os.getcwd();
                os.chdir(currDir)
                self.listDirectory(test.app, file, realWriteDir, firstLevel = 1)
        file.close()
        if os.path.getsize(fileName) == 0:
            os.remove(fileName)
    def listDirectory(self, app, file, writeDir, firstLevel = 0):
        subDirs = []
        files = []
        availFiles = os.listdir(writeDir)
        availFiles.sort()
        for writeFile in availFiles:
            # Don't list special directories or the framework's own temporary files
            if writeFile == "CVS" or (firstLevel and writeFile == "framework_tmp"):
                continue
            fullPath = os.path.join(writeDir, writeFile)
            if os.path.isdir(fullPath):
                subDirs.append(fullPath)
            elif not app.ownsFile(writeFile, unknown=0):
                files.append(writeFile)
        if len(files) == 0 and len(subDirs) == 0:
            return 0
        file.write("Under " + self.getName(writeDir) + " :" + os.linesep)
        for writeFile in files:
            file.write(writeFile + os.linesep)
        for subDir in subDirs:
            self.listDirectory(app, file, subDir)
        return 1
    def getName(self, writeDir):
        currDir = os.getcwd()
        if plugins.samefile(writeDir, currDir):
            return "Test Directory"
        if writeDir.startswith(currDir):
            return "Test subdirectory " + writeDir.replace(currDir + os.sep, "")
        return os.path.basename(writeDir) + "(" + writeDir + " != " + currDir + ")"
                    
class CountTest(plugins.Action):
    def __init__(self):
        self.appCount = {}
    def __del__(self):
        for app, count in self.appCount.items():
            print "Application", app, "has", count, "tests"
    def __repr__(self):
        return "Counting"
    def __call__(self, test):
        self.describe(test)
        self.appCount[repr(test.app)] += 1
    def setUpSuite(self, suite):
        self.describe(suite)
    def setUpApplication(self, app):
        self.appCount[repr(app)] = 0

class ReconnectTest(plugins.Action):
    def __init__(self, fetchUser, fullRecalculate):
        self.fetchUser = fetchUser
        self.userDepWriteDir = self.hasUserDependentWriteDir()
        self.rootDirToCopy = None
        self.fullRecalculate = fullRecalculate
        self.diag = plugins.getDiagnostics("Reconnection")
    def __repr__(self):
        if self.fullRecalculate:
            return "Copying files for recalculation of"
        else:
            return "Reconnecting to"
    def __call__(self, test):
        self.performReconnection(test)
        self.loadStoredState(test)
    def performReconnection(self, test):
        reconnLocation = os.path.join(self.rootDirToCopy, test.getRelPath())
        if not self.canReconnectTo(reconnLocation):
            raise plugins.TextTestError, "No test results found to reconnect to"

        if self.fullRecalculate:
            self.copyFiles(reconnLocation, test)
        else:
            test.writeDirs[0] = reconnLocation
    def copyFiles(self, reconnLocation, test):
        for file in os.listdir(reconnLocation):
            fullPath = os.path.join(reconnLocation, file)
            if os.path.isfile(fullPath):
                shutil.copyfile(fullPath, os.path.join(test.writeDirs[0], file))
        testStateFile = os.path.join(reconnLocation, "framework_tmp", "teststate")
        if os.path.isfile(testStateFile):
            shutil.copyfile(testStateFile, test.getStateFile())
    def loadStoredState(self, test):
        loaded = test.loadState(self.fullRecalculate)
        if loaded:
            # State will refer to TEXTTEST_HOME in the original (which we may not have now,
            # and certainly don't want to save), try to fix this...
            test.state.updateAbsPath(test.app.abspath)
            self.describe(test, " (state " + test.state.category + ")")
        else:
            if not self.fullRecalculate:
                raise plugins.TextTestError, "No teststate file found, cannot do fast reconnect. Maybe try full recalculation to see what happened"
            self.describe(test)
    def canReconnectTo(self, dir):
        # If the directory does not exist or is empty, we cannot reconnect to it.
        return os.path.exists(dir) and len(os.listdir(dir)) > 0
    def setUpApplication(self, app):
        root, localDir = os.path.split(app.writeDirectory)
        fetchDir = root
        userId = app.getTestUser()
        if self.fetchUser and self.userDepWriteDir:
            fetchDir = fetchDir.replace(userId, self.fetchUser)
        userToFind = self.fetchUser
        if not self.fetchUser:
            userToFind = userId
        self.rootDirToCopy = self.findReconnDirectory(fetchDir, app, userToFind)
        if self.rootDirToCopy:
            print "Reconnecting to test results in directory", self.rootDirToCopy
            if not self.fullRecalculate:
                app.writeDirectory = self.rootDirToCopy
        else:
            raise plugins.TextTestError, "Could not find any runs matching " + app.name + app.versionSuffix() + userToFind + " under " + fetchDir
    def findReconnDirectory(self, fetchDir, app, userToFind):
        if not os.path.isdir(fetchDir):
            return None

        versions = app.getVersionFileExtensions()
        versions.append("")
        for versionSuffix in versions:
            reconnDir = self.findReconnDirWithVersion(fetchDir, app, versionSuffix, userToFind)
            if reconnDir:
                return reconnDir
    def findReconnDirWithVersion(self, fetchDir, app, versionSuffix, userToFind):
        if versionSuffix:
            patternToFind = app.name + "." + versionSuffix + userToFind
        else:
            patternToFind = app.name + userToFind
        for subDir in os.listdir(fetchDir):
            fullPath = os.path.join(fetchDir, subDir)
            if os.path.isdir(fullPath) and subDir.startswith(patternToFind):
                return fullPath
    def setUpSuite(self, suite):
        self.describe(suite)
    def hasUserDependentWriteDir(self):
        return os.environ["TEXTTEST_TMP"].find("~") != -1

# Relies on the config entry string_before_memory, so looks in the log file for anything reported
# by the program
class MakeMemoryFile(plugins.Action):
    def __init__(self):
        self.memoryFinder = None
        self.logFileStem = None
    def setUpApplication(self, app):
        self.memoryFinder = app.getConfigValue("string_before_memory")
        self.logFileStem = app.getConfigValue("log_file")
    def __call__(self, test, temp=1):
        self.makeMemoryFile(test, temp=1)
    def makeMemoryFile(self, test, temp):
        if not self.memoryFinder:
            return
        
        logFile = test.makeFileName(self.logFileStem, temporary=temp)
        if not os.path.isfile(logFile):
            return
        
        maxMem = self.findMaxMemory(logFile)
        if maxMem:
            # We save memory performance in steps of 0.01Mb
            roundedMaxMem = float(int(100*maxMem))/100
            fileName = test.makeFileName("memory", temporary=temp)
            file = open(fileName, "w")
            file.write(string.lstrip("Max Memory  :      " + str(roundedMaxMem) + " MB") + os.linesep)
            file.close()
    def findMaxMemory(self, logFile):
        maxMemory = 0.0
        for line in open(logFile).xreadlines():
            memory = self.getMemory(line)
            if memory and memory > maxMemory:
                maxMemory = memory
        return maxMemory
    def getMemory(self, line):
        pos = line.find(self.memoryFinder)
        if pos == -1:
            return None
        endOfString = pos + len(self.memoryFinder)
        memString = line[endOfString:].lstrip()
        try:
            memNumber = float(memString.split()[0])
            if memString.lower().find("kb") != -1:
                memNumber = float(memNumber / 1024.0)
            return memNumber
        except:
            return None

# A standalone action, we add description and generate the main file instead...
class ExtractMemory(MakeMemoryFile):
    def __repr__(self):
        return "Extracting memory performance for"
    def __call__(self, test):
        self.describe(test)
        self.makeMemoryFile(test, temp=0)
    def setUpSuite(self, suite):
        self.describe(suite)
