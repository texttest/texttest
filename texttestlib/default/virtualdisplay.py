#!/usr/local/bin/python

import os, sys, subprocess, signal, logging
from texttestlib import plugins
        
# Unlike earlier incarnations of this functionality,
# we don't rely on sharing displays but create our own for each test run.
class VirtualDisplayResponder(plugins.Responder):
    instance = None
    def __init__(self, *args):
        plugins.Responder.__init__(self, *args)
        self.displayInfo = []
        self.guiSuites = []
        self.diag = logging.getLogger("virtual display")
        self.killDiag = logging.getLogger("kill processes")
        VirtualDisplayResponder.instance = self
        
    def addSuites(self, suites):
        guiSuites = filter(lambda suite : suite.getConfigValue("use_case_record_mode") == "GUI", suites)
        if len(self.displayInfo) == 0:
            self.setUpVirtualDisplay(guiSuites)
            for var, value in self.getVariablesToSet():
                plugins.log.info("Tests will run with " + var + " variable set to " + value)
                
    def getVariablesToSet(self):
        vars = []
        for i, (_, displayName, _, _) in enumerate(self.displayInfo):
            suffix = "" if i == 0 else str(i + 1)
            vars.append(("DISPLAY" + suffix, displayName))
        return vars
                 
    def setUpVirtualDisplay(self, guiSuites):
        if len(guiSuites) == 0:
            return
        machines = self.findMachines(guiSuites)
        displayCount = max((suite.getConfigValue("virtual_display_count") for suite in guiSuites))
        for _ in range(displayCount):
            displayInfo = self.getDisplayInfo(machines, guiSuites[0].app)
            if displayInfo:
                self.displayInfo.append(displayInfo)
                self.guiSuites = guiSuites
            elif len(machines) > 0:
                plugins.printWarning("Failed to start virtual display on " + ",".join(machines) + " - using real display.")

    def getDisplayInfo(self, machines, app):
        for machine in machines:
            displayName, pid, proc = self.createDisplay(machine, app)
            if displayName:
                return machine, displayName, pid, proc
            else:
                plugins.printWarning("Virtual display program Xvfb not available on " + machine, stdout=True)
    
    def findMachines(self, suites):
        allMachines = []
        for suite in suites:
            for machine in suite.getConfigValue("virtual_display_machine"):
                if machine == "localhost": # Local to the test run, not to where we're trying to run...
                    machine = suite.app.getRunMachine()
                if not machine in allMachines:
                    allMachines.append(machine)
        return allMachines

    def notifyTestProcessComplete(self, test):
        if self.restartXvfb():
            plugins.log.info("Virtual display had terminated unexpectedly with some test processes still to run.")
            for var, value in self.getVariablesToSet():
                plugins.log.info("Reset " + var + " variable to " + value + " for test " + repr(test))
                test.setEnvironment(var, value)
        
    def notifyComplete(self, *args):
        if self.restartXvfb():
            plugins.log.info("Virtual display had terminated unexpectedly.")
            for var, value in self.getVariablesToSet():
                plugins.log.info("Reset " + var + " variable to " + value + ".")
        
    def restartXvfb(self):
        # Whenever a test completes, we check to see if the virtual server is still going
        changed = False
        for i, displayInfo in enumerate(self.displayInfo):
            displayProc = displayInfo[-1]
            if displayProc is not None and displayProc.poll() is not None:
                displayProc.wait() # Don't leave zombie processes around
                # If Xvfb has terminated, we need to restart it
                newDisplayInfo = self.getDisplayInfo(self.findMachines(self.guiSuites), self.guiSuites[0].app)
                if newDisplayInfo:
                    self.displayInfo[i] = newDisplayInfo
                    changed = True
        return changed
            
    def notifyAllComplete(self):
        self.cleanXvfb()

    def terminateIfRunning(self, pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError: # pragma: no cover - only set up this way to avoid race conditions. Should never happen in real life anyway
            pass
    
    def cleanXvfb(self):
        if len(self.displayInfo) and os.name == "posix":
            for displayInfo in self.displayInfo:
                machine, _, pid, proc = displayInfo
                if machine == "localhost":
                    self.killDiag.info("Killing Xvfb process " + str(pid))
                    self.terminateIfRunning(pid)
                else:
                    self.killRemoteServer(machine, pid, proc)
                proc.wait() # don't leave zombies around
            self.displayInfo = []

    def killRemoteServer(self, machine, pid, proc):
        self.diag.info("Getting ps output from " + machine)
        self.killDiag.info("Killing remote Xvfb process on " + machine + " with pid " + str(pid))
        self.guiSuites[0].app.runCommandOn(machine, [ "kill", str(pid) ])
        self.terminateIfRunning(proc.pid) # only for self-tests really : traffic mechanism doesn't fake remote process

    def createDisplay(self, machine, app):
        if not self.canRunVirtualServer(machine, app):
            return None, None, None

        startArgs = self.getVirtualServerArgs(machine, app)
        return self.startXvfb(startArgs, machine)

    def ignoreSignals(self):
        for signum in [ signal.SIGUSR1, signal.SIGUSR2, signal.SIGXCPU ]:
            signal.signal(signum, signal.SIG_IGN)

    def startXvfb(self, startArgs, machine):
        for _ in range(5):
            self.diag.info("Starting Xvfb using args " + repr(startArgs))
            # Ignore job control signals for remote processes
            # Otherwise the ssh process gets killed, but the stuff it's started remotely doesn't, and we leak Xvfb processes
            preexec_fn = None if machine == "localhost" else self.ignoreSignals
            displayProc = subprocess.Popen(startArgs, preexec_fn=preexec_fn, stdin=open(os.devnull), stdout=subprocess.PIPE, stderr=open(os.devnull, "w"))
            line = plugins.retryOnInterrupt(displayProc.stdout.readline)
            if "Time Out!" in line:
                displayProc.wait()
                displayProc.stdout.close()
                self.diag.info("Timed out waiting for Xvfb to come up")
                # We try again and hope for a better process ID!
                continue
            try:
                displayNum, pid = map(int, line.strip().split(","))
                displayProc.stdout.close()
                return self.getDisplayName(machine, displayNum), pid, displayProc
            except ValueError: #pragma : no cover - should never happen, just a fail-safe
                sys.stderr.write("ERROR: Failed to parse startXvfb.py line :\n " + line + "\n")
                displayProc.stdout.close()
                return None, None, None

        messages = "Failed to start Xvfb in 5 attempts, giving up"
        plugins.printWarning(messages)
        return None, None, None

    def getXvfbLogDir(self):
        if not self.diag.isEnabledFor(logging.INFO):
            return os.devnull
        
        return os.getenv("TEXTTEST_PERSONAL_LOG", os.devnull)
    
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
            logDir = self.getXvfbLogDir()
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
