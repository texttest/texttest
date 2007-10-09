#!/usr/local/bin/python

import default, plugins, os, subprocess, signal
from respond import Responder
from socket import gethostname
                
class RunTest(default.RunTest):
    def __init__(self, hasAutomaticCputimeChecking):
        default.RunTest.__init__(self)
        self.hasAutomaticCputimeChecking = hasAutomaticCputimeChecking
    def getTestProcess(self, test):
        if not self.hasAutomaticCputimeChecking(test.app):
            return default.RunTest.getTestProcess(self, test) # Don't bother with this if we aren't measuring CPU time!

        cmdArgs = [ "time", "-p", "sh", "-c", self.getExecuteCommand(test) ]
        self.diag.info("Running performance-test with args : " + repr(cmdArgs))
        stderrFile = test.makeTmpFileName("unixperf", forFramework=1)
        return subprocess.Popen(cmdArgs, stdin=open(os.devnull), cwd=test.getDirectory(temporary=1),\
                                env=test.getRunEnvironment(), stdout=open(os.devnull, "w"), stderr=open(stderrFile, "w"))
    def getExecuteCommand(self, test):
        cmdParts = self.getCmdParts(test)
        testCommand = " ".join(cmdParts)
        testCommand += " < " + self.getInputFile(test)
        outfile = test.makeTmpFileName("output")
        testCommand += " > " + outfile
        errfile = test.makeTmpFileName("errors")
        return testCommand + " 2> " + errfile
        
# Unlike earlier incarnations of this functionality,
# we don't rely on sharing displays but create our own for each test run.
class VirtualDisplayResponder(Responder):
    MAX_DISPLAY = 32768
    def __init__(self, optionMap):
        self.serverInfo = None
        self.diag = plugins.getDiagnostics("virtual display")
    
    def addSuites(self, suites):
        guiSuites = filter(lambda suite : suite.getConfigValue("use_case_record_mode") == "GUI", suites)
        # On UNIX this is a virtual display to set the DISPLAY variable to, on Windows it's just a marker to hide the windows
        if os.name != "posix":
            self.setHideWindows(guiSuites)
        elif self.serverInfo:
            self.setExistingDisplay(guiSuites)
        else:
            self.setUpVirtualDisplay(guiSuites)
    def setExistingDisplay(self, guiSuites):
        machine, proc = self.serverInfo
        displayName = self.getDisplayName(machine, self.getDisplayNumber())
        self.setDisplayVariable(guiSuites, displayName)

    def setHideWindows(self, suites):
        for suite in suites:
            suite.setEnvironment("DISPLAY", "HIDE_WINDOWS")
        if len(suites) > 0 and not self.serverInfo:
            print "Tests will run with windows hidden"

    def setDisplayVariable(self, guiSuites, displayName):
        for suite in guiSuites:
            suite.setEnvironment("DISPLAY", displayName)

    def getXvfbLogDir(self, guiSuites):
        if len(guiSuites) > 0:
            return os.path.join(guiSuites[0].app.writeDirectory, "Xvfb") 
                              
    def setUpVirtualDisplay(self, guiSuites):
        machines = self.findMachines(guiSuites)
        logDir = self.getXvfbLogDir(guiSuites)
        display = self.getDisplay(machines, logDir)
        if display:
            self.setDisplayVariable(guiSuites, display)
            print "Tests will run with DISPLAY variable set to", display
        elif len(machines) > 0:
            plugins.printWarning("Failed to start virtual display on " + ",".join(machines) + " - using real display.")

    def getDisplay(self, machines, logDir):
        displayNumber = self.getDisplayNumber()
        for machine in machines:
            if self.createDisplay(machine, displayNumber, logDir):
                return self.getDisplayName(machine, displayNumber)
            else:
                plugins.printWarning("Virtual display program Xvfb not available on " + machine) 

    def getDisplayNumber(self):
        # We use the device of making the display number match our process ID (mod 32768)!
        # And we hope that works :) Should prevent clashes with others using the same strategy anyway
        # Display numbers up to 32768 seem to be allowed, which is less than most process IDs on systems I've observed...
        return str(os.getpid() % self.MAX_DISPLAY)
    
    def findMachines(self, suites):
        allMachines = []
        for suite in suites:
            for machine in suite.getConfigValue("virtual_display_machine"):
                if not machine in allMachines:
                    allMachines.append(machine)
        return allMachines
    
    def notifyAllComplete(self):
        self.cleanXvfb()
    def notifyExit(self, *args):
        self.cleanXvfb()
    def cleanXvfb(self):
        if self.serverInfo:
            machine, proc = self.serverInfo
            if machine == "localhost":
                print "Killing Xvfb process", proc.pid
                try:
                    os.kill(proc.pid, signal.SIGINT)
                except OSError:
                    print "Process had already terminated"
                proc.wait()
                self.cleanLeakedLockFiles()
            else:
                self.killRemoteServer(machine)
            self.serverInfo = None
            
    def cleanLeakedLockFiles(self):
        # Xvfb sometimes leaves lock files lying around, clean up
        for lockFile in self.getLockFiles():
            if os.path.isfile(lockFile):
                print "Xvfb leaked lock file at", lockFile, "attempting to remove it"
                try:
                    os.remove(lockFile)
                except:
                    print "Failed to do so: ", plugins.getExceptionString()
                
    def getLockFiles(self):
        num = self.getDisplayNumber()
        lockFile = "/tmp/.X" + num + "-lock"
        xFile = "/tmp/.X11-unix/X" + num
        return [ lockFile, xFile ]

    def killRemoteServer(self, machine):
        self.diag.info("Getting ps output from " + machine)
        pid = self.findRemoteServerPid(machine)
        if pid:
            print "Killing remote Xvfb process on", machine, "with pid", pid
            subprocess.call([ "rsh", machine, "kill", pid ])
                
    def findRemoteServerPid(self, machine):
        psArgs = [ "rsh", machine, "ps -efl" ]
        process = subprocess.Popen(psArgs, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        outstr, errstr = process.communicate()
        for line in outstr.splitlines():
            if line.find("Xvfb") != -1 and line.find(self.getDisplayNumber()) != -1 and line.find("csh") == -1:
                self.diag.info("Found Xvfb process running:\n" + line)
                # Assumes linux ps output (!)
                return line.split()[3]

    def createDisplay(self, machine, displayNumber, logDir):
        if machine != "localhost" and not self.canRunVirtualServer(machine):
            return False
            
        startArgs = self.getVirtualServerArgs(machine, displayNumber)
        self.diag.info("Starting Xvfb using args " + repr(startArgs))
        try:
            local = "Xvfb." + machine.replace("localhost", gethostname()) + "." + displayNumber
            logFile = plugins.openForWrite(os.path.join(logDir, local))
            proc = subprocess.Popen(startArgs, stdout=logFile, stderr=subprocess.STDOUT)
            self.serverInfo = machine, proc
            return True
        except OSError:
            return False
    def getVirtualServerArgs(self, machine, displayNumber):
        # -ac option disables all access control so we can get at it from elsewhere
        if machine == "localhost":
            return [ "Xvfb", "-ac", "-audit", "2", ":" + displayNumber ]
        else:
            return [ "rsh", machine, "Xvfb -ac -audit 2 :" + displayNumber ]
    def getDisplayName(self, machine, displayNumber):
        return machine + ":" + displayNumber + ".0"

    def canRunVirtualServer(self, machine):
        # If it's not localhost, we need to make sure it exists and has Xvfb installed
        whichArgs = [ "rsh", machine, "which", "Xvfb" ]
        whichProc = subprocess.Popen(whichArgs, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        outStr, errStr = whichProc.communicate()
        return len(errStr) == 0 and outStr.find("not found") == -1
