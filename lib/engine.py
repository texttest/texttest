#!/usr/bin/env python

import plugins, os, sys, testmodel, signal
from threading import Thread
from usecase import ScriptEngine
from ndict import seqdict
from actionrunner import ActionRunner

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
            self.storeBothWays(oldTest.name + " version " + self.getVersionName(oldTest), oldTest)
            self.storeBothWays(newTest.name + " version " + self.getVersionName(newTest), newTest)
        else:
            raise plugins.TextTestError, "Could not find unique name for tests with name " + oldTest.name
    def getVersionName(self, test):
        version = test.app.getFullVersion()
        if len(version):
            return version
        else:
            return "<default>"
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
        self.appSuites = seqdict()
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
            for version in versionList:
                app = self.addApplication(appName, dircache, version, versionList)
                if app:
                    appList.append(app)
                else:
                    raisedError = True
        return raisedError, appList
    def createApplication(self, appName, dircache, version):
        try:
            return testmodel.Application(appName, dircache, version, self.inputOptions)
        except (testmodel.BadConfigError, plugins.TextTestError), e:
            sys.stderr.write("Could not use application '" + appName +  "' - " + str(e) + "\n")
    def addApplication(self, appName, dircache, version, allVersions):
        raisedError = False
        app = self.createApplication(appName, dircache, version)
        if not app:
            return
        for extraVersion in app.getExtraVersions():
            if extraVersion in allVersions:
                plugins.printWarning("Same version '" + extraVersion + "' implicitly requested more than once, ignoring.")
                continue
            aggVersion = extraVersion
            if len(version) > 0:
                aggVersion = version + "." + extraVersion
            extraApp = self.createApplication(appName, dircache, aggVersion)
            if extraApp:
                app.extras.append(extraApp)
        return app
    def needsTestRuns(self):
        for responder in self.allResponders:
            if not responder.needsTestRuns():
                return False
        return True
    def createResponders(self, allApps):
        # With scripts, we ignore all responder options, we're just transforming data
        if self.inputOptions.runScript():
            return
        responderClasses = []
        for app in allApps:
            for respClass in app.getResponderClasses(allApps):
                if not respClass in responderClasses:
                    self.diag.info("Adding responder " + repr(respClass))
                    responderClasses.append(respClass)
        # Make sure we send application events when tests change state
        responderClasses.append(testmodel.ApplicationEventResponder)
        self.allResponders = map(lambda x : x(self.inputOptions), responderClasses)
        allCompleteResponder = testmodel.AllCompleteResponder(self.allResponders)
        self.allResponders.append(allCompleteResponder)
    def createTestSuites(self, allApps):
        uniqueNameFinder = UniqueNameFinder()
        appSuites = seqdict()
        forTestRuns = self.needsTestRuns()
        for app in allApps:
            errorMessages = []
            appGroup = [ app ] + app.extras
            for partApp in appGroup:
                try:
                    testSuite = partApp.createTestSuite(responders=self.allResponders, forTestRuns=forTestRuns)
                    appSuites[partApp] = testSuite
                    uniqueNameFinder.addSuite(testSuite)
                except plugins.TextTestError, e:
                    errorMessages.append("Rejected " + partApp.description() + " - " + str(e) + "\n")
                except:  
                    sys.stderr.write("Error creating test suite for " + partApp.description() + " :\n")
                    plugins.printException()
            fullMsg = "".join(errorMessages)
            # If the whole group failed, we write to standard error, where the GUI will find it. Otherwise we just log in case anyone cares.
            if len(errorMessages) == len(appGroup):
                sys.stderr.write(fullMsg)
            else:
                sys.stdout.write(fullMsg)
        return appSuites
    def deleteTempFiles(self):
        for app, testSuite in self.appSuites.items():
            app.removeWriteDirectory()
    def setUpResponders(self):
        testSuites = [ testSuite for app, testSuite in self.appSuites.items() ]
        for responder in self.allResponders:
            responder.addSuites(testSuites)
    def run(self):
        allApps = self.findApps()
        if self.inputOptions.helpMode():
            if len(allApps) > 0:
                allApps[0].printHelpText()
            else:
                print testmodel.helpIntro
                print "TextTest didn't find any valid test applications - you probably need to tell it where to find them."
                print "The most common way to do this is to set the environment variable TEXTTEST_HOME."
                print "If this makes no sense, read the online documentation..."
            return
        self._run(allApps)
    def findOwnThreadResponder(self):
        for responder in self.allResponders:
            if responder.needsOwnThread():
                return responder
    def _run(self, allApps):
        try:
            self.createResponders(allApps)
        except plugins.TextTestError, e:
            # Responder class-level errors are basically fatal : there is no point running without them (cannot
            # do anything about them) and no way to get partial errors.
            sys.stderr.write(str(e) + "\n")
            return
        self.appSuites = self.createTestSuites(allApps)
        if len(self.appSuites) > 0:
            try:
                self.runAppSuites()
            finally:
                self.deleteTempFiles() # include the dud ones, possibly
    def runAppSuites(self):
        # pick out any responder that is designed to hang around executing
        # some sort of loop in its own thread... generally GUIs of some sort
        ownThreadResponder = self.findOwnThreadResponder()
        if not ownThreadResponder or ownThreadResponder.needsTestRuns():
            self.runWithTests(ownThreadResponder)
        else:
            self.runAlone(ownThreadResponder)
    def runAlone(self, ownThreadResponder):
        self.setUpResponders()
        ownThreadResponder.run()
    def runWithTests(self, ownThreadResponder):              
        actionRunner = ActionRunner(self.inputOptions)
        actionRunner.addSuites([ testSuite for app, testSuite in self.appSuites.items() ])
    
        # Wait until now to do this, in case problems encountered so far...
        self.setUpResponders()
        if ownThreadResponder:
            thread = Thread(target=actionRunner.run)
            thread.start()
            ownThreadResponder.run()
        else:
            actionRunner.run()
    def setSignalHandlers(self):
        # Signals used on UNIX to signify running out of CPU time, wallclock time etc.
        if os.name == "posix":
            signal.signal(signal.SIGINT, self.handleSignal)
            signal.signal(signal.SIGUSR1, self.handleSignal)
            signal.signal(signal.SIGUSR2, self.handleSignal)
            signal.signal(signal.SIGXCPU, self.handleSignal)
    def handleSignal(self, sig, stackFrame):
        # Don't respond to the same signal more than once!
        signal.signal(sig, signal.SIG_IGN)
        signalText = self.getSignalText(sig)
        self.writeTermMessage(signalText)
        fetchResults = signalText.find("LIMIT") != -1
        # block all event notifications...
        if not fetchResults:
            plugins.Observable.blocked = True
            
        self.killAllTests(signalText)
    def killAllTests(self, signalText):
        # Kill all the tests and wait for the action runner to finish
        for app, suite in self.appSuites.items():
            for test in suite.getRunningTests():
                app.killTest(test, signalText)
    def writeTermMessage(self, signalText):
        message = "Terminating testing due to external interruption"
        if signalText:
            message += " (" + signalText + ")"
        print message
        sys.stdout.flush() # Try not to lose log file information...
    def getSignalText(self, sig):
        if sig == signal.SIGUSR1:
            return "RUNLIMIT1"
        elif sig == signal.SIGXCPU:
            return "CPULIMIT"
        elif sig == signal.SIGUSR2:
            return "RUNLIMIT2"
        elif sig == signal.SIGINT:
            return "" # mostly for historical reasons to be compatible with the default handler
        else:
            return "signal " + str(sig)
    
