import os, shutil, plugins, re, stat, subprocess, glob, logging, difflib, time

from runtest import Killed
from jobprocess import killArbitaryProcess, killSubProcessAndChildren
from ordereddict import OrderedDict
from string import Template


def getScriptArgs(script):
    args = script.split()
    scriptName = args[0]
    instScript = plugins.installationPath(os.path.join("libexec", scriptName))
    if instScript:
        args = [ instScript ] + args[1:]
        
    return args


class MakeWriteDirectory(plugins.Action):
    def __call__(self, test):
        test.makeWriteDirectory()
    def setUpApplication(self, app):
        app.makeWriteDirectory()

class PrepareWriteDirectory(plugins.Action):
    storytextDirsCopied = set()
    def __init__(self, ignoreCatalogues):
        self.diag = logging.getLogger("Prepare Writedir")
        self.ignoreCatalogues = ignoreCatalogues
        if self.ignoreCatalogues:
            self.diag.info("Ignoring all information in catalogue files")

    def __call__(self, test):
        if self.hasPreviousData(test):
            self.backupPreviousData(test)
        machine, remoteTmpDir = test.app.getRemoteTestTmpDir(test)
        if remoteTmpDir:
            test.app.ensureRemoteDirExists(machine, remoteTmpDir)
            remoteCopy = plugins.Callable(self.copyDataRemotely, test, machine, remoteTmpDir)
        else:
            remoteCopy = None

        self.collateAllPaths(test, remoteCopy)
        test.createPropertiesFiles()

    def hasPreviousData(self, test):
        tmpDir = test.getDirectory(temporary=1)
        for f in os.listdir(tmpDir):
            if os.path.isfile(os.path.join(tmpDir, f)):
                return True
        return False

    def backupPreviousData(self, test):
        writeDir = test.getDirectory(temporary=1)
        newBackupPath, oldBackupPaths = self.findBackupPaths(test)
        localTmpDir = os.path.join(os.path.dirname(writeDir), os.path.basename(newBackupPath))
        os.rename(writeDir, localTmpDir)
        test.makeWriteDirectory()
        for oldBackupPath in oldBackupPaths:
            currLocation = os.path.join(localTmpDir, plugins.relpath(oldBackupPath, writeDir))
            os.rename(currLocation, oldBackupPath)
        os.rename(localTmpDir, newBackupPath)

    def findBackupPaths(self, test):
        number = 1
        oldPaths = []
        while True:
            path = test.makeBackupFileName(number)
            if os.path.exists(path):
                oldPaths.append(path)
                number += 1
            else:
                return path, oldPaths

    def collateAllPaths(self, test, remoteCopy):
        self.collatePaths(test, "copy_test_path", self.copyTestPath, remoteCopy)
        self.collatePaths(test, "copy_test_path_merge", self.copyTestPath, remoteCopy, mergeDirectories=True)
        self.collatePaths(test, "partial_copy_test_path", self.partialCopyTestPath, remoteCopy)
        self.collatePaths(test, "link_test_path", self.linkTestPath, remoteCopy)

    def collatePaths(self, test, configListName, *args, **kwargs):
        for configName in test.getConfigValue(configListName, expandVars=False):
            self.collatePath(test, configName, *args, **kwargs)

    def collatePath(self, test, configName, collateMethod, remoteCopy, mergeDirectories=False):
        targetPath = self.getTargetPath(test, configName)
        sourceFileName = self.getSourceFileName(configName, test)
        if not targetPath or not sourceFileName: # Can happen with e.g. empty environment
            return
        plugins.ensureDirExistsForFile(targetPath)
        for sourcePath in self.getSourcePaths(test, configName, sourceFileName):
            self.diag.info("Collating " + configName + " from " + repr(sourcePath) +
                           "\nto " + repr(targetPath))
            collateMethod(test, sourcePath, targetPath)
            if not mergeDirectories or not os.path.isdir(sourcePath):
                break

        if remoteCopy and targetPath:
            remoteCopy(targetPath)
            
        envVarToSet = self.findDataEnvironment(test, configName)
        if envVarToSet and targetPath:
            self.diag.info("Setting env. variable " + envVarToSet + " to " + targetPath)
            test.setEnvironment(envVarToSet, targetPath)

    def copyDataRemotely(self, sourcePath, test, machine, remoteTmpDir):
        if os.path.exists(sourcePath):
            copyScript = test.getCompositeConfigValue("copy_test_path_script", os.path.basename(sourcePath), expandVars=False)
            if copyScript:
                scriptSource = os.path.join(remoteTmpDir, "scriptSource")
                test.app.copyFileRemotely(sourcePath, "localhost", scriptSource, machine)
                cmdArgs = getScriptArgs(copyScript) + [ scriptSource, os.path.join(remoteTmpDir, os.path.basename(sourcePath)) ]
                test.app.runCommandOn(machine, cmdArgs)
            else:
                test.app.copyFileRemotely(sourcePath, "localhost", remoteTmpDir, machine)
            
    def getEnvironmentSourcePath(self, configName, test):
        pathName = self.getPathFromEnvironment(configName, test)
        if pathName != configName:
            self.diag.info("Found source file name for " + configName + " = " + repr(pathName))
            return pathName
    
    def getPathFromEnvironment(self, configName, test):
        expanded = Template(configName).safe_substitute(test.environment)
        if expanded: # Don't do normpath on empty strings, you get "." which causes trouble later...
            return os.path.normpath(expanded)
        else:
            return expanded
    
    def getTargetPath(self, test, configName):
        # handle environment variables
        localName = os.path.basename(self.getPathFromEnvironment(configName, test))
        if localName:
            return test.makeTmpFileName(localName, forComparison=0)
    
    def getSourcePaths(self, test, configName, fileName):
        if os.path.isabs(fileName):
            return [ fileName ]
        else:
            return reversed(test.getAllPathNames(fileName, configName)) # most specific first

    def getSourceFileName(self, configName, test):
        # These can refer to environment variables or to paths within the test structure
        if configName.startswith("$"):
            return self.getEnvironmentSourcePath(configName, test)
        else:
            return configName

    def findDataEnvironment(self, test, configName):
        self.diag.info("Finding env. var name from " + configName)
        if configName.startswith("$"):
            return configName[1:]
        
        envVarDict = test.getConfigValue("test_data_environment")
        return envVarDict.get(configName)
    
    def copyTestPath(self, test, fullPath, target):
        copyScript = test.getCompositeConfigValue("copy_test_path_script", os.path.basename(target))
        if copyScript:
            try:
                args = getScriptArgs(copyScript)
                subprocess.call(args + [ fullPath, target ])
                return
            except OSError:
                pass # If this doesn't work, assume it's on the remote machine and we'll handle it later

        if os.path.isfile(fullPath):
            self.copyfile(fullPath, target)
        if os.path.isdir(fullPath):
            self.copytree(fullPath, target)

    def copytimes(self, src, dst):
        if os.path.isdir(src) and os.name == "nt":
            # Windows doesn't let you update modification times of directories!
            return
        # copy modification times, but not permissions. This is a copy of half of shutil.copystat
        st = os.stat(src)
        if hasattr(os, 'utime'):
            os.utime(dst, (st[stat.ST_ATIME], st[stat.ST_MTIME]))

    def copytree(self, src, dst):
        # Code is a copy of shutil.copytree, with copying modification times
        # so that we can tell when things change...
        names = os.listdir(src)
        if not os.path.exists(dst):
            os.mkdir(dst)
        for name in names:
            srcname = os.path.join(src, name)
            dstname = os.path.join(dst, name)
            if os.path.isfile(dstname) or os.path.islink(dstname):
                continue
            try:
                if os.path.islink(srcname):
                    self.copylink(srcname, dstname)
                elif os.path.isdir(srcname):
                    self.copytree(srcname, dstname)
                else:
                    self.copyfile(srcname, dstname)
            except (IOError, os.error), why:
                print "Can't copy", srcname, "to", dstname, ":", why
        # Last of all, keep the modification time as it was
        self.copytimes(src, dst)
    def copylink(self, srcname, dstname):
        linkto = srcname
        if os.path.islink(srcname):
            linkto = os.readlink(srcname)
        os.symlink(linkto, dstname)
    def copyfile(self, srcname, dstname):
        # Basic aim is to keep the permission bits and times where possible, but ensure it is writeable
        shutil.copy2(srcname, dstname)
        plugins.makeWriteable(dstname)
    def linkTestPath(self, test, fullPath, target):
        # Linking doesn't exist on windows!
        if os.name != "posix":
            return self.copyTestPath(test, fullPath, target)
        if os.path.exists(fullPath):
            if not os.path.exists(target):
                os.symlink(fullPath, target)
            else: #pragma : no cover
                raise plugins.TextTestError, "File already existed at " + target + "\nTrying to link to " + fullPath
    def partialCopyTestPath(self, test, sourcePath, targetPath):
        # Linking doesn't exist on windows!
        if os.name != "posix":
            return self.copyTestPath(test, sourcePath, targetPath)
        modifiedPaths = self.getModifiedPaths(test, sourcePath, os.path.basename(targetPath))
        if modifiedPaths is None:
            # If we don't know, assume anything can change...
            self.copyTestPath(test, sourcePath, targetPath)
        elif not modifiedPaths.has_key(sourcePath):
            self.linkTestPath(test, sourcePath, targetPath)
        elif os.path.exists(sourcePath):
            os.mkdir(targetPath)
            self.diag.info("Copying/linking for Test " + repr(test))
            writeDirs = self.copyAndLink(sourcePath, targetPath, modifiedPaths)
            # Link everywhere new files appear from the write directory for ease of collection
            for writeDir in writeDirs:
                self.diag.info("Creating bypass link to " + writeDir)
                linkTarget = test.makeTmpFileName(os.path.basename(writeDir), forComparison=0)
                if linkTarget != writeDir and not os.path.exists(linkTarget):
                    # Don't link locally - and it's possible to have the same name twice under different paths
                    os.symlink(writeDir, linkTarget)
            self.copytimes(sourcePath, targetPath)
    def copyAndLink(self, sourcePath, targetPath, modifiedPaths):
        writeDirs = []
        self.diag.info("Copying/linking from " + sourcePath)
        modPathsLocal = modifiedPaths[sourcePath]
        self.diag.info("Modified paths here " + repr(modPathsLocal))
        for file in os.listdir(sourcePath):
            sourceFile = os.path.normpath(os.path.join(sourcePath, file))
            targetFile = os.path.join(targetPath, file)
            if sourceFile in modPathsLocal:
                if os.path.isdir(sourceFile):
                    os.mkdir(targetFile)
                    writeDirs += self.copyAndLink(sourceFile, targetFile, modifiedPaths)
                    self.copytimes(sourceFile, targetFile)
                else:
                    self.copyfile(sourceFile, targetFile)
            else:
                self.handleReadOnly(sourceFile, targetFile)
        if self.isWriteDir(targetPath, modPathsLocal):
            self.diag.info("Registering " + targetPath + " as a write directory")
            writeDirs.append(targetPath)
        return writeDirs
    def handleReadOnly(self, sourceFile, targetFile):
        try:
            self.copylink(sourceFile, targetFile)
        except OSError: #pragma : no cover
            print "Failed to create symlink " + targetFile
            
    def isWriteDir(self, dummy, modPaths):
        for modPath in modPaths:
            if not os.path.isdir(modPath):
                return True
        return False
    
    def getModifiedPaths(self, test, sourcePath, sourceNameInCatalogue):
        catFile = test.getFileName("catalogue")
        if not catFile or self.ignoreCatalogues:
            # This means we don't know
            return None
        # Catalogue file is actually relative to temporary directory, need to take one level above...
        rootDir = os.path.split(sourcePath)[0]
        fullPaths = { rootDir : [] }
        currentPaths = [ rootDir ]
        for line in open(catFile).readlines():
            fileName, indent = self.parseCatalogue(line)
            if not fileName:
                continue

            if fileName == sourceNameInCatalogue and indent == 1:
                fileName = os.path.basename(sourcePath)
                
            prevPath = currentPaths[indent - 1]
            fullPath = os.path.join(prevPath, fileName)
            if indent >= len(currentPaths):
                currentPaths.append(fullPath)
            else:
                currentPaths[indent] = fullPath
            if not fullPaths.has_key(fullPath):
                fullPaths[fullPath] = []
            if not fullPath in fullPaths[prevPath]:
                fullPaths[prevPath].append(fullPath)
        del fullPaths[rootDir]
        return fullPaths
    def parseCatalogue(self, line):
        pos = line.rfind("----")
        if pos == -1:
            return None, None
        pos += 4
        dashes = line[:pos]
        indent = len(dashes) / 4
        fileName = line.strip()[pos:]
        return fileName, indent

    def setUpSuite(self, suite):
        if suite.parent is None:
            self.tryCopySUTRemotely(suite)

    def tryCopySUTRemotely(self, suite):
        # Copy the executables remotely, if necessary
        machine, tmpDir = suite.app.getRemoteTmpDirectory()
        if tmpDir:
            self.copySUTRemotely(machine, tmpDir, suite)
            self.copyStorytextDirRemotely(machine, tmpDir, suite)

    def tryCopyPathRemotely(self, path, fullTmpDir, machine, app):
        if os.path.isabs(path) and os.path.exists(path) and not app.pathExistsRemotely(path, machine):
            # If not absolute, assume it's an installed program
            # If it doesn't exist locally, it must already exist remotely or we'd have raised an error by now
            remotePath = os.path.join(fullTmpDir, os.path.basename(path))
            app.copyFileRemotely(path, "localhost", remotePath, machine)
            self.diag.info("Copied " + path + " to " + remotePath)
            return remotePath
                    
    def copySUTRemotely(self, machine, tmpDir, suite):
        self.diag.info("Copying SUT for " + repr(suite.app) + " to machine " + machine + " at " + tmpDir)
        fullTmpDir = os.path.join(tmpDir, "system_under_test")
        suite.app.ensureRemoteDirExists(machine, fullTmpDir)
        checkout = suite.app.checkout
        remoteCheckout = self.tryCopyPathRemotely(checkout, fullTmpDir, machine, suite.app)
        if remoteCheckout:
            suite.app.checkout = remoteCheckout
            
        for setting in [ "interpreter", "executable" ]:
            localFile = suite.getConfigValue(setting)
            if remoteCheckout and localFile.startswith(checkout):
                remoteFile = localFile.replace(checkout, remoteCheckout) # We've copied it already, don't do it again...
            else:
                remoteFile = self.tryCopyPathRemotely(localFile, fullTmpDir, machine, suite.app)
            if remoteFile:
                self.diag.info("Setting " + repr(setting) + " to " + repr(remoteFile))
                # For convenience, so we don't have to set it everywhere...
                suite.app.setConfigDefault(setting, remoteFile)

        scripts = suite.getConfigValue("copy_test_path_script")
        newScripts = {}
        for fileName, script in scripts.items():
            if script:
                localScript = getScriptArgs(script)[0]
                remoteScript = self.tryCopyPathRemotely(localScript, fullTmpDir, machine, suite.app)
                if remoteScript:
                    self.diag.info("Setting copy_test_path_script for " + repr(fileName) + " to " + repr(remoteFile))
                    newScripts[fileName] = remoteScript
        if newScripts:
            suite.app.setConfigDefault("copy_test_path_script", newScripts)

    def copyStorytextDirRemotely(self, machine, tmpDir, suite):
        storytextDir = suite.getEnvironment("STORYTEXT_HOME_LOCAL")
        if storytextDir:
            newbasename = os.path.basename(storytextDir)
            if os.path.isdir(storytextDir) and storytextDir not in self.storytextDirsCopied:
                self.storytextDirsCopied.add(storytextDir)
                remoteName = os.path.join(tmpDir, newbasename)
                suite.app.copyFileRemotely(storytextDir, "localhost", remoteName, machine)        
        

# Class for automatically adding things to test environment files...
class TestEnvironmentCreator:
    def __init__(self, test, optionMap):
        self.test = test
        self.optionMap = optionMap
        self.diag = logging.getLogger("Environment Creator")

    def getVariables(self):
        vars, props = [], []
        self.diag.info("Creating environment for " + repr(self.test))
        if self.topLevel():
            vars.append(("TEXTTEST_ROOT", self.test.app.getDirectory())) # Full path to the root directory for each test application
            checkout = self.test.app.checkout
            if checkout:
                vars.append(("TEXTTEST_CHECKOUT", checkout)) # Full path to the checkout directory
            localCheckout = self.test.app.getCheckout()
            if localCheckout and localCheckout != checkout:
                vars.append(("TEXTTEST_CHECKOUT_NAME", localCheckout)) # Local name of the checkout directory
            vars.append(("TEXTTEST_SANDBOX_ROOT", self.test.app.writeDirectory)) # Full path to the sandbox root directory
            if self.test.getConfigValue("use_case_record_mode") == "GUI":
                usecaseRecorder = self.test.getConfigValue("use_case_recorder")
                # Mostly to make sure StoryText's own tests have a chance of working
                # Almost any other test suite shouldn't be doing this...
                envSetInTests = self.test.getConfigValue("test_data_environment").values()
                if usecaseRecorder != "none" and "STORYTEXT_HOME" not in envSetInTests:
                    if not usecaseRecorder:
                        usecaseRecorder = "ui_simulation"
                    usecaseDir = os.path.join(self.test.app.getDirectory(), usecaseRecorder + "_files")
                    remoteTmpDir = self.test.app.getRemoteTmpDirectory()[1]
                    if remoteTmpDir:
                        # We pretend it's a local temporary file
                        # so that the $HOME reference gets preserved in runtest.py
                        # (no guarantee $HOME is the same remotely)
                        fakeRemotePath = os.path.join(self.test.app.writeDirectory, os.path.basename(usecaseDir))
                        vars.append(("STORYTEXT_HOME", fakeRemotePath))
                        vars.append(("STORYTEXT_HOME_LOCAL", usecaseDir))
                    else:
                        vars.append(("STORYTEXT_HOME", usecaseDir))
                    
                if os.name == "posix":
                    from virtualdisplay import VirtualDisplayResponder
                    if VirtualDisplayResponder.instance:
                        virtualDisplay = VirtualDisplayResponder.instance.displayName
                        if virtualDisplay:
                            vars.append(("DISPLAY", virtualDisplay))
        elif self.testCase():
            useCaseVars = self.getUseCaseVariables()
            if self.useJavaRecorder():
                props += useCaseVars
            else:
                vars += useCaseVars
            vars += self.getPathVariables()
        return vars, props
    def topLevel(self):
        return self.test.parent is None
    def testCase(self):
        return self.test.classId() == "test-case"

    def getUseCaseVariables(self):
        # Here we assume the application uses either StoryText or JUseCase
        # StoryText reads environment variables, but you can't do that from java,
        # so we have a "properties file" set up as well. Do both always, to save forcing
        # apps to tell us which to do...
        usecaseFile = self.test.getFileName("usecase")
        replayUseCase = self.findReplayUseCase(usecaseFile)
        vars = []
        if replayUseCase is not None:
            vars.append(self.getReplayScriptVariable(replayUseCase))
            if self.optionMap.has_key("actrep"):
                vars.append(self.getReplayDelayVariable())
        if usecaseFile or self.isRecording():
            # Re-record if recorded files are already present or recording explicitly requested
            vars.append(self.getRecordScriptVariable(self.test.makeTmpFileName("usecase")))
        return vars

    def isRecording(self):
        return self.optionMap.has_key("record")
    
    def findReplayUseCase(self, usecaseFile):
        if not self.isRecording():
            if usecaseFile:
                return self.copyRemoteReplayFilesIfNeeded(usecaseFile)
            elif os.environ.has_key("USECASE_REPLAY_SCRIPT") and not self.useJavaRecorder():
                return "" # Clear our own script, if any, for further apps wanting to use StoryText

    def copyRemoteReplayFilesIfNeeded(self, path):
        machine, remoteTmpDir = self.test.app.getRemoteTestTmpDir(self.test)
        if remoteTmpDir:
            newbasename = "replay_usecase"
            # Sometimes more than one UI is run, copy all files with 'usecase' in the name
            usecasePattern = os.path.join(os.path.dirname(path), "*usecase*." + self.test.app.name)
            for currPath in sorted(glob.glob(usecasePattern)):
                currStem = os.path.basename(currPath).split(".")[0]
                remoteName = os.path.join(remoteTmpDir, currStem.replace("usecase", newbasename))
                self.test.app.copyFileRemotely(currPath, "localhost", remoteName, machine)
            # Don't return remoteName, we pretend it's a local temporary file
            # so that the $HOME reference gets preserved (no guarantee $HOME is the same remotely)
            return os.path.join(self.test.getDirectory(temporary=1), newbasename)
        else:
            return path
        
    def useJavaRecorder(self):
        return self.test.getConfigValue("use_case_recorder") == "jusecase"

    def getReplayScriptVariable(self, replayScript):
        if self.useJavaRecorder():
            return "replay", replayScript, "jusecase"
        else:
            return "USECASE_REPLAY_SCRIPT", replayScript # Full path to the script to replay in GUI tests
    def getReplayDelayVariable(self):
        replaySpeed = str(self.test.getConfigValue("slow_motion_replay_speed"))
        if self.useJavaRecorder():
            return "delay", replaySpeed, "jusecase"
        else:
            return "USECASE_REPLAY_DELAY", replaySpeed # Time to wait between each action in GUI tests
    def getRecordScriptVariable(self, recordScript):
        self.diag.info("Enabling recording")
        if self.useJavaRecorder():
            return "record", recordScript, "jusecase"
        else:
            return "USECASE_RECORD_SCRIPT", recordScript # Full path to the script to record in GUI tests
    def getPathVariables(self):
        testDir = self.test.getDirectory(temporary=1)
        vars = [("TEXTTEST_SANDBOX", testDir)] # Full path to the sandbox directory
        # Always include the working directory of the test in PATH, to pick up fake
        # executables provided as test data. Allow for later expansion...
        for pathVar in self.getPathVars():
            newPathVal = testDir + os.pathsep + "$" + pathVar
            vars.append((pathVar, newPathVal))
        return vars

    def getPathVars(self):
        pathVars = [ "PATH" ]
        for dataFile in self.test.getDataFileNames():
            if dataFile.endswith(".py") and "PYTHONPATH" not in pathVars:
                pathVars.append("PYTHONPATH")
            elif (dataFile.endswith(".jar") or dataFile.endswith(".class")) and "CLASSPATH" not in pathVars:
                pathVars.append("CLASSPATH")
        return pathVars


class CollateFiles(plugins.Action):
    def __init__(self):
        self.filesPresentBefore = {}
        self.collationProc = None
        self.diag = logging.getLogger("Collate Files")

    def expandCollations(self, test):
        newColl = OrderedDict()
        coll = test.getConfigValue("collate_file")
        self.diag.info("coll initial:" + str(coll))
        for targetPattern in sorted(coll.keys()):
            sourcePatterns = coll.get(targetPattern)
            if not glob.has_magic(targetPattern):
                newColl[targetPattern] = sourcePatterns
                continue

            # add each file to newColl by transferring wildcards across
            for sourcePattern in sourcePatterns:
                for sourcePath in self.findPaths(test, sourcePattern):
                    # Use relative paths: easier to debug and SequenceMatcher breaks down if strings are longer than 200 chars
                    relativeSourcePath = plugins.relpath(sourcePath, test.getDirectory(temporary=1))
                    newTargetStem = self.makeTargetStem(targetPattern, sourcePattern, relativeSourcePath)
                    self.diag.info("New collation to " + newTargetStem + " : from " + relativeSourcePath)
                    newColl.setdefault(newTargetStem, []).append(sourcePath)
        return newColl.items()

    def makeTargetStem(self, targetPattern, sourcePattern, sourcePath):
        newTargetStem = targetPattern
        for wildcardMatch in self.findWildCardMatches(sourcePattern, sourcePath):
            newTargetStem = newTargetStem.replace("*", wildcardMatch, 1)
        return newTargetStem.replace("*", "WILDCARD").replace(".", "_")

    def inSquareBrackets(self, pattern, pos):
        closeBracket = pattern.find("]", pos)
        if closeBracket == -1:
            return False
        openBracket = pattern.find("[", pos)
        return openBracket == -1 or closeBracket < openBracket

    def findWildCardMatches(self, pattern, result):
        parts = zip(pattern.split("/"), result.split("/"))
        allMatches = []
        # We take wildcards in the file name first, then those in directory names
        for subPattern, subResult in reversed(parts):
            allMatches += self._findWildCardMatches(subPattern, subResult)
        return allMatches

    def _findWildCardMatches(self, pattern, result):
        matcher = difflib.SequenceMatcher(None, pattern, result)
        wildcardStart = 0
        matches = []
        self.diag.info("Trying to find wildcard matches in " + repr(result) + " from " + repr(pattern))
        for patternPos, resultPos, length in matcher.get_matching_blocks():
            if length == 0 or self.inSquareBrackets(pattern, patternPos):
                continue
            self.diag.info("Found match of length " + repr(length) + " at positions " + repr((patternPos, resultPos)))
            if resultPos or patternPos:
                matches.append(result[wildcardStart:resultPos])
            wildcardStart = resultPos + length
        remainder = result[wildcardStart:]
        if remainder:
            matches.append(remainder)
        self.diag.info("Found matches : " + repr(matches))
        return matches
                    
    def __call__(self, test):
        if not self.filesPresentBefore.has_key(test):
            self.filesPresentBefore[test] = self.getFilesPresent(test)
        else:
            self.tryFetchRemoteFiles(test)
            self.collate(test)
            self.removeUnwanted(test)

    def removeUnwanted(self, test):
        for stem in test.getConfigValue("discard_file"):
            self.diag.info("Trying to remove generated file with stem " + stem)
            filePath = test.makeTmpFileName(stem)
            try:
                # Checking for existence too dependent on file server (?)
                os.remove(filePath)
            except EnvironmentError:
                pass

    def findEditedFile(self, test, patterns):
        for pattern in patterns:
            for fullpath in self.findPaths(test, pattern):
                if self.testEdited(test, fullpath):
                    return fullpath
                else:
                    self.diag.info("Found " + fullpath + " but it wasn't edited")

    def collate(self, test):
        for targetStem, sourcePatterns in self.expandCollations(test):
            sourceFile = self.findEditedFile(test, sourcePatterns)
            if sourceFile:
                targetFile = test.makeTmpFileName(targetStem)
                collationErrFile = test.makeTmpFileName(targetStem + ".collate_errs", forFramework=1)
                self.diag.info("Extracting " + sourceFile + " to " + targetFile)
                self.extract(test, sourceFile, targetFile, collationErrFile)

    def tryFetchRemoteFiles(self, test):
        machine, remoteTmpDir = test.app.getRemoteTestTmpDir(test)
        if remoteTmpDir:
            self.fetchRemoteFiles(test, machine, remoteTmpDir)
                
    def fetchRemoteFiles(self, test, machine, tmpDir):
        sourcePaths = os.path.join(plugins.quote(tmpDir), "*")
        test.app.copyFileRemotely(sourcePaths, machine, test.getDirectory(temporary=1), "localhost")
    
    def getFilesPresent(self, test):
        files = OrderedDict()
        for sourcePatterns in test.getConfigValue("collate_file").values():
            for sourcePattern in sourcePatterns:
                for fullPath in self.findPaths(test, sourcePattern):
                    self.diag.info("Pre-existing file found " + fullPath)
                    files[fullPath] = plugins.modifiedTime(fullPath)
        return files
    
    def testEdited(self, test, fullPath):
        filesBefore = self.filesPresentBefore[test]
        if not filesBefore.has_key(fullPath):
            return True
        return filesBefore[fullPath] != plugins.modifiedTime(fullPath)

    def alreadyCollated(self, test, path, sourcePattern):
        if "/" not in sourcePattern:
            parts = os.path.basename(path).split(".")
            if len(parts) > 1 and parts[1] == test.app.name:
                return True # Don't collate generated files
        return False

    def glob(self, test, sourcePattern):
        # Test name may contain glob meta-characters, and there is no way to quote them (see comment in fnmatch.py)
        # So we can't just form an absolute path and glob that
        testDir = test.getDirectory(temporary=1)
        origCwd = os.getcwd()
        os.chdir(testDir)
        result = glob.glob(sourcePattern)
        os.chdir(origCwd)
        return [ os.path.join(testDir, f) for f in result ]

    def findPaths(self, test, sourcePattern):
        self.diag.info("Looking for pattern " + sourcePattern + " for " + repr(test))
        paths = self.glob(test, sourcePattern)
        paths.sort()
        existingPaths = filter(os.path.isfile, paths)
        if sourcePattern == "*": # interpret this specially to mean 'all files which are not collated already'
            return filter(lambda f: not self.alreadyCollated(test, f, sourcePattern), existingPaths)
        else:
            return existingPaths

    def runCollationScript(self, args, test, stdin, stdout, stderr, useShell):
        # Windows isn't clever enough to know how to run Python/Java programs without some help...
        if os.name == "nt" and not useShell: 
            interpreter = plugins.getInterpreter(args[0])
            if interpreter:
                args = [ interpreter ] + args

        try:
            return subprocess.Popen(args, env=test.getRunEnvironment(),
                                    stdin=stdin, stdout=stdout, stderr=stderr,
                                    cwd=test.getDirectory(temporary=1), shell=useShell)
        except OSError:
            # Might just be pipe identifiers here
            if hasattr(stdout, "close"):
                stdout.close()
                stderr.close()

    def kill(self, test, sig):
        if self.collationProc:
            proc = self.collationProc
            self.collationProc = None
            killSubProcessAndChildren(proc, cmd=test.getConfigValue("kill_command"))
            
    def extract(self, test, sourceFile, targetFile, collationErrFile):
        stem = os.path.splitext(os.path.basename(targetFile))[0]
        scripts = test.getCompositeConfigValue("collate_script", stem)
        if len(scripts) == 0:
            return shutil.copyfile(sourceFile, targetFile)
            
        self.collationProc = None
        stdin = None
        for script in scripts:
            args = getScriptArgs(script)
            if self.collationProc:
                stdin = self.collationProc.stdout
            else:
                args.append(sourceFile)
            self.diag.info("Opening extract process with args " + repr(args))
            if script is scripts[-1]:
                stdout = open(targetFile, "w")
                stderr = open(collationErrFile, "w")
            else:
                stdout = subprocess.PIPE
                stderr = subprocess.STDOUT

            useShell = os.name == "nt" and len(scripts) == 1
            self.collationProc = self.runCollationScript(args, test, stdin, stdout, stderr, useShell)
            if not self.collationProc:
                if os.path.isfile(targetFile):
                    os.remove(targetFile)
                errorMsg = "Could not find extract script '" + script + "', not extracting file at\n" + sourceFile + "\n"
                stderr = open(collationErrFile, "w")
                stderr.write(errorMsg)
                plugins.printWarning(errorMsg.strip())
                stderr.close()
                return

        if self.collationProc:
            self.diag.info("Waiting for collation process to terminate...")
            self.collationProc.wait()
            if self.collationProc:
                self.collationProc = None
            else:
                procName = args[0]
                briefText = "KILLED (" + os.path.basename(procName) + ")"
                freeText = "Killed collation script '" + procName + "'\n while collating file at " + sourceFile + "\n"
                test.changeState(Killed(briefText, freeText, test.state))
            stdout.close()
            stderr.close()

        if os.path.getsize(sourceFile) > 0 and os.path.getsize(targetFile) == 0 and os.path.getsize(collationErrFile) == 0:
            # Collation scripts that don't write anything shouldn't produce empty files...
            # If they write errors though, we might want to pick those up
            os.remove(targetFile)

        collateErrMsg = test.app.filterErrorText(collationErrFile)
        if collateErrMsg:
            msg = "Errors occurred running collate_script(s) " + " and ".join(scripts) + \
                  "\nwhile trying to extract file at \n" + sourceFile + " : \n" + collateErrMsg
            plugins.printWarning(msg)
        
        

class FindExecutionHosts(plugins.Action):
    def __call__(self, test):
        test.state.executionHosts = self.getExecutionMachines(test)
    def getExecutionMachines(self, test):
        runMachine = test.app.getRunMachine()
        if runMachine == "localhost":
            return [ plugins.gethostname() ]
        else:
            return [ runMachine ]

class CreateCatalogue(plugins.Action):
    def __init__(self):
        self.catalogues = {}
        self.diag = logging.getLogger("catalogues")
    def __call__(self, test):
        if test.app.getConfigValue("create_catalogues") != "true":
            return

        if self.catalogues.has_key(test):
            self.diag.info("Creating catalogue change file...")
            self.createCatalogueChangeFile(test)
        else:
            self.diag.info("Collecting original information...")
            self.catalogues[test] = self.findAllPaths(test)
    def createCatalogueChangeFile(self, test):
        oldPaths = self.catalogues[test]
        newPaths = self.findAllPaths(test)
        pathsLost, pathsEdited, pathsGained = self.findDifferences(oldPaths, newPaths, test.getDirectory(temporary=1))
        processesGained = self.findProcessesGained(test)
        fileName = test.makeTmpFileName("catalogue")
        file = open(fileName, "w")
        if len(pathsLost) == 0 and len(pathsEdited) == 0 and len(pathsGained) == 0:
            file.write("No files or directories were created, edited or deleted.\n")
        if len(pathsGained) > 0:
            file.write("The following new files/directories were created:\n")
            self.writeFileStructure(file, pathsGained)
        if len(pathsEdited) > 0:
            file.write("\nThe following existing files/directories changed their contents:\n")
            self.writeFileStructure(file, pathsEdited)
        if len(pathsLost) > 0:
            file.write("\nThe following existing files/directories were deleted:\n")
            self.writeFileStructure(file, pathsLost)
        if len(processesGained) > 0:
            file.write("\nThe following processes were created:\n")
            self.writeProcesses(file, processesGained)
        file.close()
    def writeProcesses(self, file, processesGained):
        for process in processesGained:
            file.write("- " + process + "\n")
    def writeFileStructure(self, file, pathNames):
        prevParts = []
        tabSize = 4
        for pathName in pathNames:
            parts = pathName.split(os.sep)
            indent = 0
            for index in range(len(parts)):
                part = parts[index]
                indent += tabSize
                if index >= len(prevParts) or part != prevParts[index]:
                    prevParts = []
                    file.write(part + "\n")
                    if index != len(parts) - 1:
                        file.write(("-" * indent))
                else:
                    file.write("-" * tabSize)
            prevParts = parts
    def findProcessesGained(self, test):
        searchString = test.getConfigValue("catalogue_process_string")
        if len(searchString) == 0:
            return []
        # Code untested and unlikely to work on Windows...
        processes = []
        logFile = test.makeTmpFileName(test.getConfigValue("log_file"))
        if not os.path.isfile(logFile):
            return []
        for line in open(logFile).xreadlines():
            if line.startswith(searchString):
                parts = line.strip().split(" : ")
                try:
                    processId = int(parts[-1])
                except ValueError:
                    continue
                self.diag.info("Found process ID " + str(processId))
                if killArbitaryProcess(processId):
                    processes.append(parts[1])
        return processes
    def findAllPaths(self, test):
        allPaths = OrderedDict()
        for path in test.listUnownedTmpPaths():
            editInfo = self.getEditInfo(path)
            self.diag.info("Path " + path + " edit info " + editInfo)
            allPaths[path] = editInfo
        return allPaths

    def getEditInfo(self, fullPath):
        # Check modified times for files and directories, targets for links
        if os.path.islink(fullPath):
            return os.path.realpath(fullPath)
        else:
            return time.strftime(plugins.datetimeFormat, time.localtime(plugins.modifiedTime(fullPath)))
    
    def findDifferences(self, oldPaths, newPaths, writeDir):
        pathsGained, pathsEdited, pathsLost = [], [], []
        for path, modTime in newPaths.items():
            if not oldPaths.has_key(path):
                pathsGained.append(self.outputPathName(path, writeDir))
            elif oldPaths[path] != modTime:
                pathsEdited.append(self.outputPathName(path, writeDir))
        for path, modTime in oldPaths.items():
            if not newPaths.has_key(path):
                pathsLost.append(self.outputPathName(path, writeDir))
        # Clear out duplicates
        self.removeParents(pathsEdited, pathsGained)
        self.removeParents(pathsEdited, pathsEdited)
        self.removeParents(pathsEdited, pathsLost)
        self.removeParents(pathsGained, pathsGained)
        self.removeParents(pathsLost, pathsLost)
        return pathsLost, pathsEdited, pathsGained
    def removeParents(self, toRemove, toFind):
        removeList = []
        for path in toFind:
            parent = os.path.split(path)[0]
            if parent in toRemove and not parent in removeList:
                removeList.append(parent)
        for path in removeList:
            self.diag.info("Removing parent path " + path)
            toRemove.remove(path)
    def outputPathName(self, path, writeDir):
        self.diag.info("Output name for " + path)
        return path.replace(writeDir, "<Test Directory>")

class MachineInfoFinder:
    def findPerformanceMachines(self, test, fileStem):
        return test.getCompositeConfigValue("performance_test_machine", fileStem)

    def setUpApplication(self, app):
        pass

    def getMachineInformation(self, testArg):
        # A space for subclasses to write whatever they think is relevant about
        # the machine environment right now.
        return ""


class PerformanceFileCreator(plugins.Action):
    def __init__(self, machineInfoFinder):
        self.diag = logging.getLogger("makeperformance")
        self.machineInfoFinder = machineInfoFinder

    def setUpApplication(self, app):
        self.machineInfoFinder.setUpApplication(app)
        
    def allMachinesTestPerformance(self, test, fileStem):
        performanceMachines = self.machineInfoFinder.findPerformanceMachines(test, fileStem)
        self.diag.info("Found performance machines as " + repr(performanceMachines))
        if "any" in performanceMachines:
            return True

        for host in test.state.executionHosts:
            if host not in performanceMachines:
                self.diag.info("Real host rejected for performance " + host)
                return False
        return True

    def __call__(self, test):
        return self.makePerformanceFiles(test)


class UNIXPerformanceInfoFinder:
    def __init__(self, diag):
        self.diag = diag
        self.includeSystemTime = 0
        
    def findTimesUsedBy(self, test):
        # Read the UNIX performance file, allowing us to discount system time.
        tmpFile = test.makeTmpFileName("unixperf", forFramework=1)
        self.diag.info("Reading performance file " + tmpFile)
        if not os.path.isfile(tmpFile):
            return None, None

        file = open(tmpFile)
        cpuTime = None
        realTime = None
        for line in file.readlines():
            self.diag.info("Parsing line " + line.strip())
            if line.startswith("user") or line.startswith("User"):
                cpuTime = self.parseUnixTime(line)
            if self.includeSystemTime and (line.startswith("sys") or line.startswith("Sys")):
                cpuTime = cpuTime + self.parseUnixTime(line)
            if line.startswith("real") or line.startswith("Real"):
                realTime = self.parseUnixTime(line)
        return cpuTime, realTime

    def parseUnixTime(self, line):
        # Assumes output of GNU time
        words = line.strip().split()
        return float(words[-1])

    def setUpApplication(self, app):
        self.includeSystemTime = app.getConfigValue("cputime_include_system_time")

# Class for making a performance file directly from system-collected information,
# rather than parsing reported entries in a log file
class MakePerformanceFile(PerformanceFileCreator):
    def __init__(self, machineInfoFinder):
        PerformanceFileCreator.__init__(self, machineInfoFinder)
        self.systemPerfInfoFinder = UNIXPerformanceInfoFinder(self.diag)
    def setUpApplication(self, app):
        PerformanceFileCreator.setUpApplication(self, app)
        self.systemPerfInfoFinder.setUpApplication(app)
    def makePerformanceFiles(self, test):
        # Check that all of the execution machines are also performance machines
        if not self.allMachinesTestPerformance(test, "cputime"):
            return
        cpuTime, realTime = self.systemPerfInfoFinder.findTimesUsedBy(test)
        # There was still an error (jobs killed in emergency), so don't write performance files
        if cpuTime == None:
            plugins.log.info("Not writing performance file for " + repr(test))
            return

        fileToWrite = test.makeTmpFileName("performance")
        self.writeFile(test, cpuTime, realTime, fileToWrite)
    def timeString(self, timeVal):
        return str(round(float(timeVal), 1)).rjust(9)
    def writeFile(self, test, cpuTime, realTime, fileName):
        file = open(fileName, "w")
        cpuLine = "CPU time   : " + self.timeString(cpuTime) + " sec. " + test.state.hostString() + "\n"
        file.write(cpuLine)
        if realTime is not None:
            realLine = "Real time  : " + self.timeString(realTime) + " sec.\n"
            file.write(realLine)
        file.write(self.machineInfoFinder.getMachineInformation(test))

# Relies on the config entry performance_logfile_extractor, so looks in the log file for anything reported
# by the program
class ExtractPerformanceFiles(PerformanceFileCreator):
    def __init__(self, machineInfoFinder):
        PerformanceFileCreator.__init__(self, machineInfoFinder)
        self.entryFinders = None
        self.entryFiles = None
        self.logFileStem = None
        
    def setUpApplication(self, app):
        PerformanceFileCreator.setUpApplication(self, app)
        self.entryFinders = app.getConfigValue("performance_logfile_extractor")
        self.entryFiles = app.getConfigValue("performance_logfile")
        self.logFileStem = app.getConfigValue("log_file")
        self.diag.info("Found the following entry finders:" + str(self.entryFinders))

    def makePerformanceFiles(self, test):
        for fileStem, entryFinder in self.entryFinders.items():
            if len(entryFinder) == 0:
                continue # don't allow empty entry finders
            if not self.allMachinesTestPerformance(test, fileStem):
                self.diag.info("Not extracting performance file for " + fileStem + ": not on performance machines")
                continue
            values = []
            for logFileStem in self.findLogFileStems(fileStem):
                self.diag.info("Looking for log files matching " + logFileStem)
                for fileName in self.findLogFiles(test, logFileStem):
                    self.diag.info("Scanning log file for entry: " + entryFinder)
                    values += self.findValues(fileName, entryFinder)
            if len(values) > 0:
                fileName = self.getFileToWrite(test, fileStem)
                self.diag.info("Writing performance to file " + fileName)
                contents = self.makeFileContents(test, values, fileStem)
                self.saveFile(fileName, contents)
    def getFileToWrite(self, test, stem):
        return test.makeTmpFileName(stem)
    def findLogFiles(self, test, stem):
        collatedfiles = glob.glob(test.makeTmpFileName(stem))
        if len(collatedfiles) == 0:
            return glob.glob(test.makeTmpFileName(stem, forComparison=0))
        return collatedfiles
    def findLogFileStems(self, fileStem):
        if self.entryFiles.has_key(fileStem):
            return self.entryFiles[fileStem]
        else:
            return [ self.logFileStem ]
    def saveFile(self, fileName, contents):
        file = open(fileName, "w")
        file.write(contents)
        file.close()
    def makeFileContents(self, test, values, fileStem):
        # Round to accuracy 0.01
        unit = test.getCompositeConfigValue("performance_unit", fileStem)
        if fileStem.find("mem") != -1:
            return self.makeMemoryLine(values, fileStem) + " " + unit + "\n"
        else:
            return self.makeTimeLine(values, fileStem) + " " + unit + self.getMachineContents(test)
    def getMachineContents(self, test):
        return " " + test.state.hostString() + "\n" + self.machineInfoFinder.getMachineInformation(test)
    def makeMemoryLine(self, values, fileStem):
        maxVal = max(values)
        roundedMaxVal = float(int(100*maxVal))/100
        return "Max " + fileStem.capitalize() + "  :      " + str(roundedMaxVal)
    def makeTimeLine(self, values, fileStem):
        sum = 0.0
        for value in values:
            sum += value
        roundedSum = float(int(10*sum))/10
        return "Total " + fileStem.capitalize() + "  :      " + str(roundedSum)
    def findValues(self, logFile, entryFinder):
        values = []
        for line in open(logFile).xreadlines():
            value = self.getValue(line, entryFinder)
            if value:
                self.diag.info(" found value: " + str(value))
                values.append(value)
        return values
    def getValue(self, line, entryFinder):
        # locates the first whitespace after an occurrence of entryFinder in line,
        # and scans the rest of the string after that whitespace
        pattern = '.*' + entryFinder + r'\S*\s(?P<restofline>.*)'
        regExp = re.compile(pattern)
        match = regExp.match(line)
        if not match:
            return
        restOfLine = match.group('restofline')
        self.diag.info(" entry found, extracting value from: " + restOfLine)
        words = restOfLine.split()
        if len(words) == 0:
            return
        try:
            number = float(words[0])
            if restOfLine.lower().find("kb") != -1:
                number = float(number / 1024.0)
            return number
        except ValueError:
            # try parsing the memString as a h*:mm:ss time string
            # * - any number of figures are allowed for the hour part
            timeRegExp = re.compile(r'(?P<hours>\d+)\:(?P<minutes>\d\d)\:(?P<seconds>\d\d)')
            match = timeRegExp.match(words[0])
            if match:
                hours = float(match.group('hours'))
                minutes = float(match.group('minutes'))
                seconds = float(match.group('seconds'))
                return hours*60*60 + minutes*60 + seconds

