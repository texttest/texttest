
import os
import string
import subprocess
from . import gridqueuesystem
from texttestlib.plugins import gethostname, log, TextTestError
from time import sleep
from locale import getpreferredencoding

# Used by master process for submitting, deleting and monitoring slave jobs


class QueueSystem(gridqueuesystem.QueueSystem):
    allStatuses = {"qw": ("PEND", "Pending"),
                   "hqw": ("HOLD", "On hold"),
                   "t": ("TRANS", "Transferring"),
                   "r": ("RUN", "Running"),
                   "s": ("USUSP", "Suspended by the user"),
                   "dRr": ("DEL", "In the process of being killed"),
                   "dr": ("DEL", "In the process of being killed"),
                   "dt": ("DEL", "In the process of being killed"),
                   "ds": ("DEL", "In the process of being killed"),
                   "dS": ("DEL", "In the process of being killed"),
                   "R": ("RESTART", "Restarted"),
                   "Rr": ("RESTART", "Restarted"),
                   "Rt": ("RESTART", "Restarted"),
                   "Rq": ("REQUEUED", "Requested a restart"),
                   "S": ("SSUSP", "Suspended by SGE due to other higher priority jobs"),
                   "St": ("SSUSP", "Suspended by SGE due to other higher priority jobs"),
                   "SR": ("SSUSP", "Suspended by SGE due to other higher priority jobs"),
                   "SRt": ("SSUSP", "Suspended by SGE due to other higher priority jobs"),
                   "T": ("THRESH", "Suspended by SGE as it exceeded allowed thresholds")}
    errorStatuses = ["Eqw", "ERq"]
    submitProg = "qsub"
    def __init__(self, *args):
        self.qdelOutput = ""
        self.errorReasons = {}
        gridqueuesystem.QueueSystem.__init__(self, *args)

    def getSlaveStartErrorFile(self):
        return os.path.join(self.coreFileLocation, "slave_start_errors." + os.getenv("USER"))

    def getSubmitCmdArgs(self, submissionRules, commandArgs=[], slaveEnv={}):
        qsubArgs = ["qsub", "-N", submissionRules.getJobName()]
        if submissionRules.processesNeeded != 1:
            qsubArgs += ["-pe", submissionRules.getParallelEnvironment(),
                         str(submissionRules.processesNeeded)]
        if submissionRules.useCoreBinding():
            qsubArgs += ["-binding", "linear:"+str(submissionRules.processesNeeded)]
        queue = submissionRules.findQueue()
        if queue:
            qsubArgs += ["-q", queue]
        priority = submissionRules.findPriority()
        if priority:
            qsubArgs += ["-p", str(priority)]
        resource = self.getResourceArg(submissionRules)
        if len(resource):
            qsubArgs += ["-l", resource]
        qsubArgs += ["-w", "e", "-notify", "-m", "n", "-cwd", "-b", "y"]
        if slaveEnv:
            if len(slaveEnv) >= len(os.environ):  # We've clearly copied the environment, just forward the whole thing
                qsubArgs.append("-V")
            else:
                qsubArgs.append("-v")
                qsubArgs.append(",".join(slaveEnv))

        qsubArgs += ["-o", os.devnull, "-e", self.getSlaveStartErrorFile()]
        return self.addExtraAndCommand(qsubArgs, submissionRules, commandArgs)

    def getResourceArg(self, submissionRules):
        resourceList = submissionRules.findResourceList()
        machines = submissionRules.findMachineList()
        if len(machines):
            resourceList.append("hostname=" + "|".join(machines))
        return ",".join(resourceList)

    def findSubmitError(self, stderr):
        return stderr.strip().splitlines()[0]

    def killJob(self, jobId):
        proc = subprocess.Popen(["qdel", jobId], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding=getpreferredencoding())
        self.qdelOutput = proc.communicate()[0]
        return self.qdelOutput.find("has registered the job") != -1 or self.qdelOutput.find("has deleted job") != -1

    def setSuspendState(self, jobId, newState):
        arg = "-sj" if newState else "-usj"
        cmdArgs = ["qmod", arg, jobId]
        proc = subprocess.Popen(cmdArgs, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding=getpreferredencoding())
        output = proc.communicate()[0]
        # unsuspend always provides return code 1, even when it works (bug in SGE)
        if newState and proc.returncode > 0:
            raise TextTestError("Failed to suspend job using command '" + " ".join(cmdArgs) +
                                "'\nError message from SGE follows:\n" + output)

    def getJobId(self, line):
        return line.split()[2]

    def findJobId(self, stdout):
        jobId = ""
        for line in stdout.splitlines():
            if line.find("has been submitted") != -1:
                jobId = self.getJobId(line)
            else:
                log.info("Unexpected output from qsub : " + line.strip())
        return jobId

    def getStatusForAllJobs(self):
        statusDict = {}
        proc = subprocess.Popen(["qstat"], stdin=open(os.devnull), stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding=getpreferredencoding())
        outMsg = proc.communicate()[0]
        if proc.returncode > 0:
            # SGE unavailable for the moment, don't update the job status
            return

        for line in outMsg.splitlines():
            words = line.split()
            if len(words) >= 5 and words[0].isdigit():
                jobId = words[0]
                statusLetter = self.getStatusLetter(words, 4)
                if statusLetter in self.errorStatuses:
                    self.errorReasons[jobId] = self.getErrorReason(jobId)
                    self.killJob(jobId)
                    continue

                status = self.allStatuses.get(statusLetter)
                if status:
                    statusDict[jobId] = status
                else:
                    log.info("WARNING: unexpected job status " + repr(statusLetter) + " received from SGE!")
                    statusDict[jobId] = statusLetter, statusLetter
        return statusDict

    def isDate(self, text):
        return len(text) == 10 and text.count("/") == 2

    def getStatusLetter(self, words, statusIndex):
        if len(words) < statusIndex + 1 or self.isDate(words[statusIndex + 1]):
            return words[statusIndex]
        else:
            return self.getStatusLetter(words, statusIndex + 1)

    def getErrorReason(self, jobId):
        proc = subprocess.Popen(["qstat", "-j", jobId], stdin=open(os.devnull), encoding=getpreferredencoding(),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        outMsg = proc.communicate()[0]
        for line in outMsg.splitlines():
            if line.startswith("error reason"):
                return line.strip()
        return ""

    def getSlaveStartErrorMessage(self):
        errFile = self.getSlaveStartErrorFile()
        if not os.path.isfile(errFile):
            return ""

        errLines = open(errFile).read().splitlines()
        errText = "\n".join(errLines[-3:])
        if not errText:
            return ""

        return self.makeHeader("Recent errors written when starting SGE slave jobs") + errText + "\n(full file is at " + errFile + " - please remove this file sometime you aren't running TextTest)"

    def getJobFailureInfo(self, jobId):
        text = gridqueuesystem.QueueSystem.getJobFailureInfo(self, jobId)
        errors = self.getSlaveStartErrorMessage()
        if errors:
            text = errors + "\n" + text
        return text

    def _getJobFailureInfo(self, jobId):
        if jobId in self.errorReasons:
            return "SGE job entered error state: " + jobId + "\nTextTest terminated this job as a result. SGE's error reason follows:\n" + self.errorReasons.get(jobId)
        methods = [self.getAccountInfo, self.getAccountInfoOldFiles, self.retryAccountInfo]
        acctError = ""
        for method in methods:
            acctOutput, acctError = method(jobId)
            if acctOutput is not None:
                return acctOutput
        if self.qdelOutput:
            return "SGE lost job: " + jobId + "\nqdel output was as follows:\n" + self.qdelOutput
        else:
            return "Could not find info about job: " + jobId + "\nqacct error was as follows:\n" + acctError

    def getAccountInfo(self, jobId, extraArgs=[]):
        cmdArgs = ["qacct", "-j", jobId] + extraArgs
        proc = subprocess.Popen(cmdArgs, stdin=open(os.devnull), stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding=getpreferredencoding())
        outMsg, errMsg = proc.communicate()
        notFoundMsg = "error: job id " + jobId + " not found"
        if len(errMsg) == 0 or notFoundMsg not in errMsg:
            return outMsg, errMsg
        else:
            return None, errMsg

    def retryAccountInfo(self, jobId):
        sleepTime = 0.5
        acctError = ""
        for i in range(9):  # would be 10 but we had one already
            # assume failure is because the job hasn't propagated yet, wait a bit
            sleep(sleepTime)
            if sleepTime < 5:
                sleepTime *= 2
            acctOutput, acctError = self.getAccountInfo(jobId)
            if acctOutput is not None:
                return acctOutput, acctError
            else:
                log.info("Waiting " + str(sleepTime) + " seconds before retrying account info for job " + jobId)
        return None, acctError

    def getAccountInfoOldFiles(self, jobId):
        acctError = ""
        for logNum in range(5):
            # try at most 5 accounting files for now - assume jobs don't run longer than 5 days!
            fileName = self.findAccountingFile(logNum)
            if not fileName:
                return None, acctError
            acctInfo, acctError = self.getAccountInfo(jobId, ["-f", fileName])
            if acctInfo:
                return acctInfo, acctError
        return None, acctError

    def findAccountingFile(self, logNum):
        if "SGE_ROOT" in os.environ and "SGE_CELL" in os.environ:
            findPattern = os.path.join(os.environ["SGE_ROOT"], os.environ["SGE_CELL"])
            acctFile = os.path.join(findPattern, "common", "accounting." + str(logNum))
            if os.path.isfile(acctFile):
                return acctFile


# Used by slave for producing performance data
class MachineInfo:
    def findActualMachines(self, machineOrGroup):
        # In LSF this unpacks host groups, taking advantage of the fact that they are
        # interchangeable with machines. This is not true in SGE anyway, so don't support it.
        return [machineOrGroup]

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
        user, jobId = "", ""
        myJobId = os.path.basename(os.getenv("SGE_JOB_SPOOL_DIR", "")).split(".")[0]
        for line in os.popen("qstat -r -s r -u '*' -l hostname='" + machine + "'"):
            if line.startswith("job") or line.startswith("----"):
                continue
            if line[0] in string.digits:
                fields = line.split()
                if fields[0] != myJobId:
                    user = fields[-6]
                    jobId = fields[0]
                else:
                    user, jobId = "", ""
            elif jobId and line.find("Full jobname") != -1:
                jobName = line.split(":")[-1].strip()
                jobs.append((user, jobId, jobName))
        return jobs

# Interpret what the limit signals mean...


def getUserSignalKillInfo(userSignalNumber, explicitKillMethod):
    if userSignalNumber == "1":
        return "RUNLIMIT", "exceeded maximum wallclock time allowed by SGE (s_rt parameter)"
    else:
        return explicitKillMethod()

# Used by slave to find all execution machines


def getExecutionMachines():
    hostFile = os.getenv("PE_HOSTFILE")
    if not hostFile or not os.path.isfile(hostFile):
        return [gethostname()]
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
