
import os, string

class QueueSystem:
    def __init__(self, envString):
        self.activeJobs = {}
        self.envString = envString
    def getSubmitCommand(self, jobName, submissionRules):
        bsubArgs = "-J " + jobName
        if submissionRules.processesNeeded != "1":
            bsubArgs += " -n " + submissionRules.processesNeeded
        queue = submissionRules.findQueue()
        if queue:
            bsubArgs += " -q " + queue
        resource = self.getResourceArg(submissionRules)
        if len(resource):
            bsubArgs += " -R \"" + resource + "\""
        machines = submissionRules.findMachineList()
        if len(machines):
            bsubArgs += " -m '" + string.join(machines, " ") + "'"
        bsubArgs += " -u nobody"
        return "bsub " + bsubArgs
    def findSubmitError(self, stderr):
        for errorMessage in stderr.readlines():
            if errorMessage and errorMessage.find("still trying") == -1:
                return errorMessage
        return ""
    def findJobLimitMessage(self, jobId):
        for line in os.popen("bjobs -a -l " + jobId).readlines():
            if line.find("signal 24") != -1:
                return "Test hit LSF's CPU time limit, and was killed." + os.linesep + \
                      "Maybe it went into an infinite loop or maybe it needs to be run in another queue."
            if line.find("exit code 140") != -1:
                return "Test hit LSF's total run time limit, and was killed." + os.linesep + \
                       "Maybe it was hanging or maybe it needs to be run in another queue."
        return ""
    def killJob(self, jobId):
        os.system("bkill " + jobId + " > /dev/null 2>&1")
    def getJobId(self, line):
        word = line.split()[1]
        return word[1:-1]
    def findJobId(self, stdout):
        for line in stdout.readlines():
            if line.find("is submitted") != -1:
                return self.getJobId(line)
        print "ERROR: unexpected output from bsub!!!"
        return ""
    def getResourceArg(self, submissionRules):
        resourceList = submissionRules.findResourceList()
        if len(resourceList) == 0:
            return ""
        elif len(resourceList) == 1:
            return resourceList[0]
        else:
            resource = "(" + resourceList[0] + ")"
            for res in resourceList[1:]:
                resource += " && (" + res + ")"
            return resource
    def updateJobs(self):
        commandLine = self.envString + "bjobs -a -w " + string.join(self.activeJobs.keys())
        stdin, stdout, stderr = os.popen3(commandLine)
        self.parseBjobsOutput(stdout)
        self.parseBjobsErrors(stderr)
    def parseBjobsOutput(self, stdout):
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
    def parseBjobsErrors(self, stderr):
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

class MachineInfo:
    def findActualMachines(self, machineOrGroup):
        machines = []
        for line in os.popen("bhosts " + machineOrGroup + " 2>&1"):
            if not line.startswith("HOST_NAME"):
                machines.append(line.split()[0].split(".")[0])
        return machines
    def findModelMachines(self, model):
        machines = []
        for line in os.popen("bhosts -w -R 'model=" + model + "' 2>&1"):
            if not line.startswith("HOST_NAME"):
                machines.append(line.split()[0].split(".")[0])
        return machines
    def findRunningJobs(self, machine):
        jobs = []
        for line in os.popen("bjobs -m " + machine + " -u all -w 2>&1 | grep RUN").xreadlines():
            fields = line.split()
            user = fields[1]
            jobName = fields[6]
            jobs.append((user, jobName))
        return jobs
    
