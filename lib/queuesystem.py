import os, sys, default, unixonly, performance, plugins, socket, subprocess, operator
from Queue import Queue, Empty
from SocketServer import TCPServer, StreamRequestHandler
from time import sleep
from copy import copy, deepcopy
from cPickle import dumps
from respond import Responder, TextDisplayResponder, InteractiveResponder
from traffic_cmd import sendServerState
from knownbugs import CheckForBugs
from actionrunner import ActionRunner
from types import StringType

plugins.addCategory("abandoned", "abandoned", "were abandoned")

def getConfig(optionMap):
    return QueueSystemConfig(optionMap)

def queueSystemName(app):
    return app.getConfigValue("queue_system_module")

# Use a non-monitoring runTest, but the rest from unix
class RunTestInSlave(unixonly.RunTest):
    def runTest(self, test):
        process = self.getTestProcess(test)
        self.describe(test)
        self.changeToRunningState(test, process)
        plugins.retryOnInterrupt(process.wait)
    def getBriefText(self, execMachines):
        return "RUN (" + ",".join(execMachines) + ")"

class FindExecutionHosts(default.FindExecutionHosts):
    def getExecutionMachines(self, test):
        moduleName = queueSystemName(test.app).lower()
        command = "from " + moduleName + " import getExecutionMachines as _getExecutionMachines"
        exec command
        return _getExecutionMachines()

class KillTestInSlave(default.KillTest):
    def interpret(self, test, origBriefText):
        moduleName = queueSystemName(test.app).lower()
        command = "from " + moduleName + " import getLimitInterpretation as _getLimitInterpretation"
        exec command
        return _getLimitInterpretation(origBriefText)

def socketSerialise(test):
    return test.app.name + test.app.versionSuffix() + ":" + test.getRelPath()

class SocketResponder(Responder,plugins.Observable):
    def __init__(self, optionMap):
        Responder.__init__(self, optionMap)
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
        sendSocket.connect(self.serverAddress)
    def notifyLifecycleChange(self, test, state, changeDesc):
        testData = socketSerialise(test)
        pickleData = dumps(state)
        sendSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connect(sendSocket)
        sendSocket.sendall(str(os.getpid()) + os.linesep + testData + os.linesep + pickleData)
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
                group.addSwitch("perf", "Run on performance machines only")
            elif group.name.startswith("Invisible"):
                group.addOption("slave", "Private: used to submit slave runs remotely")
                group.addOption("servaddr", "Private: used to submit slave runs remotely")
    def getPossibleQueues(self, queueSystem):
        return [] # placeholders for derived configurations
    def getPossibleResources(self, queueSystem):
        return []
    def useQueueSystem(self):
        return not self.isReconnecting() and not self.optionMap.has_key("l") and \
               not self.optionMap.has_key("gx") and not self.optionMap.runScript() and not self.optionMap.has_key("coll")
    def getRunOptions(self, checkout):
        # Options to add by default when recording, auto-replaying or running as slave
        return [ "-l" ] + default.Config.getRunOptions(self, checkout)
    def slaveRun(self):
        return self.optionMap.has_key("slave")
    def getWriteDirectoryName(self, app):
        slaveDir = self.optionMap.get("slave")
        if slaveDir:
            parts = os.path.basename(slaveDir).split(".")
            if parts[0] == app.name and parts[1:-1] == app.versions:
                return slaveDir
            else:
                return os.path.join(os.path.dirname(slaveDir), app.name + app.versionSuffix() + "." + parts[-1])
        else:
            return default.Config.getWriteDirectoryName(self, app)
    def useExtraVersions(self, app):
        return default.Config.useExtraVersions(self, app) and not self.slaveRun()
    def getCleanMode(self):
        if self.slaveRun():
            return plugins.CleanMode()
        else:
            return default.Config.getCleanMode(self)
    def getTextResponder(self):
        if self.useQueueSystem():
            return MasterInteractiveResponder
        else:
            return InteractiveResponder
    def getTestKiller(self):
        if self.slaveRun():
            return KillTestInSlave()
        elif not self.useQueueSystem():
            return default.Config.getTestKiller(self)
        else:
            return self.getSubmissionKiller()
    def getSubmissionKiller(self):
        return KillTestSubmission()
    def getSlaveSwitches(self):
        return [ "b", "trace", "ignorecat", "actrep", "rectraffic", "keeptmp" ]
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
        responderClasses = default.Config.getResponderClasses(self, allApps)
        if self.useQueueSystem():
            responderClasses.append(self.getSlaveServerClass())
        return responderClasses
    def getThreadActionClasses(self):
        if not self.slaveRun() and self.useQueueSystem():
            return [ self.getActivatorClass(), QueueSystemServer, SlaveServerResponder ] # don't use the action runner at all!
        else:
            return default.Config.getThreadActionClasses(self)
    def getSlaveServerClass(self):
        return SlaveServerResponder
    def getActivatorClass(self):
        return Activator
    def getEnvironmentCreator(self, test):
        if self.slaveRun() or self.useQueueSystem():
            return TestEnvironmentCreator(test, self.optionMap)
        else:
            return default.Config.getEnvironmentCreator(self, test)
    def useVirtualDisplay(self):
        if self.useQueueSystem():
            return False
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
        app.setConfigDefault("queue_system_module", "SGE", "Which queue system (grid engine) software to use. (\"SGE\" or \"LSF\")")
        app.setConfigDefault("performance_test_resource", { "default" : [] }, "Resources to request from queue system for performance testing")
        app.setConfigDefault("parallel_environment_name", "*", "(SGE) Which SGE parallel environment to use when SUT is parallel")
        app.setConfigDefault("queue_system_max_capacity", self.getDefaultMaxCapacity(), "Maximum possible number of parallel similar jobs in the available grid")

class Activator:
    def __init__(self, optionMap):
        self.allTests = []
        self.allApps = []
    def addSuites(self, suites):
        self.allTests = reduce(operator.add, [ suite.testCaseList() for suite in suites ]) 
        self.allApps = [ suite.app for suite in suites ]
    def makeAppWriteDirectories(self):
        for app in self.allApps:
            app.makeWriteDirectory()            
    def run(self):
        self.makeAppWriteDirectories()
        for test in self.allTests:
            test.makeWriteDirectory()
            QueueSystemServer.instance.submit(test)

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
        return "Test-" + ".".join(parts) + "-" + repr(self.test.app).replace(" ", "_") + self.test.app.versionSuffix()
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
        return "framework_tmp/slavelog", "framework_tmp/slaveerrs"
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
        else:
            expectedHost, expectedPid = self.server.testClientInfo[test]
            sys.stderr.write("WARNING: Unexpected TextTest slave for " + repr(test) + " connected from " + \
                             hostname + " (process " + identifier + ")\n")
            sys.stderr.write("Slave already registered from " + expectedHost + " (process " + expectedPid + ")\n")
            sys.stderr.write("Ignored all communication from this unexpected TextTest slave")
            sys.stderr.flush()
    def getHostName(self, ipAddress):
        return socket.gethostbyaddr(ipAddress)[0].split(".")[0]

class SlaveServerResponder(Responder,TCPServer):
    submitAddress = os.getenv("TEXTTEST_MIM_SERVER") # Where we tell the slaves to report back to
    def __init__(self, optionMap):
        Responder.__init__(self, optionMap)
        TCPServer.__init__(self, (socket.gethostname(), 0), self.handlerClass())
        self.testMap = {}
        self.testClientInfo = {}
        self.diag = plugins.getDiagnostics("Slave Server")
        self.terminate = False
        # Need to tell the submission code where we are, if it's not using the MIM already
        if not self.submitAddress:
            SlaveServerResponder.submitAddress = self.getAddress()
    def handlerClass(self):
        return SlaveRequestHandler
    def run(self):
        # Tell the man-in-the-middle (MIM), if any, where we are
        serverAddress = self.getAddress()
        sendServerState("TextTest slave server started on " + serverAddress)
        self.diag.info("Starting slave server at " + serverAddress)
        while not self.terminate:
            self.handle_request()
        
        self.diag.info("Terminating slave server")
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
    def addSuites(self, suites):
        for suite in suites:
            for test in suite.testCaseList():
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
        print "S: Test", test.uniqueName, test.state.description()

# Don't indent, and use the unique name rather than repr()
class MasterInteractiveResponder(InteractiveResponder):
    def describeSave(self, test, saveDesc):
        print "Saving test", test.uniqueName + saveDesc
    def describeViewOptions(self, test, options):
        print options

class QueueSystemServer:
    instance = None
    def __init__(self, optionMap):
        self.optionMap = optionMap
        self.queue = Queue()
        # queue for putting tests when we couldn't reuse the originals
        self.reuseFailureQueue = Queue()
        self.testCount = 0
        self.testsSubmitted = 0
        self.maxCapacity = 100000 # infinity, sort of
        self.jobs = {}
        self.submissionRules = {}
        self.killedTests = []
        self.queueSystems = {}
        self.reuseOnly = False
        self.diag = plugins.getDiagnostics("Queue System Submit")
        QueueSystemServer.instance = self
    def addSuites(self, suites):
        for suite in suites:
            currCap = suite.getConfigValue("queue_system_max_capacity")
            if currCap < self.maxCapacity:
                self.maxCapacity = currCap
            print "Using", queueSystemName(suite.app), "queues for", suite.app.description(includeCheckout=True)
            self.testCount += suite.size()
    def submit(self, test, initial=True):
        # If we've gone into reuse mode and there are no active tests for reuse, use the "reuse failure queue"
        if self.reuseOnly and self.testsSubmitted == 0:
            self.reuseFailureQueue.put(test)
        else:
            self.queue.put(test)
    def handleLocalError(self, test):
        self.handleErrorState(test)
        if self.testCount == 0:
            self.submitTerminators()
    def submitTerminators(self):
        # snap out of our loop if this was the last one
        self.queue.put(None)
        self.reuseFailureQueue.put(None)
    def getItemFromQueue(self, queue, block):
        try:
            return queue.get(block=block)
        except Empty:
            return
    def getTestForReuse(self, test):
        # Pick up any test that matches the current one's resource requirements
        newTest = self.getTest(block=False)
        if newTest:
            if self.allowReuse(test, newTest):
                self.jobs[newTest] = self.getJobInfo(test)
                if self.testCount > 1:
                    self.testCount -= 1
                    self.diag.info("Reusing slave for " + newTest.uniqueName + self.remainStr())
                else:
                    # Don't allow test count to drop to 0 here, can cause race conditions
                    self.submitTerminators() 
                return newTest
            else:
                self.reuseFailureQueue.put(newTest)
        # Allowed a submitted job to terminate
        self.testsSubmitted -= 1
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
        testOrStatus = self.getItemFromQueue(self.queue, block)
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
    def getTestForSubmit(self):
        if self.testsSubmitted < self.maxCapacity:
            self.reuseOnly = False
            reuseFailure = self.getItemFromQueue(self.reuseFailureQueue, block=False)
            if reuseFailure:
                self.diag.info("Found a reuse failure...")
                return reuseFailure
            else:
                self.diag.info("Waiting for new tests...")
                return self.getTest(block=True)
        else:
            self.reuseOnly = True
            self.diag.info("Waiting for reuse failures...")
            return self.getItemFromQueue(self.reuseFailureQueue, block=True)
    def run(self):        
        while self.testCount > 0:
            test = self.getTestForSubmit()
            if not test:
                self.diag.info("Found no-test marker, exiting")
                break
            self.diag.info("Handling test " + test.uniqueName)
            if not test.state.isComplete():
                self.performSubmission(test)
            
        self.sendServerState("Completed submission of all tests")
    def remainStr(self):
        return " : " + str(self.testCount) + " tests remain."
    def performSubmission(self, test):
        command = self.getSlaveCommand(test)
        submissionRules = test.app.getSubmissionRules(test)
        print "Q: Submitting test", test.uniqueName, submissionRules.getSubmitSuffix()
        if not self.submitJob(test, submissionRules, command):
            return
        
        self.testCount -= 1
        self.diag.info("Submission successful" + self.remainStr())
        self.testsSubmitted += 1
        if not test.state.hasStarted():
            test.changeState(self.getPendingState(test))
        if self.testsSubmitted == self.maxCapacity:
            self.sendServerState("Completed submission of tests up to capacity")
    def getPendingState(self, test):
        freeText = "Job pending in " + queueSystemName(test.app)
        return plugins.TestState("pending", freeText=freeText, briefText="PEND", lifecycleChange="become pending")
    def shellWrap(self, command):
        # Must use exec so as not to create extra processes: SGE's qdel isn't very clever when
        # it comes to noticing extra shells
        return "exec " + os.getenv("SHELL") + " -c \"exec " + command + "\""
    def getSlaveCommand(self, test):
        return plugins.textTestName + " " + " ".join(test.app.getRunOptions()) + " -tp " + test.getRelPath() \
               + self.getSlaveArgs(test) + " " + self.getRunOptions(test.app)
    def getSlaveArgs(self, test):
        return " -slave " + test.app.writeDirectory + " -servaddr " + SlaveServerResponder.submitAddress
    def getRunOptions(self, app):
        runOptions = []
        for slaveSwitch in app.getSlaveSwitches():
            value = self.optionMap.get(slaveSwitch)
            if value is not None:
                option = "-" + slaveSwitch
                if len(value) > 0:
                    option += " " + value
                runOptions.append(option)

        if self.optionMap.diagConfigFile:
            runOptions.append("-x")
            runOptions.append("-xr " + self.optionMap.diagConfigFile)
            slaveWriteDir = os.path.join(self.optionMap.diagWriteDir, "slave")
            runOptions.append("-xw " + slaveWriteDir)
        return " ".join(runOptions)
    def submitJob(self, test, submissionRules, command, \
                  envVars = [ "DISPLAY", "USECASE_REPLAY_SCRIPT", "USECASE_RECORD_SCRIPT" ]):
        self.diag.info("Submitting job at " + plugins.localtime() + ":" + command)
        self.diag.info("Creating job at " + plugins.localtime())
        queueSystem = self.getQueueSystem(test)
        extraArgs = test.getEnvironment("QUEUE_SYSTEM_SUBMIT_ARGS")
        cmdArgs = queueSystem.getSubmitCmdArgs(submissionRules)
        if extraArgs:
            cmdArgs += plugins.splitcmd(extraArgs)
        cmdArgs.append(self.shellWrap(command))
        jobName = submissionRules.getJobName()
        self.diag.info("Creating job " + jobName + " with command arguments : " + repr(cmdArgs))
        process = subprocess.Popen(cmdArgs, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=test.getDirectory(temporary=1), env=test.getRunEnvironment(envVars))
        stdout, stderr = process.communicate()
        errorMessage = self.findErrorMessage(stderr, queueSystem)
        if not errorMessage:
            jobId = queueSystem.findJobId(stdout)
            self.diag.info("Job created with id " + jobId)
            self.jobs[test] = jobId, jobName
            return True
        else:
            self.diag.info("Job not created : " + errorMessage)
            qname = queueSystemName(test.app)
            fullError = "Failed to submit to " + qname + " (" + errorMessage.strip() + ")\n" + \
                      "Submission command was '" + " ".join(cmdArgs[:-1]) + " ... '\n"
            test.changeState(plugins.Unrunnable(freeText=fullError))
            self.handleErrorState(test)
            return False
    def findErrorMessage(self, stderr, queueSystem):
        if len(stderr) > 0:
            return queueSystem.findSubmitError(stderr)
    def handleErrorState(self, test):
        self.testCount -= 1
        self.diag.info("Test " + test.uniqueName + " in error state" + self.remainStr())
        bugchecker = CheckForBugs()
        self.setUpSuites(bugchecker, test)
        bugchecker(test)
        test.actionsCompleted()        
    def setUpSuites(self, bugchecker, test):
        if test.parent:
            bugchecker.setUpSuite(test.parent)
            self.setUpSuites(bugchecker, test.parent)
    def getJobFailureInfo(self, test):
        if not self.jobs.has_key(test):
            return "No job has been submitted to " + queueSystemName(test)
        queueSystem = self.getQueueSystem(test)
        jobId, jobName = self.jobs[test]
        return queueSystem.getJobFailureInfo(jobId)
    def getJobInfo(self, test):
        return self.jobs.get(test, (None, None))
    def killJob(self, test):
        if not self.jobs.has_key(test) or test in self.killedTests:
            return False
        queueSystem = self.getQueueSystem(test)
        jobId, jobName = self.jobs[test]
        jobExisted = queueSystem.killJob(jobId)
        self.killedTests.append(test)
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

class KillTestSubmission:
    def __init__(self):
        self.diag = plugins.getDiagnostics("Kill Test")
    def changeState(self, test, newState):
        test.changeState(newState)
        QueueSystemServer.instance.handleLocalError(test)
    def __call__(self, test, killReason):
        self.diag.info("Killing test " + repr(test) + " in state " + test.state.category)
        jobId, jobName = self.getJobInfo(test)
        if not jobId:
            self.diag.info("No job info found from queue system server, changing state to cancelled")
            return self.changeState(test, default.Cancelled())
        
        self.describeJob(test, jobId, jobName)
        jobExisted = QueueSystemServer.instance.killJob(test)
        startNotified = self.jobStarted(test)
        if jobExisted:
            if startNotified:
                self.setKilled(test, killReason, jobId)
            else:
                self.setKilledPending(test)
        else:
            # might get here when the test completed since we checked...
            if not test.state.isComplete():
                if startNotified:
                    self.setSlaveLost(test)
                else:
                    self.setSlaveFailed(test)
    def setKilled(self, test, killReason, jobId):
        if killReason.find("LIMIT") != -1:
            self.waitForKill(test, jobId)
    def jobStarted(self, test):
        return test.state.hasStarted()
    def getJobInfo(self, test):
        if not QueueSystemServer.instance:
            return None, None
        return QueueSystemServer.instance.getJobInfo(test)
    def setKilledPending(self, test):
        timeStr =  plugins.localtime("%H:%M")
        briefText = "cancelled pending job at " + timeStr
        freeText = "Test job was cancelled (while still pending in " + queueSystemName(test.app) +\
                   ") at " + timeStr
        self.changeState(test, default.Cancelled(briefText, freeText))
    def setSlaveLost(self, test):
        failReason = "no report, possibly killed with SIGKILL"
        fullText = failReason + "\n" + self.getJobFailureInfo(test)
        self.changeState(test, plugins.TestState("killed", briefText=failReason, \
                                                 freeText=fullText, completed=1, lifecycleChange="complete"))
    def getJobFailureInfo(self, test):
        name = queueSystemName(test.app)
        return "Full accounting info from " + name + " follows:\n" + \
               QueueSystemServer.instance.getJobFailureInfo(test)
    def setSlaveFailed(self, test):
        failReason, fullText = self.getSlaveFailure(test)
        fullText = failReason + "\n" + fullText
        self.changeState(test, plugins.Unrunnable(briefText=failReason, freeText=fullText, lifecycleChange="complete"))
    def getSlaveFailure(self, test):
        slaveErrFile = test.makeTmpFileName("slaveerrs", forFramework=1)
        if os.path.isfile(slaveErrFile):
            errStr = open(slaveErrFile).read()
            if errStr and errStr.find("Traceback") != -1:
                return "Slave exited", errStr
        name = queueSystemName(test.app)
        return name + "/system error", "Full accounting info from " + name + " follows:\n" + \
               QueueSystemServer.instance.getJobFailureInfo(test)
    def getPostText(self, test, jobId):
        name = queueSystemName(test.app)
        return "in " + name + " (job " + jobId + ")"
    def describeJob(self, test, jobId, jobName):
        postText = self.getPostText(test, jobId)
        print "T: Cancelling test", test.uniqueName, postText
    def waitForKill(self, test, jobId):
        # Wait for a minute for the kill to take effect, otherwise give up
        for attempt in range(1, 61):
            if test.state.isComplete():
                return
            sleep(1)
            print "T: Cancellation in progress for test", test.uniqueName + \
                  ", waited " + str(attempt) + " seconds so far."
        name = queueSystemName(test.app)
        freeText = "Could not delete test in " + name + " (job " + jobId + "): have abandoned it"
        self.changeState(test, Abandoned(freeText))

class Abandoned(plugins.TestState):
    def __init__(self, freeText):
        plugins.TestState.__init__(self, "abandoned", briefText="job deletion failed", \
                                                      freeText=freeText, completed=1, lifecycleChange="complete")
    def shouldAbandon(self):
        return 1

# Only used when actually running master + slave
class TestEnvironmentCreator(default.TestEnvironmentCreator):
    def doSetUp(self):
        if self.optionMap.has_key("slave"):
            self.setDiagEnvironment()
            self.setUseCaseEnvironment()
        else:
            self.clearUseCaseEnvironment() # don't have the slave using these
    def clearUseCaseEnvironment(self):
        if self.testCase() and os.environ.has_key("USECASE_REPLAY_SCRIPT"):
            # If we're in the master, make sure we clear the scripts so the slave doesn't use them too...
            self.test.setEnvironment("USECASE_REPLAY_SCRIPT", "")
            self.test.setEnvironment("USECASE_RECORD_SCRIPT", "")
        
class MachineInfoFinder(default.MachineInfoFinder):
    def __init__(self):
        self.queueMachineInfo = None
    def findPerformanceMachines(self, app, fileStem):
        perfMachines = []
        resources = app.getCompositeConfigValue("performance_test_resource", fileStem)
        for resource in resources:
            perfMachines += plugins.retryOnInterrupt(self.queueMachineInfo.findResourceMachines, resource)

        rawPerfMachines = default.MachineInfoFinder.findPerformanceMachines(self, app, fileStem)
        for machine in rawPerfMachines:
            if machine != "any":
                perfMachines += self.queueMachineInfo.findActualMachines(machine)
        if "any" in rawPerfMachines and len(perfMachines) == 0:
            return rawPerfMachines
        else:
            return perfMachines
    def setUpApplication(self, app):
        default.MachineInfoFinder.setUpApplication(self, app)
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
