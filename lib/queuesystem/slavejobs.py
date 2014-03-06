
"""
Module containing code that's only run in the slave jobs when running with a grid engine / queue system
"""

import plugins, os, sys, time, socket, signal, logging
from utils import *
from default.runtest import RunTest
from default.sandbox import FindExecutionHosts, MachineInfoFinder
from default.actionrunner import ActionRunner
from cPickle import dumps

def importAndCallFromQueueSystem(app, *args):
    moduleName = "queuesystem." + queueSystemName(app).lower()
    return plugins.importAndCall(moduleName, *args)


# Use a non-monitoring runTest, but the rest from unix
class RunTestInSlave(RunTest):
    def getBriefText(self, execMachines):
        return "RUN (" + ",".join(execMachines) + ")"

    def getKillInfoOtherSignal(self, test):
        if self.killSignal == signal.SIGUSR1:
            return self.getUserSignalKillInfo(test, "1")
        elif self.killSignal == signal.SIGUSR2:
            return self.getUserSignalKillInfo(test, "2")
        else:
            return RunTest.getKillInfoOtherSignal(self, test)
    
    def getUserSignalKillInfo(self, test, userSignalNumber):
        return importAndCallFromQueueSystem(test.app, "getUserSignalKillInfo", userSignalNumber, self.getExplicitKillInfo)

# Redirect the log mechanism locally in the slave
# Workaround for NFS slowness, essentially: we can't create these files in the master process in case they
# don't propagate in time
class RedirectLogResponder(plugins.Responder):
    done = False
    def notifyAdd(self, test, *args, **kw):
        if not self.done:
            RedirectLogResponder.done = True
            logDir = os.path.join(test.app.writeDirectory, "slavelogs")
            plugins.ensureDirectoryExists(logDir)
            os.chdir(logDir)
            logFile, errFile = test.app.getSubmissionRules(test).getJobFiles()
            errPath = os.path.join(logDir, errFile)
            logPath = os.path.join(logDir, logFile)
            if not os.path.isfile(errPath) and not os.path.isfile(logPath):
                sys.stderr = open(errPath, "w")
                # This is more or less hardcoded to use a timed formatter and write to the file
                handler = logging.FileHandler(logPath)
                formatter = logging.Formatter("%(asctime)s - %(message)s")
                handler.setFormatter(formatter)
                plugins.log.addHandler(handler)

class FileTransferResponder(plugins.Responder):
    def __init__(self, optionMap, *args):
        plugins.Responder.__init__(self)
        self.destination = optionMap.get("slavefilesynch")
        self.transferAll = optionMap.get("keepslave") or optionMap.get("keeptmp")
        
    def notifyLifecycleChange(self, test, state, changeDesc):
        if self.destination and changeDesc == "complete" and (self.transferAll or not test.state.hasSucceeded()):
            test.app.copyFileRemotely(test.writeDirectory, "localhost", os.path.dirname(test.writeDirectory), self.destination)


class SocketResponder(plugins.Responder,plugins.Observable):
    def __init__(self, optionMap, *args):
        plugins.Responder.__init__(self)
        plugins.Observable.__init__(self)
        self.killed = False
        self.testsForRerun = []
        self.serverAddress = self.getServerAddress(optionMap)
    def getServerAddress(self, optionMap):
        servAddrStr = optionMap.get("servaddr", os.getenv("CAPTUREMOCK_SERVER"))
        if not servAddrStr:
            raise plugins.TextTestError, "Cannot run slave, no server address has been provided to send results to!"
        host, port = servAddrStr.split(":")
        return host, int(port)
    def connect(self, sendSocket):
        for i in range(5):
            try:
                sendSocket.connect(self.serverAddress)
                return True
            except socket.error:
                time.sleep(1)
        sys.stderr.write("Failed to connect to " + repr(self.serverAddress) + " : " + self.exceptionOutput())
        return False

    def exceptionOutput(self):
        exctype, value = sys.exc_info()[:2]
        from traceback import format_exception_only
        return "".join(format_exception_only(exctype, value))

    def notifyKillProcesses(self, *args):
        self.killed = True

    def getProcessIdentifier(self, test):
        identifier = str(os.getpid())
        if self.killed:
            identifier += ".NO_REUSE"
        if test in self.testsForRerun:
            self.testsForRerun.remove(test)
            identifier += ".RERUN_TEST"
        return identifier

    def notifyRerun(self, test):
        self.testsForRerun.append(test)

    def notifyLifecycleChange(self, test, state, changeDesc):
        testData = socketSerialise(test)
        pickleData = dumps(state)
        fullData = self.getProcessIdentifier(test) + os.linesep + testData + os.linesep + pickleData
        sleepTime = 1
        for i in range(9):
            sendSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if not self.connect(sendSocket):
                return self.notify("NoMoreExtraTests")
            try:
                response = self.sendData(sendSocket, fullData)
                return self.interpretResponse(state, response)
            except socket.error, e:
                plugins.log.info("Failed to communicate with master process - waiting " +
                                 str(sleepTime) + " seconds and then trying again.")
                plugins.log.info("Error received was " + str(e))
                time.sleep(sleepTime)
                sleepTime *= 2

        message = "Terminating as failed to communicate with master process : " + self.exceptionOutput()
        sys.stderr.write(message)
        plugins.log.info(message.strip())
        self.notify("NoMoreExtraTests")
        
    def sendData(self, sendSocket, fullData):
        sendSocket.sendall(fullData)
        sendSocket.shutdown(socket.SHUT_WR)
        response = sendSocket.makefile().read()
        sendSocket.close()
        return response

    def interpretResponse(self, state, response):
        if len(response) > 0:
            appDesc, testPath = socketParse(response)
            appParts = appDesc.split(".")
            self.notify("ExtraTest", testPath, appParts[0], appParts[1:])
        elif state.isComplete():
            self.notify("NoMoreExtraTests")


class SlaveActionRunner(ActionRunner):
    def notifyAllRead(self, goodSuites):
        # don't ordinarily add a terminator, we might get given more tests via the socket (code above)
        # Need to add one if we haven't found any tests though
        if len(goodSuites) == 0:
            ActionRunner.notifyAllRead(self, goodSuites)
        
    def notifyRerun(self, *args):
        pass # don't rerun directly in the slave, tell the master and give it a chance to send the job elsewhere

    def notifyNoMoreExtraTests(self):
        self.diag.info("No more extra tests, adding terminator")
        self.testQueue.put(None)


class FindExecutionHostsInSlave(FindExecutionHosts):
    def getExecutionMachines(self, test):
        return importAndCallFromQueueSystem(test.app, "getExecutionMachines")


class SlaveMachineInfoFinder(MachineInfoFinder):
    def __init__(self):
        self.queueMachineInfo = None
        
    def findPerformanceMachines(self, test, fileStem):
        perfMachines = []
        resources = test.getCompositeConfigValue("performance_test_resource", fileStem)
        for resource in resources:
            perfMachines += plugins.retryOnInterrupt(self.queueMachineInfo.findResourceMachines, resource)

        rawPerfMachines = MachineInfoFinder.findPerformanceMachines(self, test, fileStem)
        for machine in rawPerfMachines:
            if machine != "any":
                perfMachines += self.queueMachineInfo.findActualMachines(machine)
        if "any" in rawPerfMachines and len(resources) == 0:
            return rawPerfMachines
        else:
            return perfMachines

    def setUpApplication(self, app):
        MachineInfoFinder.setUpApplication(self, app)
        self.queueMachineInfo = importAndCallFromQueueSystem(app, "MachineInfo")

    def getMachineInformation(self, test):
        # Try and write some information about what's happening on the machine
        info = ""
        for machine in test.state.executionHosts:
            for jobLine in self.findRunningJobs(machine):
                info += jobLine + "\n"
        return info

    def findRunningJobs(self, machine):
        return plugins.retryOnInterrupt(self._findRunningJobs, machine)

    def _findRunningJobs(self, machine):
        # On a multi-processor machine performance can be affected by jobs on other processors,
        # as for example a process can hog the memory bus. Describe these so the user can judge
        # for himself if performance is likely to be affected...
        jobsFromQueue = self.queueMachineInfo.findRunningJobs(machine)
        jobs = []
        for user, jobId, jobName in jobsFromQueue:
            jobs.append("Also on " + machine + " : " + user + "'s job " + jobId + " '" + jobName + "'")
        return jobs    
