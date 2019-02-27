
# Module which more or less handles a group of processes as a job:

# - find all the child processes of a random process (on UNIX via ps, on Windows there aren't any)
# - kill them all (hack for lack of os.kill on Windows)
# - pretty print names for them (on UNIX) based on whatever ps says

# We try to make the JobProcess class look as much like subprocess.Popen objects as possible
# so we can if necessary treat them interchangeably.

import signal
import os
import time
import subprocess
import select
import shlex


class WrongOSException(RuntimeError):
    pass


class JobProcess:
    def __init__(self, pid):
        if os.name == "nt":
            raise WrongOSException("JobProcess doesn't work on Windows")
        self.pid = pid
        self.name = None

    def __repr__(self):
        return self.getName()

    def findAllProcesses(self):
        return [self] + self.findChildProcesses()

    def findChildProcesses(self):
        ids = self.findChildProcessIDs(self.pid)
        return [JobProcess(id) for id in ids]

    def getName(self):
        if self.name is None:
            self.name = self.findProcessName()
        return self.name

    def killAll(self, killSignal=None):
        processes = self.findAllProcesses()
        # If intent is to kill everything (signal not specified) start with the deepest child process...
        # otherwise notify the process itself first
        if not killSignal:
            processes.reverse()
        killedSomething = False
        for proc in processes:
            killedSomething |= proc.kill(killSignal)
        return killedSomething

    def kill(self, killSignal):
        if killSignal:
            return self._kill(killSignal)
        if self.tryKillAndWait(signal.SIGINT):
            return True
        if self.tryKillAndWait(signal.SIGTERM):
            return True
        return self.tryKillAndWait(signal.SIGKILL)

    def _kill(self, killSignal):
        try:
            os.kill(self.pid, killSignal)
            return True
        except OSError:
            return False

    def tryKillAndWait(self, killSignal):
        if self._kill(killSignal):
            for i in range(20):
                time.sleep(0.1)
                if self.poll() is not None:
                    return True
        return False

    def findProcessName(self):
        pslines = self.getPsLines(["-l", "-p", str(self.pid)])
        if len(pslines) > 1:
            return pslines[-1].split()[-1]
        else:
            return ""  # process couldn't be found

    def findChildProcessIDs(self, pid):
        outLines = self.getPsLines(["-efl"])
        return self.findChildProcessesInLines(pid, outLines)

    def findChildProcessesInLines(self, pid, outLines):
        processes = []
        for line in outLines:
            entries = line.split()
            if len(entries) > 4 and entries[4] == str(pid):
                childPid = int(entries[3])
                processes.append(childPid)
                processes += self.findChildProcessesInLines(childPid, outLines)
        return processes

    def getPsLines(self, psArgs):
        try:
            proc = subprocess.Popen(["ps"] + psArgs, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, stdin=open(os.devnull))
            return proc.communicate()[0].splitlines()
        except (IOError, OSError) as detail:
            if "Interrupted system call" in str(detail):
                return self.getPsLines(psArgs)
            else:
                raise

    def poll(self):
        try:
            lines = self.getPsLines(["-p", str(self.pid)])
            if len(lines) < 2 or lines[-1].strip().endswith(b"<defunct>"):
                return "returncode"  # should return return code but can't be bothered, don't use it currently
        except (OSError, select.error) as detail:
            if str(detail).find("Interrupted system call") != -1:
                return self.poll()
            else:
                raise


def runCmd(cmdArgs):
    try:
        return subprocess.call(cmdArgs, stdout=open(os.devnull, "w"), stderr=subprocess.STDOUT) == 0
    except OSError:
        return False


def killArbitaryProcess(pid, sig=None):
    if os.name == "posix":
        return JobProcess(pid).killAll(sig)
    else:
        pidStr = str(pid)
        # Every new Windows version produces a new way of killing processes...
        if runCmd(["tskill", pidStr]):  # Windows XP
            return True
        elif runCmd(["taskkill", "/F", "/PID", pidStr]):  # Windows Vista
            return True
        elif runCmd(["pskill", pidStr]):  # Windows 2000
            return True
        else:
            print("WARNING - none of taskkill (Vista), tskill (XP) nor pskill (2000) found, not able to kill processes")
            return False


def killSubProcessAndChildren(process, sig=None, cmd=None):
    if not cmd or not runCmd(shlex.split(cmd) + [str(process.pid)]):
        if os.name == "posix":
            killArbitaryProcess(process.pid, sig)
        else:
            import ctypes
            ctypes.windll.kernel32.TerminateProcess(int(process._handle), -1)
