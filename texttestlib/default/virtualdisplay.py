#!/usr/local/bin/python

import os
import sys
import subprocess
import signal
import logging
from texttestlib import plugins

# Unlike earlier incarnations of this functionality,
# we don't rely on sharing displays but create our own for each test run.


class VirtualDisplayResponder(plugins.Responder):
    instance = None

    def __init__(self, *args):
        plugins.Responder.__init__(self, *args)
        self.displayInfoList = []
        self.guiSuites = []
        self.diag = logging.getLogger("virtual display")
        self.killDiag = logging.getLogger("kill processes")
        VirtualDisplayResponder.instance = self

    def addSuites(self, suites):
        guiSuites = [suite for suite in suites if suite.getConfigValue("use_case_record_mode") == "GUI"]
        if len(self.displayInfoList) == 0:
            self.setUpVirtualDisplay(guiSuites)
            for var, value in self.getVariablesToSet():
                plugins.log.info("Tests will run with " + var + " variable set to " + value)

    def getVariablesToSet(self):
        vars = []
        for i, (_, displayName, _, _, _, _) in enumerate(self.displayInfoList):
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
                self.displayInfoList.append(displayInfo)
                self.guiSuites = guiSuites
            elif len(machines) > 0:
                plugins.printWarning("Failed to start virtual display on " +
                                     ",".join(machines) + " - using real display.")

    def getDisplayInfo(self, machines, app):
        for machine in machines:
            displayName, xvfbPid, xvfbOrSshProc, wmPid, wmOrSshProc = self.createDisplay(machine, app)
            if displayName:
                return machine, displayName, xvfbPid, xvfbOrSshProc, wmPid, wmOrSshProc
            else:
                plugins.printWarning("Virtual display program Xvfb not available on " + machine, stdout=True)

    def findMachines(self, suites):
        allMachines = []
        for suite in suites:
            for machine in suite.getConfigValue("virtual_display_machine"):
                if machine == "localhost":  # Local to the test run, not to where we're trying to run...
                    machine = suite.app.getRunMachine()
                if not machine in allMachines:
                    allMachines.append(machine)
        return allMachines

    def notifyTestProcessComplete(self, test):
        if self.restartXvfbAndWm():
            plugins.log.info("Virtual display had terminated unexpectedly with some test processes still to run.")
            for var, value in self.getVariablesToSet():
                plugins.log.info("Reset " + var + " variable to " + value + " for test " + repr(test))
                test.setEnvironment(var, value)

    def notifyComplete(self, *args):
        if self.restartXvfbAndWm():
            plugins.log.info("Virtual display had terminated unexpectedly.")
            for var, value in self.getVariablesToSet():
                plugins.log.info("Reset " + var + " variable to " + value + ".")

    def restartXvfbAndWm(self):
        # Whenever a test completes, we check to see if the virtual server is still going
        changed = False
        for i, displayInfo in enumerate(self.displayInfoList):
            xvfbOrSshProc = displayInfo[3]
            if xvfbOrSshProc is not None and xvfbOrSshProc.poll() is not None:
                xvfbOrSshProc.wait()  # Don't leave zombie processes around
                # If Xvfb has terminated, we need to restart it
                newDisplayInfo = self.getDisplayInfo(self.findMachines(self.guiSuites), self.guiSuites[0].app)
                if newDisplayInfo:
                    self.displayInfoList[i] = newDisplayInfo
                    changed = True
        return changed

    def notifyAllComplete(self):
        self.cleanXvfbAndWm()

    def terminateIfRunning(self, pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:  # pragma: no cover - only set up this way to avoid race conditions. Should never happen in real life anyway
            pass

    def cleanXvfbAndWm(self):
        if len(self.displayInfoList) and os.name == "posix":
            wmExecutable = self.guiSuites[0].app.getConfigValue("virtual_display_wm_executable")
            for displayInfo in self.displayInfoList:
                machine, _, xvfbPid, xvfbOrSshProc, wmPid, wmOrSshProc = displayInfo
                if wmExecutable:
                    self.killProcess("window manager", machine, wmPid, wmOrSshProc)
                self.killProcess("Xvfb", machine, xvfbPid, xvfbOrSshProc)
            self.displayInfoList = []

    def killProcess(self, procName, machine, pid, localProc):
        if machine == "localhost":
            self.killDiag.info("Killing " + procName + " process " + str(pid))
            self.terminateIfRunning(pid)
        else:
            self.killDiag.info("Killing remote " + procName + " process on " + machine + " with pid " + str(pid))
            self.guiSuites[0].app.runCommandOn(machine, ["kill", str(pid)])
            # only for self-tests really : traffic mechanism doesn't fake remote process
            self.terminateIfRunning(localProc.pid)
        localProc.wait()  # don't leave zombies around

    def createDisplay(self, machine, app):
        if not self.executableExists(machine, app, "Xvfb"):
            return None, None, None, None, None
        wmExecutable = app.getConfigValue("virtual_display_wm_executable")
        if wmExecutable and not self.executableExists(machine, app, wmExecutable):
            return None, None, None, None, None

        extraArgs = plugins.splitcmd(app.getConfigValue("virtual_display_extra_args"))
        xvfbCmd = self.getRemoteCmd(machine, app, "startXvfb.py", extraArgs)
        displayName, xvfbPid, xvfbOrSshProc = self.startXvfb(xvfbCmd, machine)

        wmPid, wmOrSshProc = None, None
        if wmExecutable:
            extraArgs = [wmExecutable, displayName]
            wmArgs = self.getRemoteCmd(machine, app, "startWindowManager.py", extraArgs)
            wmPid, wmOrSshProc = self.startWindowManager(wmArgs, machine)
        return displayName, xvfbPid, xvfbOrSshProc, wmPid, wmOrSshProc

    def ignoreSignals(self):
        for signum in [signal.SIGUSR1, signal.SIGUSR2, signal.SIGXCPU]:
            signal.signal(signum, signal.SIG_IGN)

    def startXvfb(self, command, machine):
        for _ in range(5):
            self.diag.info("Starting Xvfb using args " + repr(command))
            # Ignore job control signals for remote processes
            # Otherwise the ssh process gets killed, but the stuff it's started remotely doesn't, and we leak Xvfb processes
            preexec_fn = None if machine == "localhost" else self.ignoreSignals
            xvfbOrSshProc = subprocess.Popen(command, preexec_fn=preexec_fn, stdin=open(
                os.devnull), stdout=subprocess.PIPE, stderr=open(os.devnull, "w"), universal_newlines=True)
            line = plugins.retryOnInterrupt(xvfbOrSshProc.stdout.readline)
            if "Time Out!" in line:
                xvfbOrSshProc.wait()
                xvfbOrSshProc.stdout.close()
                self.diag.info("Timed out waiting for Xvfb to come up")
                # We try again and hope for a better process ID!
                continue
            try:
                displayNum, xvfbPid = list(map(int, line.strip().split(",")))
                xvfbOrSshProc.stdout.close()
                return self.getDisplayName(machine, displayNum), xvfbPid, xvfbOrSshProc
            except ValueError:  # pragma : no cover - should never happen, just a fail-safe
                sys.stderr.write("ERROR: Failed to parse startXvfb.py line :\n " + line + "\n")
                xvfbOrSshProc.stdout.close()
                return None, None, None

        messages = "Failed to start Xvfb in 5 attempts, giving up"
        plugins.printWarning(messages)
        return None, None, None

    def getPersonalLogDir(self):
        if not self.diag.isEnabledFor(logging.INFO):
            return os.devnull

        return os.getenv("TEXTTEST_PERSONAL_LOG", os.devnull)

    def getRemoteCmd(self, machine, app, pythonScript, extraArgs):
        binDir = plugins.installationDir("libexec")
        localPath = os.path.join(binDir, pythonScript)
        appTmpDir = app.getRemoteTmpDirectory()[1]
        if appTmpDir:
            logDir = os.path.join(appTmpDir, "Xvfb")
            app.ensureRemoteDirExists(machine, logDir)
            remotePath = os.path.join(appTmpDir, pythonScript)
            app.copyFileRemotely(localPath, "localhost", remotePath, machine)
            fullPath = remotePath
            pythonArgs = ["python", "-u"]
        else:
            logDir = self.getPersonalLogDir()
            fullPath = localPath
            pythonArgs = self.findPythonArgs(machine)

        cmdArgs = pythonArgs + [fullPath, logDir] + extraArgs
        return app.getCommandArgsOn(machine, cmdArgs)

    def findPythonArgs(self, machine):
        # In case it isn't the default, allow for a ttpython script in the installation
        if machine == "localhost":
            return [sys.executable, "-u"]

        localPointer = plugins.installationPath("bin/ttpython")
        if localPointer:
            return [localPointer, "-u"]
        else:  # pragma : no cover -there is one in our local installation whether we like it or not...
            return ["python", "-u"]

    def getDisplayName(self, machine, displayNumber):
        # No point in using the port if we don't have to, this seems less reliable if the process is local
        # X keeps track of these numbers internally and connecting to them works rather better.
        displayStr = ":" + str(displayNumber) + ".0"
        if machine == "localhost":
            return displayStr
        else:
            # Don't include user name, if any
            return machine.split("@")[-1] + displayStr

    def startWindowManager(self, command, machine):
        self.diag.info("Starting window manager")
        preexec_fn = None if machine == "localhost" else self.ignoreSignals
        wmProc = subprocess.Popen(command, preexec_fn=preexec_fn, stdin=open(
            os.devnull), stdout=subprocess.PIPE, stderr=open(os.devnull, "w"))
        line = plugins.retryOnInterrupt(wmProc.stdout.readline)
        try:
            wmPid = int(line.strip())
            wmProc.stdout.close()
        except ValueError:
            sys.stderr.write("ERROR: Failed to start window manager")
            wmProc.stdout.close()
            return None, None
        return wmPid, wmProc

    def executableExists(self, machine, app, executable):
        retcode = app.runCommandOn(machine, ["which", executable], collectExitCode=True)
        return retcode == 0
