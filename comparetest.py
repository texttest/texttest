#!/usr/local/bin/python

helpDescription = """
By default, TextTest collects the application's standard output in output.<app> and standard error
in errors.<app> (this last on UNIX only). You can collect other files for comparison by specifying
[collate_file]
<target>:<source>
, where <source> is some file your application writes (standard UNIX
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
helpScripts = """
comparetest.RemoveObsoleteVersions
                           - For each selected test, compares all files with the same stem with each other
                             and schedules any obsolete versions for removal. For example, if output.app.2
                             is equivalent to output.app, it will be removed, but not if it is equivalent to
                             output.app.3, when only a warning is written.
""" 

import os, filecmp, string, plugins, time
from ndict import seqdict
from predict import FailedPrediction
from shutil import copyfile

plugins.addCategory("success", "succeeded")
plugins.addCategory("failure", "FAILED")

class TestComparison(plugins.TestState):
    def __init__(self, previousInfo, execHost, appAbs):
        plugins.TestState.__init__(self, "failure", "", started=1, completed=1)
        self.execHost = execHost
        self.allResults = []
        self.changedResults = []
        self.newResults = []
        self.correctResults = []
        self.failedPrediction = None
        if isinstance(previousInfo, FailedPrediction):
            self.setFailedPrediction(previousInfo)
        self.diag = plugins.getDiagnostics("TestComparison")
        # Cache this only so it gets output when we pickle, so we can re-interpret if needed...
        self.appAbsPath = appAbs
    def __repr__(self):
        if len(self.changedResults) > 0 or self.failedPrediction:
            return plugins.TestState.__repr__(self)
        elif len(self.newResults) > 0:
            return ":"
        else:
            return ""
    def updateAbsPath(self, newAbsPath):
        self.diag = plugins.getDiagnostics("TestComparison")
        self.diag.info("Updating abspath " + self.appAbsPath + " to " + newAbsPath)
        for comparison in self.allResults:
            comparison.updatePaths(self.appAbsPath, newAbsPath)
        self.appAbsPath = newAbsPath
    def setFailedPrediction(self, prediction):
        self.failedPrediction = prediction
        self.freeText = str(prediction)
        self.briefText = prediction.briefText
        self.category = prediction.category
    def hasNewResults(self):
        return len(self.newResults) > 0
    def hasSucceeded(self):
        return self.category == "success"
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
        details = worstResult.getSummary()
        if len(self.getComparisons()) > 1:
            details += "(+)"
        if worstSeverity == 1:
            return "failure", details
        else:
            return "success", details
    def hasResults(self):
        return len(self.allResults) > 0
    def getComparisons(self):
        return self.changedResults + self.newResults
    def _comparisonsString(self, comparisons):
        return string.join([repr(x) for x in comparisons], ",")
    def getDifferenceSummary(self, actionDesc):
        basicSummary = repr(self) + actionDesc + self._getDifferenceSummary()
        if self.failedPrediction:
            return basicSummary + os.linesep + str(self.failedPrediction)
        else:
            return basicSummary
    def _getDifferenceSummary(self):
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
        if not self.hasResults():
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
        if len(self.changedResults) == 1 and self.changedResults[0].checkExternalExcuses(test.app):
            # If the only difference has an excuse, remove it...
            fileComparison = self.changedResults[0]
            del self.changedResults[0]
            self.correctResults.append(fileComparison)
        # No point categorising if we're overriding everything anyway...
        if not makeNew:
            self.categorise()
    def categorise(self):
        if not self.hasResults():
            errMsg = "No output files at all produced, presuming problems running test" 
            if self.execHost:
                raise plugins.TextTestError, errMsg + " on " + self.execHost
            else:
                raise plugins.TextTestError, errMsg
        if self.failedPrediction:
            # Keep the category we had before
            return
        worstResult = self.getMostSevereFileComparison()
        if not worstResult:
            self.category = "success"
        else:
            self.category = worstResult.getType()
    def makeComparisonsInDir(self, test, dir, makeNew = 0):
        fileList = os.listdir(dir)
        fileList.sort()
        for file in fileList:
            if file == "framework_tmp":
                continue
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
            self.diag.info("Finding standard file from " + result)
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
        return os.path.join(test.abspath, test.makeFileName(local))
    def createFileComparison(self, test, standardFile, tmpFile, makeNew = 0):
        return FileComparison(test, standardFile, tmpFile, makeNew)
    def saveSingle(self, stem, exact = 1, versionString = ""):
        comparison, storageList = self.findComparison(stem)
        if comparison:
            comparison.overwrite(exact, versionString)
            storageList.remove(comparison)
            self.correctResults.append(comparison)
    def findComparison(self, stem):
        for comparison in self.changedResults:
            if comparison.stem == stem:
                return comparison, self.changedResults
        for comparison in self.newResults:
            if comparison.stem == stem:
                return comparison, self.newResults
        return None, None
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
        self.category = "success"

class MakeComparisons(plugins.Action):
    testComparisonClass = TestComparison
    def __repr__(self):
        return "Comparing differences for"
    def execHost(self, test):
        try:
            return test.execHost
        except AttributeError:
            return None
    def __call__(self, test):
        # Don't compare already completed tests if they have errors
        if test.state.isComplete() and not test.state.hasResults():
            return
        testComparison = self.testComparisonClass(test.state, self.execHost(test), test.app.abspath)
        testComparison.makeComparisons(test)
        self.describe(test, testComparison.getPostText())
        test.changeState(testComparison)
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
        filterFileBase = test.makeFileName(os.path.basename(tmpFile), temporary=1, forComparison=0)
        self.stdCmpFile = filter.filterFile(standardFile, filterFileBase + "origcmp")
        tmpCmpFileName = filterFileBase + "cmp"
        if makeNew:
            tmpCmpFileName = filterFileBase + "partcmp"
        self.tmpCmpFile = filter.filterFile(tmpFile, tmpCmpFileName, makeNew)
        self._cacheValues(test.app)
    def _cacheValues(self, app):
        self.differenceId = self._hasDifferences(app)
        self.severity = 99
        failureSeverityDict = app.getConfigValue("failure_severity")
        if failureSeverityDict.has_key(self.stem):
            self.severity = failureSeverityDict[self.stem]
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
        return not self.newResult() and (plugins.modifiedTime(self.stdCmpFile) <= plugins.modifiedTime(self.stdFile))
    def getType(self):
        return "failure"
    def isDiagnostic(self):
        root, local = os.path.split(self.stdFile)
        return os.path.basename(root) == "Diagnostics"
    def getDetails(self):
        # Nothing to report above what is already known
        return ""
    def getSummary(self):
        if self.newResult():
            return self.stem + " new"
        else:
            return self.stem + " different"
    def newResult(self):
        return not os.path.exists(self.stdFile)
    def hasDifferences(self):
        return self.differenceId
    def _hasDifferences(self, app):
        if os.path.isfile(self.stdCmpFile):
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
        if exact:
            copyfile(self.tmpFile, stdFile)
        else:
            self.saveResults(stdFile)
        # Try to get everything to behave normally after a save...
        self.differenceId = 0
        self.tmpFile = stdFile
        self.tmpCmpFile = self.stdCmpFile
        self.stdFile = stdFile
    def saveResults(self, destFile):
        copyfile(self.tmpFile, destFile)
        
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

class RemoveObsoleteVersions(plugins.Action):
    def __init__(self):
        self.filesToRemove = []
    def __repr__(self):
        return "Removing obsolete versions for"
    def __call__(self, test):
        self.describe(test)
        test.makeBasicWriteDirectory()
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
        for file in self.filesToRemove:
            os.system("cvs rm -f " + file)
        self.filesToRemove = []
    def cmpFile(self, test, file):
        basename = os.path.basename(file)
        return test.makeFileName(basename + "cmp", temporary=1, forComparison=0)
    def origFile(self, test, file):
        if file.endswith("cmp"):
            return os.path.join(test.abspath, os.path.basename(file)[:-3])
        else:
            return file
    def filterFile(self, test, file):
        newFile = self.cmpFile(test, file)
        filter = RunDependentTextFilter(test.app, os.path.basename(file).split(".")[0])
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
    def setUpApplication(self, app):
        app.makeWriteDirectory()
