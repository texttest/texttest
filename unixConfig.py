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
    def addToOptionGroup(self, group):
        default.Config.addToOptionGroup(self, group)
        if group.name.startswith("Select"):
            group.addOption("r", "Execution time <min, max>")
        elif group.name.startswith("How"):
            group.addOption("b", "Run batch mode session")
    def getFilterList(self):
        filters = default.Config.getFilterList(self)
        self.addFilter(filters, "b", batch.BatchFilter)
        self.addFilter(filters, "r", performance.TimeFilter)
        return filters
    def batchMode(self):
        # If running multiple times, batch mode is assumed
        return self.optionMap.has_key("b") or self.optionMap.has_key("m")
    def keepTmpFiles(self):
        return self.batchMode()
    def getTestCollator(self):
        return CollateUNIXFiles()
    def hasPerformanceComparison(self, app):
        return default.Config.hasPerformanceComparison(self, app) or len(app.getConfigValue("performance_test_machine")) > 0
    def getPerformanceFileMaker(self):
        return MakePerformanceFile()
    def getTestRunner(self):
        return RunTest()
    def getTestResponder(self):
        diffLines = 30
        if self.batchMode():
            return batch.BatchResponder(diffLines, self.optionValue("b"))
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
    def setApplicationDefaults(self, app):
        default.Config.setApplicationDefaults(self, app)
        app.setConfigDefault("collect_standard_error", 1)
        app.setConfigDefault("virtual_display_machine", [])
        # Performance values
        app.setConfigDefault("performance_test_machine", [])
        app.setConfigDefault("cputime_include_system_time", 0)
        app.setConfigDefault("cputime_slowdown_variation_%", 30)
        app.setConfigDefault("cputime_variation_%", 10)
        app.setConfigDefault("minimum_cputime_for_test", 10)
        # Batch values. Maps from session name to values
        app.setConfigDefault("batch_recipients", { "default" : "$USER" })
        app.setConfigDefault("batch_timelimit", { "default" : None })
        app.setConfigDefault("batch_use_collection", { "default" : "false" })
        # Sample to show that values are lists
        app.setConfigDefault("batch_version", { "default" : [] })

class RunTest(default.RunTest):
    def __init__(self):
        default.RunTest.__init__(self)
        self.process = None
        self.collectStdErr = 1
        self.testDisplay = None
        self.realDisplay = os.getenv("DISPLAY")
    def __call__(self, test):
        if self.testDisplay:
            os.environ["DISPLAY"] = self.testDisplay
        retValue = default.RunTest.__call__(self, test)
        if self.testDisplay and self.realDisplay:
            os.environ["DISPLAY"] = self.realDisplay
        return retValue
    def runTest(self, test):
        if self.process:
            # See if the running process is finished
            if self.process.hasTerminated():
                self.process = None
                return
            else:
                return self.RETRY

        testCommand = self.getExecuteCommand(test)
        self.describe(test)
        self.process = plugins.BackgroundProcess(testCommand, testRun=1)
        self.process.waitForStart()
        return self.RETRY
    def getExecuteCommand(self, test):
        testCommand = default.RunTest.getExecuteCommand(self, test)
        if self.collectStdErr:
            errfile = test.makeFileName("errors", temporary=1)
            testCommand += " 2> " + errfile
        # put the command in a file to avoid quoting problems,
        # also fix env.variables that remote login doesn't reset
        cmdFile = test.makeFileName("cmd", temporary=1, forComparison=0)
        self.buildCommandFile(test, cmdFile, testCommand)
        unixPerfFile = test.makeFileName("unixperf", temporary=1, forComparison=0)
        timedTestCommand = '\\time -p sh ' + cmdFile + ' 2> ' + unixPerfFile
        return timedTestCommand
    def buildCommandFile(self, test, cmdFile, testCommand):
        f = open(cmdFile, "w")
        f.write(testCommand + os.linesep)
        f.close()
        return cmdFile
    def changeState(self, test):
        test.changeState(test.RUNNING, "Running on " + hostname())
    def getCleanUpAction(self):
        if self.process:
            print "Killing running test (process id", str(self.process.processId) + ")"
            self.process.kill()
    def setUpApplication(self, app):
        default.RunTest.setUpApplication(self, app)
        self.collectStdErr = app.getConfigValue("collect_standard_error")
        virtualDisplayMachines = app.getConfigValue("virtual_display_machine")
        if len(virtualDisplayMachines) > 0:
            self.allocateVirtualDisplay(virtualDisplayMachines)
    def allocateVirtualDisplay(self, virtualDisplayMachines):
        for machine in virtualDisplayMachines:
            display = self.findDisplay(machine)
            if display and display != "":
                return self.setDisplay(display)
            if display != None:
                self.killServer(machine)
        for machine in virtualDisplayMachines:
            display = self.startServer(machine)
            if display and display != "":
                return self.setDisplay(display)
    def setDisplay(self, display):
        self.testDisplay = display
        print "Tests will run with DISPLAY variable set to", display
    def killServer(self, server):
        # Xvfb servers get overloaded after a while. If they do, kill them
        line = os.popen("remsh " + server + " 'ps -efl | grep Xvfb | grep 42 | grep -v grep'").readline()
        if len(line) == 0:
            # We will only kill servers that were started by TextTest (have number 42!)
            return
        # On Linux fourth column of ps output is pid
        pidStr = line.split()[3]
        os.system("remsh " + server + " 'kill -9 " + pidStr + " >& /dev/null &' < /dev/null >& /dev/null &")
    def startServer(self, server):
        print "Starting Xvfb on machine", server
        os.system("remsh " + server + " 'Xvfb :42 >& /dev/null &' < /dev/null >& /dev/null &")
        #
        # The Xvfb server needs a running X-client and 'xhost +' if it is to receive X clients from
        # remote hosts.
        #
        serverName = server + ":42.0"
        os.system("remsh " + server + " 'xclock -display " + serverName + " >& /dev/null &' < /dev/null >& /dev/null & ")
        os.system("remsh " + server + " 'xterm -display " + serverName + " -e xhost + >& /dev/null &'< /dev/null >& /dev/null & ")
        return serverName
    def findDisplay(self, server):
        line = os.popen("remsh " + server + " 'ps -efl | grep Xvfb | grep -v grep'").readline()
        if len(line):
            serverName = server + line.split()[-1] + ".0"
            (cin, cout, cerr) = os.popen3("remsh " + server + " 'xterm -display " + serverName + " -e echo test'")
            lines = cerr.readlines()
            if len(lines) == 0:
                return serverName
            else:
                return ""
        return None
   
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
        self.collations["stacktrace"] = "core*"
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
            file.write("Core file of zero size written - Stack trace not produced for crash\nCheck your coredumpsize limit" + os.linesep)
            file.close()
            return
        fileName = "coreCommands.gdb"
        file = open(fileName, "w")
        file.write("bt\n")
        file.close()
        # Yes, we know this is horrible. Does anyone know a better way of getting the binary out of a core file???
        # Unfortunately running gdb is not the answer, because it truncates the data...
        binary = os.popen("csh -c 'echo `tail -c 1024 " + path + "`' 2> /dev/null").read().split(" ")[-1].strip()
        newPath = path + "tmp" 
        writeFile = open(newPath, "w")
        if os.path.isfile(binary):
            stdoutFile = "gdbout.txt"
            stderrFile = "gdberr.txt"
            gdbCommand = "gdb -q -batch -x " + fileName + " " + binary + " " + path + \
                         " > " + stdoutFile + " 2> " + stderrFile
            self.diag.info("Running GDB with command '" + gdbCommand + "'")
            os.system(gdbCommand)
            if not self.writeStackTrace(stdoutFile, writeFile):
                self.writeGdbErrors(stderrFile, writeFile)
                os.rename(path, "core")
            else:
                os.remove(path)
            os.remove(stdoutFile)
            os.remove(stderrFile)
        else:
            writeFile.write("Could not find binary name from core file : Stack trace not produced for crash" + os.linesep)
            # Keep the core file for later viewing
            os.rename(path, "core")
        os.remove(fileName)
        os.rename(newPath, path)
    def writeStackTrace(self, stdoutFile, writeFile):
        prevLine = ""
        foundStack = 0
        for line in open(stdoutFile).xreadlines():
            if line.find("Program terminated") != -1:
                writeFile.write(line)
                writeFile.write("Stack trace from gdb :" + os.linesep)
                foundStack = 1
            if line[0] == "#" and line != prevLine:
                startPos = line.find("in ") + 3
                endPos = line.rfind("(")
                writeFile.write(line[startPos:endPos] + os.linesep)
            prevLine = line
        return foundStack
    def writeGdbErrors(self, stderrFile, writeFile):
        writeFile.write("GDB backtrace command failed : Stack trace not produced for crash" + os.linesep)
        writeFile.write("Errors from GDB:" + os.linesep)
        for line in open(stderrFile).xreadlines():
            writeFile.write(line)
    def extract(self, sourcePath, targetFile):
        if self.isCoreFile(targetFile):
            # Try to avoid race conditions extracting core files
            time.sleep(2)
        # Renaming links is fairly dangerous, if they point at relative paths. Copy these.
        if os.path.islink(sourcePath):
            shutil.copyfile(sourcePath, targetFile)
        else:
            plugins.movefile(sourcePath, targetFile)

class MakePerformanceFile(plugins.Action):
    def __init__(self):
        self.includeSystemTime = 0
        self.diag = plugins.getDiagnostics("makeperformance")
    def setUpApplication(self, app):
        self.includeSystemTime = app.getConfigValue("cputime_include_system_time")
    def __repr__(self):
        return "Making performance file for"
    def __call__(self, test):
        if test.state == test.UNRUNNABLE or test.state == test.KILLED:
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
        self.diag.info("Reading performance file " + tmpFile)
        if not os.path.isfile(tmpFile):
            return None, None
            
        file = open(tmpFile)
        cpuTime = None
        realTime = None
        for line in file.readlines():
            self.diag.info("Parsing line " + line.strip())
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
    
