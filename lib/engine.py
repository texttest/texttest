#!/usr/bin/env python

import plugins, os, sys, testmodel, signal
from threading import Thread
from usecase import ScriptEngine
from ndict import seqdict
from time import sleep
from respond import Responder

# Class to allocate unique names to tests for script identification and cross process communication
class UniqueNameFinder(Responder):
    def __init__(self, optionMap):
        Responder.__init__(self, optionMap)
        self.name2test = {}
        self.diag = plugins.getDiagnostics("Unique Names")
    def notifyAdd(self, test, initial):
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
        test.setUniqueName(name)

class TextTest:
    def __init__(self):
        self.setSignalHandlers(self.handleSignalWhileStarting)
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
    def createApplication(self, appName, dircache, versionStr):
        try:
            versions = filter(len, versionStr.split(".")) # remove empty versions
            return testmodel.Application(appName, dircache, versions, self.inputOptions)
        except (testmodel.BadConfigError, plugins.TextTestError), e:
            sys.stderr.write("Could not use application '" + appName +  "' - " + str(e) + "\n")
    def addApplication(self, appName, dircache, version, allVersions):
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
        responderClasses += [ UniqueNameFinder, testmodel.ApplicationEventResponder, testmodel.AllCompleteResponder ]
        allResponders = map(lambda x : x(self.inputOptions), responderClasses)
        self.allResponders = self.removeBaseClasses(allResponders)
        
    def createThreadRunners(self, allApps):
        threadRunnerClasses = []
        threadRunners = []
        for app in allApps:
            for threadClass in app.getThreadRunnerClasses():
                if not threadClass in threadRunnerClasses:
                    self.diag.info("Adding thread runner " + repr(threadClass))
                    threadRunnerClasses.append(threadClass)
                    threadRunners.append(self.makeThreadRunner(threadClass))
        return self.removeBaseClasses(threadRunners)
    def removeBaseClasses(self, objects):
        # Different apps can produce different versions of the same responder/thread runner
        # We should make sure we only include the most specific ones
        toRemove = []
        for i in range(len(objects)):
            for j in range(i + 1, len(objects)):
                obj1 = objects[i]
                obj2 = objects[j]
                if isinstance(obj1, obj2.__class__):
                    toRemove.append(obj2)
                elif isinstance(obj2, obj1.__class__):
                    toRemove.append(obj1)
        return filter(lambda obj: obj not in toRemove, objects)
    def makeThreadRunner(self, threadRunnerClass):
        for responder in self.allResponders:
            if isinstance(responder, threadRunnerClass):
                return responder
        return threadRunnerClass(self.inputOptions)
    def createTestSuites(self, allApps):
        appSuites = seqdict()
        forTestRuns = self.needsTestRuns()
        for app in allApps:
            errorMessages = []
            appGroup = [ app ] + app.extras
            for partApp in appGroup:
                try:
                    testSuite = partApp.createTestSuite(responders=self.allResponders, forTestRuns=forTestRuns)
                    appSuites[partApp] = testSuite
                except plugins.TextTestError, e:
                    errorMessages.append("Rejected " + partApp.description() + " - " + str(e) + "\n")
                except KeyboardInterrupt:
                    raise
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
    def run(self):
        try:
            self._run()
        except KeyboardInterrupt:
            pass # already written about this
    def _run(self):
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
        try:
            self.createAndRunSuites(allApps)
        finally:
            self.deleteTempFiles() # include the dud ones, possibly
    def createAndRunSuites(self, allApps):
        try:
            self.createResponders(allApps)
        except plugins.TextTestError, e:
            # Responder class-level errors are basically fatal : there is no point running without them (cannot
            # do anything about them) and no way to get partial errors.
            sys.stderr.write(str(e) + "\n")
            return
        self.appSuites = self.createTestSuites(allApps)
        if len(self.appSuites) == 0:
            return
        threadRunners = self.createThreadRunners(allApps)
        self.addSuites(threadRunners)
        self.runThreads(threadRunners)
    def getObjectsToAddSuites(self, threadRunners):
        return self.allResponders + filter(lambda runner: runner not in self.allResponders, threadRunners)
    def addSuites(self, threadRunners):
        for object in self.getObjectsToAddSuites(threadRunners):
            # For all observable responders, set them to be observed by the others if they
            # haven't fixed their own observers
            if isinstance(object, plugins.Observable) and len(object.observers) == 0:
                self.diag.info("All responders now observing " + str(object.__class__))
                object.setObservers(self.allResponders)
            suites = self.getSuitesToAdd(object, threadRunners)
            self.diag.info("Adding suites " + repr(suites) + " for " + str(object.__class__))
            object.addSuites(suites)
    def getSuitesToAdd(self, responderOrThreadRunner, threadRunners):
        if not responderOrThreadRunner in threadRunners:
            return [ suite for app, suite in self.appSuites.items() ]
        suites = []
        for app, testSuite in self.appSuites.items():
            for threadRunnerClass in app.getThreadRunnerClasses():
                if isinstance(responderOrThreadRunner, threadRunnerClass):
                    suites.append(testSuite)
                    break
        return suites        
    def runThreads(self, threadRunners):
        # Set the signal handlers to use when running
        self.setSignalHandlers(self.handleSignalWhileRunning)
        # Run the first one as the main thread and the rest in subthreads
        # Make sure all of them are finished before we stop
        allThreads = []
        for subThreadRunner in threadRunners[1:]:
            thread = Thread(target=subThreadRunner.run)
            allThreads.append(thread)
            self.diag.info("Running " + str(subThreadRunner.__class__) + " in a subthread")
            thread.start()
            
        if len(threadRunners) > 0:
            self.diag.info("Running " + str(threadRunners[0].__class__) + " in main thread")
            threadRunners[0].run()
            
        self.waitForThreads(allThreads)
    def waitForThreads(self, allThreads):
        # Need to wait for the threads to terminate in a way that allows signals to be
        # caught. thread.join doesn't do this. signal.pause seems like a good idea but
        # doesn't return unless a signal is caught, leading to sending "fake" ones from the
        # threads when they finish. And playing with signals and threads together is playing with fire...
        
        # So we poll, which we don't really want to do, but it seems better than using Twisted or asyncore
        # just for this :) With a long enough sleep it shouldn't generate too much load... 
        
        # See http://groups.google.com/group/comp.lang.python/browse_thread/thread/a244905b86f06e48/7e969a0c7932fa91#
        currThreads = self.aliveThreads(allThreads)
        while len(currThreads) > 0:
            sleep(0.5)
            currThreads = self.aliveThreads(currThreads)
    def aliveThreads(self, threads):
        return filter(lambda thread: thread.isAlive(), threads)
    def getSignals(self):
        if hasattr(signal, "SIGUSR1"):
            # Signals used on UNIX to signify running out of CPU time, wallclock time etc.
            return [ signal.SIGINT, signal.SIGUSR1, signal.SIGUSR2, signal.SIGXCPU ]
        else:
            # Windows, which doesn't do signals
            return []
    def setSignalHandlers(self, handler):
        for sig in self.getSignals():
            signal.signal(sig, handler)
    def handleSignalWhileStarting(self, sig, stackFrame):
        # Don't respond to the same signal more than once!
        signal.signal(sig, signal.SIG_IGN)
        signalText = self.getSignalText(sig)
        self.writeTermMessage(signalText)
        raise KeyboardInterrupt, signalText
    def handleSignalWhileRunning(self, sig, stackFrame):
        # Don't respond to the same signal more than once!
        signal.signal(sig, signal.SIG_IGN)
        signalText = self.getSignalText(sig)
        self.writeTermMessage(signalText)    
        self.killAllTests(signalText)
    def killAllTests(self, signalText):
        # Kill all the tests and wait for the action runner to finish
        for app, suite in reversed(self.appSuites.items()):
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
        else:
            return "" # mostly for historical reasons to be compatible with the default handler
