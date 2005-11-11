#!/usr/local/bin/python

import os, string, sys, default, unixonly, performance, plugins, socket, time
from Queue import Queue, Empty
from SocketServer import TCPServer, StreamRequestHandler
from threading import Thread
from time import sleep
from copy import copy, deepcopy
from cPickle import dumps
from respond import Responder

plugins.addCategory("abandoned", "abandoned", "were abandoned")

def getConfig(optionMap):
    return QueueSystemConfig(optionMap)

def queueSystemName(app):
    return app.getConfigValue("queue_system_module")

# Use a non-monitoring runTest, but the rest from unix
class RunTestInSlave(unixonly.RunTest):
    def runTest(self, test, inChild=0):
        command = self.getExecuteCommand(test)
        self.describe(test)
        self.diag.info("Running test with command '" + command + "'")
        if not inChild:
            self.changeToRunningState(test, None)
        os.system(command)
    def setUpVirtualDisplay(self, app):
        # Assume the master sets DISPLAY for us
        pass
    def getExecutionMachines(self, test):
        moduleName = queueSystemName(test.app).lower()
        command = "from " + moduleName + " import getExecutionMachines as _getExecutionMachines"
        exec command
        return _getExecutionMachines()
    def getBriefText(self, execMachines):
        return "RUN (" + string.join(execMachines, ",") + ")"
    def getInterruptActions(self):
        return [ KillTestInSlave() ]

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
        servAddr = optionMap["servaddr"]
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
    def notifyLifecycleChange(self, test, changeDesc):
        testData = test.app.name + test.app.versionSuffix() + ":" + test.getRelPath()
        pickleData = dumps(test.state)
        sendSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connect(sendSocket)
        sendSocket.sendall(testData + os.linesep + pickleData)
        sendSocket.close()
    
class QueueSystemConfig(default.Config):
    def addToOptionGroups(self, app, groups):
        default.Config.addToOptionGroups(self, app, groups)
        queueSystem = queueSystemName(app)
        queueSystemGroup = app.createOptionGroup(queueSystem)
        queueSystemGroup.addSwitch("l", "Run tests locally", nameForOff="Submit tests to " + queueSystem)
        queueSystemGroup.addSwitch("perf", "Run on performance machines only")
        queueSystemGroup.addOption("R", "Request " + queueSystem + " resource")
        queueSystemGroup.addOption("q", "Request " + queueSystem + " queue")
        groups.insert(3, queueSystemGroup)
        for group in groups:
            if group.name.startswith("Invisible"):
                group.addOption("slave", "Private: used to submit slave runs remotely")
                group.addOption("servaddr", "Private: used to submit slave runs remotely")
    def useQueueSystem(self):
        if self.optionMap.has_key("reconnect") or self.optionMap.has_key("l"):
            return 0
        return 1
    def slaveRun(self):
        return self.optionMap.has_key("slave")
    def getRunIdentifier(self, prefix):
        if self.slaveRun():
            return prefix + self.optionMap["slave"]
        else:
            return default.Config.getRunIdentifier(self, prefix)
    def useTextResponder(self):
        if self.slaveRun():
            return 0
        else:
            return default.Config.useTextResponder(self)
    def useExtraVersions(self):
        return not self.slaveRun()
    def getCleanMode(self):
        if self.slaveRun():
            if self.optionMap.has_key("keeptmp"):
                return self.CLEAN_NONE
            else:
                return self.CLEAN_NONBASIC
        else:
            return default.Config.getCleanMode(self)
    def getTestProcessor(self):
        baseProcessor = default.Config.getTestProcessor(self)
        if not self.useQueueSystem() or self.slaveRun():
            return baseProcessor

        submitter = SubmitTest(self.getSubmissionRules, self.optionMap)
        return [ submitter, WaitForCompletion() ]
    def getResponderClasses(self):
        if self.slaveRun():
            return [ SocketResponder ]
        else:
            return default.Config.getResponderClasses(self)
    def getTestRunner(self):
        if self.slaveRun():
            return RunTestInSlave()
        else:
            return default.Config.getTestRunner(self)
    def showExecHostsInFailures(self):
        # Always show execution hosts, many different ones are used
        return 1
    def getSubmissionRules(self, test):
        return SubmissionRules(self.optionMap, test)
    def getPerformanceFileMaker(self):
        if self.slaveRun():
            return MakePerformanceFile(self.getMachineInfoFinder(), self.isSlowdownJob)
        else:
            return default.Config.getPerformanceFileMaker(self)
    def getMachineInfoFinder(self):
        if self.slaveRun():
            return MachineInfoFinder()
        else:
            return default.Config.getMachineInfoFinder(self)
    def isSlowdownJob(self, jobUser, jobName):
        return 0
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

class SubmissionRules:
    def __init__(self, optionMap, test):
        self.test = test
        self.optionMap = optionMap
        self.envResource = ""
        self.processesNeeded = self.getProcessesNeeded()
        if os.environ.has_key("QUEUE_SYSTEM_RESOURCE"):
            self.envResource = os.getenv("QUEUE_SYSTEM_RESOURCE")
    def getProcessesNeeded(self):
        if os.environ.has_key("QUEUE_SYSTEM_PROCESSES"):
            return os.environ["QUEUE_SYSTEM_PROCESSES"]
        else:
            return "1"
    def getJobName(self):
        jobName = repr(self.test.app).replace(" ", "_") + self.test.app.versionSuffix() + self.test.getRelPath()
        return self.test.getTmpExtension() + jobName
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
            resources = self.test.app.getCompositeConfigValue("performance_test_resource", "cputime")
            for resource in resources:
                resourceList.append(resource)
        return resourceList
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
        performanceMachines = self.test.app.getCompositeConfigValue("performance_test_machine", "cputime")
        if len(performanceMachines) == 0 or performanceMachines[0] == "none":
            return []

        return performanceMachines
    def getJobFiles(self):
        return "framework_tmp/slavelog", "framework_tmp/slaveerrs"
    def forceOnPerformanceMachines(self):
        if self.optionMap.has_key("perf"):
            return 1

        minTimeForce = self.test.getConfigValue("min_time_for_performance_force")
        if minTimeForce >= 0 and performance.getTestPerformance(self.test) > minTimeForce:
            return 1
        # If we haven't got a log_file yet, we should do this so we collect performance reliably
        logFile = self.test.makeFileName(self.test.getConfigValue("log_file"))
        return not os.path.isfile(logFile)

class SlaveRequestHandler(StreamRequestHandler):
    def handle(self):
        testString = self.rfile.readline().strip()
        test = self.server.getTest(testString)
        test.loadState(self.rfile)

class SlaveServer(TCPServer):
    def __init__(self):
        TCPServer.__init__(self, (socket.gethostname(), 0), SlaveRequestHandler)
        self.testMap = {}
        self.diag = plugins.getDiagnostics("Slave Server")
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
        return self.socketServer.socket.getsockname()
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
        os.chdir(submissionRules.test.writeDirs[0])
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
    def killJob(self, test):
        if not self.jobs.has_key(test) or test in self.killedTests:
            return None, None
        queueSystem = self.getQueueSystem(test)
        jobId, jobName = self.jobs[test]
        queueSystem.killJob(jobId)
        self.killedTests.append(test)
        return jobId, jobName
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
    def __init__(self, submitRuleFunction, optionMap):
        self.loginShell = None
        self.submitRuleFunction = submitRuleFunction
        self.optionMap = optionMap
        self.runOptions = ""
        self.diag = plugins.getDiagnostics("Queue System Submit")
        self.slaveEnv = {}
        self.setUpScriptEngine()
        if os.environ.has_key("TEXTTEST_DIAGDIR"):
            self.slaveEnv["TEXTTEST_DIAGDIR"] = os.path.join(os.getenv("TEXTTEST_DIAGDIR"), self.slaveType())
    def setUpScriptEngine(self):
        # For self-testing: make sure the slave doesn't read the master use cases.
        variables = [ "USECASE_RECORD_STDIN", "USECASE_RECORD_SCRIPT", "USECASE_REPLAY_SCRIPT" ]
        for var in variables:
            self.slaveEnv[var] = ""
    def slaveType(self):
        return "slave"
    def __repr__(self):
        return "Submitting"
    def shouldSubmit(self, test):
        return not test.state.isComplete()
    def __call__(self, test):
        if not self.shouldSubmit(test):
            return
        
        self.tryStartServer()
        command = self.getExecuteCommand(test)
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
    def getExecuteCommand(self, test):
        # Must use exec so as not to create extra processes: SGE's qdel isn't very clever when
        # it comes to noticing extra shells
        tmpDir, local = os.path.split(test.app.writeDirectory)
        commandLine = "exec python " + sys.argv[0] + " -d " + test.app.abspath + " -a " + test.app.name + test.app.versionSuffix() \
                      + " -c " + test.app.checkout + " -tp " + test.getRelPath() + self.getSlaveArgs(test) \
                      + " -tmp " + tmpDir + " " + self.runOptions
        return "exec " + self.loginShell + " -c \"" + commandLine + "\""
    def getSlaveArgs(self, test):
        host, port = QueueSystemServer.instance.getServerAddress()
        return " -" + self.slaveType() + " " + test.getTmpExtension() + " -servaddr " + host + ":" + str(port)
    def tryStartServer(self):
        if not QueueSystemServer.instance:
            QueueSystemServer.instance = QueueSystemServer()
    def setRunOptions(self, app):
        runOptions = []
        runGroup = self.findRunGroup(app)
        for switch in runGroup.switches.keys():
            if self.optionMap.has_key(switch):
                runOptions.append("-" + switch)
        for option in runGroup.options.keys():
            if self.optionMap.has_key(option):
                runOptions.append("-" + option)
                runOptions.append(self.optionMap[option])
        if self.optionMap.has_key("keeptmp"):
            runOptions.append("-keeptmp")
        return string.join(runOptions)
    def setUpDisplay(self, app):
        finder = unixonly.VirtualDisplayFinder(app)
        display = finder.getDisplay()
        if display:
            self.slaveEnv["DISPLAY"] = display
            print "Tests will run with DISPLAY variable set to", display
    def findRunGroup(self, app):
        for group in app.optionGroups:
            if group.name.startswith("How"):
                return group
    def getPostText(self, test, submissionRules):
        name = queueSystemName(test.app)
        return submissionRules.getSubmitSuffix(name)
    def setUpSuite(self, suite):
        name = queueSystemName(suite.app)
        self.describe(suite, " to " + name + " queues")
    def setUpApplication(self, app):
        app.checkBinaryExists()
        self.setUpDisplay(app)
        self.runOptions = self.setRunOptions(app)
        self.loginShell = app.getConfigValue("login_shell")
    def getInterruptActions(self):
        return [ SubmissionMissed() ]

class SubmissionMissed(plugins.Action):
    def __call__(self, test):
        if not test.state.isComplete():
            raise plugins.TextTestError, "Termination already in progress when trying to submit to " + \
                  queueSystemName(test.app)

class KillTestSubmission(plugins.Action):
    def __repr__(self):
        return "Cancelling"
    def __call__(self, test):
        if test.state.isComplete():
            return

        jobId, jobName = self.performKill(test)
        if not jobId:
            return

        self.describeJob(test, jobId, jobName)
        if not self.jobStarted(test):
            self.setSlaveFailed(test)
    def jobStarted(self, test):
        return test.state.hasStarted()
    def performKill(self, test):
        if not QueueSystemServer.instance:
            return None, None
        return QueueSystemServer.instance.killJob(test)
    def setSlaveFailed(self, test):
        failReason, fullText = self.getSlaveFailure(test)
        fullText = failReason + "\n" + fullText
        test.changeState(plugins.TestState("unrunnable", briefText=failReason, \
                                           freeText=fullText, completed=1))
    def getSlaveFailure(self, test):
        slaveErrFile = test.makeFileName("slaveerrs", temporary=1, forComparison=0)
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
    def __repr__(self):
        return "Evaluating"
    def __call__(self, test):
        if test.state.isComplete():
            self.describe(test, self.getPostText(test))
        else:
            return self.WAIT | self.RETRY
    def getPostText(self, test):
        try:
            return test.state.getPostText()
        except AttributeError:
            return " (" + test.state.category + ")"
    def getInterruptActions(self):
        return [ KillTestSubmission(), WaitForKill() ]
    
class WaitForKill(plugins.Action):
    def __init__(self):
        self.testsWaitingForKill = {}
    def __call__(self, test, postText=""):
        if test.state.isComplete():
            return

        attempt = self.getAttempt(test)
        if attempt > 600:
            freeText = "Could not delete " + repr(test) + " in queuesystem: have abandoned it"
            newState = plugins.TestState("abandoned", briefText="job deletion failed", \
                                                      freeText=freeText, completed=1)
            return test.changeState(newState)

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

class MakePerformanceFile(default.MakePerformanceFile):
    def __init__(self, machineInfoFinder, isSlowdownJob):
        default.MakePerformanceFile.__init__(self, machineInfoFinder)
        self.isSlowdownJob = isSlowdownJob
    def writeMachineInformation(self, file, test):
        # Try and write some information about what's happening on the machine
        for machine in test.state.executionHosts:
            for jobLine in self.findRunningJobs(machine):
                file.write(jobLine + "\n")
    def findRunningJobs(self, machine):
        try:
            return self._findRunningJobs(machine)
        except IOError:
            # If system calls to the queue system are interrupted, it shouldn't matter, try again
            return self._findRunningJobs(machine)
    def _findRunningJobs(self, machine):
        # On a multi-processor machine performance can be affected by jobs on other processors,
        # as for example a process can hog the memory bus. Allow subclasses to define how to
        # stop these "slowdown jobs" to avoid false performance failures. Even if they aren't defined
        # as such, print them anyway so the user can judge for himself...
        jobsFromQueue = self.machineInfoFinder.queueMachineInfo.findRunningJobs(machine)
        jobs = []
        for user, jobName in jobsFromQueue:
            descriptor = "Also on "
            if self.isSlowdownJob(user, jobName):
                descriptor = "Suspected of SLOWING DOWN "
            jobs.append(descriptor + machine + " : " + user + "'s job '" + jobName + "'")
        return jobs
        
