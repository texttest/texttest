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
             the config file as the entries "build_targets". So if my config file contains the lines
             [build_targets]
             codebase:$TEXTTEST_CHECKOUT/Rules_and_Reports
             codebase:$TEXTTEST_CHECKOUT/Optimization
             then specifying -build codebase will cause a build (= gmake) to be run in these places (relative to checkout
             of course), before anything else is done.

             It will build on the platform whose architecture you specify.
             
-skip      - Don't build any rulesets before running the tests.

-debug     - Compile a debug ruleset, and rename it so that it is used instead of the normal one.
"""

helpScripts = """ravebased.TraverseCarmUsers   - Traverses all CARMUSR's associated with the selected tests,
                             and executes the command specified by argument. Be careful to quote the command
                             if you use options, otherwise texttest will try to interpret the options.
                             Example: texttest -s ravebased.TraverseCarmUsers "pwd". This will
                             display the path of all CARMUSR's in the test suite.
                                              
                             If the argument findchanges=<changed within minutes> is given,
                             a find command is issued, that prints all files that has changed within
                             the specified time. Default time is 1440 minutes.
"""

import default, os, string, shutil, plugins, sys, signal, stat, guiplugins, subprocess
from socket import gethostname, SHUT_WR
from respond import Responder
from copy import copy
from traffic_cmd import sendServerState
from carmenqueuesystem import getArchitecture, CarmenConfig, CarmenSgeSubmissionRules
from queuesystem import Activator, KillTestSubmission, queueSystemName, SlaveServerResponder, SlaveRequestHandler, QueueSystemServer
from ndict import seqdict
RuleBuildFailed = plugins.Unrunnable # for backwards compatibility with old website files

def getConfig(optionMap):
    return Config(optionMap)

def isUserSuite(suite):
    return suite.environment.has_key("CARMUSR")

class UserFilter(plugins.TextFilter):
    option = "u"
    def isUserSuite(self, suite):
        for file in suite.findAllStdFiles("environment"):
            for line in open(file).xreadlines():
                if line.startswith("CARMUSR:"):
                    return 1
        return 0
    def acceptsTestSuite(self, suite):
        if self.isUserSuite(suite):
            return self.containsText(suite)
        else:
            return 1


 # Rave compilations
 #                              R3-Pent_32 R3-Xeon_32  R3-Opteron_32 R3-Opteron_64 R4-Xeon_32 R4-Opteron_64
 #
 # i386_linux.carmen_11           X          X           X                                      x
 # i386_linux.carmen_12                                                                         X
 # i386_linux.master                                                                            X
 # x86_64_linux.carmen_12                                                                       X
 # x86_64_linux.master                                                                          X
 #

class RaveSubmissionRules(CarmenSgeSubmissionRules):
    namesCreated = {}
    def __init__(self, optionMap, test, getRuleSetNames):
        CarmenSgeSubmissionRules.__init__(self, optionMap, test, nightjob=False)
        self.diag = plugins.getDiagnostics("Rule job names")
        self.getRuleSetNames = getRuleSetNames
        self.testRuleName = None
    def getMajorReleaseResourceType(self):
        return "build"
    def getProcessesNeeded(self):
        return "1"
    def findPriority(self):
        # Don't lower the priority of these
        return 0
    def getEnvironmentResource(self):
        return self.test.getEnvironment("QUEUE_SYSTEM_RESOURCE_RAVE", "")
    def getJobName(self):
        if self.testRuleName:
            return self.testRuleName
        basicName = "Rules-" + "-".join(self.getRuleSetNames(self.test)) + "." + self.getUserParentName(self.test) + "-" + getBasicRaveName(self.test)
        testCarmtmp = self.test.getEnvironment("CARMTMP")
        if self.namesCreated.has_key(basicName):
            carmtmp = self.namesCreated[basicName]
            if carmtmp == testCarmtmp:
                return basicName
            else:
                basicName += "." + self.test.app.getFullVersion()
        self.namesCreated[basicName] = testCarmtmp
        self.diag.info(repr(self.namesCreated))
        self.testRuleName = basicName
        return basicName
    def getUserParentName(self, test):
        if isUserSuite(test.parent):
            return test.parent.name
        return self.getUserParentName(test.parent)
    def findQueueResource(self):
        return "rave" # all rave compilations now go to this queue which cannot be suspended
    def getBasicResources(self):
        if self.envResource:
            return [ self.envResource ]
        else:
            return []

class Config(CarmenConfig):
    def addToOptionGroups(self, app, groups):
        CarmenConfig.addToOptionGroups(self, app, groups)
        for group in groups:
            if group.name.startswith("Select"):
                group.addOption("u", "CARMUSRs containing")
            elif group.name.startswith("Advanced"):
                group.addSwitch("rulecomp", "Build all rulesets")
                group.addOption("build", "Build application target")
                group.addSwitch("skip", "Build no rulesets")
                group.addSwitch("debug", "Use debug rulesets")
                group.addSwitch("raveexp", "Run with RAVE Explorer")
            elif group.name.startswith("Invisible"):
                group.addOption("rset", "Private: used for submitting ruleset names to compile")
    def getFilterClasses(self):
        return CarmenConfig.getFilterClasses(self) + [ UserFilter ]
    def getSlaveServerClass(self):
        if self.buildRules():
            return RuleBuildSlaveServer
        else:
            return CarmenConfig.getSlaveServerClass(self)
    def getActivatorClass(self):
        if self.buildRules():
            return RuleBuildActivator
        else:
            return CarmenConfig.getActivatorClass(self)
    def isolatesDataUsingCatalogues(self, app):
        return app.getConfigValue("create_catalogues") == "true"
    def getTestProcessor(self): # active for slave and local runs
        baseProc = CarmenConfig.getTestProcessor(self)
        if not self.slaveRun() and self.buildRules():
            return self.getRuleActions() + baseProc
        else:
            return baseProc
    def getSlaveSwitches(self):
        return CarmenConfig.getSlaveSwitches(self) + [ "debug", "lprof", "raveexp" ]
    def isRaveRun(self):
        return self.optionValue("a").find("rave") != -1 or self.optionValue("v").find("rave") != -1
    def rebuildAllRulesets(self):
        return self.isNightJob() or (self.optionMap.has_key("rulecomp") and not self.optionValue("rulecomp"))\
               or self.isRaveRun()
    def buildRules(self):
        if self.optionMap.has_key("skip") or self.isReconnecting():
            return 0
        if self.optionMap.has_key("rulecomp"):
            return 1
        return self.defaultBuildRules()
    def defaultBuildRules(self):
        return 0
    def getRuleSetNames(self, test, forCompile=True):
        cmdLineOption = self.optionMap.get("rset")
        if cmdLineOption:
            cmdLineRules = cmdLineOption.split(",")
            if forCompile:
                return cmdLineRules
            else:
                allNames = self._getRuleSetNames(test)
                return filter(lambda name: name not in cmdLineRules, allNames)
        else:
            if forCompile:
                return self._getRuleSetNames(test)
            else:
                return []
    def _getRuleSetNames(self, test):
        raise plugins.TextTestError, "Cannot determine ruleset name(s), need to provide derived configuration to use rule compilation"
    def getRuleBuildFilterer(self):
        return FilterRuleBuilds()
    def getRuleActions(self):
        return [ self.getRuleBuildFilterer(), self.getRuleBuildObject(), EvaluateRuleBuild() ]
    def getRaveSubmissionRules(self, test):
        if queueSystemName(test.app) == "LSF":
            return self.getSubmissionRules(test)
        else:    
            return RaveSubmissionRules(self.optionMap, test, self.getRuleSetNames)
    def getRuleBuildObject(self):
        return CompileRules()
    def getSubmissionKiller(self):
        return KillRuleBuildOrTestSubmission()
    def raveMode(self):
        if self.optionMap.has_key("raveexp"):
            return "-explorer"
        elif self.optionMap.has_key("debug"):
            return "-debug"
        else:
            return "-optimize"
    def verifyWithEnvironment(self, suite):
        CarmenConfig.verifyWithEnvironment(self, suite)
        if self.optionMap.has_key("build"):
            builder = BuildCode(self.optionValue("build"))
            builder.build(suite.app)
    def _getLocalPlanPath(self, test):
        # Key assumption : to avoid reading Carmen Resource system LocalPlanPath
        # If this does not hold changing the CARMUSR is needed
        carmdataVar, carmdata = getCarmdata(test)
        return os.path.join(carmdata, "LOCAL_PLAN")
    def _getSubPlanDirName(self, test):
        subPlan = self._subPlanName(test)
        if not subPlan:
            return
        fullPath = os.path.join(self._getLocalPlanPath(test), subPlan)
        return os.path.normpath(fullPath)
    def _subPlanName(self, test):
        # just a stub so this configuration can be used directly
        pass
    def extraReadFiles(self, test):
        readDirs = CarmenConfig.extraReadFiles(self, test)
        if test.classId() == "test-case":
            subplan = self._getSubPlanDirName(test)
            if subplan and os.path.isdir(subplan):
                for title, fileName in self.filesFromSubplan(test, subplan):
                    readDirs[title] = [ fileName ]
            try:
                rulesets = [ os.path.join(test.getEnvironment("CARMUSR"), "crc", "source", name) \
                             for name in self.getRuleSetNames(test) ]
                if len(rulesets) > 0:
                    readDirs["Ruleset"] = rulesets
            except plugins.TextTestError:
                pass
        elif test.environment.has_key("CARMUSR"):
            files = self.getResourceFiles(test)
            if len(files):
                readDirs["Resources"] = files
        elif test.environment.has_key("CARMSYS"):
            raveModule = self.getRaveModule(test)
            if os.path.isfile(raveModule):
                readDirs["RAVE module"] = [ raveModule ]
        return readDirs
    def getResourceFiles(self, test):
        files = []
        customerFile = os.path.join(test.environment["CARMUSR"], "Resources", "CarmResources", "Customer.etab")
        if os.path.isfile(customerFile):
            files.append(customerFile)
        impFile = os.path.join(test.environment["CARMUSR"], "data", "config", "CarmResources", "Implementation.etab")
        if os.path.isfile(impFile):
            files.append(impFile)
        return files
    def getRaveModule(self, test):
        return os.path.join(test.environment["CARMSYS"], \
                            "carmusr_default", "crc", "modules", getBasicRaveName(test))
    def filesFromSubplan(self, test, subplanDir):
        return []
    def ensureDebugLibrariesExist(self, app):
        pass
    def setEnvironment(self, test):
        CarmenConfig.setEnvironment(self, test)
        # Change PATH so we can intercept crc_compile calls
        if test.parent and test.parent.parent is None and not self.slaveRun() and not self.useQueueSystem():
            carmsys = test.getEnvironment("CARMSYS")
            if carmsys and (not test.parent.environment.has_key("PATH") or \
                            test.parent.environment["PATH"].find("$CARMSYS/bin") == -1):
                test.setEnvironment("PATH", "$PATH:$CARMSYS/bin")
        if not test.parent and self.useQueueSystem():
            test.setEnvironment("_AUTOTEST__LOCAL_COMPILE_", "1")
    def printHelpOptions(self):
        CarmenConfig.printHelpOptions(self)
        print helpOptions
    def printHelpScripts(self):
        CarmenConfig.printHelpScripts(self)
        print helpScripts
    def printHelpDescription(self):
        print helpDescription
        CarmenConfig.printHelpDescription(self)
    def setApplicationDefaults(self, app):
        CarmenConfig.setApplicationDefaults(self, app)
        app.setConfigDefault("rave_name", { "default" : [] }, "Name of application as used by rule compilation")
        app.setConfigDefault("rave_static_library", "", "Library to link with when building static rulesets")
        app.setConfigDefault("lines_of_crc_compile", 30, "How many lines to present in textual previews of rave compilation failures")
        # dictionary of lists
        app.setConfigDefault("build_targets", { "" : [] }, "Directories to build in when -build specified")
        app.addConfigEntry("need_rulecompile", "white", "test_colours")
        app.addConfigEntry("pend_rulecompile", "white", "test_colours")
        app.addConfigEntry("running_rulecompile", "peach puff", "test_colours")
        app.addConfigEntry("ruleset_compiled", "white", "test_colours")

def getProductName(test):
    return os.popen(". $CARMSYS/CONFIG > /dev/null 2>&1; echo $PRODUCT").read().strip()

def getRaveNames(test):
    raveNameDir = test.getConfigValue("rave_name")
    if len(raveNameDir) == 1:
        return raveNameDir["default"]
    else:
        return test.getCompositeConfigValue("rave_name", getProductName(test))

def getBasicRaveName(test):
    return test.getConfigValue("rave_name")["default"][0]

def getCarmdata(test):
    carmdata = test.getEnvironment("CARMDATA")
    if carmdata:
        return "CARMDATA", os.path.normpath(carmdata)
    else:
        return "CARMUSR", os.path.normpath(test.getEnvironment("CARMUSR"))

# Pick up a temporary CARMUSR. Used directly by Studio, and a derived form used by the optimizers,
# that includes the raveparamters functionality
class PrepareCarmdataWriteDir(default.PrepareWriteDirectory):
    def __call__(self, test):
        default.PrepareWriteDirectory.__call__(self, test)
        # Collate the CARMUSR/CARMDATA. Hard to change config as we don't know which variable!
        if test.getEnvironment("CARMDATA"):
            self.collatePath(test, "$CARMDATA", self.partialCopyTestPath)
        else:
            self.collatePath(test, "$CARMUSR", self.partialCopyTestPath)
    
class RuleBuildActivator(Activator):
    def run(self):
        self.makeAppWriteDirectories()
        # push the non-rules tests last, to avoid indeterminism and decrease total time as these need two
        # SGE submissions
        testsNoRuleBuild = []
        ruleCompilations = []
        for test in self.allTests:
            rulecomp = self.getRuleCompilation(test)
            if rulecomp:
                ruleCompilations.append((test, rulecomp))
            else:
                testsNoRuleBuild.append(test)
        
        for test, rulecomp in ruleCompilations:
            test.makeWriteDirectory()
            self.submitRuleCompilation(test, rulecomp)
            
        for test in testsNoRuleBuild:
            test.makeWriteDirectory()
            QueueSystemServer.instance.submit(test)
            
        if len(ruleCompilations) > 0:
            QueueSystemServer.instance.submit("Completed submission of all rule compilations and tests that don't require rule compilation")
    def getRuleCompilation(self, test):
        try:
            filterer = test.app.getRuleBuildFilterer()
        except AttributeError:
            return
        return filterer.getRuleCompilation(test)
    def submitRuleCompilation(self, test, rulecomp):
        submissionRules = test.app.getRaveSubmissionRules(test)
        remoteCmd = os.path.join(os.path.dirname(plugins.textTestName), "remotecmd.py")
        test.changeState(NeedRuleCompilation(rulecomp))
        rulecompEnvVars = [ "CARMSYS", "CARMUSR", "CARMTMP", "CARMGROUP", "_AUTOTEST__LOCAL_COMPILE_" ] 
        for ruleset in rulecomp.rulesetsForSelf:
            postText = submissionRules.getSubmitSuffix()
            print "R: Submitting Rule Compilation for ruleset", ruleset.name, "(for test " + test.uniqueName + ")", postText
            compileArgs = [ remoteCmd, ruleset.targetFiles[0], SlaveServerResponder.submitAddress ] + ruleset.getCompilationArgs(remote=True)
            command = " ".join(compileArgs)
            QueueSystemServer.instance.submitJob(test, submissionRules, command, rulecompEnvVars)
        
        if test.state.category == "need_rulecompile":
            test.changeState(PendingRuleCompilation(rulecomp))

class RuleBuildRequestHandler(SlaveRequestHandler):        
    def handleRequestFromHost(self, hostname, requestId):
        if requestId.startswith("remotecmd.py"):
            self.handleRuleCompRequest(hostname, requestId)
        else:
            SlaveRequestHandler.handleRequestFromHost(self, hostname, requestId)
    def handleRuleCompRequest(self, hostname, requestId):
        self.connection.shutdown(SHUT_WR) # avoid deadlock, we don't plan to write anything
        diag = plugins.getDiagnostics("Synchroniser")
        header, name, status = requestId.split(":")
        diag.info("Got ruleset response for " + name)
        raveOutput = self.getRaveOutput(status)
        evaluator = EvaluateRuleBuild()
        ruleset = self.findRuleset(name)
        testsToSubmit = []
        for test in self.findTestsForRuleset(name):
            diag.info("Found test " + test.uniqueName)
            if test.state.isComplete():
                continue
            if status == "start":
                test.changeState(RunningRuleCompilation(test.state, hostname))
            else:
                if status == "exitcode=0":
                    ruleset.succeeded(raveOutput)
                else:
                    ruleset.failed(raveOutput)
                if evaluator.buildsSucceeded(test):
                    testsToSubmit.append(test)
                elif test.state.isComplete():
                    QueueSystemServer.instance.handleLocalError(test)
        # do this at the end to avoid output problems
        for test in testsToSubmit:
            QueueSystemServer.instance.submit(test)
        diag.info("Completed handling response for " + name)
    def findRuleset(self, name):
        return FilterRuleBuilds.rulesetNamesToRulesets.get(name)
    def findTestsForRuleset(self, name):
        return FilterRuleBuilds.rulesetNamesToTests.get(name, [])
    def getRaveOutput(self, status):
        if status == "start":
            return ""
        else:
            stdout, stderr = self.rfile.read().split("|STD_ERR|")
            return stdout + stderr
        
class RuleBuildSlaveServer(SlaveServerResponder):
    def handlerClass(self):
        return RuleBuildRequestHandler
                        
class EvaluateRuleBuild(plugins.Action):
    def __init__(self):
        self.diag = plugins.getDiagnostics("Synchroniser")
    def __call__(self, test):
        self.buildsSucceeded(test)
    def buildsSucceeded(self, test):
        self.diag.info("Evaluating rule build for " + test.uniqueName)
        if not hasattr(test.state, "rulecomp"):
            return False
        rulecomp = test.state.rulecomp
        fileToWrite = test.makeTmpFileName("crc_compile_output", forFramework=1)
        writeFile = open(fileToWrite, "w")
        writeFile.write(rulecomp.getRuleBuildOutput())
        writeFile.close()
        ruleset = rulecomp.findFailedRuleset()
        if ruleset:
            freeText = "Failed to build ruleset " + ruleset.name + "\n" + self.getPreview(test, ruleset.output)            
            test.changeState(plugins.Unrunnable(freeText, "Ruleset build failed"))
            return False
        elif rulecomp.allSucceeded():
            print "S: All rulesets compiled for", test.uniqueName, \
                  "(ruleset" + rulecomp.description() + ")"
            sys.stdout.flush() # don't get mixed up with what the submit thread might write
            return True
        else:
            return False
    def getPreview(self, test, raveInfo):
        # For final reports, abbreviate the free text to avoid newsgroup bounces etc.
        maxLength = test.getConfigValue("lines_of_crc_compile")
        maxWidth = test.getConfigValue("max_width_text_difference")
        previewGenerator = plugins.PreviewGenerator(maxWidth, maxLength, startEndRatio=0.5)
        return previewGenerator.getPreviewFromText(raveInfo)
            
class FilterRuleBuilds(plugins.Action):
    rulesetNamesToTests = {}
    rulesetNamesToRulesets = {}
    def __init__(self):
        self.diag = plugins.getDiagnostics("Filter Rule Builds")
    def __repr__(self):
        return "Filtering rule builds for"
    def getRuleCompilation(self, test):
        buildSelf, othersBuild = self.makeRulesets(test)
        if len(buildSelf + othersBuild) == 0:
            return None

        rulecomp = TestRuleCompilation(test, buildSelf, othersBuild)
        self.diag.info("Rule compilation for " + repr(test) + " : " + repr(rulecomp)) 
        return rulecomp
    def __call__(self, test):
        rulecomp = self.getRuleCompilation(test)
        if rulecomp:
            test.changeState(NeedRuleCompilation(rulecomp))
    def makeRulesets(self, test):
        unknown, known = [], []
        try:
            rulesetNames = test.app.getRuleSetNames(test)
        except plugins.TextTestError, e:
            # assume problems here are due to compilation itself not being setup, ignore
            print e
            return [], []

        for rulesetName in rulesetNames:
            ruleset = RuleSet(rulesetName, test)
            
            # If no ruleset is associated with the test anyway, or the source file isn't there, don't try to build it...
            if not ruleset.isValid():
                continue

            if self.shouldCompileFor(test, ruleset):
                self.ensureCarmTmpExists(test)
                targetName = ruleset.targetFiles[0]
                origRuleset = self.rulesetNamesToRulesets.get(targetName)
                if origRuleset:
                    known.append(origRuleset)
                else:
                    FilterRuleBuilds.rulesetNamesToTests[targetName] = []
                    unknown.append(ruleset)
                    self.rulesetNamesToRulesets[targetName] = ruleset
                self.rulesetNamesToTests[targetName].append(test)
            else:
                self.diag.info("Filter rejected rule build for " + test.name)
                
        return unknown, known
    def ensureCarmTmpExists(self, test):
        carmTmp = os.path.normpath(test.getEnvironment("CARMTMP"))
        if not os.path.isdir(carmTmp):
            if os.path.islink(carmTmp):
                print "CARMTMP", carmTmp, "seems to be a deadlink"
            else:
                print "CARMTMP", carmTmp, "did not exist, attempting to create it"
                os.makedirs(carmTmp)
    def getStaticLibrary(self, test):
        carmsys = test.getEnvironment("CARMSYS")
        libFile = test.getConfigValue("rave_static_library").replace("$CARMSYS", carmsys).replace("${CARMSYS}", carmsys)
        if test.app.raveMode() == "-debug":
            libFile = libFile.replace(".a", "_g.a")
        self.diag.info("Library file is " + libFile)
        return libFile
    def shouldCompileFor(self, test, ruleset):
        if test.app.rebuildAllRulesets() or not ruleset.isCompiled():
            return 1

        libFile = self.getStaticLibrary(test)
        if self.assumeDynamicLinkage(libFile, test.getEnvironment("CARMUSR")):
            return 0
        else:            
            return plugins.modifiedTime(ruleset.targetFiles[0]) < plugins.modifiedTime(libFile)
    def assumeDynamicLinkage(self, libFile, carmUsr):
        # If library file not defined, assume dynamic linkage and don't recompile
        return not libFile or not os.path.isfile(libFile)

class CompileRules(plugins.Action):
    def __init__(self):
        self.diag = plugins.getDiagnostics("Compile Rules")
    def __repr__(self):
        return "Compiling rules for"
    def getRuleCompilation(self, test):
        try:
            return test.state.rulecomp
        except AttributeError:
            pass
    def __call__(self, test):
        rulecomp = self.getRuleCompilation(test)
        if not rulecomp:
            return
        
        raveInfo = ""
        for ruleset in rulecomp.rulesetsForSelf:
            self.describe(test, " - ruleset " + ruleset.name)

            commandArgs = ruleset.getCompilationArgs(remote=False)
            if ruleset.modeString == "-debug":
                test.app.ensureDebugLibrariesExist()
            success, currRaveInfo = self.performCompile(test, commandArgs)
            if success:
                ruleset.succeeded(currRaveInfo)
            else:
                ruleset.failed(currRaveInfo)
    def performCompile(self, test, commandArgs):
        self.diag.info("Compiling with command '" + repr(commandArgs) + "' from directory " + os.getcwd())
        self.diag.info("PATH is " + os.getenv("PATH"))
        test.changeState(RunningRuleCompilation(test.state))
        proc = subprocess.Popen(commandArgs, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        raveInfo = proc.communicate()[0] # wait to finish
        if proc.returncode:
            return False, raveInfo
        else:
            return True, raveInfo

    def setUpSuite(self, suite):
        if suite.parent is None or isUserSuite(suite):
            self.describe(suite)
 
class KillRuleBuildOrTestSubmission(KillTestSubmission):
    def isRuleBuild(self, test):
        return test.state.category == "running_rulecompile"
    def jobStarted(self, test):
        return self.isRuleBuild(test) or test.state.hasStarted()
    def setKilled(self, test, killReason, jobId):
        if self.isRuleBuild(test):
            timeStr =  plugins.localtime("%H:%M")
            briefText = "Ruleset build killed at " + timeStr
            freeText = "Ruleset compilation killed explicitly at " + timeStr
            self.changeState(test, default.Cancelled(briefText, freeText))
        else:
            KillTestSubmission.setKilled(self, test, killReason, jobId)
    def setKilledPending(self, test):
        if self.isRuleBuild(test):
            timeStr =  plugins.localtime("%H:%M")
            briefText = "killed pending rule compilation at " + timeStr
            freeText = "Rule compilation job was killed (while still pending in " + queueSystemName(test.app) +\
                     ") at " + timeStr
            self.changeState(test, default.Cancelled(freeText, briefText))
        else:
            KillTestSubmission.setKilledPending(self, test)
    def setSlaveLost(self, test):
        if self.isRuleBuild(test):
            failReason = "no report from rule compilation (possibly killed with SIGKILL)"
            fullText = failReason + "\n" + self.getJobFailureInfo(test)
            self.changeState(test, plugins.Unrunnable(fullText, failReason))
        else:
            KillTestSubmission.setSlaveLost(self, test)
    def describeJob(self, test, jobId, jobName):
        if self.isRuleBuild(test):
            postText = self.getPostText(test, jobId)
            print "T: Cancelling job", jobName, postText
        else:
            KillTestSubmission.describeJob(self, test, jobId, jobName)

class TestRuleCompilation:
    rulesCompiled = {}
    def __init__(self, test, rulesetsToBuild, rulesetsFromOthers):
        self.rulesetsForSelf = rulesetsToBuild
        self.rulesetsFromOthers = rulesetsFromOthers
    def allSucceeded(self):
        for ruleset in self.allRulesets():
            if not ruleset.hasSucceeded():
                return False
        return True
    def allRulesets(self):
        return self.rulesetsForSelf + self.rulesetsFromOthers
    def __repr__(self):
        return ",".join(self.getRuleSetNames(self.rulesetsForSelf)) + " / " + self.reprOthers()
    def reprOthers(self):
        return ",".join(self.getRuleSetNames(self.rulesetsFromOthers))
    def getRuleSetNames(self, rulesets):
        return [ ruleset.name for ruleset in rulesets ]
    def getRuleBuildOutput(self):
        return "\n".join([ ruleset.output for ruleset in self.allRulesets() ])
    def findFailedRuleset(self):
        for ruleset in self.allRulesets():
            if ruleset.hasFailed():
                return ruleset
    def description(self):
        allRulesets = self.getRuleSetNames(self.allRulesets())
        if len(allRulesets) > 1:
            return "s " + " and ".join(allRulesets)
        else:
            return " " + allRulesets[0]

class NeedRuleCompilation(plugins.TestState):
    def __init__(self, rulecomp):
        self.rulecomp = rulecomp
        plugins.TestState.__init__(self, "need_rulecompile")
        
class PendingRuleCompilation(plugins.TestState):
    def __init__(self, rulecomp):
        self.rulecomp = rulecomp
        briefText = "RULES PEND"
        freeText = "Build pending for ruleset" + self.rulecomp.description()
        lifecycleChange="become pending for rule compilation"
        plugins.TestState.__init__(self, "pend_rulecompile", briefText=briefText, \
                                   freeText=freeText, lifecycleChange=lifecycleChange)

class RunningRuleCompilation(plugins.TestState):
    def __init__(self, prevState, hostname = None):
        self.rulecomp = prevState.rulecomp
        if not hostname:
            hostname = gethostname()
        briefText = "RULES (" + hostname + ")"
        freeText = "Compiling ruleset" + self.rulecomp.description() + " on " + hostname
        lifecycleChange = "start ruleset compilation"
        plugins.TestState.__init__(self, "running_rulecompile", briefText=briefText, \
                                   freeText=freeText, lifecycleChange=lifecycleChange)

class RuleSet:
    NOT_COMPILED = 0
    COMPILED = 1
    COMPILE_FAILED = 2
    def __init__(self, ruleSetName, test):
        self.name = ruleSetName
        self.envMethod = test.getEnvironment
        self.raveNames = getRaveNames(test)
        self.arch = getArchitecture(test.app)
        self.modeString = test.app.raveMode()
        self.sourceFile = self.sourcePath(self.name)
        self.targetFiles = []
        self.status = self.NOT_COMPILED
        self.output = ""
        for raveName in self.raveNames:
            self.targetFiles.append(self.targetPath("rule_set", raveName, self.arch, self.name))
            if self.modeString == "-debug":
                self.targetFiles[-1] += "_g"
    def hasSucceeded(self):
        return self.status == self.COMPILED
    def hasFailed(self):
        return self.status == self.COMPILE_FAILED
    def succeeded(self, output):
        self.status = self.COMPILED
        self.output = output
    def failed(self, output):
        self.status = self.COMPILE_FAILED
        self.output = output
    def getCompilationArgs(self, remote):
        return [ self.getExecutable(remote) ] + self.raveNames + self.getModeArgs() + [ "-archs", self.arch, self.sourceFile ]
    def getExecutable(self, remote):
        if remote:
            # Don't allow interception or path corruption
            return os.path.join(self.envMethod("CARMSYS"), "bin", "crc_compile")
        else:
            # Let the traffic mechanism intercept local runs though
            return "crc_compile"
    def getModeArgs(self):
        raveMode = self.envMethod("TEXTTEST_RAVE_MODE")
        if raveMode:
            return [ self.modeString, raveMode ]
        else:
            return [ self.modeString ]
    def isValid(self):
        return self.name and os.path.isfile(self.sourceFile)
    def isCompiled(self):
        for targetFile in self.targetFiles:
            if not os.path.isfile(targetFile):
                return False
        return True
    def targetPath(self, type, raveName, arch, name):
        return os.path.join(self.envMethod("CARMTMP"), "crc", type, raveName.upper(), arch, name)
    def sourcePath(self, name):
        return os.path.join(self.envMethod("CARMUSR"), "crc", "source", name)
    def backup(self):
        if self.isCompiled():
            try:
                for targetFile in self.targetFiles:
                    shutil.copyfile(targetFile, targetFile + ".bak")
            except IOError:
                plugins.printWarning("Did not have permissions to backup ruleset, continuing anyway.")
            
# Graphical import suite
class ImportTestSuite(guiplugins.ImportTestSuite):
    def getEnvironment(self, envVar):
        if self.currentTest:
            return self.currentTest.getEnvironment("CARMUSR", "")
        else:
            return ""
    def addEnvironmentFileOptions(self):
        usr = self.getEnvironment("CARMUSR")
        dta = self.getEnvironment("CARMDATA")
        if dta == usr:
            dta = ""
        if dta and usr:
            try:
                rdta = os.path.realpath(dta)
                rusr = os.path.realpath(usr)
                if rdta.startswith(rusr):
                    dta=""
            except:
                    dta=""
        self.optionGroup.addOption("usr", "CARMUSR", usr)
        self.optionGroup.addOption("data", "CARMDATA (only if different)", dta)
    def updateOptionGroup(self, state):
        guiplugins.ImportTestSuite.updateOptionGroup(self, state)
        self.optionGroup.setOptionValue("usr", "")
        self.optionGroup.setOptionValue("data", "")
    def getCarmValue(self, val):
        optionVal = self.optionGroup.getOptionValue(val)
        if optionVal:
            return os.path.normpath(optionVal)
    def hasStaticLinkage(self, carmUsr):
        return 1
    def openFile(self, fileName):
        guiplugins.guilog.info("Writing file " + os.path.basename(fileName))
        return open(fileName, "w")
    def writeLine(self, file, line):
        file.write(line + os.linesep)
        guiplugins.guilog.info(line)
    def getCarmtmpDirName(self, carmUsr):
        # Important not to get basename clashes - this can lead to isolation problems
        baseName = os.path.basename(carmUsr)
        if baseName.find("_user") != -1:
            return baseName.replace("_user", "_tmp")
        else:
            return baseName + "_tmp"
    def getEnvironmentFileName(self, suite):
        return "environment." + suite.app.name
    def writeEnvironmentFiles(self, suite, testDir):
        carmUsr = self.getCarmValue("usr")
        if not carmUsr:
            return
        envFile = os.path.join(testDir, self.getEnvironmentFileName(suite))
        file = self.openFile(envFile)
        self.writeLine(file, "CARMUSR:" + carmUsr)
        carmData = self.getCarmValue("data")
        if carmData:
            self.writeLine(file, "CARMDATA:" + carmData)
        carmtmp = self.getCarmtmpDirName(carmUsr)
        if self.hasStaticLinkage(carmUsr):
            self.writeLine(file, "CARMTMP:$CARMSYS/" + carmtmp)
            return

        self.writeLine(file, "CARMTMP:" + self.getCarmtmpPath(carmtmp))
        envLocalFile = os.path.join(testDir, "environment.local")
        localFile = self.openFile(envLocalFile)
        self.writeLine(localFile, "CARMTMP:$CARMSYS/" + carmtmp)
    def getCarmtmpPath(self, carmtmp):
        pass
    # getCarmtmpPath implemented by subclasses

class BuildCode:
    builtDirs = {}
    buildFailedDirs = {}
    def __init__(self, target):
        self.target = target
    def build(self, app):
        targetDir = app.getConfigValue("build_targets")
        if not targetDir.has_key(self.target):
            return
        arch = getArchitecture(app)
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
    def getPathAndTargets(self, optValue):
        relPath = os.path.normpath(optValue)
        makeTargets = ""
        optParts = string.split(optValue)
        if len(optParts) > 1:
            relPath = os.path.normpath(optParts[0])
            makeTargets = string.join(optParts[1:])
        return (relPath, makeTargets)
    def getMachine(self, app, arch):
        version12 = "12" in app.versions
        if arch == "i386_linux":
            if version12:
                return "taylor"
            else:
                return "abbeville"
        if arch == "sparc":
            return "turin"
        if arch == "sparc_64":
            return "elmira"
        if arch == "parisc_2_0":
            return "ramechap"
        if arch == "powerpc":
            return "tororo"
        if arch == "ia64_hpux":
            return "wakeman"
        if arch == "x86_64_linux":
            if version12:
                return "centreville"
            else:
                return "brockville"
    def getRemoteCommandLine(self, arch, absPath, makeCommand):
        commandLine = makeCommand + " -C " + absPath
        if arch == "sparc_64" or arch == "x86_64_linux":
            commandLine = "setenv BITMODE 64; " + commandLine
        return commandLine
    def buildLocal(self, absPath, app, makeTargets):
        arch = getArchitecture(app)
        buildFile = os.path.join(absPath, "build.default." + arch)
        extra = ""
        if app.raveMode() == "-debug":
            extra = "VERSION=debug "
        makeCommand = "gmake " + extra + makeTargets
        commandLine = self.getRemoteCommandLine(arch, absPath, makeCommand)
        machine = self.getMachine(app, arch)
        print "Building", app, "in", absPath, "on", machine, "..."
        os.system("rsh " + machine + " '" + commandLine + "' < /dev/null > " + buildFile + " 2>&1")
        if self.checkBuildFile(buildFile):
            self.buildFailedDirs[arch].append(absPath)
            raise plugins.TextTestError, "BUILD ERROR: Product " + repr(app) + " did not build!" + os.linesep + \
                  "(See " + os.path.join(absPath, buildFile) + " for details)"
        print "Product", app, "built correctly in", absPath
        self.builtDirs[arch].append(absPath)
        os.remove(buildFile)
        if os.environ.has_key("CARMSYS"):
            makeCommand = "gmake install " + extra + "CARMSYS=" + os.environ["CARMSYS"]
            commandLine = self.getRemoteCommandLine(arch, absPath, makeCommand)
            os.system("rsh " + machine + " '" + commandLine + "' < /dev/null > /dev/null 2>&1")
            print "Making install from", absPath ,"to", os.environ["CARMSYS"]
    def checkBuildFile(self, buildFile):
        for line in open(buildFile).xreadlines():
            if line.find("***") != -1 and line.find("Error") != -1:
                return 1
        return 0

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
