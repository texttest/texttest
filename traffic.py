#!/usr/bin/env python

import os, string, plugins, shutil, sys
from ndict import seqdict
from SocketServer import TCPServer, StreamRequestHandler
from socket import gethostname
from threading import Thread

class SetUpTrafficHandlers(plugins.Action):
    def __init__(self, record):
        self.record = record
        self.trafficFile = self.findTrafficFile()
    def findTrafficFile(self):
        for dir in sys.path:
            fullPath = os.path.join(dir, "traffic_cmd.py")
            if os.path.isfile(fullPath):
                return fullPath
    def __call__(self, test):
        if not TrafficServer.instance:
            return
        if self.configureServer(test):
            self.makeIntercepts(test)
    def configureServer(self, test):
        recordFile = test.makeTmpFileName("traffic")
        if self.record:
            TrafficServer.instance.setFiles(recordFile, None)
            return True
        else:
            trafficReplay = test.getFileName("traffic")
            if trafficReplay:
                TrafficServer.instance.setFiles(recordFile, trafficReplay)
                return True
            else:
                return False
    def makeIntercepts(self, test):
        for cmd in test.getConfigValue("collect_traffic"):
            linkName = test.makeTmpFileName(cmd, forComparison=0)
            self.intercept(linkName)
    def intercept(self, linkName):
        # Linking doesn't exist on windows!
        if os.name == "posix":
            os.symlink(self.trafficFile, linkName)
        else:
            shutil.copy(self.trafficFile, linkName)
    def setUpApplication(self, app):
        if len(app.getConfigValue("collect_traffic")) > 0 and not TrafficServer.instance:
            TrafficServer.instance = TrafficServer()

class TrafficRequestHandler(StreamRequestHandler):
    def handle(self):
        text = self.rfile.readline()
        self.server.diag.info("Received traffic " + text.strip())
        #if text.startswith("SUT_SERVER_ADDRESS:"):
        cmdText = self.getValue(text, "SUT_COMMAND_LINE:")
        if cmdText:
            self.server.diag.info("Parsed as command line traffic: " + cmdText)
            traffic = CommandLineTraffic(cmdText)
        reply = self.server.process(traffic)
        self.wfile.write(reply + traffic.getTerminator())
    def getValue(self, text, prefix):
        if text.startswith(prefix):
            return text[len(prefix):]
            
class TrafficServer(TCPServer):
    instance = None
    def __init__(self):
        self.recordFile = None
        self.replayInfo = seqdict()
        self.replayIndex = -1
        self.diag = plugins.getDiagnostics("Traffic Server")
        TrafficServer.instance = self
        TCPServer.__init__(self, (gethostname(), 0), TrafficRequestHandler)
        self.setAddressVariable()
        self.thread = Thread(target=self.serve_forever)
        self.thread.setDaemon(1)
        self.thread.start()
    def setAddressVariable(self):
        host, port = self.socket.getsockname()
        address = host + ":" + str(port)
        os.environ["TEXTTEST_MIM_SERVER"] = address
        self.diag.info("Starting traffic server on " + address)
    def setFiles(self, recordFile, replayFile):
        self.recordFile = recordFile
        if replayFile:
            self.readReplayFile(replayFile)
    def readReplayFile(self, replayFile):
        self.replayIndex = -1
        self.replayInfo = seqdict()
        currTrafficIn = ""
        for line in open(replayFile).xreadlines():
            if line.startswith("<-"):
                currTrafficIn = line
                self.replayInfo[line] = []
            elif line.startswith("->"):
                self.replayInfo[currTrafficIn].append(line)
    def process(self, traffic):
        writeFile = open(self.recordFile, "a")
        writeFile.write(traffic.getDescription())
        response = self.getResponse(traffic)
        writeFile.write(response)
        writeFile.close()
        self.diag.info("Recording response: " + response)
        return response
    def getResponse(self, traffic):
        if len(self.replayInfo) > 0:
            return self.readReplayResponse(traffic)
        else:
            return traffic.forwardToDestination()
    def readReplayResponse(self, traffic):
        # We return the response matching the traffic in if we can, otherwise just one after the last one
        # assuming a match
        responses = self.findAllResponses(traffic)
        response = ""
        for currline in responses:
            if traffic.ownsResponseLine(currline):
                response += currline
        return response
    def findAllResponses(self, traffic):
        desc = traffic.getDescription()
        if self.replayInfo.has_key(desc):
            self.replayIndex = self.replayInfo.keys().index(desc)
            return self.replayInfo[desc]
        else:
            self.replayIndex += 1
            key = self.replayInfo.keys()[self.replayIndex]
            return self.replayInfo[key]
            
class CommandLineTraffic:
    def __init__(self, cmdText):
        exec "argv = " + cmdText
        self.fullCommand = argv[0]
        self.commandName = os.path.basename(self.fullCommand)
        self.args = argv[1:]
    def quote(self, arg):
        quoteChars = "|* "
        for char in quoteChars:
            if char in arg:
                return "'" + arg + "'"
        return arg
    def getDescription(self):
        return "<-CMD:" + self.getStoredCmdLine() + os.linesep
    def getStoredCmdLine(self):
        return self.commandName + " " + string.join(self.args)
    def forwardToDestination(self):
        quotedArgs = string.join(map(self.quote, self.args))
        realCmdLine = self.findRealCommand() + " " + quotedArgs
        cin, cout, cerr = os.popen3(realCmdLine)
        response = ""
        for line in cout.readlines():
            response += "->OUT:" + line
        for line in cerr.readlines():
            response += "->ERR:" + line
        return response
    def ownsResponseLine(self, line):
        return line.startswith("->OUT:") or line.startswith("->ERR:")
    def findRealCommand(self):
        # Find the first one in the path that isn't us :)
        for currDir in os.getenv("PATH").split(os.pathsep):
            fullPath = os.path.join(currDir, self.commandName)
            if self.isRealCommand(fullPath):
                return fullPath
    def getTerminator(self):
        return "TT_END_CMD_RESPONSE"
    def isRealCommand(self, fullPath):
        return os.path.isfile(fullPath) and os.access(fullPath, os.X_OK) and \
               not os.path.samefile(fullPath, self.fullCommand)
