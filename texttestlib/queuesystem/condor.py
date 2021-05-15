
import os
import subprocess
from . import abstractqueuesystem
from texttestlib.plugins import log

# Used by the master to submit, monitor and delete jobs...


class QueueSystem(abstractqueuesystem.QueueSystem):
    allStatuses = {"0": ("HOLD", "On hold"),
                   "1": ("IDLE", "Waiting for a machine to execute on"),
                   "2": ("RUN", "Running"),
                   "3": ("REM", "Removed"),
                   "4": ("COMP", "Completed"),
                   "5": ("HELD", "Being held"),
                   "6": ("TRANS", "Transfering output")}
    submitProg = "condor_submit"

    def getSubmitCmdArgs(self, submissionRules, commandArgs=[], slaveEnv={}):
        return commandArgs  # These really aren't very interesting, as all the stuff is in the command file

    def submitSlaveJob(self, cmdArgs, slaveEnv, logDir, submissionRules, jobType):
        submitScript = self.writeSubmitScript(submissionRules, logDir, cmdArgs, slaveEnv)
        realArgs = ["condor_submit", submitScript]
        return abstractqueuesystem.QueueSystem.submitSlaveJob(self, realArgs, slaveEnv, logDir, submissionRules, jobType)

    def writeSubmitScript(self, submissionRules, directory, cmdArgs, slaveEnv):
        jobName = submissionRules.getJobName()
        submitFileName = jobName + ".sub"
        resources = " && ".join(submissionRules.findResourceList())
        with open(os.path.join(directory, submitFileName), "w") as submitFile:
            submitFile.writelines(['universe = vanilla\n',
                                   'executable = ' + cmdArgs[0] + '\n',
                                   'arguments = ' + " ".join(cmdArgs[1:]) + '\n',
                                   'requirements = ' + resources + '\n',
                                   'output = ' + jobName + '.out\n',
                                   'error = ' + jobName + '.errors\n',
                                   'log = ' + jobName + '.log\n',
                                   'queue' + '\n'])
            if slaveEnv:
                envStr = [var + "=" + value for var, value in list(slaveEnv.items())]
                submitFile.write("environment = " + "|".join(envStr) + "\n")

        return submitFileName

    def findSubmitError(self, stderr):
        return stderr.strip().splitlines()[0]

    def _getJobFailureInfo(self, jobId):
        resultOutput = os.popen("condor_history " + jobId + " 2>&1").read()
        if resultOutput.find("is not found") != -1:
            return "Condor lost job:" + jobId
        else:
            return resultOutput

    def getStatusForAllJobs(self):
        statusDict = {}
        proc = subprocess.Popen(['condor_q', '-format', '%s ', 'ClusterId', '-format', '%s\\n',
                                 'JobStatus'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        outMsg = proc.communicate()[0]
        for line in outMsg.splitlines():
            words = line.split()
            statusLetter = words[1]
            status = self.allStatuses.get(statusLetter)
            if status:
                statusDict[words[0]] = status
        return statusDict

    def killJob(self, jobId):
        killProcess = subprocess.Popen(["condor_rm", jobId], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        killProcess.communicate()
        killProcess.wait()
        return killProcess.returncode == 0

    def getJobId(self, line):
        word = line.split()[5]
        return word[:-1]

    def findJobId(self, stdout):
        jobId = ""
        for line in stdout.splitlines():
            if line.find("submitted to cluster") != -1:
                jobId = self.getJobId(line)
            elif line.find("Submitting job") != -1 or line.find("Logging submit event") != -1:
                continue
            else:
                log.info("Unexpected output from condor_submit : " + line.strip())
        return jobId

# Used by the slave for getting performance info


class MachineInfo:
    def findActualMachines(self, machineOrGroup):
        machines = []
        for line in os.popen('condor_status -format "%s\\n" Name ' + machineOrGroup + ' 2>&1'):
            machines.append(line.split()[0])
        return machines

    def findResourceMachines(self, resource):
        machines = []
        for line in os.popen('condor_status -constraint "' + resource + '" -format "%s\\n" Name 2>&1'):
            machines.append(line.split()[0])
        return machines

    def findRunningJobs(self, machine):
        jobs = []
        for line in os.popen('condor_q -run -name ' + machine + ' -format "%s " ClusterId -format "%s\\n" Owner 2>&1'):
            fields = line.split()
            jobId = fields[0]
            user = fields[1]
            jobs.append((user, jobId))
        return jobs

# Interpret what the limit signals mean...


def getUserSignalKillInfo(userSignalNumber, explicitKillMethod):
    return explicitKillMethod()

# Used by slave to find all execution machines    - basically same code as MachineInfo.findActualMachines


def getExecutionMachines():
    machines = []
    for line in os.popen('condor_config_val HOSTNAME 2>&1'):
        machines.append(line.split()[0])
    return machines
