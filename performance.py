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

When differences in performance are reported, you are given the option to save as described below.
The default behaviour is to save the average of the old result and the new result. In order
to override this and save the exact result, append a '+' to the save option that you type.
(so "s+" to save the standard version, "1+" to save the first offered version etc.)
""" + comparetest.helpDescription

# This module won't work without an external module creating a file called performance.app
# This file should be of a format understood by the function below i.e. a single line containing
# CPU time   :      30.31 sec. on heathlands
# 

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
    def __init__(self, test, newFiles):
        comparetest.TestComparison.__init__(self, test, newFiles)
        self.execHost = None
    def __repr__(self):
        if self.execHost != None and self.hasDifferences():
            return "FAILED on " + self.execHost + " :"
        return comparetest.TestComparison.__repr__(self)
    def createFileComparison(self, test, standardFile, tmpFile):
        stem, ext = standardFile.split(".", 1)
        if (stem == "performance"):
            return PerformanceFileComparison(test, standardFile, tmpFile)
        else:
            return comparetest.TestComparison.createFileComparison(self, test, standardFile, tmpFile)
    def shouldCompare(self, file, tmpExt, dirPath):
        if not comparetest.TestComparison.shouldCompare(self, file, tmpExt, dirPath):
            return 0
        stem, ext = file.split(".",1)
        if stem != "performance":
            return 1
        tmpFile = os.path.join(dirPath, file)
        execHost = getPerformanceHost(tmpFile)
        cmpFlag = 0
        self.execHost = execHost
        if execHost != None:
            cmpFlag = execHost in self.test.app.getConfigList("performance_test_machine")
        if cmpFlag == 0:
            os.remove(tmpFile)
        return cmpFlag
        
# Does the same as the basic test comparison apart from when comparing the performance file
class MakeComparisons(comparetest.MakeComparisons):
    def makeTestComparison(self, test):
        return PerformanceTestComparison(test, self.overwriteOnSuccess)

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
        else:
            self.newCPUtime = getPerformance(self.tmpFile)
            self.oldCPUtime = self.newCPUtime
            self.percentageChange = 0.0
    def __repr__(self):
        baseText = comparetest.FileComparison.__repr__(self)
        if self.newResult():
            return baseText
        return baseText + "(" + self.getType() + ")"
    def getType(self):
        if self.newCPUtime < self.oldCPUtime:
            return "faster"
        else:
            return "slower"
    def hasDifferences(self):
        perfList = self.test.app.getConfigList("performance_test_machine")
        if perfList == None or len(perfList) == 0 or perfList[0] == "none":
            return 0
        longEnough = self.newCPUtime > float(self.test.app.getConfigValue("minimum_cputime_for_test"))
        varianceEnough = self.percentageChange > float(self.test.app.getConfigValue("cputime_variation_%"))
        return longEnough and varianceEnough
    def calculatePercentageIncrease(self):
        largest = max(self.oldCPUtime, self.newCPUtime)
        smallest = min(self.oldCPUtime, self.newCPUtime)
        if smallest == 0.0:
            return 0.0
        return ((largest - smallest) / smallest) * 100
    def saveResults(self, destFile):
        # Here we save the average of the old and new performance, assuming fluctuation
        avgPerformance = round((self.oldCPUtime + self.newCPUtime) / 2.0, 2)
        line = open(self.tmpFile).readlines()[0]
        lineToWrite = line.replace(str(self.newCPUtime), str(avgPerformance))
        newFile = open(destFile, "w")
        newFile.write(lineToWrite)
        os.remove(self.tmpFile)

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
