#!/usr/local/bin/python

# Text only relevant to using the LSF configuration directly
helpDescription = """
The UNIX configuration is designed to run on a UNIX system. It therefore makes use of some
UNIX tools, such as tkdiff, diff and /usr/lib/sendmail. The difference tools are used in preference
to Python's ndiff, and sendmail is used to implement an email-sending batch mode (see options)

The default behaviour is to run all tests locally.
"""

import default, batch, respond, performance, predict, os, shutil, plugins, string, time
from threading import currentThread

def getConfig(optionMap):
    return UNIXConfig(optionMap)

class UNIXConfig(default.Config):
    def addToOptionGroups(self, app, groups):
        default.Config.addToOptionGroups(self, app, groups)
        for group in groups:
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
        return self.optionMap.has_key("b")
    def getCleanMode(self):
        defaultMode = default.Config.getCleanMode(self)
        if self.batchMode() and defaultMode & self.CLEAN_BASIC:
            return self.CLEAN_PREVIOUS
        else:
            return defaultMode
    def getTestCollator(self):
        return CollateUNIXFiles()
    def getPerformanceFileMaker(self):
        return MakePerformanceFile(self.getMachineInfoFinder())
    def getTestRunner(self):
        return RunTest()
    def getTestResponder(self):
        if self.batchMode():
            return batch.BatchResponder(self.optionValue("b"))
        else:
            return default.Config.getTestResponder(self)
    def defaultLoginShell(self):
        return "sh"
    def defaultTextDiffTool(self):
        return "diff"
    def defaultSeverities(self):
        severities = default.Config.defaultSeverities(self)
        severities["errors"] = 1
        severities["performance"] = 2
        return severities
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
        app.setConfigDefault("cputime_include_system_time", 0)
        app.setConfigDefault("cputime_slowdown_variation_%", 30)
        # Batch values. Maps from session name to values
        app.setConfigDefault("batch_recipients", { "default" : "$USER" })
        app.setConfigDefault("batch_timelimit", { "default" : None })
        app.setConfigDefault("batch_use_collection", { "default" : "false" })
        # Sample to show that values are lists
        app.setConfigDefault("batch_version", { "default" : [] })
        app.setConfigDefault("login_shell", self.defaultLoginShell())
        # Use batch session as a base version
        batchSession = self.optionValue("b")
        if batchSession:
            app.addConfigEntry("base_version", batchSession)
        app.addConfigEntry("pending", "white", "test_colours")

# Workaround for python bug 853411: tell main thread to start the process
# if we aren't it...
class Pending(plugins.TestState):
    def __init__(self, process):
        plugins.TestState.__init__(self, "pending")
        self.process = process
        if currentThread().getName() == "MainThread":
            self.notifyInMainThread()
    def notifyInMainThread(self):
        self.process.doFork()

class RunTest(default.RunTest):
    def __init__(self):
        default.RunTest.__init__(self)
        self.process = None
        self.loginShell = None
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
        test.changeState(Pending(self.process))
        self.process.waitForStart()
        return self.RETRY
    def getExecuteCommand(self, test):
        testCommand = default.RunTest.getExecuteCommand(self, test)
        if self.collectStdErr:
            errfile = test.makeFileName("errors", temporary=1)
            # C-shell based shells have different syntax here...
            if self.loginShell.find("csh") != -1:
                testCommand = "( " + testCommand + " ) >& " + errfile
            else:
                testCommand += " 2> " + errfile
        # put the command in a file to avoid quoting problems,
        # also fix env.variables that remote login doesn't reset
        cmdFile = test.makeFileName("cmd", temporary=1, forComparison=0)
        self.buildCommandFile(test, cmdFile, testCommand)
        unixPerfFile = test.makeFileName("unixperf", temporary=1, forComparison=0)
        timedTestCommand = '\\time -p ' + self.loginShell + ' ' + cmdFile + ' 2> ' + unixPerfFile
        return timedTestCommand
    def buildCommandFile(self, test, cmdFile, testCommand):
        f = open(cmdFile, "w")
        f.write(testCommand + os.linesep)
        f.close()
        return cmdFile
    def getCleanUpAction(self):
        return KillTest(self)
    def setUpApplication(self, app):
        default.RunTest.setUpApplication(self, app)
        self.collectStdErr = app.getConfigValue("collect_standard_error")
        self.loginShell = app.getConfigValue("login_shell")
        self.setUpVirtualDisplay(app)
    def setUpVirtualDisplay(self, app):
        finder = VirtualDisplayFinder(app)
        display = finder.getDisplay()
        if display:
            self.testDisplay = display
            print "Tests will run with DISPLAY variable set to", display

class VirtualDisplayFinder:
    def __init__(self, app):
        self.machines = app.getConfigValue("virtual_display_machine")
        self.slowMotionReplay = app.slowMotionReplaySpeed != 0
        self.diag = plugins.getDiagnostics("virtual display")
    def getDisplay(self):
        if len(self.machines) == 0 or self.slowMotionReplay:
            return
        for machine in self.machines:
            self.diag.info("Looking for virtual display on " + machine)
            display = self.findDisplay(machine)
            if display and display != "":
                return display
            if display != None:
                self.killServer(machine)
        for machine in self.machines:
            display = self.startServer(machine)
            if display and display != "":
                return display
    def killServer(self, server):
        # Xvfb servers get overloaded after a while. If they do, kill them
        line = self.getPsOutput(server, ownProcesses=1)
        if len(line) == 0:
            # We will only kill servers that were started by TextTest (have number 42!)
            return
        # On Linux fourth column of ps output is pid
        pidStr = line.split()[3]
        os.system(self.getSysCommand(server, "kill -9 " + pidStr))
    def getSysCommand(self, server, command, background=1):
        if server == default.hostname():
            if background:
                return command + " >& /dev/null &"
            else:
                return command
        else:
            if background:
                command = "'" + command + " >& /dev/null &' < /dev/null >& /dev/null &"
            else:
                command = "'" + command + "'"
            return "remsh " + server + " " + command
    def startServer(self, server):
        print "Starting Xvfb on machine", server
        os.system(self.getSysCommand(server, "Xvfb :42"))
        #
        # The Xvfb server needs a running X-client and 'xhost +' if it is to receive X clients from
        # remote hosts.
        #
        serverName = server + ":42.0"
        os.system(self.getSysCommand(server, "xclock -display " + serverName))
        os.system(self.getSysCommand(server, "xterm -display " + serverName + " -e xhost +"))
        return serverName
    def getPsOutput(self, server, ownProcesses):
        psCommand = self.getSysCommand(server, "ps -efl | grep Xvfb | grep -v grep", background=0)
        lines = os.popen(psCommand).readlines()
        for line in lines:
            if line.find("Xvfb") != -1 and (not ownProcesses or line.find("42") != -1):
                return line
        return ""
    def findDisplay(self, server):
        line = self.getPsOutput(server, ownProcesses=0)
        if len(line):
            self.diag.info("Found Xvfb process running:" + os.linesep + line)
            serverName = server + line.split()[-1] + ".0"
            testCommandLine = self.getSysCommand(server, "xterm -display " + serverName + " -e echo test", background=0)
            self.diag.info("Testing with command '" + testCommandLine + "'")
            (cin, cout, cerr) = os.popen3(testCommandLine)
            lines = cerr.readlines()
            if len(lines) == 0:
                return serverName
            else:
                print "Failed to connect to virtual server on", server
                for line in lines:
                    print line.strip()
                return ""
        return None

class KillTest(plugins.Action):
    def __init__(self, testRunner):
        self.runner = testRunner
    def setUpApplication(self, app):
        process = self.runner.process
        if process and process.processId:
            print "Killing running test (process id", str(process.processId) + ")"
            process.kill()
   
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
    def transformToText(self, path, test):
        if isCompressed(path):
            toUse = path + ".Z"
            os.rename(path, toUse)
            os.system("uncompress " + toUse)
        if self.isCoreFile(path) and self.extractCoreFor(test):
            # Extract just the stack trace rather than the whole core
            self.interpretCoreFile(path, test)
    def isCoreFile(self, path):
        return os.path.basename(path).startswith("stacktrace")
    def extractCoreFor(self, test):
        return 1
    def interpretCoreFile(self, path, test):
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
        binary = self.getBinaryFromCore(path, test)
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
            writeFile.write("Could not find binary name '" + binary + "' from core file : Stack trace not produced for crash" + os.linesep)
            os.rename(path, "core")
        os.remove(fileName)
        os.rename(newPath, path)
    def getBinaryFromCore(self, path, test):
        # Yes, we know this is horrible. Does anyone know a better way of getting the binary out of a core file???
        # Unfortunately running gdb is not the answer, because it truncates the data...
        finalWord = os.popen("csh -c 'echo `tail -c 1024 " + path + "`' 2> /dev/null").read().split(" ")[-1].strip()
        return finalWord.split(os.linesep)[-1]
    def writeStackTrace(self, stdoutFile, writeFile):
        prevLine = ""
        foundStack = 0
        printedStackLines = 0
        for line in open(stdoutFile).xreadlines():
            if line.find("Program terminated") != -1:
                writeFile.write(line)
                writeFile.write("Stack trace from gdb :" + os.linesep)
                foundStack = 1
            if line[0] == "#" and line != prevLine:
                startPos = line.find("in ") + 3
                endPos = line.rfind("(")
                writeFile.write(line[startPos:endPos] + os.linesep)
                printedStackLines += 1
            prevLine = line
            # Sometimes you get enormous stacktraces from GDB, for example, if you have
            # an infinite recursive loop.
            if printedStackLines >= 30:
                writeFile.write("Stack trace print-out aborted after 30 function calls" + os.linesep)
                break
        return foundStack
    def writeGdbErrors(self, stderrFile, writeFile):
        writeFile.write("GDB backtrace command failed : Stack trace not produced for crash" + os.linesep)
        writeFile.write("Errors from GDB:" + os.linesep)
        for line in open(stderrFile).xreadlines():
            writeFile.write(line)
    def extract(self, sourcePath, targetFile):
        # Renaming links is fairly dangerous, if they point at relative paths. Copy these.
        if os.path.islink(sourcePath):
            shutil.copyfile(sourcePath, targetFile)
        else:
            plugins.movefile(sourcePath, targetFile)

class MakePerformanceFile(default.PerformanceFileCreator):
    def __init__(self, machineInfoFinder):
        default.PerformanceFileCreator.__init__(self, machineInfoFinder)
        self.includeSystemTime = 0
    def setUpApplication(self, app):
        default.PerformanceFileCreator.setUpApplication(self, app)
        self.includeSystemTime = app.getConfigValue("cputime_include_system_time")
    def __repr__(self):
        return "Making performance file for"
    def makePerformanceFiles(self, test, temp):
        # Ugly hack to work around lack of proper test states
        executionMachines = self.machineInfoFinder.findExecutionMachines(test)
        test.execHost = string.join(executionMachines, ",")
        
        # Check that all of the execution machines are also performance machines
        if not self.allMachinesTestPerformance(test, "cputime"):
            return
        cpuTime, realTime = self.readTimes(test)
        # There was still an error (jobs killed in emergency), so don't write performance files
        if cpuTime == None:
            print "Not writing performance file for", test
            return
        
        fileToWrite = test.makeFileName("performance", temporary=1)
        self.writeFile(test, cpuTime, realTime, executionMachines, fileToWrite)
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
        cpuLine = "CPU time   : " + self.timeString(cpuTime) + " sec. on " + test.execHost + os.linesep
        file.write(cpuLine)
        realLine = "Real time  : " + self.timeString(realTime) + " sec." + os.linesep
        file.write(realLine)
        self.writeMachineInformation(file, executionMachines)
    def writeMachineInformation(self, file, executionMachines):
        # A space for subclasses to write whatever they think is relevant about
        # the machine environment right now.
        pass
    
