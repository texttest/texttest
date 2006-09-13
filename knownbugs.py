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
    def __init__(self, bugSystem, bugId, ignoreFlag):
        self.bugId = bugId
        self.bugSystem = bugSystem
        self.ignoreFlag = ignoreFlag
    def ignoreOtherErrors(self):
        return self.ignoreFlag
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
    def ignoreOtherErrors(self):
        return self.internalError        

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
        multipleErrors = len(test.state.getComparisons()) > 1
        for stem, info in self.bugMap.items():
            # bugs are only relevant if the file itself is changed
            comparison, list = test.state.findComparison(stem)
            if not comparison:
                continue
            fileName = test.makeTmpFileName(stem)
            bug = self.findBug(fileName, test.state.executionHosts, info)
            if bug and (not multipleErrors or bug.ignoreOtherErrors()):
                category, briefText, fullText = bug.findInfo()
                newState = copy(test.state)
                bugState = KnownBugState(category, fullText, briefText)
                newState.setFailedPrediction(bugState)
                test.changeState(newState)
        self.unreadBugs(test)
    def findBug(self, fileName, execHosts, entryInfo):
        if not os.path.isfile(fileName):
            return
        presentList, absentList = entryInfo
        currAbsent = copy(absentList)
        for line in open(fileName).xreadlines():
            for trigger, triggerHosts, bug in presentList:
                if trigger.matches(line) and self.hostsMatch(triggerHosts, execHosts):
                    return bug
            for entry in currAbsent:
                trigger, triggerHosts, bug = entry
                if trigger.matches(line):
                    currAbsent.remove(entry)
                    break
        for trigger, triggerHosts, bug in currAbsent:
            if self.hostsMatch(triggerHosts, execHosts):
                return bug
    def hostsMatch(self, triggerHosts, execHosts):
        if len(triggerHosts) == 0:
            return True
        for host in execHosts:
            if not host in triggerHosts:
                return False
        return True
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
                self.bugMap[fileStem] = [], []
            self.diag.info("Adding entry to bug map " + fileStem + " : " + bugText)
            trigger = plugins.TextTrigger(bugText)
            execHosts = self.getExecutionHosts(testBugParser, section)
            presentList, absentList = self.bugMap[fileStem]
            bugInfo = self.createBugInfo(testBugParser, section)
            if self.checkForAbsence(testBugParser, section):
                absentList.append((trigger, execHosts, bugInfo))
            else:
                presentList.append((trigger, execHosts, bugInfo))
    def checkForAbsence(self, parser, section):
        try:
            return parser.get(section, "trigger_on_absence")
        except NoOptionError:
            return False
    def getSearchInfo(self, parser, section):
        return parser.get(section, "search_file"), parser.get(section, "search_string")
    def getExecutionHosts(self, parser, section):
        try:
            stringVal = parser.get(section, "execution_hosts")
            return stringVal.split(",")
        except NoOptionError:
            return []
    def createBugInfo(self, parser, section):
        internalErrorFlag = self.getIntErrFlag(parser, section)
        try:
            bugSystem = parser.get(section, "bug_system")
            return BugSystemBug(bugSystem, parser.get(section, "bug_id"), internalErrorFlag)
        except NoOptionError:
            return UnreportedBug(parser.get(section, "full_description"), \
                                 parser.get(section, "brief_description"), internalErrorFlag)
    def getIntErrFlag(self, parser, section):
        try:
            return int(parser.get(section, "internal_error"))
        except NoOptionError:
            return 0
    def unreadBugs(self, suite):
        testBugParser = self.testBugParserMap.get(suite)
        if not testBugParser:
            return
        
        for section in testBugParser.sections():
            fileStem, bugText = self.getSearchInfo(testBugParser, section)
            self.diag.info("Removing entry from bug map " + fileStem + " : " + bugText)
            presentList, absentList = self.bugMap[fileStem]
            self.removeFrom(presentList, bugText)
            self.removeFrom(absentList, bugText)
    def removeFrom(self, list, bugText):
        for item in list:
            trigger, execHosts, bug = item
            if trigger.text == bugText:
                list.remove(item)
                return
            
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
