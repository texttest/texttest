#!/usr/bin/env python
import os, sys, types, string, getopt, types, time, plugins, exceptions, stat, log4py, shutil
from stat import *
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
             
-record <s>- record all user actions in the GUI to the script <s>

-replay <s>- replay the script <s> created previously in the GUI. No effect without -g.

-s <scrpt> - instead of the normal actions performed by the configuration, use the script <scpt>. If this contains
             a ".", an attempt will be made to understand it as the Python class <module>.<classname>. If this fails,
             it will be interpreted as an external script.

-m <times> - perform the actions usually performed by the configuration, but repeated <times> times.

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
    #State names
    NOT_STARTED = 0
    RUNNING = 1
    KILLED = 2
    SUCCEEDED = 3
    FAILED = 4
    UNRUNNABLE = 5
    def __init__(self, name, abspath, app, parent = None):
        self.name = name
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
        self.environment.readValuesFromFile(os.path.join(self.abspath, "environment"), app.name, app.getVersionFileExtensions())
        # Single pass to expand all variables (don't want multiple expansion)
        for var, value in self.environment.items():
            expValue = os.path.expandvars(value)
            if value.find(os.sep) != -1:
                self.environment[var] = self.app.makeAbsPath(expValue)
                debugLog.info("Expanded " + var + " path " + value + " to " + self.environment[var])
            else:
                self.environment[var] = expValue
                debugLog.info("Expanded variable " + var + " to " + expValue + " in " + self.name)
            if os.environ.has_key(var):
                self.previousEnv[var] = os.environ[var]
            os.environ[var] = self.environment[var]
    def makeFileName(self, stem, refVersion = None, temporary = 0, forComparison = 1):
        root = self.getDirectory(temporary)
        if not forComparison:
            return os.path.join(root, stem)
        stemWithApp = stem + "." + self.app.name
        nonVersionName = os.path.join(root, stemWithApp)
        versions = self.app.getVersionFileExtensions()
        debugLog.info("Versions available : " + repr(versions))
        if refVersion != None:
            versions = [ refVersion ]
        if len(versions) == 0:
            return nonVersionName
        
        # Prioritise finding earlier versions
        testNonVersion = os.path.join(self.abspath, stemWithApp)
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
    def notifyChanged(self):
        for observer in self.observers:
            observer.notifyChange(self)
    def getRelPath(self):
        relPath = self.abspath.replace(self.app.abspath, "")
        if relPath.startswith(os.sep):
            return relPath[1:]
        return relPath
    def getDirectory(self, temporary):
        return self.abspath
    def getInstructions(self, action):
        return [ (self, plugins.SetUpEnvironment()) ] + action.getInstructions(self) \
               + self.getSubInstructions(action) + [ (self, plugins.TearDownEnvironment()) ]
    def performAction(self, action):
        self.setUpEnvironment()
        self.callAction(action)
        self.performOnSubTests(action)
        self.tearDownEnvironment()
    def setUpEnvironment(self, parents=0):
        if parents and self.parent:
            self.parent.setUpEnvironment(1)
        for var, value in self.environment.items():
            if os.environ.has_key(var):
                self.previousEnv[var] = os.environ[var]
            os.environ[var] = value
            debugLog.info("Setting " + var + " to " + os.environ[var])
    def tearDownEnvironment(self, parents=0):
        # Note this has no effect on the real environment, but can be useful for internal environment
        # variables. It would be really nice if Python had a proper "unsetenv" function...
        debugLog.info("Restoring environment for " + self.name + " to " + repr(self.previousEnv))
        for var in self.environment.keys():
            if os.environ.has_key(var):
                if self.previousEnv.has_key(var):
                    os.environ[var] = self.previousEnv[var]
                else:
                    debugLog.info("Removed variable " + var)
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
        optionsFile = self.makeFileName("options")
        self.options = ""
        if (os.path.isfile(optionsFile)):
            self.options = os.path.expandvars(open(optionsFile).readline().strip())
        elif not os.path.isfile(self.inputFile):
            self.valid = 0
        # List of directories where this test will write files. First is where it executes from
        self.writeDirs = []
        self.writeDirs.append(os.path.join(app.writeDirectory, self.getRelPath()))
    def __repr__(self):
        return repr(self.app) + " " + self.classId() + " " + self.paddedName
    def classId(self):
        return "test-case"
    def getDirectory(self, temporary):
        if temporary:
            return self.writeDirs[0]
        else:
            return self.abspath
    def callAction(self, action):
        if os.path.isdir(self.writeDirs[0]):
            os.chdir(self.writeDirs[0])
        try:
            return action(self)
        except plugins.TextTestError, e:
            self.changeState(self.UNRUNNABLE, e)
    def changeState(self, state, details = ""):
        # Once we've left the pathway, we can't return...
        if self.state == self.UNRUNNABLE or self.state == self.KILLED:
            return
        oldState = self.state
        self.state = state
        self.stateDetails = details
        if state != oldState:
            self.notifyChanged()
    def performOnSubTests(self, action):
        pass
    def getSubInstructions(self, action):
        return []
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
        os.makedirs(self.writeDirs[0])
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
            shutil.rmtree(writeDir)
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
    def classId(self):
        return "test-suite"
    def isEmpty(self):
        return len(self.testcases) == 0
    def callAction(self, action):
        return action.setUpSuite(self)
    def performOnSubTests(self, action):
        for testcase in self.testcases:
            testcase.performAction(action)
    def getSubInstructions(self, action):
        instructions = []
        for testcase in self.testcases:
            instructions += testcase.getInstructions(action)
        return instructions
    def isAcceptedBy(self, filter):
        return filter.acceptsTestSuite(self)
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
    def cleanNonBasicWriteDirectories(self):
        for test in self.testcases:
            test.cleanNonBasicWriteDirectories()
            
class Application:
    def __init__(self, name, abspath, configFile, version, optionMap):
        self.name = name
        self.abspath = abspath
        self.versions = version.split(".")
        if self.versions[0] == "":
            self.versions = []
        self.configDir = MultiEntryDictionary()
        self.setConfigDefaults()
        self.configDir.readValuesFromFile(configFile, name, self.getVersionFileExtensions(baseVersion=0), insert=0)
        self.fullName = self.getConfigValue("full_name")
        debugLog.info("Found application " + repr(self))
        self.checkout = self.makeCheckout(optionMap)
        debugLog.info("Checkout set to " + self.checkout)
        self.configObject = self.makeConfigObject(optionMap)
        self.keepTmpFiles = (optionMap.has_key("keeptmp") or self.configObject.keepTmpFiles() or self.getConfigValue("keeptmp_default"))
        self.writeDirectory = self._getWriteDirectory()
        # Fill in the values we expect from the configurations, and read the file a second time
        self.configObject.setApplicationDefaults(self)
        self.setDependentConfigDefaults()
        self.configDir.readValuesFromFile(configFile, name, self.getVersionFileExtensions(baseVersion=0), insert=0, errorOnUnknown=1)
        self.optionGroups = self.createOptionGroups(optionMap)
    def __repr__(self):
        return self.fullName
    def __cmp__(self, other):
        return cmp(self.name, other.name)
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
        self.setConfigDefault("compare_extension", [])
        self.setConfigDefault("copy_test_path", [])
        self.setConfigDefault("link_test_path", [])
        # External viewing tools
        # Do this here rather than from the GUI: if applications can be run with the GUI
        # anywhere it needs to be set up
        if os.name == "posix":
            self.setConfigDefault("view_program", "xemacs")
            self.setConfigDefault("diff_program", "tkdiff")
            self.setConfigDefault("follow_program", "tail -f")
        elif os.name == "dos" or os.name == "nt":
            self.setConfigDefault("view_program", "wordpad.exe")
            self.setConfigDefault("diff_program", "tkdiff.tcl")
            self.setConfigDefault("follow_program", None)
    def setDependentConfigDefaults(self):
        # Set values which default to other values
        self.setConfigDefault("display_module", self.getConfigValue("config_module"))
        self.setConfigDefault("interactive_action_module", self.getConfigValue("config_module"))
        if self.getConfigValue("binary").endswith(".py"):
            self.setConfigDefault("interpreter", "python")
        else:
            self.setConfigDefault("interpreter", "")
    def createOptionGroups(self, optionMap):
        groupNames = [ "Select Tests", "What to run", "How to run", "Side effects", "Invisible" ]
        optionGroups = []
        for name in groupNames:
            group = plugins.OptionGroup(name)
            self.addToOptionGroup(group)
            self.configObject.addToOptionGroup(group)
            optionGroups.append(group)
        for option in optionMap.keys():
            optionGroup = self.findOptionGroup(option, optionGroups)
            if not optionGroup:
                raise plugins.TextTestError, "unrecognised option -" + option
        return optionGroups
    def addToOptionGroup(self, group):
        if group.name.startswith("What"):
            group.addOption("c", "Use checkout")
            group.addOption("s", "Run this script")
            group.addOption("v", "Run this version")
        elif group.name.startswith("Side"):
            group.addSwitch("x", "Write TextTest diagnostics")
            group.addSwitch("keeptmp", "Keep write-directories on success")
        elif group.name.startswith("Invisible"):
            group.addOption("a", "Applications containing")
            group.addOption("d", "Run tests at")
            group.addOption("m", "Run this number of times")
            group.addOption("record", "Record user actions to this script")
            group.addOption("replay", "Replay user actions from this script")
            group.addOption("help", "Print help text")
            group.addSwitch("g", "use GUI", 1)
            group.addSwitch("gx", "use static GUI")
    def findOptionGroup(self, option, optionGroups):
        for optionGroup in optionGroups:
            if optionGroup.options.has_key(option) or optionGroup.switches.has_key(option):
                return optionGroup
        return None
    def _getWriteDirectory(self):
        if not os.environ.has_key("TEXTTEST_TMP"):
            if os.name == "posix":
                os.environ["TEXTTEST_TMP"] = "~/texttesttmp"
            else:
                os.environ["TEXTTEST_TMP"] = os.environ["TEMP"]
        root = os.path.expanduser(os.environ["TEXTTEST_TMP"])
        absroot = os.path.abspath(root)
        if not os.path.isdir(absroot):
            os.makedirs(absroot)
        return os.path.join(absroot, self.getTmpIdentifier())
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
    def createTestSuite(self, optionGroup = None):
        if optionGroup:
            for key, option in optionGroup.options.items():
                if len(option.getValue()):
                    self.configObject.optionMap[key] = option.getValue()
                elif self.configObject.optionMap.has_key(key):
                    del self.configObject.optionMap[key]
        valid, filters = self.getFilterList()
        suite = TestSuite(os.path.basename(self.abspath), self.abspath, self, filters)
        suite.reFilter(filters)
        return valid, suite
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
            versionsToUse = self.getConfigValue("base_version") + self.versions
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
        root, tmpId = os.path.split(self.writeDirectory)
        self.tryCleanPreviousWriteDirs(root)
        os.makedirs(self.writeDirectory)
        debugLog.info("Made root directory at " + self.writeDirectory)
    def removeWriteDirectory(self):
        # Don't be somewhere under the directory when it's removed
        os.chdir(self.abspath)
        if not self.keepTmpFiles and os.path.isdir(self.writeDirectory):
            self._removeDir()
    def _removeDir(self):
        for i in range(5):
            try:
                shutil.rmtree(self.writeDirectory)
                return
            except OSError:
                print "Write directory still in use, waiting 1 second to remove..."
                time.sleep(1)
        print "Something still using write directory", self.writeDirectory, ": leaving it"
    def tryCleanPreviousWriteDirs(self, rootDir, nameBase = ""):
        if not self.keepTmpFiles or not os.path.isdir(rootDir):
            return
        currTmpString = nameBase + self.name + self.versionSuffix() + tmpString()
        for file in os.listdir(rootDir):
            fpath = os.path.join(rootDir, file)
            if not os.path.isdir(fpath):
                continue
            if fpath.find(currTmpString) != -1:
                shutil.rmtree(os.path.join(rootDir, file))
    def getTmpIdentifier(self):
        return self.name + self.versionSuffix() + globalRunIdentifier
    def getTestUser(self):
        return tmpString()
    def ownsFile(self, fileName, unknown = 1):
        # Environment file may or may not be owned. Return whatever we're told to return for unknown
        if fileName == "environment":
            return unknown
        # And anything ending in cmp we don't want...
        if fileName.endswith("cmp"):
            return 0
        parts = fileName.split(".")
        if len(parts) == 1:
            return 0
        ext = parts[1]
        if ext == self.name or ext in self.getConfigValue("compare_extension"):
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
        except:
            errorString = "No module named " + configModule
            if sys.exc_type == exceptions.ImportError and str(sys.exc_value) == errorString:
                raise KeyError, "could not find config_module " + configModule
            else:
                printException()
                raise KeyError, "config_module " + configModule + " contained errors and could not be imported"  
        return getConfig(optionMap)
    def getActionSequence(self):
        return self.configObject.getActionSequence()
    def printHelpText(self):
        print helpIntro
        header = "Description of the " + self.getConfigValue("config_module") + " configuration"
        length = len(header)
        header += os.linesep
        for x in range(length):
            header += "-"
        print header
        self.configObject.printHelpText(builtInOptions)
    def getFilterList(self):
        filters = self.configObject.getFilterList()
        success = 1
        for filter in filters:
            if not filter.acceptsApplication(self):
                success = 0
        return success, filters
    def getConfigValue(self, key):
        value = self.configDir[key]
        if type(value) == types.StringType:
            return os.path.expandvars(value)
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
        binary = self.getBinary()
        if self.configDir.has_key("interpreter"):
            binary = self.configDir["interpreter"] + " " + binary
        return self.configObject.getExecuteCommand(binary, test)
    def getBinary(self):
        return self.makeAbsPath(self.getConfigValue("binary"))
    def getVitalFiles(self):
        return self.configObject.getVitalFiles(self)
            
class OptionFinder:
    def __init__(self):
        self.inputOptions = self.buildOptions()
        self.directoryName = self.findDirectoryName()
        self._setUpLogging()
        debugLog.debug(repr(self.inputOptions))
    def _setUpLogging(self):
        global debugLog
        if self.inputOptions.has_key("x"):
            diagFile = self._getDiagnosticFile()
            if os.path.isfile(diagFile):
                diagDir = os.path.dirname(diagFile)
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
        selectedAppList = self.findSelectedAppNames()
        for f in os.listdir(dirName):
            pathname = os.path.join(dirName, f)
            if os.path.isfile(pathname):
                components = string.split(f, '.')
                if len(components) != 2 or components[0] != "config":
                    continue
                appName = components[1]
                if len(selectedAppList) and not appName in selectedAppList:
                    continue
                versionList = self.findVersionList()
                try:
                    for version in versionList:
                        appList += self.addApplications(appName, dirName, pathname, version)
                except (SystemExit, KeyboardInterrupt):
                    raise sys.exc_type, sys.exc_value
                except:
                    print "Could not use application", appName, "-", sys.exc_value
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
        appList.append(self.createApplication(appName, dirName, pathname, aggVersion))
        return appList
    def findVersionList(self):
        if self.inputOptions.has_key("v"):
            return plugins.commasplit(self.inputOptions["v"])
        else:
            return [""]
    def findSelectedAppNames(self):
        if self.inputOptions.has_key("a"):
            return plugins.commasplit(self.inputOptions["a"])
        else:
            return []
    def timesToRun(self):
        if self.inputOptions.has_key("m"):
            return int(self.inputOptions["m"])
        else:
            return 1
    def helpMode(self):
        return self.inputOptions.has_key("help")
    def useGUI(self):
        return self.inputOptions.has_key("g") or self.inputOptions.has_key("gx")
    def guiRunTests(self):
        return not self.inputOptions.has_key("gx")
    def recordScript(self):
        if self.inputOptions.has_key("record"):
            return self.findGuiScript(self.inputOptions["record"])
        else:
            return ""
    def replayScript(self):
        if self.inputOptions.has_key("replay"):
            return self.findGuiScript(self.inputOptions["replay"])
        else:
            return ""
    def findGuiScript(self, scriptFile):
        if os.path.isfile(scriptFile):
            return os.path.join(os.getcwd(), scriptFile)
        else:
            return os.path.join(self.directoryName, scriptFile)
    def _getDiagnosticFile(self):
        if os.environ.has_key("TEXTTEST_DIAGNOSTICS"):
            return os.path.join(os.environ["TEXTTEST_DIAGNOSTICS"], "log4py.conf")
        else:
            return os.path.join(self.directoryName, "Diagnostics", "log4py.conf")
    def findDirectoryName(self):
        if self.inputOptions.has_key("d"):
            return os.path.abspath(self.inputOptions["d"])
        elif os.environ.has_key("TEXTTEST_HOME"):
            return os.path.abspath(os.environ["TEXTTEST_HOME"])
        else:
            return os.getcwd()
    def getActionSequence(self, app):
        if self.inputOptions.has_key("gx"):
            return []
        
        if not self.inputOptions.has_key("s"):
            return app.getActionSequence()
            
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
        if len(actionArgs) > 0:
            return [ _pclass(actionArgs) ]
        else:
            return [ _pclass() ]
    def getNonPython(self):
        return [ plugins.NonPythonAction(self.inputOptions["s"]) ]
            
class MultiEntryDictionary(seqdict):
    def readValuesFromFile(self, filename, appName = "", versions = [], insert=1, errorOnUnknown=0):
        self.currDict = self
        if os.path.isfile(filename):
            configFile = open(filename)
            for line in configFile.xreadlines():
                self.parseConfigLine(line.strip(), insert, errorOnUnknown)
        self.updateFor(filename, appName)
        for version in versions:
            self.updateFor(filename, version)
            self.updateFor(filename, appName + "." + version)
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
    def updateFor(self, filename, extra):
        if len(extra) == 0:
            return
        debugLog.debug("Updating " + filename + " for version " + extra) 
        extraFileName = filename + "." + extra
        if os.path.isfile(extraFileName):
            self.readValuesFromFile(extraFileName)
    def addLine(self, line, insert, errorOnUnknown, separator = ':'):
        entryName, entry = string.split(line, separator, 1)
        self.addEntry(entryName, entry, "", insert, errorOnUnknown)
    def addEntry(self, entryName, entry, sectionName="", insert=0, errorOnUnknown=1):
        if sectionName:
            self.currDict = self[sectionName]
        if not self.currDict.has_key(entryName):
            if insert or not self.currDict is self:
                val = self.currDict.values()
                if len(val) == 0 or type(val[0]) != types.ListType:
                    self.currDict[entryName] = entry
                else:
                    self.currDict[entryName] = [ entry ]
            elif errorOnUnknown:
                print "ERROR : config entry name '" + entryName + "' not recognised"
        else:
            self.insertEntry(entryName, entry)
    def insertEntry(self, entryName, entry):
        currType = type(self.currDict[entryName]) 
        if currType == types.ListType:
            if not entry in self.currDict[entryName]:
                self.currDict[entryName].append(entry)
        elif currType == types.IntType:
            self.currDict[entryName] = int(entry)
        else:
            self.currDict[entryName] = entry        
    
class ApplicationRunner:
    def __init__(self, app, inputOptions, gui):
        self.app = app
        self.actionSequence = inputOptions.getActionSequence(app)
        debugLog.debug("Action sequence = " + repr(self.actionSequence))
        if inputOptions.helpMode():
            app.printHelpText()
            self.valid = 0
            return
        self.valid, tmpSuite = app.createTestSuite()
        self.gui = gui
        if tmpSuite.size() == 0:
            print "No tests found for", app.description()
            self.valid = 0
        else:
            self.testSuite = tmpSuite
            if gui:
                gui.addSuite(self.testSuite)
    def actionCount(self):
        return len(self.actionSequence)
    def performAction(self, actionNum):
        debugLog.debug("Performing action number " + str(actionNum) + " of " + str(self.actionCount()))
        if actionNum < self.actionCount():
            action = self.actionSequence[actionNum]
            self._performAction(self.testSuite, action)
    def performCleanUp(self):
        self.valid = 0 # Make sure no future runs are made
        self.gui = None # The GUI has been exited
        self.actionSequence.reverse()
        for action in self.actionSequence:
            cleanUp = action.getCleanUpAction()
            if cleanUp != None:
                self._performAction(self.testSuite, cleanUp)
        # Hardcoded destructor-like cleanup (the destructor isn't called for some reason)
        self.app.removeWriteDirectory()
        if not self.app.keepTmpFiles:
            self.testSuite.cleanNonBasicWriteDirectories()
    def _performAction(self, suite, action):
        debugLog.debug("Performing action " + repr(action))
        suite.setUpEnvironment()
        action.setUpApplication(suite.app)
        suite.tearDownEnvironment()
        debugLog.debug("Current config dictionary for " + repr(suite.app) + ": " + os.linesep + repr(suite.app.configDir))
        if self.gui:
            instructionList = suite.getInstructions(action)
            self.gui.storeInstructions(instructionList)
        else:
            suite.performAction(action)    

def printException():
    type, value, traceback = sys.exc_info()
    sys.excepthook(type, value, traceback)
    
# Need somewhat different formats on Windows/UNIX
def tmpString():
    if os.environ.has_key("USER"):
        return os.getenv("USER")
    else:
        return "tmp"

# --- MAIN ---

class TextTest:
    def __init__(self):
        self.inputOptions = OptionFinder()
        global globalRunIdentifier
        useGui = self.inputOptions.useGUI()
        globalRunIdentifier = tmpString() + time.strftime(self.timeFormat(), time.localtime())
        self.allApps = self.inputOptions.findApps()
        self.gui = None
        if useGui:
            try:
                self.ensureDisplaySet()
                import texttestgui
                recordScript = self.inputOptions.recordScript()
                replayScript = self.inputOptions.replayScript()
                self.gui = texttestgui.TextTestGUI(self.inputOptions.guiRunTests(), replayScript, recordScript)
            except:
                print "Cannot use GUI: caught exception:"
                printException()
    def timeFormat(self):
        # Needs to work in files - Windows doesn't like : in file names
        if os.environ.has_key("USER"):
            return "%d%b%H:%M:%S"
        else:
            return "%H%M%S"
    def shouldFindTestDisplay(self):
        if not os.environ.has_key("DISPLAY"):
            return 1
        if self.inputOptions.useGUI() and self.inputOptions.recordScript() != "":
            return 0
        if os.environ.has_key("TEST_DISPLAY") and os.environ["TEST_DISPLAY"] == "TEXTTEST_GETDISPLAY":
            return 1
        return 0
    def ensureDisplaySet(self):
        # DISPLAY variable must be set if we are to run the GUI on UNIX
        if os.name == "posix" and self.shouldFindTestDisplay():
            for app in self.allApps:
                try:
                    displayModule = app.getConfigValue("display_module")
                    importCommand = "from " + displayModule + " import getDisplay"
                    exec importCommand
                    display = getDisplay()
                    if display:
                        os.environ["DISPLAY"] = display
                        return
                    else:
                        print "Application", app, "searched for a display but could not find one."
                except ImportError:
                    print "Failed to import display_module", displayModule
                except AttributeError:
                    pass
            raise plugins.TextTestError, "DISPLAY variable not set and no selected configuration has any way to set one"
    def run(self):
        try:
            self._run()
        except SystemExit:# Assumed to be a child thread, in any case exit silently
            pass
        except KeyboardInterrupt:
            print "Terminated due to interruption"
    def _run(self):
        applicationRunners = self.createAppRunners()
        if len(applicationRunners) == 0:
            return
        maxActionCount = max(map(lambda x: x.actionCount(), applicationRunners))
        # Run actions one at a time for each application. This should ensure a fair spread of machine time when this is limited
        for run in range(self.inputOptions.timesToRun()):
            for actionNum in range(maxActionCount):
                self.performActionOnApps(applicationRunners, actionNum)
            if self.gui:
                self.gui.takeControl()
            for appRunner in applicationRunners:
                appRunner.performCleanUp()
    def createAppRunners(self):
        applicationRunners = []
        for app in self.allApps:
            try:
                appRunner = ApplicationRunner(app, self.inputOptions, self.gui)
                if appRunner.valid:
                    print "Using", app.description() + ", checkout", app.checkout
                    applicationRunners.append(appRunner)
            except (SystemExit, KeyboardInterrupt):
                printException()
                raise sys.exc_type, sys.exc_value
            except:
                print "Not running tests of application", app, "due to exception in set-up:"
                printException()
        return applicationRunners
    def performActionOnApps(self, applicationRunners, actionNum):
        try:
            for appRunner in applicationRunners:
                if appRunner.valid:
                    self.performAction(appRunner, actionNum)
        except SystemExit:
            # Assumed to be a child thread, in any case exit silently
            raise sys.exc_type, sys.exc_value
        except KeyboardInterrupt:
            print "Received kill signal, cleaning up all applications..."
            for appRunner in applicationRunners:
                appRunner.performCleanUp()
            raise sys.exc_type, sys.exc_value
    def performAction(self, appRunner, actionNum):
        try:
            appRunner.performAction(actionNum)
        except (SystemExit, KeyboardInterrupt):
            raise sys.exc_type, sys.exc_value
        except:
            print "Caught exception from application", appRunner.app, ", cleaning up and terminating its tests:"
            printException()
            appRunner.performCleanUp()

if __name__ == "__main__":
    program = TextTest()
    program.run()
