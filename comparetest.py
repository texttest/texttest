#!/usr/local/bin/python

helpDescription = """
Evaluation of test results consists by default of comparing all files that have been collected.
If nothing else is specified, the application's standard output is collected in output.<app>
and standard error is collected in errors.<app>.

All files, including these two, are then filtered using the config file list entries corresponding
to the stem of the file name (e.g  "output"). This will remove all run-dependent text like process
IDs, timestamps etc., and ensure that false failures are avoided in this way.

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

If standard results have not already been collected, the results are reported as new results
and must be checked carefully by hand and saved if correct. If standard results have been
collected, the filtered new results are compared with the standard and any difference
is interpreted as a test failure. 
"""

import os, filecmp, string, plugins, re

class TestComparison:
    scoreTable = {}
    scoreTable["difference"] = 2
    scoreTable["faster"] = 1
    scoreTable["slower"] = 1
    scoreTable["larger"] = 0
    scoreTable["smaller"] = 0
    def __init__(self, test, overwriteOnSuccess):
        self.test = test
        self.overwriteOnSuccess = overwriteOnSuccess
        self.changedResults = []
        self.attemptedComparisons = []
        self.newResults = []
        self.failedPrediction = None
        if test.state == test.FAILED:
            self.failedPrediction = test.stateDetails
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
            if self.failedPrediction.find("Stack trace") != -1:
                return "crash"
            else:
                return "badPredict"
        worstType = None
        for result in self.changedResults:
            type = result.getType()
            if not worstType or self.isWorseThan(type, worstType):
                worstType = type
        if worstType:
            return worstType
        else:
            return self.newResults[0].getType()
    def isWorseThan(self, type, worstType):
        return self.scoreTable[type] > self.scoreTable[worstType]
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
        if len(self.attemptedComparisons) == 0:
            return " - NONE!"
        if len(self.newResults) == 0 and len(self.changedResults) == 0:
            return " - SUCCESS! (on " + self.attemptedComparisonsOutput() + ")"
        return " (on " + self.attemptedComparisonsOutput() + ")"
    def attemptedComparisonsOutput(self):
        baseNames = []
        for attempt in self.attemptedComparisons:
            baseNames.append(os.path.basename(attempt))
        return string.join(baseNames, ",")
    def addComparison(self, tmpFile, comparison):
        self.attemptedComparisons.append(tmpFile)
        if comparison == None:
            return
        if comparison.newResult():
            self.newResults.append(comparison)
        else:
            self.changedResults.append(comparison)
    def makeComparisons(self, test, dir, makeNew = 0):
        fileList = os.listdir(dir)
        fileList.sort()
        for file in fileList:
            if os.path.isdir(file):
                self.makeComparisons(test, os.path.join(dir, file))
            elif self.shouldCompare(file, dir, test.app):
                fullPath = os.path.join(dir, file)
                stdFile = os.path.normpath(fullPath.replace(test.app.writeDirectory, test.app.abspath))
                comparison = self.makeComparison(test, stdFile, fullPath, makeNew)
                self.addComparison(fullPath, comparison)
    def shouldCompare(self, file, dir, app):
        return not file.startswith("input.") and app.ownsFile(file)
    def makeComparison(self, test, standardFile, tmpFile, makeNew = 0):
        comparison = self.createFileComparison(test, standardFile, tmpFile, makeNew)
        if comparison.newResult() or comparison.hasDifferences():
            return comparison
        if self.overwriteOnSuccess:
            os.rename(tmpFile, standardFile)
        return None
    def createFileComparison(self, test, standardFile, tmpFile, makeNew = 0):
        return FileComparison(test, standardFile, tmpFile, makeNew)
    def findFileComparison(self, name):
        for comparison in self.getComparisons():
            if comparison.tmpFile == name:
                return comparison
        return None
    def save(self, exact = 1, versionString = ""):
        # Force exactness unless there is only one difference : otherwise
        # performance is averaged when results have changed as well
        resultCount = len(self.changedResults) + len(self.newResults)
        if resultCount > 1:
            exact = 1
        for comparison in self.changedResults:
            comparison.overwrite(exact, versionString)
        for comparison in self.newResults:
            comparison.overwrite(1, versionString)
        self.changedResults = []
        self.newResults = []
        self.test.changeState(self.test.SUCCEEDED, self)

class MakeComparisons(plugins.Action):
    def __init__(self, overwriteOnSuccess):
        self.overwriteOnSuccess = overwriteOnSuccess
    def __repr__(self):
        return "Comparing differences for"
    def __call__(self, test):
        testComparison = self.makeTestComparison(test)
        testComparison.makeComparisons(test, os.getcwd())
        if testComparison.hasDifferences() or testComparison.hasNewResults() or testComparison.failedPrediction:
            test.changeState(test.FAILED, testComparison)
        else:
            test.changeState(test.SUCCEEDED, testComparison)
        self.describe(test, testComparison.getPostText())
    def makeTestComparison(self, test):
        return TestComparison(test, self.overwriteOnSuccess)
    def fileFinders(self, test):
        defaultFinder = test.app.name + test.app.versionSuffix() + test.getTmpExtension(), ""
        return [ defaultFinder ]
    def setUpSuite(self, suite):
        self.describe(suite)

class FileComparison:
    def __init__(self, test, standardFile, tmpFile, makeNew = 0):
        self.stdFile = standardFile
        self.tmpFile = tmpFile
        stem = os.path.basename(tmpFile).split('.')[0]
        filter = RunDependentTextFilter(test.app, stem)
        self.stdCmpFile = filter.filterFile(standardFile, tmpFile + "origcmp")
        tmpCmpFileName = tmpFile + "cmp"
        if makeNew:
            tmpCmpFileName = tmpFile + "partcmp"
        self.tmpCmpFile = filter.filterFile(tmpFile, tmpCmpFileName, makeNew)
        self.test = test
    def __repr__(self):
        return os.path.basename(self.stdFile).split('.')[0]
    def getType(self):
        return "difference"
    def newResult(self):
        return not os.path.exists(self.stdFile)
    def hasDifferences(self):
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
            os.rename(self.tmpFile, stdFile)
        else:
            self.saveResults(stdFile)
    def saveResults(self, destFile):
        os.rename(self.tmpFile, destFile)
        
class RunDependentTextFilter:
    def __init__(self, app, stem):
        self.diag = plugins.getDiagnostics("Run Dependent Text")
        self.lineFilters = []
        for text in app.getConfigList(stem):
            self.lineFilters.append(LineFilter(text, self.diag))
    def filterFile(self, fileName, newFileName, makeNew = 0):
        if not len(self.lineFilters) or not os.path.isfile(fileName):
            self.diag.info("No filter for " + fileName)
            return fileName

        # Don't recreate filtered files
        if os.path.isfile(newFileName):
            if makeNew:
                os.remove(newFileName)
            else:
                return newFileName
        
        newFile = open(newFileName, "w")
        lineNumber = 0
        for line in open(fileName).xreadlines():
            lineNumber += 1
            filteredLine = self.getFilteredLine(line, lineNumber)
            if filteredLine:
                newFile.write(filteredLine)
        self.diag.info("Filter for " + fileName + " returned " + newFileName)
        return newFileName
    def getFilteredLine(self, line, lineNumber):
        for lineFilter in self.lineFilters:
            changed, filteredLine = lineFilter.applyTo(line, lineNumber)
            if changed:
                return filteredLine
        return line

class LineFilter:
    # Order is important here: word processing first, line number last.
    # This is because WORD can be combined with the others, and LINE screws up the model...
    syntaxStrings = [ "{WORD ", "{LINES ", "{->}", "{LINE " ]
    def __init__(self, text, diag):
        self.diag = diag
        self.trigger = text
        self.untrigger = None
        self.triggerNumber = 0
        self.linesToRemove = 1
        self.autoRemove = 0
        self.wordNumber = 0
        for syntaxString in self.syntaxStrings:
            linePoint = self.trigger.find(syntaxString)
            if linePoint != -1:
                beforeText = self.trigger[:linePoint]
                afterText = self.trigger[linePoint + len(syntaxString):]
                self.readSyntax(syntaxString, beforeText, afterText)
        if self.trigger:
            self.trigger = TextTrigger(self.trigger)
        if self.untrigger:
            self.untrigger = TextTrigger(self.untrigger)
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
        if self.wordNumber:
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

class TextTrigger:
    specialChars = re.compile("[\^\$\[\]\{\}\\\*\?\|]")    
    def __init__(self, text):
        self.text = text
        self.regex = None
        if self.specialChars.search(text) != None:
            self.regex = re.compile(text)
    def matches(self, line):
        if self.regex:
            return self.regex.search(line)
        else:
            return line.find(self.text) != -1
