#!/usr/bin/env python

import os, stat, sys, plugins, shutil, socket, subprocess, filecmp
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
            TrafficServer.instance.setRealVersion(localName, test.getPathName(localName))
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

    def findPossibleFileEdits(self):
        return []
    
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

    def record(self, recordFile):
        if not self.hasInfo():
            return
        desc = self.getDescription()
        if not desc.endswith("\n"):
            desc += "\n"
        writeFile = open(recordFile, "a")
        writeFile.write(desc)
        writeFile.flush()
        writeFile.close()

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

class FileEditTraffic(ResponseTraffic):
    typeId = "FIL"
    def __init__(self, activeFile, storedFile, filesToIgnore, reproduce):
        self.activeFile = activeFile
        self.storedFile = storedFile
        self.filesToIgnore = filesToIgnore
        self.reproduce = reproduce
        ResponseTraffic.__init__(self, os.path.basename(activeFile), None)

    def copy(self, src, target):
        plugins.ensureDirExistsForFile(target)
        if os.path.isfile(src):
            shutil.copyfile(src, target)
        else:
            for srcroot, srcdirs, srcfiles in os.walk(src):
                for fileToIgnore in self.filesToIgnore:
                    if fileToIgnore in srcdirs:
                        srcdirs.remove(fileToIgnore)
                    if fileToIgnore in srcfiles:
                        srcfiles.remove(fileToIgnore)
                for srcfile in srcfiles:
                    fullSrcPath = os.path.join(srcroot, srcfile)
                    fullTargetPath = fullSrcPath.replace(src, target)
                    if not os.path.exists(fullTargetPath) or not filecmp.cmp(fullSrcPath, fullTargetPath, 0):
                        plugins.ensureDirExistsForFile(fullTargetPath)
                        shutil.copyfile(fullSrcPath, fullTargetPath)
            
    def forwardToDestination(self):
        self.write(self.text)
        if self.reproduce:
            self.copy(self.storedFile, self.activeFile)
        return []
        
    def record(self, recordFile):
        # Copy the file, as well as the fact it has been stored
        ResponseTraffic.record(self, recordFile)
        if not self.reproduce:
            self.copy(self.activeFile, self.storedFile)
        
    
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
        
    def findPossibleFileEdits(self):
        edits = []
        for arg in self.cmdArgs:
            if not arg.startswith("-"):
                for word in arg.split():
                    if os.path.isabs(word) and os.path.exists(word):
                        edits.append(word)
                    else:
                        fullPath = os.path.join(self.cmdCwd, word)
                        if os.path.exists(fullPath):
                            edits.append(fullPath)
        self.diag.info("Might edit in " + repr(edits))
        return edits
        
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
            return self.makeResponse("", "ERROR: Traffic server could not find command '" + self.commandName + "' in PATH\n", 1)

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
        insertIndex = 0
        if len(trafficList) > 0 and isinstance(trafficList[0], FileEditTraffic):
            insertIndex = 1
        
        if len(trafficList) == insertIndex or not isinstance(trafficList[insertIndex], StdoutTraffic):
            trafficList.insert(insertIndex, StdoutTraffic("", self.responseFile))

        insertIndex += 1
        if len(trafficList) == insertIndex or not isinstance(trafficList[insertIndex], StderrTraffic):
            trafficList.insert(insertIndex, StderrTraffic("", self.responseFile))

        insertIndex += 1
        if len(trafficList) == insertIndex or not isinstance(trafficList[insertIndex], SysExitTraffic):
            trafficList.insert(insertIndex, SysExitTraffic("0", self.responseFile))

        insertIndex += 1
        for extraTraffic in trafficList[insertIndex:]:
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
        self.fileEditData = seqdict()
        self.currentTest = None
        self.fileRequestCount = {}
        
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
        self.currentTest = test
        ClientSocketTraffic.destination = None
        # Assume testing client until a server contacts us
        ClientSocketTraffic.direction = "<-"
        ServerTraffic.direction = "->"
        
    def findLatestModification(self, file):
        if os.path.isfile(file):
            statObj = os.stat(file)
            return statObj[stat.ST_MTIME], statObj[stat.ST_SIZE]
        elif os.path.isdir(file):
            allFiles = [ file ]
            for rootDir, dirs, files in os.walk(file):
                allFiles += [ os.path.join(rootDir, dir) for dir in dirs ]
                allFiles += [ os.path.join(rootDir, currFile) for currFile in files ]
            times = []
            totalSize = 0
            for currFile in allFiles:
                statObj = os.stat(currFile)
                times.append(statObj[stat.ST_MTIME])
                totalSize += statObj[stat.ST_SIZE]
            return max(times), totalSize

    def addPossibleFileEdits(self, traffic):
        for file in traffic.findPossibleFileEdits():
            modInfo = self.findLatestModification(file)
            self.fileEditData[file] = modInfo
            modTime, modSize = modInfo
            self.diag.info("Adding possible edit for " + file + " with mod time " +
                           plugins.localtime(seconds=modTime) + " and size " + str(modSize))
            
    def process(self, traffic):
        self.diag.info("Processing traffic " + repr(traffic.__class__))
        self.addPossibleFileEdits(traffic)
        traffic.record(self.recordFile)
        for response in self.getResponses(traffic):
            self.diag.info("Providing response " + repr(response.__class__))
            response.record(self.recordFile)
            for chainResponse in response.forwardToDestination():
                self.process(chainResponse)
            self.diag.info("Completed response " + repr(response.__class__))            

    def getResponses(self, traffic):
        if self.replayInfo.isActive():
            replayedResponses = []
            for responseClass, text in self.replayInfo.readReplayResponses(traffic):
                responseTraffic = self.makeResponseTraffic(traffic, responseClass, text)
                if responseTraffic:
                    replayedResponses.append(responseTraffic)
            return traffic.filterReplay(replayedResponses)
        else:
            trafficResponses = traffic.forwardToDestination()
            return self.getFileEditResponses() + trafficResponses

    def getFileEditPath(self, file):
        return os.path.join("file_edits", self.getFileEditName(os.path.basename(file)))

    def getFileEditName(self, name):
        timesUsed = self.fileRequestCount.setdefault(name, 0) + 1
        self.fileRequestCount[name] = timesUsed
        if timesUsed > 1:
            name += ".edit_" + str(timesUsed)
        return name

    def editFilesToIgnore(self):
        return self.currentTest.getCompositeConfigValue("test_data_ignore", "file_edits")

    def getFileBeingEdited(self, fileName):
        bestMatch, bestScore = None, -1
        for editedFile in self.fileEditData.keys():
            editedName = os.path.basename(editedFile)
            if editedName == fileName:
                bestMatch = editedFile
                break
            else:
                matchScore = self.getFileMatchScore(fileName, editedName)
                if matchScore > bestScore:
                    bestMatch, bestScore = editedFile, matchScore

        self.diag.info("File being edited for '" + fileName + "' : chose " + bestMatch)
        return bestMatch

    def getFileMatchScore(self, givenName, actualName):
        if actualName.find(".edit_") != -1:
            return -1

        return self._getFileMatchScore(givenName, actualName, lambda x: x) + \
               self._getFileMatchScore(givenName, actualName, lambda x: -1 -x)
    
    def _getFileMatchScore(self, givenName, actualName, indexFunction):
        score = 0
        while len(givenName) > score and len(actualName) > score and givenName[indexFunction(score)] == actualName[indexFunction(score)]:
            score += 1
        return score

    def makeResponseTraffic(self, traffic, responseClass, text):
        if responseClass is FileEditTraffic:
            editedFile = self.getFileBeingEdited(text.strip())
            storedFile = self.currentTest.getFileName(self.getFileEditPath(text.strip()))
            return FileEditTraffic(editedFile, storedFile, self.editFilesToIgnore(), reproduce=True)
        else:
            return responseClass(text, traffic.responseFile)

    def getFileEditResponses(self):
        traffic = []
        for file, editInfo in self.fileEditData.items():
            newEditInfo = self.findLatestModification(file)
            if newEditInfo != editInfo:
                storedFile = self.currentTest.makeTmpFileName(self.getFileEditPath(file), forComparison=0)
                traffic.append(FileEditTraffic(file, storedFile, self.editFilesToIgnore(), reproduce=False))
                self.fileEditData[file] = newEditInfo
        return traffic
        


class ReplayInfo:
    def __init__(self, replayFile):
        self.responseMap = seqdict()
        self.diag = plugins.getDiagnostics("Traffic Replay")
        if replayFile:
            self.readReplayFile(replayFile)
            
    def isActive(self):
        return len(self.responseMap) > 0

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
            allClasses = [ FileEditTraffic, ClientSocketTraffic, ServerTraffic, StdoutTraffic, StderrTraffic, SysExitTraffic ]
            for trafficClass in allClasses:
                if trafficClass.typeId == trafficType:
                    responses.append((trafficClass, trafficStr[6:]))
        self.timesChosen += 1
        return responses

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
        
