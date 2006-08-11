#!/usr/bin/env python

import sys, os, string

class CommandLineTraffic:
    def __init__(self, argv):
        self.fullCommand = argv[0]
        self.commandName = os.path.basename(self.fullCommand)
        self.args = argv[1:]
        self.recordFile = os.getenv("TRAFFIC_RECORD_FILE")
        self.replayFile = os.getenv("TRAFFIC_REPLAY_FILE")
        exec "self.ignoreArgs = " + os.getenv("TRAFFIC_IGNORE_ARGS", {})
    def quote(self, arg):
        quoteChars = "|* "
        for char in quoteChars:
            if char in arg:
                return "'" + arg + "'"
        return arg
    def run(self):
        if self.replayFile:
            self.replay()
        elif self.recordFile:
            self.record()
        else:
            sys.stderr.write("TRAFFIC ERROR : both recording and replaying disabled!\n")
    def record(self):
        file = open(self.recordFile, "a")
        file.write("<-CMD:" + self.getStoredCmdLine() + os.linesep)
        quotedArgs = string.join(map(self.quote, self.args))
        realCmdLine = self.findRealCommand() + " " + quotedArgs
        cin, cout, cerr = os.popen3(realCmdLine)
        for line in cout.readlines():
            file.write("->OUT:" + line)
            sys.stdout.write(line)
        for line in cerr.readlines():
            file.write("->ERR:" + line)
            sys.stderr.write(line)
    def findRealCommand(self):
        # Find the first one in the path that isn't us :)
        for currDir in os.getenv("PATH").split(os.pathsep):
            fullPath = os.path.join(currDir, self.commandName)
            if self.isRealCommand(fullPath):
                return fullPath
    def isRealCommand(self, fullPath):
        return os.path.isfile(fullPath) and os.access(fullPath, os.X_OK) and \
               not os.path.samefile(fullPath, self.fullCommand)
    def getStoredCmdLine(self):
        return self.commandName + " " + self.getStoredArgs()
    def getStoredArgs(self):
        argsToIgnore = self.ignoreArgs.get(self.commandName, [])
        storedArgs = string.join(self.args)
        for arg in argsToIgnore:
            storedArgs = storedArgs.replace(self.args[int(arg)], "...")
        return storedArgs
    def replay(self):
        foundCmd = False
        cmdLine = self.getStoredCmdLine()
        for line in open(self.replayFile).xreadlines():
            isCmd = line.startswith("<-CMD")
            if foundCmd:
                if isCmd:
                    return
                elif line.startswith("->OUT"):
                    sys.stdout.write(line[6:])
                elif line.startswith("->ERR"):
                    sys.stderr.write(line[6:])
            elif isCmd:
                recordedLine = line[6:].strip()
                if recordedLine == cmdLine:
                    foundCmd = True
        if not foundCmd:
            sys.stderr.write("TRAFFIC ERROR: Could not find response for following command:\n" + cmdLine + "\n")

if __name__ == "__main__":
    cmdLineTraffic = CommandLineTraffic(sys.argv)
    cmdLineTraffic.run()
