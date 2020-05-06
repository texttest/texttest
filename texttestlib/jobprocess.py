# Module to find all the child processes of a random process and kill them all (using psutil)

import signal
import os
import psutil


def killProcessAndChildren(pid, sig=None, timeout=5):
    assert pid != os.getpid(), "won't kill myself"
    parent = psutil.Process(pid)
    children = parent.children(recursive=True) + [parent]
    for p in children:
        p.send_signal(signal.SIGTERM if sig is None else sig)
    _, alive = psutil.wait_procs(children, timeout=timeout)
    if sig is None:
        for p in alive:
            p.kill()
