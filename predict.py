#!/usr/local/bin/python

helpDescription = """
It is possible to specify predictively how an application behaves. In general this works by reading
the config file list "internal_error_text" and searching the resulting log file for it. If this text
is found, a warning is generated. Conversely, you can specify the list "internal_compulsory_text" which
raises a warning if the text is not found. predict.CheckPredictions can also be run as a standalone action to
check the standard test results for internal errors.
"""

helpScripts = """predict.PredictionStatistics
                           - Displays statistics about application internal errors present in the test suite
                             Currently supports these options:
                             - v
                               version1[,version2]
"""

import os, filecmp, string, plugins, copy

class CheckLogFilePredictions(plugins.Action):
    def __init__(self, version = None):
        self.logFile = None
        self.version = version
    def getLogFile(self, test, stem):
        logFile = test.makeFileName(stem, self.version, temporary=1)
        if not os.path.isfile(logFile):
            logFile = test.makeFileName(stem, self.version)
        return logFile
    def insertError(self, test, error):
        test.changeState(test.FAILED, error)
    def setUpApplication(self, app):
        app.setConfigDefault("log_file", "output")
        self.logFile = app.getConfigValue("log_file")   

class CheckPredictions(CheckLogFilePredictions):
    def __init__(self, version = None):
        CheckLogFilePredictions.__init__(self, version)
        self.internalErrorList = None
        self.internalCompulsoryList = None
    def __repr__(self):
        return "Checking predictions for"
    def __call__(self, test):
        # Hard-coded prediction: check test didn't crash
        stackTraceFile = test.makeFileName("stacktrace", temporary=1)
        if os.path.isfile(stackTraceFile):
            errorInfo = open(stackTraceFile).read()
            self.insertError(test, errorInfo)
            os.remove(stackTraceFile)
            return 1
        
        if len(self.internalErrorList) == 0 and len(self.internalCompulsoryList) == 0:
            return 0
                
        compsNotFound = copy.deepcopy(self.internalCompulsoryList)
        errorsFound = self.extractErrorsFrom(test, self.logFile, compsNotFound)
        errorsFound += self.extractErrorsFrom(test, "errors", compsNotFound)
        errorsFound += len(compsNotFound)
        for comp in compsNotFound:
            self.insertError(test, "ERROR : Compulsory message missing (" + comp + ")")
        return errorsFound
    def extractErrorsFrom(self, test, fileStem, compsNotFound):
        errorsFound = 0
        logFile = self.getLogFile(test, fileStem)
        for line in open(logFile).xreadlines():
            for error in self.internalErrorList:
                if line.find(error) != -1:
                    errorsFound += 1
                    self.insertError(test, "Internal ERROR (" + error + ")")
            for comp in compsNotFound:
                if line.find(comp) != -1:
                    compsNotFound.remove(comp)
        return errorsFound
    def setUpApplication(self, app):
        CheckLogFilePredictions.setUpApplication(self, app)
        self.internalErrorList = app.getConfigList("internal_error_text")
        self.internalCompulsoryList = app.getConfigList("internal_compulsory_text")

def pad(str, padSize):
    return str.ljust(padSize)
        
class PredictionStatistics(plugins.Action):
    def __init__(self, args):
        arg, val = args[0].split("=")
        versions = val.split(",")
        self.referenceChecker = CheckPredictions(versions[0])
        self.currentChecker = None
        if len(versions) > 1:
            self.currentChecker = CheckPredictions(versions[1])
    def setUpSuite(self, suite):
        self.suiteName = suite.name + os.linesep + "   "
    def __call__(self, test):
        refErrors = self.referenceChecker(test)
        currErrors = 0
        if self.currentChecker:
            currErrors = self.currentChecker(test)
        if refErrors + currErrors > 0:
            print self.suiteName + test.name.ljust(30) + "\t", refErrors, currErrors
            self.suiteName = "   "
    def setUpApplication(self, app):
        self.referenceChecker.setUpApplication(app)
        if self.currentChecker:
            self.currentChecker.setUpApplication(app)
