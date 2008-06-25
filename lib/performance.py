
import os, string, plugins, sys
from comparefile import FileComparison

# This module won't work without an external module creating a file called performance.app
# This file should be of a format understood by the function below i.e. a single line containing
# CPU time   :      30.31 sec. on heathlands
# 

# For memory the same is true, and the format is
# Max Memory :       45 MB

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
    try:
        return getPerformance(test.getFileName("performance", version))
    except IOError: # assume something disappeared externally
        test.refreshFiles()
        return getTestPerformance(test, version)

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
    else:
        raise plugins.TextTestError, "Could not parse time expression '" + timeExpression + "' : all expressions must begin with '<' or '>'." 

class PerformanceConfigSettings:
    def __init__(self, test, stem):
        self.configName = self.getConfigName(stem)
        self.configMethod = test.getCompositeConfigValue
        self.processCount = max(len(test.state.executionHosts), 1)
        
    def getConfigName(self, stem):
        if stem == "performance":
            return "cputime"
        else:
            return stem
        
    def aboveMinimum(self, value, configEntry):
        minimum = self.processCount * self.configMethod(configEntry, self.configName)
        return value < 0 or value > minimum

    def getDescriptor(self, configEntry):
        desc = self._getDescriptor(configEntry, self.configName)
        if desc:
            return desc
        else:
            fallbackConfigName = self.getFallbackConfigName()
            postfix = "(" + self.configName + ")"
            return self._getDescriptor(configEntry, fallbackConfigName) + postfix

    def getFallbackConfigName(self):
        if self.configName.find("mem") != -1:
            return "memory"
        else:
            return "cputime"
        
    def _getDescriptor(self, configEntry, configName):
        fromConfig = self.configMethod(configEntry, configName)
        if len(fromConfig) > 0:
            name, briefDesc, longDesc = plugins.commasplit(fromConfig)
            plugins.addCategory(name, briefDesc, longDesc)
            return name
        

class PerformanceFileComparison(FileComparison):
    def cacheDifferences(self, test, testInProgress):
        # Don't allow process count of 0, which screws things up...
        self.perfComparison = None
        if self.stdFile and self.tmpFile:
            oldPerf = getPerformance(self.stdFile)
            # If we didn't understand the old performance, overwrite it and behave like it didn't exist
            if (oldPerf < 0):
                os.remove(self.stdFile)
            else:
                newPerf = getPerformance(self.tmpFile)
                self.diag.info("Performance is " + str(oldPerf) + " and " + str(newPerf))
                settings = PerformanceConfigSettings(test, self.stem)
                self.perfComparison = PerformanceComparison(oldPerf, newPerf, settings)
                self.differenceCache = self.perfComparison.isSignificant(settings)
    
    def __repr__(self):
        baseText = FileComparison.__repr__(self)
        if self.newResult():
            return baseText
        return baseText + "(" + self.getType() + ")"
    def getType(self):
        if self.newResult():
            return FileComparison.getType(self)
        else:
            return self.perfComparison.descriptor
    def getDifferencesSummary(self, includeNumbers=True):
        return self.perfComparison.getSummary(includeNumbers)
    def getDetails(self):
        if self.hasDifferences():
            return self.getDifferencesSummary()
        else:
            return ""
    def saveResults(self, destFile):
        # Here we save the average of the old and new performance, assuming fluctuation
        avgPerformance = self.perfComparison.getAverage()
        line = open(self.tmpFile).readlines()[0]
        lineToWrite = line.replace(str(self.perfComparison.newPerformance), str(avgPerformance))
        newFile = open(destFile, "w")
        newFile.write(lineToWrite)

# class purely for comparing two performance numbers, independent of the files they come from
class PerformanceComparison:
    def __init__(self, oldPerf, newPerf, settings):
        self.oldPerformance = oldPerf
        self.newPerformance = newPerf
        self.percentageChange = self.calculatePercentageIncrease()
        self.descriptor = self.getDescriptor(settings)
    def calculatePercentageIncrease(self):        
        largest = max(self.oldPerformance, self.newPerformance)
        smallest = min(self.oldPerformance, self.newPerformance)
        if smallest == 0.0:
            if largest == 0.0:
                return 0
            else:
                return -1
        return ((largest - smallest) / smallest) * 100
    def getDescriptor(self, settings):
        if self.newPerformance < self.oldPerformance:
            return settings.getDescriptor("performance_descriptor_decrease")
        else:
            return settings.getDescriptor("performance_descriptor_increase")
    def getSummary(self, includeNumbers=True):
        if self.newPerformance < 0:
            return "Performance comparison failed"

        perc = self.getRoundedPercentage()
        if perc == 0:
            return ""
        elif perc == -1:
            return "infinitely " + self.descriptor
        elif includeNumbers:
            return str(perc) + "% " + self.descriptor
        else:
            return self.descriptor
    def getRoundedPercentage(self):
        perc = int(self.percentageChange)
        if perc == 0:
            return float("%.0e" % self.percentageChange) # Print one significant figure
        else:
            return perc
    def isSignificant(self, settings):
        longEnough = settings.aboveMinimum(self.newPerformance, "performance_test_minimum") or \
                     settings.aboveMinimum(self.oldPerformance, "performance_test_minimum")
        varianceEnough = settings.aboveMinimum(self.percentageChange, "performance_variation_%")
        return longEnough and varianceEnough
    def getAverage(self):
        return round((self.oldPerformance + self.newPerformance) / 2.0, 2)

class TimeFilter(plugins.Filter):
    option = "r"
    def __init__(self, timeLimit, *args):
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
        
class PerformanceStatistics(plugins.Action):
    scriptDoc = "Prints a report on system resource usage per test. Can compare versions"
    printedTitle = False
    def __init__(self, args = []):
        self.compareVersion = None
        self.compareTotal = 0.0
        self.total = 0.0
        self.testCount = 0
        self.app = None
        self.file = "performance"
        self.interpretOptions(args)
    def interpretOptions(self, args):
        for ar in args:
            arr = ar.split("=")
            if arr[0]=="compv":
                self.compareVersion = arr[1]
            elif arr[0]=="file":
                self.file = arr[1]
            else:
                print "Unknown option " + arr[0]
    def setUpSuite(self, suite):
        if suite.parent:
            print suite.getIndent() + suite.name
        else:
            entries = [ suite.app.description(), "Version '" + self.app.getFullVersion() + "'" ]
            if self.compareVersion is not None:
                entries += [ "Version '" + self.compareVersion + "'", self.file + " change" ]
            self.printUnderlined(self.getPaddedLine(entries))
    def printUnderlined(self, title):
        print "-" * len(title)
        print title
        print "-" * len(title)
    def getPaddedLine(self, entries):
        line = entries[0].ljust(40)
        for entry in entries[1:]:
            line += entry.rjust(20)
        return line
    def __call__(self, test):
        self.testCount += 1
        perf = getPerformance(test.getFileName(self.file))
        self.total += perf
        entries = [ test.getIndent() + test.name, self.format(perf) ]
        if self.compareVersion is not None:
            comparePerf = getPerformance(test.getFileName(self.file, self.compareVersion))
            self.compareTotal += comparePerf
            self.settings = PerformanceConfigSettings(test, self.file)
            perfComp = PerformanceComparison(comparePerf, perf, self.settings)
            entries += [ self.format(comparePerf), perfComp.getSummary() ]
        print self.getPaddedLine(entries)
    def format(self, number):
        if self.file.find("mem") != -1:
            return self.formatMemory(number)
        else:
            from datetime import timedelta
            return str(timedelta(seconds=int(number)))
    def formatMemory(self, memUsed):
        return str(memUsed) + " MB"
    def __del__(self):
        if not self.printedTitle:
            entries = [ "Application/Version", "Total" ]
            if self.compareVersion is not None:
                entries += [ "Total (" + self.compareVersion + ")", self.file + " change" ]
            entries.append("No. of Tests")
            self.printUnderlined(self.getPaddedLine(entries))
            PerformanceStatistics.printedTitle = True
        # Note - we might need to include parallel in this calculation...
        entries = [ self.app.description(), self.format(self.total) ]
        if self.compareVersion is not None:
            perfComp = PerformanceComparison(self.compareTotal, self.total, self.settings)
            entries += [ self.format(self.compareTotal), perfComp.getSummary() ]
        entries.append(str(self.testCount))
        print self.getPaddedLine(entries)
    def setUpApplication(self, app):
        self.app = app
