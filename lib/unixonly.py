#!/usr/local/bin/python

import default, plugins, os, subprocess
                
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
    def getTestProcess(self, test):
        if not self.hasAutomaticCputimeChecking(test.app):
            return default.RunTest.getTestProcess(self, test) # Don't bother with this if we aren't measuring CPU time!

        cmdArgs = [ "time", "-p", "sh", "-c", self.getExecuteCommand(test) ]
        self.diag.info("Running performance-test with args : " + repr(cmdArgs))
        stderrFile = test.makeTmpFileName("unixperf", forFramework=1)
        return subprocess.Popen(cmdArgs, stdin=open(os.devnull), \
                                stdout=open(os.devnull, "w"), stderr=open(stderrFile, "w"))
    def getExecuteCommand(self, test):
        cmdParts = self.getCmdParts(test)
        testCommand = " ".join(cmdParts)
        testCommand += " < " + self.getInputFile(test)
        outfile = test.makeTmpFileName("output")
        testCommand += " > " + outfile
        errfile = test.makeTmpFileName("errors")
        return testCommand + " 2> " + errfile

class VirtualDisplayFinder:
    checkedDisplay = None
    def __init__(self, app):
        self.machines = app.getConfigValue("virtual_display_machine")
        self.displayNumber = app.getConfigValue("virtual_display_number")
        self.diag = plugins.getDiagnostics("virtual display")
    def getDisplay(self):
        if self.checkedDisplay:
            return self.checkedDisplay
        
        if len(self.machines) == 0:
            return

        usableDisplay, emptyMachine = self.classifyMachines()
        if usableDisplay:
            VirtualDisplayFinder.checkedDisplay = usableDisplay
            return usableDisplay
        elif emptyMachine:
            self.startServer(emptyMachine)
            return self.getDisplayName(emptyMachine)
        else:
            plugins.printWarning("Virtual display test command failed on " + ",".join(self.machines) + " - using real display.")
    def classifyMachines(self):
        emptyMachine = None
        # Try to find an existing display we can connect to
        for machine in self.machines:
            self.diag.info("Looking for virtual display on " + machine)
            display = self.getDisplayName(machine)
            connErrors = self.getConnectionErrors(display)
            if len(connErrors) == 0:
                return display, emptyMachine
                
            procOut, procErrs = self.getProcessInfo(machine)
            if len(procErrs) == 0:
                if self.clearMachine(machine, procOut, connErrors) and not emptyMachine:
                    emptyMachine = machine
            else:
                # assume stderr from rsh implies problems contacting the machine, and ignore it
                print "Could not get display info from", machine + ":\n" + procErrs
            
        return None, emptyMachine
    def clearMachine(self, server, procOut, connErrors):
        if len(procOut) == 0:
            print "No virtual server is running on", server
            return True

        # Xvfb servers get overloaded after a while. If they do, kill them
        words = procOut.split()
        # Assumes linux ps output (!)
        processOwner = words[2]
        print "Unusable Xvfb process on machine " + server + " owned by user " + processOwner + ":\n" + \
              "Errors from xdpyinfo : '" + connErrors.strip() + "'"
        if processOwner != os.getenv("USER"):
            return False
    
        pidStr = words[3]
        print "Current user owns the process (" + pidStr + "), so killing it"
        subprocess.call(self.getRemoteArgs(server, [ "kill", "-9", pidStr ]))
        return True
    def getRemoteArgs(self, server, localArgs):
        if server == "localhost":
            return localArgs
        else:
            return [ "rsh", server, " ".join(localArgs) ]
    def getDisplayName(self, server):
        return server + ":" + self.displayNumber + ".0"
    def startServer(self, server):
        print "Starting Xvfb on machine", server
        # -ac option disables all access control so anyone can run there
        startArgs = self.getRemoteArgs(server, [ "Xvfb", "-ac", ":" + self.displayNumber ])
        self.diag.info("Starting Xvfb using args " + repr(startArgs))
        return subprocess.Popen(startArgs, stdout=open(os.devnull, "w"), stderr=subprocess.STDOUT)
    def getProcessInfo(self, server):
        self.diag.info("Getting ps output from " + server)
        psArgs = self.getRemoteArgs(server, [ "ps", "-efl" ])
        process = subprocess.Popen(psArgs, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        outstr, errstr = process.communicate()
        for line in outstr.splitlines():
            if line.find("Xvfb") != -1 and line.find(self.displayNumber) != -1 and line.find("sh") == -1:
                self.diag.info("Found Xvfb process running:\n" + line)
                return line, ""
        return "", errstr
    def getConnectionErrors(self, serverName):
        args = [ "xdpyinfo", "-display", serverName ]
        self.diag.info("Testing with args '" + repr(args) + "'")
        proc = subprocess.Popen(args, stdout=open(os.devnull, "w"), stderr=subprocess.PIPE)
        return proc.stderr.read()
