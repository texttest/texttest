#!/usr/local/bin/python

import os, string, signal, sys, default, unixConfig, performance, respond, batch, plugins, types, predict, guiplugins
from Queue import Queue, Empty
from threading import Thread
from time import sleep
from copy import copy, deepcopy

# Text only relevant to using the LSF configuration directly
helpDescription = """
The LSF configuration is designed to run on a UNIX system with the LSF (Load Sharing Facility)
product from Platform installed.

Its default operation is to submit all jobs to the queue indicated by the config file value
"lsf_queue". To provide more complex rules for queue selection a derived configuration would be
needed.
"""

# Text for use by derived configurations as well
lsfGeneral = """
When all tests have been submitted to LSF, the configuration will then wait for each test in turn,
and provide comparison when each has finished.

Because UNIX is assumed anyway, results are presented using "tkdiff" for the file matching
the "log_file" entry in the config file, and "diff" for everything else. These are more
user friendly but less portable than the default "ndiff".

It also generates performance checking by using the LSF report file to
extract this information. As well as the CPU time needed by performance.py, it will
report the real time and any jobs which are currently running on the other processors of
the execution machine, if it has others. These have been found to be capable of interfering
with the performance of the job.

The environment variables LSF_RESOURCE and LSF_PROCESSES can be used to turn on LSF functionality
for particular parts of the test suite. The first will always ensure that a resource is specified
(equivalent to -R command line), while the second will ensure that LSF makes a request for that number
of processes. A single number is a precise limit, while min,max can specify a range.
"""

batchInfo = """
             Note that it can be useful to send the whole TextTest run to LSF in batch mode, using LSF's termination
             time feature. If this is done, LSF will send TextTest a signal 10 minutes before the termination time,
             which allows TextTest to kill all remaining jobs and report them as unfinished in its report."""

helpOptions = """
-l         - run in local mode. This means that the framework will not use LSF, but will behave as
             if the default configuration was being used, and run on the local machine.

-q <queue> - run in named queue

-r <limits>- run tests subject to the time limits (in minutes) represented by <limits>. If this is a single limit
             it will be interpreted as a minimum. If it is two comma-separated values, these are interpreted as
             <minimum>,<maximum>. Empty strings are treated as no limit.

-R <resrc> - Use the LSF resource <resrc>. This is essentially forwarded to LSF's bsub command, so for a full
             list of its capabilities, consult the LSF manual. However, it is particularly useful to use this
             to force a test to go to certain machines, using -R "hname == <hostname>", or to avoid similar machines
             using -R "hname != <hostname>"

-perf      - Force execution on the performance test machines. Equivalent to -R "hname == <perf1> || hname == <perf2>...",
             where <perf1>, <perf2> etc. are the machines listed in the config file list entry "performance_test_machine".
""" + batch.helpOptions             

def getConfig(optionMap):
    return LSFConfig(optionMap)

emergencyFinish = 0

def tenMinutesToGo(signal, stackFrame):
    print "Received LSF signal for termination in 10 minutes, killing all remaining jobs"
    sys.stdout.flush() # Try not to lose log file information...
    global emergencyFinish
    emergencyFinish = 1

signal.signal(signal.SIGUSR2, tenMinutesToGo)

# Use the non-monitoring version of run test, but the rest from unix
class RunTestInSlave(unixConfig.RunTest):
    def runTest(self, test):
        default.RunTest.runTest(self, test)
    def setUpVirtualDisplay(self, app):
        # Assume the master sets DISPLAY for us
        pass
        
class LSFConfig(unixConfig.UNIXConfig):
    def addToOptionGroup(self, group):
        unixConfig.UNIXConfig.addToOptionGroup(self, group)
        if group.name.startswith("How"):
            group.addSwitch("l", "Run tests locally", nameForOff="Submit tests to LSF")
            group.addSwitch("perf", "Run on performance machines only")
            group.addOption("R", "Request LSF resource")
            group.addOption("q", "Request LSF queue")
    def useLSF(self):
        if self.optionMap.has_key("reconnect") or self.optionMap.has_key("l") or self.optionMap.has_key("rundebug"):
            return 0
        return 1
    def _getActionSequence(self, makeDirs):
        if self.optionMap.slaveRun():
            return unixConfig.UNIXConfig._getActionSequence(self, 0)
        if not self.useLSF():
            return unixConfig.UNIXConfig._getActionSequence(self, makeDirs)

        submitter = SubmitTest(self.findLSFQueue, self.findLSFResource, self.findLSFMachine, self.optionMap)
        actions = [ submitter, self.updaterLSFStatus(), default.SaveState() ]
        if makeDirs:
            actions = [ self.getWriteDirectoryMaker() ] + actions
        if not self.optionMap.useGUI():
            actions.append(self.getTestResponder())
        return actions
    def getTestRunner(self):
        if self.optionMap.slaveRun():
            return RunTestInSlave(self.getLoginShell())
        else:
            return unixConfig.UNIXConfig.getTestRunner(self)
    def updaterLSFStatus(self):
        return UpdateTestLSFStatus()
    def getPerformanceFileMaker(self):
        if self.optionMap.slaveRun():
            return MakePerformanceFile(self.isSlowdownJob)
        else:
            return unixConfig.UNIXConfig.getPerformanceFileMaker(self)
    def findLSFQueue(self, test):
        if self.optionMap.has_key("q"):
            return self.optionMap["q"]
        configQueue = test.app.getConfigValue("lsf_queue")
        if configQueue != "texttest_default":
            return configQueue

        return self.findDefaultLSFQueue(test)
    def findDefaultLSFQueue(self, test):
        return "normal"
    def findLSFResource(self, test):
        resourceList = self.findResourceList(test)
        if len(resourceList) == 0:
            return ""
        elif len(resourceList) == 1:
            return resourceList[0]
        else:
            resource = "(" + resourceList[0] + ")"
            for res in resourceList[1:]:
                resource += " && (" + res + ")"
            return resource
    def findLSFMachine(self, test):
        if not self.forceOnPerformanceMachines(test):
            return ""
        performanceMachines = test.getConfigValue("performance_test_machine")
        if len(performanceMachines) == 0 or performanceMachines[0] == "none":
            return ""
    
        machine = performanceMachines[0]
        if len(performanceMachines) > 1:
            for currMachine in performanceMachines[1:]:
                machine += " " + currMachine
        return machine
    def forceOnPerformanceMachines(self, test):
        if self.optionMap.has_key("perf"):
            return 1

        minTimeForce = test.getConfigValue("min_time_for_performance_force")
        if minTimeForce >= 0 and performance.getTestPerformance(test) > minTimeForce:
            return 1
        # If we haven't got a log_file yet, we should do this so we collect performance reliably
        logFile = test.makeFileName(test.getConfigValue("log_file"))
        return not os.path.isfile(logFile)
    def findResourceList(self, test):
        resourceList = []
        if self.optionMap.has_key("R"):
            resourceList.append(self.optionValue("R"))
        if os.environ.has_key("LSF_RESOURCE"):
            resource = os.getenv("LSF_RESOURCE")
            if len(resource):
                resourceList.append(resource)
        return resourceList
    def isSlowdownJob(self, jobUser, jobName):
        return 0
    def printHelpDescription(self):
        print helpDescription, lsfGeneral, predict.helpDescription, performance.helpDescription, respond.helpDescription 
    def printHelpOptions(self, builtInOptions):
        print helpOptions + batchInfo
        default.Config.printHelpOptions(self, builtInOptions)
    def setApplicationDefaults(self, app):
        unixConfig.UNIXConfig.setApplicationDefaults(self, app)
        app.setConfigDefault("lsf_queue", "texttest_default")
        app.setConfigDefault("min_time_for_performance_force", -1)

class LSFServer:
    instance = None
    def __init__(self, origEnv):
        self.envString = self.getEnvironmentString(origEnv)
        self.submissionQueue = Queue()
        self.allJobs = {}
        self.activeJobs = {}
        self.diag = plugins.getDiagnostics("LSF Thread")
        LSFServer.instance = self
        self.lsfThread = Thread(target=self.runLsfThread)
        self.lsfThread.setDaemon(1)
        self.lsfThread.start()
    def getJobName(self, test, jobNameFunction):
        jobName = repr(test.app).replace(" ", "_") + test.app.versionSuffix() + test.getRelPath()
        if jobNameFunction:
            jobName = jobNameFunction(test)
        return test.getTmpExtension() + jobName
    def submitJob(self, test, jobNameFunction, lsfOptions, command, copyEnv):
        jobName = self.getJobName(test, jobNameFunction)
        envCopy = None
        if copyEnv:
            envCopy = deepcopy(os.environ)
        bsubArgs = "-J " + jobName + " " + lsfOptions + " -u nobody '" + command + "'"
        self.submissionQueue.put((jobName, bsubArgs, envCopy))
    def findJob(self, test, jobNameFunction = None):
        jobName = self.getJobName(test, jobNameFunction)
        if self.allJobs.has_key(jobName):
            return self.allJobs[jobName]
        else:
            return LSFJob()
    def runLsfThread(self):
        while 1:
            # Submit at most 5 jobs, then do an update
            try:
                for i in range(5):
                    self.createJobFromQueue()
            except Empty:
                pass

            if len(self.activeJobs):
                self.updateJobs()
            # We must sleep for a bit, or we use the whole CPU (busy-wait)
            sleep(0.1)
    def getEnvironmentString(self, envDict):
        envStr = "env -i "
        for key, value in envDict.items():
            envStr += "'" + key + "=" + value + "' "
        return envStr
    def createJobFromQueue(self):
        jobName, bsubArgs, envCopy = self.submissionQueue.get_nowait()
        envString = self.envString
        if envCopy:
            envString = self.getEnvironmentString(envCopy)
        command = envString + "bsub " + bsubArgs
        self.diag.info("Creating job " + jobName + " with command : " + command)
        stdin, stdout, stderr = os.popen3(command)
        errorMessage = self.findError(stderr)
        if errorMessage:
            self.allJobs[jobName] = LSFJob("submit_failed", errorMessage)
            self.diag.info("Job not created : " + errorMessage)
        else:
            jobId = self.findJobId(stdout)
            self.diag.info("Job created with id " + jobId)
            job = LSFJob(jobId)
            self.activeJobs[jobId] = job
            self.allJobs[jobName] = job
    def findError(self, stderr):
        for errorMessage in stderr.readlines():
            if errorMessage and errorMessage.find("still trying") == -1:
                return errorMessage
        return ""
    def getJobId(self, line):
        word = line.split()[1]
        return word[1:-1]
    def findJobId(self, stdout):
        for line in stdout.readlines():
            if line.find("is submitted") != -1:
                return self.getJobId(line)
        print "ERROR: unexpected output from bsub!!!"
        return ""
    def updateJobs(self):
        commandLine = self.envString + "bjobs -a -w " + string.join(self.activeJobs.keys())
        stdin, stdout, stderr = os.popen3(commandLine)
        self.parseOutput(stdout)
        self.parseErrors(stderr)
    def parseOutput(self, stdout):
        for line in stdout.xreadlines():
            if line.startswith("JOBID"):
                continue
            words = line.strip().split()
            jobId = words[0]
            job = self.activeJobs[jobId]
            status = words[2]
            if job.status == "PEND" and status != "PEND" and len(words) >= 6:
                fullMachines = words[5].split(':')
                job.machines = map(lambda x: x.split('.')[0], fullMachines)
            if status == "EXIT":
                if self._requeueTest(words):
                    job.machines = []
                    status = "PEND"
            job.status = status
            if status == "EXIT" or status == "DONE":
                del self.activeJobs[jobId]
            self.diag.info("Job " + jobId + " in state " + job.status + " on machines " + repr(job.machines))
    def parseErrors(self, stderr):
        # Assume anything we can't find any more has completed OK
        for errorMessage in stderr.readlines():
            if not errorMessage or errorMessage.find("still trying") != -1:
                continue
            jobId = self.getJobId(errorMessage)
            if not self.activeJobs.has_key(jobId):
                print "ERROR: unexpected output from bjobs :", errorMessage.strip()
                continue
            
            job = self.activeJobs[jobId]
            job.status = "DONE"
            del self.activeJobs[jobId]
    def _requeueTest(self, jobInfoList): # REQUEUE if last two log message bhist lines contains REQUEUE_PEND and Exited
        jobId = jobInfoList[0]
        std = os.popen("bhist -l " + jobId + " 2>&1")
        requeueLine = ""
        exitLine = ""
        for line in std.xreadlines():
            colonParts = line.split(":")
            if len(colonParts) < 4:
                continue
            logMsg = colonParts[3]
            if len(logMsg.strip()) == 0:
                continue
            if logMsg.find("REQUEUE_PEND") != -1:
                requeueLine = colonParts[3]
                exitLine = ""
                continue
            if len(requeueLine) > 0 and logMsg.find("Exited") != -1:
                exitLine = logMsg
                continue
            if logMsg.find("Starting"):
                requeueLine = ""
                exitLine = ""
        if len(requeueLine) > 0:
            return 1
        return 0

class LSFJob:
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
    def kill(self):
        os.system("bkill " + self.jobId + " > /dev/null 2>&1")
    
class SubmitTest(plugins.Action):
    def __init__(self, queueFunction, resourceFunction, machineFunction, optionMap):
        self.queueFunction = queueFunction
        self.resourceFunction = resourceFunction
        self.machineFunction = machineFunction
        self.optionMap = optionMap
        self.runOptions = ""
        self.origEnv = {}
        for var, value in os.environ.items():
            self.origEnv[var] = value
        self.diag = plugins.getDiagnostics("LSF")
    def __repr__(self):
        return "Submitting"
    def __call__(self, test):
        if test.state.isComplete():
            return
        
        global emergencyFinish
        if emergencyFinish:
            raise plugins.TextTestError, "Preprocessing not complete by LSF termination time"

        testCommand = self.getExecuteCommand(test)
        lsfOptions = ""
        if os.environ.has_key("LSF_PROCESSES"):
            lsfOptions += " -n " + os.environ["LSF_PROCESSES"]
        return self.runCommand(test, testCommand, None, lsfOptions, copyEnv=0)
    def getExecuteCommand(self, test):
        tmpDir, local = os.path.split(test.app.writeDirectory)
        slaveLog = test.makeFileName("slavelog", temporary=1, forComparison=0)
        slaveErrs = test.makeFileName("slaveerrs", temporary=1, forComparison=0)
        return "python " + sys.argv[0] + " -d " + test.app.abspath + " -a " + test.app.name + test.app.versionSuffix() \
               + " -c " + test.app.checkout + " -t " + test.getRelPath() + " -slave " + test.getTmpExtension() \
               + " -tmp " + tmpDir + " " + self.runOptions + " > " + slaveLog + " 2> " + slaveErrs
    def runCommand(self, test, command, jobNameFunction = None, commandLsfOptions = "", copyEnv = 1):
        self.describe(test, jobNameFunction)
        
        queueToUse = self.queueFunction(test)
        lsfOptions = " -q " + queueToUse + commandLsfOptions
        resource = self.resourceFunction(test)
        if len(resource):
            lsfOptions += " -R \"" + resource + "\""
        machine = self.machineFunction(test)
        if len(machine):
            lsfOptions += " -m '" + machine + "'"
        if not LSFServer.instance:
            LSFServer.instance = LSFServer(self.origEnv)
        LSFServer.instance.submitJob(test, jobNameFunction, lsfOptions, command, copyEnv)
        return self.WAIT
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
        return string.join(runOptions)
    def findRunGroup(self, app):
        for group in app.optionGroups:
            if group.name.startswith("How"):
                return group
    def describe(self, test, jobNameFunction = None):
        queueToUse = self.queueFunction(test)
        if jobNameFunction:
            print test.getIndent() + "Submitting", jobNameFunction(test), "to LSF queue", queueToUse
        else:
            plugins.Action.describe(self, test, " to LSF queue " + queueToUse)
    def setUpSuite(self, suite):
        self.describe(suite)
    def setUpApplication(self, app):
        app.checkBinaryExists()
        finder = unixConfig.VirtualDisplayFinder(app)
        display = finder.getDisplay()
        if display:
            self.origEnv["DISPLAY"] = display
            print "Tests will run with DISPLAY variable set to", display
        if os.environ.has_key("TEXTTEST_DIAGDIR"):
            self.origEnv["TEXTTEST_DIAGDIR"] = os.path.join(os.getenv("TEXTTEST_DIAGDIR"), "slave")
        self.runOptions = self.setRunOptions(app)
    
class KillTest(plugins.Action):
    jobsKilled = []
    def __init__(self, jobNameFunction):
        self.jobNameFunction = jobNameFunction
        # Don't double-kill jobs, it can cause problems and indeterminism
    def __repr__(self):
        return "Cancelling"
    def __call__(self, test):
        if test.state.isComplete() or not LSFServer.instance:
            return
        job = LSFServer.instance.findJob(test, self.jobNameFunction)
        if not job.isActive() or job.jobId in self.jobsKilled:
            return
        if self.jobNameFunction:
            print test.getIndent() + repr(self), self.jobNameFunction(test), "in LSF"
        else:
            self.describe(test, " in LSF")
        self.jobsKilled.append(job.jobId)
        job.kill()
        
plugins.addCategory("killed", "unfinished", "were unfinished")

class UpdateLSFStatus(plugins.Action):
    def __init__(self, jobNameFunction = None):
        self.jobNameFunction = jobNameFunction
        self.diag = plugins.getDiagnostics("LSF Status")
    def __repr__(self):
        return "Killing"
    def __call__(self, test):
        if test.state.isComplete():
            return
        job = LSFServer.instance.findJob(test, self.jobNameFunction)
        if job.errorMessage:
            raise plugins.TextTestError, "Failed to submit to LSF (" + job.errorMessage.strip() + ")"
        # Take a copy of the job status as it can be updated during this time by the LSF thread
        jobStatus = copy(job.status)
        self.diag.info("Job " + job.jobId + " in state " + jobStatus + " for test " + test.name)
        exitStatus = self.processStatus(test, jobStatus, job.machines)
        if jobStatus == "DONE" or jobStatus == "EXIT":
            return exitStatus

        global emergencyFinish
        if emergencyFinish:
            if self.jobNameFunction:
                print test.getIndent() + "Killing", self.jobNameFunction(test), "(Emergency finish)"
            else:
                print test.getIndent() + "Killing", repr(test), "(Emergency finish)"
                test.changeState(plugins.TestState("killed", completed=1))
            job.kill()
            return
        return self.WAIT | self.RETRY
    def processStatus(self, test, status, machines):
        pass
    def getCleanUpAction(self):
        return KillTest(self.jobNameFunction)

class UpdateTestLSFStatus(UpdateLSFStatus):
    def __repr__(self):
        return "Reading slave results for"
    def __init__(self):
        UpdateLSFStatus.__init__(self)
        self.logFile = None
        self.testsWaitingForFiles = {}
    def processStatus(self, test, status, machines):
        details = ""
        summary = status
        machineStr = ""
        if len(machines):
            machineStr = string.join(machines, ',')
            details += "Executing on " + machineStr + os.linesep
            summary += " (" + machineStr + ")"
        details += "Current LSF status = " + status + os.linesep
        details += self.getExtraRunData(test)
        if status == "PEND":
            pendState = plugins.TestState("pending", freeText=details, briefText=summary)
            test.changeState(pendState)
        elif status == "DONE" or status == "EXIT":
            if test.loadState():
                self.describe(test, self.getPostText(test))
            else:
                return self.handleFileWaiting(test, machineStr)
        else:
            runState = plugins.TestState("running", freeText=details, briefText=summary, started=1)
            test.changeState(runState)
    def handleFileWaiting(self, test, machineStr):
        if not self.testsWaitingForFiles.has_key(test):
            self.testsWaitingForFiles[test] = 0
        if self.testsWaitingForFiles[test] > 10:
            raise plugins.TextTestError, "No results produced on " + machineStr + ", presuming problems running test there"

        self.testsWaitingForFiles[test] += 1
        self.describe(test, " : results not yet available, file system wait time " + str(self.testsWaitingForFiles[test]))
        return self.WAIT | self.RETRY
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

class MakePerformanceFile(unixConfig.MakePerformanceFile):
    def __init__(self, isSlowdownJob):
        unixConfig.MakePerformanceFile.__init__(self)
        self.isSlowdownJob = isSlowdownJob
        self.timesWaitedForLSF = 0
    def findExecutionMachines(self, test):
        hosts = os.environ["LSB_HOSTS"].split(":")
        return [ host.split(".")[0] for host in hosts ] 
    def findPerformanceMachines(self, app):
        rawPerfMachines = unixConfig.MakePerformanceFile.findPerformanceMachines(self, app)
        perfMachines = []
        for machine in rawPerfMachines:
            perfMachines += self.findActualMachines(machine)
        return perfMachines
    def findActualMachines(self, machine):
        # 'machine' may actually be a host group
        machines = []
        for line in os.popen("bhosts " + machine + " 2>&1"):
            if line.startswith("HOST_NAME"):
                continue
            machines.append(line.split()[0].split(".")[0])
        return machines
    def writeMachineInformation(self, file, executionMachines):
        # Try and write some information about what's happening on the machine
        for machine in executionMachines:
            for jobLine in self.findRunningJobs(machine):
                file.write(jobLine + os.linesep)
    def findRunningJobs(self, machine):
        try:
            return self._findRunningJobs(machine)
        except IOError:
            # If bjobs is interrupted, it shouldn't matter, try again
            return self._findRunningJobs(machine)
    def _findRunningJobs(self, machine):
        # On a multi-processor machine performance can be affected by jobs on other processors,
        # as for example a process can hog the memory bus. Allow subclasses to define how to
        # stop these "slowdown jobs" to avoid false performance failures. Even if they aren't defined
        # as such, print them anyway so the user can judge for himself...
        jobs = []
        for line in os.popen("bjobs -m " + machine + " -u all -w 2>&1 | grep RUN").xreadlines():
            fields = line.split()
            user = fields[1]
            jobName = fields[6]
            descriptor = "Also on "
            if self.isSlowdownJob(user, jobName):
                descriptor = "Suspected of SLOWING DOWN "
            jobs.append(descriptor + machine + " : " + user + "'s job '" + jobName + "'")
        return jobs

