#!/usr/local/bin/python
import os, time, string, signal, sys

globalJobName = ""

def killJobs(signal, stackFrame):
    for job in os.popen("bjobs -w").readlines():
        if job.find(globalJobName) != -1:
            jobId = string.split(job, " ")[0]
            os.system("bkill " + jobId)
    print "Test run terminated due to interrupt"
    sys.exit(2)

signal.signal(1, killJobs)
signal.signal(2, killJobs)
signal.signal(15, killJobs)

class LSFJob:
    def __init__(self, test):
        globalJobName = test.getTmpExtension()
        self.name = globalJobName + repr(test.app) + test.getRelPath()
    def hasStarted(self):
        retstring = self.getFile("-r").readline()
        return string.find(retstring, "not found") == -1
    def hasFinished(self):
        retstring = self.getFile().readline()
        return retstring.find("not found") != -1
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
    
class SubmitTest:
    def __init__(self, queueFunction, resource = ""):
        self.queueFunction = queueFunction
        self.resource = resource
    def __repr__(self):
        return "Submitting"
    def __call__(self, test, description):
        queueToUse = self.queueFunction(test)
        print description + " to LSF queue " + queueToUse
        testCommand = "'" + test.getExecuteCommand() 
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
    def setUpSuite(self, suite, description):
        print description
    
class Wait:
    def __init__(self):
        self.eventName = "completion"
    def __repr__(self):
        return "Waiting for " + self.eventName + " of"
    def __call__(self, test, description):
        job = LSFJob(test)
        if self.checkCondition(job):
            return
        print description + "..."
        while not self.checkCondition(job):
            time.sleep(2)
    def setUpSuite(self, suite, description):
        pass
    def checkCondition(self, job):
        return job.hasFinished()

class MakeResourceFiles:
    def __repr__(self):
        return "Making resource files for"
    def __call__(self, test, description):
        textList = [ "Max Memory", "Max Swap", "CPU time", "executed on host" ]
        tmpFile = test.getTmpFileName("report", "r")
        resourceDict = self.makeResourceDict(tmpFile, textList)
        if len(resourceDict) < len(textList):
            # Race condition with LSF writing the report... wait a bit and try again
            time.sleep(2)
            resourceDict = self.makeResourceDict(tmpFile, textList)
        os.remove(tmpFile)
        self.writePerformanceFile(test, resourceDict[textList[2]], resourceDict[textList[3]], test.getTmpFileName("performance", "w"))
        #self.writeMemoryFile(resourceDict[textList[0]], resourceDict[textList[1]], test.getTmpFileName("memory", "w"))
    def setUpSuite(self, suite, description):
        pass
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


