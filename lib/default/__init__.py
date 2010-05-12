
import os, sys, plugins, sandbox, console, rundependent, pyusecase_interface, comparetest, batch, performance, subprocess, operator, signal, shutil, logging

from copy import copy
from fnmatch import fnmatch
from string import Template
from threading import Lock, Timer
from knownbugs import CheckForBugs, CheckForCrashes
from reconnect import ReconnectConfig
from traffic import SetUpTrafficHandlers
from jobprocess import killSubProcessAndChildren
from actionrunner import ActionRunner
from time import sleep
from StringIO import StringIO
from ndict import seqdict

plugins.addCategory("killed", "killed", "were terminated before completion")

def getConfig(optionMap):
    return Config(optionMap)

class Config:
    def __init__(self, optionMap):
        self.optionMap = optionMap
        self.filterFileMap = {}
        self.reconnectConfig = ReconnectConfig(optionMap)
    def getMachineNameForDisplay(self, machine):
        return machine # override for queuesystems
    def getCheckoutLabel(self):
        return "Use checkout"
    def getMachineLabel(self):
        return "Run on machine"
    def addToOptionGroups(self, apps, groups):
        recordsUseCases = len(apps) == 0 or self.anyAppHas(apps, lambda app: app.getConfigValue("use_case_record_mode") != "disabled")
        useCatalogues = self.anyAppHas(apps, self.isolatesDataUsingCatalogues)
        for group in groups:
            if group.name.startswith("Select"):
                group.addOption("t", "Test names containing", description="Select tests for which the name contains the entered text. The text can be a regular expression.")
                group.addOption("ts", "Test paths containing", description="Select tests for which the full path to the test (e.g. suite1/subsuite/testname) contains the entered text. The text can be a regular expression. You can select tests by suite name this way.")
                group.addOption("a", "App names containing", description="Select tests for which the application name matches the entered text. The text can be a regular expression.")
                possibleDirs = self.getFilterFileDirectories(apps, useOwnTmpDir=True)
                group.addOption("f", "Tests listed in file", possibleDirs=possibleDirs, selectFile=True)
                group.addOption("desc", "Descriptions containing", description="Select tests for which the description (comment) matches the entered text. The text can be a regular expression.")
                group.addOption("r", "Execution time", description="Specify execution time limits, either as '<min>,<max>', or as a list of comma-separated expressions, such as >=0:45,<=1:00. Digit-only numbers are interpreted as minutes, while colon-separated numbers are interpreted as hours:minutes:seconds.")
                group.addOption("grep", "Test-files containing", description="Select tests which have a file containing the entered text. The text can be a regular expression : e.g. enter '.*' to only look for the file without checking the contents.")
                group.addOption("grepfile", "Test-file to search", allocateNofValues=2, description="When the 'test-files containing' field is non-empty, apply the search in files with the given stem. Unix-style file expansion (note not regular expressions) may be used. For example '*' will look in any file.")
            elif group.name.startswith("Basic"):
                if len(apps) > 0:
                    version, checkout, machine = apps[0].getFullVersion(), apps[0].checkout, apps[0].getRunMachine()
                else:
                    version, checkout, machine = "", "", ""
                group.addOption("v", "Run this version", version)
                group.addOption("c", self.getCheckoutLabel(), checkout)
                group.addOption("m", self.getMachineLabel(), self.getMachineNameForDisplay(machine))
                group.addOption("cp", "Times to run", "1", description="Set this to some number larger than 1 to run the same test multiple times, for example to try to catch indeterminism in the system under test")
                if recordsUseCases:
                    group.addSwitch("actrep", "Run with slow motion replay")
                if useCatalogues:
                    group.addSwitch("ignorecat", "Ignore catalogue file when isolating data")
            elif group.name.startswith("Advanced"):
                group.addSwitch("x", "Enable self-diagnostics")
                defaultDiagDir = plugins.getPersonalDir("log")
                group.addOption("xr", "Configure self-diagnostics from", os.path.join(defaultDiagDir, "logging.debug"),
                                possibleValues=[ os.path.join(plugins.installationDir("log"), "logging.debug") ])
                group.addOption("xw", "Write self-diagnostics to", defaultDiagDir)
                group.addOption("b", "Run batch mode session")
                group.addOption("name", "Name this run", self.optionValue("name"))
                group.addSwitch("rectraffic", "(Re-)record command-line or client-server traffic")
                group.addSwitch("keeptmp", "Keep temporary write-directories")
                group.addOption("vanilla", "Ignore configuration files", self.defaultVanillaValue(),
                                possibleValues = [ "", "site", "personal", "all" ])
                group.addSwitch("ignorefilters", "Ignore all run-dependent text filtering")
            elif group.name.startswith("Invisible"):
                # Options that don't make sense with the GUI should be invisible there...
                group.addOption("s", "Run this script")
                group.addOption("d", "Look for test files under")
                group.addSwitch("help", "Print configuration help text on stdout")
                group.addSwitch("g", "use dynamic GUI")
                group.addSwitch("gx", "use static GUI")
                group.addSwitch("con", "use console interface")
                group.addSwitch("coll", "Collect results for batch mode session")
                group.addOption("tp", "Private: Tests with exact path") # use for internal communication
                group.addOption("finverse", "Tests not listed in file")
                group.addOption("fintersect", "Tests in all files")
                group.addOption("funion", "Tests in any of files")
                group.addOption("fd", "Private: Directory to search for filter files in")
                group.addOption("count", "Private: How many tests we believe there will be")
                group.addOption("o", "Overwrite failures, optionally using version")
                group.addOption("reconnect", "Reconnect to previous run")
                group.addSwitch("reconnfull", "Recompute file filters when reconnecting", options=self.getReconnFullOptions())
                group.addSwitch("n", "Create new results files (overwrite everything)")
                group.addSwitch("new", "Start static GUI with no applications loaded")
                group.addOption("bx", "Use extra versions as for batch mode session")
                if recordsUseCases:
                    group.addSwitch("record", "Private: Record usecase rather than replay what is present")
                    group.addSwitch("autoreplay", "Private: Used to flag that the run has been autogenerated")
                else:
                    # We may have other apps that do this, don't reject these options
                    group.addSwitch("actrep", "Run with slow motion replay")
                if not useCatalogues:
                    group.addSwitch("ignorecat", "Ignore catalogue file when isolating data")

    def getReconnFullOptions(self):
        return ["Display results exactly as they were in the original run",
                "Use raw data from the original run, but recompute run-dependent text, known bug information etc."]

    def anyAppHas(self, apps, propertyMethod):
        for app in apps:
            for partApp in [ app ] + app.extras:
                if propertyMethod(partApp):
                    return True
        return False

    def defaultVanillaValue(self):
        if not self.optionMap.has_key("vanilla"):
            return ""
        given = self.optionValue("vanilla")
        if given:
            return given
        else:
            return "all"

    def createOptionGroups(self, allApps):
        groupNames = [ "Selection", "Basic", "Advanced", "Invisible" ]
        optionGroups = map(plugins.OptionGroup, groupNames)
        self.addToOptionGroups(allApps, optionGroups)
        return optionGroups
    
    def findAllValidOptions(self, allApps):
        groups = self.createOptionGroups(allApps)
        return reduce(operator.add, (g.keys() for g in groups), [])

    def getCollectSequence(self):
        arg = self.optionMap.get("coll")
        sequence = []
        batchArgs = [ "batch=" + self.optionValue("b") ]
        if not arg or "web" not in arg:
            emailHandler = batch.CollectFiles(batchArgs)
            sequence.append(emailHandler)
        if not arg or arg == "web":
            summaryGenerator = batch.GenerateSummaryPage(batchArgs)
            sequence.append(summaryGenerator)
        return sequence

    def getActionSequence(self):
        if self.optionMap.has_key("coll"):
            return self.getCollectSequence()

        if self.isReconnecting():
            return self.getReconnectSequence()

        scriptObject = self.optionMap.getScriptObject()
        if scriptObject:
            if self.usesComparator(scriptObject):
                return [ self.getWriteDirectoryMaker(), scriptObject, comparetest.MakeComparisons(ignoreMissing=True) ]
            else:
                return [ scriptObject ]
        else:
            return self.getTestProcessor()

    def usesComparator(self, scriptObject):
        try:
            return scriptObject.usesComparator()
        except AttributeError:
            return False

    def useGUI(self):
        return self.optionMap.has_key("g") or self.optionMap.has_key("gx")

    def useStaticGUI(self, app):
        return self.optionMap.has_key("gx") or \
               (not self.hasExplicitInterface() and app.getConfigValue("default_interface") == "static_gui")

    def useConsole(self):
        return self.optionMap.has_key("con")

    def getExtraVersions(self, app):
        fromConfig = self.getExtraVersionsFromConfig(app)
        fromCmd = self.getExtraVersionsFromCmdLine(app, fromConfig)
        return self.createComposites(fromConfig, fromCmd)

    def createComposites(self, vlist1, vlist2):
        allVersions = copy(vlist1)        
        for v2 in vlist2:
            allVersions.append(v2)
            for v1 in vlist1:
                allVersions.append(v2 + "." + v1)

        return allVersions

    def getExtraVersionsFromCmdLine(self, app, fromConfig):
        if self.isReconnecting():
            return self.reconnectConfig.getExtraVersions(app, fromConfig)
        else:
            copyVersions = self.getCopyExtraVersions()
            checkoutVersions = self.getCheckoutExtraVersions()
            return self.createComposites(checkoutVersions, copyVersions)

    def getCopyExtraVersions(self):
        try:
            copyCount = int(self.optionMap.get("cp", 1))
        except TypeError:
            copyCount = 1
        return [ "copy_" + str(i) for i in range(1, copyCount) ]

    def versionNameFromCheckout(self, c):
        return c.replace("\\", "_").replace("/", "_").replace(".", "_")

    def getCheckoutExtraVersions(self):    
        checkoutNames = plugins.commasplit(self.optionValue("c"))[1:]
        return map(self.versionNameFromCheckout, checkoutNames)
        
    def getExtraVersionsFromConfig(self, app):
        basic = app.getConfigValue("extra_version")
        batchSession = self.optionMap.get("b") or self.optionMap.get("bx")
        if batchSession is not None:
            for batchExtra in app.getCompositeConfigValue("batch_extra_version", batchSession):
                if batchExtra not in basic:
                    basic.append(batchExtra)
        for extra in basic:
            if extra in app.versions:
                return []
        return basic

    def getDefaultInterface(self, allApps):
        if self.optionMap.has_key("s"):
            return "console"
        elif len(allApps) == 0 or self.optionMap.has_key("new"):
            return "static_gui"

        defaultIntf = None
        for app in allApps:
            appIntf = app.getConfigValue("default_interface")
            if defaultIntf and appIntf != defaultIntf:
                raise plugins.TextTestError, "Conflicting default interfaces for different applications - " + \
                      appIntf + " and " + defaultIntf
            defaultIntf = appIntf
        return defaultIntf

    def setDefaultInterface(self, allApps):
        mapping = { "static_gui" : "gx", "dynamic_gui": "g", "console": "con" }
        defaultInterface = self.getDefaultInterface(allApps)
        if mapping.has_key(defaultInterface):
            self.optionMap[mapping[defaultInterface]] = ""
        else:
            raise plugins.TextTestError, "Invalid value for default_interface '" + defaultInterface + "'"
        
    def hasExplicitInterface(self):
        return self.useGUI() or self.batchMode() or self.useConsole() or self.optionMap.has_key("o")

    def getLogfilePostfixes(self):
        if self.optionMap.has_key("x"):
            return [ "debug" ]
        elif self.optionMap.has_key("gx"):
            return [ "gui", "static_gui" ]
        elif self.optionMap.has_key("g"):
            return [ "gui", "dynamic_gui" ]
        elif self.batchMode():
            return [ "console", "batch" ]
        else:
            return [ "console" ]
        
    def setUpLogging(self):
        filePatterns = [ "logging." + postfix for postfix in self.getLogfilePostfixes() ]
        includeSite, includePersonal = self.optionMap.configPathOptions()
        allPaths = plugins.findDataPaths(filePatterns, includeSite, includePersonal, dataDirName="log")
        if len(allPaths) > 0:
            plugins.configureLogging(allPaths[-1]) # Won't have any effect if we've already got a log file
        else:
            plugins.configureLogging()
            
    def getResponderClasses(self, allApps):
        # Global side effects first :)
        if not self.hasExplicitInterface():
            self.setDefaultInterface(allApps)

        self.setUpLogging()
        return self._getResponderClasses(allApps)

    def _getResponderClasses(self, allApps):
        classes = []        
        if not self.optionMap.has_key("gx"):
            if self.optionMap.has_key("new"):
                raise plugins.TextTestError, "'--new' option can only be provided with the static GUI"
            elif len(allApps) == 0:
                raise plugins.TextTestError, "Could not find any matching applications (files of the form config.<app>) under " + " or ".join(self.optionMap.rootDirectories)
            
        if self.useGUI():
            self.addGuiResponder(classes)
        else:
            classes.append(self.getTextDisplayResponderClass())
        if not self.optionMap.has_key("gx"):
            classes += self.getThreadActionClasses()

        if self.batchMode() and not self.optionMap.has_key("s"):
            if self.optionMap.has_key("coll"):
                if self.optionMap["coll"] != "mail": 
                    classes.append(batch.WebPageResponder)
            else:
                if self.optionValue("b") is None:
                    plugins.log.info("No batch session identifier provided, using 'default'")
                    self.optionMap["b"] = "default"
                classes.append(batch.BatchResponder)
                classes.append(batch.junitreport.JUnitResponder)
        if self.useVirtualDisplay():
            from virtualdisplay import VirtualDisplayResponder
            classes.append(VirtualDisplayResponder)
        if self.keepTemporaryDirectories():
            classes.append(self.getStateSaver())
        if not self.useGUI() and not self.batchMode():
            classes.append(self.getTextResponder())
        # At the end, so we've done the processing before we proceed
        classes.append(pyusecase_interface.ApplicationEventResponder)
        return classes

    def isActionReplay(self):
        for option, desc in self.getInteractiveReplayOptions():
            if self.optionMap.has_key(option):
                return True
        return False

    def noFileAdvice(self):
        # What can we suggest if files aren't present? In this case, not much
        return ""
        
    def useVirtualDisplay(self):
        # Don't try to set it if we're using the static GUI or
        # we've requested a slow motion replay or we're trying to record a new usecase.
        return not self.optionMap.has_key("record") and not self.optionMap.has_key("gx") and \
               not self.isActionReplay() and not self.optionMap.has_key("coll") and not self.optionMap.runScript()
    
    def getThreadActionClasses(self):
        return [ ActionRunner ]

    def getTextDisplayResponderClass(self):
        return console.TextDisplayResponder

    def isolatesDataUsingCatalogues(self, app):
        return app.getConfigValue("create_catalogues") == "true" and \
               len(app.getConfigValue("partial_copy_test_path")) > 0

    def hasWritePermission(self, path):
        if os.path.isdir(path):
            return os.access(path, os.W_OK)
        else:
            return self.hasWritePermission(os.path.dirname(path))

    def getWriteDirectory(self, app):
        rootDir = self.optionMap.setPathFromOptionsOrEnv("TEXTTEST_TMP", app.getConfigValue("default_texttest_tmp")) # Location of temporary files from test runs
        if not os.path.isdir(rootDir) and not self.hasWritePermission(os.path.dirname(rootDir)):
            rootDir = self.optionMap.setPathFromOptionsOrEnv("", "$TEXTTEST_PERSONAL_CONFIG/tmp")
        return os.path.join(rootDir, self.getWriteDirectoryName(app))

    def getWriteDirectoryName(self, app):
        parts = self.getBasicRunDescriptors(app) + self.getVersionDescriptors() + [ self.getTimeDescriptor(), str(os.getpid()) ]
        return ".".join(parts)

    def getBasicRunDescriptors(self, app):
        appDescriptors = self.getAppDescriptors()
        if self.useStaticGUI(app):
            return [ "static_gui" ] + appDescriptors
        elif appDescriptors:
            return appDescriptors
        elif self.optionValue("b"):
            return [ self.optionValue("b") ]
        elif self.optionMap.has_key("g"):
            return [ "dynamic_gui" ]
        else:
            return [ "console" ]

    def getTimeDescriptor(self):
        return plugins.startTimeString().replace(":", "")

    def getAppDescriptors(self):
        givenAppDescriptor = self.optionValue("a")
        if givenAppDescriptor and givenAppDescriptor.find(",") == -1:
            return [ givenAppDescriptor ]
        else:
            return []

    def getVersionDescriptors(self):
        givenVersion = self.optionValue("v")
        if givenVersion:
            # Commas in path names are a bit dangerous, some applications may have arguments like
            # -path path1,path2 and just do split on the path argument.
            # We try something more obscure instead...
            return [ "++".join(plugins.commasplit(givenVersion)) ]
        else:
            return []

    def addGuiResponder(self, classes):
        from gtkgui.controller import GUIController
        classes.append(GUIController)

    def getReconnectSequence(self):
        actions = [ self.reconnectConfig.getReconnectAction() ]
        actions += [ self.getOriginalFilterer(), self.getTemporaryFilterer(), \
                     self.getTestComparator(), self.getFailureExplainer() ]
        return actions

    def getOriginalFilterer(self):
        if not self.optionMap.has_key("ignorefilters"):
            return rundependent.FilterOriginal(useFilteringStates=not self.batchMode())

    def getTemporaryFilterer(self):
        if not self.optionMap.has_key("ignorefilters"):
            return rundependent.FilterTemporary(useFilteringStates=not self.batchMode())
    
    def filterErrorText(self, app, errFile):
        runDepFilter = rundependent.RunDependentTextFilter(app.getConfigValue("suppress_stderr_text"), "")
        outFile = StringIO()
        runDepFilter.filterFile(open(errFile), outFile)
        value = outFile.getvalue()
        outFile.close()
        return value

    def getTestProcessor(self):        
        catalogueCreator = self.getCatalogueCreator()
        ignoreCatalogues = self.shouldIgnoreCatalogues()
        collator = self.getTestCollator()
        trafficHandler = SetUpTrafficHandlers(self.optionMap.has_key("rectraffic"))
        return [ self.getExecHostFinder(), self.getWriteDirectoryMaker(), \
                 self.getWriteDirectoryPreparer(ignoreCatalogues), \
                 trafficHandler, catalogueCreator, collator, self.getOriginalFilterer(), self.getTestRunner(), \
                 trafficHandler, catalogueCreator, collator, self.getTestEvaluator() ]
    def shouldIgnoreCatalogues(self):
        return self.optionMap.has_key("ignorecat") or self.optionMap.has_key("record")
    def hasPerformance(self, app):
        if len(app.getConfigValue("performance_logfile_extractor")) > 0:
            return True
        return self.hasAutomaticCputimeChecking(app)
    def hasAutomaticCputimeChecking(self, app):
        return len(app.getCompositeConfigValue("performance_test_machine", "cputime")) > 0
    def getFilterFileDirectories(self, apps, useOwnTmpDir):
        # 
        # - For each application, collect
        #   - temporary filter dir
        #   - all dirs in filter_file_directory
        #
        # Add these to a list. Never add the same dir twice. The first item will
        # be the default save/open dir, and the others will be added as shortcuts.
        #
        dirs = []
        for app in apps:
            appDirs = app.getConfigValue("filter_file_directory")
            tmpDir = self.getTmpFilterDir(app, useOwnTmpDir)
            if tmpDir and tmpDir not in dirs:
                dirs.append(tmpDir)

            for dir in appDirs:
                if os.path.isabs(dir) and os.path.isdir(dir):
                    if dir not in dirs:
                        dirs.append(dir)
                else:
                    newDir = os.path.join(app.getDirectory(), dir)
                    if not newDir in dirs:
                        dirs.append(newDir)
        return dirs

    def getTmpFilterDir(self, app, useOwnTmpDir):
        cmdLineDir = self.optionValue("fd")
        if cmdLineDir:
            return os.path.normpath(cmdLineDir)
        elif useOwnTmpDir:
            return os.path.join(app.writeDirectory, "temporary_filter_files")
        
    def getFilterClasses(self):
        return [ TestNameFilter, plugins.TestSelectionFilter, \
                 TestRelPathFilter, performance.TimeFilter, \
                 plugins.ApplicationFilter, TestDescriptionFilter ]
            
    def getAbsoluteFilterFileName(self, filterFileName, app):
        if os.path.isabs(filterFileName):
            if os.path.isfile(filterFileName):
                return filterFileName
            else:
                raise plugins.TextTestError, "Could not find filter file at '" + filterFileName + "'"
        else:
            dirsToSearchIn = self.getFilterFileDirectories([app], useOwnTmpDir=False)
            absName = app.getFileName(dirsToSearchIn, filterFileName)
            if absName:
                return absName
            else:
                raise plugins.TextTestError, "No filter file named '" + filterFileName + "' found in :\n" + \
                      "\n".join(dirsToSearchIn)

    def optionListValue(self, options, key):
        if options.has_key(key):
            return plugins.commasplit(options[key])
        else:
            return []

    def findFilterFileNames(self, app, options, includeConfig):
        names = self.optionListValue(options, "f") + self.optionListValue(options, "fintersect")
        if includeConfig:
            names += app.getConfigValue("default_filter_file")
            if self.batchMode():
                names += app.getCompositeConfigValue("batch_filter_file", options["b"])
        return names

    def findAllFilterFileNames(self, app, options, includeConfig):
        return self.findFilterFileNames(app, options, includeConfig) + \
               self.optionListValue(options, "funion") + self.optionListValue(options, "finverse")

    def getFilterList(self, app, suites, options=None, **kw):
        if options is None:
            return self.filterFileMap.setdefault(app, self._getFilterList(app, self.optionMap, suites, includeConfig=True, **kw))
        else:
            return self._getFilterList(app, options, suites, includeConfig=False, **kw)
        
    def checkFilterFileSanity(self, suite):
        # This will check all the files for existence from the input, and throw if it can't.
        # This is basically because we don't want to throw in a thread when we actually need the filters
        # if they aren't sensible for some reason
        self._checkFilterFileSanity(suite.app, self.optionMap, includeConfig=True)

    def _checkFilterFileSanity(self, app, options, includeConfig=False):
        for filterFileName in self.findAllFilterFileNames(app, options, includeConfig):
            optionFinder = self.makeOptionFinder(app, filterFileName)
            self._checkFilterFileSanity(app, optionFinder)
    
    def _getFilterList(self, app, options, suites, includeConfig, **kw):
        filters = self.getFiltersFromMap(options, app, suites, **kw)
        for filterFileName in self.findFilterFileNames(app, options, includeConfig):
            filters += self.getFiltersFromFile(app, filterFileName, suites)

        orFilterFiles = self.optionListValue(options, "funion")
        if len(orFilterFiles) > 0:
            orFilterLists = [ self.getFiltersFromFile(app, f, suites) for f in orFilterFiles ]
            filters.append(OrFilter(orFilterLists))

        notFilterFile = options.get("finverse")
        if notFilterFile:
            filters.append(NotFilter(self.getFiltersFromFile(app, notFilterFile, suites)))

        return filters

    def makeOptionFinder(self, app, filename):
        absName = self.getAbsoluteFilterFileName(filename, app)
        fileData = ",".join(plugins.readList(absName))
        return plugins.OptionFinder(fileData.split(), defaultKey="t")
        
    def getFiltersFromFile(self, app, filename, suites):
        optionFinder = self.makeOptionFinder(app, filename)
        return self._getFilterList(app, optionFinder, suites, includeConfig=False)
    
    def getFiltersFromMap(self, optionMap, app, suites, **kw):
        filters = []
        for filterClass in self.getFilterClasses():
            argument = optionMap.get(filterClass.option)
            if argument:
                filters.append(filterClass(argument, app, suites))
        batchSession = self.optionMap.get("b")
        if batchSession:
            timeLimit = app.getCompositeConfigValue("batch_timelimit", batchSession)
            if timeLimit:
                filters.append(performance.TimeFilter(timeLimit))
        if optionMap.has_key("grep"):
            grepFile = optionMap.get("grepfile", app.getConfigValue("log_file"))
            filters.append(GrepFilter(optionMap["grep"], grepFile, **kw))
        return filters
    
    def batchMode(self):
        return self.optionMap.has_key("b")
    def keepTemporaryDirectories(self):
        return self.optionMap.has_key("keeptmp") or (self.batchMode() and not self.isReconnecting())
    def cleanPreviousTempDirs(self):
        return self.batchMode() and not self.isReconnecting() and not self.optionMap.has_key("keeptmp")
    def cleanWriteDirectory(self, suite):
        if not self.keepTemporaryDirectories():
            self._cleanWriteDirectory(suite)
            machine, tmpDir = self.getRemoteTmpDirectory(suite.app)
            if tmpDir:
                self.cleanRemoteDir(suite.app, machine, tmpDir)

    def cleanRemoteDir(self, app, machine, tmpDir):
        self.runCommandOn(app, machine, [ "rm", "-rf", tmpDir ])
                
    def _cleanWriteDirectory(self, suite):
        if os.path.isdir(suite.app.writeDirectory):
            plugins.rmtree(suite.app.writeDirectory)

    def makeWriteDirectory(self, app, subdir=None):
        if self.cleanPreviousTempDirs():
            self.cleanPreviousWriteDirs(app.writeDirectory)
            machine, tmpDir = self.getRemoteTmpDirectory(app)
            if tmpDir:
                # Ignore the datetime and the pid at the end
                searchParts = tmpDir.split(".")[:-2] + [ "*" ]
                self.runCommandOn(app, machine, [ "rm", "-rf", ".".join(searchParts) ])

        dirToMake = app.writeDirectory
        if subdir:
            dirToMake = os.path.join(app.writeDirectory, subdir)
        plugins.ensureDirectoryExists(dirToMake)
        app.diag.info("Made root directory at " + dirToMake)
        return dirToMake

    def cleanPreviousWriteDirs(self, writeDir):
        rootDir, basename = os.path.split(writeDir)
        if os.path.isdir(rootDir):
            # Ignore the datetime and the pid at the end
            searchParts = basename.split(".")[:-2]
            for file in os.listdir(rootDir):
                fileParts = file.split(".")
                if fileParts[:-2] == searchParts:
                    previousWriteDir = os.path.join(rootDir, file)
                    if os.path.isdir(previousWriteDir) and not plugins.samefile(previousWriteDir, writeDir):
                        plugins.log.info("Removing previous write directory " + previousWriteDir)
                        plugins.rmtree(previousWriteDir, attempts=3)
    
    def isReconnecting(self):
        return self.optionMap.has_key("reconnect")
    def getWriteDirectoryMaker(self):
        return sandbox.MakeWriteDirectory()
    def getExecHostFinder(self):
        return sandbox.FindExecutionHosts()
    def getWriteDirectoryPreparer(self, ignoreCatalogues):
        return sandbox.PrepareWriteDirectory(ignoreCatalogues)
    def getTestRunner(self):
        return RunTest()
    def getTestEvaluator(self):
        return [ self.getFileExtractor(), self.getTemporaryFilterer(), self.getTestComparator(), self.getFailureExplainer() ]
    def getFileExtractor(self):
        return [ self.getPerformanceFileMaker(), self.getPerformanceExtractor() ]
    def getCatalogueCreator(self):
        return sandbox.CreateCatalogue()
    def getTestCollator(self):
        return sandbox.CollateFiles()
    def getPerformanceExtractor(self):
        return sandbox.ExtractPerformanceFiles(self.getMachineInfoFinder())
    def getPerformanceFileMaker(self):
        return sandbox.MakePerformanceFile(self.getMachineInfoFinder())
    def getMachineInfoFinder(self):
        return sandbox.MachineInfoFinder()
    def getFailureExplainer(self):
        return [ CheckForCrashes(), CheckForBugs() ]
    def showExecHostsInFailures(self, app):
        return self.batchMode() or app.getRunMachine() != "localhost"
    def getTestComparator(self):
        return comparetest.MakeComparisons()
    def getStateSaver(self):
        if self.batchMode():
            return batch.SaveState
        else:
            return SaveState
    def getConfigEnvironment(self, test):
        testEnvironmentCreator = self.getEnvironmentCreator(test)
        return testEnvironmentCreator.getVariables()
    def getEnvironmentCreator(self, test):
        return sandbox.TestEnvironmentCreator(test, self.optionMap)
    def getInteractiveReplayOptions(self):
        return [ ("actrep", "slow motion") ]
    def getTextResponder(self):
        return console.InteractiveResponder
    # Utilities, which prove useful in many derived classes
    def optionValue(self, option):
        return self.optionMap.get(option, "")
    def ignoreExecutable(self):
        return self.optionMap.has_key("s") or self.ignoreCheckout() or self.optionMap.has_key("coll") or self.optionMap.has_key("gx")
    def ignoreCheckout(self):
        return self.isReconnecting() # No use of checkouts has yet been thought up when reconnecting :)
    def setUpCheckout(self, app):
        if self.ignoreCheckout():
            return ""
        else:
            checkoutPath = self.getGivenCheckoutPath(app)
            os.environ["TEXTTEST_CHECKOUT"] = checkoutPath # Full path to the checkout directory
            return checkoutPath
    
    def verifyCheckoutValid(self, app):
        if not os.path.isabs(app.checkout):
            raise plugins.TextTestError, "could not create absolute checkout from relative path '" + app.checkout + "'"
        elif not os.path.isdir(app.checkout):
            self.handleNonExistent(app.checkout, "checkout", app)

    def checkCheckoutExists(self, app):
        if not app.checkout:
            return "" # Allow empty checkout, means no checkout is set, basically
        
        try: 
            self.verifyCheckoutValid(app)
        except plugins.TextTestError, e:
            if self.ignoreExecutable():
                plugins.printWarning(str(e))
                return ""
            else:
                raise

    def checkSanity(self, suite):
        if not self.ignoreCheckout():
            self.checkCheckoutExists(suite.app)
        if not self.ignoreExecutable():
            self.checkExecutableExists(suite)

        self.checkFilterFileSanity(suite)
        self.checkConfigSanity(suite.app)
        if self.batchMode() and not self.optionMap.has_key("coll"):
            batchFilter = batch.BatchVersionFilter(self.optionMap.get("b"))
            batchFilter.verifyVersions(suite.app)
        if self.isReconnecting():
            self.reconnectConfig.checkSanity(suite.app)
        # side effects really from here on :(
        if self.readsTestStateFiles():
            # Reading stuff from stored pickle files, need to set up categories independently
            self.setUpPerformanceCategories(suite.app)

    def readsTestStateFiles(self):
        return self.isReconnecting() or self.optionMap.has_key("coll")

    def setUpPerformanceCategories(self, app):
        # We don't create these in the normal way, so we don't know what they are.
        allCategories = app.getConfigValue("performance_descriptor_decrease").values() + \
                        app.getConfigValue("performance_descriptor_increase").values()
        for cat in allCategories:
            if cat:
                plugins.addCategory(*plugins.commasplit(cat))
                
    def checkExecutableExists(self, suite):
        executable = suite.getConfigValue("executable")
        if not executable:
            raise plugins.TextTestError, "config file entry 'executable' not defined"
        if self.executableShouldBeFile(suite.app, executable) and not os.path.isfile(executable):
            self.handleNonExistent(executable, "executable program", suite.app)

        interpreterStr = suite.getConfigValue("interpreter")
        if interpreterStr:
            interpreter = plugins.splitcmd(interpreterStr)[0]
            if os.path.isabs(interpreter) and not os.path.exists(interpreter):
                self.handleNonExistent(interpreter, "interpreter program", suite.app)

    def pathExistsRemotely(self, path, machine, app):
        exitCode = self.runCommandOn(app, machine, [ "test", "-e", path ], collectExitCode=True)
        return exitCode == 0

    def checkConnection(self, app, machine):
        self.runCommandAndCheckMachine(app, machine, [ "echo", "hello" ])
 
    def handleNonExistent(self, path, desc, app):
        message = "The " + desc + " '" + path + "' does not exist"
        remoteCopy = app.getConfigValue("remote_copy_program")
        if remoteCopy:
            runMachine = app.getRunMachine()
            if runMachine != "localhost":
                if not self.pathExistsRemotely(path, runMachine, app):
                    self.checkConnection(app, runMachine) # throws if we can't get to it
                    raise plugins.TextTestError, message + ", either locally or on machine '" + runMachine + "'."
        else:
            raise plugins.TextTestError, message + "."

    def getRemoteTmpDirectory(self, app):
        remoteCopy = app.getConfigValue("remote_copy_program")
        if remoteCopy:
            runMachine = app.getRunMachine()
            if runMachine != "localhost":
                return runMachine, "~/.texttest/tmp/" + os.path.basename(app.writeDirectory)
        return "localhost", None

    def getRemoteTestTmpDir(self, test):
        machine, appTmpDir = self.getRemoteTmpDirectory(test.app)
        if appTmpDir:
            return machine, os.path.join(appTmpDir, test.app.name + test.app.versionSuffix(), test.getRelPath())
        else:
            return machine, appTmpDir
                
    def executableShouldBeFile(self, app, executable):
        if os.path.isabs(executable):
            return True

        # If it's part of the data it will be available as a relative path anyway
        if executable in app.getDataFileNames():
            return False
        
        # For finding java classes, don't warn if they don't exist as files...
        interpreter = app.getConfigValue("interpreter")
        return not interpreter.startswith("java") or executable.endswith(".jar")
    
    def checkConfigSanity(self, app):
        for key in app.getConfigValue("collate_file"):
            if "." in key or "/" in key:
                raise plugins.TextTestError, "Cannot collate files to stem '" + key + "' - '.' and '/' characters are not allowed"

    def getGivenCheckoutPath(self, app):
        checkout = self.getCheckout(app)
        if os.path.isabs(checkout):
            return checkout
        checkoutLocations = app.getCompositeConfigValue("checkout_location", checkout, expandVars=False)
        # do this afterwards, so it doesn't get expanded (yet)
        os.environ["TEXTTEST_CHECKOUT_NAME"] = checkout # Local name of the checkout directory
        if len(checkoutLocations) > 0:
            return self.makeAbsoluteCheckout(checkoutLocations, checkout, app)
        else:
            return checkout

    def getCheckout(self, app):
        if self.optionMap.has_key("c"):
            allCheckouts = plugins.commasplit(self.optionMap["c"])
            for checkout in allCheckouts[1:]:
                versionName = self.versionNameFromCheckout(checkout)
                if versionName in app.versions:
                    return checkout
            return allCheckouts[0]

        # Under some circumstances infer checkout from batch session
        batchSession = self.optionValue("b")
        if batchSession and  batchSession != "default" and \
               app.getConfigValue("checkout_location").has_key(batchSession):
            return batchSession
        else:
            return app.getConfigValue("default_checkout")        

    def makeAbsoluteCheckout(self, locations, checkout, app):
        isSpecific = app.getConfigValue("checkout_location").has_key(checkout)
        for location in locations:
            fullCheckout = self.absCheckout(location, checkout, isSpecific)
            if os.path.isdir(fullCheckout):
                return fullCheckout
        return self.absCheckout(locations[0], checkout, isSpecific)

    def absCheckout(self, location, checkout, isSpecific):
        fullLocation = os.path.expanduser(os.path.expandvars(location))
        if isSpecific or location.find("TEXTTEST_CHECKOUT_NAME") != -1:
            return fullLocation
        else:
            # old-style: infer expansion in default checkout
            return os.path.join(fullLocation, checkout)

    def recomputeProgress(self, test, state, observers):
        if state.isComplete():
            if state.hasResults():
                state.recalculateStdFiles(test)
                fileFilter = rundependent.FilterResultRecompute()
                fileFilter(test)
                state.recalculateComparisons(test)
                newState = state.makeNewState(test.app, "recalculated")
                test.changeState(newState)
        else:
            fileFilter = rundependent.FilterProgressRecompute()
            fileFilter(test)
            comparator = self.getTestComparator()
            comparator.recomputeProgress(test, state, observers)

    def getRunDescription(self, test):
        return RunTest().getRunDescription(test)

    def getFilePreview(self, fileName):
        return "Expected " + os.path.basename(fileName).split(".")[0] + " for the default version:\n" + \
               performance.describePerformance(fileName)

    # For display in the GUI
    def extraReadFiles(self, test):
        return {}
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
    def getDefaultMailAddress(self):
        user = os.getenv("USER", "$USER")
        return user + "@localhost"
    def getDefaultTestOverviewColours(self):
        colours = {}
        for wkday in plugins.weekdays:
            colours["run_" + wkday + "_fg"] = "black"
        colours["column_header_bg"] = "gray1"
        colours["row_header_bg"] = "#FFFFCC"
        colours["performance_fg"] = "red6"
        colours["memory_bg"] = "pink"
        colours["success_bg"] = "#CEEFBD"
        colours["failure_bg"] = "#FF3118"
        colours["knownbug_bg"] = "#FF9900"
        colours["incomplete_bg"] = "#8B1A1A"
        colours["no_results_bg"] = "gray2"
        colours["performance_bg"] = "#FFC6A5"
        colours["test_default_fg"] = "black"
        return colours

    def getDefaultPageName(self, app):
        pageName = app.fullName()
        fullVersion = app.getFullVersion()
        if fullVersion:
            pageName += " - version " + fullVersion
        return pageName
    def getDefaultCollectCompulsoryVersions(self):
        return { "default" : [] }
    def setBatchDefaults(self, app):
        # Batch values. Maps from session name to values
        app.setConfigDefault("smtp_server", "localhost", "Server to use for sending mail in batch mode")
        app.setConfigDefault("smtp_server_username", "", "Username for SMTP authentication when sending mail in batch mode")
        app.setConfigDefault("smtp_server_password", "", "Password for SMTP authentication when sending mail in batch mode")
        app.setConfigDefault("batch_result_repository", { "default" : "" }, "Directory to store historical batch results under")
        app.setConfigDefault("historical_report_location", { "default" : "" }, "Directory to create reports on historical batch data under")
        app.setConfigDefault("historical_report_page_name", { "default" : self.getDefaultPageName(app) }, "Header for page on which this application should appear")
        app.setConfigDefault("historical_report_colours", self.getDefaultTestOverviewColours(), "Colours to use for historical batch HTML reports")
        app.setConfigDefault("historical_report_subpages", { "default" : [ "Last six runs" ]}, "Names of subselection pages to generate as part of historical report")
        app.setConfigDefault("historical_report_subpage_cutoff", { "default" : 100000, "Last six runs" : 6 }, "How many runs should the subpage show, starting from the most recent?")
        app.setConfigDefault("historical_report_subpage_weekdays", { "default" : [] }, "Which weekdays should the subpage apply to (empty implies all)?")
        app.setConfigDefault("historical_report_resource_pages", { "default": [ "" ] }, "Which performance/memory pages should be generated by default on running -coll")
        app.setConfigDefault("historical_report_resource_page_tables", { "default": []}, "Resource names to generate the tables for the relevant performance/memory pages")
        app.setConfigDefault("historical_report_piechart_summary", { "default": "false" }, "Generate pie chart summary page rather than default HTML tables.")
        app.setConfigDefault("batch_sender", { "default" : self.getDefaultMailAddress() }, "Sender address to use sending mail in batch mode")
        app.setConfigDefault("batch_recipients", { "default" : self.getDefaultMailAddress() }, "Addresses to send mail to in batch mode")
        app.setConfigDefault("batch_timelimit", { "default" : "" }, "Maximum length of test to include in batch mode runs")
        app.setConfigDefault("batch_filter_file", { "default" : [] }, "Generic filter for batch session, more flexible than timelimit")
        app.setConfigDefault("batch_use_collection", { "default" : "false" }, "Do we collect multiple mails into one in batch mode")
        app.setConfigDefault("batch_junit_format", { "default" : "false" }, "Do we write out results in junit format in batch mode")
        app.setConfigDefault("batch_junit_folder", { "default" : "" }, "Which folder to write test results in junit format in batch mode. Only useful together with batch_junit_format")
        app.setConfigDefault("batch_collect_max_age_days", { "default" : 100000 }, "When collecting multiple messages, what is the maximum age of run that we should accept?")
        app.setConfigDefault("batch_collect_compulsory_version", self.getDefaultCollectCompulsoryVersions(), "When collecting multiple messages, which versions should be expected and give an error if not present?")
        app.setConfigDefault("batch_mail_on_failure_only", { "default" : "false" }, "Send mails only if at least one test fails")
        app.setConfigDefault("batch_use_version_filtering", { "default" : "false" }, "Which batch sessions use the version filtering mechanism")
        app.setConfigDefault("batch_version", { "default" : [] }, "List of versions to allow if batch_use_version_filtering enabled")
        app.setConfigAlias("testoverview_colours", "historical_report_colours")
        
    def setPerformanceDefaults(self, app):
        # Performance values
        app.setConfigDefault("cputime_include_system_time", 0, "Include system time when measuring CPU time?")
        app.setConfigDefault("performance_logfile", { "default" : [] }, "Which result file to collect performance data from")
        app.setConfigDefault("performance_logfile_extractor", {}, "What string to look for when collecting performance data")
        app.setConfigDefault("performance_test_machine", { "default" : [], "*mem*" : [ "any" ] }, \
                             "List of machines where performance can be collected")
        app.setConfigDefault("performance_variation_%", { "default" : 10.0 }, "How much variation in performance is allowed")
        app.setConfigDefault("performance_variation_serious_%", { "default" : 0.0 }, "Additional cutoff to performance_variation_% for extra highlighting")                
        app.setConfigDefault("use_normalised_percentage_change", { "default" : "true" }, \
                             "Do we interpret performance percentage changes as normalised (symmetric) values?")
        app.setConfigDefault("performance_test_minimum", { "default" : 0.0 }, \
                             "Minimum time/memory to be consumed before data is collected")
        app.setConfigDefault("performance_descriptor_decrease", self.defaultPerfDecreaseDescriptors(), "Descriptions to be used when the numbers decrease in a performance file")
        app.setConfigDefault("performance_descriptor_increase", self.defaultPerfIncreaseDescriptors(), "Descriptions to be used when the numbers increase in a performance file")
        app.setConfigDefault("performance_unit", self.defaultPerfUnits(), "Name to be used to identify the units in a performance file")
        app.setConfigDefault("performance_ignore_improvements", { "default" : "false" }, "Should we ignore all improvements in performance?")
        app.setConfigAlias("performance_use_normalised_%", "use_normalised_percentage_change")
        
    def setUsecaseDefaults(self, app):
        app.setConfigDefault("use_case_record_mode", "disabled", "Mode for Use-case recording (GUI, console or disabled)")
        app.setConfigDefault("use_case_recorder", "", "Which Use-case recorder is being used")
        app.setConfigDefault("slow_motion_replay_speed", 3, "How long in seconds to wait between each GUI action")
        app.setConfigDefault("virtual_display_machine", [ "localhost" ], \
                             "(UNIX) List of machines to run virtual display server (Xvfb) on")
        app.setConfigDefault("virtual_display_extra_args", "", \
                             "(UNIX) Extra arguments (e.g. bitdepth) to supply to virtual display server (Xvfb)")

    def defaultPerfUnits(self):
        units = {}
        units["default"] = "seconds"
        units["*mem*"] = "MB"
        return units

    def defaultPerfDecreaseDescriptors(self):
        descriptors = {}
        descriptors["default"] = ""
        descriptors["memory"] = "smaller, memory-, used less memory"
        descriptors["cputime"] = "faster, faster, ran faster"
        return descriptors

    def defaultPerfIncreaseDescriptors(self):
        descriptors = {}
        descriptors["default"] = ""
        descriptors["memory"] = "larger, memory+, used more memory"
        descriptors["cputime"] = "slower, slower, ran slower"
        return descriptors

    def defaultSeverities(self):
        severities = {}
        severities["errors"] = 1
        severities["output"] = 1
        severities["traffic"] = 1
        severities["usecase"] = 1
        severities["performance"] = 2
        severities["catalogue"] = 2
        severities["default"] = 99
        return severities
    def defaultDisplayPriorities(self):
        prios = {}
        prios["default"] = 99
        return prios
    def getDefaultCollations(self):
        if os.name == "posix":
            return { "stacktrace" : [ "core*" ] }
        else:
            return { "" : [] }
    def getDefaultCollateScripts(self):
        if os.name == "posix":
            return { "default" : [], "stacktrace" : [ "interpretcore.py" ] }
        else:
            return { "default" : [] }
    def setComparisonDefaults(self, app, homeOS):
        app.setConfigDefault("log_file", "output", "Result file to search, by default")
        app.setConfigDefault("failure_severity", self.defaultSeverities(), \
                             "Mapping of result files to how serious diffs in them are")
        app.setConfigDefault("failure_display_priority", self.defaultDisplayPriorities(), \
                             "Mapping of result files to which order they should be shown in the text info window.")
        app.setConfigDefault("floating_point_tolerance", { "default" : 0.0 }, "Which tolerance to apply when comparing floating point values in output")
        app.setConfigDefault("relative_float_tolerance", { "default" : 0.0 }, "Which relative tolerance to apply when comparing floating point values")

        app.setConfigDefault("collate_file", self.getDefaultCollations(), "Mapping of result file names to paths to collect them from")
        app.setConfigDefault("collate_script", self.getDefaultCollateScripts(), "Mapping of result file names to scripts which turn them into suitable text")
        app.setConfigDefault("collect_traffic", { "default": [], "asynchronous": [] }, "List of command-line programs to intercept")
        app.setConfigDefault("collect_traffic_environment", { "default" : [] }, "Mapping of collected programs to environment variables they care about")
        app.setConfigDefault("collect_traffic_py_module", [], "List of Python modules to intercept")
        app.setConfigDefault("collect_traffic_py_attributes", { "": []}, "List of Python attributes to intercept per intercepted module.")
        app.setConfigDefault("collect_traffic_use_threads", "true", "Whether to enable threading, and hence concurrent requests, in traffic mechanism")
        app.setConfigDefault("run_dependent_text", { "default" : [] }, "Mapping of patterns to remove from result files")
        app.setConfigDefault("unordered_text", { "default" : [] }, "Mapping of patterns to extract and sort from result files")
        app.setConfigDefault("create_catalogues", "false", "Do we create a listing of files created/removed by tests")
        app.setConfigDefault("catalogue_process_string", "", "String for catalogue functionality to identify processes created")
        app.setConfigDefault("binary_file", [], "Which output files are known to be binary, and hence should not be shown/diffed?")
        
        app.setConfigDefault("discard_file", [], "List of generated result files which should not be compared")
        if self.optionMap.has_key("rectraffic"):
            app.addConfigEntry("implied", "rectraffic", "base_version")
        if self.optionMap.has_key("record"):
            app.addConfigEntry("implied", "recusecase", "base_version")
        if homeOS != "any" and homeOS != os.name:
            app.addConfigEntry("implied", os.name, "base_version")

    def defaultViewProgram(self, homeOS):
        if os.name == "posix":
            return "emacs"
        else:
            if homeOS == "posix":
                # Notepad cannot handle UNIX line-endings: for cross platform suites use wordpad by default...
                return "wordpad"
            else:
                return "notepad"
    def defaultFollowProgram(self):
        if os.name == "posix":
            return "xterm -bg white -T $TEXTTEST_FOLLOW_FILE_TITLE -e tail -f"
        else:
            return "baretail"
    def setExternalToolDefaults(self, app, homeOS):
        app.setConfigDefault("text_diff_program", "diff", \
                             "External program to use for textual comparison of files")
        app.setConfigDefault("lines_of_text_difference", 30, "How many lines to present in textual previews of file diffs")
        app.setConfigDefault("max_width_text_difference", 500, "How wide lines can be in textual previews of file diffs")
        app.setConfigDefault("max_file_size", { "default": "-1" }, "The maximum file size to load into external programs, in bytes. -1 means no limit.")
        app.setConfigDefault("text_diff_program_filters", { "default" : [], "diff" : [ "^<", "^>" ]}, "Filters that should be applied for particular diff tools to aid with grouping in dynamic GUI")
        app.setConfigDefault("diff_program", { "default": "tkdiff" }, "External program to use for graphical file comparison")
        app.setConfigDefault("view_program", { "default": self.defaultViewProgram(homeOS) },  \
                              "External program(s) to use for viewing and editing text files")
        app.setConfigDefault("follow_program", { "default": self.defaultFollowProgram() }, "External program to use for following progress of a file")
        app.setConfigDefault("follow_file_by_default", 0, "When double-clicking running files, should we follow progress or just view them?")
        app.setConfigDefault("bug_system_location", {}, "The location of the bug system we wish to extract failure information from.")
        app.setConfigDefault("bug_system_username", {}, "Username to use when logging in to bug systems defined in bug_system_location")
        app.setConfigDefault("bug_system_password", {}, "Password to use when logging in to bug systems defined in bug_system_location")
        app.setConfigAlias("text_diff_program_max_file_size", "max_file_size")
        
    def setInterfaceDefaults(self, app):
        app.setConfigDefault("default_interface", "static_gui", "Which interface to start if none of -con, -g and -gx are provided")
        # These configure the GUI but tend to have sensible defaults per application
        app.setConfigDefault("gui_entry_overrides", { "default" : "<not set>" }, "Default settings for entries in the GUI")
        app.setConfigDefault("gui_entry_options", { "default" : [] }, "Default drop-down box options for GUI entries")
        app.setConfigDefault("suppress_stderr_text", [], "List of patterns which, if written on TextTest's own stderr, should not be propagated to popups and further logfiles")
        app.setConfigAlias("suppress_stderr_popup", "suppress_stderr_text")
        
    def getDefaultRemoteProgramOptions(self):
        # The aim is to ensure they never hang, but always return errors if contact not possible
        # Disable passwords: only use public key based authentication.
        # Also disable hostkey checking, we assume we don't run tests on untrusted hosts.
        # Also don't run tests on machines which take a very long time to connect to...
        sshOptions = "-o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=10"
        return { "default": "", "ssh" : sshOptions,
                 "rsync" : "-azLp", "scp": "-Crp " + sshOptions }

    def getCommandArgsOn(self, app, machine, cmdArgs):
        if machine == "localhost":
            return cmdArgs
        else:
            return self.getRemoteProgramArgs(app, "remote_shell_program") + [ machine ] + cmdArgs

    def runCommandOn(self, app, machine, cmdArgs, collectExitCode=False):
        allArgs = self.getCommandArgsOn(app, machine, cmdArgs)
        if allArgs[0] == "rsh" and collectExitCode:
            searchStr = "remote cmd succeeded"
            # Funny tricks here because rsh does not forward the exit status of the program it runs
            allArgs += [ "&&", "echo", searchStr ]
            proc = subprocess.Popen(allArgs, stdin=open(os.devnull), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            output = proc.communicate()[0]
            return searchStr not in output # Return an "exit code" which is 0 when we succeed!
        else:
            return subprocess.call(allArgs, stdin=open(os.devnull), stdout=open(os.devnull, "w"), stderr=subprocess.STDOUT)

    def runCommandAndCheckMachine(self, app, machine, cmdArgs):
        allArgs = self.getCommandArgsOn(app, machine, cmdArgs)
        proc = subprocess.Popen(allArgs, stdin=open(os.devnull), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = proc.communicate()[0]
        exitCode = proc.returncode
        if exitCode > 0:
            raise plugins.TextTestError, "Unable to contact machine '" + machine + \
                  "'.\nMake sure you have passwordless access set up correctly. The failing command was:\n" + \
                  " ".join(allArgs) + "\n\nThe command produced the following output:\n" + output

    def ensureRemoteDirExists(self, app, machine, dirname):
        self.runCommandAndCheckMachine(app, machine, [ "mkdir", "-p", plugins.quote(dirname, '"') ])

    def getRemotePath(self, file, machine):
        if machine == "localhost":
            return file
        else:
            return machine + ":" + plugins.quote(file, '"')
                                                 
    def copyFileRemotely(self, app, srcFile, srcMachine, dstFile, dstMachine):
        srcPath = self.getRemotePath(srcFile, srcMachine)
        dstPath = self.getRemotePath(dstFile, dstMachine)
        args = self.getRemoteProgramArgs(app, "remote_copy_program") + [ srcPath, dstPath ]
        return subprocess.call(args, stdin=open(os.devnull)) #, stdout=open(os.devnull, "w"), stderr=subprocess.STDOUT)

    def getRemoteProgramArgs(self, app, setting):
        progStr = app.getConfigValue(setting)
        progArgs = plugins.splitcmd(progStr)
        argStr = app.getCompositeConfigValue("remote_program_options", progArgs[0])
        return progArgs + plugins.splitcmd(argStr)

    def setMiscDefaults(self, app):
        app.setConfigDefault("default_texttest_tmp", "$TEXTTEST_PERSONAL_CONFIG/tmp", "Default value for $TEXTTEST_TMP, if it is not set")
        app.setConfigDefault("checkout_location", { "default" : []}, "Absolute paths to look for checkouts under")
        app.setConfigDefault("default_checkout", "", "Default checkout, relative to the checkout location")
        app.setConfigDefault("remote_shell_program", "rsh", "Program to use for running commands remotely")
        app.setConfigDefault("remote_program_options", self.getDefaultRemoteProgramOptions(), "Default options to use for particular remote shell programs")
        app.setConfigDefault("remote_copy_program", "", "(UNIX) Program to use for copying files remotely, in case of non-shared file systems")
        app.setConfigDefault("default_filter_file", [], "Filter file to use by default, generally only useful for versions")
        app.setConfigDefault("test_data_environment", {}, "Environment variables to be redirected for linked/copied test data")
        app.setConfigDefault("test_data_properties", { "default" : "" }, "Write the contents of test_data_environment to the given Java properties file")
        app.setConfigDefault("filter_file_directory", [ "filter_files" ], "Default directories for test filter files, relative to an application directory.")
        app.setConfigDefault("extra_version", [], "Versions to be run in addition to the one specified")
        app.setConfigDefault("batch_extra_version", { "default" : [] }, "Versions to be run in addition to the one specified, for particular batch sessions")
        app.setConfigDefault("save_filtered_file_stems", [], "Files where the filtered version should be saved rather than the SUT output")
        # Applies to any interface...
        app.setConfigDefault("auto_sort_test_suites", 0, "Automatically sort test suites in alphabetical order. 1 means sort in ascending order, -1 means sort in descending order.")
        app.addConfigEntry("builtin", "options", "definition_file_stems")
        app.addConfigEntry("builtin", "interpreter_options", "definition_file_stems")
        app.addConfigEntry("regenerate", "usecase", "definition_file_stems")
        app.addConfigEntry("regenerate", "traffic", "definition_file_stems")
        app.addConfigEntry("builtin", "input", "definition_file_stems")
        app.addConfigEntry("builtin", "knownbugs", "definition_file_stems")
        app.setConfigAlias("test_list_files_directory", "filter_file_directory")
        
    def setApplicationDefaults(self, app):
        homeOS = app.getConfigValue("home_operating_system")
        self.setComparisonDefaults(app, homeOS)
        self.setExternalToolDefaults(app, homeOS)
        self.setInterfaceDefaults(app)
        self.setMiscDefaults(app)
        self.setBatchDefaults(app)
        self.setPerformanceDefaults(app)
        self.setUsecaseDefaults(app)

class SaveState(plugins.Responder):
    def notifyComplete(self, test):
        if test.state.isComplete(): # might look weird but this notification also comes in scripts etc.
            test.saveState()


class OrFilter(plugins.Filter):
    def __init__(self, filterLists):
        self.filterLists = filterLists
    def accepts(self, test):
        return reduce(operator.or_, (test.isAcceptedByAll(filters) for filters in self.filterLists), False)
    def acceptsTestCase(self, test):
        return self.accepts(test)
    def acceptsTestSuite(self, suite):
        return self.accepts(suite)
    def acceptsTestSuiteContents(self, suite):
        return reduce(operator.or_, (self.contentsAccepted(suite, filters) for filters in self.filterLists), False)
    def contentsAccepted(self, suite, filters):
        return reduce(operator.and_, (filter.acceptsTestSuiteContents(suite) for filter in filters), True)

class NotFilter(plugins.Filter):
    def __init__(self, filters):
        self.filters = filters
    def acceptsTestCase(self, test):
        return not test.isAcceptedByAll(self.filters)
    
class TestNameFilter(plugins.TextFilter):
    option = "t"
    def acceptsTestCase(self, test):
        return self.stringContainsText(test.name)

class TestRelPathFilter(plugins.TextFilter):
    option = "ts"
    def parseInput(self, filterText, *args):
        # Handle paths pasted from web page
        return [ text.replace(" ", "/") for text in plugins.commasplit(filterText) ]

    def acceptsTestCase(self, test):
        return self.stringContainsText(test.getRelPath())


class GrepFilter(plugins.TextFilter):
    def __init__(self, filterText, fileStem, useTmpFiles=False):
        plugins.TextFilter.__init__(self, filterText)
        self.fileStem = fileStem
        self.useTmpFiles = useTmpFiles
        
    def acceptsTestCase(self, test):
        if self.fileStem == "free_text":
            return self.stringContainsText(test.state.freeText)
        for logFile in self.findAllFiles(test):
            if self.matches(logFile):
                return True
        return False

    def findAllFiles(self, test):
        if self.useTmpFiles:
            files = []
            try:
                for comparison in test.state.allResults:
                    if comparison.tmpFile and fnmatch(comparison.stem, self.fileStem) and os.path.isfile(comparison.tmpFile):
                        files.append(comparison.tmpFile)
                return files
            except AttributeError:
                return []
        else:
            return self.findAllStdFiles(test)

    def findAllStdFiles(self, test):
        logFiles = []
        for fileName in test.getFileNamesMatching(self.fileStem):
            if os.path.isfile(fileName):
                logFiles.append(fileName)
            else:
                test.refreshFiles()
                return self.findAllStdFiles(test)
        return logFiles

    def matches(self, logFile):
        for line in open(logFile).xreadlines():
            if self.stringContainsText(line):
                return True
        return False


class TestDescriptionFilter(plugins.TextFilter):
    option = "desc"
    def acceptsTestCase(self, test):
        return self.stringContainsText(test.description)

class Running(plugins.TestState):
    def __init__(self, execMachines, freeText = "", briefText = ""):
        plugins.TestState.__init__(self, "running", freeText, briefText, started=1,
                                   executionHosts = execMachines, lifecycleChange="start")

class Killed(plugins.TestState):
    def __init__(self, briefText, freeText, prevState):
        plugins.TestState.__init__(self, "killed", briefText=briefText, freeText=freeText, \
                                   started=1, completed=1, executionHosts=prevState.executionHosts)
        # Cache running information, it can be useful to have this available...
        self.prevState = prevState
        self.failedPrediction = self

class RunTest(plugins.Action):
    def __init__(self):
        self.diag = logging.getLogger("run test")
        self.killDiag = logging.getLogger("kill processes")
        self.currentProcess = None
        self.killedTests = []
        self.killSignal = None
        self.lock = Lock()
    def __repr__(self):
        return "Running"
    def __call__(self, test):
        return self.runTest(test)
    def changeToRunningState(self, test):
        execMachines = test.state.executionHosts
        self.diag.info("Changing " + repr(test) + " to state Running on " + repr(execMachines))
        briefText = self.getBriefText(execMachines)
        freeText = "Running on " + ",".join(execMachines)
        newState = Running(execMachines, briefText=briefText, freeText=freeText)
        test.changeState(newState)
    def getBriefText(self, execMachines):
        # Default to not bothering to print the machine name: all is local anyway
        return ""
    def runTest(self, test):
        self.describe(test)
        machine = test.app.getRunMachine()
        process = self.getTestProcess(test, machine)
        self.changeToRunningState(test)
        
        self.registerProcess(test, process)
        if test.getConfigValue("kill_timeout"):
            timer = Timer(test.getConfigValue("kill_timeout"), self.kill, (test, "timeout"))
            timer.start()
            self.wait(process)
            timer.cancel()
        else:
            self.wait(process)
        self.checkAndClear(test)
    
    def registerProcess(self, test, process):
        self.lock.acquire()
        self.currentProcess = process
        if test in self.killedTests:
            self.killProcess(test)
        self.lock.release()

    def storeReturnCode(self, test, code):
        file = open(test.makeTmpFileName("exitcode"), "w")
        file.write(str(code) + "\n")
        file.close()

    def checkAndClear(self, test):        
        returncode = self.currentProcess.returncode
        self.diag.info("Process terminated with return code " + repr(returncode))
        if os.name == "posix" and test not in self.killedTests and returncode < 0:
            # Process externally killed, but we haven't been notified. Wait for a while to see if we get kill notification
            self.waitForKill()
            
        self.lock.acquire()
        self.currentProcess = None
        if test in self.killedTests:
            self.changeToKilledState(test)
        elif returncode: # Don't bother to store return code when tests are killed, it isn't interesting
            self.storeReturnCode(test, returncode)
        
        self.lock.release()

    def waitForKill(self):
        for i in range(10):
            sleep(0.2)
            if self.killSignal is not None:
                return

    def changeToKilledState(self, test):
        self.diag.info("Killing test " + repr(test) + " in state " + test.state.category)
        briefText, fullText = self.getKillInfo(test)
        freeText = "Test " + fullText + "\n"
        test.changeState(Killed(briefText, freeText, test.state))

    def getKillInfo(self, test):
        if self.killSignal is None:
            return self.getExplicitKillInfo()
        elif self.killSignal == "timeout":
            return "TIMEOUT", "exceeded wallclock time limit of " + str(test.getConfigValue("kill_timeout")) + " seconds"
        elif self.killSignal == signal.SIGUSR1:
            return self.getUserSignalKillInfo(test, "1")
        elif self.killSignal == signal.SIGUSR2:
            return self.getUserSignalKillInfo(test, "2")
        elif self.killSignal == signal.SIGXCPU:
            return "CPULIMIT", "exceeded maximum cpu time allowed"
        elif self.killSignal == signal.SIGINT:
            return "INTERRUPT", "terminated via a keyboard interrupt (Ctrl-C)"
        else:
            briefText = "signal " + str(self.killSignal)
            return briefText, "terminated by " + briefText
        
    def getExplicitKillInfo(self):
        timeStr = plugins.localtime("%H:%M")
        return "KILLED", "killed explicitly at " + timeStr

    def getUserSignalKillInfo(self, test, userSignalNumber):
        return "SIGUSR" + userSignalNumber, "terminated by user signal " + userSignalNumber

    def kill(self, test, sig):
        self.lock.acquire()
        self.killedTests.append(test)
        self.killSignal = sig
        if self.currentProcess:
            self.killProcess(test)
        self.lock.release()
        
    def killProcess(self, test):
        machine = test.app.getRunMachine()
        if machine != "localhost" and test.getConfigValue("remote_shell_program") == "ssh":
            self.killRemoteProcess(test, machine)
        self.killDiag.info("Killing running test (process id " + str(self.currentProcess.pid) + ")")
        killSubProcessAndChildren(self.currentProcess, cmd=test.getConfigValue("kill_command"))

    def killRemoteProcess(self, test, machine):
        tmpDir = self.getTmpDirectory(test)
        remoteScript = os.path.join(tmpDir, "kill_test.sh")
        test.app.runCommandOn(machine, [ "sh", plugins.quote(remoteScript, '"') ])
        
    def wait(self, process):
        try:
            plugins.retryOnInterrupt(process.wait)
        except OSError:
            pass # safest, as there are python bugs in this area

    def diagnose(self, testEnv, commandArgs):
        if self.diag.isEnabledFor(logging.INFO):
            for var, value in testEnv.items():
                self.diag.info("Environment: " + var + " = " + value)
            self.diag.info("Running test with args : " + repr(commandArgs))

    def getRunDescription(self, test):
        commandArgs = self.getLocalExecuteCmdArgs(test, makeDirs=False)
        text =  "Command Line   : " + plugins.commandLineString(commandArgs) + "\n"
        interestingVars = self.getEnvironmentChanges(test)
        if len(interestingVars) == 0:
            return text
        text += "\nEnvironment variables :\n"
        for var, value in interestingVars:
            text += var + "=" + value + "\n"
        return text

    def getEnvironmentChanges(self, test):
        testEnv = test.getRunEnvironment()
        return sorted(filter(lambda (var, value): value != os.getenv(var), testEnv.items()))
        
    def getTestProcess(self, test, machine):
        commandArgs = self.getExecuteCmdArgs(test, machine)
        testEnv = test.getRunEnvironment()
        self.diagnose(testEnv, commandArgs)
        try:
            return subprocess.Popen(commandArgs, preexec_fn=self.getPreExecFunction(), \
                                    stdin=open(self.getInputFile(test)), cwd=test.getDirectory(temporary=1), \
                                    stdout=self.makeFile(test, "output"), stderr=self.makeFile(test, "errors"), \
                                    env=testEnv, startupinfo=plugins.getProcessStartUpInfo(test.environment))
        except OSError:
            message = "OS-related error starting the test command - probably cannot find the program " + repr(commandArgs[0])
            raise plugins.TextTestError, message
        
    def getPreExecFunction(self):
        if os.name == "posix": # pragma: no cover - only run in the subprocess!
            return self.ignoreJobControlSignals

    def ignoreJobControlSignals(self): # pragma: no cover - only run in the subprocess!
        for signum in [ signal.SIGQUIT, signal.SIGUSR1, signal.SIGUSR2, signal.SIGXCPU ]:
            signal.signal(signum, signal.SIG_IGN)

    def getInterpreterArgs(self, test):
        args = plugins.splitcmd(test.getConfigValue("interpreter"))
        if len(args) > 0 and args[0] == "ttpython": # interpreted to mean "whatever python TextTest runs with"
            return [ sys.executable, "-u" ] + args[1:]
        else:
            return args

    def getRemoteExecuteCmdArgs(self, test, runMachine, localArgs):
        scriptFileName = test.makeTmpFileName("run_test.sh", forComparison=0)
        scriptFile = open(scriptFileName, "w")
        scriptFile.write("#!/bin/sh\n\n")

        # Need to change working directory remotely
        tmpDir = self.getTmpDirectory(test)
        scriptFile.write("cd " + plugins.quote(tmpDir, "'") + "\n")

        for arg, value in self.getEnvironmentArgs(test): # Must set the environment remotely
            scriptFile.write("export " + arg + "=" + value + "\n")
        if test.app.getConfigValue("remote_shell_program") == "ssh":
            # SSH doesn't kill remote processes, create a kill script
            scriptFile.write('echo "kill $$" > kill_test.sh\n')
        scriptFile.write("exec " + " ".join(localArgs) + "\n")
        scriptFile.close()
        os.chmod(scriptFileName, 0775) # make executable
        remoteTmp = test.app.getRemoteTestTmpDir(test)[1]
        if remoteTmp:
            test.app.copyFileRemotely(scriptFileName, "localhost", remoteTmp, runMachine)
            remoteScript = os.path.join(remoteTmp, os.path.basename(scriptFileName))
            return test.app.getCommandArgsOn(runMachine, [ plugins.quote(remoteScript, '"') ])
        else:
            return test.app.getCommandArgsOn(runMachine, [ plugins.quote(scriptFileName, '"') ])

    def getEnvironmentArgs(self, test):
        vars = self.getEnvironmentChanges(test)
        if len(vars) == 0:
            return []
        else:
            args = []
            localTmpDir = test.app.writeDirectory
            machine, remoteTmp = test.app.getRemoteTmpDirectory()
            for var, value in vars:
                if remoteTmp:
                    remoteValue = value.replace(localTmpDir, remoteTmp)
                else:
                    remoteValue = value
                if var == "PATH":
                    # This needs to be correctly reset remotely
                    remoteValue = plugins.quote(remoteValue.replace(os.getenv(var), "${" + var + "}"), '"')
                else:
                    remoteValue = plugins.quote(remoteValue, "'")
                args.append((var, remoteValue))
            return args
    
    def getTmpDirectory(self, test):
        machine, remoteTmp = test.app.getRemoteTestTmpDir(test)
        if remoteTmp:
            return remoteTmp
        else:
            return test.getDirectory(temporary=1)

    def getTimingArgs(self, test, makeDirs):
        machine, remoteTmp = test.app.getRemoteTestTmpDir(test)
        if remoteTmp:
            frameworkDir = os.path.join(remoteTmp, "framework_tmp")
            if makeDirs:
                test.app.ensureRemoteDirExists(machine, frameworkDir)
            perfFile = os.path.join(frameworkDir, "unixperf")
        else:
            perfFile = test.makeTmpFileName("unixperf", forFramework=1)
        return [ "time", "-p", "-o", perfFile ]

    def getLocalExecuteCmdArgs(self, test, makeDirs=True):
        args = []
        if test.app.hasAutomaticCputimeChecking():
            args += self.getTimingArgs(test, makeDirs)

        args += self.getInterpreterArgs(test)
        args += test.getInterpreterOptions()
        args += plugins.splitcmd(test.getConfigValue("executable"))
        args += test.getCommandLineOptions()
        return args
        
    def getExecuteCmdArgs(self, test, runMachine):
        args = self.getLocalExecuteCmdArgs(test)
        if runMachine == "localhost":
            return args
        else:
            return self.getRemoteExecuteCmdArgs(test, runMachine, args)

    def makeFile(self, test, name):
        fileName = test.makeTmpFileName(name)
        return open(fileName, "w")

    def getInputFile(self, test):
        inputFileName = test.getFileName("input")
        if inputFileName:
            return inputFileName
        else:
            return os.devnull
    def setUpSuite(self, suite):
        self.describe(suite)
                    
class CountTest(plugins.Action):
    scriptDoc = "report on the number of tests selected, by application"
    appCount = seqdict()
    @classmethod
    def finalise(self):
        for app, count in self.appCount.items():
            print app.description(), "has", count, "tests"
        print "There are", sum(self.appCount.values()), "tests in total."

    def __repr__(self):
        return "Counting"

    def __call__(self, test):
        self.describe(test)
        self.appCount[test.app] += 1

    def setUpSuite(self, suite):
        self.describe(suite)

    def setUpApplication(self, app):
        self.appCount[app] = 0


class DocumentOptions(plugins.Action):
    multiValueOptions = [ "a", "c", "f", "funion", "fintersect", "t", "ts", "v" ]
    def setUpApplication(self, app):
        groups = app.createOptionGroups([ app ])
        keys = reduce(operator.add, (g.keys() for g in groups), [])
        keys.sort()
        for key in keys:
            self.displayKey(key, groups)

    def displayKey(self, key, groups):
        for group in groups:
            option = group.getOption(key)
            if option:
                keyOutput, docOutput = self.optionOutput(key, group, option)
                self.display(keyOutput, self.groupOutput(group), docOutput)

    def display(self, keyOutput, groupOutput, docOutput):
        if not docOutput.startswith("Private"):
            print keyOutput + ";" + groupOutput + ";" + docOutput.replace("SGE", "SGE/LSF")

    def groupOutput(self, group):
        if group.name == "Invisible":
            return "N/A"
        else:
            return group.name

    def optionOutput(self, key, group, option):
        keyOutput = "-" + key
        docs = option.name
        if isinstance(option, plugins.TextOption):
            keyOutput += " <value>"
            if (docs == "Execution time"):
                keyOutput = "-" + key + " <time specification string>"
            else:
                docs += " <value>"
            if key in self.multiValueOptions:
                keyOutput += ",..."
                docs += ",..."

        if group.name.startswith("Select"):
            return keyOutput, "Select " + docs.lower()
        else:
            return keyOutput, docs
        

class DocumentConfig(plugins.Action):
    def __init__(self, args=[]):
        self.onlyEntries = args

    def getEntriesToUse(self, app):
        if len(self.onlyEntries) > 0:
            return self.onlyEntries
        else:
            return sorted(app.configDir.keys() + app.configDir.aliases.keys())
        
    def setUpApplication(self, app):
        for key in self.getEntriesToUse(app):
            realKey = app.configDir.aliases.get(key, key)
            if realKey == key:
                docOutput = app.configDocs.get(realKey, "NO DOCS PROVIDED")
            else:
                docOutput = "Alias. See entry for '" + realKey + "'"
            if not docOutput.startswith("Private"):
                value = app.configDir[realKey]
                print key + "|" + str(value) + "|" + docOutput  

class DocumentEnvironment(plugins.Action):
    def __init__(self, args=[]):
        self.onlyEntries = args
        self.prefixes = [ "TEXTTEST_", "USECASE_" ]
        self.exceptions = [ "TEXTTEST_DELETION", "TEXTTEST_SYMLINK", "TEXTTEST_PERSONAL_" ]
        
    def getEntriesToUse(self, app):
        if len(self.onlyEntries) > 0:
            return self.onlyEntries
        else:
            rootDir = plugins.installationRoots[0]
            return self.findAllVariables(app, self.prefixes, rootDir)

    def findAllVariables(self, app, prefixes, rootDir):
        includeSite = app.inputOptions.configPathOptions()[0]
        allVars = {}
        for root, dirs, files in os.walk(rootDir):
            if "log" in dirs:
                dirs.remove("log")
            if not includeSite and "site" in dirs:
                dirs.remove("site")
            if root.endswith("lib"):
                for dir in dirs:
                    if not sys.modules.has_key(dir):
                        dirs.remove(dir)
            for file in files:
                if file.endswith(".py") and ("usecase" not in file and "gtk" not in file): # exclude PyUseCase, which may be linked/copied in
                    path = os.path.join(root, file)
                    self.findVarsInFile(path, allVars, prefixes)
        return allVars

    def getArgList(self, line, functionName):
        pos = line.find(functionName) + len(functionName)
        parts = line[pos:].strip().split("#")
        endPos = parts[0].find(")")
        argStr = parts[0][:endPos + 1]
        for i in range(argStr.count("(", 1)):
            endPos = parts[0].find(")", endPos + 1)
            argStr = parts[0][:endPos + 1]
        allArgs = self.getActualArguments(argStr)
        if len(parts) > 1:
            allArgs.append(parts[1].strip())
        else:
            allArgs.append("")
        return allArgs

    def getActualArguments(self, argStr):
        if not argStr.startswith("("):
            return []

        # Pick up app.getConfigValue
        class FakeApp:
            def getConfigValue(self, name):
                return "Config value '" + name + "'"
        app = FakeApp()
        try:
            argTuple = eval(argStr)
            from types import TupleType
            if type(argTuple) == TupleType:
                allArgs = list(eval(argStr))
                return [ self.interpretArgument(str(allArgs[1])) ]
            else:
                return []
        except: # could be anything at all
            return []

    def interpretArgument(self, arg):
        if arg.endswith("texttest.py"):
            return "<source directory>/bin/texttest.py"
        else:
            return arg

    def isRelevant(self, var, vars, prefixes):
        if var in self.exceptions or var in prefixes or "SLEEP" in var:
            return False
        prevVal = vars.get(var, [])
        return not prevVal or not prevVal[0]
        
    def findVarsInFile(self, path, vars, prefixes):
        import re
        regexes = [ re.compile("([^/ \"'\.,\(]*)[\(]?[\"'](" + prefix + "[^/ \"'\.,]*)") for prefix in prefixes ]
        for line in open(path).xreadlines():
            for regex in regexes:
                match = regex.search(line)
                if match is not None:
                    functionName = match.group(1)
                    var = match.group(2).strip()
                    if self.isRelevant(var, vars, prefixes):
                        argList = self.getArgList(line, functionName)
                        vars[var] = argList
        
    def setUpApplication(self, app):
        vars = self.getEntriesToUse(app)
        print "The following variables may be set by the user :"
        for key in sorted(vars.keys()):
            argList = vars[key]
            if len(argList) > 1:
                print key + "|" + "|".join(argList)

        print "The following variables are set by TextTest :"
        for var in sorted(filter(lambda key: len(vars[key]) == 1, vars.keys())):
            print var + "|" + vars[var][0]


class DocumentScripts(plugins.Action):
    def setUpApplication(self, app):
        modNames = [ "batch", "comparetest", "default", "performance" ]
        for modName in modNames:
            importCommand = "import " + modName
            exec importCommand
            command = "names = dir(" + modName + ")"
            exec command
            for name in names:
                scriptName = modName + "." + name
                docFinder = "docString = " + scriptName + ".scriptDoc"
                try:
                    exec docFinder
                    print scriptName + "|" + docString
                except AttributeError:
                    pass

class ReplaceText(plugins.ScriptWithArgs):
    scriptDoc = "Perform a search and replace on all files with the given stem"
    def __init__(self, args):
        argDict = self.parseArguments(args, [ "old", "new", "file" ])
        self.oldTextTrigger = plugins.TextTrigger(argDict["old"])
        self.newText = argDict["new"].replace("\\n", "\n")
        fileStr = argDict.get("file", "")
        self.stems = plugins.commasplit(fileStr)

    def __repr__(self):
        return "Replacing " + self.oldTextTrigger.text + " with " + self.newText + " for"

    def __call__(self, test):
        for stem in self.stems:
            for stdFile in test.getFileNamesMatching(stem):
                fileName = os.path.basename(stdFile)
                self.describe(test, " - file " + fileName)
                sys.stdout.flush()
                unversionedFileName = ".".join(fileName.split(".")[:2])
                tmpFile = os.path.join(test.getDirectory(temporary=1), unversionedFileName)
                writeFile = open(tmpFile, "w")
                for line in open(stdFile).xreadlines():
                    writeFile.write(self.oldTextTrigger.replace(line, self.newText))
                writeFile.close()

    def usesComparator(self):
        return True

    def setUpSuite(self, suite):
        self.describe(suite)

    def setUpApplication(self, app):
        if len(self.stems) == 0:
            logFile = app.getConfigValue("log_file")
            if not logFile in self.stems:
                self.stems.append(logFile)                
            

class ExportTests(plugins.ScriptWithArgs):
    scriptDoc = "Export the selected tests to a different test suite"
    def __init__(self, args):
        argDict = self.parseArguments(args, [ "dest" ])
        self.otherTTHome = argDict.get("dest")
        self.otherSuites = {}
        self.placements = {}
        if not self.otherTTHome:
            raise plugins.TextTestError, "Must provide 'dest' argument to indicate where tests should be exported"
    def __repr__(self):
        return "Checking for export of"
    def __call__(self, test):
        self.tryExport(test)
    def setUpSuite(self, suite):
        self.placements[suite] = 0
        if suite.parent:
            self.tryExport(suite)
    def tryExport(self, test):
        otherRootSuite = self.otherSuites.get(test.app)
        otherTest = otherRootSuite.findSubtestWithPath(test.getRelPath())
        parent = test.parent
        if otherTest:
            self.describe(test, " - already exists")
        else:
            otherParent = otherRootSuite.findSubtestWithPath(parent.getRelPath())
            if otherParent:
                self.describe(test, " - CREATING...")
                self.copyTest(test, otherParent, self.placements[parent])
            else:
                self.describe(test, " - COULDN'T FIND PARENT")
        self.placements[parent] += 1

    def copyTest(self, test, otherParent, placement):
        # Do this first, so that if it fails due to e.g. full disk, we won't register the test either...
        testDir = otherParent.makeSubDirectory(test.name)
        self.copyTestContents(test, testDir)
        otherParent.registerTest(test.name, test.description, placement)
        otherParent.addTest(test.__class__, test.name, test.description, placement)

    def copyTestContents(self, test, newDir):
        stdFiles, defFiles = test.listStandardFiles(allVersions=True)
        for sourceFile in stdFiles + defFiles:
            dirname, local = os.path.split(sourceFile)
            if dirname == test.getDirectory():
                targetFile = os.path.join(newDir, local)
                shutil.copy2(sourceFile, targetFile)

        root, extFiles = test.listExternallyEditedFiles()
        dataFiles = test.listDataFiles() + extFiles
        for sourcePath in dataFiles:
            if os.path.isdir(sourcePath):
                continue
            targetPath = sourcePath.replace(test.getDirectory(), newDir)
            plugins.ensureDirExistsForFile(targetPath)
            shutil.copy2(sourcePath, targetPath)

    def setUpApplication(self, app):
        self.otherSuites[app] = app.createExtraTestSuite(otherDir=self.otherTTHome)

# A standalone action, we add description and generate the main file instead...
class ExtractStandardPerformance(sandbox.ExtractPerformanceFiles):
    scriptDoc = "update the standard performance files from the standard log files"
    def __init__(self):
        sandbox.ExtractPerformanceFiles.__init__(self, sandbox.MachineInfoFinder())
    def __repr__(self):
        return "Extracting standard performance for"
    def __call__(self, test):
        self.describe(test)
        sandbox.ExtractPerformanceFiles.__call__(self, test)
    def findLogFiles(self, test, stem):
        return test.getFileNamesMatching(stem)
    def getFileToWrite(self, test, stem):
        name = stem + "." + test.app.name + test.app.versionSuffix()
        return os.path.join(test.getDirectory(), name)
    def allMachinesTestPerformance(self, test, fileStem):
        # Assume this is OK: the current host is in any case utterly irrelevant
        return 1
    def setUpSuite(self, suite):
        self.describe(suite)
    def getMachineContents(self, test):
        return " on unknown machine (extracted)\n"
