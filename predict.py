#!/usr/local/bin/python

helpDescription = """
It is possible to specify predictively how an application behaves. In general this works by reading
the config file list "internal_error_text" and searching the resulting log file for it. If this text
is found, a warning is generated. predict.CheckPredictions can also be run as a standalone action to
check the standard test results for internal errors.
"""

import os, filecmp, string, plugins

# Map from test to broken prediction text
testBrokenPredictionMap = {}

class CheckLogFilePredictions(plugins.Action):
    def __init__(self):
        self.logFile = None
    def __del__(self):
        # Useful to have a nice list at the end...
        for test, error in testBrokenPredictionMap.items():
            print error, "in", test, "(under", test.getRelPath() + ")"
    def getLogFile(self, test):
        logFile = test.getTmpFileName(self.logFile, "r")
        if not os.path.isfile(logFile):
            logFile = test.makeFileName(self.logFile)
        return logFile
    def insertError(self, test, error):
        testBrokenPredictionMap[test] = error
    def setUpApplication(self, app):
        app.setConfigDefault("log_file", "output")
        self.logFile = app.getConfigValue("log_file")   

class CheckPredictions(CheckLogFilePredictions):
    def __init__(self):
        CheckLogFilePredictions.__init__(self)
        self.internalErrorList = None
    def __repr__(self):
        return "Checking predictions for"
    def __call__(self, test):
        if len(self.internalErrorList) == 0:
            return

        logFile = self.getLogFile(test)
        for line in open(logFile).xreadlines():
            for error in self.internalErrorList:
                if line.find(error) != -1:
                    self.insertError(test, "Internal Error (" + error + ")")
    def setUpApplication(self, app):
        CheckLogFilePredictions.setUpApplication(self, app)
        self.internalErrorList = app.getConfigList("internal_error_text")
        
