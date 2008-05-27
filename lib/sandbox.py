import os, shutil, plugins, re, stat, subprocess, glob

from jobprocess import JobProcess
from socket import gethostname
from ndict import seqdict

class MakeWriteDirectory(plugins.Action):
    def __call__(self, test):
        test.makeWriteDirectory()
    def setUpApplication(self, app):
        app.makeWriteDirectory()

class PrepareWriteDirectory(plugins.Action):
    def __init__(self, ignoreCatalogues):
        self.diag = plugins.getDiagnostics("Prepare Writedir")
        self.ignoreCatalogues = ignoreCatalogues
        if self.ignoreCatalogues:
            self.diag.info("Ignoring all information in catalogue files")
    def __call__(self, test):
        self.collatePaths(test, "copy_test_path", self.copyTestPath)
        self.collatePaths(test, "partial_copy_test_path", self.partialCopyTestPath)
        self.collatePaths(test, "link_test_path", self.linkTestPath)
        test.createPropertiesFiles()
    def collatePaths(self, test, configListName, collateMethod):
        for configName in test.getConfigValue(configListName, expandVars=False):
            self.collatePath(test, configName, collateMethod)
    def collatePath(self, test, configName, collateMethod):
        sourcePath = self.getSourcePath(test, configName)
        target = self.getTargetPath(test, configName)
        self.diag.info("Collating " + configName + " from " + repr(sourcePath) + "\nto " + repr(target))
        if sourcePath:
            self.collateExistingPath(test, sourcePath, target, collateMethod)
            
        envVarToSet, propFileName = self.findDataEnvironment(test, configName)
        if envVarToSet:
            self.diag.info("Setting env. variable " + envVarToSet + " to " + target)
            test.setEnvironment(envVarToSet, target, propFileName)
    def collateExistingPath(self, test, sourcePath, target, collateMethod):
        self.diag.info("Path for linking/copying at " + sourcePath)
        plugins.ensureDirExistsForFile(target)
        collateMethod(test, sourcePath, target)
    def getEnvironmentSourcePath(self, configName, test):
        pathName = self.getPathFromEnvironment(configName, test)
        if pathName != configName:
            return pathName
    def getPathFromEnvironment(self, configName, test):
        return os.path.normpath(os.path.expandvars(configName, test.getEnvironment))
    def getTargetPath(self, test, configName):
        # handle environment variables
        localName = os.path.basename(self.getPathFromEnvironment(configName, test))
        return test.makeTmpFileName(localName, forComparison=0)
    def getSourcePath(self, test, configName):
        # These can refer to environment variables or to paths within the test structure
        fileName = self.getSourceFileName(configName, test)
        self.diag.info("Found source file name for " + configName + " = " + fileName)
        if not fileName or os.path.isabs(fileName):
            return fileName
        
        return test.getPathName(fileName, configName)
    def getSourceFileName(self, configName, test):
        if configName.startswith("$"):
            return self.getEnvironmentSourcePath(configName, test)
        else:
            return configName
    def findDataEnvironment(self, test, configName):
        self.diag.info("Finding env. var name from " + configName)
        if configName.startswith("$"):
            return configName[1:], None
        envVarDict = test.getConfigValue("test_data_environment")
        propFile = test.getCompositeConfigValue("test_data_properties", configName)
        return envVarDict.get(configName), propFile
    def copyTestPath(self, test, fullPath, target):
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
            try:
                if os.path.islink(srcname):
                    self.copylink(srcname, dstname)
                elif os.path.isdir(srcname):
                    self.copytree(srcname, dstname)
                else:
                    self.copyfile(srcname, dstname)
            except (IOError, os.error), why:
                print "Can't copy %s to %s: %s" % (`srcname`, `dstname`, str(why))
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
        currMode = os.stat(dstname)[stat.ST_MODE]
        currPerm = stat.S_IMODE(currMode)
        newPerm = currPerm | 0220
        os.chmod(dstname, newPerm)
    def linkTestPath(self, test, fullPath, target):
        # Linking doesn't exist on windows!
        if os.name != "posix":
            return self.copyTestPath(test, fullPath, target)
        if os.path.exists(fullPath):
            if not os.path.exists(target):
                os.symlink(fullPath, target)
            else:
                raise plugins.TextTestError, "File already existed at " + target + "\nTrying to link to " + fullPath
    def partialCopyTestPath(self, test, sourcePath, targetPath):
        # Linking doesn't exist on windows!
        if os.name != "posix":
            return self.copyTestPath(test, sourcePath, targetPath)
        modifiedPaths = self.getModifiedPaths(test, sourcePath)
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
        except OSError:
            print "Failed to create symlink " + targetFile
    def isWriteDir(self, targetPath, modPaths):
        for modPath in modPaths:
            if not os.path.isdir(modPath):
                return True
        return False
    def getModifiedPaths(self, test, sourcePath):
        catFile = test.getFileName("catalogue")
        if not catFile or self.ignoreCatalogues:
            # This means we don't know
            return None
        # Catalogue file is actually relative to temporary directory, need to take one level above...
        rootDir, local = os.path.split(sourcePath)
        fullPaths = { rootDir : [] }
        currentPaths = [ rootDir ]
        for line in open(catFile).readlines():
            fileName, indent = self.parseCatalogue(line)
            if not fileName:
                continue
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

# Class for automatically adding things to test environment files...
class TestEnvironmentCreator:
    def __init__(self, test, optionMap):
        self.test = test
        self.optionMap = optionMap
        self.diag = plugins.getDiagnostics("Environment Creator")
    def runsTests(self):
        return not self.optionMap.has_key("gx") and not self.optionMap.has_key("s") and \
               not self.optionMap.has_key("reconnect")
    def getVariables(self):
        vars, props = [], []
        if self.topLevel():
            vars.append(("TEXTTEST_CHECKOUT", self.test.app.checkout))
            if self.test.getConfigValue("use_case_record_mode") == "GUI":
                from unixonly import VirtualDisplayResponder
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
        # Here we assume the application uses either PyUseCase or JUseCase
        # PyUseCase reads environment variables, but you can't do that from java,
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
        if self.isRecording():
            if os.environ.has_key("USECASE_REPLAY_SCRIPT"):
                if os.getenv("USECASE_DISABLE_TARGET_RECORD"):
                    return "" # clear the outer script
                else:
                    # For self-testing, to allow us to record TextTest performing recording
                    targetReplayFile = plugins.addLocalPrefix(os.getenv("USECASE_REPLAY_SCRIPT"), "target")
                    if os.path.isfile(targetReplayFile):
                        return targetReplayFile
            else:
                # Don't replay when recording - let the user do it...
                return None
        else:
            if usecaseFile:
                return usecaseFile
            elif os.environ.has_key("USECASE_REPLAY_SCRIPT") and not self.useJavaRecorder():
                return "" # Clear our own script, if any, for further apps wanting to use PyUseCase
            
    def useJavaRecorder(self):
        return self.test.getConfigValue("use_case_recorder") == "jusecase"
    def getReplayScriptVariable(self, replayScript):        
        if self.useJavaRecorder():
            return "replay", replayScript, "jusecase"
        else:
            return "USECASE_REPLAY_SCRIPT", replayScript
    def getReplayDelayVariable(self):
        replaySpeed = str(self.test.getConfigValue("slow_motion_replay_speed"))
        if self.useJavaRecorder():
            return "delay", replaySpeed, "jusecase"
        else:
            return "USECASE_REPLAY_DELAY", replaySpeed
    def getRecordScriptVariable(self, recordScript):
        self.diag.info("Enabling recording")
        if self.useJavaRecorder():
            return "record", recordScript, "jusecase"
        else:
            return "USECASE_RECORD_SCRIPT", recordScript
    def getPathVariables(self):
        testDir = self.test.getDirectory(temporary=1)
        vars = [("TEXTTEST_SANDBOX", testDir)] 
        # Always include the working directory of the test in PATH, to pick up fake
        # executables provided as test data. Allow for later expansion...
        for pathVar in self.getPathVars():
            newPathVal = testDir + os.pathsep + "$" + pathVar
            vars.append((pathVar, newPathVal))
        return vars

    def getPathVars(self):
        pathVars = [ "PATH" ]
        for dataFile in self.test.app.getDataFileNames():
            if dataFile.endswith(".py") and "PYTHONPATH" not in pathVars:
                pathVars.append("PYTHONPATH")
            elif (dataFile.endswith(".jar") or dataFile.endswith(".class")) and "CLASSPATH" not in pathVars:
                pathVars.append("CLASSPATH")
        return pathVars
    

    
class CollateFiles(plugins.Action):
    def __init__(self):
        self.collations = {}
        self.discardFiles = []
        self.filesPresentBefore = {}
        self.diag = plugins.getDiagnostics("Collate Files")
    def setUpApplication(self, app):
        self.collations.update(app.getConfigValue("collate_file"))
        self.discardFiles = app.getConfigValue("discard_file")
    def expandCollations(self, test, coll):
        newColl = seqdict()
        # copy items specified without "*" in targetStem
        self.diag.info("coll initial:", str(coll))
        for targetStem, sourcePattern in coll.items():
            if not glob.has_magic(targetStem):
                newColl[targetStem] = sourcePattern
        # add files generated from items in targetStem containing "*"
        for targetStem, sourcePattern in coll.items():
            if not glob.has_magic(targetStem):
                continue

            # add each file to newColl using suffix from sourcePtn
            for aFile in self.getFilesFromExpansions(test, targetStem, sourcePattern):
                fullStem = os.path.splitext(aFile)[0]
                newTargetStem = os.path.basename(fullStem).replace(".", "_")
                if not newColl.has_key(newTargetStem):
                    sourceExt = os.path.splitext(sourcePattern)[1]
                    self.diag.info("New collation to " + newTargetStem + " : from " + fullStem + " with extension " + sourceExt)
                    newColl[newTargetStem] = fullStem + sourceExt
        return newColl
    def getFilesFromExpansions(self, test, targetStem, sourcePattern):
        # generate a list of filenames from previously saved files
        self.diag.info("Collating for " + targetStem)
        targetFiles = test.getFileNamesMatching(targetStem)
        fileList = map(os.path.basename, targetFiles)
        self.diag.info("Found files: " + repr(fileList))

        # generate a list of filenames for generated files
        self.diag.info("Adding files for source pattern " + sourcePattern)
        sourceFiles = glob.glob(test.makeTmpFileName(sourcePattern, forComparison=0))
        self.diag.info("Found files : " + repr(sourceFiles))
        fileList += sourceFiles
        fileList.sort()
        return fileList
    def __call__(self, test):
        if not self.filesPresentBefore.has_key(test):
            self.filesPresentBefore[test] = self.getFilesPresent(test)
        else:
            self.removeUnwanted(test)
            self.collate(test)
    def removeUnwanted(self, test):
        for stem in self.discardFiles:
            filePath = test.makeTmpFileName(stem)
            try:
                # Checking for existence too dependent on file server (?)
                os.remove(filePath)
            except:
                pass

    def collate(self, test):
        testCollations = self.expandCollations(test, self.collations)
        for targetStem, sourcePattern in testCollations.items():
            targetFile = test.makeTmpFileName(targetStem)
            collationErrFile = test.makeTmpFileName(targetStem + ".collate_errs", forFramework=1)
            for fullpath in self.findPaths(test, sourcePattern):
                if self.testEdited(test, fullpath):
                    self.diag.info("Extracting " + fullpath + " to " + targetFile)
                    self.extract(test, fullpath, targetFile, collationErrFile)
                    break
    def getFilesPresent(self, test):
        files = seqdict()
        for targetStem, sourcePattern in self.collations.items():
            for fullPath in self.findPaths(test, sourcePattern):
                self.diag.info("Pre-existing file found " + fullPath)
                files[fullPath] = plugins.modifiedTime(fullPath)
        return files
    def testEdited(self, test, fullPath):
        filesBefore = self.filesPresentBefore[test]
        if not filesBefore.has_key(fullPath):
            return True
        return filesBefore[fullPath] != plugins.modifiedTime(fullPath)
    def findPaths(self, test, sourcePattern):
        self.diag.info("Looking for pattern " + sourcePattern + " for " + repr(test))
        pattern = test.makeTmpFileName(sourcePattern, forComparison=0)
        paths = glob.glob(pattern)
        paths.sort()
        return filter(os.path.isfile, paths)
    def extract(self, test, sourceFile, targetFile, collationErrFile):
        stem = os.path.splitext(os.path.basename(targetFile))[0]
        scripts = test.getCompositeConfigValue("collate_script", stem)
        if len(scripts) == 0:
            return shutil.copyfile(sourceFile, targetFile)

        currProc = None
        stdin = None
        for script in scripts:
            if not plugins.canExecute(script):
                errorMsg = "Could not find extract script '" + script + "', not extracting file at\n" + sourceFile + "\n"
                stderr = open(collationErrFile, "w")
                stderr.write(errorMsg)
                print "WARNING : " + errorMsg.strip()
                stderr.close()
                return

            args = script.split()
            if os.name == "nt": # Windows isn't clever enough to know how to run Python/Java programs without some help...
                interpreter = plugins.getInterpreter(args[0])
                if interpreter:
                    args = [ interpreter ] + args
            if currProc:
                stdin = currProc.stdout
            else:
                args.append(sourceFile)
            self.diag.info("Opening extract process with args " + repr(args))
            if script is scripts[-1]:
                stdout = open(targetFile, "w")
                stderr = open(collationErrFile, "w")
            else:
                stdout = subprocess.PIPE
                stderr = subprocess.STDOUT

            currProc = subprocess.Popen(args, env=test.getRunEnvironment(), 
                                        stdin=stdin, stdout=stdout, stderr=stderr,
                                        cwd=test.getDirectory(temporary=1))
            
        if currProc:
            currProc.wait()    

class FindExecutionHosts(plugins.Action):
    def __call__(self, test):
        test.state.executionHosts = self.getExecutionMachines(test)
    def getExecutionMachines(self, test):
        return [ gethostname() ]

class CreateCatalogue(plugins.Action):
    def __init__(self):
        self.catalogues = {}
        self.diag = plugins.getDiagnostics("catalogues")
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
                process = JobProcess(processId)
                self.diag.info("Found process ID " + str(processId))
                if process.killAll():
                    processes.append(parts[1])
        return processes
    def findAllPaths(self, test):
        allPaths = seqdict()
        for path in test.listUnownedTmpPaths():
            editInfo = self.getEditInfo(path)
            self.diag.info("Path " + path + " edit info " + str(editInfo))
            allPaths[path] = editInfo
        return allPaths
    def getEditInfo(self, fullPath):
        # Check modified times for files and directories, targets for links
        if os.path.islink(fullPath):
            return os.path.realpath(fullPath)
        else:
            return plugins.modifiedTime(fullPath)
    def editInfoChanged(self, fullPath, oldInfo, newInfo):
        if os.path.islink(fullPath):
            return oldInfo != newInfo
        else:
            try:
                return newInfo - oldInfo > 0
            except:
                # Handle the case where a link becomes a normal file
                return oldInfo != newInfo
    def findDifferences(self, oldPaths, newPaths, writeDir):
        pathsGained, pathsEdited, pathsLost = [], [], []
        for path, modTime in newPaths.items():
            if not oldPaths.has_key(path):
                pathsGained.append(self.outputPathName(path, writeDir))
            elif self.editInfoChanged(path, oldPaths[path], modTime):
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
            parent, local = os.path.split(path)
            if parent in toRemove and not parent in removeList:
                removeList.append(parent)
        for path in removeList:
            self.diag.info("Removing parent path " + path)
            toRemove.remove(path)
    def outputPathName(self, path, writeDir):
        self.diag.info("Output name for " + path)
        return path.replace(writeDir, "<Test Directory>")
                    
class MachineInfoFinder:
    def findPerformanceMachines(self, app, fileStem):
        return app.getCompositeConfigValue("performance_test_machine", fileStem)
    def setUpApplication(self, app):
        pass
    def getMachineInformation(self, test):
        # A space for subclasses to write whatever they think is relevant about
        # the machine environment right now.
        return ""


class PerformanceFileCreator(plugins.Action):
    def __init__(self, machineInfoFinder):
        self.diag = plugins.getDiagnostics("makeperformance")
        self.machineInfoFinder = machineInfoFinder
    def setUpApplication(self, app):
        self.machineInfoFinder.setUpApplication(app)
    def allMachinesTestPerformance(self, test, fileStem):
        performanceMachines = self.machineInfoFinder.findPerformanceMachines(test.app, fileStem)
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
        timeVal = line.strip().split()[-1]
        if timeVal.find(":") == -1:
            return float(timeVal)

        parts = timeVal.split(":")
        return 60 * float(parts[0]) + float(parts[1])
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
            print "Not writing performance file for", test
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
        return glob.glob(test.makeTmpFileName(stem))
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
        if fileStem.find("mem") != -1:
            return self.makeMemoryLine(values, fileStem) + "\n"
        else:
            return self.makeTimeLine(values, fileStem) + self.getMachineContents(test)
    def getMachineContents(self, test):
        return " " + test.state.hostString() + "\n" + self.machineInfoFinder.getMachineInformation(test)
    def makeMemoryLine(self, values, fileStem):
        maxVal = max(values)
        roundedMaxVal = float(int(100*maxVal))/100
        return "Max " + fileStem.capitalize() + "  :      " + str(roundedMaxVal) + " MB"
    def makeTimeLine(self, values, fileStem):
        sum = 0.0
        for value in values:
            sum += value
        roundedSum = float(int(10*sum))/10
        return "Total " + fileStem.capitalize() + "  :      " + str(roundedSum) + " seconds"
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

