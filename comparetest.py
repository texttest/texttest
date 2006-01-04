#!/usr/local/bin/python


import os, filecmp, string, sys, plugins, time
from ndict import seqdict
from predict import FailedPrediction
from shutil import copyfile
from fnmatch import fnmatch
from tempfile import mktemp
from re import sub

plugins.addCategory("success", "succeeded")
plugins.addCategory("failure", "FAILED")

class TestComparison(plugins.TestState):
    def __init__(self, previousInfo, app):
        plugins.TestState.__init__(self, "failure", "", started=1, completed=1, executionHosts=previousInfo.executionHosts)
        self.allResults = []
        self.changedResults = []
        self.newResults = []
        self.missingResults = []
        self.correctResults = []
        self.failedPrediction = None
        if previousInfo.category == "killed" or isinstance(previousInfo, FailedPrediction):
            self.setFailedPrediction(previousInfo)
        self.diag = plugins.getDiagnostics("TestComparison")
        # Cache these only so it gets output when we pickle, so we can re-interpret if needed... data may be moved
        self.appAbsPath = app.abspath
        self.appWriteDir = app.writeDirectory
    def __repr__(self):    
        if self.failedPrediction:
            briefDescription, longDescription = self.categoryDescriptions[self.category]
            return longDescription + " (" + self.failedPrediction.briefText + ")" + self.hostRepr()
        else:
            return plugins.TestState.__repr__(self)
    def ensureCompatible(self):
        # If loaded from old pickle files, can get out of date objects...
        if not hasattr(self, "missingResults"):
            self.missingResults = []
    def updatePaths(self, newAbsPath, newWriteDir):
        self.diag = plugins.getDiagnostics("TestComparison")
        self.diag.info("Updating abspath " + self.appAbsPath + " to " + newAbsPath)
        self.diag.info("Updating writedir " + self.appWriteDir + " to " + newWriteDir)
        for comparison in self.allResults:
            comparison.updatePaths(self.appAbsPath, newAbsPath)
            comparison.updatePaths(self.appWriteDir, newWriteDir)
        self.appAbsPath = newAbsPath
        self.appWriteDir = newWriteDir
    def setFailedPrediction(self, prediction):
        self.failedPrediction = prediction
        self.freeText = str(prediction)
        self.briefText = prediction.briefText
        self.category = prediction.category
    def hasSucceeded(self):
        return self.category == "success"
    def isSaveable(self):
        if self.failedPrediction:
            return self.failedPrediction.isSaveable()
        else:
            return plugins.TestState.isSaveable(self)
    def hasDifferences(self):
        return len(self.changedResults) > 0
    def needsRecalculation(self):
        for comparison in self.allResults:
            self.diag.info(comparison.stem + " dates " + comparison.modifiedDates())
            if comparison.needsRecalculation():
                self.diag.info("Recalculation needed for file " + comparison.stem)
                return 1
        self.diag.info("All file comparisons up to date")
        return 0
    def getMostSevereFileComparison(self):
        worstSeverity = None
        worstResult = None
        for result in self.getComparisons():
            severity = result.severity
            if not worstSeverity or severity < worstSeverity:
                worstSeverity = severity
                worstResult = result
        return worstResult
    def getTypeBreakdown(self):
        if self.hasSucceeded():
            return self.category, ""
        if self.failedPrediction:
            return self.failedPrediction.getTypeBreakdown()

        worstResult = self.getMostSevereFileComparison()
        worstSeverity = worstResult.severity
        self.diag.info("Severity " + str(worstSeverity) + " for failing test")
        details = self.getSummary(worstResult)
        if len(self.getComparisons()) > 1:
            details += "(+)"
        if worstSeverity == 1:
            return "failure", details
        else:
            return "success", details
    def getSummary(self, worstResult):
        # Don't call worstResult.newResult() - we want the right answer
        # even if all the files are gone, for the sake of testoverview etc.
        if worstResult in self.newResults:
            return worstResult.stem + " new"
        elif worstResult in self.missingResults:
            return worstResult.stem + " missing"
        else:
            return worstResult.getSummary()
    def hasResults(self):
        return len(self.allResults) > 0
    def getComparisons(self):
        return self.changedResults + self.newResults + self.missingResults
    def _comparisonsString(self, comparisons):
        return string.join([repr(x) for x in comparisons], ",")
    def getDifferenceSummary(self):
        return repr(self) + self._getDifferenceSummary()
    def _getDifferenceSummary(self):
        if len(self.getComparisons()) == 0:
            return ""
        texts = []
        if len(self.newResults) > 0:
            texts.append("new results in " + self._comparisonsString(self.newResults))
        if len(self.missingResults) > 0:
            texts.append("missing results for " + self._comparisonsString(self.missingResults))
        if len(self.changedResults) > 0:
            texts.append("differences in " + self._comparisonsString(self.changedResults))
        return " " + string.join(texts, ", ")
    def getPostText(self):
        if not self.hasResults():
            return " - NONE!"
        if len(self.getComparisons()) == 0:
            return " - SUCCESS! (on " + self.attemptedComparisonsOutput() + ")"
        return " (on " + self.attemptedComparisonsOutput() + ")"
    def attemptedComparisonsOutput(self):
        baseNames = []
        for comparison in self.allResults:
            baseNames.append(os.path.basename(comparison.tmpFile))
        return string.join(baseNames, ",")
    def addComparison(self, comparison):
        info = "Making comparison for " + comparison.stem + " "
        self.allResults.append(comparison)
        if comparison.newResult():
            self.newResults.append(comparison)
            info += "(new)"
        elif comparison.missingResult():
            self.missingResults.append(comparison)
            info += "(missing)"
        elif comparison.hasDifferences():
            self.changedResults.append(comparison)
            info += "(diff)"
        else:
            self.correctResults.append(comparison)
            info += "(correct)"
        self.diag.info(info)
    def makeComparisons(self, test, makeNew = 0):
        stems = self.getFileStems(test, makeNew)
        for stem in stems:
            stdFile = test.makeFileName(stem)
            tmpFile = test.makeFileName(stem, temporary=1, findInTmp=1)
            if os.path.isfile(stdFile) or os.path.isfile(tmpFile):
                comparison = self.createFileComparison(test, stdFile, tmpFile, makeNew)
                self.addComparison(comparison)
        self.handleSingleDiffWithExcuse(test)
    def handleSingleDiffWithExcuse(self, test):
        if len(self.changedResults) == 1 and self.changedResults[0].checkExternalExcuses(test.app):
            # If the only difference has an excuse, remove it...
            fileComparison = self.changedResults[0]
            del self.changedResults[0]
            self.correctResults.append(fileComparison)
    def getFileStems(self, test, makeNew):
        stems = []
        relDirs = [ "", "Diagnostics", "Diagnostics/slave" ]
        for relDir in relDirs:
            self.getFileStemsFromDir(stems, test.writeDirectory, test.app.name, relDir)

        # Pick up anything that disappeared, if we've actually completed
        if not makeNew:
            self.getFileStemsFromDir(stems, test.abspath, test.app.name, ignoreStems=self.getOptionalStems(test))
        return stems
    def getOptionalStems(self, test):
        return test.getConfigValue("definition_file_stems")
    def getFileStemsFromDir(self, stems, rootDir, allowedExt, relDir="", ignoreStems=[]):
        absDir = os.path.join(rootDir, relDir)
        if not os.path.isdir(absDir):
            return
        fileList = os.listdir(absDir)
        fileList.sort()
        for file in fileList:
            fullPath = os.path.join(absDir, file)
            if not os.path.isfile(fullPath) or os.path.islink(fullPath):
                continue

            parts = file.split(".")
            if len(parts) == 1:
                continue
            stem, ext = parts[:2]
            if len(stem) == 0 or stem in ignoreStems or ext != allowedExt:
                continue
            if relDir:
                stem = os.path.join(relDir, stem)
            if not stem in stems:
                stems.append(stem)
    def createFileComparison(self, test, standardFile, tmpFile, makeNew = 0):
        return FileComparison(test, standardFile, tmpFile, makeNew)
    def saveSingle(self, stem, exact = 1, versionString = ""):
        comparison, storageList = self.findComparison(stem)
        if comparison:
            comparison.overwrite(exact, versionString)
            storageList.remove(comparison)
            if storageList is self.missingResults:
                self.allResults.remove(comparison)
            else:
                self.correctResults.append(comparison)
        if len(self.getComparisons()) == 0:
            self.category = "success"
            self.freeText = ""
    def findComparison(self, stem):
        lists = [ self.changedResults, self.newResults, self.missingResults ]
        for list in lists:
            for comparison in list:
                if comparison.stem == stem:
                    return comparison, list
        return None, None
    def save(self, exact = 1, versionString = "", overwriteSuccessFiles = 0):
        # Force exactness unless there is only one difference : otherwise
        # performance is averaged when results have changed as well
        resultCount = len(self.changedResults) + len(self.newResults)
        if resultCount > 1:
            exact = 1
        for comparison in self.changedResults:
            comparison.overwrite(exact, versionString)
        for comparison in self.newResults + self.missingResults:
            comparison.overwrite(1, versionString)
        for comparison in self.missingResults:
            self.allResults.remove(comparison)
        if overwriteSuccessFiles:
            for comparison in self.correctResults:
                comparison.overwrite(exact, versionString)
        self.correctResults += self.changedResults + self.newResults
        self.changedResults = []
        self.newResults = []
        self.missingResults = []
        self.category = "success"
        self.freeText = ""

class MakeComparisons(plugins.Action):
    defaultComparisonClass = None
    def __init__(self, testComparisonClass=None):
        self.lineCount = None
        self.maxLineWidth = None
        self.textDiffTool = None
        if testComparisonClass:
            self.testComparisonClass = testComparisonClass
            MakeComparisons.defaultComparisonClass = testComparisonClass
        else:
            self.testComparisonClass = MakeComparisons.defaultComparisonClass
    def __repr__(self):
        return "Comparing differences for"
    def __call__(self, test):
        testComparison = self.testComparisonClass(test.state, test.app)
        testComparison.makeComparisons(test)
        self.categorise(testComparison)
        self.describe(test, testComparison.getPostText())
        test.changeState(testComparison)
    def setUpSuite(self, suite):
        self.describe(suite)
    def categorise(self, state):
        if state.failedPrediction:
            # Keep the category we had before
            state.freeText += self.getFreeTextInfo(state)
            return
        if not state.hasResults():
            raise plugins.TextTestError, "No output files at all produced, presuming problems running test " + state.hostString() 
        worstResult = state.getMostSevereFileComparison()
        if not worstResult:
            state.category = "success"
        else:
            state.category = worstResult.getType()
            state.freeText = self.getFreeTextInfo(state)
    def getFreeTextInfo(self, state):
        fullText = ""
        for comparison in state.getComparisons():
            fullText += self.fileComparisonTitle(comparison) + "\n"
            fullText += self.fileComparisonBody(comparison)
        return fullText
    def fileComparisonTitle(self, comparison):
        if comparison.missingResult():
            titleText = "Missing result in"
        elif comparison.newResult():
            titleText = "New result in"
        else:
            titleText = "Differences in"
        titleText += " " + repr(comparison)
        return "------------------ " + titleText + " --------------------"
    def fileComparisonBody(self, comparison):
        if comparison.newResult():
            return self.previewGenerator.getPreview(open(comparison.tmpCmpFile))
        elif comparison.missingResult():
            return self.previewGenerator.getPreview(open(comparison.stdCmpFile))
        
        cmdLine = self.textDiffTool + " " + comparison.stdCmpFile + " " + comparison.tmpCmpFile
        stdout = os.popen(cmdLine)
        return self.previewGenerator.getPreview(stdout)
    def findTextDiffTool(self, app):
        configVal = app.getConfigValue("text_diff_program")
        return plugins.findDiffTool(configVal)
    def setUpApplication(self, app):
        maxLength = app.getConfigValue("lines_of_text_difference")
        maxWidth = app.getConfigValue("max_width_text_difference")
        self.previewGenerator = plugins.PreviewGenerator(maxWidth, maxLength)
        self.textDiffTool = self.findTextDiffTool(app)
    
class FileComparison:
    def __init__(self, test, standardFile, tmpFile, makeNew = 0):
        self.stdFile = standardFile
        self.tmpFile = tmpFile
        self.stem = os.path.basename(tmpFile).split('.')[0]
        self.diag = plugins.getDiagnostics("FileComparison")
        filter = RunDependentTextFilter(test, self.stem)
        filterFileBase = test.makeFileName(os.path.basename(tmpFile), temporary=1, forComparison=0)
        self.stdCmpFile = filter.filterFile(standardFile, filterFileBase + "origcmp")
        tmpCmpFileName = filterFileBase + "cmp"
        if makeNew:
            tmpCmpFileName = filterFileBase + "partcmp"
        self.tmpCmpFile = filter.filterFile(tmpFile, tmpCmpFileName, makeNew)
        self.diag.info("File comparison std: " + repr(self.stdFile) + " tmp: " + repr(self.tmpFile))
        self._cacheValues(test.app)
    def _cacheValues(self, app):
        self.differenceId = self._hasDifferences(app)
        self.severity = 99
        failureSeverityDict = app.getConfigValue("failure_severity")
        for key in failureSeverityDict.keys():
            if fnmatch(self.stem, key):
                self.severity = failureSeverityDict[key]
    def __repr__(self):
        return os.path.basename(self.stdFile).split('.')[0]
    def checkExternalExcuses(self, app):
        # No excuses here...
        return 0
    def modifiedDates(self):
        files = [ self.stdFile, self.tmpFile, self.stdCmpFile, self.tmpCmpFile ]
        return string.join(map(self.modifiedDate, files), " : ")
    def modifiedDate(self, file):
        if not os.path.isfile(file):
            return "---"
        modTime = plugins.modifiedTime(file)
        return time.strftime("%d%b%H:%M:%S", time.localtime(modTime))
    def needsRecalculation(self):
        # A test that has been saved doesn't need recalculating
        if self.tmpCmpFile == self.stdCmpFile or self.stdCmpFile == self.stdFile:
            return 0
        
        if plugins.modifiedTime(self.tmpCmpFile) < plugins.modifiedTime(self.tmpFile):
            return 1
        return not self.newResult() and not self.missingResult() and \
               (plugins.modifiedTime(self.stdCmpFile) <= plugins.modifiedTime(self.stdFile))
    def getType(self):
        return "failure"
    def isDiagnostic(self):
        root, local = os.path.split(self.stdFile)
        return os.path.basename(root) == "Diagnostics"
    def getDetails(self):
        # Nothing to report above what is already known
        return ""
    def getSummary(self):
        return self.stem + " different"
    def newResult(self):
        return not os.path.exists(self.stdFile)
    def missingResult(self):
        return not os.path.exists(self.tmpFile)
    def hasDifferences(self):
        return self.differenceId
    def _hasDifferences(self, app):
        if os.path.isfile(self.stdCmpFile) and os.path.isfile(self.tmpCmpFile):
            return not filecmp.cmp(self.stdCmpFile, self.tmpCmpFile, 0)
        else:
            return 0
    def updatePaths(self, oldAbsPath, newAbsPath):
        self.stdFile = self.stdFile.replace(oldAbsPath, newAbsPath)
        self.stdCmpFile = self.stdCmpFile.replace(oldAbsPath, newAbsPath)
        self.tmpCmpFile = self.tmpCmpFile.replace(oldAbsPath, newAbsPath)
        self.tmpFile = self.tmpFile.replace(oldAbsPath, newAbsPath)
    def overwrite(self, exact, versionString = ""):
        parts = os.path.basename(self.stdFile).split(".")[:2] 
        if len(versionString):
            parts += versionString.split(".")
        stdFile = os.path.join(os.path.dirname(self.stdFile), string.join(parts, "."))
        if os.path.isfile(stdFile):
            os.remove(stdFile)
        # Allow for subclasses to differentiate between a literal overwrite and a
        # more intelligent save, e.g. for performance. Default is the same for exact
        # and inexact save
        if not self.missingResult():
            if exact:
                copyfile(self.tmpFile, stdFile)
            else:
                self.saveResults(stdFile)
        # Try to get everything to behave normally after a save...
        self.differenceId = 0
        self.tmpFile = stdFile
        self.stdCmpFile = self.tmpCmpFile
        self.stdFile = stdFile
    def saveResults(self, destFile):
        copyfile(self.tmpFile, destFile)
        
class RunDependentTextFilter:
    def __init__(self, test, stem):
        self.diag = plugins.getDiagnostics("Run Dependent Text")
        self.contentFilters = []
        self.orderFilters = seqdict()
        dict = test.getConfigValue("run_dependent_text")
        for text in self.findConfigTexts(dict, stem):
            self.contentFilters.append(LineFilter(text, test.writeDirectory, self.diag))
        dict = test.getConfigValue("unordered_text")
        for text in self.findConfigTexts(dict, stem):
            orderFilter = LineFilter(text, test.writeDirectory, self.diag)
            self.orderFilters[orderFilter] = []
        self.osChange = self.changedOs(test.app)
    def changedOs(self, app):
        homeOs = app.getConfigValue("home_operating_system")
        if homeOs == "any":
            return 0
        return os.name != homeOs
    def hasFilters(self):
        return len(self.contentFilters) > 0 or len(self.orderFilters) > 0
    def findConfigTexts(self, dict, stem):
        texts = []
        for key in dict.keys():
            if fnmatch(stem, key):
                texts += dict[key]
        return texts
    def shouldFilter(self, fileName, newFileName):
        if not os.path.isfile(fileName):
            return 0
        if self.hasFilters():
            return 1
        # Force recomputation of files that come from other operating systems...
        return self.osChange
    def filterFile(self, fileName, newFileName, makeNew = 0):
        if not self.shouldFilter(fileName, newFileName):
            self.diag.info("No filter for " + fileName)
            return fileName

        # Don't recreate filtered files, unless makeNew is set or they're out of date...
        if os.path.isfile(newFileName):
            newModTime = plugins.modifiedTime(newFileName)
            oldModTime = plugins.modifiedTime(fileName)
            self.diag.info("Filter file exists, modified at " + str(newModTime) + " (original updated at " + str(oldModTime) + ")")
            if makeNew or newModTime <= oldModTime:
                os.remove(newFileName)
            else:
                return newFileName

        self.resetFilters()
        newFile = open(newFileName, "w")
        lineNumber = 0
        for line in open(fileName).xreadlines():
            lineNumber += 1
            filteredLine = self.getFilteredLine(line, lineNumber)
            if filteredLine:
                newFile.write(filteredLine)
        self.writeUnorderedText(newFile)
        self.diag.info("Filter for " + fileName + " returned " + newFileName)
        return newFileName
    def resetFilters(self):
        for filter in self.contentFilters:
            filter.reset()
        for filter in self.orderFilters.keys():
            filter.reset()
    def getFilteredLine(self, line, lineNumber):
        for contentFilter in self.contentFilters:
            changed, filteredLine = contentFilter.applyTo(line, lineNumber)
            if changed:
                if not filteredLine:
                    return filteredLine
                line = filteredLine
        for orderFilter in self.orderFilters.keys():
            changed, filteredLine = orderFilter.applyTo(line, lineNumber)
            if changed:
                if not filteredLine:
                    filteredLine = line
                self.orderFilters[orderFilter].append(filteredLine)
                return ""
        return line
    def writeUnorderedText(self, newFile):
        for filter, linesFiltered in self.orderFilters.items():
            if len(linesFiltered) == 0:
                continue
            linesFiltered.sort()
            newFile.write("-- Unordered text as found by filter '" + filter.originalText + "' --" + "\n")
            for line in linesFiltered:
                newFile.write(line)
            newFile.write("\n")
            self.orderFilters[filter] = []

class LineNumberTrigger:
    def __init__(self, lineNumber):
        self.lineNumber = lineNumber
    def __repr__(self):
        return "Line number trigger for line " + str(self.lineNumber)
    def matches(self, line, lineNumber):
        return lineNumber == self.lineNumber
    def replace(self, line, newText):
        return newText

class LineFilter:
    divider = "{->}"
    # All syntax that affects how a match is found
    matcherStrings = [ "{LINE ", "{INTERNAL " ]
    # All syntax that affects what is done when a match is found
    matchModifierStrings = [ "{WORD ", "{REPLACE ", "{LINES " ]
    def __init__(self, text, testWriteDir, diag):
        self.originalText = text
        self.diag = diag
        self.triggers = []
        self.untrigger = None
        self.linesToRemove = 1
        self.autoRemove = 0
        self.wordNumber = None
        self.replaceText = None
        self.removeWordsAfter = 0
        self.internalExpressions = { "writedir" : testWriteDir }
        self.parseOriginalText()
    def makeRegexTriggers(self, parameter):
        if parameter != "writedir":
            return [ plugins.TextTrigger(parameter) ]
        writeDir = self.internalExpressions[parameter]
        realPath = os.path.realpath(writeDir)
        triggers = [ self.makeRegex(writeDir) ]
        if writeDir != realPath:
            triggers.append(self.makeRegex(realPath))
        return triggers
    def makeRegex(self, thisText):
        userName = os.getenv("USER", "tmp")
        versionRegexp = "\..*" + userName
        thisText = sub(versionRegexp, ".*", thisText)
        thisText = thisText.replace(userName, "[^/]*")
        dateRegexp = "[0-3][0-9][A-Za-z][a-z][a-z][0-9][0-9][0-9][0-9][0-9][0-9]"
        return plugins.TextTrigger(sub(dateRegexp, dateRegexp, thisText))
    def parseOriginalText(self):
        dividerPoint = self.originalText.find(self.divider)
        if dividerPoint != -1:
            beforeText, afterText, parameter = self.extractParameter(self.originalText, dividerPoint, self.divider)
            self.triggers = self.parseText(beforeText)
            self.untrigger = self.parseText(afterText)[0]
        else:
            self.triggers = self.parseText(self.originalText)
        self.diag.info("Created triggers : " + repr(self.triggers))
    def parseText(self, text):
        for matchModifierString in self.matchModifierStrings:
            linePoint = text.find(matchModifierString)
            if linePoint != -1:
                beforeText, afterText, parameter = self.extractParameter(text, linePoint, matchModifierString)
                self.readMatchModifier(matchModifierString, parameter)
                text = beforeText + afterText
        matcherString, parameter = self.findMatcherInfo(text)
        return self.createTriggers(matcherString, parameter)
    def findMatcherInfo(self, text):
        for matcherString in self.matcherStrings:
            linePoint = text.find(matcherString)
            if linePoint != -1:
                beforeText, afterText, parameter = self.extractParameter(text, linePoint, matcherString)
                return matcherString, parameter
        return "", text
    def reset(self):
        self.autoRemove = 0
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
                self.removeWordsAfter = 1
                self.wordNumber = int(parameter[:-1])
            else:
                self.wordNumber = int(parameter)
            # Somewhat non-intuitive to count from 0...
            if self.wordNumber > 0:
                self.wordNumber -= 1
        elif matchModifierString == "{LINES ":
            self.linesToRemove = int(parameter)
    def createTriggers(self, matcherString, parameter):
        if matcherString == "{LINE ":
            return [ LineNumberTrigger(int(parameter)) ]
        elif matcherString == "{INTERNAL " and self.internalExpressions.has_key(parameter):
            return self.makeRegexTriggers(parameter)
        else:
            return [ plugins.TextTrigger(parameter) ]
    def applyTo(self, line, lineNumber):
        if self.autoRemove:
            return self.applyAutoRemove(line)

        trigger = self.getMatchingTrigger(line, lineNumber)
        if trigger:
            return self.applyMatchingTrigger(line, trigger)
        else:
            return False, line
    def applyAutoRemove(self, line):
        if self.untrigger:
            if self.untrigger.matches(line.strip()):
                self.autoRemove = 0
                return False, line
        else:
            self.autoRemove -= 1
        return True, self.filterWords(line)
    def applyMatchingTrigger(self, line, trigger):
        if self.untrigger:
            self.autoRemove = 1
            return False, line
        if self.linesToRemove:
            self.autoRemove = self.linesToRemove - 1
        return True, self.filterWords(line, trigger)
    def getMatchingTrigger(self, line, lineNumber):
        for trigger in self.triggers:
            if trigger.matches(line, lineNumber):
                return trigger
    def filterWords(self, line, trigger=None):
        if self.wordNumber != None:
            words = line.rstrip().split(" ")
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
            return string.join(words).rstrip() + "\n"
        elif trigger and self.replaceText != None:
            return trigger.replace(line, self.replaceText)
        else:
            return None
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
            if len(words[realWordNumber]):
                if wordNumber == self.wordNumber:
                    return realWordNumber
                wordNumber -= 1
        return len(words) + 1

class RemoveObsoleteVersions(plugins.Action):
    def __init__(self):
        self.filesToRemove = []
    def __repr__(self):
        return "Removing obsolete versions for"
    def __call__(self, test):
        self.describe(test)
        compFiles = {}
        for file in os.listdir(test.abspath):
            if test.app.ownsFile(file):
                stem = file.split(".")[0]
                compFile = self.filterFile(test, os.path.join(test.abspath, file))
                if compFiles.has_key(stem):
                    compFiles[stem].append(compFile)
                else:
                    compFiles[stem] = [ compFile ]
        for compFilesMatchingStem in compFiles.values():
            for index1 in range(len(compFilesMatchingStem)):
                for index2 in range(index1 + 1, len(compFilesMatchingStem)):
                    self.compareFiles(test, compFilesMatchingStem[index1], compFilesMatchingStem[index2])
                os.remove(compFilesMatchingStem[index1])
        for file in self.filesToRemove:
            os.system("cvs rm -f " + file)
        self.filesToRemove = []
    def scriptDoc(self):
        return "Removes (from CVS) all files with version IDs that are equivalent to a non-versioned file"
    def cmpFile(self, test, file):
        basename = os.path.basename(file)
        return mktemp(basename + "cmp")
    def origFile(self, test, file):
        if file.endswith("cmp"):
            return os.path.join(test.abspath, os.path.basename(file)[:-3])
        else:
            return file
    def filterFile(self, test, file):
        newFile = self.cmpFile(test, file)
        filter = RunDependentTextFilter(test, os.path.basename(file).split(".")[0])
        return filter.filterFile(file, newFile)
    def compareFiles(self, test, file1, file2):
        origFile1 = self.origFile(test, file1)
        origFile2 = self.origFile(test, file2)
        if origFile1 in self.filesToRemove or origFile2 in self.filesToRemove:
            return
        if filecmp.cmp(file1, file2, 0):
            local1 = os.path.basename(origFile1)
            local2 = os.path.basename(origFile2)
            if local1.find(local2) != -1:
                print test.getIndent() + local1, "obsolete due to", local2
                self.filesToRemove.append(origFile1)
            elif local2.find(local1) != -1:
                print test.getIndent() + local2, "obsolete due to", local1
                self.filesToRemove.append(origFile2)
            else:
                print test.getIndent() + local1, "equivalent to", local2
    def setUpSuite(self, suite):
        self.describe(suite)
