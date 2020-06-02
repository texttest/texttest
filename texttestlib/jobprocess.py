# Module to find all the child processes of a random process and kill them all (using psutil)

import signal
import os
import subprocess
import psutil


def killProcessAndChildren(pid, sig=None, cmd=None, timeout=5):
    assert pid != os.getpid(), "won't kill myself"
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return False
    children = parent.children(recursive=True) + [parent]
    for p in children:
        try:
            p.send_signal(signal.SIGTERM if sig is None else sig)
        except psutil.NoSuchProcess:
            pass # if it's terminated by itself already, so much the better
    _, alive = psutil.wait_procs(children, timeout=timeout)
    if sig is None:
        for p in alive:
            if os.name == "posix":
                p.send_signal(signal.SIGKILL)
            else:
                if cmd is None:
                    cmd = "taskkill /F /PID"
                cmd += " " + str(pid)
                try:
                    subprocess.call(cmd, stdout=open(os.devnull, "w"), stderr=subprocess.STDOUT)
                except OSError:
                    pass
    return True
