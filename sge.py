
import os, string
from plugins import getDiagnostics

class QueueSystem:
    def __init__(self, envString):
        self.activeJobs = {}
        self.envString = envString
        self.diag = getDiagnostics("Queue System Thread")
    def getSubmitCommand(self, jobName, submissionRules):
        # Sungrid doesn't like : or / in job names
        qsubArgs = "-N " + jobName.replace(":", "").replace("/", ".")
        if submissionRules.processesNeeded != "1":
            # We need a 'parallel environment' to be defined here for this
            # to work
            qsubArgs += " -pe " + submissionRules.processesNeeded
        queue = submissionRules.findQueue()
        if queue:
            qsubArgs += " -q " + queue
        resource = self.getResourceArg(submissionRules)
        if len(resource):
            qsubArgs += " -l " + resource
        qsubArgs += " -m n -b y -V"
        return "qsub " + qsubArgs
    def findSubmitError(self, stderr):
        errLines = stderr.readlines()
        if len(errLines):
            return errLines[0].strip()
        else:
            return ""
    def findJobLimitMessage(self, jobId):
        # Don't yet know how to do this
        return ""
    def killJob(self, jobId):
        os.system("qdel " + jobId + " > /dev/null 2>&1")
    def getJobId(self, line):
        return line.split()[2]
    def findJobId(self, stdout):
        for line in stdout.readlines():
            if line.find("has been submitted") != -1:
                return self.getJobId(line)
        print "ERROR: unexpected output from qsub!!!"
        return ""
    def getResourceArg(self, submissionRules):
        resourceList = submissionRules.findResourceList()
        machines = submissionRules.findMachineList()
        if len(machines):
            resourceList.append("hostname='" + string.join(machines, "|") + "'")
        return string.join(resourceList, ",")
    def getStatus(self, sgeStat, states):
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
    def updateJobs(self):
        self._updateJobs("prs")
        self._updateJobs("z")
    def _updateJobs(self, states):
        commandLine = self.envString + "qstat -s " + states + " -u " + os.environ["USER"]
        stdin, stdout, stderr = os.popen3(commandLine)
        self.parseQstatOutput(stdout, states)
        self.parseQstatErrors(stderr)
    def parseQstatOutput(self, stdout, states):
        for line in stdout.xreadlines():
            if line.startswith("job") or line.startswith("----"):
                continue
            words = line.strip().split()
            jobId = words[0]
            if not self.activeJobs.has_key(jobId):
                continue
            job = self.activeJobs[jobId]
            status = self.getStatus(words[4], states)
            if job.status == "PEND" and status != "PEND" and len(words) >= 6:
                fullMachines = words[7].split('@')[-1]
                job.machines = map(lambda x: x.split('.')[0], fullMachines)
            job.status = status
            if status == "EXIT" or status == "DONE":
                del self.activeJobs[jobId]
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
    def findActualMachines(self, machine):
        # In LSF this unpacks host groups. Don't know how they work here yet, or whether they'll
        # be useful
        return [ machine ]
    def findRunningJobs(self, machine):
        jobs = []
        fieldInfo = 0
        user = ""
        for line in os.popen("qstat -r -s r -l hostname ='" + machine + "' 2>&1").xreadlines():
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
