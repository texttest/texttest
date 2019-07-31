
"""
Code to do with the grid engine master process, i.e. submitting slave jobs and waiting for them to report back
"""

import os
import sys
import socket
import signal
import logging
import time
from .utils import *
from queue import Queue
from socketserver import ThreadingTCPServer, StreamRequestHandler
from threading import RLock, Lock
from collections import OrderedDict
from texttestlib import plugins
from texttestlib.default.console import TextDisplayResponder, InteractiveResponder
from texttestlib.default.knownbugs import CheckForBugs
from texttestlib.default.actionrunner import BaseActionRunner
from texttestlib.default.performance import getTestPerformance
from glob import glob
from locale import getpreferredencoding

plugins.addCategory("abandoned", "abandoned", "were abandoned")


class Abandoned(plugins.TestState):
    def __init__(self, freeText):
        plugins.TestState.__init__(self, "abandoned", briefText="job deletion failed",
                                   freeText=freeText, completed=1, lifecycleChange="complete")


class Pending(plugins.TestState):
    defaultBriefText = "PEND"

    def __init__(self, freeText, briefText=None, lifecycleChange="become pending"):
        briefText = briefText or self.defaultBriefText
        plugins.TestState.__init__(self, "pending", freeText=freeText,
                                   briefText=briefText, lifecycleChange=lifecycleChange)

    def makeModifiedState(self, newRunStatus, newDetails, lifecycleChange):
        if newRunStatus != self.briefText:
            newFreeText = self.freeText + "\n" + newDetails
            return self.__class__(newFreeText, newRunStatus, lifecycleChange)


class QueueSystemServer(BaseActionRunner):
    instance = None

    def __init__(self, optionMap, allApps):
        BaseActionRunner.__init__(self, optionMap, logging.getLogger("Queue System Submit"))
        # queue for putting tests when we couldn't reuse the originals
        self.reuseFailureQueue = Queue()
        self.counterLock = Lock()
        self.testCount = 0
        self.testsSubmitted = 0
        self.maxCapacity = 100000  # infinity, sort of
        self.allApps = allApps
        self.jobs = OrderedDict()
        self.submissionRules = {}
        self.killedJobs = {}
        self.queueSystems = {}
        self.reusedTests = {}
        self.reuseOnly = False
        self.allRead = False
        self.submitAddress = None
        self.createDirectories = False
        self.slaveLogDirs = set()
        self.delayedTestsForAdd = []
        self.remainingForApp = OrderedDict()
        appCapacities = []
        for app in allApps:
            appCapacity = self.maxCapacity
            queueSystem = self.getQueueSystem(app)  # populate cache
            queueCapacity = queueSystem.getCapacity() if queueSystem else None
            # If the slaves run somewhere else, they won't create directories for us
            if queueSystem:
                self.createDirectories |= queueSystem.slavesOnRemoteSystem()
            configCapacity = app.getConfigValue("queue_system_max_capacity")
            for currCap in [queueCapacity, configCapacity]:
                if currCap is not None and currCap < appCapacity:
                    appCapacity = currCap
            appCapacities.append(appCapacity)
        if all((c == 0 for c in appCapacities)):
            raise plugins.TextTestError(
                "The queue system module is reporting zero capacity.\nEither you have set 'queue_system_max_capacity' to 0 or something is uninstalled or unavailable. Exiting.")

        self.maxCapacity = min((c for c in appCapacities if c != 0))
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
        self.submitAddress = os.getenv("CAPTUREMOCK_SERVER", address)
        self.testQueue.put("TextTest slave server started on " + address)

    def addTest(self, test):
        if self.createDirectories:
            test.makeWriteDirectory()
        capacityForApp = self.remainingForApp[test.app.name]
        if capacityForApp > 0:
            self.addTestToQueues(test)
            self.remainingForApp[test.app.name] = capacityForApp - 1
        else:
            if test.app.name == list(self.remainingForApp.keys())[-1]:
                self.addTestToQueues(test)  # For the last app (which may be the only one) there is no point in delaying
            else:
                self.delayedTestsForAdd.append(test)

    def queueTestForRerun(self, test):
        # Clear out the previous job reference, otherwise our grid polling will kill it off
        self.jobs[test] = []
        self.addTestToQueues(test)

    def addTestToQueues(self, test):
        with self.counterLock:
            self.testCount += 1
        queue = self.findQueueForTest(test)
        if queue:
            queue.put(test)

    def addDelayedTests(self):
        for test in self.delayedTestsForAdd:
            self.addTestToQueues(test)
        self.delayedTestsForAdd = []

    def notifyAllRead(self, suites):
        self.addDelayedTests()
        BaseActionRunner.notifyAllRead(self, suites)
        self.allRead = True

    def run(self):  # picked up by core to indicate running in a thread
        try:
            self.runAllTests()
            if len(self.jobs):
                self.diag.info("All jobs submitted, polling the queue system now.")
                if self.canPoll():
                    self.pollQueueSystem()
            self.diag.info("No jobs left to poll, exiting thread")
        except:
            self.diag.info("Submit thread exited with exception!")
            plugins.printException()

    def pollQueueSystem(self):
        # Start by polling after 5 seconds, ever after try every 15
        interval = float(os.getenv("TEXTTEST_QS_POLL_INTERVAL", "0.5"))         # Amount of time to wait between checks for exit/completion when polling grid/cloud
        attempts = int(float(os.getenv("TEXTTEST_QS_POLL_WAIT", "5")) / interval) # Amount of time to wait before initiating polling of grid/cloud
        subsequentAttempts = int(float(os.getenv("TEXTTEST_QS_POLL_SUBSEQUENT_WAIT", "15")) / interval) # Amount of time to wait before subsequent polling of grid/cloud
        if attempts >= 0:
            while True:
                for _ in range(attempts):
                    time.sleep(interval)
                    if self.allComplete:
                        return
                    if self.exited:
                        break
                if not self.exited:
                    self.updateJobStatus()
                attempts = subsequentAttempts
                self.diag.info("Trying to rerun queues " + repr(self.testsSubmitted) +
                               " out of " + repr(self.maxCapacity) + " tests submitted")
                # In case any tests have had reruns triggered since we stopped submitting
                self.runQueue(self.getTestForRun, self.runTest, "rerunning", block=False)

    def canPoll(self):
        queueSystem = self.getQueueSystem(list(self.jobs.keys())[0])
        return queueSystem.supportsPolling()

    def updateJobStatus(self):
        queueSystem = self.getQueueSystem(list(self.jobs.keys())[0])
        statusInfo = queueSystem.getStatusForAllJobs()
        self.diag.info("Got status for all jobs : " + repr(statusInfo))
        if statusInfo is not None:  # queue system not available for some reason
            for test, jobs in list(self.jobs.items()):
                if not test.state.isComplete():
                    for jobId, jobName in jobs:
                        status = statusInfo.get(jobId)
                        if status:
                            # Only do this to test jobs (might make a difference for derived configurations)
                            # Ignore filtering states for now, which have empty 'briefText'.
                            self.updateRunStatus(test, status)
                        elif not status and not self.jobCompleted(test, jobName):
                            # Do this to any jobs
                            self.setSlaveFailed(test, self.jobStarted(test, jobName), True, jobId)

    def updateRunStatus(self, test, status):
        newRunStatus, newExplanation = status
        newState = test.state.makeModifiedState(newRunStatus, newExplanation, "grid status update")
        if newState:
            test.changeState(newState)

    def findQueueForTest(self, test):
        # If we've gone into reuse mode and there are no active tests for reuse, use the "reuse failure queue"
        if self.reuseOnly and self.testsSubmitted == 0:
            self.diag.info("Putting " + test.uniqueName + " in reuse failure queue " + self.remainStr())
            return self.reuseFailureQueue
        else:
            self.diag.info("Putting " + test.uniqueName + " in normal queue " + self.remainStr())
            return self.testQueue

    def handleLocalError(self, test, previouslySubmitted):
        self.handleErrorState(test, previouslySubmitted)
        if (self.testCount == 0 and self.allRead) or (self.reuseOnly and self.testsSubmitted == 0):
            self.diag.info("Submitting terminators after local error")
            self.submitTerminators()

    def submitTerminators(self):
        # snap out of our loop if this was the last one. Rely on others to manage the test queue
        self.reuseFailureQueue.put(None)

    def getTestForReuse(self, test, state, tryReuse, doneRerun):
        # Pick up any test that matches the current one's resource requirements
        if not self.exited:
            if test in self.reusedTests:
                newTest = self.reusedTests.get(test)
                newTestName = newTest.uniqueName if newTest else " no test."
                self.diag.info("Repeating answer: using slave from " + test.uniqueName + " for " + newTestName)
                return newTest
            # Don't allow this to use up the terminator
            newTest = self.getTest(block=False, replaceTerminators=True)
            if newTest:
                if tryReuse and self.allowReuse(test, state, newTest):
                    if not doneRerun:
                        self.reusedTests[test] = newTest
                    self.jobs[newTest] = self.getJobInfo(test)
                    with self.counterLock:
                        if self.testCount > 1:
                            self.testCount -= 1
                            postText = self.remainStr()
                        else:
                            # Don't allow test count to drop to 0 here, can cause race conditions
                            self.submitTerminators()
                            postText = ": submitting terminators as final test"
                    self.diag.info("Reusing slave from " + test.uniqueName + " for " + newTest.uniqueName + postText)
                    return newTest
                else:
                    self.diag.info("Adding to reuse failure queue : " + newTest.uniqueName)
                    self.reuseFailureQueue.put(newTest)
            else:
                self.diag.info("No tests available for reuse : " + test.uniqueName)
            self.reusedTests[test] = None

        # Allowed a submitted job to terminate
        with self.counterLock:
            self.testsSubmitted -= 1
            self.diag.info("No reuse for " + test.uniqueName + " : " +
                           repr(self.testsSubmitted) + " tests still submitted")
            if self.exited and self.testsSubmitted == 0:
                self.diag.info("Forcing termination")
                self.submitTerminators()

    def allowReuse(self, oldTest, oldState, newTest):
        # Don't reuse jobs that have been killed
        if newTest.state.isComplete() or oldState.category == "killed":
            return False

        if oldTest.getConfigValue("queue_system_proxy_executable") or \
           newTest.getConfigValue("queue_system_proxy_executable"):
            return False

        # Jobs maintain the same virtual display instance where possible, if they require different settings they can't be reused
        if oldTest.getConfigValue("virtual_display_extra_args") != newTest.getConfigValue("virtual_display_extra_args") or \
                oldTest.getConfigValue("virtual_display_count") != newTest.getConfigValue("virtual_display_count"):
            return False

        oldRules = self.getSubmissionRules(oldTest)
        newRules = self.getSubmissionRules(newTest)
        return oldRules.allowsReuse(newRules)

    def getJobSubmissionRules(self, test):
        proxyRules = test.app.getProxySubmissionRules(test)
        if proxyRules:
            return proxyRules
        else:
            return self.getSubmissionRules(test)

    def getSubmissionRules(self, test):
        if test in self.submissionRules:
            return self.submissionRules[test]
        else:
            submissionRules = test.app.getSubmissionRules(test)
            self.submissionRules[test] = submissionRules
            return submissionRules

    def getTest(self, block, replaceTerminators=False):
        testOrStatus = self.getItemFromQueue(self.testQueue, block, replaceTerminators)
        if not testOrStatus:
            return
        if type(testOrStatus) == str:
            self.sendServerState(testOrStatus)
            return self.getTest(block)
        else:
            return testOrStatus

    def sendServerState(self, state):
        self.diag.info("Sending server state '" + state + "'")
        mimServAddr = os.getenv("CAPTUREMOCK_SERVER")
        if mimServAddr:
            host, port = mimServAddr.split(":")
            serverAddress = (host, int(port))
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(serverAddress)
            sock.sendall(("SUT_SERVER:" + state + "\n").encode(getpreferredencoding()))
            sock.close()

    def getTestForRunNormalMode(self, block):
        self.reuseOnly = False
        reuseFailure = self.getItemFromQueue(self.reuseFailureQueue, block=False)
        if reuseFailure:
            self.diag.info("Found a reuse failure...")
            return reuseFailure
        else:
            self.diag.info("Waiting for new tests...")
            newTest = self.getTest(block=block)
            if newTest:
                return newTest
            else:
                # Make sure we pick up anything that failed in reuse while we were submitting the final test...
                self.diag.info("No normal test found, checking reuse failures...")
                return self.getItemFromQueue(self.reuseFailureQueue, block=False)

    def getTestForRunReuseOnlyMode(self, block):
        self.reuseOnly = True
        self.diag.info("Waiting for reuse failures...")
        reuseFailure = self.getItemFromQueue(self.reuseFailureQueue, block=block)
        if reuseFailure:
            return reuseFailure
        elif self.testCount > 0 and self.testsSubmitted < self.maxCapacity:
            # Try again, the capacity situation has changed...
            return self.getTestForRunNormalMode(block)

    def getTestForRun(self, block=True):
        if (self.testCount == 0 and self.allRead) or (self.testsSubmitted < self.maxCapacity):
            return self.getTestForRunNormalMode(block)
        elif self.reuseCanFail():
            return self.getTestForRunReuseOnlyMode(block)
        else:
            self.diag.info("No more tests found, reuse cannot fail, stopping.")

    def reuseCanFail(self):
        return any((not qs.slavesOnRemoteSystem() for qs in list(self.queueSystems.values())))

    def notifyAllComplete(self):
        BaseActionRunner.notifyAllComplete(self)
        self.cleanup(final=True)
        if self.reuseOnly: # could still be hanging waiting for this, make sure we terminate
            self.submitTerminators()

        errors = {}
        errorFiles = []
        for logDir in self.slaveLogDirs:
            errorFiles += list(filter(os.path.getsize, glob(os.path.join(logDir, "*.errors"))))
        self.diag.info("All complete, processing " + str(len(errorFiles)) + " error files...")
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

        for msg, jobName in list(errors.items()):
            sys.stderr.write("WARNING: error produced by slave job '" + jobName + "'\n" + msg)

    def cleanup(self, final=False):
        cleanupComplete = True
        if self.jobs:
            queueSystem = self.getQueueSystem(list(self.jobs.keys())[0])
            cleanupComplete &= queueSystem.cleanup(final)
        if cleanupComplete and not final:
            self.sendServerState("Completed submission of all tests")

    def remainStr(self):
        return " : " + str(self.testCount) + " tests remain, " + str(self.testsSubmitted) + " are submitted."

    def runTest(self, test):
        submissionRules = self.getSubmissionRules(test)
        commandArgs = self.getSlaveCommandArgs(test, submissionRules)
        plugins.log.info("Q: Submitting " + repr(test) + submissionRules.getSubmitSuffix())
        sys.stdout.flush()
        self.jobs[test] = []  # Preliminary jobs aren't interesting any more
        slaveEnv = OrderedDict()
        if not self.submitJob(test, submissionRules, commandArgs, slaveEnv):
            return

        with self.counterLock:
            self.testCount -= 1
            self.testsSubmitted += 1
            self.diag.info("Submission successful" + self.remainStr())
        if not test.state.hasStarted():
            test.changeState(self.getPendingState(test))
        if self.testsSubmitted == self.maxCapacity:
            self.sendServerState("Completed submission of tests up to capacity")

    def fixConfigEnv(self, env, test):
        for envVar in test.getConfigValue("queue_system_environment"):
            val = os.getenv(envVar)
            if val is not None:
                env[envVar] = val

    def fixProxyVar(self, env, test, withProxy):
        if withProxy and test.getConfigValue("queue_system_proxy_executable"):
            env["TEXTTEST_SUBMIT_COMMAND_ARGS"] = "?"

    def fixDisplay(self, env):
        # Must make sure SGE jobs don't get a locally referencing DISPLAY
        display = os.environ.get("DISPLAY")
        if display and display.startswith(":"):
            env["DISPLAY"] = plugins.gethostname() + display

    def getPendingState(self, test):
        return Pending(freeText="Job pending in " + queueSystemName(test.app))

    def getSlaveCommandArgs(self, test, submissionRules):
        queueSystem = self.getQueueSystem(test)
        args = queueSystem.getTextTestArgs()
        if queueSystem.slavesOnRemoteSystem():
            args += ["-home", os.path.expanduser("~")]
        return args + ["-d", ":".join(self.optionMap.rootDirectories),
                       "-a", test.app.name + test.app.versionSuffix(),
                       "-l", "-tp", test.getRelPath()] + \
            self.getSlaveArgs(test) + self.getRunOptions(test.app, submissionRules)

    def getSlaveArgs(self, test):
        return ["-slave", test.app.writeDirectory, "-servaddr", self.submitAddress]

    def getRunOptions(self, app, submissionRules):
        runOptions = []
        for slaveSwitch in app.getSlaveSwitches():
            if slaveSwitch in self.optionMap:
                option = "-" + slaveSwitch
                runOptions.append(option)
                value = self.optionMap.get(slaveSwitch)
                if value:
                    runOptions.append(value)

        if "xs" in self.optionMap:
            runOptions.append("-x")
            runOptions.append("-xr")
            runOptions.append(self.optionMap.get("xr", os.path.expandvars("$TEXTTEST_PERSONAL_LOG/logging.debug")))
            runOptions.append("-xw")
            runOptions.append(os.path.expandvars("$TEXTTEST_PERSONAL_LOG/" + submissionRules.getJobName()))
        return runOptions

    def getSlaveLogDir(self, test):
        return os.path.join(test.app.writeDirectory, "slavelogs")

    def setRemoteProcessId(self, test, pid):
        jobInfo = self.getJobInfo(test)
        if len(jobInfo) > 0:
            # Take the most recent job, it's hopefully the most interesting
            jobId = jobInfo[-1][0]
            queueSystem = self.getQueueSystem(test)
            queueSystem.setRemoteProcessId(jobId, pid)

    def getRemoteTestTmpDir(self, test):
        jobInfo = self.getJobInfo(test)
        if len(jobInfo) > 0:
            # Take the most recent job, it's hopefully the most interesting
            jobId = jobInfo[-1][0]
            queueSystem = self.getQueueSystem(test)
            remoteMachine = queueSystem.getRemoteTestMachine(jobId)
            if remoteMachine:
                return remoteMachine, test.writeDirectory

    def getSubmitCmdArgs(self, test, *args):
        queueSystem = self.getQueueSystem(test)
        return queueSystem.getSubmitCmdArgs(*args)

    def getQueueSystemCommand(self, test):
        submissionRules = self.getSubmissionRules(test)
        cmdArgs = self.getSubmitCmdArgs(test, submissionRules)
        text = queueSystemName(test) + " Command   : " + plugins.commandLineString(cmdArgs) + " ...\n" + \
            "Slave Command : " + " ".join(self.getSlaveCommandArgs(test, submissionRules)) + "\n"
        proxyArgs = self.getProxyCmdArgs(test)
        if proxyArgs:
            return queueSystemName(test) + " Proxy Command   : " + plugins.commandLineString(proxyArgs) + "\n" + text
        else:
            return text

    def getProxyCmdArgs(self, test, slaveEnv={}):
        proxyCmd = test.getConfigValue("queue_system_proxy_executable")
        if proxyCmd:
            proxyOptions = test.getCommandLineOptions("proxy_options")
            fullProxyCmdArgs = [proxyCmd] + proxyOptions
            proxyRules = self.getJobSubmissionRules(test)
            return self.getSubmitCmdArgs(test, proxyRules, fullProxyCmdArgs, slaveEnv)
        else:
            return []

    def modifyCommandForProxy(self, test, cmdArgs, slaveEnv):
        proxyArgs = self.getProxyCmdArgs(test, slaveEnv)
        if proxyArgs:
            cmdArgs[1:1] = ["-sync", "y", "-V"]  # must sychronise in the proxy
            # Proxy likes to set environment variables, make sure they get forwarded
            slaveEnv["TEXTTEST_SUBMIT_COMMAND_ARGS"] = repr(cmdArgs) # Exact command arguments to run TextTest slave, for use by proxy
            return proxyArgs
        else:
            return cmdArgs

    def submitJob(self, test, submissionRules, commandArgs, slaveEnv, withProxy=True, jobType=""):
        self.diag.info("Submitting job at " + plugins.localtime() + ":" + repr(commandArgs))
        self.diag.info("Creating job at " + plugins.localtime())
        self.fixDisplay(slaveEnv)
        self.fixConfigEnv(slaveEnv, test)
        self.fixProxyVar(slaveEnv, test, withProxy)
        cmdArgs = self.getSubmitCmdArgs(test, submissionRules, commandArgs, slaveEnv)
        if withProxy:
            cmdArgs = self.modifyCommandForProxy(test, cmdArgs, slaveEnv)

        jobName = submissionRules.getJobName()
        self.diag.info("Creating job " + jobName + " with command arguments : " + " ".join(cmdArgs))
        with self.lock:
            if self.exited:
                self.cancel(test)
                plugins.log.info("Q: Submission cancelled for " + repr(test) + " - exit underway")
                return False

            self.lockDiag.info("Got lock for submission")
            queueSystem = self.getQueueSystem(test)
            logDir = self.getSlaveLogDir(test)
            jobId, errorMessage = queueSystem.submitSlaveJob(cmdArgs, slaveEnv, logDir, submissionRules, jobType)
            if jobId is not None:
                self.diag.info("Job created with id " + jobId)
                self.checkQueueCapacity(queueSystem)
                self.jobs.setdefault(test, []).append((jobId, jobName))
                self.lockDiag.info("Releasing lock for submission...")
                return True
            else:
                self.diag.info("Job not created : " + errorMessage)
                test.changeState(plugins.Unrunnable(errorMessage, "NOT SUBMITTED"))
                self.handleErrorState(test)
                return False

    def checkQueueCapacity(self, queueSystem):
        queueCapacity = queueSystem.getCapacity()
        if queueCapacity:
            with self.counterLock:
                if queueCapacity < self.maxCapacity:
                    self.maxCapacity = queueCapacity

    def handleErrorState(self, test, previouslySubmitted=False):
        with self.counterLock:
            if self.maxCapacity > 1:
                self.maxCapacity -= 1
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
        # Take the most recent job, it's hopefully the most interesting
        jobId = jobInfo[-1][0] if len(jobInfo) > 0 else None
        queueSystem = self.getQueueSystem(test)
        return queueSystem.getJobFailureInfo(jobId)

    def getSlaveErrors(self, test, name):
        errorTexts = [self.getSlaveErrorText(test, jobName, desc)
                      for jobName, desc in self.getErrorJobNames(test, name)]
        return "\n".join([text for text in errorTexts if text])

    def getErrorJobNames(self, test, name):
        jobNames = []
        for _, jobName in self.getJobInfo(test):
            jobNames.append((jobName, name))
            if jobName.startswith("Test-"):
                jobNames.append(("Proxy-" + jobName[5:], name + " Proxy"))
        return jobNames

    def getSlaveErrorText(self, test, jobName, desc):
        errFile = os.path.join(self.getSlaveLogDir(test), jobName + ".errors")
        if os.path.isfile(errFile):
            errors = open(errFile).read()
            if errors:
                return "-" * 10 + " Error messages written by " + desc + " job " + "-" * 10 + \
                    "\n" + errors
        return ""

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
        queueModuleText = queueSystemName(test)
        if queueModuleText is None:
            return None
        queueModule = queueModuleText.lower()
        if queueModule in self.queueSystems:
            return self.queueSystems[queueModule]

        namespace = {}
        command = "from ." + queueModule + " import QueueSystem as _QueueSystem"
        exec(command, globals(), namespace)
        system = namespace["_QueueSystem"](test)
        self.queueSystems[queueModule] = system
        return system

    def changeState(self, test, newState, previouslySubmitted=True):
        test.changeState(newState)
        self.handleLocalError(test, previouslySubmitted)

    def killTests(self):
        # If we've been killed with some sort of limit signal, wait here until we know
        # all tests terminate. Otherwise we rely on them terminating naturally, and if they don't
        wantStatus = self.killSignal and self.killSignal not in [signal.SIGINT, signal.SIGTERM]
        killedTests = []
        for test, jobList in list(self.jobs.items()):
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
            stillRunning = [test_jobId for test_jobId in stillRunning if not test_jobId[0].state.isComplete()]
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
            for jobId, jobName in jobInfo:
                self.killTest(test, jobId, jobName, wantStatus=True)
        else:
            self.diag.info("No job info found from queue system server, changing state to cancelled")
            return self.cancel(test)

    def killTest(self, test, jobId, jobName, wantStatus):
        self.diag.info("Killing test " + repr(test) + " in state " + test.state.category)
        jobExisted = self.killJob(test, jobId, jobName)
        startNotified = self.jobStarted(test, jobName)
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
                self.setSlaveFailed(test, startNotified, wantStatus, jobId)
        return False

    def setSuspendStateForTests(self, tests, newState):
        for test in tests:
            queueSystem = self.getQueueSystem(test)
            for jobId, _ in self.getJobInfo(test):
                queueSystem.setSuspendState(jobId, newState)

    def jobStarted(self, test, *args):
        return test.state.hasStarted()

    def jobCompleted(self, test, *args):
        return test.state.isComplete()

    def setKilledPending(self, test, jobId):
        timeStr = plugins.localtime("%H:%M")
        briefText = "cancelled pending job at " + timeStr
        freeText = "Test job " + jobId + " was cancelled (while still pending in " + queueSystemName(test.app) +\
                   ") at " + timeStr
        self.cancel(test, briefText, freeText)

    def getJobFailureInfo(self, test, wantStatus):
        if wantStatus:
            return self._getJobFailureInfo(test)
        else:
            # Job accounting info can take ages to find, don't do it from GUI quit
            return "No accounting info found as quitting..."

    def setSlaveFailed(self, test, startNotified, wantStatus, jobId):
        failReason, fullText = self.getSlaveFailure(test, startNotified, wantStatus)
        fullText = failReason + "\nJob ID was " + jobId + "\n" + fullText
        self.changeState(test, self.getSlaveFailureState(startNotified, failReason, fullText))

    def getSlaveFailure(self, test, startNotified, wantStatus):
        fullText = ""
        name = queueSystemName(test.app)
        slaveErrors = self.getSlaveErrors(test, name)
        if slaveErrors:
            fullText += slaveErrors

        fullText += self.getJobFailureInfo(test, wantStatus)
        return self.getSlaveFailureBriefText(name, startNotified), fullText

    def getSlaveFailureBriefText(self, name, startNotified):
        if startNotified:
            return "no report, possibly killed with SIGKILL"
        else:
            return name + " job exited"

    def getSlaveFailureState(self, startNotified, failReason, fullText):
        if startNotified:
            return plugins.TestState("killed", briefText=failReason,
                                     freeText=fullText, completed=1, lifecycleChange="complete")
        else:
            return plugins.Unrunnable(briefText=failReason, freeText=fullText, lifecycleChange="complete")

    def getPostText(self, test, jobId):
        name = queueSystemName(test.app)
        return "in " + name + " (job " + jobId + ")"

    def describeJob(self, test, jobId, *args):
        postText = self.getPostText(test, jobId)
        plugins.log.info("T: Cancelling " + repr(test) + " " + postText)

# Used in slave


class BasicSubmissionRules:
    classPrefix = "Test"

    def __init__(self, test):
        self.test = test
        self.diag = logging.getLogger("Submission Rules")

    def getJobName(self):
        path = self.test.getRelPath()
        parts = path.split(os.sep)
        parts.reverse()
        name = self.classPrefix + "-" + ".".join(parts) + "-" + repr(self.test.app).replace(" ", "_").replace("/", "_")
        return name.replace(":", "_")

    def getJobFiles(self):
        jobName = self.getJobName()
        return jobName + ".log", jobName + ".errors"


class SubmissionRules(BasicSubmissionRules):
    def __init__(self, optionMap, test):
        BasicSubmissionRules.__init__(self, test)
        self.optionMap = optionMap
        self.configResources = self.getConfigResources(test)
        self.processesNeeded = self.getProcessesNeeded()

    def getProcessesNeeded(self):
        return 1

    def getExtraSubmitArgs(self):  # pragma: no cover - documentation only
        return []

    def getParallelEnvironment(self):
        return ""

    def useCoreBinding(self):
        return False

    def findPriority(self):
        return 0

    def findResourceList(self):
        return self.configResources

    def findQueue(self):
        cmdQueue = self.optionMap.get("q", "")
        if cmdQueue:
            return cmdQueue
        configQueue = self.test.app.getConfigValue("default_queue")
        if configQueue != "texttest_default":
            return configQueue

        return self.findDefaultQueue()

    def findDefaultQueue(self):
        return ""

    def findMachineList(self):
        return []

    def forceOnPerformanceMachines(self):
        return False

    def allowsReuse(self, newRules):
        # Don't care about the order of the resources
        return set(self.configResources) == set(newRules.configResources)


class ProxySubmissionRules(SubmissionRules):
    classPrefix = "Proxy"

    def getConfigResources(self, test):
        return test.getConfigValue("queue_system_proxy_resource")


class TestSubmissionRules(SubmissionRules):
    classPrefix = "Test"

    def getConfigResources(self, test):
        if "reconnect" not in self.optionMap:
            configSettings = test.getConfigValue("queue_system_resource")
            envSetting = os.path.expandvars(test.getEnvironment("QUEUE_SYSTEM_RESOURCE", "")) # Deprecated. See "queue_system_resource" in config file docs
            return configSettings + [envSetting] if envSetting else configSettings
        else:
            return ""

    def getProcessesNeeded(self):
        if "reconnect" not in self.optionMap:
            envSetting = self.test.getEnvironment("QUEUE_SYSTEM_PROCESSES", "")  # Deprecated. See "queue_system_processes" in config file docs
            return int(envSetting) if envSetting else self.test.getConfigValue("queue_system_processes")
        else:
            return 1

    def getExtraSubmitArgs(self):
        if "reconnect" not in self.optionMap:
            envSetting = os.path.expandvars(self.test.getEnvironment("QUEUE_SYSTEM_SUBMIT_ARGS", ""))  # Deprecated. See "queue_system_submit_args" in config file docs
            argStr = envSetting or self.test.getConfigValue("queue_system_submit_args")
            return plugins.splitcmd(argStr)
        else:
            return []

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
        self.diag.info("Finding resource list for " + repr(self.test))
        cmdResource = self.optionMap.get("R")
        if cmdResource:
            self.diag.info("Adding from command line resource: " + repr(cmdResource))
            resourceList.append(cmdResource)
        resourceList += self.configResources
        machine = self.optionMap.get("m")
        if machine and machine != "localhost":
            # Won't work with LSF, but can't be bothered to figure it out there for now...
            machineResource = "hostname=" + machine
            self.diag.info("Adding from command line machine: " + repr(machineResource))
            resourceList.append(machineResource)
        if self.forceOnPerformanceMachines():
            resources = self.getConfigValue("performance_test_resource")
            self.diag.info(
                "Forcing on performance machines: adding from all keys in performance_test_resource : " + repr(",".join(resources)))
            for resource in resources:
                resourceList.append(resource)
        self.diag.info("Resource list for " + repr(self.test) + " = " + ",".join(resourceList))
        return resourceList

    def getConfigValue(self, configKey):
        configDict = self.test.getConfigValue(configKey)
        defVal = configDict.get("default")
        if len(defVal) > 0:
            return defVal
        for val in list(configDict.values()):
            if len(val) > 0 and val[0] != "any" and val[0] != "none":
                return val
        return []

    def findMachineList(self):
        self.diag.info("Finding machine list for " + repr(self.test))
        if not self.forceOnPerformanceMachines():
            return []
        performanceMachines = self.getConfigValue("performance_test_machine")
        self.diag.info("Machine list for " + repr(self.test) + " = " + ",".join(performanceMachines))
        return performanceMachines

    def getJobFiles(self):
        jobName = self.getJobName()
        return jobName + ".log", jobName + ".errors"

    def forceOnPerformanceMachines(self):
        if "perf" in self.optionMap:
            self.diag.info("-perf flag provided, forcing on performance machines")
            return True

        minTimeForce = plugins.getNumberOfSeconds(str(self.test.getConfigValue("min_time_for_performance_force")))
        if minTimeForce >= 0:
            testPerf = getTestPerformance(self.test)
            if testPerf > minTimeForce:
                self.diag.info("Test expects to take " + repr(testPerf) +
                               " seconds, min_time_for_performance_force = " + repr(minTimeForce) + " seconds")
                return True
        # If we haven't got a log_file yet, we should do this so we collect performance reliably
        logFileStem = self.test.getConfigValue("log_file")
        logFile = self.test.getFileName(logFileStem)
        if logFile is None:
            self.diag.info("No log file (file with stem " + repr(logFileStem) +
                           ") exists in test yet, forcing on performance machines to collect initial files")
        return logFile is None

    def allowsReuse(self, newRules):
        if "reconnect" in self.optionMap:
            return True  # should be able to reconnect anywhere...
        else:
            # Don't care about the order of the resources
            return set(self.findResourceList()) == set(newRules.findResourceList()) and \
                self.processesNeeded == newRules.processesNeeded


class SlaveRequestHandler(StreamRequestHandler):
    def handle(self):
        identifier = str(self.rfile.readline().strip(), getpreferredencoding())
        if identifier == "TERMINATE_SERVER":
            return

        self.handleMessage(identifier)

    def handleMessage(self, identifier):
        # Don't use port, it changes all the time
        identifier, sendFiles, getFiles, tryReuse, rerun = parseIdentifier(identifier)
        testString = str(self.rfile.readline().strip(), getpreferredencoding())
        test = self.server.getTest(testString)
        if test is None:
            clientHost = self.client_address[0]
            sys.stderr.write("WARNING: Received request from hostname " + self.getHostName(clientHost) +
                             " (process " + identifier + ")\nwhich could not be parsed:\n'" + testString + "'\n")
        elif getFiles:
            self.pushFiles(test)
        elif not test.state.isComplete() or not test.state.hasResults():  # we might have killed it already...
            if sendFiles:
                self.server.diag.info("Test " + test.uniqueName +
                                      " - receiving files sent from slave to sandbox directory")
                directoryUnserialise(test.writeDirectory, self.rfile)
            # Don't use port, it changes all the time
            self.handleRequestFromHost(test, identifier, tryReuse, rerun)
        else:
            self.server.diag.info("Test " + test.uniqueName + " already complete, ignoring new results")
            self.sendReuseResponse(test, test.state, tryReuse, False)
        self.connection.shutdown(socket.SHUT_RDWR)

    def getHostName(self, ipAddress):
        try:
            return socket.gethostbyaddr(ipAddress)[0].split(".")[0]
        except socket.error:
            return ipAddress

    def pushFiles(self, test):
        encoding = getpreferredencoding()
        userAndHost = str(self.rfile.readline().strip(), encoding)
        paths = []
        for line in self.rfile:
            paths.append(str(line.strip(), encoding))
        self.server.pushFiles(test, userAndHost, paths)

    def sendReuseResponse(self, *args):
        newTest = QueueSystemServer.instance.getTestForReuse(*args)
        if newTest:
            response = socketSerialise(newTest)
            self.server.diag.info("Sending reuse response " + response)
            self.wfile.write(response.encode(getpreferredencoding()))

    def handleRequestFromHost(self, test, pid, tryReuse, rerun):
        # The updates are only for testing against old slave traffic,
        # a bit sad we can't disable them when not testing...
        _, state = test.getNewState(self.rfile, updatePaths=True)
        if test.state.isComplete():
            state.lifecycleChange = "recalculated"
        doneRerun = self.server.changeStateOrRerun(test, state, rerun)
        try:
            self.connection.shutdown(socket.SHUT_RD)
        except socket.error:
            # This only occurs on a mac, and doesn't affect functionality.
            pass
        if state.isComplete():
            self.sendReuseResponse(test, state, tryReuse, doneRerun)
        else:
            QueueSystemServer.instance.setRemoteProcessId(test, pid)


class SlaveServerResponder(plugins.Responder, ThreadingTCPServer):
    # Python's default value of 5 isn't very much...
    # There doesn't seem to be any disadvantage of allowing a longer queue, so we will use the system's maximum size
    request_queue_size = socket.SOMAXCONN

    def __init__(self, optionMap, allApps):
        plugins.Responder.__init__(self)
        ThreadingTCPServer.__init__(self, (getIPAddress(allApps), 0), self.handlerClass())
        self.testMap = {}
        self.testLocks = {}
        self.filePushLock = Lock()
        self.filePushProcesses = {}
        self.diag = logging.getLogger("Slave Server")
        self.terminate = False
        self.totalReruns = 0
        self.maxReruns = max(filter(lambda x: x is not None,
                                    (app.getBatchConfigValue("queue_system_max_reruns") for app in allApps)))

        # If a client rings in and then the connectivity is lost, we don't want to hang waiting for it forever
        # So we enable keepalive that will check the connection if no data is received for a while
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, True)
        # Default is 2 hours here on Linux which is rather a long time to wait for anything to happen.
        # We give up after 5 minutes
        if hasattr(socket, "TCP_KEEPIDLE"):
            self.socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPIDLE, 300)

    def addSuites(self, *args):
        # use this as an opportunity to broadcast our address
        serverAddress = self.getAddress()
        self.diag.info("Starting slave server at " + serverAddress)
        # Tell the submission code where we are
        QueueSystemServer.instance.setSlaveServerAddress(serverAddress)

    def handlerClass(self):
        return SlaveRequestHandler

    def canBeMainThread(self):
        return False  # We wait for sockets and stuff

    def run(self):
        while not self.terminate:
            self.diag.info("Waiting for a new request...")
            try:
                self.handle_request()
            except:
                # e.g. can get interrupted system call here in 'select' if we get a signal
                sys.stderr.write("WARNING: slave server caught exception while processing request!\n")
                plugins.printException()

        self.diag.info("Terminating slave server")

    def notifyAllRead(self, *args):
        if len(self.testMap) == 0:
            self.notifyAllComplete()

    def notifyAllComplete(self):
        self.diag.info("Notified all complete, shutting down soon...")
        self.terminate = True
        sendSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sendSocket.connect(self.socket.getsockname())
        sendSocket.sendall("TERMINATE_SERVER\n".encode(getpreferredencoding()))
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
        if testApp not in self.testMap:
            self.testMap[testApp] = {}
        self.testMap[testApp][testPath] = test
        self.testLocks[test] = RLock()

    def changeState(self, test, state):
        # Several threads could be trying to do this at once...
        lock = self.testLocks.get(test)
        with lock:
            allow = self.allowChange(test.state, state)
            if allow:
                test.changeState(state)
            else:
                self.diag.info("Rejecting state change, old state " + test.state.category +
                               " is complete, new state " + state.category + " is not.")
        return allow

    def changeStateOrRerun(self, test, state, rerun):
        oldBt = test.state.briefText
        self.diag.info("Changed from '" + oldBt + "' to '" + state.briefText + "'")
        if rerun and self.totalReruns < self.maxReruns:
            lock = self.testLocks.get(test)
            with lock:
                self.totalReruns += 1
            self.diag.info("Instructed to rerun test " + test.uniqueName + ", now performed " +
                           str(self.totalReruns) + " reruns of max " + str(self.maxReruns) + ".")
            QueueSystemServer.instance.queueTestForRerun(test)
            return True
        else:
            if rerun:
                self.diag.info("Instructed to rerun test " + test.uniqueName +
                               ", but refusing, already rerun maximum " + str(self.totalReruns) + " times.")
            self.changeState(test, state)
            return False

    def allowChange(self, oldState, newState):
        return newState.isComplete() or not oldState.isComplete()

    def getTest(self, testString):
        self.diag.info("Received request for '" + testString + "'")
        try:
            appName, testPath = socketParse(testString)
            return self.testMap[appName][testPath]
        except ValueError:
            return

    def getFilePushProcess(self, test, userAndHost, path):
        key = userAndHost, path
        with self.filePushLock:
            if key in self.filePushProcesses:
                return self.filePushProcesses[key], False
            else:
                proc = test.app.getRemoteCopyFileProcess(path, "localhost", os.path.dirname(path), userAndHost)
                self.filePushProcesses[key] = proc
                return proc, True

    def pushFiles(self, test, userAndHost, paths):
        for path in paths:
            proc, started = self.getFilePushProcess(test, userAndHost, path)
            if started:
                self.diag.info("Pushing '" + path + "'...")
                proc.wait()
                self.diag.info("Done Pushing '" + path + "'")
                # Aim for synchronising tests properly
                QueueSystemServer.instance.sendServerState("Sychronised " + path + " to " + userAndHost)
            else:
                self.diag.info("Waiting for '" + path + "'...")
                while proc.poll() is None:
                    time.sleep(0.1)
                self.diag.info("Done Waiting for '" + path + "'.")


class MasterTextResponder(TextDisplayResponder):
    def getPrefix(self, test):
        return "S: "  # don't get things in order, so indenting is pointless

    def shouldDescribe(self, test):
        return True  # Write the successful tests also


class MasterInteractiveResponder(InteractiveResponder):
    def getPrefix(self, test):
        return ""  # don't get things in order, so indenting is pointless
