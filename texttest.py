#!/usr/bin/env python
import os, sys, types, string, getopt, types, time, plugins, exceptions, stat, log4py, shutil
from stat import *
from usecase import ScriptEngine, UseCaseScriptError
from ndict import seqdict

helpIntro = """
Note: the purpose of this help is primarily to document the configuration you currently have,
though also to provide a full list of options supported by both your framework and your configuration.
A user guide (UserGuide.html) is available to document the framework itself.
"""

builtInOptions = """
-a <app>   - run only the application with extension <app>

-v <vers>  - use <vers> as the version name(s). Versions separated by "." characters will be aggregated.
             Versions separated by "," characters will be run one after another. See the User Guide for
             a fuller explanation of what a "version" means.

-c <chkt>  - use <chkt> as the checkout instead of the "default_checkout" entry (see User Guide)

-d <root>  - use <root> as the root directory instead of the value of TEXTTEST_HOME,
             or the current working directory, which are used otherwise.

-g         - run with GUI instead of text interface. Will only work if PyGTK is installed.

-gx        - run static GUI, which won't run tests unless instructed. Useful for creating new tests
             and viewing the test suite.
             
-record <s>- use PyUseCase to record all user actions in the GUI to the script <s>

-replay <s>- use PyUseCase to replay the script <s> created previously in the GUI. No effect without -g.

-recinp <s>- use PyUseCase to record everything received on standard input to the script <s> 

-s <scrpt> - instead of the normal actions performed by the configuration, use the script <scpt>. If this contains
             a ".", an attempt will be made to understand it as the Python class <module>.<classname>. If this fails,
             it will be interpreted as an external script.

-keeptmp   - Keep any temporary directories where test(s) write files. Note that once you run the test again the old
             temporary dirs will be removed.       

-help      - Do not run anything. Instead, generate useful text, such as this.

-x         - Enable log4py diagnostics for the framework. This will use a diagnostic directory from the environment
             variable TEXTTEST_DIAGNOSTICS, if defined, or the directory <root>/Diagnostics/ if not. It will read
             the log4py configuration file present in that directory and write all diagnostic files there as well.
             More details can be had from the log4py documentation.
"""

# Base class for TestCase and TestSuite
class Test:
    # Used by the static GUI to say that a test's definition has changed and it needs to re-read its files
    UPDATED = -3
    #State names. By default, the negative states are not used. We start in state NOT_STARTED
    NEED_PREPROCESS = -2
    RUNNING_PREPROCESS = -1
    NOT_STARTED = 0
    RUNNING = 1
    KILLED = 2
    SUCCEEDED = 3
    FAILED = 4
    UNRUNNABLE = 5
    def __init__(self, name, abspath, app, parent = None):
        self.name = name
        # There is nothing to stop several tests having the same name. Maintain another name known to be unique
        self.uniqueName = name
        self.app = app
        self.parent = parent
        self.abspath = abspath
        self.valid = os.path.isdir(abspath)
        self.paddedName = self.name
        self.state = self.NOT_STARTED 
        self.stateDetails = None
        self.previousEnv = {}
        # List of objects observing this test, to be notified when it changes state
        self.observers = []
        self.environment = MultiEntryDictionary()
        if parent == None:
            for var, value in app.getEnvironment():
                self.environment[var] = value
        diagDict = self.getConfigValue("diagnostics")
        if diagDict.has_key("input_directory_variable"):
            diagConfigFile = os.path.join(self.abspath, diagDict["configuration_file"])
            if os.path.isfile(diagConfigFile):
                inVarName = diagDict["input_directory_variable"]
                self.environment[inVarName] = self.abspath
        self.environment.readValuesFromFile(os.path.join(self.abspath, "environment"), app.name, app.getVersionFileExtensions())
        # Single pass to expand all variables (don't want multiple expansion)
        for var, value in self.environment.items():
            expValue = os.path.expandvars(value)
            # If it constaints a separator, try to make it into an absolute path by pre-pending the checkout
            self.environment[var] = expValue
            debugLog.info("Expanded variable " + var + " to " + expValue + " in " + self.name)
            if os.environ.has_key(var):
                self.previousEnv[var] = os.environ[var]
            os.environ[var] = self.environment[var]
    def makeFileName(self, stem, refVersion = None, temporary = 0, forComparison = 1):
        root = self.getDirectory(temporary, forComparison)
        if not forComparison:
            return os.path.join(root, stem)
        if stem.find(".") == -1: 
            stem += "." + self.app.name
        nonVersionName = os.path.join(root, stem)
        versions = self.app.getVersionFileExtensions()
        debugLog.info("Versions available : " + repr(versions))
        if refVersion != None:
            versions = [ refVersion ]
        if len(versions) == 0:
            return nonVersionName
        
        # Prioritise finding earlier versions
        testNonVersion = os.path.join(self.abspath, stem)
        for version in versions:
            versionName = testNonVersion + "." + version
            if os.path.isfile(versionName):
                debugLog.info("Chosen " + versionName)
                return nonVersionName + "." + version
        return nonVersionName
    def getConfigValue(self, key):
        return self.app.getConfigValue(key)
    def makePathName(self, fileName, startDir):
        fullPath = os.path.join(startDir, fileName)
        if os.path.exists(fullPath) or startDir == self.app.abspath:
            return fullPath
        parent, current = os.path.split(startDir)
        return self.makePathName(fileName, parent)
    def extraReadFiles(self):
        return self.app.configObject.extraReadFiles(self)
    def notifyChanged(self):
        for observer in self.observers:
            observer.notifyChange(self)
    def getRelPath(self):
        relPath = self.abspath.replace(self.app.abspath, "")
        if relPath.startswith(os.sep):
            return relPath[1:]
        return relPath
    def getDirectory(self, temporary, forComparison = 1):
        return self.abspath
    def setUpEnvironment(self, parents=0):
        if parents and self.parent:
            self.parent.setUpEnvironment(1)
        for var, value in self.environment.items():
            if os.environ.has_key(var):
                self.previousEnv[var] = os.environ[var]
            os.environ[var] = value
            debugLog.debug("Setting " + var + " to " + os.environ[var])
    def tearDownEnvironment(self, parents=0):
        # Note this has no effect on the real environment, but can be useful for internal environment
        # variables. It would be really nice if Python had a proper "unsetenv" function...
        debugLog.debug("Restoring environment for " + self.name + " to " + repr(self.previousEnv))
        for var in self.environment.keys():
            if os.environ.has_key(var):
                if self.previousEnv.has_key(var):
                    os.environ[var] = self.previousEnv[var]
                else:
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
        dirCount = string.count(relPath, os.sep) + 1
        retstring = ""
        for i in range(dirCount):
            retstring = retstring + "  "
        return retstring
    def isAcceptedByAll(self, filters):
        for filter in filters:
            debugLog.debug(repr(self) + " filter " + repr(filter))
            if not self.isAcceptedBy(filter):
                debugLog.debug("REJECTED")
                return 0
        return 1
    def size(self):
        return 1

class TestCase(Test):
    def __init__(self, name, abspath, app, parent):
        Test.__init__(self, name, abspath, app, parent)
        self.inputFile = self.makeFileName("input")
        self.useCaseFile = self.makeFileName("usecase")
        self._setOptions()
        # List of directories where this test will write files. First is where it executes from
        self.writeDirs = []
        basicWriteDir = os.path.join(app.writeDirectory, self.getRelPath())
        self.writeDirs.append(basicWriteDir)
        diagDict = self.app.getConfigValue("diagnostics")
        if self.app.useDiagnostics:
            inVarName = diagDict["input_directory_variable"]
            self.environment[inVarName] = os.path.join(self.abspath, "Diagnostics")
            outVarName = diagDict["write_directory_variable"]
            self.environment[outVarName] = os.path.join(basicWriteDir, "Diagnostics")
        elif diagDict.has_key("write_directory_variable"):
            outVarName = diagDict["write_directory_variable"]
            self.environment[outVarName] = basicWriteDir
    def __repr__(self):
        return repr(self.app) + " " + self.classId() + " " + self.paddedName
    def classId(self):
        return "test-case"
    def testCaseList(self):
        return [ self ]
    def _setOptions(self):
        optionsFile = self.makeFileName("options")
        self.options = ""
        if (os.path.isfile(optionsFile)):
            self.options = os.path.expandvars(open(optionsFile).readline().strip())
        elif not os.path.isfile(self.inputFile) and not os.path.isfile(self.useCaseFile):
            self.valid = 0
    def getDirectory(self, temporary, forComparison = 1):
        if temporary:
            if forComparison:
                return self.writeDirs[0]
            else:
                return os.path.join(self.writeDirs[0], "framework_tmp")
        else:
            return self.abspath
    def callAction(self, action):
        if os.path.isdir(self.writeDirs[0]):
            os.chdir(self.writeDirs[0])
        return action(self)
    def waitingForProcess(self):
        return isinstance(self.stateDetails, plugins.BackgroundProcess)
    def filesChanged(self):
        self._setOptions()
        self.notifyChanged()
    def changeState(self, state, details = ""):
        # Once we've left the pathway, we can't return...
        if self.state == self.UNRUNNABLE or self.state == self.KILLED:
            return
        oldState = self.state
        self.state = state
        self.stateDetails = details
        if state != oldState or self.waitingForProcess():
            self.notifyChanged()
            # Tests changing state are reckoned to be significant enough to wait for...
            try:
                self.stateChangeEvent(state, oldState)
            except UseCaseScriptError:
                # This will be raised if we're in a subthread, i.e. if the GUI is running
                # Rely on the GUI to report the same event
                pass
    def stateChangeEvent(self, state, oldState = None):
        if state == self.UPDATED or (oldState and oldState == self.FAILED):
            # Don't record event if we're being 'saved' or whatever
            return
        eventName = "test " + self.uniqueName + " to " + self.stateChangeDescription(state)
        category = self.uniqueName
        # Files abound here, we wait a little for them to clear up
        ScriptEngine.instance.applicationEvent(eventName, category, timeDelay=1)
    def stateChangeDescription(self, state):
        if state == self.RUNNING:
            return "start"
        if state == self.FAILED or state == self.UNRUNNABLE or state == self.SUCCEEDED:
            return "complete"
        if state == self.RUNNING_PREPROCESS:
            return "start preprocessing"
        return "finish preprocessing"
    def getExecuteCommand(self):
        return self.app.getExecuteCommand(self)
    def getTmpExtension(self):
        return globalRunIdentifier
    def isOutdated(self, filename):
        modTime = os.stat(filename)[stat.ST_MTIME]
        currTime = time.time()
        threeDaysInSeconds = 60 * 60 * 24 * 3
        return currTime - modTime > threeDaysInSeconds
    def isAcceptedBy(self, filter):
        return filter.acceptsTestCase(self)
    def makeBasicWriteDirectory(self):
        fullPathToMake = os.path.join(self.writeDirs[0], "framework_tmp")
        os.makedirs(fullPathToMake)
        if self.app.useDiagnostics:
            os.mkdir(os.path.join(self.writeDirs[0], "Diagnostics"))
        self.collatePaths("copy_test_path", self.copyTestPath)
        self.collatePaths("link_test_path", self.linkTestPath)
    def cleanNonBasicWriteDirectories(self):
        if len(self.writeDirs) > 0:
            for writeDir in self.writeDirs[1:]:
                self._removeDir(writeDir)
    def _removeDir(self, writeDir):
        parent, local = os.path.split(writeDir)
        if local.find(self.app.getTmpIdentifier()) != -1:
            debugLog.info("Removing write directory under", parent)
            plugins.rmtree(writeDir)
        elif parent:
            self._removeDir(parent)
    def collatePaths(self, configListName, collateMethod):
        for copyTestPath in self.app.getConfigValue(configListName):
            fullPath = self.makePathName(copyTestPath, self.abspath)
            target = os.path.join(self.writeDirs[0], copyTestPath)
            dir, localName = os.path.split(target)
            if not os.path.isdir(dir):
                os.makedirs(dir)
            collateMethod(fullPath, target)
    def copyTestPath(self, fullPath, target):
        if os.path.isfile(fullPath):
            shutil.copy(fullPath, target)
        if os.path.isdir(fullPath):
            shutil.copytree(fullPath, target)
            if os.name == "posix":
                # Cannot get os.chmod to work recursively, or worked out the octal digits..."
                # In any case, it's important that it's writeable
                os.system("chmod -R +w " + target)
    def linkTestPath(self, fullPath, target):
        # Linking doesn't exist on windows!
        if os.name != "posix":
            return self.copyTestPath(fullPath, target)
        if os.path.exists(fullPath):
            os.symlink(fullPath, target)
    def createDir(self, rootDir, nameBase = "", subDir = None):
        writeDir = os.path.join(rootDir, nameBase + self.app.getTmpIdentifier())
        fullWriteDir = writeDir
        if subDir:
            fullWriteDir = os.path.join(writeDir, subDir)
        try:
            self.createDirs(fullWriteDir)
        except OSError:
            # If started twice at the same time this can happen...
            return self.createDir(rootDir, nameBase + "?", subDir)
        return writeDir
    def createDirs(self, fullWriteDir):
        os.makedirs(fullWriteDir)    
        debugLog.info("Created write directory " + fullWriteDir)
        self.writeDirs.append(fullWriteDir)
        return fullWriteDir
    def makeWriteDirectory(self, rootDir, basicDir, subDir = None):
        nameBase = basicDir + "."
        self.app.tryCleanPreviousWriteDirs(rootDir, nameBase)
        writeDir = self.createDir(rootDir, nameBase, subDir)
        newBasic = os.path.basename(writeDir)
        debugLog.info("Replacing " + basicDir + " with " + newBasic)
        self.options = self.options.replace(basicDir, newBasic)
        debugLog.info("Options string now '" + self.options + "'") 
        if os.path.isfile(self.inputFile):
            tmpFileName = self.makeFileName("input", temporary=1)
            tmpFile = open(tmpFileName, "w")
            for line in open(self.inputFile).xreadlines():
                tmpFile.write(line.replace(basicDir, newBasic))
            self.inputFile = tmpFileName
            debugLog.info("Input file now '" + self.inputFile + "'")
        return writeDir
            
class TestSuite(Test):
    def __init__(self, name, abspath, app, filters, parent=None):
        Test.__init__(self, name, abspath, app, parent)
        self.testCaseFile = self.makeFileName("testsuite")
        if not os.path.isfile(self.testCaseFile):
            self.valid = 0
        debugLog.info("Reading test suite file " + self.testCaseFile)
        self.testcases = self.getTestCases(filters)
        if len(self.testcases):
            maxNameLength = max([len(test.name) for test in self.testcases])
            for test in self.testcases:
                test.paddedName = string.ljust(test.name, maxNameLength)
        self.tearDownEnvironment()
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
    def filesChanged(self):
        # Here we assume that only order can change and suites be removed...
        newList = []
        for testline in open(self.testCaseFile).xreadlines():
            testName = testline.strip()
            if len(testName) == 0  or testName[0] == '#':
                continue
            for testcase in self.testcases:
                if testcase.name == testName:
                    newList.append(testcase)
                    break
        self.testcases = newList
        self.notifyChanged()
    def reFilter(self, filters):
        testCaseList = []
        debugLog.debug("Refilter for " + self.name)
        for test in self.testcases:
            debugLog.debug("Refilter check of " + test.name + " for " + self.name)
            if test.size() == 0:
                continue
            if test.classId() == self.classId():
                test.reFilter(filters)
                if test.size() > 0:
                    testCaseList.append(test)
            elif test.isAcceptedByAll(filters):
                debugLog.debug("Refilter ok of " + test.name + " for " + self.name)
                testCaseList.append(test)
            else:
                debugLog.debug("Refilter loose " + test.name + " for " + self.name)
        self.testcases = testCaseList
    def size(self):
        size = 0
        for testcase in self.testcases:
            size += testcase.size()
        return size
# private:
    def getTestCases(self, filters):
        testCaseList = []
        if not self.isAcceptedByAll(filters):
            self.valid = 0
            
        if not self.valid:
            return testCaseList

        allowEmpty = 1
        for testline in open(self.testCaseFile).xreadlines():
            testName = testline.strip()
            if len(testName) == 0  or testName[0] == '#':
                continue
            if self.alreadyContains(testCaseList, testName):
                print "WARNING: the test", testName, "was included several times in the test suite file - please check!"
                continue

            allowEmpty = 0
            testPath = os.path.join(self.abspath, testName)
            testSuite = TestSuite(testName, testPath, self.app, filters, self)
            if testSuite.valid:
                testCaseList.append(testSuite)
            else:
                testCase = TestCase(testName, testPath, self.app, self)
                if testCase.valid and testCase.isAcceptedByAll(filters):
                    testCaseList.append(testCase)
                testCase.tearDownEnvironment()
        if not allowEmpty and len(testCaseList) == 0:
            self.valid = 0
        return testCaseList
    def addTest(self, testName, testPath):
        testCase = TestCase(testName, testPath, self.app, self)
        if testCase.valid:
            return self.newTest(testCase)
        else:
            testSuite = TestSuite(testName, testPath, self.app, [], self)
            if testSuite.valid:
                return self.newTest(testSuite)
    def newTest(self, test):
        self.testcases.append(test)
        self.notifyChanged()
        return test
    def alreadyContains(self, testCaseList, testName):
        for test in testCaseList:
            if test.name == testName:
                return 1
        return 0

class BadConfigError(RuntimeError):
    pass
        
class ConfigurationWrapper:
    def __init__(self, moduleName, optionMap):
        self.moduleName = moduleName
        importCommand = "from " + moduleName + " import getConfig"
        try:
            exec importCommand
        except:
            errorString = "No module named " + moduleName
            if sys.exc_type == exceptions.ImportError and str(sys.exc_value) == errorString:
                self.raiseException(msg = "could not find config_module " + moduleName, useOrigException=0)
            else:
                self.raiseException(msg = "config_module " + moduleName + " contained errors and could not be imported") 
        self.target = getConfig(optionMap)
    def raiseException(self, msg = None, req = None, useOrigException = 1):
        message = msg
        if not msg:
            message = "Exception thrown by '" + self.moduleName + "' configuration, while requesting '" + req + "'"
        if useOrigException:
            printException()
        raise BadConfigError, message
    def updateOptions(self, optionGroup):
        for key, option in optionGroup.options.items():
            if len(option.getValue()):
                self.target.optionMap[key] = option.getValue()
            elif self.target.optionMap.has_key(key):
                del self.target.optionMap[key]
    def getFilterList(self):
        try:
            return self.target.getFilterList()
        except:
            self.raiseException(req = "filter list")
    def keepTmpFiles(self):
        try:
            return self.target.keepTmpFiles()
        except:
            self.raiseException(req = "keep tmpfiles")
    def setApplicationDefaults(self, app):
        try:
            return self.target.setApplicationDefaults(app)
        except:
            self.raiseException(req = "set defaults")
    def addToOptionGroup(self, group):
        try:
            return self.target.addToOptionGroup(group)
        except:
            self.raiseException(req = "add to option group")
    def getActionSequence(self, useGui):
        try:
            actionSequenceFromConfig = self.target.getActionSequence(useGui)
        except:
            self.raiseException(req = "action sequence")
        actionSequence = []
        # Collapse lists and remove None actions
        for action in actionSequenceFromConfig:
            self.addActionToList(action, actionSequence)
        return actionSequence
    def addActionToList(self, action, actionSequence):
        if type(action) == types.ListType:
            for subAction in action:
                self.addActionToList(subAction, actionSequence)
        elif action != None:
            actionSequence.append(action)
            debugLog.info("Adding to action sequence : " + str(action))
    def printHelpText(self, builtInOptions):
        try:
            return self.target.printHelpText(builtInOptions)
        except:
            self.raiseException(req = "help text")
    def getApplicationEnvironment(self, app):
        try:
            return self.target.getApplicationEnvironment(app)
        except:
            self.raiseException(req = "application environment")
    def extraReadFiles(self, test):
        try:
            return self.target.extraReadFiles(test)
        except:
            self.raiseException(req = "extra read files")
    def getExecuteCommand(self, test, binary):
        try:
            return self.target.getExecuteCommand(test, binary)
        except:
            self.raiseException(req = "execute command")

class Application:
    def __init__(self, name, abspath, configFile, version, optionMap):
        self.name = name
        self.abspath = abspath
        # Place to store reference to extra_version application
        self.extra = None
        self.versions = version.split(".")
        if self.versions[0] == "":
            self.versions = []
        self.configDir = MultiEntryDictionary()
        self.setConfigDefaults()
        extensions = self.getVersionFileExtensions(baseVersion=0)
        self.configDir.readValuesFromFile(configFile, name, extensions, insert=0)
        self.fullName = self.getConfigValue("full_name")
        debugLog.info("Found application " + repr(self))
        self.configObject = ConfigurationWrapper(self.getConfigValue("config_module"), optionMap)
        self.keepTmpFiles = (optionMap.has_key("keeptmp") or self.configObject.keepTmpFiles() or self.getConfigValue("keeptmp_default"))
        self.writeDirectory = self._getWriteDirectory(optionMap.has_key("gx"))
        # Fill in the values we expect from the configurations, and read the file a second time
        self.configObject.setApplicationDefaults(self)
        self.setDependentConfigDefaults()
        self.configDir.readValuesFromFile(configFile, name, extensions, insert=0, errorOnUnknown=1)
        personalFile = self.getPersonalConfigFile()
        self.configDir.readValuesFromFile(personalFile, insert=0, errorOnUnknown=1)
        self.checkout = self.makeCheckout(optionMap)
        debugLog.info("Checkout set to " + self.checkout)
        self.optionGroups = self.createOptionGroups(optionMap)
        self.useDiagnostics = self.setDiagnosticSettings(optionMap)
    def __repr__(self):
        return self.fullName
    def __cmp__(self, other):
        return cmp(self.name, other.name)
    def getIndent(self):
        # Useful for printing with tests
        return ""
    def classId(self):
        return "test-app"
    def getPersonalConfigFile(self):
        if os.environ.has_key("TEXTTEST_PERSONAL_CONFIG"):
            return os.path.join(os.environ["TEXTTEST_PERSONAL_CONFIG"], ".texttest")
        elif os.name == "posix":
            return os.path.join(os.environ["HOME"], ".texttest")
        else:
            return os.path.join(self.abspath, ".texttest")
    def setConfigDefaults(self):
        self.setConfigDefault("binary", None)
        self.setConfigDefault("config_module", "default")
        self.setConfigDefault("full_name", string.upper(self.name))
        self.setConfigDefault("checkout_location", ".")
        self.setConfigDefault("default_checkout", "")
        self.setConfigDefault("keeptmp_default", 0)
        self.setConfigDefault("extra_version", "none")
        self.setConfigDefault("base_version", [])
        self.setConfigDefault("unsaveable_version", [])
        self.setConfigDefault("diagnostics", {})
        self.setConfigDefault("copy_test_path", [])
        self.setConfigDefault("link_test_path", [])
        # External viewing tools
        # Do this here rather than from the GUI: if applications can be run with the GUI
        # anywhere it needs to be set up
        self.setConfigDefault("add_shortcut_bar", 1)
        self.setConfigDefault("test_colours", self.getGuiColourDictionary())
        self.setConfigDefault("file_colours", self.getGuiColourDictionary())
        self.setConfigDefault("gui_entry_overrides", {})
        if os.name == "posix":
            self.setConfigDefault("view_program", "xemacs")
            self.setConfigDefault("follow_program", "tail -f")
            self.setConfigDefault("diff_program", "tkdiff")
        elif os.name == "dos" or os.name == "nt":
            self.setConfigDefault("view_program", "wordpad.exe")
            self.setConfigDefault("follow_program", None)
            self.setConfigDefault("diff_program", "tkdiff.tcl")
    def getGuiColourDictionary(self):
        dict = {}
        dict["run_preprocess"] = "peach puff"
        dict["success"] = "green"
        dict["failure"] = "red"
        dict["running"] = "yellow"
        dict["not_started"] = "white"
        dict["static"] = "pale green"
        dict["app_static"] = "purple"
        return dict
    def setDependentConfigDefaults(self):
        binary = self.getConfigValue("binary")
        if not binary:
            raise BadConfigError, "config file entry 'binary' not defined"
        # Set values which default to other values
        self.setConfigDefault("interactive_action_module", self.getConfigValue("config_module"))
        if binary.endswith(".py"):
            self.setConfigDefault("interpreter", "python")
        else:
            self.setConfigDefault("interpreter", "")
    def createOptionGroups(self, optionMap):
        defaultDict = self.getConfigValue("gui_entry_overrides")
        groupNames = [ "Select Tests", "What to run", "How to run", "Side effects", "Invisible" ]
        optionGroups = []
        for name in groupNames:
            group = plugins.OptionGroup(name, defaultDict)
            self.addToOptionGroup(group)
            self.configObject.addToOptionGroup(group)
            optionGroups.append(group)
        for option in optionMap.keys():
            optionGroup = self.findOptionGroup(option, optionGroups)
            if not optionGroup:
                raise BadConfigError, "unrecognised option -" + option
        return optionGroups
    def setDiagnosticSettings(self, optionMap):
        if optionMap.has_key("diag"):
            return 1
        elif optionMap.has_key("trace"):
            envVarName = self.getConfigValue("diagnostics")["trace_level_variable"]
            os.environ[envVarName] = optionMap["trace"]
        return 0
    def addToOptionGroup(self, group):
        if group.name.startswith("What"):
            group.addOption("c", "Use checkout")
            group.addOption("s", "Run this script")
            group.addOption("v", "Run this version")
        elif group.name.startswith("How"):
            diagDict = self.getConfigValue("diagnostics")
            if diagDict.has_key("configuration_file"):
                group.addSwitch("diag", "Write target application diagnostics")
            if diagDict.has_key("trace_level_variable"):
                group.addOption("trace", "Target application trace level")
        elif group.name.startswith("Side"):
            group.addSwitch("x", "Write TextTest diagnostics")
            group.addSwitch("keeptmp", "Keep write-directories on success")
        elif group.name.startswith("Invisible"):
            group.addOption("a", "Applications containing")
            group.addOption("d", "Run tests at")
            group.addOption("record", "Record user actions to this script")
            group.addOption("replay", "Replay user actions from this script")
            group.addOption("recinp", "Record standard input to this script")
            group.addOption("help", "Print help text")
            group.addSwitch("g", "use GUI", 1)
            group.addSwitch("gx", "use static GUI")
    def findOptionGroup(self, option, optionGroups):
        for optionGroup in optionGroups:
            if optionGroup.options.has_key(option) or optionGroup.switches.has_key(option):
                return optionGroup
        return None
    def _getWriteDirectory(self, staticGUI):
        if not os.environ.has_key("TEXTTEST_TMP"):
            if os.name == "posix":
                os.environ["TEXTTEST_TMP"] = "~/texttesttmp"
            else:
                os.environ["TEXTTEST_TMP"] = os.environ["TEMP"]
        root = os.path.expanduser(os.environ["TEXTTEST_TMP"])
        absroot = plugins.abspath(root)
        if not os.path.isdir(absroot):
            os.makedirs(absroot)
        localName = self.getTmpIdentifier()
        if staticGUI:
            localName = "static_gui." + localName
        return os.path.join(absroot, localName)
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
    def createTestSuite(self, filters = None):
        if not filters:
            filters = self.configObject.getFilterList()

        success = 1
        for filter in filters:
            if not filter.acceptsApplication(self):
                success = 0
        suite = TestSuite(os.path.basename(self.abspath), self.abspath, self, filters)
        suite.reFilter(filters)
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
    def getVersionFileExtensions(self, baseVersion = 1, forSave = 0):
        versionsToUse = self.versions
        if baseVersion:
            versionsToUse = self.versions + self.getConfigValue("base_version")
        if forSave:
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
        if (os.path.isdir(self.writeDirectory)):
            return
        root, tmpId = os.path.split(self.writeDirectory)
        self.tryCleanPreviousWriteDirs(root)
        os.makedirs(self.writeDirectory)
        debugLog.info("Made root directory at " + self.writeDirectory)
    def removeWriteDirectory(self):
        # Don't be somewhere under the directory when it's removed
        os.chdir(self.abspath)
        if not self.keepTmpFiles and os.path.isdir(self.writeDirectory):
            plugins.rmtree(self.writeDirectory)
    def tryCleanPreviousWriteDirs(self, rootDir, nameBase = ""):
        if not self.keepTmpFiles or not os.path.isdir(rootDir):
            return
        currTmpString = nameBase + self.name + self.versionSuffix() + tmpString()
        for file in os.listdir(rootDir):
            fpath = os.path.join(rootDir, file)
            if not os.path.isdir(fpath):
                continue
            if file.startswith(currTmpString):
                previousWriteDir = os.path.join(rootDir, file)
                print "Removing previous write directory", previousWriteDir
                shutil.rmtree(previousWriteDir)
    def getTmpIdentifier(self):
        return self.name + self.versionSuffix() + globalRunIdentifier
    def getTestUser(self):
        return tmpString()
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
    def makePathName(self, name):
        if os.path.isabs(name):
            return name
        localName = os.path.join(self.abspath, name)
        if os.path.exists(localName):
            return localName
        homeDir, baseName = os.path.split(self.abspath)
        homeName = os.path.join(homeDir, name)
        if os.path.exists(homeName):
            return homeName
        # Return the name even though it doesn't exist, then it can be used
        return name
    def getActionSequence(self, useGui):
        return self.configObject.getActionSequence(useGui)
    def printHelpText(self):
        print helpIntro
        header = "Description of the " + self.getConfigValue("config_module") + " configuration"
        length = len(header)
        header += os.linesep
        for x in range(length):
            header += "-"
        print header
        self.configObject.printHelpText(builtInOptions)
    def getConfigValue(self, key):
        value = self.configDir[key]
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
    def addConfigEntry(self, key, value, sectionName = ""):
        self.configDir.addEntry(key, value, sectionName)
    def setConfigDefault(self, key, value):
        self.configDir[key] = value
    def makeCheckout(self, optionMap):
        if optionMap.has_key("c"):
            checkout = optionMap["c"]
        else:
            checkout = self.getConfigValue("default_checkout")
        checkoutLocation = os.path.expanduser(self.getConfigValue("checkout_location"))
        return self.makePathName(os.path.join(checkoutLocation, checkout))
    def getExecuteCommand(self, test):
        binary = self.getConfigValue("binary")
        if self.configDir.has_key("interpreter"):
            binary = self.configDir["interpreter"] + " " + binary
        return self.configObject.getExecuteCommand(binary, test)
    def getEnvironment(self):
        env = [ ("TEXTTEST_CHECKOUT", self.checkout) ]
        return env + self.configObject.getApplicationEnvironment(self)
            
class OptionFinder:
    def __init__(self):
        self.inputOptions = self.buildOptions()
        self.directoryName = self.findDirectoryName()
        os.environ["TEXTTEST_HOME"] = self.directoryName
        self._setUpLogging()
        debugLog.debug(repr(self.inputOptions))
    def _setUpLogging(self):
        global debugLog
        # Don't use the default locations, particularly current directory causes trouble
        del log4py.CONFIGURATION_FILES[1]
        if self.inputOptions.has_key("x") or os.environ.has_key("TEXTTEST_DIAGNOSTICS"):
            diagFile = self._getDiagnosticFile()
            if os.path.isfile(diagFile):
                diagDir = os.path.dirname(diagFile)
                if not os.environ.has_key("TEXTTEST_DIAGDIR"):
                    os.environ["TEXTTEST_DIAGDIR"] = diagDir
                print "TextTest will write diagnostics in", diagDir
                for file in os.listdir(diagDir):
                    if file.endswith("diag"):
                        os.remove(os.path.join(diagDir, file))
                # To set new config files appears to require a constructor...
                rootLogger = log4py.Logger(log4py.TRUE, diagFile)
            else:
                print "Could not find diagnostic file at", diagFile, ": cannot run with diagnostics"
                self._disableDiags()
        else:
            self._disableDiags()
        # Module level debugging logger
        global debugLog
        debugLog = plugins.getDiagnostics("texttest")
    def _disableDiags(self):
        rootLogger = log4py.Logger().get_root()        
        rootLogger.set_loglevel(log4py.LOGLEVEL_NONE)
    # Yes, we know that getopt exists. However it throws exceptions when it finds unrecognised things, and we can't do that...
    def buildOptions(self):                                                                                                              
        inputOptions = {}                                                                                                 
        optionKey = None                                                                                                                 
        for item in sys.argv[1:]:                      
            if item[0] == "-":                         
                optionKey = self.stripMinuses(item)
                inputOptions[optionKey] = ""
            elif optionKey:
                if len(inputOptions[optionKey]):
                    inputOptions[optionKey] += " "
                inputOptions[optionKey] += item.strip()
        return inputOptions
    def stripMinuses(self, item):
        if item[1] == "-":
            return item[2:].strip()
        else:
            return item[1:].strip()
    def findApps(self):
        dirName = self.directoryName
        os.chdir(dirName)
        debugLog.info("Using test suite at " + dirName)
        raisedError, appList = self._findApps(dirName, 1)
        appList.sort()
        debugLog.info("Found applications : " + repr(appList))
        if len(appList) == 0 and not raisedError:
            print "Could not find any matching applications (files of the form config.<app>) under", dirName
        return appList
    def _findApps(self, dirName, recursive):
        appList = []
        raisedError = 0
        selectedAppDict = self.findSelectedAppNames()
        debugLog.info("Selecting apps according to dictionary :" + repr(selectedAppDict))
        for f in os.listdir(dirName):
            pathname = os.path.join(dirName, f)
            if os.path.isfile(pathname):
                components = string.split(f, '.')
                if len(components) != 2 or components[0] != "config":
                    continue
                appName = components[1]
                if len(selectedAppDict) and not selectedAppDict.has_key(appName):
                    continue

                versionList = self.findVersionList()
                if selectedAppDict.has_key(appName):
                    versionList = selectedAppDict[appName]
                try:
                    for version in versionList:
                        appList += self.addApplications(appName, dirName, pathname, version)
                except (SystemExit, KeyboardInterrupt):
                    raise sys.exc_type, sys.exc_value
                except BadConfigError:
                    sys.stderr.write("Could not use application " + appName +  " - " + str(sys.exc_value) + os.linesep)
                    raisedError = 1
            elif os.path.isdir(pathname) and recursive:
                subRaisedError, subApps = self._findApps(pathname, 0)
                raisedError |= subRaisedError
                for app in subApps:
                    appList.append(app)
        return raisedError, appList
    def createApplication(self, appName, dirName, pathname, version):
        return Application(appName, dirName, pathname, version, self.inputOptions)
    def addApplications(self, appName, dirName, pathname, version):
        appList = []
        app = self.createApplication(appName, dirName, pathname, version)
        appList.append(app)
        extraVersion = app.getConfigValue("extra_version")
        if extraVersion == "none":
            return appList
        aggVersion = extraVersion
        if len(version) > 0:
            aggVersion = version + "." + extraVersion
        extraApp = self.createApplication(appName, dirName, pathname, aggVersion)
        app.extra = extraApp
        appList.append(extraApp)
        return appList
    def findVersionList(self):
        if self.inputOptions.has_key("v"):
            return plugins.commasplit(self.inputOptions["v"])
        else:
            return [""]
    def findSelectedAppNames(self):
        if not self.inputOptions.has_key("a"):
            return {}

        apps = plugins.commasplit(self.inputOptions["a"])
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
    def helpMode(self):
        return self.inputOptions.has_key("help")
    def useGUI(self):
        return self.inputOptions.has_key("g") or self.inputOptions.has_key("gx")
    def guiRunTests(self):
        return not self.inputOptions.has_key("gx")
    def _getDiagnosticFile(self):
        if os.environ.has_key("TEXTTEST_DIAGNOSTICS"):
            return os.path.join(os.environ["TEXTTEST_DIAGNOSTICS"], "log4py.conf")
        else:
            return os.path.join(self.directoryName, "Diagnostics", "log4py.conf")
    def findDirectoryName(self):
        if self.inputOptions.has_key("d"):
            return plugins.abspath(self.inputOptions["d"])
        elif os.environ.has_key("TEXTTEST_HOME"):
            return plugins.abspath(os.environ["TEXTTEST_HOME"])
        else:
            return os.getcwd()
    def getActionSequence(self, app, useGui):
        if self.inputOptions.has_key("gx"):
            return []
        
        if not self.inputOptions.has_key("s"):
            return app.getActionSequence(useGui)
            
        actionCom = self.inputOptions["s"].split(" ")[0]
        actionArgs = self.inputOptions["s"].split(" ")[1:]
        actionOption = actionCom.split(".")
        if len(actionOption) != 2:
            return self.getNonPython()
                
        module, pclass = actionOption
        importCommand = "from " + module + " import " + pclass + " as _pclass"
        try:
            exec importCommand
        except:
            return self.getNonPython()

        # Assume if we succeed in importing then a python module is intended.
        try:
            if len(actionArgs) > 0:
                return [ _pclass(actionArgs) ]
            else:
                return [ _pclass() ]
        except:
            printException()
            raise BadConfigError, "Could not instantiate script action " + repr(actionCom) + " with arguments " + repr(actionArgs) 
    def getNonPython(self):
        return [ plugins.NonPythonAction(self.inputOptions["s"]) ]
            
class MultiEntryDictionary(seqdict):
    def readValuesFromFile(self, filename, appName = "", versions = [], insert=1, errorOnUnknown=0):
        self.currDict = self
        if os.path.isfile(filename):
            configFile = open(filename)
            for line in configFile.xreadlines():
                self.parseConfigLine(line.strip(), insert, errorOnUnknown)
        # Versions are in order of most specific first. We want to update with least specific first.
        versions.reverse()
        self.updateFor(filename, appName, insert, errorOnUnknown)
        for version in versions:
            self.updateFor(filename, version, insert, errorOnUnknown)
            self.updateFor(filename, appName + "." + version, insert, errorOnUnknown)
    def parseConfigLine(self, line, insert, errorOnUnknown):
        if line.startswith("#") or len(line) == 0:
            return
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
    def updateFor(self, filename, extra, ins, errUnk):
        if len(extra) == 0:
            return
        debugLog.debug("Updating " + filename + " for version " + extra) 
        extraFileName = filename + "." + extra
        if os.path.isfile(extraFileName):
            self.readValuesFromFile(extraFileName, insert=ins, errorOnUnknown=errUnk)
    def addLine(self, line, insert, errorOnUnknown, separator = ':'):
        entryName, entry = string.split(line, separator, 1)
        self.addEntry(entryName, entry, "", insert, errorOnUnknown)
    def addEntry(self, entryName, entry, sectionName="", insert=0, errorOnUnknown=1):
        if sectionName:
            self.currDict = self[sectionName]
        entryExists = self.currDict.has_key(entryName)
        if entry == "{CLEAR LIST}":
            if entryExists:
                self.currDict[entryName] = []
        elif not entryExists:
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
        else:
            self.insertEntry(entryName, entry)
    def getDictionaryValueType(self):
        val = self.currDict.values()
        if len(val) == 0:
            return types.StringType
        else:
            return type(val[0])
    def insertEntry(self, entryName, entry):
        currType = type(self.currDict[entryName]) 
        if currType == types.ListType:
            if not entry in self.currDict[entryName]:
                self.currDict[entryName].append(entry)
        elif currType == types.IntType:
            self.currDict[entryName] = int(entry)
        else:
            self.currDict[entryName] = entry        

class TestRunner:
    def __init__(self, test, actionSequence, appRunner, diag):
        self.test = test
        self.diag = diag
        self.interrupted = 0
        self.actionSequence = []
        self.appRunner = appRunner
        # Copy the action sequence, so we can edit it and mark progress
        for action in actionSequence:
            self.actionSequence.append(action)
    def interrupt(self):
        self.interrupted = 1
    def handleExceptions(self, method, *args):
        try:
            return method(*args)
        except plugins.TextTestError, e:
            self.test.changeState(self.test.UNRUNNABLE, e)
        except KeyboardInterrupt:
            raise sys.exc_type, sys.exc_info
        except:
            print "WARNING : caught exception while running", self.test, "changing state to UNRUNNABLE :"
            printException()
            self.test.changeState(self.test.UNRUNNABLE, str(sys.exc_type) + ": " + str(sys.exc_value))
    def performActions(self, previousTestRunner, runToCompletion):
        tearDownSuites, setUpSuites = self.findSuitesToChange(previousTestRunner)
        for suite in tearDownSuites:
            self.handleExceptions(previousTestRunner.appRunner.tearDownSuite, suite)
        for suite in setUpSuites:
            suite.setUpEnvironment()
            self.appRunner.markForSetUp(suite)
        while len(self.actionSequence):
            action = self.actionSequence[0]
            self.diag.info("->Performing action " + str(action) + " on " + repr(self.test))
            self.handleExceptions(self.appRunner.setUpSuites, action, self.test)
            completed, tryOthersNow = self.performAction(action, runToCompletion)
            self.diag.info("<-End Performing action " + str(action) + self.returnString(completed, tryOthersNow))
            if completed:
                self.actionSequence.pop(0)
            if tryOthersNow:
                return 0
        return 1
    def returnString(self, completed, tryOthersNow):
        retString = " - "
        if completed:
            retString += "COMPLETE"
        else:
            retString += "RETRY"
        if tryOthersNow:
            retString += ", CHANGE TEST"
        else:
            retString += ", CONTINUE"
        return retString
    def performAction(self, action, runToCompletion):
        while 1:
            if self.interrupted:
                raise KeyboardInterrupt, "Interrupted externally"
            retValue = self.callAction(action)
            if not retValue:
                # No return value: we've finished and should proceed
                return 1, 0

            completed = not retValue & plugins.Action.RETRY
            tryOthers = retValue & plugins.Action.WAIT and not runToCompletion
            if completed or tryOthers:
                # Don't attempt to retry the action, mark complete
                return completed, tryOthers 
            # Don't busy-wait
            time.sleep(0.1)
    def callAction(self, action):
        self.test.setUpEnvironment()
        retValue = self.handleExceptions(self.test.callAction, action)
        self.test.tearDownEnvironment()
        return retValue
    def performCleanUpActions(self):
        for action in self.appRunner.cleanupSequence:
            self.diag.info("Performing cleanup " + str(action) + " on " + repr(self.test))
            self.test.callAction(action)
        if not self.test.app.keepTmpFiles:
            self.test.cleanNonBasicWriteDirectories()
    def findSuitesToChange(self, previousTestRunner):
        tearDownSuites = []
        commonAncestor = None
        if previousTestRunner:
            commonAncestor = self.findCommonAncestor(self.test, previousTestRunner.test)
            self.diag.info("Common ancestor : " + repr(commonAncestor))
            tearDownSuites = previousTestRunner.findSuitesUpTo(commonAncestor)
        setUpSuites = self.findSuitesUpTo(commonAncestor)
        # We want to set up the earlier ones first
        setUpSuites.reverse()
        return tearDownSuites, setUpSuites
    def findCommonAncestor(self, test1, test2):
        if self.hasAncestor(test1, test2):
            self.diag.info(test1.getRelPath() + " has ancestor " + test2.getRelPath())
            return test2
        if self.hasAncestor(test2, test1):
            self.diag.info(test2.getRelPath() + " has ancestor " + test1.getRelPath())
            return test1
        if test1.parent:
            return self.findCommonAncestor(test1.parent, test2)
        else:
            self.diag.info(test1.getRelPath() + " unrelated to " + test2.getRelPath())
            return None
    def hasAncestor(self, test1, test2):
        if test1 == test2:
            return 1
        if test1.parent:
            return self.hasAncestor(test1.parent, test2)
        else:
            return 0
    def findSuitesUpTo(self, ancestor):
        suites = []
        currCheck = self.test.parent
        while currCheck != ancestor:
            suites.append(currCheck)
            currCheck = currCheck.parent
        return suites

class ApplicationRunner:
    def __init__(self, testSuite, actionSequence, diag):
        self.testSuite = testSuite
        self.actionSequence = actionSequence
        self.cleanupSequence = self.getCleanUpSequence(actionSequence)
        self.suitesSetUp = {}
        self.suitesToSetUp = {}
        self.diag = diag
        self.setUpApplications(self.actionSequence)
    def getCleanUpSequence(self, actionSequence):
        cleanupSequence = []
        for action in actionSequence:
            cleanAction = action.getCleanUpAction()
            if cleanAction:
                cleanupSequence.append(cleanAction)
        cleanupSequence.reverse()
        return cleanupSequence
    def performCleanup(self):
        self.setUpApplications(self.cleanupSequence)
        self.testSuite.app.removeWriteDirectory()
    def setUpApplications(self, sequence):
        self.testSuite.setUpEnvironment()
        for action in sequence:
            self.diag.info("Performing " + str(action) + " set up on " + repr(self.testSuite.app))
            try:
                action.setUpApplication(self.testSuite.app)
            except KeyboardInterrupt:
                raise sys.exc_type, sys.exc_value
            except:
                message = str(sys.exc_value)
                if sys.exc_type != plugins.TextTestError:
                    printException()
                    message = str(sys.exc_type) + ": " + message
                raise BadConfigError, message
        self.testSuite.tearDownEnvironment()
    def markForSetUp(self, suite):
        newActions = []
        for action in self.actionSequence:
            newActions.append(action)
        self.suitesToSetUp[suite] = newActions
    def setUpSuites(self, action, test):
        if test.parent:
            self.setUpSuites(action, test.parent)
        if test.classId() == "test-suite":
            if action in self.suitesToSetUp[test]:
                self.setUpSuite(action, test)
                self.suitesToSetUp[test].remove(action)
    def setUpSuite(self, action, suite):
        self.diag.info(str(action) + " set up " + repr(suite))
        action.setUpSuite(suite)
        if self.suitesSetUp.has_key(suite):
            self.suitesSetUp[suite].append(action)
        else:
            self.suitesSetUp[suite] = [ action ]
    def tearDownSuite(self, suite):
        for action in self.suitesSetUp[suite]:
            self.diag.info(str(action) + " tear down " + repr(suite))
            action.tearDownSuite(suite)
        suite.tearDownEnvironment()
        self.suitesSetUp[suite] = []

class ActionRunner:
    def __init__(self):
        self.interrupted = 0
        self.previousTestRunner = None
        self.currentTestRunner = None
        self.allTests = []
        self.testQueue = []
        self.appRunners = []
        self.diag = plugins.getDiagnostics("Action Runner")
    def addTestActions(self, testSuite, actionSequence):
        self.diag.info("Processing test suite of size " + str(testSuite.size()) + " for app " + testSuite.app.name)
        appRunner = ApplicationRunner(testSuite, actionSequence, self.diag)
        self.appRunners.append(appRunner)
        for test in testSuite.testCaseList():
            self.diag.info("Adding test runner for test " + test.getRelPath())
            testRunner = TestRunner(test, actionSequence, appRunner, self.diag)
            self.testQueue.append(testRunner)
            self.allTests.append(testRunner)
    def hasTests(self):
        return len(self.allTests) > 0
    def runCleanup(self):
        for testRunner in self.allTests:
            self.diag.info("Running cleanup actions for test " + testRunner.test.getRelPath())
            testRunner.performCleanUpActions()
        for appRunner in self.appRunners:
            appRunner.performCleanup()
    def run(self):
        while len(self.testQueue):
            if self.interrupted:
                raise KeyboardInterrupt, "Interrupted externally"
            self.currentTestRunner = self.testQueue[0]
            self.diag.info("Running actions for test " + self.currentTestRunner.test.getRelPath())
            runToCompletion = len(self.testQueue) == 1
            completed = self.currentTestRunner.performActions(self.previousTestRunner, runToCompletion)
            self.testQueue.pop(0)
            if not completed:
                self.diag.info("Incomplete - putting to back of queue")
                self.testQueue.append(self.currentTestRunner)
            self.previousTestRunner = self.currentTestRunner
    def interrupt(self):
        self.interrupted = 1
        if self.currentTestRunner:
            self.currentTestRunner.interrupt()

def printException():
    sys.stderr.write("Description of exception thrown :" + os.linesep)
    type, value, traceback = sys.exc_info()
    sys.excepthook(type, value, traceback)
    
# Need somewhat different formats on Windows/UNIX
def tmpString():
    if os.environ.has_key("USER"):
        return os.getenv("USER")
    else:
        return "tmp"

# Class to allocate unique names to tests for script identification and cross process communication
class UniqueNameFinder:
    def __init__(self):
        self.name2test = {}
        self.diag = plugins.getDiagnostics("Unique Names")
    def addSuite(self, test):
        self.store(test)
        try:
            for subtest in test.testcases:
                self.addSuite(subtest)
        except AttributeError:
            pass
    def store(self, test):
        if self.name2test.has_key(test.name):
            oldTest = self.name2test[test.name]
            self.storeUnique(oldTest, test)
        else:
            self.name2test[test.name] = test
    def findParentIdentifiers(self, oldTest, newTest):
        oldParentId = " at top level"
        if oldTest.parent:
            oldParentId = " under " + oldTest.parent.name
        newParentId = " at top level"
        if newTest.parent:
            newParentId = " under " + newTest.parent.name
        if oldTest.parent and newTest.parent and oldParentId == newParentId:
            oldNextLevel, newNextLevel = self.findParentIdentifiers(oldTest.parent, newTest.parent)
            oldParentId += oldNextLevel
            newParentId += newNextLevel
        return oldParentId, newParentId
    def storeUnique(self, oldTest, newTest):
        oldParentId, newParentId = self.findParentIdentifiers(oldTest, newTest)
        if oldParentId != newParentId:
            self.storeBothWays(oldTest.name + oldParentId, oldTest)
            self.storeBothWays(newTest.name + newParentId, newTest)
        elif oldTest.app.name != newTest.app.name:
            self.storeBothWays(oldTest.name + " for " + oldTest.app.fullName, oldTest)
            self.storeBothWays(newTest.name + " for " + newTest.app.fullName, newTest)
        elif oldTest.app.getFullVersion() != newTest.app.getFullVersion():
            self.storeBothWays(oldTest.name + " version " + oldTest.app.getFullVersion(), oldTest)
            self.storeBothWays(newTest.name + " version " + newTest.app.getFullVersion(), newTest)
        else:
            raise plugins.TextTestError, "Could not find unique name for tests with name " + oldTest.name
    def storeBothWays(self, name, test):
        self.diag.info("Setting unique name for test " + test.name + " to " + name)
        self.name2test[name] = test
        test.uniqueName = name

# --- MAIN ---

class TextTest:
    def __init__(self):
        self.inputOptions = OptionFinder()
        global globalRunIdentifier
        globalRunIdentifier = tmpString() + time.strftime(self.timeFormat(), time.localtime())
        self.allApps = self.inputOptions.findApps()
        self.gui = None
        # Set USECASE_HOME for the use-case recorders we expect people to use for their tests...
        if not os.environ.has_key("USECASE_HOME"):
            os.environ["USECASE_HOME"] = os.path.join(self.inputOptions.directoryName, "usecases")
        if self.inputOptions.useGUI():
            try:
                import texttestgui
                self.gui = texttestgui.TextTestGUI(self.inputOptions.guiRunTests())
            except:
                print "Cannot use GUI: caught exception:"
                printException()
        if not self.gui:
            logger = plugins.getDiagnostics("Use-case log")
            self.scriptEngine = ScriptEngine(logger)
    def timeFormat(self):
        # Needs to work in files - Windows doesn't like : in file names
        if os.environ.has_key("USER"):
            return "%d%b%H:%M:%S"
        else:
            return "%H%M%S"
    def createActionRunner(self):
        actionRunner = ActionRunner()
        uniqueNameFinder = UniqueNameFinder()
        appSuites = []
        for app in self.allApps:
            try:
                valid, testSuite = app.createTestSuite()
                if valid:
                    appSuites.append((app, testSuite))
                    uniqueNameFinder.addSuite(testSuite)
            except BadConfigError:
                print "Error creating test suite for application", app, "-", sys.exc_value
                    
        for app, testSuite in appSuites:
            try:
                empty = testSuite.size() == 0
                if self.gui and (not empty or not self.gui.dynamic):
                    self.gui.addSuite(testSuite)
                if empty:
                    print "No tests found for", app.description()
                else:
                    useGui = self.inputOptions.useGUI()
                    actionSequence = self.inputOptions.getActionSequence(app, useGui)
                    actionRunner.addTestActions(testSuite, actionSequence)
                    print "Using", app.description() + ", checkout", app.checkout
            except BadConfigError:
                sys.stderr.write("Error in set-up of application " + repr(app) + " - " + str(sys.exc_value) + os.linesep)
        return actionRunner
    def run(self):
        try:
            if self.inputOptions.helpMode():
                self.allApps[0].printHelpText()
                return
            self._run()
        except KeyboardInterrupt:
            print "Terminated due to interruption"
    def _run(self):
        actionRunner = self.createActionRunner()
        # Allow no tests for static GUI
        if not actionRunner.hasTests() and (not self.gui or self.gui.dynamic):
            return
        try:
            if self.gui:
                self.gui.takeControl(actionRunner)
            else:
                actionRunner.run()
        finally:
            actionRunner.runCleanup()

if __name__ == "__main__":
    program = TextTest()
    program.run()
