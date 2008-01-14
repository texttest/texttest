#!/usr/local/bin/python

import default, plugins, os, sys, subprocess, signal
from respond import Responder
from socket import gethostname
                
class RunTest(default.RunTest):
    def __init__(self, hasAutomaticCputimeChecking):
        default.RunTest.__init__(self)
        self.hasAutomaticCputimeChecking = hasAutomaticCputimeChecking
    def getExecuteCmdArgs(self, test):
        origArgs = default.RunTest.getExecuteCmdArgs(self, test)
        if self.hasAutomaticCputimeChecking(test.app):
            perfFile = test.makeTmpFileName("unixperf", forFramework=1)
            return [ "time", "-p", "-o", perfFile ] + origArgs
        else:
            return origArgs
        
# Unlike earlier incarnations of this functionality,
# we don't rely on sharing displays but create our own for each test run.
class VirtualDisplayResponder(Responder):
    instance = None
    def __init__(self, optionMap):
        Responder.__init__(self, optionMap)
        self.displayName = None
        self.displayMachine = None
        self.displayPid = None
        self.diag = plugins.getDiagnostics("virtual display")
        VirtualDisplayResponder.instance = self
        
    def addSuites(self, suites):
        guiSuites = filter(lambda suite : suite.getConfigValue("use_case_record_mode") == "GUI", suites)
        # On UNIX this is a virtual display to set the DISPLAY variable to, on Windows it's just a marker to hide the windows
        if os.name != "posix":
            self.setHideWindows(guiSuites)
        elif not self.displayName:
            self.setUpVirtualDisplay(guiSuites)

    def setHideWindows(self, suites):
        if len(suites) > 0 and not self.displayName:
            self.displayName = "HIDE_WINDOWS"
            print "Tests will run with windows hidden"

    def getXvfbLogDir(self, guiSuites):
        if len(guiSuites) > 0:
            return os.path.join(guiSuites[0].app.writeDirectory, "Xvfb") 
                              
    def setUpVirtualDisplay(self, guiSuites):
        machines = self.findMachines(guiSuites)
        logDir = self.getXvfbLogDir(guiSuites)
        machine, display, pid = self.getDisplay(machines, logDir)
        if display:
            self.displayName = display
            self.displayMachine = machine
            self.displayPid = pid
            print "Tests will run with DISPLAY variable set to", display
        elif len(machines) > 0:
            plugins.printWarning("Failed to start virtual display on " + ",".join(machines) + " - using real display.")

    def getDisplay(self, machines, logDir):
        for machine in machines:
            displayName, pid = self.createDisplay(machine, logDir)
            if displayName:
                return machine, displayName, pid
            else:
                plugins.printWarning("Virtual display program Xvfb not available on " + machine)
        return None, None, None
    
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
        if self.displayName:
            if self.displayMachine == "localhost":
                print "Killing Xvfb process", self.displayPid
                try:
                    os.kill(self.displayPid, signal.SIGTERM)
                except OSError:
                    print "Process had already terminated"
            else:
                self.killRemoteServer()
            self.displayName = None

    def killRemoteServer(self):
        self.diag.info("Getting ps output from " + self.displayMachine)
        print "Killing remote Xvfb process on", self.displayMachine, "with pid", self.displayPid
        subprocess.call([ "rsh", self.displayMachine, "kill", str(self.displayPid) ])

    def createDisplay(self, machine, logDir):
        if not self.canRunVirtualServer(machine):
            return None, None

        plugins.ensureDirectoryExists(logDir)
        startArgs = self.getVirtualServerArgs(machine, logDir)
        self.diag.info("Starting Xvfb using args " + repr(startArgs))
        proc = subprocess.Popen(startArgs, stdin=open(os.devnull), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        line = plugins.retryOnInterrupt(proc.stdout.readline)
        try:
            displayNum, pid = map(int, line.strip().split(","))
            proc.stdout.close()
            return self.getDisplayName(machine, displayNum), pid
        except ValueError:
            print "Failed to parse line :\n " + line + proc.stdout.read()
            return None, None
            
    def getVirtualServerArgs(self, machine, logDir):
        binDir = plugins.installationDir("bin")
        fullPath = os.path.join(binDir, "startXvfb.py")
        if machine == "localhost":
            return [ sys.executable, fullPath, logDir ]
        else:
            remotePython = self.findRemotePython(binDir)
            return [ "rsh", machine, remotePython + " -u " + fullPath + " " + logDir ]

    def findRemotePython(self, binDir):
        # In case it isn't the default, allow for a ttpython script in the installation
        localPointer = os.path.join(binDir, "ttpython")
        if os.path.isfile(localPointer):
            return localPointer
        else:
            return "python"
        
    def getDisplayName(self, machine, displayNumber):
        return machine + ":" + str(displayNumber) + ".0"

    def canRunVirtualServer(self, machine):
        # If it's not localhost, we need to make sure it exists and has Xvfb installed
        whichArgs = [ "which", "Xvfb" ]
        if machine != "localhost":
            whichArgs = [ "rsh", machine ] + whichArgs
        whichProc = subprocess.Popen(whichArgs, stdin=open(os.devnull), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        outStr, errStr = whichProc.communicate()
        return len(errStr) == 0 and outStr.find("not found") == -1
