#!/usr/bin/env python
import os, sys, types, string, plugins, exceptions, log4py, shutil, operator
from time import time
from fnmatch import fnmatch
from ndict import seqdict
from copy import copy
from cPickle import Pickler, loads, UnpicklingError
from respond import Responder
from threading import Lock
from sets import Set, ImmutableSet

helpIntro = """
Note: the purpose of this help is primarily to document derived configurations and how they differ from the
defaults. To find information on the configurations provided with texttest, consult the documentation at
http://www.texttest.org
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

    def hasStem(self, stem):
        for fileName in self.contents:
            if fileName.startswith(stem):
                return True
        return False

    def exists(self, fileName):
        if fileName.find("/") != -1:
            return os.path.exists(self.pathName(fileName))
        else:
            return fileName in self.contents

    def pathName(self, fileName):
        return os.path.join(self.dir, fileName)
    def findFilesMatching(self, pattern, predicate):
        matchingFiles = filter(lambda fileName : self.matchesPattern(fileName, pattern, predicate), self.contents)
        return map(self.pathName, matchingFiles)

    def matchesPattern(self, fileName, pattern, versionPredicate):
        if not fnmatch(fileName, pattern):
            return False
        stem, versions = self.splitStem(fileName)
        return versionPredicate(versions)

    def splitStem(self, fileName):
        parts = fileName.split(".")
        return parts[0], ImmutableSet(parts[1:])

    def findVersionSet(self, fileName, stem):
        if fileName.startswith(stem):
            fileStem, versions = self.splitStem(fileName[len(stem):])
            if len(fileStem) == 0:
                return versions
            
    def findVersionSetMethod(self, versionSetMethod):
        if versionSetMethod:
            return versionSetMethod
        else:
            return self.findVersionSet

    def findAllFiles(self, stem, extensionPred=None):
        versionSets = self.findVersionSets(stem, extensionPred)
        return reduce(operator.add, versionSets.values(), [])
    
    def findVersionSets(self, stem, predicate, versionSetMethod=None):
        if stem.find("/") != -1:
            root, local = os.path.split(stem)
            newCache = DirectoryCache(os.path.join(self.dir, root))
            return newCache.findVersionSets(local, predicate, versionSetMethod)
            
        methodToUse = self.findVersionSetMethod(versionSetMethod)
        versionSets = seqdict()
        for fileName in self.contents:
            versionSet = methodToUse(fileName, stem)
            if versionSet is not None and (predicate is None or predicate(versionSet)):
                versionSets.setdefault(versionSet, []).append(self.pathName(fileName))
        return versionSets
       
    def findAllStems(self):
        stems = []
        for file in self.contents:
            stem, versionSet = self.splitStem(file)
            if len(stem) > 0 and len(versionSet) > 0 and not stem in stems:
                stems.append(stem)
        return stems

class MultiEntryDictionary(seqdict):
    def __init__(self):
        seqdict.__init__(self)
        self.currDict = self
        self.aliases = {}
    def setAlias(self, aliasName, realName):
        self.aliases[aliasName] = realName
    def getEntryName(self, fromConfig):
        return self.aliases.get(fromConfig, fromConfig)
    def readValues(self, fileNames, insert=True, errorOnUnknown=False):
        self.currDict = self
        for filename in fileNames:
            for line in plugins.readList(filename):
                self.parseConfigLine(line, insert, errorOnUnknown)
            self.currDict = self
    def parseConfigLine(self, line, insert, errorOnUnknown):
        if line.startswith("[") and line.endswith("]"):
            sectionName = self.getEntryName(line[1:-1])
            self.currDict = self.changeSectionMarker(sectionName, errorOnUnknown)
        elif line.find(":") != -1:
            key, value = line.split(":", 1)
            entryName = self.getEntryName(os.path.expandvars(key))
            self.addEntry(entryName, value, "", insert, errorOnUnknown)
        else:
            plugins.printWarning("Could not parse config line " + line, stdout = False, stderr = True)
    def changeSectionMarker(self, name, errorOnUnknown):
        if name == "end":
            return self
        if self.has_key(name) and type(self[name]) == types.DictType:
            return self[name]
        if errorOnUnknown:
            plugins.printWarning("Config section name '" + name + "' not recognised.", stdout = False, stderr = True)
        return self
    def getVarName(self, name):
        if name.startswith("${"):
            return name[2:-1]
        else:
            return name[1:]
    def addEntry(self, entryName, entry, sectionName="", insert=0, errorOnUnknown=1):
        if sectionName:
            self.currDict = self[sectionName]
        entryExists = self.currDict.has_key(entryName)
        if entryExists:
            self.insertEntry(entryName, entry)
        else:
            if insert or not self.currDict is self:
                self.currDict[entryName] = self.castEntry(entry)
            elif errorOnUnknown:
                plugins.printWarning("Config entry name '" + entryName + "' not recognised.", stdout = False, stderr = True)
        # Make sure we reset...
        if sectionName:
            self.currDict = self
    def getDictionaryValueType(self):
        val = self.currDict.values()
        if len(val) == 0:
            return types.StringType
        else:
            return type(val[0])

    def castEntry(self, entry):
        if type(entry) != types.StringType:
            return entry
        dictValType = self.getDictionaryValueType()
        if dictValType == types.ListType:
            return [ entry ]
        else:
            return dictValType(entry)
    
    def insertEntry(self, entryName, entry):
        currType = type(self.currDict[entryName]) 
        if currType == types.ListType:
            if entry == "{CLEAR LIST}":
                self.currDict[entryName] = []
            elif not entry in self.currDict[entryName]:
                self.currDict[entryName].append(entry)
        elif currType == types.DictType:
            self.currDict = self.currDict[entryName]
            self.insertEntry("default", entry)
            self.currDict = self
        else:
            self.currDict[entryName] = currType(entry)

    
class Callable:
    def __init__(self, method, *args):
        self.method = method
        self.extraArgs = args
    def __call__(self, *calledArgs):
        toUse = calledArgs + self.extraArgs
        return self.method(*toUse)

class TestEnvironment(seqdict):
    def __init__(self, populateFunction):
        seqdict.__init__(self)
        self.diag = plugins.getDiagnostics("read environment")
        self.populateFunction = populateFunction
        self.populated = False
    def checkPopulated(self):
        if not self.populated:
            self.populated = True
            self.populateFunction()
    def definesValue(self, var):
        self.checkPopulated()
        return self.has_key(var)
    def getValues(self, onlyVars = []):
        self.checkPopulated()
        values = {}
        for key, value in self.items():
            if len(onlyVars) == 0 or key in onlyVars:
                values[key] = value
        # copy in the external environment last
        for var, value in os.environ.items():
            if not values.has_key(var):
                values[var] = value
        return values
    
    def getSingleValue(self, var, defaultValue=None):
        self.checkPopulated()
        return self._getSingleValue(var, defaultValue)
    def _getSingleValue(self, var, defaultValue=None):
        value = self.get(var, os.getenv(var, defaultValue))
        self.diag.info("Single: got " + var + " = " + repr(value))
        return value
    def getSelfReference(self, var, originalVar):
        if var == originalVar:
            return self._getSingleValue(var)
    def getSingleValueNoSelfRef(self, var, originalVar):
        if var != originalVar:
            return self._getSingleValue(var)
    def storeVariables(self, vars):
        for var, valueOrMethod in vars:
            newValue = self.expandSelfReferences(var, valueOrMethod)
            self.diag.info("Storing " + var + " = " + newValue)
            self[var] = newValue

        while self.expandVariables():
            pass
    def expandSelfReferences(self, var, valueOrMethod):
        if type(valueOrMethod) == types.StringType:
            getenvFunc = Callable(self.getSelfReference, var)
            return os.path.expandvars(valueOrMethod, getenvFunc)
        else:
            return valueOrMethod(var, self._getSingleValue(var, ""))
    def expandVariables(self):
        expanded = False
        for var, value in self.items():
            getenvFunc = Callable(self.getSingleValueNoSelfRef, var)
            newValue = os.path.expandvars(value, getenvFunc)
            if newValue != value:
                expanded = True
                self.diag.info("Expanded " + var + " = " + newValue)
                self[var] = newValue
        return expanded    

# Have the description as our free text, for display in the static GUI
class NotStarted(plugins.TestState):
    def __init__(self, freeTextMethod):
        plugins.TestState.__init__(self, "not_started")
        self.freeTextMethod = freeTextMethod
    def getFreeText(self):
        if len(self.freeText) == 0:
            self.freeText = self.freeTextMethod()
        return self.freeText
        
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
        populateFunction = Callable(app.setEnvironment, self)
        self.environment = TestEnvironment(populateFunction)
        # Java equivalent of the environment mechanism...
        self.properties = MultiEntryDictionary()
        self.diag = plugins.getDiagnostics("test objects")
        # Test suites never change state, but it's convenient that they have one
        self.state = NotStarted(self.getDescription)
    def __repr__(self):
        return repr(self.app) + " " + self.classId() + " " + self.name
    def paddedRepr(self):
        return repr(self.app) + " " + self.classId() + " " + self.paddedName()
    def paddedName(self):
        if not self.parent:
            return self.name
        maxLength = max(len(test.name) for test in self.parent.testcases)
        return self.name.ljust(maxLength)
    def getDescription(self):
        description = plugins.extractComment(self.description)
        if description:
            return description
        else:
            return "<No description provided>"

    def setName(self, newName):
        # Create new directory, copy files if the new name is new (we might have
        # changed only the comment ...) (we don't want to rename dir, that can confuse CVS ...)
        if self.name != newName:
            newDir = self.parent.makeSubDirectory(newName)
            if os.path.isdir(self.getDirectory()):
                self.copyTestContents(newDir)
                self.removeFiles()

            origRelPath = self.getRelPath()
            self.name = newName
            self.dircache = DirectoryCache(newDir)
            self.notify("NameChange", origRelPath)
            if self.parent.autoSortOrder:
                self.parent.updateOrder()
        
    def setDescription(self, newDesc):
        if self.description != newDesc:
            self.description = newDesc
            self.refreshDescription()
        
    def refreshDescription(self):
        oldDesc = self.state.freeText
        self.state.freeText = self.getDescription()
        if oldDesc != self.state.freeText:
            self.notify("DescriptionChange")
    def classDescription(self):
        return self.classId().replace("-", " ")
    
    def diagnose(self, message):
        self.diag.info("In test " + self.uniqueName + " : " + message)
    def getWordsInFile(self, stem):
        file = self.getFileName(stem)
        if file:
            contents = open(file).read().strip()
            return contents.split()
        else:
            return []
    def setUniqueName(self, newName):
        if newName != self.uniqueName:
            self.notify("UniqueNameChange", newName)
            self.uniqueName = newName
    def setEnvironment(self, var, value, propFile=None):
        if propFile:
            self.addProperty(var, value, propFile)
        else:
            self.environment[var] = value
    def addProperty(self, var, value, propFile):
        if not self.properties.has_key(propFile):
            self.properties.addEntry(propFile, {}, insert=1)
        self.properties.addEntry(var, value, sectionName = propFile, insert=1)
            
    def getEnvironment(self, var, defaultValue=None):
        return self.environment.getSingleValue(var, defaultValue)
    def hasEnvironment(self, var):
        return self.environment.definesValue(var)
    def getTestRelPath(self, file):
        # test suites don't use this mechanism currently
        return ""
    def needsRecalculation(self):
        return False
    def defFileStems(self):
        return self.getConfigValue("definition_file_stems")
    def resultFileStems(self):
        stems = []
        exclude = self.defFileStems() + self.app.getDataFileNames()
        for stem in self.dircache.findAllStems():
            if not stem in exclude:
                stems.append(stem)
        return stems
    def listStandardFiles(self, allVersions):
        resultFiles, defFiles = [],[]
        self.diagnose("Looking for all standard files")
        for stem in self.defFileStems():
            defFiles += self.listStdFilesWithStem(stem, allVersions)
        for stem in self.resultFileStems():
            resultFiles += self.listStdFilesWithStem(stem, allVersions)
        self.diagnose("Found " + repr(resultFiles) + " and " + repr(defFiles))
        return resultFiles, defFiles
    def listStdFilesWithStem(self, stem, allVersions):
        self.diagnose("Getting files for stem " + stem)
        files = []
        if allVersions:
            files += self.findAllStdFiles(stem)
        else:
            currFile = self.getFileName(stem)
            if currFile:
                files.append(currFile)
        return files
    def listDataFiles(self):
        existingDataFiles = []
        for dataFile in self.getDataFileNames():
            self.diagnose("Searching for data files called " + dataFile)
            for fileName in self.dircache.findAllFiles(dataFile):
                for fullPath in self.listFiles(fileName, dataFile):
                    if not fullPath in existingDataFiles:
                        existingDataFiles.append(fullPath)

        self.diagnose("Found data files as " + repr(existingDataFiles))
        return existingDataFiles
    def listFiles(self, fileName, dataFile):
        filesToIgnore = self.getCompositeConfigValue("test_data_ignore", dataFile)
        return self.listFilesFrom([ fileName ], filesToIgnore)
    def fullPathList(self, dir):
        return map(lambda file: os.path.join(dir, file), os.listdir(dir))
    def listExternallyEditedFiles(self):
        if self.dircache.exists("file_edits"):
            rootDir = self.dircache.pathName("file_edits")
            fileList = self.fullPathList(rootDir)
            filesToIgnore = self.getCompositeConfigValue("test_data_ignore", "file_edits")
            return rootDir, self.listFilesFrom(fileList, filesToIgnore)
        else:
            return None, []
    def listFilesFrom(self, files, filesToIgnore=[]):
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
            dataFiles += self.listFilesFrom(self.fullPathList(subdir), filesToIgnore)
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
            otherAppExcludor = lambda vset: len(vset.intersection(otherApps)) == 0
            return self.dircache.findAllFiles(stem, otherAppExcludor)
        else:
            return self.app._getAllFileNames([ self.dircache ], stem, allVersions=True)
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
        pred = self.app.getExtensionPredicate(allVersions=False)
        return self.dircache.findFilesMatching(pattern, pred)
    def getFileName(self, stem, refVersion = None):
        self.diagnose("Getting file from " + stem)
        appToUse = self.app
        if refVersion:
            appToUse = self.app.getRefVersionApplication(refVersion)
        return appToUse._getFileName([ self.dircache ], stem)
    def getPathName(self, stem, configName=None):
        return self.pathNameMethod(stem, configName, self.app._getFileName)
    def getAllPathNames(self, stem, configName=None):
        return self.pathNameMethod(stem, configName, self.app._getAllFileNames)
    def pathNameMethod(self, stem, configName, method):
        if configName is None:
            configName = stem
        dirCaches = self.getDirCachesToRoot(configName)
        self.diagnose("Directories to be searched: " + repr([ d.dir for d in dirCaches ]))
        return method(dirCaches, stem)
    def getAllTestsToRoot(self):
        tests = [ self ]
        if self.parent:
            tests = self.parent.getAllTestsToRoot() + tests
        return tests
        
    def getDirCachesToRoot(self, configName):
        fromTests = [ test.dircache for test in self.getAllTestsToRoot() ]
        dirNames = self.getCompositeConfigValue("extra_search_directory", configName)
        dirNames.reverse() # lowest priroity comes first, as above
        return self.app.getExtraDirCaches(dirNames) + fromTests
    
    def getAllFileNames(self, stem, refVersion = None):
        self.diagnose("Getting file from " + stem)
        appToUse = self.app
        if refVersion:
            appToUse = self.app.getRefVersionApplication(refVersion)
        return appToUse._getAllFileNames([ self.dircache ], stem)
    def getConfigValue(self, key, expandVars=True):
        return self.app.getConfigValue(key, expandVars, self.getEnvironment)
    def getDataFileNames(self):
        return self.app.getDataFileNames(self.getEnvironment)
    def getCompositeConfigValue(self, key, subKey, expandVars=True):
        return self.app.getCompositeConfigValue(key, subKey, expandVars, self.getEnvironment)
    def actionsCompleted(self):
        self.diagnose("All actions completed")
        if self.state.isComplete():
            if not self.state.lifecycleChange:
                self.diagnose("Completion notified")
                self.state.lifecycleChange = "complete"
                self.changeState(self.state)
        else:
            self.notify("Complete")
    def getRelPath(self):
        if self.parent:
            parentPath = self.parent.getRelPath()
            if parentPath:
                return os.path.join(parentPath, self.name)
            else:
                return self.name
        else:
            return ""
    def getDirectory(self, temporary=False, forFramework=False):
        return self.dircache.dir
    def positionInParent(self):
        if self.parent:
            return self.parent.testcases.index(self)
        else:
            return 0
    def removeFiles(self):
        dir = self.getDirectory()
        if os.path.isdir(dir):
            shutil.rmtree(dir)
    def remove(self, removeFromTestFile=True):
        if self.parent: # might have already removed the enclosing suite
            self.parent.removeTest(self, removeFromTestFile)
            return True
        else:
            return False
    def rename(self, newName, newDescription):
        # Correct all testsuite files ...
        for testSuiteFileName in self.parent.findTestSuiteFiles():
            self.parent.testSuiteFileHandler.rename(testSuiteFileName, self.name, newName, newDescription)

        self.setName(newName)
        self.setDescription(newDescription)
        
    def copyTestContents(self, newDir):
        stdFiles, defFiles = self.listStandardFiles(allVersions=True)
        for sourceFile in stdFiles + defFiles:
            dirname, local = os.path.split(sourceFile)
            if dirname == self.getDirectory():
                targetFile = os.path.join(newDir, local)
                shutil.copy2(sourceFile, targetFile)
        root, extFiles = self.listExternallyEditedFiles()
        dataFiles = self.listDataFiles() + extFiles
        for sourcePath in dataFiles:
            if os.path.isdir(sourcePath):
                continue
            targetPath = sourcePath.replace(self.getDirectory(), newDir)
            plugins.ensureDirExistsForFile(targetPath)
            shutil.copy2(sourcePath, targetPath)

    def getRunEnvironment(self, onlyVars = []):
        return self.environment.getValues(onlyVars)
    def createPropertiesFiles(self):
        self.environment.checkPopulated()
        for var, value in self.properties.items():
            propFileName = self.makeTmpFileName(var + ".properties", forComparison=0)
            file = open(propFileName, "w")
            for subVar, subValue in value.items():
                file.write(subVar + " = " + subValue + "\n")
    def getIndent(self):
        relPath = self.getRelPath()
        if not len(relPath):
            return ""
        dirCount = string.count(relPath, "/") + 1
        return " " * (dirCount * 2) 
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
    def refresh(self, filters):
        self.refreshFiles()
        self.notify("FileChange")
    
class TestCase(Test):
    def __init__(self, name, description, abspath, app, parent):
        Test.__init__(self, name, description, abspath, app, parent)
        # Directory where test executes from and hopefully where all its files end up
        self.writeDirectory = os.path.join(app.writeDirectory, app.name + app.versionSuffix(), self.getRelPath())       
    def classId(self):
        return "test-case"
    def testCaseList(self, filters=[]):
        if self.isAcceptedByAll(filters):
            return [ self ]
        else:
            return []
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
        if not os.path.isdir(self.writeDirectory):
            return tmpFiles
        filelist = os.listdir(self.writeDirectory)
        filelist.sort()
        for file in filelist:
            if file.endswith("." + self.app.name):
                tmpFiles.append(os.path.join(self.writeDirectory, file))
        return tmpFiles
    def getAllTmpFiles(self): # Also checks comparison files, if present.
        files = self.listTmpFiles()
        if len(files) == 0:
            if self.state.hasResults():
                for comparison in self.state.allResults:
                    if comparison.stdFile: # New files have no std file ...
                        files.append(os.path.basename(comparison.stdFile))
        return files
    def listUnownedTmpPaths(self):
        paths = []
        filelist = os.listdir(self.writeDirectory)
        filelist.sort()
        for file in filelist:
            if file == "framework_tmp" or file == "file_edits" or file.endswith("." + self.app.name):
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
            # Would like to do load(file) here... but it doesn't work with universal line endings, see Python bug 1724366
            # http://sourceforge.net/tracker/index.php?func=detail&aid=1724366&group_id=5470&atid=105470
            newState = loads(file.read())
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

# class for caching and managing changes to test suite files
class TestSuiteFileHandler:
    def __init__(self):
        self.cache = {}

    def fileEdited(self, fileName):
        if self.cache.has_key(fileName):
            del self.cache[fileName]
            
    def read(self, fileName, warn=False, ignoreCache=False):
        if not ignoreCache:
            cached = self.cache.get(fileName)
            if cached:
                return cached

        tests = plugins.readListWithComments(fileName, self.getDuplicateMethod(warn))
        self.cache[fileName] = tests
        return tests
    
    def getDuplicateMethod(self, warn):
        if warn:
            return self.warnDuplicateTest

    def warnDuplicateTest(self, testName, fileName):
        plugins.printWarning("The test " + testName + " was included several times in a test suite file.\n" + \
                             "Please check the file at " + fileName)

    def write(self, fileName, content):
        testEntries = self.makeWriteEntries(content)
        output = "\n".join(testEntries)
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

    def add(self, fileName, *args):
        cache = self.read(fileName)
        self.addToCache(cache, *args)
        self.write(fileName, cache)

    def addToCache(self, cache, testName, description, index):
        newEntry = seqdict()
        newEntry[testName] = description
        cache.insert(index, newEntry)
        
    def remove(self, fileName, testName):
        cache = self.read(fileName)
        description, index = self.removeFromCache(cache, testName)
        if description is not None:
            self.write(fileName, cache)

    def removeFromCache(self, cache, testName):
        description = cache.get(testName)
        if description is not None:
            index = cache.index(testName)
            del cache[testName]
            return description, index
        else:
            return None, None
        
    def rename(self, fileName, oldName, newName, newDescription):
        cache = self.read(fileName)
        description, index = self.removeFromCache(cache, oldName)
        if description is None:
            return False

        # intended to preserve comments that aren't tied to a test
        descToUse = plugins.replaceComment(description, newDescription)
        self.addToCache(cache, newName, descToUse, index)
        self.write(fileName, cache)
        return True
    
    def reposition(self, fileName, testName, newIndex):
        cache = self.read(fileName)
        description, index = self.removeFromCache(cache, testName)
        if description is None:
            return False

        self.addToCache(cache, testName, description, newIndex)
        self.write(fileName, cache)
        return True

    def sort(self, fileName, comparator):
        tests = self.read(fileName)
        tests.sort(comparator)
        self.write(fileName, tests)

    
            
class TestSuite(Test):
    testSuiteFileHandler = TestSuiteFileHandler()
    def __init__(self, name, description, dircache, app, parent=None):
        Test.__init__(self, name, description, dircache, app, parent)
        self.testcases = []
        contentFile = self.getContentFileName()
        if not contentFile:
            self.createContentFile()
        self.autoSortOrder = self.getConfigValue("auto_sort_test_suites")
    def getDescription(self):
        return "\nDescription:\n" + Test.getDescription(self)
            
    def readContents(self, filters, initial=True):
        testNames = self.readTestNames()
        self.createTestCases(filters, testNames, initial)
        if len(self.testcases) == 0 and len(testNames) > 0:
            # If the contents are filtered away, don't include the suite 
            return False

        for filter in filters:
            if not filter.acceptsTestSuiteContents(self):
                self.diagnose("Contents rejected due to " + repr(filter))
                return False
        return True
    def readTestNames(self, warn=True, ignoreCache=False):
        names = seqdict()
        fileName = self.getContentFileName()
        if not fileName:
            return names
        for name, comment in self.testSuiteFileHandler.read(fileName, warn, ignoreCache).items():
            self.diagnose("Read " + name)
            if warn and not self.fileExists(name):
                plugins.printWarning("The test " + name + " could not be found.\nPlease check the file at " + fileName)
                continue
            if not names.has_key(name):
                names[name] = comment
        return names
    def findTestCases(self, version):
        versionFile = self.getFileName("testsuite", version)        
        newTestNames = self.testSuiteFileHandler.read(versionFile)
        newTestList = []
        for testCase in self.testcases:
            if testCase.name in newTestNames:
                newTestList.append(testCase)
        return newTestList

    def fileExists(self, name):
        return self.dircache.exists(name)
    def testCaseList(self, filters=[]):
        list = []
        if not self.isAcceptedByAll(filters):
            return list
        for case in self.testcases:
            list += case.testCaseList(filters)
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
    def findTestSuiteFiles(self):
        contentFile = self.getContentFileName()
        versionFiles = []
        allFiles = self.app._getAllFileNames([ self.dircache ], "testsuite", allVersions=True)
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
    def contentChanged(self, fileEdit=""):
        if fileEdit:
            self.testSuiteFileHandler.fileEdited(fileEdit)
        # Here we assume that only order can change...
        self.refreshFiles()
        self.updateOrder(True, fileEdit)            
    def updateOrder(self, readTestNames=False, fileEdit=""):
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
            self.notify("ContentChange", fileEdit)
    def size(self):
        size = 0
        for testcase in self.testcases:
            size += testcase.size()
        return size
    def maxIndex(self):
        return len(self.testcases) - 1
    def refresh(self, filters):
        self.diagnose("refreshing!")
        Test.refresh(self, filters)
        newTestNames = self.readTestNames(ignoreCache=True)
        for test in self.testcases:
            if test.name not in newTestNames:
                self.diagnose("removing " + repr(test))
                self.testcases.remove(test)
                test.notify("Remove")

        for testName, desc in newTestNames.items():
            existingTest = self.findSubtest(testName)
            if existingTest:
                existingTest.setDescription(desc)
                existingTest.refresh(filters)
                testClass = self.getSubtestClass(existingTest.dircache)
                if existingTest.__class__ != testClass:
                     self.diagnose("changing type for " + repr(existingTest))
                     self.testcases.remove(existingTest)
                     existingTest.notify("Remove")
                     self.createTestOrSuite(testName, desc, existingTest.dircache, filters, initial=False)
            else:
                self.diagnose("creating new test called '" + testName + "'")
                dirCache = self.createTestCache(testName)
                self.createTestOrSuite(testName, desc, dirCache, filters, initial=False)
        self.updateOrder(readTestNames=True)
        
# private:
    # Observe: orderedTestNames can be both list and seqdict ... (it will be seqdict if read from file)
    def getOrderedTestNames(self, orderedTestNames = None): # We assume that tests exists, we just want to re-order ...
        if orderedTestNames is None:
            orderedTestNames = self.readTestNames(warn=False)
        if self.autoSortOrder:
            testCaseNames = map(lambda l: l.name, filter(lambda l: l.classId() == "test-case", self.testcases))
            if self.autoSortOrder == 1:
                orderedTestNames.sort(lambda a, b: self.compareTests(True, testCaseNames, a, b))
            else:
                orderedTestNames.sort(lambda a, b: self.compareTests(False, testCaseNames, a, b))
        return orderedTestNames
    def createTestCases(self, filters, testNames, initial):
        if self.autoSortOrder:
            self.createAndSortTestCases(filters, testNames, initial)
        else:
            for testName, desc in testNames.items():
                dirCache = self.createTestCache(testName)
                self.createTestOrSuite(testName, desc, dirCache, filters, initial)

    def createAndSortTestCases(self, filters, testNames, initial):
        orderedTestNames = testNames.keys()
        testCaches = {}
        for testName in orderedTestNames:
            testCaches[testName] = self.createTestCache(testName)

        testCaseNames = filter(lambda l: not testCaches[l].hasStem("testsuite"), orderedTestNames)
        if self.autoSortOrder == 1:
            orderedTestNames.sort(lambda a, b: self.compareTests(True, testCaseNames, a, b))
        else:
            orderedTestNames.sort(lambda a, b: self.compareTests(False, testCaseNames, a, b))

        for testName in orderedTestNames:
            dirCache = testCaches[testName]
            self.createTestOrSuite(testName, testNames[testName], dirCache, filters, initial)

    def createTestOrSuite(self, testName, description, dirCache, filters, initial=True):
        className = self.getSubtestClass(dirCache)
        subTest = self.createSubtest(testName, description, dirCache, className)
        if subTest.isAcceptedByAll(filters) and \
               (className is TestCase or subTest.readContents(filters, initial)):
            self.testcases.append(subTest)
            subTest.notify("Add", initial)
                
    def createTestCache(self, testName):
        return DirectoryCache(os.path.join(self.getDirectory(), testName))
    def getSubtestClass(self, cache):
        allFiles = self.app._getAllFileNames([ cache ], "testsuite", allVersions=True)
        if len(allFiles) > 0:
            return TestSuite
        else:
            return TestCase

    def createSubtest(self, testName, description, cache, className):
        test = className(testName, description, cache, self.app, self)
        test.setObservers(self.observers)
        return test
    
    def addTestCase(self, *args, **kwargs):
        return self.addTest(TestCase, *args, **kwargs)
    def addTestSuite(self, *args, **kwargs):
        return self.addTest(TestSuite, *args, **kwargs)
    def addTest(self, className, testName, description="", placement=-1, postProcFunc=None):
        cache = self.createTestCache(testName)
        test = self.createSubtest(testName, description, cache, className)
        if postProcFunc:
            postProcFunc(test)
        self.testcases.insert(placement, test) 
        test.notify("Add", initial=False)
        return test
    def addTestCaseWithPath(self, testPath):
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
    def findSubtestWithPath(self, testPath):
        if len(testPath) == 0:
            return self
        pathElements = testPath.split("/", 1)
        subTest = self.findSubtest(pathElements[0])
        if subTest:
            if len(pathElements) > 1:
                return subTest.findSubtestWithPath(pathElements[1])
            else:
                return subTest
            
    def findSubtest(self, testName):
        for test in self.testcases:
            if test.name == testName:
                return test
    def repositionTest(self, test, newIndex):
        # Find test in list
        testSuiteFileName = self.getContentFileName()
        if not self.testSuiteFileHandler.reposition(testSuiteFileName, test.name, newIndex):
            return False

        testNamesInOrder = self.readTestNames(warn=False)
        newList = []
        for testName in testNamesInOrder.keys():
            test = self.findSubtest(testName)
            if test:
                newList.append(test)
                    
        self.testcases = newList
        self.notify("ContentChange")
        return True
    def sortTests(self, ascending = True):
        # Get testsuite list, sort in the desired order. Test
        # cases always end up before suites, regardless of name.
        for testSuiteFileName in self.findTestSuiteFiles():
            testNames = map(lambda t: t.name, filter(lambda t: t.classId() == "test-case", self.testcases))
            comparator = lambda a, b: self.compareTests(ascending, testNames, a, b)
            self.testSuiteFileHandler.sort(testSuiteFileName, comparator)

        testNamesInOrder = self.readTestNames(warn=False)
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

    def copyTest(self, test, newName, newDesc, placement):
        testDir = self.writeNewTest(newName, newDesc, placement)
        test.copyTestContents(testDir)
        return self.addTest(test.__class__, os.path.basename(testDir), newDesc, placement)
        
    def writeNewTest(self, testName, description, placement):
        contentFileName = self.getContentFileName()
        self.testSuiteFileHandler.add(contentFileName, testName, description, placement)
        return self.makeSubDirectory(testName)
    def getFollower(self, test):
        try:
            position = self.testcases.index(test)
            return self.testcases[position + 1]
        except (ValueError, IndexError):
            pass
    def removeTest(self, test, removeFromTestFile = True):
        try:
            test.removeFiles()
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
    def removeFromTestFile(self, testName):
        # Remove from all versions, since we've removed the actual
        # test dir, it's useless to keep the test anywhere ... 
        for contentFileName in self.findTestSuiteFiles():
            self.testSuiteFileHandler.remove(contentFileName, testName)
        
    
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
        # Cache all environment files in the whole suite to stop constantly re-reading them
        self.envFiles = {}
        self.versions = versions    
        self.diag = plugins.getDiagnostics("application")
        self.inputOptions = inputOptions
        self.setUpConfiguration()
        self.writeDirectory = self.getWriteDirectory()
        self.rootTmpDir = os.path.dirname(self.writeDirectory)
        self.diag.info("Write directory at " + self.writeDirectory)
        self.checkout = self.configObject.setUpCheckout(self)
        self.diag.info("Checkout set to " + self.checkout)
        self.optionGroups = self.createOptionGroups(inputOptions)
    def __repr__(self):
        return self.fullName + self.versionSuffix()
    def __hash__(self):
        return id(self)

    def setUpConfiguration(self):
        self.configDir = MultiEntryDictionary()
        self.configDocs = {}
        self.extraDirCaches = {}
        self.setConfigDefaults()
        self.readConfigFiles(configModuleInitialised=False)
        self.readValues(self.configDir, "config", self.dircache, insert=0)
        self.fullName = self.getConfigValue("full_name")
        self.diag.info("Found application " + repr(self))
        self.configObject = self.makeConfigObject()
        # Fill in the values we expect from the configurations, and read the file a second time
        self.configObject.setApplicationDefaults(self)
        self.setDependentConfigDefaults()
        self.readConfigFiles(configModuleInitialised=True)
        personalFile = self.getPersonalConfigFile()
        if personalFile:
            self.configDir.readValues([ personalFile ], insert=0, errorOnUnknown=1)
        self.diag.info("Config file settings are: " + "\n" + repr(self.configDir.dict))
        
    def makeExtraDirCache(self, envDir):
        if envDir == "":
            return
            
        if os.path.isabs(envDir) and os.path.isdir(envDir):
            return DirectoryCache(envDir)

        rootPath = os.path.join(self.inputOptions.directoryName, envDir)
        if os.path.isdir(rootPath):
            return DirectoryCache(rootPath)
        appPath = os.path.join(self.getDirectory(), envDir)
        if os.path.isdir(appPath):
            return DirectoryCache(appPath)

    def getExtraDirCaches(self, dirNames):
        dirCaches = []
        for dirName in dirNames:
            if self.extraDirCaches.has_key(dirName):
                cached = self.extraDirCaches.get(dirName)
                if cached:
                    dirCaches.append(cached)
            else:
                dirCache = self.makeExtraDirCache(dirName)
                if dirCache:
                    self.extraDirCaches[dirName] = dirCache
                    dirCaches.append(dirCache)
                else:
                    self.extraDirCaches[dirName] = None # don't repeat the warning
                    plugins.printWarning("The directory '" + dirName + "' could not be found, ignoring 'extra_search_directory' config entry.")
        return dirCaches
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
        allFiles = self._getAllFileNames([ dircache ], stem)
        self.diag.info("Reading values for " + stem + " from files : " + "\n".join(allFiles))
        multiEntryDict.readValues(allFiles, insert, errorOnUnknown)
    def setEnvironment(self, test):
        test.environment.diag.info("Reading environment for " + repr(test))
        envFiles = test.getAllPathNames("environment")
        envVars = map(self.readEnvironment, envFiles)
        allVars = reduce(operator.add, envVars, [])
        allProps = []
        for suite in test.getAllTestsToRoot():
            vars, props = self.configObject.getConfigEnvironment(suite)
            allVars += vars
            allProps += props

        test.environment.storeVariables(allVars)
        for var, value, propFile in allProps:
            test.addProperty(var, value, propFile)

    def readEnvironment(self, envFile):
        if self.envFiles.has_key(envFile):
            return self.envFiles[envFile]

        envDir = MultiEntryDictionary()
        envDir.readValues([ envFile ])
        envVars = envDir.items()
        self.envFiles[envFile] = envVars
        return envVars
    def getConfigFilesToImport(self):
        return map(self.configPath, self.getConfigValue("import_config_file"))
    def configPath(self, fileName):
        if os.path.isabs(fileName):
            return fileName
        dirCacheNames = self.getCompositeConfigValue("extra_search_directory", fileName)
        dirCacheNames.append(".") # pick up the root directory
        dirCaches = self.getExtraDirCaches(dirCacheNames)
        dirCaches.append(self.dircache)
        configPath = self._getFileName(dirCaches, fileName)
        if not configPath:
            raise BadConfigError, "Cannot find file '" + fileName + "' to import config file settings from"
        return os.path.normpath(configPath)
    
    def getDataFileNames(self, getenvFunc=os.getenv):
        allNames = self.getConfigValue("link_test_path", getenvFunc=getenvFunc) + \
                   self.getConfigValue("copy_test_path", getenvFunc=getenvFunc) + \
                   self.getConfigValue("partial_copy_test_path", getenvFunc=getenvFunc)
        # Don't manage data that has an external path name, only accept absolute paths built by ourselves...
        return filter(lambda name: name.find(self.writeDirectory) != -1 or not os.path.isabs(name), allNames)
    def getFileName(self, dirList, stem, versionSetMethod=None):
        dircaches = map(lambda dir: DirectoryCache(dir), dirList)
        return self._getFileName(dircaches, stem, versionSetMethod=versionSetMethod)
    def getAllFileNames(self, dirList, stem, versionSetMethod=None):
        dircaches = map(lambda dir: DirectoryCache(dir), dirList)
        return self._getAllFileNames(dircaches, stem, versionSetMethod=versionSetMethod)
    def _getFileName(self, dircaches, stem, versionSetMethod=None):
        allFiles = self._getAllFileNames(dircaches, stem, versionSetMethod=versionSetMethod)
        if len(allFiles):
            return allFiles[-1]

    def _getAllFileNames(self, dircaches, stem, allVersions=False, versionSetMethod=None):
        versionPred = self.getExtensionPredicate(allVersions)
        versionSets = seqdict()
        for dircache in dircaches:
            # Sorts into order most specific first
            currVersionSets = dircache.findVersionSets(stem, versionPred, versionSetMethod)
            for vset, files in currVersionSets.items():
                versionSets.setdefault(vset, []).extend(files)

        if allVersions:
            versionSets.sort(self.compareForDisplay)
        else:
            versionSets.sort(self.compareForPriority)
        allFiles =  reduce(operator.add, versionSets.values(), [])
        self.diag.info("Files for stem " + stem + " found " + repr(allFiles))
        return allFiles

    def getRefVersionApplication(self, refVersion):
        return Application(self.name, self.dircache, refVersion.split("."), self.inputOptions)
    def getPreviousWriteDirInfo(self, previousTmpInfo):
        # previousTmpInfo can be either a directory, which should be returned if it exists,
        # a user name, which should be expanded and checked
        if previousTmpInfo:
            previousTmpInfo = os.path.expanduser(previousTmpInfo)
        else:
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
        names = Set()
        for configFile in self.dircache.findAllFiles("config"):
            appName = os.path.basename(configFile).split(".")[1]
            if appName != self.name:
                names.add(appName)
        return names
    def setConfigDefaults(self):
        self.setConfigDefault("executable", "", "Full path to the System Under Test")
        self.setConfigAlias("binary", "executable")
        self.setConfigDefault("config_module", "default", "Configuration module to use")
        self.setConfigDefault("import_config_file", [], "Extra config files to use")
        self.setConfigDefault("full_name", self.name.upper(), "Expanded name to use for application")
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
        self.setConfigDefault("extra_search_directory", { "default" : [] }, "Additional directories to search for TextTest files")
        self.setConfigAlias("test_data_searchpath", "extra_search_directory")
        self.setConfigAlias("extra_config_directory", "extra_search_directory")
    def setDependentConfigDefaults(self):
        executable = self.getConfigValue("executable")
        # Set values which default to other values
        self.setConfigDefault("interactive_action_module", self.getConfigValue("config_module") + "_gui",
                              "Module to search for InteractiveActions for the GUI")
        self.setConfigDefault("interpreter", plugins.getInterpreter(executable), "Program to use as interpreter for the SUT")
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
    def addToOptionGroup(self, group):
        if group.name.startswith("Select"):
            group.addOption("a", "App names containing", description="Select tests for which the application name matches the entered text. The text can be a regular expression.")
        elif group.name.startswith("Basic"):
            group.addOption("v", "Run this version", self.getFullVersion())
        elif group.name.startswith("Advanced"):
            group.addOption("xr", "Configure self-diagnostics from", self.inputOptions.getSelfDiagFile())
            group.addOption("xw", "Write self-diagnostics to", self.inputOptions.getSelfDiagWriteDir())
            group.addSwitch("x", "Enable self-diagnostics")
        elif group.name.startswith("Invisible"):
            # Options that don't make sense with the GUI should be invisible there...
            group.addOption("s", "Run this script")
            group.addOption("d", "Run as if TEXTTEST_HOME was")
            group.addSwitch("help", "Print configuration help text on stdout")
    def findOptionGroup(self, option, optionGroups):
        for optionGroup in optionGroups:
            if optionGroup.options.has_key(option) or optionGroup.switches.has_key(option):
                return optionGroup
    
    def getFullVersion(self, forSave = 0):
        versionsToUse = self.versions
        if forSave:
            versionsToUse = self.filterUnsaveable(self.versions)
        return ".".join(versionsToUse)
    def versionSuffix(self):
        fullVersion = self.getFullVersion()
        if len(fullVersion) == 0:
            return ""
        return "." + fullVersion
    def makeTestSuite(self, responders, otherDir=None):
        if otherDir:
            dircache = DirectoryCache(otherDir)
        else:
            dircache = self.dircache
        suite = TestSuite(os.path.basename(dircache.dir), "Root test suite", dircache, self)
        suite.setObservers(responders)
        return suite
    def createInitialTestSuite(self, responders):
        suite = self.makeTestSuite(responders)
        # allow the configurations to decide whether to accept the application in the presence of
        # the suite's environment
        self.configObject.checkSanity(suite)
        return suite
    def createExtraTestSuite(self, filters=[], responders=[], otherDir=None):
        suite = self.makeTestSuite(responders, otherDir)
        suite.readContents(filters)
        return suite
    
    def description(self, includeCheckout = False):
        description = "Application " + self.fullName
        if len(self.versions):
            description += ", version " + ".".join(self.versions)
        if includeCheckout and self.checkout:
            description += ", checkout " + self.checkout
        return description
    def rejectionMessage(self, message):
        return "Rejected " + self.description() + " - " + str(message) + "\n"

    def filterUnsaveable(self, versions):
        saveableVersions = []
        unsaveableVersions = self.getConfigValue("unsaveable_version")
        for version in versions:
            if not version in unsaveableVersions and not version.startswith("copy_"):
                saveableVersions.append(version)
        return saveableVersions
    def getExtensionPredicate(self, allVersions):
        if allVersions:
            # everything that has at least the given extensions
            return Set([ self.name ]).issubset
        else:
            possVersions = [ self.name ] + self.getConfigValue("base_version") + self.versions
            return Set(possVersions).issuperset
    def compareForDisplay(self, vset1, vset2):
        if vset1.issubset(vset2):
            return -1
        elif vset2.issubset(vset1):
            return 1
        
        extraVersions = self.getExtraVersions()
        extraIndex1 = self.extraVersionIndex(vset1, extraVersions)
        extraIndex2 = self.extraVersionIndex(vset2, extraVersions)
        return cmp(extraIndex1, extraIndex2)
    def extraVersionIndex(self, vset, extraVersions):
        for version in vset:
            if version in extraVersions:
                return extraVersions.index(version)
        return 99
    def compareForPriority(self, vset1, vset2):
        versionSet = Set(self.versions)
        self.diag.info("Compare " + repr(vset1) + " to " + repr(vset2))
        if len(versionSet) > 0:
            if vset1.issuperset(versionSet):
                return 1
            elif vset2.issuperset(versionSet):
                return -1
            
        explicitVersions = Set([ self.name ] + self.versions)
        priority1 = self.getVersionSetPriority(vset1)
        priority2 = self.getVersionSetPriority(vset2)
        # Low number implies higher priority...
        if priority1 != priority2:
            self.diag.info("Version priority " + repr(priority1) + " vs " + repr(priority2))
            return cmp(priority2, priority1)
        
        versionCount1 = len(vset1.intersection(explicitVersions))
        versionCount2 = len(vset2.intersection(explicitVersions))
        if versionCount1 != versionCount2:
            # More explicit versions implies higher priority
            self.diag.info("Version count " + repr(versionCount1) + " vs " + repr(versionCount2))
            return cmp(versionCount1, versionCount2)

        baseVersions = Set(self.getConfigValue("base_version"))
        baseCount1 = len(vset1.intersection(baseVersions))
        baseCount2 = len(vset2.intersection(baseVersions))
        self.diag.info("Base count " + repr(baseCount1) + " vs " + repr(baseCount2))
        # More base versions implies higher priority
        return cmp(baseCount1, baseCount2)
        
    def getVersionSetPriority(self, vlist):
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
    def makeWriteDirectory(self, subdir=None):
        if self.configObject.cleanPreviousTempDirs():
            root, tmpId = os.path.split(self.writeDirectory)
            if os.path.isdir(root):
                self.cleanPreviousWriteDirs(root)
        dirToMake = self.writeDirectory
        if subdir:
            dirToMake = os.path.join(self.writeDirectory, subdir)
        plugins.ensureDirectoryExists(dirToMake)
        self.diag.info("Made root directory at " + dirToMake)
    def cleanPreviousWriteDirs(self, rootDir):
        # Ignore the datetime and the pid at the end
        searchParts = os.path.basename(self.writeDirectory).split(".")[:-2]
        for file in os.listdir(rootDir):
            fileParts = file.split(".")
            if fileParts[:-2] == searchParts:
                previousWriteDir = os.path.join(rootDir, file)
                if os.path.isdir(previousWriteDir) and not plugins.samefile(previousWriteDir, self.writeDirectory):
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
        header += "\n" + "-" * length
        print header
        self.configObject.printHelpText()
    def getConfigValue(self, key, expandVars=True, getenvFunc=os.getenv):
        value = self.configDir.get(key)
        if not expandVars:
            return value
        if type(value) == types.StringType:
            # See top of plugins.py, we redefined this one so we can use a different environment
            return os.path.expandvars(value, getenvFunc)
        elif type(value) == types.ListType:
            return [ os.path.expandvars(element, getenvFunc) for element in value ]
        elif type(value) == types.DictType:
            newDict = {}
            for key, val in value.items():
                if type(val) == types.StringType:
                    newDict[key] = os.path.expandvars(val, getenvFunc)
                elif type(val) == types.ListType:
                    newDict[key] = [ os.path.expandvars(element, getenvFunc) for element in val ]
                else:
                    newDict[key] = val
            return newDict
        else:
            return value
    def getCompositeConfigValue(self, key, subKey, expandVars=True, getenvFunc=os.getenv, defaultKey="default"):
        dict = self.getConfigValue(key, expandVars, getenvFunc)
        # If it wasn't a dictionary, return None
        if not hasattr(dict, "items"):
            return None
        listVal = []
        for currSubKey, currValue in dict.items():
            if fnmatch(subKey, currSubKey):
                if type(currValue) == types.ListType:
                    listVal += currValue
                else:
                    return currValue
        # A certain amount of duplication here - hard to see how to avoid it
        # without compromising performance though...
        defValue = dict.get(defaultKey)
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
    def setConfigAlias(self, aliasName, realName):
        self.configDir.setAlias(aliasName, realName)
            
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
            self.diagWriteDir = os.getenv("TEXTTEST_DIAGDIR", os.getcwd())

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
            parts = app.split(".", 1)
            appName = parts[0]
            appVersion = ""
            if len(parts) > 1:
                appVersion = parts[1]
            for version in versionList:
                self.addToAppDict(appDict, appName, self.combineVersions(appVersion, version))

        return appDict
    def combineVersions(self, v1, v2):
        if len(v1) == 0 or v1 == v2:
            return v2
        elif len(v2) == 0:
            return v1
        else:
            return v1 + "." + v2
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
            return plugins.abspath(os.environ["TEXTTEST_HOME"])
        else:
            return os.getcwd()
    
# Compulsory responder to generate application events. Always present. See respond module
class ApplicationEventResponder(Responder):
    def notifyLifecycleChange(self, test, state, changeDesc):
        if changeDesc.find("saved") != -1 or changeDesc.find("recalculated") != -1 or changeDesc.find("marked") != -1:
            # don't generate application events when a test is saved or recalculated or marked...
            return
        eventName = "test " + test.uniqueName + " to " + changeDesc
        category = test.uniqueName
        timeDelay = self.getTimeDelay()
        self.scriptEngine.applicationEvent(eventName, category, timeDelay)
    def notifyAdd(self, test, initial):
        if initial and test.classId() == "test-case":
            eventName = "test " + test.uniqueName + " to be read"
            self.scriptEngine.applicationEvent(eventName, test.uniqueName)
    def notifyUniqueNameChange(self, test, newName):
        if test.classId() == "test-case":
            self.scriptEngine.applicationEventRename("test " + test.uniqueName + " to", "test " + newName + " to")
    
    def getTimeDelay(self):
        try:
            return int(os.getenv("TEXTTEST_FILEWAIT_SLEEP", 1))
        except ValueError:
            return 1
    def notifyAllRead(self, *args):
        self.scriptEngine.applicationEvent("all tests to be read")
    def notifyAllComplete(self):
        self.scriptEngine.applicationEvent("completion of test actions")
    def notifyCloseDynamic(self, test, name):
        self.scriptEngine.applicationEvent(name + " GUI to be closed")
    def notifyContentChange(self, suite, fileEdit=""):
        if fileEdit:
            # Only bother with this if we're picking up a viewer process closing
            eventName = "suite " + suite.uniqueName + " to change order"
            self.scriptEngine.applicationEvent(eventName, suite.uniqueName)

# Simple responder that collects completion notifications and sends one out when
# it thinks everything is done.
class AllCompleteResponder(Responder,plugins.Observable):
    def __init__(self, inputOptions, allApps):
        Responder.__init__(self)
        plugins.Observable.__init__(self)
        self.unfinishedTests = 0
        self.lock = Lock()
        self.checkInCompletion = False
        self.hadCompletion = False
        self.diag = plugins.getDiagnostics("test objects")
    def notifyAdd(self, test, initial):
        if test.classId() == "test-case":
            # Locking long thought to be unnecessary
            # but += 1 is not an atomic operation!!
            # a = a + 1 and a = a - 1 from different threads do not guarantee "a" unchanged. 
            self.lock.acquire()
            self.unfinishedTests += 1
            self.lock.release()
    def notifyAllRead(self, *args):
        self.lock.acquire()
        if self.unfinishedTests == 0 and self.hadCompletion:
            self.diag.info("All read -> notifying all complete")
            self.notify("AllComplete")
        else:
            self.checkInCompletion = True
        self.lock.release()
    def notifyComplete(self, test):
        self.diag.info("Complete " + str(self.unfinishedTests))
        self.lock.acquire()
        self.unfinishedTests -= 1
        if self.checkInCompletion and self.unfinishedTests == 0:
            self.diag.info("Final test read -> notifying all complete")
            self.notify("AllComplete")
        self.hadCompletion = True
        self.lock.release()
        
