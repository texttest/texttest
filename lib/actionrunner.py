
import plugins, os, sys, time
from respond import Responder
from Queue import Queue, Empty
from ndict import seqdict
from threading import Lock

plugins.addCategory("cancelled", "cancelled", "were cancelled before starting")

class Cancelled(plugins.TestState):
    def __init__(self, briefText, freeText):
        plugins.TestState.__init__(self, "cancelled", briefText=briefText, freeText=freeText, \
                                   started=1, completed=1, lifecycleChange="complete")

class BaseActionRunner(Responder, plugins.Observable):
    def __init__(self, optionMap, diag):
        Responder.__init__(self)
        plugins.Observable.__init__(self)
        self.optionMap = optionMap
        self.testQueue = Queue()
        self.exited = False
        self.allComplete = False
        self.lock = Lock()
        self.killSignal = None
        self.diag = diag
        self.lockDiag = plugins.getDiagnostics("locks")
    def notifyAdd(self, test, initial):
        if test.classId() == "test-case":
            self.diag.info("Adding test " + repr(test))
            self.addTest(test)
    def addTest(self, test):
        self.testQueue.put(test)
    def notifyAllRead(self, suites):
        self.diag.info("All read, adding terminator")
        self.testQueue.put(None)    
    def run(self):
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
        
    def cancel(self, test, briefText="cancelled", freeText="Test run was cancelled before it had started", **kwargs):
        if not test.state.isComplete():
            self.changeState(test, Cancelled(briefText, freeText), **kwargs)
    def changeState(self, test, state):
        test.changeState(state) # for overriding in case we need other notifiers
    def runQueue(self, getMethod, runMethod, desc):
        while True:
            test = getMethod()
            if not test: # completed normally
                break

            if self.exited:
                self.cancel(test)
                self.diag.info("Cancelled " + desc + " " + repr(test))
            elif not test.state.isComplete():
                self.diag.info(desc.capitalize() + " test " + repr(test))
                runMethod(test)
                self.diag.info("Completed " + desc + " " + repr(test))
    def getItemFromQueue(self, queue, block):
        try:
            item = queue.get(block=block)
            if item is None:
                item = self.getItemFromQueue(queue, False) # In case more stuff comes after the terminator
                queue.put(None) # Put the terminator back, we'll probably need it again
            return item
        except Empty:
            return

    def getTestForRun(self):
        return self.getItemFromQueue(self.testQueue, block=True)
    def cleanup(self):
        pass
    def canBeMainThread(self):
        return False # We block, so we shouldn't be the main thread...
            
class ActionRunner(BaseActionRunner):
    def __init__(self, optionMap, allApps):
        BaseActionRunner.__init__(self, optionMap, plugins.getDiagnostics("Action Runner"))
        self.currentTestRunner = None
        self.previousTestRunner = None
        self.script = optionMap.runScript()
        self.appRunners = seqdict()
    def addSuite(self, suite):
        print "Using", suite.app.description(includeCheckout=True)
        appRunner = ApplicationRunner(suite, self.script, self.diag)
        self.appRunners[suite.app] = appRunner
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
            self.lock.release()
    def killTests(self):
        if self.currentTestRunner:
            self.currentTestRunner.kill(self.killSignal)
    def killOrCancel(self, test):
        if self.currentTestRunner and self.currentTestRunner.test is test:
            self.currentTestRunner.kill()
        else:
            self.cancel(test)
    def cleanup(self):
        for appRunner in self.appRunners.values():
            appRunner.cleanActions()
    
class ApplicationRunner:
    def __init__(self, testSuite, script, diag):
        self.testSuite = testSuite
        self.suitesSetUp = {}
        self.suitesToSetUp = {}
        self.diag = diag
        self.actionSequence = self.getActionSequence(script)
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
        except:
            sys.stderr.write("Exception thrown performing " + str(action) + " set up on " + repr(self.testSuite.app) + " :\n")
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
        if self.suitesSetUp.has_key(suite):
            self.suitesSetUp[suite].append(action)
        else:
            self.suitesSetUp[suite] = [ action ]
    def tearDownSuite(self, suite):
        self.diag.info("Try tear down " + repr(suite))
        actionsToTearDown = self.suitesSetUp.get(suite, [])
        for action in actionsToTearDown:
            self.diag.info(str(action) + " tear down " + repr(suite))
            action.tearDownSuite(suite)
        self.suitesSetUp[suite] = []
    
    def getActionSequence(self, script):
        if not script:
            return self.testSuite.app.getActionSequence()
            
        actionCom = script.split(" ")[0]
        actionArgs = script.split(" ")[1:]
        actionOption = actionCom.split(".")
        if len(actionOption) != 2:
            sys.stderr.write("Plugin scripts must be of the form <module_name>.<script>\n")
            return []

                
        module, pclass = actionOption
        importCommand = "from " + module + " import " + pclass + " as _pclass"
        try:
            exec importCommand
        except:
            sys.stderr.write("Could not import script " + pclass + " from module " + module + "\n" +\
                             "Import failed, looked at " + repr(sys.path) + "\n")
            plugins.printException()
            return []

        # Assume if we succeed in importing then a python module is intended.
        try:
            if len(actionArgs) > 0:
                return [ _pclass(actionArgs) ]
            else:
                return [ _pclass() ]
        except:
            sys.stderr.write("Could not instantiate script action " + repr(actionCom) +\
                             " with arguments " + repr(actionArgs) + "\n")
            plugins.printException()
            return []

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
        self.setActionSequence(appRunner.actionSequence)
    def setActionSequence(self, actionSequence):
        self.actionSequence = []
        # Copy the action sequence, so we can edit it and mark progress
        for action in actionSequence:
            self.actionSequence.append(action)
    def handleExceptions(self, method, *args):
        try:
            return method(*args)
        except plugins.TextTestError, e:
            self.failTest(str(e))
        except:
            plugins.printWarning("Caught exception while running " + repr(self.test) + " changing state to UNRUNNABLE :")
            exceptionText = plugins.printException()
            self.failTest(exceptionText)
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
            action = self.actionSequence[0]
            if abandon and not action.callDuringAbandon(self.test):
                self.actionSequence.pop(0)
                continue
            self.diag.info("->Performing action " + str(action) + " on " + repr(self.test))
            self.handleExceptions(self.appRunner.setUpSuites, action, self.test)
            self.callAction(action)
            self.diag.info("<-End Performing action " + str(action))
            self.actionSequence.pop(0)
            if not abandon and self.test.state.shouldAbandon():
                self.diag.info("Abandoning test...")
                abandon = True

        self.test.actionsCompleted()
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

        self.handleExceptions(self.test.callAction, action)

        self.lock.acquire()
        self.currentAction = None
        self.lock.release()
        
    def findSuitesToChange(self, previousTestRunner):
        tearDownSuites = []
        commonAncestor = None
        if previousTestRunner:
            commonAncestor = self.findCommonAncestor(self.test, previousTestRunner.test)
            self.diag.info("Common ancestor : " + repr(commonAncestor))
            tearDownSuites = previousTestRunner.findSuitesUpTo(commonAncestor)
        setUpSuites = self.findSuitesUpTo(commonAncestor)
        # We want to set up the earlier ones first
        setUpSuites.reverse()
        return tearDownSuites, setUpSuites
    def findCommonAncestor(self, test1, test2):
        if self.hasAncestor(test1, test2):
            self.diag.info(test1.getRelPath() + " has ancestor " + test2.getRelPath())
            return test2
        if self.hasAncestor(test2, test1):
            self.diag.info(test2.getRelPath() + " has ancestor " + test1.getRelPath())
            return test1
        if test1.parent:
            return self.findCommonAncestor(test1.parent, test2)
        else:
            self.diag.info(test1.getRelPath() + " unrelated to " + test2.getRelPath())
            return None
    def hasAncestor(self, test1, test2):
        if test1 == test2:
            return 1
        if test1.parent:
            return self.hasAncestor(test1.parent, test2)
        else:
            return 0
    def findSuitesUpTo(self, ancestor):
        suites = []
        currCheck = self.test.parent
        while currCheck != ancestor:
            suites.append(currCheck)
            currCheck = currCheck.parent
        return suites

