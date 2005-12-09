#!/usr/local/bin/python

import os, shutil, plugins, respond, performance, comparetest, string, predict, sys, batch, re, stat
import glob
from threading import currentThread
from knownbugs import CheckForBugs
from cPickle import Unpickler
from socket import gethostname
from ndict import seqdict

plugins.addCategory("killed", "killed", "were terminated before completion")

def getConfig(optionMap):
    return Config(optionMap)

class Config(plugins.Configuration):
    def addToOptionGroups(self, app, groups):
        for group in groups:
            if group.name.startswith("Select"):
                group.addOption("t", "Test names containing")
                group.addOption("f", "Tests listed in file", possibleValues=self.getPossibleFilterFiles(app))
                group.addOption("ts", "Suite names containing")
                group.addOption("grep", "Result files containing")
                group.addOption("grepfile", "Result file to search", app.getConfigValue("log_file"), self.getPossibleResultFiles(app))
                group.addOption("r", "Execution time <min, max>")
            elif group.name.startswith("What"):
                group.addOption("reconnect", "Reconnect to previous run")
                group.addSwitch("reconnfull", "Recompute file filters when reconnecting")
                if self.isolatesDataUsingCatalogues(app):
                    group.addSwitch("ignorecat", "Ignore catalogue file when isolating data")
            elif group.name.startswith("How"):
                group.addOption("b", "Run batch mode session")
                group.addSwitch("noperf", "Disable any performance testing")
            elif group.name.startswith("Invisible"):
                # Only relevant without the GUI
                group.addSwitch("g", "use dynamic GUI", 1)
                group.addSwitch("gx", "use static GUI")
                group.addSwitch("o", "Overwrite all failures")
                group.addOption("tp", "Private: Tests with exact path") # use for internal communication
                group.addSwitch("n", "Create new results files (overwrite everything)")
            elif group.name.startswith("Side"):
                group.addSwitch("keeptmp", "Keep temporary write-directories")
    def getActionSequence(self):
        if self.useStaticGUI():
            return []

        return self._getActionSequence(makeDirs=1)
    def useGUI(self):
        return self.optionMap.has_key("g") or self.useStaticGUI()
    def useStaticGUI(self):
        return self.optionMap.has_key("gx")
    def getResponderClasses(self):
        classes = []
##        if not self.isReconnecting():
##            actions.append(CollectFailureData())
        # Put the GUI first ... first one gets the script engine - see respond module :)
        if self.useGUI():
            self.addGuiResponder(classes)
        if self.batchMode():
            classes.append(batch.BatchResponder)
        if self.keepTemporaryDirectories():
            classes.append(self.getStateSaver())
        if not self.useGUI() and not self.batchMode():
            classes.append(self.getTextResponder())
        return classes
    def isolatesDataUsingCatalogues(self, app):
        return app.getConfigValue("create_catalogues") == "true" and \
               len(app.getConfigValue("partial_copy_test_path")) > 0
    def getRunIdentifier(self, prefix):
        basicId = plugins.Configuration.getRunIdentifier(self, prefix)
        if prefix and self.useStaticGUI():
            return "static_gui." + basicId
        else:
            return basicId
    def addGuiResponder(self, classes):
        try:
            from texttestgui import TextTestGUI
            classes.append(TextTestGUI)
        except:
            print "Cannot use GUI: caught exception:"
            plugins.printException()
    def useTextResponder(self):
        return not self.optionMap.useGUI()

    def _getActionSequence(self, makeDirs):
        actions = [ self.getTestProcessor() ]
        if makeDirs:
            actions = [ self.getWriteDirectoryMaker() ] + actions
        return actions
    def getTestProcessor(self):
        if self.isReconnectingFast():
            return self.getFileExtractor()
        
        catalogueCreator = self.getCatalogueCreator()
        ignoreCatalogues = self.optionMap.has_key("ignorecat")
        return [ self.getWriteDirectoryPreparer(ignoreCatalogues), catalogueCreator, \
                 self.tryGetTestRunner(), catalogueCreator, self.getTestEvaluator() ]
    def getPossibleResultFiles(self, app):
        files = [ "output", "errors" ]
        if app.getConfigValue("create_catalogues") == "true":
            files.append("catalogue")
        files += app.getConfigValue("collate_file").keys()
        for file in app.getConfigValue("discard_file"):
            if file in files:
                files.remove(file)
        return files
    def getPossibleFilterFiles(self, app):
        filterFiles = []
        for directory in app.getConfigValue("test_list_files_directory"):
            fullPath = os.path.join(app.abspath, directory)
            if os.path.exists(fullPath):
                filenames = os.listdir(fullPath)
                filenames.sort()
                for filename in filenames:
                    if os.path.isfile(os.path.join(fullPath, filename)):
                        filterFiles.append(filename)
        return filterFiles
    def makeFilterFileName(self, app, filename):
        for directory in app.getConfigValue("test_list_files_directory"):
            fullPath = os.path.join(app.abspath, directory, filename)
            if os.path.isfile(fullPath):
                return fullPath
    def getFilterClasses(self):
        return [ TestNameFilter, TestPathFilter, TestSuiteFilter, \
                 batch.BatchFilter, performance.TimeFilter ]
    def getFilterList(self, app):
        filters = self.getFiltersFromMap(self.optionMap, app)
        if self.optionMap.has_key("f"):
            filters += self.getFiltersFromFile(app, self.optionMap["f"])
        return filters
    def getFiltersFromFile(self, app, filename):
        fullPath = self.makeFilterFileName(app, filename)
        if not fullPath:
            print "File", filename, "not found for application", app
            return []
        fileData = string.join(plugins.readList(fullPath), ",")
        optionFinder = plugins.OptionFinder(fileData.split(), defaultKey="t")
        return self.getFiltersFromMap(optionFinder, app)
    def getFiltersFromMap(self, optionMap, app):
        filters = []
        for filterClass in self.getFilterClasses():
            if optionMap.has_key(filterClass.option):
                filters.append(filterClass(optionMap[filterClass.option]))
        if optionMap.has_key("grep"):
            filters.append(GrepFilter(optionMap["grep"], self.getGrepFile(optionMap, app)))
        return filters
    def getGrepFile(self, optionMap, app):
        if optionMap.has_key("grepfile"):
            return optionMap["grepfile"]
        else:
            return app.getConfigValue("log_file")
    def batchMode(self):
        return self.optionMap.has_key("b")
    def keepTemporaryDirectories(self):
        return self.optionMap.has_key("keeptmp") or (self.batchMode() and not self.isReconnecting())
    def getCleanMode(self):
        if self.isReconnectingFast():
            return self.CLEAN_NONE
        if self.keepTemporaryDirectories():
            return self.CLEAN_PREVIOUS
        
        return self.CLEAN_SELF
    def isReconnecting(self):
        return self.optionMap.has_key("reconnect")
    def getWriteDirectoryMaker(self):
        if self.isReconnectingFast():
            return None
        else:
            return self._getWriteDirectoryMaker()
    def getWriteDirectoryPreparer(self, ignoreCatalogues):
        return PrepareWriteDirectory(ignoreCatalogues)
    def _getWriteDirectoryMaker(self):
        return MakeWriteDirectory()
    def tryGetTestRunner(self):
        if self.isReconnecting():
            return None
        else:
            return self.getTestRunner()
    def getTestRunner(self):
        if os.name == "posix":
            # Use Xvfb to suppress GUIs, cmd files to prevent shell-quote problems,
            # UNIX time to collect system performance info.
            from unixonly import RunTest as UNIXRunTest
            return UNIXRunTest()
        else:
            return RunTest()
    def isReconnectingFast(self):
        return self.isReconnecting() and not self.optionMap.has_key("reconnfull")
    def getTestEvaluator(self):
        return [ self.getFileExtractor(), self.getTestPredictionChecker(), \
                 self.getTestComparator(), self.getFailureExplainer() ]
    def getFileExtractor(self):
        if self.isReconnecting():
            return ReconnectTest(self.optionValue("reconnect"), self.optionMap.has_key("reconnfull"))
        else:
            if self.optionMap.has_key("noperf"):
                return self.getTestCollator()
            elif self.optionMap.has_key("diag"):
                print "Note: Running with Diagnostics on, so performance checking is disabled!"
                return [ self.getTestCollator(), self.getPerformanceExtractor() ] 
            else:
                return [ self.getTestCollator(), self.getPerformanceFileMaker(), self.getPerformanceExtractor() ] 
    def getCatalogueCreator(self):
        return CreateCatalogue()
    def getTestCollator(self):
        if os.name == "posix":
            # Handle UNIX compression and collect core files
            from unixonly import CollateFiles as UNIXCollateFiles
            return UNIXCollateFiles(self.optionMap.has_key("keeptmp"))
        else:
            return CollateFiles()
    def getPerformanceExtractor(self):
        return ExtractPerformanceFiles(self.getMachineInfoFinder())
    def getPerformanceFileMaker(self):
        return MakePerformanceFile(self.getMachineInfoFinder())
    def getMachineInfoFinder(self):
        return MachineInfoFinder()
    def getTestPredictionChecker(self):
        return predict.CheckPredictions()
    def getFailureExplainer(self):
        return CheckForBugs()
    def showExecHostsInFailures(self):
        return self.batchMode()
    def getTestComparator(self):
        return comparetest.MakeComparisons(performance.PerformanceTestComparison)
    def getStateSaver(self):
        if self.batchMode():
            return batch.SaveState
        else:
            return respond.SaveState
    def getTextResponder(self):
        return respond.InteractiveResponder
    # Utilities, which prove useful in many derived classes
    def optionValue(self, option):
        if self.optionMap.has_key(option):
            return self.optionMap[option]
        else:
            return ""
            info = ""
    # For display in the GUI
    def getTextualInfo(self, test):
        info = ""
        if test.state.isComplete():
            info = "Test " + repr(test.state) + "\n"
            if len(test.state.freeText) == 0:
                info = info.replace(" :", "")
        info += str(test.state.freeText)
        if not test.state.isComplete():
            info += self.progressText(test)
        return info
    def extraReadFiles(self, test):
        knownDataFiles = test.getConfigValue("link_test_path") + test.getConfigValue("copy_test_path") + \
                         test.getConfigValue("partial_copy_test_path")
        readFiles = seqdict()
        readFiles[""] = map(lambda file: os.path.join(test.abspath, file), knownDataFiles)
        return readFiles
    def progressText(self, test):
        perc = self.calculatePercentage(test)
        if perc > 0:
            return "\nFrom log file reckoned to be " + str(perc) + "% complete."
        else:
            return ""
    def calculatePercentage(self, test):
        logFileStem = test.getConfigValue("log_file")
        stdFile = test.makeFileName(logFileStem)
        tmpFile = test.makeFileName(logFileStem, temporary=1)
        if not os.path.isfile(tmpFile) or not os.path.isfile(stdFile):
            return 0
        stdSize = os.path.getsize(stdFile)
        tmpSize = os.path.getsize(tmpFile)
        if stdSize == 0:
            return 0
        return (tmpSize * 100) / stdSize 
    def printHelpScripts(self):
        pass
    def printHelpDescription(self):
        print "The default configuration is a published configuration. Consult the online documentation."
    def printHelpOptions(self):
        pass
    def printHelpText(self):
        self.printHelpDescription()
        print "\nAdditional Command line options supported :"
        print "-------------------------------------------"
        self.printHelpOptions()
        print "\nPython scripts: (as given to -s <module>.<class> [args])"
        print "--------------------------------------------------------"
        self.printHelpScripts()
    def defaultLoginShell(self):
        # For UNIX
        return "sh"
    def defaultTextDiffTool(self):
        if os.name == "posix":
            return "diff"
        else:
            return "ndiff"
    def defaultSeverities(self):
        severities = {}
        severities["errors"] = 1
        severities["output"] = 1
        severities["performance"] = 2
        severities["usecase"] = 2
        severities["catalogue"] = 2
        return severities
    def getDefaultMailAddress(self):
        user = os.getenv("USER", "$USER")
        return user + "@localhost"
    def setApplicationDefaults(self, app):
        app.setConfigDefault("log_file", "output", "Result file to search, by default")
        app.setConfigDefault("failure_severity", self.defaultSeverities(), \
                             "Mapping of result files to how serious diffs in them are")
        app.setConfigDefault("text_diff_program", self.defaultTextDiffTool(), \
                             "External program to use for textual comparison of files")
        app.setConfigDefault("lines_of_text_difference", 30, "How many lines to present in textual previews of file diffs")
        app.setConfigDefault("max_width_text_difference", 500, "How wide lines can be in textual previews of file diffs")
        app.setConfigDefault("home_operating_system", "any", "Which OS the test results were originally collected on")
        app.setConfigDefault("partial_copy_test_path", [], "Paths to be part-copied, part-linked to the temporary directory")
        app.setConfigDefault("copy_test_path", [], "Paths to be copied to the temporary directory when running tests")
        app.setConfigDefault("link_test_path", [], "Paths to be linked from the temp. directory when running tests")
        app.setConfigDefault("test_data_environment", {}, "Environment variables to be redirected for linked/copied test data")
        app.setConfigDefault("collate_file", {}, "Mapping of result file names to paths to collect them from")
        app.setConfigDefault("run_dependent_text", { "" : [] }, "Mapping of patterns to remove from result files")
        app.setConfigDefault("unordered_text", { "" : [] }, "Mapping of patterns to extract and sort from result files")
        app.setConfigDefault("create_catalogues", "false", "Do we create a listing of files created/removed by tests")
        app.setConfigDefault("catalogue_process_string", "", "String for catalogue functionality to identify processes created")
        app.setConfigDefault("internal_error_text", [], "List of text to be considered as an internal error, if present")
        app.setConfigDefault("internal_compulsory_text", [], "List of text to be considered as an internal error, if not present")
        # Performance values
        app.setConfigDefault("cputime_include_system_time", 0, "Include system time when measuring CPU time?")
        app.setConfigDefault("cputime_slowdown_variation_%", 30, "CPU time tolerance allowed when interference detected")
        app.setConfigDefault("performance_logfile", { "default" : [] }, "Which result file to collect performance data from")
        app.setConfigDefault("performance_logfile_extractor", {}, "What string to look for when collecting performance data")
        app.setConfigDefault("performance_test_machine", { "default" : [], "memory" : [ "any" ] }, \
                             "List of machines where performance can be collected")
        app.setConfigDefault("performance_variation_%", { "default" : 10 }, "How much variation in performance is allowed")
        app.setConfigDefault("performance_test_minimum", { "default" : 0 }, \
                             "Minimum time/memory to be consumed before data is collected")
        app.setConfigDefault("use_case_record_mode", "disabled", "Mode for Use-case recording (GUI, console or disabled)")
        app.setConfigDefault("discard_file", [], "List of generated result files which should not be compared")
        app.addConfigEntry("pending", "white", "test_colours")
        app.addConfigEntry("definition_file_stems", "knownbugs")
        # Batch values. Maps from session name to values
        app.setConfigDefault("smtp_server", "localhost", "Server to use for sending mail in batch mode")
        app.setConfigDefault("batch_result_repository", { "default" : "" }, "Directory to store historical batch results under")
        app.setConfigDefault("batch_sender", { "default" : self.getDefaultMailAddress() }, "Sender address to use sending mail in batch mode")
        app.setConfigDefault("batch_recipients", { "default" : self.getDefaultMailAddress() }, "Addresses to send mail to in batch mode")
        app.setConfigDefault("batch_timelimit", { "default" : None }, "Maximum length of test to include in batch mode runs")
        app.setConfigDefault("batch_use_collection", { "default" : "false" }, "Do we collect multiple mails into one in batch mode")
        # Sample to show that values are lists
        app.setConfigDefault("batch_version", { "default" : [] }, "Which versions are allowed as batch mode runs")
        # Use batch session as a base version
        batchSession = self.optionValue("b")
        if batchSession:
            app.addConfigEntry("base_version", batchSession)
        if not plugins.TestState.showExecHosts:
            plugins.TestState.showExecHosts = self.showExecHostsInFailures()
        if os.name == "posix":
            app.setConfigDefault("virtual_display_machine", [], \
                                 "(UNIX) List of machines to run virtual display server (Xvfb) on")
            app.setConfigDefault("login_shell", self.defaultLoginShell(), \
                                 "(UNIX) Which shell to use when starting processes")

class MakeWriteDirectory(plugins.Action):
    def __call__(self, test):
        fullPathToMake = os.path.join(test.writeDirectory, "framework_tmp")
        plugins.ensureDirectoryExists(fullPathToMake)
        os.chdir(test.writeDirectory)
    def __repr__(self):
        return "Make write directory for"
    def setUpApplication(self, app):
        app.makeWriteDirectory()

class PrepareWriteDirectory(plugins.Action):
    def __init__(self, ignoreCatalogues):
        self.diag = plugins.getDiagnostics("Prepare Writedir")
        self.ignoreCatalogues = ignoreCatalogues
    def __repr__(self):
        return "Prepare write directory for"
    def __call__(self, test):
        self.collatePaths(test, "copy_test_path", self.copyTestPath)
        self.collatePaths(test, "partial_copy_test_path", self.partialCopyTestPath)
        self.collatePaths(test, "link_test_path", self.linkTestPath)
        self.createPropertiesFiles(test)
        if test.app.useDiagnostics:
            plugins.ensureDirectoryExists(os.path.join(test.writeDirectory, "Diagnostics"))
    def collatePaths(self, test, configListName, collateMethod):
        for configName in test.getConfigValue(configListName):
            self.collatePath(test, configName, collateMethod)
    def collatePath(self, test, configName, collateMethod):
        sourcePath = self.getSourcePath(test, configName)
        self.diag.info("Path for linking/copying at " + sourcePath)
        target = os.path.join(test.writeDirectory, os.path.basename(sourcePath))
        plugins.ensureDirExistsForFile(target)
        collateMethod(test, sourcePath, target)
        envVarToSet = self.findEnvironmentVariable(test, configName)
        if envVarToSet:
            test.environment[envVarToSet] = target
            test.previousEnv[envVarToSet] = sourcePath
    def getSourcePath(self, test, configName):
        # These can refer to environment variables or to paths within the test structure
        if configName.startswith("$"):
            return os.path.normpath(os.path.expandvars(configName))
        else:
            return test.makePathName(configName, test.abspath)
    def findEnvironmentVariable(self, test, configName):
        if configName.startswith("$"):
            return configName[1:]
        envVarDict = test.getConfigValue("test_data_environment")
        return envVarDict.get(configName)
    def copyTestPath(self, test, fullPath, target):
        if os.path.isfile(fullPath):
            shutil.copy(fullPath, target)
        if os.path.isdir(fullPath):
            self.copytree(fullPath, target)
    def copytimes(self, src, dst):
        # copy modification times, but not permissions. This is a copy of half of shutil.copystat
        st = os.stat(src)
        if hasattr(os, 'utime'):
            os.utime(dst, (st[stat.ST_ATIME], st[stat.ST_MTIME]))
    def copytree(self, src, dst):
        # Code is a copy of shutil.copytree, with copying modification times
        # so that we can tell when things change...
        names = os.listdir(src)
        os.mkdir(dst)
        for name in names:
            srcname = os.path.join(src, name)
            dstname = os.path.join(dst, name)
            try:
                if os.path.islink(srcname):
                    linkto = os.path.realpath(srcname)
                    os.symlink(linkto, dstname)
                elif os.path.isdir(srcname):
                    self.copytree(srcname, dstname)
                else:
                    self.copyfile(srcname, dstname)
            except (IOError, os.error), why:
                print "Can't copy %s to %s: %s" % (`srcname`, `dstname`, str(why))
        # Last of all, keep the modification time as it was
        self.copytimes(src, dst)
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
            os.symlink(fullPath, target)
    def partialCopyTestPath(self, test, sourcePath, targetPath):
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
                linkTarget = os.path.join(test.writeDirectory, os.path.basename(writeDir))
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
        if os.path.basename(sourceFile) == "CVS":
            return
        try:
            os.symlink(sourceFile, targetFile)
        except OSError:
            print "Failed to create symlink " + targetFile
    def isWriteDir(self, targetPath, modPaths):
        for modPath in modPaths:
            if not os.path.isdir(modPath):
                return True
        return False
    def getModifiedPaths(self, test, sourcePath):
        catFile = test.makeFileName("catalogue")
        if not os.path.isfile(catFile) or self.ignoreCatalogues:
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
    def createPropertiesFiles(self, test):
        for var, value in test.properties.items():
            propFileName = os.path.join(test.writeDirectory, var + ".properties")
            self.diag.info("Writing " + propFileName + " for " + var + " : " + repr(value))
            file = open(propFileName, "w")
            for subVar, subValue in value.items():
                file.write(subVar + " = " + subValue + "\n")
    def getInterruptActions(self):
        # This can take a very long time, best to let it be interrupted...
        return []

class CollectFailureData(plugins.Action):
    def __init__(self):
        self.hardFailures = []
        self.softFailures = []
    def __call__(self, test):
        category, details = test.state.getTypeBreakdown()
        if category != "success":
            self.hardFailures.append(test.getRelPath())
        elif len(details) > 0:
            self.softFailures.append(test.getRelPath())
    def getCleanUpAction(self):
        return CreateSelectionFiles(self)

class CreateSelectionFiles(plugins.Action):
    def __init__(self, collector):
        self.collector = collector
    def setUpApplication(self, app):
        self.writeList(app, "hard_failures", self.collector.hardFailures)
        self.writeList(app, "soft_failures", self.collector.softFailures)
    def writeList(self, app, fileName, list):
        if len(list) == 0:
            return
        fullPath = os.path.join(app.writeDirectory, fileName)
        file = open(fullPath, "w")
        file.write("-tp " + string.join(list, ",") + "\n")
        file.close()
    
class CollateFiles(plugins.Action):
    def __init__(self):
        self.collations = {}
        self.discardFiles = []
        self.diag = plugins.getDiagnostics("Collate Files")
    def setUpApplication(self, app):
        self.collations.update(app.getConfigValue("collate_file"))
        self.discardFiles = app.getConfigValue("discard_file")
    def expandCollations(self, test, coll):
	newColl = {}
	# copy items specified without "*" in targetStem
	self.diag.info("coll initial:", str(coll))
        for targetStem, sourcePattern in coll.items():
	    if not glob.has_magic(targetStem):
	    	newColl[targetStem] = sourcePattern
	# add files generated from items in targetStem containing "*"
        for targetStem, sourcePattern in coll.items():
	    if not glob.has_magic(targetStem):
		continue

	    # generate a list of filenames from previously saved files
            targetPtn = test.makeFileName(targetStem)
	    self.diag.info("targetPtn: " + targetPtn)
	    fileList = map(os.path.basename,glob.glob(targetPtn))

	    # generate a list of filenames for generated files
            sourcePtn = test.makeFileName(sourcePattern, temporary=1)
	    # restore suffix (makeFileName automatically adds application name)
	    sourcePtn = os.path.splitext(sourcePtn)[0] + \
				os.path.splitext(sourcePattern)[1]
	    self.diag.info("sourcePtn: " + sourcePtn)
            for file in glob.glob(sourcePtn):
                fileList.append(file.replace(test.writeDirectory + os.sep, ""))
	    fileList.sort()

	    # add each file to newColl using suffix from sourcePtn
	    for aFile in fileList:
		self.diag.info("aFile: " + aFile)
	    	newTarget = os.path.splitext(os.path.basename(aFile))[0]
	    	if not newTarget in newColl:
		    ext = os.path.splitext(sourcePtn)[1]
		    newColl[newTarget] = os.path.splitext(aFile)[0] + ext
	self.diag.info("coll final:", str(newColl))
	return newColl
    def __call__(self, test):
        self.removeUnwanted(test)
        self.collate(test)
    def removeUnwanted(self, test):
        for stem in self.discardFiles:
            filePath = test.makeFileName(stem, temporary=1)
            if os.path.isfile(filePath):
                os.remove(filePath)
    def collate(self, test):
	testCollations = self.expandCollations(test, self.collations)
        errorWrites = []
        for targetStem, sourcePattern in testCollations.items():
            targetFile = test.makeFileName(targetStem, temporary=1)
            fullpath = self.findPath(test, sourcePattern)
            if fullpath:
                self.diag.info("Extracting " + fullpath + " to " + targetFile) 
                self.extract(fullpath, targetFile)
                self.transformToText(targetFile, test)
            elif os.path.isfile(test.makeFileName(targetStem)):
                errorWrites.append((sourcePattern, targetFile))

        # Don't write collation failures if there aren't any files anyway : the point
        # is to highlight partial failure to collect files
        if self.hasAnyFiles(test):
            for sourcePattern, targetFile in errorWrites:
                errText = self.getErrorText(sourcePattern)
                open(targetFile, "w").write(errText + "\n")
    def hasAnyFiles(self, test):
        for file in os.listdir(test.getDirectory(temporary=1)):
            if os.path.isfile(file) and test.app.ownsFile(file):
                return 1
        return 0
    def getErrorText(self, sourcePattern):
        return "Expected file '" + sourcePattern + "' not created by test"
    def findPath(self, test, sourcePattern):
        self.diag.info("Looking for pattern " + sourcePattern + " for " + repr(test))
        pattern = os.path.join(test.writeDirectory, sourcePattern)
        paths = glob.glob(pattern)
        for path in paths:
            if os.path.isfile(path):
                return path
    def transformToText(self, path, test):
        # By default assume it is text
        pass
    def extract(self, sourcePath, targetFile):
        shutil.copyfile(sourcePath, targetFile)
    
class TextFilter(plugins.Filter):
    def __init__(self, filterText):
        self.texts = plugins.commasplit(filterText)
        self.textTriggers = [ plugins.TextTrigger(text) for text in self.texts ]
    def containsText(self, test):
        return self.stringContainsText(test.name)
    def stringContainsText(self, searchString):
        for trigger in self.textTriggers:
            if trigger.matches(searchString):
                return 1
        return 0
    def equalsText(self, test):
        return test.name in self.texts

class TestPathFilter(TextFilter):
    option = "tp"
    def acceptsTestCase(self, test):
        return test.getRelPath() in self.texts
    def acceptsTestSuite(self, suite):
        for relPath in self.texts:
            if relPath.startswith(suite.getRelPath()):
                return 1
        return 0
    
class TestNameFilter(TextFilter):
    option = "t"
    def acceptsTestCase(self, test):
        return self.containsText(test)

class TestSuiteFilter(TextFilter):
    option = "ts"
    def acceptsTestCase(self, test):
        pathComponents = test.getRelPath().split(os.sep)
        for path in pathComponents:
            if len(path) and path != test.name:
                for trigger in self.textTriggers:
                    if trigger.matches(path):
                        return 1
        return 0

class GrepFilter(TextFilter):
    def __init__(self, filterText, fileStem):
        TextFilter.__init__(self, filterText)
        self.fileStem = fileStem
    def acceptsTestCase(self, test):
        logFile = test.makeFileName(self.fileStem)
        if not os.path.isfile(logFile):
            return 0
        for line in open(logFile).xreadlines():
            if self.stringContainsText(line):
                return 1
        return 0

# Workaround for python bug 853411: tell main thread to start the process
# if we aren't it...
class Pending(plugins.TestState):
    def __init__(self, process):
        plugins.TestState.__init__(self, "pending")
        self.process = process
        if currentThread().getName() == "MainThread":
            self.notifyInMainThread()
    def notifyInMainThread(self):
        self.process.doFork()

class Running(plugins.TestState):
    def __init__(self, execMachines, bkgProcess = None, freeText = "", briefText = ""):
        plugins.TestState.__init__(self, "running", freeText, briefText, started=1,
                                   executionHosts = execMachines, lifecycleChange="start")
        self.bkgProcess = bkgProcess
    def processCompleted(self):
        return self.bkgProcess.hasTerminated()
    def killProcess(self):
        if self.bkgProcess and self.bkgProcess.processId:
            print "Killing running test (process id", str(self.bkgProcess.processId) + ")"
            self.bkgProcess.killAll()
        return 1

# Poll CPU time values as well
class WindowsRunning(Running):
    def __init__(self, execMachines, bkgProcess = None, freeText = "", briefText = ""):
        Running.__init__(self, execMachines, bkgProcess, freeText, briefText)
        self.latestCpu = 0.0
        self.cpuDelta = 0.0
    def processCompleted(self):
        newCpu = self.bkgProcess.getCpuTime()
        if newCpu is None:
            return 1
        self.cpuDelta = newCpu - self.latestCpu
        self.latestCpu = newCpu
        return 0
    def getProcessCpuTime(self):
        # Assume it finished linearly halfway between the last poll and now...
        return self.latestCpu + (self.cpuDelta / 2.0)

class RunTest(plugins.Action):
    if os.name == "posix":
        runningClass = Running
    else:
        runningClass = WindowsRunning
    def __init__(self):
        self.diag = plugins.getDiagnostics("run test")
    def __repr__(self):
        return "Running"
    def __call__(self, test, inChild=0):
        # Change to the directory so any incidental files can be found easily
        os.chdir(test.writeDirectory)
        return self.runTest(test, inChild)
    def getExecutionMachines(self, test):
        return [ gethostname() ]
    def changeToRunningState(self, test, process):
        execMachines = self.getExecutionMachines(test)
        self.diag.info("Changing " + repr(test) + " to state Running on " + repr(execMachines))
        briefText = self.getBriefText(execMachines)
        freeText = "Running on " + string.join(execMachines, ",")
        newState = self.runningClass(execMachines, process, briefText=briefText, freeText=freeText)
        test.changeState(newState)
    def getBriefText(self, execMachines):
        # Default to not bothering to print the machine name: all is local anyway
        return ""
    def updateStateAfterRun(self, test):
        # space to add extra states after running
        pass
    def runTest(self, test, inChild=0):
        if test.state.hasStarted():
            if test.state.processCompleted():
                self.diag.info("Process completed.")
                return
            else:
                self.diag.info("Process not complete yet, retrying...")
                return self.RETRY

        testCommand = self.getExecuteCommand(test)
        self.describe(test)
        if os.name == "nt" and plugins.BackgroundProcess.processHandler.processManagement == 0:
            self.changeToRunningState(test, None)
            os.system(testCommand)
            return
        process = plugins.BackgroundProcess(testCommand, testRun=1)
        # Working around Python bug
        test.changeState(Pending(process))
        process.waitForStart()
        if not inChild:
            self.changeToRunningState(test, process)
        return self.RETRY
    def getExecuteCommand(self, test):
        testCommand = test.getExecuteCommand()
        if self.recordMode == "console" and test.app.useSlowMotion():
            # Replaying in a shell, need everything visible...
            return testCommand
        testCommand += " < " + self.getInputFile(test)
        outfile = test.makeFileName("output", temporary=1)
        testCommand += " > " + outfile
        errfile = test.makeFileName("errors", temporary=1)
        return self.getStdErrRedirect(testCommand, errfile)
    def getStdErrRedirect(self, command, file):
        return command + " 2> " + file
    def getInputFile(self, test):
        inputFileName = test.inputFile
        if os.path.isfile(inputFileName):
            return inputFileName
        if os.name == "posix":
            return "/dev/null"
        else:
            return "nul"
    def getInterruptActions(self):
        return [ KillTest() ]
    def setUpSuite(self, suite):
        self.describe(suite)
    def setUpApplication(self, app):
        app.checkBinaryExists()
        self.recordMode = app.getConfigValue("use_case_record_mode")

class KillTest(plugins.Action):
    def __call__(self, test):
        if not test.state.hasStarted():
            raise plugins.TextTestError, "Termination already in progress before test started."
        
        test.state.killProcess()
        briefText, fullText = self.getKillInfo(test)
        freeText = "Test " + fullText + "\n"
        newState = plugins.TestState("killed", briefText=briefText, freeText=freeText, \
                                     started=1, executionHosts=test.state.executionHosts)
        test.changeState(newState)
    def getKillInfo(self, test):
        briefText = self.getBriefText(test, str(sys.exc_value))
        if briefText:
            return briefText, self.getFullText(briefText)
        else:
            return "quit", "terminated by quitting"
    def getBriefText(self, test, origBriefText):
        return origBriefText
    def getFullText(self, briefText):
        if briefText.startswith("RUNLIMIT"):
            return "exceeded maximum wallclock time allowed"
        elif briefText == "CPULIMIT":
            return "exceeded maximum cpu time allowed"
        elif briefText.startswith("signal"):
            return "terminated by " + briefText
        else:
            return briefText

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
        pathsLost, pathsEdited, pathsGained = self.findDifferences(oldPaths, newPaths, test.writeDirectory)
        processesGained = self.findProcessesGained(test)
        fileName = test.makeFileName("catalogue", temporary=1)
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
        logFile = test.makeFileName(test.getConfigValue("log_file"), temporary=1)
        if not os.path.isfile(logFile):
            return []
        for line in open(logFile).xreadlines():
            if line.startswith(searchString):
                parts = line.strip().split(" : ")
                processId = int(parts[-1])
                process = plugins.Process(processId)
                self.diag.info("Found process ID " + str(processId))
                if not process.hasTerminated():
                    process.killAll()
                    processes.append(parts[1])
        return processes
    def findAllPaths(self, test):
        allPaths = seqdict()
        if os.path.isdir(test.writeDirectory):
            # Don't list the framework's own temporary files
            pathsToIgnore = [ "framework_tmp", "file_edits", "Diagnostics" ]
            self.listDirectory(test.app, test.writeDirectory, allPaths, pathsToIgnore)
        return allPaths
    def listDirectory(self, app, dir, allPaths, pathsToIgnore=[]):
        # Never list special directories (CVS is the one we know about...)
        pathsToIgnore.append("CVS")
        subDirs = []
        availPaths = os.listdir(dir)
        availPaths.sort()
        for writeFile in availPaths:
            if writeFile in pathsToIgnore:
                continue
            fullPath = os.path.join(dir, writeFile)
            # important not to follow soft links in catalogues...
            if os.path.isdir(fullPath) and not os.path.islink(fullPath):
                subDirs.append(fullPath)
            if not app.ownsFile(writeFile, unknown=0):
                editInfo = self.getEditInfo(fullPath)
                self.diag.info("Path " + fullPath + " edit info " + str(editInfo))
                allPaths[fullPath] = editInfo
                
        for subDir in subDirs:
            self.listDirectory(app, subDir, allPaths)
    def getEditInfo(self, fullPath):
        # Check modified times for files and directories, targets for links
        if os.path.islink(fullPath):
            return os.path.realpath(fullPath)
        else:
            return plugins.modifiedTime(fullPath)
    def findDifferences(self, oldPaths, newPaths, writeDir):
        pathsGained, pathsEdited, pathsLost = [], [], []
        for path, modTime in newPaths.items():
            if not oldPaths.has_key(path):
                pathsGained.append(self.outputPathName(path, writeDir))
            elif modTime != oldPaths[path]:
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
            toRemove.remove(path)
    def outputPathName(self, path, writeDir):
        self.diag.info("Output name for " + path)
        if path.startswith(writeDir):
            return path.replace(writeDir, "<Test Directory>")
        else:
            return path
                    
class CountTest(plugins.Action):
    def __init__(self):
        self.appCount = {}
    def __del__(self):
        for app, count in self.appCount.items():
            print "Application", app, "has", count, "tests"
    def scriptDoc(self):
        return "report on the number of tests selected, by application"
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
    def __init__(self, fetchUser, fullRecalculate):
        self.fetchUser = fetchUser
        self.rootDirToCopy = None
        self.fullRecalculate = fullRecalculate
        self.diag = plugins.getDiagnostics("Reconnection")
    def __repr__(self):
        if self.fullRecalculate:
            return "Copying files for recalculation of"
        else:
            return "Reconnecting to"
    def __call__(self, test):
        self.performReconnection(test)
        self.loadStoredState(test)
    def performReconnection(self, test):
        reconnLocation = os.path.join(self.rootDirToCopy, test.getRelPath())

        if self.fullRecalculate:
            self.copyFiles(reconnLocation, test)
        else:
            test.writeDirectory = reconnLocation
    def copyFiles(self, reconnLocation, test):
        if not self.canReconnectTo(reconnLocation):
            return
        for file in os.listdir(reconnLocation):
            fullPath = os.path.join(reconnLocation, file)
            if os.path.isfile(fullPath):
                shutil.copyfile(fullPath, os.path.join(test.writeDirectory, file))
        testStateFile = os.path.join(reconnLocation, "framework_tmp", "teststate")
        if os.path.isfile(testStateFile):
            shutil.copyfile(testStateFile, test.getStateFile())
    def loadStoredState(self, test):
        storedState = test.getStoredState()
        if self.fullRecalculate:
            # Only pick up errors here, recalculate the rest. Don't notify until
            # we're done with recalculation.
            if not storedState.hasResults():
                test.changeState(storedState)
            else:
                # Also pick up execution machines, we can't get them otherwise...
                test.state.executionHosts = storedState.executionHosts
        else:
            test.changeState(storedState)

        # State will refer to TEXTTEST_HOME in the original (which we may not have now,
        # and certainly don't want to save), try to fix this...
        test.state.updatePaths(test.app.abspath, self.rootDirToCopy)
        self.describe(test, " (state " + test.state.category + ")")
    def canReconnectTo(self, dir):
        # If the directory does not exist or is empty, we cannot reconnect to it.
        return os.path.exists(dir) and len(os.listdir(dir)) > 0
    def setUpApplication(self, app):
        userToFind, fetchDir = app.getPreviousWriteDirInfo(self.fetchUser)
        self.rootDirToCopy = self.findReconnDirectory(fetchDir, app, userToFind)
        if self.rootDirToCopy:
            print "Reconnecting to test results in directory", self.rootDirToCopy
            if not self.fullRecalculate:
                app.writeDirectory = self.rootDirToCopy
        else:
            raise plugins.TextTestError, "Could not find any runs matching " + app.name + app.versionSuffix() + userToFind + " under " + fetchDir
    def findReconnDirectory(self, fetchDir, app, userToFind):
        if not os.path.isdir(fetchDir):
            return None

        versions = app.getVersionFileExtensions()
        versions.append("")
        for versionSuffix in versions:
            reconnDir = self.findReconnDirWithVersion(fetchDir, app, versionSuffix, userToFind)
            if reconnDir:
                return reconnDir
    def findReconnDirWithVersion(self, fetchDir, app, versionSuffix, userToFind):
        if versionSuffix:
            patternToFind = app.name + "." + versionSuffix + userToFind
        else:
            patternToFind = app.name + userToFind
        fileList = os.listdir(fetchDir)
        fileList.sort()
        fileList.reverse()
        for subDir in fileList:
            fullPath = os.path.join(fetchDir, subDir)
            if os.path.isdir(fullPath) and subDir.startswith(patternToFind) and not plugins.samefile(fullPath, app.writeDirectory):
                return fullPath
    def setUpSuite(self, suite):
        self.describe(suite)

class MachineInfoFinder:
    def findPerformanceMachines(self, app, fileStem):
        return app.getCompositeConfigValue("performance_test_machine", fileStem)
    def setUpApplication(self, app):
        pass

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
            return 1
        for host in test.state.executionHosts:
            realHost = host
            # Format support e.g. 2*apple for multi-processor machines
            if host[1] == "*":
                realHost = host[2:]
            if not realHost in performanceMachines:
                self.diag.info("Real host rejected for performance " + realHost)
                return 0
        return 1
    def __call__(self, test, temp=1):
        return self.makePerformanceFiles(test, temp)

class UNIXPerformanceInfoFinder:
    def __init__(self, diag):
        self.diag = diag
        self.includeSystemTime = 0
    def findTimesUsedBy(self, test):
        # Read the UNIX performance file, allowing us to discount system time.
        tmpFile = test.makeFileName("unixperf", temporary=1, forComparison=0)
        self.diag.info("Reading performance file " + tmpFile)
        if not os.path.isfile(tmpFile):
            return None, None
            
        file = open(tmpFile)
        cpuTime = None
        realTime = None
        for line in file.readlines():
            self.diag.info("Parsing line " + line.strip())
            if line.startswith("user"):
                cpuTime = self.parseUnixTime(line)
            if self.includeSystemTime and line.startswith("sys"):
                cpuTime = cpuTime + self.parseUnixTime(line)
            if line.startswith("real"):
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

class WindowsPerformanceInfoFinder:
    def findTimesUsedBy(self, test):
        # On Windows, these are collected by the process polling
        return test.state.getProcessCpuTime(), None
    def setUpApplication(self, app):
        pass

# Class for making a performance file directly from system-collected information,
# rather than parsing reported entries in a log file
class MakePerformanceFile(PerformanceFileCreator):
    def __init__(self, machineInfoFinder):
        PerformanceFileCreator.__init__(self, machineInfoFinder)
        if os.name == "posix":
            self.systemPerfInfoFinder = UNIXPerformanceInfoFinder(self.diag)
        else:
            self.systemPerfInfoFinder = WindowsPerformanceInfoFinder()
    def setUpApplication(self, app):
        PerformanceFileCreator.setUpApplication(self, app)
        self.systemPerfInfoFinder.setUpApplication(app)
    def __repr__(self):
        return "Making performance file for"
    def makePerformanceFiles(self, test, temp):
        # Check that all of the execution machines are also performance machines
        if not self.allMachinesTestPerformance(test, "cputime"):
            return
        cpuTime, realTime = self.systemPerfInfoFinder.findTimesUsedBy(test)
        # There was still an error (jobs killed in emergency), so don't write performance files
        if cpuTime == None:
            print "Not writing performance file for", test
            return
        
        fileToWrite = test.makeFileName("performance", temporary=1)
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
        self.writeMachineInformation(file, test)
    def writeMachineInformation(self, file, test):
        # A space for subclasses to write whatever they think is relevant about
        # the machine environment right now.
        pass


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
    def makePerformanceFiles(self, test, temp):
        for fileStem, entryFinder in self.entryFinders.items():
            if not self.allMachinesTestPerformance(test, fileStem):
                self.diag.info("Not extracting performance file for " + fileStem + ": not on performance machines")
                continue
            values = []
            for logFileStem in self.findLogFileStems(fileStem):
                logFilePattern = test.makeFileName(logFileStem, temporary=temp)
                for fileName in glob.glob(logFilePattern):
                    values += self.findValues(fileName, entryFinder)
            if len(values) > 0:
                fileName = test.makeFileName(fileStem, temporary=temp)
                lineToWrite = self.makeLine(values, fileStem)
                self.saveFile(fileName, lineToWrite)
    def findLogFileStems(self, fileStem):
        if self.entryFiles.has_key(fileStem):
            return self.entryFiles[fileStem]
        else:
            return [ self.logFileStem ]
    def saveFile(self, fileName, lineToWrite):
        file = open(fileName, "w")
        file.write(lineToWrite + "\n")
        file.close()
    def makeLine(self, values, fileStem):
        # Round to accuracy 0.01
        if fileStem.find("mem") != -1:
            return self.makeMemoryLine(values, fileStem)
        else:
            return self.makeTimeLine(values, fileStem)
    def makeMemoryLine(self, values, fileStem):
        maxVal = max(values)
        roundedMaxVal = float(int(100*maxVal))/100
        return "Max " + string.capitalize(fileStem) + "  :      " + str(roundedMaxVal) + " MB"
    def makeTimeLine(self, values, fileStem):
        sum = 0.0
        for value in values:
            sum += value
        roundedSum = float(int(10*sum))/10
        return "Total " + string.capitalize(fileStem) + "  :      " + str(roundedSum) + " seconds"
    def findValues(self, logFile, entryFinder):
        values = []
        self.diag.info("Scanning log file for entry: " + entryFinder)
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
            return None
        restOfLine = match.group('restofline')
        self.diag.info(" entry found, extracting value from: " + restOfLine)
        try:
            number = float(restOfLine.split()[0])
            if restOfLine.lower().find("kb") != -1:
                number = float(number / 1024.0)
            return number
        except:
            # try parsing the memString as a h*:mm:ss time string
            # * - any number of figures are allowed for the hour part
            timeRegExp = re.compile(r'(?P<hours>\d+)\:(?P<minutes>\d\d)\:(?P<seconds>\d\d)')
            match = timeRegExp.match(restOfLine.split()[0])
            if match:
                hours = float(match.group('hours'))
                minutes = float(match.group('minutes'))
                seconds = float(match.group('seconds'))
                return hours*60*60 + minutes*60 + seconds
            else:
                return None

# A standalone action, we add description and generate the main file instead...
class ExtractStandardPerformance(ExtractPerformanceFiles):
    def __init__(self):
        ExtractPerformanceFiles.__init__(self, MachineInfoFinder())
    def __repr__(self):
        return "Extracting standard performance for"
    def scriptDoc(self):
        return "update the standard performance files from the standard log files"
    def __call__(self, test):
        self.describe(test)
        ExtractPerformanceFiles.__call__(self, test, temp=0)
    def allMachinesTestPerformance(self, test, fileStem):
        # Assume this is OK: the current host is in any case utterly irrelevant
        return 1
    def setUpSuite(self, suite):
        self.describe(suite)

class DocumentOptions(plugins.Action):
    def setUpApplication(self, app):
        keys = []
        for group in app.optionGroups:
            keys += group.options.keys()
            keys += group.switches.keys()
        keys.sort()
        for key in keys:
            self.displayKey(key, app.optionGroups)
    def displayKey(self, key, groups):
        for group in groups:
            if group.options.has_key(key):
                keyOutput, docOutput = self.optionOutput(key, group, group.options[key].name)
                self.display(keyOutput, self.groupOutput(group), docOutput)
            if group.switches.has_key(key):    
                self.display("-" + key, self.groupOutput(group), group.switches[key].name)
    def display(self, keyOutput, groupOutput, docOutput):
        if not docOutput.startswith("Private"):
            print keyOutput + ";" + groupOutput + ";" + docOutput.replace("SGE", "SGE/LSF")
    def groupOutput(self, group):
        if group.name == "Invisible":
            return "N/A"
        elif group.name == "SGE":
            return "SGE/LSF"
        else:
            return group.name
    def optionOutput(self, key, group, docs):
        keyOutput = "-" + key + " <value>"
        if docs.find("<") != -1:
            keyOutput = self.filledOptionOutput(key, docs)
        else:
            docs += " <value>"
        if group.name.startswith("Select"):
            return keyOutput, "Select " + docs.lower()
        else:
            return keyOutput, docs
    def filledOptionOutput(self, key, docs):
        start = docs.find("<")
        end = docs.find(">", start)
        filledPart = docs[start:end + 1]
        return "-" + key + " " + filledPart

class DocumentConfig(plugins.Action):
    def setUpApplication(self, app):
        for key, value in app.configDir.items():
            print key + "|" + str(value) + "|" + app.configDocs[key]

class DocumentScripts(plugins.Action):
    def setUpApplication(self, app):
        modNames = [ "batch", "comparetest", "default", "performance", "predict" ]
        for modName in modNames:
            importCommand = "import " + modName
            exec importCommand
            command = "names = dir(" + modName + ")"
            exec command
            for name in names:
                scriptName = modName + "." + name
                constructCommand = "obj = " + scriptName + "()"
                try:
                    exec constructCommand
                except TypeError:
                    continue
                try:
                    docString = obj.scriptDoc()
                    print scriptName + "|" + docString
                except AttributeError:
                    pass

class ReplaceText(plugins.Action):
    def __init__(self, args):
        argDict = self.parseArguments(args)
        self.oldText = argDict["old"]
        self.newText = argDict["new"]
        self.logFile = None
        if argDict.has_key("file"):
            self.logFile = argDict["file"]
        self.textDiffTool = None
    def __repr__(self):
        return "Replacing " + self.oldText + " with " + self.newText + " for"
    def parseArguments(self, args):
        currKey = ""
        dict = {}
        for arg in args:
            if arg.find("=") != -1:
                currKey, val = arg.split("=")
                dict[currKey] = val
            else:
                dict[currKey] += " " + arg
        return dict
    def __call__(self, test):
        self.describe(test)
        sys.stdout.flush()
        logFile = test.makeFileName(self.logFile)
        newLogFile = test.makeFileName("new_" + self.logFile)
        writeFile = open(newLogFile, "w")
        for line in open(logFile).xreadlines():
            writeFile.write(line.replace(self.oldText, self.newText))
        writeFile.close()
        os.system(self.textDiffTool + " " + logFile + " " + newLogFile)
        os.rename(newLogFile, logFile)
    def setUpSuite(self, suite):
        self.describe(suite)
    def setUpApplication(self, app):
        if not self.logFile:
            self.logFile = app.getConfigValue("log_file")
        self.textDiffTool = plugins.findDiffTool(app.getConfigValue("text_diff_program"))
