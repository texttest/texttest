#!/usr/bin/env python

import sys, os, string, socket

def readFromSocket(sock):
    response = ""
    while not response.endswith("TT_END_CMD_RESPONSE"):
        response += sock.recv(1024)
    return response[:-19]

if __name__ == "__main__":
    servAddr = os.getenv("TEXTTEST_MIM_SERVER")
    host, port = servAddr.split(":")
    serverAddress = (host, int(port))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(serverAddress)
    text = "SUT_COMMAND_LINE:" + repr(sys.argv) + os.linesep
    sys.stdout.flush()
    sock.sendall(text)
    response = readFromSocket(sock)
    sock.close()
    errParts = response.split("->ERR:")
    outParts = errParts[0].split("->OUT:")
    sys.stdout.write(string.join(outParts[1:], ""))
    sys.stderr.write(string.join(errParts[1:], ""))    
