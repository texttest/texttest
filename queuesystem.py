#!/usr/local/bin/python

import os, string, sys, default, unixonly, performance, plugins, socket, time
from Queue import Queue, Empty
from SocketServer import TCPServer, StreamRequestHandler
from threading import Thread
from time import sleep
from copy import copy, deepcopy
from cPickle import dumps
from respond import Responder, TextDisplayResponder
from traffic_cmd import sendServerState
from knownbugs import CheckForBugs

plugins.addCategory("abandoned", "abandoned", "were abandoned")

def getConfig(optionMap):
    return QueueSystemConfig(optionMap)

def queueSystemName(app):
    return app.getConfigValue("queue_system_module")

# Use a non-monitoring runTest, but the rest from unix
class RunTestInSlave(unixonly.RunTest):
    def runTest(self, test, inChild=0):
        command = self.getExecuteCommand(test)
        if not inChild:
            self.describe(test)
            self.diag.info("Running test with command '" + command + "'")
            self.changeToRunningState(test, None)
        os.system(command)
    def getBriefText(self, execMachines):
        return "RUN (" + string.join(execMachines, ",") + ")"
    def getInterruptActions(self, fetchResults):
        return [ KillTestInSlave() ]

class FindExecutionHosts(default.FindExecutionHosts):
    def getExecutionMachines(self, test):
        moduleName = queueSystemName(test.app).lower()
        command = "from " + moduleName + " import getExecutionMachines as _getExecutionMachines"
        exec command
        return _getExecutionMachines()

class KillTestInSlave(default.KillTest):
    def getBriefText(self, test, origBriefText):
        moduleName = queueSystemName(test.app).lower()
        command = "from " + moduleName + " import getLimitInterpretation as _getLimitInterpretation"
        exec command
        interpretation = _getLimitInterpretation(origBriefText)
        if interpretation == "KILLED":
            timeStr = plugins.localtime("%H:%M")
            return "killed at " + timeStr
        else:
            return interpretation
    def getFullText(self, briefText):
        if briefText.startswith("killed at"):
            return briefText.replace("killed", "killed explicitly")
        else:
            return default.KillTest.getFullText(self, briefText)
    
class SocketResponder(Responder):
    def __init__(self, optionMap):
        Responder.__init__(self, optionMap)
        self.serverAddress = None
        servAddr = optionMap.get("servaddr")
        if servAddr:
            host, port = servAddr.split(":")
            self.serverAddress = (host, int(port))
    def connect(self, sendSocket):
        for attempt in range(5):
            try:
                sendSocket.connect(self.serverAddress)
                return
            except socket.error:
                sleep(1)
        sendSocket.connect(self.serverAddress)
    def notifyLifecycleChange(self, test, state, changeDesc):
        if self.serverAddress:
            testData = test.app.name + test.app.versionSuffix() + ":" + test.getRelPath()
            pickleData = dumps(state)
            sendSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.connect(sendSocket)
            sendSocket.sendall(str(os.getpid()) + os.linesep + testData + os.linesep + pickleData)
            sendSocket.close()
    
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
        if self.optionMap.has_key("reconnect") or self.optionMap.has_key("l"):
            return 0
        return 1
    def getRunOptions(self, checkout):
        # Options to add by default when recording, auto-replaying or running as slave
        return "-l " + default.Config.getRunOptions(self, checkout)
    def slaveRun(self):
        return self.optionMap.has_key("slave")
    def getWriteDirectoryName(self, app):
        slaveDir = self.optionMap.get("slave")
        if slaveDir:
            return slaveDir
        else:
            return default.Config.getWriteDirectoryName(self, app)
    def useExtraVersions(self, app):
        return default.Config.useExtraVersions(self, app) and not self.slaveRun()
    def getCleanMode(self):
        if self.slaveRun():
            return self.CLEAN_NONE
        else:
            return default.Config.getCleanMode(self)
    def getTestProcessor(self):
        baseProcessor = default.Config.getTestProcessor(self)
        if not self.useQueueSystem() or self.slaveRun():
            return baseProcessor

        submitter = SubmitTest(self.getSubmissionRules, self.optionMap, self.getSlaveSwitches())
        return [ submitter, WaitForCompletion(), CheckForUnrunnableBugs() ]
    def getSlaveSwitches(self):
        return [ "diag", "ignorecat", "actrep", "rectraffic", "keeptmp" ]
    def getExecHostFinder(self):
        if self.slaveRun():
            return FindExecutionHosts()
        else:
            return default.Config.getExecHostFinder(self)
    def getSlaveResponderClasses(self):
        return [ TextDisplayResponder, SocketResponder ]
    def getResponderClasses(self, allApps):
        if self.slaveRun():
            return self.getSlaveResponderClasses()
        else:
            return default.Config.getResponderClasses(self, allApps)
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
    def runsTests(self):
        return default.Config.runsTests(self) and not self.slaveRun()
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
    def defaultLoginShell(self):
        return "sh"
    def printHelpDescription(self):
        print """The queuesystem configuration is a published configuration, 
               documented online at http://www.texttest.org/TextTest/docs/queuesystem"""
    def setApplicationDefaults(self, app):
        default.Config.setApplicationDefaults(self, app)
        app.setConfigDefault("default_queue", "texttest_default", "Which queue to submit tests to by default")
        app.setConfigDefault("min_time_for_performance_force", -1, "Minimum CPU time for test to always run on performance machines")
        app.setConfigDefault("queue_system_module", "SGE", "Which queue system (grid engine) software to use. (\"SGE\" or \"LSF\")")
        app.setConfigDefault("performance_test_resource", { "default" : [] }, "Resources to request from queue system for performance testing")
        app.setConfigDefault("parallel_environment_name", "'*'", "(SGE) Which SGE parallel environment to use when SUT is parallel")
        app.setConfigDefault("login_shell", self.defaultLoginShell(), \
                             "Which shell to use when starting remote processes")

class SubmissionRules:
    def __init__(self, optionMap, test):
        self.test = test
        self.optionMap = optionMap
        self.envResource = self.getEnvironmentResource()
        self.processesNeeded = self.getProcessesNeeded()
    def getEnvironmentResource(self):
        return os.getenv("QUEUE_SYSTEM_RESOURCE", "")
    def getProcessesNeeded(self):
        return os.getenv("QUEUE_SYSTEM_PROCESSES", "1")
    def getJobName(self):
        path = self.test.getRelPath()
        parts = path.split("/")
        parts.reverse()
        return "Test-" + string.join(parts, ".") + "-" + repr(self.test.app).replace(" ", "_") + self.test.app.versionSuffix()
    def getSubmitSuffix(self, name):
        queue = self.findQueue()
        if queue:
            return " to " + name + " queue " + queue
        else:
            return " to default " + name + " queue"
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

class SlaveRequestHandler(StreamRequestHandler):
    def handle(self):
        clientPid = self.rfile.readline().strip()
        testString = self.rfile.readline().strip()
        test = self.server.getTest(testString)
        self.wfile.close()
        clientHost, clientPort = self.client_address
        # Don't use port, it changes all the time
        clientInfo = (clientHost, clientPid)
        if self.server.clientCorrect(test, clientInfo):
            test.loadState(self.rfile)
            if test.state.hasStarted():
                self.server.storeClient(test, clientInfo)
        else:
            expectedHost, expectedPid = self.server.testClientInfo[test]
            sys.stderr.write("WARNING: Unexpected TextTest slave for " + repr(test) + " connected from " + \
                             self.getHostName(clientHost) + " (process " + clientPid + ")\n")
            sys.stderr.write("Slave already registered from " + self.getHostName(expectedHost) + " (process " + expectedPid + ")\n")
            sys.stderr.write("Ignored all communication from this unexpected TextTest slave")
            sys.stderr.flush()
    def getHostName(self, ipAddress):
        name, aliasList, ipList = socket.gethostbyaddr(ipAddress)
        return name

class SlaveServer(TCPServer):
    def __init__(self):
        TCPServer.__init__(self, (socket.gethostname(), 0), SlaveRequestHandler)
        self.testMap = {}
        self.testClientInfo = {}
        self.diag = plugins.getDiagnostics("Slave Server")
        sendServerState("TextTest slave server started on " + self.getAddress())
    def getAddress(self):
        host, port = self.socket.getsockname()
        return host + ":" + str(port)
    def testSubmitted(self, test):
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
    def handle_error(self, request, client_address):
        print "Slave server caught an exception, ignoring..."

class MasterTextResponder(TextDisplayResponder):
    def notifyComplete(self, test):
        self.describe(test) # Do it for all of them, as we don't see the comparison stage

class QueueSystemServer:
    instance = None
    def __init__(self):
        self.jobs = {}
        self.killedTests = []
        self.queueSystems = {}
        self.submitDiag = plugins.getDiagnostics("Queue System Submit")
        QueueSystemServer.instance = self
        self.socketServer = SlaveServer()
        self.updateThread = Thread(target=self.socketServer.serve_forever)
        self.updateThread.setDaemon(1)
        self.updateThread.start()
    def getServerAddress(self):
        return self.socketServer.getAddress()
    def getEnvString(self, envDict):
        envStr = "env "
        for key, value in envDict.items():
            envStr += "'" + key + "=" + value + "' "
        return envStr
    def submitJob(self, test, submissionRules, command, slaveEnv):
        self.socketServer.testSubmitted(test)
        self.submitDiag.info("Creating job at " + plugins.localtime())
        queueSystem = self.getQueueSystem(test)
        extraArgs = os.getenv("QUEUE_SYSTEM_SUBMIT_ARGS")
        submitCommand = queueSystem.getSubmitCommand(submissionRules)
        if extraArgs:
            submitCommand += " " + extraArgs
        fullCommand = self.getEnvString(slaveEnv) + submitCommand + " '" + command + "'"
        jobName = submissionRules.getJobName()
        self.submitDiag.info("Creating job " + jobName + " with command : " + fullCommand)
        # Change directory to the appropriate test dir
        submissionRules.test.grabWorkingDirectory()
        stdin, stdout, stderr = os.popen3(fullCommand)
        errorMessage = plugins.retryOnInterrupt(queueSystem.findSubmitError, stderr)
        if errorMessage:
            self.submitDiag.info("Job not created : " + errorMessage)
            raise plugins.TextTestError, "Failed to submit to " + queueSystemName(test.app) \
                  + " (" + errorMessage.strip() + ")"

        jobId = queueSystem.findJobId(stdout)
        self.submitDiag.info("Job created with id " + jobId)
        self.jobs[test] = jobId, jobName
    def getJobFailureInfo(self, test):
        if not self.jobs.has_key(test):
            return "No job has been submitted to " + queueSystemName(test)
        queueSystem = self.getQueueSystem(test)
        jobId, jobName = self.jobs[test]
        return queueSystem.getJobFailureInfo(jobId)
    def getJobId(self, test):
        if not self.jobs.has_key(test):
            return "NONE"
        jobId, jobName = self.jobs[test]
        return jobId             
    def killJob(self, test):
        if not self.jobs.has_key(test) or test in self.killedTests:
            return False, None, None
        queueSystem = self.getQueueSystem(test)
        jobId, jobName = self.jobs[test]
        jobExisted = queueSystem.killJob(jobId)
        self.killedTests.append(test)
        return jobExisted, jobId, jobName
    def getQueueSystem(self, test):
        queueModule = test.app.getConfigValue("queue_system_module").lower()
        if self.queueSystems.has_key(queueModule):
            return self.queueSystems[queueModule]
        
        command = "from " + queueModule + " import QueueSystem as _QueueSystem"
        exec command
        system = _QueueSystem()
        self.queueSystems[queueModule] = system
        return system
                                 
class SubmitTest(plugins.Action):
    def __init__(self, submitRuleFunction, optionMap, slaveSwitches):
        self.loginShell = None
        self.submitRuleFunction = submitRuleFunction
        self.optionMap = optionMap
        self.slaveSwitches = slaveSwitches
        self.runOptions = ""
        self.diag = plugins.getDiagnostics("Queue System Submit")
        self.slaveEnv = {}
        self.setUpScriptEngine()
    def setUpScriptEngine(self):
        # For self-testing: make sure the slave doesn't read the master use cases.
        variables = [ "USECASE_RECORD_STDIN", "USECASE_RECORD_SCRIPT", "USECASE_REPLAY_SCRIPT" ]
        for var in variables:
            self.slaveEnv[var] = ""
    def slaveType(self):
        return "slave"
    def __repr__(self):
        return "Submitting"
    def __call__(self, test):    
        self.tryStartServer()
        command = self.getSlaveCommand(test)
        submissionRules = self.submitRuleFunction(test)
        self.describe(test, self.getPostText(test, submissionRules))

        self.diag.info("Submitting job : " + command)
        QueueSystemServer.instance.submitJob(test, submissionRules, command, self.slaveEnv)
        if not test.state.hasStarted():
            self.setPending(test)
        return self.WAIT
    def getPendingState(self, test):
        freeText = "Job pending in " + queueSystemName(test.app)
        return plugins.TestState("pending", freeText=freeText, briefText="PEND", lifecycleChange="become pending")
    def setPending(self, test):
        test.changeState(self.getPendingState(test))
    def getSlaveCommand(self, test):
        # Must use exec so as not to create extra processes: SGE's qdel isn't very clever when
        # it comes to noticing extra shells
        commandLine = "exec " + plugins.textTestName + " " + test.app.getRunOptions() + " -tp " + test.getRelPath() \
                      + self.getSlaveArgs(test) + " " + self.runOptions
        return "exec " + self.loginShell + " -c \"" + commandLine + "\""
    def getSlaveArgs(self, test):
        servAddr = os.getenv("TEXTTEST_MIM_SERVER")
        if not servAddr:
            servAddr = QueueSystemServer.instance.getServerAddress()
        return " -" + self.slaveType() + " " + test.app.writeDirectory + \
               " -servaddr " + servAddr
    def tryStartServer(self):
        if not QueueSystemServer.instance:
            QueueSystemServer.instance = QueueSystemServer()
    def setRunOptions(self, app):
        runOptions = []
        for slaveSwitch in self.slaveSwitches:
            value = self.optionMap.get(slaveSwitch)
            if value is not None:
                option = "-" + slaveSwitch
                if len(value) > 0:
                    option += " " + value
                runOptions.append(option)

        if self.optionMap.diagsEnabled():
            runOptions.append("-x")
            runOptions.append("-xr " + self.optionMap.getDiagReadDir())
            slaveWriteDir = os.path.join(self.optionMap.getDiagWriteDir(), self.slaveType())
            runOptions.append("-xw " + slaveWriteDir)
        return string.join(runOptions)
    def getPostText(self, test, submissionRules):
        name = queueSystemName(test.app)
        return submissionRules.getSubmitSuffix(name)
    def setUpSuite(self, suite):
        name = queueSystemName(suite.app)
        self.describe(suite, " to " + name + " queues")
    def setUpApplication(self, app):
        app.checkBinaryExists()
        self.runOptions = self.setRunOptions(app)
        self.loginShell = app.getConfigValue("login_shell")
    def getInterruptActions(self, fetchResults):
        return [ SubmissionMissed() ]

class SubmissionMissed(plugins.Action):
    def __call__(self, test):
        if not test.state.hasStarted() and test.state.category != "pending":
            raise plugins.TextTestError, "Termination already in progress when trying to submit to " + \
                  queueSystemName(test.app)

class KillTestSubmission(plugins.Action):
    def __repr__(self):
        return "Cancelling"
    def __call__(self, test):
        jobExisted, jobId, jobName = self.performKill(test)
        if not jobId:
            return

        self.describeJob(test, jobId, jobName)
        startNotified = self.jobStarted(test)
        if jobExisted:
            if not startNotified:
                self.setKilledPending(test)
        else:
            if startNotified:
                self.setSlaveLost(test)
            else:
                self.setSlaveFailed(test)
    def jobStarted(self, test):
        return test.state.hasStarted()
    def performKill(self, test):
        if not QueueSystemServer.instance:
            return False, None, None
        return QueueSystemServer.instance.killJob(test)
    def setKilledPending(self, test):
        timeStr =  plugins.localtime("%H:%M")
        briefText = "killed pending job at " + timeStr
        freeText = "Test job was killed (while still pending in " + queueSystemName(test.app) +\
                   ") at " + timeStr
        test.changeState(plugins.TestState("killed", briefText=briefText, freeText=freeText, completed=1))
    def setSlaveLost(self, test):
        failReason = "no report, possibly killed with SIGKILL"
        fullText = failReason + "\n" + self.getJobFailureInfo(test)
        test.changeState(plugins.TestState("killed", briefText=failReason, \
                                           freeText=fullText, completed=1))
    def getJobFailureInfo(self, test):
        name = queueSystemName(test.app)
        return "Full accounting info from " + name + " follows:\n" + \
               QueueSystemServer.instance.getJobFailureInfo(test)
    def setSlaveFailed(self, test):
        failReason, fullText = self.getSlaveFailure(test)
        fullText = failReason + "\n" + fullText
        test.changeState(plugins.Unrunnable(briefText=failReason, freeText=fullText))
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
        return " in " + name + " (job " + jobId + ")"
    def describeJob(self, test, jobId, jobName):
        postText = self.getPostText(test, jobId)
        self.describe(test, postText)
    
class WaitForCompletion(plugins.Action):
    messageSent = False
    def __call__(self, test):
        self.tryNotifyState()
        if not test.state.isComplete():
            return self.WAIT | self.RETRY
    def tryNotifyState(self):
        if not self.messageSent:
            WaitForCompletion.messageSent = True
            sendServerState("Completed submission of all tests")
    def getInterruptActions(self, fetchResults):
        actions = [ KillTestSubmission() ]
        if fetchResults:
            actions.append(WaitForKill())
        return actions

class Abandoned(plugins.TestState):
    def __init__(self, freeText):
        plugins.TestState.__init__(self, "abandoned", briefText="job deletion failed", \
                                                      freeText=freeText, completed=1)
    def shouldAbandon(self):
        return 1
    
class WaitForKill(plugins.Action):
    def __init__(self):
        self.testsWaitingForKill = {}
    def __call__(self, test):
        if test.state.isComplete():
            return

        attempt = self.getAttempt(test)
        if attempt > 600:
            name = queueSystemName(test.app)
            jobId = QueueSystemServer.instance.getJobId(test)
            freeText = "Could not delete " + repr(test) + " in " + name + " (job " + jobId + "): have abandoned it"
            print test.getIndent() + freeText
            return test.changeState(Abandoned(freeText))

        self.testsWaitingForKill[test] += 1
        attempt = self.testsWaitingForKill[test]
        if attempt % 10 == 0:
            print test.getIndent() + "Cancellation in progress for " + repr(test) + \
                  ", queue system wait time " + str(attempt)
        return self.WAIT | self.RETRY
    def getAttempt(self, test):
        if not self.testsWaitingForKill.has_key(test):
            self.testsWaitingForKill[test] = 0
        self.testsWaitingForKill[test] += 1
        return self.testsWaitingForKill[test]    
            
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
        
class CheckForUnrunnableBugs(CheckForBugs):
    def __call__(self, test):
        # Try to pick up only on unrunnable tests that have not come from a slave process
        if not test.state.hasResults() and test.state.lifecycleChange != "complete":
            CheckForBugs.__call__(self, test)
