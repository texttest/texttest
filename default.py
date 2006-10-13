#!/usr/local/bin/python

import os, shutil, plugins, respond, performance, comparetest, string, sys, batch, re, stat
import glob
from threading import currentThread
from knownbugs import CheckForBugs, CheckForCrashes
from traffic import SetUpTrafficHandlers
from cPickle import Unpickler
from socket import gethostname
from ndict import seqdict

plugins.addCategory("killed", "killed", "were terminated before completion")

def getConfig(optionMap):
    return Config(optionMap)

class Config(plugins.Configuration):
    def addToOptionGroups(self, app, groups):
        recordsUseCases = app.getConfigValue("use_case_record_mode") != "disabled"
        for group in groups:
            if group.name.startswith("Select"):
                group.addOption("t", "Test names containing")
                group.addOption("f", "Tests listed in file", possibleValues=self.getPossibleFilterFiles(app))
                group.addOption("ts", "Suite names containing")
                group.addOption("grep", "Result files containing")
                group.addOption("grepfile", "Result file to search", app.getConfigValue("log_file"), self.getPossibleResultFiles(app))
                group.addOption("r", "Execution time <min, max>")
            elif group.name.startswith("What"):
                group.addOption("c", "Use checkout", app.checkout)
                group.addOption("reconnect", "Reconnect to")
                group.addSwitch("reconnfull", "Recompute file filters when reconnecting")
            elif group.name.startswith("How"):
                group.addOption("b", "Run batch mode session")
                if recordsUseCases:
                    group.addSwitch("actrep", "Run with slow motion replay")
                diagDict = app.getConfigValue("diagnostics")
                if diagDict.has_key("configuration_file"):
                    group.addSwitch("diag", "Write target application diagnostics")
                if diagDict.has_key("trace_level_variable"):
                    group.addOption("trace", "Target application trace level")
                group.addSwitch("noperf", "Disable any performance testing")
                if self.isolatesDataUsingCatalogues(app):
                    group.addSwitch("ignorecat", "Ignore catalogue file when isolating data")
                group.addSwitch("rectraffic", "(Re-)record command-line or client-server traffic")
            elif group.name.startswith("Invisible"):
                # Only relevant without the GUI
                group.addSwitch("g", "use dynamic GUI", 1)
                group.addSwitch("gx", "use static GUI")
                group.addSwitch("con", "use console interface")
                group.addSwitch("o", "Overwrite all failures")
                group.addSwitch("coll", "Collect results for batch mode session")
                group.addOption("tp", "Private: Tests with exact path") # use for internal communication
                group.addOption("fd", "Private: Directory to search for filter files in")
                group.addSwitch("n", "Create new results files (overwrite everything)")
                if recordsUseCases:
                    group.addSwitch("record", "Record usecase rather than replay what is present")
                    group.addSwitch("holdshell", "Hold shells running system under test...")
            elif group.name.startswith("Side"):
                group.addSwitch("keeptmp", "Keep temporary write-directories")
    def getActionSequence(self):
        if self.optionMap.has_key("coll"):
            batchSession = self.optionValue("b")
            emailHandler = batch.CollectFiles([ "batch=" + batchSession ])
            webHandler = batch.GenerateHistoricalReport([ batchSession ])
            return [ emailHandler, webHandler ]
        if self.isReconnecting():
            return self.getReconnectSequence()

        return self._getActionSequence(makeDirs=1)
    def useGUI(self):
        return self.optionMap.has_key("g") or self.optionMap.has_key("gx")
    def useStaticGUI(self, app):
        return self.optionMap.has_key("gx") or \
               (not self.hasExplicitInterface() and app.getConfigValue("default_interface") == "static_gui")
    def useConsole(self):
        return self.optionMap.has_key("con")
    def getDefaultInterface(self, allApps):
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
    def getResponderClasses(self, allApps):
        classes = []
        if not self.hasExplicitInterface():
            self.setDefaultInterface(allApps)
        # Put the GUI first ... first one gets the script engine - see respond module :)
        if self.useGUI():
            self.addGuiResponder(classes)
        else:
            classes.append(respond.TextDisplayResponder)
        if self.batchMode() and not self.optionMap.has_key("coll"):
            classes.append(batch.BatchResponder)
        if self.keepTemporaryDirectories():
            classes.append(self.getStateSaver())
        if not self.useGUI() and not self.batchMode():
            classes.append(self.getTextResponder())
        return classes
    def isolatesDataUsingCatalogues(self, app):
        return app.getConfigValue("create_catalogues") == "true" and \
               len(app.getConfigValue("partial_copy_test_path")) > 0
    def getRunOptions(self, checkout):
        if checkout:
            return "-c " + checkout
        else:
            return ""
    def getWriteDirectoryName(self, app):
        defaultName = plugins.Configuration.getWriteDirectoryName(self, app)
        if self.useStaticGUI(app):
            dirname, local = os.path.split(defaultName)
            versionSuffix = app.versionSuffix()
            if versionSuffix:
                local = local.replace(versionSuffix, "")
            return os.path.join(dirname, "static_gui." + local)
        else:
            return defaultName
    def addGuiResponder(self, classes):
        from texttestgui import TextTestGUI
        classes.append(TextTestGUI)
    def _getActionSequence(self, makeDirs):
        actions = [ self.getTestProcessor() ]
        if makeDirs:
            actions = [ self.getWriteDirectoryMaker() ] + actions
        return actions
    def getReconnectSequence(self):
        reconnFull = self.optionMap.has_key("reconnfull")
        actions = [ ReconnectTest(self.optionValue("reconnect"), reconnFull) ]
        if reconnFull:
            actions += [ self.getTestComparator(), self.getFailureExplainer() ]
        return actions
    def getTestProcessor(self):        
        catalogueCreator = self.getCatalogueCreator()
        ignoreCatalogues = self.shouldIgnoreCatalogues()
        collator = self.getTestCollator()
        return [ self.getExecHostFinder(), self.getWriteDirectoryPreparer(ignoreCatalogues), \
                 SetUpTrafficHandlers(self.optionMap.has_key("rectraffic")), \
                 catalogueCreator, collator, self.getTestRunner(), catalogueCreator, collator, self.getTestEvaluator() ]
    def shouldIgnoreCatalogues(self):
        return self.optionMap.has_key("ignorecat") or self.optionMap.has_key("record")
    def getPossibleResultFiles(self, app):
        files = [ "output", "errors" ]
        if app.getConfigValue("create_catalogues") == "true":
            files.append("catalogue")
        collateKeys = app.getConfigValue("collate_file").keys()
        if "stacktrace" in collateKeys:
            collateKeys.remove("stacktrace")
        collateKeys.sort()
        files += collateKeys
        files += app.getConfigValue("performance_logfile_extractor").keys()
        if self.hasAutomaticCputimeChecking(app):
            files.append("performance")
        for file in app.getConfigValue("discard_file"):
            if file in files:
                files.remove(file)
        return files
    def hasPerformance(self, app):
        if len(app.getConfigValue("performance_logfile_extractor")) > 0:
            return True
        return self.hasAutomaticCputimeChecking(app)
    def hasAutomaticCputimeChecking(self, app):
        return len(app.getCompositeConfigValue("performance_test_machine", "cputime")) > 0
    def getPossibleFilterFiles(self, app):
        filterFiles = []
        for directory in self.getFilterDirs(app):
            filenames = os.listdir(directory)
            filenames.sort()
            for filename in filenames:
                if os.path.isfile(os.path.join(directory, filename)):
                    filterFiles.append(filename)
        return filterFiles
    def getFilterFilePath(self, app, filename, forWrite):
        filterDirs = self.getFilterDirs(app)
        if forWrite:
            dirToUse = filterDirs[0]
            plugins.ensureDirectoryExists(dirToUse)
            return os.path.join(dirToUse, filename)
        else:
            return app.getFileName(filterDirs, filename)
    def getFilterDirs(self, app):
        cmdLineDir = self.optionValue("fd")
        if cmdLineDir:
            return [ cmdLineDir ]

        return self.getConfigFilterDirs(app) + self.getTmpFilterDirs(app) 
    def getTmpFilterDirs(self, app):
        return glob.glob(os.path.join(app.writeDirectory, "dynamic_run*"))
    def getConfigFilterDirs(self, app):
        rawDirs = app.getConfigValue("test_list_files_directory")
        allDirs = map(lambda dir: os.path.join(app.getDirectory(), dir), rawDirs)
        return filter(os.path.isdir, allDirs)
    def getFilterClasses(self):
        return [ TestNameFilter, TestPathFilter, TestSuiteFilter, \
                 batch.BatchFilter, performance.TimeFilter ]
    def getFilterFileName(self, app):
        if self.optionMap.has_key("f"):
            return self.optionMap["f"]
        if self.batchMode():
            return app.getCompositeConfigValue("batch_filter_file", self.optionMap["b"])
        else:
            return ""
    def getFilterList(self, app):
        filters = self.getFiltersFromMap(self.optionMap, app)
        filterFileName = self.getFilterFileName(app)
        if filterFileName:
            filters += self.getFiltersFromFile(app, filterFileName)
        return filters
    def getFiltersFromFile(self, app, filename):
        fullPath = self.getFilterFilePath(app, filename, forWrite=False)
        if not fullPath:
            sys.stderr.write("Rejected application " + repr(app) + " : filter file '" + filename + "' could not be found\n")
            return [ RejectFilter() ]

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
        return MakeWriteDirectory()
    def getExecHostFinder(self):
        return FindExecutionHosts()
    def getWriteDirectoryPreparer(self, ignoreCatalogues):
        return PrepareWriteDirectory(ignoreCatalogues)
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
        return [ self.getFileExtractor(), self.getTestComparator(), self.getFailureExplainer() ]
    def getFileExtractor(self):
        if self.optionMap.has_key("noperf"):
            return
        elif self.optionMap.has_key("diag"):
            print "Note: Running with Diagnostics on, so performance checking is disabled!"
            return [ self.getPerformanceExtractor() ] 
        else:
            return [ self.getPerformanceFileMaker(), self.getPerformanceExtractor() ]
    def getCatalogueCreator(self):
        return CreateCatalogue()
    def getTestCollator(self):
        return CollateFiles()
    def getPerformanceExtractor(self):
        return ExtractPerformanceFiles(self.getMachineInfoFinder())
    def getPerformanceFileMaker(self):
        return MakePerformanceFile(self.getMachineInfoFinder())
    def getMachineInfoFinder(self):
        return MachineInfoFinder()
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
    def setEnvironment(self, test):
        testEnvironmentCreator = TestEnvironmentCreator(test, self.optionMap)
        testEnvironmentCreator.setUp(self.runsTests())
    def runsTests(self):
        return not self.optionMap.has_key("gx")
    def getTextResponder(self):
        return respond.InteractiveResponder
    # Utilities, which prove useful in many derived classes
    def optionValue(self, option):
        return self.optionMap.get(option, "")
    def getCheckoutPath(self, app):
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
    def progressText(self, test):
        perc = self.calculatePercentage(test)
        if perc > 0:
            return "\nFrom log file reckoned to be " + str(perc) + "% complete."
        else:
            return ""
    def calculatePercentage(self, test):
        logFileStem = test.getConfigValue("log_file")
        stdFile = test.getFileName(logFileStem)
        tmpFile = test.makeTmpFileName(logFileStem)
        if not os.path.isfile(tmpFile) or not stdFile:
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
    def getDefaultMailAddress(self):
        user = os.getenv("USER", "$USER")
        return user + "@localhost"
    def getDefaultTestOverviewColours(self):
        try:
            from testoverview import colourFinder
            return colourFinder.getDefaultDict()
        except:
            return {}
    def setBatchDefaults(self, app):
        # Batch values. Maps from session name to values
        app.setConfigDefault("smtp_server", "localhost", "Server to use for sending mail in batch mode")
        app.setConfigDefault("batch_result_repository", { "default" : "" }, "Directory to store historical batch results under")
        app.setConfigDefault("historical_report_location", { "default" : "" }, "Directory to create reports on historical batch data under")
        app.setConfigDefault("testoverview_colours", self.getDefaultTestOverviewColours(), "Colours to use for historical batch HTML reports")
        app.setConfigDefault("batch_sender", { "default" : self.getDefaultMailAddress() }, "Sender address to use sending mail in batch mode")
        app.setConfigDefault("batch_recipients", { "default" : self.getDefaultMailAddress() }, "Addresses to send mail to in batch mode")
        app.setConfigDefault("batch_timelimit", { "default" : None }, "Maximum length of test to include in batch mode runs")
        app.setConfigDefault("batch_filter_file", { "default" : None }, "Generic filter for batch session, more flexible than timelimit")
        app.setConfigDefault("batch_use_collection", { "default" : "false" }, "Do we collect multiple mails into one in batch mode")
        # Sample to show that values are lists
        app.setConfigDefault("batch_version", { "default" : [] }, "Which versions are allowed as batch mode runs")
        # Use batch session as a base version
        batchSession = self.optionValue("b")
        if batchSession:
            app.addConfigEntry("base_version", batchSession)
    def setPerformanceDefaults(self, app):
        # Performance values
        app.setConfigDefault("cputime_include_system_time", 0, "Include system time when measuring CPU time?")
        app.setConfigDefault("performance_logfile", { "default" : [] }, "Which result file to collect performance data from")
        app.setConfigDefault("performance_logfile_extractor", {}, "What string to look for when collecting performance data")
        app.setConfigDefault("performance_test_machine", { "default" : [], "memory" : [ "any" ] }, \
                             "List of machines where performance can be collected")
        app.setConfigDefault("performance_variation_%", { "default" : 10 }, "How much variation in performance is allowed")
        app.setConfigDefault("performance_test_minimum", { "default" : 0 }, \
                             "Minimum time/memory to be consumed before data is collected")
    def setUsecaseDefaults(self, app):
        app.setConfigDefault("use_case_record_mode", "disabled", "Mode for Use-case recording (GUI, console or disabled)")
        app.setConfigDefault("use_case_recorder", "", "Which Use-case recorder is being used")
        app.setConfigDefault("slow_motion_replay_speed", 3, "How long in seconds to wait between each GUI action")
        if os.name == "posix":
            app.setConfigDefault("virtual_display_machine", [], \
                                 "(UNIX) List of machines to run virtual display server (Xvfb) on")
    def defaultSeverities(self):
        severities = {}
        severities["errors"] = 1
        severities["output"] = 1
        severities["performance"] = 2
        severities["usecase"] = 2
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
            return { "stacktrace" : "interpretcore.py" }
        else:
            return {}
    def setComparisonDefaults(self, app):
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
        
        app.setConfigDefault("discard_file", [], "List of generated result files which should not be compared")
        app.setConfigDefault("home_operating_system", "any", "Which OS the test results were originally collected on")
        if self.optionMap.has_key("rectraffic"):
            app.addConfigEntry("base_version", "rectraffic")
    def defaultViewProgram(self):
        if os.name == "posix":
            return "emacs"
        else:
            return "notepad"
    def defaultFollowProgram(self):
        if os.name == "posix":
            return "tail -f"
        else:
            return "baretail"
    def setExternalToolDefaults(self, app):
        app.setConfigDefault("text_diff_program", "diff", \
                             "External program to use for textual comparison of files")
        app.setConfigDefault("lines_of_text_difference", 30, "How many lines to present in textual previews of file diffs")
        app.setConfigDefault("max_width_text_difference", 500, "How wide lines can be in textual previews of file diffs")
        app.setConfigDefault("text_diff_program_max_file_size", "-1", "The maximum file size to use the text_diff_program, in bytes. -1 means no limit.")
        app.setConfigDefault("diff_program", "tkdiff", "External program to use for graphical file comparison")
        app.setConfigDefault("view_program", { "default": self.defaultViewProgram() },  \
                              "External program(s) to use for viewing and editing text files")
        app.setConfigDefault("follow_program", self.defaultFollowProgram(), "External program to use for following progress of a file")
    def getGuiColourDictionary(self):
        dict = {}
        dict["success"] = "green"
        dict["failure"] = "red"
        dict["running"] = "yellow"
        dict["not_started"] = "white"
        dict["pending"] = "white"
        dict["static"] = "pale green"
        dict["app_static"] = "purple"
        return dict
    def setInterfaceDefaults(self, app):
        app.setConfigDefault("default_interface", "static_gui", "Which interface to start if none of -con, -g and -gx are provided")
        # Do this here rather than from the GUI: if applications can be run with the GUI
        # anywhere it needs to be set up
        app.setConfigDefault("add_shortcut_bar", 1, "Whether or not TextTest's shortcut bar will appear")
        app.setConfigDefault("add_status_bar", 1, "Whether or not TextTest's status bar will appear")
        app.setConfigDefault("static_collapse_suites", 0, "Whether or not the static GUI will show everything collapsed")
        app.setConfigDefault("test_colours", self.getGuiColourDictionary(), "Colours to use for each test state")
        app.setConfigDefault("file_colours", self.getGuiColourDictionary(), "Colours to use for each file state")
        app.setConfigDefault("auto_collapse_successful", 1, "Automatically collapse successful test suites?")
        app.setConfigDefault("auto_sort_test_suites", 0, "Automatically sort test suites in alphabetical order")
        app.setConfigDefault("window_size", { "" : [] }, "To set the initial size of the dynamic/static GUI.")
        app.setConfigDefault("hide_test_category", [], "Categories of tests which should not appear in the dynamic GUI test view")
        app.setConfigDefault("query_kill_processes", { "" : [] }, "Ask about whether to kill these processes when exiting texttest.")
        app.setConfigDefault("gui_entry_overrides", {}, "Default settings for entries in the GUI")
        app.setConfigDefault("gui_entry_options", { "" : [] }, "Default drop-down box options for GUI entries")
        app.setConfigDefault("gui_accelerators", { "" : [] }, "Custom action accelerators.")
        app.setConfigDefault("static_gui_show_menubar", 1, "Show menubar in the static GUI?")
        app.setConfigDefault("static_gui_show_toolbar", 1, "Show toolbar in the static GUI?")
        app.setConfigDefault("dynamic_gui_show_menubar", 1, "Show menubar in the dynamic GUI?")
        app.setConfigDefault("dynamic_gui_show_toolbar", 1, "Show toolbar in the dynamic GUI?")
    def setMiscDefaults(self, app):
        app.setConfigDefault("checkout_location", { "default" : []}, "Absolute paths to look for checkouts under")
        app.setConfigDefault("default_checkout", "", "Default checkout, relative to the checkout location")
        app.setConfigDefault("diagnostics", {}, "Dictionary to define how SUT diagnostics are used")
        app.setConfigDefault("test_data_environment", {}, "Environment variables to be redirected for linked/copied test data")
        app.setConfigDefault("test_data_searchpath", { "default" : [] }, "Locations to search for test data if not present in test structure")
        app.setConfigDefault("test_list_files_directory", [ "filter_files" ], "Directories to search for test-filter files")
        app.addConfigEntry("definition_file_stems", "options")
        app.addConfigEntry("definition_file_stems", "usecase")
        app.addConfigEntry("definition_file_stems", "traffic")
        app.addConfigEntry("definition_file_stems", "input")
        app.addConfigEntry("definition_file_stems", "knownbugs")
    def setApplicationDefaults(self, app):
        self.setComparisonDefaults(app)
        self.setExternalToolDefaults(app)
        self.setInterfaceDefaults(app)
        self.setMiscDefaults(app)
        self.setBatchDefaults(app)
        self.setPerformanceDefaults(app)
        self.setUsecaseDefaults(app)
        if not plugins.TestState.showExecHosts:
            plugins.TestState.showExecHosts = self.showExecHostsInFailures()

# Class for automatically adding things to test environment files...
class TestEnvironmentCreator:
    def __init__(self, test, optionMap):
        self.test = test
        self.optionMap = optionMap
        self.usecaseFile = self.test.getFileName("usecase")
        self.inputFile = self.test.getFileName("input")
        self.diagDict = self.test.getConfigValue("diagnostics")
        self.diag = plugins.getDiagnostics("Environment Creator")
    def setUp(self, runsTests):
        if self.setVirtualDisplay(runsTests):
            self.setDisplayEnvironment()
        self.setDiagEnvironment()
        if self.testCase():
            self.setUseCaseEnvironment()
    def topLevel(self):
        return self.test.parent is None
    def testCase(self):
        return self.test.classId() == "test-case"
    def setDisplayEnvironment(self):
        from unixonly import VirtualDisplayFinder
        finder = VirtualDisplayFinder(self.test.app)
        display = finder.getDisplay()
        if display:
            self.test.setEnvironment("TEXTTEST_VIRTUAL_DISPLAY", display)
            print "Tests will run with DISPLAY variable set to", display
    def setVirtualDisplay(self, runsTests):
        # Set a virtual DISPLAY for the top level test on UNIX, if tests are going to be run
        # Don't set it if we've requested a slow motion replay or we're trying to record a new usecase.
        return runsTests and os.name == "posix" and self.topLevel() and \
               not self.optionMap.has_key("actrep") and not self.isRecording()
    def setDiagEnvironment(self):
        if self.optionMap.has_key("trace"):
            self.setTraceDiagnostics()
        configFile = self.diagDict.get("configuration_file")
        if configFile and self.test.parent is None:
            self.diag.info("Adding definition file stem " + configFile)
            self.test.app.addConfigEntry("definition_file_stems", configFile)
        # Read the temporary diagnostics in the static GUI also
        if self.optionMap.has_key("diag") or self.optionMap.has_key("gx"):
            self.setTemporaryDiagnostics()
        elif self.diagDict.has_key("input_directory_variable"):
            self.setPermanentDiagnostics(configFile)
    def setTraceDiagnostics(self):
        if self.topLevel:
            envVarName = self.diagDict.get("trace_level_variable")
            self.diag.info("Setting " + envVarName + " to " + self.optionMap["trace"])
            self.test.setEnvironment(envVarName, self.optionMap["trace"])
    def setPermanentDiagnostics(self, configFile):
        diagConfigFile = self.test.getFileName(configFile)
        if diagConfigFile:
            inVarName = self.diagDict.get("input_directory_variable")
            self.addDiagVariable(inVarName, self.test.getDirectory())
        outVarName = self.diagDict.get("write_directory_variable")
        if outVarName and self.testCase():
            self.addDiagVariable(outVarName, self.test.getDirectory(temporary=1))
    def setTemporaryDiagnostics(self):
        if self.testCase():
            inVarName = self.diagDict.get("input_directory_variable")
            self.addDiagVariable(inVarName, os.path.join(self.test.getDirectory(temporary=0), "Diagnostics"))
            outVarName = self.diagDict.get("write_directory_variable")
            self.addDiagVariable(outVarName, os.path.join(self.test.getDirectory(temporary=1), "Diagnostics"))
            self.test.readSubDirectory("Diagnostics")
    def addDiagVariable(self, entryName, entry):
        # Diagnostics are usually controlled from the environment, but in Java they have to work with properties...
        if self.diagDict.has_key("properties_file"):
            propFile = self.diagDict["properties_file"]
            if not self.test.properties.has_key(propFile):
                self.test.properties.addEntry(propFile, {}, insert=1)
            self.test.properties.addEntry(entryName, entry.replace(os.sep, "/"), sectionName = propFile, insert=1)
        elif entryName:
            self.test.setEnvironment(entryName, entry)
    def setUseCaseEnvironment(self):
        # Here we assume the application uses either PyUseCase or JUseCase
        # PyUseCase reads environment variables, but you can't do that from java,
        # so we have a "properties file" set up as well. Do both always, to save forcing
        # apps to tell us which to do...
        if self.useJavaRecorder():
            self.test.properties.addEntry("jusecase", {}, insert=1)
        usecaseFile = self.findReplayUseCase()
        if usecaseFile:
            self.setReplay(usecaseFile)
        if self.usecaseFile or self.isRecording() or self.inputFile:
            # Re-record if recorded files are already present or recording explicitly requested
            self.setRecord(self.test.makeTmpFileName("usecase"), self.test.makeTmpFileName("input"))
    def isRecording(self):
        return self.optionMap.has_key("record")
    def findReplayUseCase(self):
        if self.isRecording():
            if os.environ.has_key("USECASE_REPLAY_SCRIPT"):
                # For self-testing, to allow us to record TextTest performing recording
                targetReplayFile = plugins.addLocalPrefix(os.getenv("USECASE_REPLAY_SCRIPT"), "target")
                if os.path.isfile(targetReplayFile):
                    return targetReplayFile
            else:
                # Don't replay when recording - let the user do it...
                return None
        else:
            return self.usecaseFile
    def useJavaRecorder(self):
        return self.test.getConfigValue("use_case_recorder") == "jusecase"
    def addJusecaseProperty(self, name, value):
        self.test.properties.addEntry(name, value, sectionName="jusecase", insert=1)
    def setReplay(self, replayScript):        
        if self.useJavaRecorder():
            self.addJusecaseProperty("replay", replayScript)
        else:
            self.test.setEnvironment("USECASE_REPLAY_SCRIPT", replayScript)
        if self.optionMap.has_key("actrep"):
            replaySpeed = self.test.getConfigValue("slow_motion_replay_speed")
            if self.useJavaRecorder():
                self.addJusecaseProperty("delay", str(replaySpeed))
            else:
                self.test.setEnvironment("USECASE_REPLAY_DELAY", str(replaySpeed))
    def setRecord(self, recordScript, recinpScript = None):
        self.diag.info("Enabling recording")
        if recordScript:
            if self.useJavaRecorder():
                self.addJusecaseProperty("record", recordScript)
            else:
                self.test.setEnvironment("USECASE_RECORD_SCRIPT", recordScript)
        if recinpScript:
            if self.useJavaRecorder():
                self.addJusecaseProperty("record_stdin", recinpScript)
            else:
                self.test.setEnvironment("USECASE_RECORD_STDIN", recinpScript)
    
class MakeWriteDirectory(plugins.Action):
    def __call__(self, test):
        test.makeWriteDirectories()
        test.grabWorkingDirectory()
    def __repr__(self):
        return "Make write directory for"
    def setUpApplication(self, app):
        app.makeWriteDirectory()

class PrepareWriteDirectory(plugins.Action):
    def __init__(self, ignoreCatalogues):
        self.diag = plugins.getDiagnostics("Prepare Writedir")
        self.ignoreCatalogues = ignoreCatalogues
        if self.ignoreCatalogues:
            self.diag.info("Ignoring all information in catalogue files")
    def __repr__(self):
        return "Prepare write directory for"
    def __call__(self, test):
        self.collatePaths(test, "copy_test_path", self.copyTestPath)
        self.collatePaths(test, "partial_copy_test_path", self.partialCopyTestPath)
        self.collatePaths(test, "link_test_path", self.linkTestPath)
        self.createPropertiesFiles(test)
    def collatePaths(self, test, configListName, collateMethod):
        for configName in test.getConfigValue(configListName, expandVars=False):
            self.collatePath(test, configName, collateMethod)
    def collatePath(self, test, configName, collateMethod):
        sourcePath = self.getSourcePath(test, configName)
        target = self.getTargetPath(test, configName)
        self.diag.info("Collating " + configName + " from " + repr(sourcePath) + "\nto " + repr(target))
        if sourcePath:
            self.collateExistingPath(test, sourcePath, target, collateMethod)
            
        envVarToSet = self.findEnvironmentVariable(test, configName)
        if envVarToSet:
            prevEnv = test.getEnvironment(envVarToSet)
            self.diag.info("Setting env. variable " + envVarToSet + " to " + target)
            test.setEnvironment(envVarToSet, target)
            if prevEnv:
                test.previousEnv[envVarToSet] = prevEnv
    def collateExistingPath(self, test, sourcePath, target, collateMethod):
        self.diag.info("Path for linking/copying at " + sourcePath)
        plugins.ensureDirExistsForFile(target)
        collateMethod(test, sourcePath, target)
    def getEnvironmentSourcePath(self, configName):
        pathName = self.getPathFromEnvironment(configName)
        if pathName != configName:
            return pathName
    def getPathFromEnvironment(self, configName):
        return os.path.normpath(os.path.expandvars(configName))
    def getTargetPath(self, test, configName):
        # handle environment variables
        localName = os.path.basename(self.getPathFromEnvironment(configName))
        return test.makeTmpFileName(localName, forComparison=0)
    def getSourcePath(self, test, configName):
        # These can refer to environment variables or to paths within the test structure
        fileName = self.getSourceFileName(configName)
        if not fileName or os.path.isabs(fileName):
            return fileName
        
        pathName = test.makePathName(fileName)
        if pathName:
            return pathName
        else:
            return self.getSourceFromSearchPath(test, fileName, configName)
    def getSourceFileName(self, configName):
        if configName.startswith("$"):
            return self.getEnvironmentSourcePath(configName)
        else:
            return configName
    def getSourceFromSearchPath(self, test, fileName, configName):
        self.diag.info("Searching for " + fileName + " in search path corresponding to " + configName)
        # Need to get both expanded and unexpanded varieties to be sure...
        searchPathDirs = test.getCompositeConfigValue("test_data_searchpath", configName) + \
                         test.getCompositeConfigValue("test_data_searchpath", fileName)
        for dir in searchPathDirs:
            fullPath = os.path.join(dir, fileName)
            self.diag.info("Trying " + fullPath)
            if os.path.exists(fullPath):
                self.diag.info("Found!")
                return fullPath
    def findEnvironmentVariable(self, test, configName):
        self.diag.info("Finding env. var name from " + configName)
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
            os.symlink(fullPath, target)
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
    def createPropertiesFiles(self, test):
        for var, value in test.properties.items():
            propFileName = test.makeTmpFileName(var + ".properties", forComparison=0)
            self.diag.info("Writing " + propFileName + " for " + var + " : " + repr(value))
            file = open(propFileName, "w")
            for subVar, subValue in value.items():
                # Don't write windows separators, they get confused with escape characters...
                file.write(subVar + " = " + subValue.replace(os.sep, "/") + "\n")
    
class CollateFiles(plugins.Action):
    def __init__(self):
        self.collations = {}
        self.discardFiles = []
        self.filesPresentBefore = {}
        self.diag = plugins.getDiagnostics("Collate Files")
    def setUpApplication(self, app):
        self.collations.update(app.getConfigValue("collate_file"))
        for key in self.collations.keys():
            if key.find(".") != -1:
                raise plugins.TextTestError, "Cannot collate files to stem '" + key + "' - '.' characters are not allowed"
        self.discardFiles = app.getConfigValue("discard_file")
        self.collateScripts = app.getConfigValue("collate_script")
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

            # add each file to newColl using suffix from sourcePtn
            for aFile in self.getFilesFromExpansions(test, targetStem, sourcePattern):
                fullStem = os.path.splitext(aFile)[0]
                newTargetStem = os.path.basename(fullStem).replace(".", "_")
                if not newTargetStem in newColl:
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
        test.grabWorkingDirectory()
        self.diag.info("Adding files for source pattern " + sourcePattern)
        sourceFiles = glob.glob(sourcePattern)
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
            if os.path.isfile(filePath):
                os.remove(filePath)
    def collate(self, test):
	testCollations = self.expandCollations(test, self.collations)
        for targetStem, sourcePattern in testCollations.items():
            targetFile = test.makeTmpFileName(targetStem)
            collationErrFile = test.makeTmpFileName(targetStem + ".collate_errs", forFramework=1)
            for fullpath in self.findPaths(test, sourcePattern):
                if self.testEdited(test, fullpath):
                    self.diag.info("Extracting " + fullpath + " to " + targetFile)
                    self.extract(fullpath, targetFile, collationErrFile)
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
        return filter(os.path.isfile, paths)
    def findExtractionScript(self, sourceFile, targetFile):
        stem = os.path.splitext(os.path.basename(targetFile))[0]
        script = self.collateScripts.get(stem)
        if script:
            return script
        elif os.name == "posix":
            from unixonly import isCompressed
            if isCompressed(sourceFile):
                return "zcat"
    def extract(self, sourceFile, targetFile, collationErrFile):
        extractionScript = self.findExtractionScript(sourceFile, targetFile)
        if extractionScript:
            os.system(extractionScript + " " + sourceFile + " > " + targetFile + " 2> " + collationErrFile)
        else:
            shutil.copyfile(sourceFile, targetFile)
    
class TextFilter(plugins.Filter):
    def __init__(self, filterText):
        self.texts = plugins.commasplit(filterText)
        self.textTriggers = [ plugins.TextTrigger(text) for text in self.texts ]
    def containsText(self, test):
        return self.stringContainsText(test.name)
    def stringContainsText(self, searchString):
        for trigger in self.textTriggers:
            if trigger.matches(searchString):
                return True
        return False
    def equalsText(self, test):
        return test.name in self.texts

class TestPathFilter(TextFilter):
    option = "tp"
    def acceptsTestCase(self, test):
        return test.getRelPath() in self.texts
    def acceptsTestSuite(self, suite):
        for relPath in self.texts:
            if relPath.startswith(suite.getRelPath()):
                return True
        return False
    
class TestNameFilter(TextFilter):
    option = "t"
    def acceptsTestCase(self, test):
        return self.containsText(test)

class TestSuiteFilter(TextFilter):
    option = "ts"
    def acceptsTestCase(self, test):
        return self.stringContainsText(test.parent.getRelPath())
    def acceptsTestSuiteContents(self, suite):
        return not suite.isEmpty()

class GrepFilter(TextFilter):
    def __init__(self, filterText, fileStem):
        TextFilter.__init__(self, filterText)
        self.fileStem = fileStem
    def acceptsTestCase(self, test):
        logFile = test.getFileName(self.fileStem)
        if not logFile:
            return False
        for line in open(logFile).xreadlines():
            if self.stringContainsText(line):
                return True
        return False

# Dummy class to signify failure...
class RejectFilter(plugins.Filter):
    def acceptsTestCase(self, test):
        return False
    def acceptsTestSuite(self, suite):
        return False
    def acceptsTestSuiteContents(self, suite):
        return False
    def acceptsApplication(self, app):
        return False

# Workaround for python bug 853411: tell main thread to start the process
# if we aren't it...
class Pending(plugins.TestState):
    def __init__(self, process, execHosts):
        plugins.TestState.__init__(self, "pending", executionHosts=execHosts, lifecycleChange="become pending")
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
        self.shellTitle = None
        self.holdShell = False
    def __repr__(self):
        return "Running"
    def __call__(self, test, inChild=0):
        # Change to the directory so any incidental files can be found easily
        test.grabWorkingDirectory()
        return self.runTest(test, inChild)
    def changeToRunningState(self, test, process):
        execMachines = test.state.executionHosts
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

        self.diag.info("Running test with command : " + testCommand)
        process = plugins.BackgroundProcess(testCommand, testRun=1, shellTitle=self.shellTitle, holdShell=self.holdShell)
        # Working around Python bug
        test.changeState(Pending(process, test.state.executionHosts))
        self.diag.info("Waiting for process start...")
        process.waitForStart()
        if not inChild:
            self.changeToRunningState(test, process)
        return self.RETRY
    def getOptions(self, test):
        optionsFile = test.getFileName("options")
        if optionsFile:
            return " " + os.path.expandvars(open(optionsFile).read().strip())
        else:
            return ""
    def getExecuteCommand(self, test):
        testCommand = test.getConfigValue("binary")
        interpreter = test.getConfigValue("interpreter")
        if interpreter:
            testCommand = interpreter + " " + testCommand
        testCommand += self.getOptions(test)
        if self.shellTitle:
            if os.environ.has_key("USECASE_REPLAY_SCRIPT"):
                # self-testing... rather cheating really...
                dir, file = os.path.split(os.environ["USECASE_REPLAY_SCRIPT"])
                stem, ext = file.split(".", 1)
                testCommand += " < " + os.path.join(dir, "target_input." + ext)
            # Replaying in a shell, need everything visible...
            return testCommand
        testCommand += " < " + self.getInputFile(test)
        outfile = test.makeTmpFileName("output")
        testCommand += " > " + outfile
        errfile = test.makeTmpFileName("errors")
        return self.getStdErrRedirect(testCommand, errfile)
    def getStdErrRedirect(self, command, file):
        return command + " 2> " + file
    def getInputFile(self, test):
        inputFileName = test.getFileName("input")
        if inputFileName:
            return inputFileName
        if os.name == "posix":
            return "/dev/null"
        else:
            return "nul"
    def getInterruptActions(self, fetchResults):
        return [ KillTest() ]
    def setUpSuite(self, suite):
        self.describe(suite)
    def setUpApplication(self, app):
        app.checkBinaryExists()
        if app.inputOptions.has_key("record"):
            recordMode = app.getConfigValue("use_case_record_mode")
            if recordMode == "console":
                self.shellTitle = "Running " + app.fullName + " in order to capture user actions..."
                self.holdShell = app.inputOptions.has_key("holdshell")

class Killed(plugins.TestState):
    def __init__(self, briefText, freeText, prevState):
        plugins.TestState.__init__(self, "killed", briefText=briefText, freeText=freeText, \
                                   started=1, executionHosts=prevState.executionHosts)
        # Cache running information, it can be useful to have this available...
        self.prevState = prevState
    def getProcessCpuTime(self):
        # for Windows
        return self.prevState.getProcessCpuTime()

class KillTest(plugins.Action):
    def __call__(self, test):
        if not test.state.hasStarted():
            raise plugins.TextTestError, "Termination already in progress before test started."
        
        test.state.killProcess()
        briefText, fullText = self.getKillInfo(test)
        freeText = "Test " + fullText + "\n"
        newState = Killed(briefText, freeText, test.state)
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
                processId = int(parts[-1])
                process = plugins.Process(processId)
                self.diag.info("Found process ID " + str(processId))
                if not process.hasTerminated():
                    process.killAll()
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
                # Allow one second error margin, seems necessary on Windows...
                return newInfo - oldInfo > 1
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
        if path.startswith(writeDir):
            return path.replace(writeDir, "<Test Directory>")
        else:
            return path
                    
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

class ReconnectTest(plugins.Action):
    def __init__(self, reconnectTmpInfo, fullRecalculate):
        self.reconnectTmpInfo = reconnectTmpInfo
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
            test.setWriteDirectory(reconnLocation)
    def copyFiles(self, reconnLocation, test):
        if not self.canReconnectTo(reconnLocation):
            return

        test.makeWriteDirectories()
        for file in os.listdir(reconnLocation):
            fullPath = os.path.join(reconnLocation, file)
            self.copyFile(fullPath, test.makeTmpFileName(file, forComparison=0))

        testStateFile = os.path.join(reconnLocation, "framework_tmp", "teststate")
        self.copyFile(testStateFile, test.getStateFile())
    def copyFile(self, sourcePath, targetPath):
        if os.path.isfile(sourcePath):
            shutil.copyfile(sourcePath, targetPath)
    def loadStoredState(self, test):
        loaded, newState = test.getStoredStateInfo()
        if self.fullRecalculate:
            if not loaded and self.hasFiles(test):
                # If the teststate file isn't there or we can't read it, ignore it and recompute, provided
                # we have some files to do so with...
                return self.describe(test)
            # Only pick up errors here, recalculate the rest. Don't notify until
            # we're done with recalculation.
            if not newState.hasResults():
                # Don't generate a view of the pre-calculated changes, we're trying again...
                newState.lifecycleChange = ""
                test.changeState(newState)
            else:
                # Also pick up execution machines, we can't get them otherwise...
                test.state.executionHosts = newState.executionHosts
        else:
            test.changeState(newState)

        # State will refer to TEXTTEST_HOME in the original (which we may not have now,
        # and certainly don't want to save), try to fix this...
        test.state.updatePaths(test.app.getDirectory(), self.rootDirToCopy)
        self.describe(test, " (state " + test.state.category + ")")
    def hasFiles(self, test):
        dir = test.getDirectory(temporary=1)
        if not os.path.isdir(dir):
            return False
        for file in os.listdir(dir):
            fullPath = os.path.join(dir, file)
            if os.path.isfile(fullPath):
                return True
        return False
    def canReconnectTo(self, dir):
        # If the directory does not exist or is empty, we cannot reconnect to it.
        return os.path.exists(dir) and len(os.listdir(dir)) > 0
    def setUpApplication(self, app):
        fetchDir = app.getPreviousWriteDirInfo(self.reconnectTmpInfo)
        self.rootDirToCopy = self.findReconnDirectory(fetchDir, app)
        if not self.rootDirToCopy:
            raise plugins.TextTestError, "Could not find any runs matching " + app.name + app.versionSuffix() + " under " + fetchDir

        print "Reconnecting to test results in directory", self.rootDirToCopy
        if not self.fullRecalculate:
            app.writeDirectory = self.rootDirToCopy
    def findReconnDirectory(self, fetchDir, app):
        self.diag.info("Looking for reconnection in " + fetchDir)
        return app.getFileName([ fetchDir ], app.name, self.getVersionList)
    def getVersionList(self, fileName, stem):
        # Show the framework how to find the version list given a file name
        # If it doesn't match, return None
        parts = fileName.split(".")
        if len(parts) < 2 or stem != parts[0]:
            return
        # drop the application at the start and the date/time at the end
        return parts[1:-1]
    def setUpSuite(self, suite):
        self.describe(suite)

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
        return "Max " + string.capitalize(fileStem) + "  :      " + str(roundedMaxVal) + " MB"
    def makeTimeLine(self, values, fileStem):
        sum = 0.0
        for value in values:
            sum += value
        roundedSum = float(int(10*sum))/10
        return "Total " + string.capitalize(fileStem) + "  :      " + str(roundedSum) + " seconds"
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
    scriptDoc = "update the standard performance files from the standard log files"
    def __init__(self):
        ExtractPerformanceFiles.__init__(self, MachineInfoFinder())
    def __repr__(self):
        return "Extracting standard performance for"
    def __call__(self, test):
        self.describe(test)
        ExtractPerformanceFiles.__call__(self, test)
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
                self.display("-" + key, self.groupOutput(group), group.switches[key].description())
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
        entries = app.configDir.keys()
        entries.sort()
        for key in entries:
            docOutput = app.configDocs[key]
            if not docOutput.startswith("Private"):
                value = app.configDir[key]
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
        self.oldText = argDict["old"]
        self.newText = argDict["new"].replace("\\n", "\n")
        self.logFile = None
        if argDict.has_key("file"):
            self.logFile = argDict["file"]
        self.textDiffTool = None
    def __repr__(self):
        return "Replacing " + self.oldText + " with " + self.newText + " for"
    def __call__(self, test):
        logFile = test.getFileName(self.logFile)
        if not logFile:
            return
        self.describe(test)
        sys.stdout.flush()
        newLogFile = logFile + "_new"
        writeFile = open(newLogFile, "w")
        for line in open(logFile).xreadlines():
            writeFile.write(line.replace(self.oldText, self.newText))
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
