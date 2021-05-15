
import os
from . import gridqueuesystem

# Used by the master to submit, monitor and delete jobs...


class QueueSystem(gridqueuesystem.QueueSystem):
    submitProg = "bsub"
    def getSubmitCmdArgs(self, submissionRules, commandArgs=[], slaveEnv={}):
        bsubArgs = ["bsub", "-J", submissionRules.getJobName()]
        if submissionRules.processesNeeded != 1:
            bsubArgs += ["-n", str(submissionRules.processesNeeded)]
        queue = submissionRules.findQueue()
        if queue:
            bsubArgs += ["-q", queue]
        resource = self.getResourceArg(submissionRules)
        if len(resource):
            bsubArgs += ["-R", resource]
        machines = submissionRules.findMachineList()
        if len(machines):
            bsubArgs += ["-m", " ".join(machines)]
        bsubArgs += ["-u", "nobody", "-o", os.devnull, "-e", os.devnull]
        return self.addExtraAndCommand(bsubArgs, submissionRules, commandArgs)

    def getSlaveVarsToBlock(self):
        """Make sure we clear out the master scripts so the slave doesn't use them too,
        otherwise just use the environment as is.

        If we're being run via SSH, don't pass this on to the slave jobs
        This has been known to trip up shell starter scripts, e.g. on SuSE 10
        making them believe that the SGE job is an SSH login and setting things wrongly
        as a result.

        LS_COLORS has also been shown to be problematic as older version of tcsh fail hard
        if given newer instructions they don't understand there.
        """
        return ["USECASE_REPLAY_SCRIPT", "USECASE_RECORD_SCRIPT", "SSH_TTY", "LS_COLORS"]

    def findSubmitError(self, stderr):
        for errorMessage in stderr.splitlines():
            if self.isRealError(errorMessage):
                return errorMessage

    def isRealError(self, errorMessage):
        if not errorMessage:
            return 0
        okStrings = ["still trying", "Waiting for dispatch", "Job is finished"]
        for okStr in okStrings:
            if errorMessage.find(okStr) != -1:
                return 0
        return 1

    def _getJobFailureInfo(self, jobId):
        resultOutput = os.popen("bjobs -a -l " + jobId + " 2>&1").read()
        if resultOutput.find("is not found") != -1:
            return "LSF lost job:" + jobId
        else:
            return resultOutput

    def supportsPolling(self):
        # This feature was added to the SGE handling when I no longer had access to an LSF cluster
        return False

    def killJob(self, jobId):
        resultOutput = os.popen("bkill -s USR1 " + jobId + " 2>&1").read()
        return resultOutput.find("is being terminated") != -1 or resultOutput.find("is being signaled") != -1

    def getJobId(self, line):
        word = line.split()[1]
        return word[1:-1]

    def findJobId(self, stdout):
        for line in stdout.splitlines():
            if line.find("is submitted") != -1:
                return self.getJobId(line)
            else:
                print("Unexpected output from bsub :", line.strip())
        return ""  # pragma : no cover, should never happen...

    def getResourceArg(self, submissionRules):
        resourceList = submissionRules.findResourceList()
        if len(resourceList) == 0:
            return ""
        selectResources = []
        others = []
        for resource in resourceList:
            if resource.find("rusage[") != -1 or resource.find("order[") != -1 or \
               resource.find("span[") != -1 or resource.find("same[") != -1:
                others.append(resource)
            else:
                selectResources.append(resource)
        if len(selectResources) == 0:
            return " ".join(others)
        else:
            return self.getSelectResourceArg(selectResources) + " " + " ".join(others)

    def getSelectResourceArg(self, resourceList):
        if len(resourceList) == 1:
            return self.formatResource(resourceList[0])
        else:
            resource = "(" + self.formatResource(resourceList[0]) + ")"
            for res in resourceList[1:]:
                resource += " && (" + self.formatResource(res) + ")"
            return resource

    def formatResource(self, res):
        if res.find("==") == -1 and res.find("!=") == -1 and res.find("<=") == -1 and \
           res.find(">=") == -1 and res.find("=") != -1:
            return res.replace("=", "==")
        else:
            return res

# Used by the slave for getting performance info


class MachineInfo:
    def findActualMachines(self, machineOrGroup):
        machines = []
        for line in os.popen("bhosts " + machineOrGroup + " 2>&1"):
            if not line.startswith("HOST_NAME"):
                machines.append(line.split()[0].split(".")[0])
        return machines

    def findResourceMachines(self, resource):
        machines = []
        for line in os.popen("bhosts -w -R '" + resource + "' 2>&1"):
            if not line.startswith("HOST_NAME"):
                machines.append(line.split()[0].split(".")[0])
        return machines

    def findRunningJobs(self, machine):
        jobs = []
        for line in os.popen("bjobs -m " + machine + " -u all -w 2>&1 | grep RUN"):
            fields = line.split()
            jobId = fields[0]
            user = fields[1]
            jobName = fields[6]
            jobs.append((user, jobId, jobName))
        return jobs

# Interpret what the limit signals mean...


def getUserSignalKillInfo(userSignalNumber, explicitKillMethod):
    if userSignalNumber == "2":
        return "RUNLIMIT", "exceeded maximum wallclock time allowed by LSF (RUNLIMIT parameter)"
    else:
        return explicitKillMethod()

# Need to get all hosts for parallel


def getExecutionMachines():
    if "LSB_HOSTS" in os.environ:
        hosts = os.environ["LSB_HOSTS"].split()
        return [host.split(".")[0] for host in hosts]
    else:
        from texttestlib.plugins import gethostname
        return [gethostname()]
