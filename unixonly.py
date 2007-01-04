#!/usr/local/bin/python

import default, plugins, os
                
class RunTest(default.RunTest):
    def __init__(self, hasAutomaticCputimeChecking):
        default.RunTest.__init__(self)
        self.realDisplay = os.getenv("DISPLAY")
        self.hasAutomaticCputimeChecking = hasAutomaticCputimeChecking
    def __call__(self, test, inChild=0):
        if os.environ.has_key("TEXTTEST_VIRTUAL_DISPLAY"):
            os.environ["DISPLAY"] = os.environ["TEXTTEST_VIRTUAL_DISPLAY"]
        retValue = default.RunTest.__call__(self, test, inChild)
        if self.realDisplay:
            os.environ["DISPLAY"] = self.realDisplay
        return retValue
    def getExecuteCommand(self, test):
        testCommand = default.RunTest.getExecuteCommand(self, test)
        selfTestStdin = self.shellTitle and os.environ.has_key("USECASE_REPLAY_SCRIPT")
            
        if not selfTestStdin and not self.hasAutomaticCputimeChecking(test.app):
            return testCommand # Don't bother with this if we aren't measuring CPU time!
        
        # put the command in a file to avoid quoting problems,
        cmdFile = test.makeTmpFileName("cmd", forFramework=1)
        self.buildCommandFile(test, cmdFile, testCommand)
        unixPerfFile = test.makeTmpFileName("unixperf", forFramework=1)
        if selfTestStdin:
            return 'sh ' + cmdFile
        else:
            return '\\time -p sh ' + cmdFile + ' 2> ' + unixPerfFile
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

        usableDisplay, emptyMachine = self.classifyMachines()
        if usableDisplay:
            return usableDisplay
        elif emptyMachine:
            return self.startServer(emptyMachine)
        else:
            plugins.printWarning("Virtual display test command failed on all machines - attempting to use first one anyway.")
            return self.machines[0] + ":42.0"
    def classifyMachines(self):
        emptyMachine = None
        # Try to find an existing display we can connect to
        for machine in self.machines:
            self.diag.info("Looking for virtual display on " + machine)
            display, displayErrs = self.findDisplay(machine)
            if display:
                connErrors = self.getConnectionErrors(display)
                if len(connErrors) > 0:
                    print "Failed to connect to virtual server on", machine + "\n" + connErrors
                    if self.killServer(machine) and not emptyMachine:
                        emptyMachine = machine
                else:
                    return display, emptyMachine
            else:
                if displayErrs:
                    print "Could not get display info from", machine + ":\n" + displayErrs
                elif not emptyMachine:
                    emptyMachine = machine
        return None, emptyMachine
    def killServer(self, server):
        # Xvfb servers get overloaded after a while. If they do, kill them
        line, errors = self.getPsOutput(server)
        if len(line) == 0:
            # If it's been killed in the meantime, all is well...
            return True

        words = line.split()
        # Assumes linux ps output (!)
        processOwner = words[2]
        if processOwner != os.getenv("USER"):
            print "Unusable Xvfb process on machine " + server + " owned by user " + processOwner
            return False
    
        pidStr = words[3]
        print "Killing unusable Xvfb process", pidStr, "on machine " + server
        os.system(self.getSysCommand(server, "kill -9 " + pidStr, background=0))
        return True
    def getSysCommand(self, server, command, background=1):
        if background:
            command = "'" + command + plugins.nullRedirect() + " &' < /dev/null" + plugins.nullRedirect() + " &"
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
    def getPsOutput(self, server):
        self.diag.info("Getting ps output from " + server)
        psCommand = self.getSysCommand(server, "ps -efl | grep Xvfb | grep -v grep", background=0)
        cin, cout,cerr = os.popen3(psCommand)
        for line in cout.readlines():
            if line.find("Xvfb") != -1 and line.find("42") != -1:
                return line, ""
        return "", cerr.read()
    def findDisplay(self, server):
        line, errors = self.getPsOutput(server)
        if len(line):
            self.diag.info("Found Xvfb process running:\n" + line)
            serverName = server + line.split()[-1] + ".0"
            return serverName, ""
        else:
            return "", errors
    def getConnectionErrors(self, serverName):
        testCommandLine = "xdpyinfo -display " + serverName + " > /dev/null"
        self.diag.info("Testing with command '" + testCommandLine + "'")
        cin, cerr = os.popen4(testCommandLine)
        return cerr.read()
   
def isCompressed(path):
    if os.path.getsize(path) == 0:
        return False
    magic = open(path).read(2)
    if magic[0] == chr(0x1f) and magic[1] == chr(0x9d):
        return True
    else:
        return False

