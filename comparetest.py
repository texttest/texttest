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

class MakeComparisons(plugins.Action):
    def __repr__(self):
        return "Comparing differences for" 
    def __call__(self, test):
        comparisons = []
        attemptedComparisons = []
        for tmpExt, subDir in self.fileFinders(test):
            self.makeComparisons(test, tmpExt, subDir, comparisons, attemptedComparisons)
        postText = ""
        if len(comparisons) > 0:
            testComparisonMap[test] = comparisons
        else:
            postText += " - SUCCESS!"
        postText +=  " (on " + string.join(attemptedComparisons, ",") + ")"
        self.describe(test, postText)
    def fileFinders(self, test):
        defaultFinder = test.app.name + test.getTmpExtension(), ""
        return [ defaultFinder ]
    def makeComparisons(self, test, tmpExt, subDirectory, comparisons, attemptedComparisons):
        dirPath = os.path.join(test.abspath, subDirectory)
        for file in os.listdir(dirPath):
            if file.endswith(tmpExt):
                stem, ext = os.path.splitext(file)
                standardFile = os.path.basename(test.makeFileName(stem))
                comparison = self.makeComparison(test, os.path.join(subDirectory, standardFile), os.path.join(subDirectory, file))
                attemptedComparisons.append(standardFile)
                if comparison != None:
                    comparisons.append(comparison)
    def setUpSuite(self, suite):
        self.describe(suite)
#private:
    def makeComparison(self, test, standardFile, tmpFile):
        comparison = self.createFileComparison(test, standardFile, tmpFile)
        if os.path.exists(standardFile):
            if comparison.hasDifferences():
                return comparison
            else:
                os.remove(tmpFile)
        else:
            os.rename(tmpFile, standardFile)
        return None
    def createFileComparison(self, test, standardFile, tmpFile):
        return FileComparison(test, standardFile, tmpFile)

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
    def overwrite(self, version = ""):
        if len(version) and not self.stdFile.endswith("." + version):
            stdFile = self.stdFile + "." + version
        else:
            stdFile = self.stdFile
        if os.path.isfile(stdFile):
            os.remove(stdFile)
        os.rename(self.tmpFile, stdFile)


