#!/usr/local/bin/python

import os, time, string, signal, sys, default, unixConfig, performance, respond, batch, plugins, types, predict

# Text only relevant to using the LSF configuration directly
helpDescription = """
The LSF configuration is designed to run on a UNIX system with the LSF (Load Sharing Facility)
product from Platform installed.

It's default operation is to submit all tests to LSF's "normal" queue. For this reason
it is probably not so useful as a standalone configuration, because most people will
want to configure which queue they send jobs to, and hence need a derived configuration.
"""

# Text for use by derived configurations as well
lsfGeneral = """
When all tests have been submitted to LSF, the configuration will then wait for each test in turn,
and provide comparison when each has finished.

Because UNIX is assumed anyway, results are presented using "tkdiff" for the file matching
the "log_file" entry in the config file, and "diff" for everything else. These are more
user friendly but less portable than the default "ndiff".

It also generates performance checking and memory checking by using the LSF report file to
extract this information. The reliability of memory checking is however uncertain, hence
it is currently disabled by default.
"""

batchInfo = """
             Note that it can be useful to send the whole TextTest run to LSF in batch mode, using LSF's termination
             time feature. If this is done, LSF will send TextTest a signal 10 minutes before the termination time,
             which allows TextTest to kill all remaining jobs and report them as unfinished in its report."""

helpOptions = """
-l         - run in local mode. This means that the framework will not use LSF, but will behave as
             if the default configuration was being used, and run on the local machine.

-r <limits>- run tests subject to the time limits (in minutes) represented by <limits>. If this is a single limit
             it will be interpreted as a minimum. If it is two comma-separated values, these are interpreted as
             <minimum>,<maximum>. Empty strings are treated as no limit.

-R <resrc> - Use the LSF resource <resrc>. This is essentially forwarded to LSF's bsub command, so for a full
             list of its capabilities, consult the LSF manual. However, it is particularly useful to use this
             to force a test to go to certain machines, using -R "hname == <hostname>", or to avoid similar machines
             using -R "hname != <hostname>"

-perf      - Force execution on the performance test machines. Equivalent to -R "hname == <perf1> || hname == <perf2>...",
             where <perf1>, <perf2> etc. are the machines listed in the config file list entry "performance_test_machine".
             Does not work in conjunction with -R <resrc>, currently.
""" + batch.helpOptions             

def getConfig(optionMap):
    return LSFConfig(optionMap)

emergencyFinish = 0

def tenMinutesToGo(signal, stackFrame):
    print "Received LSF signal for termination in 10 minutes, killing all remaining jobs"
    global emergencyFinish
    emergencyFinish = 1

signal.signal(signal.SIGUSR2, tenMinutesToGo)

class LSFConfig(unixConfig.UNIXConfig):
    def getOptionString(self):
        return "elr:R:" + unixConfig.UNIXConfig.getOptionString(self)
    def getFilterList(self):
        filters = unixConfig.UNIXConfig.getFilterList(self)
        self.addFilter(filters, "r", performance.TimeFilter)
        return filters
    def useLSF(self):
        if self.optionMap.has_key("reconnect") or self.optionMap.has_key("l"):
            return 0
        return 1
    def getTestRunner(self):
        if not self.useLSF():
            return default.Config.getTestRunner(self)
        else:
            return SubmitTest(self.findLSFQueue, self.findLSFResource)
    # Default queue function, users probably need to override
    def findLSFQueue(self, test):
        return "normal"
    def findLSFResource(self, test):
        resourceList = self.findResourceList(test.app)
        if len(resourceList) == 0:
            return ""
        elif len(resourceList) == 1:
            return resourceList[0]
        else:
            resource = "(" + resourceList[0] + ")"
            for res in resourceList[1:]:
                resource += " && (" + res + ")"
            return resource
    def findResourceList(self, app):
        resourceList = []
        if self.optionMap.has_key("R"):
            resourceList.append(self.optionValue("R"))
        if self.optionMap.has_key("perf"):
            performanceMachines = app.getConfigList("performance_test_machine")
            resource = "hname == " + performanceMachines[0]
            if len(performanceMachines) > 1:
                for machine in performanceMachines[1:]:
                    resource += " || hname == " + machine
            resourceList.append(resource)
        return resourceList
    def getTestCollator(self):
        if not self.useLSF():
            return default.Config.getTestCollator(self)
        else:
            return plugins.CompositeAction([ Wait(), MakeResourceFiles(self.checkPerformance(), self.checkMemory()) ])
    def getTestComparator(self):
        if self.optionMap.has_key("l"):
            return default.Config.getTestComparator(self)
        else:
            return performance.MakeComparisons(self.optionMap.has_key("n"))
    def checkMemory(self):
        return 0
    def checkPerformance(self):
        return 1
    def printHelpDescription(self):
        print helpDescription, lsfGeneral, predict.helpDescription, performance.helpDescription, respond.helpDescription 
    def printHelpOptions(self, builtInOptions):
        print helpOptions + batchInfo
        default.Config.printHelpOptions(self, builtInOptions)

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
    def __init__(self, queueFunction, resourceFunction):
        self.queueFunction = queueFunction
        self.resourceFunction = resourceFunction
    def __repr__(self):
        return "Submitting"
    def __call__(self, test):
        queueToUse = self.queueFunction(test)
        self.describe(test, " to LSF queue " + queueToUse)
        testCommand = self.getExecuteCommand(test)
        reportfile =  test.getTmpFileName("report", "w")
        lsfJob = LSFJob(test)
        lsfOptions = "-J " + lsfJob.name + " -q " + queueToUse + " -o " + reportfile
        resource = self.resourceFunction(test)
        if len(resource):
            lsfOptions += " -R '" + resource + "'"
        unixPerfFile = test.getTmpFileName("unixperf", "w")
        # put the command in a file to avoid quoting problems,
        # also fix env.variables that LSF doesn't reset
        cmdFile = test.getTmpFileName("cmd", "w")
        f = open(cmdFile, "w")
        f.write("HOST=`hostname`; export HOST\n")
        f.write(testCommand + "\n")
        f.close()
        timedTestCommand = '\\time -p sh ' + cmdFile + ' 2> ' + unixPerfFile
        commandLine = "bsub " + lsfOptions + " '" + timedTestCommand + "' > " + reportfile + " 2>&1"
        os.system(commandLine)
    def getExecuteCommand(self, test):
        testCommand = test.getExecuteCommand()
        inputFileName = test.getInputFileName()
        if os.path.isfile(inputFileName):
            testCommand = testCommand + " < " + inputFileName
        outfile = test.getTmpFileName("output", "w")
        errfile = test.getTmpFileName("errors", "w")
        return testCommand + " > " + outfile + " 2> " + errfile
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
        # Read the UNIX performance file, allowing us to discount system time.
        tmpFile = test.getTmpFileName("unixperf", "r")
        file = open(tmpFile)
        for line in file.readlines():
            if line.find("user") != -1:
                cpuTime = line.strip().split()[-1]
                resourceDict["CPU time"] = "CPU time   : " + string.rjust(cpuTime, 9) + " sec."
        os.remove(tmpFile)
	# remove the command-file created before submitting the command
        cmdFile = test.getTmpFileName("cmd", "r")
        os.remove(cmdFile)
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
        file = open(fileName, "w")
        line = string.strip(cpuLine) + " on " + executionMachine + os.linesep
        file.write(line)
        file.close()
    def findExecutionMachine(self, line):
        start = string.find(line, "<")
        end = string.find(line, ">", start)
        fullName = line[start + 1:end]
        return string.split(fullName, ".")[0]
    def writeMemoryFile(self, memLine, swapLine, fileName):
        file = open(fileName, "w")
        file.write(string.lstrip(memLine))
        file.write(string.lstrip(swapLine))
        file.close()


