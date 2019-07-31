
"""
Utilities for both master and slave code
"""

import os
import socket
from texttestlib import plugins
from locale import getpreferredencoding

noReusePostfix = ".NO_REUSE"
rerunPostfix = ".RERUN_TEST"
sendFilePostfix = ".SEND_FILES"
getFilePostfix = ".GET_FILES"


def getIPAddress(apps):
    if useLocalQueueSystem(apps):
        return "127.0.0.1"  # always works if everything is local

    # Seems to be no good portable way to get the IP address in a portable way
    # See e.g. http://stackoverflow.com/questions/166506/finding-local-ip-addresses-using-pythons-stdlib
    # These two methods seem to be the only vaguely portable ones
    try:
        # Doesn't always work, sometimes not available
        return socket.gethostbyname(socket.gethostname())
    except socket.error:
        # Relies on being online, but seems there is no other way...
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 0))  # Google's DNS server. Should always be there :)
        return s.getsockname()[0]


def queueSystemName(app):
    return app.getConfigValue("queue_system_module")


def useLocalQueueSystem(apps):
    return all((queueSystemName(app) == "local" for app in apps))


def socketSerialise(test):
    return test.app.name + test.app.versionSuffix() + ":" + test.getRelPath()


def socketParse(testString):
    # Test name might contain ":"
    return testString.strip().split(":", 1)


def makeIdentifierLine(identifier, sendFiles=False, getFiles=False, noReuse=False, rerun=False):
    if sendFiles:
        identifier += sendFilePostfix
    if getFiles:
        identifier += getFilePostfix
    if noReuse:
        identifier += noReusePostfix
    if rerun:
        identifier += rerunPostfix
    return identifier


def parseIdentifier(line):
    rerun = line.endswith(rerunPostfix)
    if rerun:
        line = line.replace(rerunPostfix, "")

    tryReuse = not line.endswith(noReusePostfix)
    if not tryReuse:
        line = line.replace(noReusePostfix, "")

    sendFiles = line.endswith(sendFilePostfix)
    if sendFiles:
        line = line.replace(sendFilePostfix, "")

    getFiles = line.endswith(getFilePostfix)
    if getFiles:
        line = line.replace(getFilePostfix, "")

    return line, sendFiles, getFiles, tryReuse, rerun


dirText = "DIRECTORY_CONTENTS"
fileText = "FILE_CONTENTS"
endPrefix = "END_"


def directorySerialise(dirName, ignoreLinks=False):
    text = ""
    for root, _, files in os.walk(dirName):
        for fn in sorted(files):
            path = os.path.join(root, fn)
            if not os.path.islink(path):
                relpath = plugins.relpath(path, dirName)
                text += fileText + " " + relpath + "\n"
                with open(path) as f:
                    text += f.read()
                if not text.endswith("\n"):
                    text += "\n"
                text += endPrefix + fileText + "\n"
    text += endPrefix + dirText
    return text


def directoryUnserialise(rootDir, f):
    currFile = None
    for line in f:
        lineStr = str(line, getpreferredencoding())
        if currFile is not None:
            if lineStr.startswith(endPrefix + fileText):
                currFile.close()
                currFile = None
            else:
                currFile.write(lineStr)
        else:
            if lineStr.startswith(fileText):
                fn = lineStr.strip().split()[-1]
                path = os.path.join(rootDir, fn)
                plugins.ensureDirExistsForFile(path)
                currFile = open(path, "w")
            elif lineStr.startswith(endPrefix + dirText):
                break
