
import sys
import logging
import types
from texttestlib import plugins
from queue import Queue, Empty
from collections import OrderedDict
from threading import Lock

plugins.addCategory("cancelled", "cancelled", "were cancelled before starting")


class Cancelled(plugins.TestState):
    def __init__(self, briefText, freeText):
        plugins.TestState.__init__(self, "cancelled", briefText=briefText, freeText=freeText,
                                   started=1, completed=1, lifecycleChange="complete")

# We're set up for running in a thread but we don't do so by default, for simplicity


class BaseActionRunner(plugins.Responder, plugins.Observable):
    cancelFreeText = "Test run was cancelled before it had started"

    def __init__(self, optionMap, diag):
        plugins.Responder.__init__(self)
        plugins.Observable.__init__(self)
        self.optionMap = optionMap
        self.testQueue = Queue()
        self.exited = False
        self.allComplete = False
        self.lock = Lock()
        self.killSignal = None
        self.diag = diag
        self.lockDiag = logging.getLogger("locks")

    def notifyAdd(self, test, initial):
        if test.classId() == "test-case":
            self.diag.info("Adding test " + test.uniqueName)
            self.addTest(test)

    def addTest(self, test):
        self.testQueue.put(test)

    def notifyAllRead(self, *args):
        self.diag.info("All read, adding terminator")
        self.testQueue.put(None)

    def notifyComplete(self, test):
        if not self.exited and "stop" in self.optionMap and test.state.hasFailed():
            self.exited = True
            self.cancelFreeText = "Test run was cancelled due to previous failure of test " + test.getRelPath()

    def runAllTests(self):
        self.runQueue(self.getTestForRun, self.runTest, "running")
        self.cleanup()
        self.diag.info("Terminating")

    def notifyAllComplete(self):
        self.allComplete = True

    def notifyKill(self, test):
        self.lock.acquire()
        self.killOrCancel(test)
        self.lock.release()

    def notifyKillProcesses(self, sig=None):
        self.diag.info("Got exit!")
        if self.allComplete:
            return
        self.lockDiag.info("Trying to get lock for killing")
        self.lock.acquire()
        self.lockDiag.info("Got lock for killing")
        self.notify("Status", "Killing all running tests ...")
        self.killSignal = sig
        self.exited = True
        self.killTests()
        self.notify("Status", "Killed all running tests.")
        self.lock.release()

    def cancel(self, test, briefText="cancelled", freeText="", **kwargs):
        if not test.state.isComplete():
            if not freeText:
                freeText = self.cancelFreeText
            self.changeState(test, Cancelled(briefText, freeText), **kwargs)

    def changeState(self, test, state):
        test.changeState(state)  # for overriding in case we need other notifiers

    def runQueue(self, getMethod, runMethod, desc, block=True):
        while True:
            test = getMethod(block)
            if not test:  # completed normally
                break

            if self.exited:
                self.cancel(test)
                self.diag.info("Cancelled " + desc + " " + test.uniqueName)
            elif not test.state.isComplete():
                self.diag.info(desc.capitalize() + " test " + test.uniqueName)
                runMethod(test)
                self.diag.info("Completed " + desc + " " + test.uniqueName)

    def getItemFromQueue(self, queue, block, replaceTerminators=False):
        try:
            item = queue.get(block=block)
            if replaceTerminators and item is None:
                if not block:
                    item = self.getItemFromQueue(queue, False, True)
                queue.put(None)
            return item
        except Empty:
            return

    def getTestForRun(self, block=True):
        return self.getItemFromQueue(self.testQueue, block=block)

    def canBeMainThread(self):
        return False  # We block, so we shouldn't be the main thread...


class ActionRunner(BaseActionRunner):
    def __init__(self, optionMap, *args):
        BaseActionRunner.__init__(self, optionMap, logging.getLogger("Action Runner"))
        self.currentTestRunner = None
        self.previousTestRunner = None
        self.appRunners = OrderedDict()

    def addSuite(self, suite):
        plugins.log.info("Using " + suite.app.description(includeCheckout=True))
        appRunner = ApplicationRunner(suite, self.diag)
        self.appRunners[suite.app] = appRunner

    def notifyAllReadAndNotified(self):
        # kicks off processing. Don't use notifyAllRead as we end up running all the tests before
        # everyone's been notified of the reading.
        self.runAllTests()

    def notifyRerun(self, test):
        if self.currentTestRunner and self.currentTestRunner.test is test:
            self.diag.info("Got rerun notification for " + repr(test) + ", resetting actions")
            self.currentTestRunner.resetActionSequence()

    def runTest(self, test):
        # We have the lock coming in to here...
        appRunner = self.appRunners.get(test.app)
        if appRunner:
            self.lock.acquire()
            self.currentTestRunner = TestRunner(test, appRunner, self.diag, self.exited, self.killSignal)
            self.lock.release()

            self.currentTestRunner.performActions(self.previousTestRunner)
            self.previousTestRunner = self.currentTestRunner

            self.lock.acquire()
            self.currentTestRunner = None
            self.notifyComplete(test)
            self.lock.release()

    def killTests(self):
        if self.currentTestRunner:
            self.currentTestRunner.kill(self.killSignal)

    def killOrCancel(self, test):
        if self.currentTestRunner and self.currentTestRunner.test is test:
            self.currentTestRunner.kill()
        else:
            self.cancel(test)

    def getAllActionClasses(self):
        classes = set()
        for appRunner in list(self.appRunners.values()):
            for action in appRunner.actionSequence:
                classes.add(action.__class__)
        return classes

    def cleanup(self):
        for actionClass in self.getAllActionClasses():
            actionClass.finalise()
        for appRunner in list(self.appRunners.values()):
            appRunner.cleanActions()


class ActionsCompleteAction(plugins.Action):
    def __call__(self, test):
        test.actionsCompleted()

    def setUpSuite(self, suite):
        # Only occasionally needed, e.g. in ReplaceText script
        if suite.state.hasStarted():
            suite.actionsCompleted()

    def callDuringAbandon(self, *args):
        return True


class ApplicationRunner:
    def __init__(self, testSuite, diag):
        self.testSuite = testSuite
        self.suitesSetUp = {}
        self.suitesToSetUp = {}
        self.diag = diag
        self.actionSequence = self.getActionSequence()
        self.setUpApplications()

    def cleanActions(self):
        # clean up the actions before we exit
        self.suitesToSetUp = {}
        self.suitesSetUp = {}
        self.actionSequence = []

    def setUpApplications(self):
        for action in self.actionSequence:
            self.setUpApplicationFor(action)

    def setUpApplicationFor(self, action):
        self.diag.info("Performing " + str(action) + " set up on " + repr(self.testSuite.app))
        try:
            action.setUpApplication(self.testSuite.app)
        except Exception:
            sys.stderr.write("Exception thrown performing " + str(action) +
                             " set up on " + repr(self.testSuite.app) + " :\n")
            plugins.printException()

    def markForSetUp(self, suite):
        newActions = []
        for action in self.actionSequence:
            newActions.append(action)
        self.suitesToSetUp[suite] = newActions

    def setUpSuites(self, action, test):
        if test.parent:
            self.setUpSuites(action, test.parent)
        if test.classId() == "test-suite":
            if action in self.suitesToSetUp[test]:
                self.setUpSuite(action, test)
                self.suitesToSetUp[test].remove(action)

    def setUpSuite(self, action, suite):
        self.diag.info(str(action) + " set up " + repr(suite))
        action.setUpSuite(suite)
        if suite in self.suitesSetUp:
            self.suitesSetUp[suite].append(action)
        else:
            self.suitesSetUp[suite] = [action]

    def tearDownSuite(self, suite):
        self.diag.info("Try tear down " + repr(suite))
        actionsToTearDown = self.suitesSetUp.get(suite, [])
        for action in actionsToTearDown:
            self.diag.info(str(action) + " tear down " + repr(suite))
            action.tearDownSuite(suite)
        self.suitesSetUp[suite] = []

    def getActionSequence(self):
        actionSequenceFromConfig = self.testSuite.app.getActionSequence()
        actionSequence = []
        # Collapse lists and remove None actions
        for action in actionSequenceFromConfig:
            self.addActionToList(action, actionSequence)

        self.addActionToList(ActionsCompleteAction(), actionSequence)
        return actionSequence

    def addActionToList(self, action, actionSequence):
        if type(action) == list:
            for subAction in action:
                self.addActionToList(subAction, actionSequence)
        elif action != None:
            actionSequence.append(action)


class TestRunner:
    def __init__(self, test, appRunner, diag, killed, killSignal):
        self.test = test
        self.diag = diag
        self.actionSequence = []
        self.appRunner = appRunner
        self.killed = killed
        self.killSignal = killSignal
        self.currentAction = None
        self.lock = Lock()
        self.resetActionSequence()

    def resetActionSequence(self):
        self.setActionSequence(self.appRunner.actionSequence)

    def setActionSequence(self, actionSequence):
        self.actionSequence = []
        # Copy the action sequence, so we can edit it and mark progress
        for action in actionSequence:
            self.actionSequence.append(action)

    def handleExceptions(self, method, *args):
        try:
            method(*args)
            return True
        except plugins.TextTestError as e:
            self.failTest(str(e))
        except:
            exceptionText = plugins.getExceptionString()
            plugins.printWarning("Caught exception while running " + repr(self.test) +
                                 " changing state to UNRUNNABLE :\n" + exceptionText.rstrip(), stdout=True)
            self.failTest(exceptionText)
        return False

    def failTest(self, excString):
        execHosts = self.test.state.executionHosts
        failState = plugins.Unrunnable(freeText=excString, briefText="TEXTTEST EXCEPTION", executionHosts=execHosts)
        self.test.changeState(failState)

    def performActions(self, previousTestRunner):
        tearDownSuites, setUpSuites = self.findSuitesToChange(previousTestRunner)
        for suite in tearDownSuites:
            self.handleExceptions(previousTestRunner.appRunner.tearDownSuite, suite)
        for suite in setUpSuites:
            self.appRunner.markForSetUp(suite)
        abandon = self.test.state.shouldAbandon()
        while len(self.actionSequence):
            action = self.actionSequence.pop(0)
            if abandon and not action.callDuringAbandon(self.test):
                continue
            self.diag.info("->Performing action " + str(action) + " on " + repr(self.test))
            if self.handleExceptions(self.appRunner.setUpSuites, action, self.test):
                self.callAction(action)
            self.diag.info("<-End Performing action " + str(action))
            if not abandon and self.test.state.shouldAbandon():
                self.diag.info("Abandoning test...")
                abandon = True

    def kill(self, sig=None):
        self.diag.info("Killing test " + repr(self.test))
        self.lock.acquire()
        self.killed = True
        self.killSignal = sig
        if self.currentAction:
            self.currentAction.kill(self.test, sig)
        self.lock.release()

    def callAction(self, action):
        self.lock.acquire()
        self.currentAction = action
        if self.killed:
            action.kill(self.test, self.killSignal)
        self.lock.release()

        self.handleExceptions(action, self.test)

        self.lock.acquire()
        self.currentAction = None
        self.lock.release()

    def findSuitesToChange(self, previousTestRunner):
        tearDownSuites = []
        commonAncestor = None
        if previousTestRunner:
            commonAncestor = self.test.findCommonAncestor(previousTestRunner.test)
            self.diag.info("Common ancestor : " + repr(commonAncestor))
            tearDownSuites = previousTestRunner.findSuitesUpTo(commonAncestor)
        setUpSuites = self.findSuitesUpTo(commonAncestor)
        # We want to set up the earlier ones first
        setUpSuites.reverse()
        return tearDownSuites, setUpSuites

    def findSuitesUpTo(self, ancestor):
        suites = []
        currCheck = self.test.parent
        while currCheck != ancestor:
            suites.append(currCheck)
            currCheck = currCheck.parent
        return suites
