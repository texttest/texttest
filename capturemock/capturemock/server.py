
import optparse, os, stat, sys, logging, logging.config, socket, threading, time
import commandlinetraffic, pythontraffic, fileedittraffic, clientservertraffic
from SocketServer import TCPServer, StreamRequestHandler
from ordereddict import OrderedDict
from replayinfo import ReplayInfo

def create_option_parser():
    usage = """usage: %prog [options] 

Standalone traffic server program. Basic usage is to grab the
address it writes out and run a program with TEXTTEST_MIM_SERVER set to it.
capturecommand.py can then intercept command-line programs, .py can
intercept python modules while the system itself can be modified to "internally"
react to the above module to repoint where it sends socket interactions"""

    parser = optparse.OptionParser(usage)
    parser.add_option("-a", "--asynchronous-file-edit-commands", metavar="ENV",
                      help="Commands which may cause files to be edited after they have exited (presumably via background processes they start)")
    parser.add_option("-A", "--alter-response", metavar="REPLACEMENTS",
                      help="Response alterations to perform on the text before recording or returning it")
    parser.add_option("-e", "--transfer-environment", metavar="ENV",
                      help="Environment variables that are significant to particular programs and should be recorded if changed.")
    parser.add_option("-i", "--ignore-edits", metavar="FILES",
                      help="When monitoring which files have been edited by a program, ignore files and directories with the given names")
    parser.add_option("-p", "--replay", 
                      help="replay traffic recorded in FILE.", metavar="FILE")
    parser.add_option("-I", "--replay-items", 
                      help="attempt replay only items in ITEMS, record the rest", metavar="ITEMS")
    parser.add_option("-l", "--logdefaults",
                      help="Default values to pass to log configuration file. Only useful with -L", metavar="LOGDEFAULTS")
    parser.add_option("-L", "--logconfigfile",
                      help="Configure logging via the log configuration file at FILE.", metavar="LOGCONFIGFILE")
    parser.add_option("-f", "--replay-file-edits", 
                      help="restore edited files referred to in replayed file from DIR.", metavar="DIR")
    parser.add_option("-m", "--python-module-intercepts", 
                      help="Python modules whose objects should be stored locally rather than returned as they are", metavar="MODULES")
    parser.add_option("-r", "--record", 
                      help="record traffic to FILE.", metavar="FILE")
    parser.add_option("-F", "--record-file-edits", 
                      help="store edited files under DIR.", metavar="DIR")
    parser.add_option("-s", "--sequential-mode", action="store_true",
                      help="Disable concurrent traffic, handle all incoming messages sequentially")
    return parser


class TrafficServer(TCPServer):
    def __init__(self, options):
        self.useThreads = not options.sequential_mode
        self.filesToIgnore = []
        if options.ignore_edits:
            self.filesToIgnore = options.ignore_edits.split(",")
        self.recordFileHandler = RecordFileHandler(options.record)
        self.replayInfo = ReplayInfo(options.replay, options.replay_items)
        self.requestCount = 0
        self.diag = logging.getLogger("Traffic Server")
        self.topLevelForEdit = [] # contains only paths explicitly given. Always present.
        self.fileEditData = OrderedDict() # contains all paths, including subpaths of the above. Empty when replaying.
        self.terminate = False
        self.hasAsynchronousEdits = False
        TCPServer.__init__(self, (socket.gethostname(), 0), TrafficRequestHandler)
        host, port = self.socket.getsockname()
        sys.stdout.write(host + ":" + str(port) + "\n") # Tell our caller, so they can tell the program being handled
        sys.stdout.flush()
        
    def run(self):
        self.diag.info("Starting traffic server")
        while not self.terminate:
            self.handle_request()
        # Join all remaining request threads so they don't
        # execute after Python interpreter has started to shut itself down.
        for t in threading.enumerate():
            if t.name == "request":
                t.join()
        self.diag.info("Shut down traffic server")
            
    def shutdown(self):
        self.diag.info("Told to shut down!")
        if self.useThreads:
            # Setting terminate will only work if we do it in the main thread:
            # otherwise the main thread might be in a blocking call at the time
            # So we reset the thread flag and send a new message
            self.useThreads = False
            sendSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sendSocket.connect(self.socket.getsockname())
            sendSocket.sendall("TERMINATE_SERVER\n")
            sendSocket.shutdown(2)
        else:
            self.terminate = True
        
    def process_request_thread(self, request, client_address, requestCount):
        # Copied from ThreadingMixin, more or less
        # We store the order things appear in so we know what order they should go in the file
        try:
            TrafficRequestHandler(requestCount, request, client_address, self)
            self.close_request(request)
        except: # pragma : no cover - interpreter code in theory...
            self.handle_error(request, client_address)
            self.close_request(request)

    def process_request(self, request, client_address):
        self.requestCount += 1
        if self.useThreads:
            """Start a new thread to process the request."""
            t = threading.Thread(target = self.process_request_thread, name="request",
                                 args = (request, client_address, self.requestCount))
            t.start()
        else:
            self.process_request_thread(request, client_address, self.requestCount)
        
    def findFilesAndLinks(self, path):
        if not os.path.exists(path):
            return []
        if os.path.isfile(path) or os.path.islink(path):
            return [ path ]

        paths = []
        for srcroot, srcdirs, srcfiles in os.walk(path):
            for fileToIgnore in self.filesToIgnore:
                if fileToIgnore in srcdirs:
                    srcdirs.remove(fileToIgnore)
                if fileToIgnore in srcfiles:
                    srcfiles.remove(fileToIgnore)
            for srcfile in srcfiles:
                paths.append(os.path.join(srcroot, srcfile))

            for srcdir in srcdirs:
                fullSrcPath = os.path.join(srcroot, srcdir)
                if os.path.islink(fullSrcPath):
                    paths.append(fullSrcPath)
        return paths

    def getLatestModification(self, path):
        if os.path.exists(path):
            statObj = os.stat(path)
            return statObj[stat.ST_MTIME], statObj[stat.ST_SIZE]
        else:
            return None, 0
        
    def addPossibleFileEdits(self, traffic):
        allEdits = traffic.findPossibleFileEdits()
        for file in allEdits:
            if file in self.topLevelForEdit:
                self.topLevelForEdit.remove(file)
            # Always move them to the beginning, most recent edits are most relevant
            self.topLevelForEdit.insert(0, file)

            # edit times aren't interesting when doing pure replay
            if not self.replayInfo.isActiveForAll():
                for subPath in self.findFilesAndLinks(file):                
                    modTime, modSize = self.getLatestModification(subPath)
                    self.fileEditData[subPath] = modTime, modSize
                    self.diag.info("Adding possible sub-path edit for " + subPath + " with mod time " +
                                   time.strftime("%d%b%H:%M:%S", time.localtime(modTime)) + " and size " + str(modSize))
        return len(allEdits) > 0
    
    def process(self, traffic, reqNo):
        if not self.replayInfo.isActiveFor(traffic):
            # If we're recording, check for file changes before we do
            # Must do this before as they may be a side effect of whatever it is we're processing
            for fileTraffic in self.getLatestFileEdits():
                self._process(fileTraffic, reqNo)

        self._process(traffic, reqNo)
        self.hasAsynchronousEdits |= traffic.makesAsynchronousEdits()
        self.recordFileHandler.requestComplete(reqNo)
        if not self.hasAsynchronousEdits:
            # Unless we've marked it as asynchronous we start again for the next traffic.
            self.topLevelForEdit = []
            self.fileEditData = OrderedDict()
        
    def _process(self, traffic, reqNo):
        self.diag.info("Processing traffic " + traffic.__class__.__name__)
        hasFileEdits = self.addPossibleFileEdits(traffic)
        responses = self.getResponses(traffic, hasFileEdits)
        shouldRecord = not traffic.enquiryOnly(responses)
        if shouldRecord:
            traffic.record(self.recordFileHandler, reqNo)
        for response in responses:
            self.diag.info("Response of type " + response.__class__.__name__ + " with text " + repr(response.text))
            if shouldRecord:
                response.record(self.recordFileHandler, reqNo)
            for chainResponse in response.forwardToDestination():
                self._process(chainResponse, reqNo)
            self.diag.info("Completed response of type " + response.__class__.__name__)            

    def getResponseClasses(self):
        return [ fileedittraffic.FileEditTraffic,
                 clientservertraffic.ClientSocketTraffic, clientservertraffic.ServerTraffic,
                 commandlinetraffic.StdoutTraffic, commandlinetraffic.StderrTraffic,
                 commandlinetraffic.SysExitTraffic, pythontraffic.PythonResponseTraffic ]

    def getResponses(self, traffic, hasFileEdits):
        if self.replayInfo.isActiveFor(traffic):
            self.diag.info("Replay active for current command")
            replayedResponses = []
            filesMatched = []
            for responseClass, text in self.replayInfo.readReplayResponses(traffic, self.getResponseClasses()):
                responseTraffic = self.makeResponseTraffic(traffic, responseClass, text, filesMatched)
                if responseTraffic:
                    replayedResponses.append(responseTraffic)
            return traffic.filterReplay(replayedResponses)
        else:
            trafficResponses = traffic.forwardToDestination()
            if hasFileEdits: # Only if the traffic itself can produce file edits do we check here
                return self.getLatestFileEdits() + trafficResponses
            else:
                return trafficResponses

    def getFileBeingEdited(self, givenName, fileType, filesMatched):
        # drop the suffix which is internal to TextTest
        fileName = givenName.split(".edit_")[0]
        bestMatch, bestScore = None, -1
        for editedFile in self.topLevelForEdit:
            if (fileType == "directory" and os.path.isfile(editedFile)) or \
               (fileType == "file" and os.path.isdir(editedFile)):
                continue

            editedName = os.path.basename(editedFile)
            if editedName == fileName and editedFile not in filesMatched:
                filesMatched.append(editedFile)
                bestMatch = editedFile
                break
            else:
                matchScore = self.getFileMatchScore(fileName, editedName)
                if matchScore > bestScore:
                    bestMatch, bestScore = editedFile, matchScore

        if bestMatch and bestMatch.startswith("/cygdrive"): # on Windows, paths may be referred to by cygwin path, handle this
            bestMatch = bestMatch[10] + ":" + bestMatch[11:]
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

    def makeResponseTraffic(self, traffic, responseClass, text, filesMatched):
        if responseClass is fileedittraffic.FileEditTraffic:
            fileName = text.strip()
            storedFile, fileType = fileedittraffic.FileEditTraffic.getFileWithType(fileName)
            if storedFile:
                editedFile = self.getFileBeingEdited(fileName, fileType, filesMatched)
                if editedFile:
                    self.diag.info("File being edited for '" + fileName + "' : will replace " + str(editedFile) + " with " + str(storedFile))
                    changedPaths = self.findFilesAndLinks(storedFile)
                    return fileedittraffic.FileEditTraffic(fileName, editedFile, storedFile, changedPaths, reproduce=True)
        else:
            return responseClass(text, traffic.responseFile)

    def findRemovedPath(self, removedPath):
        # We know this path is removed, what about its parents?
        # We want to store the most concise removal.
        parent = os.path.dirname(removedPath)
        if os.path.exists(parent):
            return removedPath
        else:
            return self.findRemovedPath(parent)

    def getLatestFileEdits(self):
        traffic = []
        removedPaths = []
        for file in self.topLevelForEdit:
            changedPaths = []
            newPaths = self.findFilesAndLinks(file)
            for subPath in newPaths:
                newEditInfo = self.getLatestModification(subPath)
                if newEditInfo != self.fileEditData.get(subPath):
                    changedPaths.append(subPath)
                    self.fileEditData[subPath] = newEditInfo

            for oldPath in self.fileEditData.keys():
                if (oldPath == file or oldPath.startswith(file + "/")) and oldPath not in newPaths:
                    removedPath = self.findRemovedPath(oldPath)
                    self.diag.info("Deletion of " + oldPath + "\n - registering " + removedPath)
                    removedPaths.append(oldPath)
                    if removedPath not in changedPaths:
                        changedPaths.append(removedPath)
                    
            if len(changedPaths) > 0:
                traffic.append(fileedittraffic.FileEditTraffic.makeRecordedTraffic(file, changedPaths))

        for path in removedPaths:
            del self.fileEditData[path]

        return traffic


class TrafficRequestHandler(StreamRequestHandler):
    parseDict = { "SUT_SERVER"           : clientservertraffic.ServerStateTraffic,
                  "SUT_COMMAND_LINE"     : commandlinetraffic.CommandLineTraffic,
                  "SUT_COMMAND_KILL"     : commandlinetraffic.CommandLineKillTraffic,
                  "SUT_PYTHON_CALL"      : pythontraffic.PythonFunctionCallTraffic,
                  "SUT_PYTHON_ATTR"      : pythontraffic.PythonAttributeTraffic,
                  "SUT_PYTHON_SETATTR"   : pythontraffic.PythonSetAttributeTraffic,
                  "SUT_PYTHON_IMPORT"    : pythontraffic.PythonImportTraffic }
    def __init__(self, requestNumber, *args):
        self.requestNumber = requestNumber
        StreamRequestHandler.__init__(self, *args)
        
    def handle(self):
        self.server.diag.info("Received incoming request...")
        text = self.rfile.read()
        self.server.diag.info("Request text : " + text)
        if text.startswith("TERMINATE_SERVER"):
            self.server.shutdown()
        else:
            traffic = self.parseTraffic(text)
            self.server.process(traffic, self.requestNumber)
            self.server.diag.info("Finished processing incoming request")

    def parseTraffic(self, text):
        for key in self.parseDict.keys():
            prefix = key + ":"
            if text.startswith(prefix):
                value = text[len(prefix):]
                return self.parseDict[key](value, self.wfile)
        return clientservertraffic.ClientSocketTraffic(text, self.wfile)

        
# The basic point here is to make sure that traffic appears in the record
# file in the order in which it comes in, not in the order in which it completes (which is indeterministic and
# may be wrong next time around)
class RecordFileHandler:
    def __init__(self, file):
        self.file = file
        self.recordingRequest = 1
        self.cache = {}
        self.completedRequests = []
        self.lock = threading.Lock()

    def requestComplete(self, requestNumber):
        self.lock.acquire()
        if requestNumber == self.recordingRequest:
            self.recordingRequestComplete()
        else:
            self.completedRequests.append(requestNumber)
        self.lock.release()

    def writeFromCache(self):
        text = self.cache.get(self.recordingRequest)
        if text:
            self.doRecord(text)
            del self.cache[self.recordingRequest]
            
    def recordingRequestComplete(self):
        self.writeFromCache()
        self.recordingRequest += 1
        if self.recordingRequest in self.completedRequests:
            self.recordingRequestComplete()

    def record(self, text, requestNumber):
        self.lock.acquire()
        if requestNumber == self.recordingRequest:
            self.writeFromCache()
            self.doRecord(text)
        else:
            self.cache.setdefault(requestNumber, "")
            self.cache[requestNumber] += text
        self.lock.release()

    def doRecord(self, text):
        writeFile = open(self.file, "a")
        writeFile.write(text)
        writeFile.flush()
        writeFile.close()
        
        
def main():
    parser = create_option_parser()
    options = parser.parse_args()[0] # no positional arguments
    defaults = commandlinetraffic.parseCmdDictionary(options.logdefaults, listvals=False)
    logging.config.fileConfig(options.logconfigfile, defaults)

    for cls in [ commandlinetraffic.CommandLineTraffic,
                 fileedittraffic.FileEditTraffic,
                 pythontraffic.PythonModuleTraffic ]:
        cls.configure(options)

    server = TrafficServer(options)
    server.run()
