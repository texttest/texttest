#!/usr/bin/env python


import os
import logging
import shutil
from texttestlib.default import fpdiff
from texttestlib import plugins
from optparse import OptionParser
from io import StringIO


class Filtering(plugins.TestState):
    def __init__(self, name, **kw):
        plugins.TestState.__init__(self, name, briefText="", **kw)

# Generic base class for filtering standard and temporary files


class FilterAction(plugins.Action):
    def __init__(self, useFilteringStates=False):
        self.diag = logging.getLogger("Filter Actions")
        self.useFilteringStates = useFilteringStates

    def __call__(self, test):
        if self.useFilteringStates:
            self.changeToFilteringState(test)

        for fileName, postfix in self.filesToFilter(test):
            self.diag.info("Considering for filtering : " + fileName)
            stem = self.getStem(fileName)
            newFileName = test.makeTmpFileName(stem + "." + test.app.name + postfix, forFramework=1)
            self.performAllFilterings(test, stem, fileName, newFileName)

    def getStem(self, fileName):
        return os.path.basename(fileName).split(".")[0]

    def changeToFilteringState(self, *args):  # pragma: no cover - documentation only
        pass

    def performAllFilterings(self, test, stem, fileName, newFileName):
        currFileName = fileName
        filters = self.makeAllFilters(test, stem, test.app)
        for fileFilter in filters:
            writeFileName = newFileName + "." + fileFilter.postfix
            self.diag.info("Applying " + fileFilter.__class__.__name__ +
                           " to make\n" + writeFileName + " from\n " + currFileName)
            if os.path.isfile(writeFileName):
                self.diag.info("Removing previous file at " + writeFileName)
                os.remove(writeFileName)
            currFile = open(currFileName, errors="ignore")
            writeFile = plugins.openForWrite(writeFileName)
            fileFilter.filterFile(currFile, writeFile)
            writeFile.close()
            currFileName = writeFileName
        if len(filters) > 0 and currFileName != newFileName:
            shutil.move(currFileName, newFileName)

    def getAllFilters(self, test, fileName, app):
        stem = self.getStem(fileName)
        return self.makeAllFilters(test, stem, app)

    def getFilteredText(self, test, fileName, app):
        filters = self.getAllFilters(test, fileName, app)
        inFile = open(fileName, errors="ignore")
        if len(filters) == 0:
            try:
                return inFile.read()
            finally:
                inFile.close()
        for fileFilter in filters:
            self.diag.info("Applying " + fileFilter.__class__.__name__ + " to " + fileName)
            outFile = StringIO()
            fileFilter.filterFile(inFile, outFile)
            inFile.close()
            inFile = outFile
            inFile.seek(0)
        value = outFile.getvalue()
        outFile.close()
        return value

    def makeAllFilters(self, test, stem, app):
        filters = self._makeAllFilters(test, stem, app)
        if len(filters) == 0 and self.changedOs(app):
            return [RunDependentTextFilter([], "")]
        else:
            return filters

    def _makeAllFilters(self, test, stem, app):
        filters = []
        configObj = test
        if test.app is not app:  # happens when testing filtering in the static GUI
            configObj = app

        for filterClass in [RunDependentTextFilter, UnorderedTextFilter]:
            texts = configObj.getCompositeConfigValue(filterClass.configKey, stem)
            if texts:
                filters.append(filterClass(texts, test.getRelPath()))

        return filters

    def changedOs(self, app):
        homeOs = app.getConfigValue("home_operating_system")
        return homeOs != "any" and os.name != homeOs

    def constantPostfix(self, files, postfix):
        return [(file, postfix) for file in files]


class FilterOriginal(FilterAction):
    def filesToFilter(self, test):
        resultFiles, defFiles = test.listApprovedFiles(allVersions=False, defFileCategory="regenerate")
        return self.constantPostfix(resultFiles + defFiles, "origcmp")

    def changeToFilteringState(self, test):
        # Notifications of current status are only useful when doing normal filtering in the GUI
        execMachines = test.state.executionHosts
        freeText = "Filtering stored result files on " + ",".join(execMachines)
        test.changeState(Filtering("initial_filter", executionHosts=execMachines,
                                   freeText=freeText, lifecycleChange="start initial filtering"))


class FilterOnTempFile(FilterAction):
    def _makeAllFilters(self, test, stem, app):
        filters = FilterAction._makeAllFilters(self, test, stem, app)
        floatTolerance = test.getCompositeConfigValue("floating_point_tolerance", stem)
        relTolerance = test.getCompositeConfigValue("relative_float_tolerance", stem)
        floatSplit = test.getCompositeConfigValue("floating_point_split", stem)
        if floatTolerance or relTolerance:
            origFile = test.makeTmpFileName(stem + "." + app.name + "origcmp", forFramework=1)
            if not os.path.isfile(origFile):
                origFile = test.getFileName(stem)
            if origFile and os.path.isfile(origFile):
                filters.append(FloatingPointFilter(origFile, floatTolerance, relTolerance, floatSplit))
        return filters


class FilterTemporary(FilterOnTempFile):
    def filesToFilter(self, test):
        return self.constantPostfix(test.listTmpFiles(), "cmp")

    def changeToFilteringState(self, test):
        # Notifications of current status are only useful when doing normal filtering in the GUI
        execMachines = test.state.executionHosts
        freeText = "Filtering and comparing newly generated result files on " + ",".join(execMachines)
        newState = Filtering("final_filter", executionHosts=execMachines, started=1,
                             freeText=freeText, lifecycleChange="start final filtering and comparison")
        if test.state.category == "killed":
            newState.failedPrediction = test.state
        test.changeState(newState)


class FilterOriginalForScript(FilterOriginal):
    def _makeAllFilters(self, *args):
        return []


class FilterErrorText(FilterAction):
    def _makeAllFilters(self, test, stem, app):
        texts = app.getConfigValue("suppress_stderr_text")
        return [RunDependentTextFilter(texts)]


class FilterProgressRecompute(FilterOnTempFile):
    def filesToFilter(self, test):
        return self.constantPostfix(test.listTmpFiles(), "partcmp")


class FilterResultRecompute(FilterOnTempFile):
    def filesToFilter(self, test):
        result = []
        for fileComp in test.state.allResults:
            # Either of these files might have disappeared
            if fileComp.stdFile and os.path.isfile(fileComp.stdFile):
                result.append((fileComp.stdFile, "origcmp"))
            if fileComp.tmpFile and os.path.isfile(fileComp.tmpFile):
                result.append((fileComp.tmpFile, "cmp"))
        return result


class FloatingPointFilter:
    postfix = "fpdiff"

    def __init__(self, origFileName, tolerance, relative, split):
        self.origFileName = origFileName
        self.tolerance = tolerance if tolerance else None
        self.relative = relative if relative else None
        self.split = split

    def filterFile(self, inFile, writeFile):
        fromlines = open(self.origFileName, errors="ignore").readlines()
        tolines = inFile.readlines()
        fpdiff.fpfilter(fromlines, tolines, writeFile, self.tolerance, self.relative, split=self.split)


class RunDependentTextFilter(plugins.Observable):
    configKey = "run_dependent_text"
    postfix = "normal"

    def __init__(self, filterTexts, testId=""):
        plugins.Observable.__init__(self)
        self.diag = logging.getLogger("Run Dependent Text")
        self.lineFilters = [LineFilter(text, testId, self.diag) for text in filterTexts]

    def findRelevantFilters(self, file):
        relevantFilters, sectionFilters = [], []
        for lineFilter in self.lineFilters:
            if lineFilter.untrigger is not None:
                sectionFilters.append(lineFilter)
            else:
                relevantFilters.append(lineFilter)
        if sectionFilters:
            # Must preserve the original order
            relevantSectionFilters = self.findRelevantSectionFilters(sectionFilters, file)
            orderedRelevantFilters = []
            for lineFilter in self.lineFilters:
                if lineFilter in relevantFilters:
                    orderedRelevantFilters.append((lineFilter, None))
                else:
                    lastLine = self.getLastLine(relevantSectionFilters, lineFilter)
                    if lastLine:
                        orderedRelevantFilters.append((lineFilter, lastLine))
            return orderedRelevantFilters
        else:
            return [(f, None) for f in relevantFilters]

    def getLastLine(self, filters, lineFilter):
        for f, lastLine in reversed(filters):
            if f is lineFilter:
                return lastLine

    def findRelevantSectionFilters(self, sectionFilters, file):
        lineNumber = 0
        matchedFirst, relevantFilters = [], []
        for line in file:
            lineNumber += 1
            for sectionFilter in matchedFirst:
                if sectionFilter not in relevantFilters and sectionFilter.untrigger.matches(line, lineNumber):
                    relevantFilters.append((sectionFilter, lineNumber))
            for sectionFilter in sectionFilters:
                if sectionFilter not in matchedFirst and \
                        sectionFilter.trigger.matches(line, lineNumber) and not sectionFilter.untrigger.matches(line, lineNumber):
                    matchedFirst.append(sectionFilter)
        for sectionFilter in sectionFilters:
            sectionFilter.trigger.reset()
            sectionFilter.untrigger.reset()
        file.seek(0)
        return relevantFilters

    def filterFile(self, file, newFile, filteredAway=None):
        lineNumber = 0
        seekPoints = []
        lineFilters = self.findRelevantFilters(file)
        for line in file:
            # We don't want to stack up ActionProgreess calls in ThreaderNotificationHandler ...
            self.notifyIfMainThread("ActionProgress")
            lineNumber += 1
            lineFilter, filteredLine, removeCount = self.getFilteredLine(line, lineNumber, lineFilters)
            if removeCount:
                seekPoint = seekPoints[-removeCount - 1] if removeCount < len(seekPoints) else 0
                self.diag.info("Removing " + repr(removeCount) + " lines")
                newFile.seek(seekPoint)
                newFile.truncate()
                seekPoints = []
            if filteredLine:
                newFile.write(filteredLine)
            else:
                if filteredAway is not None and lineFilter is not None:
                    filteredAway.setdefault(lineFilter, []).append(line)
            seekPoints.append(newFile.tell())

    def getFilteredLine(self, line, lineNumber, lineFilters):
        appliedLineFilter = None
        filteredLine = line
        linesToRemove = 0
        filtersToRemove = []
        alreadyFilteredAway = False
        for lineFilter, lastRelevantLine in lineFilters:
            changed, currFilteredLine, removeCount = lineFilter.applyTo(line, lineNumber, alreadyFilteredAway)
            if lastRelevantLine is not None and lineNumber >= lastRelevantLine:
                filtersToRemove.append((lineFilter, lastRelevantLine))

            if changed:
                appliedLineFilter = lineFilter
                linesToRemove = max(removeCount, linesToRemove)
                if currFilteredLine and filteredLine:
                    line = currFilteredLine
                if filteredLine:
                    filteredLine = currFilteredLine
                if currFilteredLine is None:
                    alreadyFilteredAway = True
        for lineFilter, lastRelevantLine in filtersToRemove:
            lineFilters.remove((lineFilter, lastRelevantLine))

        return appliedLineFilter, filteredLine, linesToRemove


class UnorderedTextFilter(RunDependentTextFilter):
    configKey = "unordered_text"
    postfix = "sorted"

    def filterFile(self, file, newFile):
        unorderedLines = {}
        RunDependentTextFilter.filterFile(self, file, newFile, unorderedLines)
        self.writeUnorderedText(newFile, unorderedLines)

    def writeUnorderedText(self, newFile, lines):
        for filter in self.lineFilters:
            unordered = lines.get(filter, [])
            if len(unordered) == 0:
                continue
            unordered.sort()
            newFile.write("-- Unordered text as found by filter '" + filter.originalText + "' --" + "\n")
            for line in unordered:
                newFile.write(line)
            newFile.write("\n")


class LineNumberTrigger:
    def __init__(self, lineNumber):
        self.lineNumber = lineNumber

    def __repr__(self):
        return "Line number trigger for line " + str(self.lineNumber)

    def matches(self, lineArg, lineNumber):
        return lineNumber == self.lineNumber

    def replace(self, lineArg, newText):
        return newText

    def reset(self):
        pass


class MatchNumberTrigger(plugins.TextTrigger):
    def __init__(self, text, matchNumber):
        self.matchNumber = matchNumber
        self.matchCounter = 0
        plugins.TextTrigger.__init__(self, text)

    def __repr__(self):
        return "Match number trigger for the " + str(self.matchNumber) + ":th match"

    def matches(self, line, *args):
        if plugins.TextTrigger.matches(self, line):
            self.matchCounter += 1
            return self.matchNumber == self.matchCounter
        return False

    def reset(self):
        self.matchCounter = 0


def getWriteDirRegexp(testId):
    testId = testId.replace("\\", "/")
    for char in "+^":
        testId = testId.replace(char, "\\" + char)
    # Some stuff, a date, and the testId (ignore the appId as we don't know when or where)
    # Doesn't handle paths with spaces, which seems hard, but does hardcode the default location of $HOME on Windows...
    posixVersion = '([A-Za-z]:/Documents and Settings)?[^ \'"=]*/[^ "=]*[0-3][0-9][A-Za-z][a-z][a-z][0-9]{6}[^ "=]*/' + testId
    return posixVersion.replace("/", "[/\\\\]+")


class LineFilter:
    dividers = ["{->}", "{[->]}", "{[->}", "{->]}"]
    # All syntax that affects how a match is found
    matcherStrings = ["{LINE ", "{INTERNAL ", "{MATCH "]
    # All syntax that affects what is done when a match is found
    matchModifierStrings = ["{WORD ", "{REPLACE ", "{LINES ", "{PREVLINES "]
    internalExpressions = {"writedir": getWriteDirRegexp}

    def __init__(self, text, testId, diag):
        self.originalText = text
        self.testId = testId
        self.diag = diag
        self.trigger = None
        self.untrigger = None
        self.linesToRemove = 1
        self.prevLinesToRemove = 0
        self.autoRemove = 0
        self.wordNumber = None
        self.replaceText = None
        self.divider = None
        self.removeWordsAfter = False
        self.parseOriginalText()
        self.diag.info("Created trigger : " + repr(self.trigger))

    def makeNew(self, newText):
        return LineFilter(newText, self.testId, self.diag)

    def getInternalExpression(self, parameter):
        method = self.internalExpressions.get(parameter)
        return method(self.testId)

    def makeRegexTrigger(self, parameter):
        expression = self.getInternalExpression(parameter)
        return plugins.TextTrigger(expression)

    def parseOriginalText(self):
        for divider in self.dividers:
            dividerPoint = self.originalText.find(divider)
            if dividerPoint != -1:
                beforeText, afterText = self.originalText.split(divider)
                self.divider = divider
                self.trigger = self.parseText(beforeText)
                self.untrigger = self.parseText(afterText)
                return
        self.trigger = self.parseText(self.originalText)

    def parseText(self, text):
        for matchModifierString in self.matchModifierStrings:
            linePoint = text.find(matchModifierString)
            if linePoint != -1:
                beforeText, afterText, parameter = self.extractParameter(text, linePoint, matchModifierString)
                self.readMatchModifier(matchModifierString, parameter)
                text = beforeText + afterText
        matcherString, text, parameter = self.findMatcherInfo(text)
        return self.createTrigger(matcherString, text, parameter)

    def findMatcherInfo(self, text):
        for matcherString in self.matcherStrings:
            linePoint = text.find(matcherString)
            if linePoint != -1:
                beforeText, afterText, parameter = self.extractParameter(text, linePoint, matcherString)
                return matcherString, beforeText + afterText, parameter
        return "", text, None

    def extractParameter(self, textToParse, linePoint, syntaxString):
        beforeText = textToParse[:linePoint]
        afterText = textToParse[linePoint + len(syntaxString):]
        endPos = afterText.find("}")
        parameter = afterText[:endPos]
        afterText = afterText[endPos + 1:]
        return beforeText, afterText, parameter

    def readMatchModifier(self, matchModifierString, parameter):
        if matchModifierString == "{REPLACE ":
            self.replaceText = parameter
        elif matchModifierString == "{WORD ":
            if parameter.endswith("+"):
                self.removeWordsAfter = True
                self.wordNumber = int(parameter[:-1])
            else:
                self.wordNumber = int(parameter)
            # Somewhat non-intuitive to count from 0...
            if self.wordNumber > 0:
                self.wordNumber -= 1
        elif matchModifierString == "{LINES ":
            self.linesToRemove = int(parameter)
        elif matchModifierString == "{PREVLINES ":
            self.prevLinesToRemove = int(parameter)

    def createTrigger(self, matcherString, text, parameter):
        if matcherString == "{LINE ":
            return LineNumberTrigger(int(parameter))
        elif matcherString == "{INTERNAL " and parameter in self.internalExpressions:
            return self.makeRegexTrigger(parameter)
        elif matcherString == "{MATCH ":
            return MatchNumberTrigger(text, int(parameter))
        else:
            return plugins.TextTrigger(text)

    def isMultiLine(self):
        return self.linesToRemove > 1 or self.prevLinesToRemove > 0 or self.untrigger is not None

    def applyTo(self, line, lineNumber=0, alreadyFilteredAway=False):
        if self.autoRemove:
            return self.applyAutoRemove(line)
        elif alreadyFilteredAway and not self.isMultiLine():
            return False, None, 0

        if self.trigger.matches(line, lineNumber):
            self.diag.info(repr(self.trigger) + " matched " + line.rstrip())
            return self.applyMatchingTrigger(line)
        else:
            return False, line, 0

    def applyAutoRemove(self, line):
        if self.untrigger:
            if self.untrigger.matches(line.rstrip()):
                self.diag.info(repr(self.untrigger) + " (end) matched " + line.rstrip())
                self.autoRemove = 0
                if self.divider.endswith("]}"):
                    return True, None, 0
                else:
                    return False, line, 0
        else:
            self.autoRemove -= 1
        return True, self.filterWords(line), 0

    def applyMatchingTrigger(self, line):
        if self.untrigger:
            self.autoRemove = 1
            return self.divider.startswith("{["), self.filterWords(line), 0
        if self.linesToRemove:
            self.autoRemove = self.linesToRemove - 1
        return True, self.filterWords(line, self.trigger), self.prevLinesToRemove

    def filterWords(self, line, trigger=None):
        if self.wordNumber != None:
            stripped = line.rstrip()
            postfix = line.replace(stripped, "", 1)
            words = stripped.split(" ")
            self.diag.info("Removing word " + str(self.wordNumber) + " from " + repr(words))
            realNumber = self.findRealWordNumber(words)
            self.diag.info("Real number was " + str(realNumber))
            if realNumber < len(words):
                if self.removeWordsAfter:
                    words = words[:realNumber]
                    if self.replaceText:
                        words.append(self.replaceText)
                else:
                    if self.replaceText:
                        words[realNumber] = self.replaceText
                    else:
                        del words[realNumber]
            if realNumber == -1 or realNumber >= len(words) - 1:  # Trim trailing spaces for words at end or beyond
                postfix = "\n"
            return " ".join(words).rstrip() + postfix
        elif trigger and self.replaceText != None:
            return trigger.replace(line.rstrip("\n"), self.replaceText) + "\n"

    def findRealWordNumber(self, words):
        if self.wordNumber < 0:
            return self.findRealWordNumberBackwards(words)
        wordNumber = 0
        for realWordNumber in range(len(words)):
            if len(words[realWordNumber]):
                if wordNumber == self.wordNumber:
                    return realWordNumber
                wordNumber += 1
        return len(words) + 1

    def findRealWordNumberBackwards(self, words):
        wordNumber = -1
        for index in range(len(words)):
            realWordNumber = -1 - index
            word = words[realWordNumber]
            if len(word):
                if wordNumber == self.wordNumber:
                    return realWordNumber
                wordNumber -= 1
        return len(words) + 1
