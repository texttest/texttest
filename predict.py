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

class CheckPredictions(plugins.Action):
    def __init__(self):
        self.logFile = None
        self.internalErrorList = None
    def __repr__(self):
        return "Checking predictions for"
    def __del__(self):
        # Useful to have a nice list at the end...
        for test, error in testBrokenPredictionMap.items():
            print error, "in", test, "(under", test.getRelPath() + ")"
    def __call__(self, test):
        if len(self.internalErrorList) == 0:
            return

        logFile = test.getTmpFileName(self.logFile, "r")
        if not os.path.isfile(logFile):
            logFile = test.makeFileName(self.logFile)
        
        for line in open(logFile).xreadlines():
            for error in self.internalErrorList:
                if line.find(error) != -1:
                    testBrokenPredictionMap[test] = "Internal Error (" + error + ")" 
    def setUpApplication(self, app):
        self.logFile = app.getConfigValue("log_file")
        self.internalErrorList = app.getConfigList("internal_error_text")
        
