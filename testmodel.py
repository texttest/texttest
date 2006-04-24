#!/usr/bin/env python
import os, sys, types, string, plugins, exceptions, log4py, shutil, fnmatch
from time import time
from usecase import ScriptEngine, UseCaseScriptError
from ndict import seqdict
from copy import copy
from cPickle import Pickler, Unpickler, UnpicklingError
from respond import Responder

helpIntro = """
Note: the purpose of this help is primarily to document derived configurations and how they differ from the
defaults. To find information on the configurations provided with texttest, consult the documentation at
http://www.texttest.org/TextTest/docs
"""            

class DirectoryCache:
    def __init__(self, dir):
        self.dir = dir
        self.contents = []
        self.refresh()
    def refresh(self):
        self.contents = os.listdir(self.dir)
    def exists(self, fileName):
        if fileName.find(os.sep) != -1:
            return os.path.exists(self.pathName(fileName))
        else:
            return fileName in self.contents
    def pathName(self, fileName):
        return os.path.join(self.dir, fileName)
    def findFile(self, fileNames):
        for fileName in fileNames:
            if self.exists(fileName):
                return self.pathName(fileName)
    def findFilesMatching(self, patterns):
        matchingFiles = filter(lambda fileName : self.matchesPattern(fileName, patterns), self.contents)
        return map(self.pathName, matchingFiles)
    def matchesPattern(self, fileName, patterns):
        for pattern in patterns:
            if fnmatch.fnmatch(fileName, pattern):
                return True
        return False        
    def findAllFiles(self, fileNames):
        fileNames.reverse() # assume most-specific first, we want least-specific first here
        existingFiles = filter(self.exists, fileNames)
        return map(self.pathName, existingFiles)
    def relPath(self, otherCache):
        # We standardise communication around UNIX paths, it's all much easier that way
        relPath = self.dir.replace(otherCache.dir, "").replace(os.sep, "/")
        if relPath.startswith("/"):
            return relPath[1:]
        return relPath
    def findExtensionFiles(self, stem, compulsory = [], forbidden = []):
        # return all files beginning with "stem", that contain all extensions in "compulsory" and none in "forbidden"...
        localNames = filter(lambda file: self.matches(file, stem, compulsory, forbidden), self.contents)
        return map(self.pathName, localNames)
    def matches(self, file, stem, compulsory, forbidden):
        if not file.startswith(stem):
            return False
        for ext in compulsory:
            if file.find(ext) == -1:
                return False
        for ext in forbidden:
            if file.find(ext) != -1:
                return False
        return True

# Base class for TestCase and TestSuite
class Test:
    # List of objects observing all tests, for reacting to state changes
    observers = []    
    def __init__(self, name, dircache, app, parent = None):
        self.name = name
        # There is nothing to stop several tests having the same name. Maintain another name known to be unique
        self.uniqueName = name
        self.app = app
        self.parent = parent
        self.dircache = dircache
        # Test suites never change state, but it's convenient that they have one
        self.state = plugins.TestState("not_started")
        self.paddedName = self.name
        self.previousEnv = {}
        self.environment = MultiEntryDictionary()
        # Java equivalent of the environment mechanism...
        self.properties = MultiEntryDictionary()
    def readEnvironment(self, referenceVars = []):
        self.app.configObject.setEnvironment(self)
        if self.parent == None:
            self.setEnvironment("TEXTTEST_CHECKOUT", self.app.checkout)

        envFiles = self.app.getVersionExtendedNames("environment")
        self.environment.readValues(envFiles, self.dircache)
        # Should do this, but not quite yet...
        # self.properties.readValues("properties", self.dircache)
        debugLog.info("Expanding " + self.name)
        childReferenceVars = self.expandEnvironmentReferences(referenceVars)
        self.readChildEnvironment(childReferenceVars)
        self.tearDownEnvironment()
        debugLog.info("End Expanding " + self.name)
    def getWordsInFile(self, stem):
        file = self.getFileName(stem)
        if file:
            contents = open(file).read().strip()
            return contents.split()
        else:
            return []
    def setEnvironment(self, var, value):
        self.environment[var] = value
    def expandEnvironmentReferences(self, referenceVars = []):
        childReferenceVars = copy(referenceVars)
        for var, value in self.environment.items():
            expValue = os.path.expandvars(value)
            if expValue != value:
                debugLog.info("Expanded variable " + var + " to " + expValue + " in " + self.name)
                # Check for self-referential variables: don't multiple-expand
                if value.find(var) == -1:
                    childReferenceVars.append((var, value))
                self.environment[var] = expValue
            self.setUpEnvVariable(var, expValue)
        for var, value in referenceVars:
            debugLog.info("Trying reference variable " + var + " in " + self.name)
            if self.environment.has_key(var):
                childReferenceVars.remove((var, value))
                continue
            expValue = os.path.expandvars(value)
            if expValue != os.getenv(var):
                self.environment[var] = expValue
                debugLog.info("Adding reference variable " + var + " as " + expValue + " in " + self.name)
                self.setUpEnvVariable(var, expValue)
            else:
                debugLog.info("Not adding reference " + var + " as same as local value " + expValue + " in " + self.name)
        return childReferenceVars
    def readChildEnvironment(self, referenceVars):
        pass
    def getEnvironment(self, var):
        if self.environment.has_key(var):
            return self.environment[var]
        elif self.parent:
            return self.parent.getEnvironment(var)
    def ownFiles(self):
        localNames = filter(self.app.ownsFile, self.dircache.contents)
        return map(self.dircache.pathName, localNames)
    def filesChanged(self):
        self.dircache.refresh()
        self.refreshContents()
        self.notifyChanged()
    def refreshContents(self):
        pass
    def getVersionExtendedNames(self, stem, refVersion = None):
        if refVersion:
            refApp = self.app.createCopy(refVersion)
            return refApp.getVersionExtendedNames(stem)
        else:
            return self.app.getVersionExtendedNames(stem)
    def makeSubDirectory(self, name):
        subdir = self.dircache.pathName(name)
        if os.path.isdir(subdir):
            return subdir
        try:
            os.mkdir(subdir)
            return subdir
        except OSError:
            raise plugins.TextTestError, "Cannot create test sub-directory : " + subdir
    def getFileNamesMatching(self, pattern):
        patterns = self.getVersionExtendedNames(pattern)
        return self.dircache.findFilesMatching(patterns)
    def getFileName(self, stem, refVersion = None):
        debugLog.info("Getting file from " + stem)
        names = self.getVersionExtendedNames(stem, refVersion)
        return self.dircache.findFile(names)
    def getConfigValue(self, key, expandVars=True):
        return self.app.getConfigValue(key, expandVars)
    def makePathName(self, fileName):
        if self.parent is None or self.dircache.exists(fileName):
            return self.dircache.pathName(fileName)
        return self.parent.makePathName(fileName)
    def notifyCompleted(self):
        debugLog.info("Completion notified, test " + self.name)
        for observer in self.observers:
            observer.notifyLifecycleChange(self, "complete")
            observer.notifyComplete(self)
    def notifyChanged(self, state=None):
        for observer in self.observers:
            if observer.notifyChange(self, state):
                # threaded observers can transfer the change to another thread for later propagation
                return
        if state and state.lifecycleChange:
            for observer in self.observers:
                observer.notifyLifecycleChange(self, state.lifecycleChange)
    def getRelPath(self):
        return self.dircache.relPath(self.app.dircache)
    def getDirectory(self, temporary=False, forComparison=True):
        return self.dircache.dir
    def setUpEnvVariable(self, var, value):
        if os.environ.has_key(var):
            self.previousEnv[var] = os.environ[var]
        os.environ[var] = value
        debugLog.debug("Setting " + var + " to " + os.environ[var])
    def setUpEnvironment(self, parents=0):
        if parents and self.parent:
            self.parent.setUpEnvironment(1)
        for var, value in self.environment.items():
            self.setUpEnvVariable(var, value)
    def tearDownEnvironment(self, parents=0):
        # Note this has no effect on the real environment, but can be useful for internal environment
        # variables. It would be really nice if Python had a proper "unsetenv" function...
        debugLog.debug("Restoring environment for " + self.name + " to " + repr(self.previousEnv))
        for var in self.previousEnv.keys():
            os.environ[var] = self.previousEnv[var]
        for var in self.environment.keys():
            if not self.previousEnv.has_key(var):
                debugLog.debug("Removed variable " + var)
                # Set to empty string as a fake-remove. Some versions of
                # python do not have os.unsetenv and hence del only has an internal
                # effect. It's better to leave an empty value than to leak the set value
                os.environ[var] = ""
                del os.environ[var]
        if parents and self.parent:
            self.parent.tearDownEnvironment(1)
    def getIndent(self):
        relPath = self.getRelPath()
        if not len(relPath):
            return ""
        dirCount = string.count(relPath, "/") + 1
        retstring = ""
        for i in range(dirCount):
            retstring = retstring + "  "
        return retstring
    def isAcceptedByAll(self, filters):
        for filter in filters:
            debugLog.debug(repr(self) + " filter " + repr(filter))
            if not self.isAcceptedBy(filter):
                debugLog.debug("REJECTED")
                return False
        return True
    def size(self):
        return 1

class TestCase(Test):
    def __init__(self, name, abspath, app, parent):
        Test.__init__(self, name, abspath, app, parent)
        # Directory where test executes from and hopefully where all its files end up
        self.writeDirectory = os.path.join(app.writeDirectory, self.getRelPath())
    def __repr__(self):
        return repr(self.app) + " " + self.classId() + " " + self.paddedName
    def classId(self):
        return "test-case"
    def testCaseList(self):
        return [ self ]
    def getDirectory(self, temporary=False, forComparison=True):
        if temporary:
            if forComparison:
                return self.writeDirectory
            else:
                return os.path.join(self.writeDirectory, "framework_tmp")
        else:
            return self.dircache.dir
    def callAction(self, action):
        return action(self)
    def changeState(self, state):
        self.state = state
        debugLog.info("Change notified, test " + self.uniqueName + " in state " + state.category)
        self.notifyChanged(state)
    def getStateFile(self):
        return self.makeTmpFileName("teststate", forComparison=0)
    def getFileToLoad(self):
        stateFile = self.getStateFile()
        if not os.path.isfile(stateFile):
            return None
        
        return open(stateFile)
    def getStoredStateInfo(self):
        file = self.getFileToLoad()
        return self.getNewState(file)
    def loadState(self, file):
        loaded, state = self.getNewState(file)
        self.changeState(state)
    def makeTmpFileName(self, stem, forComparison=1):
        if forComparison:
            return os.path.join(self.writeDirectory, stem + "." + self.app.name)
        else:
            return os.path.join(self.writeDirectory, "framework_tmp", stem)
    def getNewState(self, file):
        if not file:
            return False, plugins.TestState("unrunnable", briefText="no results", \
                                            freeText="No file found to load results from", completed=1)
        try:
            unpickler = Unpickler(file)
            return True, unpickler.load()
        except UnpicklingError:
            return False, plugins.TestState("unrunnable", briefText="read error", \
                                            freeText="Failed to read results file", completed=1)
    def saveState(self):
        stateFile = self.getStateFile()
        if os.path.isfile(stateFile):
            # Don't overwrite previous saved state
            return

        file = plugins.openForWrite(stateFile)
        pickler = Pickler(file)
        pickler.dump(self.state)
        file.close()
    def getTmpExtension(self):
        return self.app.configObject.getRunIdentifier()
    def isOutdated(self, filename):
        modTime = plugins.modifiedTime(filename)
        currTime = time()
        threeDaysInSeconds = 60 * 60 * 24 * 3
        return currTime - modTime > threeDaysInSeconds
    def isAcceptedBy(self, filter):
        return filter.acceptsTestCase(self)
            
class TestSuite(Test):
    def __init__(self, name, dircache, app, parent=None, forTestRuns=0):
        Test.__init__(self, name, dircache, app, parent)
        self.testcases = []
    def readContents(self, filters, forTestRuns):
        testNames = self.readTestNames(forTestRuns)
        self.testcases = self.getTestCases(filters, testNames, forTestRuns)
        if len(self.testcases):
            maxNameLength = max([len(test.name) for test in self.testcases])
            for test in self.testcases:
                test.paddedName = string.ljust(test.name, maxNameLength)
        elif forTestRuns or len(testNames) > 0:
            # If we want to run tests, there is no point in empty test suites. For other purposes they might be useful...
            # If the contents are filtered away we shouldn't include the suite either though.
            return False

        for filter in filters:
            if not filter.acceptsTestSuiteContents(self):
                return False
        return True
    def readTestNames(self, forTestRuns):
        testCaseFile = self.getContentFileName()
        if not testCaseFile:
            return []
        names = self.readTestNamesFromFile(testCaseFile)
        debugLog.info("Test suite file " + testCaseFile + " had " + str(len(names)) + " tests")
        if forTestRuns:
            return names
        # If we're not running tests, we're displaying information and should find all the sub-versions 
        for fileName in self.findVersionTestSuiteFiles():
            newNames = self.readTestNamesFromFile(fileName)
            for name in newNames:
                if not name in names:
                    names.append(name)
            debugLog.info("Reading more tests from " + fileName)
        return names
    def readTestNamesFromFile(self, fileName):
        names = []
        debugLog.info("Reading " + fileName)
        for name in plugins.readList(fileName, self.getConfigValue("auto_sort_test_suites")):
            debugLog.info("Read " + name)
            if name in names:
                print "WARNING: the test", name, "was included several times in a test suite file"
                print "Please check the file at", fileName
                continue

            if not self.dircache.exists(name):
                print "WARNING: the test", name, "could not be found"
                print "Please check the file at", fileName
                continue
            names.append(name)
        return names
    def __repr__(self):
        return repr(self.app) + " " + self.classId() + " " + self.name
    def testCaseList(self):
        list = []
        for case in self.testcases:
            list += case.testCaseList()
        return list
    def classId(self):
        return "test-suite"
    def isEmpty(self):
        return len(self.testcases) == 0
    def callAction(self, action):
        return action.setUpSuite(self)
    def isAcceptedBy(self, filter):
        return filter.acceptsTestSuite(self)
    def findVersionTestSuiteFiles(self):
        root = "testsuite." + self.app.name + "."
        compulsoryExts = [ self.app.getFullVersion() ]
        # Don't do this for extra versions, they appear anyway...
        ignoreExts = map(lambda extra: extra.getFullVersion(), self.app.extras)
        return self.dircache.findExtensionFiles(root, compulsoryExts, ignoreExts)
    def getContentFileName(self):
        return self.getFileName("testsuite")
    def refreshContents(self):
        # Here we assume that only order can change and suites be removed...
        newList = []
        for testName in self.readTestNamesFromFile(self.getContentFileName()):
            for testcase in self.testcases:
                if testcase.name == testName:
                    newList.append(testcase)
                    break
        self.testcases = newList
    def readChildEnvironment(self, referenceVars):
        for case in self.testcases:
            case.readEnvironment(referenceVars)
    def size(self):
        size = 0
        for testcase in self.testcases:
            size += testcase.size()
        return size
# private:
    def getTestCases(self, filters, testNames, forTestRuns):
        testCaseList = []
        for testName in testNames:
            newTest = self.createTest(testName, filters, forTestRuns)
            if newTest:
                testCaseList.append(newTest)
        return testCaseList
    def createTest(self, testName, filters = [], forTestRuns=0):
        cache = DirectoryCache(os.path.join(self.getDirectory(), testName))
        if cache.findFile(self.app.getVersionExtendedNames("testsuite")):
            return self.createTestSuite(testName, cache, filters, forTestRuns)
        else:
            return self.createTestCase(testName, cache, filters)
    def createTestCase(self, testName, cache, filters):
        newTest = TestCase(testName, cache, self.app, self)
        if newTest.isAcceptedByAll(filters):
            return newTest
    def createTestSuite(self, testName, cache, filters, forTestRuns):
        newSuite = TestSuite(testName, cache, self.app, self)
        if not newSuite.isAcceptedByAll(filters):
            return
            
        if newSuite.readContents(filters, forTestRuns):
            return newSuite
    def writeNewTest(self, testName, description):
        contentFile = self.getContentFileName()
        if not contentFile:
            contentFile = self.dircache.pathName("testsuite." + self.app.name)
        file = open(contentFile, "a")
        file.write("\n")
        file.write("# " + description + "\n")
        file.write(testName + "\n")
        return self.makeSubDirectory(testName)
    def addTest(self, testName):
        test = self.createTest(testName)
        self.testcases.append(test)
        test.readEnvironment()
        self.notifyChanged()
        return test
    def removeTest(self, test):
        self.testcases.remove(test)
        self.notifyChanged()
    
class BadConfigError(RuntimeError):
    pass
        
class ConfigurationWrapper:
    def __init__(self, moduleName, inputOptions):
        self.moduleName = moduleName
        importCommand = "from " + moduleName + " import getConfig"
        try:
            exec importCommand
        except:
            if sys.exc_type == exceptions.ImportError:
                errorString = "No module named " + moduleName
                if str(sys.exc_value) == errorString:
                    self.raiseException(msg = "could not find config_module " + moduleName, useOrigException=0)
                elif str(sys.exc_value) == "cannot import name getConfig":
                    self.raiseException(msg = "module " + moduleName + " is not intended for use as a config_module", useOrigException=0)
            self.raiseException(msg = "config_module " + moduleName + " contained errors and could not be imported") 
        self.target = getConfig(inputOptions)
    def raiseException(self, msg = None, req = None, useOrigException = 1):
        message = msg
        if not msg:
            message = "Exception thrown by '" + self.moduleName + "' configuration, while requesting '" + req + "'"
        if useOrigException:
            plugins.printException()
        raise BadConfigError, message
    def updateOptions(self, optionGroup):
        for key, option in optionGroup.options.items():
            if len(option.getValue()):
                self.target.optionMap[key] = option.getValue()
            elif self.target.optionMap.has_key(key):
                del self.target.optionMap[key]
    def getFilterList(self, app):
        try:
            return self.target.getFilterList(app)
        except:
            self.raiseException(req = "filter list")
    def getCleanMode(self):
        try:
            return self.target.getCleanMode()
        except:
            self.raiseException(req = "clean mode")
    def setApplicationDefaults(self, app):
        try:
            return self.target.setApplicationDefaults(app)
        except:
            self.raiseException(req = "set defaults")
    def getRunIdentifier(self, prefix=""):
        try:
            return self.target.getRunIdentifier(prefix)
        except:
            self.raiseException(req = "run id")
    def getPossibleResultFiles(self, app):
        try:
            return self.target.getPossibleResultFiles(app)
        except:
            self.raiseException(req = "possible result files")
    def useExtraVersions(self):
        try:
            return self.target.useExtraVersions()
        except:
            self.raiseException(req = "extra versions")
    def getRunOptions(self):
        try:
            return self.target.getRunOptions()
        except:
            self.raiseException(req = "run options")
    def addToOptionGroups(self, app, groups):
        try:
            return self.target.addToOptionGroups(app, groups)
        except:
            self.raiseException(req = "add to option group")
    def getActionSequence(self):
        try:
            actionSequenceFromConfig = self.target.getActionSequence()
        except:
            self.raiseException(req = "action sequence")
        actionSequence = []
        # Collapse lists and remove None actions
        for action in actionSequenceFromConfig:
            self.addActionToList(action, actionSequence)
        return actionSequence
    def getResponderClasses(self):
        try:
            return self.target.getResponderClasses()
        except:
            self.raiseException(req = "responder classes")
    def addActionToList(self, action, actionSequence):
        if type(action) == types.ListType:
            for subAction in action:
                self.addActionToList(subAction, actionSequence)
        elif action != None:
            actionSequence.append(action)
            debugLog.info("Adding to action sequence : " + str(action))
    def printHelpText(self):
        try:
            return self.target.printHelpText()
        except:
            self.raiseException(req = "help text")
    def setEnvironment(self, test):
        try:
            self.target.setEnvironment(test)
        except:
            self.raiseException(req = "test set environment")
    def extraReadFiles(self, test):
        try:
            return self.target.extraReadFiles(test)
        except:
            sys.stderr.write("WARNING - ignoring exception thrown by '" + self.moduleName + \
                             "' configuration while requesting extra data files, not displaying any such files")
            plugins.printException()
            return seqdict()
    def getTextualInfo(self, test):
        try:
            return self.target.getTextualInfo(test)
        except:
            self.raiseException(req = "textual info")
    
class Application:
    def __init__(self, name, dircache, version, inputOptions):
        self.name = name
        self.dircache = dircache
        # Place to store reference to extra_version applications
        self.extras = []
        self.versions = version.split(".")
        if self.versions[0] == "":
            self.versions = []
        self.inputOptions = inputOptions
        self.configDir = MultiEntryDictionary()
        self.configDocs = {}
        self.setConfigDefaults()
        configFiles = self.getVersionExtendedNames("config", baseVersion=False)
        self.configDir.readValues(configFiles, self.dircache, insert=0)
        self.fullName = self.getConfigValue("full_name")
        debugLog.info("Found application " + repr(self))
        self.configObject = ConfigurationWrapper(self.getConfigValue("config_module"), inputOptions)
        self.cleanMode = self.configObject.getCleanMode()
        self.writeDirectory = self._getWriteDirectory(inputOptions)
        # Fill in the values we expect from the configurations, and read the file a second time
        self.configObject.setApplicationDefaults(self)
        self.setDependentConfigDefaults()
        configFiles = self.getVersionExtendedNames("config", baseVersion=True)
        self.configDir.readValues(configFiles, self.dircache, insert=0, errorOnUnknown=1)
        personalFile = self.getPersonalConfigFile()
        if personalFile:
            self.configDir.readValuesFromFile(personalFile, insert=0, errorOnUnknown=1)
        self.checkout = self.makeCheckout(inputOptions.checkoutOverride())
        debugLog.info("Checkout set to " + self.checkout)
        self.setCheckoutVariable()
        self.optionGroups = self.createOptionGroups(inputOptions)
        debugLog.info("Config file settings are: " + "\n" + repr(self.configDir.dict))
    def __repr__(self):
        return self.fullName
    def __hash__(self):
        return id(self)
    def getIndent(self):
        # Useful for printing with tests
        return ""
    def classId(self):
        return "test-app"
    def getDirectory(self):
        return self.dircache.dir
    def createCopy(self, version):
        return Application(self.name, self.dircache, version, self.inputOptions)
    def setCheckoutVariable(self):
        os.environ["TEXTTEST_CHECKOUT"] = self.checkout
    def getPreviousWriteDirInfo(self, userName):
        userId = plugins.tmpString
        if userName:
            if globalTmpDirectory == os.path.expanduser("~/texttesttmp"):
                return userName, globalTmpDirectory.replace(userId, userName)
            else:
                # hack for self-tests, don't replace user globally, only locally
                return userName, globalTmpDirectory
        else:
            return userId, globalTmpDirectory
    def getPersonalConfigFile(self):
        personalDir = plugins.getPersonalConfigDir()
        if personalDir:
            personalFile = os.path.join(personalDir, ".texttest")
            if os.path.isfile(personalFile):
                return personalFile
    def setConfigDefaults(self):
        self.setConfigDefault("binary", "", "Full path to the System Under Test")
        self.setConfigDefault("config_module", "default", "Configuration module to use")
        self.setConfigDefault("full_name", string.upper(self.name), "Expanded name to use for application")
        self.setConfigDefault("checkout_location", [], "Absolute paths to look for checkouts under")
        self.setConfigDefault("default_checkout", "", "Default checkout, relative to the checkout location")
        self.setConfigDefault("extra_version", [], "Versions to be run in addition to the one specified")
        self.setConfigDefault("base_version", [], "Versions to inherit settings from")
        self.setConfigDefault("unsaveable_version", [], "Versions which should not have results saved for them")
        self.setConfigDefault("slow_motion_replay_speed", 0, "How long in seconds to wait between each GUI action")
        # External viewing tools
        # Do this here rather than from the GUI: if applications can be run with the GUI
        # anywhere it needs to be set up
        self.setConfigDefault("add_shortcut_bar", 1, "Whether or not TextTest's shortcut bar will appear")
        self.setConfigDefault("test_colours", self.getGuiColourDictionary(), "Colours to use for each test state")
        self.setConfigDefault("file_colours", self.getGuiColourDictionary(), "Colours to use for each file state")
        self.setConfigDefault("auto_collapse_successful", 1, "Automatically collapse successful test suites?")
        self.setConfigDefault("auto_sort_test_suites", 0, "Automatically sort test suites in alphabetical order")
        self.setConfigDefault("window_size", { "" : [] }, "To set the initial size of the dynamic/static GUI.")
        self.setConfigDefault("test_progress", { "" : [] }, "Options for showing/customizing test progress report.")
        self.setConfigDefault("query_kill_processes", { "" : [] }, "Ask about whether to kill these processes when exiting texttest.")
        self.setConfigDefault("definition_file_stems", [ "environment", "testsuite" ], \
                              "files to be shown as definition files by the static GUI")
        self.setConfigDefault("test_list_files_directory", [ "filter_files" ], "Directories to search for test-filter files")
        self.setConfigDefault("gui_entry_overrides", {}, "Default settings for entries in the GUI")
        self.setConfigDefault("gui_entry_options", { "" : [] }, "Default drop-down box options for GUI entries")
        self.setConfigDefault("diff_program", "tkdiff", "External program to use for graphical file comparison")
        viewDoc = "External program to use for viewing and editing text files"
        follDoc = "External program to use for following progress of a file"
        if os.name == "posix":
            self.setConfigDefault("view_program", "xemacs", viewDoc)
            self.setConfigDefault("follow_program", "tail -f", follDoc)
        elif os.name == "dos" or os.name == "nt":
            self.setConfigDefault("view_program", "notepad", viewDoc)
            self.setConfigDefault("follow_program", "baretail", follDoc)
    def getGuiColourDictionary(self):
        dict = {}
        dict["success"] = "green"
        dict["failure"] = "red"
        dict["running"] = "yellow"
        dict["not_started"] = "white"
        dict["static"] = "pale green"
        dict["app_static"] = "purple"
        return dict
    def setDependentConfigDefaults(self):
        binary = self.getConfigValue("binary")
        # Set values which default to other values
        self.setConfigDefault("interactive_action_module", self.getConfigValue("config_module"),
                              "Module to search for InteractiveActions for the GUI")
        interDoc = "Program to use as interpreter for the SUT"
        if binary.endswith(".py"):
            self.setConfigDefault("interpreter", "python", interDoc)
        else:
            self.setConfigDefault("interpreter", "", interDoc)
    def createOptionGroup(self, name):
        defaultDict = self.getConfigValue("gui_entry_overrides")
        optionDict = self.getConfigValue("gui_entry_options")
        return plugins.OptionGroup(name, defaultDict, optionDict)
    def createOptionGroups(self, inputOptions):
        groupNames = [ "Select Tests", "What to run", "How to run", "Side effects", "Invisible" ]
        optionGroups = []
        for name in groupNames:
            group = self.createOptionGroup(name)
            self.addToOptionGroup(group)
            optionGroups.append(group)
        self.configObject.addToOptionGroups(self, optionGroups)
        for option in inputOptions.keys():
            optionGroup = self.findOptionGroup(option, optionGroups)
            if not optionGroup:
                raise BadConfigError, "unrecognised option -" + option
        return optionGroups
    def getRunOptions(self, version=None, checkout=None):
        if not checkout:
            checkout = self.checkout
        if not version:
            version = self.getFullVersion()
        options = "-d " + self.inputOptions.directoryName + " -a " + self.name
        if version:
            options += " -v " + version
        return options + " -c " + checkout + " " + self.configObject.getRunOptions()
    def getPossibleResultFiles(self):
        return self.configObject.getPossibleResultFiles(self)
    def addToOptionGroup(self, group):
        if group.name.startswith("Select"):
            group.addOption("vs", "Tests for version", self.getFullVersion())
            group.addSwitch("current_selection", "Current selection:", options = [ "Discard", "Refine", "Extend", "Exclude"])
        elif group.name.startswith("What"):
            group.addOption("c", "Use checkout", self.checkout)
            group.addOption("v", "Run this version", self.getFullVersion())
        elif group.name.startswith("Side"):
            group.addSwitch("x", "Write TextTest diagnostics")
        elif group.name.startswith("Invisible"):
            # Options that don't make sense with the GUI should be invisible there...
            group.addOption("a", "Run Applications whose name contains")
            group.addOption("s", "Run this script")
            group.addOption("d", "Run as if TEXTTEST_HOME was")
            group.addOption("tmp", "Private: write test-tmp files at")
            group.addSwitch("help", "Print configuration help text on stdout")
    def findOptionGroup(self, option, optionGroups):
        for optionGroup in optionGroups:
            if optionGroup.options.has_key(option) or optionGroup.switches.has_key(option):
                return optionGroup
        return None
    def _getWriteDirectory(self, inputOptions):
        if inputOptions.has_key("tmp"):
            os.environ["TEXTTEST_TMP"] = inputOptions["tmp"]
        if not os.environ.has_key("TEXTTEST_TMP"):
            if os.name == "posix":
                os.environ["TEXTTEST_TMP"] = "~/texttesttmp"
            else:
                os.environ["TEXTTEST_TMP"] = os.environ["TEMP"]
        global globalTmpDirectory
        globalTmpDirectory = os.path.expanduser(os.environ["TEXTTEST_TMP"])
        debugLog.info("Global tmp directory at " + globalTmpDirectory)
        localName = self.getTmpIdentifier().replace(":", "")
        return os.path.join(globalTmpDirectory, localName)
    def getFullVersion(self, forSave = 0):
        versionsToUse = self.versions
        if forSave:
            versionsToUse = self.filterUnsaveable(self.versions)
        return string.join(versionsToUse, ".")
    def versionSuffix(self):
        fullVersion = self.getFullVersion()
        if len(fullVersion) == 0:
            return ""
        return "." + fullVersion
    def createTestSuite(self, filters = None, forTestRuns = True):
        # Reasonable that test-suite creation can depend on checkout...
        self.setCheckoutVariable()
        if not filters:
            filters = self.configObject.getFilterList(self)

        success = 1
        for filter in filters:
            if not filter.acceptsApplication(self):
                success = 0
        suite = TestSuite(os.path.basename(self.dircache.dir), self.dircache, self)
        suite.readContents(filters, forTestRuns)
        if success:
            suite.readEnvironment()
        return success, suite
    def description(self):
        description = "Application " + self.fullName
        if len(self.versions):
            description += ", version " + string.join(self.versions, ".")
        return description
    def filterUnsaveable(self, versions):
        saveableVersions = []
        unsaveableVersions = self.getConfigValue("unsaveable_version")
        for version in versions:
            if not version in unsaveableVersions:
                saveableVersions.append(version)
        return saveableVersions
    def getVersionExtendedNames(self, stem="", baseVersion=True):
        versionsToUse = [ self.name ] + self.versions
        if baseVersion:
            versionsToUse += self.getConfigValue("base_version")
        permutedList = self._getVersionExtensions(versionsToUse)
        if stem:
            names = map(lambda v: stem + "." + v, permutedList)
            names.append(stem)
            return names
        else:
            return permutedList
    def getSaveableVersions(self):
        versionsToUse = self.versions + self.getConfigValue("base_version")
        versionsToUse = self.filterUnsaveable(versionsToUse)
        if len(versionsToUse) == 0:
            return []

        return self._getVersionExtensions(versionsToUse)
    def _getVersionExtensions(self, versions):
        if len(versions) == 1:
            return versions

        fullList = []
        current = versions[0]
        fromRemaining = self._getVersionExtensions(versions[1:])
        for item in fromRemaining:
            fullList.append(current + "." + item)
        fullList.append(current)
        fullList += fromRemaining
        return fullList
    def makeWriteDirectory(self):
        if os.path.isdir(self.writeDirectory):
            return
        root, tmpId = os.path.split(self.writeDirectory)
        self.tryCleanPreviousWriteDirs(root)
        plugins.ensureDirectoryExists(self.writeDirectory)
        debugLog.info("Made root directory at " + self.writeDirectory)
    def removeWriteDirectory(self):
        doRemove = self.cleanMode & plugins.Configuration.CLEAN_SELF
        if doRemove and os.path.isdir(self.writeDirectory):
            plugins.rmtree(self.writeDirectory)
    def tryCleanPreviousWriteDirs(self, rootDir, nameBase = ""):
        doRemove = self.cleanMode & plugins.Configuration.CLEAN_PREVIOUS
        if not doRemove or not os.path.isdir(rootDir):
            return
        currTmpString = nameBase + self.name + self.versionSuffix() + plugins.tmpString
        for file in os.listdir(rootDir):
            fpath = os.path.join(rootDir, file)
            if not os.path.isdir(fpath):
                continue
            if file.startswith(currTmpString):
                previousWriteDir = os.path.join(rootDir, file)
                print "Removing previous write directory", previousWriteDir
                plugins.rmtree(previousWriteDir, attempts=3)
    def getTmpIdentifier(self):
        return self.configObject.getRunIdentifier(self.name + self.versionSuffix())
    def ownsFile(self, fileName, unknown = 1):
        # Environment file may or may not be owned. Return whatever we're told to return for unknown
        if fileName == "environment":
            return unknown
        parts = fileName.split(".")
        if len(parts) == 1 or len(parts[0]) == 0:
            return 0
        ext = parts[1]
        if ext == self.name:
            return 1
        elif parts[0] == "environment":
            return unknown
        return 0    
    def getActionSequence(self):
        return self.configObject.getActionSequence()
    def printHelpText(self):
        print helpIntro
        header = "Description of the " + self.getConfigValue("config_module") + " configuration"
        length = len(header)
        header += "\n"
        for x in range(length):
            header += "-"
        print header
        self.configObject.printHelpText()
    def getConfigValue(self, key, expandVars=True):
        value = self.configDir[key]
        if not expandVars:
            return value
        if type(value) == types.StringType:
            return os.path.expandvars(value)
        elif type(value) == types.ListType:
            return map(os.path.expandvars, value)
        elif type(value) == types.DictType:
            newDict = {}
            for key, val in value.items():
                if type(val) == types.StringType:
                    newDict[key] = os.path.expandvars(val)
                elif type(val) == types.ListType:
                    newDict[key] = map(os.path.expandvars, val)
                else:
                    newDict[key] = val
            return newDict
        else:
            return value
    def getCompositeConfigValue(self, key, subKey):
        dict = self.getConfigValue(key)
        if dict.has_key(subKey):
            retVal = dict[subKey]
            if type(retVal) == types.ListType:
                return retVal + dict["default"]
            else:
                return retVal
        elif dict.has_key("default"):
            return dict["default"]
    def addConfigEntry(self, key, value, sectionName = ""):
        self.configDir.addEntry(key, value, sectionName)
    def setConfigDefault(self, key, value, docString = ""):
        self.configDir[key] = value
        if len(docString) > 0:
            self.configDocs[key] = docString
    def makeCheckout(self, checkoutOverride):
        checkout = checkoutOverride
        if not checkoutOverride:
            checkout = self.getConfigValue("default_checkout")
        if os.path.isabs(checkout):
            return checkout
        checkoutLocations = self.getConfigValue("checkout_location")
        if len(checkoutLocations) > 0:
            return self.makeAbsoluteCheckout(checkoutLocations, checkout)
        else:
            # Assume relative checkouts are relative to the root directory...
            return self.dircache.pathName(checkout)
    def makeAbsoluteCheckout(self, locations, checkout):
        for location in locations:
            fullCheckout = self.absCheckout(location, checkout)
            if os.path.isdir(fullCheckout):
                return fullCheckout
        return self.absCheckout(locations[0], checkout)
    def absCheckout(self, location, checkout):
        return os.path.join(os.path.expanduser(location), checkout)
    def checkBinaryExists(self):
        binary = self.getConfigValue("binary")
        if not binary:
            raise plugins.TextTestError, "config file entry 'binary' not defined"
        if not os.path.isfile(binary):
            raise plugins.TextTestError, binary + " has not been built."
            
class OptionFinder(plugins.OptionFinder):
    def __init__(self):
        plugins.OptionFinder.__init__(self, sys.argv[1:])
        self.directoryName = os.path.normpath(self.findDirectoryName())
        os.environ["TEXTTEST_HOME"] = self.directoryName
        self._setUpLogging()
        debugLog.debug(repr(self))
    def _setUpLogging(self):
        global debugLog
        # Don't use the default locations, particularly current directory causes trouble
        del log4py.CONFIGURATION_FILES[1]
        if self.has_key("x") or os.environ.has_key("TEXTTEST_DIAGNOSTICS"):
            diagFile = self._getDiagnosticFile()
            if os.path.isfile(diagFile):
                if not os.environ.has_key("TEXTTEST_DIAGDIR"):
                    os.environ["TEXTTEST_DIAGDIR"] = os.path.dirname(diagFile)
                writeDir = os.getenv("TEXTTEST_DIAGDIR")
                plugins.ensureDirectoryExists(writeDir)
                print "TextTest will write diagnostics in", writeDir, "based on file at", diagFile
                for file in os.listdir(writeDir):
                    if file.endswith(".diag"):
                        os.remove(os.path.join(writeDir, file))
                # To set new config files appears to require a constructor...
                rootLogger = log4py.Logger(log4py.TRUE, diagFile)
            else:
                print "Could not find diagnostic file at", diagFile, ": cannot run with diagnostics"
                self._disableDiags()
        else:
            self._disableDiags()
        # Module level debugging logger
        global debugLog, directoryLog
        debugLog = plugins.getDiagnostics("texttest")
        directoryLog = plugins.getDiagnostics("directories")
        debugLog.info("Replaying from " + repr(os.getenv("USECASE_REPLAY_SCRIPT")))
    def _disableDiags(self):
        rootLogger = log4py.Logger().get_root()        
        rootLogger.set_loglevel(log4py.LOGLEVEL_NONE)
    def findVersionList(self):
        if self.has_key("v"):
            return plugins.commasplit(self["v"])
        else:
            return [""]
    def findSelectedAppNames(self):
        if not self.has_key("a"):
            return {}

        apps = plugins.commasplit(self["a"])
        appDict = {}
        versionList = self.findVersionList()
        for app in apps:
            if "." in app:
                appName, versionName = app.split(".", 1)
                self.addToAppDict(appDict, appName, versionName)
            else:
                for version in versionList:
                    self.addToAppDict(appDict, app, version)
        return appDict
    def addToAppDict(self, appDict, appName, versionName):
        if appDict.has_key(appName):
            appDict[appName].append(versionName)
        else:
            appDict[appName] = [ versionName ]
    def checkoutOverride(self):
        if self.has_key("c"):
            return self["c"]
        else:
            return ""
    def helpMode(self):
        return self.has_key("help")
    def runScript(self):
        return self.has_key("s")
    def _getDiagnosticFile(self):
        if not os.environ.has_key("TEXTTEST_DIAGNOSTICS"):
            os.environ["TEXTTEST_DIAGNOSTICS"] = os.path.join(self.directoryName, "Diagnostics")
        return os.path.join(os.environ["TEXTTEST_DIAGNOSTICS"], "log4py.conf")
    def findDirectoryName(self):
        if self.has_key("d"):
            return plugins.abspath(self["d"])
        elif os.environ.has_key("TEXTTEST_HOME"):
            return os.environ["TEXTTEST_HOME"]
        else:
            return os.getcwd()
    def getActionSequence(self, app):        
        if not self.runScript():
            return app.getActionSequence()
            
        actionCom = self["s"].split(" ")[0]
        actionArgs = self["s"].split(" ")[1:]
        actionOption = actionCom.split(".")
        if len(actionOption) != 2:
            return self.getNonPython()
                
        module, pclass = actionOption
        importCommand = "from " + module + " import " + pclass + " as _pclass"
        try:
            exec importCommand
        except:
            if os.path.isfile(self["s"]):
                return self.getNonPython()
            else:
                sys.stderr.write("Import failed, looked at " + repr(sys.path) + "\n")
                plugins.printException()
                raise BadConfigError, "Could not import script " + pclass + " from module " + module

        # Assume if we succeed in importing then a python module is intended.
        try:
            if len(actionArgs) > 0:
                return [ _pclass(actionArgs) ]
            else:
                return [ _pclass() ]
        except:
            plugins.printException()
            raise BadConfigError, "Could not instantiate script action " + repr(actionCom) + " with arguments " + repr(actionArgs) 
    def getNonPython(self):
        return [ plugins.NonPythonAction(self["s"]) ]

# Compulsory responder to generate application events. Always present. See respond module
class ApplicationEventResponder(Responder):
    def notifyLifecycleChange(self, test, changeDesc):
        eventName = "test " + test.uniqueName + " to " + changeDesc
        category = test.uniqueName
        self.scriptEngine.applicationEvent(eventName, category, timeDelay=1)
            
class MultiEntryDictionary(seqdict):
    def __init__(self):
        seqdict.__init__(self)
        self.currDict = self
    def readValues(self, fileNames, dircache, insert=True, errorOnUnknown=False):
        self.currDict = self
        for filename in dircache.findAllFiles(fileNames):
            self.readValuesFromFile(filename, insert, errorOnUnknown)
    def readValuesFromFile(self, filename, insert=True, errorOnUnknown=False):
        debugLog.info("Reading values from file " + os.path.basename(filename))
        for line in plugins.readList(filename):
            self.parseConfigLine(line, insert, errorOnUnknown)
        self.currDict = self
    def parseConfigLine(self, line, insert, errorOnUnknown):
        if line.startswith("[") and line.endswith("]"):
            self.currDict = self.changeSectionMarker(line[1:-1], errorOnUnknown)
        elif line.find(":") != -1:
            self.addLine(line, insert, errorOnUnknown)
        else:
            print "WARNING : could not parse config line", line
    def changeSectionMarker(self, name, errorOnUnknown):
        if name == "end":
            return self
        if self.has_key(name) and type(self[name]) == types.DictType:
            return self[name]
        if errorOnUnknown:
            print "ERROR : config section name '" + name + "' not recognised."
        return self
    def addLine(self, line, insert, errorOnUnknown, separator = ':'):
        entryName, entry = line.split(separator, 1)
        self.addEntry(entryName, entry, "", insert, errorOnUnknown)
    def addEntry(self, entryName, entry, sectionName="", insert=0, errorOnUnknown=1):
        if sectionName:
            self.currDict = self[sectionName]
        entryExists = self.currDict.has_key(entryName)
        if entryExists:
            self.insertEntry(entryName, entry)
        else:
            if insert or not self.currDict is self:
                dictValType = self.getDictionaryValueType()
                if dictValType == types.ListType:
                    self.currDict[entryName] = [ entry ]
                elif dictValType == types.IntType:
                    self.currDict[entryName] = int(entry)
                else:
                    self.currDict[entryName] = entry
            elif errorOnUnknown:
                print "ERROR : config entry name '" + entryName + "' not recognised"
        # Make sure we reset...
        if sectionName:
            self.currDict = self
    def getDictionaryValueType(self):
        val = self.currDict.values()
        if len(val) == 0:
            return types.StringType
        else:
            return type(val[0])
    def insertEntry(self, entryName, entry):
        currType = type(self.currDict[entryName]) 
        if currType == types.ListType:
            if entry == "{CLEAR LIST}":
                self.currDict[entryName] = []
            elif not entry in self.currDict[entryName]:
                self.currDict[entryName].append(entry)
        elif currType == types.IntType:
            self.currDict[entryName] = int(entry)
        elif currType == types.DictType:
            self.currDict = self.currDict[entryName]
            self.insertEntry("default", entry)
            self.currDict = self
        else:
            self.currDict[entryName] = entry        
