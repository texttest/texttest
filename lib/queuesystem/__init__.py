
"""
Module for the queuesystem configuration, i.e. using grid engines to run tests in parallel
"""

import masterprocess, slavejobs, utils, os, default, plugins
from default.virtualdisplay import VirtualDisplayResponder
from default.pyusecase_interface import ApplicationEventResponder

def getConfig(optionMap):
    return QueueSystemConfig(optionMap)
            
class QueueSystemConfig(default.Config):
    def __init__(self, *args):
        default.Config.__init__(self, *args)
        self.useQueueSystem = None
        
    def addToOptionGroups(self, apps, groups):
        default.Config.addToOptionGroups(self, apps, groups)
        minTestCount = min((app.getConfigValue("queue_system_min_test_count") for app in apps))
        for group in groups:
            if group.name.startswith("Basic"):
                options = [ "Always", "Never" ]
                qsName = "grid"
                for app in apps:
                    currName = utils.queueSystemName(app)
                    if currName:
                        qsName = currName
                descriptions = [ "Submit the tests to " + qsName,
                                 "Run the tests directly, not using " + qsName ] 
                defaultValue = 0
                if minTestCount:
                    options.append("If enough tests")
                    descriptions.append("Submit the tests to " + qsName + " only if " + str(minTestCount) + " or more are selected.")
                    defaultValue = 2
                group.addSwitch("l", "Use grid", value=defaultValue, options=options, description=descriptions)
            elif group.name.startswith("Advanced"):
                group.addOption("R", "Request grid resource", possibleValues = self.getPossibleResources())
                group.addOption("q", "Request grid queue", possibleValues = self.getPossibleQueues())
                group.addSwitch("keepslave", "Keep data files and successful tests until termination")
                group.addSwitch("perf", "Run on performance machines only")
            elif group.name.startswith("Invisible"):
                group.addOption("slave", "Private: used to submit slave runs remotely")
                group.addOption("servaddr", "Private: used to submit slave runs remotely")

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
        return [] # placeholders for derived configurations
    def getPossibleResources(self):
        return []

    def getLocalRunArgs(self):
        return [ "gx", "s", "coll", "record", "autoreplay" ]
    
    def calculateUseQueueSystem(self, allApps):
        for localFlag in self.getLocalRunArgs():
            if self.optionMap.has_key(localFlag):
                return False

        if self.optionMap.has_key("l"):
            value = self.optionValue("l")
            if value is None or value == "1":
                return False
            elif value == "2" and self.optionMap.has_key("count"):
                count = int(self.optionMap.get("count"))
                minCount = min((app.getConfigValue("queue_system_min_test_count") for app in allApps))
                return count >= minCount

        if self.optionMap.has_key("reconnect"):
            # GUI gives us a numeric value, can also get it from the command line
            return self.optionValue("reconnfull") in [ "2", "grid" ]
        else:
            return True
    
    def hasExplicitInterface(self):
        return self.slaveRun() or default.Config.hasExplicitInterface(self)
    def slaveRun(self):
        return self.optionMap.has_key("slave")
    def getWriteDirectoryName(self, app):
        slaveDir = self.optionMap.get("slave")
        if slaveDir:
            return slaveDir
        else:
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
                return self.reconnectConfig.getExtraVersions(app, fromConfig)
            else:
                return []
        else:
            return default.Config.getExtraVersions(self, app)

    def keepTemporaryDirectories(self):
        return default.Config.keepTemporaryDirectories(self) or (self.slaveRun() and self.optionMap.has_key("keepslave"))

    def cleanPreviousTempDirs(self):
        return not self.slaveRun() and default.Config.cleanPreviousTempDirs(self)

    def readsTestStateFiles(self):
        # Reads the data via a socket, need to set up categories
        return default.Config.readsTestStateFiles(self) or (self.useQueueSystem and not self.slaveRun())

    def cleanSlaveFiles(self, test):
        if test.state.hasSucceeded():
            writeDir = test.getDirectory(temporary=1)
            plugins.rmtree(writeDir)
        else:
            for dataFile in test.getDataFileNames():
                fullPath = test.makeTmpFileName(dataFile, forComparison=0)
                plugins.removePath(fullPath)
                
    def _cleanWriteDirectory(self, suite):
        if self.slaveRun():
            # Slaves leave their files for the master process to clean
            for test in suite.testCaseList():
                self.cleanSlaveFiles(test)
        else:
            default.Config._cleanWriteDirectory(self, suite)

    def getTextResponder(self):
        if self.useQueueSystem:
            return masterprocess.MasterInteractiveResponder
        else:
            return default.Config.getTextResponder(self)
    
    def getSlaveSwitches(self):
        return [ "c", "b", "trace", "ignorecat", "ignorefilters", "actrep",
                 "rectraffic", "keeptmp", "keepslave", "x", "reconnect", "reconnfull" ]

    def getExecHostFinder(self):
        if self.slaveRun():
            return slavejobs.FindExecutionHostsInSlave()
        else:
            return default.Config.getExecHostFinder(self)

    def getRunDescription(self, test):
        basicDescription = default.Config.getRunDescription(self, test)
        if self.useQueueSystem:
            return basicDescription + "\n" + masterprocess.QueueSystemServer.instance.getQueueSystemCommand(test)
        else:
            return basicDescription
        
    def getSlaveResponderClasses(self):
        classes = [ slavejobs.SocketResponder, slavejobs.SlaveActionRunner ]
        if not self.isActionReplay():
            classes.append(VirtualDisplayResponder)
        classes.append(ApplicationEventResponder)
        return classes

    def _getResponderClasses(self, allApps, *args):
        self.useQueueSystem = self.calculateUseQueueSystem(allApps)
        if self.slaveRun():
            return self.getSlaveResponderClasses()
        else:
            return default.Config._getResponderClasses(self, allApps, *args)
        
    def getThreadActionClasses(self):
        if self.useQueueSystem:
            return [ self.getSlaveServerClass(), self.getQueueServerClass() ] # don't use the action runner at all!
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
        return masterprocess.SubmissionRules(self.optionMap, test)

    def getMachineInfoFinder(self):
        if self.slaveRun():
            return slavejobs.SlaveMachineInfoFinder()
        else:
            return default.Config.getMachineInfoFinder(self)

    def printHelpDescription(self):
        print """The queuesystem configuration is a published configuration, 
               documented online at http://www.texttest.org/TextTest/docs/queuesystem"""

    def setApplicationDefaults(self, app):
        default.Config.setApplicationDefaults(self, app)
        app.setConfigDefault("default_queue", "texttest_default", "Which queue to submit tests to by default")
        app.setConfigDefault("min_time_for_performance_force", -1, "Minimum CPU time for test to always run on performance machines")
        app.setConfigDefault("view_file_on_remote_machine", { "default" : 0 }, "Do we try to start viewing programs on the test execution machine?")
        app.setConfigDefault("queue_system_module", "SGE", "Which queue system (grid engine) software to use. (\"SGE\" or \"LSF\")")
        app.setConfigDefault("performance_test_resource", { "default" : [] }, "Resources to request from queue system for performance testing")
        app.setConfigDefault("parallel_environment_name", "*", "(SGE) Which SGE parallel environment to use when SUT is parallel")
        app.setConfigDefault("queue_system_max_capacity", 100000, "Maximum possible number of parallel similar jobs in the available grid")
        app.setConfigDefault("queue_system_min_test_count", 0, "Minimum number of tests before it's worth submitting them to the grid")
        

class DocumentEnvironment(default.DocumentEnvironment):
    def setUpApplication(self, app):
        default.DocumentEnvironment.setUpApplication(self, app)
        vars = self.findAllVariables(app, [ "QUEUE_SYSTEM_" ], os.path.dirname(__file__))
        print "The following variables can be used in environment files :"
        for key in sorted(vars.keys()):
            argList = vars[key]
            print key + "|" + "|".join(argList)
