
import os, string, signal
from plugins import getDiagnostics, localtime
from time import sleep

# Used by master process for submitting, deleting and monitoring slave jobs
class QueueSystem:
    def getSubmitCommand(self, submissionRules):
        qsubArgs = "-N " + submissionRules.getJobName()
        if submissionRules.processesNeeded != "1":
            qsubArgs += " -pe " + submissionRules.getParallelEnvironment() + " " + \
                        submissionRules.processesNeeded
        queue = submissionRules.findQueue()
        if queue:
            qsubArgs += " -q " + queue
        priority = submissionRules.findPriority()
        if priority:
            qsubArgs += " -p " + str(priority)
        resource = self.getResourceArg(submissionRules)
        if len(resource):
            qsubArgs += " -l " + resource
        outputFile, errorsFile = submissionRules.getJobFiles()
        qsubArgs += " -w e -notify -m n -cwd -b y -V -o " + outputFile + " -e " + errorsFile
        return "qsub " + qsubArgs
    def getResourceArg(self, submissionRules):
        resourceList = submissionRules.findResourceList()
        machines = submissionRules.findMachineList()
        if len(machines):
            resourceList.append("hostname='" + string.join(machines, "|") + "'")
        return string.join(resourceList, ",")
    def findSubmitError(self, stderr):
        errLines = stderr.readlines()
        if len(errLines):
            return errLines[0].strip()
        else:
            return ""
    def killJob(self, jobId):
        self.qdelOutput = os.popen("qdel " + jobId + " 2>&1").read()
        return self.qdelOutput.find("has registered the job") != -1 or self.qdelOutput.find("has deleted job") != -1
    def getJobId(self, line):
        return line.split()[2]
    def findJobId(self, stdout):
        jobId = ""
        for line in stdout.readlines():
            if line.find("has been submitted") != -1:
                jobId = self.getJobId(line)
            else:
                print "Unexpected output from qsub :", line.strip()
        return jobId
    def getJobFailureInfo(self, jobId):
        methods = [ self.getAccountInfo, self.getAccountInfoOldFiles, self.retryAccountInfo ]
        for method in methods:
            acctOutput = method(jobId)
            if acctOutput is not None:
                return acctOutput
        return "SGE lost job:" + jobId + "\n qdel output was as follows:\n" + self.qdelOutput
    def getAccountInfo(self, jobId, extraArgs=""):
        cmdLine = "qacct -j " + jobId + extraArgs
        stdin, stdout, stderr = os.popen3(cmdLine)
        errMsg = stderr.read()
        if len(errMsg) == 0 or errMsg.find("error: job id " + jobId + " not found") == -1:
            return stdout.read()
    def retryAccountInfo(self, jobId):
        sleepTime = 0.5
        for trial in range(9): # would be 10 but we had one already
            # assume failure is because the job hasn't propagated yet, wait a bit
            sleep(sleepTime)
            if sleepTime < 5:
                sleepTime *= 2
            acctOutput = self.getAccountInfo(jobId)
            if acctOutput is not None:
                return acctOutput
            else:
                print "Waiting", sleepTime, "seconds before retrying account info for job", jobId
    def getAccountInfoOldFiles(self, jobId):
        for logNum in range(5):
            # try at most 5 accounting files for now - assume jobs don't run longer than 5 days!
            fileName = self.findAccountingFile(logNum)
            if not fileName:
                return
            acctInfo = self.getAccountInfo(jobId, " -f " + fileName)
            if acctInfo:
                return acctInfo
    def findAccountingFile(self, logNum):
        if os.environ.has_key("SGE_ROOT") and os.environ.has_key("SGE_CELL"):
            findPattern = os.path.join(os.environ["SGE_ROOT"], os.environ["SGE_CELL"])
            acctFile = os.path.join(findPattern, "common", "accounting." + str(logNum))
            if os.path.isfile(acctFile):
                return acctFile        

# Used by slave for producing performance data
class MachineInfo:
    def findActualMachines(self, machineOrGroup):
        # In LSF this unpacks host groups, taking advantage of the fact that they are
        # interchangeable with machines. This is not true in SGE anyway, so don't support it.
        return [ machineOrGroup ]
    def findResourceMachines(self, resource):
        machines = []
        # Hacked workaround for problems with SGE, bug 1513 in their bug system
        # Should really use qhost but that seems flaky
        for line in os.popen("qselect -l '" + resource + "'"):
            fullMachine = line.strip().split("@")[-1]
            machineName = fullMachine.split(".")[0]
            if not machineName in machines:
                machines.append(machineName)
        return machines
    def findRunningJobs(self, machine):
        jobs = []
        user = ""
        for line in os.popen("qstat -r -s r -l hostname='" + machine + "'").xreadlines():
            if line.startswith("job") or line.startswith("----"):
                continue
            if line[0] in string.digits:
                fields = line.split()
                user = fields[-6]
            elif line.find("Full jobname") != -1:
                jobName = line.split(":")[-1].strip()
                jobs.append((user, jobName))
        return jobs

# Interpret what the limit signals mean...
def getLimitInterpretation(origLimitText):
    if origLimitText == "RUNLIMIT1":
        return "RUNLIMIT"
    elif origLimitText == "RUNLIMIT2":
        return "KILLED"
    else:
        return origLimitText
    
# Used by slave to find all execution machines    
def getExecutionMachines():
    hostFile = os.getenv("PE_HOSTFILE")
    if not hostFile or not os.path.isfile(hostFile):
        from socket import gethostname
        return [ gethostname() ]
    hostlines = open(hostFile).readlines()
    hostlist = []
    for line in hostlines:
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        host = parts[0].split(".")[0]
        counter = int(parts[1])
        while counter > 0:
            hostlist.append(host)
            counter = counter - 1
    return hostlist

