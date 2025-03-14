#!/usr/bin/env python3

import os, sys, subprocess, shutil
from tempfile import mktemp
from locale import getpreferredencoding

def interpretCore(corefile):
    if os.path.getsize(corefile) == 0:
        details = "Core file of zero size written - Stack trace not produced for crash\nCheck your coredumpsize limit"
        return "Empty core file", details, None
    
    binary = getBinary(corefile)
    if not os.path.isfile(binary):
        details = "Could not find binary name '" + binary + "' from core file : Stack trace not produced for crash"
        return "No binary found from core", details, None

    summary, details = writeGdbStackTrace(corefile, binary)
    if "Parse failure" in summary:
        try:
            if shutil.which("dbx") is None:
                return "Parse failure in GDB: DBX not installed", details, binary

            dbxSummary, dbxDetails = writeDbxStackTrace(corefile, binary)
            if "Parse failure" in dbxSummary:
                return "Parse failure from both GDB and DBX", details + dbxDetails, binary
            else:
                return dbxSummary, dbxDetails, binary
        except OSError:
            pass # If DBX isn't installed, just return the GDB details anyway
    return summary, details, binary

def getLocalName(corefile):
    data = os.popen("file " + corefile).readline()
    parts = data.split("'")
    if len(parts) == 3:
        return parts[1].split()[0] # don't pass arguments along, only want program name
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
    if os.path.isfile(localName):
        return localName

    localRegexp = localName 
    if not os.path.isabs(localName):
        localRegexp = "/.*/" + localName

    possibleNames = os.popen("strings " + corefile + " | grep '^" + localRegexp + "'").readlines()
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
    # pick up temporary binaries (Jeppesen-hack, should not be here...)
    if len(parts) > 2 and len(parts[0]) == 0:
        user = os.getenv("USER")
        try:
            pos = parts.index(user)
            return os.path.join(dirname, ".".join(parts[1:pos]))
        except ValueError:
            pass
    return binary

def writeCmdFile():
    fileName = mktemp("coreCommands.gdb")
    file = open(fileName, "w")
    file.write("thread apply all backtrace\n")
    file.close()
    return fileName

def parseGdbOutput(output):
    summaryLine = ""
    signalDesc = ""
    stackLines = []
    prevLine = ""
    stackStarted = False
    for line in output.splitlines():
        if line.find("Program terminated") != -1:
            summaryLine = line.strip()
            signalDesc = summaryLine.split(",")[-1].strip().replace(".", "")
        if line.startswith("#"):
            stackStarted = True
        if stackStarted and line != prevLine:
            methodName = line.rstrip()
            startPos = methodName.find("in ")
            if startPos != -1:
                methodName = methodName[startPos + 3:]
                stackLines.append(methodName)
            else:
                stackLines.append(methodName)
        prevLine = line
        
    if len(stackLines) > 1:
        signalDesc += " in " + getGdbMethodName(stackLines[0])

    return signalDesc, summaryLine, stackLines    

def parseDbxOutput(output):
    summaryLine = ""
    signalDesc = ""
    stackLines = []
    prevLine = ""
    for line in output.splitlines():
        stripLine = line.strip()
        if line.find("program terminated") != -1:
            summaryLine = stripLine
            signalDesc = summaryLine.split("(")[-1].replace(")", "")
        if (stripLine.startswith("[") or stripLine.startswith("=>[")) and line != prevLine:
            startPos = line.find("]") + 2
            endPos = line.rfind("(")
            methodName = line[startPos:endPos]
            stackLines.append(methodName)
        prevLine = line

    if len(stackLines) > 1:
        signalDesc += " in " + stackLines[0].strip()
        
    return signalDesc, summaryLine, stackLines    

def getGdbMethodName(line):
    endPos = line.rfind("(")
    methodName = line[:endPos]
    pointerPos = methodName.find("+0")
    if pointerPos != -1:
        methodName = methodName[:pointerPos]
    return methodName.strip()

def parseFailure(errMsg, debugger):
    summary = "Parse failure on " + debugger + " output"
    if len(errMsg) > 50000:
        return summary, "Over 50000 error characters printed - suspecting binary output"
    else:
        return summary, debugger + " backtrace command failed : Stack trace not produced for crash\nErrors from " + debugger + ":\n" + str(errMsg, getpreferredencoding())


def assembleInfo(signalDesc, summaryLine, stackLines, debugger):
    summary = signalDesc
    details = summaryLine + "\nStack trace from " + debugger + " :\n" + \
              "\n".join(stackLines[:1000])
    # Sometimes you get enormous stacktraces from GDB, for example, if you have
    # an infinite recursive loop.
    if len(stackLines) > 1000:
        details += "\nStack trace print-out aborted after 1000 function calls"
    return summary, details


def writeGdbStackTrace(corefile, binary):
    fileName = writeCmdFile()
    cmdArgs = [ "gdb", "-q", "-batch", "-x", fileName, binary, corefile ]
    proc = subprocess.Popen(cmdArgs, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, errors = proc.communicate()
    signalDesc, summaryLine, stackLines = parseGdbOutput(str(output, getpreferredencoding()))
    os.remove(fileName)
    if summaryLine:
        return assembleInfo(signalDesc, summaryLine, stackLines, "GDB")
    else:
        return parseFailure(errors, "GDB")

def writeDbxStackTrace(corefile, binary):
    cmdArgs = [ "dbx", "-f", "-q", "-c", "where; quit", binary, corefile ]
    proc = subprocess.Popen(cmdArgs, stdin=open(os.devnull), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, errors = proc.communicate()
    signalDesc, summaryLine, stackLines = parseDbxOutput(str(output, getpreferredencoding()))
    if summaryLine:
        return assembleInfo(signalDesc, summaryLine, stackLines, "DBX")
    else:
        return parseFailure(errors, "DBX")

def printCoreInfo(corefile):
    compression = corefile.endswith(".Z")
    if compression:
        os.system("uncompress " + corefile)
        corefile = corefile[:-2]
    summary, details, binary = interpretCore(corefile)
    print(summary)
    print("-" * len(summary))
    print("(Core file at", corefile + ")")
    if binary:
        print("(Created by binary", binary + ")")
    print(details)
    if compression:
        os.system("compress " + corefile)

def main():
    if len(sys.argv) != 2:
        print("Usage: interpretcore <corefile>")
    else:
        corefile = sys.argv[1]
        if os.path.isfile(corefile):
            printCoreInfo(corefile)
        else:    
            sys.stderr.write("File not found : " + corefile + "\n")

if __name__ == "__main__":
    main()
