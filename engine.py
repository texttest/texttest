#!/usr/bin/env python

import plugins, os, sys, testmodel, time, signal
from threading import Thread
from usecase import ScriptEngine
from ndict import seqdict

plugins.addCategory("unrunnable", "unrunnable", "could not be run")

class TestRunner:
    def __init__(self, test, appRunner, diag):
        self.test = test
        self.diag = diag
        self.interrupted = 0
        self.actionSequence = []
        self.appRunner = appRunner
        self.setActionSequence(appRunner.actionSequence)
    def switchToCleanup(self):
        self.interrupted = 0
        newActionSequence = []
        for action in self.actionSequence:
            newActionSequence += self.appRunner.cleanUpActions[action]
        self.actionSequence = newActionSequence
    def setActionSequence(self, actionSequence):
        self.actionSequence = []
        # Copy the action sequence, so we can edit it and mark progress
        for action in actionSequence:
            self.actionSequence.append(action)
    def interrupt(self):
        self.interrupted = 1
    def handleExceptions(self, method, *args):
        try:
            return method(*args)
        except plugins.TextTestError, e:
            self.failTest(str(sys.exc_value))
        except KeyboardInterrupt:
            raise
        except:
            print "WARNING : caught exception while running", self.test, "changing state to UNRUNNABLE :"
            exceptionText = plugins.printException()
            self.failTest(exceptionText)
    def failTest(self, excString):
        execHosts = self.test.state.executionHosts
        failState = plugins.TestState("unrunnable", briefText="UNRUNNABLE", freeText=excString, \
                                      executionHosts=execHosts, completed=1)
        self.test.changeState(failState)
    def performActions(self, previousTestRunner, runToCompletion):
        tearDownSuites, setUpSuites = self.findSuitesToChange(previousTestRunner)
        for suite in tearDownSuites:
            self.handleExceptions(previousTestRunner.appRunner.tearDownSuite, suite)
        for suite in setUpSuites:
            suite.setUpEnvironment()
            self.appRunner.markForSetUp(suite)
        while len(self.actionSequence):
            action = self.actionSequence[0]
            self.diag.info("->Performing action " + str(action) + " on " + repr(self.test))
            self.handleExceptions(self.appRunner.setUpSuites, action, self.test)
            completed, tryOthersNow = self.performAction(action, runToCompletion)
            self.diag.info("<-End Performing action " + str(action) + self.returnString(completed, tryOthersNow))
            if completed:
                if self.test.state.shouldAbandon():
                    self.diag.info("Abandoning test...")
                    self.actionSequence = []
                    break
                else:
                    self.actionSequence.pop(0)
            if tryOthersNow:
                return 0
        self.test.notifyCompleted()
        return 1
    def returnString(self, completed, tryOthersNow):
        retString = " - "
        if completed:
            retString += "COMPLETE"
        else:
            retString += "RETRY"
        if tryOthersNow:
            retString += ", CHANGE TEST"
        else:
            retString += ", CONTINUE"
        return retString
    def performAction(self, action, runToCompletion):
        while 1:
            if self.interrupted:
                raise KeyboardInterrupt, "Interrupted externally"
            retValue = self.callAction(action)
            if not retValue:
                # No return value: we've finished and should proceed
                return 1, 0

            completed = not retValue & plugins.Action.RETRY
            tryOthers = retValue & plugins.Action.WAIT and not runToCompletion
            # Don't busy-wait : assume lack of completion is a sign we might keep doing this
            if not completed:
                time.sleep(0.1)
            if completed or tryOthers:
                # Don't attempt to retry the action, mark complete
                return completed, tryOthers 
    def callAction(self, action):
        self.test.setUpEnvironment()
        retValue = self.handleExceptions(self.test.callAction, action)
        self.test.tearDownEnvironment()
        return retValue
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

class ApplicationRunner:
    def __init__(self, testSuite, script, diag):
        self.testSuite = testSuite
        self.suitesSetUp = {}
        self.suitesToSetUp = {}
        self.diag = diag
        self.cleanUpActions = {}
        self.actionSequence = self.getActionSequence(script)
        self.setUpApplications(self.actionSequence)
    def switchToCleanup(self, fetchResults):
        newActionSequence = []
        for action in self.actionSequence:
            cleanUpActions = action.getInterruptActions(fetchResults)
            self.cleanUpActions[action] = cleanUpActions
            newActionSequence += cleanUpActions
        self.actionSequence = newActionSequence
    def setUpApplications(self, sequence):
        self.testSuite.setUpEnvironment()
        for action in sequence:
            self.diag.info("Performing " + str(action) + " set up on " + repr(self.testSuite.app))
            try:
                action.setUpApplication(self.testSuite.app)
            except KeyboardInterrupt:
                raise
            except:
                self.handleFailedSetup()
        self.testSuite.tearDownEnvironment()
    def handleFailedSetup(self):
        message = str(sys.exc_value)
        if sys.exc_type != plugins.TextTestError:
            plugins.printException()
            message = str(sys.exc_type) + ": " + message
        for test in self.testSuite.testCaseList():
            test.changeState(plugins.TestState("unrunnable", briefText="Set-up Failed", freeText=message, completed=1))
        raise testmodel.BadConfigError, message
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
        for action in self.suitesSetUp[suite]:
            self.diag.info(str(action) + " tear down " + repr(suite))
            action.tearDownSuite(suite)
        suite.tearDownEnvironment()
        self.suitesSetUp[suite] = []
    def getActionSequence(self, script):
        if not script:
            return self.testSuite.app.getActionSequence()
            
        actionCom = script.split(" ")[0]
        actionArgs = script.split(" ")[1:]
        actionOption = actionCom.split(".")
        if len(actionOption) != 2:
            return self.getNonPython(script)
                
        module, pclass = actionOption
        importCommand = "from " + module + " import " + pclass + " as _pclass"
        try:
            exec importCommand
        except:
            if os.path.isfile(script):
                return self.getNonPython(script)
            else:
                sys.stderr.write("Import failed, looked at " + repr(sys.path) + "\n")
                plugins.printException()
                raise testmodel.BadConfigError, "Could not import script " + pclass + " from module " + module

        # Assume if we succeed in importing then a python module is intended.
        try:
            if len(actionArgs) > 0:
                return [ _pclass(actionArgs) ]
            else:
                return [ _pclass() ]
        except:
            plugins.printException()
            raise testmodel.BadConfigError, "Could not instantiate script action " + repr(actionCom) +\
                  " with arguments " + repr(actionArgs) 
    def getNonPython(self, script):
        return [ plugins.NonPythonAction(script) ]

class ActionRunner:
    def __init__(self):
        self.interrupted = 0
        self.previousTestRunner = None
        self.currentTestRunner = None
        self.allTests = []
        self.testQueue = []
        self.appRunners = []
        self.diag = plugins.getDiagnostics("Action Runner")
    def addTestActions(self, testSuite, script):
        self.diag.info("Processing test suite of size " + str(testSuite.size()) + " for app " + testSuite.app.name)
        appRunner = ApplicationRunner(testSuite, script, self.diag)
        self.appRunners.append(appRunner)
        for test in testSuite.testCaseList():
            self.diag.info("Adding test runner for test " + test.getRelPath())
            testRunner = TestRunner(test, appRunner, self.diag)
            self.testQueue.append(testRunner)
            self.allTests.append(testRunner)
    def isEmpty(self):
        return len(self.appRunners) == 0
    def switchToCleanup(self, fetchResults):
        for appRunner in self.appRunners:
            appRunner.switchToCleanup(fetchResults)
        for testRunner in self.testQueue:
            self.diag.info("Running cleanup actions for test " + testRunner.test.getRelPath())
            testRunner.switchToCleanup()
        self.interrupted = 0
    def run(self):
        try:
            self.runNormal()
            self.diag.info("Finishing - notifying all completed")
            for responder in testmodel.Test.observers:
                responder.notifyAllComplete()
        except KeyboardInterrupt, e:
            excData = str(e)
            self.writeTermMessage(excData)
            fetchResults = excData.find("LIMIT") != -1
            self.switchToCleanup(fetchResults)
            for responder in testmodel.Test.observers:
                responder.notifyInterrupt(fetchResults)
            self.run()
    def writeTermMessage(self, excData):
        message = "Terminating testing due to external interruption"
        if excData:
            message += " (" + excData + ")"
        print message
        sys.stdout.flush() # Try not to lose log file information...
    def runNormal(self):
        while len(self.testQueue):
            if self.interrupted:
                raise KeyboardInterrupt, "Interrupted externally"
            self.currentTestRunner = self.testQueue[0]
            self.diag.info("Running actions for test " + self.currentTestRunner.test.getRelPath())
            runToCompletion = len(self.testQueue) == 1
            completed = self.currentTestRunner.performActions(self.previousTestRunner, runToCompletion)
            self.testQueue.pop(0)
            if not completed:
                self.diag.info("Incomplete - putting to back of queue")
                self.testQueue.append(self.currentTestRunner)
            self.previousTestRunner = self.currentTestRunner
    def interrupt(self):
        self.interrupted = 1
        if self.currentTestRunner:
            self.currentTestRunner.interrupt()

# Class to allocate unique names to tests for script identification and cross process communication
class UniqueNameFinder:
    def __init__(self):
        self.name2test = {}
        self.diag = plugins.getDiagnostics("Unique Names")
    def addSuite(self, test):
        self.store(test)
        try:
            for subtest in test.testcases:
                self.addSuite(subtest)
        except AttributeError:
            pass
    def store(self, test):
        if self.name2test.has_key(test.name):
            oldTest = self.name2test[test.name]
            self.storeUnique(oldTest, test)
        else:
            self.name2test[test.name] = test
    def findParentIdentifiers(self, oldTest, newTest):
        oldParentId = " at top level"
        if oldTest.parent:
            oldParentId = " under " + oldTest.parent.name
        newParentId = " at top level"
        if newTest.parent:
            newParentId = " under " + newTest.parent.name
        if oldTest.parent and newTest.parent and oldParentId == newParentId:
            oldNextLevel, newNextLevel = self.findParentIdentifiers(oldTest.parent, newTest.parent)
            oldParentId += oldNextLevel
            newParentId += newNextLevel
        return oldParentId, newParentId
    def storeUnique(self, oldTest, newTest):
        oldParentId, newParentId = self.findParentIdentifiers(oldTest, newTest)
        if oldParentId != newParentId:
            self.storeBothWays(oldTest.name + oldParentId, oldTest)
            self.storeBothWays(newTest.name + newParentId, newTest)
        elif oldTest.app.name != newTest.app.name:
            self.storeBothWays(oldTest.name + " for " + oldTest.app.fullName, oldTest)
            self.storeBothWays(newTest.name + " for " + newTest.app.fullName, newTest)
        elif oldTest.app.getFullVersion() != newTest.app.getFullVersion():
            self.storeBothWays(oldTest.name + " version " + oldTest.app.getFullVersion(), oldTest)
            self.storeBothWays(newTest.name + " version " + newTest.app.getFullVersion(), newTest)
        else:
            raise plugins.TextTestError, "Could not find unique name for tests with name " + oldTest.name
    def storeBothWays(self, name, test):
        self.diag.info("Setting unique name for test " + test.name + " to " + name)
        self.name2test[name] = test
        test.uniqueName = name

class TextTest:
    def __init__(self):
        self.setSignalHandlers()
        if os.environ.has_key("FAKE_OS"):
            os.name = os.environ["FAKE_OS"]
        self.allResponders = []
        self.inputOptions = testmodel.OptionFinder()
        self.diag = plugins.getDiagnostics("Find Applications")
        self.allApps = self.findApps()
        # Set USECASE_HOME for the use-case recorders we expect people to use for their tests...
        if not os.environ.has_key("USECASE_HOME"):
            os.environ["USECASE_HOME"] = os.path.join(self.inputOptions.directoryName, "usecases")
    def findSearchDirs(self):
        root = self.inputOptions.directoryName
        self.diag.info("Using test suite at " + root)
        fullPaths = map(lambda name: os.path.join(root, name), os.listdir(root))
        return [ self.inputOptions.directoryName ] + filter(os.path.isdir, fullPaths)
    def findApps(self):
        root = self.inputOptions.directoryName
        if not os.path.isdir(root):
            sys.stderr.write("Test suite root directory does not exist: " + root + "\n")
            return []
        appList = []
        raisedError = False
        for dir in self.findSearchDirs():
            subRaisedError, apps = self.findAppsUnder(dir)
            appList += apps
            raisedError |= subRaisedError
        appList.sort(self.compareApps)
        self.diag.info("Found applications : " + repr(appList))
        if len(appList) == 0 and not raisedError:
            print "Could not find any matching applications (files of the form config.<app>) under", root
        return appList
    def compareApps(self, app1, app2):
        return cmp(app1.name, app2.name)
    def findAppsUnder(self, dirName):
        appList = []
        raisedError = False
        selectedAppDict = self.inputOptions.findSelectedAppNames()
        self.diag.info("Selecting apps in " + dirName + " according to dictionary :" + repr(selectedAppDict))
        dircache = testmodel.DirectoryCache(dirName)
        for f in dircache.findAllFiles("config"):
            components = os.path.basename(f).split('.')
            if len(components) != 2:
                continue
            appName = components[1]
            if len(selectedAppDict) and not selectedAppDict.has_key(appName):
                continue

            self.diag.info("Building apps from " + f)
            versionList = self.inputOptions.findVersionList()
            if selectedAppDict.has_key(appName):
                versionList = selectedAppDict[appName]
            try:
                for version in versionList:
                    appList += self.addApplications(appName, dircache, version)
            except testmodel.BadConfigError:
                sys.stderr.write("Could not use application " + appName +  " - " + str(sys.exc_value) + "\n")
                raisedError = True
        return raisedError, appList
    def createApplication(self, appName, dircache, version):
        return testmodel.Application(appName, dircache, version, self.inputOptions)
    def addApplications(self, appName, dircache, version):
        appList = []
        app = self.createApplication(appName, dircache, version)
        appList.append(app)
        for extraVersion in app.getExtraVersions():
            aggVersion = extraVersion
            if len(version) > 0:
                aggVersion = version + "." + extraVersion
            extraApp = self.createApplication(appName, dircache, aggVersion)
            app.extras.append(extraApp)
            appList.append(extraApp)
        return appList
    def needsTestRuns(self):
        for responder in self.allResponders:
            if not responder.needsTestRuns():
                return False
        return True
    def createResponders(self):
        # With scripts, we ignore all responder options, we're just transforming data
        if self.inputOptions.runScript():
            return
        responderClasses = []
        for app in self.allApps:
            for respClass in app.configObject.getResponderClasses(self.allApps):
                if not respClass in responderClasses:
                    self.diag.info("Adding responder " + repr(respClass))
                    responderClasses.append(respClass)
        # Make sure we send application events when tests change state
        responderClasses.append(testmodel.ApplicationEventResponder)
        self.allResponders = map(lambda x : x(self.inputOptions), responderClasses)
        testmodel.Test.observers = self.allResponders
    def createTestSuites(self):
        uniqueNameFinder = UniqueNameFinder()
        appSuites = seqdict()
        forTestRuns = self.needsTestRuns()
        for app in self.allApps:
            valid = False
            try:
                valid, testSuite = app.createTestSuite(forTestRuns=forTestRuns)
            except testmodel.BadConfigError:
                print "Error creating test suite for application", app, "-", sys.exc_value
            if not valid:
                continue
            
            appSuites[app] = testSuite
            uniqueNameFinder.addSuite(testSuite)
        return appSuites
    def deleteTempFiles(self, appSuites):
        for app, testSuite in appSuites.items():
            if app.cleanMode & plugins.Configuration.CLEAN_SELF:
                app.removeWriteDirectory()
    def setUpResponders(self, appSuites):
        for responder in self.allResponders:
            for app, testSuite in appSuites.items():
                responder.addSuite(testSuite)
    def createActionRunner(self, appSuites):
        actionRunner = ActionRunner()
        script = self.inputOptions.runScript()
        if not script:
            self.checkForNoTests(appSuites)
        for app, testSuite in appSuites.items():
            if not script and testSuite.size() == 0:
                continue
            print "Using", app.description() + ", checkout", app.checkout
            try:
                actionRunner.addTestActions(testSuite, script)
            except testmodel.BadConfigError:
                sys.stderr.write("Error in set-up of application " + repr(app) + " - " + str(sys.exc_value) + "\n")
        return actionRunner
    def run(self):
        if self.inputOptions.helpMode():
            if len(self.allApps) > 0:
                self.allApps[0].printHelpText()
            else:
                print testmodel.helpIntro
                print "TextTest didn't find any valid test applications - you probably need to tell it where to find them."
                print "The most common way to do this is to set the environment variable TEXTTEST_HOME."
                print "If this makes no sense, read the online documentation..."
            return
        self._run()
    def findOwnThreadResponder(self):
        for responder in self.allResponders:
            if responder.needsOwnThread():
                return responder
    def _run(self):
        self.createResponders()
        appSuites = self.createTestSuites()
        try:
            self.runAppSuites(appSuites)
        finally:
            self.deleteTempFiles(appSuites)
    def runAppSuites(self, appSuites):
        # pick out any responder that is designed to hang around executing
        # some sort of loop in its own thread... generally GUIs of some sort
        ownThreadResponder = self.findOwnThreadResponder()
        if not ownThreadResponder or ownThreadResponder.needsTestRuns():
            self.runWithTests(ownThreadResponder, appSuites)
        else:
            self.runAlone(ownThreadResponder, appSuites)
    def runAlone(self, ownThreadResponder, appSuites):
        self.setUpResponders(appSuites)
        ownThreadResponder.runAlone()
    def runWithTests(self, ownThreadResponder, appSuites):                
        actionRunner = self.createActionRunner(appSuites)
        if actionRunner.isEmpty():
            return # error already printed

        # Wait until now to do this, in case problems encountered so far...
        self.setUpResponders(appSuites)
        if ownThreadResponder:
            actionThread = ActionThread(actionRunner)
            actionThread.start()
            ownThreadResponder.runWithActionThread(actionThread)
        else:
            actionRunner.run()
    def checkForNoTests(self, appSuites):
        extraVersions = []
        for app, testSuite in appSuites.items():
            if app in extraVersions:
                continue
            extraVersions += app.extras
            self.checkNoTestsInApp(app, appSuites)
    def checkNoTestsInApp(self, app, appSuites):
        appsToCheck = [ app ] + app.extras
        for checkApp in appsToCheck:
            if appSuites[checkApp].size() > 0:
                return
        sys.stderr.write("No tests matching the selection criteria found for " + app.description() + "\n")
    def setSignalHandlers(self):
        # Signals used on UNIX to signify running out of CPU time, wallclock time etc.
        if os.name == "posix":
            signal.signal(signal.SIGUSR1, self.handleSignal)
            signal.signal(signal.SIGUSR2, self.handleSignal)
            signal.signal(signal.SIGXCPU, self.handleSignal)
    def handleSignal(self, sig, stackFrame):
        # Don't respond to the same signal more than once!
        signal.signal(sig, signal.SIG_IGN)
        raise KeyboardInterrupt, self.getSignalText(sig)
    def getSignalText(self, sig):
        if sig == signal.SIGUSR1:
            return "RUNLIMIT1"
        elif sig == signal.SIGXCPU:
            return "CPULIMIT"
        elif sig == signal.SIGUSR2:
            return "RUNLIMIT2"
        else:
            return "signal " + str(sig)

class ActionThread(Thread):
    def __init__(self, actionRunner):
        Thread.__init__(self)
        self.actionRunner = actionRunner
    def run(self):
        try:
            self.actionRunner.run()
        except KeyboardInterrupt:
            print "Terminated before tests complete: cleaning up..." 
    def terminate(self):
        self.actionRunner.interrupt()
        self.join()
