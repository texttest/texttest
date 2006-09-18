#!/usr/local/bin/python

import sys, string, os, plugins, types
from usecase import ScriptEngine
from threading import currentThread
from Queue import Queue, Empty
from time import sleep

# Interface all responders must fulfil
class Responder:
    def __init__(self, optionMap):
        if ScriptEngine.instance:
            self.scriptEngine = ScriptEngine.instance
        else:
            self.setUpScriptEngine()
        self.closedown = False
    def setUpScriptEngine(self):
        logger = plugins.getDiagnostics("Use-case log")
        self.scriptEngine = ScriptEngine(logger)
    # Full suite of tests, get notified of it at the start...
    def addSuite(self, suite):
        pass
    # Called when anything changes at all, not related to lifecycle below
    def notifyChange(self, test):
        pass
    # Called when the state of the test "moves on" in its lifecycle
    def notifyLifecycleChange(self, test, state, changeDesc):
        pass
    # Called when no further actions will be performed on the test
    def notifyComplete(self, test):
        pass
    # Called when everything is finished
    def notifyAllComplete(self, observerGroup):
        pass
    def notifyInterrupt(self, fetchResults):
        if not fetchResults:
            self.closedown = True
    def needsOwnThread(self):
        return 0
    def needsTestRuns(self):
        return 1
    def describeFailures(self, test):
        if test.state.hasFailed() and not self.closedown:
            print test.getIndent() + repr(test), test.state.getDifferenceSummary()
        
class SaveState(Responder):
    def notifyComplete(self, test):
        if test.state.isComplete():
            self.performSave(test)
    def performSave(self, test):
        # overridden in subclasses
        test.saveState()

# Utility for responders that want a separate thread to run permanently... generally useful for GUIs
# Make it a singleton so we can find it...
class ThreadTransferResponder(Responder):
    instance = None
    def __init__(self, optionMap):
        Responder.__init__(self, optionMap)
        self.workQueue = Queue()
        self.allCompleted = False
        ThreadTransferResponder.instance = self
    def setUpScriptEngine(self):
        # Don't want the script engine attached here, leave for GUI...
        pass
    def pollQueue(self):
        try:
            method, args = self.workQueue.get_nowait()
            method(*args)
        except Empty:
            pass
        # We must sleep for a bit, or we use the whole CPU (busy-wait)
        sleep(0.1)
        return not self.allCompleted
    def maybeTransfer(self, queueMethod, *args):
        if self.closedown:
            return
        if not plugins.inMainThread():
            self.workQueue.put((queueMethod, args))
            return 1
    def notifyChange(self, test):
        return self.maybeTransfer(test.notifyChanged)
    def notifyLifecycleChange(self, test, state, changeDesc):
        return self.maybeTransfer(test.notifyLifecycle, state, changeDesc)
    def notifyAllComplete(self, observerGroup):
        retVal = self.maybeTransfer(observerGroup.notifyAllCompleted)
        if plugins.inMainThread():
            self.allCompleted = True
        return retVal
            
class InteractiveResponder(Responder):
    def __init__(self, optionMap):
        Responder.__init__(self, optionMap)
        self.overwriteSuccess = optionMap.has_key("n")
        self.overwriteFailure = optionMap.has_key("o")
    def notifyComplete(self, test):
        if self.closedown:
            return
        self.describeFailures(test)
        if self.shouldSave(test):
            self.save(test, test.app.getFullVersion(forSave=1))
        elif self.useInteractiveResponse(test):
            self.presentInteractiveDialog(test)
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
        test.state.save(test, exact, version, self.overwriteSuccess)
    def useInteractiveResponse(self, test):
        return test.state.hasFailed() and test.state.hasResults() and not self.overwriteFailure
    def presentInteractiveDialog(self, test):            
        performView = self.askUser(test, allowView=1)
        if performView:
            process = self.viewTest(test)
            self.askUser(test, allowView=0, process=process)
    def getViewCmdInfo(self, test, comparison):
        if comparison.missingResult():
            # Don't fire up GUI tools for missing results...
            return None, None
        if comparison.newResult():
            tool = test.getCompositeConfigValue("view_program", comparison.stem)
            cmdLine = tool + " " + comparison.tmpCmpFile + plugins.nullRedirect()
        else:
            tool = test.getConfigValue("diff_program")
            cmdLine = tool + " " + comparison.stdCmpFile + " " +\
                      comparison.tmpCmpFile + plugins.nullRedirect()
        return tool, cmdLine        
    def viewTest(self, test):
        outputText = test.state.freeText
        sys.stdout.write(outputText)
        if not outputText.endswith("\n"):
            sys.stdout.write("\n")
        logFile = test.getConfigValue("log_file")
        logFileComparison, list = test.state.findComparison(logFile)
        if logFileComparison:
            tool, cmdLine = self.getViewCmdInfo(test, logFileComparison)
            if tool:
                print "<See also " + tool + " window for details of " + logFile + ">"
                return plugins.BackgroundProcess(cmdLine)
    def askUser(self, test, allowView, process=None):      
        versions = test.app.getSaveableVersions()
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
   
