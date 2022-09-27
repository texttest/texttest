
"""
Module for the queuesystem configuration, i.e. using grid engines to run tests in parallel
"""

import texttestlib.queuesystem.masterprocess
import texttestlib.queuesystem.slavejobs
import texttestlib.queuesystem.utils
import os
from texttestlib import plugins, default
from texttestlib.default.virtualdisplay import VirtualDisplayResponder
from texttestlib.default.storytext_interface import ApplicationEventResponder
from multiprocessing import cpu_count


def getConfig(optionMap):
    return QueueSystemConfig(optionMap)


class QueueSystemConfig(default.Config):
    defaultMaxCapacity = 100000
    defaultMaxReruns = 100
    useCloud = False

    def __init__(self, *args):
        default.Config.__init__(self, *args)
        self.useQueueSystem = False

    def getRunningGroupNames(self, app):
        groups = default.Config.getRunningGroupNames(self, app)
        useGrid = app is None or app.getConfigValue("queue_system_module") not in ["local", "ec2cloud"]
        label = "Grid" if useGrid else "Cloud"
        groups.insert(2, (label, "l", 1))
        return groups

    def cloudUseConsistent(self, apps):
        return len(set([app.getConfigValue("queue_system_module") == "ec2cloud" for app in apps])) == 1

    def addToOptionGroups(self, apps, groups):
        default.Config.addToOptionGroups(self, apps, groups)
        minTestCount = min((app.getConfigValue("queue_system_min_test_count")
                            for app in apps if app.getConfigValue("queue_system_min_test_count") is not None))
        localQueueSystem = utils.useLocalQueueSystem(apps)
        useGrid = all((app.getConfigValue("queue_system_module") not in ["local", "ec2cloud"] for app in apps))
        QueueSystemConfig.useCloud = all((app.getConfigValue("queue_system_module") == "ec2cloud" for app in apps))
        for group in groups:
            if group.name.startswith("Basic"):
                options = ["Always", "Never"]
                qsName = "grid"
                for app in apps:
                    currName = utils.queueSystemName(app)
                    if currName:
                        qsName = currName
                descriptions = ["Submit the tests to " + qsName,
                                "Run the tests directly, not using " + qsName]
                defaultValue = 0
                if minTestCount:
                    options.append("If enough tests")
                    descriptions.append("Submit the tests to " + qsName + " only if " +
                                        str(minTestCount) + " or more are selected.")
                    defaultValue = 2
                if "l" in self.optionMap:
                    defaultValue = self.optionIntValue("l")
                recTrafficOption = None
                if "rectraffic" in group.options:
                    # Move capturemock control to the end so it doesn't end up between checkboxes.
                    recTrafficOption = group.options.pop("rectraffic")
                if localQueueSystem:
                    group.addSwitch("l", "Run tests sequentially", value=defaultValue)
                else:
                    title = "Use grid" if useGrid else "Use cloud"
                    replayOptions = [opt for opt, _ in self.getInteractiveReplayOptions()]
                    group.addSwitch("l", title, value=defaultValue, options=options,
                                    description=descriptions, autoEnable=replayOptions)
                if recTrafficOption:
                    group.options["rectraffic"] = recTrafficOption
            elif group.name.startswith("Grid") and useGrid:
                self.addDefaultOption(group, "R", "Request grid resource", possibleValues=self.getPossibleResources())
                self.addDefaultOption(group, "q", "Request grid queue", possibleValues=self.getPossibleQueues())
                self.addDefaultSwitch(group, "keepslave", "Keep data files and successful tests until termination")
                self.addDefaultSwitch(group, "perf", "Run on performance machines only")
            elif group.name.startswith("Cloud") and self.useCloud:
                self.addDefaultOption(group, "R", "Request EC2 tag", possibleValues=self.getPossibleResources())
                self.addDefaultSwitch(group, "perf", "Run on performance machines only")
            elif group.name.startswith("Advanced") and not useGrid:
                self.addDefaultSwitch(group, "keepslave", "Keep data files and successful tests until termination")
            elif group.name.startswith("Self-diagnostics"):
                self.addDefaultSwitch(group, "xs", "Enable self-diagnostics in slave processes")
            elif group.name.startswith("Invisible"):
                group.addOption("slave", "Private: used to submit slave runs remotely")
                group.addOption("servaddr", "Private: used to submit slave runs remotely")
                group.addOption(
                    "home", "Private: used to communicate local home directory to environments that run as a different user")

    def absCheckout(self, location, checkout, isSpecific):
        if "home" in self.optionMap:
            # Use 'home' from the master machine as provided on the command line: user may be different there.
            # Important in cloud
            if location.startswith("~"):
                location = location.replace("~", self.optionValue("home"))
            if checkout.startswith("~"):
                checkout = checkout.replace("~", self.optionValue("home"))
        return default.Config.absCheckout(self, location, checkout, isSpecific)

    def getReconnFullOptions(self):
        return default.Config.getReconnFullOptions(self) + [
            "Use raw data from the original run and recompute as above, but use the grid for computations"]

    def getMachineNameForDisplay(self, machine):
        # Don't display localhost, as it's not true when using the grid
        # Should really be something like "whatever grid gives us" but blank space will do for now...
        if machine == "localhost":
            return ""
        else:
            return machine

    def getPossibleQueues(self):
        return []  # placeholders for derived configurations

    def getPossibleResources(self):
        return []

    def getLocalRunArgs(self):
        return ["gx", "s", "coll", "record", "autoreplay"]

    def calculateUseQueueSystem(self, allApps):
        for localFlag in self.getLocalRunArgs():
            if localFlag in self.optionMap:
                return False

        localQueueSystem = utils.useLocalQueueSystem(allApps)
        if localQueueSystem and self.optionValue("m"):
            return False

        value = self.optionIntValue("l")
        if value == 1:  # local
            return False
        elif value == 2 and "count" in self.optionMap:
            count = int(self.optionMap.get("count"))
            minCount = min((app.getConfigValue("queue_system_min_test_count") for app in allApps))
            return count >= minCount
        else:
            if "reconnect" in self.optionMap:
                # GUI gives us a numeric value, can also get it from the command line
                return self.optionValue("reconnfull") in ["2", "grid"]
            else:
                for app in allApps:
                    if any(("dbtext-setup-" + pathName.lower() in self.optionMap for pathName in app.getConfigValue("dbtext_database_path"))):
                        return False
                return True

    def getRemoteTestTmpDir(self, test):
        qs = masterprocess.QueueSystemServer.instance
        if qs:
            fromQs = qs.getRemoteTestTmpDir(test)
            if fromQs:
                return fromQs
        return default.Config.getRemoteTestTmpDir(self, test)

    def hasExplicitInterface(self):
        return self.slaveRun() or default.Config.hasExplicitInterface(self)

    def slaveRun(self):
        return "slave" in self.optionMap

    def getWriteDirectoryName(self, app):
        return self.optionMap.get("slave") or default.Config.getWriteDirectoryName(self, app)

    def getLocalWriteDirectoryName(self, app):
        return default.Config.getWriteDirectoryName(self, app)

    def noFileAdvice(self):
        if self.useQueueSystem:
            return "Try re-running the test, and either use local mode, or check the box for keeping\n" + \
                   "successful test files under the Running/Advanced tab in the static GUI"
        else:
            return ""

    def getExtraVersions(self, app):
        if self.slaveRun():
            if self.isReconnecting():
                fromConfig = self.getExtraVersionsFromConfig(app)
                # This has side-effects which we need, but we shouldn't actually have any extra versions...
                self.reconnectConfig.getExtraVersions(app, fromConfig)
            return []
        else:
            return default.Config.getExtraVersions(self, app)

    def keepTemporaryDirectories(self):
        if self.hasKeeptmpFlag():
            return True
        if self.slaveRun():
            if self.useCloud:
                return False
            elif "keepslave" in self.optionMap or "rerun" in self.optionMap:
                return True
        return default.Config.keepTemporaryDirectories(self)

    def cleanPreviousTempDirs(self):
        return not self.slaveRun() and default.Config.cleanPreviousTempDirs(self)

    def readsTestStateFiles(self):
        # Reads the data via a socket, need to set up categories
        return default.Config.readsTestStateFiles(self) or (self.useQueueSystem and not self.slaveRun())

    def cleanSlaveFiles(self, test):
        if self.useCloud:
            # Don't keep anything on a remote system, we've transferred it all back anyhow...
            writeDir = test.getDirectory(temporary=1)
            plugins.rmtree(writeDir)
        elif test.state.hasSucceeded():
            writeDir = test.getDirectory(temporary=1)
            # If we've made screenshots, keep them, we might want to look at them...
            if os.path.isdir(os.path.join(writeDir, "screenshots")):
                for f in os.listdir(writeDir):
                    if f != "screenshots":
                        plugins.removePath(os.path.join(writeDir, f))
            else:
                plugins.rmtree(writeDir)
        else:
            for dataFile in self.getDataFiles(test):
                fullPath = test.makeTmpFileName(dataFile, forComparison=0)
                plugins.removePath(fullPath)

    @classmethod
    def cleanEmptyDirectories(cls, path):
        try:
            files = os.listdir(path)
        except OSError:
            # Other slaves are potentially doing this at the same time, potential for race conditions
            return False
        subdirs = []
        for f in files:
            fullpath = os.path.join(path, f)
            if os.path.isdir(fullpath):
                subdirs.append(fullpath)
        foundFiles = len(subdirs) != len(files)
        if not foundFiles:
            for subdir in subdirs:
                foundFiles |= cls.cleanEmptyDirectories(subdir)

        if not foundFiles:
            try:
                os.rmdir(path)
            except OSError:
                # Other slaves are potentially doing this at the same time, potential for race conditions
                pass
        return foundFiles

    def getDataFiles(self, test):
        return test.getDataFileNames()

    def _cleanWriteDirectory(self, suite):
        if self.slaveRun():
            # Slaves leave their files for the master process to clean
            for test in suite.testCaseList():
                self.cleanSlaveFiles(test)
            if self.useCloud:
                self.cleanEmptyDirectories(suite.app.writeDirectory)
        else:
            default.Config._cleanWriteDirectory(self, suite)

    def getTextResponder(self):
        if self.useQueueSystem:
            return masterprocess.MasterInteractiveResponder
        else:
            return default.Config.getTextResponder(self)

    def getSlaveSwitches(self):
        return ["c", "b", "trace", "ignorecat", "ignorefilters", "delay", "screenshot", "gui", "td",
                "rectraffic", "keeptmp", "keepslave", "reconnect", "reconnfull", "rerun"]

    def getExecHostFinder(self):
        if self.slaveRun():
            return slavejobs.FindExecutionHostsInSlave()
        else:
            return default.Config.getExecHostFinder(self)

    def expandExternalEnvironment(self):
        return not self.useQueueSystem or self.slaveRun()

    def getRunDescription(self, test):
        basicDescription = default.Config.getRunDescription(self, test)
        if self.useQueueSystem:
            return basicDescription + "\n" + masterprocess.QueueSystemServer.instance.getQueueSystemCommand(test)
        else:
            return basicDescription

    def getSlaveResponderClasses(self):
        classes = [slavejobs.RedirectLogResponder] if not self.useCloud else []
        slavejobs.SocketResponder.synchFiles = self.useCloud
        classes += [slavejobs.SocketResponder, slavejobs.SlaveActionRunner]
        if os.name == "posix" and not self.isActionReplay():
            classes.append(VirtualDisplayResponder)
        classes.append(ApplicationEventResponder)
        return classes

    def _getResponderClasses(self, allApps, *args):
        self.useQueueSystem = self.calculateUseQueueSystem(allApps)
        if self.useQueueSystem and not self.cloudUseConsistent(allApps):
            raise plugins.TextTestError(
                "No support currently for running ec2cloud tests at the same time as tests with other queue systems")

        if self.slaveRun():
            return self.getSlaveResponderClasses()
        else:
            return default.Config._getResponderClasses(self, allApps, *args)

    def getThreadActionClasses(self):
        if self.useQueueSystem:
            return [self.getSlaveServerClass(), self.getQueueServerClass()]  # don't use the action runner at all!
        else:
            return default.Config.getThreadActionClasses(self)

    def getQueueServerClass(self):
        return masterprocess.QueueSystemServer

    def getSlaveServerClass(self):
        return masterprocess.SlaveServerResponder

    def useVirtualDisplay(self):
        if self.useQueueSystem and not self.slaveRun():
            return False
        else:
            return default.Config.useVirtualDisplay(self)

    def getTestRunVariables(self):
        return ["JOB_ID"] if self.slaveRun() else []

    def getTextDisplayResponderClass(self):
        if self.useQueueSystem:
            return masterprocess.MasterTextResponder
        else:
            return default.Config.getTextDisplayResponderClass(self)

    def getTestRunner(self):
        if self.slaveRun():
            return slavejobs.RunTestInSlave()
        else:
            return default.Config.getTestRunner(self)

    def showExecHostsInFailures(self, app):
        # Always show execution hosts, many different ones are used
        return True

    def hasAutomaticCputimeChecking(self, app):
        return default.Config.hasAutomaticCputimeChecking(self, app) or \
            len(app.getCompositeConfigValue("performance_test_resource", "cputime")) > 0

    def getSubmissionRules(self, test):
        if self.slaveRun():
            return masterprocess.BasicSubmissionRules(test)
        else:
            return masterprocess.TestSubmissionRules(self.optionMap, test)

    def getProxySubmissionRulesClass(self):
        return masterprocess.ProxySubmissionRules

    def getProxySubmissionRules(self, test):
        proxyResources = test.getConfigValue("queue_system_proxy_resource")
        if proxyResources:
            return self.getProxySubmissionRulesClass()(self.optionMap, test)

    def getMachineInfoFinder(self):
        if self.slaveRun():
            return slavejobs.SlaveMachineInfoFinder()
        else:
            return default.Config.getMachineInfoFinder(self)

    def setApplicationDefaults(self, app):
        default.Config.setApplicationDefaults(self, app)
        app.setConfigDefault("default_queue", "texttest_default", "Which queue to submit tests to by default")
        app.setConfigDefault("min_time_for_performance_force", -1,
                             "Minimum CPU time for test to always run on performance machines")
        app.setConfigDefault("queue_system_module", "local",
                             "Which queue system (grid engine) set-up to use. (\"local\", \"SGE\" or \"LSF\")")
        app.setConfigDefault("performance_test_resource", {"default": []},
                             "Resources to request from queue system for performance testing")
        app.setConfigDefault("parallel_environment_name", "*",
                             "(SGE) Which SGE parallel environment to use when SUT is parallel")
        app.setConfigDefault("queue_system_max_capacity", self.defaultMaxCapacity,
                             "Maximum possible number of parallel tests to run")
        app.setConfigDefault("queue_system_max_reruns", {
                             "default": self.defaultMaxReruns}, "Maximum number of times to rerun tests due to known bugs")
        app.setConfigDefault("queue_system_min_test_count", 0,
                             "Minimum number of tests before it's worth submitting them to the grid")
        app.setConfigDefault("queue_system_resource", [],
                             "Grid engine resources required to locate test execution machines")
        app.setConfigDefault("queue_system_environment", [
        ], "Environment variables (external to TextTest) whose values need to be transferred to the execution machine")
        app.setConfigDefault("queue_system_processes", 1,
                             "Number of processes the grid engine should reserve for tests")
        app.setConfigDefault("queue_system_submit_args", "",
                             "Additional arguments to provide to grid engine submission command")
        app.setConfigDefault("queue_system_proxy_executable", "",
                             "Executable to run as a proxy for the real test program")
        app.setConfigDefault("queue_system_proxy_resource", [],
                             "Grid engine resources required to locate machine to run proxy process")
        app.setConfigDefault("queue_system_core_file_location", "",
                             "System-wide location for core files from grid jobs, in case TEXTTEST_TMP is generated")
        app.addConfigEntry("builtin", "proxy_options", "definition_file_stems")

    def setDependentConfigDefaults(self, app):
        # Cloud doesn't work without a remote copy program
        # which should be rsync or a similar program. Use rsync as default.
        if app.getConfigValue("queue_system_module") == "ec2cloud" and not app.getConfigValue("remote_copy_program"):
            app.setConfigDefault("remote_copy_program", "rsync")
        return default.Config.setDependentConfigDefaults(self, app)


class DocumentEnvironment(default.DocumentEnvironment):
    def setUpApplication(self, app):
        default.DocumentEnvironment.setUpApplication(self, app)
        vars = self.findAllVariables(app, ["QUEUE_SYSTEM_"], os.path.dirname(__file__))
        print("The following variables can be used in environment files :")
        for key in sorted(vars.keys()):
            argList = vars[key]
            print(key + "|" + "|".join(argList))
