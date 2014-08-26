
""" Base class for all the queue system implementations """

import subprocess, os, signal
import abstractqueuesystem
from multiprocessing import cpu_count

class QueueSystem(abstractqueuesystem.QueueSystem):
    def __init__(self, *args):
        self.processes = {}

    def submitSlaveJob(self, cmdArgs, slaveEnv, logDir, submissionRules, jobType):
        outputFile, errorsFile = submissionRules.getJobFiles()
        try:
            process = subprocess.Popen(cmdArgs, 
                                       stdout=open(os.path.join(logDir, outputFile), "w"), 
                                       stderr=open(os.path.join(logDir, errorsFile), "w"),
                                       cwd=logDir, env=self.getSlaveEnvironment(slaveEnv))
            errorMessage = None
        except OSError, e:
            errorMessage = "Failed to start slave process : " + str(e)
        if errorMessage:
            return None, self.getFullSubmitError(errorMessage, cmdArgs, jobType)
        else:
            jobId = str(process.pid)
            self.processes[jobId] = process
            return jobId, None
        
    def getCapacity(self):
        return cpu_count()
        
    def formatCommand(self, cmdArgs):
        return " ".join(cmdArgs)

    def getSignal(self):
        return signal.SIGUSR2 if os.name == "posix" else signal.SIGTERM

    def killJob(self, jobId):
        proc = self.processes[jobId]
        jobExisted = proc.poll() is None
        if jobExisted:
            sig = self.getSignal()
            proc.send_signal(sig)
        return jobExisted        
    
    def getStatusForAllJobs(self):
        statusDict = {}
        for procId, process in self.processes.items():
            if process.poll() is None:
                statusDict[procId] = "RUN", "Running"
        return statusDict
    
    def getJobFailureInfo(self, jobId):
        return "" # no accounting system here...
    
    def getQueueSystemName(self):
        return "local queue"
    
# Interpret what the limit signals mean...
def getUserSignalKillInfo(userSignalNumber, explicitKillMethod):
    return explicitKillMethod()

# Used by slave for producing performance data
class MachineInfo:
    def findActualMachines(self, machineOrGroup):
        # In LSF this unpacks host groups, taking advantage of the fact that they are
        # interchangeable with machines. This is not true in SGE anyway, so don't support it.
        return [ machineOrGroup ]

    def findResourceMachines(self, resource):
        return []

    def findRunningJobs(self, machine):
        return []

def getExecutionMachines():
    from texttestlib.plugins import gethostname
    return [ gethostname() ]
