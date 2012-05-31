
""" Base class for all the queue system implementations """

import subprocess, os, socket
import abstractqueuesystem

class QueueSystem(abstractqueuesystem.QueueSystem):
    def __init__(self):
        self.processes = {}

    def submitSlaveJob(self, cmdArgs, slaveEnv, logDir, submissionRules): 
        outputFile, errorsFile = submissionRules.getJobFiles()
        try:
            process = subprocess.Popen(cmdArgs, 
                                       stdout=open(os.path.join(logDir, outputFile), "w"), 
                                       stderr=open(os.path.join(logDir, errorsFile), "w"),
                                       cwd=logDir, env=slaveEnv)
            errorMessage = None
        except OSError, e:
            errorMessage = "Failed to start slave process : " + str(e)
        if errorMessage:
            return None, self.getFullSubmitError(errorMessage, cmdArgs)
        else:
            jobId = str(process.pid)
            self.processes[jobId] = process
            return jobId, None

    def formatCommand(self, cmdArgs):
        return " ".join(cmdArgs)

    def killJob(self, jobId):
        self.processes[jobId].terminate()


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
    return [ socket.gethostname() ]
