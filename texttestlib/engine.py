#!/usr/bin/env python

from . import plugins, testmodel
import os
import sys
import signal
import operator
import logging
from threading import Thread
from collections import OrderedDict
from time import sleep
from glob import glob
from copy import copy
import time
from functools import reduce, cmp_to_key

# Class to allocate unique names to tests for script identification and cross process communication


class UniqueNameFinder(plugins.Responder):
    def __init__(self, optionMap, *args):
        plugins.Responder.__init__(self, optionMap)
        self.name2test = {}
        self.diag = logging.getLogger("Unique Names")

    def notifyAdd(self, test, *args, **kw):
        if test.name in self.name2test:
            oldTest = self.name2test[test.name]
            self.storeUnique(oldTest, test)
        else:
            self.storeBothWays(test.name, test)

    def notifyRemove(self, test):
        self.removeName(test.name)

    def removeName(self, name):
        if name in self.name2test:
            self.diag.info("Removing test name " + name)
            del self.name2test[name]

    def notifyNameChange(self, test, origRelPath):
        oldName = os.path.basename(origRelPath)
        self.removeName(oldName)
        self.notifyAdd(test)

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
            self.storeBothWays(oldTest.name + " for " + oldTest.app.fullName(), oldTest)
            self.storeBothWays(newTest.name + " for " + newTest.app.fullName(), newTest)
        elif oldTest.app.getFullVersion() != newTest.app.getFullVersion():
            self.storeBothWays(oldTest.name + " version " + self.getVersionName(oldTest), oldTest)
            self.storeBothWays(newTest.name + " version " + self.getVersionName(newTest), newTest)
        else:
            # Overwrite the old with the new if they can't be distinguished
            self.storeBothWays(newTest.name + newParentId, newTest)

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


class Activator(plugins.Responder, plugins.Observable):
    def __init__(self, optionMap, allApps):
        plugins.Responder.__init__(self, optionMap, allApps)
        plugins.Observable.__init__(self)
        self.allowEmpty = "gx" in optionMap or optionMap.runScript()
        self.suites = []
        self.diag = logging.getLogger("Activator")
        self.suiteCopyCache = {}

    def addSuites(self, suites):
        self.suites = suites

    def findGuideSuiteForCopy(self, versions):
        versionsForGuide = tuple([v for v in versions if "copy_" not in v])
        if versionsForGuide in self.suiteCopyCache:
            return self.suiteCopyCache.get(versionsForGuide)

        for suite in self.suites:
            if tuple(suite.app.versions) == versionsForGuide:
                self.suiteCopyCache[versionsForGuide] = suite
                return suite

    def readTestSuiteContents(self, suite):
        if any(("copy_" in v) for v in suite.app.versions):
            guideSuite = self.findGuideSuiteForCopy(suite.app.versions)
            if guideSuite is not None:
                self.diag.info("Creating test suite by copying " + repr(guideSuite))
                return suite.readContents(guideSuite=guideSuite)

        filters = suite.app.getFilterList(self.suites)
        self.diag.info("Creating test suite with filters " + repr(filters))
        return suite.readContents(filters)

    def run(self):
        goodSuites = []
        rejectionInfo = OrderedDict()
        self.notify("StartRead")
        for suite in self.suites:
            try:
                self.readTestSuiteContents(suite)
                self.diag.info("SUCCESS: Created test suite of size " + str(suite.size()))

                if suite.size() > 0 or self.allowEmpty:
                    goodSuites.append(suite)
                    suite.notify("Add", initial=True)
                else:
                    rejectionInfo[suite.app] = "no tests matching the selection criteria found."
            except plugins.TextTestError as e:
                rejectionInfo[suite.app] = str(e)

        self.notify("AllRead", goodSuites)

        if len(rejectionInfo) > 0:
            self.writeErrors(rejectionInfo)
        # triggers the ActionRunner to start if needed, do this in the same thread!
        self.performNotify("AllReadAndNotified")
        return goodSuites

    def writeErrors(self, rejectionInfo):
        # Don't write errors if only some of a group are rejected
        appsByName = OrderedDict()
        rejectedApps = set(rejectionInfo.keys())
        for suite in self.suites:
            app = suite.app
            appsByName.setdefault(app.name, []).append(app)

        for _, appGroup in list(appsByName.items()):
            if set(appGroup).issubset(rejectedApps):
                for app in appGroup:
                    if app in rejectionInfo:
                        sys.stderr.write(app.rejectionMessage(rejectionInfo.get(app)))


class TextTest(plugins.Responder, plugins.Observable):
    def __init__(self):
        plugins.Responder.__init__(self)
        plugins.Observable.__init__(self)
        if os.name == "posix":
            # To aid in debugging tests that hang...
            signal.signal(signal.SIGQUIT, self.printStackTrace)
        self.setSignalHandlers(self.handleSignalWhileStarting)
        self.inputOptions = testmodel.OptionFinder()
        self.diag = logging.getLogger("Find Applications")
        self.appSuites = OrderedDict()
        self.exitCode = 0

    def printStackTrace(self, *args):
        # Swiped from http://stackoverflow.com/questions/1032813/dump-stacktraces-of-all-active-threads
        # print_stack() only shows the main thread which is often just waiting for the others.
        sys.stderr.write("Received SIGQUIT: showing current stack trace below:\n")
        code = []
        from traceback import extract_stack
        for threadId, stack in list(sys._current_frames().items()):
            code.append("# ThreadID: %s" % threadId)
            for filename, lineno, name, line in extract_stack(stack):
                code.append('  File "%s", line %d, in %s' % (filename, lineno, name))
                if line:
                    code.append("    " + line.strip())

        for line in code:
            sys.stderr.write(line + "\n")

    def findSearchDirs(self, roots):
        subDirs = []
        for root in roots:
            for f in sorted(os.listdir(root)):
                path = os.path.join(root, f)
                if os.path.isdir(path):
                    subDirs.append(path)
        return roots + subDirs

    def findApps(self):
        roots = list(filter(os.path.isdir, self.inputOptions.rootDirectories))
        if len(roots) == 0:
            for root in self.inputOptions.rootDirectories:
                sys.stderr.write("Test suite root directory does not exist: " + root + "\n")
            return True, []

        # Just ignore any roots that don't exist
        self.inputOptions.rootDirectories = roots
        self.diag.info("Using test suite at " + repr(roots))
        searchDirs = self.findSearchDirs(roots)
        if "new" in self.inputOptions:
            return False, []

        appList = []
        raisedError = False
        selectedAppDict = self.inputOptions.findSelectedAppNames()
        for dir in searchDirs:
            ignoreNames = [app.name for app in appList]
            subRaisedError, apps = self.findAppsUnder(dir, selectedAppDict, ignoreNames)
            appList += apps
            raisedError |= subRaisedError

        if not raisedError:
            for missingAppName in self.findMissingApps(appList, list(selectedAppDict.keys())):
                sys.stderr.write("Could not read application '" + missingAppName + "'. No file named config." +
                                 missingAppName + " was found under " + " or ".join(self.inputOptions.rootDirectories) + ".\n")
                raisedError = True

        appList.sort(key=lambda app: app.name)
        self.diag.info("Found applications : " + repr(appList))
        return raisedError, appList

    def findMissingApps(self, appList, selectedApps):
        return [appName for appName in selectedApps if self.appMissing(appName, appList)]

    def appMissing(self, appName, apps):
        return reduce(operator.and_, (app.name != appName for app in apps), True)

    def findAppsUnder(self, dirName, selectedAppDict, ignoreNames):
        appList = []
        raisedError = False
        self.diag.info("Selecting apps in " + dirName + " according to dictionary :" + repr(selectedAppDict))
        dircache = testmodel.DirectoryCache(dirName)
        for f in dircache.findAllFiles("config"):
            if not os.path.isfile(f):
                continue  # ignore broken links and directories
            components = os.path.basename(f).split('.')
            if len(components) != 2:
                continue
            appName = components[1]

            # Ignore emacs backup files and stuff we haven't selected
            if appName.endswith("~") or (len(selectedAppDict) and appName not in selectedAppDict) or appName in ignoreNames:
                continue

            self.diag.info("Building apps from " + f)
            versionList = self.inputOptions.findVersionList()
            if appName in selectedAppDict:
                versionList = selectedAppDict[appName]
            extraVersionsDuplicating = []
            for versionStr in versionList:
                appVersions = list(filter(len, versionStr.split(".")))  # remove empty versions
                app, currExtra = self.addApplication(appName, dircache, appVersions, versionList)
                if app:
                    appList.append(app)
                    extraVersionsDuplicating += currExtra
                else:
                    raisedError = True
            for toRemove in [app for app in appList if app.getFullVersion() in extraVersionsDuplicating]:
                appList.remove(toRemove)
        return raisedError, appList

    def createApplication(self, appName, dircache, versions):
        try:
            return testmodel.Application(appName, dircache, versions, self.inputOptions)
        except (testmodel.BadConfigError, plugins.TextTestError) as e:
            sys.stderr.write("Unable to load application from file 'config." + appName + "' - " + str(e) + ".\n")

    def addApplication(self, appName, dircache, appVersions, allVersions=[]):
        app = self.createApplication(appName, dircache, appVersions)
        if not app:
            return None, []
        extraVersionsDuplicating = []
        for extraVersion in app.getExtraVersions():
            if extraVersion in allVersions:
                extraVersionsDuplicating.append(extraVersion)
            if "copy_" in extraVersion:
                extraApp = copy(app)
                extraApp.versions = appVersions + extraVersion.split(".")
                extraApp.extras = []
                extraApp.checkout = extraApp.configObject.setUpCheckout(extraApp)
            else:
                extraApp = self.createApplication(appName, dircache, appVersions + extraVersion.split("."))
            if extraApp:
                # Autogenerated extra versions are marked unsaveable on the parent,
                # obviously needs transferring to the extraApp here
                if extraVersion in app.getConfigValue("unsaveable_version"):
                    extraApp.addConfigEntry("unsaveable_version", extraVersion)
                app.extras.append(extraApp)
        return app, extraVersionsDuplicating

    def getAllConfigObjects(self, allApps):
        if len(allApps) > 0:
            return allApps
        else:
            return [plugins.importAndCall("default", "getConfig", self.inputOptions)]

    def createResponders(self, allApps):
        responderClasses = self.getBuiltinResponderClasses()
        for configObject in self.getAllConfigObjects(allApps):
            for respClass in configObject.getResponderClasses(allApps):
                if not respClass in responderClasses:
                    self.diag.info("Adding responder " + repr(respClass))
                    responderClasses.insert(-2, respClass)  # keep Activator and AllCompleteResponder at the end
        self.removeBaseClasses(responderClasses)
        self.diag.info("Filtering away base classes, using " + repr(responderClasses))
        self.observers = [x(self.inputOptions, allApps) for x in responderClasses]

    def getBuiltinResponderClasses(self):
        return [UniqueNameFinder, Activator, testmodel.AllCompleteResponder]

    def removeBaseClasses(self, classes):
        # Different apps can produce different versions of the same responder/thread runner
        # We should make sure we only include the most specific ones, in the furthest forward position their relatives achieved...
        # (the order can be important)
        toRemove = []
        newPositions = {}
        for i, class1 in enumerate(classes):
            for class2 in classes[i+1:]:
                if issubclass(class1, class2):
                    toRemove.append(class2)
                elif issubclass(class2, class1):
                    toRemove.append(class1)
                    if class2 not in newPositions:
                        newPositions[class2] = i

        for cls, i in list(newPositions.items()):
            classes.remove(cls)
            classes.insert(i, cls)
        for cls in toRemove:
            classes.remove(cls)

    def createTestSuites(self, allApps):
        appSuites = OrderedDict()
        raisedError = False
        for app in allApps:
            warningMessages = []
            appGroup = [app] + app.extras
            for partApp in appGroup:
                try:
                    testSuite = self.createInitialTestSuite(partApp)
                    appSuites[partApp] = testSuite
                except plugins.TextTestWarning as e:
                    warningMessages.append(partApp.rejectionMessage(str(e)))
                except plugins.TextTestError as e:
                    sys.stderr.write(partApp.rejectionMessage(str(e)))
                    raisedError = True
                except Exception:
                    sys.stderr.write("Error creating test suite for " + partApp.description() + " :\n")
                    plugins.printException()
            fullMsg = "".join(warningMessages)
            # If the whole group failed, we write to standard error, where the GUI will find it. Otherwise we just log in case anyone cares.
            if len(warningMessages) == len(appGroup):
                sys.stderr.write(fullMsg)
                raisedError = True
            else:
                sys.stdout.write(fullMsg)
        return raisedError, appSuites

    def notifyExit(self):
        # Can get called several times, protect against this...
        if len(self.appSuites) > 0:
            self.notify("Status", "Removing all temporary files ...")
            for app, testSuite in self.appSuites.items():
                self.notify("ActionProgress")
                app.cleanWriteDirectory(testSuite)
            self.notify("Status", "Removed all temporary files ...")
            self.appSuites = []

    def notifyComplete(self, test):
        testExitCode = test.state.getExitCode()
        if testExitCode and self.exitCode != 1:
            self.exitCode = testExitCode

    def run(self):
        try:
            self._run()
            self.diag.info("Exiting with exit code " + str(self.exitCode))
            sys.exit(self.exitCode)
        except plugins.TextTestError as e:
            sys.stderr.write(str(e) + "\n")
            sys.exit(1)
        except KeyboardInterrupt:
            pass  # already written about this

    def _run(self):
        appFindingWroteError, allApps = self.findApps()
        if self.inputOptions.helpMode():
            if len(allApps) > 0:
                allApps[0].printHelpText()
            else:
                print("TextTest didn't find any valid test applications - you probably need to tell it where to find them.")
                print("The most common way to do this is to set the environment variable TEXTTEST_HOME.")
                print("If this makes no sense, read the online documentation...")
                print(testmodel.helpIntro)
            return

        if len(allApps) == 0 and appFindingWroteError:
            self.exitCode = 1
            return

        if self.inputOptionsValid(allApps):
            try:
                self.createAndRunSuites(allApps)
            finally:
                self.notifyExit()  # include the dud ones, possibly

    def inputOptionsValid(self, allApps):
        validOptions = self.findAllValidOptions(allApps)
        for option in list(self.inputOptions.keys()):
            if option not in validOptions:
                sys.stderr.write("texttest: unrecognised option '-" + option + "'\n")
                self.exitCode = 1
                return False
        return True

    def findAllValidOptions(self, allApps):
        validOptions = set()
        for configObject in self.getAllConfigObjects(allApps):
            validOptions.update(set(configObject.findAllValidOptions(allApps)))
        return validOptions

    def createAndRunSuites(self, allApps):
        self.createResponders(allApps)
        raisedError, self.appSuites = self.createTestSuites(allApps)
        if not raisedError or len(self.appSuites) > 0:
            self.addSuites(list(self.appSuites.values()), allApps)

            # Set the signal handlers to use when running, if we actually plan to do any
            self.setSignalHandlers(self.handleSignal)

            self.runThreads()
        if raisedError:
            self.exitCode = 1

    def addSuites(self, emptySuites, allApps):
        for object in self.observers:
            # For all observable responders, set them to be observed by the others if they
            # haven't fixed their own observers
            if isinstance(object, plugins.Observable) and len(object.observers) == 0:
                self.diag.info("All responders now observing " + str(object.__class__))
                object.setObservers([self] + self.observers)
            suites = self.getSuitesToAdd(object, emptySuites, allApps)
            self.diag.info("Adding suites " + repr(suites) + " for " + str(object.__class__))
            object.addSuites(suites)

    def getSuitesToAdd(self, observer, emptySuites, allApps):
        for responderClass in self.getBuiltinResponderClasses():
            if isinstance(observer, responderClass):
                return emptySuites

        responderClassDict = {}
        for app in allApps:
            responderClassDict[app.name] = app.getResponderClasses(list(self.appSuites.keys()))

        suites = []
        for testSuite in emptySuites:
            for responderClass in responderClassDict.get(testSuite.app.name):
                if isinstance(observer, responderClass):
                    suites.append(testSuite)
                    break
        return suites

    def getRootSuite(self, appName, versions):
        for app, testSuite in list(self.appSuites.items()):
            if app.name == appName and app.versions == versions:
                return testSuite

        dirCache = self.makeDirectoryCache(appName)
        if dirCache:
            newApp = self.addApplication(appName, dirCache, versions)[0]
            return self.createEmptySuite(newApp)
        else:
            message = "Couldn't create directory cache for application: " + str(appName)
            plugins.printWarning(message)
            return None

    def createEmptySuite(self, newApp):
        emptySuite = self.createInitialTestSuite(newApp)
        self.appSuites[newApp] = emptySuite
        self.addSuites([emptySuite], [newApp])
        return emptySuite

    def createInitialTestSuite(self, app):
        return app.createInitialTestSuite([self] + self.observers)

    def makeDirectoryCache(self, appName):
        configFile = "config." + appName
        for rootDir in self.inputOptions.rootDirectories:
            rootConfig = os.path.join(rootDir, configFile)
            if os.path.isfile(rootConfig):
                return testmodel.DirectoryCache(rootDir)
            else:
                allFiles = glob(os.path.join(rootDir, "*", configFile))
                if len(allFiles) > 0:
                    return testmodel.DirectoryCache(os.path.dirname(allFiles[0]))

    def notifyExtraTest(self, testPath, appName, versions):
        rootSuite = self.getRootSuite(appName, versions)
        if rootSuite:
            rootSuite.addTestCaseWithPath(testPath)
        else:
            message = "Couldn't add extra test for application: " + str(appName)
            plugins.printWarning(message)

    def notifyNewApplication(self, newApp):
        suite = self.createEmptySuite(newApp)
        suite.notify("Add", initial=False)

    def findThreadRunners(self):
        allRunners = [x for x in self.observers if hasattr(x, "run")]
        mainThreadRunner = None
        for runner in allRunners:
            if runner.canBeMainThread():
                mainThreadRunner = runner
                break
        allRunners.remove(mainThreadRunner)
        return mainThreadRunner, allRunners

    def runThreads(self):
        # Run the first one as the main thread and the rest in subthreads
        # Make sure all of them are finished before we stop
        mainThreadRunner, subThreadRunners = self.findThreadRunners()
        allThreads = []
        for subThreadRunner in subThreadRunners:
            thread = Thread(target=subThreadRunner.run, name=subThreadRunner.__class__.__name__)
            allThreads.append(thread)
            self.diag.info("Running " + str(subThreadRunner.__class__) + " in a subthread")
            thread.start()

        if mainThreadRunner:
            self.diag.info("Running " + str(mainThreadRunner.__class__) + " in main thread")
            mainThreadRunner.run()

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
        threadCount = len(currThreads)
        while threadCount > 0:
            sleep(0.5)
            currThreads = self.aliveThreads(currThreads)
            if len(currThreads) < threadCount:
                self.diag.info("Thread(s) terminated, remaining are " + repr([t.name for t in currThreads]))
            threadCount = len(currThreads)

    def aliveThreads(self, threads):
        return [thread for thread in threads if thread.isAlive()]

    def getSignals(self):
        if hasattr(signal, "SIGUSR1"):
            # Signals used on UNIX to signify running out of CPU time, wallclock time etc.
            return [signal.SIGINT, signal.SIGTERM, signal.SIGUSR1, signal.SIGUSR2, signal.SIGXCPU]
        else:
            # Windows, which doesn't do signals
            return []

    def setSignalHandlers(self, handler):
        if os.name == "nt":
            try:
                import ctypes
                # Must store this, otherwise it gets garbage collected, and a crash results...
                self.wrapper = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)(handler)
                ctypes.windll.kernel32.SetConsoleCtrlHandler(self.wrapper, True)
            except ImportError:
                pass # probably just documentation
        else:
            for sig in self.getSignals():
                signal.signal(sig, handler)

    def handleSignal(self, sig, *args):
        # Respond to the same signal only once and ignore all others!
        for ignoreSignal in self.getSignals():
            signal.signal(ignoreSignal, signal.SIG_IGN)
        signalText = self.getSignalText(sig)
        self.writeTermMessage(signalText)
        self.notify("Quit", sig)
        if len(self.appSuites) > 0:  # If the above succeeds in quitting they will be reset
            self.notify("KillProcesses", sig)
        if os.name == "nt":
            time.sleep(20)  # Time to clean up, process is killed when we exit
        else:
            return signalText

    def handleSignalWhileStarting(self, sig, *args):
        signalText = self.handleSignal(sig)
        if os.name != "nt":
            raise KeyboardInterrupt(signalText)

    def writeTermMessage(self, signalText):
        message = "Terminating testing due to external interruption"
        if signalText:
            message += " (" + signalText + ")"
        print(message)
        sys.stdout.flush()  # Try not to lose log file information...

    def getSignalText(self, sig):
        if hasattr(signal, "SIGUSR1"):
            if sig == signal.SIGUSR1:
                return "RUNLIMIT1"
            elif sig == signal.SIGXCPU:
                return "CPULIMIT"
            elif sig == signal.SIGUSR2:
                return "RUNLIMIT2"
        return ""  # mostly for historical reasons to be compatible with the default handler
