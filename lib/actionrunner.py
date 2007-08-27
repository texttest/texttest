
import plugins, os, sys, time
from respond import Responder
from testmodel import Application, DirectoryCache
from glob import glob

class ActionRunner(Responder):
    def __init__(self, optionMap):
        Responder.__init__(self, optionMap)
        self.inputOptions = optionMap
        self.previousTestRunner = None
        self.currentTestRunner = None
        self.script = optionMap.runScript()
        self.allTests = []
        self.testQueue = []
        self.appRunners = []
        self.diag = plugins.getDiagnostics("Action Runner")
    def addSuites(self, suites):
        for suite in suites:
            self.addTestActions(suite)
    def addTestActions(self, suite):
        print "Using", suite.app.description(includeCheckout=True)
        self.diag.info("Processing test suite of size " + str(suite.size()) + " for app " + suite.app.name)
        appRunner = ApplicationRunner(suite, self.script, self.diag)
        self.appRunners.append(appRunner)
        for test in suite.testCaseList():
            self.addTestRunner(test, appRunner)
    def addTestRunner(self, test, appRunner):
        self.diag.info("Adding test runner for test " + test.getRelPath())
        testRunner = TestRunner(test, appRunner, self.diag)
        self.testQueue.append(testRunner)
        self.allTests.append(testRunner)
    def notifyExtraTest(self, testPath, appName, versions):
        appRunner = self.findApplicationRunner(appName, versions)
        if appRunner:
            extraTest = appRunner.addExtraTest(testPath)
            if extraTest:
                self.addTestRunner(extraTest, appRunner)
        else:
            newApp = Application(appName, self.makeDirectoryCache(appName), versions, self.inputOptions)
            self.createTestSuite(newApp, testPath)
    def makeDirectoryCache(self, appName):
        configFile = "config." + appName
        rootDir = self.inputOptions.directoryName
        rootConfig = os.path.join(rootDir, configFile)
        if os.path.isfile(rootConfig):
            return DirectoryCache(rootDir)
        else:
            allFiles = glob(os.path.join(rootDir, "*", configFile))
            return DirectoryCache(os.path.dirname(allFiles[0]))
    def createTestSuite(self, app, testPath):
        filter = plugins.TestPathFilter(testPath)
        responders = self.appRunners[0].testSuite.observers
        suite = app.createTestSuite(responders, [ filter ])
        for responder in responders:
            responder.addSuites([ suite ]) # This will recursively notify ourselves(!) along with everyone else
       
    def findApplicationRunner(self, appName, versions):
        for appRunner in self.appRunners:
            if appRunner.matches(appName, versions):
                return appRunner
    def run(self):
        while len(self.testQueue):
            self.currentTestRunner = self.testQueue[0]
            self.diag.info("Running actions for test " + self.currentTestRunner.test.getRelPath())
            self.currentTestRunner.performActions(self.previousTestRunner)
            self.testQueue.pop(0)
            self.previousTestRunner = self.currentTestRunner
        self.diag.info("Finishing the action runner.")
        
class ApplicationRunner:
    def __init__(self, testSuite, script, diag):
        self.testSuite = testSuite
        self.suitesSetUp = {}
        self.suitesToSetUp = {}
        self.diag = diag
        self.actionSequence = self.getActionSequence(script)
        self.setUpApplications(self.actionSequence)
    def matches(self, appName, versions):
        app = self.testSuite.app
        return app.name == appName and app.versions == versions
    def addExtraTest(self, testPath):
        return self.testSuite.addTestCaseWithPath(testPath)
    def setUpApplications(self, sequence):
        for action in sequence:
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
    def __init__(self, test, appRunner, diag):
        self.test = test
        self.diag = diag
        self.actionSequence = []
        self.appRunner = appRunner
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
        failState = plugins.Unrunnable(freeText=excString, executionHosts=execHosts)
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
            self.performAction(action)
            self.diag.info("<-End Performing action " + str(action))
            self.actionSequence.pop(0)
            if not abandon and self.test.state.shouldAbandon():
                self.diag.info("Abandoning test...")
                abandon = True

        self.test.actionsCompleted()

    def performAction(self, action):
        while 1:
            retValue = self.callAction(action)
            if not retValue:
                # No return value: we've finished and should proceed
                return
            else:
                # Don't busy-wait : assume lack of completion is a sign we might keep doing this
                time.sleep(0.1)
             
    def callAction(self, action):
        return self.handleExceptions(self.test.callAction, action)
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

