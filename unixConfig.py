#!/usr/local/bin/python

# Text only relevant to using the LSF configuration directly
helpDescription = """
The UNIX configuration is designed to run on a UNIX system. It therefore makes use of some
UNIX tools, such as tkdiff, diff and /usr/lib/sendmail. The difference tools are used in preference
to Python's ndiff, and sendmail is used to implement an email-sending batch mode (see options)

The default behaviour is to run all tests locally.
"""

import default, batch, respond, comparetest, performance, predict, os, shutil, plugins, string

def getConfig(optionMap):
    return UNIXConfig(optionMap)

class UNIXConfig(default.Config):
    def getArgumentOptions(self):
        options = default.Config.getArgumentOptions(self)
        options["b"] = "Run batch mode with identifier"
        options["r"] = "Select tests by execution time"
        return options
    def getFilterList(self):
        filters = default.Config.getFilterList(self)
        self.addFilter(filters, "b", batch.BatchFilter)
        self.addFilter(filters, "r", performance.TimeFilter)
        return filters
    def getActionSequence(self):
        seq = default.Config.getActionSequence(self)
        if self.batchMode():
            seq.append(batch.MailSender(self.optionValue("b")))
        return seq
    def batchMode(self):
        # If running multiple times, batch mode is assumed
        return self.optionMap.has_key("b") or self.optionMap.has_key("m")
    def keepTmpFiles(self):
        return self.batchMode()
    def getTestCollator(self):
        coreAction = CollateCore("core*", "stacktrace")
        return plugins.CompositeAction([coreAction, default.Config.getTestCollator(self)])
    def getPerformanceFileMaker(self):
        return MakePerformanceFile()
    def getTestComparator(self):
        return performance.MakeComparisons(self.optionMap.has_key("n"))
    def getTestRunner(self):
        return RunTest()
    def getTestResponder(self):
        diffLines = 30
        if self.batchMode():
            return batch.BatchResponder(diffLines)
        elif self.optionMap.has_key("o"):
            return default.Config.getTestResponder(self)
        else:
            return respond.UNIXInteractiveResponder(diffLines)
    def printHelpDescription(self):
        print helpDescription, predict.helpDescription, comparetest.helpDescription, respond.helpDescription
    def printHelpScripts(self):
        print performance.helpScripts
    def printHelpOptions(self, builtInOptions):
        print batch.helpOptions
        default.Config.printHelpOptions(self, builtInOptions)

class RunTest(default.RunTest):
    def runTest(self, test):
        testCommand = self.getExecuteCommand(test)
        os.system(testCommand)
    def getExecuteCommand(self, test):
        testCommand = test.getExecuteCommand()
        inputFileName = test.inputFile
        if os.path.isfile(inputFileName):
            testCommand = testCommand + " < " + inputFileName
        outfile = test.makeFileName("output", temporary=1)
        errfile = test.makeFileName("errors", temporary=1)
        # put the command in a file to avoid quoting problems,
        # also fix env.variables that remote login doesn't reset
        cmdFile = test.makeFileName("cmd", temporary=1, forComparison=0)
        f = open(cmdFile, "w")
        f.write("HOST=`hostname`; export HOST\n")
        f.write(testCommand + " > " + outfile + " 2> " + errfile + "\n")
        f.close()
        unixPerfFile = test.makeFileName("unixperf", temporary=1, forComparison=0)
        timedTestCommand = '\\time -p sh ' + cmdFile + ' 2> ' + unixPerfFile
        return timedTestCommand
    def changeState(self, test):
        test.changeState(test.RUNNING, "Running on " + hostname())

def hostname():
    if os.environ.has_key("HOST"):
        return os.environ["HOST"]
    elif os.environ.has_key("HOSTNAME"):
        return os.environ["HOSTNAME"]
    else:
        raise plugins.TextTestError, "No hostname could be found for local machine!!!"

def isCompressed(path):
    if os.path.getsize(path) == 0:
        return 0
    magic = open(path).read(2)
    if magic[0] == chr(0x1f) and magic[1] == chr(0x9d):
        return 1
    else:
        return 0

# Deal with UNIX-compressed files as well as straight text
class CollateFile(default.CollateFile):
    def transformToText(self, path):
        if not isCompressed(path):
            return        
        toUse = path + ".Z"
        os.rename(path, toUse)
        os.system("uncompress " + toUse)

# Extract just the stack trace rather than the whole core
class CollateCore(CollateFile):
    def transformToText(self, path):
        CollateFile.transformToText(self, path)
        if os.path.getsize(path) == 0:
            os.remove(path)
            file = open(path, "w")
            file.write("Core file of zero size written - no stack trace for crash\nCheck your coredumpsize limit" + os.linesep)
            file.close()
            return
        fileName = "coreCommands.gdb"
        file = open(fileName, "w")
        file.write("bt\nq\n")
        file.close()
        # Yes, we know this is horrible. Does anyone know a better way of getting the binary out of a core file???
        # Unfortunately running gdb is not the answer, because it truncates the data...
        binary = os.popen("csh -c 'echo `tail -c 1024 " + path + "`' 2> /dev/null").read().split(" ")[-1].strip()
        newPath = path + "tmp" 
        writeFile = open(newPath, "w")
        if os.path.isfile(binary):
            gdbData = os.popen("gdb -q -x " + fileName + " " + binary + " " + path)
            # reckoned necessary on UNIX
            os.wait()
            prevLine = ""
            for line in gdbData.xreadlines():
                if line.find("Program terminated") != -1:
                    writeFile.write(line)
                    writeFile.write("Stack trace from gdb :" + os.linesep)
                if line[0] == "#" and line != prevLine:
                    startPos = line.find("in ") + 3
                    endPos = line.rfind("(")
                    writeFile.write(line[startPos:endPos] + os.linesep)
                prevLine = line
        else:
            writeFile.write("Could not find binary name from core file - no stack trace for crash" + os.linesep)
        os.remove(path)
        os.remove(fileName)
        os.rename(newPath, path)
    def extract(self, sourcePath, targetFile):
        try:
            os.rename(sourcePath, targetFile)
        except:
            print "Failed to rename '" + sourcePath + "' to '" + targetFile + "', using copy-delete"
            shutil.copyfile(sourcePath, targetFile)
            os.remove(sourcePath)

class MakePerformanceFile(plugins.Action):
    def __repr__(self):
        return "Making performance file for"
    def __call__(self, test):
        if test.state == test.UNRUNNABLE:
            return

        cpuTime, realTime = self.readTimes(test)
        # remove the command-file created before submitting the command
        # Note not everybody creates one!
        cmdFile = test.makeFileName("cmd", temporary=1, forComparison=0)
        if os.path.isfile(cmdFile):
            os.remove(cmdFile)

        executionMachines = self.findExecutionMachines(test)
        # There was still an error (jobs killed in emergency), so don't write performance files
        if cpuTime == None:
            print "Not writing performance file for", test
            return
        fileToWrite = test.makeFileName("performance", temporary=1)
        self.writeFile(test, cpuTime, realTime, executionMachines, fileToWrite)
    def findExecutionMachines(self, test):
        return [ hostname() ] 
    def readTimes(self, test):
        # Read the UNIX performance file, allowing us to discount system time.
        tmpFile = test.makeFileName("unixperf", temporary=1, forComparison=0)
        if not os.path.isfile(tmpFile):
            return None, None
            
        file = open(tmpFile)
        cpuTime = None
        realTime = None
        for line in file.readlines():
            if line.find("user") != -1:
                cpuTime = self.parseUnixTime(line.strip().split()[-1])
            if line.find("real") != -1:
                realTime = self.parseUnixTime(line.strip().split()[-1])
        os.remove(tmpFile)
        return cpuTime, realTime
    def parseUnixTime(self, timeVal):
        if timeVal.find(":") == -1:
            return timeVal.rjust(9)

        parts = timeVal.split(":")
        floatVal = 60 * float(parts[0]) + float(parts[1])
        return str(floatVal).rjust(9)
    def writeFile(self, test, cpuTime, realTime, executionMachines, fileName):
        file = open(fileName, "w")
        cpuLine = "CPU time   : " + cpuTime + " sec. on " + string.join(executionMachines, ",") + os.linesep
        file.write(cpuLine)
        realLine = "Real time  : " + realTime + " sec."
        file.write(realLine)
        self.writeMachineInformation(file, executionMachines)
    def writeMachineInformation(self, file, executionMachines):
        # A space for subclasses to write whatever they think is relevant about
        # the machine environment right now.
        pass
    
