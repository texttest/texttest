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

-reconnect <fetchdir:user>
            - Reconnect to already run tests, optionally takes a directory and user from which to
              fetch temporary files.

-t <text>  - only run tests whose names contain <text> as a substring. Note that <text> may be a comma-separated
             list

-ts <text> - only run test suites whose full relative paths contain <text> as a substring. As above this may be
             a comma-separated list.

-f <file>  - only run tests whose names appear in the file <file>
"""

helpScripts = """
default.CountTest          - produce a brief report on the number of tests in the chosen selection, by application
"""

import os, re, shutil, plugins, respond, comparetest, string, predict
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
        actions = [ self.getWriteDirectoryMaker(), self.tryGetTestRunner(), self.getTestEvaluator() ]
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
        return MakeWriteDirectory();
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
            return self.getTestCollator()
    def getCatalogueCreator(self):
        return CreateCatalogue()
    def getTestCollator(self):
        return plugins.Action()
    def getTestPredictionChecker(self):
        return predict.CheckPredictions()
    def getTestComparator(self):
        return comparetest.MakeComparisons(self.optionMap.has_key("n"))
    def getTestResponder(self):
        if self.optionMap.has_key("o"):
            return respond.OverwriteOnFailures(self.optionValue("v"))
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
        print helpScripts
    def printHelpDescription(self):
        print helpDescription, predict.helpDescription, comparetest.helpDescription, respond.helpDescription
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

class CollateFile(plugins.Action):
    def __init__(self, sourcePattern, targetStem):
        self.sourcePattern = sourcePattern
        self.targetStem = targetStem
	self.errText = "Expected file '" + sourcePattern + "' not created by test"
    def __call__(self, test):
        if test.state > test.RUNNING:
            return
        targetFile = test.makeFileName(self.targetStem, temporary=1)
        fullpath = self.findPath(test)
        if fullpath:
            self.extract(fullpath, targetFile)
            self.transformToText(targetFile)
        elif os.path.isfile(test.makeFileName(self.targetStem)):
            open(targetFile, "w").write(self.errText + os.linesep)
    def findPath(self, test):
        for writeDir in test.writeDirs:
            pattern = os.path.join(writeDir, self.sourcePattern)
            paths = glob(pattern)
            if len(paths):
                return paths[0]
        return None
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
        outfile = test.makeFileName("output", temporary=1)
        stdin, stdout, stderr = os.popen3(self.getExecuteCommand(test) + " > " + outfile)
        inputFileName = test.inputFile
        if os.path.isfile(inputFileName):
            inputData = open(inputFileName).read()
            stdin.write(inputData)
        stdin.close()
        errfile = open(test.makeFileName("errors", temporary=1), "w")
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
        for writeDir in test.writeDirs:
            self.listDirectory(test.app, file, os.path.normpath(writeDir))
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
        return os.path.basename(writeDir)
                    
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
    def __init__(self, fetchOption):
        self.fetchDir = None
        self.fetchUser = None
        if len(fetchOption) > 0:
            if fetchOption.find(":") != -1:
                self.fetchDir, self.fetchUser = fetchOption.split(":")
            else:
                self.fetchDir = fetchOption
    def __repr__(self):
        return "Reconnect to"
    def findTestDir(self, test):
        configFile = "config." + test.app.name
        testCaseDir = test.getRelPath()[1:]
        parts = test.app.abspath.split(os.sep)
        for ix in range(len(parts)):
            if ix == 0:
                findDir = self.fetchDir
            else:
                backIx = -1 * (ix + 1)
                findDir = os.path.join(self.fetchDir, string.join(parts[backIx:], os.sep))
            if os.path.isfile(os.path.join(findDir, configFile)):
                return os.path.join(findDir, testCaseDir)
        return None
    def __call__(self, test):
        translateUser = 0
        if self.fetchDir == None or not os.path.isdir(self.fetchDir):
            testDir = test.abspath
        else:
            testDir = self.findTestDir(test)
        if testDir == None:
            self.describe(test, "Failed!")
            return
        pattern = test.app.name + test.app.versionSuffix()
        if self.fetchUser != None:
            pattern += self.fetchUser
        else:
            pattern += test.getTestUser()
        self.describe(test)
        for subDir in os.listdir(testDir):
            fullPath = os.path.join(testDir, subDir)
            if os.path.isdir(fullPath) and subDir.startswith(pattern):
                for file in os.listdir(fullPath):
                    if not file.endswith("cmp"):
                        fullFilePath = os.path.join(fullPath, file)
                        if os.path.isfile(fullFilePath):
                            shutil.copyfile(fullFilePath, os.path.join(os.getcwd(), file))
                break
    def setUpSuite(self, suite):
        self.describe(suite)

class CleanTmpFiles(plugins.Action):
    def __init__(self):
        self.numFiles = 0
        self.regExps = []
        self.regExps.append(re.compile("[0-9][0-9]:[0-9][0-9]:[0-9][0-9]$"))
        self.regExps.append(re.compile("[0-9][0-9]:[0-9][0-9]:[0-9][0-9]cmp$"))
    def __del__(self):
        if self.numFiles > 0:
            print "Removed " + str(self.numFiles) + " file(s)"
    def __repr__(self):
        return "Cleaning tmp files"
    def __call__(self, test):
        curNumFiles = self.numFiles
        for file in os.listdir(test.abspath):
            for regExp in self.regExps:
                if regExp.search(file):
                    os.remove(file)
                    self.numFiles += 1
                    break
        if self.numFiles > curNumFiles:
            self.describe(test, " " + str(self.numFiles - curNumFiles) + " file(s)")
    def setUpSuite(self, suite):
        self.describe(suite)
