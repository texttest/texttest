#!/usr/local/bin/python

import os, string, signal, sys, default, unixonly, performance, respond, batch, plugins, types, predict, guiplugins
from Queue import Queue, Empty
from threading import Thread
from time import sleep
from copy import copy, deepcopy

# Text only relevant to using the parallel configuration directly
helpDescription = """
The queue system configuration is designed to run on a UNIX system with some queuing/load balancing
software installed. This enables tests to be run in parallel on multiple machines across a network.

This is a generic configuration for all such software. The products LSF from Platform Computing,
and Sun Grid Engine are supported via the corresponding modules.
"""

# Text for use by derived configurations as well
queueGeneral = """
When all tests have been submitted to the queueing system, the configuration will
then wait for each test, and provide comparison when each has finished.

It also generates performance checking in a similar way to the unix module. As well as
the CPU time needed by performance.py, it will report the real time and any jobs which
are currently running on the other processors of the execution machine, if it has others.
These have been found to be capable of interfering with the performance of the job.

The environment variables QUEUE_SYSTEM_RESOURCE and QUEUE_SYSTEM_PROCESSES can be used to
turn on queue system functionality for particular parts of the test suite. The first will
always ensure that a queue system resource is specified
(equivalent to -R command line in LSF or -l in SGE), while the second will ensure that
the queueing system makes a request for that number of processes. A single number is a
precise limit, while min,max can specify a range.
"""

batchInfo = """
             Note that it can be useful to send the whole TextTest run to the queue system in batch mode, using LSF's termination
             time feature. If this is done, LSF will send TextTest a signal 10 minutes before the termination time,
             which allows TextTest to kill all remaining jobs and report them as unfinished in its report."""

helpOptions = """
-l         - run in local mode. This means that the framework will not use the queue system, but
             will behave as if the default configuration was being used, and run on the local machine.

-q <queue> - run in named queue

-r <limits>- run tests subject to the time limits (in minutes) represented by <limits>. If this is a single limit
             it will be interpreted as a minimum. If it is two comma-separated values, these are interpreted as
             <minimum>,<maximum>. Empty strings are treated as no limit.

-R <resrc> - Use the queue system resource <resrc>. This is essentially forwarded to LSF's bsub command or SGE's qsub command, so for a full
             list of its capabilities, consult the queue system manual. In LSF, it is particularly useful to use this
             to force a test to go to certain machines, using -R "hname == <hostname>", or to avoid similar machines
             using -R "hname != <hostname>"

-perf      - Force execution on the performance test machines. These are the machines listed in the config file list entry "performance_test_machine".
""" + batch.helpOptions             

def getConfig(optionMap):
    return QueueSystemConfig(optionMap)

def queueSystemName(app):
    return app.getConfigValue("queue_system_module")

# Exception to throw if job got lost, typical SGE SNAFU behaviour
class QueueSystemLostJob(RuntimeError):
    pass

# Use a non-monitoring runTest, but the rest from unix
class RunTestInSlave(unixonly.RunTest):
    def runTest(self, test):
        command = self.getExecuteCommand(test)
        self.describe(test)
        self.diag.info("Running test with command '" + command + "'")
        self.changeToRunningState(test, None)
        os.system(command)
        if plugins.emergencySignal:
            briefText, freeText = self.getKillText(plugins.emergencySignal)
            test.changeState(plugins.TestState("killed", completed=1, briefText=briefText, freeText=freeText))
    def getKillText(self, sig):
        if sig == signal.SIGUSR1:
            return "RUNLIMIT", "Test exceeded queue system's maximum wallclock time allowed"
        elif sig == signal.SIGXCPU:
            return "CPULIMIT", "Test exceeded queue system's maximum cpu time allowed"
        elif sig == signal.SIGUSR2:
            timeStr = plugins.localtime("%H:%M")
            return "killed at " + timeStr, "Test killed explicitly at " + timeStr
        else:
            return "signal " + str(sig), "Terminated by signal " + str(sig)
    def setUpVirtualDisplay(self, app):
        # Assume the master sets DISPLAY for us
        pass
        
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
    def useQueueSystem(self):
        if self.optionMap.has_key("reconnect") or self.optionMap.has_key("l") or self.optionMap.has_key("rundebug"):
            return 0
        return 1
    def _getActionSequence(self, makeDirs):
        if self.optionMap.slaveRun():
            return default.Config._getActionSequence(self, 0)
        if not self.useQueueSystem():
            return default.Config._getActionSequence(self, makeDirs)

        submitter = SubmitTest(self.getSubmissionRules, self.optionMap)
        actions = [ submitter, self.statusUpdater(), default.SaveState() ]
        if makeDirs:
            actions = [ self.getWriteDirectoryMaker() ] + actions
        if not self.optionMap.useGUI():
            actions.append(self.getTestResponder())
        return actions
    def getTestRunner(self):
        if self.optionMap.slaveRun():
            return RunTestInSlave()
        else:
            return default.Config.getTestRunner(self)
    def showExecHostsInFailures(self):
        # Always show execution hosts, many different ones are used
        return 1
    def getSubmissionRules(self, test, nonTestProcess):
        return SubmissionRules(self.optionMap, test, nonTestProcess)
    def statusUpdater(self):
        return UpdateTestStatus()
    def getPerformanceFileMaker(self):
        if self.optionMap.slaveRun():
            return MakePerformanceFile(self.getMachineInfoFinder(), self.isSlowdownJob)
        else:
            return default.Config.getPerformanceFileMaker(self)
    def getMachineInfoFinder(self):
        if self.optionMap.slaveRun():
            return MachineInfoFinder()
        else:
            return default.Config.getMachineInfoFinder(self)
    def isSlowdownJob(self, jobUser, jobName):
        return 0
    def printHelpDescription(self):
        print helpDescription, queueGeneral, predict.helpDescription, performance.helpDescription, respond.helpDescription 
    def printHelpOptions(self, builtInOptions):
        print helpOptions + batchInfo
        default.Config.printHelpOptions(self, builtInOptions)
    def setApplicationDefaults(self, app):
        default.Config.setApplicationDefaults(self, app)
        app.setConfigDefault("default_queue", "texttest_default", "Which queue to submit tests to by default")
        app.setConfigDefault("min_time_for_performance_force", -1, "Minimum CPU time for test to always run on performance machines")
        app.setConfigDefault("queue_system_module", "SGE", "Which queue system (grid engine) software to use. (\"SGE\" or \"LSF\")")
        app.setConfigDefault("performance_test_resource", { "default" : [] }, "Resources to request from queue system for performance testing")
        app.setConfigDefault("parallel_environment_name", "'*'", "(SGE) Which SGE parallel environment to use when SUT is parallel")

class SubmissionRules:
    def __init__(self, optionMap, test, nonTestProcess):
        self.test = test
        self.optionMap = optionMap
        self.processesNeeded = "1"
        self.nonTestProcess = nonTestProcess
        if not nonTestProcess and os.environ.has_key("QUEUE_SYSTEM_PROCESSES"):
            self.processesNeeded = os.environ["QUEUE_SYSTEM_PROCESSES"]
        self.envResource = ""
        if os.environ.has_key("QUEUE_SYSTEM_RESOURCE"):
            self.envResource = os.getenv("QUEUE_SYSTEM_RESOURCE")
    def getSubmitSuffix(self, name):
        queue = self.findQueue()
        if queue:
            return name + " queue " + queue
        else:
            return "default " + name + " queue"
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
        if self.nonTestProcess:
            return self.findDefaultQueue()
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
    def forceOnPerformanceMachines(self):
        if self.nonTestProcess:
            return 0
        
        if self.optionMap.has_key("perf"):
            return 1

        minTimeForce = self.test.getConfigValue("min_time_for_performance_force")
        if minTimeForce >= 0 and performance.getTestPerformance(self.test) > minTimeForce:
            return 1
        # If we haven't got a log_file yet, we should do this so we collect performance reliably
        logFile = self.test.makeFileName(self.test.getConfigValue("log_file"))
        return not os.path.isfile(logFile)

class PollThread(Thread):
    def __init__(self, polledAction):
        Thread.__init__(self)
        self.polledAction = polledAction
        self.setDaemon(1)
        self.diag = plugins.getDiagnostics("Polling")
    def run(self):
        totalTime = self.totalTime()
        while 1:
            self.polledAction()
            newTotalTime = self.totalTime()
            sleepTime = (newTotalTime - totalTime) * 10
            if sleepTime == 0.0:
                sleepTime = 0.1
            self.diag.info("Sleeping for " + str(sleepTime) + " seconds")
            # We must sleep for a bit, or we use the whole CPU (busy-wait)
            sleep(sleepTime)
            totalTime = newTotalTime
    def totalTime(self):
        userTime, sysTime, childUserTime, childSysTime, realTime = os.times()
        self.diag.info("Times: " + str(userTime) + " " + str(sysTime) + " " + str(childUserTime) + str(childSysTime))
        return userTime + sysTime + childUserTime + childSysTime
    
class QueueSystemServer:
    instance = None
    def __init__(self, origEnv):
        self.envString = self.getEnvironmentString(origEnv)
        self.submissionQueue = Queue()
        self.allJobs = {}
        self.queueSystems = {}
        self.submitDiag = plugins.getDiagnostics("Queue System Submit Thread")
        self.updateDiag = plugins.getDiagnostics("Queue System Thread")
        QueueSystemServer.instance = self
        self.submitThread = Thread(target=self.runSubmitThread)
        self.submitThread.setDaemon(1)
        self.submitThread.start()
        self.updateThread = PollThread(self.updateJobs)
        self.updateThread.start()        
    def getJobName(self, test, jobNameFunction):
        jobName = repr(test.app).replace(" ", "_") + test.app.versionSuffix() + test.getRelPath()
        if jobNameFunction:
            jobName = jobNameFunction(test)
        return test.getTmpExtension() + jobName
    def submitJob(self, test, jobNameFunction, submissionRules, command, copyEnv):
        jobName = self.getJobName(test, jobNameFunction)
        envCopy = None
        if copyEnv:
            envCopy = deepcopy(os.environ)
        self.submissionQueue.put((jobName, submissionRules, command, envCopy))
    def findJob(self, test, jobNameFunction = None):
        jobName = self.getJobName(test, jobNameFunction)
        if self.allJobs.has_key(jobName):
            return self.allJobs[jobName]
        else:
            return QueueSystemJob()
    def getJobFailureInfo(self, test, jobNameFunction):
        job = self.findJob(test, jobNameFunction)
        queueSystem = self.getQueueSystem(test)
        return queueSystem.getJobFailureInfo(job.jobId)
    def killJob(self, test, jobNameFunction):
        job = self.findJob(test, jobNameFunction)
        queueSystem = self.getQueueSystem(test)
        return queueSystem.killJob(job.jobId)
    def runSubmitThread(self):
        # only update if there is nothing to submit...
        while 1:
            self.submitDiag.info("Creating job at " + plugins.localtime())
            self.createJobFromQueue()
    def getEnvironmentString(self, envDict):
        envStr = "env -i "
        for key, value in envDict.items():
            envStr += "'" + key + "=" + value + "' "
        return envStr
    def createJobFromQueue(self):
        jobName, submissionRules, command, envCopy = self.submissionQueue.get()
        queueSystem = self.getQueueSystem(submissionRules.test)
        envString = self.envString
        if envCopy:
            envString = self.getEnvironmentString(envCopy)
        submitCommand = queueSystem.getSubmitCommand(jobName, submissionRules)
        fullCommand = envString + submitCommand + " '" + command + "'"
        self.submitDiag.info("Creating job " + jobName + " with command : " + fullCommand)
        # Change directory to the appropriate test dir
        os.chdir(submissionRules.test.writeDirs[0])
        stdin, stdout, stderr = os.popen3(fullCommand)
        errorMessage = queueSystem.findSubmitError(stderr)
        if errorMessage:
            self.allJobs[jobName] = QueueSystemJob("submit_failed", errorMessage)
            self.submitDiag.info("Job not created : " + errorMessage)
        else:
            jobId = queueSystem.findJobId(stdout)
            self.submitDiag.info("Job created with id " + jobId)
            job = QueueSystemJob(jobId)
            queueSystem.activeJobs[jobId] = job
            self.allJobs[jobName] = job
    def getQueueSystem(self, test):
        queueModule = test.app.getConfigValue("queue_system_module").lower()
        if self.queueSystems.has_key(queueModule):
            return self.queueSystems[queueModule]
        
        command = "from " + queueModule + " import QueueSystem as _QueueSystem"
        exec command
        system = _QueueSystem(self.envString)
        self.queueSystems[queueModule] = system
        return system
    def findError(self, stderr):
        for errorMessage in stderr.readlines():
            if errorMessage and errorMessage.find("still trying") == -1:
                return errorMessage
        return ""
    def updateJobs(self):
        self.updateDiag.info("Updating jobs at " + plugins.localtime())
        for system in self.queueSystems.values():
            if len(system.activeJobs):
                system.updateJobs()

class QueueSystemJob:
    def __init__(self, jobId = "not_submitted", errorMessage = ""):
        self.jobId = jobId
        self.errorMessage = errorMessage
        self.machines = []
        if errorMessage:
            self.status = "EXIT"
        else:
            self.status = "PEND"
    def hasStarted(self):
        return self.status != "PEND"
    def hasFinished(self):
        return self.status == "DONE" or self.status == "EXIT"
    def isSubmitted(self):
        return self.jobId != "not_submitted" and len(self.errorMessage) == 0
    def isActive(self):
        return self.isSubmitted() and not self.hasFinished()
        
class SubmitTest(plugins.Action):
    def __init__(self, submitRuleFunction, optionMap):
        self.loginShell = None
        self.submitRuleFunction = submitRuleFunction
        self.optionMap = optionMap
        self.runOptions = ""
        self.origEnv = {}
        for var, value in os.environ.items():
            self.origEnv[var] = value
        self.diag = plugins.getDiagnostics("Queue System Submit")
    def __repr__(self):
        return "Submitting"
    def __call__(self, test):
        if plugins.emergencySignal:
            raise plugins.TextTestError, "Preprocessing not complete by " + \
                  queueSystemName(test.app) + " termination time"

        if test.state.isComplete():
            return
        
        testCommand = self.getExecuteCommand(test)
        return self.runCommand(test, testCommand, None, copyEnv=0)
    def getExecuteCommand(self, test):
        # Must use exec so as not to create extra processes: SGE's qdel isn't very clever when
        # it comes to noticing extra shells
        tmpDir, local = os.path.split(test.app.writeDirectory)
        commandLine = "exec python " + sys.argv[0] + " -d " + test.app.abspath + " -a " + test.app.name + test.app.versionSuffix() \
                      + " -c " + test.app.checkout + " -tp " + test.getRelPath() + " -slave " + test.getTmpExtension() \
                      + " -tmp " + tmpDir + " " + self.runOptions
        return "exec " + self.loginShell + " -c \"" + commandLine + "\""
    def runCommand(self, test, command, jobNameFunction = None, copyEnv = 1):
        submissionRules = self.submitRuleFunction(test, jobNameFunction)
        self.describe(test, jobNameFunction, submissionRules)

        self.tryStartServer()
        self.diag.info("Submitting job : " + command)
        QueueSystemServer.instance.submitJob(test, jobNameFunction, submissionRules, command, copyEnv)
        return self.WAIT
    def tryStartServer(self):
        if not QueueSystemServer.instance:
            QueueSystemServer.instance = QueueSystemServer(self.origEnv)
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
            self.origEnv["DISPLAY"] = display
            print "Tests will run with DISPLAY variable set to", display
            # If we are running with a virtual display, make sure the server knows that...
            self.tryStartServer()
    def findRunGroup(self, app):
        for group in app.optionGroups:
            if group.name.startswith("How"):
                return group
    def describe(self, test, jobNameFunction = None, submissionRules = None):
        name = queueSystemName(test.app)
        suffix = name + " queues"
        if submissionRules:
            suffix = submissionRules.getSubmitSuffix(name)
        if jobNameFunction:
            print test.getIndent() + "Submitting", jobNameFunction(test), "to", suffix
        else:
            plugins.Action.describe(self, test, " to " + suffix)
    def setUpSuite(self, suite):
        self.describe(suite)
    def setUpApplication(self, app):
        app.checkBinaryExists()
        if os.environ.has_key("TEXTTEST_DIAGDIR"):
            self.origEnv["TEXTTEST_DIAGDIR"] = os.path.join(os.getenv("TEXTTEST_DIAGDIR"), "slave")
        self.setUpDisplay(app)
        self.setUpScriptEngine()
        self.runOptions = self.setRunOptions(app)
        self.loginShell = app.getConfigValue("login_shell")
    def setUpScriptEngine(self):
        # For self-testing: make sure the slave doesn't read the master use cases.
        # If it reads anything, it should read its own. Check for "SLAVE_" versions of the variables,
        # set them to the real values
        variables = [ "USECASE_RECORD_STDIN", "USECASE_RECORD_SCRIPT", "USECASE_REPLAY_SCRIPT" ]
        for var in variables:
            self.setUpUseCase(var)
    def setUpUseCase(self, var):
        slaveVar = "SLAVE_" + var
        if os.environ.has_key(slaveVar):
            self.origEnv[var] = os.environ[slaveVar]
        elif os.environ.has_key(var):
            del self.origEnv[var]    
        
class KillTest(plugins.Action):
    jobsKilled = []
    def __init__(self, jobNameFunction):
        self.jobNameFunction = jobNameFunction
        # Don't double-kill jobs, it can cause problems and indeterminism
    def __repr__(self):
        return "Cancelling"
    def __call__(self, test, postText=""):
        if test.state.isComplete() or not QueueSystemServer.instance:
            return
        job = QueueSystemServer.instance.findJob(test, self.jobNameFunction)
        if not job.isActive() or job.jobId in self.jobsKilled:
            return
        name = queueSystemName(test.app)
        if self.jobNameFunction:
            print test.getIndent() + repr(self), self.jobNameFunction(test), "in " + name + postText
        else:
            self.describe(test, " in " + name + postText)
        self.jobsKilled.append(job.jobId)
        QueueSystemServer.instance.killJob(test, self.jobNameFunction)
        
plugins.addCategory("killed", "killed", "were killed by the queue system")

class UpdateStatus(plugins.Action):
    def __init__(self, jobNameFunction = None):
        self.jobNameFunction = jobNameFunction
        self.diag = plugins.getDiagnostics("Queue Status")
        self.killer = KillTest(self.jobNameFunction)
    def __call__(self, test):
        if test.state.isComplete():
            return
        job = QueueSystemServer.instance.findJob(test, self.jobNameFunction)
        if job.errorMessage:
            raise plugins.TextTestError, "Failed to submit to " + queueSystemName(test.app) \
                  + " (" + job.errorMessage.strip() + ")"
        # Take a copy of the job status as it can be updated during this time by the queue thread
        jobStatus = copy(job.status)
        self.diag.info("Job " + job.jobId + " in state " + jobStatus + " for test " + test.name)
        exitStatus = self.processStatus(test, jobStatus, job)
        if jobStatus == "DONE" or jobStatus == "EXIT":
            return exitStatus

        if plugins.emergencySignal:
            postText = " (Emergency finish of job " + str(job.jobId) + ")" 
            self.killer(test, postText)
        return self.WAIT | self.RETRY
    def processStatus(self, test, status, job):
        pass
    def getCleanUpAction(self):
        return self.killer

class UpdateTestStatus(UpdateStatus):
    def __repr__(self):
        return "Reading slave results for"
    def __init__(self):
        UpdateStatus.__init__(self)
        self.logFile = None
        self.testsWaitingForFiles = {}
    def processStatus(self, test, status, job):
        details = ""
        jobDone = status == "DONE" or status == "EXIT"
        summary = status
        if jobDone:
            summary = "RUN"
        machineStr = ""
        if len(job.machines):
            machineStr = string.join(job.machines, ',')
            details += "Executing on " + machineStr + "\n"
            summary += " (" + machineStr + ")"
        details += "Current " + queueSystemName(test.app) + " status = " + status + "\n"
        details += self.getExtraRunData(test)
        if status == "PEND":
            pendState = plugins.TestState("pending", freeText=details, briefText=summary)
            test.changeState(pendState)
        else:
            if not jobDone or not test.state.hasStarted():
                runState = default.Running(job.machines, freeText=details, briefText=summary)
                test.changeState(runState)
            if jobDone:
                if test.loadState():
                    self.describe(test, self.getPostText(test))
                else:
                    return self.handleFileWaiting(test, machineStr)
    def handleFileWaiting(self, test, machineStr):
        if not self.testsWaitingForFiles.has_key(test):
            self.testsWaitingForFiles[test] = 0
        if self.testsWaitingForFiles[test] > 10:
            failReason, fullText = self.getSlaveFailure(test)
            failReason += " on " + machineStr
            fullText = failReason + "\n" + fullText
            return test.changeState(plugins.TestState("unrunnable", briefText=failReason, \
                                                      freeText=fullText, completed=1))

        self.testsWaitingForFiles[test] += 1
        self.describe(test, " : results not yet available, file system wait time " + str(self.testsWaitingForFiles[test]))
        return self.WAIT | self.RETRY
    def getSlaveFailure(self, test):
        slaveErrFile = test.makeFileName("slaveerrs", temporary=1, forComparison=0)
        if os.path.isfile(slaveErrFile):
            errStr = open(slaveErrFile).read()
            if errStr and errStr.find("Traceback") != -1:
                return "Slave exited", errStr
        name = queueSystemName(test.app)
        return name + "/system error", "Full accounting info from " + name + " follows:\n" + \
               QueueSystemServer.instance.getJobFailureInfo(test, self.jobNameFunction)
    def setUpApplication(self, app):
        self.logFile = app.getConfigValue("log_file")
    def getPostText(self, test):
        try:
            return test.state.getPostText()
        except AttributeError:
            return " (" + test.state.category + ")"
    def getExtraRunData(self, test):
        perc = self.calculatePercentage(test)
        if perc > 0:
            return "From log file reckoned to be " + str(perc) + "% complete."
        else:
            return ""
    def calculatePercentage(self, test):
        stdFile = test.makeFileName(self.logFile)
        tmpFile = test.makeFileName(self.logFile, temporary=1)
        if not os.path.isfile(tmpFile) or not os.path.isfile(stdFile):
            return 0
        stdSize = os.path.getsize(stdFile)
        tmpSize = os.path.getsize(tmpFile)
        if stdSize == 0:
            return 0
        return (tmpSize * 100) / stdSize 

class MachineInfoFinder(default.MachineInfoFinder):
    def __init__(self):
        self.queueMachineInfo = None        
    def updateExecutionHosts(self, test):
        machines = self.queueMachineInfo.findAllMachinesForJob()
        if len(machines):
            test.state.executionHosts = machines
    def findPerformanceMachines(self, app, fileStem):
        perfMachines = []
        resources = app.getCompositeConfigValue("performance_test_resource", fileStem)
        for resource in resources:
            perfMachines += self.queueMachineInfo.findResourceMachines(resource)

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
    
        
