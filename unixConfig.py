#!/usr/local/bin/python

# Text only relevant to using the LSF configuration directly
helpDescription = """
The UNIX configuration is designed to run on a UNIX system. It therefore makes use of some
UNIX tools, such as tkdiff, diff and /usr/lib/sendmail. The difference tools are used in preference
to Python's ndiff, and sendmail is used to implement an email-sending batch mode (see options)

The default behaviour is to run all tests locally.
"""

import default, batch, respond, performance, predict, os, shutil, plugins, string, time

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
    def _getActionSequence(self, makeDirs=1):
        seq = default.Config._getActionSequence(self, makeDirs)
        if self.batchMode():
            seq.append(batch.MailSender(self.optionValue("b")))
        return seq
    def batchMode(self):
        # If running multiple times, batch mode is assumed
        return self.optionMap.has_key("b") or self.optionMap.has_key("m")
    def keepTmpFiles(self):
        return self.batchMode()
    def getTestCollator(self):
        return CollateUNIXFiles()
    def getPerformanceFileMaker(self):
        return MakePerformanceFile()
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
        print helpDescription, predict.helpDescription, performance.helpDescription, respond.helpDescription
    def printHelpScripts(self):
        print performance.helpScripts
        default.Config.printHelpScripts(self)
    def printHelpOptions(self, builtInOptions):
        print batch.helpOptions
        default.Config.printHelpOptions(self, builtInOptions)

class RunTest(default.RunTest):
    def __init__(self):
        self.interactive = 0
        self.process = None
        self.collectStdErr = 1
    def runTest(self, test):
        if self.process:
            # See if the running process is finished
            if self.process.hasTerminated():
                self.process = None
                return
            else:
                return "retry"

        testCommand = self.getExecuteCommand(test)
        self.describe(test)
        if self.interactive:
            self.process = plugins.BackgroundProcess(testCommand, testRun=1)
            return "retry"
        else:
            os.system(testCommand)
    def getExecuteCommand(self, test):
        testCommand = default.RunTest.getExecuteCommand(self, test)
        if self.collectStdErr:
            errfile = test.makeFileName("errors", temporary=1)
            testCommand += " 2> " + errfile
        # put the command in a file to avoid quoting problems,
        # also fix env.variables that remote login doesn't reset
        cmdFile = test.makeFileName("cmd", temporary=1, forComparison=0)
        f = open(cmdFile, "w")
        f.write("HOST=`hostname`; export HOST" + os.linesep)
        f.write(testCommand + os.linesep)
        f.close()
        unixPerfFile = test.makeFileName("unixperf", temporary=1, forComparison=0)
        timedTestCommand = '\\time -p sh ' + cmdFile + ' 2> ' + unixPerfFile
        return timedTestCommand
    def changeState(self, test):
        test.changeState(test.RUNNING, "Running on " + hostname())
    def getInstructions(self, test):
        self.interactive = 1
        return plugins.Action.getInstructions(self, test)
    def getCleanUpAction(self):
        if self.process:
            print "Killing running test (process id", str(self.process.processId) + ")"
            self.process.kill()
    def setUpApplication(self, app):
        app.setConfigDefault("collect_standard_error", 1)
        self.collectStdErr = int(app.getConfigValue("collect_standard_error"))
   
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
class CollateUNIXFiles(default.CollateFiles):
    def __init__(self):
        default.CollateFiles.__init__(self)
        self.collations.append(("core*", "stacktrace"))
    def transformToText(self, path):
        if isCompressed(path):
            toUse = path + ".Z"
            os.rename(path, toUse)
            os.system("uncompress " + toUse)
        if self.isCoreFile(path):
            # Extract just the stack trace rather than the whole core
            self.interpretCoreFile(path)
    def isCoreFile(self, path):
        return os.path.basename(path).startswith("stacktrace")
    def interpretCoreFile(self, path):
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
            os.remove(path)
        else:
            writeFile.write("Could not find binary name from core file : Stack trace not produced for crash" + os.linesep)
            # Keep the core file for later viewing
            os.rename(path, "core")
        os.remove(fileName)
        os.rename(newPath, path)
    def extract(self, sourcePath, targetFile):
        if self.isCoreFile(targetFile):
            # Try to avoid race conditions extracting core files
            time.sleep(2)
        # Renaming links is fairly dangerous, if they point at relative paths. Copy these.
        if os.path.islink(sourcePath):
            shutil.copyfile(sourcePath, targetFile)
        else:
            try:
                # This generally fails due to cross-device link problems
                os.rename(sourcePath, targetFile)
            except:
                shutil.copyfile(sourcePath, targetFile)
                os.remove(sourcePath)

class MakePerformanceFile(plugins.Action):
    def __init__(self):
        self.includeSystemTime = 0
    def setUpApplication(self, app):
        app.setConfigDefault("cputime_include_system_time", 0)
        self.includeSystemTime = app.getConfigValue("cputime_include_system_time")
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
            if line.startswith("user"):
                cpuTime = self.parseUnixTime(line)
            if self.includeSystemTime and line.startswith("sys"):
                cpuTime = cpuTime + self.parseUnixTime(line)
            if line.startswith("real"):
                realTime = self.parseUnixTime(line)
        if cpuTime != None:
            os.remove(tmpFile)
        return cpuTime, realTime
    def timeString(self, timeVal):
        return str(round(float(timeVal), 1)).rjust(9)
    def parseUnixTime(self, line):
        timeVal = line.strip().split()[-1]
        if timeVal.find(":") == -1:
            return float(timeVal)

        parts = timeVal.split(":")
        return 60 * float(parts[0]) + float(parts[1])
    def writeFile(self, test, cpuTime, realTime, executionMachines, fileName):
        file = open(fileName, "w")
        cpuLine = "CPU time   : " + self.timeString(cpuTime) + " sec. on " + string.join(executionMachines, ",") + os.linesep
        file.write(cpuLine)
        realLine = "Real time  : " + self.timeString(realTime) + " sec." + os.linesep
        file.write(realLine)
        self.writeMachineInformation(file, executionMachines)
    def writeMachineInformation(self, file, executionMachines):
        # A space for subclasses to write whatever they think is relevant about
        # the machine environment right now.
        pass
    
