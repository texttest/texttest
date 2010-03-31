#!/usr/bin/env python

import plugins, os, string, shutil, sys, logging
from ConfigParser import ConfigParser, NoOptionError
from copy import copy
from ndict import seqdict

plugins.addCategory("bug", "known bugs", "had known bugs")
plugins.addCategory("badPredict", "internal errors", "had internal errors")
plugins.addCategory("crash", "CRASHED")

# For backwards compatibility...
class FailedPrediction(plugins.TestState):
    def getTypeBreakdown(self):
        if self.category == "bug":
            return "success", self.briefText
        else:
            return "failure", self.briefText

class Bug:
    def __cmp__(self, other):
        return cmp(self.getPriority(), other.getPriority())
                   
    def findCategory(self, internalError):
        if internalError:
            return "badPredict"
        else:
            return "bug"

    def isCancellation(self):
        return False

class BugSystemBug(Bug):
    def __init__(self, bugSystem, bugId):
        self.bugId = bugId
        self.bugSystem = bugSystem

    def getPriority(self):
        return 2
        
    def findInfo(self, test):
        location = test.getCompositeConfigValue("bug_system_location", self.bugSystem)
        username = test.getCompositeConfigValue("bug_system_username", self.bugSystem)
        password = test.getCompositeConfigValue("bug_system_password", self.bugSystem)
        exec "from " + self.bugSystem + " import findBugInfo as _findBugInfo"
        status, bugText, isResolved = _findBugInfo(self.bugId, location, username, password)
        category = self.findCategory(isResolved)
        briefText = "bug " + self.bugId + " (" + status + ")"
        return category, briefText, bugText

    
class UnreportedBug(Bug):
    def __init__(self, fullText, briefText, internalError):
        self.fullText = fullText
        self.briefText = briefText
        self.internalError = internalError

    def isCancellation(self):
        return not self.briefText and not self.fullText

    def getPriority(self):
        if self.internalError:
            return 1
        else:
            return 3
        
    def findInfo(self, *args):
        return self.findCategory(self.internalError), self.briefText, self.fullText


class BugTrigger:
    def __init__(self, getOption):
        self.textTrigger = plugins.TextTrigger(getOption("search_string"))
        self.triggerHosts = self.getTriggerHosts(getOption)
        self.checkUnchanged = int(getOption("trigger_on_success", "0"))
        self.reportInternalError = int(getOption("internal_error", "0"))
        self.ignoreOtherErrors = int(getOption("ignore_other_errors", self.reportInternalError))
        self.bugInfo = self.createBugInfo(getOption)
        self.diag = logging.getLogger("Check For Bugs")
    def __repr__(self):
        return repr(self.textTrigger)
    def getTriggerHosts(self, getOption):
        hostStr = getOption("execution_hosts")
        if hostStr:
            return hostStr.split(",")
        else:
            return []
    def createBugInfo(self, getOption):
        bugSystem = getOption("bug_system")
        if bugSystem:
            return BugSystemBug(bugSystem, getOption("bug_id"))
        else:
            return UnreportedBug(getOption("full_description"), getOption("brief_description"), self.reportInternalError)
    def matchesText(self, line):
        return self.textTrigger.matches(line)
    def findBug(self, execHosts, isChanged, multipleDiffs, line=None):
        if not self.checkUnchanged and not isChanged:
            self.diag.info("File not changed, ignoring")
            return
        if multipleDiffs and not self.ignoreOtherErrors:
            self.diag.info("Multiple differences present, allowing others through")
            return
        if line is not None and not self.textTrigger.matches(line):
            return
        if self.hostsMatch(execHosts):
            return self.bugInfo
        else:
            self.diag.info("No match " + repr(execHosts) + " with " + repr(self.triggerHosts))
    def hostsMatch(self, execHosts):
        if len(self.triggerHosts) == 0:
            return True
        for host in execHosts:
            if not host in self.triggerHosts:
                return False
        return True

class FileBugData:
    def __init__(self):
        self.presentList = []
        self.absentList = []
        self.checkUnchanged = False
        self.diag = logging.getLogger("Check For Bugs")

    def addBugTrigger(self, getOption):
        bugTrigger = BugTrigger(getOption)
        if bugTrigger.checkUnchanged:
            self.checkUnchanged = True
        if getOption("trigger_on_absence", False):
            self.absentList.append(bugTrigger)
        else:
            self.presentList.append(bugTrigger)

    def findBugs(self, fileName, execHosts, isChanged, multipleDiffs):
        self.diag.info("Looking for bugs in " + fileName)
        if not self.checkUnchanged and not isChanged:
            self.diag.info("File not changed, ignoring all bugs")
            return []
        if not os.path.isfile(fileName):
            self.diag.info("File doesn't exist, checking only for absence bugs")
            return self.findAbsenceBugs(self.absentList, execHosts, isChanged, multipleDiffs)
        
        return self.findBugsInText(open(fileName).readlines(), execHosts, isChanged, multipleDiffs)

    def findBugsInText(self, lines, execHosts, isChanged=True, multipleDiffs=False):
        currAbsent = copy(self.absentList)
        bugs = []
        for line in lines:
            for bugTrigger in self.presentList:
                self.diag.info("Checking for existence of " + repr(bugTrigger))
                bug = bugTrigger.findBug(execHosts, isChanged, multipleDiffs, line)
                if bug:
                    bugs.append(bug)
            for bugTrigger in currAbsent:
                if bugTrigger.matchesText(line):
                    currAbsent.remove(bugTrigger)

        return bugs + self.findAbsenceBugs(currAbsent, execHosts, isChanged, multipleDiffs)

    def findAbsenceBugs(self, absentList, execHosts, isChanged, multipleDiffs):
        bugs = []
        for bugTrigger in absentList:
            bug = bugTrigger.findBug(execHosts, isChanged, multipleDiffs)
            if bug:
                bugs.append(bug)
        return bugs


class ParseMethod:
    def __init__(self, parser, section):
        self.parser = parser
        self.section = section
    def __call__(self, option, default=""):
        try:
            return self.parser.get(self.section, option)
        except NoOptionError:
            return default

class BugMap(seqdict):
    def checkUnchanged(self):
        for bugData in self.values():
            if bugData.checkUnchanged:
                return True
        return False
    def readFromFile(self, fileName):
        parser = self.makeParser(fileName)
        if parser:
            self.readFromParser(parser)

    def lookupSection(self, name, fileName, realLookup):
        msg = "Bug file at " + fileName + " has duplicated sections named '" + name + "', the later ones will be ignored"
        plugins.printWarning(msg, stderr=True, stdout=False)
        return realLookup(name)
    
    def makeParser(self, fileName):
        parser = ConfigParser()
        # Default behaviour transforms to lower case: we want case-sensitive
        parser.optionxform = str
        parser._sections = seqdict()
        # There isn't a nice way to change the behaviour on getting a duplicate section
        # so we use a nasty way :)
        realLookup = parser._sections.__getitem__
        parser._sections.__getitem__ = plugins.Callable(self.lookupSection, fileName, realLookup)
        try:
            parser.read(fileName)
            parser._sections.__getitem__ = realLookup
            return parser
        except:
            plugins.printWarning("Bug file at " + fileName + " not understood, ignoring", stderr=True, stdout=False)
    def readFromParser(self, parser):
        for section in reversed(sorted(parser.sections())):
            getOption = ParseMethod(parser, section)
            fileStem = getOption("search_file")
            self.setdefault(fileStem, FileBugData()).addBugTrigger(getOption)

    
class CheckForCrashes(plugins.Action):
    def __init__(self):
        self.diag = logging.getLogger("check for crashes")

    def __call__(self, test):
        if test.state.category == "killed":
            return
        # Hard-coded prediction: check test didn't crash
        comparison, newList = test.state.findComparison("stacktrace")
        if comparison and comparison.newResult():
            stackTraceFile = comparison.tmpFile
            self.diag.info("Parsing " + stackTraceFile)
            summary, errorInfo = self.parseStackTrace(test, stackTraceFile)
            
            newState = copy(test.state)
            newState.removeComparison("stacktrace")
        
            crashState = FailedPrediction("crash", errorInfo, summary)
            newState.setFailedPrediction(crashState)
            test.changeState(newState)
            os.remove(stackTraceFile)

    def parseStackTrace(self, test, stackTraceFile):
        lines = open(stackTraceFile).readlines()
        if len(lines) > 2:
            return lines[0].strip(), string.join(lines[2:], "")
        else:
            errFile = test.makeTmpFileName("stacktrace.collate_errs", forFramework=1)
            script = test.getCompositeConfigValue("collate_script", "stacktrace")[0]
            return "core not parsed", "The core file could not be parsed. Errors from '" + script + "' follow :\n" + open(errFile).read()


class CheckForBugs(plugins.Action):
    def __init__(self):
        self.diag = logging.getLogger("Check For Bugs")
    def callDuringAbandon(self, test):
        # want to be able to mark UNRUNNABLE tests as known bugs too...
        return test.state.lifecycleChange != "complete"
    def __call__(self, test):
        activeBugs = self.readBugs(test)
        if not activeBugs.checkUnchanged() and not test.state.hasFailed():
            self.diag.info(repr(test) + " succeeded, not looking for bugs")
            return

        bug = self.findBug(test, activeBugs)
        if bug:
            category, briefText, fullText = bug.findInfo(test)
            self.diag.info("Changing to " + category + " with text " + briefText)
            bugState = FailedPrediction(category, fullText, briefText, completed=1)
            self.changeState(test, bugState)
            
    def findBug(self, test, activeBugs):
        multipleDiffs = self.hasMultipleDifferences(test)
        bugs = []
        for stem, fileBugData in activeBugs.items():
            bugs += self.findBugsInFile(test, stem, fileBugData, multipleDiffs)

        unblockedBugs = self.findUnblockedBugs(bugs)
        if len(unblockedBugs) > 0:
            unblockedBugs.sort()
            return unblockedBugs[0]

    def findUnblockedBugs(self, bugs):
        unblockedBugs = []
        for bug in bugs:
            if bug.isCancellation():
                return unblockedBugs
            else:
                unblockedBugs.append(bug)
        return unblockedBugs
        
    def findBugsInFile(self, test, stem, fileBugData, multipleDiffs):
        self.diag.info("Looking for bugs in file " + stem)
        if stem == "free_text":
            return fileBugData.findBugsInText(test.state.freeText.split("\n"), test.state.executionHosts)
        elif test.state.hasResults():
            # bugs are only relevant if the file itself is changed, unless marked to trigger on success also
            isChanged = self.fileChanged(test, stem)
            fileName = test.makeTmpFileName(stem)
            return fileBugData.findBugs(fileName, test.state.executionHosts, isChanged, multipleDiffs)
        else:
            return []

    def changeState(self, test, bugState):
        if hasattr(test.state, "failedPrediction"):
            # if we've already compared, slot our things into the comparison object
            newState = copy(test.state)
            newState.setFailedPrediction(bugState, usePreviousText=True)
            test.changeState(newState)
        else:
            test.changeState(bugState)

    def hasMultipleDifferences(self, test):
        if not test.state.hasResults():
            # check for unrunnables...
            return False
        comparisons = test.state.getComparisons()
        diffCount = len(comparisons)
        if diffCount <= 1:
            return False
        perfStems = test.state.getPerformanceStems(test)
        for comp in comparisons:
            if comp.stem in perfStems:
                diffCount -= 1
        return diffCount > 1
    def fileChanged(self, test, stem):
        comparison, list = test.state.findComparison(stem)
        return bool(comparison)
    def readBugs(self, test):
        bugMap = BugMap()
        # Mostly for backwards compatibility, reverse the list so that more specific bugs
        # get checked first.
        for bugFile in reversed(test.getAllPathNames("knownbugs")):
            self.diag.info("Reading bugs from file " + bugFile)
            bugMap.readFromFile(bugFile)
        return bugMap
            
# For migrating from knownbugs files which are from TextTest 3.7 and older
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
                plugins.printWarning("Bug file at " + bugFileName + " not understood, ignoring", stderr=True, stdout=False)
                continue
            if not parser.has_section("Migrated section 1"):
                self.describe(test, " - " + os.path.basename(bugFileName))
                sys.stdout.flush()
                self.updateFile(bugFileName, parser)
            else:
                self.describe(test, " (already migrated)")
    def updateFile(self, bugFileName, parser):
        newBugFileName = bugFileName + ".new"
        newBugFile = open(newBugFileName, "w")
        self.writeNew(parser, newBugFile)
        newBugFile.close()
        print "Old File:\n" + open(bugFileName).read()
        print "New File:\n" + open(newBugFileName).read()
        shutil.move(newBugFileName, bugFileName)
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
