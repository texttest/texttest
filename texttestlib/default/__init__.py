""" The default configuration, from which all others should be derived """

import os
import subprocess
import operator
import logging
import texttestlib.default.sandbox
import texttestlib.default.console
import texttestlib.default.rundependent
import texttestlib.default.comparetest
import texttestlib.default.batch
import texttestlib.default.performance
from .. import plugins
from copy import copy
from string import Template
from fnmatch import fnmatch
from threading import Thread
from locale import getpreferredencoding
# For back-compatibility
from .runtest import RunTest, Running, Killed
from .batch.externalreport import ExternalFormatResponder, ExternalFormatCollector
from .database_data import SaveDatabase
from .scripts import *
from functools import reduce
from configparser import ConfigParser


def getConfig(optionMap):
    return Config(optionMap)


class Config:
    loggingSetup = False
    removePreviousThread = None

    def __init__(self, optionMap):
        self.optionMap = optionMap
        self.filterFileMap = {}
        if self.hasExplicitInterface():
            self.trySetUpLogging()
        from .reconnect import ReconnectConfig
        self.reconnectConfig = ReconnectConfig(optionMap)

    def getMachineNameForDisplay(self, machine):
        return machine  # override for queuesystems

    def getCheckoutLabel(self):
        return "Use checkout"

    def getMachineLabel(self):
        return "Run on machine"

    def addCheckoutOptions(self, group, checkout):
        return group.addOption("c", self.getCheckoutLabel(), checkout)

    def addToOptionGroups(self, apps, groups):
        recordsUseCases = len(apps) == 0 or self.anyAppHas(
            apps, lambda app: app.getConfigValue("use_case_record_mode") != "disabled")
        useCatalogues = self.anyAppHas(apps, self.isolatesDataUsingCatalogues)
        useCaptureMock = self.anyAppHas(apps, self.usesCaptureMock)
        for group in groups:
            if group.name.startswith("Select"):
                group.addOption("t", "Test names containing",
                                description="Select tests for which the name contains the entered text. The text can be a regular expression.")
                group.addOption("ts", "Test paths containing", description="Select tests for which the full path to the test (e.g. suite1/subsuite/testname) contains the entered text. The text can be a regular expression. You can select tests by suite name this way.")
                possibleDirs = self.getFilterFileDirectories(apps, useOwnTmpDir=True)
                group.addOption("f", "Tests listed in file", possibleDirs=possibleDirs, selectFile=True)
                group.addOption("desc", "Descriptions containing",
                                description="Select tests for which the description (comment) matches the entered text. The text can be a regular expression.")
                if self.anyAppHas(apps, self.hasPerformance):
                    group.addOption("r", "Execution time", description="Specify execution time limits, either as '<min>,<max>', or as a list of comma-separated expressions, such as >=0:45,<=1:00. Digit-only numbers are interpreted as minutes, while colon-separated numbers are interpreted as hours:minutes:seconds.")
                group.addOption("grep", "Test-files containing",
                                description="Select tests which have a file containing the entered text. The text can be a regular expression : e.g. enter '.*' to only look for the file without checking the contents.")
                group.addOption("grepfile", "Test-file to search", allocateNofValues=2,
                                description="When the 'test-files containing' field is non-empty, apply the search in files with the given stem. Unix-style file expansion (note not regular expressions) may be used. For example '*' will look in any file.")
            elif group.name.startswith("Basic"):
                if len(apps) > 0:
                    version = plugins.getAggregateString(apps, lambda app: app.getFullVersion())
                    checkout = plugins.getAggregateString(apps, lambda app: app.getCheckoutForDisplay())
                    machine = plugins.getAggregateString(apps, lambda app: app.getRunMachine())
                else:
                    version, checkout, machine = "", "", ""
                group.addOption("v", "Run this version", version)
                self.addCheckoutOptions(group, checkout)
                group.addOption("m", self.getMachineLabel(), self.getMachineNameForDisplay(machine))
                group.addOption("cp", "Times to run", 1, minimum=1, maximum=10000,
                                description="Set this to some number larger than 1 to run the same test multiple times, for example to try to catch indeterminism in the system under test")
                if recordsUseCases:
                    group.addOption("delay", "Replay pause (sec)", 0.0,
                                    description="How long to wait, in seconds, between replaying each GUI action in the usecase file")
                    self.addDefaultSwitch(group, "gui", "Show GUI and record any extra actions",
                                          description="Disable virtual display usage if any. Replay whatever is in the usecase file and enabled recording when done")
                    self.addDefaultSwitch(group, "screenshot", "Generate a screenshot after each replayed action",
                                          description="The screenshots can be viewed via the 'View Screenshots' action in the test (left panel) context menu")
                self.addDefaultSwitch(group, "stop", "Stop after first failure")
                if useCatalogues:
                    self.addDefaultSwitch(group, "ignorecat", "Ignore catalogue file when isolating data", description="Treat test data identified by 'partial_copy_test_path' as if it were in 'copy_test_path', " +
                                          "i.e. copy everything without taking notice of the catalogue file. Useful when many things have changed with the files written by the test")
                
                db_pathnames = set()
                for app in apps:
                    for pathName, dirName in app.getConfigValue("dbtext_database_path").items():
                        if not dirName:
                            continue
                        if pathName not in db_pathnames:
                            postfix = " (" + pathName + ")" if pathName != "default" else ""
                            group.addSwitch("dbtext-setup-" + pathName.lower(), "Database setup run" + postfix, description="Set up the " + pathName + " database: save all changes after this run")
                        db_pathnames.add(pathName)

                if useCaptureMock:
                    hasClientServer = self.anyAppHas(apps, self.captureMockHasClientServer)
                    self.addCaptureMockSwitch(group, hasClientServer=hasClientServer)
            elif group.name.startswith("Advanced"):
                self.addDefaultOption(group, "b", "Run batch mode session")
                self.addDefaultOption(group, "name", "Name this run")
                group.addOption("vanilla", "Ignore configuration files", self.defaultVanillaValue(),
                                possibleValues=["", "site", "personal", "all"])
                self.addDefaultSwitch(group, "keeptmp", "Keep temporary write-directories")
                group.addSwitch("ignorefilters", "Ignore all run-dependent text filtering")
            elif group.name.startswith("Self-diagnostics"):
                self.addDefaultSwitch(group, "x", "Enable self-diagnostics")
                defaultDiagDir = plugins.getPersonalDir("log")
                group.addOption("xr", "Configure self-diagnostics from", os.path.join(defaultDiagDir, "logging.debug"),
                                possibleValues=[os.path.join(plugins.installationDir("log"), "logging.debug")])
                group.addOption("xw", "Write self-diagnostics to", defaultDiagDir)
            elif group.name.startswith("Invisible"):
                # Options that don't make sense with the GUI should be invisible there...
                group.addOption("a", "Load test applications named")
                group.addOption("s", "Run this script")
                group.addOption("d", "Look for test files under")
                group.addSwitch("help", "Print configuration help text on stdout")
                group.addSwitch("g", "use dynamic GUI")
                group.addSwitch("gx", "use static GUI")
                group.addSwitch("con", "use console interface")
                group.addSwitch("coll", "Collect results for batch mode session")
                group.addSwitch(
                    "collarchive", "Collect results for batch mode session using data in the archive, back to the given date")
                group.addSwitch("manualarchive", "Disable the automatic archiving of unused repository files")
                group.addOption("tp", "Private: Tests with exact path")  # use for internal communication
                group.addOption("finverse", "Tests not listed in file")
                group.addOption("fintersect", "Tests in all files")
                group.addOption("funion", "Tests in any of files")
                group.addOption("fd", "Private: Directory to search for filter files in")
                group.addOption("td", "Private: Directory to search for temporary settings in")
                group.addOption("count", "Private: How many tests we believe there will be")
                group.addOption("o", "Overwrite failures, optionally using version")
                group.addOption("reconnect", "Reconnect to previous run")
                group.addSwitch("reconnfull", "Recompute file filters when reconnecting",
                                options=self.getReconnFullOptions())
                group.addSwitch("n", "Create new results files (overwrite everything)")
                group.addSwitch("new", "Start static GUI with no applications loaded")
                group.addOption("bx", "Select tests exactly as for batch mode session")
                group.addOption("rerun", "Private: Rerun number, used to flag GUI reruns")
                group.addSwitch("zen", "Make console output coloured, for use e.g. with ZenTest")
                if recordsUseCases:
                    group.addSwitch("record", "Private: Record usecase rather than replay what is present")
                    group.addSwitch("autoreplay", "Private: Used to flag that the run has been autogenerated")
                else:
                    # We may have other apps that do this, don't reject these options
                    group.addOption("delay", "Replay pause (sec)", 0)
                    group.addSwitch("gui", "Show GUI and record any extra actions")
                    group.addSwitch("screenshot", "Generate a screenshot after each replayed action")

                if not useCatalogues:
                    group.addSwitch("ignorecat", "Ignore catalogue file when isolating data")
                if not useCaptureMock:
                    self.addCaptureMockSwitch(group)

    def addDefaultSwitch(self, group, key, name, *args, **kw):
        group.addSwitch(key, name, self.optionIntValue(key), *args, **kw)

    def addDefaultOption(self, group, key, name, *args, **kw):
        group.addOption(key, name, self.optionValue(key), *args, **kw)

    def addCaptureMockSwitch(self, group, value=0, hasClientServer=False):
        options = ["Replay", "Record", "Mixed Mode", "Disabled"]
        descriptions = ["Replay all existing interactions from the information in CaptureMock's mock files. Do not record anything new.",
                        "Ignore any existing CaptureMock files and record all the interactions afresh.",
                        "Replay all existing interactions from the information in the CaptureMock mock files. " +
                        "Record any other interactions that occur.",
                        "Disable CaptureMock"]
        if hasClientServer:
            # "Mixed mode" makes no sense here, so remove it
            options.pop(2)
            descriptions.pop(2)
        group.addSwitch("rectraffic", "CaptureMock", value=value, options=options, description=descriptions)

    def getReconnFullOptions(self):
        return ["Display results exactly as they were in the original run",
                "Use raw data from the original run, but recompute run-dependent text, known bug information etc."]

    def anyAppHas(self, apps, propertyMethod):
        for app in apps:
            for partApp in [app] + app.extras:
                if propertyMethod(partApp):
                    return True
        return False

    def defaultVanillaValue(self):
        if "vanilla" not in self.optionMap:
            return ""
        given = self.optionValue("vanilla")
        return given or "all"

    def getRunningGroupNames(self, *args):
        return [("Basic", None, None), ("Self-diagnostics (internal logging)", "x", 0), ("Advanced", None, None)]

    def getAllRunningGroupNames(self, allApps):
        if len(allApps) == 0:
            return self.getRunningGroupNames(None)

        names = []
        for app in allApps:
            for name in app.getRunningGroupNames():
                if name not in names:
                    names.append(name)
        return names

    def createOptionGroups(self, allApps):
        groupNames = ["Selection", "Invisible"] + [x[0] for x in self.getAllRunningGroupNames(allApps)]
        optionGroups = list(map(plugins.OptionGroup, groupNames))
        self.addToOptionGroups(allApps, optionGroups)
        return optionGroups

    def findAllValidOptions(self, allApps):
        groups = self.createOptionGroups(allApps)
        return reduce(operator.add, (list(g.keys()) for g in groups), [])

    def getActionSequence(self, app):
        if "coll" in self.optionMap:
            return []

        if self.isReconnecting():
            return self.getReconnectSequence()

        scriptObject = self.optionMap.getScriptObject()
        if scriptObject:
            if self.usesComparator(scriptObject):
                comparator = comparetest.MakeComparisons(ignoreMissing=True, enableColor="zen" in self.optionMap,
                                                         compareSuites=scriptObject.comparesSuites(app))
                return [self.getWriteDirectoryMaker(), rundependent.FilterOriginalForScript(), scriptObject, comparator]
            else:
                return [scriptObject]
        else:
            return self.getTestProcessor(app)

    def usesComparator(self, scriptObject):
        try:
            return scriptObject.usesComparator()
        except AttributeError:
            return False

    def useGUI(self):
        return "g" in self.optionMap or "gx" in self.optionMap

    def useStaticGUI(self, app):
        return "gx" in self.optionMap or \
               (not self.hasExplicitInterface() and app.getConfigValue("default_interface") == "static_gui")

    def useConsole(self):
        return "con" in self.optionMap

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
            checkoutVersions, _ = self.getCheckoutExtraVersions(app)
            # Generated automatically to be able to distinguish, don't save them
            for ver in copyVersions + checkoutVersions:
                app.addConfigEntry("unsaveable_version", ver)
            return self.createComposites(checkoutVersions, copyVersions)

    def getCopyExtraVersions(self):
        copyCount = self.optionIntValue("cp", 1)
        return ["copy_" + str(i) for i in range(1, copyCount)]

    def makeParts(self, c):
        return c.replace("\\", "/").split("/")

    def versionNameFromCheckout(self, c, checkoutNames):
        checkoutParts = self.makeParts(c)
        for other in checkoutNames:
            if other != c:
                for otherPart in self.makeParts(other):
                    if otherPart in checkoutParts:
                        checkoutParts.remove(otherPart)

        return checkoutParts[-1].replace(".", "_")

    def getCheckoutExtraVersions(self, app):
        checkoutNames = plugins.commasplit(self.optionValue("c"))
        if len(checkoutNames) > 1:
            expandedNames = [self.expandCheckout(c, app) for c in checkoutNames]
            extraCheckouts = expandedNames[1:]
            return [self.versionNameFromCheckout(c, expandedNames) for c in extraCheckouts], extraCheckouts
        else:
            return [], []

    def getBatchSession(self, app):
        return self.optionValue("b")

    def getBatchSessionForSelect(self, app):
        return self.getBatchSession(app) or self.optionMap.get("bx")

    def getExtraVersionsFromConfig(self, app):
        basic = app.getConfigValue("extra_version")
        batchSession = self.getBatchSessionForSelect(app)
        if batchSession is not None:
            for batchExtra in app.getCompositeConfigValue("batch_extra_version", batchSession):
                if batchExtra not in basic:
                    basic.append(batchExtra)
        if "count" in self.optionMap:
            return []  # dynamic GUI started from static GUI, rely on it telling us what to load
        for extra in basic:
            if extra in app.versions:
                return []
        return basic

    def getDefaultInterface(self, allApps):
        if self.runningScript():
            return "console"
        elif len(allApps) == 0 or "new" in self.optionMap:
            return "static_gui"

        defaultIntf = None
        for app in allApps:
            appIntf = app.getConfigValue("default_interface")
            if defaultIntf and appIntf != defaultIntf:
                raise plugins.TextTestError("Conflicting default interfaces for different applications - " +
                                            appIntf + " and " + defaultIntf)
            defaultIntf = appIntf
        return defaultIntf

    def setDefaultInterface(self, allApps):
        mapping = {"static_gui": "gx", "dynamic_gui": "g", "console": "con"}
        defaultInterface = self.getDefaultInterface(allApps)
        if defaultInterface in mapping:
            self.optionMap[mapping[defaultInterface]] = ""
        else:
            raise plugins.TextTestError("Invalid value for default_interface '" + defaultInterface + "'")

    def hasExplicitInterface(self):
        return self.useGUI() or self.batchMode() or self.useConsole() or "o" in self.optionMap

    def getLogfilePostfixes(self):
        if "x" in self.optionMap:
            return ["debug"]
        elif "gx" in self.optionMap:
            return ["gui", "static_gui"]
        elif "g" in self.optionMap:
            return ["gui", "dynamic_gui"]
        elif self.batchMode():
            return ["console", "batch"]
        else:
            return ["console"]

    def trySetUpLogging(self):
        if not self.loggingSetup:
            self.setUpLogging()
            Config.loggingSetup = True

    def setUpLogging(self):
        # Can cause deadlock problems with subprocess module and CaptureMock. Not useful in TextTest, simplify logging usage.
        logging.logProcesses = 0
        filePatterns = ["logging." + postfix for postfix in self.getLogfilePostfixes()]
        includeSite, includePersonal = self.optionMap.configPathOptions()
        allPaths = plugins.findDataPaths(filePatterns, includeSite, includePersonal, dataDirName="log")
        if len(allPaths) > 0:
            plugins.configureLogging(allPaths[-1])  # Won't have any effect if we've already got a log file
        else:
            plugins.configureLogging()

    def getResponderClasses(self, allApps):
        # Global side effects first :)
        if not self.hasExplicitInterface():
            self.setDefaultInterface(allApps)
            self.trySetUpLogging()

        return self._getResponderClasses(allApps)

    def _getResponderClasses(self, allApps):
        classes = []
        if "gx" not in self.optionMap:
            if "new" in self.optionMap:
                raise plugins.TextTestError("'--new' option can only be provided with the static GUI")
            elif len(allApps) == 0:
                raise plugins.TextTestError(
                    "Could not find any matching applications (files of the form config.<app>) under " + " or ".join(self.optionMap.rootDirectories))

        if any(self.useStaticGUI(app) for app in allApps) and self.isReconnecting():
            raise plugins.TextTestError("'-reconnect' option doesn't work with static GUI")

        if self.useGUI():
            self.addGuiResponder(classes)
        else:
            classes.append(self.getTextDisplayResponderClass())

        if "gx" not in self.optionMap:
            classes += self.getThreadActionClasses()

        if self.batchMode() and not self.runningScript():
            if "coll" in self.optionMap:
                arg = self.optionMap["coll"]
                if arg != "mail":
                    classes.append(self.getWebPageResponder())
                if not arg or "web" not in arg:
                    classes.append(batch.CollectFilesResponder)
                if self.anyAppHas(allApps, lambda app: self.getBatchConfigValue(app, "batch_external_format") in ["trx", "jetbrains"]):
                    classes.append(ExternalFormatCollector)
            else:
                if self.optionValue("b") is None:
                    plugins.log.info("No batch session identifier provided, using 'default'")
                    self.optionMap["b"] = "default"
                if self.anyAppHas(allApps, lambda app: self.emailEnabled(app)):
                    classes.append(batch.EmailResponder)
                if self.anyAppHas(allApps, lambda app: self.getBatchConfigValue(app, "batch_external_format") != "false"):
                    classes.append(ExternalFormatResponder)

        if os.name == "posix" and self.useVirtualDisplay():
            from .virtualdisplay import VirtualDisplayResponder
            classes.append(VirtualDisplayResponder)
        stateSaver = self.getStateSaver()
        if stateSaver is not None:
            classes.append(stateSaver)
        if not self.useGUI() and not self.batchMode():
            classes.append(self.getTextResponder())
        # At the end, so we've done the processing before we proceed
        from .storytext_interface import ApplicationEventResponder
        classes.append(ApplicationEventResponder)
        return classes

    def emailEnabled(self, app):
        return self.getBatchConfigValue(app, "batch_recipients") or \
            self.getBatchConfigValue(app, "batch_use_collection") == "true"

    def getBatchConfigValue(self, app, configName, **kw):
        return app.getCompositeConfigValue(configName, self.getBatchSession(app), **kw)

    def isActionReplay(self):
        for option, _ in self.getInteractiveReplayOptions():
            if option in self.optionMap:
                return True
        return False

    def getTestRunVariables(self):
        return []

    def noFileAdvice(self):
        # What can we suggest if files aren't present? In this case, not much
        return ""

    def useVirtualDisplay(self):
        # Don't try to set it if we're using the static GUI or
        # we've requested a slow motion replay or we're trying to record a new usecase.
        return not self.isRecording() and "gx" not in self.optionMap and not self.isReconnecting() and \
            not self.isActionReplay() and "coll" not in self.optionMap and not self.optionMap.runScript()

    def getThreadActionClasses(self):
        from .actionrunner import ActionRunner
        return [ActionRunner]

    def getTextDisplayResponderClass(self):
        return console.TextDisplayResponder

    def isolatesDataUsingCatalogues(self, app):
        return app.getConfigValue("create_catalogues") == "true" and \
            len(app.getConfigValue("partial_copy_test_path")) > 0

    def usesCaptureMock(self, app):
        return "traffic" in app.defFileStems()
    
    def captureMockHasClientServer(self, app):
        rcFile = os.path.join(app.getDirectory(), "capturemockrc." + app.name)
        return self.clientServerEnabled([ rcFile ]) if rcFile and os.path.isfile(rcFile) else False
         
    def clientServerEnabled(self, rcFiles):
        # check for server_protocol being explicitly set
        parser = ConfigParser(strict=False)
        parser.read(rcFiles)
        return parser.has_section("general") and parser.has_option("general", "server_protocol")

    def hasWritePermission(self, path):
        if os.path.isdir(path):
            return os.access(path, os.W_OK)
        else:
            return self.hasWritePermission(os.path.dirname(path))

    def getWriteDirectories(self, app):
        rootDir = self.optionMap.setPathFromOptionsOrEnv("TEXTTEST_TMP", app.getConfigValue("default_texttest_tmp"))  # Location of temporary files from test runs
        if not os.path.isdir(rootDir) and not self.hasWritePermission(os.path.dirname(rootDir)):
            rootDir = self.optionMap.setPathFromOptionsOrEnv("", "$TEXTTEST_PERSONAL_CONFIG/tmp")
        writeDir = os.path.join(rootDir, self.getWriteDirectoryName(app))
        localRootDir = self.optionMap.getPathFromOptionsOrEnv("TEXTTEST_LOCAL_TMP", app.getConfigValue("default_texttest_local_tmp")) # Location of temporary files on local disk from test runs. Defaults to value of TEXTTEST_TMP
        if localRootDir:
            return writeDir, os.path.join(localRootDir, self.getLocalWriteDirectoryName(app))
        else:
            return writeDir, writeDir

    def getWriteDirectoryName(self, app):
        appDescriptor = self.getAppDescriptor()
        parts = self.getBasicRunDescriptors(app, appDescriptor) + self.getVersionDescriptors(appDescriptor) + \
            [self.getTimeDescriptor(), str(os.getpid())]
        return ".".join(parts)

    def getLocalWriteDirectoryName(self, app):
        return self.getWriteDirectoryName(app)

    def getBasicRunDescriptors(self, app, appDescriptor):
        appDescriptors = [appDescriptor] if appDescriptor else []
        if self.useStaticGUI(app):
            return ["static_gui"] + appDescriptors
        elif appDescriptors:
            return appDescriptors
        elif self.getBatchSession(app):
            return [self.getBatchSession(app)]
        elif "g" in self.optionMap:
            return ["dynamic_gui"]
        else:
            return ["console"]

    def getTimeDescriptor(self):
        timeStr = self.optionMap.get("rerun", plugins.startTimeString())
        return timeStr.replace(":", "").replace(" ", "_")

    def getAppDescriptor(self):
        givenAppDescriptor = self.optionValue("a")
        if givenAppDescriptor and "," not in givenAppDescriptor:
            return givenAppDescriptor

    def getVersionDescriptors(self, appDescriptor):
        givenVersion = self.optionValue("v")
        if givenVersion:
            # Commas in path names are a bit dangerous, some applications may have arguments like
            # -path path1,path2 and just do split on the path argument.
            # We try something more obscure instead...
            versionList = plugins.commasplit(givenVersion)
            if appDescriptor:
                parts = appDescriptor.split(".", 1)
                if len(parts) > 1:
                    versionList = self.filterForApp(versionList, parts[1])
            return ["++".join(versionList)] if versionList else []
        else:
            return []

    def filterForApp(self, versionList, appVersionDescriptor):
        filteredVersions = []
        for version in versionList:
            if version != appVersionDescriptor:
                filteredVersions.append(version.replace(appVersionDescriptor + ".", ""))
        return filteredVersions

    def addGuiResponder(self, classes):
        from .gtkgui.controller import GUIController
        classes.append(GUIController)

    def getReconnectSequence(self):
        actions = [self.reconnectConfig.getReconnectAction()]
        actions += [self.getOriginalFilterer(), self.getTemporaryFilterer(),
                    self.getTestComparator(), self.getFailureExplainer()]
        return actions

    def getOriginalFilterer(self):
        if "ignorefilters" not in self.optionMap:
            return rundependent.FilterOriginal(useFilteringStates=not self.batchMode())

    def getTemporaryFilterer(self):
        if "ignorefilters" not in self.optionMap:
            return rundependent.FilterTemporary(useFilteringStates=not self.batchMode())

    def filterErrorText(self, app, errFile):
        filterAction = rundependent.FilterErrorText()
        return filterAction.getFilteredText(app, errFile, app)

    def getFileNameVersionApp(self, test, fileName):
        fileVersions = set(os.path.basename(fileName).split(".")[1:])
        testVersions = set(test.app.versions + [test.app.name])
        additionalVersions = fileVersions.difference(testVersions)
        version = ".".join(additionalVersions)
        return test.getAppForVersion(version)

    def applyFiltering(self, test, fileName):
        app = self.getFileNameVersionApp(test, fileName)
        filterAction = rundependent.FilterAction()
        return filterAction.getFilteredText(test, fileName, app)

    def getAllFilters(self, test, fileName):
        app = self.getFileNameVersionApp(test, fileName)
        filterAction = rundependent.FilterAction()
        return filterAction.getAllFilters(test, fileName, app), app

    def getTestProcessor(self, app):
        catalogueCreator = self.getCatalogueCreator()
        ignoreCatalogues = self.shouldIgnoreCatalogues()
        collator = self.getTestCollator()
        from .traffic import SetUpCaptureMockHandlers, TerminateCaptureMockHandlers
        trafficSetup = SetUpCaptureMockHandlers(self.optionIntValue("rectraffic"))
        trafficTerminator = TerminateCaptureMockHandlers()
        actions = [self.getExecHostFinder(), self.getWriteDirectoryMaker(),
                   self.getWriteDirectoryPreparer(ignoreCatalogues),
                   trafficSetup, catalogueCreator, collator, self.getOriginalFilterer(), self.getTestRunner(),
                   trafficTerminator, catalogueCreator, collator, self.getTestEvaluator()]
        for pathName, path in app.getConfigValue("dbtext_database_path").items():
            if "dbtext-setup-" + pathName.lower() in self.optionMap:
                actions.append(SaveDatabase(path))
        return actions

    def isRecording(self):
        return "record" in self.optionMap

    def shouldIgnoreCatalogues(self):
        return "ignorecat" in self.optionMap or self.isRecording()

    def hasPerformance(self, app, perfType=""):
        extractors = app.getConfigValue("performance_logfile_extractor")
        if (perfType and perfType in extractors) or (not perfType and len(extractors) > 0):
            return True
        else:
            return app.hasAutomaticCputimeChecking()

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
            writeDir = app.writeDirectory if useOwnTmpDir else None
            dirs += self._getFilterFileDirs(app, app.getDirectory(), writeDir)
        return dirs

    def _getFilterFileDirs(self, suiteOrApp, rootDir, writeDir=None):
        dirs = []
        appDirs = suiteOrApp.getConfigValue("filter_file_directory")
        tmpDir = self.getTmpFilterDir(writeDir)
        if tmpDir and tmpDir not in dirs:
            dirs.append(tmpDir)

        for dir in appDirs:
            if os.path.isabs(dir) and os.path.isdir(dir):
                if dir not in dirs:
                    dirs.append(dir)
            else:
                newDir = os.path.join(rootDir, dir)
                if not newDir in dirs:
                    dirs.append(newDir)
        return dirs

    def getTmpFilterDir(self, writeDir):
        cmdLineDir = self.optionValue("fd")
        if cmdLineDir:
            return os.path.normpath(cmdLineDir)
        elif writeDir:
            return os.path.join(writeDir, "temporary_filter_files")

    def getFilterClasses(self):
        return [TestNameFilter, plugins.TestSelectionFilter, TestRelPathFilter,
                performance.TimeFilter, performance.FastestFilter, performance.SlowestFilter,
                plugins.ApplicationFilter, TestDescriptionFilter]

    def getAbsoluteFilterFileName(self, suite, filterFileName):
        if os.path.isabs(filterFileName):
            if os.path.isfile(filterFileName):
                return filterFileName
            else:
                raise plugins.TextTestError("Could not find filter file at '" + filterFileName + "'")
        else:
            dirsToSearchIn = self._getFilterFileDirs(suite, suite.app.getDirectory())
            absName = suite.app.getFileName(dirsToSearchIn, filterFileName)
            if absName:
                return absName
            else:
                raise plugins.TextTestError("No filter file named '" + filterFileName + "' found in :\n" +
                                            "\n".join(dirsToSearchIn))

    def optionListValue(self, options, key):
        if key in options:
            return plugins.commasplit(options[key])
        else:
            return []

    def findFilterFileNames(self, app, options, includeConfig):
        names = self.optionListValue(options, "f") + self.optionListValue(options, "fintersect")
        if includeConfig:
            names += app.getConfigValue("default_filter_file")
            batchSession = self.getBatchSessionForSelect(app)
            if batchSession:
                names += app.getCompositeConfigValue("batch_filter_file", batchSession)
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
        self._checkFilterFileSanity(suite, self.optionMap, includeConfig=True)

    def _checkFilterFileSanity(self, suite, options, includeConfig=False):
        for filterFileName in self.findAllFilterFileNames(suite.app, options, includeConfig):
            optionFinder = self.makeOptionFinder(suite, filterFileName)
            self._checkFilterFileSanity(suite, optionFinder)

    def _getFilterList(self, app, options, suites, includeConfig, **kw):
        filters = self.getFiltersFromMap(options, app, suites, **kw)
        for filterFileName in self.findFilterFileNames(app, options, includeConfig):
            filters += self.getFiltersFromFile(app, filterFileName, suites)
        if self.isReconnecting():
            filters.append(self.reconnectConfig.getFilter())

        orFilterFiles = self.optionListValue(options, "funion")
        if len(orFilterFiles) > 0:
            orFilterLists = [self.getFiltersFromFile(app, f, suites) for f in orFilterFiles]
            filters.append(OrFilter(orFilterLists))

        notFilterFile = options.get("finverse")
        if notFilterFile:
            filters.append(NotFilter(self.getFiltersFromFile(app, notFilterFile, suites)))

        return filters

    def makeOptionFinder(self, *args):
        absName = self.getAbsoluteFilterFileName(*args)
        fileData = ",".join(plugins.readList(absName))
        return plugins.OptionFinder(fileData.split(), defaultKey="t")

    def getFiltersFromFile(self, app, filename, suites):
        for suite in suites:
            if suite.app is app:
                optionFinder = self.makeOptionFinder(suite, filename)
                return self._getFilterList(app, optionFinder, suites, includeConfig=False)

    def getFiltersFromMap(self, optionMap, app, suites, **kw):
        filters = []
        for filterClass in self.getFilterClasses():
            argument = optionMap.get(filterClass.option)
            if argument:
                filters.append(filterClass(argument, app, suites))
        batchSession = self.getBatchSessionForSelect(app)
        if batchSession:
            timeLimit = app.getCompositeConfigValue("batch_timelimit", batchSession)
            if timeLimit:
                filters.append(performance.TimeFilter(timeLimit))
        if "grep" in optionMap:
            grepFile = optionMap.get("grepfile", app.getConfigValue("log_file"))
            filters.append(GrepFilter(optionMap["grep"], grepFile, **kw))
        return filters

    def batchMode(self):
        return "b" in self.optionMap

    def actualBatchMode(self):
        return self.batchMode() and not self.isReconnecting() and not self.runningScript() and not "coll" in self.optionMap

    def keepTemporaryDirectories(self):
        if "keeptmp" in self.optionMap:
            return self.optionMap.get("keeptmp") != "0"
        else:
            return self.actualBatchMode()

    def hasKeeptmpFlag(self):
        return "keeptmp" in self.optionMap and self.optionMap.get("keeptmp") != "0"

    def cleanPreviousTempDirs(self):
        return self.actualBatchMode() and "keeptmp" not in self.optionMap

    def cleanWriteDirectory(self, suite):
        if self.removePreviousThread and self.removePreviousThread.is_alive():
            plugins.log.info("Waiting for removal of previous write directories to complete...")
            self.removePreviousThread.join()
            Config.removePreviousThread = None
        if not self.hasKeeptmpFlag():
            self._cleanLocalWriteDirectory(suite)
        if not self.keepTemporaryDirectories():
            self._cleanWriteDirectory(suite)
            machine, tmpDir = self.getRemoteTmpDirectory(suite.app)
            if tmpDir:
                self.cleanRemoteDir(suite.app, machine, tmpDir)

    def cleanRemoteDir(self, app, machine, tmpDir):
        self.runCommandOn(app, machine, ["rm", "-rf", tmpDir])

    def _cleanWriteDirectory(self, suite):
        if os.path.isdir(suite.app.writeDirectory):
            plugins.rmtree(suite.app.writeDirectory)

    def _cleanLocalWriteDirectory(self, suite):
        if suite.app.localWriteDirectory != suite.app.writeDirectory and os.path.isdir(suite.app.localWriteDirectory):
            plugins.rmtree(suite.app.localWriteDirectory)

    def findRemotePreviousDirInfo(self, app):
        machine, tmpDir = self.getRemoteTmpDirectory(app)
        if tmpDir:  # Ignore the datetime and the pid at the end
            searchParts = tmpDir.split(".")[:-2] + ["*"]
            fileArg = ".".join(searchParts)
            return machine, fileArg
        else:
            return None, None

    def cleanPreviousWriteDirs(self, previousWriteDirs):
        for previousWriteDir in previousWriteDirs:
            plugins.rmtree(previousWriteDir, attempts=3)

    def makeWriteDirectory(self, app, subdir=None):
        if not self.removePreviousThread and self.cleanPreviousTempDirs():
            previousWriteDirs = self.findPreviousWriteDirs(app.writeDirectory)
            machine, fileArg = self.findRemotePreviousDirInfo(app)
            if fileArg:
                plugins.log.info("Removing previous remote write directories on " + machine + " matching " + fileArg)
                self.runCommandOn(app, machine, ["rm", "-rf", fileArg])
            for previousWriteDir in previousWriteDirs:
                plugins.log.info("Removing previous write directory " + previousWriteDir + " in background")
            if previousWriteDirs:
                thread = Thread(target=self.cleanPreviousWriteDirs, args=(previousWriteDirs,))
                thread.start()
                Config.removePreviousThread = thread

        dirToMake = app.writeDirectory
        if subdir:
            dirToMake = os.path.join(app.writeDirectory, subdir)
        plugins.ensureDirectoryExists(dirToMake)
        app.diag.info("Made root directory at " + dirToMake)
        return dirToMake

    def findPreviousWriteDirs(self, writeDir):
        previousWriteDirs = []
        rootDir, basename = os.path.split(writeDir)
        if os.path.isdir(rootDir):
            # Ignore the datetime and the pid at the end
            searchParts = basename.split(".")[:-2]
            for file in os.listdir(rootDir):
                fileParts = file.split(".")
                if fileParts[:-2] == searchParts:
                    previousWriteDir = os.path.join(rootDir, file)
                    if os.path.isdir(previousWriteDir) and not plugins.samefile(previousWriteDir, writeDir):
                        previousWriteDirs.append(previousWriteDir)
        return previousWriteDirs

    def isReconnecting(self):
        return "reconnect" in self.optionMap

    def getWriteDirectoryMaker(self):
        return sandbox.MakeWriteDirectory()

    def getExecHostFinder(self):
        return sandbox.FindExecutionHosts()

    def getWriteDirectoryPreparer(self, ignoreCatalogues):
        return sandbox.PrepareWriteDirectory(ignoreCatalogues)

    def getTestRunner(self):
        return RunTest()

    def getTestEvaluator(self):
        return [self.getFileExtractor(), self.getTemporaryFilterer(), self.getTestComparator(), self.getFailureExplainer()]

    def getFileExtractor(self):
        return [self.getPerformanceFileMaker(), self.getPerformanceExtractor()]

    def getCatalogueCreator(self):
        return sandbox.CreateCatalogue()

    def getTestCollator(self):
        return sandbox.CollateFiles()

    def getPerformanceExtractor(self):
        return sandbox.ExtractPerformanceFiles(self.getMachineInfoFinder())

    def getPerformanceFileMaker(self):
        return sandbox.MakePerformanceFile(self.getMachineInfoFinder())

    def executingOnPerformanceMachine(self, test, stem="cputime"):
        infoFinder = self.getMachineInfoFinder()
        infoFinder.setUpApplication(test.app)
        return infoFinder.allMachinesTestPerformance(test, stem)

    def getMachineInfoFinder(self):
        return sandbox.MachineInfoFinder()

    def getFailureExplainer(self):
        from .knownbugs import CheckForBugs, CheckForCrashes
        return [CheckForCrashes(), CheckForBugs()]

    def showExecHostsInFailures(self, app):
        return self.batchMode() or app.getRunMachine() != "localhost"

    def getTestComparator(self):
        return comparetest.MakeComparisons(enableColor="zen" in self.optionMap)

    def getStateSaver(self):
        if self.actualBatchMode():
            return batch.SaveState
        elif self.keepTemporaryDirectories() or "rerun" in self.optionMap:
            return SaveState

    def getConfigEnvironment(self, test, allVars):
        testEnvironmentCreator = self.getEnvironmentCreator(test)
        return testEnvironmentCreator.getVariables(allVars)

    def getEnvironmentCreator(self, test):
        return sandbox.TestEnvironmentCreator(test, self.optionMap)

    def getInteractiveReplayOptions(self):
        return [("gui", "visible GUI")]

    def getTextResponder(self):
        return console.InteractiveResponder

    def getWebPageResponder(self):
        return batch.WebPageResponder

    # Utilities, which prove useful in many derived classes
    def optionValue(self, option):
        return self.optionMap.get(option, "")

    def optionIntValue(self, option, defaultValue=0, optionType=int):
        if option in self.optionMap:
            value = self.optionMap.get(option)
            if value is None:
                return 1
            try:
                return optionType(value)
            except ValueError:
                raise plugins.TextTestError("ERROR: Arguments to -" + option +
                                            " flag must be numeric, received '" + value + "'")
        else:
            return defaultValue

    def runningScript(self):
        return "s" in self.optionMap

    def ignoreExecutable(self):
        return self.runningScript() or self.ignoreCheckout() or "coll" in self.optionMap or "gx" in self.optionMap

    def ignoreCheckout(self):
        return self.isReconnecting()  # No use of checkouts has yet been thought up when reconnecting :)

    def setUpCheckout(self, app):
        return self.getGivenCheckoutPath(app) if not self.ignoreCheckout() else ""

    def verifyCheckoutValid(self, app):
        if not os.path.isdir(app.checkout):
            self.handleNonExistent(app.checkout, "checkout", app)

    def checkCheckoutExists(self, app):
        if not app.checkout:
            return ""  # Allow empty checkout, means no checkout is set, basically

        try:
            self.verifyCheckoutValid(app)
        except plugins.TextTestError as e:
            if self.ignoreExecutable():
                plugins.printWarning(str(e), stdout=True)
                return ""
            else:
                raise

    def checkSanity(self, suite):
        if not self.ignoreCheckout():
            self.checkCheckoutExists(suite.app)
        if not self.ignoreExecutable():
            self.checkExecutableExists(suite)

        self.checkFilterFileSanity(suite)
        self.checkCaptureMockMigration(suite)
        self.checkConfigSanity(suite.app)
        batchSession = self.getBatchSessionForSelect(suite.app)
        if "coll" in self.optionMap and batchSession is None:
            raise plugins.TextTestError(
                "Must provide '-b' argument to identify the batch session when running with '-coll' to collect batch run data")
        self.optionIntValue("delay", optionType=float)  # throws if it's not numeric...
        if batchSession is not None and "coll" not in self.optionMap:
            batchFilter = batch.BatchVersionFilter(batchSession)
            batchFilter.verifyVersions(suite.app)
        if self.isReconnecting():
            self.reconnectConfig.checkSanity(suite.app)
        # side effects really from here on :(
        if self.readsTestStateFiles():
            # Reading stuff from stored pickle files, need to set up categories independently
            self.setUpPerformanceCategories(suite.app)

    def checkCaptureMockMigration(self, suite):
        if (suite.getCompositeConfigValue("collect_traffic", "asynchronous") or
                suite.getConfigValue("collect_traffic_python")) and \
                not self.optionMap.runScript():
            raise plugins.TextTestError("collect_traffic settings have been deprecated.\n" +
                                        "They have been replaced by using the CaptureMock program which is now separate from TextTest.\n" +
                                        "Please run with '-s traffic.ConvertToCaptureMock' and consult the migration notes at\n" +
                                        os.path.join(plugins.installationDir("doc"), "MigrationNotes_from_3.20") + "\n")

    def readsTestStateFiles(self):
        return self.isReconnecting() or "coll" in self.optionMap

    def setUpPerformanceCategories(self, app):
        # We don't create these in the normal way, so we don't know what they are.
        allCategories = list(app.getConfigValue("performance_descriptor_decrease").values()) + \
            list(app.getConfigValue("performance_descriptor_increase").values())
        for cat in allCategories:
            if cat:
                plugins.addCategory(*plugins.commasplit(cat))

    def checkExecutableExists(self, suite):
        executable = suite.getConfigValue("executable")
        if self.executableShouldBeFile(suite.app, executable) and not os.path.isfile(executable):
            self.handleNonExistent(executable, "executable program", suite.app)

        for interpreterStr in list(suite.getConfigValue("interpreters").values()):
            interpreter = plugins.splitcmd(interpreterStr)[0]
            if os.path.isabs(interpreter) and not os.path.exists(interpreter):
                self.handleNonExistent(interpreter, "interpreter program", suite.app)

    def pathExistsRemotely(self, app, path, machine):
        exitCode = self.runCommandOn(app, machine, ["test", "-e", path], collectExitCode=True)
        return exitCode == 0

    def checkConnection(self, app, machine):
        self.runCommandAndCheckMachine(app, machine, ["echo", "hello"])

    def handleNonExistent(self, path, desc, app):
        message = "The " + desc + " '" + path + "' does not exist"
        remoteCopy = app.getConfigValue("remote_copy_program")
        if remoteCopy:
            runMachine = app.getRunMachine()
            if runMachine != "localhost":
                if not self.pathExistsRemotely(app, path, runMachine):
                    self.checkConnection(app, runMachine)  # throws if we can't get to it
                    raise plugins.TextTestError(message + ", either locally or on machine '" + runMachine + "'.")
        else:
            raise plugins.TextTestError(message + ".")

    def getRemoteTmpDirectory(self, app):
        remoteCopy = app.getConfigValue("remote_copy_program")
        if remoteCopy:
            runMachine = app.getRunMachine()
            if runMachine != "localhost":
                return runMachine, "${HOME}/.texttest/tmp/" + os.path.basename(app.writeDirectory)
        return "localhost", None

    def getRemoteTestTmpDir(self, test):
        machine, appTmpDir = self.getRemoteTmpDirectory(test.app)
        if appTmpDir:
            return machine, os.path.join(appTmpDir, test.app.name + test.app.versionSuffix(), test.getRelPath())
        else:
            return machine, appTmpDir

    def hasChanged(self, var, value):
        return os.getenv(var) != value

    def executableShouldBeFile(self, app, executable):
        if os.path.isabs(executable):
            return True

        # If it's part of the data it will be available as a relative path anyway
        if executable in app.getDataFileNames():
            return False

        # For finding java classes, don't warn if they don't exist as files...
        if executable.endswith(".jar"):
            return False
        interpreters = list(app.getConfigValue("interpreters").values())
        return all(("java" not in i and "jython" not in i for i in interpreters))

    def checkConfigSanity(self, app):
        for key in app.getConfigValue("collate_file"):
            if "." in key or "/" in key:
                raise plugins.TextTestError("Cannot collate files to stem '" + key +
                                            "' - '.' and '/' characters are not allowed")

        definitionFileStems = app.defFileStems()
        definitionFileStems += [stem + "." + app.name for stem in definitionFileStems]
        for dataFileName in app.getDataFileNames():
            if dataFileName in definitionFileStems:
                raise plugins.TextTestError("Cannot name data files '" + dataFileName +
                                            "' - this name is reserved by TextTest for a particular kind of definition file.\n" +
                                            "Please adjust the naming in your config file.")

    def getGivenCheckoutPath(self, app):
        if "c" in self.optionMap:
            extraVersions, extraCheckouts = self.getCheckoutExtraVersions(app)
            for versionName, checkout in zip(extraVersions, extraCheckouts):
                if versionName in app.versions:
                    return checkout

        checkout = self.getCheckout(app)
        return self.expandCheckout(checkout, app)

    def expandCheckout(self, checkout, app):
        if os.path.isabs(checkout):
            return os.path.normpath(checkout)
        checkoutLocations = app.getCompositeConfigValue("checkout_location", checkout, expandVars=False)
        checkoutLocations.append(os.getcwd())
        return self.makeAbsoluteCheckout(checkoutLocations, checkout, app)

    def getCheckout(self, app):
        if "c" in self.optionMap:
            return plugins.commasplit(self.optionMap["c"])[0]

        # Under some circumstances infer checkout from batch session
        batchSession = self.getBatchSession(app)
        if batchSession and batchSession != "default" and \
                batchSession in app.getConfigValue("checkout_location"):
            return batchSession
        else:
            return app.getConfigValue("default_checkout")

    def makeAbsoluteCheckout(self, locations, checkout, app):
        isSpecific = checkout in app.getConfigValue("checkout_location")
        for location in locations:
            fullCheckout = self.absCheckout(location, checkout, isSpecific)
            if os.path.isdir(fullCheckout):
                return fullCheckout
        return self.absCheckout(locations[0], checkout, isSpecific)

    def absCheckout(self, location, checkout, isSpecific):
        locationWithName = Template(location).safe_substitute(TEXTTEST_CHECKOUT_NAME=checkout)
        fullLocation = os.path.normpath(os.path.expanduser(os.path.expandvars(locationWithName)))
        if isSpecific or "TEXTTEST_CHECKOUT_NAME" in location:
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
                newState = state.makeNewState(test, "recalculated")
                test.changeState(newState)
        else:
            collator = test.app.getTestCollator()
            collator.tryFetchRemoteFiles(test)
            fileFilter = rundependent.FilterProgressRecompute()
            fileFilter(test)
            comparator = self.getTestComparator()
            comparator.recomputeProgress(test, state, observers)

    def getRunDescription(self, test):
        return RunTest().getRunDescription(test)

    def expandExternalEnvironment(self):
        return True

    # For display in the GUI
    def extraReadFiles(self, testArg):
        return {}

    def printHelpScripts(self):
        pass

    def printHelpDescription(self):
        configName = self.__class__.__module__.replace("texttestlib.", "")
        print("The " + configName + " configuration is a published configuration. Consult the online documentation.")

    def printHelpOptions(self):
        pass

    def printHelpText(self):
        self.printHelpDescription()
        print("\nAdditional Command line options supported :")
        print("-------------------------------------------")
        self.printHelpOptions()
        print("\nPython scripts: (as given to -s <module>.<class> [args])")
        print("--------------------------------------------------------")
        self.printHelpScripts()

    def getDefaultMailAddress(self):
        user = os.getenv("USER", "$USER")
        return user + "@localhost"

    def getDefaultTestOverviewColours(self):
        colours = {}
        for wkday in plugins.weekdays:
            colours["run_" + wkday + "_fg"] = "black"
        colours["column_header_bg"] = "gray1"
        colours["changes_header_bg"] = "#E2E2FF"
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
        return {"default": []}

    def setBatchDefaults(self, app):
        # Batch values. Maps from session name to values
        app.setConfigDefault("smtp_server", "localhost", "Server to use for sending mail in batch mode")
        app.setConfigDefault("smtp_server_username", "",
                             "Username for SMTP authentication when sending mail in batch mode")
        app.setConfigDefault("smtp_server_password", "",
                             "Password for SMTP authentication when sending mail in batch mode")
        app.setConfigDefault("batch_result_repository", {"default": ""},
                             "Directory to store historical batch results under")
        app.setConfigDefault("file_to_url", {}, "Mapping of file locations to URLS, for linking to HTML reports")
        app.setConfigDefault("historical_report_location", {"default": ""},
                             "Directory to create reports on historical batch data under")
        app.setConfigDefault("historical_report_page_name", {"default": self.getDefaultPageName(
            app)}, "Header for page on which this application should appear")
        app.setConfigDefault("historical_report_colours", self.getDefaultTestOverviewColours(),
                             "Colours to use for historical batch HTML reports")
        app.setConfigDefault("historical_report_subpages", {"default": [
                             "Last six runs"]}, "Names of subselection pages to generate as part of historical report")
        app.setConfigDefault("historical_report_subpage_cutoff", {
                             "default": 100000, "Last six runs": 6}, "How many runs should the subpage show, starting from the most recent?")
        app.setConfigDefault("historical_report_subpage_weekdays", {
                             "default": []}, "Which weekdays should the subpage apply to (empty implies all)?")
        app.setConfigDefault("historical_report_resources", {
                             "default": []}, "Which performance/memory entries should be shown as separate lines in the historical report")
        app.setConfigDefault("historical_report_piechart_summary", {
                             "default": "false"}, "Generate pie chart summary page rather than default HTML tables.")
        app.setConfigDefault("historical_report_split_version", {
                             "default": "false"}, "Split pages per version.")
        app.setConfigDefault("batch_sender", {"default": self.getDefaultMailAddress()},
                             "Sender address to use sending mail in batch mode")
        app.setConfigDefault("batch_recipients", {"default": ""},
                             "Comma-separated addresses to send mail to in batch mode")
        app.setConfigDefault("batch_timelimit", {"default": ""}, "Maximum length of test to include in batch mode runs")
        app.setConfigDefault("batch_filter_file", {"default": []},
                             "Generic filter for batch session, more flexible than timelimit")
        app.setConfigDefault("batch_use_collection", {"default": "false"},
                             "Do we collect multiple mails into one in batch mode")
        app.setConfigDefault("batch_external_format", {"default": "false"},
                             "Do we write out results in external format in batch mode. Supports junit, trx")
        app.setConfigDefault("batch_include_comment_plugin", {"default": "true"},
                             "Do we include the comment plugin in the HTML report (requires PHP)")
        app.setConfigDefault("batch_external_folder", {
                             "default": ""}, "Which folder to write test results in external format in batch mode. Only useful together with batch_external_format")
        app.setConfigDefault("batch_collect_max_age_days", {
                             "default": 100000}, "When collecting multiple messages, what is the maximum age of run that we should accept?")
        app.setConfigDefault("batch_collect_compulsory_version", self.getDefaultCollectCompulsoryVersions(
        ), "When collecting multiple messages, which versions should be expected and give an error if not present?")
        app.setConfigDefault("batch_mail_on_failure_only", {
                             "default": "false"}, "Send mails only if at least one test fails")
        app.setConfigDefault("batch_use_version_filtering", {
                             "default": "false"}, "Which batch sessions use the version filtering mechanism")
        app.setConfigDefault("batch_version", {"default": []},
                             "List of versions to allow if batch_use_version_filtering enabled")
        app.setConfigAlias("testoverview_colours", "historical_report_colours")
        app.setConfigAlias("historical_report_resource_pages", "historical_report_resources")
        app.setConfigAlias("batch_junit_format", "batch_external_format")
        app.setConfigAlias("batch_junit_folder", "batch_external_folder")


    def setPerformanceDefaults(self, app):
        # Performance values
        app.setConfigDefault("cputime_include_system_time", 0, "Include system time when measuring CPU time?")
        app.setConfigDefault("default_performance_stem", "performance",
                             "Which performance statistic to use when selecting tests by performance, placing performance in Junit XML reports etc")
        app.setConfigDefault("performance_logfile", {"default": []},
                             "Which result file to collect performance data from")
        app.setConfigDefault("performance_logfile_extractor", {},
                             "What string to look for when collecting performance data")
        app.setConfigDefault("performance_test_machine", {"default": [], "*mem*": ["any"]},
                             "List of machines where performance can be collected")
        app.setConfigDefault("performance_variation_%", {"default": 10.0},
                             "How much variation in performance is allowed")
        app.setConfigDefault("performance_variation_serious_%", {
                             "default": 0.0}, "Additional cutoff to performance_variation_% for extra highlighting")
        app.setConfigDefault("use_normalised_percentage_change", {"default": "true"},
                             "Do we interpret performance percentage changes as normalised (symmetric) values?")
        app.setConfigDefault("performance_test_minimum", {"default": 0.0},
                             "Minimum time/memory to be consumed before data is collected")
        app.setConfigDefault("performance_descriptor_decrease", self.defaultPerfDecreaseDescriptors(),
                             "Descriptions to be used when the numbers decrease in a performance file")
        app.setConfigDefault("performance_descriptor_increase", self.defaultPerfIncreaseDescriptors(),
                             "Descriptions to be used when the numbers increase in a performance file")
        app.setConfigDefault("performance_unit", self.defaultPerfUnits(),
                             "Name to be used to identify the units in a performance file")
        app.setConfigDefault("performance_ignore_improvements", {
                             "default": "false"}, "Should we ignore all improvements in performance?")
        app.setConfigAlias("performance_use_normalised_%", "use_normalised_percentage_change")
        app.setConfigAlias("batch_junit_performance", "default_performance_stem")

    def setUsecaseDefaults(self, app):
        app.setConfigDefault("use_case_record_mode", "disabled",
                             "Mode for Use-case recording (GUI, console or disabled)")
        app.setConfigDefault("use_case_recorder", "", "Which Use-case recorder is being used")
        app.setConfigDefault("virtual_display_machine", ["localhost"],
                             "(UNIX) List of machines to run virtual display server (Xvfb) on")
        app.setConfigDefault("virtual_display_count", 1,
                             "(UNIX) Number of virtual display server (Xvfb) instances to run, if enabled")
        app.setConfigDefault("virtual_display_extra_args", "",
                             "(UNIX) Extra arguments (e.g. bitdepth) to supply to virtual display server (Xvfb)")
        app.setConfigDefault("virtual_display_wm_executable", "",
                             "(UNIX) Window manager executable to start under virtual display server (Xvfb)")
        app.setConfigDefault("virtual_display_hide_windows", "true",
                             "(Windows) Whether to emulate the virtual display handling on Windows by hiding the SUT's windows")

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
        severities["stderr"] = 1
        severities["stdout"] = 1
        severities["usecase"] = 1
        severities["performance"] = 2
        severities["catalogue"] = 2
        severities["default"] = 99
        return severities

    def defaultDisplayPriorities(self):
        prios = {}
        prios["default"] = 99
        prios["errors"] = 1
        prios["stderr"] = 1
        return prios

    def getDefaultCollations(self):
        if os.name == "posix":
            return {"stacktrace": ["core*"]}
        else:
            return {"": []}

    def getDefaultCollateScripts(self):
        if os.name == "posix":
            return {"default": [], "stacktrace": ["interpretcore"]}
        else:
            return {"default": []}

    def getStdoutName(self, namingScheme):
        if namingScheme == "classic":
            return "output"
        else:
            return "stdout"

    def getStderrName(self, namingScheme):
        if namingScheme == "classic":
            return "errors"
        else:
            return "stderr"

    def getStdinName(self, namingScheme):
        if namingScheme == "classic":
            return "input"
        else:
            return "stdin"

    def setComparisonDefaults(self, app, homeOS, namingScheme):
        app.setConfigDefault("log_file", self.getStdoutName(namingScheme), "Result file to search, by default")
        app.setConfigDefault("failure_severity", self.defaultSeverities(),
                             "Mapping of result files to how serious diffs in them are")
        app.setConfigDefault("failure_display_priority", self.defaultDisplayPriorities(),
                             "Mapping of result files to which order they should be shown in the text info window.")
        app.setConfigDefault("floating_point_tolerance", {
                             "default": 0.0}, "Which tolerance to apply when comparing floating point values in output")
        app.setConfigDefault("relative_float_tolerance", {
                             "default": 0.0}, "Which relative tolerance to apply when comparing floating point values")
        app.setConfigDefault("floating_point_split", {
                             "default": ''}, "Separator to split at when comparing floating point values")

        app.setConfigDefault("collate_file", self.getDefaultCollations(),
                             "Mapping of result file names to paths to collect them from")
        app.setConfigDefault("collate_script", self.getDefaultCollateScripts(),
                             "Mapping of result file names to scripts which turn them into suitable text")
        trafficText = "Deprecated. Use CaptureMock."
        app.setConfigDefault("collect_traffic", {"default": [], "asynchronous": []}, trafficText)
        app.setConfigDefault("collect_traffic_environment", {"default": []}, trafficText)
        app.setConfigDefault("collect_traffic_python", [], trafficText)
        app.setConfigDefault("collect_traffic_python_ignore_callers", [], trafficText)
        app.setConfigDefault("collect_traffic_use_threads", "true", trafficText)
        app.setConfigDefault("collect_traffic_client_server", "false", trafficText)
        app.setConfigDefault("run_dependent_text", {"default": []},
                             "Mapping of patterns to remove from result files", trackFiles=True)
        app.setConfigAlias("scrubbers", "run_dependent_text")

        app.setConfigDefault("unordered_text", {"default": []},
                             "Mapping of patterns to extract and sort from result files", trackFiles=True)
        app.setConfigDefault("file_split_pattern", {}, "Pattern to use for splitting result files")
        app.setConfigDefault("create_catalogues", "false", "Do we create a listing of files created/removed by tests")
        app.setConfigAlias("collect_file_changes", "create_catalogues")
        app.setConfigAlias("collate_file_changes", "create_catalogues")

        app.setConfigDefault("catalogue_process_string", "",
                             "String for catalogue functionality to identify processes created")
        app.setConfigDefault(
            "binary_file", [], "Which output files are known to be binary, and hence should not be shown/diffed?")

        app.setConfigDefault("discard_file", [], "List of generated result files which should not be compared")
        app.setConfigDefault("discard_file_text", {
                             "default": []}, "List of generated result files which should not be compared if they contain the given patterns")
        app.setConfigDefault("capturemock_path", "", "Path to local CaptureMock installation, in case newer one is required with frozen TextTest")
        app.setConfigDefault("capturemock_clientserver_mock_name", "httpmocks", "Path stem to use for client-server mocks for CaptureMock")
        rectrafficValue = self.optionIntValue("rectraffic")
        if rectrafficValue == 1:
            # Re-record everything. Don't use this when only recording additional new stuff
            # Should possibly have some way to configure this
            app.addConfigEntry("implied", "rectraffic", "base_version")
        if self.isRecording():
            app.addConfigEntry("implied", "recusecase", "base_version")
        if homeOS != "any" and homeOS != os.name:
            app.addConfigEntry("implied", os.name, "base_version")
        app.setConfigAlias("collect_traffic_py_module", "collect_traffic_python")

    def defaultViewProgram(self, homeOS):
        if os.name == "posix":
            return os.getenv("EDITOR", "emacs")
        else:
            # Notepad cannot handle UNIX line-endings: so check for alternatives by default...
            for editor in (r'Notepad++\notepad++.exe', r'Windows NT\Accessories\wordpad.exe'):
                for prefix in (r"C:\Program Files", r"C:\Program Files (x86)"):
                    path = os.path.join(prefix, editor)
                    if os.path.exists(path):
                        return path
            return "notepad"

    def defaultFollowProgram(self):
        if os.name == "posix":
            return "xterm -bg white -T $TEXTTEST_FOLLOW_FILE_TITLE -e tail -f"
        else:
            return "baretail"

    def defaultDiffProgram(self):
        if os.name == "posix":
            for diff in ('tkdiff', 'kdiff3', 'meld'):
                for prefix in ("/usr/bin", "/usr/local/bin"):
                    path = os.path.join(prefix, diff)
                    if os.path.exists(path):
                        return path
        else:
            for diff in (r'TkDiff\tkdiff.exe', r'TortoiseSVN\bin\TortoiseMerge.exe', r'TortoiseGit\bin\TortoiseGitMerge.exe'):
                for prefix in (r"C:\Program Files", r"C:\Program Files (x86)"):
                    path = os.path.join(prefix, diff)
                    if os.path.exists(path):
                        return path
        if getattr(sys, 'frozen', False):
            return os.path.join(os.path.dirname(sys.executable), "Meld.exe")
        return "tkdiff"

    def setExternalToolDefaults(self, app, homeOS):
        app.setConfigDefault("text_diff_program", "diff",
                             "External program to use for textual comparison of files")
        app.setConfigDefault("lines_of_text_difference", 30,
                             "How many lines to present in textual previews of file diffs")
        app.setConfigDefault("max_width_text_difference", 500,
                             "How wide lines can be in textual previews of file diffs")
        app.setConfigDefault("max_file_size", {
                             "default": "-1"}, "The maximum file size to load into external programs, in bytes. -1 means no limit.")
        app.setConfigDefault("text_diff_program_filters", {"default": [], "diff": [
                             "^<", "^>"]}, "Filters that should be applied for particular diff tools to aid with grouping in dynamic GUI")
        app.setConfigDefault("diff_program", {"default": self.defaultDiffProgram()},
                             "External program to use for graphical file comparison")
        app.setConfigDefault("view_program", {"default": self.defaultViewProgram(homeOS)},
                             "External program(s) to use for viewing and editing text files")
        app.setConfigDefault("view_file_on_remote_machine", {
                             "default": 0}, "Do we try to start viewing programs on the test execution machine?")
        app.setConfigDefault("follow_program", {"default": self.defaultFollowProgram()},
                             "External program to use for following progress of a file")
        app.setConfigDefault("follow_file_by_default", 0,
                             "When double-clicking running files, should we follow progress or just view them?")
        app.setConfigDefault("bug_system_location", {},
                             "The location of the bug system we wish to extract failure information from.")
        app.setConfigDefault("bug_system_username", {},
                             "Username to use when logging in to bug systems defined in bug_system_location")
        app.setConfigDefault("bug_system_password", {},
                             "Password to use when logging in to bug systems defined in bug_system_location")
        app.setConfigDefault("batch_jenkins_marked_artefacts", {
                             "default": []}, "Artefacts to highlight in the report when they are updated")
        app.setConfigDefault("batch_jenkins_archive_file_pattern", {
                             "default": ""}, "Path to the built files in the archive, in case Jenkins fingerprints need double-checking")
        app.setConfigAlias("text_diff_program_max_file_size", "max_file_size")

    def setInterfaceDefaults(self, app):
        app.setConfigDefault("default_interface", "static_gui",
                             "Which interface to start if none of -con, -g and -gx are provided")
        # These configure the GUI but tend to have sensible defaults per application
        app.setConfigDefault("gui_entry_overrides", {"default": "<not set>"}, "Default settings for entries in the GUI")
        app.setConfigDefault("gui_entry_options", {"default": []}, "Default drop-down box options for GUI entries")
        app.setConfigDefault("suppress_stderr_text", [
        ], "List of patterns which, if written on TextTest's own stderr, should not be propagated to popups and further logfiles")
        app.setConfigAlias("suppress_stderr_popup", "suppress_stderr_text")

    def getDefaultRemoteProgramOptions(self):
        # The aim is to ensure they never hang, but always return errors if contact not possible
        # Disable warnings, they get in the way of output
        # Disable passwords: only use public key based authentication.
        # Also disable hostkey checking, we assume we don't run tests on untrusted hosts.
        # Also don't run tests on machines which take a very long time to connect to...
        sshOptions = "-o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=30"
        rsyncExcludeFile = plugins.installationPath("etc", "rsync_exclude_patterns")
        return {"default": "", "ssh": "-q " + sshOptions,
                "rsync": "-e 'ssh -x " + sshOptions + "' -av --copy-unsafe-links --delete --exclude-from=" + rsyncExcludeFile, "scp": "-Crp " + sshOptions}

    def getCommandArgsOn(self, app, machine, cmdArgs, graphical=False, agentForwarding=False):
        if machine == "localhost":
            return cmdArgs
        else:
            args = self.getRemoteProgramArgs(app, "remote_shell_program")
            if args[0] == "ssh":
                if graphical:
                    args.append("-Y")
                else:
                    args.append("-x")
                if agentForwarding:
                    args.append("-A")

            args.append(machine)
            if graphical and args[0] == "rsh":
                args += ["env", "DISPLAY=" + self.getFullDisplay()]
            args += cmdArgs
            if graphical:
                remoteTmp = app.getRemoteTmpDirectory()[1]
                if remoteTmp:
                    args[-1] = args[-1].replace(app.writeDirectory, remoteTmp)
                for i in range(len(args)):
                    # Remote shells cause spaces etc to be interpreted several times
                    args[i] = args[i].replace(" ", "\ ")
            return args

    def getFullDisplay(self):
        display = os.getenv("DISPLAY", "")
        hostaddr = plugins.gethostname()
        if display.startswith(":"):
            return hostaddr + display
        else:
            return display.replace("localhost", hostaddr)

    def runCommandOn(self, app, machine, cmdArgs, collectExitCode=False):
        allArgs = self.getCommandArgsOn(app, machine, cmdArgs)
        if allArgs[0] == "rsh" and collectExitCode:
            searchStr = "remote cmd succeeded"
            # Funny tricks here because rsh does not forward the exit status of the program it runs
            allArgs += ["&&", "echo", searchStr]
            diag = logging.getLogger("remote commands")
            proc = subprocess.Popen(allArgs, stdin=open(os.devnull), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            output = proc.communicate()[0]
            outputStr = str(output, getpreferredencoding())
            diag.info("Running remote command " + repr(allArgs) + ", output was:\n" + outputStr)
            return searchStr not in outputStr  # Return an "exit code" which is 0 when we succeed!
        else:
            return subprocess.call(allArgs, stdin=open(os.devnull), stdout=open(os.devnull, "w"), stderr=subprocess.STDOUT)

    def runCommandAndCheckMachine(self, app, machine, cmdArgs):
        allArgs = self.getCommandArgsOn(app, machine, cmdArgs)
        proc = subprocess.Popen(allArgs, stdin=open(os.devnull), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = proc.communicate()[0]
        exitCode = proc.returncode
        if exitCode > 0:
            outputStr = str(output, getpreferredencoding()).strip()
            raise plugins.TextTestError("Unable to contact machine '" + machine +
                                        "'.\nMake sure you have passwordless access set up correctly. The failing command was:\n" +
                                        " ".join(allArgs) + "\n\nThe command produced exit code " + str(exitCode) + " and the following output:\n" + outputStr)

    def ensureRemoteDirExists(self, app, machine, *dirnames):
        quotedDirs = list(map(plugins.quote, dirnames))
        self.runCommandAndCheckMachine(app, machine, ["mkdir", "-p"] + quotedDirs)

    @staticmethod
    def getRemotePath(fileName, machine):
        if machine == "localhost":
            # Right now the only way we can run remote execution on a Windows system is using Cygwin
            # Remote copy programs like 'scp' assume that colons separate hostnames and so don't work
            # on classic Windows paths.
            # Assume for now that we can convert it to a Cygwin path.
            drive, tail = os.path.splitdrive(fileName)
            if drive:
                cygwinDrive = '/cygdrive/' + drive[0].lower()
                return cygwinDrive + tail
            else:
                return fileName
        else:
            return machine + ":" + plugins.quote(fileName)

    def copyFileRemotely(self, *args, **kw):
        proc = self.getRemoteCopyFileProcess(*args, **kw)
        return proc.wait()

    def getRemoteCopyFileProcess(self, app, srcFile, srcMachine, dstFile, dstMachine, ignoreLinks=False):
        srcPath = self.getRemotePath(srcFile, srcMachine)
        dstPath = self.getRemotePath(dstFile, dstMachine)
        args = self.getRemoteProgramArgs(app, "remote_copy_program") + [srcPath, dstPath]
        if ignoreLinks:
            args = self.removeLinkArgs(args)
        return subprocess.Popen(args, stdin=open(os.devnull), stdout=open(os.devnull, "w"), stderr=subprocess.STDOUT)

    def removeLinkArgs(self, args):
        for opt in ["--copy-unsafe-links", "--delete"]:  # rsync args. Add others...
            if opt in args:
                args.remove(opt)
        return args

    def getRemoteProgramArgs(self, app, setting):
        progStr = app.getConfigValue(setting)
        progArgs = plugins.splitcmd(progStr)
        argStr = app.getCompositeConfigValue("remote_program_options", progArgs[0])
        return progArgs + plugins.splitcmd(argStr)

    def setMiscDefaults(self, app, namingScheme):
        app.setConfigDefault("default_texttest_tmp", "$TEXTTEST_PERSONAL_CONFIG/tmp",
                             "Default value for $TEXTTEST_TMP, if it is not set")
        app.setConfigDefault("default_texttest_local_tmp", "",
                             "Default value for $TEXTTEST_LOCAL_TMP, if it is not set")
        app.setConfigDefault("checkout_location", {"default": []}, "Absolute paths to look for checkouts under")
        app.setConfigDefault("default_checkout", "", "Default checkout, relative to the checkout location")
        app.setConfigDefault("remote_shell_program", "ssh", "Program to use for running commands remotely")
        app.setConfigDefault("remote_program_options", self.getDefaultRemoteProgramOptions(),
                             "Default options to use for particular remote shell programs")
        app.setConfigDefault("remote_copy_program", "",
                             "(UNIX) Program to use for copying files remotely, in case of non-shared file systems")
        app.setConfigDefault("default_filter_file", [],
                             "Filter file to use by default, generally only useful for versions")
        app.setConfigDefault("test_data_environment", {},
                             "Environment variables to be redirected for linked/copied test data")
        app.setConfigDefault("test_data_require", [], "Test data names that are required to exist for the SUT to work")
        app.setConfigDefault("filter_file_directory", [
                             "filter_files"], "Default directories for test filter files, relative to an application directory.")
        app.setConfigDefault("extra_version", [], "Versions to be run in addition to the one specified")
        app.setConfigDefault("batch_extra_version", {
                             "default": []}, "Versions to be run in addition to the one specified, for particular batch sessions")
        app.setConfigDefault("save_filtered_file_stems", [],
                             "Files where the filtered version should be saved rather than the SUT output")
        # Applies to any interface...
        app.setConfigDefault("auto_sort_test_suites", 0,
                             "Automatically sort test suites in alphabetical order. 1 means sort in ascending order, -1 means sort in descending order.")
        app.setConfigDefault("extra_test_process_postfix", [],
                             "Postfixes to use on ordinary files to denote an additional run of the SUT to be triggered")
        app.setConfigDefault("dbtext_database_path", {"default": ""}, "Paths which represent textual data for databases, for use in dbtext")
        app.addConfigEntry("builtin", "options", "definition_file_stems")
        app.addConfigEntry("regenerate", "usecase", "definition_file_stems")
        app.addConfigEntry("builtin", self.getStdinName(namingScheme), "definition_file_stems")
        app.addConfigEntry("builtin", "knownbugs", "definition_file_stems")
        app.setConfigAlias("test_list_files_directory", "filter_file_directory")
        

    def setApplicationDefaults(self, app):
        homeOS = app.getConfigValue("home_operating_system")
        namingScheme = app.getConfigValue("filename_convention_scheme")
        self.setComparisonDefaults(app, homeOS, namingScheme)
        self.setExternalToolDefaults(app, homeOS)
        self.setInterfaceDefaults(app)
        self.setMiscDefaults(app, namingScheme)
        self.setBatchDefaults(app)
        self.setPerformanceDefaults(app)
        self.setUsecaseDefaults(app)

    def setDependentConfigDefaults(self, app):
        # For setting up configuration where the config file needs to have been read first
        # Should return True if it does anything that could cause new config files to be found
        interpreters = list(app.getConfigValue("interpreters").values())
        if any(("python" in i or "storytext" in i for i in interpreters)):
            app.addConfigEntry("default", "testcustomize.py", "definition_file_stems")
        extraPostfixes = app.getConfigValue("extra_test_process_postfix")
        for interpreterName in list(app.getConfigValue("interpreters").keys()):
            stem = interpreterName + "_options"
            app.addConfigEntry("builtin", stem, "definition_file_stems")
            for postfix in extraPostfixes:
                app.addConfigEntry("builtin", stem + postfix, "definition_file_stems")

        namingScheme = app.getConfigValue("filename_convention_scheme")
        for postfix in extraPostfixes:
            app.addConfigEntry("builtin", "options" + postfix, "definition_file_stems")
            app.addConfigEntry("regenerate", "usecase" + postfix, "definition_file_stems")
            app.addConfigEntry("builtin", self.getStdinName(namingScheme) + postfix, "definition_file_stems")
        if app.getConfigValue("use_case_record_mode") == "GUI" and \
                app.getConfigValue("use_case_recorder") in ["", "storytext"] and \
                not any(("usecase" in k for k in app.getConfigValue("view_program"))):
            app.addConfigEntry("*usecase*", "storytext_editor", "view_program")
        test_data_paths = app.getConfigValue("copy_test_path") + app.getConfigValue("link_test_path") + \
                          app.getConfigValue("partial_copy_test_path") + app.getConfigValue("copy_test_path_merge")
        for path in app.getConfigValue("dbtext_database_path").values():
            for sep in { "/", os.sep }:
                path = path.split(sep)[0]
            if path and path not in test_data_paths:
                app.addConfigEntry("copy_test_path_merge", path)
        return False


class SaveState(plugins.Responder):
    def notifyComplete(self, test):
        if test.state.isComplete():  # might look weird but this notification also comes in scripts etc.
            test.saveState()


class OrFilter(plugins.Filter):
    def __init__(self, filterLists):
        self.filterLists = filterLists

    def accepts(self, test):
        return reduce(operator.or_, (test.isAcceptedByAll(filters, checkContents=False) for filters in self.filterLists), False)

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
        return [text.replace(" ", "/") for text in plugins.commasplit(filterText)]

    def acceptsTestCase(self, test):
        return self.stringContainsText(test.getRelPath().replace(os.sep, "/"))


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
        for line in open(logFile, errors="ignore"):
            if self.stringContainsText(line):
                return True
        return False


class TestDescriptionFilter(plugins.TextFilter):
    option = "desc"

    def acceptsTestCase(self, test):
        return self.stringContainsText(test.description)
