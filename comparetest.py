#!/usr/local/bin/python
import os, filecmp, string

testComparisonMap = {}

class MakeComparisons:
    def __repr__(self):
        return "Comparing differences for" 
    def __call__(self, test, description):
        comparisons = []
        attemptedComparisons = []
        for file in os.listdir(test.abspath):
            if file.endswith(test.getTmpExtension()):
                stem, ext = os.path.splitext(file)
                standardFile = os.path.basename(test.makeFileName(stem))
                comparison = self.makeComparison(test, standardFile, file)
                attemptedComparisons.append(standardFile)
                if comparison != None:
                    comparisons.append(comparison)
        if len(comparisons) > 0:
            testComparisonMap[test] = comparisons
        else:
            description += " - SUCCESS!"
        description +=  " (on " + string.join(attemptedComparisons, ",") + ")"
        print description
    def setUpSuite(self, suite, description):
        print description
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
        return self.stdFile.split('.')[0]
    def hasDifferences(self):
        return not filecmp.cmp(self.stdCmpFile, self.tmpCmpFile)
    def overwrite(self, version = ""):
        if len(version) and not self.stdFile.endswith("." + version):
            stdFile = self.stdFile + "." + version
        else:
            stdFile = self.stdFile
        if os.path.isfile(stdFile):
            os.remove(stdFile)
        os.rename(self.tmpFile, stdFile)


