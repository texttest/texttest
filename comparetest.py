#!/usr/local/bin/python
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
        defaultFinder = test.getTmpExtension(), ""
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


