#!/usr/local/bin/python

import os, comparetest, string, plugins

helpDescription = """
Performance analysis makes use of files containing a single line, which
looks like:
CPU time :     30.31 sec. on apple
where "apple" is some host name.

Instead of the default file comparison described below, these files are evaluated
as follows. First, the execution machine (apple) is looked for in the config file
list entry called "performance_test_machine". If our execution machine is not in
this list, performance information is disregarded. If it is in this list, the number
of seconds is extracted. If this is then less than the config file entry
"minimum_cputime_for_test", performance information is also disregarded. If the
test ran on a performance test machine and it ran for long enough for performance
checking to be worthwhile, the deviation from the standard performance in percentage
is checked. If it is greater than the config file entry "cputime_variation_%", failure
is reported.
""" + comparetest.helpDescription

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

def getTestPerformance(test, version = None):
    return getPerformance(test.makeFileName("performance", version)) / 60

def getPerformanceHost(fileName):
    try:
        parts = open(fileName).readline().split()
        if parts[-2] == "on":
            return parts[-1]
    except:
        pass
    return None

class PerformanceTestComparison(comparetest.TestComparison):
    def __init__(self, test, comparisonMaker):
        comparetest.TestComparison.__init__(self, test)
        self.comparisonMaker = comparisonMaker
    def __repr__(self):
        if self.comparisonMaker.execHost == None:
            return comparetest.TestComparison.__repr__(self)
        if len(self.comparisons) > 0:
            return "FAILED on " + self.comparisonMaker.execHost + " :"
        else:
            return ""
        
# Does the same as the basic test comparison apart from when comparing the performance file
class MakeComparisons(comparetest.MakeComparisons):
    def __init__(self):
        self.execHost = None
    def createFileComparison(self, test, standardFile, tmpFile):
        stem, ext = os.path.splitext(standardFile)
        if (stem == "performance"):
            return PerformanceFileComparison(test, standardFile, tmpFile)
        else:
            return comparetest.FileComparison(test, standardFile, tmpFile)
    def shouldCompare(self, file, test, tmpExt, dirPath):
        if not comparetest.MakeComparisons.shouldCompare(self, file, test, tmpExt, dirPath):
            return 0
        stem, ext = os.path.splitext(file)
        if stem != "performance":
            return 1
        self.execHost = getPerformanceHost(os.path.join(dirPath, file))
        if self.execHost != None:
            return self.execHost in test.app.getConfigList("performance_test_machine")
        else:
            return 0
    def makeTestComparison(self, test):
        return PerformanceTestComparison(test, self)

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
        return comparetest.FileComparison.__repr__(self) + "(" + self.getType() + ")"
    def getType(self):
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

class TimeFilter(plugins.Filter):
    def __init__(self, timeLimit):
        self.minTime = 0.0
        self.maxTime = None
        times = timeLimit.split(",")
        if len(times) == 1:
            self.maxTime = float(timeLimit)
        else:
            self.minTime = float(times[0])
            if len(times[1]):
                self.maxTime = float(times[1])
    def acceptsTestCase(self, test):
        testPerformance = getTestPerformance(test)
        return testPerformance > self.minTime and (self.maxTime == None or testPerformance < self.maxTime)
