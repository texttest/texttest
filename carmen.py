#!/usr/local/bin/python
import lsf, default, performance, os, string, shutil, stat, plugins, batch, sys, signal

def getConfig(optionMap):
    return CarmenConfig(optionMap)

def isUserSuite(suite):
    return suite.environment.has_key("CARMUSR")

class UserFilter(default.TextFilter):
    def acceptsTestSuite(self, suite):
        if isUserSuite(suite):
            return self.containsText(suite)
        else:
            return 1

architecture = os.popen("arch").readline()[:-1]

class CarmenBatchFilter(batch.BatchFilter):
    def acceptsApplication(self, app):
        if self.acceptsArchitecture(app):
            return batch.BatchFilter.acceptsApplication(self, app)
        else:
            print "Rejected application", app, "on architecture", architecture 
            return 0
    def acceptsArchitecture(self, app):
        allowedArchs = app.getConfigList(self.batchSession + "_architecture")
        return len(allowedArchs) == 0 or architecture in allowedArchs

class CarmenConfig(lsf.LSFConfig):
    def getOptionString(self):
        return "u:" + lsf.LSFConfig.getOptionString(self)
    def getFilterList(self):
        filters = lsf.LSFConfig.getFilterList(self)
        self.addFilter(filters, "u", UserFilter)
        return filters
    def batchFilterClass(self):
        return CarmenBatchFilter
    def getActionSequence(self):
        if self.optionMap.has_key("rulecomp"):
            return [ self.getRuleBuilder(0) ]
        else:
            builder = self.getAppBuilder()
            return [ builder, self.getRuleBuilder(1) ] + lsf.LSFConfig.getActionSequence(self) + [ self.getBuildChecker(builder) ]
    def getRuleBuilder(self, neededOnly):
        if neededOnly:
            return plugins.Action()
        else:
            return CompileRules(self.getRuleSetName)
    def getAppBuilder(self):
        if self.optionMap.has_key("build"):
            return BuildCode(self.optionValue("build"))
        else:
            return plugins.Action()
    def getBuildChecker(self, builder):
        if self.optionMap.has_key("build"):
            return CheckBuild(builder)
        else:
            return plugins.Action()
    def getTestRunner(self):
        if self.optionMap.has_key("lprof"):
            subActions = [ lsf.LSFConfig.getTestRunner(self), WaitForDispatch(), RunLProf() ]
            return plugins.CompositeAction(subActions)
        else:
            return lsf.LSFConfig.getTestRunner(self)
    def findLSFQueue(self, test):
        if architecture == "powerpc" or architecture == "parisc_2_0":
            return architecture
        cpuTime = performance.getTestPerformance(test)
        if cpuTime < 10:
            return "short_" + architecture
        elif cpuTime < 120:
            return architecture
        else:
            return "idle_" + architecture
    def interpretVersion(self, app, versionString):
        defaultArch = app.getConfigValue("default_architecture")
        if architecture == defaultArch:
            return versionString
        else:
            supportedArchs = app.getConfigList("supported_architecture")
            if len(supportedArchs) and not architecture in supportedArchs:
                raise "Unsupported architecture " + architecture + "!!!"
            else:
                print "Non-default architecture: using version", architecture + versionString
                return architecture + versionString
    
def getRaveName(test):
    return test.app.getConfigValue("rave_name")

class CompileRules(plugins.Action):
    def __init__(self, getRuleSetName, modeString = "-optimize", filter = None):
        self.rulesCompiled = []
        self.raveName = None
        self.getRuleSetName = getRuleSetName
        self.modeString = modeString
        self.filter = filter
    def __repr__(self):
        return "Compiling rules for"
    def __call__(self, test):
        ruleset = RuleSet(self.getRuleSetName(test), self.raveName)
        if ruleset.isValid() and not ruleset.name in self.rulesCompiled:
            self.describe(test, " - ruleset " + ruleset.name)
            ruleset.backup()
            compiler = os.path.join(os.environ["CARMSYS"], "bin", "crc_compile")
            commandLine = compiler + " " + self.raveName + " " + self.modeString + " -archs " + architecture + " " + ruleset.sourceFile
            self.rulesCompiled.append(ruleset.name)
            returnValue = os.system(commandLine)
            if returnValue:
                raise "Failed to build ruleset, exiting"
            if self.modeString == "-debug":
                ruleset.moveDebugVersion()
    def setUpSuite(self, suite):
        self.describe(suite)
        self.rulesCompiled = []
        if self.raveName == None:
            self.raveName = getRaveName(suite)
    def getFilter(self):
        return self.filter
    
class RuleSet:
    def __init__(self, ruleSetName, raveName):
        self.name = ruleSetName
        if self.name != None:
            self.targetFile = os.path.join(os.environ["CARMTMP"], "crc", "rule_set", string.upper(raveName), architecture, self.name)
            self.sourceFile = os.path.join(os.environ["CARMUSR"], "crc", "source", self.name)
    def isValid(self):
        return self.name != None
    def isCompiled(self):
        return os.path.isfile(self.targetFile)
    def backup(self):
        if self.isCompiled():
            shutil.copyfile(self.targetFile, self.targetFile + ".bak")
    def moveDebugVersion(self):
        debugVersion = self.targetFile + "_g"
        if os.path.isfile(debugVersion):
            os.remove(self.targetFile)
            os.rename(debugVersion, self.targetFile)
        
class UpdatedLocalRulesetFilter(plugins.Filter):
    def __init__(self, getRuleSetName, libraryFile):
        self.getRuleSetName = getRuleSetName
        self.libraryFile = libraryFile
    def acceptsTestCase(self, test):
        ruleset = RuleSet(self.getRuleSetName(test), getRaveName(test))
        if not ruleset.isValid():
            return 0
        if not ruleset.isCompiled():
            return 1
        return self.modifiedTime(ruleset.targetFile) < self.modifiedTime(os.path.join(os.environ["CARMSYS"], self.libraryFile))
    def acceptsTestSuite(self, suite):
        if not isUserSuite(suite):
            return 1

        carmtmp = suite.environment["CARMTMP"]
        return carmtmp.find("$CARMSYS") != -1 or carmtmp.find("${CARMSYS}") != -1
    def modifiedTime(self, filename):
        return os.stat(filename)[stat.ST_MTIME]

class WaitForDispatch(lsf.Wait):
    def __init__(self):
        self.eventName = "dispatch"
    def checkCondition(self, job):
        return len(job.getProcessIds()) >= 4

class RunLProf(plugins.Action):
    def __repr__(self):
        return "Running LProf profiler on"
    def __call__(self, test):
        job = lsf.LSFJob(test)
        executionMachine = job.getExecutionMachine()
        self.describe(test, ", executing on " + executionMachine)
        processId = job.getProcessIds()[-1]
        runLine = "cd " + os.getcwd() + "; /users/lennart/bin/gprofile " + processId
        outputFile = "prof." + processId
        processLine = "/users/lennart/bin/process_gprof " + outputFile + " > lprof." + test.app.name
        removeLine = "rm " + outputFile
        commandLine = "rsh " + executionMachine + " '" + runLine + "; " + processLine + "; " + removeLine + "'"
        os.system(commandLine)

class BuildCode(plugins.Action):
    def __init__(self, target):
        self.target = target
        self.childProcesses = []
    def setUpApplication(self, app):
        for relPath in app.getConfigList("build_" + self.target):
            absPath = app.makeAbsPath(relPath)
            if os.path.isdir(absPath):
                self.buildLocal(absPath, app)
            else:
                print "Not building in", absPath, "which doesn't exist!"
        for relPath in app.getConfigList("build_codebase"):
            absPath = app.makeAbsPath(relPath)
            if os.path.isdir(absPath):
                self.buildRemote("sundance", "sparc", absPath) 
                self.buildRemote("ramechap", "parisc_2_0", absPath)
            else:
                print "Not building in", absPath, "which doesn't exist!"
    def buildLocal(self, absPath, app):
        os.chdir(absPath)
        print "Building", app, "in", absPath, "..."
        buildFile = "build.default"
        os.system("gmake >& " + buildFile)
        if self.checkBuildFile(buildFile):
            raise "Product " + repr(app) + " did not build, exiting"
        print "Product", app, "built correctly in", absPath
        os.remove(buildFile)
        os.system("gmake install CARMSYS=" + os.environ["CARMSYS"] + " >& build.install")
        print "Making install from", absPath ,"to", os.environ["CARMSYS"]
        sys.exit(1)
    def buildRemote(self, machine, arch, absPath):
        print "Building remotely in parallel on " + machine + "..."
        processId = os.fork()
        if processId == 0:
            sys.stdin = open("/dev/null")
            signal.signal(1, self.killBuild)
            signal.signal(2, self.killBuild)
            signal.signal(15, self.killBuild)
            commandLine = "cd " + absPath + "; gmake >& build." + arch
            os.system("rsh " + machine + " '" + commandLine + "' < /dev/null")
            os.chdir(absPath)
            sys.exit(self.checkBuildFile("build." + arch))
        else:
            tuple = processId, arch
            self.childProcesses.append(tuple)
    def getAbsPath(self, app, target):
        relPath = app.getConfigValue("build_" + target)
        return app.makeAbsPath(relPath)
    def checkBuildFile(self, buildFile):
        for line in open(buildFile).xreadlines():
            if line.find("***") != -1 and line.find("Error") != -1:
                return 1
        return 0
    def killBuild(self):
        print "Terminating remote build."

class CheckBuild(plugins.Action):
    def __init__(self, builder):
        self.builder = builder
    def setUpApplication(self, app):
        print "Waiting for remote builds..." 
        for process, arch in self.builder.childProcesses:
            pid, status = os.waitpid(process, 0)
            if status:
                print "Build on", arch, "FAILED!"
            else:
                print "Build on", arch, "SUCCEEDED!"
                absPath = self.builder.getAbsPath(app, "codebase")
                os.remove(os.path.join(absPath, "build." + arch))
