
import os, sys, plugins, shutil, socket, subprocess

class SetUpTrafficHandlers(plugins.Action):
    REPLAY_ONLY = 0
    RECORD_ONLY = 1
    RECORD_NEW_REPLAY_OLD = 2
    def __init__(self, recordSetting):
        self.recordSetting = recordSetting
        self.trafficServerProcess = None
        libexecDir = plugins.installationDir("libexec")
        self.siteCustomizeFile = os.path.join(libexecDir, "sitecustomize.py")
        
    def __call__(self, test):
        pythonCustomizeFiles = test.getAllPathNames("testcustomize.py") 
        pythonCoverage = test.hasEnvironment("COVERAGE_PROCESS_START")
        if test.app.usesTrafficMechanism() or pythonCoverage or pythonCustomizeFiles:
            replayFile = test.getFileName("traffic")
            rcFiles = test.getAllPathNames("capturemockrc")
            serverActive = self.recordSetting != self.REPLAY_ONLY or replayFile is not None
            if serverActive or pythonCoverage or pythonCustomizeFiles:
                self.setUpIntercepts(test, replayFile, rcFiles, pythonCoverage, pythonCustomizeFiles)

    def setUpIntercepts(self, test, replayFile, rcFiles, pythonCoverage, pythonCustomizeFiles):
        interceptDir = test.makeTmpFileName("traffic_intercepts", forComparison=0)
        pathVars = self.makeIntercepts(interceptDir, rcFiles, replayFile,
                                       pythonCoverage, pythonCustomizeFiles)
        if rcFiles:
            # Environment which the server should get
            test.setEnvironment("CAPTUREMOCK_MODE", str(self.recordSetting))
            if replayFile:
                test.setEnvironment("CAPTUREMOCK_FILE", replayFile)
            self.trafficServerProcess = self.makeTrafficServer(test, rcFiles, replayFile)
            address = self.trafficServerProcess.stdout.readline().strip()
            # And environment it shouldn't get...
            test.setEnvironment("CAPTUREMOCK_PROCESS_START", ",".join(rcFiles))
            test.setEnvironment("CAPTUREMOCK_SERVER", address) # Address of TextTest's server for recording client/server traffic

        for pathVar in pathVars:
            # Change test environment to pick up the intercepts
            test.setEnvironment(pathVar, interceptDir + os.pathsep + test.getEnvironment(pathVar, ""))

    def getTrafficServerLogDefaults(self):
        return "TEXTTEST_CWD=" + os.getcwd().replace("\\", "/") + ",TEXTTEST_PERSONAL_LOG=" + os.getenv("TEXTTEST_PERSONAL_LOG")

    def getTrafficServerLogConfig(self):
        allPaths = plugins.findDataPaths([ "logging.traffic" ], dataDirName="log", includePersonal=True)
        return allPaths[-1]
        
    def makeTrafficServer(self, test, rcFiles, replayFile):
        recordFile = test.makeTmpFileName("traffic")
        recordEditDir = test.makeTmpFileName("file_edits", forComparison=0)
        cmdArgs = [ "capturemock_server", "--rcfiles", ",".join(rcFiles),
                    "-r", recordFile, "-F", recordEditDir,
                    "-l", self.getTrafficServerLogDefaults(),
                    "-L", self.getTrafficServerLogConfig() ]
                    
        filesToIgnore = test.getCompositeConfigValue("test_data_ignore", "file_edits")
        if filesToIgnore:
            cmdArgs += [ "-i", ",".join(filesToIgnore) ]
            
        if replayFile and self.recordSetting != self.RECORD_ONLY:
            cmdArgs += [ "-p", replayFile ]
            replayEditDir = test.getFileName("file_edits")
            if replayEditDir:
                cmdArgs += [ "-f", replayEditDir ]
            if self.recordSetting == self.RECORD_NEW_REPLAY_OLD:
                cmdArgs.append("--filter-replay-file")

        return subprocess.Popen(cmdArgs, env=test.getRunEnvironment(), universal_newlines=True,
                                cwd=test.getDirectory(temporary=1), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    
    def makeIntercepts(self, interceptDir, rcFiles, replayFile, pythonCoverage, pythonCustomizeFiles):
        pathVars = []
        if rcFiles:
            from capturemock import makePathIntercepts
            if makePathIntercepts(rcFiles, interceptDir, replayFile, self.recordSetting):
                pathVars.append("PATH")

        if pythonCustomizeFiles:
            self.interceptOwnModule(pythonCustomizeFiles[-1], interceptDir) # most specific
                
        useSiteCustomize = rcFiles or pythonCoverage or pythonCustomizeFiles
        if useSiteCustomize:
            self.interceptOwnModule(self.siteCustomizeFile, interceptDir)
            pathVars.append("PYTHONPATH")
        return pathVars

    def interceptOwnModule(self, moduleFile, interceptDir):
        self.intercept(interceptDir, os.path.basename(moduleFile), [ moduleFile ])
    
    def intercept(self, interceptDir, cmd, trafficFiles):
        interceptName = os.path.join(interceptDir, cmd)
        plugins.ensureDirExistsForFile(interceptName)
        for trafficFile in trafficFiles:
            if os.name == "posix":
                os.symlink(trafficFile, interceptName)
            else:
                shutil.copy(trafficFile, interceptName)


class TerminateTrafficServer(plugins.Action):
    def __init__(self, setupHandler):
        self.setupHandler = setupHandler

    def __call__(self, test):
        if self.setupHandler.trafficServerProcess:
            servAddr = test.getEnvironment("CAPTUREMOCK_SERVER")
            if servAddr:
                self.sendTerminationMessage(servAddr)
            self.writeServerErrors(self.setupHandler.trafficServerProcess)
            self.setupHandler.trafficServerProcess = None

    def sendTerminationMessage(self, servAddr):
        sendSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        host, port = servAddr.split(":")
        serverAddress = (host, int(port))
        try:
            sendSocket.connect(serverAddress)
            sendSocket.sendall("TERMINATE_SERVER\n")
            sendSocket.shutdown(2)
        except socket.error: # pragma: no cover - should be unreachable, just for robustness
            plugins.log.info("Could not send terminate message to traffic server at " + servAddr + ", seemed not to be running anyway.")
        
    def writeServerErrors(self, process):
        err = process.communicate()[1]
        if err:
            sys.stderr.write("Error from Traffic Server :\n" + err)
        

class ModifyTraffic(plugins.ScriptWithArgs):
    # For now, only bother with the client server traffic which is mostly what needs tweaking...
    scriptDoc = "Apply a script to all the client server data"
    def __init__(self, args):
        argDict = self.parseArguments(args, [ "script", "types" ])
        self.script = argDict.get("script")
        self.trafficTypes = plugins.commasplit(argDict.get("types", "CLI,SRV"))
    def __repr__(self):
        return "Updating traffic in"
    def __call__(self, test):
        fileName = test.getFileName("traffic")
        if not fileName:
            return

        self.describe(test)
        try:
            newTrafficTexts = [ self.getModified(t, test.getDirectory()) for t in self.readIntoList(fileName) ]
        except plugins.TextTestError, e:
            print str(e).strip()
            return

        newFileName = fileName + "tmpedit"
        newFile = open(newFileName, "w")
        for trafficText in newTrafficTexts:
            self.write(newFile, trafficText) 
        newFile.close()
        shutil.move(newFileName, fileName)
        
    def readIntoList(self, fileName):
        # Copied from traffic server ReplayInfo, easier than trying to reuse it
        trafficList = []
        currTraffic = ""
        for line in open(fileName, "rU").xreadlines():
            if line.startswith("<-") or line.startswith("->"):
                if currTraffic:
                    trafficList.append(currTraffic)
                currTraffic = ""
            currTraffic += line
        if currTraffic:
            trafficList.append(currTraffic)
        return trafficList
            
    def getModified(self, fullLine, dir):
        trafficType = fullLine[2:5]
        if trafficType in self.trafficTypes:
            proc = subprocess.Popen([ self.script, fullLine[6:]], cwd=dir,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=os.name=="nt")
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


class ConvertToCaptureMock(plugins.Action):
    def setUpApplication(self, app):
        newFile = os.path.join(app.getDirectory(), "capturemockrc")
        from ConfigParser import ConfigParser
        from ordereddict import OrderedDict
        parser = ConfigParser(dict_type=OrderedDict)
        multiThreads = app.getConfigValue("collect_traffic_use_threads") == "true"
        if not multiThreads:
            parser.add_section("general")
            parser.set("general", "server_multithreaded", multiThreads)
        cmdTraffic = app.getCompositeConfigValue("collect_traffic", "asynchronous")
        if cmdTraffic:
            parser.add_section("command line")
            parser.set("command line", "intercepts", ",".join(cmdTraffic))
            async = app.getConfigValue("collect_traffic").get("asynchronous", [])
            for cmd in cmdTraffic:
                env = app.getConfigValue("collect_traffic_environment").get("cmd")
                cmdAsync = cmd in async
                if env or cmdAsync:
                    parser.add_section(cmd)
                    if env:
                        parser.set(cmd, "environment", ",".join(env))
                    if cmdAsync:
                        parser.set(cmd, "asynchronous", cmdAsync)

        envVars = app.getConfigValue("collect_traffic_environment").get("default")
        if envVars:
            parser.set("command line", "environment", ",".join(envVars))

        pyTraffic = app.getConfigValue("collect_traffic_python")
        if pyTraffic:
            parser.add_section("python")
            ignore_callers = app.getConfigValue("collect_traffic_python_ignore_callers")
            parser.set("python", "intercepts", ",".join(pyTraffic))
            if ignore_callers:
                parser.set("python", "ignore_callers", ",".join(ignore_callers))

        print "Wrote file at", newFile
        parser.write(open(newFile, "w"))
