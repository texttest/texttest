#!/usr/local/bin/python

helpDescription = """
It is possible to specify predictively how an application behaves. In general this works by reading
the config file list "internal_error_text" and searching the resulting log file for it. If this text
is found, a warning is generated. Conversely, you can specify the list "internal_compulsory_text" which
raises a warning if the text is not found. predict.CheckPredictions can also be run as a standalone action to
check the standard test results for internal errors.
"""

import os, filecmp, string, plugins, copy

class CheckLogFilePredictions(plugins.Action):
    def __init__(self):
        self.logFile = None
    def getLogFile(self, test):
        logFile = test.getTmpFileName(self.logFile, "r")
        if not os.path.isfile(logFile):
            logFile = test.makeFileName(self.logFile)
        return logFile
    def insertError(self, test, error):
        test.changeState(test.FAILED, error)
    def setUpApplication(self, app):
        app.setConfigDefault("log_file", "output")
        self.logFile = app.getConfigValue("log_file")   

class CheckPredictions(CheckLogFilePredictions):
    def __init__(self):
        CheckLogFilePredictions.__init__(self)
        self.internalErrorList = None
        self.internalCompulsoryList = None
    def __repr__(self):
        return "Checking predictions for"
    def __call__(self, test):
        # Hard-coded prediction: check test didn't crash
        stackTraceFile = test.getTmpFileName("stacktrace", "r")
        if os.path.isfile(stackTraceFile):
            errorInfo = open(stackTraceFile).read()
            self.insertError(test, errorInfo)
            os.remove(stackTraceFile)
            return
        
        if len(self.internalErrorList) == 0 and len(self.internalCompulsoryList) == 0:
            return
                
        logFile = self.getLogFile(test)
        compsNotFound = copy.deepcopy(self.internalCompulsoryList)
        for line in open(logFile).xreadlines():
            for error in self.internalErrorList:
                if line.find(error) != -1:
                    self.insertError(test, "Internal ERROR (" + error + ")")
            for comp in compsNotFound:
                if line.find(comp) != -1:
                    compsNotFound.remove(comp)
        for comp in compsNotFound:
            self.insertError(test, "ERROR : Compulsory message missing (" + comp + ")")
    def setUpApplication(self, app):
        CheckLogFilePredictions.setUpApplication(self, app)
        self.internalErrorList = app.getConfigList("internal_error_text")
        self.internalCompulsoryList = app.getConfigList("internal_compulsory_text")
