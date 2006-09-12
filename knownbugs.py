#!/usr/bin/env python

import plugins, os, string
from ConfigParser import ConfigParser, NoOptionError
from predict import FailedPrediction
from copy import copy

plugins.addCategory("bug", "known bugs", "had known bugs")

class KnownBugState(FailedPrediction):
    def isSaveable(self):
        return self.category != "bug"
    def getTypeBreakdown(self):
        return "success", self.briefText

class Bug:
    def findCategory(self, internalError):
        if internalError:
            return "badPredict"
        else:
            return "bug"

class BugSystemBug(Bug):
    def __init__(self, bugSystem, bugId):
        self.bugId = bugId
        self.bugSystem = bugSystem
    def findInfo(self):
        exec "from " + self.bugSystem + " import findBugText, findStatus, isResolved"
        bugText = findBugText(self.bugId)
        status = findStatus(bugText)
        category = self.findCategory(isResolved(status))
        briefText = "bug " + self.bugId + " (" + status + ")"
        return category, briefText, bugText
    
class UnreportedBug(Bug):
    def __init__(self, fullText, briefText, internalError):
        self.fullText = fullText
        self.briefText = briefText
        self.internalError = internalError
    def findInfo(self):
        return self.findCategory(self.internalError), self.briefText, self.fullText

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
            fileName = test.makeTmpFileName(stem)
            if os.path.isfile(fileName):
                for line in open(fileName).xreadlines():
                    for trigger, bug in entryDict.items():
                        if trigger.matches(line):
                            newState = copy(test.state)
                            category, briefText, fullText = bug.findInfo()
                            bugState = KnownBugState(category, fullText, briefText)
                            newState.setFailedPrediction(bugState)
                            test.changeState(newState)
        self.unreadBugs(test)
    def makeBugParser(self, suite):
        bugFile = suite.getFileName("knownbugs")
        if not bugFile:
            return

        self.diag.info("Reading bugs from file " + bugFile)
        parser = ConfigParser()
        # Default behaviour transforms to lower case: we want case-sensitive
        parser.optionxform = str
        try:
            parser.read(bugFile)
            return parser
        except:
            print "Bug file at", bugFile, "not understood, ignoring"
    def readBugs(self, suite):
        if not self.testBugParserMap.has_key(suite):
            self.testBugParserMap[suite] = self.makeBugParser(suite)
            
        testBugParser = self.testBugParserMap.get(suite)
        if not testBugParser:
            return
        for section in testBugParser.sections():
            fileStem, bugText = self.getSearchInfo(testBugParser, section)
            if not self.bugMap.has_key(fileStem):
                self.bugMap[fileStem] = {}
            self.diag.info("Adding entry to bug map " + fileStem + " : " + bugText)
            trigger = plugins.TextTrigger(bugText)
            self.bugMap[fileStem][trigger] = self.createBugInfo(testBugParser, section)
    def getSearchInfo(self, parser, section):
        return parser.get(section, "search_file"), parser.get(section, "search_string")
    def createBugInfo(self, parser, section):
        try:
            bugSystem = parser.get(section, "bug_system")
            return BugSystemBug(bugSystem, parser.get(section, "bug_id"))
        except NoOptionError:
            return UnreportedBug(parser.get(section, "full_description"), \
                                 parser.get(section, "brief_description"), int(parser.get(section, "internal_error")))
    def unreadBugs(self, suite):
        testBugParser = self.testBugParserMap.get(suite)
        if not testBugParser:
            return
        
        for section in testBugParser.sections():
            fileStem, bugText = self.getSearchInfo(testBugParser, section)
            self.diag.info("Removing entry from bug map " + fileStem + " : " + bugText)
            trigger = self.findTrigger(fileStem, bugText)
            del self.bugMap[fileStem][trigger]
    def findTrigger(self, fileStem, bugText):
        for trigger in self.bugMap[fileStem].keys():
            if trigger.text == bugText:
                return trigger
            
class MigrateFiles(plugins.Action):
    def setUpSuite(self, suite):
        self.migrate(suite)
    def __call__(self, test):
        self.migrate(test)
    def __repr__(self):
        return "Migrating knownbugs file in"
    def migrate(self, test):
        for bugFileName in test.findAllStdFiles("knownbugs"):
            parser = ConfigParser()
            # Default behaviour transforms to lower case: we want case-sensitive
            parser.optionxform = str
            try:
                parser.read(bugFileName)
            except:
                print "Bug file at", bugFileName, "not understood, ignoring"
                continue
            if not parser.has_section("Migrated section 1"):
                self.describe(test, " - " + os.path.basename(bugFileName))
                self.updateFile(bugFileName, parser)
            else:
                self.describe(test, " (already migrated)")
    def updateFile(self, bugFileName, parser):
        newBugFileName = bugFileName + ".new"
        newBugFile = open(newBugFileName, "w")
        self.writeNew(parser, newBugFile)
        newBugFile.close()
        os.system("diff " + bugFileName + " " + newBugFileName)
        os.rename(newBugFileName, bugFileName)
    def writeNew(self, parser, newBugFile):
        sectionNo = 0
        for fileStem in parser.sections():
            for bugText in parser.options(fileStem):
                bugId = parser.get(fileStem, bugText)
                sectionNo += 1
                self.writeSection(newBugFile, sectionNo, fileStem, bugText, bugId)
    def writeSection(self, newBugFile, sectionNo, fileStem, bugText, bugId):
        newBugFile.write("[Migrated section " + str(sectionNo) + "]\n")
        newBugFile.write("search_string:" + bugText + "\n")
        newBugFile.write("search_file:" + fileStem + "\n")
        bugSystem = self.findBugSystem(bugId)
        if bugSystem:
            newBugFile.write("bug_system:" + bugSystem + "\n")
            newBugFile.write("bug_id:" + bugId + "\n")
        else:
            newBugFile.write("full_description:" + bugId + "\n")
            newBugFile.write("brief_description:unreported bug\n")
            newBugFile.write("internal_error:0\n")
        newBugFile.write("\n")
    def findBugSystem(self, bugId):
        for letter in bugId:
            if not letter in string.digits:
                return None
        return "bugzilla"
