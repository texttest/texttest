#!/usr/bin/env python

import plugins, os, string
from ConfigParser import ConfigParser
from predict import FailedPrediction
from copy import copy

plugins.addCategory("bug", "known bugs", "had known bugs")

class KnownBug(FailedPrediction):
    def __init__(self, bugDesc):
        self.bugStatus = "UNREPORTED"
        self.diag = plugins.getDiagnostics("known bugs")
        fullBugText = bugDesc
        briefBugText = "unreported bug"
        if self.isNumber(bugDesc):
            fullBugText = os.popen(self.getBugcli() + " -b " + bugDesc).read()
            self.diag.info("Found bug with text " + fullBugText)
            self.bugStatus = self.findStatus(fullBugText)
            briefBugText = "bug " + bugDesc + " (" + self.bugStatus + ")"
        FailedPrediction.__init__(self, self.findCategory(), briefText=briefBugText, freeText=fullBugText, completed = 1)
    def getBugcli(self):
        if os.name == "posix":
            return "bugcli"
        # Windows requires file extensions, but unknown what it needs for bugcli :)
        for dir in os.environ["PATH"].split(";"):
            for file in os.listdir(dir):
                if file.startswith("bugcli."):
                    return file
        return "bugcli"
    def isNumber(self, desc):
        for letter in desc:
            if not letter in string.digits:
                return 0
        return 1
    def findStatus(self, description):
        if len(description) == 0:
            return "no bugcli found"
        for line in description.split("\n"):
            words = line.split()
            if len(words) < 4:
                continue
            if words[2].startswith("Status"):
                return words[3]
        return "no such bug"
    def findCategory(self):
        if self.bugStatus == "RESOLVED" or self.bugStatus == "CLOSED":
            return "badPredict"
        else:
            return "bug"
    def isSaveable(self):
        return self.findCategory() != "bug"
    def getTypeBreakdown(self):
        return "success", self.briefText

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
        if not test.state.hasFailed():
            return

        self.readBugs(test)
        for stem, entryDict in self.bugMap.items():
            # bugs are only relevant if the file itself is changed
            comparison, list = test.state.findComparison(stem)
            if not comparison:
                continue
            fileName = test.makeFileName(stem, temporary=1)
            if os.path.isfile(fileName):
                for line in open(fileName).xreadlines():
                    for trigger, bugDesc in entryDict.items():
                        if trigger.matches(line):
                            newState = copy(test.state)
                            newState.setFailedPrediction(KnownBug(bugDesc))
                            test.changeState(newState)
        self.unreadBugs(test)
    def readBugs(self, suite):
        if not self.testBugParserMap.has_key(suite):
            bugFile = suite.makeFileName("knownbugs")
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
                trigger = plugins.TextTrigger(bugText)
                self.bugMap[fileStem][trigger] = bugId
    def unreadBugs(self, suite):
        if not self.testBugParserMap.has_key(suite):
            return
        
        testBugParser = self.testBugParserMap[suite]
        for fileStem in testBugParser.sections():
            for bugText in testBugParser.options(fileStem):
                self.diag.info("Removing entry from bug map " + fileStem + " : " + bugText)
                trigger = self.findTrigger(fileStem, bugText)
                del self.bugMap[fileStem][trigger]
    def findTrigger(self, fileStem, bugText):
        for trigger in self.bugMap[fileStem].keys():
            if trigger.text == bugText:
                return trigger
            
