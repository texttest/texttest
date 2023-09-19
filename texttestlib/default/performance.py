
import os
import sys
import time
from texttestlib import plugins
from .comparefile import FileComparison

from functools import cmp_to_key

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
    return getPerformanceFromLine(line)


def getPerformanceFromLine(line):
    pos = line.find(":")
    if pos == -1:
        return float(-1)
    return float(line[pos + 1:].lstrip().split()[0])


def getTestPerformance(test, version=None):
    try:
        perfStem = test.getConfigValue("default_performance_stem")
        return getPerformance(test.getFileName(perfStem, version))
    except IOError:  # assume something disappeared externally
        test.refreshFiles()
        return getTestPerformance(test, version)


def describePerformance(fileName):
    line = open(fileName).readline().strip()
    if "mem" in os.path.basename(fileName):
        return line

    # Assume seconds
    perf = getPerformanceFromLine(line)
    description = getTimeDescription(perf)
    return line.replace(str(perf) + " sec.", description)


def getTimeDescription(seconds):
    values = list(time.gmtime(seconds)[2:6])
    values[0] -= 1  # not actually using timedelta which doesn't support formatting...
    units = ["day", "hour", "minute", "second"]
    parts = []
    for unit, val in zip(units, values):
        if val:
            parts.append(plugins.pluralise(val, unit))

    if len(parts) > 0:
        description = " and ".join(parts).replace(" and ", ", ", len(parts) - 2)
    else:
        description = "Less than 1 second"
    return description


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
        raise plugins.TextTestError("Could not parse time expression '" + timeExpression + 
                                    "' : all expressions must begin with '<' or '>'.")


class PerformanceConfigSettings:
    def __init__(self, test, stem):
        self.configName = self.getConfigName(stem)
        self.configMethod = test.getCompositeConfigValue

    def getConfigName(self, stem):
        if stem == "performance":
            return "cputime"
        else:
            return stem

    def flagSet(self, configEntry):
        return self.configMethod(configEntry, self.configName) == "true"

    def aboveMinimum(self, value, configEntry):
        minimum = self.configMethod(configEntry, self.configName)
        return value < 0 or value > minimum

    def getMinimumMultipleRange(self, value, configEntry):
        minimum = self.configMethod(configEntry, self.configName)
        if minimum == 0:
            return None, None
        multiple = int(value / minimum)
        return int(multiple * minimum), int((multiple + 1) * minimum)

    def getDescriptor(self, configEntry):
        desc = self._getDescriptor(configEntry, self.configName)
        if desc:
            return desc
        else:
            fallbackConfigName = self.getFallbackConfigName()
            postfix = "(" + self.configName + ")"
            return self._getDescriptor(configEntry, fallbackConfigName) + postfix

    def getFallbackConfigName(self):
        if "mem" in self.configName:
            return "memory"
        else:
            return "cputime"

    def ignoreImprovements(self):
        return self.configMethod("performance_ignore_improvements", self.configName) == "true"

    def _getDescriptor(self, configEntry, configName):
        fromConfig = self.configMethod(configEntry, configName)
        if len(fromConfig) > 0:
            name, briefDesc, longDesc = plugins.commasplit(fromConfig)
            plugins.addCategory(name, briefDesc, longDesc)
            return name


class PerformanceFileComparison(FileComparison):
    def __init__(self, *args, **kw):
        self.perfComparison = None
        FileComparison.__init__(self, *args, **kw)

    def cacheDifferences(self, test, testInProgress):
        # Don't allow process count of 0, which screws things up...
        if self.stdFile and self.tmpFile:
            oldPerf = getPerformance(self.stdFile)
            # If we didn't understand the old performance, overwrite it and behave like it didn't exist
            if (oldPerf == float(-1)):
                os.remove(self.stdFile)
                test.refreshFiles()
                self.stdFile = test.getFileName(self.stem)
                self.stdCmpFile = self.stdFile
                if not self.stdFile:
                    return

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

    def getToleranceMultipleRange(self, test):
        settings = PerformanceConfigSettings(test, self.stem)
        return self.perfComparison.getToleranceMultipleRange(settings)

    def getDetails(self):
        if self.hasDifferences():
            return self.getDifferencesSummary()
        else:
            return ""

    def getNewPerformance(self):
        if self.perfComparison:
            return self.perfComparison.newPerformance
        else:
            return getPerformanceFromLine(self.freeTextBody.splitlines()[0])

    def saveResults(self, tmpFile, destFile):
        # Here we save the average of the old and new performance, assuming fluctuation
        avgPerformance = self.perfComparison.getAverage()
        self.diag.info("Found average performance = " + str(avgPerformance) + 
                       ", new performance = " + str(self.perfComparison.newPerformance))
        line = open(tmpFile).readlines()[0]
        lineToWrite = line.replace(str(self.perfComparison.newPerformance), str(avgPerformance))
        newFile = open(destFile, "w")
        newFile.write(lineToWrite)

# class purely for comparing two performance numbers, independent of the files they come from


class PerformanceComparison:
    def __init__(self, oldPerf, newPerf, settings):
        self.oldPerformance = oldPerf
        self.newPerformance = newPerf
        self.percentageChange = self.calculatePercentageChange(settings)
        self.descriptor = self.getDescriptor(settings)

    def calculatePercentageChange(self, settings):
        if settings.flagSet("use_normalised_percentage_change"):
            return plugins.calculatePercentageNormalised(self.oldPerformance, self.newPerformance)
        else:
            return plugins.calculatePercentageStandard(self.oldPerformance, self.newPerformance)

    def getDescriptor(self, settings):
        if self.newPerformance < self.oldPerformance:
            return settings.getDescriptor("performance_descriptor_decrease")
        else:
            return settings.getDescriptor("performance_descriptor_increase")

    def getSummary(self, includeNumbers=True):
        if self.newPerformance < 0 or self.oldPerformance < 0:
            return "Performance comparison failed"

        perc = plugins.roundPercentage(self.percentageChange)
        if perc == 0:
            return ""
        elif perc == -1:
            return "infinitely " + self.descriptor
        elif includeNumbers:
            return str(perc) + "% " + self.descriptor
        else:
            return self.descriptor

    def getToleranceMultipleRange(self, settings):
        perc = plugins.roundPercentage(self.percentageChange)
        if perc <= 0:
            return ""
        lower, upper = settings.getMinimumMultipleRange(perc, "performance_variation_%")
        if lower is not None:
            return str(lower) + "%-" + str(upper) + "%"
        else:
            return ""

    def isSignificant(self, settings):
        if settings.ignoreImprovements() and self.newPerformance < self.oldPerformance:
            return False

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
        self.maxTime = sys.maxsize
        times = plugins.commasplit(timeLimit)
        if timeLimit.count("<") == 0 and timeLimit.count(">") == 0:  # Backwards compatible
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
                    self.adjustMaxTime(parsedExpression[1] - 1)  # We don't care about fractions of seconds ...
                elif parsedExpression[0] == "<=":
                    self.adjustMaxTime(parsedExpression[1])
                elif parsedExpression[0] == ">":
                    self.adjustMinTime(parsedExpression[1] + 1)  # We don't care about fractions of seconds ...
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
            return True
        return testPerformance >= self.minTime and testPerformance <= self.maxTime


class TimeGroupFilter(plugins.Filter):
    def __init__(self, testCount, *args):
        self.testCount = testCount

    def makePerformanceDictionary(self, tests):
        return {test: getTestPerformance(test) for test in tests}

    def refine(self, tests):
        if self.testCount <= 0 or self.testCount >= len(tests):
            return tests
        testPerfDict = self.makePerformanceDictionary(tests)
        sortedTestPerfDict = sorted(testPerfDict, key=cmp_to_key(lambda test1, test2: self.comparePerformance(testPerfDict[test1], testPerfDict[test2])))
        return sortedTestPerfDict[:self.testCount]
    
    def comparePerformance(self, perf1, perf2):
        return 0


class FastestFilter(TimeGroupFilter):
    option = "fastest"

    def comparePerformance(self, perf1, perf2):
        return perf1 - perf2


class SlowestFilter(TimeGroupFilter):
    option = "slowest"

    def comparePerformance(self, perf1, perf2):
        return perf2 - perf1


class PerformanceStatistics(plugins.ScriptWithArgs):
    scriptDoc = "Prints a report on system resource usage per test. Can compare versions"
    printedTitle = False

    def __init__(self, args=[]):
        optDict = self.parseArguments(args, ["compv", "file"])
        self.settings = None
        self.compareVersion = optDict.get("compv")
        self.compareTotal = 0.0
        self.total = 0.0
        self.testCount = 0
        self.app = None
        self.file = optDict.get("file", "performance")

    def setUpSuite(self, suite):
        if suite.parent:
            print(suite.getIndent() + suite.name)
        else:
            entries = [suite.app.description(), "Version '" + self.app.getFullVersion() + "'"]
            if self.compareVersion is not None:
                entries += ["Version '" + self.compareVersion + "'", self.file + " change"]
            self.printUnderlined(self.getPaddedLine(entries))

    def printUnderlined(self, title):
        print("-" * len(title))
        print(title)
        print("-" * len(title))

    def getPaddedLine(self, entries):
        line = entries[0].ljust(40)
        for entry in entries[1:]:
            line += entry.rjust(20)
        return line

    def __call__(self, test):
        self.testCount += 1
        perf = getPerformance(test.getFileName(self.file))
        if perf > 0:
            self.total += perf
        entries = [test.getIndent() + test.name, self.format(perf)]
        if self.compareVersion is not None:
            comparePerf = getPerformance(test.getFileName(self.file, self.compareVersion))
            self.compareTotal += comparePerf
            self.settings = PerformanceConfigSettings(test, self.file)
            perfComp = PerformanceComparison(comparePerf, perf, self.settings)
            entries += [self.format(comparePerf), perfComp.getSummary()]
        print(self.getPaddedLine(entries))

    def format(self, number):
        if number < 0:
            return "N/A"
        if "mem" in self.file:
            return self.formatMemory(number)
        else:
            from datetime import timedelta
            return str(timedelta(seconds=int(number)))

    def formatMemory(self, memUsed):
        return str(memUsed) + " MB"

    def __del__(self):
        if not self.printedTitle:
            entries = ["Application/Version", "Total"]
            if self.compareVersion is not None:
                entries += ["Total (" + self.compareVersion + ")", self.file + " change"]
            entries.append("No. of Tests")
            self.printUnderlined(self.getPaddedLine(entries))
            PerformanceStatistics.printedTitle = True
        # Note - we might need to include parallel in this calculation...
        entries = [self.app.description(), self.format(self.total)]
        if self.compareVersion is not None:
            perfComp = PerformanceComparison(self.compareTotal, self.total, self.settings)
            entries += [self.format(self.compareTotal), perfComp.getSummary()]
        entries.append(str(self.testCount))
        print(self.getPaddedLine(entries))

    def setUpApplication(self, app):
        self.app = app
