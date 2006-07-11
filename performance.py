#!/usr/local/bin/python

import os, comparetest, string, plugins, sys

# This module won't work without an external module creating a file called performance.app
# This file should be of a format understood by the function below i.e. a single line containing
# CPU time   :      30.31 sec. on heathlands
# 

# For memory the same is true, and the format is
# Max Memory :       45 MB

plugins.addCategory("smaller", "memory-", "used less memory")
plugins.addCategory("larger", "memory+", "used more memory")
plugins.addCategory("faster", "faster", "ran faster")
plugins.addCategory("slower", "slower", "ran slower")

# Returns -1 as error value, if the file is the wrong format
def getPerformance(fileName):
    if not fileName:
        return float(-1)
    line = open(fileName).readline()
    pos = line.find(":")
    if pos == -1:
        return float(-1)
    return float(line[pos + 1:].lstrip().split()[0])
    
def getTestPerformance(test, version = None):
    return getPerformance(test.getFileName("performance", version))

def getTestMemory(test, version = None):
    return getPerformance(test.getFileName("memory", version))

def parseTimeExpression(timeExpression):
    # Starts with <, >, <=, >= ?
    if timeExpression == "":
        return "", 0
    if timeExpression.startswith("<="):
        return "<=", plugins.getNumberOfSeconds(timeExpression[2:])
    if timeExpression.startswith("<"):
        return "<", plugins.getNumberOfSeconds(timeExpression[1:])
    if timeExpression.startswith(">="):
        return ">=", plugins.getNumberOfSeconds(timeExpression[2:])
    if timeExpression.startswith(">"):
        return ">", plugins.getNumberOfSeconds(timeExpression[1:])  

class PerformanceTestComparison(comparetest.TestComparison):
    def getPerformanceStems(self, test):
        return [ "performance" ] + test.getConfigValue("performance_logfile_extractor").keys()
    def createFileComparison(self, test, stem, standardFile, tmpFile, testInProgress):
        if stem in self.getPerformanceStems(test):
            if tmpFile:
                descriptors = self.findDescriptors(stem)
                return PerformanceFileComparison(test, stem, standardFile, tmpFile, descriptors, testInProgress)
            else:
                # Don't care if performance is missing
                return None
        else:
            return comparetest.TestComparison.createFileComparison(self, test, stem, standardFile, tmpFile, testInProgress)
    def findDescriptors(self, stem):
        descriptors = {}
        if stem == "memory":
            descriptors["goodperf"] = "smaller"
            descriptors["badperf"] = "larger"
            descriptors["config"] = "memory"
        elif stem == "performance":
            descriptors["goodperf"] = "faster"
            descriptors["badperf"] = "slower"
            descriptors["config"] = "cputime"
        else:
            descriptors["config"] = stem
            if stem.find("mem") != -1:
                descriptors["goodperf"] = "smaller(" + stem + ")"
                descriptors["badperf"] = "larger(" + stem + ")"
            else:
                descriptors["goodperf"] = "faster(" + stem + ")"
                descriptors["badperf"] = "slower(" + stem + ")"
        return descriptors

class PerformanceFileComparison(comparetest.FileComparison):
    def __init__(self, test, stem, standardFile, tmpFile, descriptors, testInProgress):
        self.descriptors = descriptors
        # Don't allow process count of 0, which screws things up...
        self.processCount = max(len(test.state.executionHosts), 1)
        comparetest.FileComparison.__init__(self, test, stem, standardFile, tmpFile, testInProgress)
        self.diag.info("Checking test " + test.name + " process count " + str(self.processCount))
    def _cacheValues(self, app):
        if self.stdCmpFile:
            self.oldPerformance = getPerformance(self.stdCmpFile)
            self.newPerformance = getPerformance(self.tmpCmpFile)
            self.diag.info("Performance is " + str(self.oldPerformance) + " and " + str(self.newPerformance))
            self.percentageChange = self.calculatePercentageIncrease()
            # If we didn't understand the old performance, overwrite it
            if (self.oldPerformance < 0):
                os.remove(self.stdFile)
        else:
            self.newPerformance = getPerformance(self.tmpFile)
            self.oldPerformance = self.newPerformance
            self.percentageChange = 0.0
        comparetest.FileComparison._cacheValues(self, app)
    def __repr__(self):
        baseText = comparetest.FileComparison.__repr__(self)
        if self.newResult():
            return baseText
        return baseText + "(" + self.getType() + ")"
    def getType(self):
        if self.newResult():
            return comparetest.FileComparison.getType(self)
        if self.newPerformance < self.oldPerformance:
            return self.descriptors["goodperf"]
        else:
            return self.descriptors["badperf"]
    def getSummary(self):
        type = self.getType()
        return str(int(self.calculatePercentageIncrease())) + "% " + type
    def getDetails(self):
        if self.hasDifferences():
            return self.getSummary()
        else:
            return ""
    def getConfigSetting(self, app, configDescriptor, configName):
        return self.processCount * float(app.getCompositeConfigValue(configName, configDescriptor))
    def _hasDifferences(self, app):
        configDescriptor = self.descriptors["config"]
        longEnough = self.newPerformance > self.getConfigSetting(app, configDescriptor, "performance_test_minimum")
        varianceEnough = self.percentageChange > self.getConfigSetting(app, configDescriptor, "performance_variation_%")
        return longEnough and varianceEnough
    def calculatePercentageIncrease(self):
        largest = max(self.oldPerformance, self.newPerformance)
        smallest = min(self.oldPerformance, self.newPerformance)
        if smallest == 0.0:
            return 0.0
        return ((largest - smallest) / smallest) * 100
    def saveResults(self, destFile):
        # Here we save the average of the old and new performance, assuming fluctuation
        avgPerformance = round((self.oldPerformance + self.newPerformance) / 2.0, 2)
        line = open(self.tmpFile).readlines()[0]
        lineToWrite = line.replace(str(self.newPerformance), str(avgPerformance))
        newFile = open(destFile, "w")
        newFile.write(lineToWrite)
        try:
            os.remove(self.tmpFile)
        except OSError:
            # May not have permission, don't worry if not
            pass

class TimeFilter(plugins.Filter):
    option = "r"
    def __init__(self, timeLimit):
        self.minTime = 0.0
        self.maxTime = sys.maxint
        times = plugins.commasplit(timeLimit)
        if timeLimit.count("<") == 0 and timeLimit.count(">") == 0: # Backwards compatible
            if len(times) == 1:
                self.maxTime = plugins.getNumberOfSeconds(timeLimit)
            else:
                self.minTime = plugins.getNumberOfSeconds(times[0])
                if len(times[1]):
                    self.maxTime = plugins.getNumberOfSeconds(times[1])
        else:
            for expression in times:
                parsedExpression = parseTimeExpression(expression)
                if parsedExpression[0] == "":
                    continue
                elif parsedExpression[0] == "<":
                    self.adjustMaxTime(parsedExpression[1] - 1) # We don't care about fractions of seconds ...
                elif parsedExpression[0] == "<=":
                    self.adjustMaxTime(parsedExpression[1]) 
                elif parsedExpression[0] == ">":
                    self.adjustMinTime(parsedExpression[1] + 1) # We don't care about fractions of seconds ...
                else:
                    self.adjustMinTime(parsedExpression[1])
    def adjustMinTime(self, newMinTime):
        if newMinTime > self.minTime:
            self.minTime = newMinTime
    def adjustMaxTime(self, newMaxTime):
        if newMaxTime < self.maxTime:
            self.maxTime = newMaxTime
    def acceptsTestCase(self, test):
        testPerformance = getTestPerformance(test)
        if testPerformance < 0:
            return 1
        return testPerformance >= self.minTime and testPerformance <= self.maxTime

class AddTestPerformance(plugins.Action):
    def __init__(self):
        self.performance = 0.0
        self.numberTests = 0
    def __repr__(self):
        return "Adding performance for"
    def __call__(self, test):
        testPerformance = getTestPerformance(test) / 60 # getTestPerformance returns seconds now ...
        if os.environ.has_key("LSF_PROCESSES"):
            parCPUs = int(os.environ["LSF_PROCESSES"])
            self.describe(test, ": " + str(int(testPerformance)) + " minutes * " + str(parCPUs))
            if parCPUs > 0:
                testPerformance *= parCPUs
        else:
            self.describe(test, ": " + str(int(testPerformance)) + " minutes")
        self.performance += testPerformance
        self.numberTests += 1
    def __del__(self):
        print "Added-up test performance (for " + str(self.numberTests) + " tests) is " + str(int(self.performance)) + " minutes (" + str(int(self.performance/60)) + " hours)"
        
def percentDiff(perf1, perf2):
    if perf2 != 0:
        return int((perf1 / perf2) * 100.0)
    else:
        return 0

class PerformanceStatistics(plugins.Action):
    def __init__(self, args = []):
        self.referenceVersion = ""
        self.currentVersion = None
        self.limit = 0
        self.file = "performance"
        self.interpretOptions(args)
    def interpretOptions(self, args):
        for ar in args:
            arr = ar.split("=")
            if arr[0]=="v":
                versions = arr[1].split(",")
                self.referenceVersion = versions[0]
                self.currentVersion = None
                if len(versions) > 1:
                    self.currentVersion = versions[1]
            elif arr[0]=="f":
                self.file = arr[1]
            elif arr[0]=="l":
                try:
                    self.limit = int(arr[1])
                except:
                    self.limit = 0
            else:
                print "Unknown option " + arr[0]
    def scriptDoc(self):
        return "Prints a report on system resource usage per test. Can compare versions"
    def setUpSuite(self, suite):
        self.suiteName = suite.name + "\n" + "   "
    def __call__(self, test):
        refPerf = getPerformance(test.getFileName(self.file, self.referenceVersion))
        if self.currentVersion is not None:
            currPerf = getPerformance(test.getFileName(self.file, self.currentVersion))
            pDiff = percentDiff(currPerf, refPerf)
            if self.limit == 0 or pDiff > self.limit:
                print self.suiteName + test.name.ljust(30) + "\t", \
                      self.format(refPerf), self.format(currPerf), "\t" + str(pDiff) + "%"
                self.suiteName = "   "
        else:
            print self.rowHeader(test), self.format(refPerf)
    def rowHeader(self, test):
        return self.suiteName + test.name.ljust(30) + "\t"
    def format(self, number):
        if self.file.find("mem") != -1:
            return self.formatMemory(number)
        else:
            return self.formatTime(number)
    def formatMemory(self, memUsed):
        return str(memUsed) + " MB"
    def formatTime(self, seconds):
        intSec = int(seconds)
        intMin = intSec / 60
        secPart = intSec - (intMin * 60)
        return str(intMin) + "m" + str(secPart) + "s"
