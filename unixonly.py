#!/usr/local/bin/python

import default, respond, performance, predict, os, shutil, plugins, string, time, sys
from socket import gethostname
                
class RunTest(default.RunTest):
    def __init__(self):
        default.RunTest.__init__(self)
        self.realDisplay = os.getenv("DISPLAY")
    def __call__(self, test, inChild=0):
        if os.environ.has_key("TEXTTEST_VIRTUAL_DISPLAY"):
            os.environ["DISPLAY"] = os.environ["TEXTTEST_VIRTUAL_DISPLAY"]
        retValue = default.RunTest.__call__(self, test, inChild)
        if self.realDisplay:
            os.environ["DISPLAY"] = self.realDisplay
        return retValue
    def getExecuteCommand(self, test):
        testCommand = default.RunTest.getExecuteCommand(self, test)

        # put the command in a file to avoid quoting problems,
        cmdFile = test.makeTmpFileName("cmd", forFramework=1)
        self.buildCommandFile(test, cmdFile, testCommand)
        unixPerfFile = test.makeTmpFileName("unixperf", forFramework=1)
        timedTestCommand = '\\time -p sh ' + cmdFile + ' 2> ' + unixPerfFile
        return timedTestCommand
    def buildCommandFile(self, test, cmdFile, testCommand):
        f = plugins.openForWrite(cmdFile)
        f.write(testCommand + "\n")
        self.diag.info("Writing cmdFile at " + cmdFile)
        self.diag.info("Contains : " + testCommand)
        f.close()
        return cmdFile

class VirtualDisplayFinder:
    def __init__(self, app):
        self.machines = app.getConfigValue("virtual_display_machine")
        self.diag = plugins.getDiagnostics("virtual display")
    def getDisplay(self):
        if len(self.machines) == 0:
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
        print "Trying to kill unusable Xvfb process", pidStr, "on machine " + server
        os.system(self.getSysCommand(server, "kill -9 " + pidStr, background=0))
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
            return "rsh " + server + " " + command
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
        self.diag.info("Getting ps output from " + server)
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
            testCommandLine = self.getSysCommand(gethostname(), "xterm -display " + serverName + " -e echo test", background=0)
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
        return False
    magic = open(path).read(2)
    if magic[0] == chr(0x1f) and magic[1] == chr(0x9d):
        return True
    else:
        return False

