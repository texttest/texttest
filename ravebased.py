#!/usr/local/bin/python

helpDescription = """
The Rave-based configuration is based on the Carmen configuration. Besides taking advantage of Carmen's local set-up,
it manages the building of rulesets via crc_compile, the CARMSYS/CARMUSR/CARMTMP structure and building Carmen code via
gmake
"""

helpOptions = """
-u <texts> - select only user suites whose name contains one of the strings in <texts>. <texts> is interpreted as a
             comma-separated list. A user suite is defined as a test suite which defines CARMUSR locally.

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

helpScripts = """ravebased.TraverseCarmUsers   - Traverses all CARMUSR's associated with the selected tests,
                             and executes the command specified by argument. Be careful to quote the command
                             if you use options, otherwise texttest will try to interpret the options.
                             Example: texttest -s carmen.TraverseCarmUsers "pwd". This will
                             display the path of all CARMUSR's in the test suite.
                                              
                             If the argument findchanges=<changed within minutes> is given,
                             a find command is issued, that prints all files that has changed within
                             the specified time. Default time is 1440 minutes.
"""

import carmen, queuesystem, default, os, string, shutil, plugins, sys, signal

def getConfig(optionMap):
    return Config(optionMap)

def isUserSuite(suite):
    return suite.environment.has_key("CARMUSR")

class UserFilter(default.TextFilter):
    def isUserSuite(self, suite):
        # Don't use the generic one because we can't guarantee environment has been read yet...
        envFiles = [ os.path.join(suite.abspath, "environment"), suite.makeFileName("environment") ]
        for file in envFiles:
            if os.path.isfile(file):
                for line in open(file).xreadlines():
                    if line.startswith("CARMUSR:"):
                        return 1
        return 0
    def acceptsTestSuite(self, suite):
        if self.isUserSuite(suite):
            return self.containsText(suite)
        else:
            return 1

class RulesetJobBuildNameCreator:
    namesCreated = {}
    def __init__(self, getRuleSetName):
        self.diag = plugins.getDiagnostics("Rule job names")
        self.getRuleSetName = getRuleSetName
        self.testRuleNames = {}
    def getName(self, test):
        if self.testRuleNames.has_key(test):
            return self.testRuleNames[test]
        basicName = getRaveName(test) + "." + self.getUserParentName(test) + "." + self.getRuleSetName(test)
        if self.namesCreated.has_key(basicName):
            carmtmp = self.namesCreated[basicName]
            if carmtmp == os.environ["CARMTMP"]:
                return basicName
            else:
                basicName += "." + test.app.getFullVersion()
        self.namesCreated[basicName] = os.environ["CARMTMP"]
        self.diag.info(repr(self.namesCreated))
        self.testRuleNames[test] = basicName
        return basicName
    def getUserParentName(self, test):
        if isUserSuite(test.parent):
            return test.parent.name
        return self.getUserParentName(test.parent)

class Config(carmen.CarmenConfig):
    def addToOptionGroups(self, app, groups):
        carmen.CarmenConfig.addToOptionGroups(self, app, groups)
        for group in groups:
            if group.name.startswith("Select"):
                group.addOption("u", "CARMUSRs containing")
            elif group.name.startswith("What"):
                group.addSwitch("rulecomp", "Build all rulesets")
                group.addSwitch("skip", "Build no rulesets")
            elif group.name.startswith("How"):
                group.addSwitch("debug", "Use debug rulesets")
                group.addSwitch("raveexp", "Run with RAVE Explorer")
            elif group.name.startswith("Side"):
                group.addOption("build", "Build application target")
                group.addOption("buildl", "Build application target locally")        
    def getFilterList(self):
        filters = carmen.CarmenConfig.getFilterList(self)
        self.addFilter(filters, "u", UserFilter)
        return filters
    def getActionSequence(self):
        if self.optionMap.slaveRun():
            return carmen.CarmenConfig.getActionSequence(self)
        
        # Drop the write directory maker, in order to insert the rulebuilder in between it and the test runner
        return [ self.getAppBuilder(), self.getWriteDirectoryMaker(), self.getCarmVarChecker(), self.getRuleBuilder() ] + \
                 carmen.CarmenConfig._getActionSequence(self, makeDirs = 0)
    def getCarmVarChecker(self):
        if not self.isReconnecting():
            return CheckCarmVariables()
        else:
            return None
    def getRuleCleanup(self):
        return CleanupRules(self.getRuleSetName)
    def isRaveRun(self):
        return self.optionValue("a").find("rave") != -1 or self.optionValue("v").find("rave") != -1
    def getRuleBuildFilter(self):
        if self.isNightJob() or (self.optionMap.has_key("rulecomp") and not self.optionValue("rulecomp")) or self.isRaveRun():
            return None
        return UpdatedLocalRulesetFilter(self.getRuleSetName)
    def getRuleBuilder(self):
        if self.buildRules():
            realBuilder = self.getRealRuleBuilder()
            if self.optionValue("rulecomp") != "clean":
                return realBuilder
            else:
                return [ self.getRuleCleanup(), realBuilder ]
        else:
            return None
    def getRuleSetName(self, test):
        raise plugins.TextTestError, "Cannot determine ruleset name, need to provide derived configuration to use rule compilation"
    def getRealRuleBuilder(self):
        jobNameCreator = RulesetJobBuildNameCreator(self.getRuleSetName)
        if self.useQueueSystem():
            ruleRunner = queuesystem.SubmitTest(self.getSubmissionRules, self.optionMap)
            return [ self.getRuleBuildObject(ruleRunner, jobNameCreator), \
                     UpdateRulesetBuildStatus(self.getRuleSetName, jobNameCreator) ]
        else:
            return self.getRuleBuildObject(default.RunTest(), jobNameCreator)
    def getRuleBuildObject(self, ruleRunner, jobNameCreator):
        return CompileRules(self.getRuleSetName, jobNameCreator, self.raveMode(), self.getRuleBuildFilter(), ruleRunner)
    def buildRules(self):
        if self.optionMap.has_key("skip") or self.isReconnecting():
            return 0
        if self.optionMap.has_key("rulecomp"):
            return 1
        return self.defaultBuildRules()
    def defaultBuildRules(self):
        return 0
    def raveMode(self):
        if self.optionMap.has_key("raveexp"):
            return "-explorer"
        elif self.optionMap.has_key("debug"):
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
    def isSlowdownJob(self, user, jobName):
        # APC is observed to slow down the other job on its machine by up to 20%. Detect it
        apcDevelopers = [ "curt", "lennart", "johani", "rastjo", "tomasg", "fredrik", "henrike" ]
        if user in apcDevelopers:
            return 1

        # Detect TextTest APC jobs and XPRESS tests
        parts = jobName.split(os.sep)
        return parts[0].find("APC") != -1 or parts[0].find("MpsSolver") != -1
    def printHelpOptions(self, builtInOptions):
        carmen.CarmenConfig.printHelpOptions(self, builtInOptions)
        print helpOptions
    def printHelpScripts(self):
        carmen.CarmenConfig.printHelpScripts(self)
        print helpScripts
    def printHelpDescription(self):
        print helpDescription
        carmen.CarmenConfig.printHelpDescription(self)
    def setApplicationDefaults(self, app):
        carmen.CarmenConfig.setApplicationDefaults(self, app)
        app.setConfigDefault("rave_name", None)
        app.setConfigDefault("rave_static_library", "")
        # dictionary of lists
        app.setConfigDefault("build_targets", { "" : [] })
        app.addConfigEntry("need_rulecompile", "white", "test_colours")
        app.addConfigEntry("running_rulecompile", "peach puff", "test_colours")

def getRaveName(test):
    return test.app.getConfigValue("rave_name")

class CheckCarmVariables(plugins.Action):
    def setUpSuite(self, suite):
        if isUserSuite(suite):
            self.ensureCarmTmpDirExists()
    def __call__(self, test):
        if isUserSuite(test):
            self.ensureCarmTmpDirExists()
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

class CleanupRules(plugins.Action):
    def __init__(self, getRuleSetName):
        self.rulesCleaned = []
        self.raveName = None
        self.getRuleSetName = getRuleSetName
    def __repr__(self):
        return "Cleanup rules for"
    def __call__(self, test):
        arch = carmen.getArchitecture(test.app)
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
    rulesCompiled = []
    def __init__(self, getRuleSetName, jobNameCreator, modeString = "-optimize", filter = None, ruleRunner = None):
        self.raveName = None
        self.getRuleSetName = getRuleSetName
        self.jobNameCreator = jobNameCreator
        self.modeString = modeString
        self.filter = filter
        self.ruleRunner = ruleRunner
        self.diag = plugins.getDiagnostics("Compile Rules")
    def __repr__(self):
        return "Compiling rules for"
    def __call__(self, test):
        if self.raveName and (not self.filter or self.filter.acceptsTestCase(test)):
            try:
                return self.compileRulesForTest(test)
            except plugins.TextTestError, e:
                print e
                return 
        else:
            self.diag.info("Rejecting ruleset compile for " + test.name)
    def compileRulesForTest(self, test):
        arch = carmen.getArchitecture(test.app)
        ruleset = RuleSet(self.getRuleSetName(test), self.raveName, arch)
        if not ruleset.isValid():
            return
        jobName = self.jobNameCreator.getName(test)
        if jobName in self.rulesCompiled:
            self.describe(test, " - ruleset " + ruleset.name + " already being compiled")
            test.changeState(NeedRuleCompilation("Compiling ruleset " + ruleset.name, thisTestCompiles=0))
            return
        self.describe(test, " - ruleset " + ruleset.name)
        ruleset.backup()
        self.rulesCompiled.append(jobName)
        retStatus = None
        if ruleset.precompiled:
            root, local = os.path.split(ruleset.targetFile)
            if not os.path.isdir(root):
                os.makedirs(root)
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
            retStatus = self.performCompile(test, commandLine)
        if self.getModeString() == "-debug":
            ruleset.moveDebugVersion()
        return retStatus
    def getModeString(self):
        if os.environ.has_key("TEXTTEST_RAVE_MODE"):
            return self.modeString + " " + os.environ["TEXTTEST_RAVE_MODE"]
        else:
            return self.modeString
    def performCompile(self, test, commandLine):
        compTmp = test.makeFileName("ravecompile", temporary=1, forComparison=0)
        # Hack to work around crc_compile bug which fails if ":" in directory
        os.chdir(test.abspath)
        # Hack to work around AMD automounter which creates weird temporary path
        os.environ["PWD"] = test.abspath
        self.diag.info("Compiling with command '" + commandLine + "' from directory " + os.environ["PWD"])
        # Redirect standard out and standard error to same file. Unfortunately, not all queue systems use the same shell.
        # This is another hack...
        if queuesystem.queueSystemName(test.app) == "LSF": # LSF uses sh...
            fullCommand = commandLine + " > " + compTmp + " 2>&1"
        else: # ... but SGE uses csh
            fullCommand = commandLine + " >& " + compTmp
        test.changeState(NeedRuleCompilation("Compiling ruleset " + self.getRuleSetName(test), thisTestCompiles=1))
        return self.ruleRunner.runCommand(test, fullCommand, self.jobNameCreator.getName)
    def setUpSuite(self, suite):
        if self.filter and not self.filter.acceptsTestSuite(suite):
            self.raveName = None
            self.diag.info("Rejecting ruleset compile for " + suite.name)
            return
        if self.raveName == None and isUserSuite(suite):
            self.describe(suite)
            self.raveName = getRaveName(suite)
        if suite.abspath == suite.app.abspath:
            self.describe(suite)
    def getFilter(self):
        return self.filter

class NeedRuleCompilation(plugins.TestState):
    def __init__(self, details, thisTestCompiles):
        plugins.TestState.__init__(self, "need_rulecompile", details)
        self.thisTestCompiles = thisTestCompiles

class RunningRuleCompilation(plugins.TestState):
    def __init__(self, details, prevState):
        plugins.TestState.__init__(self, "running_rulecompile", details)
        self.thisTestCompiles = prevState.thisTestCompiles
    def changeDescription(self):
        return "start ruleset compilation"
    def timeElapsedSince(self, oldState):
        return oldState.category == "need_rulecompile"

class UpdateRulesetBuildStatus(queuesystem.UpdateStatus):
    ruleCompilations = []
    def __init__(self, getRuleSetName, jobNameCreator):
        queuesystem.UpdateStatus.__init__(self, jobNameCreator.getName)
        self.getRuleSetName = getRuleSetName
    def __call__(self, test):
        # Don't do anything unless we've been put in need_rulecompile state
        if test.state.category.endswith("rulecompile"):
            return queuesystem.UpdateStatus.__call__(self, test)
        elif test.state.isComplete():
            jobName = self.jobNameFunction(test)
            self.ruleCompilations.append(jobName)
            ruleset = self.getRuleSetName(test)
            self.raiseFailureWithError(ruleset, str(test.state))
    def processStatus(self, test, status, job):
        ruleset = self.getRuleSetName(test)
        details = "Compiling ruleset " + ruleset
        machineStr = string.join(job.machines, ",")
        if len(job.machines):
            details += " on " + machineStr
        details += os.linesep + "Current LSF status = " + status + os.linesep
        if status == "PEND":
            test.state.freeText = details
        else:
            test.changeState(RunningRuleCompilation(details, test.state))

        if status != "EXIT" and status != "DONE":
            return

        queueSystem = queuesystem.QueueSystemServer.instance.getQueueSystem(test)
        try:
            if queueSystem.exitedWithError(job):
                return self.raiseFailure(test, ruleset, machineStr)
            else:
                self.ruleCompilations.append(self.jobNameFunction(test))
                test.changeState(plugins.TestState("not_started", "Ruleset " + ruleset + " succesfully compiled"))
        except queuesystem.QueueSystemLostJob:
            self.raiseFailureWithError(ruleset, "Queue system lost the job")
            
    def raiseFailure(self, test, ruleset, machineStr):
        compTmp = test.makeFileName("ravecompile", temporary=1, forComparison=0)
        jobName = self.jobNameFunction(test)
        if not test.state.thisTestCompiles:
            # Make sure first test is first one to report - less confusing...
            if jobName in self.ruleCompilations:
                raise plugins.TextTestError, "Trying to use ruleset '" + ruleset + "' that failed to build."
            else:
                return self.RETRY | self.WAIT
        self.ruleCompilations.append(jobName)
        errContents = self.findErrorMessage(compTmp, machineStr)
        self.raiseFailureWithError(ruleset, errContents)
    def findErrorMessage(self, compTmp, machineStr):
        if not os.path.isfile(compTmp):
            return "Rave compiler did not run at all, possibly problems with execution machine (" + machineStr + ")"
        errContents = string.join(open(compTmp).readlines(),"")
        if errContents.find("Compiling... failed!") != -1:
            return "Rave compiler failed in C-compilation phase." + os.linesep + "See " + compTmp + " for details."
        else:
            return errContents
    def raiseFailureWithError(self, ruleset, errContents):
        errMsg = "Failed to build ruleset " + ruleset + os.linesep + errContents 
        raise plugins.TextTestError, errMsg
            
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
    def __init__(self, getRuleSetName):
        self.getRuleSetName = getRuleSetName
        self.diag = plugins.getDiagnostics("UpdatedLocalRulesetFilter")
    def acceptsTestCase(self, test):
        ruleset = RuleSet(self.getRuleSetName(test), getRaveName(test), carmen.getArchitecture(test.app))
        self.diag.info("Checking " + self.getRuleSetName(test))
        self.diag.info("Target file is " + ruleset.targetFile)
        if not ruleset.isValid():
            self.diag.info("Invalid")
            return 0
        if not ruleset.isCompiled():
            self.diag.info("Not compiled")
            return 1
        libFile = test.getConfigValue("rave_static_library")
        if libFile:
            return plugins.modifiedTime(ruleset.targetFile) < plugins.modifiedTime(libFile)
        else:
            return 1
    def acceptsTestSuite(self, suite):
        if not isUserSuite(suite):
            return 1

        carmtmp = suite.environment["CARMTMP"]
        self.diag.info("CARMTMP: " + carmtmp)
        # Ruleset is local if CARMTMP depends on the CARMSYS or the tests
        if carmtmp.find(os.environ["CARMSYS"]) != -1:
            return 1
        ttHome = os.getenv("TEXTTEST_HOME")
        return ttHome and carmtmp.find(ttHome) != -1

class BuildCode(plugins.Action):
    builtDirs = {}
    buildFailedDirs = {}
    builtDirsBackground = {}
    def __init__(self, target, remote = 1):
        self.target = target
        self.remote = remote
        self.childProcesses = []
    def setUpApplication(self, app):
        targetDir = app.getConfigValue("build_targets")
        if not targetDir.has_key(self.target):
            return
        arch = carmen.getArchitecture(app)
        if not self.builtDirs.has_key(arch):
            self.builtDirs[arch] = []
            self.buildFailedDirs[arch] = []
        for optValue in targetDir[self.target]:
            absPath, makeTargets = self.getPathAndTargets(optValue)
            if absPath in self.builtDirs[arch]:
                print "Already built on", arch, "under", absPath, "- skipping build"
                continue
            if absPath in self.buildFailedDirs[arch]:
                raise plugins.TextTestError, "BUILD ERROR: " + repr(app) + " depends on already failed build " + os.linesep \
                      + "(Build in " + absPath + " on " + arch + ")"
            
            if os.path.isdir(absPath):
                self.buildLocal(absPath, app, makeTargets)
            else:
                print "Not building in", absPath, "which doesn't exist!"
        if arch == "i386_linux" and self.remote:
            self.buildRemote("sparc", app)
            if not "9" in app.versions and not "10" in app.versions:
                self.buildRemote("sparc_64", app)
                if not "11" in app.versions:
                    self.buildRemote("x86_64_linux", app)
            self.buildRemote("parisc_2_0", app)
            self.buildRemote("powerpc", app)
    def getPathAndTargets(self, optValue):
        relPath = optValue
        makeTargets = ""
        optParts = string.split(optValue)
        if len(optParts) > 1:
            relPath = optParts[0]
            makeTargets = string.join(optParts[1:])
        return (relPath, makeTargets)
    def getMachine(self, app, arch):
        version9 = "9" in app.versions
        version12 = "12" in app.versions
        if arch == "i386_linux":
            if version9:
                return "xanxere"
            else:
                return "taylor"
        if arch == "sparc":
            return "turin"
        if arch == "sparc_64":
            return "elmira"
        if arch == "parisc_2_0":
            return "ramechap"
        if arch == "powerpc":
            if version9:
                return "morlaix"
            else:
                return "tororo"
        if arch == "ia64_hpux":
            return "wakeman"
        if arch == "x86_64_linux":
            if version12:
                return "woodville"
            else:
                return "brockville"
    def getRemoteCommandLine(self, arch, absPath, makeCommand):
        commandLine = "cd " + absPath + "; " + makeCommand
        if arch == "sparc_64" or arch == "x86_64_linux":
            commandLine = "setenv BITMODE 64; " + commandLine
        return commandLine
    def buildLocal(self, absPath, app, makeTargets):
        os.chdir(absPath)
        arch = carmen.getArchitecture(app)
        buildFile = "build.default." + arch
        commandLine = self.getRemoteCommandLine(arch, absPath, "gmake " + makeTargets + " >& " + buildFile)
        machine = self.getMachine(app, arch)
        print "Building", app, "in", absPath, "on", machine, "..."
        os.system("rsh " + machine + " '" + commandLine + "' < /dev/null")
        if self.checkBuildFile(buildFile):
            self.buildFailedDirs[arch].append(absPath)
            raise plugins.TextTestError, "BUILD ERROR: Product " + repr(app) + " did not build!" + os.linesep + \
                  "(See " + os.path.join(absPath, buildFile) + " for details)"
        print "Product", app, "built correctly in", absPath
        self.builtDirs[arch].append(absPath)
        os.remove(buildFile)
        if os.environ.has_key("CARMSYS"):
            commandLine = self.getRemoteCommandLine(arch, absPath, "gmake install CARMSYS=" + os.environ["CARMSYS"] + " >& /dev/null")
            os.system("rsh " + machine + " '" + commandLine + "' < /dev/null")
            print "Making install from", absPath ,"to", os.environ["CARMSYS"]
    def buildRemote(self, arch, app):
        targetDir = app.getConfigValue("build_targets")
        if not targetDir.has_key("codebase"):
            return
        if not self.builtDirsBackground.has_key(arch):
            self.builtDirsBackground[arch] = []
        buildDirs = []
        machine = self.getMachine(app, arch)
        for optValue in targetDir["codebase"]:
            absPath, makeTargets = self.getPathAndTargets(optValue)
            if os.path.isdir(absPath) and not absPath in self.builtDirsBackground[arch]:
                buildDirs.append((absPath, makeTargets))
                print "Building", absPath, "remotely in parallel on", machine, "..."
                self.builtDirsBackground[arch].append(absPath)
        if len(buildDirs) == 0:
            return
        processId = os.fork()
        if processId == 0:
            result = self.buildRemoteInChild(machine, arch, buildDirs)
            os._exit(result)
        else:
            tuple = processId, arch
            self.childProcesses.append(tuple)
    def buildRemoteInChild(self, machine, arch, buildDirs):
        sys.stdin = open("/dev/null")
        signal.signal(1, self.killBuild)
        signal.signal(2, self.killBuild)
        signal.signal(15, self.killBuild)
        for absPath, makeTargets in buildDirs:
            commandLine = self.getRemoteCommandLine(arch, absPath, "gmake " + makeTargets + " >& build." + arch)
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
    checkedDirs = {}
    def __init__(self, builder):
        self.builder = builder
    def setUpApplication(self, app):
        if len(self.builder.childProcesses) > 0:
            print "Waiting for remote builds..." 
        for process, arch in self.builder.childProcesses:
            pid, status = os.waitpid(process, 0)
            # In theory we should be able to trust the status. In practice, it seems to be 0, even when the build failed.
            targetDir = app.getConfigValue("build_targets")
            if not targetDir.has_key("codebase"):
                return
            for optValue in targetDir["codebase"]:
                absPath, makeTargets = self.builder.getPathAndTargets(optValue)
                self.checkBuild(arch, absPath)
    def checkBuild(self, arch, absPath):
        if os.path.isdir(absPath):
            os.chdir(absPath)
            if not self.checkedDirs.has_key(arch):
                self.checkedDirs[arch] = []
            if absPath in self.checkedDirs[arch]:
                return
            else:
                self.checkedDirs[arch].append(absPath)
            fileName = "build." + arch
            if not os.path.isfile(fileName):
                print "FILE NOT FOUND: ", os.path.join(absPath, fileName)
                return
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


