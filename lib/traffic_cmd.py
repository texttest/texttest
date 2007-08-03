#!/usr/bin/env python

import sys, os, socket

def createSocket():
    servAddr = os.getenv("TEXTTEST_MIM_SERVER")
    if servAddr:
        host, port = servAddr.split(":")
        serverAddress = (host, int(port))
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(serverAddress)
        return sock

def sendServerState(stateDesc):
    sock = createSocket()
    if sock:
        sock.sendall("SUT_SERVER:" + stateDesc + "\n")
        sock.close()

if __name__ == "__main__":
    sock = createSocket()
    text = "SUT_COMMAND_LINE:" + repr(sys.argv) + ":SUT_SEP:" + repr(os.environ) + ":SUT_SEP:" + os.getcwd()
    sock.sendall(text)
    sock.shutdown(1)
    response = sock.makefile().read()
    sock.close()
    try:
        stdout, stderr, exitStr = response.split("|TT_CMD_SEP|")
        sys.stdout.write(stdout)
        sys.stdout.flush()
        sys.stderr.write(stderr)
        sys.stderr.flush()
        sys.exit(int(exitStr))
    except ValueError:
        sys.stderr.write("Received unexpected communication from MIM server:\n " + response + "\n\n")

