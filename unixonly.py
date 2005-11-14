#!/usr/local/bin/python

import default, respond, performance, predict, os, shutil, plugins, string, time, sys
from socket import gethostname
                
class RunTest(default.RunTest):
    def __init__(self):
        default.RunTest.__init__(self)
        self.loginShell = None
        self.testDisplay = None
        self.realDisplay = os.getenv("DISPLAY")
    def __call__(self, test, inChild=0):
        if self.testDisplay:
            os.environ["DISPLAY"] = self.testDisplay
        retValue = default.RunTest.__call__(self, test, inChild)
        if self.testDisplay and self.realDisplay:
            os.environ["DISPLAY"] = self.realDisplay
        return retValue
    def getExecuteCommand(self, test):
        testCommand = default.RunTest.getExecuteCommand(self, test)

        # put the command in a file to avoid quoting problems,
        cmdFile = test.makeFileName("cmd", temporary=1, forComparison=0)
        self.buildCommandFile(test, cmdFile, testCommand)
        unixPerfFile = test.makeFileName("unixperf", temporary=1, forComparison=0)
        timedTestCommand = '\\time -p ' + self.loginShell + ' ' + cmdFile + ' 2> ' + unixPerfFile
        return timedTestCommand
    def getStdErrRedirect(self, command, file):
        # C-shell based shells have different syntax here...
        if self.loginShell.find("csh") != -1:
            return "( " + command + " ) >& " + file
        else:
            return default.RunTest.getStdErrRedirect(self, command, file)        
    def buildCommandFile(self, test, cmdFile, testCommand):
        f = plugins.openForWrite(cmdFile)
        f.write(testCommand + "\n")
        f.close()
        return cmdFile
    def setUpApplication(self, app):
        default.RunTest.setUpApplication(self, app)
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
        self.slowMotionReplay = app.useSlowMotion()
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
        if server == gethostname():
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
            self.diag.info("Found Xvfb process running:" + "\n" + line)
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
   
def isCompressed(path):
    if os.path.getsize(path) == 0:
        return 0
    magic = open(path).read(2)
    if magic[0] == chr(0x1f) and magic[1] == chr(0x9d):
        return 1
    else:
        return 0

# Deal with UNIX-compressed files as well as straight text
class CollateFiles(default.CollateFiles):
    def __init__(self, keepCoreFiles):
        default.CollateFiles.__init__(self)
        self.collations["stacktrace"] = "core*"
        self.keepCoreFiles = keepCoreFiles
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
            file.write("Core file of zero size written - Stack trace not produced for crash\nCheck your coredumpsize limit" + "\n")
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
            stackTraceFound = self.writeStackTrace(stdoutFile, writeFile)
            if not stackTraceFound:
                self.writeGdbErrors(stderrFile, writeFile)
                self.keepCoreFiles = 1
            if self.keepCoreFiles:
                os.rename(path, "core")
            else:
                os.remove(path)
            os.remove(stdoutFile)
            os.remove(stderrFile)
        else:
            writeFile.write("Could not find binary name '" + binary + "' from core file : Stack trace not produced for crash" + "\n")
            os.rename(path, "core")
        os.remove(fileName)
        os.rename(newPath, path)
    def getBinaryFromCore(self, path, test):
        # Yes, we know this is horrible. Does anyone know a better way of getting the binary out of a core file???
        # Unfortunately running gdb is not the answer, because it truncates the data...
        finalWord = os.popen("csh -c 'echo `tail -c 1024 " + path + "`' 2> /dev/null").read().split(" ")[-1].strip()
        return finalWord.split("\n")[-1]
    def writeStackTrace(self, stdoutFile, writeFile):
        prevLine = ""
        foundStack = 0
        printedStackLines = 0
        for line in open(stdoutFile).xreadlines():
            if line.find("Program terminated") != -1:
                writeFile.write(line)
                writeFile.write("Stack trace from gdb :" + "\n")
                foundStack = 1
            if line[0] == "#" and line != prevLine:
                startPos = line.find("in ") + 3
                endPos = line.rfind("(")
                writeFile.write(line[startPos:endPos] + "\n")
                printedStackLines += 1
            prevLine = line
            # Sometimes you get enormous stacktraces from GDB, for example, if you have
            # an infinite recursive loop.
            if printedStackLines >= 30:
                writeFile.write("Stack trace print-out aborted after 30 function calls" + "\n")
                break
        return foundStack
    def writeGdbErrors(self, stderrFile, writeFile):
        writeFile.write("GDB backtrace command failed : Stack trace not produced for crash" + "\n")
        writeFile.write("Errors from GDB:" + "\n")
        for line in open(stderrFile).xreadlines():
            writeFile.write(line)
    def extract(self, sourcePath, targetFile):
        # Renaming links is fairly dangerous, if they point at relative paths. Copy these.
        if os.path.islink(sourcePath):
            shutil.copyfile(sourcePath, targetFile)
        else:
            plugins.movefile(sourcePath, targetFile)
    def getInterruptActions(self):
        if str(sys.exc_value) == "CPULIMIT":
            return [ default.CollateFiles() ]
        else:
            return [ self ]

