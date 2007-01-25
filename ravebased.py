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

import queuesystem, default, os, string, shutil, plugins, sys, signal, stat, guiplugins
from socket import gethostname
from tempfile import mktemp
from respond import Responder
from copy import copy
from traffic_cmd import sendServerState
from carmenqueuesystem import getArchitecture, CarmenConfig, CarmenSgeSubmissionRules

def getConfig(optionMap):
    return Config(optionMap)

def isUserSuite(suite):
    return suite.environment.has_key("CARMUSR")

class UserFilter(default.TextFilter):
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
    def __init__(self, optionMap, test, getRuleSetName):
        CarmenSgeSubmissionRules.__init__(self, optionMap, test, nightjob=False)
        self.diag = plugins.getDiagnostics("Rule job names")
        self.getRuleSetName = getRuleSetName
        self.testRuleName = None
    def getMajorReleaseResourceType(self):
        return "build"
    def getProcessesNeeded(self):
        return "1"
    def findPriority(self):
        # Don't lower the priority of these
        return 0
    def getEnvironmentResource(self):
        return os.getenv("QUEUE_SYSTEM_RESOURCE_RAVE", "")
    def getJobName(self):
        if self.testRuleName:
            return self.testRuleName
        basicName = "Rules-" + self.getRuleSetName(self.test) + "." + self.getUserParentName(self.test) + "-" + getBasicRaveName(self.test)
        if self.namesCreated.has_key(basicName):
            carmtmp = self.namesCreated[basicName]
            if carmtmp == os.environ["CARMTMP"]:
                return basicName
            else:
                basicName += "." + self.test.app.getFullVersion()
        self.namesCreated[basicName] = os.environ["CARMTMP"]
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
    def getSubmitSuffix(self, name):
        return " (" + self.getRuleSetName(self.test) + " ruleset)" + \
               CarmenSgeSubmissionRules.getSubmitSuffix(self, name)

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
                group.addOption("raveslave", "Private: used for submitting slaves to compile rulesets")
    def getFilterClasses(self):
        return CarmenConfig.getFilterClasses(self) + [ UserFilter ]
    def useExtraVersions(self, app):
        return CarmenConfig.useExtraVersions(self, app) and not self.raveSlave()
    def isolatesDataUsingCatalogues(self, app):
        return app.getConfigValue("create_catalogues") == "true"
    def getResponderClasses(self, allApps):
        if self.raveSlave():
            return self.getSlaveResponderClasses()
        baseResponders = CarmenConfig.getResponderClasses(self, allApps)
        if self.useQueueSystem():
            baseResponders.append(RuleBuildSynchroniser)
        return baseResponders
    def getActionSequence(self):
        if self.slaveRun() or self.optionMap.has_key("coll") or self.isReconnecting():
            return CarmenConfig.getActionSequence(self)

        if self.raveSlave():
            return [ SetBuildRequired(self.getRuleSetName), self.getRuleBuildObject() ]
        
        # Drop the write directory maker, in order to insert the rulebuilder in between it and the test runner
        return [ self.getAppBuilder(), self.getWriteDirectoryMaker(), self.getCarmVarChecker(), self.getRuleActions() ] + \
                 CarmenConfig._getActionSequence(self, makeDirs = 0)
    def raveSlave(self):
        return self.optionMap.has_key("raveslave")
    def getSlaveSwitches(self):
        return CarmenConfig.getSlaveSwitches(self) + [ "debug", "lprof", "raveexp" ]
    def getWriteDirectoryName(self, app):
        slaveDir = self.optionMap.get("raveslave")
        if slaveDir:
            return slaveDir
        else:
            return CarmenConfig.getWriteDirectoryName(self, app)
    def getCleanMode(self):
        if self.raveSlave():
            return self.CLEAN_NONE
        else:
            return CarmenConfig.getCleanMode(self)
    def getCarmVarChecker(self):
        if not self.isReconnecting():
            return CheckCarmVariables()
        else:
            return None
    def getRuleCleanup(self):
        return CleanupRules(self.getRuleSetName)
    def isRaveRun(self):
        return self.optionValue("a").find("rave") != -1 or self.optionValue("v").find("rave") != -1
    def rebuildAllRulesets(self):
        return self.isNightJob() or (self.optionMap.has_key("rulecomp") and not self.optionValue("rulecomp")) or self.isRaveRun()
    def getRuleActions(self):
        if self.buildRules():
            realBuilder = self.getRealRuleActions()
            if self.optionValue("rulecomp") != "clean":
                return realBuilder
            else:
                return [ self.getRuleCleanup(), realBuilder ]
        else:
            return None
    def getRuleSetName(self, test):
        raise plugins.TextTestError, "Cannot determine ruleset name, need to provide derived configuration to use rule compilation"
    def getRuleBuildFilterer(self):
        return FilterRuleBuilds(self.getRuleSetName, self.rebuildAllRulesets())
    def getRealRuleActions(self):
        filterer = self.getRuleBuildFilterer()
        if self.useQueueSystem():
            submitter = SubmitRuleCompilations(self.getRaveSubmissionRules, self.optionMap, self.getSlaveSwitches())
            waiter = WaitForRuleCompile(self.getRuleSetName)
            return [ filterer, submitter, waiter ]
        else:
            return [ filterer, self.getRuleBuildObject(), SynchroniseState() ]
    def getRaveSubmissionRules(self, test):
        if queuesystem.queueSystemName(test.app) == "LSF":
            return self.getSubmissionRules(test)
        else:    
            return RaveSubmissionRules(self.optionMap, test, self.getRuleSetName)
    def getRuleBuildObject(self):
        return CompileRules(self.getRuleSetName, self.raveMode())
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
        else:
            return None
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
                ruleset = self.getRuleSetName(test)
                if ruleset:
                    readDirs["Ruleset"] = [ os.path.join(test.getEnvironment("CARMUSR"), "crc", "source", ruleset) ]
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
    def setEnvironment(self, test):
        CarmenConfig.setEnvironment(self, test)
        if test.parent and test.parent.parent is None:
            carmsys = test.getEnvironment("CARMSYS")
            if carmsys and (not test.parent.environment.has_key("PATH") or \
                            test.parent.environment["PATH"].find("$CARMSYS/bin") == -1):
                test.setEnvironment("PATH", "$PATH:$CARMSYS/bin")
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
        if os.environ.has_key("CARMDATA"):
            self.collatePath(test, "$CARMDATA", self.partialCopyTestPath)
        else:
            self.collatePath(test, "$CARMUSR", self.partialCopyTestPath)
    
class CleanupRules(plugins.Action):
    def __init__(self, getRuleSetName):
        self.rulesCleaned = []
        self.raveNames = []
        self.getRuleSetName = getRuleSetName
    def __repr__(self):
        return "Cleanup rules for"
    def __call__(self, test):
        arch = getArchitecture(test.app)
        ruleset = RuleSet(self.getRuleSetName(test), self.raveNames, arch)
        for raveName in self.raveNames:
            if self.shouldCleanup(ruleset):
                self.describe(test, " - ruleset " + ruleset.name)
                self.rulesCleaned.append(ruleset.name)
                self.removeRuleSet(arch, ruleset.name, raveName)
                self.removeRuleCompileFiles(arch, raveName)
                self.removeRulePrecompileFiles(ruleset.name, raveName)
    def removeRuleSet(self, arch, name, raveName):
        carmTmp = os.environ["CARMTMP"]
        targetPath = os.path.join(carmTmp, "crc", "rule_set", string.upper(raveName), arch, name)
        self.removeFile(targetPath)
        self.removeFile(targetPath + ".bak")
    def removeRuleCompileFiles(self, arch, raveName):
        carmTmp = os.environ["CARMTMP"]
        targetPath = os.path.join(carmTmp, "compile", string.upper(raveName), arch + "_opt")
        if os.path.isdir(targetPath):
            for file in os.listdir(targetPath):
                if file.endswith(".o"):
                    self.removeFile(os.path.join(targetPath, file))
    def removeRulePrecompileFiles(self, name, raveName):
        carmTmp = os.environ["CARMTMP"]
        targetPath = os.path.join(carmTmp, "compile", string.upper(raveName), name)
        self.removeFile(targetPath + "_recompile.xml")
        targetPath = os.path.join(carmTmp, "crc", "rule_set", string.upper(raveName), name)
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
        if self.raveNames == []:
            self.raveNames = getRaveNames(suite)

class SetBuildRequired(plugins.Action):
    def __init__(self, getRuleSetName):
        self.getRuleSetName = getRuleSetName
    def __call__(self, test):
        test.changeState(NeedRuleCompilation(self.getRuleSetName(test)))
    def setUpApplication(self, app):
        # If building rulesets remotely, don't distribute them further...
        os.environ["_AUTOTEST__LOCAL_COMPILE_"] = "1"

class FilterRuleBuilds(plugins.Action):
    rulesCompiled = {}
    def __init__(self, getRuleSetName, forceRebuild):
        self.raveNames = []
        self.getRuleSetName = getRuleSetName
        self.forceRebuild = forceRebuild
        self.diag = plugins.getDiagnostics("Filter Rule Builds")
    def __repr__(self):
        return "Filtering rule builds for"
    def __call__(self, test):
        arch = getArchitecture(test.app)
        try:
            ruleset = RuleSet(self.getRuleSetName(test), self.raveNames, arch, test.app.configObject.target.raveMode())
        except plugins.TextTestError, e:
            # assume problems here are due to compilation itself not being setup, ignore
            print e
            return

        # If no ruleset is associated with the test anyway, don't try to build it...
        if not ruleset.name:
            return
        
        if not ruleset.isValid():
            if os.environ.has_key("ALLOW_INVALID_RULESETS"):
                return
            else:
                raise plugins.TextTestError, "Could not compile ruleset '" + ruleset.name + "' : rule source file does not exist"

        if not self.shouldCompileFor(test, ruleset):
            self.diag.info("Filter rejected rule build for " + test.name)
            return
        
        targetName = ruleset.targetFiles[0]
        # We WAIT here to avoid race conditions - make sure everyone knows the state of their
        # rule compilations before we start any of them.
        if self.rulesCompiled.has_key(targetName):
            test.changeState(NeedRuleCompilation(ruleset.name, self.rulesCompiled[targetName]))
            return self.WAIT
        ruleset.backup()
        self.rulesCompiled[targetName] = test
        test.changeState(NeedRuleCompilation(self.getRuleSetName(test)))
        return self.WAIT
    def setUpSuite(self, suite):
        if isUserSuite(suite):
            self.raveNames = getRaveNames(suite)
    def shouldCompileFor(self, test, ruleset):
        if self.forceRebuild or not ruleset.isCompiled():
            return 1

        libFile = test.getConfigValue("rave_static_library")
        if test.app.configObject.target.raveMode() == "-debug":
            libFile = libFile.replace(".a", "_g.a")
        self.diag.info("Library file is " + libFile)
        if self.assumeDynamicLinkage(libFile, test.getEnvironment("CARMUSR")):
            return 0
        else:            
            return plugins.modifiedTime(ruleset.targetFiles[0]) < plugins.modifiedTime(libFile)
    def assumeDynamicLinkage(self, libFile, carmUsr):
        # If library file not defined, assume dynamic linkage and don't recompile
        return not libFile or not os.path.isfile(libFile)        

class SubmitRuleCompilations(queuesystem.SubmitTest):
    def slaveType(self):
        return "raveslave"
    def __repr__(self):
        return "Submitting Rule Builds for"
    def __call__(self, test):
        if test.state.category != "need_rulecompile":
            return

        if test.state.testCompiling:
            self.setPending(test)
            return self.WAIT
        return queuesystem.SubmitTest.__call__(self, test)
    def getPendingState(self, test):
        return PendingRuleCompilation(test.state)

class CompileRules(plugins.Action):
    def __init__(self, getRuleSetName, modeString = "-optimize"):
        self.getRuleSetName = getRuleSetName
        self.modeString = modeString
        self.diag = plugins.getDiagnostics("Compile Rules")
    def __repr__(self):
        return "Compiling rules for"
    def __call__(self, test):
        if test.state.category != "need_rulecompile" or test.state.testCompiling != None:
            return
        arch = getArchitecture(test.app)
        raveNames = getRaveNames(test)
        ruleset = RuleSet(self.getRuleSetName(test), raveNames, arch, self.modeString)
        self.describe(test, " - ruleset " + ruleset.name)

        # Fix to be able to run crc_compile for apc also on Carmen 8.
        # crc_compile provides backward compability, so we can always have the '-'.
        extra = ""
        if test.app.name == "apc":
            extra = "-"
        commandLine = "crc_compile " + extra + string.join(raveNames) + " " + self.getModeString() \
                          + " -archs " + arch + " " + ruleset.sourceFile
        self.performCompile(test, ruleset.name, commandLine)
    def getModeString(self):
        if os.environ.has_key("TEXTTEST_RAVE_MODE"):
            return self.modeString + " " + os.environ["TEXTTEST_RAVE_MODE"]
        else:
            return self.modeString
    def performCompile(self, test, ruleset, commandLine):
        # We don't have a write directory here if running remotely and creating one tends to cause the Eqw problem
        # Instead we write a temporary file and send the contents over the wires.
        compTmp = mktemp()
        self.diag.info("Compiling with command '" + commandLine + "' from directory " + os.getcwd())
        fullCommand = commandLine + " > " + compTmp + " 2>&1"
        test.changeState(RunningRuleCompilation(test.state))
        retStatus = os.system(fullCommand)
        raveInfo = open(compTmp).read()
        fileToWrite = test.makeTmpFileName("crc_compile_output", forFramework=1)
        if retStatus:
            freeText = "Failed to build ruleset " + self.getRuleSetName(test) + "\n" + self.getPreview(test, open(compTmp))
            test.changeState(RuleBuildFailed(freeText, "Ruleset build failed", raveInfo, fileToWrite))
        else:
            test.changeState(RulesetCompiled(raveInfo, fileToWrite))
        os.remove(compTmp)        
    def getPreview(self, test, compTmp):
        # For final reports, abbreviate the free text to avoid newsgroup bounces etc.
        maxLength = test.getConfigValue("lines_of_crc_compile")
        maxWidth = test.getConfigValue("max_width_text_difference")
        previewGenerator = plugins.PreviewGenerator(maxWidth, maxLength, startEndRatio=0.5)
        return previewGenerator.getPreview(compTmp)
    def setUpSuite(self, suite):
        if suite.parent is None or isUserSuite(suite):
            self.describe(suite)
    def getInterruptActions(self, fetchResults):
        return [ RuleBuildKilled() ]

class RuleBuildKilled(queuesystem.KillTestInSlave):
    def __call__(self, test):
        if test.state.category != "running_rulecompile":
            return
        short, long = self.getKillInfo(test)
        briefText = "Ruleset build " + short
        freeText = "Ruleset compilation " + long
        test.changeState(RuleBuildFailed(freeText, briefText))    
    
class SynchroniseState(plugins.Action):
    def getCompilingTestState(self, test):
        try:
            return test.state.testCompiling.state
        except AttributeError:
            return None
    def getRuleSetName(self, test):
        try:
            return test.state.rulesetName
        except AttributeError:
            return None
    def __call__(self, test):
        newState = self.getCompilingTestState(test)
        if newState:
            self.synchronise(test, newState)
    def synchronise(self, test, newState):
        if self.waitingForSynchronise(test):
            test.changeState(copy(newState))
    def waitingForSynchronise(self, test):
        if test.state.hasStarted():
            return False
        rulesetName = self.getRuleSetName(test)
        if rulesetName:
            return True
        else:
            # Means we've got some other situation than a rule compilation failing or succeeding...
            return False

class RuleBuildSynchroniser(Responder):
    def __init__(self, optionMap):
        self.updateMap = {}
        self.synchroniser = SynchroniseState()
        self.diag = plugins.getDiagnostics("Synchroniser")
    def notifyLifecycleChange(self, test, state, changeDesc):
        self.diag.info("Got change " + repr(test) + " -> " + state.category)
        self.writeRaveFile(test, state)
        if state.category == "pend_rulecompile":
            self.registerUpdate(state.testCompiling, test)
        elif self.updateMap.has_key(test):
            for updateTest in self.updateMap[test]:
                self.diag.info("Generated change for " + repr(updateTest))
                self.synchroniser.synchronise(updateTest, state)
                self.diag.info("Done.")
    def registerUpdate(self, comptest, test):
        if comptest:
            self.updateMap[comptest].append(test)
        else:
            self.updateMap[test] = []
    def writeRaveFile(self, test, state):
        try:
            raveFile = state.raveFile
            raveInfo = state.raveInfo
        except AttributeError:
            return
        if not raveFile:
            return
        fileToWrite = test.makeTmpFileName("crc_compile_output", forFramework=1)
        self.diag.info("Rave file at " + raveFile + ", write at " + fileToWrite)
        plugins.ensureDirExistsForFile(fileToWrite)
        if fileToWrite == raveFile:
            writeFile = open(fileToWrite, "w")
            writeFile.write(raveInfo)
            writeFile.close()
        else:
            os.symlink(raveFile, fileToWrite)

class WaitForRuleCompile(queuesystem.WaitForCompletion):
    raveMessageSent = False
    def __init__(self, getRuleSetName):
        self.getRuleSetName = getRuleSetName
    def __repr__(self):
        return "Evaluating Rule Build for"
    def __call__(self, test):
        # Don't do this if tests not compiled
        if test.state.category == "not_started":
            return
        self.tryNotifyState()
        if not test.state.isComplete() and test.state.category != "ruleset_compiled":
            return self.WAIT | self.RETRY
        self.describe(test, self.getResultText(test))
    def tryNotifyState(self):
        if not self.raveMessageSent:
            WaitForRuleCompile.raveMessageSent = True
            sendServerState("Completed submission of all rule compilations")
    def getResultText(self, test):
        text = " (ruleset " + self.getRuleSetName(test) + " "
        if test.state.isComplete():
            text += "FAILED!"
        else:
            text += "ok"
        return text + ")"
    def getInterruptActions(self, fetchResults):
        actions = [ KillRuleBuildSubmission() ]
        if fetchResults:
            actions.append(queuesystem.WaitForKill())
        return actions

class KillRuleBuildSubmission(queuesystem.KillTestSubmission):
    def __repr__(self):
        return "Cancelling Rule Build"
    def jobStarted(self, test):
        return test.state.category != "need_rulecompile" and test.state.category != "pend_rulecompile"
    def setKilledPending(self, test):
        timeStr =  plugins.localtime("%H:%M")
        briefText = "killed pending rule compilation at " + timeStr
        freeText = "Rule compilation job was killed (while still pending in " + queuesystem.queueSystemName(test.app) +\
                   ") at " + timeStr
        test.changeState(RuleBuildFailed(freeText, briefText))
    def setSlaveLost(self, test):
        failReason = "no report from rule compilation (possibly killed with SIGKILL)"
        fullText = failReason + "\n" + self.getJobFailureInfo(test)
        test.changeState(RuleBuildFailed(fullText, failReason))
    def describeJob(self, test, jobId, jobName):
        postText = self.getPostText(test, jobId)
        print test.getIndent() + repr(self), jobName + postText

class NeedRuleCompilation(plugins.TestState):
    def __init__(self, rulesetName, testCompiling = None):
        self.rulesetName = rulesetName
        self.testCompiling = testCompiling
        plugins.TestState.__init__(self, "need_rulecompile")
        
class PendingRuleCompilation(plugins.TestState):
    def __init__(self, prevState):
        self.rulesetName = prevState.rulesetName
        self.testCompiling = prevState.testCompiling
        briefText = "RULES PEND"
        freeText = "Build pending for ruleset '" + self.rulesetName + "'"
        lifecycleChange="become pending for rule compilation"
        plugins.TestState.__init__(self, "pend_rulecompile", briefText=briefText, \
                                   freeText=freeText, lifecycleChange=lifecycleChange)

class RunningRuleCompilation(plugins.TestState):
    def __init__(self, prevState, compilingState = None):
        self.testCompiling = prevState.testCompiling
        self.rulesetName = prevState.rulesetName
        if compilingState:
            briefText = compilingState.briefText
            freeText = compilingState.freeText
        else:
            briefText = "RULES (" + gethostname() + ")"
            freeText = "Compiling ruleset " + self.rulesetName + " on " + gethostname()
        lifecycleChange = "start ruleset compilation"
        plugins.TestState.__init__(self, "running_rulecompile", briefText=briefText, \
                                   freeText=freeText, lifecycleChange=lifecycleChange)

class RuleBuildFailed(plugins.Unrunnable):
    def __init__(self, freeText, briefText, raveInfo="", raveFile=""):
        plugins.Unrunnable.__init__(self, freeText, briefText)
        self.raveInfo = raveInfo
        self.raveFile = raveFile

class RulesetCompiled(plugins.TestState):
    def __init__(self, raveInfo, raveFile):
        plugins.TestState.__init__(self, "ruleset_compiled", lifecycleChange="complete rule compilation")
        self.raveInfo = raveInfo
        self.raveFile = raveFile

class RuleSet:
    def __init__(self, ruleSetName, raveNames, arch, modeString = "-optimize"):
        self.name = ruleSetName
        if not self.name:
            return
        self.sourceFile = self.sourcePath(self.name)
        self.targetFiles = []
        for raveName in raveNames:
            self.targetFiles.append(self.targetPath("rule_set", raveName, arch, self.name))
            if modeString == "-debug":
                self.targetFiles[-1] += "_g"
    def isValid(self):
        return self.name and os.path.isfile(self.sourceFile)
    def isCompiled(self):
        for targetFile in self.targetFiles:
            if not os.path.isfile(targetFile):
                return False
        return True
    def targetPath(self, type, raveName, arch, name):
        return os.path.join(os.environ["CARMTMP"], "crc", type, string.upper(raveName), arch, name)
    def sourcePath(self, name):
        return os.path.join(os.environ["CARMUSR"], "crc", "source", name)
    def backup(self):
        if self.isCompiled():
            try:
                for targetFile in self.targetFiles:
                    shutil.copyfile(targetFile, targetFile + ".bak")
            except IOError:
                plugins.printWarning("Did not have permissions to backup ruleset, continuing anyway.")
            
# Graphical import suite
class ImportTestSuite(guiplugins.ImportTestSuite):
    def addEnvironmentFileOptions(self):
        usr = os.getenv("CARMUSR")
        if not usr:
            usr=""
        dta = os.getenv("CARMDATA")
        if not dta:
            dta=""
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

class BuildCode(plugins.Action):
    builtDirs = {}
    buildFailedDirs = {}
    def __init__(self, target):
        self.target = target
    def setUpApplication(self, app):
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
        os.chdir(absPath)
        arch = getArchitecture(app)
        buildFile = "build.default." + arch
        extra = ""
        if app.configObject.target.raveMode() == "-debug":
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
