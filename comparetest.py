#!/usr/local/bin/python

helpDescription = """
Evaluation of test results consists by default of comparing all files that have been collected.
If nothing else is specified, the application's standard output is collected in output.<app>
and standard error is collected in errors.<app>. All files, including these two, are then
filtered using the config file list entries corresponding to the stem of the file name (e.g  "output").
This will remove all run-dependent text like process IDs, timestamps etc., and ensure
that false failures are avoided in this way.

If standard results have not already been collected, the results are saved as the new
standard results and must be checked carefully by hand. If standard results have been
collected, the filtered new results are compared with the standard and any difference
is interpreted as a test failure. 
"""

import os, filecmp, string, plugins

testComparisonMap = {}

class TestComparison:
    def __init__(self, test, newFiles):
        self.test = test
        self.newFiles = newFiles
        self.comparisons = []
        self.attemptedComparisons = []
    def __repr__(self):
        if len(self.comparisons) > 0:
            return "FAILED :"
        else:
            return ""
    def hasDifferences(self):
        return len(self.comparisons) > 0
    def getPostText(self):
        postText = ""
        if len(self.comparisons) == 0:
            if len(self.attemptedComparisons) == 0:
                postText += " - NONE!"
            else:
                postText += " - SUCCESS!"
        if len(self.attemptedComparisons) > 0:
            postText +=  " (on " + string.join(self.attemptedComparisons, ",") + ")"
        return postText
    def addComparison(self, standardFile, comparison):
        self.attemptedComparisons.append(standardFile)
        if comparison != None:
            self.comparisons.append(comparison)
    def makeComparisons(self, test, tmpExt, subDirectory):
        dirPath = os.path.join(test.abspath, subDirectory)
        fileList = os.listdir(dirPath)
        fileList.sort()
        for file in fileList:
            if self.shouldCompare(file, tmpExt, dirPath):
                stem, ext = file.split(".", 1)
                standardFile = os.path.basename(test.makeFileName(stem))
                comparison = self.makeComparison(test, os.path.join(subDirectory, standardFile), os.path.join(subDirectory, file))
                self.addComparison(standardFile, comparison)
    def shouldCompare(self, file, tmpExt, dirPath):
        return file.endswith(tmpExt)
    def makeComparison(self, test, standardFile, tmpFile):
        comparison = self.createFileComparison(test, standardFile, tmpFile)
        if os.path.exists(standardFile):
            if comparison.hasDifferences():
                return comparison
            elif self.newFiles:
                os.rename(tmpFile, standardFile)
            else:
                os.remove(tmpFile)
        else:
            os.rename(tmpFile, standardFile)
        return None
    def createFileComparison(self, test, standardFile, tmpFile):
        return FileComparison(test, standardFile, tmpFile)
    def save(self, exact = 1, versionString = ""):
        for comparison in self.comparisons:
            comparison.overwrite(exact, versionString)


class MakeComparisons(plugins.Action):
    def __init__(self, newFiles):
        self.newFiles = newFiles
    def __repr__(self):
        return "Comparing differences for"
    def __call__(self, test):
        testComparison = self.makeTestComparison(test)
        for tmpExt, subDir in self.fileFinders(test):
            testComparison.makeComparisons(test, tmpExt, subDir)
        if testComparison.hasDifferences():
            testComparisonMap[test] = testComparison
        self.describe(test, testComparison.getPostText())
    def makeTestComparison(self, test):
        return TestComparison(test, self.newFiles)
    def fileFinders(self, test):
        defaultFinder = test.app.name + test.app.versionSuffix() + test.getTmpExtension(), ""
        return [ defaultFinder ]
    def setUpSuite(self, suite):
        self.describe(suite)

class FileComparison:
    def __init__(self, test, standardFile, tmpFile):
        self.stdFile = standardFile
        self.tmpFile = tmpFile
        self.stdCmpFile = test.app.filterFile(standardFile)
        self.tmpCmpFile = test.app.filterFile(tmpFile)
        self.test = test
    def __del__(self):
        if self.tmpFile != self.tmpCmpFile and os.path.isfile(self.tmpCmpFile):
            os.remove(self.tmpCmpFile)
        if self.stdFile != self.stdCmpFile and os.path.isfile(self.stdCmpFile):
            os.remove(self.stdCmpFile)
    def __repr__(self):
        return os.path.basename(self.stdFile).split('.')[0]
    def getType(self):
        return "difference"
    def hasDifferences(self):
        return not filecmp.cmp(self.stdCmpFile, self.tmpCmpFile, 0)
    def overwrite(self, exact, versionString = ""):
        newVersions = versionString.split(".")
        stdFile = self.stdFile
        for version in newVersions:
            ext = "." + version
            if self.stdFile.find(ext) == -1:
                stdFile += ext
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
        

