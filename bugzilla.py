#!/usr/bin/env python

import plugins, os
from ConfigParser import ConfigParser

class CheckForBugs(plugins.Action):
    def __init__(self):
        self.bugMap = {}
        self.testBugParserMap = {}
        self.diag = plugins.getDiagnostics("Check For Bugs")
    def setUpSuite(self, suite):
        self.readBugs(suite)
    def tearDownSuite(self, suite):
        self.unreadBugs(suite)
    def __call__(self, test):
        if test.state != test.FAILED:
            return

        self.readBugs(test)
        for stem, entryDict in self.bugMap.items():
            fileName = test.makeFileName(stem, temporary=1)
            if os.path.isfile(fileName):
                for line in open(fileName).xreadlines():
                    for text, bugNum in entryDict.items():
                        if line.find(text) != -1:
                            test.stateDetails.failedPrediction = os.popen("bugcli -b " + bugNum).read()
        self.unreadBugs(test)
    def readBugs(self, suite):
        if not self.testBugParserMap.has_key(suite):
            bugFile = suite.makeFileName("bugzilla")
            if os.path.isfile(bugFile):
                self.diag.info("Reading bugs from file " + bugFile)
                parser = ConfigParser()
                # Default behaviour transforms to lower case: we want case-sensitive
                parser.optionxform = str
                try:
                    parser.read(bugFile)
                except:
                    print "Bug file at", bugFile, "not understood, ignoring"
                    return
                
                self.testBugParserMap[suite] = parser    
            else:
                return
            
        testBugParser = self.testBugParserMap[suite]
        for fileStem in testBugParser.sections():
            if not self.bugMap.has_key(fileStem):
                self.bugMap[fileStem] = {}
            for bugText in testBugParser.options(fileStem):
                bugId = testBugParser.get(fileStem, bugText)
                self.diag.info("Adding entry to bug map " + fileStem + " : " + bugText + " : " + bugId)
                self.bugMap[fileStem][bugText] = bugId
    def unreadBugs(self, suite):
        if not self.testBugParserMap.has_key(suite):
            return
        
        testBugParser = self.testBugParserMap[suite]
        for fileStem in testBugParser.sections():
            for bugText in testBugParser.options(fileStem):
                self.diag.info("Removing entry from bug map " + fileStem + " : " + bugText)
                del self.bugMap[fileStem][bugText]
                bugId = testBugParser.get(fileStem, bugText)
