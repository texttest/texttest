#!/usr/local/bin/python

helpDescription = """
By default, TextTest collects the application's standard output in output.<app> and standard error
in errors.<app> (this last on UNIX only). You can collect other files for comparison by specifying
collate_file:<source>-><target>, where <source> is some file your application writes (standard UNIX
pattern matching is allowed here, e.g *.myext), and <target> is what you want it to be called by TextTest.

Evaluation of test results consists by default of comparing all files that have been collected.

All files are then filtered using the config file dictionary entry 'run_dependent_text', with
list entries corresponding to the stem of the file name (e.g  "output"). This will remove all
run-dependent text like process IDs, timestamps etc., and ensure that false failures are avoided
in this way.

Various extensions are available. The following is a summary of what will happen...

output:remove this          - Lines containing the text "remove this" in the file output are filtered out
                              Note that the text may be a regular expression, which will be matched
output:remove this{LINES 3} - Any line containing the text "remove this" will cause 3 lines starting
                              with it to be filtered out
output:{LINE 5}             - will cause the fifth line to be filtered out
my_file:remove this{WORD 1} - Lines containing the text "remove this" in my_file will have their 1st word
                              filtered out. Use negative numbers to count from the end of the line: i.e.
                              {WORD -2} will remove the second-to-last word.
output:start{->}end         - On encountering the text "start", all lines are filtered out until the text
                              "end" is encountered. Neither the line containing "start" nor the line containing
                              "end" are themselves filtered.

You can also use the config file dictionary entry 'unordered_text' in a similar way. Note that in this
case the matching text is not removed, but assumed to be in random order. It is therefore sorted and appears
in a section of its own at the end.

If standard results have not already been collected, the results are reported as new results
and must be checked carefully by hand and saved if correct. If standard results have been
collected, the filtered new results are compared with the standard and any difference
is interpreted as a test failure. 
"""

import os, filecmp, string, plugins
from ndict import seqdict
from predict import FailedPrediction

class TestComparison:
    def __init__(self, test):
        self.test = test
        self.allResults = []
        self.changedResults = []
        self.newResults = []
        self.correctResults = []
        self.failedPrediction = None
        if isinstance(test.stateDetails, FailedPrediction):
            self.failedPrediction = test.stateDetails
        self.diag = plugins.getDiagnostics("TestComparison")
    def __repr__(self):
        if len(self.changedResults) > 0 or self.failedPrediction:
            return "FAILED :"
        elif len(self.newResults) > 0:
            return ":"
        else:
            return ""
    def hasNewResults(self):
        return len(self.newResults) > 0
    def hasDifferences(self):
        return len(self.changedResults) > 0
    def getType(self):
        if self.failedPrediction:
            return self.failedPrediction.type
        else:
            return self.getMostSevereFileComparison().getType()
    def getMostSevereFileComparison(self):
        worstSeverity = None
        worstResult = None
        for result in self.changedResults:
            severity = result.getSeverity()
            if not worstSeverity or severity < worstSeverity:
                worstSeverity = severity
                worstResult = result
        if worstResult:
            return worstResult
        else:
            return self.newResults[0]
        return worstResult
    def getTypeBreakdown(self):
        if self.failedPrediction:
            if self.failedPrediction.type == "crash":
                return "failure", "CRASHED"
            elif self.failedPrediction.type == "bug":
                return "success", "known bug"
            else:
                return "failure", "internal error"
        worstResult = self.getMostSevereFileComparison()
        worstSeverity = worstResult.getSeverity()
        self.diag.info("Severity " + str(worstSeverity) + " for failing test")
        if worstSeverity == 1:
            return "failure", worstResult.getSummary()
        else:
            return "success", worstResult.getSummary()
    def getComparisons(self):
        return self.changedResults + self.newResults
    def _comparisonsString(self, comparisons):
        return string.join([repr(x) for x in comparisons], ",")
    def getDifferenceSummary(self):
        diffText = ""
        if len(self.changedResults) > 0:
            diffText = " differences in " + self._comparisonsString(self.changedResults)
        if len(self.newResults) == 0:
            return diffText
        newText = " new results in " + self._comparisonsString(self.newResults)
        if len(self.changedResults) == 0:
            return newText
        return newText + "," + diffText
    def getPostText(self):
        if len(self.allResults) == 0:
            return " - NONE!"
        if len(self.newResults) == 0 and len(self.changedResults) == 0:
            return " - SUCCESS! (on " + self.attemptedComparisonsOutput() + ")"
        return " (on " + self.attemptedComparisonsOutput() + ")"
    def attemptedComparisonsOutput(self):
        baseNames = []
        for comparison in self.allResults:
            baseNames.append(os.path.basename(comparison.tmpFile))
        return string.join(baseNames, ",")
    def addComparison(self, comparison):
        self.allResults.append(comparison)
        if comparison.newResult():
            self.newResults.append(comparison)
        elif comparison.hasDifferences():
            self.changedResults.append(comparison)
        else:
            self.correctResults.append(comparison)
    def makeComparisons(self, test, makeNew = 0):
        self.makeComparisonsInDir(test, test.getDirectory(temporary=1), makeNew)
        if len(self.changedResults) == 1 and self.changedResults[0].checkExternalExcuses():
            # If the only difference has an excuse, remove it...
            fileComparison = self.changedResults[0]
            del self.changedResults[0]
            self.correctResults.append(fileComparison)
    def makeComparisonsInDir(self, test, dir, makeNew = 0):
        fileList = os.listdir(dir)
        fileList.sort()
        for file in fileList:
            fullPath = os.path.join(dir, file)
            if os.path.isdir(file):
                self.makeComparisonsInDir(test, fullPath, makeNew)
            elif self.shouldCompare(file, dir, test.app):
                self.diag.info("Decided we should compare " + file)
                stdFile = self.findTestDirectory(fullPath, test)
                self.diag.info("Using standard file " + stdFile)
                comparison = self.createFileComparison(test, stdFile, fullPath, makeNew)
                self.addComparison(comparison)
            else:
                self.diag.info("Rejected " + file)
    def shouldCompare(self, file, dir, app):
        return not file.startswith("input.") and not file.startswith("environment") and app.ownsFile(file)
    def findTestDirectory(self, fullPath, test):
        result = os.path.normpath(fullPath.replace(test.app.writeDirectory, test.app.abspath))
        if result != fullPath:
            return self.getStandardFile(result, test)
        # writeDir contains so
        savedir = os.getcwd()
        os.chdir(test.app.writeDirectory)
        result = os.path.normpath(fullPath.replace(os.getcwd(), test.app.abspath))
        os.chdir(savedir)
        return self.getStandardFile(result, test)
    def getStandardFile(self, fullPath, test):
        realPath = os.path.normpath(fullPath)
        local = realPath.replace(test.abspath + os.sep, "")
        if local.find(os.sep) == -1:
            return realPath
        # Find standard file in subdirectory
        return os.path.join(test.abspath, test.makeFileName(local))
    def createFileComparison(self, test, standardFile, tmpFile, makeNew = 0):
        return FileComparison(test, standardFile, tmpFile, makeNew)
    def save(self, exact = 1, versionString = "", overwriteSuccessFiles = 0):
        # Force exactness unless there is only one difference : otherwise
        # performance is averaged when results have changed as well
        resultCount = len(self.changedResults) + len(self.newResults)
        if resultCount > 1:
            exact = 1
        for comparison in self.changedResults:
            comparison.overwrite(exact, versionString)
        for comparison in self.newResults:
            comparison.overwrite(1, versionString)
        if overwriteSuccessFiles:
            for comparison in self.correctResults:
                comparison.overwrite(exact, versionString)
        self.correctResults += self.changedResults + self.newResults
        self.changedResults = []
        self.newResults = []
        self.test.changeState(self.test.SUCCEEDED, self)

class MakeComparisons(plugins.Action):
    def __repr__(self):
        return "Comparing differences for"
    def __call__(self, test):
        # Don't compare killed tests...
        if test.state == test.KILLED:
            return
        testComparison = self.makeTestComparison(test)
        testComparison.makeComparisons(test)
        if testComparison.hasDifferences() or testComparison.hasNewResults() or testComparison.failedPrediction:
            test.changeState(test.FAILED, testComparison)
        else:
            test.changeState(test.SUCCEEDED, testComparison)
        self.describe(test, testComparison.getPostText())
    def makeTestComparison(self, test):
        return TestComparison(test)
    def fileFinders(self, test):
        defaultFinder = test.app.name + test.app.versionSuffix() + test.getTmpExtension(), ""
        return [ defaultFinder ]
    def setUpSuite(self, suite):
        self.describe(suite)

class FileComparison:
    def __init__(self, test, standardFile, tmpFile, makeNew = 0):
        self.stdFile = standardFile
        self.tmpFile = tmpFile
        self.stem = os.path.basename(tmpFile).split('.')[0]
        filter = RunDependentTextFilter(test.app, self.stem)
        self.stdCmpFile = filter.filterFile(standardFile, tmpFile + "origcmp")
        tmpCmpFileName = tmpFile + "cmp"
        if makeNew:
            tmpCmpFileName = tmpFile + "partcmp"
        self.tmpCmpFile = filter.filterFile(tmpFile, tmpCmpFileName, makeNew)
        self.test = test
        self.differenceId = -1
    def __repr__(self):
        return os.path.basename(self.stdFile).split('.')[0]
    def checkExternalExcuses(self):
        # No excuses here...
        return 0
    def getType(self):
        return "difference"
    def isDiagnostic(self):
        root, local = os.path.split(self.stdFile)
        return os.path.basename(root) == "Diagnostics"
    def getSummary(self):
        if self.newResult():
            return "new files"
        else:
            return self.stem + " different"
    def getSeverity(self):
        dict = self.test.getConfigValue("failure_severity")
        if dict.has_key(self.stem):
            return dict[self.stem]
        else:
            return 99
    def newResult(self):
        return not os.path.exists(self.stdFile)
    def hasDifferences(self):
        # Cache the result: typically expensive to compute...
        if self.differenceId == -1:
            self.differenceId = self._hasDifferences()
        return self.differenceId
    def _hasDifferences(self):
        return not filecmp.cmp(self.stdCmpFile, self.tmpCmpFile, 0)
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
        if exact:
            plugins.movefile(self.tmpFile, stdFile)
        else:
            self.saveResults(stdFile)
        # Try to get everything to behave normally after a save...
        self.differenceId = 0
        self.tmpFile = stdFile
        self.tmpCmpFile = self.stdCmpFile
    def saveResults(self, destFile):
        plugins.movefile(self.tmpFile, destFile)
        
class RunDependentTextFilter:
    def __init__(self, app, stem):
        self.diag = plugins.getDiagnostics("Run Dependent Text")
        self.contentFilters = []
        self.orderFilters = seqdict()
        dict = app.getConfigValue("run_dependent_text")
        if dict.has_key(stem):
            for text in dict[stem]:
                self.contentFilters.append(LineFilter(text, self.diag))
        dict = app.getConfigValue("unordered_text")
        if dict.has_key(stem):
            for text in dict[stem]:
                orderFilter = LineFilter(text, self.diag)
                self.orderFilters[orderFilter] = []
    def hasFilters(self):
        return len(self.contentFilters) > 0 or len(self.orderFilters) > 0
    def filterFile(self, fileName, newFileName, makeNew = 0):
        if not self.hasFilters() or not os.path.isfile(fileName):
            self.diag.info("No filter for " + fileName)
            return fileName

        # Don't recreate filtered files
        if os.path.isfile(newFileName):
            if makeNew:
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
                return filteredLine
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
            newFile.write("-- Unordered text as found by filter '" + filter.originalText + "' --" + os.linesep)
            for line in linesFiltered:
                newFile.write(line)
            newFile.write(os.linesep)
            self.orderFilters[filter] = []

class LineFilter:
    # Order is important here: word processing first, line number last.
    # This is because WORD can be combined with the others, and LINE screws up the model...
    syntaxStrings = [ "{WORD ", "{LINES ", "{->}", "{LINE " ]
    def __init__(self, text, diag):
        self.originalText = text
        self.diag = diag
        self.trigger = text
        self.untrigger = None
        self.triggerNumber = 0
        self.linesToRemove = 1
        self.autoRemove = 0
        self.wordNumber = None
        for syntaxString in self.syntaxStrings:
            linePoint = self.trigger.find(syntaxString)
            if linePoint != -1:
                beforeText = self.trigger[:linePoint]
                afterText = self.trigger[linePoint + len(syntaxString):]
                self.readSyntax(syntaxString, beforeText, afterText)
        if self.trigger:
            self.trigger = plugins.TextTrigger(self.trigger)
        if self.untrigger:
            self.untrigger = plugins.TextTrigger(self.untrigger)
    def reset(self):
        self.autoRemove = 0
    def readSyntax(self, syntaxString, beforeText, afterText):
        if syntaxString == "{WORD ":
            self.trigger = beforeText
            self.wordNumber = int(afterText[:-1])
            # Somewhat non-intuitive to count from 0...
            if self.wordNumber > 0:
                self.wordNumber -= 1
        elif syntaxString == "{LINES ":
            self.trigger = beforeText
            self.linesToRemove = int(afterText[:-1])
        elif syntaxString == "{LINE ":
            self.trigger = None
            self.triggerNumber = int(afterText[:-1])
        elif syntaxString == "{->}":
            self.trigger = beforeText
            self.untrigger = afterText
    def applyTo(self, line, lineNumber):
        if self.autoRemove:
            if self.untrigger:
                if self.untrigger.matches(line.strip()):
                    self.autoRemove = 0
                    return 0, line
            else:
                self.autoRemove -= 1
            return 1, self.filterWords(line)
        
        if self.triggerNumber == lineNumber:
            return 1, self.filterWords(line)

        if self.checkMatch(line.strip()):
            return 1, self.filterWords(line)
        else:
            return 0, line
    def checkMatch(self, line):
        if self.trigger and self.trigger.matches(line):
            if self.untrigger:
                self.autoRemove = 1
                return 0
            if self.linesToRemove:
                self.autoRemove = self.linesToRemove - 1
            return 1
        else:
            return 0
    def filterWords(self, line):
        if self.wordNumber != None:
            words = line.rstrip().split(" ")
            self.diag.info("Removing word " + str(self.wordNumber) + " from " + repr(words))
            realNumber = self.findRealWordNumber(words)
            self.diag.info("Real number was " + str(realNumber))
            try:
                del words[realNumber]
                return string.join(words).rstrip() + os.linesep
            except IndexError:
                return line
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

