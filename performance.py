#!/usr/local/bin/python
import os, comparetest, string

# This module won't work without an external module creating a file called performance.app
# This file should be of a format understood by the function below i.e. a single line containing
# CPU time   :      30.31 sec. on heathlands

# Returns -1 as error value, if the file is the wrong format
def getPerformance(fileName):
    try:
        line = open(fileName).readline()
        start = line.find(":")
        end = line.find("s", start)
        fullName = line[start + 1:end - 1]
        return float(string.strip(fullName))
    except:
        return float(-1)

def getTestPerformance(test):
    return getPerformance(test.makeFileName("performance")) / 60

# Does the same as the basic test comparison apart from when comparing the performance file
class MakeComparisons(comparetest.MakeComparisons):
    def createFileComparison(self, test, standardFile, tmpFile):
        stem, ext = os.path.splitext(standardFile)
        if (stem == "performance"):
            return PerformanceFileComparison(test, standardFile, tmpFile)
        else:
            return comparetest.FileComparison(test, standardFile, tmpFile)

class PerformanceFileComparison(comparetest.FileComparison):
    def __init__(self, test, standardFile, tmpFile):
        comparetest.FileComparison.__init__(self, test, standardFile, tmpFile)
        if (os.path.exists(self.stdCmpFile)):
            self.oldCPUtime = getPerformance(self.stdCmpFile)
            self.newCPUtime = getPerformance(self.tmpCmpFile)
            self.percentageChange = self.calculatePercentageIncrease()
        # If we didn't understand the old performance, overwrite it
        if (self.oldCPUtime < 0):
            os.remove(self.stdFile)
    def __repr__(self):
        return comparetest.FileComparison.__repr__(self) + "(" + self.getDirection() + ")"
    def getDirection(self):
        if self.newCPUtime < self.oldCPUtime:
            return "faster"
        else:
            return "slower"
    def hasDifferences(self):
        longEnough = self.newCPUtime > float(self.test.app.getConfigValue("minimum_cputime_for_test"))
        varianceEnough = self.percentageChange > float(self.test.app.getConfigValue("cputime_variation_%"))
        return longEnough and varianceEnough
    def calculatePercentageIncrease(self):
        largest = max(self.oldCPUtime, self.newCPUtime)
        smallest = min(self.oldCPUtime, self.newCPUtime)
        return ((largest - smallest) / smallest) * 100

class TimeFilter:
    def __init__(self, timeLimit):
        self.timeLimit = float(timeLimit)
    def acceptsTestCase(self, test):
        testPerformance = getTestPerformance(test)
        return testPerformance < self.timeLimit
    def acceptsTestSuite(self, suite):
        return 1
