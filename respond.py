#!/usr/local/bin/python

import sys, string, os, plugins
from usecase import ScriptEngine
from threading import currentThread
from Queue import Queue, Empty

# Interface all responders must fulfil
class Responder:
    def __init__(self, optionMap):
        if ScriptEngine.instance:
            self.scriptEngine = ScriptEngine.instance
        else:
            self.setUpScriptEngine()
    def setUpScriptEngine(self):
        logger = plugins.getDiagnostics("Use-case log")
        self.scriptEngine = ScriptEngine(logger)
    def readAllVersions(self):
        return 0
    # Full suite of tests, get notified of it at the start...
    def addSuite(self, suite):
        pass
    # Called when anything changes at all
    def notifyChange(self, test, state):
        pass
    # Called when the state of the test "moves on" in its lifecycle
    def notifyLifecycleChange(self, test, changeDesc):
        pass
    # Called when no further actions will be performed on the test
    def notifyComplete(self, test):
        pass
    # Called when everything is finished
    def notifyAllComplete(self):
        pass
    def needsOwnThread(self):
        return 0
    def needsTestRuns(self):
        return 1
    def describeFailures(self, test):
        if test.state.hasFailed():
            print test.getIndent() + repr(test), test.state.getDifferenceSummary()
        
class SaveState(Responder):
    def notifyComplete(self, test):
        if test.state.isComplete():
            self.performSave(test)
    def performSave(self, test):
        # overridden in subclasses
        test.saveState()

# Utility for responders that want a separate thread to run permanently... generally useful for GUIs
class ThreadedResponder(Responder):
    def __init__(self, optionMap):
        Responder.__init__(self, optionMap)
        self.workQueue = Queue()
    def needsOwnThread(self):
        return 1
    def processChangesMainThread(self):
        try:
            test, state = self.workQueue.get_nowait()
            if state == "allComplete":
                self.notifyAllComplete()
                return False
            if test:
                test.notifyChanged(state)
        except Empty:
            pass
        return True
    def notifyChange(self, test, state):
        if not plugins.inMainThread():
            self.workQueue.put((test, state))
            return 1
        else:
            self.notifyChangeMainThread(test, state)
    def notifyAllComplete(self):
        if plugins.inMainThread():
            self.scriptEngine.applicationEvent("completion of test actions")
        else:
            self.workQueue.put((None, "allComplete"))
    def runMain(self):
        # typically call main loop of GUI library
        pass
            
class InteractiveResponder(Responder):
    def __init__(self, optionMap):
        Responder.__init__(self, optionMap)
        self.overwriteSuccess = optionMap.has_key("n")
        self.overwriteFailure = optionMap.has_key("o")
    def notifyComplete(self, test):
        self.describeFailures(test)
        if self.shouldSave(test):
            self.save(test, self.getAutosaveVersion(test))
        elif self.useInteractiveResponse(test):
            self.presentInteractiveDialog(test)
    def getAutosaveVersion(self, test):
        versions = test.app.getVersionFileExtensions(forSave=1)
        logFileStem = os.path.join(test.abspath, test.getConfigValue("log_file") + "." + test.app.name)
        if not os.path.isfile(logFileStem):
            return ""
        # Start with the least specific, we want to create a reusable file if we can...
        versions.reverse()
        for version in versions:
            logFile = logFileStem + "." + version
            if not os.path.isfile(logFile):
                return version
        return test.app.getFullVersion(forSave=1)
    def shouldSave(self, test):
        if not test.state.hasResults():
            return 0
        if self.overwriteSuccess and test.state.hasSucceeded():
            return 1
        return self.overwriteFailure and test.state.hasFailed()
    def save(self, test, version, exact=1):
        saveDesc = " "
        if version:
            saveDesc += "version " + version + " "
        if exact:
            saveDesc += "(exact) "
        if self.overwriteSuccess:
            saveDesc += "(overwriting succeeded files also)"
        print test.getIndent() + "Saving " + repr(test) + saveDesc
        test.state.save(exact, version, self.overwriteSuccess)
    def useInteractiveResponse(self, test):
        return test.state.hasFailed() and test.state.hasResults() and not self.overwriteFailure
    def presentInteractiveDialog(self, test):            
        performView = self.askUser(test, allowView=1)
        if performView:
            process = self.viewTest(test)
            self.askUser(test, allowView=0, process=process)
    def viewTest(self, test):
        outputText = test.state.freeText
        sys.stdout.write(outputText)
        logFile = test.getConfigValue("log_file")
        logFileComparison, list = test.state.findComparison(logFile)
        if logFileComparison:
            tool = test.getConfigValue("diff_program")
            cmdLine = tool + " " + logFileComparison.stdCmpFile + " " +\
                      logFileComparison.tmpCmpFile + plugins.nullRedirect()
            if logFileComparison.newResult():
                tool = test.getConfigValue("view_program")
                cmdLine = tool + " " + logFileComparison.tmpCmpFile + plugins.nullRedirect()
            if tool:
                print "<See also " + tool + " window for details of " + logFile + ">"
                return plugins.BackgroundProcess(cmdLine)
    def askUser(self, test, allowView, process=None):      
        versions = test.app.getVersionFileExtensions(forSave=1)
        options = ""
        for i in range(len(versions)):
            options += "Save Version " + versions[i] + "(" + str(i + 1) + "), "
        options += "Save(s) or continue(any other key)?"
        if allowView:
            options = "View details(v), " + options
        print test.getIndent() + options
        response = self.scriptEngine.readStdin()
        exactSave = response.find('+') != -1
        if response.startswith('s'):
            self.save(test, version="", exact=exactSave)
        elif allowView and response.startswith('v'):
            return 1
        else:
            for i in range(len(versions)):
                versionOption = str(i + 1)
                if response.startswith(versionOption):
                    self.save(test, versions[i], exactSave)
        if process:
            process.killAll()
        return 0
   
