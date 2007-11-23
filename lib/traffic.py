#!/usr/bin/env python

import os, sys, plugins, shutil, socket, subprocess
from ndict import seqdict
from SocketServer import TCPServer, StreamRequestHandler
from threading import Thread
from types import StringType

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
            self.setServerState(recordFile, None, test)
            return True
        else:
            trafficReplay = test.getFileName("traffic")
            if trafficReplay:
                self.setServerState(recordFile, trafficReplay, test)
                return True
            else:
                self.setServerState(None, None, test)
                return False
    def setServerState(self, recordFile, replayFile, test):
        if (recordFile or replayFile) and not TrafficServer.instance:
            TrafficServer.instance = TrafficServer()
        if TrafficServer.instance:
            TrafficServer.instance.setState(recordFile, replayFile, test)
    def makeIntercepts(self, test):
        for cmd in test.getConfigValue("collect_traffic"):
            linkName = test.makeTmpFileName(cmd, forComparison=0)
            self.intercept(test, linkName)
    def intercept(self, test, linkName):
        if os.path.exists(linkName):
            # We might have written a fake version - store what it points to so we can
            # call it later, and remove the link
            localName = os.path.basename(linkName)
            TrafficServer.instance.setRealVersion(localName, test.makePathName(localName))
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
    def write(self, message):
        if self.responseFile:
            try:
                self.responseFile.write(message)
            except socket.error:
                # The system under test has died or is otherwise unresponsive
                # Should handle this, probably. For now, ignoring it is better than stack dumps
                pass
                
    def forwardToDestination(self):
        self.write(self.text)
        if self.responseFile:
            self.responseFile.close()
        return []
    def filterReplay(self, trafficList):
        return trafficList
    
class ResponseTraffic(Traffic):
    direction = "->"

class StdoutTraffic(ResponseTraffic):
    typeId = "OUT"
    def forwardToDestination(self):
        self.write(self.text + "|TT_CMD_SEP|")
        return []

class StderrTraffic(ResponseTraffic):
    typeId = "ERR"
    def forwardToDestination(self):
        self.write(self.text + "|TT_CMD_SEP|")
        return []

class SysExitTraffic(ResponseTraffic):
    typeId = "EXC"
    def __init__(self, status, responseFile):
        ResponseTraffic.__init__(self, str(status), responseFile)
        self.exitStatus = int(status)
    def hasInfo(self):
        return self.exitStatus != 0
    
class ClientSocketTraffic(Traffic):
    destination = None
    direction = "<-"
    typeId = "CLI"
    def forwardToDestination(self):
        if self.destination:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(self.destination)
            sock.sendall(self.text)
            sock.shutdown(socket.SHUT_WR)
            response = sock.makefile().read()
            sock.close()
            return [ ServerTraffic(response, self.responseFile) ]
        else:
            return [] # client is alone, nowhere to forward

class ServerTraffic(Traffic):
    typeId = "SRV"
    direction = "->"

class ServerStateTraffic(ServerTraffic):
    def __init__(self, inText, responseFile):
        ServerTraffic.__init__(self, inText, responseFile)
        if not ClientSocketTraffic.destination:
            lastWord = inText.strip().split()[-1]
            host, port = lastWord.split(":")
            ClientSocketTraffic.destination = host, int(port)
            # If we get a server state message, switch the order around
            ClientSocketTraffic.direction = "->"
            ServerTraffic.direction = "<-"
    def forwardToDestination(self):
        return []
            
class CommandLineTraffic(Traffic):
    typeId = "CMD"
    direction = "<-"
    currentTest = None
    realCommands = {}
    def __init__(self, inText, responseFile):
        self.diag = plugins.getDiagnostics("Traffic Server")
        cmdText, environText, cmdCwd = inText.split(":SUT_SEP:")
        argv = eval(cmdText)
        self.cmdEnviron = eval(environText)
        self.cmdCwd = cmdCwd
        self.diag.info("Received command with cwd = " + cmdCwd)
        self.fullCommand = argv[0].replace("\\", "/")
        self.commandName = os.path.basename(self.fullCommand)
        self.cmdArgs = argv[1:]
        self.argStr = " ".join(map(self.quote, argv[1:]))
        self.environ = self.filterEnvironment(self.cmdEnviron)
        self.path = self.cmdEnviron.get("PATH")
        text = self.getEnvString() + self.commandName + " " + self.argStr
        Traffic.__init__(self, text, responseFile)
    def filterEnvironment(self, cmdEnviron):
        interestingEnviron = []
        for var in self.currentTest.getCompositeConfigValue("collect_traffic_environment", self.commandName):
            value = cmdEnviron.get(var)
            if value is not None and value != self.currentTest.getEnvironment(var):
                interestingEnviron.append((var, value))
        return interestingEnviron
    def getEnvString(self):
        recStr = ""
        if not plugins.samefile(self.cmdCwd, self.currentTest.getDirectory(temporary=1)):
            recStr += "cd " + self.cmdCwd + "; "
        if len(self.environ) == 0:
            return recStr
        recStr += "env "
        for var, value in self.environ:
            recLine = "'" + var + "=" + value + "' "
            oldVal = self.currentTest.getEnvironment(var)
            if oldVal and oldVal != value:
                recLine = recLine.replace(oldVal, "$" + var)
            recStr += recLine
        return recStr
    def getQuoteChar(self, char):
        if char == "\"" and os.name == "posix":
            return "'"
        else:
            return '"'
    def quote(self, arg):
        quoteChars = "'\"|* "
        for char in quoteChars:
            if char in arg:
                quoteChar = self.getQuoteChar(char)
                return quoteChar + arg + quoteChar
        return arg
    def forwardToDestination(self):
        realCmd = self.findRealCommand()
        if realCmd:                
            fullArgs = [ realCmd ] + self.cmdArgs
            interpreter = plugins.getInterpreter(realCmd)
            if interpreter:
                fullArgs = [ interpreter ] + fullArgs
            proc = subprocess.Popen(fullArgs, env=self.cmdEnviron, cwd=self.cmdCwd, 
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            output, errors = proc.communicate()
            return self.makeResponse(output, errors, proc.returncode)
        else:
            return self.makeResponse("", "ERROR: Traffic server could not find command '" + self.commandName + "' in PATH", 1)
    def makeResponse(self, output, errors, exitCode):
        return [ StdoutTraffic(output, self.responseFile), StderrTraffic(errors, self.responseFile), \
                 SysExitTraffic(exitCode, self.responseFile) ]
    def findRealCommand(self):
        # If we found a link already, use that, otherwise look on the path
        if self.realCommands.has_key(self.commandName):
            return self.realCommands[self.commandName]
        # Find the first one in the path that isn't us :)
        TrafficServer.instance.diag.info("Finding real command to replace " + self.fullCommand)
        for currDir in self.path.split(os.pathsep):
            TrafficServer.instance.diag.info("Searching " + currDir)
            fullPath = os.path.join(currDir, self.commandName)
            if self.isRealCommand(fullPath):
                return fullPath
    def isRealCommand(self, fullPath):
        return os.path.isfile(fullPath) and os.access(fullPath, os.X_OK) and \
               not plugins.samefile(fullPath, self.fullCommand)
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
                               
class TrafficRequestHandler(StreamRequestHandler):
    parseDict = { "SUT_SERVER" : ServerStateTraffic, "SUT_COMMAND_LINE" : CommandLineTraffic }
    def handle(self):
        self.server.diag.info("Received incoming request...")
        text = self.rfile.read()
        traffic = self.parseTraffic(text)
        self.server.process(traffic)
        self.server.diag.info("Finished processing incoming request")
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
        self.replayInfo = None
        self.diag = plugins.getDiagnostics("Traffic Server")
        TrafficServer.instance = self
        TCPServer.__init__(self, (socket.gethostname(), 0), TrafficRequestHandler)
        self.thread = Thread(target=self.serve_forever)
        self.thread.setDaemon(1)
        self.diag.info("Starting traffic server thread")
        self.thread.start()
    def setAddressVariable(self, test):
        host, port = self.socket.getsockname()
        address = host + ":" + str(port)
        test.setEnvironment("TEXTTEST_MIM_SERVER", address)
        self.diag.info("Setting traffic server address to '" + address + "'")
        
    def setRealVersion(self, command, realCommand):
        self.diag.info("Storing faked command for " + command + " = " + realCommand) 
        CommandLineTraffic.realCommands[command] = realCommand
    def setState(self, recordFile, replayFile, test):
        self.recordFile = recordFile
        self.replayInfo = ReplayInfo(replayFile)
        if recordFile or replayFile:
            self.setAddressVariable(test)
        CommandLineTraffic.currentTest = test
        ClientSocketTraffic.destination = None
        # Assume testing client until a server contacts us
        ClientSocketTraffic.direction = "<-"
        ServerTraffic.direction = "->"
        
    def process(self, traffic):
        self.diag.info("Processing traffic " + repr(traffic.__class__))
        self.record(traffic)
        for response in self.replayInfo.getResponses(traffic):
            self.diag.info("Providing response " + repr(response.__class__))
            self.record(response)
            for chainResponse in response.forwardToDestination():
                self.process(chainResponse)
            self.diag.info("Completed response " + repr(response.__class__))
    def record(self, traffic):
        if not traffic.hasInfo():
            return
        desc = traffic.getDescription()
        if not desc.endswith("\n"):
            desc += "\n"
        self.diag.info("Recording " + repr(traffic.__class__) + " " + desc)
        writeFile = open(self.recordFile, "a")
        writeFile.write(desc)
        writeFile.flush()
        writeFile.close()

class ReplayInfo:
    def __init__(self, replayFile):
        self.responseMap = seqdict()
        self.diag = plugins.getDiagnostics("Traffic Replay")
        if replayFile:
            self.readReplayFile(replayFile)
    def readReplayFile(self, replayFile):
        trafficList = self.readIntoList(replayFile)
        currResponseHandler = None
        for trafficStr in trafficList:
            if trafficStr.startswith("<-"):
                currTrafficIn = trafficStr.strip()
                currResponseHandler = self.responseMap.get(currTrafficIn)
                if currResponseHandler:
                    currResponseHandler.newResponse()
                else:
                    currResponseHandler = ReplayedResponseHandler()
                    self.responseMap[currTrafficIn] = currResponseHandler
            else:
                currResponseHandler.addResponse(trafficStr)
        self.diag.info("Replay info " + repr(self.responseMap))
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
    def getResponses(self, traffic):
        if len(self.responseMap) > 0:
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
        if bestMatchKey:
            return self.responseMap[bestMatchKey].makeResponses(traffic)
        else:
            return []
    def findBestMatch(self, desc):
        self.diag.info("Trying to match '" + desc + "'")
        if self.responseMap.has_key(desc):
            self.diag.info("Found exact match")
            return desc
        bestMatchPerc, bestMatch, fewestTimesChosen = 0.0, None, 100000
        for currDesc, responseHandler in self.responseMap.items():
            if not self.sameType(desc, currDesc):
                continue
            matchPerc = self.findMatchPercentage(currDesc, desc)
            self.diag.info("Match percentage " + repr(matchPerc) + " with '" + currDesc + "'")
            if matchPerc > bestMatchPerc or (matchPerc == bestMatchPerc and responseHandler.timesChosen < fewestTimesChosen):
                bestMatchPerc, bestMatch, fewestTimesChosen = matchPerc, currDesc, responseHandler.timesChosen
        if bestMatch is not None:
            self.diag.info("Best match chosen as '" + bestMatch + "'")
            return bestMatch
    def sameType(self, desc1, desc2):
        return desc1[2:5] == desc2[2:5]
    def getWords(self, desc):
        words = []
        for part in desc.split("/"):
            words += part.split()
        return words
    def findMatchPercentage(self, traffic1, traffic2):
        words1 = self.getWords(traffic1)
        words2 = self.getWords(traffic2)
        matches = 0
        for word in words1:
            if word in words2:
                matches += 1
        nomatches = len(words1) + len(words2) - (2 * matches)
        return 100.0 * float(matches) / float(nomatches + matches)
    

# Need to handle multiple replies to the same question
class ReplayedResponseHandler:
    def __init__(self):
        self.timesChosen = 0
        self.responses = [[]]
    def __repr__(self):
        return repr(self.responses)
    def newResponse(self):
        self.responses.append([])        
    def addResponse(self, trafficStr):
        self.responses[-1].append(trafficStr)
    def getCurrentStrings(self):
        if len(self.responses) == 0:
            return []
        if self.timesChosen < len(self.responses):
            currStrings = self.responses[self.timesChosen]
        else:
            currStrings = self.responses[0]
        return currStrings
    def makeResponses(self, traffic):
        trafficStrings = self.getCurrentStrings()
        responses = []
        for trafficStr in trafficStrings:
            trafficType = trafficStr[2:5]
            allClasses = [ ClientSocketTraffic, ServerTraffic, StdoutTraffic, StderrTraffic, SysExitTraffic ]
            for trafficClass in allClasses:
                if trafficClass.typeId == trafficType:
                    responses.append(trafficClass(trafficStr[6:], traffic.responseFile))
        self.timesChosen += 1
        return traffic.filterReplay(responses)

class ModifyTraffic(plugins.ScriptWithArgs):
    # For now, only bother with the client server traffic which is mostly what needs tweaking...
    scriptDoc = "Apply a script to all the client server data"
    def __init__(self, args):
        argDict = self.parseArguments(args)
        self.script = argDict.get("script")
    def __repr__(self):
        return "Updating traffic in"
    def __call__(self, test):
        try:
            fileName = test.getFileName("traffic")
            if fileName:
                self.describe(test)
                newFileName = fileName + "tmpedit"
                newFile = open(newFileName, "w")
                replayInfo = ReplayInfo(None)
                for item in replayInfo.readIntoList(fileName):
                    self.writeTraffic(newFile, item, test.getDirectory())
                newFile.close()
                os.rename(newFileName, fileName)
        except plugins.TextTestError, e:
            print e
            
    def writeTraffic(self, newFile, fullLine, dir):
        self.write(newFile, self.getModified(fullLine, dir))

    def getModified(self, fullLine, dir):
        trafficType = fullLine[2:5]
        if trafficType in [ "CLI", "SRV" ]:
            proc = subprocess.Popen([ self.script, fullLine[6:]], cwd=dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = proc.communicate()
            if len(stderr) > 0:
                raise plugins.TextTestError, "Couldn't modify traffic :\n " + stderr
            else:
                return fullLine[:6] + stdout
        else:
            return fullLine
            
    def write(self, newFile, desc):
        if not desc.endswith("\n"):
            desc += "\n"
        newFile.write(desc)

    def setUpSuite(self, suite):
        self.describe(suite)
        
