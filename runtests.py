#!/usr/bin/env python
import os, sys, string, getopt, types, time
from stat import *

# Base class for TestCase and TestSuite
class Test:
    def __init__(self, name, abspath, app):
        self.name = name
        self.app = app
        self.abspath = abspath
        self.paddedName = self.name
    def isValid(self):
        return os.path.isdir(self.abspath) and self.isValidSpecific()
    def makeFileName(self, stem, version = None):
        if version == None:
            version = self.app.version
        nonVersionName = os.path.join(self.abspath, stem + "." + self.app.name)
        if len(version) == 0:
            return nonVersionName
        versionName = nonVersionName + "." + version
        if os.path.isfile(versionName):
            return versionName
        else:
            return nonVersionName
    def getRelPath(self):
        return string.replace(self.abspath, self.app.abspath, "")
    def performAction(self, action):
        self.performSetUp()
        if type(action) == types.ListType:
            for subAction in action:
                self.performSubAction(subAction)
        else:
            self.performSubAction(action)
        self.performOnSubTests(action)
    def getIndent(self):
        dirCount = string.count(self.getRelPath(), os.sep)
        retstring = ""
        for i in range(dirCount):
            retstring = retstring + "  "
        return retstring
    def isAcceptedByAll(self, filters):
        for filter in filters:
            debugPrint(repr(self) + " filter " + repr(filter))
            if not self.isAcceptedBy(filter):
                return 0
        return 1
        
class TestCase(Test):
    def __init__(self, name, abspath, app):
        Test.__init__(self, name, abspath, app)
        self.inputFile = self.makeFileName("input")
        optionsFile = self.makeFileName("options")
        self.options = ""
        if (os.path.isfile(optionsFile)):
            self.options = open(optionsFile).readline()[:-1]
    def __repr__(self):
        return repr(self.app) + " " + self.classId() + " " + self.paddedName
    def classId(self):
        return "test-case"
    def isValidSpecific(self):
        return os.path.isfile(self.inputFile) or len(self.options) > 0
    def performSetUp(self):
        os.chdir(self.abspath)
        debugPrint(self.getExecuteCommand())
    def performSubAction(self, subAction):
        description = self.getIndent() + repr(subAction) + " " + repr(self)
        subAction(self, description)
    def performOnSubTests(self, action):
        pass
    def getExecuteCommand(self):
        return self.app.executeCommand + " " + self.options
    def getTmpExtension(self):
        return globalRunIdentifier
    def getTmpFileName(self, text, mode):
        prefix = text + "." + self.app.name
        fileName = prefix + globalRunIdentifier
        if mode == "w" and not inputOptions.parallelMode():
            tmpString = prefix + os.environ["USER"]
            for file in os.listdir(self.abspath):
                if file.find(tmpString) != -1:
                    os.remove(file)
        return fileName
    def isAcceptedBy(self, filter):
        return filter.acceptsTestCase(self)
        
class TestSuite(Test):
    def __init__(self, name, abspath, app, filters):
        Test.__init__(self, name, abspath, app)
        self.testCaseFile = self.makeFileName("testsuite")
        self.environment = MultiEntryDictionary(os.path.join(self.abspath, "environment"), app.version)
        self.testcases = self.getTestCases(filters)
        if len(self.testcases):
            maxNameLength = max([len(test.name) for test in self.testcases])
            for test in self.testcases:
                test.paddedName = string.ljust(test.name, maxNameLength) 
    def __repr__(self):
        return repr(self.app) + " " + self.classId() + " " + self.name + ", checkout " + self.app.checkout
    def classId(self):
        return "test-suite"
    def isValidSpecific(self):
        return os.path.isfile(self.testCaseFile)
    def isEmpty(self):
        return len(self.testcases) == 0
    def performSetUp(self):
        for var, value in self.environment.items():
            os.environ[var] = self.app.makeAbsPath(os.path.expandvars(value))
            debugPrint("Setting " + var + " to " + os.environ[var])
    def performSubAction(self, subAction):
        description = self.getIndent() + repr(subAction) + " " + repr(self)
        subAction.setUpSuite(self, description)
    def performOnSubTests(self, action):
        for testcase in self.testcases:
            testcase.performAction(action)
    def isAcceptedBy(self, filter):
        return filter.acceptsTestSuite(self)
# private:
    def getTestCases(self, filters):
        testCaseList = []
        if not self.isValid() or not self.isAcceptedByAll(filters):
            return testCaseList

        self.performSetUp()
        for testline in open(self.testCaseFile).readlines():
            if testline == '\n' or testline[0] == '#':
                continue
            testName = string.strip(testline)
            testPath = os.path.join(self.abspath, testName)
            testSuite = TestSuite(testName, testPath, self.app, filters)
            if testSuite.isValid():
                if not testSuite.isEmpty():
                    testCaseList.append(testSuite)
            else:
                testCase = TestCase(testName, testPath, self.app)
                if testCase.isValid() and testCase.isAcceptedByAll(filters):
                    testCaseList.append(testCase)
        return testCaseList
            
class Application:
    def __init__(self, name, abspath, configFile, version, optionMap, builtInOptions):
        self.name = name
        self.abspath = abspath
        self.configDir = MultiEntryDictionary(configFile, version)
        self.version = version
        debugPrint("Found application " + repr(self))
        self.checkout = self.makeCheckout()
        debugPrint("Checkout set to " + self.checkout)
        self.executeCommand = self.setExecuteCommand()
        self.configObject = self.makeConfigObject(optionMap)
        allowedOptions = self.configObject.getOptionString() + builtInOptions
        # Force exit if something isn't present
        getopt.getopt(sys.argv[1:], allowedOptions)    
        debugPrint("Execute command set to " + self.executeCommand)
    def __repr__(self):
        return string.upper(self.name)
    def makeAbsPath(self, path):
        if (os.path.isabs(path)):
            return path
        else:
            return os.path.join(self.checkout, path)
    def makeConfigObject(self, optionMap):
        configModule = self.getConfigValue("config_module")
        importCommand = "from " + configModule + " import getConfig"
        try:
            exec importCommand
        except ImportError:
            raise "Could not find config_module " + configModule
        return getConfig(optionMap)
    def getActionSequence(self):
        return self.configObject.getActionSequence()
    def getFilterList(self):
        return self.configObject.getFilterList()
    def getConfigValue(self, key):
        if self.configDir.has_key(key):
            return self.configDir[key]
        else:
            raise "Error: " + repr(self) + " cannot find config entry " + key
    def getConfigList(self, key):
        return self.configDir.getListValue(key)
    def filterFile(self, fileName):
        stem = fileName.split('.')[0]
        if not self.configDir.has_key(stem) or not os.path.isfile(fileName):
            return fileName

        newFileName = fileName + "cmp"
        oldFile = open(fileName)
        newFile = open(newFileName, "w")
        forbiddenText = self.getConfigValue(stem)
        for line in oldFile.readlines():
            if self.filterLine(line, forbiddenText):
                newFile.write(line)
        newFile.close()
        return newFileName
#private:
    def filterLine(self, line, forbiddenText):
        for text in forbiddenText:
            if line.find(text) != -1:
                return 0
        return 1
    def makeCheckout(self):
        checkout = inputOptions.checkoutName()
        if checkout == None:
            checkout = self.getConfigValue("default_checkout")
        checkoutLocation = os.path.expanduser(self.getConfigValue("checkout_location"))
        return os.path.join(checkoutLocation, checkout)
    def setExecuteCommand(self):
        binary = self.makeAbsPath(self.getConfigValue("binary"))
        if self.configDir.has_key("interpreter"):
            return self.configDir["interpreter"] + " " + binary
        else:
            return binary
            
class OptionFinder:
    def __init__(self):
        self.inputOptions = self.buildOptions()
    # Yes, we know that getopt exists. However it throws exceptions when it finds unrecognised things, and we can't do that...
    def buildOptions(self):
        inputOptions = {}
        fullString = string.join(sys.argv[1:])
        optionList = string.split(fullString, '-')[1:]
        for item in optionList:
            option = string.strip(item)
            if ' ' in option:
                opt, value = string.split(option, ' ')
                inputOptions[opt] = value
            else:
                inputOptions[option] = ""
        return inputOptions
    def findApps(self):
        dirName = self.directoryName()
        debugPrint("Using test suite at " + dirName)
        return self._findApps(dirName, 1)
    def _findApps(self, dirName, recursive):
        appList = []
        for f in os.listdir(dirName):
            pathname = os.path.join(dirName, f)
            if os.path.isfile(pathname):
                components = string.split(f, '.')
                if len(components) > 2 or components[0] != "config":
                    continue
                appName = components[1]
                if self.inputOptions.has_key("a") and appName != self.inputOptions["a"]:
                    continue
                versionString = self.findVersionString()
                app = Application(appName, dirName, pathname, versionString, self.inputOptions, "a:c:d:s:v:xp")
                appList.append(app)
            elif os.path.isdir(pathname) and recursive:
                for app in self._findApps(pathname, 0):
                    appList.append(app)
        return appList
    def findVersionString(self):
        if self.inputOptions.has_key("v"):
            return self.inputOptions["v"]
        else:
            return ""
    def debugMode(self):
        return self.inputOptions.has_key("x")
    def parallelMode(self):
        return self.inputOptions.has_key("p")
    def directoryName(self):
        if self.inputOptions.has_key("d"):
            return os.path.abspath(self.inputOptions["d"])
        else:
            return os.getcwd()
    def checkoutName(self):
        if self.inputOptions.has_key("c"):
            return self.inputOptions["c"]
        else:
            return None
    def getActionSequence(self, app):
        if self.inputOptions.has_key("s"):
            return [ NonPythonAction(self.inputOptions["s"]) ]
        else:
            return app.getActionSequence()

class NonPythonAction:
    def __init__(self, actionText):
        self.script = os.path.abspath(actionText)
    def __repr__(self):
        return "Running script " + os.path.basename(self.script) + " for"
    def __call__(self, test, description):
        self.callScript(test, description, "test_level")
    def setUpSuite(self, suite, description):
        os.chdir(suite.abspath)
        self.callScript(suite, description, "suite_level")
    def callScript(self, test, description, level):
        os.system(self.script + " " + level + " " + test.name + " " + test.app.name + " '" + description + "'")
            
class MultiEntryDictionary:
    def __init__(self, filename, version = ""):
        self.dict = {}
        if os.path.isfile(filename):
            configFile = open(filename)
            for line in configFile.readlines():
                if line[0] == '#' or not ':' in line:
                    continue
                self.addLine(line[:-1])
        self.updateForVersion(filename, version)
    def updateForVersion(self, filename, version):
        if len(version) == 0:
            return
        versionFileName = filename + "." + version
        if not os.path.isfile(versionFileName):
            return
        overrideDir = MultiEntryDictionary(versionFileName)
        for key, value in overrideDir.items():
            self.dict[key] = value
    def addLine(self, line, separator = ':'):
        entryName, entry = string.split(line, separator, 1)
        if self.dict.has_key(entryName):
            try:
                self.dict[entryName].append(entry)
            except:
                oldEntry = self.dict[entryName]
                entryList = []
                entryList.append(oldEntry)
                entryList.append(entry)
                self.dict[entryName] = entryList
        else:
            self.dict[entryName] = entry
    def has_key(self, key):
        return self.dict.has_key(key)
    def keys(self):
        return self.dict.keys()
    def items(self):
        return self.dict.items()
    def __getitem__(self, key):
        return self.dict[key]
    def __setitem__(self, key, value):
        self.dict[key] = value
    def __repr__(self):
        return repr(self.dict)
    def getListValue(self, key):
        if self.dict.has_key(key):
            value = self.dict[key]
            if type(value) == types.ListType:
                return value
            else:
                list = []
                list.append(value)
                return list
        else:
            return []

def debugPrint(text):
    if inputOptions.debugMode():
        print text

def extraFilter(action):
    try:
        return action.filter
    except:
        return None

# --- MAIN ---

def main():
    # Declared global for debugPrint() above
    global inputOptions
    inputOptions = OptionFinder()
    global globalRunIdentifier
    globalRunIdentifier = os.environ["USER"] + time.strftime("%H:%M:%S", time.localtime())

    for app in inputOptions.findApps():
        actionSequence = inputOptions.getActionSequence(app)
        allTests = TestSuite(os.path.basename(app.abspath), app.abspath, app, app.getFilterList())
        for action in actionSequence:
            filter = extraFilter(action)
            if filter != None:
                filterList = app.getFilterList()
                filterList.append(filter)
                debugPrint("Creating extra test suite from new filter " + repr(filter))
                debugPrint(os.getcwd())
                actionTests = TestSuite(os.path.basename(app.abspath), app.abspath, app, filterList)
                actionTests.performAction(action)
            else:
                allTests.performAction(action)

if __name__ == "__main__":
    main()
