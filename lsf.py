#!/usr/local/bin/python

helpDescription = """
The LSF configuration, with no modifications, will submit all tests to LSF's "normal" queue.
It will then wait for each test in turn, and provide comparison when each has finished.

sending standard output to output.<app> and standard error to errors.<app>. These files
will then be filtered using the list entries "output" and "error" from the config file,
to remove run-dependent text.

Failure is reported on any differences with the standard versions of those files, and displayed
using Python's ndiff module. A simple interactive dialogue is then produced, allowing the changes
to be saved as new standard results.

The default configuration is intended to be usable on any platform.
"""

helpOptions = """
-l         - run in local mode. This means that the framework will not use LSF, but will behave as
             if the default configuration was being used, and run on the local machine.

-r <mins>  - run only tests which are expected to complete in less than <mins> minutes.

-b <bname> - run in batch mode, using batch session name <bname>. This will replace the interactive
             dialogue with an email report, which is sent to $USER if the session name <bname> is
             not recognised by the config file.

             There is also a possibility to define batch sessions in the config file. The following
             entries are understood:
             <bname>_timelimit,  if present, will run only tests up to that limit
             <bname>_recipients, if present, ensures that mail is sent to those addresses instead of $USER.
             If set to "none", it ensures that that batch session will ignore that application.
             <bname>_version, these entries form a list and ensure that only the versions listed are accepted.
             If the list is empty, all versions are allowed.

-R <resrc> - Use the LSF resource <resrc>. This is essentially forwarded to LSF's bsub command, so for a full
             list of its capabilities, consult the LSF manual. However, it is particularly useful to use this
             to force a test to go to certain machines, using -R "hname == hostname", or to avoid similar machines
             using -R "hname != hostname"
"""

import os, time, string, signal, sys, default, performance, respond, batch, plugins, types

def getConfig(optionMap):
    return LSFConfig(optionMap)

emergencyFinish = 0

def tenMinutesToGo(signal, stackFrame):
    print "Received LSF signal for termination in 10 minutes, killing all remaining jobs"
    global emergencyFinish
    emergencyFinish = 1

signal.signal(signal.SIGUSR2, tenMinutesToGo)

class LSFConfig(default.Config):
    def getOptionString(self):
        return "lb:r:R:" + default.Config.getOptionString(self)
    def getFilterList(self):
        filters = default.Config.getFilterList(self)
        self.addFilter(filters, "r", performance.TimeFilter)
        self.addFilter(filters, "b", self.batchFilterClass())
        return filters
    def batchFilterClass(self):
        return batch.BatchFilter
    def getTestRunner(self):
        if self.optionMap.has_key("l"):
            return default.Config.getTestRunner(self)
        else:
            return SubmitTest(self.findLSFQueue, self.optionValue("R"))
    # Default queue function, users probably need to override
    def findLSFQueue(self, test):
        return "normal"
    def getTestCollator(self):
        if self.optionMap.has_key("l"):
            return default.Config.getTestCollator(self)
        else:
            return plugins.CompositeAction([ Wait(), MakeResourceFiles(self.checkPerformance(), self.checkMemory()) ])
    def getTestComparator(self):
        if self.optionMap.has_key("l"):
            return default.Config.getTestComparator(self)
        else:
            return performance.MakeComparisons()
    def getTestResponder(self):
        diffLines = 30
        # If running multiple times, batch mode is assumed
        if self.optionMap.has_key("b") or self.optionMap.has_key("m"):
            return batch.BatchResponder(diffLines, self.optionValue("b"))
        elif self.optionMap.has_key("o"):
            return default.Config.getTestResponder(self)
        else:
            return respond.UNIXInteractiveResponder(diffLines)
    def checkMemory(self):
        return 0
    def checkPerformance(self):
        return 1
    def printHelpDescription(self):
        print default.helpDescription
    def printHelpOptions(self, builtInOptions):
        print helpOptions, default.helpOptions, builtInOptions

class LSFJob:
    def __init__(self, test):
        self.name = test.getTmpExtension() + repr(test.app) + test.getRelPath()
    def hasStarted(self):
        retstring = self.getFile("-r").readline()
        return string.find(retstring, "not found") == -1
    def hasFinished(self):
        retstring = self.getFile().readline()
        return retstring.find("not found") != -1
    def kill(self):
        os.system("bkill -J " + self.name + " > /dev/null 2>&1")
    def getExecutionMachine(self):
        file = self.getFile("-w")
        lastline = file.readlines()[-1]
        fullName = self.getPreviousWord(lastline, self.name)
        return fullName.split('.')[0]
    def getProcessIds(self):
        for line in self.getFile("-l").xreadlines():
            pos = line.find("PIDs")
            if pos != -1:
                return line[pos + 6:].strip().split(' ')
        return []
    def getFile(self, options = ""):
        return os.popen("bjobs -J " + self.name + " " + options + " 2>&1")
    def getPreviousWord(self, line, field):
        prevWord = ""
        for word in line.split(' '):
            if word == field:
                return prevWord
            prevWord = word
        return ""
    
class SubmitTest(plugins.Action):
    def __init__(self, queueFunction, resource = ""):
        self.queueFunction = queueFunction
        self.resource = resource
    def __repr__(self):
        return "Submitting"
    def __call__(self, test):
        queueToUse = self.queueFunction(test)
        self.describe(test, " to LSF queue " + queueToUse)
        testCommand = "'" + self.getExecuteCommand(test) 
        if os.path.isfile(test.inputFile):
            testCommand = testCommand + " < " + test.inputFile
        outfile = test.getTmpFileName("output", "w")
        testCommand = testCommand + " > " + outfile + "'"
        errfile = test.getTmpFileName("errors", "w")
        reportfile =  test.getTmpFileName("report", "w")
        lsfJob = LSFJob(test)
        lsfOptions = "-J " + lsfJob.name + " -q " + queueToUse + " -o " + reportfile + " -e " + errfile
        if len(self.resource):
            lsfOptions += " -R '" + self.resource + "'"
        commandLine = "bsub " + lsfOptions + " " + testCommand + " > " + reportfile + " 2>&1"
        os.system(commandLine)
    def getExecuteCommand(self, test):
        return test.getExecuteCommand()
    def setUpSuite(self, suite):
        self.describe(suite)
    def getCleanUpAction(self):
        return KillTest()

class KillTest(plugins.Action):
    def __repr__(self):
        return "Cancelling"
    def __call__(self, test):
        job = LSFJob(test)
        if job.hasFinished():
            return
        self.describe(test, " in LSF")
        job.kill()
    def setUpSuite(self, suite):
        self.describe(suite)
        
class Wait(plugins.Action):
    def __init__(self):
        self.eventName = "completion"
    def __repr__(self):
        return "Waiting for " + self.eventName + " of"
    def __call__(self, test):
        job = LSFJob(test)
        if self.checkCondition(job):
            return
        self.describe(test, "...")
        while not self.checkCondition(job):
            global emergencyFinish
            if emergencyFinish:
                print "Emergency finish: killing job!"
                job.kill()
                # This will only happen in batch mode: tell batch to treat the job as unfinished
                batch.killedTests.append(test)
                return
            time.sleep(2)
    def checkCondition(self, job):
        return job.hasFinished()

class MakeResourceFiles(plugins.Action):
    def __init__(self, checkPerformance, checkMemory):
        self.checkPerformance = checkPerformance
        self.checkMemory = checkMemory
    def __call__(self, test):
        textList = [ "Max Memory", "Max Swap", "CPU time", "executed on host" ]
        tmpFile = test.getTmpFileName("report", "r")
        resourceDict = self.makeResourceDict(tmpFile, textList)
        if len(resourceDict) < len(textList):
            # Race condition with LSF writing the report... wait a bit and try again
            time.sleep(2)
            resourceDict = self.makeResourceDict(tmpFile, textList)
        os.remove(tmpFile)
        # There was still an error (jobs killed in emergency), so don't write resource files
        if len(resourceDict) < len(textList):
            return
        if self.checkPerformance:
            self.writePerformanceFile(test, resourceDict[textList[2]], resourceDict[textList[3]], test.getTmpFileName("performance", "w"))
        if self.checkMemory:
            self.writeMemoryFile(resourceDict[textList[0]], resourceDict[textList[1]], test.getTmpFileName("memory", "w"))
#private
    def makeResourceDict(self, tmpFile, textList):
        resourceDict = {}
        file = open(tmpFile)
        for line in file.readlines():
            for text in textList:
                if string.find(line, text) != -1:
                    resourceDict[text] = line
        return resourceDict
    def writePerformanceFile(self, test, cpuLine, executionLine, fileName):
        executionMachine = self.findExecutionMachine(executionLine)
        if executionMachine in test.app.getConfigList("performance_test_machine"):
            file = open(fileName, "w")
            file.write(string.strip(cpuLine) + " on " + executionMachine + "\n")
            file.close()
    def findExecutionMachine(self, line):
        start = string.find(line, "<")
        end = string.find(line, ">", start)
        fullName = line[start + 1:end - 1]
        return string.split(fullName, ".")[0]
    def writeMemoryFile(self, memLine, swapLine, fileName):
        file = open(fileName, "w")
        file.write(string.lstrip(memLine))
        file.write(string.lstrip(swapLine))
        file.close()


