#!/usr/local/bin/python

import os, time, string, signal, sys, default, unixConfig, performance, respond, batch, plugins, types, predict

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
    global emergencyFinish
    emergencyFinish = 1

signal.signal(signal.SIGUSR2, tenMinutesToGo)

class LSFConfig(unixConfig.UNIXConfig):
    def getArgumentOptions(self):
        options = unixConfig.UNIXConfig.getArgumentOptions(self)
        options["R"] = "Request LSF resource"
        options["q"] = "Request LSF queue"
        return options
    def getSwitches(self):
        switches = unixConfig.UNIXConfig.getSwitches(self)
        switches["l"] = "Run tests locally (not LSF)"
        switches["perf"] = "Run on performance machines only"
        return switches
    def useLSF(self):
        if self.optionMap.has_key("reconnect") or self.optionMap.has_key("l") or self.optionMap.has_key("rundebug"):
            return 0
        return 1
    def getTestRunner(self):
        if not self.useLSF():
            return unixConfig.UNIXConfig.getTestRunner(self)
        else:
            return SubmitTest(self.findLSFQueue, self.findLSFResource)
    def getPerformanceFileMaker(self):
        if self.useLSF():
            return MakePerformanceFile(self.isSlowdownJob)
        else:
            return unixConfig.UNIXConfig.getPerformanceFileMaker(self)
    def queueDecided(self, test):
        return self.optionMap.has_key("q")
    def findLSFQueue(self, test):
        if self.queueDecided(test):
            return self.optionMap["q"]
        return test.app.getConfigValue("lsf_queue")
    def findLSFResource(self, test):
        resourceList = self.findResourceList(test.app)
        if len(resourceList) == 0:
            return ""
        elif len(resourceList) == 1:
            return resourceList[0]
        else:
            resource = "(" + resourceList[0] + ")"
            for res in resourceList[1:]:
                resource += " && (" + res + ")"
            return resource
    def findResourceList(self, app):
        resourceList = []
        if self.optionMap.has_key("R"):
            resourceList.append(self.optionValue("R"))
        if self.optionMap.has_key("perf"):
            performanceMachines = app.getConfigList("performance_test_machine")
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
        return plugins.CompositeAction([ self.getWaitingAction(), self.getFileCollator() ])
    def getFileCollator(self):
        return unixConfig.UNIXConfig.getTestCollator(self)
    def getWaitingAction(self):
        if not self.useLSF():
            return plugins.Action()
        else:
            return plugins.CompositeAction([ Wait(), self.updaterLSFStatus() ])
    def updaterLSFStatus(self):
        return UpdateLSFStatus()
    def isSlowdownJob(self, jobUser, jobName):
        return 0
    def printHelpDescription(self):
        print helpDescription, lsfGeneral, predict.helpDescription, performance.helpDescription, respond.helpDescription 
    def printHelpOptions(self, builtInOptions):
        print helpOptions + batchInfo
        default.Config.printHelpOptions(self, builtInOptions)

class LSFJob:
    def __init__(self, test):
        self.name = test.getTmpExtension() + repr(test.app) + test.app.versionSuffix() + test.getRelPath()
        self.app = test.app
    def hasStarted(self):
        retstring = self.getFile("-r").readline()
        return retstring.find("not found") == -1
    def hasFinished(self):
        retstring = self.getFile().readline()
        return retstring.find("not found") != -1
    def kill(self):
        os.system("bkill -J " + self.name + " > /dev/null 2>&1")
    def getStatus(self):
        file = self.getFile("-w -a")
        lines = file.readlines()
        if len(lines) == 0:
            return "DONE", None
        data = lines[-1].strip().split()
        status = data[2]
        if status == "PEND" or len(data) < 6:
            return status, None
        else:
            execMachine = data[5].split('.')[0]
            return status, execMachine
    def getProcessIdWithoutLSF(self, firstpid):
        status, machine = self.getStatus()
        if machine:
            stdout = os.popen("rsh " + machine + " pstree -p -l " + firstpid + " 2>&1")
            psline = stdout.readlines()[0]
            batchpos = psline.find(os.path.basename(self.app.getConfigValue("binary")))
            if batchpos != -1:
                apcj = psline[batchpos:].split('---')
                if len(apcj) > 1:
                    pid = apcj[1].split('(')[-1].split(')')[0]
                    return pid
        return []
    def getProcessId2(self):
        for line in self.getFile("-l").xreadlines():
            print line
            pos = line.find("PIDs")
            if pos != -1:
                pids = line[pos + 6:].strip().split(' ')
                if len(pids) >= 4:
                    return pids[-1]
                # Try to figure out the PID, without having to wait for LSF.
                if len(pids) == 1:
                    return self.getProcessIdWithoutLSF(pids[0])
        return []
    def getProcessId(self):
        std = os.popen("bhist -l -J " + self.name + " 2>&1")
        for line in std.xreadlines():
            pos = line.find("Starting")
            if pos != -1:
                rootpid = line[pos + 14:].split(')')[0]
                return self.getProcessIdWithoutLSF(rootpid)
        return []
    def getFile(self, options = ""):
        return os.popen("bjobs -J " + self.name + " " + options + " 2>&1")
    
class SubmitTest(unixConfig.RunTest):
    def __init__(self, queueFunction, resourceFunction):
        self.queueFunction = queueFunction
        self.resourceFunction = resourceFunction
        self.diag = plugins.getDiagnostics("LSF")
    def __repr__(self):
        return "Submitting"
    def runTest(self, test):
        self.describe(test)
        queueToUse = self.queueFunction(test)
        testCommand = self.getExecuteCommand(test)
        reportfile =  test.makeFileName("lsfreport", temporary=1, forComparison=0)
        lsfJob = LSFJob(test)
        lsfOptions = "-J " + lsfJob.name + " -q " + queueToUse + " -o " + reportfile + " -u nobody"
        resource = self.resourceFunction(test)
        if len(resource):
            lsfOptions += " -R '" + resource + "'"
        if os.environ.has_key("LSF_PROCESSES"):
            lsfOptions += " -n " + os.environ["LSF_PROCESSES"]
        commandLine = "bsub " + lsfOptions + " '" + testCommand + "' > " + reportfile
        self.diag.info("Submitting with command : " + commandLine)
        stdin, stdout, stderr = os.popen3(commandLine)
        errorMessage = stderr.readline()
        if errorMessage and errorMessage.find("still trying") == -1:
            raise plugins.TextTestError, "Failed to submit to LSF (" + errorMessage.strip() + ")"
    def describe(self, test):
        queueToUse = self.queueFunction(test)
        unixConfig.RunTest.describe(self, test, " to LSF queue " + queueToUse)
    def changeState(self, test):
        # Don't change state just because we submitted to LSF
        pass
    def setUpApplication(self, app):
        unixConfig.RunTest.setUpApplication(self, app)
        app.setConfigDefault("lsf_queue", "normal")
        app.setConfigDefault("lsf_processes", "1")
    def getCleanUpAction(self):
        return KillTest()

class KillTest(plugins.Action):
    def __repr__(self):
        return "Cancelling"
    def __call__(self, test):
        job = LSFJob(test)
        if job.hasFinished():
            return
        self.describe(test, " in LSF")
        job.kill()
        
class Wait(plugins.Action):
    def __init__(self):
        self.eventName = "completion"
    def __repr__(self):
        return "Waiting for " + self.eventName + " of"
    def __call__(self, test):
        job = LSFJob(test)
        if self.checkCondition(job):
            return
        self.describe(test, "...")
        while not self.checkCondition(job):
            global emergencyFinish
            if emergencyFinish:
                print "Emergency finish: killing job!"
                job.kill()
                test.changeState(test.KILLED, "Killed by LSF emergency finish")
                return
            time.sleep(2)
    # Involves sleeping, don't do it from GUI
    def getInstructions(self, test):
        return []
    def checkCondition(self, job):
        try:
            return job.hasFinished()
        # Can get interrupted system call here, which is bad. Assume not finished.
        except IOError:
            return 0

class UpdateLSFStatus(plugins.Action):
    def __init__(self):
        self.logFile = None
    def __repr__(self):
        return "Updating LSF status for"
    def __call__(self, test):
        job = LSFJob(test)
        status, machine = job.getStatus()
        if status == "DONE" or status == "EXIT":
            return
        if status != "PEND":
            perc = self.calculatePercentage(test)
            details = ""
            if machine != None:
                details += "Executing on " + machine + os.linesep

            details += "Current LSF status = " + status + os.linesep
            if perc > 0:
                details += "From log file reckoned to be " + str(perc) + "% complete."
            test.changeState(test.RUNNING, details)
        return "wait"
    def setUpApplication(self, app):
        app.setConfigDefault("log_file", "output")
        self.logFile = app.getConfigValue("log_file")
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

        os.remove(tmpFile)
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


