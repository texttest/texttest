import os, sys, default, sandbox, unixonly, performance, plugins, socket, subprocess, operator, signal
from Queue import Queue, Empty
from SocketServer import TCPServer, StreamRequestHandler
from time import sleep
from ndict import seqdict
from copy import copy, deepcopy
from cPickle import dumps
from respond import Responder, TextDisplayResponder, InteractiveResponder
from traffic_cmd import sendServerState
from knownbugs import CheckForBugs
from actionrunner import ActionRunner, BaseActionRunner
from types import StringType

plugins.addCategory("abandoned", "abandoned", "were abandoned")

def getConfig(optionMap):
    return QueueSystemConfig(optionMap)

def queueSystemName(app):
    return app.getConfigValue("queue_system_module")

# Use a non-monitoring runTest, but the rest from unix
class RunTestInSlave(unixonly.RunTest):
    def getBriefText(self, execMachines):
        return "RUN (" + ",".join(execMachines) + ")"
    def getUserSignalKillInfo(self, test, userSignalNumber):
        moduleName = queueSystemName(test.app).lower()
        command = "from " + moduleName + " import getUserSignalKillInfo as _getUserSignalKillInfo"
        exec command
        return _getUserSignalKillInfo(userSignalNumber, self.getExplicitKillInfo)

class FindExecutionHosts(sandbox.FindExecutionHosts):
    def getExecutionMachines(self, test):
        moduleName = queueSystemName(test.app).lower()
        command = "from " + moduleName + " import getExecutionMachines as _getExecutionMachines"
        exec command
        return _getExecutionMachines()

def socketSerialise(test):
    return test.app.name + test.app.versionSuffix() + ":" + test.getRelPath()

class SocketResponder(Responder,plugins.Observable):
    def __init__(self, optionMap, *args):
        Responder.__init__(self)
        plugins.Observable.__init__(self)
        self.serverAddress = self.getServerAddress(optionMap)
    def getServerAddress(self, optionMap):
        servAddrStr = optionMap.get("servaddr", os.getenv("TEXTTEST_MIM_SERVER"))
        if not servAddrStr:
            raise plugins.TextTestError, "Cannot run slave, no server address has been provided to send results to!"
        host, port = servAddrStr.split(":")
        return host, int(port)
    def connect(self, sendSocket):
        for attempt in range(5):
            try:
                sendSocket.connect(self.serverAddress)
                return
            except socket.error:
                sleep(1)
        print "Trouble connecting to", self.serverAddress
        sendSocket.connect(self.serverAddress)
    def notifyLifecycleChange(self, test, state, changeDesc):
        testData = socketSerialise(test)
        pickleData = dumps(state)
        fullData = str(os.getpid()) + os.linesep + testData + os.linesep + pickleData
        for attempt in range(5):
            try:
                self.sendData(fullData)
                return
            except socket.error:
                sleep(1)
                
        print "Terminating as failed to communicate with master process, got error :\n" + plugins.getExceptionString()
    def sendData(self, fullData):
        sendSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connect(sendSocket)
        sendSocket.sendall(fullData)
        sendSocket.shutdown(socket.SHUT_WR)
        response = sendSocket.makefile().read()
        sendSocket.close()
        if len(response) > 0:
            appDesc, testPath = response.strip().split(":")
            appParts = appDesc.split(".")
            self.notify("ExtraTest", testPath, appParts[0], appParts[1:])
            
class QueueSystemConfig(default.Config):
    def addToOptionGroups(self, app, groups):
        default.Config.addToOptionGroups(self, app, groups)
        queueSystem = queueSystemName(app)
        for group in groups:
            if group.name.startswith("Basic"):
                group.addSwitch("l", "", value = 0, options = ["Submit tests to " + queueSystem, "Run tests locally"])
            elif group.name.startswith("Advanced"):
                group.addOption("R", "Request " + queueSystem + " resource", possibleValues = self.getPossibleResources(queueSystem))
                group.addOption("q", "Request " + queueSystem + " queue", possibleValues = self.getPossibleQueues(queueSystem))
                group.addSwitch("keepslave", "Keep data files and successful tests until termination")
                group.addSwitch("perf", "Run on performance machines only")
            elif group.name.startswith("Invisible"):
                group.addOption("slave", "Private: used to submit slave runs remotely")
                group.addOption("servaddr", "Private: used to submit slave runs remotely")
    def getPossibleQueues(self, queueSystem):
        return [] # placeholders for derived configurations
    def getPossibleResources(self, queueSystem):
        return []
    def useQueueSystem(self):
        for localFlag in [ "reconnect", "l", "gx", "s", "coll", "record", "autoreplay" ]:
            if self.optionMap.has_key(localFlag):
                return False
        return True
    def slaveRun(self):
        return self.optionMap.has_key("slave")
    def getWriteDirectoryName(self, app):
        slaveDir = self.optionMap.get("slave")
        if slaveDir:
            return slaveDir
        else:
            return default.Config.getWriteDirectoryName(self, app)
    def noFileAdvice(self):
        if self.useQueueSystem():
            return "Try re-running the test, and either use local mode, or check the box for keeping\n" + \
                   "successful test files under the Running/Advanced tab in the static GUI"
        else:
            return ""
    def useExtraVersions(self):
        return not self.slaveRun()
    def keepTemporaryDirectories(self):
        return default.Config.keepTemporaryDirectories(self) or (self.slaveRun() and self.optionMap.has_key("keepslave"))
    def cleanPreviousTempDirs(self):
        return not self.slaveRun() and default.Config.cleanPreviousTempDirs(self)
    def cleanSlaveFiles(self, test):
        if test.state.hasSucceeded():
            writeDir = test.getDirectory(temporary=1)
            if os.path.isdir(writeDir):
                plugins.rmtree(writeDir)
        else:
            for dataFile in test.getDataFileNames():
                fullPath = test.makeTmpFileName(dataFile, forComparison=0)
                if os.path.isfile(fullPath) or os.path.islink(fullPath):
                    os.remove(fullPath)
                elif os.path.isdir(fullPath):
                    plugins.rmtree(fullPath)
                
    def _cleanWriteDirectory(self, suite):
        if self.slaveRun():
            # Slaves leave their files for the master process to clean
            for test in suite.testCaseList():
                self.cleanSlaveFiles(test)
        else:
            default.Config._cleanWriteDirectory(self, suite)
    def getTextResponder(self):
        if self.useQueueSystem():
            return MasterInteractiveResponder
        else:
            return InteractiveResponder
    
    def getSlaveSwitches(self):
        return [ "c", "b", "trace", "ignorecat", "actrep", "rectraffic", "keeptmp", "keepslave" ]
    def getExecHostFinder(self):
        if self.slaveRun():
            return FindExecutionHosts()
        else:
            return default.Config.getExecHostFinder(self)
    def getSlaveResponderClasses(self):
        classes = [ SocketResponder, default.ActionRunner ]
        if not self.isActionReplay():
            classes.append(unixonly.VirtualDisplayResponder)
        return classes

    def getResponderClasses(self, allApps):
        if self.slaveRun():
            return self.getSlaveResponderClasses()
        else:
            return default.Config.getResponderClasses(self, allApps)
    def getThreadActionClasses(self):
        if self.useQueueSystem():
            return [ self.getSlaveServerClass(), self.getQueueServerClass() ] # don't use the action runner at all!
        else:
            return default.Config.getThreadActionClasses(self)
    def getQueueServerClass(self):
        return QueueSystemServer
    def getSlaveServerClass(self):
        return SlaveServerResponder
    def useVirtualDisplay(self):
        if self.useQueueSystem() and not self.slaveRun():
            return False
        else:
            return default.Config.useVirtualDisplay(self)
        
    def getTextDisplayResponderClass(self):
        if self.useQueueSystem():
            return MasterTextResponder
        else:
            return default.Config.getTextDisplayResponderClass(self)
    def getTestRunner(self):
        if self.slaveRun():
            return RunTestInSlave(self.hasAutomaticCputimeChecking)
        else:
            return default.Config.getTestRunner(self)
    def showExecHostsInFailures(self):
        # Always show execution hosts, many different ones are used
        return 1
    def hasAutomaticCputimeChecking(self, app):
        return default.Config.hasAutomaticCputimeChecking(self, app) or \
               len(app.getCompositeConfigValue("performance_test_resource", "cputime")) > 0
    def getSubmissionRules(self, test):
        return SubmissionRules(self.optionMap, test)
    def getMachineInfoFinder(self):
        if self.slaveRun():
            return MachineInfoFinder()
        else:
            return default.Config.getMachineInfoFinder(self)
    def getDefaultMaxCapacity(self):
        return 100000
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
        app.setConfigDefault("queue_system_max_capacity", self.getDefaultMaxCapacity(), "Maximum possible number of parallel similar jobs in the available grid")

class SubmissionRules:
    def __init__(self, optionMap, test):
        self.test = test
        self.optionMap = optionMap
        self.envResource = self.getEnvironmentResource()
        self.processesNeeded = self.getProcessesNeeded()
    def getEnvironmentResource(self):
        return os.path.expandvars(self.test.getEnvironment("QUEUE_SYSTEM_RESOURCE", ""))
    def getProcessesNeeded(self):
        return self.test.getEnvironment("QUEUE_SYSTEM_PROCESSES", "1")
    def getJobName(self):
        path = self.test.getRelPath()
        parts = path.split("/")
        parts.reverse()
        return "Test-" + ".".join(parts) + "-" + repr(self.test.app).replace(" ", "_")
    def getSubmitSuffix(self):
        name = queueSystemName(self.test)
        queue = self.findQueue()
        if queue:
            return "to " + name + " queue " + queue
        else:
            return "to default " + name + " queue"
    def getParallelEnvironment(self):
        return self.test.getConfigValue("parallel_environment_name")
    def findResourceList(self):
        resourceList = []
        if self.optionMap.has_key("R"):
            resourceList.append(self.optionMap["R"])
        if len(self.envResource):
            resourceList.append(self.envResource)
        if self.forceOnPerformanceMachines():
            resources = self.getConfigValue("performance_test_resource")
            for resource in resources:
                resourceList.append(resource)
        return resourceList
    def getConfigValue(self, configKey):
        configDict = self.test.getConfigValue(configKey)
        defVal = configDict.get("default")
        if len(defVal) > 0:
            return defVal
        for val in configDict.values():
            if len(val) > 0 and val[0] != "any" and val[0] != "none":
                return val
        return []
    def findPriority(self):
        return 0
    def findQueue(self):
        if self.optionMap.has_key("q"):
            return self.optionMap["q"]
        configQueue = self.test.app.getConfigValue("default_queue")
        if configQueue != "texttest_default":
            return configQueue

        return self.findDefaultQueue()
    def findDefaultQueue(self):
        return ""
    def findMachineList(self):
        if not self.forceOnPerformanceMachines():
            return []
        performanceMachines = self.getConfigValue("performance_test_machine")
        if len(performanceMachines) == 0:
            return []

        return performanceMachines
    def getJobFiles(self):
        jobName = self.getJobName()
        return jobName + ".log", jobName + ".errors"
    def forceOnPerformanceMachines(self):
        if self.optionMap.has_key("perf"):
            return 1

        minTimeForce = plugins.getNumberOfSeconds(str(self.test.getConfigValue("min_time_for_performance_force")))
        if minTimeForce >= 0 and performance.getTestPerformance(self.test) > minTimeForce:
            return 1
        # If we haven't got a log_file yet, we should do this so we collect performance reliably
        logFile = self.test.getFileName(self.test.getConfigValue("log_file"))
        return logFile is None
    def allowsReuse(self, newRules):
        return self.findResourceList() == newRules.findResourceList() and \
               self.getProcessesNeeded() == newRules.getProcessesNeeded()

class SlaveRequestHandler(StreamRequestHandler):
    def handle(self):
        identifier = self.rfile.readline().strip()
        if identifier == "TERMINATE_SERVER":
            return
        clientHost, clientPort = self.client_address
        # Don't use port, it changes all the time
        self.handleRequestFromHost(self.getHostName(clientHost), identifier)
    def handleRequestFromHost(self, hostname, identifier):
        testString = self.rfile.readline().strip()
        test = self.server.getTest(testString)
        if self.server.clientCorrect(test, (hostname, identifier)):
            if not test.state.isComplete(): # we might have killed it already...
                oldBt = test.state.briefText
                test.loadState(self.rfile)
                self.connection.shutdown(socket.SHUT_RD)
                self.server.diag.info("Changed from '" + oldBt + "' to '" + test.state.briefText + "'")
                if test.state.isComplete():
                    newTest = QueueSystemServer.instance.getTestForReuse(test)
                    if newTest:
                        self.wfile.write(socketSerialise(newTest))
                else:
                    self.server.storeClient(test, (hostname, identifier))
                self.connection.shutdown(socket.SHUT_WR)
        else:
            expectedHost, expectedPid = self.server.testClientInfo[test]
            sys.stderr.write("WARNING: Unexpected TextTest slave for " + repr(test) + " connected from " + \
                             hostname + " (process " + identifier + ")\n")
            sys.stderr.write("Slave already registered from " + expectedHost + " (process " + expectedPid + ")\n")
            sys.stderr.write("Ignored all communication from this unexpected TextTest slave\n")
            sys.stderr.flush()
            self.connection.shutdown(socket.SHUT_RDWR)
            
    def getHostName(self, ipAddress):
        return socket.gethostbyaddr(ipAddress)[0].split(".")[0]

class SlaveServerResponder(Responder, TCPServer):
    def __init__(self, *args):
        Responder.__init__(self, *args)
        TCPServer.__init__(self, (socket.gethostname(), 0), self.handlerClass())
        self.testMap = {}
        self.testClientInfo = {}
        self.diag = plugins.getDiagnostics("Slave Server")
        self.terminate = False
        # Socket may have to be around for some time,
        # enable the keepalive option in the hope that that will make it more resilient
        # to network problems
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, True)
        
    def addSuites(self, *args):
        # use this as an opportunity to broadcast our address
        serverAddress = self.getAddress()
        self.diag.info("Starting slave server at " + serverAddress)
        # Tell the submission code where we are
        QueueSystemServer.instance.setSlaveServerAddress(serverAddress)

    def handlerClass(self):
        return SlaveRequestHandler
    def canBeMainThread(self):
        return False # We wait for sockets and stuff
    def run(self):
        while not self.terminate:
            self.diag.info("Waiting for a new request...")
            self.handle_request()
        
        self.diag.info("Terminating slave server")
    def notifyAllRead(self, suites):
        if len(self.testMap) == 0:
            self.notifyAllComplete()
            
    def notifyAllComplete(self):
        self.diag.info("Notified all complete, shutting down soon...")
        self.terminate = True
        sendSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sendSocket.connect(self.socket.getsockname())
        sendSocket.sendall("TERMINATE_SERVER\n")
        sendSocket.close()
    def getAddress(self):
        host, port = self.socket.getsockname()
        return host + ":" + str(port)
    def notifyAdd(self, test, initial):
        if test.classId() == "test-case":
            self.storeTest(test)
    def storeTest(self, test):
        testPath = test.getRelPath()
        testApp = test.app.name + test.app.versionSuffix()
        if not self.testMap.has_key(testApp):
            self.testMap[testApp] = {}
        self.testMap[testApp][testPath] = test
    def getTest(self, testString):
        self.diag.info("Received request for '" + testString + "'")
        appName, testPath = testString.split(":")
        return self.testMap[appName][testPath]
    def clientCorrect(self, test, clientInfo):
        # Only allow one client per test!
        if self.testClientInfo.has_key(test):
            return self.testClientInfo[test] == clientInfo
        else:
            return True
    def storeClient(self, test, clientInfo):
        self.testClientInfo[test] = clientInfo

class MasterTextResponder(TextDisplayResponder):
    def notifyComplete(self, test):
        print "S:", test, test.state.description()

# Don't indent, and use the unique name rather than repr()
class MasterInteractiveResponder(InteractiveResponder):
    def describeSave(self, test, saveDesc):
        print "Saving", repr(test) + saveDesc
    def describeViewOptions(self, test, options):
        print options

class QueueSystemServer(BaseActionRunner):
    instance = None
    def __init__(self, optionMap, allApps):
        BaseActionRunner.__init__(self, optionMap, plugins.getDiagnostics("Queue System Submit"))
        # queue for putting tests when we couldn't reuse the originals
        self.reuseFailureQueue = Queue()
        self.testCount = 0
        self.testsSubmitted = 0
        self.maxCapacity = 100000 # infinity, sort of
        self.jobs = seqdict()
        self.submissionRules = {}
        self.killedJobs = {}
        self.queueSystems = {}
        self.reuseOnly = False
        self.submitAddress = None
        QueueSystemServer.instance = self
    def addSuites(self, suites):
        for suite in suites:
            suite.app.makeWriteDirectory("slavelogs")
            currCap = suite.getConfigValue("queue_system_max_capacity")
            if currCap < self.maxCapacity:
                self.maxCapacity = currCap
            print "Using", queueSystemName(suite.app), "queues for", suite.app.description(includeCheckout=True)
    def setSlaveServerAddress(self, address):
        self.submitAddress = os.getenv("TEXTTEST_MIM_SERVER", address)
        self.testQueue.put("TextTest slave server started on " + address)

    def addTest(self, test):
        self.testCount += 1
        queue = self.findQueueForTest(test)
        if queue:
            queue.put(test)
    def findQueueForTest(self, test):
        # If we've gone into reuse mode and there are no active tests for reuse, use the "reuse failure queue"
        if self.reuseOnly and self.testsSubmitted == 0:
            return self.reuseFailureQueue
        else:
            return self.testQueue
                
    def handleLocalError(self, test, previouslySubmitted):
        self.handleErrorState(test, previouslySubmitted)
        if self.testCount == 0 or (self.reuseOnly and self.testsSubmitted == 0):
            self.diag.info("Submitting terminators after local error")
            self.submitTerminators()
    def submitTerminators(self):
        # snap out of our loop if this was the last one. Rely on others to manage the test queue
        self.reuseFailureQueue.put(None)
    def getTestForReuse(self, test):
        # Pick up any test that matches the current one's resource requirements
        if not self.exited:
            newTest = self.getTest(block=False)
            if newTest:
                if self.allowReuse(test, newTest):
                    self.jobs[newTest] = self.getJobInfo(test)
                    if self.testCount > 1:
                        self.testCount -= 1
                        self.diag.info("Reusing slave for " + repr(newTest) + self.remainStr())
                    else:
                        self.diag.info("Last test : submitting terminators")
                        # Don't allow test count to drop to 0 here, can cause race conditions
                        self.submitTerminators() 
                    return newTest
                else:
                    self.reuseFailureQueue.put(newTest)
                
        # Allowed a submitted job to terminate
        self.testsSubmitted -= 1
        self.diag.info("No reuse for " + repr(test) + " : " + repr(self.testsSubmitted) + " tests still submitted")
        if self.exited and self.testsSubmitted == 0:
            self.diag.info("Forcing termination")
            self.submitTerminators()
    def allowReuse(self, oldTest, newTest):
        oldRules = self.getSubmissionRules(oldTest)
        newRules = self.getSubmissionRules(newTest)
        return oldRules.allowsReuse(newRules)
    def getSubmissionRules(self, test):
        if self.submissionRules.has_key(test):
            return self.submissionRules[test]
        else:
            submissionRules = test.app.getSubmissionRules(test)
            self.submissionRules[test] = submissionRules
            return submissionRules
    def getTest(self, block):
        testOrStatus = self.getItemFromQueue(self.testQueue, block)
        if not testOrStatus:
            return
        if type(testOrStatus) == StringType:
            self.sendServerState(testOrStatus)
            return self.getTest(block)
        else:
            return testOrStatus
    def sendServerState(self, state):
        self.diag.info("Sending server state '" + state + "'")
        sendServerState(state)
    def getTestForRunNormalMode(self):
        self.reuseOnly = False
        reuseFailure = self.getItemFromQueue(self.reuseFailureQueue, block=False)
        if reuseFailure:
            self.diag.info("Found a reuse failure...")
            return reuseFailure
        else:
            self.diag.info("Waiting for new tests...")
            return self.getTest(block=True)
    def getTestForRunReuseOnlyMode(self):
        self.reuseOnly = True
        self.diag.info("Waiting for reuse failures...")
        reuseFailure = self.getItemFromQueue(self.reuseFailureQueue, block=True)
        if reuseFailure:
            return reuseFailure
        elif self.testCount > 0 and self.testsSubmitted < self.maxCapacity:
            # Try again, the capacity situation has changed...
            return self.getTestForRunNormalMode()

    def getTestForRun(self):
        if self.testCount == 0 or (self.testsSubmitted < self.maxCapacity):
            return self.getTestForRunNormalMode()
        else:
            return self.getTestForRunReuseOnlyMode()
    
    def cleanup(self):
        self.sendServerState("Completed submission of all tests")
    def remainStr(self):
        return " : " + str(self.testCount) + " tests remain."
    def runTest(self, test):
        if test.state.isComplete():
            return
    
        submissionRules = test.app.getSubmissionRules(test)
        command = self.getSlaveCommand(test, submissionRules)
        print "Q: Submitting", test, submissionRules.getSubmitSuffix()
        sys.stdout.flush()
        self.jobs[test] = [] # Preliminary jobs aren't interesting any more
        if not self.submitJob(test, submissionRules, command, self.getSlaveEnvironment()):
            return
        
        self.testCount -= 1
        self.diag.info("Submission successful" + self.remainStr())
        self.testsSubmitted += 1
        if not test.state.hasStarted():
            test.changeState(self.getPendingState(test))
        if self.testsSubmitted == self.maxCapacity:
            self.sendServerState("Completed submission of tests up to capacity")
    def getSlaveEnvironment(self):
        env = plugins.copyEnvironment()
        self.fixUseCaseVariables(env)
        return env

    def fixUseCaseVariables(self, env):
        # Make sure we clear out the master scripts so the slave doesn't use them too,
        # otherwise just use the environment as is
        if env.has_key("USECASE_REPLAY_SCRIPT"):
            env["USECASE_REPLAY_SCRIPT"] = ""
            env["USECASE_RECORD_SCRIPT"] = ""

    def fixDisplay(self, env):
        # Must make sure SGE jobs don't get a locally referencing DISPLAY
        display = env.get("DISPLAY")
        if display and display.startswith(":"):
            env["DISPLAY"] = socket.gethostname() + display

    def getPendingState(self, test):
        freeText = "Job pending in " + queueSystemName(test.app)
        return plugins.TestState("pending", freeText=freeText, briefText="PEND", lifecycleChange="become pending")
    def shellWrap(self, command):
        # Must use exec so as not to create extra processes: SGE's qdel isn't very clever when
        # it comes to noticing extra shells
        return "exec $SHELL -c \"exec " + command + "\""
    def getSlaveCommand(self, test, submissionRules):
        return plugins.textTestName + " -d " + os.getenv("TEXTTEST_HOME") + \
               " -a " + test.app.name + test.app.versionSuffix() + \
               " -l -tp " + test.getRelPath() + \
               self.getSlaveArgs(test) + " " + \
               self.getRunOptions(test.app, submissionRules)
    def getSlaveArgs(self, test):
        return " -slave " + test.app.writeDirectory + " -servaddr " + self.submitAddress
    def getRunOptions(self, app, submissionRules):
        runOptions = []
        for slaveSwitch in app.getSlaveSwitches():
            if self.optionMap.has_key(slaveSwitch):
                option = "-" + slaveSwitch
                value = self.optionMap.get(slaveSwitch)
                if value:
                    option += " " + value
                runOptions.append(option)

        if self.optionMap.diagConfigFile:
            runOptions.append("-x")
            runOptions.append("-xr " + self.optionMap.diagConfigFile)
            # The environment variable is mostly for self-testing
            # so we can point all logs to the same place. 
            slaveWriteDir = os.getenv("TEXTTEST_SLAVE_DIAGDIR",
                                      os.path.join(self.optionMap.diagWriteDir, submissionRules.getJobName()))
            runOptions.append("-xw " + slaveWriteDir)
        return " ".join(runOptions)
    def getSlaveLogDir(self, test):
        return os.path.join(test.app.writeDirectory, "slavelogs")
    def submitJob(self, test, submissionRules, command, slaveEnv):
        self.diag.info("Submitting job at " + plugins.localtime() + ":" + command)
        self.diag.info("Creating job at " + plugins.localtime())
        queueSystem = self.getQueueSystem(test)
        extraArgs = test.getEnvironment("QUEUE_SYSTEM_SUBMIT_ARGS")
        cmdArgs = queueSystem.getSubmitCmdArgs(submissionRules)
        if extraArgs:
            cmdArgs += plugins.splitcmd(extraArgs)
        cmdArgs.append(self.shellWrap(command))
        jobName = submissionRules.getJobName()
        self.fixDisplay(slaveEnv)
        self.diag.info("Creating job " + jobName + " with command arguments : " + repr(cmdArgs))
        self.lock.acquire()
        if self.exited:
            self.cancel(test)
            self.lock.release()
            print "Q: Submission cancelled for", test, "- exit underway"
            return False
        
        self.lockDiag.info("Got lock for submission")
        try:
            process = subprocess.Popen(cmdArgs, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       cwd=self.getSlaveLogDir(test), env=slaveEnv)
            stdout, stderr = process.communicate()
            errorMessage = self.findErrorMessage(stderr, queueSystem)
        except OSError:
            errorMessage = "local machine is not a submit host"
        if not errorMessage:
            jobId = queueSystem.findJobId(stdout)
            self.diag.info("Job created with id " + jobId)
            self.jobs.setdefault(test, []).append((jobId, jobName))
            self.lockDiag.info("Releasing lock for submission...")
            self.lock.release()
            return True
        else:
            self.lock.release()
            self.diag.info("Job not created : " + errorMessage)
            fullError = self.getFullSubmitError(test, errorMessage, cmdArgs)
            test.changeState(plugins.Unrunnable(fullError, "NOT SUBMITTED"))
            self.handleErrorState(test)
            return False
    def findErrorMessage(self, stderr, queueSystem):
        if len(stderr) > 0:
            return queueSystem.findSubmitError(stderr)
    def getFullSubmitError(self, test, errorMessage, cmdArgs):
        qname = queueSystemName(test.app)
        return "Failed to submit to " + qname + " (" + errorMessage.strip() + ")\n" + \
               "Submission command was '" + " ".join(cmdArgs[:-1]) + " ... '\n"

    def handleErrorState(self, test, previouslySubmitted=False):
        if previouslySubmitted:
            self.testsSubmitted -= 1
        else:
            self.testCount -= 1
        self.diag.info(repr(test) + " in error state" + self.remainStr())
        bugchecker = CheckForBugs()
        self.setUpSuites(bugchecker, test)
        bugchecker(test)
        test.actionsCompleted()        
    def setUpSuites(self, bugchecker, test):
        if test.parent:
            bugchecker.setUpSuite(test.parent)
            self.setUpSuites(bugchecker, test.parent)
    def _getJobFailureInfo(self, test):
        jobInfo = self.getJobInfo(test)
        if len(jobInfo) == 0:
            return "No job has been submitted to " + queueSystemName(test)
        queueSystem = self.getQueueSystem(test)
        # Take the most recent job, it's hopefully the most interesting
        jobId, jobName = jobInfo[-1]
        return queueSystem.getJobFailureInfo(jobId)
    def getSlaveErrors(self, test, name):
        slaveErrFile = self.getSlaveErrFile(test)
        if slaveErrFile:
            errors = open(slaveErrFile).read()
            if errors:
                return "-" * 10 + " Error messages written by " + name + " job " + "-" * 10 + \
                       "\n" + errors
 
    def getSlaveErrFile(self, test):
        for jobId, jobName in self.getJobInfo(test):
            errFile = os.path.join(self.getSlaveLogDir(test), jobName + ".errors")
            if os.path.isfile(errFile):
                return errFile
    
    def getJobInfo(self, test):
        return self.jobs.get(test, [])
    def killJob(self, test, jobId, jobName):
        prevTest, prevJobExisted = self.killedJobs.get(jobId, (None, False))
        # Killing the same job for other tests should result in the cached result being returned
        if prevTest and test is not prevTest:
            return prevJobExisted

        self.describeJob(test, jobId, jobName)
        queueSystem = self.getQueueSystem(test)
        jobExisted = queueSystem.killJob(jobId)
        self.killedJobs[jobId] = test, jobExisted
        return jobExisted
    def getQueueSystem(self, test):
        queueModule = queueSystemName(test).lower()
        if self.queueSystems.has_key(queueModule):
            return self.queueSystems[queueModule]
        
        command = "from " + queueModule + " import QueueSystem as _QueueSystem"
        exec command
        system = _QueueSystem()
        self.queueSystems[queueModule] = system
        return system
    def changeState(self, test, newState, previouslySubmitted=True):
        test.changeState(newState)
        self.handleLocalError(test, previouslySubmitted)
    
    def killTests(self):
        # If we've been killed with some sort of limit signal, wait here until we know
        # all tests terminate. Otherwise we rely on them terminating naturally, and if they don't
        wantStatus = self.killSignal and self.killSignal != signal.SIGINT
        killedTests = []
        for test, jobList in self.jobs.items():
            if not test.state.isComplete():
                for jobId, jobName in jobList:
                    if self.killTest(test, jobId, jobName, wantStatus):
                        killedTests.append((test, jobId))
        if wantStatus:
            self.waitForKill(killedTests)

    def waitForKill(self, killedTests):
        # Wait for a minute for the kill to take effect, otherwise give up
        stillRunning = killedTests
        for attempt in range(1, 61):
            stillRunning = filter(lambda (test, jobId): not test.state.isComplete(), stillRunning)
            if len(stillRunning) == 0:
                return
            sleep(1)
            for test, jobId in stillRunning:
                print "T: Cancellation in progress for", repr(test) + \
                      ", waited " + str(attempt) + " seconds so far."
        for test, jobId in stillRunning:
            name = queueSystemName(test.app)
            freeText = "Could not delete test in " + name + " (job " + jobId + "): have abandoned it"
            self.changeState(test, Abandoned(freeText))

    def killOrCancel(self, test):
        # Explicitly chose test to kill (from the GUI)
        jobInfo = self.getJobInfo(test)
        if len(jobInfo) > 0:
            for jobId, jobName in self.getJobInfo(test):
                self.killTest(test, jobId, jobName, wantStatus=True)
        else:
            self.diag.info("No job info found from queue system server, changing state to cancelled")
            return self.cancel(test)
        
    def killTest(self, test, jobId, jobName, wantStatus):
        self.diag.info("Killing test " + repr(test) + " in state " + test.state.category)
        jobExisted = self.killJob(test, jobId, jobName)
        startNotified = self.jobStarted(test)
        if jobExisted:
            if startNotified:
                return self.shouldWaitFor(test)
            else:
                self.setKilledPending(test)
                return False
        else:
            # might get here when the test completed since we checked...
            if not test.state.isComplete():
                self.setSlaveFailed(test, startNotified, wantStatus)
        return False
    def shouldWaitFor(self, test):
        return True
    def jobStarted(self, test):
        return test.state.hasStarted()
    def setKilledPending(self, test):
        timeStr =  plugins.localtime("%H:%M")
        briefText = "cancelled pending job at " + timeStr
        freeText = "Test job was cancelled (while still pending in " + queueSystemName(test.app) +\
                   ") at " + timeStr
        self.cancel(test, briefText, freeText)

    def getJobFailureInfo(self, test, name, wantStatus):
        if wantStatus:
            return "-" * 10 + " Full accounting info from " + name + " " + "-" * 10 + "\n" + \
                   self._getJobFailureInfo(test)
        else:
            # Job accounting info can take ages to find, don't do it from GUI quit
            return "No accounting info found as quitting..."
        
    def setSlaveFailed(self, test, startNotified, wantStatus):
        failReason, fullText = self.getSlaveFailure(test, startNotified, wantStatus)
        fullText = failReason + "\n" + fullText
        self.changeState(test, self.getSlaveFailureState(startNotified, failReason, fullText))

    def getSlaveFailure(self, test, startNotified, wantStatus):
        fullText = ""
        name = queueSystemName(test.app)
        slaveErrors = self.getSlaveErrors(test, name)
        if slaveErrors:
            fullText += slaveErrors

        fullText += self.getJobFailureInfo(test, name, wantStatus)
        return self.getSlaveFailureBriefText(name, startNotified), fullText

    def getSlaveFailureBriefText(self, name, startNotified):
        if startNotified:
            return "no report, possibly killed with SIGKILL"
        else:
            return name + " job exited"

    def getSlaveFailureState(self, startNotified, failReason, fullText):
        if startNotified:
            return plugins.TestState("killed", briefText=failReason, \
                              freeText=fullText, completed=1, lifecycleChange="complete")
        else:
            return plugins.Unrunnable(briefText=failReason, freeText=fullText, lifecycleChange="complete")
        
    def getPostText(self, test, jobId):
        name = queueSystemName(test.app)
        return "in " + name + " (job " + jobId + ")"

    def describeJob(self, test, jobId, jobName):
        postText = self.getPostText(test, jobId)
        print "T: Cancelling", test, postText


class Abandoned(plugins.TestState):
    def __init__(self, freeText):
        plugins.TestState.__init__(self, "abandoned", briefText="job deletion failed", \
                                                      freeText=freeText, completed=1, lifecycleChange="complete")
    def shouldAbandon(self):
        return 1
        
class MachineInfoFinder(sandbox.MachineInfoFinder):
    def __init__(self):
        self.queueMachineInfo = None
    def findPerformanceMachines(self, app, fileStem):
        perfMachines = []
        resources = app.getCompositeConfigValue("performance_test_resource", fileStem)
        for resource in resources:
            perfMachines += plugins.retryOnInterrupt(self.queueMachineInfo.findResourceMachines, resource)

        rawPerfMachines = sandbox.MachineInfoFinder.findPerformanceMachines(self, app, fileStem)
        for machine in rawPerfMachines:
            if machine != "any":
                perfMachines += self.queueMachineInfo.findActualMachines(machine)
        if "any" in rawPerfMachines and len(resources) == 0:
            return rawPerfMachines
        else:
            return perfMachines
    def setUpApplication(self, app):
        sandbox.MachineInfoFinder.setUpApplication(self, app)
        moduleName = queueSystemName(app).lower()
        command = "from " + moduleName + " import MachineInfo as _MachineInfo"
        exec command
        self.queueMachineInfo = _MachineInfo()
    def getMachineInformation(self, test):
        # Try and write some information about what's happening on the machine
        info = ""
        for machine in test.state.executionHosts:
            for jobLine in self.findRunningJobs(machine):
                info += jobLine + "\n"
        return info
    def findRunningJobs(self, machine):
        try:
            return self._findRunningJobs(machine)
        except IOError:
            # If system calls to the queue system are interrupted, it shouldn't matter, try again
            return self._findRunningJobs(machine)
    def _findRunningJobs(self, machine):
        # On a multi-processor machine performance can be affected by jobs on other processors,
        # as for example a process can hog the memory bus. Describe these so the user can judge
        # for himself if performance is likely to be affected...
        jobsFromQueue = self.queueMachineInfo.findRunningJobs(machine)
        jobs = []
        for user, jobName in jobsFromQueue:
            jobs.append("Also on " + machine + " : " + user + "'s job '" + jobName + "'")
        return jobs    
