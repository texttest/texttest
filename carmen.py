#!/usr/local/bin/python

helpDescription = """
The Carmen configuration is based on the LSF configuration. Its default operation is therefore to
submit all jobs to LSF, rather than run them locally.

It determines the queue as follows: if a test takes less than 10 minutes, it will be submitted
to short_<arch>, where <arch> is the architecture where TextTest was called from. If it takes
more than 2 hours, it will go to idle_<arch>. If neither of these, or if the specified queue
does not exist, it will be submitted to the queue <arch>.

The Carmen configuration is also somewhat architecture-conscious in other ways. It reads the required config file
entry "default_architecture", to determine where the basic results are created. It also reads
"supported_architecture" to determine if the currently run architecture is OK. If the supported_architecture
list is present and the current one does not match, the configuration will exit with an error.

Running on an architecture other than default_architecture will cause the test suite to automatically
use the version <arch><version>, where <version> was the original version it was running. Hopefully this
will soon be replaced with a version hierarchy, when the framework can handle that.
"""

helpOptions = """
-u <text>  - select only user suites whose name contains <text>. A user suite is defined as a test suite which
             defines CARMUSR locally.

-lprof     - Run LProf on the test concerned. This will automatically profile the job and generate the textual
             data in the test directory, in a file called lprof.<app>. It is proposed to automatically generate
             the graphical information also

-rulecomp  - Instead of running normally, compile all rule sets that are relevant to the tests selected (if any)

-build <t> - Prior to running any tests, build in the appropriate location specified by <t>. This is specified in
             the config file as the entries "build_xxx". So if my config file contains the lines
             build_codebase:Rules_and_Reports
             build_codebase:Optimization
             then specifying -build codebase will cause a build (= gmake) to be run in these places (relative to checkout
             of course), before anything else is done.

             It is expected that this option is used on linux. Note that in addition, a build is kicked off in parallel
             on sparc (sundance) and parisc_2_0 (ramechap), which run in the background while your tests run,
             and are reported on at the end. This should ensure that they don't delay the appearance of test information.
"""

batchInfo = """             <bname>_architecture, these entries form a list and ensure that only runs on the architectures listed are accepted.
             If the list is empty, all architectures are allowed.

             The reason for this is that the Carmen nightjob will run TextTest on all versions and on all architectures. It
             will do so with the batch session name "nightjob" on Monday to Thursday nights, and "wkendjob" on Friday night.
             If you do not want this, you should therefore restrict or disable these session names in your config file, as
             indicated above.

             Note also that the "nightjob" sessions are killed at 8am each morning, while the "wkendjob" sessions are killed
             at 8am on Monday morning. This can cause some tests to be reported as "unfinished" in your batch report."""

import lsf, default, performance, os, string, shutil, stat, plugins, batch, sys, signal, respond

def getConfig(optionMap):
    return CarmenConfig(optionMap)

def isUserSuite(suite):
    return suite.environment.has_key("CARMUSR")

def isCompressed(path):
    magic = open(path).read(2)
    if magic[0] == chr(0x1f) and magic[1] == chr(0x9d):
        return 1
    else:
        return 0

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
    def isNightJob(self):
        batchSession = self.optionValue("b")
        return batchSession == "nightjob" or batchSession == "wkendjob"
    def interpretVersion(self, app, versionString):
        defaultArch = app.getConfigValue("default_architecture")
        if architecture == defaultArch:
            return versionString
        else:
            supportedArchs = app.getConfigList("supported_architecture")
            # In batch mode, don't throw exceptions. Let the Batch Filter deal with it
            if len(supportedArchs) and not architecture in supportedArchs and not self.optionMap.has_key("b"):
                raise "Unsupported architecture " + architecture + "!!!"
            else:
                print "Non-default architecture: using version", architecture + versionString
                return architecture + versionString
    def printHelpOptions(self, builtInOptions):
        print lsf.helpOptions + batchInfo
        default.Config.printHelpOptions(self, builtInOptions)
        print "(Carmen-specific options...)"
        print helpOptions
    def printHelpDescription(self):
        print helpDescription, lsf.lsfGeneral, performance.helpDescription, respond.helpDescription 
    
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
            if not os.path.isdir(os.environ["CARMTMP"]):
                print "CARMTMP", os.environ["CARMTMP"], "did not exist, attempting to create it"
                os.mkdir(os.environ["CARMTMP"])
            ruleset.backup()
            compiler = os.path.join(os.environ["CARMSYS"], "bin", "crc_compile")
            commandLine = compiler + " " + self.raveName + " " + self.modeString + " -archs " + architecture + " " + ruleset.sourceFile
            self.rulesCompiled.append(ruleset.name)
            returnValue = os.system(commandLine)
            if returnValue:
                raise EnvironmentError, "Failed to build ruleset " + ruleset.name
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
        return self.name != None and os.path.isfile(self.sourceFile)
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
        self.buildRemote("sundance", "sparc", app) 
        self.buildRemote("ramechap", "parisc_2_0", app)
    def buildLocal(self, absPath, app):
        os.chdir(absPath)
        print "Building", app, "in", absPath, "..."
        buildFile = "build.default"
        os.system("gmake >& " + buildFile)
        if self.checkBuildFile(buildFile):
            raise "Product " + repr(app) + " did not build, exiting"
        print "Product", app, "built correctly in", absPath
        os.remove(buildFile)
        os.system("gmake install CARMSYS=" + os.environ["CARMSYS"] + " >& /dev/null")
        print "Making install from", absPath ,"to", os.environ["CARMSYS"]
    def buildRemote(self, machine, arch, app):
        print "Building remotely in parallel on " + machine + " ..."
        processId = os.fork()
        if processId == 0:
            result = self.buildRemoteInChild(machine, arch, app)
            sys.exit(result)
        else:
            tuple = processId, arch
            self.childProcesses.append(tuple)
    def buildRemoteInChild(self, machine, arch, app):
        sys.stdin = open("/dev/null")
        signal.signal(1, self.killBuild)
        signal.signal(2, self.killBuild)
        signal.signal(15, self.killBuild) 
        for relPath in app.getConfigList("build_codebase"):
            absPath = app.makeAbsPath(relPath)
            if os.path.isdir(absPath):    
                commandLine = "cd " + absPath + "; gmake >& build." + arch
                os.system("rsh " + machine + " '" + commandLine + "' < /dev/null")
        return 0            
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
            # In theory we should be able to trust the status. In practice, it seems to be 0, even when the build failed.
            for relPath in app.getConfigList("build_codebase"):
                absPath = app.makeAbsPath(relPath)
                self.checkBuild(arch, absPath)
    def checkBuild(self, arch, absPath):
        if os.path.isdir(absPath):
            os.chdir(absPath)
            fileName = "build." + arch
            result = self.builder.checkBuildFile(fileName)
            resultString = " SUCCEEDED!"
            if result:
                resultString = " FAILED!"
            print "Build on " + arch + " in " + absPath + resultString
            if result == 0:
                os.remove(fileName)

def ensureDirectoryExists(path):
    if len(path) == 0:
        return
    if os.path.isdir(path):
        return
    h, t = os.path.split(path)
    ensureDirectoryExists(h)
    if len(t) > 0:
        os.mkdir(path)

    
    
