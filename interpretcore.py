#!/usr/bin/env python

import os, sys, string

def interpretCore(corefile):
    if os.path.getsize(corefile) == 0:
        details = "Core file of zero size written - Stack trace not produced for crash\nCheck your coredumpsize limit"
        return "Empty core file", details
    
    binary = getBinary(corefile)
    if not os.path.isfile(binary):
        details = "Could not find binary name '" + binary + "' from core file : Stack trace not produced for crash"
        return "No binary found from core", details

    return writeStackTrace(corefile, binary)

def getLocalName(corefile):
    data = os.popen("file " + corefile).readline()
    parts = data.split("'")
    if len(parts) == 3:
        return parts[1]
    else:
        newParts = data.split()
        if len(newParts) > 2 and newParts[-2].endswith(","):
            # AIX...
            return newParts[-1]
        else:
            return ""

def getLastFileName(corefile):
    # Yes, we know this is horrible. Does anyone know a better way of getting the binary out of a core file???
    # Unfortunately running gdb is not the answer, because it truncates the data...
    localName = getLocalName(corefile)
    possibleNames = os.popen("strings " + corefile + " | grep '^/.*/" + localName + "'").readlines()
    possibleNames.reverse()
    for name in possibleNames:
        name = name.strip()
        if os.path.isfile(name):
            return name
    # If none of them exist, return the first one anyway for error printout
    if len(possibleNames) > 0:
        return possibleNames[0].strip()
    else:
        return ""
    
def getBinary(corefile):
    binary = getLastFileName(corefile)
    if os.path.isfile(binary):
        return binary
    dirname, local = os.path.split(binary)
    parts = local.split(".")
    # pick up temporary binaries (Carmen-hack...)
    if len(parts) > 2 and len(parts[0]) == 0 and parts[-2] == os.getenv("USER"):
        return os.path.join(dirname, string.join(parts[1:-2], "."))
    else:
        return binary

def writeCmdFile():
    fileName = "coreCommands.gdb"
    file = open(fileName, "w")
    file.write("bt\n")
    file.close()
    return fileName

def findCoreInfo(stdout):
    summaryLine = ""
    stackLines = []
    for line in stdout.readlines():
        if line.find("Program terminated") != -1:
            summaryLine = line.strip()
        if line[0] == "#" and line != prevLine:
            startPos = line.find("in ") + 3
            endPos = line.rfind("(")
            methodName = line[startPos:endPos]
            pointerPos = methodName.find("+0")
            if pointerPos != -1:
                methodName = methodName[:pointerPos]
            stackLines.append(methodName)
        prevLine = line
    return summaryLine, stackLines    

def writeStackTrace(corefile, binary):
    fileName = writeCmdFile()
    gdbCommand = "gdb -q -batch -x " + fileName + " " + binary + " " + corefile
    foundStack = False
    prevLine = ""
    printedStackLines = 0
    stdin, stdout, stderr = os.popen3(gdbCommand)
    summaryLine, stackLines = findCoreInfo(stdout)
    os.remove(fileName)
    if not summaryLine:
        errMsg = stderr.read()
        summary = "Parse failure on GDB output"
        if len(errMsg) > 50000:
            return summary, "Over 50000 error characters printed - suspecting binary output"
        else:
            return summary, "GDB backtrace command failed : Stack trace not produced for crash\nErrors from GDB:\n" + errMsg

    summary = summaryLine.split(",")[-1].strip().replace(".", "")
    if len(stackLines) > 1:
        summary += " in " + stackLines[0].strip()
    details = summaryLine + "\nStack trace from gdb :\n" + \
              string.join(stackLines[:100], "\n")
    # Sometimes you get enormous stacktraces from GDB, for example, if you have
    # an infinite recursive loop.
    if len(stackLines) > 100:
        details += "\nStack trace print-out aborted after 100 function calls"
    return summary, details
    
if len(sys.argv) != 2:
    print "Usage: interpretcore.py <corefile>"
else:
    corefile = sys.argv[1]
    compression = corefile.endswith(".Z")
    if compression:
        os.system("uncompress " + corefile)
        corefile = corefile[:-2]
    summary, details = interpretCore(corefile)
    print summary
    print "-" * len(summary)
    print details
    if compression:
        os.system("compress " + corefile)
