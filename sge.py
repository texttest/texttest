
import os, string, signal
from plugins import getDiagnostics, localtime
from queuesystem import QueueSystemLostJob
from time import sleep

class QueueSystem:
    def __init__(self, envString):
        self.activeJobs = {}
        self.envString = envString
        self.diag = getDiagnostics("Queue System Thread")
        self.jobExitStatusCache = {}
    def getSubmitCommand(self, jobName, submissionRules):
        # Sungrid doesn't like : or / in job names
        qsubArgs = "-N " + jobName.replace(":", "").replace("/", ".")
        if submissionRules.processesNeeded != "1":
            qsubArgs += " -pe " + submissionRules.getParallelEnvironment() + " " + \
                        submissionRules.processesNeeded
        queue = submissionRules.findQueue()
        if queue:
            qsubArgs += " -q " + queue
        resource = self.getResourceArg(submissionRules)
        if len(resource):
            qsubArgs += " -l " + resource
        qsubArgs += " -w e -notify -m n -cwd -b y -V -o framework_tmp/slavelog -e framework_tmp/slaveerrs"
        return "qsub " + qsubArgs
    def findSubmitError(self, stderr):
        errLines = stderr.readlines()
        if len(errLines):
            return errLines[0].strip()
        else:
            return ""
    def findExceededLimit(self, jobId):
        exitStatus = self.exitStatus(jobId)
        if exitStatus is None:
            return ""
        if exitStatus > 128:
            terminatingSignal = exitStatus - 128
            cpuSignals = [ signal.SIGXCPU, 24, 30, 33 ]
            realSignals = [ signal.SIGUSR1, 10, 16 ]
            if terminatingSignal in cpuSignals:
                return "cpu"
            if terminatingSignal in realSignals:
                return "real"
            return "killed with signal " + str(terminatingSignal)
        return ""
    def killJob(self, jobId):
        os.system("qdel " + jobId + " > /dev/null 2>&1")
    def getJobId(self, line):
        return line.split()[2]
    def findJobId(self, stdout):
        for line in stdout.readlines():
            if line.find("has been submitted") != -1:
                return self.getJobId(line)
            else:
                print "Unexpected output from qsub :", line.strip()
        return ""
    def getResourceArg(self, submissionRules):
        resourceList = submissionRules.findResourceList()
        machines = submissionRules.findMachineList()
        if len(machines):
            resourceList.append("hostname='" + string.join(machines, "|") + "'")
        return string.join(resourceList, ",")
    def getStatus(self, sgeStat, states, jobId):
        # Use LSF status names for now as queuesystem.py expects them. man qstat gives
        # states as d(eletion), t(ransfering), r(unning), R(estarted), s(uspended),
        # S(uspended),  T(hreshold),  w(aiting) or h(old).
        # However, both pending and completed jobs seem to have state 'qw'
        self.diag.info("Got status = " + sgeStat)
        if sgeStat.startswith("r") or sgeStat.startswith("d"):
            return "RUN"
        elif sgeStat.startswith("t") or sgeStat.startswith("w"):
            return "PEND"
        elif sgeStat.startswith("q"):
            if states == "z":
                return "DONE"
            else:
                return "PEND"
        elif sgeStat.startswith("s") or sgeStat.startswith("S") or sgeStat.startswith("T"):
            return "SSUSP"
        elif sgeStat.startswith("h"):
            return "USUSP"
        else:
            return sgeStat
    def exitedWithError(self, job):
        if self.jobExitStatusCache.has_key(job.jobId):
            status = self.jobExitStatusCache[job.jobId]
            if status is None:
                raise QueueSystemLostJob, "SGE already lost job:" + job.jobId
        trials = 10
        sleepTime = 0.5
        while trials > 0:
            exitStatus = self.exitStatus(job.jobId)
            if not exitStatus is None:
                return exitStatus > 0
            sleep(sleepTime)
            if sleepTime < 5:
                sleepTime *= 2
            trials -= 1
        self.jobExitStatusCache[job.jobId] = None
        raise QueueSystemLostJob, "SGE lost job:" + job.jobId
    def exitStatus(self, jobId):
        if self.jobExitStatusCache.has_key(jobId):
            return self.jobExitStatusCache[jobId]
        errMsg, lines = self.getAccounting(jobId)
        if len(errMsg):
            # assume this is because the job hasn't propagated yet, wait a bit
            return None
        exitStatus = 1
        for line in lines:
            if line.startswith("exit_status"):
                exitStatus = int(line.strip().split()[-1])
                break
        self.jobExitStatusCache[jobId] = exitStatus
        return exitStatus
    def getAccounting(self, jobId):
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
        self.diag.info(cmdLine + " at " + localtime())
        stdin, stdout, stderr = os.popen3(cmdLine)
        errMsg = stderr.readlines()
        lines = stdout.readlines()
        if len(errMsg) > 0 and errMsg[0].find("error: job id " + jobId + " not found") != -1:
            return errMsg, lines, 0
        else:
            return errMsg, lines, 1
    def updateJobs(self):
        self._updateJobs("prs")
        self._updateJobs("z")
    def _updateJobs(self, states):
        commandLine = self.envString + "qstat -s " + states + " -u " + os.environ["USER"]
        self.diag.info("At " + localtime() + " : qstat -s " + states)
        stdin, stdout, stderr = os.popen3(commandLine)
        self.parseQstatOutput(stdout, states)
        self.parseQstatErrors(stderr)
    def parseQstatOutput(self, stdout, states):
        for line in stdout.xreadlines():
            line = line.strip()
            if line.startswith("job") or line.startswith("----") or line == "":
                continue
            words = line.split()
            jobId = words[0]
            if not self.activeJobs.has_key(jobId):
                continue
            job = self.activeJobs[jobId]
            status = self.getStatus(words[4], states, jobId)
            if job.status == "PEND" and status != "PEND" and len(words) >= 6:
                self.setJobHost(job, words[7])
            job.status = status
            if status == "EXIT" or status == "DONE":
                del self.activeJobs[jobId]
    def setJobHost(self, job, queueName):
        parts = queueName.split('@')
        if len(parts) > 1:
            fullMachine = parts[-1]
            job.machines = [ fullMachine.split('.')[0] ]
        else:
            if len(job.machines) < 1:
                job.machines = [ "UNKNOWN" ]
    def parseQstatErrors(self, stderr):
        # Assume anything we can't find any more has completed OK
        for errorMessage in stderr.readlines():
            if not errorMessage:
                continue
            jobId = self.getJobId(errorMessage)
            if not self.activeJobs.has_key(jobId):
                print "ERROR: unexpected output from qstat :", errorMessage.strip()
                continue
            
            job = self.activeJobs[jobId]
            job.status = "DONE"
            del self.activeJobs[jobId]
    
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
    def findAllMachinesForJob(self):
        if not os.environ.has_key("PE_HOSTFILE"):
            return []
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

