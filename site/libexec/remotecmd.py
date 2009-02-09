#!/usr/bin/env /usr/local/share/texttest/site/bin/ttpython

# Basic program to run a command line, and notify a remote server when it starts and ends, along
# with its result

# remotecmd.py <name> <server address> <cmdargs>

# <name> is an identifier by which the server will recognise this command
# <cmdargs> is a list of command arguments, in Python list format to avoid quoting trouble

# starting is notified via 
# remotecmd.py:<name>:start

# Results are sent back in the form
# remotecmd.py:<name>:exitcode=<exitcode>
# <stdout>|STD_ERR|<stderr>

import sys, subprocess, socket

def getServerAddress():
    host, port = sys.argv[2].split(":")
    return host, int(port)

def _sendData(serverAddress, toSend):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(serverAddress)
    sock.sendall(toSend)
    sock.close()

def sendData(*args):
    # allow for flaky networks, try five times before giving up
    for attempt in range(5):
        try:
            _sendData(*args)
            return
        except socket.error:
            from time import sleep
            sleep(1)
    raise

def runAndSend(serverAddress, prefix, cmdArgs, **kwargs):
    proc = subprocess.Popen(cmdArgs, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    stdout, stderr = proc.communicate() 
    sendData(serverAddress, prefix + "exitcode=" + str(proc.returncode) + "\n" + stdout + "|STD_ERR|" + stderr)

name = sys.argv[1]
serverAddress = getServerAddress()
cmdArgs = sys.argv[3:]
prefix = "remotecmd.py:" + name + ":"
sendData(serverAddress, prefix + "start\n")
try:
    runAndSend(serverAddress, prefix, cmdArgs)
except OSError:
    runAndSend(serverAddress, prefix, cmdArgs, shell=True) # to pick up the shell's return code and exit code
