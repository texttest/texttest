
""" Base class for all the queue system implementations """

import subprocess, os, signal
import abstractqueuesystem
from multiprocessing import cpu_count
from texttestlib import plugins

class QueueSystem(abstractqueuesystem.QueueSystem):
    def __init__(self, *args):
        self.processes = {}

    def submitSlaveJob(self, cmdArgs, slaveEnv, logDir, submissionRules, jobType):
        outputFile, errorsFile = submissionRules.getJobFiles()
        try:
            process = subprocess.Popen(cmdArgs, 
                                       stdout=open(os.path.join(logDir, outputFile), "w"), 
                                       stderr=open(os.path.join(logDir, errorsFile), "w"),
                                       cwd=logDir, env=self.getSlaveEnvironment(slaveEnv), 
                                       startupinfo=plugins.getHideStartUpInfo())
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
            if os.name == "posix":
                proc.send_signal(self.getSignal())
            else:
                if not self.runTaskKill(proc): # Sometimes Windows decides we can't kill the slave process. Better to kill it hard than not at all then.
                    self.runTaskKill(proc, [ "/T", "/F" ])
        return jobExisted
    
    def runTaskKill(self, proc, extraArgs=[]):
        return subprocess.call([ "taskkill" ] + extraArgs + [ "/PID", str(proc.pid) ], stdout=open(os.devnull, "w"), stderr=subprocess.STDOUT, startupinfo=plugins.getHideStartUpInfo()) == 0
    
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
