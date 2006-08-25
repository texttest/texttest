#!/usr/bin/env python

import os, string, sys, plugins, shutil, sys, socket
from copy import deepcopy
from ndict import seqdict
from SocketServer import TCPServer, StreamRequestHandler
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
        if self.configureServer(test):
            self.makeIntercepts(test)
    def configureServer(self, test):
        recordFile = test.makeTmpFileName("traffic")
        if self.record:
            self.setServerState(recordFile, None)
            return True
        else:
            trafficReplay = test.getFileName("traffic")
            if trafficReplay:
                self.setServerState(recordFile, trafficReplay)
                return True
            else:
                self.setServerState(None, None)
                return False
    def setServerState(self, recordFile, replayFile):
        if recordFile or replayFile and not TrafficServer.instance:
            TrafficServer.instance = TrafficServer()
        if TrafficServer.instance:
            TrafficServer.instance.setState(recordFile, replayFile)
    def makeIntercepts(self, test):
        for cmd in test.getConfigValue("collect_traffic"):
            linkName = test.makeTmpFileName(cmd, forComparison=0)
            self.intercept(linkName)
    def intercept(self, linkName):
        if os.path.islink(linkName):
            # We might have written a fake version - store what it points to so we can
            # call it later, and remove the link
            TrafficServer.instance.setRealVersion(os.path.basename(linkName), os.path.realpath(linkName))
            os.remove(linkName)
        # Linking doesn't exist on windows!
        if os.name == "posix":
            os.symlink(self.trafficFile, linkName)
        else:
            shutil.copy(self.trafficFile, linkName)

class Traffic:
    def __init__(self, text, responseFile):
        self.text = text
        self.responseFile = responseFile
    def getDescription(self):
        if len(self.text):
            return self.direction + self.typeId + ":" + self.text
        else:
            return ""
    def forwardToDestination(self):
        if self.responseFile:
            self.responseFile.write(self.text)
            self.responseFile.close()
        return []

class InTraffic(Traffic):
    direction = "<-"
    def filterReplay(self, trafficList):
        return trafficList
    
class ResponseTraffic(Traffic):
    direction = "->"

class ServerTraffic(InTraffic):
    typeId = "SRV"

class ServerStateTraffic(ServerTraffic):
    def __init__(self, inText, responseFile):
        InTraffic.__init__(self, inText, responseFile)
        if not ClientSocketTraffic.destination:
            host, port = inText.strip().split(":")
            ClientSocketTraffic.destination = host, int(port)
    def forwardToDestination(self):
        return []
            
class CommandLineTraffic(InTraffic):
    typeId = "CMD"
    origEnviron = {}
    realCommands = {}
    def __init__(self, inText, responseFile):
        cmdText, environText = inText.split(":SUT_ENVIRONMENT:")
        exec "argv = " + cmdText
        exec "cmdEnviron = " + environText
        self.fullCommand = argv[0]
        self.commandName = os.path.basename(self.fullCommand)
        self.argStr = string.join(map(self.quote, argv[1:]))
        self.envStr, recEnvStr = self.findDifferences(cmdEnviron)
        self.diag = plugins.getDiagnostics("Traffic Server")
        self.path = cmdEnviron.get("PATH")
        text = recEnvStr + self.commandName + " " + self.argStr
        InTraffic.__init__(self, text, responseFile)
    def findDifferences(self, cmdEnviron):
        diffs = {}
        toIgnore = [ "SHLVL", "_", "PWD", "DISPLAY" ]
        for var, value in cmdEnviron.items():
            if var in toIgnore:
                continue
            oldVal = self.origEnviron.get(var)
            if oldVal != value:
                diffs[var] = value
        return self.getEnvStrings(diffs)
    def getEnvStrings(self, envDict):
        if len(envDict) == 0:
            return "", ""
        realStr, recStr = "env ", "env "
        for var, value in envDict.items():
            line = "'" + var + "=" + value + "' "
            realStr += line
            oldVal = self.origEnviron.get(var)
            recLine = line
            if oldVal:
                recLine = line.replace(oldVal, "$" + var)
            recStr += recLine
        return realStr, recStr
    def quote(self, arg):
        quoteChars = "|* "
        for char in quoteChars:
            if char in arg:
                return "'" + arg + "'"
        return arg
    def forwardToDestination(self):
        realCmd = self.findRealCommand()
        if realCmd:
            realCmdLine = self.envStr + realCmd + " " + self.argStr
            TrafficServer.instance.diag.info("Executing real command : " + realCmdLine)
            cin, cout, cerr = os.popen3(realCmdLine)
            return self.makeResponse(cout.read(), cerr.read())
        else:
            return self.makeResponse("", "ERROR: Traffic server could not find command '" + self.commandName + "' in PATH")
    def makeResponse(self, output, errors):
        return [ StdoutTraffic(output, self.responseFile), StderrTraffic(errors, self.responseFile) ]
    def findRealCommand(self):
        # If we found a link already, use that, otherwise look on the path
        if self.realCommands.has_key(self.commandName):
            return self.realCommands[self.commandName]
        # Find the first one in the path that isn't us :)
        for currDir in self.path.split(os.pathsep):
            fullPath = os.path.join(currDir, self.commandName)
            if self.isRealCommand(fullPath):
                return fullPath
    def isRealCommand(self, fullPath):
        return os.path.isfile(fullPath) and os.access(fullPath, os.X_OK) and \
               not os.path.samefile(fullPath, self.fullCommand)
    def filterReplay(self, trafficList):
        if len(trafficList) == 0 or not isinstance(trafficList[0], StdoutTraffic):
            trafficList.insert(0, StdoutTraffic("", self.responseFile))
        if len(trafficList) == 1 or not isinstance(trafficList[1], StderrTraffic):
            trafficList.insert(1, StderrTraffic("", self.responseFile))
        for extraTraffic in trafficList[2:]:
            extraTraffic.responseFile = None
        return trafficList
                               
class StdoutTraffic(ResponseTraffic):
    typeId = "OUT"
    def forwardToDestination(self):
        if self.responseFile:
            self.responseFile.write(self.text + "|TT_STDOUT_STDERR|")
        return []

class StderrTraffic(ResponseTraffic):
    typeId = "ERR"

class ClientSocketTraffic(ResponseTraffic):
    destination = None
    typeId = "CLI"
    def forwardToDestination(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(self.destination)
        sock.sendall(self.text)
        sock.shutdown(1)
        response = sock.recv(1000000, socket.MSG_WAITALL)
        sock.close()
        return [ ServerTraffic(response, self.responseFile) ]

class TrafficRequestHandler(StreamRequestHandler):
    parseDict = { "SUT_SERVER" : ServerStateTraffic, "SUT_COMMAND_LINE" : CommandLineTraffic }
    def handle(self):
        text = self.rfile.read()
        traffic = self.parseTraffic(text)
        self.server.process(traffic)
    def parseTraffic(self, text):
        for key in self.parseDict.keys():
            prefix = key + ":"
            if text.startswith(prefix):
                value = text[len(prefix):]
                return self.parseDict[key](value, self.wfile)
        return ClientSocketTraffic(text, self.wfile)
            
class TrafficServer(TCPServer):
    instance = None
    def __init__(self):
        self.recordFile = None
        self.replayInfo = seqdict()
        self.replayIndex = -1
        self.diag = plugins.getDiagnostics("Traffic Server")
        TrafficServer.instance = self
        TCPServer.__init__(self, (socket.gethostname(), 0), TrafficRequestHandler)
        self.setAddressVariable()
        self.thread = Thread(target=self.serve_forever)
        self.thread.setDaemon(1)
        self.thread.start()
    def setAddressVariable(self):
        host, port = self.socket.getsockname()
        address = host + ":" + str(port)
        os.environ["TEXTTEST_MIM_SERVER"] = address
        self.diag.info("Starting traffic server on " + address)
    def setRealVersion(self, command, realCommand):
        self.diag.info("Storing faked command for " + command + " = " + realCommand) 
        CommandLineTraffic.realCommands[command] = realCommand
    def setState(self, recordFile, replayFile):
        self.recordFile = recordFile
        if replayFile:
            self.readReplayFile(replayFile)
        else:
            self.replayInfo = seqdict()
        if recordFile or replayFile:
            self.setAddressVariable()
        else:
            os.environ["TEXTTEST_MIM_SERVER"] = ""
        CommandLineTraffic.origEnviron = deepcopy(os.environ)
    def readReplayFile(self, replayFile):
        self.replayIndex = -1
        self.replayInfo = seqdict()
        trafficList = self.readIntoList(replayFile)
        currTrafficIn = ""
        for trafficStr in trafficList:
            if trafficStr.startswith("<-"):
                currTrafficIn = trafficStr.strip()
                # We can get the same question more than once. If so, store it separately
                # and rely on the index to get us through...
                while self.replayInfo.has_key(currTrafficIn):
                    currTrafficIn = "*" + currTrafficIn 
                self.replayInfo[currTrafficIn] = []
            else:
                self.replayInfo[currTrafficIn].append(trafficStr)
        self.diag.info("Replay info " + repr(self.replayInfo))
    def readIntoList(self, replayFile):
        trafficList = []
        currTraffic = ""
        for line in open(replayFile).xreadlines():
            if line.startswith("<-") or line.startswith("->"):
                if currTraffic:
                    trafficList.append(currTraffic)
                currTraffic = ""
            currTraffic += line
        if currTraffic:
            trafficList.append(currTraffic)
        return trafficList
    def process(self, traffic):
        self.record(traffic)
        for response in self.getResponses(traffic):
            self.record(response)
            for chainResponse in response.forwardToDestination():
                self.process(chainResponse)
    def record(self, traffic):
        desc = traffic.getDescription()
        if len(desc) == 0:
            return
        if not desc.endswith(os.linesep):
            desc += os.linesep
        self.diag.info("Recording " + repr(traffic.__class__) + " " + desc)
        writeFile = open(self.recordFile, "a")
        writeFile.write(desc)
        writeFile.close()
    def getResponses(self, traffic):
        if len(self.replayInfo) > 0:
            return self.readReplayResponses(traffic)
        else:
            return traffic.forwardToDestination()
    def readReplayResponses(self, traffic):
        # We return the response matching the traffic in if we can, otherwise just one after the last one
        # assuming a match
        desc = traffic.getDescription()
        if len(desc) == 0:
            return []
        if self.replayInfo.has_key(desc):
            descIndex = self.replayInfo.keys().index(desc)
            if self.replayIndex < descIndex:
                self.replayIndex = descIndex
                return self.parseResponses(self.replayInfo[desc], traffic)

        # If we can't find an exact match in the "future", just pull the next response off the list
        self.replayIndex += 1
        self.diag.info("Increased replay index to " + repr(self.replayIndex))
        if self.replayIndex < len(self.replayInfo.keys()):
            key = self.replayInfo.keys()[self.replayIndex]
            return self.parseResponses(self.replayInfo[key], traffic)
        else:
            sys.stderr.write("WARNING: Received more requests than are recorded, could not respond sensibly!\n" + desc)
            return []
    def parseResponses(self, trafficStrings, traffic):
        responses = []
        for trafficStr in trafficStrings:
            trafficType = trafficStr[2:5]
            allClasses = [ ClientSocketTraffic, StdoutTraffic, StderrTraffic ]
            for trafficClass in allClasses:
                if trafficClass.typeId == trafficType:
                    responses.append(trafficClass(trafficStr[6:], traffic.responseFile))
        return traffic.filterReplay(responses)
