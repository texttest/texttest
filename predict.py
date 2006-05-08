#!/usr/local/bin/python

import os, sys, filecmp, string, plugins, copy

plugins.addCategory("badPredict", "internal errors", "had internal errors")
plugins.addCategory("crash", "CRASHED")

# For backwards compatibility...
class FailedPrediction(plugins.TestState):
    def isSaveable(self):
        # for back-compatibility
        return 1

class CheckLogFilePredictions(plugins.Action):
    def __init__(self, version = None):
        self.logFile = None
        self.version = version
    def getLogFile(self, test, stem):
        logFile = test.makeTmpFileName(stem)
        if not os.path.isfile(logFile):
            logFile = test.getFileName(stem, self.version)
            if not logFile:
                return None
        return logFile
    def insertError(self, test, errType, briefError, error=""):
        test.changeState(FailedPrediction(errType, briefText=briefError, freeText=error, \
                                          started=1, executionHosts=test.state.executionHosts))
    def setUpApplication(self, app):
        self.logFile = app.getConfigValue("log_file")   

class CheckPredictions(CheckLogFilePredictions):
    def __init__(self, version = None):
        CheckLogFilePredictions.__init__(self, version)
        self.internalErrorList = None
        self.internalCompulsoryList = None
    def __repr__(self):
        return "Checking predictions for"
    def __call__(self, test):
        self.collectErrors(test)
    def parseStackTrace(self, stackTraceFile):
        lines = open(stackTraceFile).readlines()
        return lines[0].strip(), string.join(lines[2:], "")
    def collectErrors(self, test):
        # Hard-coded prediction: check test didn't crash
        stackTraceFile = test.makeTmpFileName("stacktrace")
        if os.path.isfile(stackTraceFile):
            summary, errorInfo = self.parseStackTrace(stackTraceFile)
            if not summary.startswith("CPU"):
                self.insertError(test, "crash", summary, errorInfo)
            os.remove(stackTraceFile)
            return 1

        if len(self.internalErrorList) == 0 and len(self.internalCompulsoryList) == 0:
            return 0
                
        compsNotFound = copy.deepcopy(self.internalCompulsoryList)
        errorsFound = self.extractErrorsFrom(test, self.logFile, compsNotFound)
        errorsFound += self.extractErrorsFrom(test, "errors", compsNotFound)
        errorsFound += len(compsNotFound)
        for comp in compsNotFound:
            self.insertError(test, "badPredict", "missing '" + comp + "'")
        return errorsFound
    def extractErrorsFrom(self, test, fileStem, compsNotFound):
        errorsFound = 0
        logFile = self.getLogFile(test, fileStem)
        if not logFile:
            return 0
        for line in open(logFile).xreadlines():
            for error in self.internalErrorList:
                if line.find(error) != -1:
                    errorsFound += 1
                    self.insertError(test, "badPredict", error)
            for comp in compsNotFound:
                if line.find(comp) != -1:
                    compsNotFound.remove(comp)
        return errorsFound
    def setUpApplication(self, app):
        CheckLogFilePredictions.setUpApplication(self, app)
        self.internalErrorList = app.getConfigValue("internal_error_text")
        self.internalCompulsoryList = app.getConfigValue("internal_compulsory_text")

def pad(str, padSize):
    return str.ljust(padSize)
        
class PredictionStatistics(plugins.Action):
    def __init__(self, args=[]):
        versions = self.getVersions(args)
        self.referenceChecker = CheckPredictions(versions[0])
        self.currentChecker = None
        if len(versions) > 1:
            self.currentChecker = CheckPredictions(versions[1])
    def getVersions(self, args):
        if len(args) == 0:
            return [""]
        arg, val = args[0].split("=")
        return val.split(",")
    def setUpSuite(self, suite):
        self.suiteName = suite.name + "\n   "
    def scriptDoc(self):
        return "Displays statistics about application internal errors present in the test suite"
    def __call__(self, test):
        refErrors = self.referenceChecker.collectErrors(test)
        currErrors = 0
        if self.currentChecker:
            currErrors = self.currentChecker.collectErrors(test)
        if refErrors + currErrors > 0:
            print self.suiteName + test.name.ljust(30) + "\t", refErrors, currErrors
            self.suiteName = "   "
    def setUpApplication(self, app):
        self.referenceChecker.setUpApplication(app)
        if self.currentChecker:
            self.currentChecker.setUpApplication(app)
