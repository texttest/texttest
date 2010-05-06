
"""
Code to do with the grid engine master process, i.e. submitting slave jobs and waiting for them to report back
"""

import plugins, os, sys, socket, subprocess, signal, logging, time
from utils import *
from Queue import Queue, Empty
from SocketServer import ThreadingTCPServer, StreamRequestHandler
from threading import RLock
from ndict import seqdict
from default.console import TextDisplayResponder, InteractiveResponder
from default.knownbugs import CheckForBugs
from default.actionrunner import BaseActionRunner
from default.performance import getTestPerformance
from types import StringType
from glob import glob

plugins.addCategory("abandoned", "abandoned", "were abandoned")

class Abandoned(plugins.TestState):
    def __init__(self, freeText):
        plugins.TestState.__init__(self, "abandoned", briefText="job deletion failed", \
                                                      freeText=freeText, completed=1, lifecycleChange="complete")
    def shouldAbandon(self):
        return 1


class QueueSystemServer(BaseActionRunner):
    instance = None
    def __init__(self, optionMap, allApps):
        BaseActionRunner.__init__(self, optionMap, logging.getLogger("Queue System Submit"))
        # queue for putting tests when we couldn't reuse the originals
        self.reuseFailureQueue = Queue()
        self.testCount = 0
        self.testsSubmitted = 0
        self.maxCapacity = 100000 # infinity, sort of
        self.allApps = allApps
        for app in allApps:
            currCap = app.getConfigValue("queue_system_max_capacity")
            if currCap is not None and currCap < self.maxCapacity:
                self.maxCapacity = currCap
            
        self.jobs = seqdict()
        self.submissionRules = {}
        self.killedJobs = {}
        self.queueSystems = {}
        self.reuseOnly = False
        self.submitAddress = None
        self.slaveLogDirs = set()
        self.delayedTestsForAdd = []
        self.remainingForApp = seqdict()
        capacityPerSuite = self.maxCapacity / len(allApps)
        for app in allApps:
            self.remainingForApp[app.name] = capacityPerSuite
        QueueSystemServer.instance = self
        
    def addSuites(self, suites):
        for suite in suites:
            self.slaveLogDirs.add(suite.app.makeWriteDirectory("slavelogs"))
            plugins.log.info("Using " + queueSystemName(suite.app) + " queues for " +
                             suite.app.description(includeCheckout=True))
        
    def setSlaveServerAddress(self, address):
        self.submitAddress = os.getenv("TEXTTEST_MIM_SERVER", address)
        self.testQueue.put("TextTest slave server started on " + address)

    def addTest(self, test):
        capacityForApp = self.remainingForApp[test.app.name]
        if capacityForApp > 0:
            self._addTest(test)
            self.remainingForApp[test.app.name] = capacityForApp - 1
        else:
            if test.app.name == self.remainingForApp.keys()[-1]:
                self._addTest(test) # For the last app (which may be the only one) there is no point in delaying
            else:
                self.delayedTestsForAdd.append(test)

    def _addTest(self, test):
        self.testCount += 1
        queue = self.findQueueForTest(test)
        if queue:
            queue.put(test)

    def addDelayedTests(self):
        for test in self.delayedTestsForAdd:
            self._addTest(test)
        self.delayedTestsForAdd = []

    def notifyAllRead(self, suites):
        self.addDelayedTests()
        BaseActionRunner.notifyAllRead(self, suites)

    def run(self): # picked up by core to indicate running in a thread
        self.runAllTests()

    def findQueueForTest(self, test):
        # If we've gone into reuse mode and there are no active tests for reuse, use the "reuse failure queue"
        if self.reuseOnly and self.testsSubmitted == 0:
            self.diag.info("Putting " + repr(test) + " in reuse failure queue " + self.remainStr())
            return self.reuseFailureQueue
        else:
            self.diag.info("Putting " + repr(test) + " in normal queue " + self.remainStr())
            return self.testQueue
                
    def handleLocalError(self, test, previouslySubmitted):
        self.handleErrorState(test, previouslySubmitted)
        if self.testCount == 0 or (self.reuseOnly and self.testsSubmitted == 0):
            self.diag.info("Submitting terminators after local error")
            self.submitTerminators()
    def submitTerminators(self):
        # snap out of our loop if this was the last one. Rely on others to manage the test queue
        self.reuseFailureQueue.put(None)
    def getTestForReuse(self, test, state, tryReuse):
        # Pick up any test that matches the current one's resource requirements
        if not self.exited:
            # Don't allow this to use up the terminator
            newTest = self.getTest(block=False, replaceTerminators=True)
            if newTest:
                if tryReuse and self.allowReuse(test, state, newTest):
                    self.jobs[newTest] = self.getJobInfo(test)
                    if self.testCount > 1:
                        self.testCount -= 1
                        self.diag.info("Reusing slave for " + repr(newTest) + self.remainStr())
                    else:
                        self.diag.info("Last test : submitting terminators")
                        # Don't allow test count to drop to 0 here, can cause race conditions
                        self.submitTerminators() 
                    return newTest
                else:
                    self.reuseFailureQueue.put(newTest)
                
        # Allowed a submitted job to terminate
        self.testsSubmitted -= 1
        self.diag.info("No reuse for " + repr(test) + " : " + repr(self.testsSubmitted) + " tests still submitted")
        if self.exited and self.testsSubmitted == 0:
            self.diag.info("Forcing termination")
            self.submitTerminators()
            
    def allowReuse(self, oldTest, oldState, newTest):
        # Don't reuse jobs that have been killed
        if newTest.state.isComplete() or oldState.category == "killed":
            return False

        oldRules = self.getSubmissionRules(oldTest)
        newRules = self.getSubmissionRules(newTest)
        return oldRules.allowsReuse(newRules)

    def getSubmissionRules(self, test):
        if self.submissionRules.has_key(test):
            return self.submissionRules[test]
        else:
            submissionRules = test.app.getSubmissionRules(test)
            self.submissionRules[test] = submissionRules
            return submissionRules

    def getTest(self, block, replaceTerminators=False):
        testOrStatus = self.getItemFromQueue(self.testQueue, block, replaceTerminators)
        if not testOrStatus:
            return
        if type(testOrStatus) == StringType:
            self.sendServerState(testOrStatus)
            return self.getTest(block)
        else:
            return testOrStatus

    def sendServerState(self, state):
        self.diag.info("Sending server state '" + state + "'")
        mimServAddr = os.getenv("TEXTTEST_MIM_SERVER")
        if mimServAddr:
            host, port = mimServAddr.split(":")
            serverAddress = (host, int(port))
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(serverAddress)
            sock.sendall("SUT_SERVER:" + state + "\n")
            sock.close()
            
    def getTestForRunNormalMode(self):
        self.reuseOnly = False
        reuseFailure = self.getItemFromQueue(self.reuseFailureQueue, block=False)
        if reuseFailure:
            self.diag.info("Found a reuse failure...")
            return reuseFailure
        else:
            self.diag.info("Waiting for new tests...")
            newTest = self.getTest(block=True)
            if newTest:
                return newTest
            else:
                # Make sure we pick up anything that failed in reuse while we were submitting the final test...
                self.diag.info("No normal test found, checking reuse failures...")
                return self.getItemFromQueue(self.reuseFailureQueue, block=False)
            
    def getTestForRunReuseOnlyMode(self):
        self.reuseOnly = True
        self.diag.info("Waiting for reuse failures...")
        reuseFailure = self.getItemFromQueue(self.reuseFailureQueue, block=True)
        if reuseFailure:
            return reuseFailure
        elif self.testCount > 0 and self.testsSubmitted < self.maxCapacity:
            # Try again, the capacity situation has changed...
            return self.getTestForRunNormalMode()

    def getTestForRun(self):
        if self.testCount == 0 or (self.testsSubmitted < self.maxCapacity):
            return self.getTestForRunNormalMode()
        else:
            return self.getTestForRunReuseOnlyMode()

    def notifyAllComplete(self):
        errors = {}
        errorFiles = []
        for logDir in self.slaveLogDirs:
            errorFiles += filter(os.path.getsize, glob(os.path.join(logDir, "*.errors")))
        if len(errorFiles) == 0:
            return

        for fileName in errorFiles:
            contents = None
            # Take the shortest (i.e. most filtered) one
            for app in self.allApps:
                currContent = app.filterErrorText(fileName)
                if contents is None or len(currContent) < len(contents):
                    contents = currContent
            if contents:
                errors[contents] = os.path.basename(fileName)[:-7]

        for msg, jobName in errors.items():
            sys.stderr.write("WARNING: error produced by slave job '" + jobName + "'\n" + msg)
    
    def cleanup(self):
        self.sendServerState("Completed submission of all tests")
    def remainStr(self):
        return " : " + str(self.testCount) + " tests remain, " + str(self.testsSubmitted) + " are submitted."
    def runTest(self, test):   
        submissionRules = self.getSubmissionRules(test)
        command = self.getSlaveCommand(test, submissionRules)
        plugins.log.info("Q: Submitting " + repr(test) + submissionRules.getSubmitSuffix())
        sys.stdout.flush()
        self.jobs[test] = [] # Preliminary jobs aren't interesting any more
        if not self.submitJob(test, submissionRules, command, self.getSlaveEnvironment()):
            return
        
        self.testCount -= 1
        self.testsSubmitted += 1
        self.diag.info("Submission successful" + self.remainStr())
        if not test.state.hasStarted():
            test.changeState(self.getPendingState(test))
        if self.testsSubmitted == self.maxCapacity:
            self.sendServerState("Completed submission of tests up to capacity")
    def getSlaveEnvironment(self):
        env = plugins.copyEnvironment()
        self.fixUseCaseVariables(env)
        return env

    def fixUseCaseVariables(self, env):
        # Make sure we clear out the master scripts so the slave doesn't use them too,
        # otherwise just use the environment as is
        if env.has_key("USECASE_REPLAY_SCRIPT") or env.has_key("USECASE_RECORD_SCRIPT"):
            env["USECASE_REPLAY_SCRIPT"] = ""
            env["USECASE_RECORD_SCRIPT"] = ""

    def fixDisplay(self, env):
        # Must make sure SGE jobs don't get a locally referencing DISPLAY
        display = env.get("DISPLAY")
        if display and display.startswith(":"):
            env["DISPLAY"] = plugins.gethostname() + display

    def getPendingState(self, test):
        freeText = "Job pending in " + queueSystemName(test.app)
        return plugins.TestState("pending", freeText=freeText, briefText="PEND", lifecycleChange="become pending")

    def shellWrap(self, command):
        # Must use exec so as not to create extra processes: SGE's qdel isn't very clever when
        # it comes to noticing extra shells
        return "exec $SHELL -c \"exec " + command + "\""

    def getSlaveCommand(self, test, submissionRules):
        cmdArgs = [ plugins.getTextTestProgram(), "-d", ":".join(self.optionMap.rootDirectories),
                    "-a", test.app.name + test.app.versionSuffix(),
                    "-l", "-tp", plugins.quote(test.getRelPath(), "'") ] + \
                    self.getSlaveArgs(test) + self.getRunOptions(test.app, submissionRules)
        return " ".join(cmdArgs)

    def getSlaveArgs(self, test):
        return [ "-slave", test.app.writeDirectory, "-servaddr", self.submitAddress ]
    
    def getRunOptions(self, app, submissionRules):
        runOptions = []
        for slaveSwitch in app.getSlaveSwitches():
            if self.optionMap.has_key(slaveSwitch):
                option = "-" + slaveSwitch
                runOptions.append(option)
                value = self.optionMap.get(slaveSwitch)
                if value:
                    runOptions.append(value)

        if self.optionMap.has_key("x"):
            runOptions.append("-xr")
            runOptions.append(os.path.expandvars("$TEXTTEST_PERSONAL_LOG/logging.debug"))
            runOptions.append("-xw")
            runOptions.append(os.path.expandvars("$TEXTTEST_PERSONAL_LOG/" + submissionRules.getJobName()))
        return runOptions
        
    def getSlaveLogDir(self, test):
        return os.path.join(test.app.writeDirectory, "slavelogs")

    def getSubmitCmdArgs(self, test, submissionRules):
        queueSystem = self.getQueueSystem(test)
        extraArgs = test.getEnvironment("QUEUE_SYSTEM_SUBMIT_ARGS", "") # Extra arguments to provide on submission to grid engine
        cmdArgs = queueSystem.getSubmitCmdArgs(submissionRules)
        if extraArgs:
            cmdArgs += plugins.splitcmd(extraArgs)
        return cmdArgs

    def getQueueSystemCommand(self, test):
        submissionRules = self.getSubmissionRules(test)
        cmdArgs = self.getSubmitCmdArgs(test, submissionRules)
        return queueSystemName(test) + " Command   : " + plugins.commandLineString(cmdArgs) + " ...\n" + \
               "Slave Command : " + self.getSlaveCommand(test, submissionRules) + "\n"

    def submitJob(self, test, submissionRules, command, slaveEnv):
        self.diag.info("Submitting job at " + plugins.localtime() + ":" + command)
        self.diag.info("Creating job at " + plugins.localtime())
        cmdArgs = self.getSubmitCmdArgs(test, submissionRules)
        cmdArgs.append(self.shellWrap(command))
        jobName = submissionRules.getJobName()
        self.fixDisplay(slaveEnv)
        self.diag.info("Creating job " + jobName + " with command arguments : " + repr(cmdArgs))
        self.lock.acquire()
        if self.exited:
            self.cancel(test)
            self.lock.release()
            plugins.log.info("Q: Submission cancelled for " + repr(test) + " - exit underway")
            return False
        
        self.lockDiag.info("Got lock for submission")
        queueSystem = self.getQueueSystem(test)
        try:
            process = subprocess.Popen(cmdArgs, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       cwd=self.getSlaveLogDir(test), env=slaveEnv)
            stdout, stderr = process.communicate()
            errorMessage = self.findErrorMessage(stderr, queueSystem)
        except OSError:
            errorMessage = "local machine is not a submit host: running '" + cmdArgs[0] + "' failed."
        if not errorMessage:
            jobId = queueSystem.findJobId(stdout)
            self.diag.info("Job created with id " + jobId)
            self.jobs.setdefault(test, []).append((jobId, jobName))
            self.lockDiag.info("Releasing lock for submission...")
            self.lock.release()
            return True
        else:
            self.lock.release()
            self.diag.info("Job not created : " + errorMessage)
            fullError = self.getFullSubmitError(test, errorMessage, cmdArgs)
            test.changeState(plugins.Unrunnable(fullError, "NOT SUBMITTED"))
            self.handleErrorState(test)
            return False
        
    def findErrorMessage(self, stderr, queueSystem):
        if len(stderr) > 0:
            return queueSystem.findSubmitError(stderr)

    def getFullSubmitError(self, test, errorMessage, cmdArgs):
        qname = queueSystemName(test.app)
        return "Failed to submit to " + qname + " (" + errorMessage.strip() + ")\n" + \
               "Submission command was '" + " ".join(cmdArgs[:-1]) + " ... '\n"

    def handleErrorState(self, test, previouslySubmitted=False):
        if previouslySubmitted:
            self.testsSubmitted -= 1
        else:
            self.testCount -= 1
        self.diag.info(repr(test) + " in error state" + self.remainStr())
        bugchecker = CheckForBugs()
        self.setUpSuites(bugchecker, test)
        bugchecker(test)
        test.actionsCompleted()        
    def setUpSuites(self, bugchecker, test):
        if test.parent:
            bugchecker.setUpSuite(test.parent)
            self.setUpSuites(bugchecker, test.parent)
    def _getJobFailureInfo(self, test):
        jobInfo = self.getJobInfo(test)
        if len(jobInfo) == 0:
            return "No job has been submitted to " + queueSystemName(test)
        queueSystem = self.getQueueSystem(test)
        # Take the most recent job, it's hopefully the most interesting
        jobId, jobName = jobInfo[-1]
        return queueSystem.getJobFailureInfo(jobId)
    def getSlaveErrors(self, test, name):
        slaveErrFile = self.getSlaveErrFile(test)
        if slaveErrFile:
            errors = open(slaveErrFile).read()
            if errors:
                return "-" * 10 + " Error messages written by " + name + " job " + "-" * 10 + \
                       "\n" + errors
 
    def getSlaveErrFile(self, test):
        for jobId, jobName in self.getJobInfo(test):
            errFile = os.path.join(self.getSlaveLogDir(test), jobName + ".errors")
            if os.path.isfile(errFile):
                return errFile
    
    def getJobInfo(self, test):
        return self.jobs.get(test, [])
    def killJob(self, test, jobId, jobName):
        prevTest, prevJobExisted = self.killedJobs.get(jobId, (None, False))
        # Killing the same job for other tests should result in the cached result being returned
        if prevTest and test is not prevTest:
            return prevJobExisted

        self.describeJob(test, jobId, jobName)
        queueSystem = self.getQueueSystem(test)
        jobExisted = queueSystem.killJob(jobId)
        self.killedJobs[jobId] = test, jobExisted
        return jobExisted
    def getQueueSystem(self, test):
        queueModule = queueSystemName(test).lower()
        if self.queueSystems.has_key(queueModule):
            return self.queueSystems[queueModule]
        
        command = "from " + queueModule + " import QueueSystem as _QueueSystem"
        exec command
        system = _QueueSystem()
        self.queueSystems[queueModule] = system
        return system
    def changeState(self, test, newState, previouslySubmitted=True):
        test.changeState(newState)
        self.handleLocalError(test, previouslySubmitted)
    
    def killTests(self):
        # If we've been killed with some sort of limit signal, wait here until we know
        # all tests terminate. Otherwise we rely on them terminating naturally, and if they don't
        wantStatus = self.killSignal and self.killSignal != signal.SIGINT
        killedTests = []
        for test, jobList in self.jobs.items():
            if not test.state.isComplete():
                for jobId, jobName in jobList:
                    if self.killTest(test, jobId, jobName, wantStatus):
                        killedTests.append((test, jobId))
        if wantStatus:
            self.waitForKill(killedTests)

    def waitForKill(self, killedTests):
        # Wait for a minute for the kill to take effect, otherwise give up
        stillRunning = killedTests
        for attempt in range(1, 61):
            stillRunning = filter(lambda (test, jobId): not test.state.isComplete(), stillRunning)
            if len(stillRunning) == 0:
                return
            time.sleep(1)
            for test, jobId in stillRunning:
                plugins.log.info("T: Cancellation in progress for " + repr(test) + 
                                 ", waited " + str(attempt) + " seconds so far.")
        for test, jobId in stillRunning:
            name = queueSystemName(test.app)
            freeText = "Could not delete test in " + name + " (job " + jobId + "): have abandoned it"
            self.changeState(test, Abandoned(freeText))

    def killOrCancel(self, test):
        # Explicitly chose test to kill (from the GUI)
        jobInfo = self.getJobInfo(test)
        if len(jobInfo) > 0:
            for jobId, jobName in self.getJobInfo(test):
                self.killTest(test, jobId, jobName, wantStatus=True)
        else:
            self.diag.info("No job info found from queue system server, changing state to cancelled")
            return self.cancel(test)
        
    def killTest(self, test, jobId, jobName, wantStatus):
        self.diag.info("Killing test " + repr(test) + " in state " + test.state.category)
        jobExisted = self.killJob(test, jobId, jobName)
        startNotified = self.jobStarted(test)
        if jobExisted:
            if startNotified:
                self.diag.info("Job " + jobId + " was running.")
                return True
            else:
                self.diag.info("Job " + jobId + " was pending.")
                self.setKilledPending(test, jobId)
                return False
        else:
            self.diag.info("Job " + jobId + " did not exist.")
            # might get here when the test completed since we checked...
            if not test.state.isComplete():
                self.setSlaveFailed(test, startNotified, wantStatus)
        return False
    def jobStarted(self, test):
        return test.state.hasStarted()
    def setKilledPending(self, test, jobId):
        timeStr =  plugins.localtime("%H:%M")
        briefText = "cancelled pending job at " + timeStr
        freeText = "Test job " + jobId + " was cancelled (while still pending in " + queueSystemName(test.app) +\
                   ") at " + timeStr
        self.cancel(test, briefText, freeText)

    def getJobFailureInfo(self, test, name, wantStatus):
        if wantStatus:
            return "-" * 10 + " Full accounting info from " + name + " " + "-" * 10 + "\n" + \
                   self._getJobFailureInfo(test)
        else:
            # Job accounting info can take ages to find, don't do it from GUI quit
            return "No accounting info found as quitting..."
        
    def setSlaveFailed(self, test, startNotified, wantStatus):
        failReason, fullText = self.getSlaveFailure(test, startNotified, wantStatus)
        fullText = failReason + "\n" + fullText
        self.changeState(test, self.getSlaveFailureState(startNotified, failReason, fullText))

    def getSlaveFailure(self, test, startNotified, wantStatus):
        fullText = ""
        name = queueSystemName(test.app)
        slaveErrors = self.getSlaveErrors(test, name)
        if slaveErrors:
            fullText += slaveErrors

        fullText += self.getJobFailureInfo(test, name, wantStatus)
        return self.getSlaveFailureBriefText(name, startNotified), fullText

    def getSlaveFailureBriefText(self, name, startNotified):
        if startNotified:
            return "no report, possibly killed with SIGKILL"
        else:
            return name + " job exited"

    def getSlaveFailureState(self, startNotified, failReason, fullText):
        if startNotified:
            return plugins.TestState("killed", briefText=failReason, \
                              freeText=fullText, completed=1, lifecycleChange="complete")
        else:
            return plugins.Unrunnable(briefText=failReason, freeText=fullText, lifecycleChange="complete")
        
    def getPostText(self, test, jobId):
        name = queueSystemName(test.app)
        return "in " + name + " (job " + jobId + ")"

    def describeJob(self, test, jobId, jobName):
        postText = self.getPostText(test, jobId)
        plugins.log.info("T: Cancelling " + repr(test) + " " + postText)


class SubmissionRules:
    def __init__(self, optionMap, test):
        self.test = test
        self.optionMap = optionMap
        self.envResource = self.getEnvironmentResource()
        self.processesNeeded = self.getProcessesNeeded()
    def getEnvironmentResource(self):
        return os.path.expandvars(self.test.getEnvironment("QUEUE_SYSTEM_RESOURCE", "")) # Grid engine resources required for the test
    def getProcessesNeeded(self):
        return self.test.getEnvironment("QUEUE_SYSTEM_PROCESSES", "1") # Number of processes the test needs to run
    def getJobName(self):
        path = self.test.getRelPath()
        parts = path.split("/")
        parts.reverse()
        name = "Test-" + ".".join(parts) + "-" + repr(self.test.app).replace(" ", "_")
        return name.replace(":", "_")
    def getSubmitSuffix(self):
        name = queueSystemName(self.test)
        queue = self.findQueue()
        if queue:
            return " to " + name + " queue " + queue
        else:
            return " to default " + name + " queue"
    def getParallelEnvironment(self):
        return self.test.getConfigValue("parallel_environment_name")
    def findResourceList(self):
        resourceList = []
        if self.optionMap.has_key("R"):
            resourceList.append(self.optionMap["R"])
        if len(self.envResource):
            resourceList.append(self.envResource)
        machine = self.test.app.getRunMachine()
        if machine != "localhost":
            resourceList.append("hostname=" + machine) # Won't work with LSF, but can't be bothered to figure it out there for now...
        if self.forceOnPerformanceMachines():
            resources = self.getConfigValue("performance_test_resource")
            for resource in resources:
                resourceList.append(resource)
        return resourceList
    def getConfigValue(self, configKey):
        configDict = self.test.getConfigValue(configKey)
        defVal = configDict.get("default")
        if len(defVal) > 0:
            return defVal
        for val in configDict.values():
            if len(val) > 0 and val[0] != "any" and val[0] != "none":
                return val
        return []
    def findPriority(self):
        return 0
    def findQueue(self):
        if self.optionMap.has_key("q"):
            return self.optionMap["q"]
        configQueue = self.test.app.getConfigValue("default_queue")
        if configQueue != "texttest_default":
            return configQueue

        return self.findDefaultQueue()
    def findDefaultQueue(self):
        return ""
    def findMachineList(self):
        if not self.forceOnPerformanceMachines():
            return []
        performanceMachines = self.getConfigValue("performance_test_machine")
        if len(performanceMachines) == 0:
            return []

        return performanceMachines
    def getJobFiles(self):
        jobName = self.getJobName()
        return jobName + ".log", jobName + ".errors"
    def forceOnPerformanceMachines(self):
        if self.optionMap.has_key("perf"):
            return 1

        minTimeForce = plugins.getNumberOfSeconds(str(self.test.getConfigValue("min_time_for_performance_force")))
        if minTimeForce >= 0 and getTestPerformance(self.test) > minTimeForce:
            return 1
        # If we haven't got a log_file yet, we should do this so we collect performance reliably
        logFile = self.test.getFileName(self.test.getConfigValue("log_file"))
        return logFile is None
    def allowsReuse(self, newRules):
        return self.findResourceList() == newRules.findResourceList() and \
               self.getProcessesNeeded() == newRules.getProcessesNeeded()

class SlaveRequestHandler(StreamRequestHandler):
    noReusePostfix = ".NO_REUSE"
    def handle(self):
        identifier = self.rfile.readline().strip()
        if identifier == "TERMINATE_SERVER":
            return
        clientHost, clientPort = self.client_address
        # Don't use port, it changes all the time
        self.handleRequestFromHost(self.getHostName(clientHost), identifier)

    def getHostName(self, ipAddress):
        return socket.gethostbyaddr(ipAddress)[0].split(".")[0]
        
    def handleRequestFromHost(self, hostname, identifier):
        testString = self.rfile.readline().strip()
        test = self.server.getTest(testString)
        tryReuse = not identifier.endswith(self.noReusePostfix)
        if not tryReuse:
            identifier = identifier.replace(self.noReusePostfix, "")
        if test is None:
            sys.stderr.write("WARNING: Received request from hostname " + hostname +
                             " (process " + identifier + ")\nwhich could not be parsed:\n'" + testString + "'\n")
            self.connection.shutdown(socket.SHUT_RDWR)
        elif self.server.clientCorrect(test, (hostname, identifier)):
            if not test.state.isComplete(): # we might have killed it already...
                oldBt = test.state.briefText
                # The updates are only for testing against old slave traffic,
                # a bit sad we can't disable them when not testing...
                loaded, state = test.getNewState(self.rfile, updatePaths=True)
                self.server.changeState(test, state)
                self.connection.shutdown(socket.SHUT_RD)
                self.server.diag.info("Changed from '" + oldBt + "' to '" + state.briefText + "'")
                if state.isComplete():
                    newTest = QueueSystemServer.instance.getTestForReuse(test, state, tryReuse)
                    if newTest:
                        self.wfile.write(socketSerialise(newTest))
                else:
                    self.server.storeClient(test, (hostname, identifier))
                self.connection.shutdown(socket.SHUT_WR)
        else:
            expectedHost, expectedPid = self.server.testClientInfo[test]
            sys.stderr.write("WARNING: Unexpected TextTest slave for " + repr(test) + " connected from " + \
                             hostname + " (process " + identifier + ")\n")
            sys.stderr.write("Slave already registered from " + expectedHost + " (process " + expectedPid + ")\n")
            sys.stderr.write("Ignored all communication from this unexpected TextTest slave\n")
            sys.stderr.flush()
            self.connection.shutdown(socket.SHUT_RDWR)
            

class SlaveServerResponder(plugins.Responder, ThreadingTCPServer):
    def __init__(self, *args):
        plugins.Responder.__init__(self, *args)
        ThreadingTCPServer.__init__(self, (socket.gethostname(), 0), self.handlerClass())
        self.testMap = {}
        self.testLocks = {}
        self.testClientInfo = {}
        self.diag = logging.getLogger("Slave Server")
        self.terminate = False
        
        # If a client rings in and then the connectivity is lost, we don't want to hang waiting for it forever
        # So we enable keepalive that will check the connection if no data is received for a while
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, True)
        # Default is 2 hours here on Linux which is rather a long time to wait for anything to happen.
        # We give up after 5 minutes
        if hasattr(socket, "TCP_KEEPIDLE"):
            self.socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPIDLE, 300)
        # Default value of 5 isn't very much...
        # There doesn't seem to be any disadvantage of allowing a longer queue, so we will increase it by a lot...
        self.request_queue_size = 500
        
    def addSuites(self, *args):
        # use this as an opportunity to broadcast our address
        serverAddress = self.getAddress()
        self.diag.info("Starting slave server at " + serverAddress)
        # Tell the submission code where we are
        QueueSystemServer.instance.setSlaveServerAddress(serverAddress)

    def handlerClass(self):    
        return SlaveRequestHandler

    def canBeMainThread(self):
        return False # We wait for sockets and stuff

    def run(self):
        while not self.terminate:
            self.diag.info("Waiting for a new request...")
            self.handle_request()
        
        self.diag.info("Terminating slave server")
        
    def notifyAllRead(self, suites):
        if len(self.testMap) == 0:
            self.notifyAllComplete()
            
    def notifyAllComplete(self):
        self.diag.info("Notified all complete, shutting down soon...")
        self.terminate = True
        sendSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sendSocket.connect(self.socket.getsockname())
        sendSocket.sendall("TERMINATE_SERVER\n")
        sendSocket.close()
        
    def getAddress(self):
        host, port = self.socket.getsockname()
        return host + ":" + str(port)

    def notifyAdd(self, test, initial):
        if test.classId() == "test-case":
            self.storeTest(test)
            
    def storeTest(self, test):
        testPath = test.getRelPath()
        testApp = test.app.name + test.app.versionSuffix()
        if not self.testMap.has_key(testApp):
            self.testMap[testApp] = {}
        self.testMap[testApp][testPath] = test
        self.testLocks[test] = RLock()

    def changeState(self, test, state):
        # Several threads could be trying to do this at once...
        lock = self.testLocks.get(test)
        lock.acquire()
        allow = self.allowChange(test.state, state)
        if allow:
            test.changeState(state)
        lock.release()
        return allow

    def allowChange(self, oldState, newState):
        return newState.isComplete() or not oldState.isComplete()

    def getTest(self, testString):
        self.diag.info("Received request for '" + testString + "'")
        try:
            appName, testPath = testString.split(":", 1)
            return self.testMap[appName][testPath]
        except ValueError:
            return
    
    def clientCorrect(self, test, clientInfo):
        # Only allow one client per test!
        if self.testClientInfo.has_key(test):
            return self.testClientInfo[test] == clientInfo
        else:
            return True

    def storeClient(self, test, clientInfo):
        self.testClientInfo[test] = clientInfo


class MasterTextResponder(TextDisplayResponder):
    def getPrefix(self, test):
        return "S: " # don't get things in order, so indenting is pointless
    
    def notifyComplete(self, test):
        self.describe(test) # Write the successful tests also

class MasterInteractiveResponder(InteractiveResponder):
    def getPrefix(self, test):
        return "" # don't get things in order, so indenting is pointless


