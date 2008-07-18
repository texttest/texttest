
import os, sys, plugins, sandbox, respond, rundependent, comparetest, batch, subprocess, operator, glob, signal, testoverview

from copy import copy
from threading import Lock
from knownbugs import CheckForBugs, CheckForCrashes
from reconnect import ReconnectConfig
from traffic import SetUpTrafficHandlers
from jobprocess import killSubProcessAndChildren
from actionrunner import ActionRunner
from performance import TimeFilter
from time import sleep
from log4py import LOGLEVEL_NORMAL

plugins.addCategory("killed", "killed", "were terminated before completion")

def getConfig(optionMap):
    return Config(optionMap)

class Config:
    def __init__(self, optionMap):
        self.optionMap = optionMap
        self.filterFileMap = {}
        self.reconnectConfig = ReconnectConfig(optionMap)
    def addToOptionGroups(self, apps, groups):
        recordsUseCases = reduce(operator.or_, (app.getConfigValue("use_case_record_mode") != "disabled" for app in apps), False)
        useCatalogues = reduce(operator.or_, (self.isolatesDataUsingCatalogues(app) for app in apps), False)
        for group in groups:
            if group.name.startswith("Select"):
                group.addOption("t", "Test names containing", description="Select tests for which the name matches the entered text. The text can be a regular expression.")
                group.addOption("ts", "Suite names containing", description="Select tests for which at least one parent suite name matches the entered text. The text can be a regular expression.")
                group.addOption("a", "App names containing", description="Select tests for which the application name matches the entered text. The text can be a regular expression.")
                possibleDirs = self.getFilterFileDirectories(apps, createDirs=False)
                group.addOption("f", "Tests listed in file", possibleDirs=possibleDirs, selectFile=True)
                group.addOption("desc", "Descriptions containing", description="Select tests for which the description (comment) matches the entered text. The text can be a regular expression.")
                group.addOption("grep", "Test-files containing")
                group.addOption("grepfile", "Test-file to search", allocateNofValues=2)
                group.addOption("r", "Execution time", description="Specify execution time limits, either as '<min>,<max>', or as a list of comma-separated expressions, such as >=0:45,<=1:00. Digit-only numbers are interpreted as minutes, while colon-separated numbers are interpreted as hours:minutes:seconds.")
            elif group.name.startswith("Basic"):
                if len(apps) > 0:
                    version, checkout = apps[0].getFullVersion(), apps[0].checkout
                else:
                    version, checkout = "", ""
                group.addOption("v", "Run this version", version)
                group.addOption("c", "Use checkout", checkout)
                group.addOption("cp", "Times to run", "1", description="Set this to some number larger than 1 to run the same test multiple times, for example to try to catch indeterminism in the system under test")
                if recordsUseCases:
                    group.addSwitch("actrep", "Run with slow motion replay")
                if useCatalogues:
                    group.addSwitch("ignorecat", "Ignore catalogue file when isolating data")
            elif group.name.startswith("Advanced"):
                group.addSwitch("x", "Enable self-diagnostics")
                defaultDiagDir = os.path.join(os.getenv("TEXTTEST_HOME"), "Diagnostics")
                group.addOption("xr", "Configure self-diagnostics from", os.path.join(defaultDiagDir, "log4py.conf"))
                group.addOption("xw", "Write self-diagnostics to", defaultDiagDir)
                group.addOption("b", "Run batch mode session")
                group.addSwitch("rectraffic", "(Re-)record command-line or client-server traffic")
                group.addSwitch("keeptmp", "Keep temporary write-directories")
            elif group.name.startswith("Invisible"):
                # Options that don't make sense with the GUI should be invisible there...
                group.addOption("s", "Run this script")
                group.addOption("d", "Run as if TEXTTEST_HOME was")
                group.addSwitch("help", "Print configuration help text on stdout")
                group.addSwitch("g", "use dynamic GUI")
                group.addSwitch("gx", "use static GUI")
                group.addSwitch("con", "use console interface")
                group.addSwitch("coll", "Collect results for batch mode session")
                group.addOption("tp", "Private: Tests with exact path") # use for internal communication
                group.addOption("fd", "Private: Directory to search for filter files in")
                group.addOption("count", "Private: How many tests we believe there will be")
                group.addOption("name", "Batch run not identified by date, but by name")
                group.addOption("o", "Overwrite failures, optionally using version")
                group.addOption("reconnect", "Reconnect to previous run")
                group.addSwitch("reconnfull", "Recompute file filters when reconnecting")
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

    def createOptionGroups(self, allApps):
        groupNames = [ "Selection", "Basic", "Advanced", "Invisible" ]
        optionGroups = map(plugins.OptionGroup, groupNames)
        self.addToOptionGroups(allApps, optionGroups)
        return optionGroups
    
    def findAllValidOptions(self, allApps):
        groups = self.createOptionGroups(allApps)
        return reduce(operator.add, (g.keys() for g in groups), [])
    
    def getActionSequence(self):
        if self.optionMap.has_key("coll"):
            arg = self.optionMap.get("coll")
            if arg == "web":
                return []
            else:
                batchSession = self.optionValue("b")
                emailHandler = batch.CollectFiles([ "batch=" + batchSession ])
                return [ emailHandler ]
        if self.isReconnecting():
            return self.getReconnectSequence()

        return self.getTestProcessor()
    def useGUI(self):
        return self.optionMap.has_key("g") or self.optionMap.has_key("gx")
    def useStaticGUI(self, app):
        return self.optionMap.has_key("gx") or \
               (not self.hasExplicitInterface() and app.getConfigValue("default_interface") == "static_gui")
    def useConsole(self):
        return self.optionMap.has_key("con")
    def useExtraVersions(self):
        return True # static GUI didn't, once, but now we always read things the same.
    def getExtraVersions(self, app):
        if not self.useExtraVersions():
            return []
        fromConfig = self.getExtraVersionsFromConfig(app)
        fromCmd = self.getExtraVersionsFromCmdLine(app)
        extraVersions = copy(fromConfig)        
        for cmdVersion in fromCmd:
            extraVersions.append(cmdVersion)
            for extra in fromConfig:
                extraVersions.append(cmdVersion + "." + extra)

        return extraVersions

    def getExtraVersionsFromCmdLine(self, app):
        if self.isReconnecting():
            return self.reconnectConfig.getExtraVersions(app)
        else:
            copyCount = int(self.optionMap.get("cp", 1))
            return [ "copy_" + str(i) for i in range(1, copyCount) ]
        
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
        if len(allApps) == 0 or self.optionMap.has_key("new"):
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
        return self.useGUI() or self.batchMode() or self.useConsole() or \
               self.optionMap.has_key("o") or self.optionMap.has_key("s")
    def getResponderClasses(self, allApps):
        classes = []
        if self.optionMap.runScript():
            return self.getThreadActionClasses()
        
        if not self.hasExplicitInterface():
            self.setDefaultInterface(allApps)

        if not self.optionMap.has_key("gx"):
            if self.optionMap.has_key("new"):
                raise plugins.TextTestError, "'--new' option can only be provided with the static GUI"
            elif len(allApps) == 0:
                raise plugins.TextTestError, "Could not find any matching applications (files of the form config.<app>) under " + self.optionMap.directoryName
            
        # Put the GUI first ... first one gets the script engine - see respond module :)
        if self.useGUI():
            self.addGuiResponder(classes)
        else:
            classes.append(self.getTextDisplayResponderClass())
        if not self.optionMap.has_key("gx"):
            classes += self.getThreadActionClasses()

        if self.batchMode():
            if self.optionMap.has_key("coll"):
                if self.optionMap["coll"] != "mail": 
                    classes.append(batch.WebPageResponder)
            else:
                if self.optionValue("b") is None:
                    print "No batch session identifier provided, using 'default'"
                    self.optionMap["b"] = "default"
                classes.append(batch.BatchResponder)
        if self.useVirtualDisplay():
            from unixonly import VirtualDisplayResponder
            classes.append(VirtualDisplayResponder)
        if self.keepTemporaryDirectories():
            classes.append(self.getStateSaver())
        if not self.useGUI() and not self.batchMode():
            classes.append(self.getTextResponder())
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
        return respond.TextDisplayResponder
    def isolatesDataUsingCatalogues(self, app):
        return app.getConfigValue("create_catalogues") == "true" and \
               len(app.getConfigValue("partial_copy_test_path")) > 0
    def getRootTmpDir(self):
        if not os.getenv("TEXTTEST_TMP"):
            os.environ["TEXTTEST_TMP"] = self.getDefaultTextTestTmp()
        return os.path.expanduser(os.getenv("TEXTTEST_TMP"))
    def getDefaultTextTestTmp(self):
        if os.name == "nt" and os.getenv("TEMP"):
            return os.getenv("TEMP").replace("\\", "/")
        else:
            return "~/texttesttmp"

    def getWriteDirectory(self, app):
        return os.path.join(self.getRootTmpDir(), self.getWriteDirectoryName(app))
    def getWriteDirectoryName(self, app):
        parts = self.getBasicRunDescriptors(app) + self.getDescriptors("v") + [ self.getTimeDescriptor(), str(os.getpid()) ]
        return ".".join(parts)
    def getBasicRunDescriptors(self, app):
        appDescriptors = self.getDescriptors("a")
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
    def getDescriptors(self, key):
        givenVersion = self.optionValue(key)
        if givenVersion and givenVersion.find(",") == -1:
            return [ givenVersion ]
        else:
            return []
    def addGuiResponder(self, classes):
        from texttestgui import TextTestGUI
        classes.append(TextTestGUI)
    def getReconnectSequence(self):
        actions = [ self.reconnectConfig.getReconnectAction() ]
        actions += [ rundependent.FilterOriginal(), rundependent.FilterTemporary(), \
                     self.getTestComparator(), self.getFailureExplainer() ]
        return actions
    def getTestProcessor(self):        
        catalogueCreator = self.getCatalogueCreator()
        ignoreCatalogues = self.shouldIgnoreCatalogues()
        collator = self.getTestCollator()
        return [ self.getExecHostFinder(), self.getWriteDirectoryMaker(), \
                 self.getWriteDirectoryPreparer(ignoreCatalogues), \
                 SetUpTrafficHandlers(self.optionMap.has_key("rectraffic")), \
                 catalogueCreator, collator, rundependent.FilterOriginal(), self.getTestRunner(), \
                 catalogueCreator, collator, self.getTestEvaluator() ]
    def shouldIgnoreCatalogues(self):
        return self.optionMap.has_key("ignorecat") or self.optionMap.has_key("record")
    def hasPerformance(self, app):
        if len(app.getConfigValue("performance_logfile_extractor")) > 0:
            return True
        return self.hasAutomaticCputimeChecking(app)
    def hasAutomaticCputimeChecking(self, app):
        return len(app.getCompositeConfigValue("performance_test_machine", "cputime")) > 0
    def getFilterFileDirectories(self, apps, createDirs = True):
        # 
        # - For each application, collect
        #   - temporary filter dir
        #   - all dirs in test_list_files_directory
        #
        # Add these to a list. Never add the same dir twice. The first item will
        # be the default save/open dir, and the others will be added as shortcuts.
        #
        dirs = []
        for app in apps:
            appDirs = app.getConfigValue("test_list_files_directory")
            tmpDir = self.getTmpFilterDir(app)
            if not tmpDir in dirs:
                if createDirs:
                    try:
                        os.makedirs(tmpDir)
                    except:
                        pass # makedir throws if dir exists ...
                dirs.append(tmpDir)            
            for dir in appDirs:
                if os.path.isabs(dir) and os.path.isdir(dir):
                    if dir not in dirs:
                        dirs.append(dir)
                else:
                    newDir = os.path.join(app.getDirectory(), dir)
                    if createDirs:
                        try:
                            os.makedirs(newDir)
                        except:
                            pass # makedir throws if dir exists ...
                    if not newDir in dirs:
                        dirs.append(newDir)
        return dirs

    def getTmpFilterDir(self, app):
        cmdLineDir = self.optionValue("fd")
        if cmdLineDir:
            return os.path.normpath(cmdLineDir)
        else:
            return os.path.join(app.writeDirectory, "temporary_filter_files")
        
    def getFilterClasses(self):
        return [ TestNameFilter, plugins.TestPathFilter, \
                 TestSuiteFilter, TimeFilter, \
                 plugins.ApplicationFilter, TestDescriptionFilter ]
    def checkFilterFileSanity(self, app):
        # Turn any input relative files into absolute ones, throw if we can't
        for filterFileName in self.findFilterFileNames(app):
            absName = self.getAbsoluteFilterFileName(filterFileName, app)
            if absName:
                self.filterFileMap.setdefault(app, []).append(absName)
            else:
                raise plugins.TextTestError, "filter file '" + filterFileName + "' could not be found."
        
    def getAbsoluteFilterFileName(self, filterFileName, app):
        if os.path.isabs(filterFileName):
            if os.path.isfile(filterFileName):
                return filterFileName
        else:
            dirsToSearchIn = self.getFilterFileDirectories([app], False)
            return app.getFileName(dirsToSearchIn, filterFileName)
             
    def findFilterFileNames(self, app):
        if self.filterFileMap.has_key(app):
            return self.filterFileMap[app]
        names = []
        if self.optionMap.has_key("f"):
            names.append(self.optionMap["f"])
        names += app.getConfigValue("default_filter_file")
        if self.batchMode():
            names += app.getCompositeConfigValue("batch_filter_file", self.optionMap["b"])
        return names

    def getFilterList(self, app, options=None):
        if options is None:
            filters = self.getFiltersFromMap(self.optionMap, app)
            for filterFileName in self.findFilterFileNames(app):
                filters += self.getFiltersFromFile(app, filterFileName)
        else:
            filters = self.getFiltersFromMap(options, app)
            if options.has_key("f"):
                filters += self.getFiltersFromFile(app, options.get("f"))
        return filters
        
    def getFiltersFromFile(self, app, filename):        
        if not os.path.isfile(filename):
            raise plugins.TextTestError, "\nCould not find filter file at '" + filename + "'"

        fileData = ",".join(plugins.readList(filename))
        optionFinder = plugins.OptionFinder(fileData.split(), defaultKey="t")
        return self.getFiltersFromMap(optionFinder, app)
    
    def getFiltersFromMap(self, optionMap, app):
        filters = []
        for filterClass in self.getFilterClasses():
            if optionMap.has_key(filterClass.option):
                filters.append(filterClass(optionMap[filterClass.option], app))
        batchSession = self.optionMap.get("b")
        if batchSession:
            timeLimit = app.getCompositeConfigValue("batch_timelimit", batchSession)
            if timeLimit:
                filters.append(TimeFilter(timeLimit))
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
    def cleanPreviousTempDirs(self):
        return self.batchMode() and not self.isReconnecting()
    def cleanWriteDirectory(self, suite):
        if not self.keepTemporaryDirectories():
            self._cleanWriteDirectory(suite)
    def _cleanWriteDirectory(self, suite):
        if os.path.isdir(suite.app.writeDirectory):
            plugins.rmtree(suite.app.writeDirectory)
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
        return [ self.getFileExtractor(), rundependent.FilterTemporary(), self.getTestComparator(), self.getFailureExplainer() ]
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
    def showExecHostsInFailures(self):
        return self.batchMode()
    def getTestComparator(self):
        return comparetest.MakeComparisons()
    def getStateSaver(self):
        if self.batchMode():
            return batch.SaveState
        else:
            return respond.SaveState
    def getConfigEnvironment(self, test):
        testEnvironmentCreator = self.getEnvironmentCreator(test)
        return testEnvironmentCreator.getVariables()
    def getEnvironmentCreator(self, test):
        return sandbox.TestEnvironmentCreator(test, self.optionMap)
    def getInteractiveReplayOptions(self):
        return [ ("actrep", "slow motion") ]
    def getTextResponder(self):
        return respond.InteractiveResponder
    # Utilities, which prove useful in many derived classes
    def optionValue(self, option):
        return self.optionMap.get(option, "")
    def ignoreExecutable(self):
        return self.optionMap.runScript() or self.isReconnecting()
    def setUpCheckout(self, app):
        if self.ignoreExecutable():
            return ""
        checkoutPath = self.getGivenCheckoutPath(app)
        # Allow empty checkout, means no checkout is set, basically
        if len(checkoutPath) > 0:
            # don't fail to start the static GUI because of checkouts, can be fixed from there
            if not self.optionMap.has_key("gx"): 
                self.verifyCheckoutValid(checkoutPath)
            if checkoutPath:
                os.environ["TEXTTEST_CHECKOUT"] = checkoutPath
    
        return checkoutPath
    def verifyCheckoutValid(self, checkoutPath):
        if not os.path.isabs(checkoutPath):
            raise plugins.TextTestError, "could not create absolute checkout from relative path '" + checkoutPath + "'"
        elif not os.path.isdir(checkoutPath):
            raise plugins.TextTestError, "checkout '" + checkoutPath + "' does not exist"
    def checkSanity(self, suite):
        if not self.ignoreExecutable() and not self.optionMap.has_key("gx"):
            self.checkExecutableExists(suite)

        self.checkFilterFileSanity(suite.app)
        self.checkConfigSanity(suite.app)
        if self.batchMode():
            batchSession = self.optionMap.get("b")
            batchFilter = batch.BatchVersionFilter(batchSession)
            batchFilter.verifyVersions(suite.app)
        if self.isReconnecting():
            self.reconnectConfig.checkSanity(suite.app)
        # side effects really from here on :(
        if self.isReconnecting() or self.optionMap.has_key("coll"):
            # Reading stuff from stored pickle files, need to set up categories independently
            self.setUpPerformanceCategories(suite.app)

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
            raise plugins.TextTestError, "The executable program '" + executable + "' does not exist."
    def executableShouldBeFile(self, app, executable):
        # For finding java classes, don't warn if they don't exist as files...
        interpreter = app.getConfigValue("interpreter")
        return not interpreter.startswith("java") or executable.endswith(".jar") 
    def checkConfigSanity(self, app):
        for key in app.getConfigValue("collate_file"):
            if key.find(".") != -1:
                raise plugins.TextTestError, "Cannot collate files to stem '" + key + "' - '.' characters are not allowed"
    def getGivenCheckoutPath(self, app):
        checkout = self.getCheckout(app)
        if os.path.isabs(checkout):
            return checkout
        checkoutLocations = app.getCompositeConfigValue("checkout_location", checkout, expandVars=False)
        # do this afterwards, so it doesn't get expanded (yet)
        os.environ["TEXTTEST_CHECKOUT_NAME"] = checkout
        if len(checkoutLocations) > 0:
            return self.makeAbsoluteCheckout(checkoutLocations, checkout, app)
        else:
            return checkout
    def getCheckout(self, app):
        if self.optionMap.has_key("c"):
            return self.optionMap["c"]

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
    def recomputeProgress(self, test, observers):
        fileFilter = rundependent.FilterRecompute()
        fileFilter(test)
        comparator = self.getTestComparator()
        comparator.recomputeProgress(test, observers)
    def getRunDescription(self, test):
        return RunTest().getRunDescription(test)
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
    def getWebPageGeneratorClass(self):
        return testoverview.GenerateWebPages
    def getDefaultTestOverviewColours(self):
        try:
            from testoverview import colourFinder
            return colourFinder.getDefaultDict()
        except:
            return {}
    def getDefaultPageName(self, app):
        pageName = app.fullName
        fullVersion = app.getFullVersion()
        if fullVersion:
            pageName += " - version " + fullVersion
        return pageName
    def setBatchDefaults(self, app):
        # Batch values. Maps from session name to values
        app.setConfigDefault("smtp_server", "localhost", "Server to use for sending mail in batch mode")
        app.setConfigDefault("batch_result_repository", { "default" : "" }, "Directory to store historical batch results under")
        app.setConfigDefault("historical_report_location", { "default" : "" }, "Directory to create reports on historical batch data under")
        app.setConfigDefault("historical_report_page_name", { "default" : self.getDefaultPageName(app) }, "Header for page on which this application should appear")
        app.setConfigDefault("testoverview_colours", self.getDefaultTestOverviewColours(), "Colours to use for historical batch HTML reports")
        app.setConfigDefault("batch_sender", { "default" : self.getDefaultMailAddress() }, "Sender address to use sending mail in batch mode")
        app.setConfigDefault("batch_recipients", { "default" : self.getDefaultMailAddress() }, "Addresses to send mail to in batch mode")
        app.setConfigDefault("batch_timelimit", { "default" : "" }, "Maximum length of test to include in batch mode runs")
        app.setConfigDefault("batch_filter_file", { "default" : [] }, "Generic filter for batch session, more flexible than timelimit")
        app.setConfigDefault("batch_use_collection", { "default" : "false" }, "Do we collect multiple mails into one in batch mode")
        app.setConfigDefault("batch_mail_on_failure_only", { "default" : "false" }, "Send mails only if at least one test fails")
        app.setConfigDefault("batch_use_version_filtering", { "default" : "false" }, "Which batch sessions use the version filtering mechanism")
        app.setConfigDefault("batch_version", { "default" : [] }, "List of versions to allow if batch_use_version_filtering enabled")
    def setPerformanceDefaults(self, app):
        # Performance values
        app.setConfigDefault("cputime_include_system_time", 0, "Include system time when measuring CPU time?")
        app.setConfigDefault("performance_logfile", { "default" : [] }, "Which result file to collect performance data from")
        app.setConfigDefault("performance_logfile_extractor", {}, "What string to look for when collecting performance data")
        app.setConfigDefault("performance_test_machine", { "default" : [], "memory" : [ "any" ] }, \
                             "List of machines where performance can be collected")
        app.setConfigDefault("performance_variation_%", { "default" : 10.0 }, "How much variation in performance is allowed")
        app.setConfigDefault("performance_test_minimum", { "default" : 0.0 }, \
                             "Minimum time/memory to be consumed before data is collected")
        app.setConfigDefault("performance_descriptor_decrease", self.defaultPerfDecreaseDescriptors(), "Descriptions to be used when the numbers decrease in a performance file")
        app.setConfigDefault("performance_descriptor_increase", self.defaultPerfIncreaseDescriptors(), "Descriptions to be used when the numbers increase in a performance file")
        app.setConfigDefault("performance_unit", self.defaultPerfUnits(), "Name to be used to identify the units in a performance file")
        
    def setUsecaseDefaults(self, app):
        app.setConfigDefault("use_case_record_mode", "disabled", "Mode for Use-case recording (GUI, console or disabled)")
        app.setConfigDefault("use_case_recorder", "", "Which Use-case recorder is being used")
        app.setConfigDefault("slow_motion_replay_speed", 3, "How long in seconds to wait between each GUI action")
        app.setConfigDefault("virtual_display_machine", [ "localhost" ], \
                             "(UNIX) List of machines to run virtual display server (Xvfb) on")

    def defaultPerfUnits(self):
        units = {}
        units["default"] = "seconds"
        units["memory"] = "MB"
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
            return { "stacktrace" : "core*" }
        else:
            return {}
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

        app.setConfigDefault("collate_file", self.getDefaultCollations(), "Mapping of result file names to paths to collect them from")
        app.setConfigDefault("collate_script", self.getDefaultCollateScripts(), "Mapping of result file names to scripts which turn them into suitable text")
        app.setConfigDefault("collect_traffic", [], "List of command-line programs to intercept")
        app.setConfigDefault("collect_traffic_environment", { "default" : [] }, "Mapping of collected programs to environment variables they care about")
        app.setConfigDefault("run_dependent_text", { "default" : [] }, "Mapping of patterns to remove from result files")
        app.setConfigDefault("unordered_text", { "default" : [] }, "Mapping of patterns to extract and sort from result files")
        app.setConfigDefault("create_catalogues", "false", "Do we create a listing of files created/removed by tests")
        app.setConfigDefault("catalogue_process_string", "", "String for catalogue functionality to identify processes created")
        app.setConfigDefault("binary_file", [], "Which output files are known to be binary, and hence should not be shown/diffed?")
        
        app.setConfigDefault("discard_file", [], "List of generated result files which should not be compared")
        if self.optionMap.has_key("rectraffic"):
            app.addConfigEntry("base_version", "rectraffic")
        if homeOS != "any" and homeOS != os.name:
            app.addConfigEntry("base_version", os.name)

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
        app.setConfigDefault("text_diff_program_max_file_size", "-1", "The maximum file size to use the text_diff_program, in bytes. -1 means no limit.")
        app.setConfigDefault("text_diff_program_filters", { "default" : [], "diff" : [ "^<", "^>" ]}, "Filters that should be applied for particular diff tools to aid with grouping in dynamic GUI")
        app.setConfigDefault("diff_program", { "default": "tkdiff" }, "External program to use for graphical file comparison")
        app.setConfigDefault("view_program", { "default": self.defaultViewProgram(homeOS) },  \
                              "External program(s) to use for viewing and editing text files")
        app.setConfigDefault("follow_program", { "default": self.defaultFollowProgram() }, "External program to use for following progress of a file")
        app.setConfigDefault("follow_file_by_default", 0, "When double-clicking running files, should we follow progress or just view them?")
        app.setConfigDefault("bug_system_script", { "default" : "" }, "The location of the script used to extract information from the bug system.")
    def setInterfaceDefaults(self, app):
        app.setConfigDefault("default_interface", "static_gui", "Which interface to start if none of -con, -g and -gx are provided")
        # These configure the GUI but tend to have sensible defaults per application
        app.setConfigDefault("gui_entry_overrides", { "default" : "<not set>" }, "Default settings for entries in the GUI")
        app.setConfigDefault("gui_entry_options", { "default" : [] }, "Default drop-down box options for GUI entries")
        app.setConfigDefault("suppress_stderr_popup", [], "List of patterns which, if written on stderr, should not produce a warning popup")
    def setMiscDefaults(self, app):
        app.setConfigDefault("checkout_location", { "default" : []}, "Absolute paths to look for checkouts under")
        app.setConfigDefault("default_checkout", "", "Default checkout, relative to the checkout location")
        app.setConfigDefault("default_filter_file", [], "Filter file to use by default, generally only useful for versions")
        app.setConfigDefault("test_data_environment", {}, "Environment variables to be redirected for linked/copied test data")
        app.setConfigDefault("test_data_properties", { "default" : "" }, "Write the contents of test_data_environment to the given Java properties file")
        app.setConfigDefault("test_list_files_directory", [ "filter_files" ], "Default directories for test filter files, relative to an application directory.")
        app.setConfigDefault("extra_version", [], "Versions to be run in addition to the one specified")
        app.setConfigDefault("batch_extra_version", { "default" : [] }, "Versions to be run in addition to the one specified, for particular batch sessions")
        # Applies to any interface...
        app.setConfigDefault("auto_sort_test_suites", 0, "Automatically sort test suites in alphabetical order. 1 means sort in ascending order, -1 means sort in descending order.")
        app.addConfigEntry("definition_file_stems", "options")
        app.addConfigEntry("definition_file_stems", "usecase")
        app.addConfigEntry("definition_file_stems", "traffic")
        app.addConfigEntry("definition_file_stems", "input")
        app.addConfigEntry("definition_file_stems", "knownbugs")
    def setApplicationDefaults(self, app):
        homeOS = app.getConfigValue("home_operating_system")
        self.setComparisonDefaults(app, homeOS)
        self.setExternalToolDefaults(app, homeOS)
        self.setInterfaceDefaults(app)
        self.setMiscDefaults(app)
        self.setBatchDefaults(app)
        self.setPerformanceDefaults(app)
        self.setUsecaseDefaults(app)
        if not plugins.TestState.showExecHosts:
            plugins.TestState.showExecHosts = self.showExecHostsInFailures()
    
class TestNameFilter(plugins.TextFilter):
    option = "t"
    def acceptsTestCase(self, test):
        return self.containsText(test)

class TestSuiteFilter(plugins.TextFilter):
    option = "ts"
    def acceptsTestCase(self, test):
        return self.stringContainsText(test.parent.getRelPath())

class GrepFilter(plugins.TextFilter):
    def __init__(self, filterText, fileStem):
        plugins.TextFilter.__init__(self, filterText)
        self.fileStem = fileStem
    def acceptsTestCase(self, test):
        for logFile in self.findAllLogFiles(test):
            if self.matches(logFile):
                return True
        return False
    def findAllLogFiles(self, test):
        logFiles = []
        for fileName in test.findAllStdFiles(self.fileStem):
            fileVersions = os.path.basename(fileName).split(".")[2:]
            if self.allAllowed(fileVersions, test.app.versions):
                if os.path.isfile(fileName):
                    logFiles.append(fileName)
                else:
                    test.refreshFiles()
                    return self.findAllLogFiles(test)
        return logFiles
    def allAllowed(self, fileVersions, versions):
        for version in fileVersions:
            if version not in versions:
                return False
        return True
    def matches(self, logFile):
        for line in open(logFile).xreadlines():
            if self.stringContainsText(line):
                return True
        return False


class TestDescriptionFilter(plugins.TextFilter):
    option = "desc"
    def acceptsTestCase(self, test):
        return self.stringContainsText(plugins.extractComment(test.description))

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

class RunTest(plugins.Action):
    def __init__(self):
        self.diag = plugins.getDiagnostics("run test")
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
        process = self.getTestProcess(test)
        self.changeToRunningState(test)
        
        self.registerProcess(test, process)
        self.wait(process)
        self.checkAndClear(test)
    
    def registerProcess(self, test, process):
        self.lock.acquire()
        self.currentProcess = process
        if test in self.killedTests:
            self.killProcess()
        self.lock.release()

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
            self.killProcess()
        self.lock.release()
    def killProcess(self):
        print "Killing running test (process id", str(self.currentProcess.pid) + ")"
        killSubProcessAndChildren(self.currentProcess)
    
    def wait(self, process):
        try:
            plugins.retryOnInterrupt(process.wait)
        except OSError:
            pass # safest, as there are python bugs in this area
        
    def getOptions(self, test):
        optionsFile = test.getFileName("options")
        if optionsFile:
            # Our own version, see plugins.py
            return os.path.expandvars(open(optionsFile).read().strip(), test.getEnvironment)
        else:
            return ""
    def diagnose(self, testEnv, commandArgs):
        if self.diag.get_loglevel() >= LOGLEVEL_NORMAL:
            for var, value in testEnv.items():
                self.diag.info("Environment: " + var + " = " + value)
            self.diag.info("Running test with args : " + repr(commandArgs))

    def getRunDescription(self, test):
        commandArgs = self.getExecuteCmdArgs(test)
        text =  "Command Line   : " + plugins.commandLineString(commandArgs) + "\n"
        interestingVars = []
        testEnv = test.getRunEnvironment()
        for var, value in testEnv.items():
            if value != os.getenv(var):
                interestingVars.append(var)
        if len(interestingVars) == 0:
            return text
        text += "\nEnvironment variables :\n"
        interestingVars.sort()
        for var in interestingVars:
            text += var + ": " + testEnv.get(var) + "\n"
        return text
        
    def getTestProcess(self, test):
        commandArgs = self.getExecuteCmdArgs(test)
        testEnv = test.getRunEnvironment()
        self.diagnose(testEnv, commandArgs)
        return subprocess.Popen(commandArgs, preexec_fn=self.getPreExecFunction(), \
                                stdin=open(self.getInputFile(test)), cwd=test.getDirectory(temporary=1), \
                                stdout=self.makeFile(test, "output"), stderr=self.makeFile(test, "errors"), \
                                env=testEnv, startupinfo=plugins.getProcessStartUpInfo(test.getEnvironment))
    def getPreExecFunction(self):
        if os.name == "posix":
            return self.ignoreJobControlSignals
    def ignoreJobControlSignals(self):
        for signum in [ signal.SIGUSR1, signal.SIGUSR2, signal.SIGXCPU ]:
            signal.signal(signum, signal.SIG_IGN)
    def getInterpreter(self, test):
        interpreter = test.getConfigValue("interpreter")
        if interpreter.startswith("ttpython"): # interpreted to mean "whatever python TextTest runs with"
            return interpreter.replace("ttpython", sys.executable + " -u")
        return interpreter
    def getCmdParts(self, test):
        args = []
        interpreter = self.getInterpreter(test)
        if interpreter:
            args.append(interpreter)
        args.append(test.getConfigValue("executable"))
        args.append(self.getOptions(test))
        return args
    def getExecuteCmdArgs(self, test):
        parts = self.getCmdParts(test)
        basicArgs = reduce(operator.add, map(plugins.splitcmd, parts))
        if test.app.hasAutomaticCputimeChecking():
            perfFile = test.makeTmpFileName("unixperf", forFramework=1)
            return [ "time", "-p", "-o", perfFile ] + basicArgs
        else:
            return basicArgs
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
    def __init__(self):
        self.appCount = {}
    def __del__(self):
        for app, count in self.appCount.items():
            print app, "has", count, "tests"
    def __repr__(self):
        return "Counting"
    def __call__(self, test):
        self.describe(test)
        self.appCount[test.app.description()] += 1
    def setUpSuite(self, suite):
        self.describe(suite)
    def setUpApplication(self, app):
        self.appCount[app.description()] = 0



class DocumentOptions(plugins.Action):
    def setUpApplication(self, app):
        groups = app.createOptionGroups([ app ])
        keys = reduce(operator.add, (g.keys() for g in groups), [])
        keys.sort()
        for key in keys:
            self.displayKey(key, groups)
    def displayKey(self, key, groups):
        for group in groups:
            if group.options.has_key(key):
                keyOutput, docOutput = self.optionOutput(key, group, group.options[key].name)
                self.display(keyOutput, self.groupOutput(group), docOutput)
            if group.switches.has_key(key):    
                self.display("-" + key, self.groupOutput(group), group.switches[key].describe())
    def display(self, keyOutput, groupOutput, docOutput):
        if not docOutput.startswith("Private"):
            print keyOutput + ";" + groupOutput + ";" + docOutput.replace("SGE", "SGE/LSF")
    def groupOutput(self, group):
        if group.name == "Invisible":
            return "N/A"
        else:
            return group.name
    def optionOutput(self, key, group, docs):
        keyOutput = "-" + key + " <value>"
        if (docs == "Execution time"):
            keyOutput = "-" + key + " <time specification string>"
        elif docs.find("<") != -1:
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
        entries = app.configDir.keys() + app.configDir.aliases.keys()
        entries.sort()
        for key in entries:
            realKey = app.configDir.aliases.get(key, key)
            if realKey == key:
                docOutput = app.configDocs[realKey]
            else:
                docOutput = "Alias. See entry for '" + realKey + "'"
            if not docOutput.startswith("Private"):
                value = app.configDir[realKey]
                print key + "|" + str(value) + "|" + docOutput  

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
        argDict = self.parseArguments(args)
        self.oldTextTrigger = plugins.TextTrigger(argDict["old"])
        self.newText = argDict["new"].replace("\\n", "\n")
        self.logFile = None
        if argDict.has_key("file"):
            self.logFile = argDict["file"]
        self.textDiffTool = None
    def __repr__(self):
        return "Replacing " + self.oldTextTrigger.text + " with " + self.newText + " for"
    def __call__(self, test):
        logFile = test.getFileName(self.logFile)
        if not logFile:
            return
        self.describe(test)
        sys.stdout.flush()
        newLogFile = logFile + "_new"
        writeFile = open(newLogFile, "w")
        for line in open(logFile).xreadlines():
            writeFile.write(self.oldTextTrigger.replace(line, self.newText))
        writeFile.close()
        os.system(self.textDiffTool + " " + logFile + " " + newLogFile)
        os.remove(logFile)
        os.rename(newLogFile, logFile)
    def setUpSuite(self, suite):
        self.describe(suite)
    def setUpApplication(self, app):
        if not self.logFile:
            self.logFile = app.getConfigValue("log_file")
        self.textDiffTool = app.getConfigValue("text_diff_program")

class ExportTests(plugins.ScriptWithArgs):
    scriptDoc = "Export the selected tests to a different test suite"
    def __init__(self, args):
        argDict = self.parseArguments(args)
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
                otherParent.copyTest(test, test.name, test.description, self.placements[parent])
            else:
                self.describe(test, " - COULDN'T FIND PARENT")
        self.placements[parent] += 1

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
        if glob.has_magic(stem):
            return test.getFileNamesMatching(stem)
        else:
            return [ test.getFileName(stem) ]
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
