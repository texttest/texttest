#!/usr/local/bin/python

import os, time, string, signal, sys, default, unixConfig, performance, respond, batch, plugins, types, predict, guiplugins

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

class LSFConfig(unixConfig.UNIXConfig):
    def addToOptionGroup(self, group):
        unixConfig.UNIXConfig.addToOptionGroup(self, group)
        if group.name.startswith("How"):
            group.addSwitch("l", "Run tests locally (not LSF)")
            group.addSwitch("perf", "Run on performance machines only")
            group.addOption("R", "Request LSF resource")
            group.addOption("q", "Request LSF queue")
    def useLSF(self):
        if self.optionMap.has_key("reconnect") or self.optionMap.has_key("l") or self.optionMap.has_key("rundebug"):
            return 0
        return 1
    def getTestRunner(self):
        if not self.useLSF():
            return unixConfig.UNIXConfig.getTestRunner(self)
        else:
            return SubmitTest(self.getLoginShell(), self.findLSFQueue, self.findLSFResource)
    def getPerformanceFileMaker(self):
        if self.useLSF():
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
        if self.forceOnPerformanceMachines(test):
            performanceMachines = test.getConfigValue("performance_test_machine")
            if len(performanceMachines) > 0 and performanceMachines[0] != "none":
                resource = "select[hname == " + performanceMachines[0]
                if len(performanceMachines) > 1:
                    for machine in performanceMachines[1:]:
                        resource += " || hname == " + machine
                resourceList.append(resource + "]")
        if os.environ.has_key("LSF_RESOURCE"):
            resource = os.getenv("LSF_RESOURCE")
            if len(resource):
                resourceList.append(resource)
        return resourceList
    def getTestCollator(self):
        return [ self.getWaitingAction(), self.getFileCollator() ]
    def getFileCollator(self):
        return unixConfig.UNIXConfig.getTestCollator(self)
    def getWaitingAction(self):
        if not self.useLSF():
            return None
        else:
            return self.updaterLSFStatus()
    def updaterLSFStatus(self):
        return UpdateTestLSFStatus()
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

class LSFJob:
    def __init__(self, test, jobNameFunction = None):
        jobName = repr(test.app) + test.app.versionSuffix() + test.getRelPath()
        if jobNameFunction:
            jobName = jobNameFunction(test)
        self.name = test.getTmpExtension() + jobName
        self.app = test.app
    def hasStarted(self):
        retstring = self.getStringFromLSF("-r")
        return retstring.find("not found") == -1
    def hasFinished(self):
        retstring = self.getStringFromLSF()
        return retstring.find("not found") != -1
    def kill(self):
        os.system("bkill -J " + self.name + " > /dev/null 2>&1")
    def getStatus(self):
        try:
            return self._getStatus()
        except IOError:
            # Assume this is interrupted system call and keep trying
            return self.getStatus()
    def _getStatus(self):
        lsfOutput = self.getStringFromLSF("-w -a")
        if len(lsfOutput) == 0:
            return "DONE", None
        if lsfOutput.find("not found") != -1:
            # If it doesn't exist we can assume it's done, it's the same effect...
            return "DONE", None
        data = lsfOutput.split()
        status = data[2]
        if status == "EXIT":
            if self._requeueTest(data):
                return "PEND", None
        if status == "PEND" or len(data) < 6:
            return status, None
        else:
            execMachine = data[5].split('.')[0]
            return status, execMachine
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
    def getProcessIdWithoutLSF(self, firstpid):
        status, machine = self.getStatus()
        if machine:
            pslines = os.popen("rsh " + machine + " pstree -p -l " + firstpid + " 2>&1").readlines()
            if len(pslines) == 0:
                return []
            psline = pslines[0]
            batchpos = psline.find(os.path.basename(self.app.getConfigValue("binary")))
            if batchpos != -1:
                apcj = psline[batchpos:].split('---')
                if len(apcj) > 1:
                    pid = apcj[1].split('(')[-1].split(')')[0]
                    return pid
        return []
    def getProcessId(self):
        for line in self.getFile("-l").xreadlines():
            pos = line.find("PIDs")
            if pos != -1:
                pids = line[pos + 6:].strip().split(' ')
                if len(pids) >= 4:
                    return pids[-1]
                # Try to figure out the PID, without having to wait for LSF.
                if len(pids) == 1:
                    return self.getProcessIdWithoutLSF(pids[0])
        return []
    def getFile(self, options = ""):
        return os.popen("bjobs -J " + self.name + " " + options + " 2>&1")
    def getStringFromLSF(self, options = ""):
        file = self.getFile(options)
        lines = file.readlines()
        if len(lines) == 0:
            return ""
        return lines[-1].strip()        
    
class SubmitTest(unixConfig.RunTest):
    def __init__(self, loginShell, queueFunction, resourceFunction):
        unixConfig.RunTest.__init__(self, loginShell)
        self.queueFunction = queueFunction
        self.resourceFunction = resourceFunction
        self.diag = plugins.getDiagnostics("LSF")
    def __repr__(self):
        return "Submitting"
    def runTest(self, test):
        global emergencyFinish
        if emergencyFinish:
            raise plugins.TextTestError, "Preprocessing not complete by LSF termination time"
        testCommand = self.getExecuteCommand(test)
        lsfOptions = ""
        if os.environ.has_key("LSF_PROCESSES"):
            lsfOptions += " -n " + os.environ["LSF_PROCESSES"]
        return self.runCommand(test, testCommand, None, lsfOptions)
    def runCommand(self, test, command, jobNameFunction = None, commandLsfOptions = ""):
        self.describe(test, jobNameFunction)
        
        queueToUse = self.queueFunction(test)
        repFileName = "lsfreport"
        if jobNameFunction:
            repFileName += jobNameFunction(test)
        reportfile =  test.makeFileName(repFileName, temporary=1, forComparison=0)
        lsfJob = LSFJob(test, jobNameFunction)
        lsfOptions = "-J " + lsfJob.name + " -q " + queueToUse + " -o " + reportfile + " -u nobody" + commandLsfOptions
        resource = self.resourceFunction(test)
        if len(resource):
            lsfOptions += " -R '" + resource + "'"
        commandLine = "bsub " + lsfOptions + " '" + command + "' > " + reportfile
        self.diag.info("Submitting with command : " + commandLine)
        stdin, stdout, stderr = os.popen3(commandLine)
        for errorMessage in stderr.readlines():
            if errorMessage and errorMessage.find("still trying") == -1:
                raise plugins.TextTestError, "Failed to submit to LSF (" + errorMessage.strip() + ")"
        return self.WAIT
    def describe(self, test, jobNameFunction = None):
        queueToUse = self.queueFunction(test)
        if jobNameFunction:
            print test.getIndent() + "Submitting", jobNameFunction(test), "to LSF queue", queueToUse
        else:
            unixConfig.RunTest.describe(self, test, " to LSF queue " + queueToUse)
    def buildCommandFile(self, test, cmdFile, testCommand):
        self.diag.info("Building command file at " + cmdFile)
        f = open(cmdFile, "w")
        # LSF is meant to ensure that directories are transferred,
        # but this is error prone with the AMD automounter. Best to make sure...
        curDir = test.getDirectory(temporary=1)
        f.write("cd " + curDir + os.linesep)
        f.write(testCommand + os.linesep)
        f.close()
        return cmdFile
    def changeState(self, test):
        # Don't change state just because we submitted to LSF
        pass

class KillTest(plugins.Action):
    jobsKilled = []
    def __init__(self, jobNameFunction):
        self.jobNameFunction = jobNameFunction
        # Don't double-kill jobs, it can cause problems and indeterminism
    def __repr__(self):
        return "Cancelling"
    def __call__(self, test):
        if test.state > test.RUNNING:
            return
        job = LSFJob(test, self.jobNameFunction)
        if job.hasFinished() or job.name in self.jobsKilled:
            return
        if self.jobNameFunction:
            print test.getIndent() + repr(self), self.jobNameFunction(test), "in LSF"
        else:
            self.describe(test, " in LSF")
        self.jobsKilled.append(job.name)
        job.kill()
        
class Wait(plugins.Action):
    def __init__(self, jobNameFunction = None):
        self.eventName = "completion"
        self.jobNameFunction = jobNameFunction
    def __repr__(self):
        return "Waiting for " + self.eventName + " of"
    def __call__(self, test):
        job = LSFJob(test, self.jobNameFunction)
        if self.checkCondition(job):
            return
        postText = "..."
        if self.jobNameFunction:
            postText += "(" + self.jobNameFunction(test) + ")"
        self.describe(test, postText)
        while not self.checkCondition(job):           
            time.sleep(2)
    def checkCondition(self, job):
        try:
            return job.hasFinished()
        # Can get interrupted system call here, which is bad. Assume not finished.
        except IOError:
            return 0


class UpdateLSFStatus(plugins.Action):
    def __init__(self, jobNameFunction = None):
        self.jobNameFunction = jobNameFunction
        self.diag = plugins.getDiagnostics("LSF Status")
    def __repr__(self):
        return "Killing"
    def __call__(self, test):
        # Don't look for unrunnable tests...
        if test.state == test.UNRUNNABLE:
            return
        job = LSFJob(test, self.jobNameFunction)
        status, machine = job.getStatus()
        self.diag.info("Job " + job.name + " in state " + status + " for test " + test.name)
        exitStatus = self.processStatus(test, status, machine)
        if status == "DONE" or status == "EXIT":
            return exitStatus

        global emergencyFinish
        if emergencyFinish:
            if self.jobNameFunction:
                print test.getIndent() + "Killing", self.jobNameFunction(test), "(Emergency finish)"
            else:
                self.describe(test, " (Emergency finish)")
                test.changeState(test.KILLED, "Killed by LSF emergency finish")
            job.kill()
            return
        return self.WAIT | self.RETRY
    def processStatus(self, test, status, machine):
        pass
    def getCleanUpAction(self):
        return KillTest(self.jobNameFunction)

class UpdateTestLSFStatus(UpdateLSFStatus):
    def __init__(self):
        UpdateLSFStatus.__init__(self)
        self.logFile = None
    def processStatus(self, test, status, machine):
        details = ""
        if machine != None:
            details += "Executing on " + machine + os.linesep
            
        details += "Current LSF status = " + status + os.linesep
        details += self.getExtraRunData(test)
        if status == "PEND":
            test.changeState(test.NOT_STARTED, details)
        else:
            test.changeState(test.RUNNING, details)
    def setUpApplication(self, app):
        self.logFile = app.getConfigValue("log_file")
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
        tmpFile = test.makeFileName("lsfreport", temporary=1, forComparison=0)
        executionMachines = []
        activeRegion = 0
        for line in open(tmpFile).xreadlines():
            if line.find("executed on host") != -1 or (activeRegion and line.find("home directory") == -1):
                executionMachines.append(self.parseMachine(line))
                activeRegion = 1
            else:
                activeRegion = 0
        if len(executionMachines) == 0:
            # Assume race condition with LSF writing the report... wait a bit and try again
            if self.timesWaitedForLSF < 10:
                time.sleep(2)
                self.timesWaitedForLSF += 1
                return self.findExecutionMachines(test)
            else:
                print "WARNING : Could not find machines in LSF report, keeping it"
                return executionMachines

        return executionMachines
    def parseMachine(self, line):
        start = string.find(line, "<")
        end = string.find(line, ">", start)
        fullName = line[start + 1:end].replace("1*", "")
        return string.split(fullName, ".")[0]
    def writeMachineInformation(self, file, executionMachines):
        # Try and write some information about what's happening on the machine
        for machine in executionMachines:
            for jobLine in self.findRunningJobs(machine):
                file.write(jobLine + os.linesep)
    def findRunningJobs(self, machine):
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

