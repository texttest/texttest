#!/usr/bin/env python
import os, sys, types, string, plugins, exceptions, log4py, shutil
from time import time
from usecase import ScriptEngine, UseCaseScriptError
from ndict import seqdict
from copy import copy
from cPickle import Pickler, Unpickler, UnpicklingError

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

-s <scrpt> - instead of the normal actions performed by the configuration, use the script <scpt>. If this contains
             a ".", an attempt will be made to understand it as the Python class <module>.<classname>. If this fails,
             it will be interpreted as an external script.

-help      - Do not run anything. Instead, generate useful text, such as this.

-x         - Enable log4py diagnostics for the framework. This will use a diagnostic directory from the environment
             variable TEXTTEST_DIAGNOSTICS, if defined, or the directory <root>/Diagnostics/ if not. It will read
             the log4py configuration file present in that directory and write all diagnostic files there as well.
             More details can be had from the log4py documentation.
"""

# Base class for TestCase and TestSuite
class Test:
    def __init__(self, name, abspath, app, parent = None):
        self.name = name
        # There is nothing to stop several tests having the same name. Maintain another name known to be unique
        self.uniqueName = name
        self.app = app
        self.parent = parent
        self.abspath = abspath
        self.valid = os.path.isdir(abspath)
        # Test suites never change state, but it's convenient that they have one
        self.state = plugins.TestState("not_started")
        self.paddedName = self.name
        self.previousEnv = {}
        # List of objects observing this test, to be notified when it changes state
        self.observers = []
        self.environment = MultiEntryDictionary()
        # Java equivalent of the environment mechanism...
        self.properties = MultiEntryDictionary()
    def readEnvironment(self):
        if self.parent == None:
            for var, value in self.app.getEnvironment():
                self.environment[var] = value
        diagDict = self.getConfigValue("diagnostics")
        if diagDict.has_key("input_directory_variable"):
            diagConfigFile = os.path.join(self.abspath, diagDict["configuration_file"])
            if os.path.isfile(diagConfigFile):
                inVarName = diagDict["input_directory_variable"]
                self.addDiagVariable(diagDict, inVarName, self.abspath)
        envFile = os.path.join(self.abspath, "environment")
        self.environment.readValuesFromFile(envFile, self.app.name, self.app.getVersionFileExtensions())
        # Should do this, but not quite yet...
        # self.properties.readValuesFromFile(os.path.join(self.abspath, "properties"), app.name, app.getVersionFileExtensions())
    def addDiagVariable(self, diagDict, entryName, entry):
        # Diagnostics are usually controlled from the environment, but in Java they have to work with properties...
        if diagDict.has_key("properties_file"):
            propFile = diagDict["properties_file"]
            if not self.properties.has_key(propFile):
                self.properties.addEntry(propFile, {}, insert=1)
            self.properties.addEntry(entryName, entry.replace(os.sep, "/"), sectionName = propFile, insert=1)
        else:
            self.environment[entryName] = entry        
    def expandEnvironmentReferences(self, referenceVars = []):
        self._expandEnvironmentReferences(referenceVars)
        self.tearDownEnvironment()
    def _expandEnvironmentReferences(self, referenceVars):
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
        self.expandChildEnvironmentReferences(childReferenceVars)
    def expandChildEnvironmentReferences(self, referenceVars):
        pass
    def makeFileName(self, stem, refVersion = None, temporary = 0, forComparison = 1):
        root = self.getDirectory(temporary, forComparison)
        if not forComparison:
            return os.path.join(root, stem)
        if os.path.split(stem)[-1].find(".") == -1:
            stem += "." + self.app.name
        nonVersionName = os.path.join(root, stem)
        versions = self.app.getVersionFileExtensions()
        debugLog.info("Versions available : " + repr(versions))
        if refVersion:
            refApp = self.app.createCopy(refVersion)
            versions = refApp.getVersionFileExtensions()
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
        localFiles = []
        knownDataFiles = self.app.getConfigValue("link_test_path") + self.app.getConfigValue("copy_test_path")
        for file in knownDataFiles:
            fullPath = os.path.join(self.abspath, file)
            if os.path.exists(fullPath):
                localFiles.append(fullPath)
        readFiles = seqdict()
        readFiles[""] = localFiles
        return readFiles + self.app.configObject.extraReadFiles(self)
    def notifyChanged(self):
        for observer in self.observers:
            observer.notifyChange(self)
    def getRelPath(self):
        # We standardise communication around UNIX paths, it's all much easier that way
        relPath = self.abspath.replace(self.app.abspath, "").replace(os.sep, "/")
        if relPath.startswith("/"):
            return relPath[1:]
        return relPath
    def getDirectory(self, temporary, forComparison = 1):
        return self.abspath
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
                return 0
        return 1
    def size(self):
        return 1

class TestCase(Test):
    def __init__(self, name, abspath, app, filters, parent):
        Test.__init__(self, name, abspath, app, parent)
        self.inputFile = self.makeFileName("input")
        self.useCaseFile = self.makeFileName("usecase")
        self._setOptions()
        # List of directories where this test will write files. First is where it executes from
        self.writeDirs = [ os.path.join(app.writeDirectory, self.getRelPath()) ]
        if self.valid and self.isAcceptedByAll(filters):
            self.readEnvironment()
            self.setTestEnvironment()
        else:
            self.valid = 0
    def setTestEnvironment(self):
        diagDict = self.app.getConfigValue("diagnostics")
        basicWriteDir = self.writeDirs[0]
        if self.app.useDiagnostics:
            inVarName = diagDict["input_directory_variable"]
            self.addDiagVariable(diagDict, inVarName, os.path.join(self.abspath, "Diagnostics"))
            outVarName = diagDict["write_directory_variable"]
            self.addDiagVariable(diagDict, outVarName, os.path.join(basicWriteDir, "Diagnostics"))
        elif diagDict.has_key("write_directory_variable"):
            outVarName = diagDict["write_directory_variable"]
            self.addDiagVariable(diagDict, outVarName, basicWriteDir)
        self.setUseCaseEnvironment()
    def setUseCaseEnvironment(self):
        if self.useJavaRecorder():
            self.properties.addEntry("jusecase", {}, insert=1)
        if os.path.isfile(self.useCaseFile):
            self.setReplayEnvironment()
    def useJavaRecorder(self):
        return self.app.getConfigValue("use_case_recorder") == "jusecase"
    # Here we assume the application uses either PyUseCase or JUseCase
    # PyUseCase reads environment variables, but you can't do that from java,
    # so we have a "properties file" set up as well. Do both always, to save forcing
    # apps to tell us which to do...
    def setReplayEnvironment(self):
        self.setReplay(self.useCaseFile, self.app.slowMotionReplaySpeed)
        self.setRecord(self.makeFileName("usecase", temporary=1))
    def setRecordEnvironment(self):
        self.setRecord(self.useCaseFile, self.inputFile)
        self.disableReplay()
    def disableReplay(self):
        if not self.useJavaRecorder():
            if self.environment.has_key("USECASE_REPLAY_SCRIPT"):
                del self.environment["USECASE_REPLAY_SCRIPT"]
            if os.environ.has_key("USECASE_REPLAY_SCRIPT"):
                self.previousEnv["USECASE_REPLAY_SCRIPT"] = os.environ["USECASE_REPLAY_SCRIPT"]
                del os.environ["USECASE_REPLAY_SCRIPT"]
    def addJusecaseProperty(self, name, value):
        self.properties.addEntry(name, value, sectionName="jusecase", insert=1)
    def setReplay(self, replayScript, replaySpeed):
        if replayScript:
            if self.useJavaRecorder():
                self.addJusecaseProperty("replay", replayScript)
            else:
                self.environment["USECASE_REPLAY_SCRIPT"] = replayScript
        if replaySpeed:
            if self.useJavaRecorder():
                self.addJusecaseProperty("delay", str(replaySpeed))
            else:
                self.environment["USECASE_REPLAY_DELAY"] = str(replaySpeed)
    def setRecord(self, recordScript, recinpScript = None):
        if recordScript:
            if self.useJavaRecorder():
                self.addJusecaseProperty("record", recordScript)
            else:
                self.environment["USECASE_RECORD_SCRIPT"] = recordScript
        if recinpScript:
            if self.useJavaRecorder():
                self.addJusecaseProperty("record_stdin", recinpScript)
            else:
                self.environment["USECASE_RECORD_STDIN"] = recinpScript
    def __repr__(self):
        return repr(self.app) + " " + self.classId() + " " + self.paddedName
    def classId(self):
        return "test-case"
    def testCaseList(self):
        return [ self ]
    def expandEnvironmentReferences(self, referenceVars = []):
        self._expandEnvironmentReferences(referenceVars)
        self.options = os.path.expandvars(self.options)
        self.tearDownEnvironment()
    def _setOptions(self):
        optionsFile = self.makeFileName("options")
        self.options = ""
        if (os.path.isfile(optionsFile)):
            self.options = open(optionsFile).readline().strip()
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
        return action(self)
    def filesChanged(self):
        self._setOptions()
        self.notifyChanged()
    def changeState(self, state):
        oldState = self.state
        self.state = state
        # Notify GUI of all category changes
        if state.displayDataChange(oldState):
            self.notifyChanged()
        # Check that the state change involved moving on in time, not just re-classifying
        # Tests changing state are reckoned to be significant enough to wait for...
        if state.timeElapsedSince(oldState):
            self.stateChangeEvent(state)
    def stateChangeEvent(self, state):
        eventName = "test " + self.uniqueName + " to " + state.changeDescription()
        category = self.uniqueName
        # Files abound here, we wait a little for them to clear up
        try:
            ScriptEngine.instance.applicationEvent(eventName, category, timeDelay=1)
        except UseCaseScriptError:
            # This will be raised if we're in a subthread, i.e. if the GUI is running
            # Rely on the GUI to report the same event
            pass
    def getStateFile(self):
        return self.makeFileName("teststate", temporary=1, forComparison=0)
    def loadState(self, retrieveErrorsOnly = 0):
        stateFile = self.getStateFile()
        if not os.path.isfile(stateFile):
            return 0
        
        file = open(stateFile)
        try:
            unpickler = Unpickler(file)
            state = unpickler.load()
        except UnpicklingError:
            return 0
        if retrieveErrorsOnly and state.hasResults():
            return 0
        self.changeState(state)
        return 1
    def saveState(self):
        stateFile = self.getStateFile()
        # Ensure directory exists, it may not
        dir, local = os.path.split(stateFile)
        if not os.path.isdir(dir):
            os.makedirs(dir)
        if os.path.isfile(stateFile):
            # Don't overwrite previous saved state
            return
        file = open(stateFile, "w")
        pickler = Pickler(file)
        pickler.dump(self.state)
        file.close()
    def getExecuteCommand(self):
        return self.app.getExecuteCommand(self)
    def getTmpExtension(self):
        return globalRunIdentifier
    def isOutdated(self, filename):
        modTime = plugins.modifiedTime(filename)
        currTime = time()
        threeDaysInSeconds = 60 * 60 * 24 * 3
        return currTime - modTime > threeDaysInSeconds
    def isAcceptedBy(self, filter):
        return filter.acceptsTestCase(self)
    def makeBasicWriteDirectory(self):
        fullPathToMake = os.path.join(self.writeDirs[0], "framework_tmp")
        os.makedirs(fullPathToMake)
    def prepareBasicWriteDirectory(self):
        if self.app.useDiagnostics:
            os.mkdir(os.path.join(self.writeDirs[0], "Diagnostics"))
        self.collatePaths("copy_test_path", self.copyTestPath)
        self.collatePaths("link_test_path", self.linkTestPath)
        self.createPropertiesFiles()
    def createPropertiesFiles(self):
        for var, value in self.properties.items():
            propFileName = os.path.join(self.writeDirs[0], var + ".properties")
            debugLog.info("Writing " + propFileName + " for " + var + " : " + repr(value))
            file = open(propFileName, "w")
            for subVar, subValue in value.items():
                file.write(subVar + " = " + subValue + "\n")            
    def cleanNonBasicWriteDirectories(self):
        if len(self.writeDirs) > 0:
            for writeDir in self.writeDirs[1:]:
                self._removeDir(writeDir)
    def _removeDir(self, writeDir):
        parent, local = os.path.split(writeDir)
        if local.find(self.app.getTmpIdentifier()) != -1:
            directoryLog.info("Removing write directory under " + parent)
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
    # Find a name base which doesn't clash with existing tests
    def getNameBaseToUse(self, rootDir, nameBase):
        fullWriteDir = self.getFullWriteDir(rootDir, nameBase)
        if os.path.isdir(fullWriteDir):
            return self.getNameBaseToUse(rootDir, "x" + nameBase)
        else:
            return nameBase
    def getFullWriteDir(self, rootDir, nameBase):
        localName = nameBase + self.app.getTmpIdentifier()
        return os.path.join(rootDir, localName)
    def createDir(self, rootDir, nameBase = "", subDir = None):
        writeDir = self.getFullWriteDir(rootDir, nameBase)
        fullWriteDir = writeDir
        if subDir:
            fullWriteDir = os.path.join(writeDir, subDir)
        self.createDirs(fullWriteDir)    
        return writeDir
    def createDirs(self, fullWriteDir):
        os.makedirs(fullWriteDir)    
        directoryLog.info("Created write directory " + fullWriteDir)
        self.writeDirs.append(fullWriteDir)
        return fullWriteDir
    def makeWriteDirectory(self, rootDir, basicDir, subDir = None):
        nameBase = self.getNameBaseToUse(rootDir, basicDir + ".")
        self.app.tryCleanPreviousWriteDirs(rootDir, nameBase)
        try:
            writeDir = self.createDir(rootDir, nameBase, subDir)
        except OSError:
            return self.makeWriteDirectory(rootDir, basicDir, subDir)
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
    def __init__(self, name, abspath, app, filters, parent=None, allVersions=0):
        Test.__init__(self, name, abspath, app, parent)
        self.testCaseFile = self.makeFileName("testsuite")
        self.testcases = []
        if self.valid and os.path.isfile(self.testCaseFile) and self.isAcceptedByAll(filters):
            self.readEnvironment()
            self.readTestCases(filters, allVersions)
        else:
            self.valid = 0
    def readTestCases(self, filters, allVersions):
        self.testcases = self.getTestCases(filters, self.testCaseFile, allVersions)
        debugLog.info("Test suite file " + self.testCaseFile + " had " + str(len(self.testcases)) + " tests")
        if allVersions:
            for fileName in self.findVersionTestSuiteFiles():
                newCases = self.getTestCases(filters, fileName, allVersions)
                self.testcases += newCases
                debugLog.info("Added " + str(len(newCases)) + " from " + fileName)
        if len(self.testcases):
            maxNameLength = max([len(test.name) for test in self.testcases])
            for test in self.testcases:
                test.paddedName = string.ljust(test.name, maxNameLength)
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
        allFiles = os.listdir(self.abspath)
        allFiles.sort()
        localFiles = filter(self.isVersionTestSuiteFile, allFiles)
        return map(lambda file: os.path.join(self.abspath, file), localFiles)
    def isVersionTestSuiteFile(self, file):
        if not file.startswith("testsuite") or file == os.path.basename(self.testCaseFile):
            return 0
        if file.find(self.app.getFullVersion()) == -1:
            return 0
        # Don't do this for extra versions, they appear anyway...
        for extraApp in self.app.extras:
            if file.find(extraApp.getFullVersion()) != -1:
                return 0
        return 1
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
    def expandChildEnvironmentReferences(self, referenceVars):
        for case in self.testcases:
            case.expandEnvironmentReferences(referenceVars)
    def size(self):
        size = 0
        for testcase in self.testcases:
            size += testcase.size()
        return size
    def getTestNames(self, fileName):
        testNames = []
        for testline in open(fileName).xreadlines():
            testName = testline.strip()
            if len(testName) > 0 and testName[0] != '#':
                testNames.append(testName)
        return testNames
# private:
    def getTestCases(self, filters, fileName, allVersions):
        testCaseList = []
        allowEmpty = 1
        for testName in self.getTestNames(fileName):
            if allVersions and self.alreadyContains(self.testcases, testName):
                continue
            if self.alreadyContains(testCaseList, testName):
                print "WARNING: the test", testName, "was included several times in the test suite file - please check!"
                continue

            allowEmpty = 0
            testPath = os.path.join(self.abspath, testName)
            testSuite = TestSuite(testName, testPath, self.app, filters, self, allVersions)
            if testSuite.valid:
                testCaseList.append(testSuite)
            else:
                testCase = TestCase(testName, testPath, self.app, filters, self)
                if testCase.valid:
                    testCaseList.append(testCase)
        if fileName == self.testCaseFile and (not allowEmpty and len(testCaseList) == 0):
            self.valid = 0
        return testCaseList
    def addTest(self, testName, testPath):
        testCase = TestCase(testName, testPath, self.app, [], self)
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
    def getFilterList(self):
        try:
            return self.target.getFilterList()
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
    def __init__(self, name, abspath, configFile, version, inputOptions):
        self.name = name
        self.abspath = abspath
        # Place to store reference to extra_version applications
        self.extras = []
        self.versions = version.split(".")
        if self.versions[0] == "":
            self.versions = []
        self.inputOptions = inputOptions
        self.configDir = MultiEntryDictionary()
        self.setConfigDefaults()
        extensions = self.getVersionFileExtensions(baseVersion=0)
        self.configDir.readValuesFromFile(configFile, name, extensions, insert=0)
        self.fullName = self.getConfigValue("full_name")
        debugLog.info("Found application " + repr(self))
        self.configObject = ConfigurationWrapper(self.getConfigValue("config_module"), inputOptions)
        self.cleanMode = self.configObject.getCleanMode()
        self.writeDirectory = self._getWriteDirectory(inputOptions)
        # Fill in the values we expect from the configurations, and read the file a second time
        self.configObject.setApplicationDefaults(self)
        self.setDependentConfigDefaults()
        extensions = self.getVersionFileExtensions(baseVersion=1)
        self.configDir.readValuesFromFile(configFile, name, extensions, insert=0, errorOnUnknown=1)
        personalFile = self.getPersonalConfigFile()
        self.configDir.readValuesFromFile(personalFile, insert=0, errorOnUnknown=1)
        self.checkout = self.makeCheckout(inputOptions.checkoutOverride())
        debugLog.info("Checkout set to " + self.checkout)
        self.optionGroups = self.createOptionGroups(inputOptions)
        self.useDiagnostics = self.setDiagnosticSettings(inputOptions)
        self.slowMotionReplaySpeed = self.setSlowMotionSettings(inputOptions)
        debugLog.info("Config file settings are: " + "\n" + repr(self.configDir.dict))
    def __repr__(self):
        return self.fullName
    def __cmp__(self, other):
        return cmp(self.name, other.name)
    def __hash__(self):
        return id(self)
    def getIndent(self):
        # Useful for printing with tests
        return ""
    def classId(self):
        return "test-app"
    def createCopy(self, version):
        configFile = os.path.join(self.abspath, "config." + self.name)
        return Application(self.name, self.abspath, configFile, version, self.inputOptions)
    def getPreviousWriteDirInfo(self, userName):
        userId = plugins.tmpString()
        if userName:
            if globalTmpDirectory == os.path.expanduser("~/texttesttmp"):
                return userName, globalTmpDirectory.replace(userId, userName)
            else:
                # hack for self-tests, don't replace user globally, only locally
                return userName, globalTmpDirectory
        else:
            return userId, globalTmpDirectory
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
        self.setConfigDefault("extra_version", [])
        self.setConfigDefault("base_version", [])
        self.setConfigDefault("unsaveable_version", [])
        self.setConfigDefault("diagnostics", {})
        self.setConfigDefault("copy_test_path", [])
        self.setConfigDefault("link_test_path", [])
        self.setConfigDefault("slow_motion_replay_speed", 0)
        # External viewing tools
        # Do this here rather than from the GUI: if applications can be run with the GUI
        # anywhere it needs to be set up
        self.setConfigDefault("add_shortcut_bar", 1)
        self.setConfigDefault("test_colours", self.getGuiColourDictionary())
        self.setConfigDefault("file_colours", self.getGuiColourDictionary())
        self.setConfigDefault("definition_file_stems", [ "input", "options", "environment", "usecase", "testsuite" ])
        self.setConfigDefault("gui_entry_overrides", {})
        self.setConfigDefault("gui_entry_options", { "" : [] })
        self.setConfigDefault("use_case_recorder", "")
        self.setConfigDefault("diff_program", "tkdiff")
        if os.name == "posix":
            self.setConfigDefault("view_program", "xemacs")
            self.setConfigDefault("follow_program", "tail -f")
        elif os.name == "dos" or os.name == "nt":
            self.setConfigDefault("view_program", "notepad")
            self.setConfigDefault("follow_program", "baretail")
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
        if not binary:
            raise BadConfigError, "config file entry 'binary' not defined"
        # Set values which default to other values
        self.setConfigDefault("interactive_action_module", self.getConfigValue("config_module"))
        if binary.endswith(".py"):
            self.setConfigDefault("interpreter", "python")
        else:
            self.setConfigDefault("interpreter", "")
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
    def setDiagnosticSettings(self, inputOptions):
        if inputOptions.has_key("diag"):
            return 1
        elif inputOptions.has_key("trace"):
            envVarName = self.getConfigValue("diagnostics")["trace_level_variable"]
            os.environ[envVarName] = inputOptions["trace"]
        return 0
    def setSlowMotionSettings(self, inputOptions):
        if inputOptions.has_key("actrep"):
            return self.getConfigValue("slow_motion_replay_speed")
        else:
            return 0
    def addToOptionGroup(self, group):
        if group.name.startswith("Select"):
            group.addOption("vs", "Version to select", self.getFullVersion())
        elif group.name.startswith("What"):
            group.addOption("c", "Use checkout")
            group.addOption("v", "Run this version", self.getFullVersion())
        elif group.name.startswith("How"):
            if self.getConfigValue("slow_motion_replay_speed"):
                group.addSwitch("actrep", "Run with slow motion replay")
            diagDict = self.getConfigValue("diagnostics")
            if diagDict.has_key("configuration_file"):
                group.addSwitch("diag", "Write target application diagnostics")
            if diagDict.has_key("trace_level_variable"):
                group.addOption("trace", "Target application trace level")
        elif group.name.startswith("Side"):
            group.addSwitch("x", "Write TextTest diagnostics")
        elif group.name.startswith("Invisible"):
            # Options that don't make sense with the GUI should be invisible there...
            group.addOption("a", "Applications containing")
            group.addOption("s", "Run this script")
            group.addOption("d", "Run tests at")
            group.addOption("tmp", "Write test-tmp files at")
            group.addOption("delay", "Between replayed actions, delay this long")
            group.addOption("record", "Record user actions to this script")
            group.addOption("replay", "Replay user actions from this script")
            group.addOption("recinp", "Record standard input to this script")
            group.addOption("slave", "Private: used to submit slave runs remotely")
            group.addOption("help", "Print help text")
            group.addSwitch("g", "use GUI", 1)
            group.addSwitch("gx", "use static GUI")
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
        root = os.path.expanduser(os.environ["TEXTTEST_TMP"])
        global globalTmpDirectory
        globalTmpDirectory = plugins.abspath(root)
        if not os.path.isdir(globalTmpDirectory):
            os.makedirs(globalTmpDirectory)
        localName = self.getTmpIdentifier().replace(":", "")
        if inputOptions.useStaticGUI():
            localName = "static_gui." + localName
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
    def createTestSuite(self, filters = None, allVersions = 0):
        if not filters:
            filters = self.configObject.getFilterList()

        success = 1
        for filter in filters:
            if not filter.acceptsApplication(self):
                success = 0
        suite = TestSuite(os.path.basename(self.abspath), self.abspath, self, filters, allVersions=allVersions)
        suite.expandEnvironmentReferences()
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
        doRemove = self.cleanMode & plugins.Configuration.CLEAN_BASIC
        if doRemove and os.path.isdir(self.writeDirectory):
            # Don't be somewhere under the directory when it's removed
            os.chdir(self.abspath)
            plugins.rmtree(self.writeDirectory)
    def tryCleanPreviousWriteDirs(self, rootDir, nameBase = ""):
        doRemove = self.cleanMode & plugins.Configuration.CLEAN_PREVIOUS
        if not doRemove or not os.path.isdir(rootDir):
            return
        currTmpString = nameBase + self.name + self.versionSuffix() + plugins.tmpString()
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
    def setConfigDefault(self, key, value):
        self.configDir[key] = value
    def makeCheckout(self, checkoutOverride):
        if checkoutOverride:
            checkout = checkoutOverride
        else:
            checkout = self.getConfigValue("default_checkout")
        checkoutLocation = os.path.expanduser(self.getConfigValue("checkout_location"))
        return self.makePathName(os.path.join(checkoutLocation, checkout))
    def getExecuteCommand(self, test):
        binary = self.getConfigValue("binary")
        if self.configDir.has_key("interpreter"):
            binary = self.configDir["interpreter"] + " " + binary
        return self.configObject.getExecuteCommand(binary, test)
    def checkBinaryExists(self):
        binary = self.getConfigValue("binary")
        if not os.path.isfile(binary):
            raise plugins.TextTestError, binary + " has not been built."
    def getEnvironment(self):
        env = [ ("TEXTTEST_CHECKOUT", self.checkout) ]
        return env + self.configObject.getApplicationEnvironment(self)
            
class OptionFinder(seqdict):
    def __init__(self):
        seqdict.__init__(self)
        self.startTime = plugins.localtime()
        self.buildOptions()
        self.directoryName = os.path.normpath(self.findDirectoryName())
        self._setUpLogging()
        self.setRunId()
        debugLog.debug(repr(self))
    def setRunId(self):
        global globalRunIdentifier
        if self.slaveRun():
            globalRunIdentifier = self["slave"]
        else:
            globalRunIdentifier = plugins.tmpString() + self.startTime
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
                if not os.path.isdir(writeDir):
                    try:
                        os.makedirs(writeDir)
                    except OSError:
                        # Not a reason not to work if we can't do this for some reason
                        pass
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
    def _disableDiags(self):
        rootLogger = log4py.Logger().get_root()        
        rootLogger.set_loglevel(log4py.LOGLEVEL_NONE)
    # Yes, we know that getopt exists. However it throws exceptions when it finds unrecognised things, and we can't do that...
    def buildOptions(self):                                                                                                              
        optionKey = None                                                                                                                 
        for item in sys.argv[1:]:                      
            if item[0] == "-":                         
                optionKey = self.stripMinuses(item)
                self[optionKey] = ""
            elif optionKey:
                if len(self[optionKey]):
                    self[optionKey] += " "
                self[optionKey] += item.strip()
    def stripMinuses(self, item):
        if item[1] == "-":
            return item[2:].strip()
        else:
            return item[1:].strip()
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
    def useGUI(self):
        return self.has_key("g") or self.useStaticGUI()
    def useStaticGUI(self):
        return self.has_key("gx")
    def slaveRun(self):
        return self.has_key("slave")
    def _getDiagnosticFile(self):
        if not os.environ.has_key("TEXTTEST_DIAGNOSTICS"):
            os.environ["TEXTTEST_DIAGNOSTICS"] = os.path.join(self.directoryName, "Diagnostics")
        return os.path.join(os.environ["TEXTTEST_DIAGNOSTICS"], "log4py.conf")
    def findDirectoryName(self):
        if self.has_key("d"):
            return plugins.abspath(self["d"])
        elif os.environ.has_key("TEXTTEST_HOME"):
            os.environ["TEXTTEST_HOME"] = plugins.abspath(os.environ["TEXTTEST_HOME"])
            return os.environ["TEXTTEST_HOME"]
        else:
            return os.getcwd()
    def getActionSequence(self, app):
        if self.useStaticGUI():
            return []
        
        if not self.has_key("s"):
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
            return self.getNonPython()

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
            
class MultiEntryDictionary(seqdict):
    def __init__(self):
        seqdict.__init__(self)
        self.currDict = self
    def readValuesFromFile(self, filename, appName = "", versions = [], insert=1, errorOnUnknown=0):
        self.currDict = self
        debugLog.info("Reading values from file " + os.path.basename(filename))
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
        # Must reset it for addConfigEntry, so that doesn't go wrong
        self.currDict = self
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
        entryName, entry = line.split(separator, 1)
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
            if not entry in self.currDict[entryName]:
                self.currDict[entryName].append(entry)
        elif currType == types.IntType:
            self.currDict[entryName] = int(entry)
        else:
            self.currDict[entryName] = entry        
