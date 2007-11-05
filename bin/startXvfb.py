#!/usr/bin/env python

# Wrapper for Xvfb. Works on UNIX only. Main points are as follows :
# - Provide a unique display ID by using our own process ID
# - Get Xvfb to ignore job control signals properly 
# - Handle Xvfb's weird mechanism whereby it sends SIGUSR1 to its parent process
#   every time a process disconnects. If the parent process is TextTest there is no
#   way to tell these signals from ordinary job control
# - Clean up after Xvfb as it leaks lock files from time to time.

import os, signal, sys, subprocess
from socket import gethostname

MAX_DISPLAY = 32768
Xvfb_ready = False

class ConnectionComplete:
    pass

class ConnectionTimeout:
    pass
    
def setReadyFlag(self, *args):
    global Xvfb_ready
    Xvfb_ready = True

def connectionComplete(self, *args):
    raise ConnectionComplete()

def connectionFailed(self, *args):
    raise ConnectionTimeout()

def ignoreSignals():
    for signum in [ signal.SIGUSR1, signal.SIGUSR2, signal.SIGXCPU ]:
        signal.signal(signum, signal.SIG_IGN)

def getDisplayNumber():
    # We use the device of making the display number match our process ID (mod 32768)!
    # And we hope that works :) Should prevent clashes with others using the same strategy anyway
    # Display numbers up to 32768 seem to be allowed, which is less than most process IDs on systems I've observed...
    return str(os.getpid() % MAX_DISPLAY)

def getLockFiles(self, num):
    lockFile = "/tmp/.X" + num + "-lock"
    xFile = "/tmp/.X11-unix/X" + num
    return [ lockFile, xFile ]

def cleanLeakedLockFiles(displayNum):
    # Xvfb sometimes leaves lock files lying around, clean up
    for lockFile in getLockFiles(displayNum):
        if os.path.isfile(lockFile):
            try:
                os.remove(lockFile)
            except:
                pass

def runXvfb(logDir):
    ignoreSignals()
    signal.signal(signal.SIGUSR1, setReadyFlag)
    displayNum = getDisplayNumber()
    logFile = os.path.join(logDir, "Xvfb." + gethostname() + "." + displayNum)
    startArgs = [ "Xvfb", "-ac", "-audit", "2", ":" + displayNum ]
    proc = subprocess.Popen(startArgs, preexec_fn=ignoreSignals,
                            stdout=open(logFile, "w"), stderr=subprocess.STDOUT, stdin=open(os.devnull))
    try:
        signal.signal(signal.SIGUSR1, connectionComplete)
        signal.signal(signal.SIGALRM, connectionFailed)
        if not Xvfb_ready:
            signal.alarm(int(os.getenv("TEXTTEST_XVFB_WAIT", 30)))
            signal.pause() # Wait until we know Xvfb is ready to be connected to before proceeding, or we time out
    except ConnectionTimeout:
        # Just kill it and try again. This should only happen very rarely and it will probably work next time round...
        os.kill(proc.pid, signal.SIGTERM)
        return runXvfb(logDir)
    except ConnectionComplete:
        pass

    ignoreSignals()
    sys.stdout.write(displayNum + "," + str(proc.pid) + "\n")
    sys.stdout.flush()
    proc.wait()
    cleanLeakedLockFiles(displayNum)


if __name__ == "__main__":
    runXvfb(sys.argv[1])
