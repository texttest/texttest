#!/usr/local/bin/python

helpDescription = """
The Carmen configuration is based on the LSF configuration. Its default operation is therefore to
submit all jobs to LSF, rather than run them locally.

Execution architectures are now determined by versions, not by which architecture TextTest is run on as before.
If any version is specified which is the name of a Carmen architecture, that architecture will be used.
Otherwise the entry "default_architecture" is read from the config file and used. "supported_architecture" is now
deprecated.

It determines the queue as follows: if a test takes less than 10 minutes, it will be submitted
to short_<arch>, where <arch> is the architecture as determined above. If it takes
more than 2 hours, it will go to idle_<arch>. If neither of these, or if the specified queue
does not exist, it will be submitted to the queue <arch>. If however the environment LSF_QUEUE_PREFIX is set
then that <prefix>_<arch> will be used if arch is i386_linux or sparc.
"""

helpOptions = """
-u <texts> - select only user suites whose name contains one of the strings in <texts>. <texts> is interpreted as a
             comma-separated list. A user suite is defined as a test suite which defines CARMUSR locally.

-lprof     - Run LProf on the test concerned. This will automatically profile the job and generate the textual
             data in the test directory, in a file called lprof.<app>. It is proposed to automatically generate
             the graphical information also

-rulecomp  - Build all rulesets before running the tests

-rulecomp clean
           - As '-rulecomp' above, but will attempt to remove ruleset files first, such that ruleset is
             rebuilt 'from scratch'. This is sometimes useful when the RAVE compiler has depenedency bugs

-build <t> - Prior to running any tests, build in the appropriate location specified by <t>. This is specified in
             the config file as the entries "build_xxx". So if my config file contains the lines
             build_codebase:Rules_and_Reports
             build_codebase:Optimization
             then specifying -build codebase will cause a build (= gmake) to be run in these places (relative to checkout
             of course), before anything else is done.

             It is expected that this option is used on linux. Note that in addition, a build is kicked off in parallel
             on sparc (sundance) and parisc_2_0 (ramechap), which run in the background while your tests run,
             and are reported on at the end. This should ensure that they don't delay the appearance of test information.

-buildl <t>
           - As above, but no parallel builds are done.

-skip      - Don't build any rulesets before running the tests.

-debug     - Compile a debug ruleset, and rename it so that it is used instead of the normal one.
"""

batchInfo = """
             Note that, because the Carmen configuration converts infers architectures from versions, you can also
             enable and disable architectures using <bname>_version.

             The Carmen nightjob will run TextTest on all versions and on all architectures. It will do so with the batch
             session name "nightjob" on Monday to Thursday nights, and "wkendjob" on Friday night.
             If you do not want this, you should therefore restrict or disable these session names in your config file, as
             indicated above.

             Note also that the "nightjob" sessions are killed at 8am each morning, while the "wkendjob" sessions are killed
             at 8am on Monday morning. This can cause some tests to be reported as "unfinished" in your batch report."""

helpScripts = """carmen.TraverseCarmUsers   - Traverses all CARMUSR's associated with the selected tests,
                             and executes the command specified by argument. Be careful to quote the command
                             if you use options, otherwise texttest will try to interpret the options.
                             Example: texttest -s carmen.TraverseCarmUsers "pwd". This will
                             display the path of all CARMUSR's in the test suite.
                                              
                             If the argument findchanges=<changed within minutes> is given,
                             a find command is issued, that prints all files that has changed within
                             the specified time. Default time is 1440 minutes.
"""

import lsf, default, performance, os, string, shutil, stat, plugins, batch, sys, signal, respond, time, predict

# Extra states for tests to be in!
RULESET_NOT_BUILT = -1

def getConfig(optionMap):
    return CarmenConfig(optionMap)

def isUserSuite(suite):
    return suite.environment.has_key("CARMUSR")

architectures = [ "i386_linux", "sparc", "sparc_64", "powerpc", "parisc_2_0", "parisc_1_1", "i386_solaris" ]
def getArchitecture(app):
    for version in app.versions:
        if version in architectures:
            return version
    return app.getConfigValue("default_architecture")

class UserFilter(default.TextFilter):
    def acceptsTestSuite(self, suite):
        if isUserSuite(suite):
            return self.containsText(suite)
        else:
            return 1

class CarmenConfig(lsf.LSFConfig):
    def addToOptionGroup(self, group):
        lsf.LSFConfig.addToOptionGroup(self, group)
        if group.name.startswith("Select"):
            group.addOption("u", "CARMUSRs containing")
        elif group.name.startswith("What"):
            group.addSwitch("rulecomp", "Build all rulesets")
            group.addSwitch("skip", "Build no rulesets")
        elif group.name.startswith("How"):
            group.addSwitch("debug", "Use debug rulesets")
            group.addSwitch("raveexp", "Run with RAVE Explorer")
            group.addSwitch("lprof", "Run with LProf profiler")
        elif group.name.startswith("Side"):
            group.addOption("build", "Build application target")
            group.addOption("buildl", "Build application target locally")        
    def getArgumentOptions(self):
        options = lsf.LSFConfig.getArgumentOptions(self)
        return options
    def getSwitches(self):
        switches = lsf.LSFConfig.getSwitches(self)
        return switches
    def getFilterList(self):
        filters = lsf.LSFConfig.getFilterList(self)
        self.addFilter(filters, "u", UserFilter)
        return filters
    def getActionSequence(self, useGui):
        # Drop the write directory maker, in order to insert the rulebuilder in between it and the test runner
        return [ self.getAppBuilder(), self.getWriteDirectoryMaker(), self.getRuleBuilder() ] + \
                 lsf.LSFConfig._getActionSequence(self, useGui, makeDirs = 0)
    def getRuleCleanup(self):
        return CleanupRules(self.getRuleSetName)
    def isRaveRun(self):
        return self.optionValue("a").find("rave") != -1 or self.optionValue("v").find("rave") != -1
    def getRuleBuildFilter(self):
        if self.isNightJob() or self.optionMap.has_key("rulecomp") or self.isRaveRun():
            return None
        return UpdatedLocalRulesetFilter(self.getRuleSetName, self.getLibraryFile)
    def getRuleBuilder(self):
        if self.buildRules():
            realBuilder = self.getRealRuleBuilder()
            if self.optionValue("rulecomp") != "clean":
                return realBuilder
            else:
                return [ self.getRuleCleanup(), realBuilder ]
        else:
            return None
    def getRealRuleBuilder(self):
        ruleRunner = None
        if self.useLSF() and not self.isNightJob():
            ruleRunner = lsf.SubmitTest(self.findLSFQueue, self.findLSFResource)
        return [ self.getRuleBuildObject(ruleRunner), self.getRuleWaitingAction(), \
                                         EvaluateRuleBuild(self.getRuleSetName) ]
    def getRuleBuildObject(self, ruleRunner):
        return CompileRules(self.getRuleSetName, self.raveMode(), self.getRuleBuildFilter(), ruleRunner)
    def getRuleWaitingAction(self):
        if self.useLSF() and not self.isNightJob():
            return lsf.UpdateLSFStatus(self.getRuleSetName, RULESET_NOT_BUILT)
        else:
            return None
    def buildRules(self):
        if self.optionMap.has_key("skip") or self.isReconnecting():
            return 0
        if self.optionMap.has_key("rulecomp"):
            return 1
        return self.defaultBuildRules()
    def defaultBuildRules(self):
        return 0
    def raveMode(self):
        if self.optionMap.has_key("debug"):
            return "-debug"
        else:
            return "-optimize"
    def getAppBuilder(self):
        if self.optionMap.has_key("build"):
            return BuildCode(self.optionValue("build"))
        elif self.optionMap.has_key("buildl"):
            return BuildCode(self.optionValue("buildl"), remote = 0)
        else:
            return None
    def getTestRunner(self):
        if self.optionMap.has_key("lprof"):
            subActions = [ lsf.LSFConfig.getTestRunner(self), AttachProfiler() ]
            return subActions
        else:
            return lsf.LSFConfig.getTestRunner(self)
    def getTestCollator(self):
        if self.optionMap.has_key("lprof"):
            return [ lsf.LSFConfig.getTestCollator(self), ProcessProfilerResults() ]
        else:
            return lsf.LSFConfig.getTestCollator(self)
    def findLSFQueue(self, test):
        if self.queueDecided(test):
            return lsf.LSFConfig.findLSFQueue(self, test)

        arch = getArchitecture(test.app)
        return self.getQueuePerformancePrefix(test, arch) + self.getArchQueueName(arch) + self.getQueuePlatformSuffix(test.app, arch)
    def getArchQueueName(self, arch):
        if arch == "sparc_64":
            return "sparc"
        else:
            return arch
    def getQueuePerformancePrefix(self, test, arch):
        cpuTime = performance.getTestPerformance(test)
        usePrefix = ""
        if os.environ.has_key("LSF_QUEUE_PREFIX"):
            usePrefix = os.environ["LSF_QUEUE_PREFIX"]
        # Currently no short queue for powerpc_aix4
        if arch == "powerpc" and "9" in test.app.versions:
            return ""
        if usePrefix == "" and cpuTime < 10:
            return "short_"
        elif arch == "powerpc" or arch == "parisc_2_0":
            return ""
        elif usePrefix == "" and cpuTime < 120:
            return ""
        elif usePrefix == "":
            return "idle_"
        else:
            return usePrefix + "_"
    def getQueuePlatformSuffix(self, app, arch):
        if arch == "i386_linux":
            return "_RHEL"
        elif arch == "sparc" or arch == "sparc_64":
            return "_sol8"
        elif arch == "powerpc":
            if "9" in app.versions:
                return "_aix4"
            else:
                return "_aix5"
        return ""
    def isNightJob(self):
        batchSession = self.optionValue("b")
        return batchSession == "nightjob" or batchSession == "wkendjob"
    def isSlowdownJob(self, user, jobName):
        # APC is observed to slow down the other job on its machine by up to 20%. Detect it
        apcDevelopers = [ "curt", "lennart", "johani", "rastjo", "tomasg", "fredrik", "henrike" ]
        if user in apcDevelopers:
            return 1

        # Detect TextTest APC jobs and XPRESS tests
        parts = jobName.split(os.sep)
        return parts[0].find("APC") != -1 or parts[0].find("MpsSolver") != -1
    def printHelpOptions(self, builtInOptions):
        print lsf.helpOptions + batchInfo
        default.Config.printHelpOptions(self, builtInOptions)
        print "(Carmen-specific options...)"
        print helpOptions
    def printHelpScripts(self):
        lsf.LSFConfig.printHelpScripts(self)
        print helpScripts
    def printHelpDescription(self):
        print helpDescription, lsf.lsfGeneral, predict.helpDescription, performance.helpDescription, respond.helpDescription
    def setApplicationDefaults(self, app):
        lsf.LSFConfig.setApplicationDefaults(self, app)
        app.setConfigDefault("default_architecture", "i386_linux")
        app.setConfigDefault("rave_name", None)
        # dictionary of lists
        app.setConfigDefault("build_targets", { "" : [] })
    
def getRaveName(test):
    return test.app.getConfigValue("rave_name")

class CleanupRules(plugins.Action):
    def __init__(self, getRuleSetName):
        self.rulesCleaned = []
        self.raveName = None
        self.getRuleSetName = getRuleSetName
    def __repr__(self):
        return "Cleanup rules for"
    def __call__(self, test):
        arch = getArchitecture(test.app)
        ruleset = RuleSet(self.getRuleSetName(test), self.raveName, arch)
        if self.shouldCleanup(ruleset):
            self.describe(test, " - ruleset " + ruleset.name)
            self.rulesCleaned.append(ruleset.name)
            self.removeRuleSet(arch, ruleset.name)
            self.removeRuleCompileFiles(arch)
            self.removeRulePrecompileFiles(ruleset.name)
    def removeRuleSet(self, arch, name):
        carmTmp = os.environ["CARMTMP"]
        targetPath = os.path.join(carmTmp, "crc", "rule_set", string.upper(self.raveName), arch, name)
        self.removeFile(targetPath)
        self.removeFile(targetPath + ".bak")
    def removeRuleCompileFiles(self, arch):
        carmTmp = os.environ["CARMTMP"]
        targetPath = os.path.join(carmTmp, "compile", string.upper(self.raveName), arch + "_opt")
        if os.path.isdir(targetPath):
            for file in os.listdir(targetPath):
                if file.endswith(".o"):
                    self.removeFile(os.path.join(targetPath, file))
    def removeRulePrecompileFiles(self, name):
        carmTmp = os.environ["CARMTMP"]
        targetPath = os.path.join(carmTmp, "compile", string.upper(self.raveName), name)
        self.removeFile(targetPath + "_recompile.xml")
        targetPath = os.path.join(carmTmp, "crc", "rule_set", string.upper(self.raveName), name)
        self.removeFile(targetPath + ".xml")
    def removeFile(self, fullPath):
        if os.path.isfile(fullPath):
            os.remove(fullPath)
    def shouldCleanup(self, ruleset):
        if not ruleset.isValid():
            return 0
        if not os.path.isdir(os.environ["CARMTMP"]):
            return 0
        if ruleset.name in self.rulesCleaned:
            return 0
        return 1
    def setUpSuite(self, suite):
        self.describe(suite)
        self.rulesCleaned = []
        if self.raveName == None:
            self.raveName = getRaveName(suite)

class CompileRules(plugins.Action):
    def __init__(self, getRuleSetName, modeString = "-optimize", filter = None, ruleRunner = None):
        self.rulesCompiled = []
        self.raveName = None
        self.getRuleSetName = getRuleSetName
        self.modeString = modeString
        self.filter = filter
        self.ruleRunner = ruleRunner
        self.diag = plugins.getDiagnostics("Compile Rules")
    def __repr__(self):
        return "Compiling rules for"
    def __call__(self, test):
        if self.raveName and (not self.filter or self.filter.acceptsTestCase(test)):
            self.compileRulesForTest(test)
    def compileRulesForTest(self, test):
        arch = getArchitecture(test.app)
        ruleset = RuleSet(self.getRuleSetName(test), self.raveName, arch)
        if not ruleset.isValid():
            return
        if ruleset.name in self.rulesCompiled:
            self.describe(test, " - ruleset " + ruleset.name + " already being compiled")
            return test.changeState(RULESET_NOT_BUILT, "Compiling ruleset " + ruleset.name)
        
        self.describe(test, " - ruleset " + ruleset.name)
        self.ensureCarmTmpDirExists()
        ruleset.backup()
        self.rulesCompiled.append(ruleset.name)
        if ruleset.precompiled:
            shutil.copyfile(ruleset.precompiled, ruleset.targetFile)
        else:
            compiler = os.path.join(os.environ["CARMSYS"], "bin", "crc_compile")
            # Fix to be able to run crc_compile for apc also on Carmen 8.
            # crc_compile provides backward compability, so we can always have the '-'.
            extra = ""
            if test.app.name == "apc":
                extra = "-"
            commandLine = compiler + " " + extra + self.raveName + " " + self.getModeString() \
                          + " -archs " + arch + " " + ruleset.sourceFile
            self.performCompile(test, commandLine)
        if self.getModeString() == "-debug":
            ruleset.moveDebugVersion()
    def getModeString(self):
        if os.environ.has_key("TEXTTEST_RAVE_MODE"):
            return self.modeString + " " + os.environ["TEXTTEST_RAVE_MODE"]
        else:
            return self.modeString
    def ensureCarmTmpDirExists(self):
        carmTmp = os.path.normpath(os.environ["CARMTMP"])
        if not os.path.isdir(carmTmp):
            if os.path.islink(carmTmp):
                print "CARMTMP", carmTmp, "seems to be a deadlink"
                return 0
            else:
                print "CARMTMP", carmTmp, "did not exist, attempting to create it"
                os.makedirs(os.environ["CARMTMP"])
        return 1
    def performCompile(self, test, commandLine):
        compTmp = test.makeFileName("ravecompile", temporary=1, forComparison=0)
        # Hack to work around crc_compile bug which fails if ":" in directory
        os.chdir(test.abspath)
        self.diag.info("Compiling with command '" + commandLine + "'")
        fullCommand = commandLine + " > " + compTmp + " 2>&1"
        test.changeState(RULESET_NOT_BUILT, "Compiling ruleset " + self.getRuleSetName(test))
        if self.ruleRunner:
            self.ruleRunner.runCommand(test, fullCommand, self.getRuleSetName)
        else:
            returnValue = os.system(fullCommand)
            if returnValue:
                errContents = string.join(open(compTmp).readlines(),"")
                if errContents.find("already being compiled by") != -1:
                    print test.getIndent() + "Waiting for other compilation to finish..."
                    time.sleep(30)
                    os.remove(compTmp)
                    self.performCompile(test, commandLine)
    def setUpSuite(self, suite):
        if self.filter and not self.filter.acceptsTestSuite(suite):
            self.raveName = None
            return
        self.describe(suite)
        self.rulesCompiled = []
        if self.raveName == None:
            self.raveName = getRaveName(suite)
    def getFilter(self):
        return self.filter

class EvaluateRuleBuild(plugins.Action):
    def __init__(self, getRuleSetName):
        self.getRuleSetName = getRuleSetName
        self.rulesCompiled = {}
    def __call__(self, test):
        if test.state != RULESET_NOT_BUILT:
            return
        compTmp = test.makeFileName("ravecompile", temporary=1, forComparison=0)
        if not os.path.isfile(compTmp):
            return self.checkForPreviousFailure(test)
        errContents = string.join(open(compTmp).readlines(),"")
        ruleset = self.getRuleSetName(test)
        # The first is C-compilation error, the second generation error...
        # Would be better if there was something unambiguous to look for!
        success = errContents.find("failed!") == -1 and errContents.find("ERROR:") == -1
        self.rulesCompiled[ruleset] = success
        if success:
            test.changeState(test.NOT_STARTED, "Ruleset " + ruleset + " succesfully compiled")
        else:
            self.raiseFailure(ruleset, errContents)
    def raiseFailure(self, ruleset, errContents):
        errMsg = "Failed to build ruleset " + ruleset + os.linesep + errContents 
        print errMsg
        raise plugins.TextTestError, errMsg
    def checkForPreviousFailure(self, test):
        ruleset = self.getRuleSetName(test)
        if not self.rulesCompiled.has_key(ruleset):
            return "wait"
        if self.rulesCompiled[ruleset] == 0:
            raise plugins.TextTestError, "Trying to use ruleset '" + ruleset + "' that failed to build."
        else:
            test.changeState(test.NOT_STARTED, "Ruleset " + ruleset + " succesfully compiled")
            
class RuleSet:
    def __init__(self, ruleSetName, raveName, arch):
        self.name = ruleSetName
        if not self.name:
            return
        self.sourceFile = self.sourcePath(self.name)
        self.targetFile = self.targetPath("rule_set", raveName, arch, self.name)
        self.precompiled = None
        if not os.path.isfile(self.sourceFile):
            # Might be a test rule set, have a try
            parts = self.name.split(".")
            if len(parts) == 2 and os.path.isdir("/users/" + parts[1]):
                self.sourceFile = self.sourcePath(parts[0])
                self.precompiled = self.targetPath("rule_set", raveName, arch, parts[0])
                self.targetFile = self.targetPath("test_rule_set", raveName, arch, self.name)
    def isValid(self):
        return self.name and os.path.isfile(self.sourceFile)
    def isCompiled(self):
        return os.path.isfile(self.targetFile)
    def targetPath(self, type, raveName, arch, name):
        return os.path.join(os.environ["CARMTMP"], "crc", type, string.upper(raveName), arch, name)
    def sourcePath(self, name):
        return os.path.join(os.environ["CARMUSR"], "crc", "source", name)
    def backup(self):
        if self.isCompiled():
            try:
                shutil.copyfile(self.targetFile, self.targetFile + ".bak")
            except IOError:
                print "WARNING - did not have permissions to backup ruleset, continuing anyway"
    def moveDebugVersion(self):
        debugVersion = self.targetFile + "_g"
        if os.path.isfile(debugVersion):
            os.remove(self.targetFile)
            os.rename(debugVersion, self.targetFile)
        
class UpdatedLocalRulesetFilter(plugins.Filter):
    def __init__(self, getRuleSetName, getLibraryFile):
        self.getRuleSetName = getRuleSetName
        self.getLibraryFile = getLibraryFile
        self.diag = plugins.getDiagnostics("UpdatedLocalRulesetFilter")
    def acceptsTestCase(self, test):
        ruleset = RuleSet(self.getRuleSetName(test), getRaveName(test), getArchitecture(test.app))
        self.diag.info("Checking " + self.getRuleSetName(test))
        self.diag.info("Target file is " + ruleset.targetFile)
        libFile = self.getLibraryFile(test.app)
        if libFile:
            self.diag.info("Library files is " + libFile)
        if not ruleset.isValid():
            self.diag.info("Invalid")
            return 0
        if not ruleset.isCompiled():
            self.diag.info("Not compiled")
            return 1
        if libFile:
            return self.modifiedTime(ruleset.targetFile) < self.modifiedTime(os.path.join(os.environ["CARMSYS"], libFile))
        else:
            return 1
    def acceptsTestSuite(self, suite):
        if not isUserSuite(suite):
            return 1

        carmtmp = suite.environment["CARMTMP"]
        self.diag.info("CARMTMP: " + carmtmp)
        return carmtmp.find(os.environ["CARMSYS"]) != -1
    def modifiedTime(self, filename):
        return os.stat(filename)[stat.ST_MTIME]

class WaitForDispatch(lsf.Wait):
    def __init__(self):
        lsf.Wait.__init__(self)
        self.eventName = "dispatch"
    def checkCondition(self, job):
        return job.getProcessId()

class AttachProfiler(plugins.Action):
    def __repr__(self):
        return "Attaching lprof on"
    def __call__(self, test):
        waitDispatch = WaitForDispatch()
        waitDispatch.__call__(test)
        job = lsf.LSFJob(test)
        status, executionMachine = job.getStatus()
        processId = job.getProcessId()
        self.describe(test, ", executing on " + executionMachine + ", pid " + str(processId))
        runLine = "cd " + os.getcwd() + "; /users/lennart/bin/gprofile " + processId + " >& gprof.output"
        os.spawnlp(os.P_NOWAIT, "rsh", "rsh", executionMachine, runLine)

class ProcessProfilerResults(plugins.Action):
    def __call__(self, test):
        processLine = "/users/lennart/bin/process_gprof -t 0.5 prof.*" + " > " + test.makeFileName("lprof", temporary = 1)
        os.system(processLine)
        # Compress and save the raw data.
        cmdLine = "gzip prof.[0-9]*;mv prof.[0-9]*.gz " + test.makeFileName("prof", temporary = 1)
        os.system(cmdLine)
    def __repr__(self):
        return "Profiling"    

class BuildCode(plugins.Action):
    builtDirs = {}
    def __init__(self, target, remote = 1):
        self.target = target
        self.remote = remote
        self.childProcesses = []
    def setUpApplication(self, app):
        targetDir = app.getConfigValue("build_targets")
        if not targetDir.has_key(self.target):
            return
        arch = getArchitecture(app)
        if not self.builtDirs.has_key(arch):
            self.builtDirs[arch] = []
        for relPath in targetDir[self.target]:
            absPath = app.makeAbsPath(relPath)
            if absPath in self.builtDirs[arch]:
                print "Already built on", arch, "under", absPath, "- skipping build"
                return
            self.builtDirs[arch].append(absPath)
            if os.path.isdir(absPath):
                self.buildLocal(absPath, app)
            else:
                print "Not building in", absPath, "which doesn't exist!"
        if arch == "i386_linux" and self.remote:
            self.buildRemote("sparc", app) 
            self.buildRemote("parisc_2_0", app)
            self.buildRemote("powerpc", app)
    def getMachine(self, app, arch):
        version9 = "9" in app.versions
        if arch == "i386_linux":
            if version9:
                return "xanxere"
            else:
                return "reedsville"
        if arch == "sparc":
            return "turin"
        if arch == "parisc_2_0":
            return "ramechap"
        if arch == "powerpc":
            if version9:
                return "morlaix"
            else:
                return "tororo"
    def buildLocal(self, absPath, app):
        os.chdir(absPath)
        print "Building", app, "in", absPath, "..."
        arch = getArchitecture(app)
        buildFile = "build.default." + arch
        commandLine = "cd " + absPath + "; gmake >& " + buildFile
        machine = self.getMachine(app, arch)
        os.system("rsh " + machine + " '" + commandLine + "' < /dev/null")
        if self.checkBuildFile(buildFile):
            raise "Product " + repr(app) + " did not build, exiting"
        print "Product", app, "built correctly in", absPath
        os.remove(buildFile)
        commandLine = "cd " + absPath + "; gmake install CARMSYS=" + os.environ["CARMSYS"] + " >& /dev/null"
        os.system("rsh " + machine + " '" + commandLine + "' < /dev/null")
        print "Making install from", absPath ,"to", os.environ["CARMSYS"]
    def buildRemote(self, arch, app):
        machine = self.getMachine(app, arch)
        print "Building remotely in parallel on " + machine + " ..."
        processId = os.fork()
        if processId == 0:
            result = self.buildRemoteInChild(machine, arch, app)
            os._exit(result)
        else:
            tuple = processId, arch
            self.childProcesses.append(tuple)
    def buildRemoteInChild(self, machine, arch, app):
        sys.stdin = open("/dev/null")
        signal.signal(1, self.killBuild)
        signal.signal(2, self.killBuild)
        signal.signal(15, self.killBuild) 
        targetDir = app.getConfigValue("build_targets")
        if not targetDir.has_key("codebase"):
            return 1
        for relPath in targetDir["codebase"]:
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
    def getCleanUpAction(self):
        if self.remote:
            return CheckBuild(self)
        else:
            return None

class CheckBuild(plugins.Action):
    def __init__(self, builder):
        self.builder = builder
    def setUpApplication(self, app):
        print "Waiting for remote builds..." 
        for process, arch in self.builder.childProcesses:
            pid, status = os.waitpid(process, 0)
            # In theory we should be able to trust the status. In practice, it seems to be 0, even when the build failed.
            targetDir = app.getConfigValue("build_targets")
            if not targetDir.has_key("codebase"):
                return
            for relPath in targetDir["codebase"]:
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

class TraverseCarmUsers(plugins.Action):
    def __init__(self, args = []):
        self.traversedUsers = {}
        self.Command = {}
        for ar in args:
            arr = ar.split("=")
            if arr[0]=="findchanges":
                if len(arr) > 1:
                    self.time = arr[1]
                else:
                    self.time = "1440"
                    print "Using default time " + self.time + " minutes"
                self.Command = "find . -path ./LOCAL_PLAN -prune -o -type f -mmin -" + self.time + " -ls"
            else:
                self.Command = string.join(args)
        if not self.Command:
            raise "No command given"
    def __repr__(self):
        return "Traversing CARMUSR "
    def __call__(self, test):
        user = os.environ["CARMUSR"]
        if self.traversedUsers.has_key(user):
            return
        self.traversedUsers[user] = 1
        # Describe is not so good here, since it prints the test name.
        print "Traversing CARMUSR " + user + ":"
        # Save the old dir, so we can restore it later.
        saveDir = os.getcwd()
        sys.stdout.flush()
        try:
            os.chdir(user)
            os.system(self.Command)
        except OSError, detail:
            print "Failed due to " + str(detail)
        # Restore dir
        os.chdir(saveDir)
    # Interactive stuff
    def getTitle(self):
        return "Traversing users"
    def getArgumentOptions(self):
        options = {}
        return options
    def getSwitches(self):
        switches = {}
        return switches

#
# This class reads a CarmResources etab file and gives access to it
#
class ConfigEtable:
    def __init__(self, fileName):
        self.inFile = open(fileName)
        self.applications = {}
        self.columns = self._readColumns()
        self.parser = ConfigEtableParser(self.inFile)
        self.diag = plugins.getDiagnostics("ConfigEtable")
        lineTuple = self._readTuple()
        while lineTuple != None:
            self._storeValue(lineTuple[0], lineTuple[1], lineTuple[2], lineTuple[4])
            lineTuple = self._readTuple()
    def getValue(self, application, module, name):
        try:
            appDict = self.applications[application]
            moduleDict = appDict[module]
            value = moduleDict[name]
        except:
            return None
        return self._etabExpand(value)
    def _storeValue(self, app, module, name, value):
        if not self.applications.has_key(app):
            self.applications[app] = {}
        if not self.applications[app].has_key(module):
            self.applications[app][module] = {}
        self.applications[app][module][name] = value
    def _readTuple(self):
        tup = []
        while len(tup) < len(self.columns):
            tok = self._readConfigToken()
            if tok == None:
                break
            if tok != ",":
                tup.append(tok)
        if len(tup) == len(self.columns):
            return tup
        else:
            return None
    def _readColumns(self):
        numCols = self._readNumCols()
        cols = []
        while len(cols) < numCols:
            line = self.inFile.readline()
            parts = line.split()
            if len(parts) > 0 and len(parts[0].strip()) > 0:
                cols.append(parts[0])
        return cols
    def _readNumCols(self):
        numCols = -1
        inComment = 0
        while numCols == -1:
            line = self.inFile.readline()
            if line.startswith("/*"):
                inComment = 1
            if line.strip().endswith("*/"):
                inComment = 0
            if not inComment:
                try:
                    numCols = int(line.strip())
                except:
                    pass
        return numCols
    def _readConfigToken(self):
        tok = self.parser.get_token()
        while tok != None and tok.startswith("/*"):
            while not tok.endswith("*/"):
                tok = self.parser.get_token()
            tok = self.parser.get_token()
        return tok
    def _etabExpand(self, value):
        self.diag.info("Expanding etable value " + value)
        if not value.startswith("$("):
            return value
        lPos = value.find(")")
        if lPos == -1:
            return value
      
        parts = value[2:lPos].split(".")
        self.diag.debug("parts = " + repr(parts))
        if len(parts) == 3:
            expanded = self.getValue(parts[0], parts[1], parts[2])
            self.diag.debug("expanded = " + repr(expanded))
            whole = expanded + self._etabExpand(value[lPos + 1:])
            return self._etabExpand(whole)
        else:
            whole = "${" + value[2:lPos] + "}" + self._etabExpand(value[lPos + 1:])
            return os.path.expandvars(whole)

class ConfigEtableParser:
    def __init__(self, infile):
        self.file = infile
        self.quotes = [ '"', "'" ]
        self.specials = {}
        self.specials["n"] = "\n"
        self.specials["r"] = "\r"
        self.specials["t"] = "\t"
        self.lastChar = None
    def _readChar(self):
        ch = self.__readChar()
        return ch
    def __readChar(self):
        if self.lastChar != None:
            ch = self.lastChar
            self.lastChar = None
            return ch
        return self.file.read(1)
    def _pushBack(self, ch):
        self.lastChar = ch
    def _peekCheck(self, ch, firstChar, nextChar):
        if ch == firstChar:
            ch2 = self._readChar()
            if ch2 == nextChar:
                return 1
            self._pushBack(ch2)
        return 0
    def _readElement(self):
        ch = self._readChar()
        if self._peekCheck(ch, "/", "*"):
            return "/*"
        if self._peekCheck(ch, "*", "/"):
            return "*/"
        if len(os.linesep) > 1:
            if self._peekCheck(ch, os.linesep[0], os.linesep[1]):
                return os.linesep
        if ch == "\\":
            ch = self._readChar()
        return ch
    def _readQuote(self, quote):
        text = ""
        ch = self._readChar()
        while len(ch) > 0 and ch != quote:
            if ch == "\\":
                ch = self._readChar()
                if self.specials.has_key(ch):
                    ch = self.specials[ch]
            text += ch
            ch = self._readChar()
        return text

    def get_token(self):
        tok = ""
        ch = self._readElement()
        while len(ch) > 0:
            if ch in self.quotes:
                return tok + self._readQuote(ch)
            if ch == "/*":
                while ch != "" and ch != "*/":
                    ch = self._readElement()
                continue
            if ch == ",":
                if len(tok) > 0:
                    self._pushBack(ch)
                    return tok
                else:
                    return ch
            if not ch in [ ' ', os.linesep, '\t' ]:
                tok += ch
            else:
                if tok != "":
                    return tok
            ch = self._readElement()
        if tok == "":
            return None
        return tok

def ensureDirectoryExists(path):
    if len(path) == 0:
        return
    if os.path.isdir(path):
        return
    h, t = os.path.split(path)
    ensureDirectoryExists(h)
    if len(t) > 0:
        os.mkdir(path)


