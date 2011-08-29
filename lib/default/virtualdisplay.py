#!/usr/local/bin/python

import plugins, os, sys, subprocess, signal, logging
        
# Unlike earlier incarnations of this functionality,
# we don't rely on sharing displays but create our own for each test run.
class VirtualDisplayResponder(plugins.Responder):
    instance = None
    def __init__(self, *args):
        plugins.Responder.__init__(self, *args)
        self.displayName = None
        self.displayMachine = None
        self.displayPid = None
        self.displayProc = None
        self.guiSuites = []
        self.diag = logging.getLogger("virtual display")
        self.killDiag = logging.getLogger("kill processes")
        VirtualDisplayResponder.instance = self
        
    def addSuites(self, suites):
        guiSuites = filter(lambda suite : suite.getConfigValue("use_case_record_mode") == "GUI", suites)
        if not self.displayName:
            self.setUpVirtualDisplay(guiSuites)
                              
    def setUpVirtualDisplay(self, guiSuites):
        if len(guiSuites) == 0:
            return
        machines = self.findMachines(guiSuites)
        machine, display, pid = self.getDisplay(machines, guiSuites[0].app)
        if display:
            self.displayName = display
            self.displayMachine = machine
            self.displayPid = pid
            self.guiSuites = guiSuites
            plugins.log.info("Tests will run with DISPLAY variable set to " + display)
        elif len(machines) > 0:
            plugins.printWarning("Failed to start virtual display on " + ",".join(machines) + " - using real display.")

    def getDisplay(self, machines, app):
        for machine in machines:
            displayName, pid = self.createDisplay(machine, app)
            if displayName:
                return machine, displayName, pid
            else:
                plugins.printWarning("Virtual display program Xvfb not available on " + machine, stdout=True)
        return None, None, None
    
    def findMachines(self, suites):
        allMachines = []
        for suite in suites:
            for machine in suite.getConfigValue("virtual_display_machine"):
                if machine == "localhost": # Local to the test run, not to where we're trying to run...
                    machine = suite.app.getRunMachine()
                if not machine in allMachines:
                    allMachines.append(machine)
        return allMachines

    def notifyComplete(self, *args):
        # Whenever a test completes, we check to see if the virtual server is still going
        if self.displayProc is not None and self.displayProc.poll() is not None:
            self.displayProc.wait() # Don't leave zombie processes around
            # If Xvfb has terminated, we need to restart it
            self.setUpVirtualDisplay(self.guiSuites)
            
    def notifyAllComplete(self):
        self.cleanXvfb()
    def notifyKillProcesses(self, *args):
        self.cleanXvfb()

    def terminateIfRunning(self, pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError: # pragma: no cover - only set up this way to avoid race conditions. Should never happen in real life anyway
            pass
    
    def cleanXvfb(self):
        if self.displayName and os.name == "posix":
            if self.displayMachine == "localhost":
                self.killDiag.info("Killing Xvfb process " + str(self.displayPid))
                self.terminateIfRunning(self.displayPid)
            else:
                self.killRemoteServer()
            self.displayName = None
            self.displayProc.wait() # don't leave zombies around
            self.displayProc = None

    def killRemoteServer(self):
        self.diag.info("Getting ps output from " + self.displayMachine)
        self.killDiag.info("Killing remote Xvfb process on " + self.displayMachine + " with pid " + str(self.displayPid))
        self.guiSuites[0].app.runCommandOn(self.displayMachine, [ "kill", str(self.displayPid) ])
        self.terminateIfRunning(self.displayProc.pid) # only for self-tests really : traffic mechanism doesn't fake remote process

    def createDisplay(self, machine, app):
        if not self.canRunVirtualServer(machine, app):
            return None, None

        startArgs = self.getVirtualServerArgs(machine, app)
        return self.startXvfb(startArgs, machine)

    def startXvfb(self, startArgs, machine):
        for i in range(5):
            self.diag.info("Starting Xvfb using args " + repr(startArgs))
            self.displayProc = subprocess.Popen(startArgs, stdin=open(os.devnull), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            line = plugins.retryOnInterrupt(self.displayProc.stdout.readline)
            if "Time Out!" in line:
                self.displayProc.wait()
                self.displayProc.stdout.close()
                self.diag.info("Timed out waiting for Xvfb to come up")
                # We try again and hope for a better process ID!
                continue
            try:
                displayNum, pid = map(int, line.strip().split(","))
                self.displayProc.stdout.close()
                return self.getDisplayName(machine, displayNum), pid
            except ValueError: #pragma : no cover - should never happen, just a fail-safe
                plugins.log.info("Failed to parse line :\n " + line + self.displayProc.stdout.read())
                return None, None

        messages = "Failed to start Xvfb in 5 attempts, giving up"
        plugins.printWarning(messages)
        return None, None
    
    def getVirtualServerArgs(self, machine, app):
        binDir = plugins.installationDir("libexec")
        fullPath = os.path.join(binDir, "startXvfb.py")
        appTmpDir = app.getRemoteTmpDirectory()[1]
        if appTmpDir:
            logDir = os.path.join(appTmpDir, "Xvfb")
            app.ensureRemoteDirExists(machine, logDir)
            remoteXvfb = os.path.join(appTmpDir, "startXvfb.py")
            app.copyFileRemotely(fullPath, "localhost", remoteXvfb, machine)
            fullPath = remoteXvfb
            pythonArgs = [ "python", "-u" ]
        else:
            logDir = os.path.join(app.writeDirectory, "Xvfb") 
            plugins.ensureDirectoryExists(logDir)
            pythonArgs = self.findPythonArgs(machine)
            
        xvfbExtraArgs = plugins.splitcmd(app.getConfigValue("virtual_display_extra_args"))
        cmdArgs = pythonArgs + [ fullPath, logDir ] + xvfbExtraArgs
        return app.getCommandArgsOn(machine, cmdArgs)

    def findPythonArgs(self, machine):
        # In case it isn't the default, allow for a ttpython script in the installation
        if machine == "localhost":
            return [ sys.executable, "-u" ]
        
        localPointer = plugins.installationPath("bin/ttpython")
        if localPointer:
            return [ localPointer, "-u" ]
        else: # pragma : no cover -there is one in our local installation whether we like it or not...
            return [ "python", "-u" ]
        
    def getDisplayName(self, machine, displayNumber):
        # No point in using the port if we don't have to, this seems less reliable if the process is local
        # X keeps track of these numbers internally and connecting to them works rather better.
        displayStr = ":" + str(displayNumber) + ".0"
        if machine == "localhost":
            return displayStr
        else:
            # Don't include user name, if any
            return machine.split("@")[-1] + displayStr

    def canRunVirtualServer(self, machine, app):
        retcode = app.runCommandOn(machine, [ "which", "Xvfb" ], collectExitCode=True)
        return retcode == 0
