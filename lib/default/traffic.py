
import os, plugins, shutil, subprocess

class SetUpTrafficHandlers(plugins.Action):
    def __init__(self, recordSetting):
        self.recordSetting = recordSetting
        libexecDir = plugins.installationDir("libexec")
        self.siteCustomizeFile = os.path.join(libexecDir, "sitecustomize.py")
        
    def __call__(self, test):
        pythonCustomizeFiles = test.getAllPathNames("testcustomize.py") 
        pythonCoverage = test.hasEnvironment("COVERAGE_PROCESS_START")
        if test.app.usesTrafficMechanism() or pythonCoverage or pythonCustomizeFiles:
            replayFile = test.getFileName("traffic")
            rcFiles = test.getAllPathNames("capturemockrc")
            if rcFiles or pythonCoverage or pythonCustomizeFiles:
                self.setUpIntercepts(test, replayFile, rcFiles, pythonCoverage, pythonCustomizeFiles)

    def setUpIntercepts(self, test, replayFile, rcFiles, pythonCoverage, pythonCustomizeFiles):
        interceptDir = test.makeTmpFileName("traffic_intercepts", forComparison=0)
        captureMockActive = False
        if rcFiles:
            captureMockActive = self.setUpCaptureMock(test, interceptDir, replayFile, rcFiles)
            
        if pythonCustomizeFiles:
            self.intercept(pythonCustomizeFiles[-1], interceptDir) # most specific
                
        useSiteCustomize = captureMockActive or pythonCoverage or pythonCustomizeFiles
        if useSiteCustomize:
            self.intercept(self.siteCustomizeFile, interceptDir)
            for var in [ "PYTHONPATH", "JYTHONPATH" ]:
                test.setEnvironment(var, interceptDir + os.pathsep + test.getEnvironment(var, ""))

    def setUpCaptureMock(self, test, interceptDir, replayFile, rcFiles):
        recordFile = test.makeTmpFileName("traffic")
        recordEditDir = test.makeTmpFileName("file_edits", forComparison=0)
        replayEditDir = test.getFileName("file_edits") if replayFile else None
        sutDirectory = test.getDirectory(temporary=1)
        from capturemock import capturemock
        return capturemock(rcFiles, interceptDir, self.recordSetting, replayFile,
                           replayEditDir, recordFile, recordEditDir, sutDirectory,
                           test.environment)
            
    def intercept(self, moduleFile, interceptDir):
        interceptName = os.path.join(interceptDir, os.path.basename(moduleFile))
        plugins.ensureDirExistsForFile(interceptName)
        self.copyOrLink(moduleFile, interceptName)

    def copyOrLink(self, src, dst):
        if os.name == "posix":
            os.symlink(src, dst)
        else:
            shutil.copy(src, dst)


class TerminateTrafficHandlers(plugins.Action):
    def __call__(self, test):
        try:
            from capturemock import terminate
            terminate()
        except ImportError:
            pass
                

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
    def convert(self, confObj, newFile):
        from ConfigParser import ConfigParser
        from ordereddict import OrderedDict
        parser = ConfigParser(dict_type=OrderedDict)
        multiThreads = confObj.getConfigValue("collect_traffic_use_threads") == "true"
        if not multiThreads:
            parser.add_section("general")
            parser.set("general", "server_multithreaded", multiThreads)
        cmdTraffic = confObj.getCompositeConfigValue("collect_traffic", "asynchronous")
        if cmdTraffic:
            parser.add_section("command line")
            parser.set("command line", "intercepts", ",".join(cmdTraffic))
            async = confObj.getConfigValue("collect_traffic").get("asynchronous", [])
            for cmd in cmdTraffic:
                env = confObj.getConfigValue("collect_traffic_environment").get(cmd)
                cmdAsync = cmd in async
                if env or cmdAsync:
                    parser.add_section(cmd)
                    if env:
                        parser.set(cmd, "environment", ",".join(env))
                    if cmdAsync:
                        parser.set(cmd, "asynchronous", cmdAsync)

        envVars = confObj.getConfigValue("collect_traffic_environment").get("default")
        if envVars:
            parser.set("command line", "environment", ",".join(envVars))

        pyTraffic = confObj.getConfigValue("collect_traffic_python")
        if pyTraffic:
            parser.add_section("python")
            ignore_callers = confObj.getConfigValue("collect_traffic_python_ignore_callers")
            parser.set("python", "intercepts", ",".join(pyTraffic))
            if ignore_callers:
                parser.set("python", "ignore_callers", ",".join(ignore_callers))

        if len(parser.sections()) > 0: # don't write empty files
            print "Wrote file at", newFile
            parser.write(open(newFile, "w"))

    def setUpApplication(self, app):
        newFile = os.path.join(app.getDirectory(), "capturemockrc" + app.versionSuffix())
        self.convert(app, newFile)

    def __call__(self, test):
        self.checkTest(test)

    def setUpSuite(self, suite):
        self.checkTest(suite)

    def checkTest(self, test):
        configFile = test.getFileName("config")
        if configFile:
            newFile = os.path.join(test.getDirectory(), "capturemockrc")
            self.convert(test, newFile)
