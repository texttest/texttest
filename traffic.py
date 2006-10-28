#!/usr/bin/env python

import os, string, sys, plugins, shutil, sys, socket, tempfile
from copy import deepcopy
from ndict import seqdict
from SocketServer import TCPServer, StreamRequestHandler
from threading import Thread

class MethodWrap:
    def __init__(self, method, firstArg):
        self.method = method
        self.firstArg = firstArg
    def __call__(self, arg):
        return self.method(self.firstArg, arg)

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
        envVarMethod = MethodWrap(test.getCompositeConfigValue, "collect_traffic_environment")
        if self.record:
            self.setServerState(recordFile, None, envVarMethod)
            return True
        else:
            trafficReplay = test.getFileName("traffic")
            if trafficReplay:
                self.setServerState(recordFile, trafficReplay, envVarMethod)
                return True
            else:
                self.setServerState(None, None, envVarMethod)
                return False
    def setServerState(self, recordFile, replayFile, envVarMethod):
        if recordFile or replayFile and not TrafficServer.instance:
            TrafficServer.instance = TrafficServer()
        if TrafficServer.instance:
            TrafficServer.instance.setState(recordFile, replayFile, envVarMethod)
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
    def hasInfo(self):
        return len(self.text) > 0
    def getDescription(self):
        return self.direction + self.typeId + ":" + self.text
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
            lastWord = inText.strip().split()[-1]
            host, port = lastWord.split(":")
            ClientSocketTraffic.destination = host, int(port)
    def forwardToDestination(self):
        return []
            
class CommandLineTraffic(InTraffic):
    typeId = "CMD"
    envVarMethod = None
    origEnviron = {}
    realCommands = {}
    def __init__(self, inText, responseFile):
        cmdText, environText = inText.split(":SUT_ENVIRONMENT:")
        argv = eval(cmdText)
        cmdEnviron = eval(environText)
        self.fullCommand = argv[0]
        self.commandName = os.path.basename(self.fullCommand)
        self.argStr = string.join(map(self.quote, argv[1:]))
        self.envStr, recEnvStr = self.getEnvStrings(cmdEnviron)
        self.diag = plugins.getDiagnostics("Traffic Server")
        self.path = cmdEnviron.get("PATH")
        text = recEnvStr + self.commandName + " " + self.argStr
        InTraffic.__init__(self, text, responseFile)
    def getEnvStrings(self, cmdEnviron):
        interestingEnviron = []
        for var in self.envVarMethod(self.commandName):
            value = cmdEnviron.get(var)
            if value is not None:
                interestingEnviron.append((var, value))
        return self.convertToEnvStrings(interestingEnviron)
    def convertToEnvStrings(self, envVars):
        if len(envVars) == 0:
            return "", ""
        realStr, recStr = "env ", "env "
        for var, value in envVars:
            line = "'" + var + "=" + value + "' "
            realStr += line
            oldVal = self.origEnviron.get(var)
            recLine = line
            if oldVal and oldVal != value:
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
            fd, coutFile = tempfile.mkstemp()
            fd, cerrFile = tempfile.mkstemp()
            exitCode = os.system(realCmdLine + " > " + coutFile + " 2> " + cerrFile)
            output = open(coutFile).read()
            errors = open(cerrFile).read()
            os.remove(coutFile)
            os.remove(cerrFile)
            return self.makeResponse(output, errors, exitCode)
        else:
            return self.makeResponse("", "ERROR: Traffic server could not find command '" + self.commandName + "' in PATH", 256)
    def makeResponse(self, output, errors, exitCode):
        return [ StdoutTraffic(output, self.responseFile), StderrTraffic(errors, self.responseFile), \
                 SysExitTraffic(str(exitCode), self.responseFile) ]
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
        if len(trafficList) == 2 or not isinstance(trafficList[2], SysExitTraffic):
            trafficList.insert(2, SysExitTraffic("0", self.responseFile))
        for extraTraffic in trafficList[3:]:
            extraTraffic.responseFile = None
        return trafficList
                               
class StdoutTraffic(ResponseTraffic):
    typeId = "OUT"
    def forwardToDestination(self):
        if self.responseFile:
            self.responseFile.write(self.text + "|TT_CMD_SEP|")
        return []

class StderrTraffic(ResponseTraffic):
    typeId = "ERR"
    def forwardToDestination(self):
        if self.responseFile:
            self.responseFile.write(self.text + "|TT_CMD_SEP|")
        return []

class SysExitTraffic(ResponseTraffic):
    typeId = "EXC"
    def hasInfo(self):
        return self.text != "0"

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
    def setState(self, recordFile, replayFile, envVarMethod):
        self.recordFile = recordFile
        if replayFile:
            self.readReplayFile(replayFile)
        else:
            self.replayInfo = seqdict()
        if recordFile or replayFile:
            self.setAddressVariable()
        else:
            os.environ["TEXTTEST_MIM_SERVER"] = ""
        CommandLineTraffic.envVarMethod = envVarMethod
        CommandLineTraffic.origEnviron = deepcopy(os.environ)
        ClientSocketTraffic.destination = None
    def readReplayFile(self, replayFile):
        self.replayInfo = seqdict()
        trafficList = self.readIntoList(replayFile)
        currResponseHandler = None
        for trafficStr in trafficList:
            if trafficStr.startswith("<-"):
                if currResponseHandler:
                    currResponseHandler.endResponse()
                currTrafficIn = trafficStr.strip()
                if not self.replayInfo.has_key(currTrafficIn):
                    self.replayInfo[currTrafficIn] = ReplayedResponseHandler()
                currResponseHandler = self.replayInfo[currTrafficIn]
            else:
                currResponseHandler.addResponse(trafficStr)
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
        if not traffic.hasInfo():
            return
        desc = traffic.getDescription()
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
        # We return the response matching the traffic in if we can, otherwise
        # the one that is most similar to it
        if not traffic.hasInfo():
            return []
        desc = traffic.getDescription()
        bestMatchKey = self.findBestMatch(desc)
        return self.replayInfo[bestMatchKey].makeResponses(traffic)
    def findBestMatch(self, desc):
        if self.replayInfo.has_key(desc):
            return desc
        bestMatchPerc, bestMatch = 0.0, None
        for key in self.replayInfo.keys():
            matchPerc = self.findMatchPercentage(key, desc)
            if matchPerc > bestMatchPerc:
                bestMatchPerc, bestMatch = matchPerc, key
        if bestMatch is not None:
            return bestMatch
        else:
            sys.stderr.write("WARNING: Could not find any sensible match for the traffic:\n" + desc + "\n")
            return self.replayInfo.keys()[0]
    def findMatchPercentage(self, traffic1, traffic2):
        words1 = traffic1.split()
        words2 = traffic2.split()
        matches = 0
        for word in words1:
            if word in words2:
                matches += 1
        nomatches = len(words1) + len(words2) - (2 * matches)
        return 100.0 * float(matches) / float(nomatches + matches)

# Need to handle multiple replies to the same question
class ReplayedResponseHandler:
    def __init__(self):
        self.currIndex = 0
        self.readIndex = 0
        self.responses = []
    def __repr__(self):
        return repr(self.responses)
    def endResponse(self):
        self.readIndex += 1
    def addResponse(self, trafficStr):
        if len(self.responses) <= self.readIndex:
            self.responses.append([])
        self.responses[self.readIndex].append(trafficStr)
    def getCurrentStrings(self):
        if len(self.responses) == 0:
            return []
        if self.currIndex < len(self.responses):
            currStrings = self.responses[self.currIndex]
            self.currIndex += 1
        else:
            currStrings = self.responses[0]
            self.currIndex = 1
        return currStrings
    def makeResponses(self, traffic):
        trafficStrings = self.getCurrentStrings()
        responses = []
        for trafficStr in trafficStrings:
            trafficType = trafficStr[2:5]
            allClasses = [ ClientSocketTraffic, StdoutTraffic, StderrTraffic, SysExitTraffic ]
            for trafficClass in allClasses:
                if trafficClass.typeId == trafficType:
                    responses.append(trafficClass(trafficStr[6:], traffic.responseFile))
        return traffic.filterReplay(responses)
