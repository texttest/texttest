#!/usr/local/bin/python

helpDescription = """
Evaluation of test results consists by default of comparing all files that have been collected.
If nothing else is specified, the application's standard output is collected in output.<app>
and standard error is collected in errors.<app>. All files, including these two, are then
filtered using the config file list entries corresponding to the stem of the file name (e.g  "output").
This will remove all run-dependent text like process IDs, timestamps etc., and ensure
that false failures are avoided in this way.

If standard results have not already been collected, the results are reported as new results
and must be checked carefully by hand and saved if correct. If standard results have been
collected, the filtered new results are compared with the standard and any difference
is interpreted as a test failure. 
"""

import os, filecmp, string, plugins

class TestComparison:
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
        if len(self.changedResults) > 1:
            return "difference"
        if len(self.changedResults) > 0:
            return self.changedResults[0].getType()
        else:
            return self.newResults[0].getType()
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
        self.stdCmpFile = test.app.filterFile(standardFile, tmpFile + "origcmp")
        tmpCmpFileName = tmpFile + "cmp"
        if makeNew:
            tmpCmpFileName = tmpFile + "partcmp"
        self.tmpCmpFile = test.app.filterFile(tmpFile, tmpCmpFileName, makeNew)
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
        

