#!/usr/bin/env python
import os, sys, types, string, plugins, exceptions, log4py, shutil
from time import time
from fnmatch import fnmatch
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
        try:
            self.contents = os.listdir(self.dir)
            self.contents.sort()
        except OSError: # usually caused by people removing stuff externally
            self.contents = []
    def exists(self, fileName):
        if fileName.find("/") != -1:
            return os.path.exists(self.pathName(fileName))
        else:
            return fileName in self.contents
    def pathName(self, fileName):
        return os.path.join(self.dir, fileName)
    def findFilesMatching(self, pattern, allowedExtensions):
        matchingFiles = filter(lambda fileName : self.matchesPattern(fileName, pattern, allowedExtensions), self.contents)
        return map(self.pathName, matchingFiles)
    def matchesPattern(self, fileName, pattern, allowedExtensions):
        if not fnmatch(fileName, pattern):
            return False
        stem, versions = self.splitStem(fileName)
        return self.matchVersions(versions, allowedExtensions)
    def splitStem(self, fileName):
        parts = fileName.split(".")
        return parts[0], parts[1:]
    def findVersionList(self, fileName, stem):
        if fileName == stem:
            return []
        fileStem, versions = self.splitStem(fileName)
        if stem == fileStem:
            return versions
    def findVersionListMethod(self, versionListMethod):
        if versionListMethod:
            return versionListMethod
        else:
            return self.findVersionList
    def findVersionLists(self, stem, versionListMethod=None):
        methodToUse = self.findVersionListMethod(versionListMethod)
        versionLists = []
        versionInfo = {}
        for fileName in self.contents:
            versions = methodToUse(fileName, stem)
            if not versions is None:
                versionLists.append(versions)
                versionInfo[string.join(versions, ".")] = fileName
        return versionLists, versionInfo
    def findAndSortFiles(self, stem, allowed, priorityFunction, versionListMethod=None):
        versionLists, versionInfo = self.findVersionLists(stem, versionListMethod)
        versionLists = filter(lambda vlist: self.allVersionsAllowed(vlist, allowed), versionLists)
        versionLists.sort(priorityFunction)
        return map(lambda vlist: self.pathName(versionInfo[string.join(vlist, ".")]), versionLists)
    def findAllStems(self):
        stems = []
        for file in self.contents:
            stem, versionList = self.splitStem(file)
            if len(versionList) > 0 and not stem in stems:
                stems.append(stem)
        return stems
    def findAllFiles(self, stem, compulsory = [], forbidden = [], priorityFunction=None):
        versionLists, versionInfo = self.findVersionLists(stem)
        if len(compulsory) or len(forbidden):
            versionLists = filter(lambda vlist: self.matchVersions(vlist, compulsory, forbidden), versionLists)
        if priorityFunction:
            versionLists.sort(priorityFunction)
        return map(lambda vlist: self.pathName(versionInfo[string.join(vlist, ".")]), versionLists)
    def allVersionsAllowed(self, vlist, allowed):
        for version in vlist:
            if not version in allowed:
                return False
        return True
    def matchVersions(self, fileVersions, compulsory=[], forbidden=[]):
        if len(fileVersions) == 0:
            return True
        for version in fileVersions:
            if version in forbidden:
                return False
        for version in compulsory:
            if not version in fileVersions:
                return False
        return True

class EnvironmentReader:
    def __init__(self, app):
        self.app = app
        self.pathVars = self.getPathVars()
        self.diag = plugins.getDiagnostics("read environment")
    def read(self, test, referenceVars = []):
        self.diag.info("Reading environment for " + repr(test))
        self.app.setEnvironment(test)
        if test.parent == None:
            test.setEnvironment("TEXTTEST_CHECKOUT", self.app.checkout)
        elif isinstance(test, TestCase):
            # Always include the working directory of the test in PATH, to pick up fake
            # executables provided as test data. Allow for later expansion...
            for pathVar in self.pathVars:
                test.setEnvironment(pathVar, test.writeDirectory + os.pathsep + "$" + pathVar)

        self.app.readValues(test.environment, "environment", test.dircache)
        for key, value in test.environment.items():
            self.diag.info("Set " + key + " to " + value)
        # Should do this, but not quite yet...
        # self.properties.readValues("properties", self.dircache)
        self.diag.info("Expanding references for " + test.name)
        childReferenceVars = self.expandReferences(test, referenceVars)
        if isinstance(test, TestSuite):
            for subTest in test.testcases:
                self.read(subTest, childReferenceVars)
        test.tearDownEnvironment()
        self.diag.info("End Expanding " + test.name)
    def getPathVars(self):
        pathVars = [ "PATH" ]
        for dataFile in self.app.getDataFileNames():
            if dataFile.endswith(".py") and "PYTHONPATH" not in pathVars:
                pathVars.append("PYTHONPATH")
            elif (dataFile.endswith(".jar") or dataFile.endswith(".class")) and "CLASSPATH" not in pathVars:
                pathVars.append("CLASSPATH")
        return pathVars
    def expandReferences(self, test, referenceVars = []):
        childReferenceVars = copy(referenceVars)
        for var, value in test.environment.items():
            expValue = os.path.expandvars(value)
            if expValue != value:
                self.diag.info("Expanded variable " + var + " to " + expValue)
                # Check for self-referential variables: don't multiple-expand
                if value.find(var) == -1:
                    childReferenceVars.append((var, value))
                test.setEnvironment(var, expValue)
            test.setUpEnvVariable(var, expValue)
        for var, value in referenceVars:
            self.diag.info("Trying reference variable " + var)
            if test.environment.has_key(var):
                childReferenceVars.remove((var, value))
                continue
            expValue = os.path.expandvars(value)
            if expValue != os.getenv(var):
                test.setEnvironment(var, expValue)
                self.diag.info("Adding reference variable " + var + " as " + expValue)
                test.setUpEnvVariable(var, expValue)
            else:
                self.diag.info("Not adding reference " + var + " as same as local value " + expValue)
        return childReferenceVars
    
# Base class for TestCase and TestSuite
class Test(plugins.Observable):
    def __init__(self, name, description, dircache, app, parent = None):
        # Should notify which test it is
        plugins.Observable.__init__(self, passSelf=True)
        self.name = name
        self.description = description
        # There is nothing to stop several tests having the same name. Maintain another name known to be unique
        self.uniqueName = name
        self.app = app
        self.parent = parent
        self.dircache = dircache
        self.paddedName = self.name
        self.previousEnv = {}
        self.environment = MultiEntryDictionary()
        # Java equivalent of the environment mechanism...
        self.properties = MultiEntryDictionary()
        self.diag = plugins.getDiagnostics("test objects")
        # Test suites never change state, but it's convenient that they have one
        self.state = plugins.TestState("not_started", freeText=self.getDescription())
    def getDescription(self):
        description = plugins.extractComment(self.description)
        if description:
            return description
        else:
            return "<No description provided>"
    def refreshDescription(self):
        oldDesc = self.state.freeText
        self.state.freeText = self.getDescription()
        if oldDesc != self.state.freeText:
            self.notify("DescriptionChange")
    def classDescription(self):
        return self.classId().replace("-", " ")
    def readEnvironment(self):
        envReader = EnvironmentReader(self.app)
        envReader.read(self)
    def diagnose(self, message):
        self.diag.info("In test " + self.uniqueName + " : " + message)
    def getWordsInFile(self, stem):
        file = self.getFileName(stem)
        if file:
            contents = open(file).read().strip()
            return contents.split()
        else:
            return []
    def setEnvironment(self, var, value):
        self.environment[var] = value
    def getEnvironment(self, var, defaultValue=None):
        if self.environment.has_key(var):
            return self.environment[var]
        elif self.parent:
            return self.parent.getEnvironment(var, defaultValue)
        else:
            return os.getenv(var, defaultValue)
    def getTestRelPath(self, file):
        # test suites don't use this mechanism currently
        return ""
    def needsRecalculation(self):
        return False
    def defFileStems(self):
        return self.getConfigValue("definition_file_stems")
    def resultFileStems(self):
        stems = []
        defStems = self.defFileStems()
        for stem in self.dircache.findAllStems():
            if not stem in defStems:
                stems.append(stem)
        return stems
    def listStandardFiles(self, allVersions):
        resultFiles, defFiles = [],[]
        allowedExtensions = self.app.getFileExtensions()
        self.diagnose("Looking for all standard files")
        for stem in self.defFileStems():
            defFiles += self.listStdFilesWithStem(stem, allowedExtensions, allVersions)
        for stem in self.resultFileStems():
            resultFiles += self.listStdFilesWithStem(stem, allowedExtensions, allVersions)
        self.diagnose("Found " + repr(resultFiles) + " and " + repr(defFiles))
        return resultFiles, defFiles
    def listStdFilesWithStem(self, stem, allowedExtensions, allVersions):
        self.diagnose("Getting files for stem " + stem)
        files = []
        if allVersions:
            files += self.findAllStdFiles(stem)
        else:
            allFiles = self.dircache.findAndSortFiles(stem, allowedExtensions, self.app.compareVersionLists)
            if len(allFiles):
                files.append(allFiles[-1])
        return files
    def listDataFiles(self):
        existingDataFiles = []
        for dataFile in self.app.getDataFileNames():
            fileName = self.getFileName(dataFile)
            if fileName:
                existingDataFiles += self.listFiles(fileName, dataFile)
        return existingDataFiles
    def listFiles(self, fileName, dataFile):
        filesToIgnore = self.getCompositeConfigValue("test_data_ignore", dataFile)
        return self.listFilesFrom([ fileName ], filesToIgnore)
    def listFilesFrom(self, files, filesToIgnore):
        files.sort()
        dataFiles = []
        dirs = []
        self.diag.info("Listing files from " + repr(files) + ", ignoring " + repr(filesToIgnore))
        for file in files:
            if self.fileMatches(os.path.basename(file), filesToIgnore):
                continue
            if os.path.isdir(file) and not os.path.islink(file):
                dirs.append(file)
            else:
                dataFiles.append(file)
        for subdir in dirs:
            dataFiles.append(subdir)
            fileList = map(lambda file: os.path.join(subdir, file), os.listdir(subdir))
            dataFiles += self.listFilesFrom(fileList, filesToIgnore)
        return dataFiles
    def fileMatches(self, file, filesToIgnore):
        for ignFile in filesToIgnore:
            if fnmatch(file, ignFile):
                return True
        return False
    def findAllStdFiles(self, stem):
        if stem == "environment":
            otherApps = self.app.findOtherAppNames()
            self.diagnose("Finding environment files, excluding " + repr(otherApps))
            return self.dircache.findAllFiles(stem, forbidden=otherApps)
        else:
            return self.dircache.findAllFiles(stem, compulsory=[ self.app.name ])
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
        allowedExtensions = self.app.getFileExtensions()
        return self.dircache.findFilesMatching(pattern, allowedExtensions)
    def getFileName(self, stem, refVersion = None):
        self.diagnose("Getting file from " + stem)
        appToUse = self.app
        if refVersion:
            appToUse = self.app.getRefVersionApplication(refVersion)
        return appToUse._getFileName([ self.dircache ], stem)
    def getConfigValue(self, key, expandVars=True):
        return self.app.getConfigValue(key, expandVars)
    def getCompositeConfigValue(self, key, subKey, expandVars=True):
        return self.app.getCompositeConfigValue(key, subKey)
    def makePathName(self, fileName):
        if self.dircache.exists(fileName):
            return self.dircache.pathName(fileName)
        if self.parent:
            return self.parent.makePathName(fileName)
    def actionsCompleted(self):
        self.diagnose("All actions completed")
        if self.state.isComplete() and not self.state.lifecycleChange:
            self.diagnose("Completion notified")
            self.state.lifecycleChange = "complete"
            self.changeState(self.state)
    def getRelPath(self):
        return plugins.relpath(self.getDirectory(), self.app.getDirectory())
    def getDirectory(self, temporary=False, forFramework=False):
        return self.dircache.dir
    def rename(self, newName, newDescription):
        # Correct all testsuite files ...
        for testSuiteFileName in self.parent.findTestSuiteFiles():
            tests = plugins.readListWithComments(testSuiteFileName)            
            try:
                thisIndex = tests.index(self.name)
                newEntry = seqdict()
                self.description = plugins.replaceComment(tests[self.name], newDescription)
                newEntry[newName] = self.description
                del tests[self.name]
                tests.insert(thisIndex, newEntry)
                self.parent.writeNewTestSuiteFile(testSuiteFileName, tests)
            except:
                pass # The test wasn't present in this version ...

        # Create new directory, copy files if the new name is new (we might have
        # changed only the comment ...) (we don't want to rename dir, that can confuse CVS ...)
        if self.name != newName:
            newDir = self.parent.makeSubDirectory(newName)
            stdFiles, defFiles = self.listStandardFiles(allVersions=True)
            for sourceFile in stdFiles + defFiles:
                dirname, local = os.path.split(sourceFile)
                if dirname == self.getDirectory():
                    targetFile = os.path.join(newDir, local)
                    shutil.copy2(sourceFile, targetFile)
            dataFiles = self.listDataFiles()
            for sourcePath in dataFiles:
                if os.path.isdir(sourcePath):
                    continue
                targetPath = sourcePath.replace(self.getDirectory(), newDir)
                plugins.ensureDirExistsForFile(targetPath)
                shutil.copy2(sourcePath, targetPath)

            # Administration to get the new test in the GUI ...
            cache = DirectoryCache(newDir)
            if self.classId() == "test-case":
                test = TestCase(newName, newDescription, cache, self.app, self.parent)
            else:
                test = TestSuite(newName, newDescription, cache, self.app, self.parent)
            test.setObservers(self.observers)
            currIndex = self.parent.testcases.index(self)
            self.parent.testcases.insert(currIndex, test)
            test.readEnvironment()
            test.notify("Add")
            self.parent.removeTest(self, False)
        self.parent.contentChanged()
    def setUpEnvVariable(self, var, value):
        if os.environ.has_key(var):
            self.previousEnv[var] = os.environ[var]
        os.environ[var] = value
        self.diagnose("Setting " + var + " to " + os.environ[var])
    def setUpEnvironment(self, parents=False):
        if parents and self.parent:
            self.parent.setUpEnvironment(parents)
        for var, value in self.environment.items():
            self.setUpEnvVariable(var, value)
    def tearDownEnvironment(self, parents=0):
        # Note this has no effect on the real environment, but can be useful for internal environment
        # variables. It would be really nice if Python had a proper "unsetenv" function...
        for var in self.previousEnv.keys():
            self.diagnose("Restoring " + var + " to " + self.previousEnv[var])
            os.environ[var] = self.previousEnv[var]
        for var in self.environment.keys():
            if not self.previousEnv.has_key(var):
                # Set to empty string as a fake-remove. Some versions of
                # python do not have os.unsetenv and hence del only has an internal
                # effect. It's better to leave an empty value than to leak the set value
                self.diagnose("Removing " + var)
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
            if not self.isAcceptedBy(filter):
                self.diagnose("Rejected due to " + repr(filter))
                return False
        return True
    def size(self):
        return 1
    def refreshFiles(self):
        self.dircache.refresh()
    def filesChanged(self):
        self.refreshFiles()
        self.refreshDescription()
        self.notify("FileChange")    

class TestCase(Test):
    def __init__(self, name, description, abspath, app, parent):
        Test.__init__(self, name, description, abspath, app, parent)
        # Directory where test executes from and hopefully where all its files end up
        self.writeDirectory = os.path.join(app.writeDirectory, self.getRelPath())       
    def __repr__(self):
        return repr(self.app) + " " + self.classId() + " " + self.paddedName
    def classId(self):
        return "test-case"
    def testCaseList(self):
        return [ self ]
    def getDirectory(self, temporary=False, forFramework=False):
        if temporary:
            if forFramework:
                return os.path.join(self.writeDirectory, "framework_tmp")
            else:
                return self.writeDirectory
        else:
            return self.dircache.dir
    def getDescription(self):
        performanceFileName = self.getFileName("performance")
        if performanceFileName:
            performanceFile = open(performanceFileName, "r")
            lines = performanceFile.readlines()
            if len(lines) >= 2:
                performanceDescription = "\n\nExpected running time for the default version:\n" + lines[0] + lines[1]
            else:
                performanceDescription = "\n\nExpected running time for the default version:\n" + "".join(lines)
            performanceFile.close()
        else:
            performanceDescription = ""
        memoryFileName = self.getFileName("memory")
        if memoryFileName:
            memoryFile = open(memoryFileName, "r")
            memoryDescription = "\nExpected memory consumption for the default version:\n" + memoryFile.read()
            memoryFile.close()
        else:
            memoryDescription = ""
        desc = Test.getDescription(self)
        return "\nDescription:\n" + desc + \
               performanceDescription + \
               memoryDescription    
    def needsRecalculation(self):
        return self.state.isComplete() and self.state.needsRecalculation() and \
               os.path.isdir(self.getDirectory(temporary=1))
    def callAction(self, action):
        return action(self)
    def changeState(self, state):
        isCompletion = not self.state.isComplete() and state.isComplete()
        self.state = state
        self.diagnose("Change notified to state " + state.category)
        if state and state.lifecycleChange:
            notifyMethod = self.getNotifyMethod(isCompletion)
            notifyMethod("LifecycleChange", state, state.lifecycleChange)
            if state.lifecycleChange == "complete":
                notifyMethod("Complete")
    def getNotifyMethod(self, isCompletion):
        if isCompletion: 
            return self.notifyThreaded # use the idle handlers to avoid things in the wrong order
        else:
            # might as well do it instantly if the test isn't still "active"
            return self.notify
    def getStateFile(self):
        return self.makeTmpFileName("teststate", forFramework=True)
    def setWriteDirectory(self, newDir):
        self.writeDirectory = newDir        
    def makeWriteDirectory(self):
        self.diagnose("Created writedir at " + self.writeDirectory)
        plugins.ensureDirectoryExists(self.writeDirectory)
        frameworkTmp = self.getDirectory(temporary=1, forFramework=True)
        plugins.ensureDirectoryExists(frameworkTmp)
    def getTestRelPath(self, file):
        parts = file.split(self.getRelPath() + "/")
        if len(parts) >= 2:
            return parts[-1]
    def listTmpFiles(self):
        tmpFiles = []
        filelist = os.listdir(self.writeDirectory)
        filelist.sort()
        for file in filelist:
            if file.endswith("." + self.app.name):
                tmpFiles.append(os.path.join(self.writeDirectory, file))
        return tmpFiles
    def listUnownedTmpPaths(self):
        paths = []
        filelist = os.listdir(self.writeDirectory)
        filelist.sort()
        for file in filelist:
            if file == "framework_tmp" or file.endswith("." + self.app.name):
                continue
            fullPath = os.path.join(self.writeDirectory, file)
            paths += self.listFiles(fullPath, file)
        return paths
    def loadState(self, file):
        loaded, state = self.getNewState(file)
        self.changeState(state)
    def makeTmpFileName(self, stem, forComparison=1, forFramework=0):
        dir = self.getDirectory(temporary=1, forFramework=forFramework)
        if forComparison and not forFramework and stem.find(os.sep) == -1:
            return os.path.join(dir, stem + "." + self.app.name)
        else:
            return os.path.join(dir, stem)
    def getNewState(self, file):
        try:
            unpickler = Unpickler(file)
            newState = unpickler.load()
            return True, newState
        except UnpicklingError:
            return False, plugins.Unrunnable(briefText="read error", \
                                             freeText="Failed to read results file")
    def saveState(self):
        stateFile = self.getStateFile()
        if os.path.isfile(stateFile):
            # Don't overwrite previous saved state
            return

        file = plugins.openForWrite(stateFile)
        pickler = Pickler(file)
        pickler.dump(self.state)
        file.close()
    def isAcceptedBy(self, filter):
        return filter.acceptsTestCase(self)
            
class TestSuite(Test):
    def __init__(self, name, description, dircache, app, parent=None, forTestRuns=0):
        Test.__init__(self, name, description, dircache, app, parent)
        self.testcases = []
        contentFile = self.getContentFileName()
        if not contentFile:
            self.createContentFile()
        self.autoSortOrder = self.getConfigValue("auto_sort_test_suites")
    def getDescription(self):
        return "\nDescription:\n" + Test.getDescription(self)
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
                self.diagnose("Contents rejected due to " + repr(filter))
                return False
        return True
    def readTestNames(self, forTestRuns, warn = True):
        names = seqdict()
        # If we're not running tests, we're displaying information and should find all the sub-versions 
        for fileName in self.findTestSuiteFiles(forTestRuns):
            if warn:
                method = self.warnDuplicateTest
            else:
                method = None
            for name, comment in plugins.readListWithComments(fileName, duplicateMethod=self.warnDuplicateTest).items():
                self.diagnose("Read " + name)
                if warn and not self.fileExists(name):
                    plugins.printWarning("The test " + name + " could not be found.\nPlease check the file at " + fileName)
                    continue
                if not names.has_key(name):
                    names[name] = comment
        return names
    def warnDuplicateTest(self, testName, fileName):
        plugins.printWarning("The test " + testName + " was included several times in a test suite file.\n" + \
                             "Please check the file at " + fileName)
    def fileExists(self, name):
        return self.dircache.exists(name)
    def __repr__(self):
        return repr(self.app) + " " + self.classId() + " " + self.name
    def testCaseList(self):
        list = []
        for case in self.testcases:
            list += case.testCaseList()
        return list
    def getRunningTests(self):
        runningTests = filter(lambda test: not test.state.isComplete(), self.testCaseList())
        runningTests.reverse() # Best to start at the end to avoid race conditions
        return runningTests
    def classId(self):
        return "test-suite"
    def isEmpty(self):
        return len(self.testcases) == 0
    def callAction(self, action):
        return action.setUpSuite(self)
    def isAcceptedBy(self, filter):
        return filter.acceptsTestSuite(self)
    def findTestSuiteFiles(self, forTestRuns=0):
        contentFile = self.getContentFileName()
        if forTestRuns:
            return [ contentFile ]
        
        compulsoryExts = [ self.app.name ] + self.app.versions
        self.diagnose("Finding test suite files, using all versions in " + repr(compulsoryExts))
        versionFiles = []
        allFiles = self.dircache.findAllFiles("testsuite", compulsoryExts, priorityFunction=self.app.compareVersionLists)
        allFiles.reverse() # sort function works the wrong way round for us...
        for newFile in allFiles:
            if newFile != contentFile:
                versionFiles.append(newFile)
        return [ contentFile ] + versionFiles
    def getContentFileName(self):
        return self.getFileName("testsuite")
    def createContentFile(self):
        contentFile = self.getContentFileName()
        if contentFile:
            return
        contentFile = self.dircache.pathName("testsuite." + self.app.name)
        file = open(contentFile, "w")
        file.write("# Ordered list of tests in test suite. Add as appropriate\n\n")
        file.close()
        self.dircache.refresh()
    def contentChanged(self):
        # Here we assume that only order can change...
        self.refreshFiles()
        self.updateOrder(True)            
    def updateOrder(self, readTestNames = False):
        if readTestNames:
            orderedTestNames = self.getOrderedTestNames().keys()
        else:
            orderedTestNames = self.getOrderedTestNames(map(lambda l: l.name, self.testcases))

        newList = []
        for testName in orderedTestNames:
            for testcase in self.testcases:
                if testcase.name == testName:
                    newList.append(testcase)
                    break
        if newList != self.testcases:
            self.testcases = newList
            self.notify("ContentChange")
    def size(self):
        size = 0
        for testcase in self.testcases:
            size += testcase.size()
        return size
# private:
    # Observe: orderedTestNames can be both list and seqdict ... (it will be seqdict if read from file)
    def getOrderedTestNames(self, orderedTestNames = None): # We assume that tests exists, we just want to re-order ...
        if orderedTestNames is None:
            orderedTestNames = self.readTestNames(False, False)
        if self.autoSortOrder:
            testCaseNames = map(lambda l: l.name, filter(lambda l: l.classId() == "test-case", self.testcases))
            if self.autoSortOrder == 1:
                orderedTestNames.sort(lambda a, b: self.compareTests(True, testCaseNames, a, b))
            else:
                orderedTestNames.sort(lambda a, b: self.compareTests(False, testCaseNames, a, b))
        return orderedTestNames
    def getTestCases(self, filters, testNames, forTestRuns):
        testCaseList = []
        orderedTestNames = testNames.keys()
        testCaches = {}
        for testName in orderedTestNames:
            testCaches[testName] = self.createTestCache(testName)
        if self.autoSortOrder:
            testCaseNames = filter(lambda l: len(testCaches[l].findAllFiles("testsuite", compulsory = [ self.app.name ])) == 0, orderedTestNames)
            if self.autoSortOrder == 1:
                orderedTestNames.sort(lambda a, b: self.compareTests(True, testCaseNames, a, b))
            else:
                orderedTestNames.sort(lambda a, b: self.compareTests(False, testCaseNames, a, b))
        for testName in orderedTestNames:
            newTest = self.createTest(testName, testNames[testName], testCaches[testName], filters, forTestRuns)
            if newTest:
                testCaseList.append(newTest)
        return testCaseList
    def createTestCache(self, testName):
        return DirectoryCache(os.path.join(self.getDirectory(), testName))
    def createTest(self, testName, description, cache, filters = [], forTestRuns=0):
        allFiles = cache.findAllFiles("testsuite", compulsory = [ self.app.name ])
        if len(allFiles) > 0:
            return self.createTestSuite(testName, description, cache, filters, forTestRuns)
        else:
            return self.createTestCase(testName, description, cache, filters)
    def createTestCase(self, testName, description, cache, filters):
        newTest = TestCase(testName, description, cache, self.app, self)
        if newTest.isAcceptedByAll(filters):
            newTest.setObservers(self.observers)
            return newTest
    def createTestSuite(self, testName, description, cache, filters, forTestRuns):
        newSuite = TestSuite(testName, description, cache, self.app, self)
        if not newSuite.isAcceptedByAll(filters):
            return
        newSuite.setObservers(self.observers)
        if newSuite.readContents(filters, forTestRuns):
            return newSuite
    def findSubtest(self, testName):
        for test in self.testcases:
            if test.name == testName:
                return test
    def repositionTest(self, test, position):
        # Find test in list
        testSuiteFileName = self.getContentFileName()
        tests = plugins.readListWithComments(testSuiteFileName)
        try:
            currIndex = tests.index(test.name)
        except:
            return False

        # Depending on 'position', move test in list
        if position == "first":
            newIndex = 0
        elif position == "up":
            newIndex = currIndex - 1
        elif position == "down":
            newIndex = currIndex + 1
        else:
            newIndex = len(tests) - 1

        # To be on the safe side, check for out-of-bounds indices
        if newIndex < 0:
            newIndex = 0
        if newIndex >= len(tests):
            newIndex = len(tests) - 1

        # Delete old entry
        newEntry = seqdict()
        newEntry[test.name] = tests[test.name]
        del tests[test.name]
        tests.insert(newIndex, newEntry)
                
        # Write back to file, set new order and notify GUI
        self.writeNewTestSuiteFile(testSuiteFileName, tests)
        testNamesInOrder = self.readTestNames(False, False)
        newList = []
        for testName in testNamesInOrder.keys():
            test = self.findSubtest(testName)
            if test:
                newList.append(test)
                    
        self.testcases = newList
        self.notify("ContentChange")
        return True
    def hasNonDefaultTests(self):
        tests = plugins.readListWithComments(self.getContentFileName())
        return len(tests) < len(self.testcases)
    def sortTests(self, ascending = True):
        # Get testsuite list, sort in the desired order. Test
        # cases always end up before suites, regardless of name.
        for testSuiteFileName in self.findTestSuiteFiles():
            tests = plugins.readListWithComments(testSuiteFileName)
            testNames = map(lambda t: t.name, filter(lambda t: t.classId() == "test-case", self.testcases))
            tests.sort(lambda a, b: self.compareTests(ascending, testNames, a, b))

            # Save back, notify change
            self.writeNewTestSuiteFile(testSuiteFileName, tests)

        testNamesInOrder = self.readTestNames(False, False)
        newList = []
        for testName in testNamesInOrder.keys():
            for test in self.testcases:
                if test.name == testName:
                    newList.append(test)
                    break
        self.testcases = newList
        self.notify("ContentChange")
    def compareTests(self, ascending, testNames, a, b):
        if a in testNames:
            if b in testNames:
                if ascending:
                    return cmp(a.lower(), b.lower())
                else:
                    return cmp(b.lower(), a.lower())
            else:
                return -1
        else:
            if b in testNames:
                return 1
            else:
                if ascending:
                    return cmp(a.lower(), b.lower())        
                else:
                    return cmp(b.lower(), a.lower())        
    def writeNewTest(self, testName, description, placement):
        contentFileName = self.getContentFileName()
        currContent = plugins.readListWithComments(contentFileName) # have to re-read, we might have sorted
        newEntry = seqdict()
        newEntry[testName] = description
        currContent.insert(placement, newEntry)
        self.writeNewTestSuiteFile(contentFileName, currContent)
        return self.makeSubDirectory(testName)
    def addTestCaseWithPath(self, testPath):
        self.setUpEnvironment()
        newTest = self.addTestCaseWithPathAndEnv(testPath)
        self.tearDownEnvironment()
        return newTest
    def addTestCaseWithPathAndEnv(self, testPath):
        pathElements = testPath.split("/", 1)
        subSuite = self.findSubtest(pathElements[0])
        if len(pathElements) == 1:
            if not subSuite:
                return self.addTestCase(testPath)
            # if it already exists, don't return anything
        else:
            if not subSuite:
                subSuite = self.addTestSuite(pathElements[0])
            return subSuite.addTestCaseWithPath(pathElements[1])
    def addTestCase(self, testName, description="", placement=-1):
        return self.addTest(testName, description, placement, TestCase)
    def addTestSuite(self, testName, description="", placement=-1):
        return self.addTest(testName, description, placement, TestSuite)
    def addTest(self, testName, description, placement, className):
        cache = DirectoryCache(os.path.join(self.getDirectory(), testName))
        test = className(testName, description, cache, self.app, self)
        test.setObservers(self.observers)
        self.testcases.insert(placement, test) 
        test.readEnvironment()
        test.notify("Add")
        return test
    def getFollower(self, test):
        position = self.testcases.index(test)
        try:
            return self.testcases[position + 1]
        except IndexError:
            return None
    def removeTest(self, test, removeFromTestFile = True):
        try: 
            shutil.rmtree(test.getDirectory())
            self.testcases.remove(test)
            if removeFromTestFile:
                self.removeFromTestFile(test.name)
            test.notify("Remove")
        except OSError, e:
            errorStr = str(e)
            if errorStr.find("Permission") != -1:
                raise plugins.TextTestError, "Failed to remove test: didn't have sufficient write permission to the test files"
            else:
                raise plugins.TextTestError, errorStr
    def writeNewTestSuiteFile(self, fileName, content):
        testEntries = self.makeWriteEntries(content)
        output = string.join(testEntries, "\n")
        if not output.endswith("\n"):
            output += "\n"
        newFile = plugins.openForWrite(fileName)
        newFile.write(output.lstrip())
        newFile.close()
    def makeWriteEntries(self, content):
        entries = []
        for testName, comment in content.items():
            entries.append(self.testOutput(testName, comment))
        return entries
    def testOutput(self, testName, comment):
        if len(comment) == 0:
            return testName
        else:
            return "\n# " + comment.replace("\n", "\n# ").replace("# __EMPTYLINE__", "") + "\n" + testName
    def removeFromTestFile(self, testName):
        # Remove from all versions, since we've removed the actual
        # test dir, it's useless to keep the test anywhere ... 
        for contentFileName in self.findTestSuiteFiles():
            currContent = plugins.readListWithComments(contentFileName) # have to re-read, we might have sorted
            try:
                del currContent[testName]
                self.writeNewTestSuiteFile(contentFileName, currContent)
            except:
                pass # The test wasn't present in this version
    
class BadConfigError(RuntimeError):
    pass

class ConfigurationCall:
    def __init__(self, name, app):
        self.name = name
        self.app = app
        self.firstAttemptException = ""
        self.targetCall = eval("app.configObject." + name)
    def __call__(self, *args, **kwargs):
        try:
            return self.targetCall(*args, **kwargs)
        except TypeError:
            if self.firstAttemptException:
                self.raiseException()
            else:
                self.firstAttemptException = plugins.getExceptionString()
                return self(self.app, *args, **kwargs)
        except plugins.TextTestError:
            # Just pass it through here, these are deliberate
            raise
        except:
            self.raiseException()
    def raiseException(self):
        message = "Exception thrown by '" + self.app.getConfigValue("config_module") + \
                  "' configuration, while requesting '" + self.name + "'"
        if self.firstAttemptException:
            sys.stderr.write("Both attempts to call configuration failed, both exceptions follow :\n")
            sys.stderr.write(self.firstAttemptException + "\n" + plugins.getExceptionString())
        else:
            plugins.printException()
        raise BadConfigError, message
    
class Application:
    def __init__(self, name, dircache, versions, inputOptions):
        self.name = name
        self.dircache = dircache
        # Place to store reference to extra_version applications
        self.extras = []
        self.versions = versions    
        self.diag = plugins.getDiagnostics("application")
        self.inputOptions = inputOptions
        self.configDir = MultiEntryDictionary()
        self.configDocs = {}
        self.setConfigDefaults()
        self.readConfigFiles(configModuleInitialised=False)
        self.readValues(self.configDir, "config", self.dircache, insert=0)
        self.fullName = self.getConfigValue("full_name")
        self.diag.info("Found application " + repr(self))
        self.configObject = self.makeConfigObject()
        self.cleanMode = self.configObject.getCleanMode()
        self.rootTmpDir = self._getRootTmpDir()
        # Fill in the values we expect from the configurations, and read the file a second time
        self.configObject.setApplicationDefaults(self)
        self.setDependentConfigDefaults()
        self.readConfigFiles(configModuleInitialised=True)
        from guiplugins import interactiveActionHandler # yuck, we should make this work properly!
        personalFile = self.getPersonalConfigFile()
        if personalFile:
            self.configDir.readValues([ personalFile ], insert=0, errorOnUnknown=1)
        for module in self.getConfigValue("interactive_action_module"):
            interactiveActionHandler.loadModules.append(module)
        self.diag.info("Config file settings are: " + "\n" + repr(self.configDir.dict))
        self.writeDirectory = self.configObject.getWriteDirectoryName(self)
        self.diag.info("Write directory at " + self.writeDirectory)
        self.checkout = self.configObject.setUpCheckout(self)
        self.diag.info("Checkout set to " + self.checkout)
        self.optionGroups = self.createOptionGroups(inputOptions)
        interactiveActionHandler.setCommandOptionGroups(self.optionGroups)
    def __repr__(self):
        return self.fullName
    def __hash__(self):
        return id(self)
    def makeConfigObject(self):
        moduleName = self.getConfigValue("config_module")
        importCommand = "from " + moduleName + " import getConfig"
        try:
            exec importCommand
        except:
            if sys.exc_type == exceptions.ImportError:
                errorString = "No module named " + moduleName
                if str(sys.exc_value) == errorString:
                    raise BadConfigError, "could not find config_module " + moduleName
                elif str(sys.exc_value) == "cannot import name getConfig":
                    raise BadConfigError, "module " + moduleName + " is not intended for use as a config_module"
            plugins.printException()
            raise BadConfigError, "config_module " + moduleName + " contained errors and could not be imported"
        return getConfig(self.inputOptions)
    def updateConfigOptions(self, optionGroup):
        for key, option in optionGroup.options.items():
            if len(option.getValue()):
                self.configObject.optionMap[key] = option.getValue()
            elif self.configObject.optionMap.has_key(key):
                del self.configObject.optionMap[key]
    def __getattr__(self, name): # If we can't find a method, assume the configuration has got one
        if hasattr(self.configObject, name):
            return ConfigurationCall(name, self)
        else:
            raise AttributeError, "No such Application method : " + name 
    def getIndent(self):
        # Useful for printing with tests
        return ""
    def classId(self):
        return "test-app"
    def getDirectory(self):
        return self.dircache.dir
    def readConfigFiles(self, configModuleInitialised):
        if not configModuleInitialised:
            self.readExplicitConfigFiles(configModuleInitialised)
        self.readImportedConfigFiles(configModuleInitialised)
        self.readExplicitConfigFiles(configModuleInitialised)
    def readExplicitConfigFiles(self, configModuleInitialised):
        self.readValues(self.configDir, "config", self.dircache, insert=False, errorOnUnknown=configModuleInitialised)
    def readImportedConfigFiles(self, configModuleInitialised):
        self.configDir.readValues(self.getConfigFilesToImport(), insert=False, errorOnUnknown=configModuleInitialised)
    def readValues(self, multiEntryDict, stem, dircache, insert=True, errorOnUnknown=False):
        allowedExtensions = self.getFileExtensions()
        allFiles = dircache.findAndSortFiles(stem, allowedExtensions, self.compareVersionLists)
        self.diag.info("Reading values for " + stem + " from files : " + string.join(allFiles, "\n"))
        multiEntryDict.readValues(allFiles, insert, errorOnUnknown)
    def getConfigFilesToImport(self):
        return map(self.configPath, self.getConfigValue("import_config_file"))
    def configPath(self, fileName):
        if os.path.isabs(fileName):
            return fileName
        if self.dircache.exists(fileName):
            return self.dircache.pathName(fileName)
        oneLevelUp = os.path.join(os.getenv("TEXTTEST_HOME"), fileName)
        if os.path.isfile(oneLevelUp):
            return oneLevelUp
        else:
            raise BadConfigError, "Cannot find file '" + fileName + "' to import config file settings from"
    def getDataFileNames(self):
        return self.getConfigValue("link_test_path") + self.getConfigValue("copy_test_path") + \
               self.getConfigValue("partial_copy_test_path")
    def getFileName(self, dirList, stem, versionListMethod=None):
        dircaches = map(lambda dir: DirectoryCache(dir), dirList)
        return self._getFileName(dircaches, stem, versionListMethod=versionListMethod)
    def _getFileName(self, dircaches, stem, versionListMethod=None):
        allowedExtensions = self.getFileExtensions()
        for dircache in dircaches:
            allFiles = dircache.findAndSortFiles(stem, allowedExtensions, self.compareVersionLists, versionListMethod)
            self.diag.info("Files for stem " + stem + " found " + repr(allFiles) + " from " + repr(allowedExtensions))
            if len(allFiles):
                return allFiles[-1]
    def getRefVersionApplication(self, refVersion):
        return Application(self.name, self.dircache, refVersion.split("."), self.inputOptions)
    def getPreviousWriteDirInfo(self, previousTmpInfo):
        # previousTmpInfo can be either a directory, which should be returned if it exists,
        # a user name, which should be expanded and checked
        if len(previousTmpInfo) == 0:
            previousTmpInfo = self.rootTmpDir
        if os.path.isdir(previousTmpInfo):
            return previousTmpInfo
        else:
            # try as user name
            if previousTmpInfo.find("/") == -1 and previousTmpInfo.find("\\") == -1:
                return os.path.expanduser("~" + previousTmpInfo + "/texttesttmp")
            else:
                return previousTmpInfo
    def getPersonalConfigFile(self):
        personalDir = plugins.getPersonalConfigDir()
        if personalDir:
            personalFile = os.path.join(personalDir, "config")
            if os.path.isfile(personalFile):
                return personalFile
    def findOtherAppNames(self):
        names = []
        for configFile in self.dircache.findAllFiles("config"):
            appName = os.path.basename(configFile).split(".")[1]
            if appName != self.name and not appName in names:
                names.append(appName)
        return names
    def getExtraVersions(self, forUse=True):
        if forUse and not self.useExtraVersions():
            return []
        
        extraVersions = self.getConfigValue("extra_version")
        for extra in extraVersions:
            if extra in self.versions:
                return []
        return extraVersions
    def setConfigDefaults(self):
        self.setConfigDefault("binary", "", "Full path to the System Under Test")
        self.setConfigDefault("config_module", "default", "Configuration module to use")
        self.setConfigDefault("import_config_file", [], "Extra config files to use")
        self.setConfigDefault("full_name", string.upper(self.name), "Expanded name to use for application")
        self.setConfigDefault("extra_version", [], "Versions to be run in addition to the one specified")
        self.setConfigDefault("base_version", [], "Versions to inherit settings from")
        # various varieties of test data
        self.setConfigDefault("partial_copy_test_path", [], "Paths to be part-copied, part-linked to the temporary directory")
        self.setConfigDefault("copy_test_path", [], "Paths to be copied to the temporary directory when running tests")
        self.setConfigDefault("link_test_path", [], "Paths to be linked from the temp. directory when running tests")
        self.setConfigDefault("test_data_ignore", { "default" : [] }, \
                              "Elements under test data structures which should not be viewed or change-monitored")
        self.setConfigDefault("definition_file_stems", [ "environment", "testsuite" ], \
                              "files to be shown as definition files by the static GUI")
        self.setConfigDefault("unsaveable_version", [], "Versions which should not have results saved for them")
        self.setConfigDefault("version_priority", { "default": 99 }, \
                              "Mapping of version names to a priority order in case of conflict.") 
    def setDependentConfigDefaults(self):
        binary = self.getConfigValue("binary")
        # Set values which default to other values
        self.setConfigDefault("interactive_action_module", [ self.getConfigValue("config_module") ],
                              "Module to search for InteractiveActions for the GUI")
        self.setConfigDefault("interpreter", plugins.getInterpreter(binary), "Program to use as interpreter for the SUT")
    def createOptionGroups(self, inputOptions):
        groupNames = [ "Select Tests", "Basic", "Advanced", "Invisible" ]
        optionGroups = []
        for name in groupNames:
            group = plugins.OptionGroup(name)
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
            inputCheckout = self.inputOptions.get("c")
            if inputCheckout:
                checkout = inputCheckout
        if not version:
            version = self.getFullVersion()
        options = [ "-d", self.inputOptions.directoryName, "-a", self.name ]
        if version:
            options += [ "-v", version ]
        return options + self.configObject.getRunOptions(checkout)
    def addToOptionGroup(self, group):
        if group.name.startswith("Basic"):
            group.addOption("v", "Run this version", self.getFullVersion())
        elif group.name.startswith("Advanced"):
            group.addOption("xr", "Configure self-diagnostics from", self.inputOptions.getSelfDiagFile())
            group.addOption("xw", "Write self-diagnostics to", self.inputOptions.getSelfDiagWriteDir())
            group.addSwitch("x", "Enable self-diagnostics")
        elif group.name.startswith("Invisible"):
            # Options that don't make sense with the GUI should be invisible there...
            group.addOption("a", "Run Applications whose name contains")
            group.addOption("s", "Run this script")
            group.addOption("d", "Run as if TEXTTEST_HOME was")
            group.addSwitch("help", "Print configuration help text on stdout")
    def findOptionGroup(self, option, optionGroups):
        for optionGroup in optionGroups:
            if optionGroup.options.has_key(option) or optionGroup.switches.has_key(option):
                return optionGroup
    def _getRootTmpDir(self):
        if not os.getenv("TEXTTEST_TMP"):
            if os.name == "nt" and os.getenv("TEMP"):
                os.environ["TEXTTEST_TMP"] = os.getenv("TEMP").replace("\\", "/")
            else:
                os.environ["TEXTTEST_TMP"] = "~/texttesttmp"
        return os.path.expanduser(os.getenv("TEXTTEST_TMP"))
    def getStandardWriteDirectoryName(self):
        timeStr = plugins.startTimeString().replace(":", "")
        localName = self.name + self.versionSuffix() + "." + timeStr
        return os.path.join(self.rootTmpDir, localName)
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
    def createTestSuite(self, responders=[], filters=[], forTestRuns = True):
        if len(filters) == 0:
            filters = self.configObject.getFilterList(self)

        self.diag.info("Creating test suite with filters " + repr(filters))
        suite = TestSuite(os.path.basename(self.dircache.dir), "Root test suite", self.dircache, self)
        suite.setObservers(responders)
        suite.readContents(filters, forTestRuns)
        self.diag.info("SUCCESS: Created test suite of size " + str(suite.size()))
        suite.readEnvironment()
        self.verifyWithEnvironment(suite) # make sure everything's OK, given the basic environment
        return suite
    def verifyWithEnvironment(self, suite):
        suite.setUpEnvironment()
        try:
            self.configObject.verifyWithEnvironment(suite)
        finally:
            suite.tearDownEnvironment()
    def description(self, includeCheckout = False):
        description = "Application " + self.fullName
        if len(self.versions):
            description += ", version " + string.join(self.versions, ".")
        if includeCheckout and self.checkout:
            description += ", checkout " + self.checkout
        return description
    def filterUnsaveable(self, versions):
        saveableVersions = []
        unsaveableVersions = self.getConfigValue("unsaveable_version")
        for version in versions:
            if not version in unsaveableVersions:
                saveableVersions.append(version)
        return saveableVersions
    def getFileExtensions(self):
        return [ self.name ] + self.getConfigValue("base_version") + self.versions
    def compareVersionLists(self, vlist1, vlist2):
        explicitVersions = [ self.name ] + self.versions
        versionCount1 = self.intersectionCount(vlist1, explicitVersions)
        versionCount2 = self.intersectionCount(vlist2, explicitVersions)
        if versionCount1 != versionCount2:
            # More explicit versions implies higher priority
            return cmp(versionCount1, versionCount2)

        baseVersions = self.getConfigValue("base_version")
        baseCount1 = self.intersectionCount(vlist1, baseVersions)
        baseCount2 = self.intersectionCount(vlist2, baseVersions)
        if baseCount1 != baseCount2:
            # More base versions implies higher priority
            return cmp(baseCount1, baseCount2)

        priority1 = self.getVersionListPriority(vlist1)
        priority2 = self.getVersionListPriority(vlist2)
        # Low number implies higher priority...
        return cmp(priority2, priority1)
    def intersectionCount(self, vlist1, vlist2):
        count = 0
        for ver in vlist1:
            if ver in vlist2:
                count += 1
        return count
    def getVersionListPriority(self, vlist):
        if len(vlist) == 0:
            return 99
        else:
            return min(map(self.getVersionPriority, vlist))
    def getVersionPriority(self, version):
        return self.getCompositeConfigValue("version_priority", version)
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
        self.diag.info("Made root directory at " + self.writeDirectory)
    def removeWriteDirectory(self):
        if self.cleanMode.cleanSelf and os.path.isdir(self.writeDirectory):
            self.diag.info("Removing write directory at " + self.writeDirectory)
            plugins.rmtree(self.writeDirectory)
    def tryCleanPreviousWriteDirs(self, rootDir):
        if not self.cleanMode.cleanPrevious or not os.path.isdir(rootDir):
            return
        searchParts = [ self.name ] + self.versions
        for file in os.listdir(rootDir):
            fileParts = file.split(".")
            if fileParts[:-1] == searchParts:
                previousWriteDir = os.path.join(rootDir, file)
                if os.path.isdir(previousWriteDir):
                    print "Removing previous write directory", previousWriteDir
                    plugins.rmtree(previousWriteDir, attempts=3)
    def getActionSequence(self):
        actionSequenceFromConfig = self.configObject.getActionSequence()
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
        value = self.configDir.get(key)
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
    def getCompositeConfigValue(self, key, subKey, expandVars=True):
        dict = self.getConfigValue(key, expandVars)
        listVal = []
        for currSubKey, currValue in dict.items():
            if fnmatch(subKey, currSubKey):
                if type(currValue) == types.ListType:
                    listVal += currValue
                else:
                    return currValue
        # A certain amount of duplication here - hard to see how to avoid it
        # without compromising performance though...
        defValue = dict.get("default")
        if defValue is not None:
            if type(defValue) == types.ListType:
                listVal += defValue
                return listVal
            else:
                return defValue
        else:
            if len(listVal) > 0:
                return listVal
    def addConfigEntry(self, key, value, sectionName = ""):
        self.configDir.addEntry(key, value, sectionName)
    def setConfigDefault(self, key, value, docString = ""):
        self.configDir[key] = value
        if len(docString) > 0:
            self.configDocs[key] = docString
            
class OptionFinder(plugins.OptionFinder):
    def __init__(self):
        plugins.OptionFinder.__init__(self, sys.argv[1:])
        self.directoryName = os.path.normpath(self.findDirectoryName()).replace("\\", "/")
        os.environ["TEXTTEST_HOME"] = self.directoryName
        self.diagConfigFile = None
        self.diagWriteDir = None
        self.setUpLogging()
        self.diag = plugins.getDiagnostics("option finder")
        self.diag.info("Replaying from " + repr(os.getenv("USECASE_REPLAY_SCRIPT")))
        self.diag.info(repr(self))
    def setUpLogging(self):
        if self.has_key("x"):
            self.diagConfigFile = self.getSelfDiagFile()
            self.diagWriteDir = self.getSelfDiagWriteDir()
        elif os.environ.has_key("TEXTTEST_LOGCONFIG"):
            self.diagConfigFile = os.getenv("TEXTTEST_LOGCONFIG")
            self.diagWriteDir = os.getenv("TEXTTEST_DIAGDIR")

        if self.diagConfigFile and not os.path.isfile(self.diagConfigFile):
            print "Could not find diagnostic file at", self.diagConfigFile, ": cannot run with diagnostics"
            self.diagConfigFile = None
            self.diagWriteDir = None

        if self.diagWriteDir:
            plugins.ensureDirectoryExists(self.diagWriteDir)
            if self.has_key("x"):
                for file in os.listdir(self.diagWriteDir):
                    if file.endswith(".diag"):
                        os.remove(os.path.join(self.diagWriteDir, file))

        self.configureLog4py()
    def configureLog4py(self):
        # Don't use the default locations, particularly current directory causes trouble
        if len(log4py.CONFIGURATION_FILES) > 1:
            del log4py.CONFIGURATION_FILES[1]
        if self.diagConfigFile:
            # Assume log4py's configuration file refers to files relative to TEXTTEST_DIAGDIR
            os.environ["TEXTTEST_DIAGDIR"] = self.diagWriteDir
            print "TextTest will write diagnostics in", self.diagWriteDir, "based on file at", self.diagConfigFile
            # To set new config files appears to require a constructor...
            rootLogger = log4py.Logger(log4py.TRUE, self.diagConfigFile)
        else:
            rootLogger = log4py.Logger().get_root()        
            rootLogger.set_loglevel(log4py.LOGLEVEL_NONE)
    def findVersionList(self):
        versionList = []
        for version in plugins.commasplit(self.get("v", "")):
            if version in versionList:
                plugins.printWarning("Same version '" + version + "' requested more than once, ignoring.")
            else:
                versionList.append(version)
        return versionList
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
    def helpMode(self):
        return self.has_key("help")
    def runScript(self):
        return self.get("s")
    def getSelfDiagFile(self):
        return self.get("xr", os.path.join(self.getDefaultSelfDiagDir(), "log4py.conf"))
    def getSelfDiagWriteDir(self):
        return self.get("xw", self.getDefaultSelfDiagDir())
    def getDefaultSelfDiagDir(self):
        return os.path.join(self.directoryName, "Diagnostics")
    def findDirectoryName(self):
        if self.has_key("d"):
            return plugins.abspath(self["d"])
        elif os.environ.has_key("TEXTTEST_HOME"):
            return os.environ["TEXTTEST_HOME"]
        else:
            return os.getcwd()
    
# Compulsory responder to generate application events. Always present. See respond module
class ApplicationEventResponder(Responder):
    def notifyLifecycleChange(self, test, state, changeDesc):
        if changeDesc.find("saved") != -1 or changeDesc.find("recalculated") != -1:
            # don't generate application events when a test is saved or recalculated...
            return
        eventName = "test " + test.uniqueName + " to " + changeDesc
        category = test.uniqueName
        timeDelay = self.getTimeDelay()
        self.scriptEngine.applicationEvent(eventName, category, timeDelay)

    def getTimeDelay(self):
        try:
            return int(os.getenv("TEXTTEST_FILEWAIT_SLEEP", 1))
        except ValueError:
            return 1
    def notifyAllComplete(self):
        self.scriptEngine.applicationEvent("completion of test actions")
    def notifyCloseDynamic(self, test, name):
        self.scriptEngine.applicationEvent(name + " GUI to be closed")
    def notifyContentChange(self, suite):
        eventName = "suite " + suite.uniqueName + " to change order"
        self.scriptEngine.applicationEvent(eventName, suite.uniqueName)

# Simple responder that collects completion notifications and sends one out when
# it thinks everything is done.
class AllCompleteResponder(Responder,plugins.Observable):
    def __init__(self, inputOptions):
        Responder.__init__(self)
        plugins.Observable.__init__(self)
        self.unfinishedTests = 0
    def addSuites(self, suites):
        self.unfinishedTests = sum([ suite.size() for suite in suites ])
    def notifyComplete(self, test):
        if self.unfinishedTests > 1:
            self.unfinishedTests -= 1
        else:
            self.notify("AllComplete")
            
class MultiEntryDictionary(seqdict):
    def __init__(self):
        seqdict.__init__(self)
        self.currDict = self
    def readValues(self, fileNames, insert=True, errorOnUnknown=False):
        self.currDict = self
        for filename in fileNames:
            for line in plugins.readList(filename):
                self.parseConfigLine(line, insert, errorOnUnknown)
            self.currDict = self
    def parseConfigLine(self, line, insert, errorOnUnknown):
        if line.startswith("[") and line.endswith("]"):
            self.currDict = self.changeSectionMarker(line[1:-1], errorOnUnknown)
        elif line.find(":") != -1:
            self.addLine(line, insert, errorOnUnknown)
        else:
            plugins.printWarning("Could not parse config line " + line)
    def changeSectionMarker(self, name, errorOnUnknown):
        if name == "end":
            return self
        if self.has_key(name) and type(self[name]) == types.DictType:
            return self[name]
        if errorOnUnknown:
            print "ERROR: Config section name '" + name + "' not recognised."
        return self
    def addLine(self, line, insert, errorOnUnknown, separator = ':'):
        entryName, entry = line.split(separator, 1)
        self.addEntry(self.expandvars(entryName), entry, "", insert, errorOnUnknown)
    def getVarName(self, name):
        if name.startswith("${"):
            return name[2:-1]
        else:
            return name[1:]
    def expandvars(self, name):
        # os.path.expandvars fails on windows, assume entire name is the env variable
        if name.startswith("$"):
            varName = self.getVarName(name)
            value = os.getenv(varName)
            if value:
                return value
            else:
                return name
        else:
            return name
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
