#!/usr/local/bin/python
import os, time, string, signal, sys

globalJobName = os.environ["USER"] + time.strftime("%H:%M:%S", time.localtime())
def findJobName(test):
    return globalJobName + repr(test.app) + test.getRelPath()

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
        lsfOptions = "-J " + findJobName(test) + " -q " + queueToUse + " -o " + reportfile + " -e " + errfile
        if len(self.resource):
            lsfOptions += " -R '" + self.resource + "'"
        commandLine = "bsub " + lsfOptions + " " + testCommand + " > " + reportfile + " 2>&1"
        os.system(commandLine)
    def setUpSuite(self, suite, description):
        print description
    
class Wait:
    def __repr__(self):
        return "Waiting for completion of"
    def __call__(self, test, description):
        if self.hasFinished(test):
            return
        print description + "..."
        while not self.hasFinished(test):
            time.sleep(2)
    def setUpSuite(self, suite, description):
        pass
#private:
    def hasFinished(self, test):
        retstring = os.popen("bjobs -J " + findJobName(test) + " 2>&1").readline()
        return string.find(retstring, "not found") != -1

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


