import os
import string
import shutil
import sys
import logging
import glob
import re
from texttestlib import plugins
from configparser import ConfigParser, NoOptionError
from copy import copy
from collections import OrderedDict

plugins.addCategory("bug", "known bugs", "had known bugs")
plugins.addCategory("badPredict", "internal errors", "had internal errors")
plugins.addCategory("crash", "CRASHED")

# For backwards compatibility...


class FailedPrediction(plugins.TestState):
    def getExitCode(self):
        return int(self.category != "bug")

    def getTypeBreakdown(self):
        status = "failure" if self.getExitCode() else "success"
        return status, self.briefText


class Bug:
    rerunLine = "(NOTE: Test was run %d times in total and each time encountered this issue."
    prevResultLine = "Results of previous runs can be found in framework_tmp/backup.previous.* under the sandbox directory.)"

    def __init__(self, priority, rerunCount, rerunOnly, allowAllRerunsFail):
        self.priority = priority
        self.rerunCount = rerunCount
        self.rerunOnly = rerunOnly
        self.allowAllRerunsFail = allowAllRerunsFail

    def findCategory(self, internalError):
        if internalError or (self.rerunCount and not self.allowAllRerunsFail):
            return "badPredict"
        else:
            return "bug"

    def isCancellation(self):
        return False

    def getRerunText(self):
        if self.rerunCount:
            return "\n" + self.rerunLine % (self.rerunCount + 1) + "\n" + self.prevResultLine + "\n\n"
        else:
            return ""


class BugSystemBug(Bug):
    def __init__(self, bugSystem, bugId, priorityStr, *args):
        self.bugId = bugId
        self.bugSystem = bugSystem
        prio = int(priorityStr) if priorityStr else 20
        Bug.__init__(self, prio, *args)

    def __repr__(self):
        return self.bugId

    def findInfo(self, test):
        location = test.getCompositeConfigValue("bug_system_location", self.bugSystem)
        username = test.getCompositeConfigValue("bug_system_username", self.bugSystem)
        password = test.getCompositeConfigValue("bug_system_password", self.bugSystem)
        status, bugText, isResolved, bugId = self.findBugInfo(self.bugId, location, username, password)
        self.bugId = bugId
        category = self.findCategory(isResolved)
        briefText = "bug " + self.bugId + " (" + status + ")"
        return category, briefText, self.getRerunText() + bugText

    def findBugInfo(self, bugId, location, username, password):
        namespace = {}
        try:
            exec("from ." + self.bugSystem + " import findBugInfo as _findBugInfo", globals(), namespace)
            return namespace["_findBugInfo"](self.bugId, location, username, password)  # @UndefinedVariable
        except ImportError:
            return "unknown", "Bug " + bugId + " in unknown bug system '" + self.bugSystem + "'", False, bugId

class UnreportedBug(Bug):
    def __init__(self, fullText, briefText, internalError, priorityStr, *args):
        self.fullText = fullText
        self.briefText = briefText
        self.internalError = internalError
        prio = self.getPriority(priorityStr)
        Bug.__init__(self, prio, *args)

    def __repr__(self):
        return self.briefText

    def isCancellation(self):
        return not self.rerunOnly and not self.briefText and not self.fullText

    def getPriority(self, priorityStr):
        if priorityStr:
            return int(priorityStr)
        elif self.internalError:
            return 10
        else:
            return 30

    def findInfo(self, *args):
        return self.findCategory(self.internalError), self.briefText, self.getRerunText() + self.fullText


class BugTrigger:
    def __init__(self, getOption):
        useRegexp = int(getOption("use_regexp", "1"))
        searchStr = getOption("search_string").replace("\\n", "\n")
        self.textTrigger = plugins.MultilineTextTrigger(searchStr, useRegexp)
        self.triggerHosts = self.getTriggerHosts(getOption)
        self.checkUnchanged = int(getOption("trigger_on_success", "0"))
        self.reportInternalError = int(getOption("internal_error", "0"))
        self.ignoreOtherErrors = int(getOption("ignore_other_errors", self.reportInternalError))
        self.customTrigger = getOption("custom_trigger", "")
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
        prioStr = getOption("priority")
        rerunCount = int(getOption("rerun_count", "0"))
        rerunOnly = int(getOption("rerun_only", "0"))
        allowAllRerunsFail = int(getOption("allow_all_reruns_fail", "0"))
        if bugSystem:
            return BugSystemBug(bugSystem, getOption("bug_id"), prioStr, rerunCount, rerunOnly, allowAllRerunsFail)
        else:
            return UnreportedBug(getOption("full_description"), getOption("brief_description"), 
                                 self.reportInternalError, prioStr, rerunCount, rerunOnly, allowAllRerunsFail)

    def matchesText(self, line):
        return self.textTrigger.matches(line)

    def exactMatch(self, lines, **kw):
        updatedLines = [line for i, line in enumerate(lines) if i < len(lines) - 1] if lines[-1] == '' else lines
        if len(updatedLines) == len(self.textTrigger.triggers):
            for index, line in enumerate(updatedLines, start=1):
                # We must check that every line match because MultilineTextTrigger.matches method
                # returns True only when the match is complete
                if index < len(updatedLines):
                    if not self.textTrigger._matches(line)[1]:
                        return False
                else:
                    return self.hasBug(line, **kw)
        return False

    def customTriggerMatches(self, *args):
        module, method = self.customTrigger.split(".", 1)
        return plugins.importAndCall(module, method, *args)

    def hasBug(self, line, execHosts=[], isChanged=True, multipleDiffs=False, tmpDir=None):
        if not self.checkUnchanged and not isChanged:
            self.diag.info("File not changed, ignoring")
            return False
        if multipleDiffs and not self.ignoreOtherErrors:
            self.diag.info("Multiple differences present, allowing others through")
            return False
        if line is not None and not self.textTrigger.matches(line):
            return False

        if self.customTrigger and not self.customTriggerMatches(execHosts, tmpDir):
            return False

        if self.hostsMatch(execHosts):
            return True
        else:
            self.diag.info("No match " + repr(execHosts) + " with " + repr(self.triggerHosts))
            return False

    def findBugInfo(self, test, fileStem, absenceBug):
        category, briefText, fullText = self.bugInfo.findInfo(test)
        whatText = "FAILING to find text" if absenceBug else "text found"
        matchText = repr(self)
        if "\n" in matchText:
            matchText = "'''\n" + matchText + "\n'''"
        else:
            matchText = "'" + matchText + "'"
        fullText += "\n(This bug was triggered by " + whatText + " in " + \
            self.getFileText(fileStem) + " matching " + matchText + ")"
        return category, briefText, fullText

    def getFileText(self, fileStem):
        if fileStem == "free_text":
            return "the full difference report"
        elif fileStem == "brief_text":
            return "the brief text/details"
        else:
            return "file " + repr(fileStem)

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
        self.identicalList = []
        self.checkUnchanged = False
        self.diag = logging.getLogger("Check For Bugs")

    def addBugTrigger(self, getOption):
        bugTrigger = BugTrigger(getOption)
        if bugTrigger.checkUnchanged:
            self.checkUnchanged = True
        if getOption("trigger_on_absence", False):
            self.absentList.append(bugTrigger)
        elif getOption("trigger_on_identical", False):
            self.identicalList.append(bugTrigger)
        else:
            self.presentList.append(bugTrigger)

    def findBugs(self, fileName, execHosts, isChanged, multipleDiffs):
        if not self.checkUnchanged and not isChanged:
            self.diag.info("File not changed, ignoring all bugs")
            return []
        if not fileName:
            self.diag.info("File doesn't exist, checking only for absence bugs")
            return self.findAbsenceBugs(self.absentList, execHosts=execHosts, isChanged=isChanged, multipleDiffs=multipleDiffs, tmpDir=None)
        if not os.path.exists(fileName):
            raise plugins.TextTestError("The file '" + fileName +
                                        "' does not exist. Maybe it has been removed by an external process. ")

        self.diag.info("Looking for bugs in " + fileName)
        dirname = os.path.dirname(fileName)
        return self.findBugsInText(open(fileName).readlines(), execHosts=execHosts, isChanged=isChanged, multipleDiffs=multipleDiffs, tmpDir=dirname)

    def findBugsInText(self, lines, **kw):
        currAbsent = copy(self.absentList)
        bugs = []
        for bugTrigger in self.identicalList:
            if bugTrigger not in bugs and bugTrigger.exactMatch(lines, **kw):
                bugs.append(bugTrigger)
        for line in lines:
            self.diag.info("Checking " + repr(line))
            for bugTrigger in self.presentList:
                self.diag.info("Checking for existence of " + repr(bugTrigger))
                if bugTrigger not in bugs and bugTrigger.hasBug(line, **kw):
                    self.diag.info("FOUND!")
                    bugs.append(bugTrigger)
            toRemove = []
            for bugTrigger in currAbsent:
                self.diag.info("Checking for absence of " + repr(bugTrigger))
                if bugTrigger.matchesText(line):
                    self.diag.info("PRESENT!")
                    toRemove.append(bugTrigger)
            for bugTrigger in toRemove:
                currAbsent.remove(bugTrigger)

        return bugs + self.findAbsenceBugs(currAbsent, **kw)

    def findAbsenceBugs(self, absentList, **kw):
        bugs = []
        for bugTrigger in absentList:
            if bugTrigger not in bugs and bugTrigger.hasBug(None, **kw):
                bugs.append(bugTrigger)
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


class BugMap(OrderedDict):
    def checkUnchanged(self):
        for bugData in list(self.values()):
            if bugData.checkUnchanged:
                return True
        return False

    def readFromFile(self, fileName):
        parser = self.makeParser(fileName)
        if parser:
            self.readFromParser(parser)

    def readFromFileObject(self, f):
        parser = self.makeParserFromFileObject(f)
        if parser:
            self.readFromParser(parser)

    def makeParserFromFileObject(self, f):
        parser = ConfigParser()
        # Default behaviour transforms to lower case: we want case-sensitive
        parser.optionxform = str
        parser.readfp(f)
        return parser

    @staticmethod
    def makeParser(fileName):
        parser = ConfigParser()
        # Default behaviour transforms to lower case: we want case-sensitive
        parser.optionxform = lambda option: option
        try:
            parser.read(fileName)
            return parser
        except Exception as e:
            plugins.printWarning("Bug file at " + fileName + " could not be parsed, ignoring\n" + str(e))

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
        comparison, _ = test.state.findComparison("stacktrace")
        if comparison and comparison.newResult():
            stackTraceFile = comparison.tmpFile
            self.diag.info("Parsing " + stackTraceFile)
            summary, errorInfo = self.parseStackTrace(test, stackTraceFile)

            newState = copy(test.state)
            newState.removeComparison("stacktrace")

            crashState = FailedPrediction("crash", errorInfo, summary)
            newState.setFailedPrediction(crashState)
            test.changeState(newState)
            if not test.app.keepTemporaryDirectories():
                os.remove(stackTraceFile)

    def parseStackTrace(self, test, stackTraceFile):
        lines = open(stackTraceFile).readlines()
        if len(lines) > 2:
            return lines[0].strip(), "".join(lines[2:])
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

    def __repr__(self):
        return "Checking known bugs for"

    def __call__(self, test):
        newState, rerunCount = self.checkTest(test, test.state)
        if newState:
            test.changeState(newState)
        if rerunCount and not test.app.isReconnecting() and not os.path.exists(test.makeBackupFileName(rerunCount)):
            self.describe(test, " - found an issue that triggered a rerun")
            test.saveState()
            # Current thread, must be done immediately or we might exit...
            test.performNotify("Rerun")
            # for test synchronisation, mainly
            test.notify("RerunTriggered")

        if test.state.category == "killed" and os.path.exists(test.makeBackupFileName(1)):
            newState = test.restoreLatestBackup()
            if newState:
                self.fixBackupMessage(newState)
                test.changeState(newState)

    def checkTest(self, test, state):
        activeBugs = self.readBugs(test)
        return self.checkTestWithBugs(test, state, activeBugs)

    def checkTestWithBugs(self, test, state, activeBugs):
        if not activeBugs.checkUnchanged() and not state.hasFailed():
            self.diag.info(repr(test) + " succeeded, not looking for bugs")
            return None, 0

        bugTrigger, bugStem = self.findBug(test, state, activeBugs)
        if bugTrigger:
            if bugTrigger.bugInfo.rerunOnly:
                return None, bugTrigger.bugInfo.rerunCount
            else:
                absenceBug = bugTrigger in activeBugs[bugStem].absentList
                category, briefText, fullText = bugTrigger.findBugInfo(test, bugStem, absenceBug)
                self.diag.info("Changing to " + category + " with text " + briefText)
                bugState = FailedPrediction(category, fullText, briefText, completed=1)
                return self.getNewState(state, bugState), bugTrigger.bugInfo.rerunCount
        else:
            return None, 0

    def findAllBugs(self, test, state, activeBugs):
        multipleDiffs = self.hasMultipleDifferences(test, state)
        bugs, bugStems = [], []
        for stem, fileBugData in list(activeBugs.items()):
            newBugs = self.findBugsInFile(test, state, stem, fileBugData, multipleDiffs)
            if newBugs:
                bugs += newBugs
                bugStems += [stem] * len(newBugs)
        return bugs, bugStems

    def findBug(self, test, state, activeBugs):
        bugs, bugStems = self.findAllBugs(test, state, activeBugs)
        unblockedBugs = self.findUnblockedBugs(bugs)
        if len(unblockedBugs) > 0:
            unblockedBugs.sort(key=lambda bug: (bug.bugInfo.priority, bug.bugInfo.rerunCount))
            bug = unblockedBugs[0]
            return bug, bugStems[bugs.index(bug)]
        else:
            return None, None

    def findUnblockedBugs(self, bugs):
        unblockedBugs = []
        for bug in bugs:
            if bug.bugInfo.isCancellation():
                return unblockedBugs
            else:
                unblockedBugs.append(bug)
        return unblockedBugs

    def findBugsInFile(self, test, state, stem, fileBugData, multipleDiffs):
        self.diag.info("Looking for bugs in file " + stem)
        if stem == "free_text":
            return fileBugData.findBugsInText(state.freeText.split("\n"), execHosts=state.executionHosts, tmpDir=test.writeDirectory)
        elif stem == "brief_text":
            briefText = state.getTypeBreakdown()[1]
            return fileBugData.findBugsInText(briefText.split("\n"), execHosts=state.executionHosts, tmpDir=test.writeDirectory)
        elif state.hasResults():
            # bugs are only relevant if the file itself is changed, unless marked to trigger on success also
            bugs = []
            for comp in state.findComparisonsMatching(stem):
                isChanged = not comp.hasSucceeded()
                bugs += fileBugData.findBugs(comp.tmpFile, state.executionHosts, isChanged, multipleDiffs)
            return bugs
        return []

    def getNewState(self, oldState, bugState):
        if hasattr(oldState, "failedPrediction"):
            # if we've already compared, slot our things into the comparison object
            newState = copy(oldState)
            newState.setFailedPrediction(bugState, usePreviousText=True)
            return newState
        else:
            return bugState

    def hasMultipleDifferences(self, test, state):
        if not state.hasResults():
            # check for unrunnables...
            return False
        comparisons = state.getComparisons()
        diffCount = len(comparisons)
        if diffCount <= 1:
            return False
        perfStems = state.getPerformanceStems(test)
        for comp in comparisons:
            if comp.stem in perfStems:
                diffCount -= 1
        return diffCount > 1

    def readBugs(self, test):
        bugMap = BugMap()
        # Mostly for backwards compatibility, reverse the list so that more specific bugs
        # get checked first.
        for bugFile in reversed(test.getAllPathNames("knownbugs")):
            self.diag.info("Reading bugs from file " + bugFile)
            bugMap.readFromFile(bugFile)
        return bugMap

    def fixBackupMessage(self, newState):
        newFreeText = ""
        backupRegex = re.compile(Bug.rerunLine.replace("%d", "[0-9]*").replace("(", "\\("))
        for line in newState.freeText.splitlines():
            if backupRegex.match(line):
                newFreeText += "(NOTE: This issue triggered a rerun, but this rerun was killed before it could complete.\n" + \
                    "The results presented here are those of the completed run.\n"
            elif line == Bug.prevResultLine:
                newFreeText += line.replace("previous runs", "the killed rerun").replace("previous.*", "aborted") + "\n"
            else:
                newFreeText += line + "\n"
        newState.freeText = newFreeText


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
            except Exception:
                plugins.printWarning("Bug file at " + bugFileName + " not understood, ignoring")
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
        print("Old File:\n" + open(bugFileName).read())
        print("New File:\n" + open(newBugFileName).read())
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
