#!/usr/bin/env python

import os
import sys
import subprocess
from socket import gethostname


def runWindowManager(logDir, wmExecutable, displayName, extraArgs):
    if not (logDir and wmExecutable and displayName):
        sys.stdout.write("Cannot find required arguments for logging directory, X display name and WM executable.")
        return 1
    command = [wmExecutable] + extraArgs
    logFileName = os.path.basename(os.path.normpath(wmExecutable)) + "." + \
        displayName.lstrip(":") + "." + gethostname().split(".")[0] + ".diag"
    logFilePath = os.path.join(logDir, logFileName) if logDir != os.devnull else os.devnull

    subEnv = dict(os.environ, DISPLAY=displayName)
    proc = subprocess.Popen(command, env=subEnv, stdout=open(logFilePath, "w"),
                            stderr=subprocess.STDOUT, stdin=open(os.devnull))
    sys.stdout.write(str(proc.pid) + "\n")
    sys.stdout.flush()
    return proc.wait()


if __name__ == "__main__":
    runWindowManager(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
