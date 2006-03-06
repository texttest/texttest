
import os, string, signal
from plugins import getDiagnostics, localtime
from time import sleep

# Used by master process for submitting, deleting and monitoring slave jobs
class QueueSystem:
    def getSubmitCommand(self, submissionRules):
        # Sungrid doesn't like : or / in job names
        jobName = submissionRules.getJobName()
        qsubArgs = "-N " + jobName.replace(":", "").replace("/", ".")
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
        return self.qdelOutput.find("has registered the job") != -1 
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
        trials = 10
        sleepTime = 0.5
        while trials > 0:
            errMsg, lines = self.tryGetAccounting(jobId)
            if len(errMsg) == 0:
                return string.join(lines)
            # assume errMsg is because the job hasn't propagated yet, wait a bit
            sleep(sleepTime)
            if sleepTime < 5:
                sleepTime *= 2
            trials -= 1
        return "SGE lost job:" + jobId + "\n qdel output was as follows:\n" + self.qdelOutput
    def tryGetAccounting(self, jobId):
        errMsg, lines, found = self.getAccountingInfo(jobId, "")
        logNum = 0
        while found == 0:
            fileName = self.findAccountingFile(logNum)
            if fileName == "":
                found = 1
            else:
                errMsg, lines, found = self.getAccountingInfo(jobId, fileName)
            logNum = logNum + 1
        return errMsg, lines
    def findAccountingFile(self, logNum):
        if os.environ.has_key("SGE_ROOT") and os.environ.has_key("SGE_CELL"):
            findPattern = os.path.join(os.environ["SGE_ROOT"], os.environ["SGE_CELL"])
            acctFile = os.path.join("common", "accounting." + str(logNum))
            if os.path.isfile(acctFile):
                return acctFile
        return ""
    def getAccountingInfo(self, jobId, file):
        if file != "":
            cmdLine = "qacct -f " + file + " -j " + jobId
        else:
            cmdLine = "qacct -j " + jobId
        stdin, stdout, stderr = os.popen3(cmdLine)
        errMsg = stderr.readlines()
        lines = stdout.readlines()
        if len(errMsg) > 0 and errMsg[0].find("error: job id " + jobId + " not found") != -1:
            return errMsg, lines, 0
        else:
            return errMsg, lines, 1

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
            machineName = line.split("@")[-1].split(".")[0]
            if not machineName in machines:
                machines.append(machineName)
        return machines
    def findRunningJobs(self, machine):
        jobs = []
        fieldInfo = 0
        user = ""
        for line in os.popen("qstat -r -s r -l hostname='" + machine + "'").xreadlines():
            if line.startswith("job") or line.startswith("----"):
                fieldInfo = 1
                continue
            if fieldInfo:
                fields = line.split()
                user = fields[-6]
                fieldInfo = 0
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
    if not os.environ.has_key("PE_HOSTFILE"):
        from socket import gethostname
        return [ gethostname() ]
    hostlines = open(os.environ["PE_HOSTFILE"]).readlines()
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

