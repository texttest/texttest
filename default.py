#!/usr/local/bin/python

helpDescription = """
The default configuration is the simplest and most portable. It is intended to run on
any architecture. Therefore, differences in results are displayed using Python's ndiff
module, the most portable differencing tool I can find, anyway.

Its default behaviour is to run all tests on the local machine.
"""

helpOptions = """
-i         - run in interactive mode. This means that the framework will interleave running and comparing
             the tests, so that test 2 is not run until test 1 has been run and compared.

-o         - run in overwrite mode. This means that the interactive dialogue is replaced by simply
             overwriting all previous results with new ones.

-n         - run in new-file mode. Tests that succeed will still overwrite the standard file, rather than
             leaving it, as is the deafult behaviour.

-reconnect <user>
            - Reconnect to already run tests, optionally takes a user from which to
              fetch temporary files. If not provided, will look for calling user.

-t <text>  - only run tests whose names contain <text> as a substring. Note that <text> may be a comma-separated
             list

-ts <text> - only run test suites whose full relative paths contain <text> as a substring. As above this may be
             a comma-separated list.

-f <file>  - only run tests whose names appear in the file <file>
"""

helpScripts = """
default.CountTest          - produce a brief report on the number of tests in the chosen selection, by application

default.ExtractMemory      - update the memory files from the standard log files
"""

import os, re, shutil, plugins, respond, performance, string, predict
from glob import glob

def getConfig(optionMap):
    return Config(optionMap)

class Config(plugins.Configuration):
    def getArgumentOptions(self):
        options = {}
        options["t"] = "Select tests containing"
        options["f"] = "Select tests from file"
        options["ts"] = "Select test suites containing"
        options["reconnect"] = "Reconnect to previous run"
        return options
    def getSwitches(self):
        switches = {}
        switches["i"] = "Interactive mode"
        switches["o"] = "Overwrite all failures"
        switches["n"] = "Create new results files (overwrite everything)"
        switches["b"] = "Plot original and temporary file"
        switches["ns"] = "Don't scale times"
        switches["nv"] = "No line type grouping for versions"
        return switches
    def getActionSequence(self):
        return self._getActionSequence(makeDirs=1)
    def _getActionSequence(self, makeDirs):
        actions = [ self.tryGetTestRunner(), self.getTestEvaluator() ]
        if makeDirs:
            actions = [ self.getWriteDirectoryMaker() ] + actions
        if self.optionMap.has_key("i"):
            return [ plugins.CompositeAction(actions) ]
        else:
            return actions
    def getFilterList(self):
        filters = []
        self.addFilter(filters, "t", TestNameFilter)
        self.addFilter(filters, "ts", TestSuiteFilter)
        self.addFilter(filters, "f", FileFilter)
        return filters
    def isReconnecting(self):
        return self.optionMap.has_key("reconnect")
    def getWriteDirectoryMaker(self):
        if self.isReconnecting():
            return plugins.Action()
        else:
            return MakeWriteDirectory()
    def tryGetTestRunner(self):
        if self.isReconnecting():
            return plugins.Action()
        else:
            return self.getTestRunner()
    def getTestRunner(self):
        return RunTest()
    def getTestEvaluator(self):
        subParts = [ self.getFileExtractor(), self.getCatalogueCreator(), \
                     self.getTestPredictionChecker(), self.getTestComparator(), self.getTestResponder() ]
        return plugins.CompositeAction(subParts)
    def getFileExtractor(self):
        if self.isReconnecting():
            return ReconnectTest(self.optionValue("reconnect"))
        else:
            return plugins.CompositeAction([self.getTestCollator(), self.getPerformanceFileMaker(), self.getMemoryFileMaker()])
    def getCatalogueCreator(self):
        return CreateCatalogue()
    def getTestCollator(self):
        return CollateFiles()
    def getMemoryFileMaker(self):
        return MakeMemoryFile()
    def getPerformanceFileMaker(self):
        return plugins.Action()
    def getTestPredictionChecker(self):
        return predict.CheckPredictions()
    def getTestComparator(self):
        return performance.MakeComparisons(self.optionMap.has_key("n"))
    def getTestResponder(self):
        if self.optionMap.has_key("o"):
            return respond.OverwriteOnFailures()
        else:
            return respond.InteractiveResponder()
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

class MakeWriteDirectory(plugins.Action):
    def __call__(self, test):
        test.makeBasicWriteDirectory()
        os.chdir(test.writeDirs[0])
    def __repr__(self):
        return "Make write directory for"
    def setUpApplication(self, app):
        app.makeWriteDirectory()

class CollateFiles(plugins.Action):
    def __init__(self):
        self.collations = []
        self.diag = plugins.getDiagnostics("Collate Files")
    def setUpApplication(self, app):
        for entry in app.getConfigList("collate_file"):
            if entry.find("->") == -1:
                print "WARNING: cannot collate file from entry '" + entry + "'"
                print "Must be of the form '<source_pattern>-><target_name>'"
                continue
            sourcePattern, targetStem = entry.split("->")
            self.collations.append((sourcePattern, targetStem))
    def __call__(self, test):
        if test.state > test.RUNNING:
            return

        for sourcePattern, targetStem in self.collations:
            targetFile = test.makeFileName(targetStem, temporary=1)
            fullpath = self.findPath(test, sourcePattern)
            if fullpath:
                self.diag.info("Extracting " + fullpath + " to " + targetFile) 
                self.extract(fullpath, targetFile)
                self.transformToText(targetFile)
            elif os.path.isfile(test.makeFileName(targetStem)):
                errText = self.getErrorText(sourcePattern)
                open(targetFile, "w").write(errText + os.linesep)
    def getErrorText(self, sourcePattern):
        return "Expected file '" + sourcePattern + "' not created by test"
    def findPath(self, test, sourcePattern):
        for writeDir in test.writeDirs:
            self.diag.info("Looking for pattern " + sourcePattern + " in " + writeDir)
            pattern = os.path.join(writeDir, sourcePattern)
            paths = glob(pattern)
            if len(paths):
                return paths[0]
    def transformToText(self, path):
        # By default assume it is text
        pass
    def extract(self, sourcePath, targetFile):
        shutil.copyfile(sourcePath, targetFile)
    
class TextFilter(plugins.Filter):
    def __init__(self, filterText):
        self.texts = plugins.commasplit(filterText)
        self.allTestCaseNames = []
    def containsText(self, test):
        for text in self.texts:
            if test.name.find(text) != -1:
                if test.name == text or not text in self.allTestCaseNames:
                    return 1
                else:
                    return 0
        return 0
    def equalsText(self, test):
        return test.name in self.texts
    
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
                for text in self.texts:
                    if path.find(text) != -1:
                        return 1
        return 0

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
    
# Use communication channels for stdin and stderr (because we don't know how to redirect these on windows).
# Tried to use communication channels on all three, but read() blocks and deadlock between stderr and stdout can result.
class RunTest(plugins.Action):
    def __repr__(self):
        return "Running"
    def __call__(self, test):
        if test.state == test.UNRUNNABLE:
            return
        self.describe(test)
        self.changeState(test)
        self.runTest(test)
    def changeState(self, test):
        test.changeState(test.RUNNING, "Running on local machine")
    def runTest(self, test):
        outfileName = test.makeFileName("output", temporary=1)
        errfileName = test.makeFileName("errors", temporary=1)
        stdin, stdout, stderr = os.popen3(self.getExecuteCommand(test) + " > " + outfileName)
        inputFileName = test.inputFile
        if os.path.isfile(inputFileName):
            inputData = open(inputFileName).read()
            stdin.write(inputData)
        stdin.close()
        errfile = open(errfileName, "w")
        errfile.write(stderr.read())
        errfile.close()
        #needed to be sure command is finished
        try:
            os.wait()
        except AttributeError:
            pass # Wait doesn't exist on Windows, but seems necessary on UNIX
    def getExecuteCommand(self, test):
        return test.getExecuteCommand()
    def setUpSuite(self, suite):
        self.describe(suite)

class CreateCatalogue(plugins.Action):
    def setUpApplication(self, app):
        app.setConfigDefault("create_catalogues", "false")
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
                self.listDirectory(test.app, file, realWriteDir)
        file.close()
        if os.path.getsize(fileName) == 0:
            os.remove(fileName)
    def listDirectory(self, app, file, writeDir):
        subDirs = []
        files = []
        availFiles = os.listdir(writeDir)
        availFiles.sort()
        for writeFile in availFiles:
            if writeFile == "CVS":
                continue
            fullPath = os.path.join(writeDir, writeFile)
            if os.path.isdir(fullPath):
                subDirs.append(fullPath)
            elif not app.ownsFile(writeFile):
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
        if os.path.samefile(writeDir, currDir):
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
    def __init__(self, fetchUser):
        self.fetchUser = fetchUser
    def __repr__(self):
        return "Reconnect to"
    def __call__(self, test):
        print "Reconnecting to test", test.name
        if os.path.isdir(test.writeDirs[0]):
            os.chdir(test.writeDirs[0])
        else:
            os.makedirs(test.writeDirs[0])
            os.chdir(test.writeDirs[0])
        for file in os.listdir(os.getcwd()):
            if file.endswith("cmp"):
                os.remove(file)
    def setUpApplication(self, app):
        root, localDir = os.path.split(app.writeDirectory)
        if not os.path.isdir(root):
            os.makedirs(root)
        fetchDir = root
        userId = app.getTestUser()
        if self.fetchUser and self.hasUserDependentWriteDir(app, userId):
            fetchDir = fetchDir.replace(userId, self.fetchUser)
        userToFind = self.fetchUser
        if not self.fetchUser:
            userToFind = userId
        patternToFind = app.name + app.versionSuffix() + userToFind
        for subDir in os.listdir(fetchDir):
            fullPath = os.path.join(fetchDir, subDir)
            if os.path.isdir(fullPath) and subDir.startswith(patternToFind):
                print "Reconnecting to test results in directory", fullPath
                shutil.copytree(fullPath, app.writeDirectory)
        if not os.path.isdir(app.writeDirectory):
            raise plugins.TextTestError, "Could not find any runs matching " + patternToFind + " under " + fetchDir
    def hasUserDependentWriteDir(self, app, userId):
        origWriteDir = app.getConfigValue("write_tmp_files")
        return origWriteDir.find(userId) != -1 or origWriteDir.find("~") != -1

# Relies on the config entry string_before_memory, so looks in the log file for anything reported
# by the program
class MakeMemoryFile(plugins.Action):
    def __init__(self):
        self.memoryFinder = None
        self.logFileStem = None
    def setUpApplication(self, app):
        app.setConfigDefault("log_file", "output")
        app.setConfigDefault("string_before_memory", "")
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
