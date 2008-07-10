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

import os, string, shutil, plugins, sandbox, sys, stat, subprocess, operator
from socket import gethostname, SHUT_WR
from respond import Responder
from copy import copy
from traffic_cmd import sendServerState
from carmenqueuesystem import getArchitecture, CarmenConfig, CarmenSgeSubmissionRules
from queuesystem import queueSystemName, SlaveServerResponder, SlaveRequestHandler, QueueSystemServer
from ndict import seqdict
from Queue import Queue
RuleBuildFailed = plugins.Unrunnable # for backwards compatibility with old website files

def getConfig(optionMap):
    return Config(optionMap)

def isUserSuite(suite):
    return suite.hasEnvironment("CARMUSR") and (not suite.parent or not suite.parent.hasEnvironment("CARMUSR"))

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
    def addToOptionGroups(self, apps, groups):
        CarmenConfig.addToOptionGroups(self, apps, groups)
        for group in groups:
            if group.name.startswith("Select"):
                group.addOption("u", "CARMUSRs containing")
            elif group.name.startswith("Advanced"):
                useSkipSwitch = reduce(operator.and_, (self.buildRulesetsAlways(app) for app in apps), False)
                if useSkipSwitch:
                    group.addSwitch("skip", "Skip ruleset builds")
                else:
                    group.addSwitch("rulecomp", "Build all rulesets")
                group.addOption("build", "Build application target")
                group.addSwitch("debug", "Use debug rulesets")
                group.addSwitch("raveexp", "Run with RAVE Explorer")
    def getFilterClasses(self):
        return CarmenConfig.getFilterClasses(self) + [ UserFilter ]
    def getSlaveServerClass(self):
        if self.buildRules():
            return RuleBuildSlaveServer
        else:
            return CarmenConfig.getSlaveServerClass(self)
    def getQueueServerClass(self):
        if self.buildRules():
            return RuleBuildSubmitServer
        else:
            return CarmenConfig.getQueueServerClass(self)
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
    def ignoreExecutable(self):
        if self.optionMap.runScript() and self.optionMap["s"].endswith("PrintRulesets"):
            return False
        return CarmenConfig.ignoreExecutable(self)
    def buildRulesetsAlways(self, app):
        return app.getConfigValue("build_rulesets_always") == "true"
    def rebuildAllRulesets(self, app):
        return self.isNightJob() or self.optionMap.has_key("rulecomp") or self.buildRulesetsAlways(app)
    def buildRules(self):
        if self.optionMap.has_key("skip") or self.isReconnecting() or self.optionMap.has_key("autoreplay"):
            return 0
        if self.optionMap.has_key("rulecomp"):
            return 1
        return self.defaultBuildRules()
    def defaultBuildRules(self):
        return 0
    def getRuleSetNames(self, test, forCompile=True):
        cmdLineOption = self.optionMap.get("rulecomp")
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
    def raveMode(self):
        if self.optionMap.has_key("raveexp"):
            return "-explorer"
        elif self.optionMap.has_key("debug"):
            return "-debug"
        else:
            return "-optimize"
    def checkSanity(self, suite):
        CarmenConfig.checkSanity(self, suite)
        if self.optionMap.has_key("build"):
            builder = BuildCode(self.optionValue("build"))
            builder.build(suite)
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
    def getSubplanRuleset(self, test):
        subplanDir = self._getSubPlanDirName(test)
        if subplanDir:
            headerFile = os.path.join(subplanDir, "subplanHeader")
            origPath = self.findOrigRulePath(headerFile)
            return os.path.basename(origPath)
                
    def findOrigRulePath(self, headerFile):
        if not os.path.isfile(headerFile):
            return ""
        index = -1
        for line in open(headerFile).xreadlines():
            if line.startswith("552"):
                index = line.split(";").index("SUB_PLAN_HEADER_RULE_SET_NAME")
            if line.startswith("554") and index > 0:
                return line.split(";")[index]
        return ""
    def extraReadFiles(self, test):
        readDirs = CarmenConfig.extraReadFiles(self, test)
        if test.classId() == "test-case":
            subplan = self._getSubPlanDirName(test)
            if subplan and os.path.isdir(subplan):
                for title, fileNames in self.filesFromSubplan(test, subplan):
                    readDirs[title] = fileNames
            try:
                rulesets = [ os.path.join(test.getEnvironment("CARMUSR"), "crc", "source", name) \
                             for name in self.getRuleSetNames(test) ]
                if len(rulesets) > 0:
                    readDirs["Ruleset"] = rulesets
            except plugins.TextTestError:
                pass
        elif isUserSuite(test):
            files = self.getResourceFiles(test)
            if len(files):
                readDirs["Resources"] = files
        elif test.hasEnvironment("CARMSYS") and not test.parent:
            raveModule = self.getRaveModule(test)
            if os.path.isfile(raveModule):
                readDirs["RAVE module"] = [ raveModule ]
        return readDirs
    def getResourceFiles(self, test):
        files = []
        customerFile = os.path.join(test.getEnvironment("CARMUSR"), "Resources", "CarmResources", "Customer.etab")
        if os.path.isfile(customerFile):
            files.append(customerFile)
        impFile = os.path.join(test.getEnvironment("CARMUSR"), "data", "config", "CarmResources", "Implementation.etab")
        if os.path.isfile(impFile):
            files.append(impFile)
        return files
    def getRaveModule(self, test):
        return os.path.join(test.getEnvironment("CARMSYS"), \
                            "carmusr_default", "crc", "modules", getBasicRaveName(test))
    def filesFromSubplan(self, test, subplanDir):
        return []
    def ensureDebugLibrariesExist(self, test):
        pass
    def getConfigEnvironment(self, test):
        baseEnv, props = CarmenConfig.getConfigEnvironment(self, test)
        if not test.parent and not self.slaveRun():
            if self.useQueueSystem():
                baseEnv.append(("_AUTOTEST__LOCAL_COMPILE_", "1"))
            else:
                # Change PATH so we can intercept crc_compile calls
                baseEnv.append(("PATH", "$PATH:$CARMSYS/bin"))
        return baseEnv, props
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
        app.setConfigDefault("build_rulesets_always", "false", "Whether we build rulesets unless told otherwise")
        app.setConfigDefault("rave_static_library", "", "Library to link with when building static rulesets")
        app.setConfigDefault("lines_of_crc_compile", 30, "How many lines to present in textual previews of rave compilation failures")
        # dictionary of lists
        app.setConfigDefault("build_targets", { "" : [] }, "Directories to build in when -build specified")
        
def getCarmCmdAndEnv(cmdLine, test):
    runEnv = test.getRunEnvironment(getCrcCompileVars())
    fullCmd = ". " + test.getEnvironment("CARMSYS") + "/CONFIG > /dev/null 2>&1; " + cmdLine
    return fullCmd, runEnv

def getEnvVarFromCONFIG(var, test):
    cmdLine, runEnv = getCarmCmdAndEnv("echo $" + var, test)
    proc = subprocess.Popen(cmdLine, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=runEnv)
    return proc.communicate()[0].strip()

def getRaveNames(test):
    raveNameDir = test.getConfigValue("rave_name")
    if len(raveNameDir) == 1:
        return raveNameDir["default"]
    else:
        return test.getCompositeConfigValue("rave_name", getEnvVarFromCONFIG("PRODUCT", test))

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
class PrepareCarmdataWriteDir(sandbox.PrepareWriteDirectory):
    def __call__(self, test):
        sandbox.PrepareWriteDirectory.__call__(self, test)
        # Collate the CARMUSR/CARMDATA. Hard to change config as we don't know which variable!
        if test.getEnvironment("CARMDATA"):
            self.collatePath(test, "$CARMDATA", self.partialCopyTestPath)
        else:
            self.collatePath(test, "$CARMUSR", self.partialCopyTestPath)

def getCrcCompileVars():
    return [ "CARMSYS", "CARMUSR", "CARMTMP", "CARMROLE", "CARMGROUP", "BITMODE", "_AUTOTEST__LOCAL_COMPILE_", "PATH", "USER", "_AUTOTEST__DEBUG_" ] 
    
class RuleBuildSubmitServer(QueueSystemServer):
    def __init__(self, *args):
        QueueSystemServer.__init__(self, *args)
        self.ruleBuildQueue = Queue()
        self.testsForRuleBuild = 0
        self.actualAddress = None
    def findQueueForTest(self, test):
        # push the non-rules tests last, to avoid indeterminism and decrease total time as these need two
        # SGE submissions
        rulecomp = self.getRuleCompilation(test)
        if not rulecomp or rulecomp.allSucceeded():
            self.diag.info("Inserting new test into normal queue")
            return QueueSystemServer.findQueueForTest(self, test)

        ruleset = rulecomp.findFailedRuleset()
        if ruleset:
            testForRuleset = self.getTestsForRuleset(ruleset)[0]
            test.changeState(copy(testForRuleset.state))
            self.diag.info("Previously detected failed ruleset found, not using test")
            self.handleLocalError(test, previouslySubmitted=False)
        else:
            self.testsForRuleBuild += 1
            test.changeState(NeedRuleCompilation(rulecomp))
            self.diag.info("Test submitted to queue for rule compilation, tests for rule build now " + str(self.testsForRuleBuild))
            return self.ruleBuildQueue

    def setSlaveServerAddress(self, address):
        self.submitAddress = os.getenv("TEXTTEST_MIM_SERVER", address)
        self.actualAddress = address

    def notifyAllRead(self, suites):
        self.ruleBuildQueue.put(None)
        if self.testsForRuleBuild > 0:
            self.diag.info("All read: " + str(self.testsForRuleBuild) + " test still waiting for rule build.")
            self.testQueue.put("Completed submission of all rule compilations and tests that don't require rule compilation")
        else:
            QueueSystemServer.notifyAllRead(self, suites)
            
    def notifyRulesetCompiled(self, test, hostname):
        if test.state.isComplete(): # failed
            self.handleLocalError(test, previouslySubmitted=False)
        else:
            test.changeState(RuleCompilationComplete(test.state, hostname))
            queue = QueueSystemServer.findQueueForTest(self, test)
            queue.put(test)

        self.ruleBuildCompleted()
        
    def run(self):
        self.sendServerState("TextTest slave server started on " + self.actualAddress)
        self.runQueue(self.ruleBuildQueue.get, self.submitRuleCompilation, "submitting rule compilations for")
        if self.testCount > 0:
            QueueSystemServer.run(self)
        
    def getRuleCompilation(self, test):
        try:
            filterer = test.app.getRuleBuildFilterer()
            return filterer.getRuleCompilation(test)
        except AttributeError:
            return
    def getTestsForRuleset(self, ruleset):
        return FilterRuleBuilds.rulesetNamesToTests.get(ruleset.uniqueName, [])
    def submitRuleCompilation(self, test):
        submissionRules = test.app.getRaveSubmissionRules(test)
        remoteCmd = os.path.join(plugins.installationDir("bin"), "remotecmd.py")
        rulecompEnv = test.getRunEnvironment(getCrcCompileVars())
        rulecomp = test.state.rulecomp
        for ruleset in rulecomp.rulesetsForSelf:
            postText = submissionRules.getSubmitSuffix()
            print "R: Submitting Rule Compilation for ruleset", ruleset.name, "(for " + repr(test) + ")", postText
            try:
                compileArgs = [ remoteCmd, ruleset.uniqueName, self.submitAddress ] + ruleset.getCompilationArgs(remote=True)
                command = " ".join(compileArgs)
                if ruleset.modeString == "-debug":
                    test.app.ensureDebugLibrariesExist(test)
                if not self.submitJob(test, submissionRules, command, rulecompEnv):
                    self.ruleBuildCompleted()
                    self.diag.info("Rule compilation submission failed, tests for rule build now " + str(self.testsForRuleBuild))
            except plugins.TextTestError, e:
                test.changeState(plugins.Unrunnable(str(e), "NO COMPILER"))
                self.handleErrorState(test)
                self.ruleBuildCompleted()
        else:
            self.associateJobs(test, rulecomp)            
        
        if test.state.category == "need_rulecompile":
            test.changeState(PendingRuleCompilation(rulecomp))
    def getFullSubmitError(self, test, errorMessage, cmdArgs):
        qname = queueSystemName(test.app)
        return "Failed to submit rule compilation to " + qname + " (" + errorMessage.strip() + ")\n" + \
               "Submission command was '" + " ".join(cmdArgs[:-1]) + " ... '\n"
        
    def associateJobs(self, test, rulecomp):
        for ruleset in rulecomp.rulesetsFromOthers:
            rulesetTests = FilterRuleBuilds.rulesetNamesToTests.get(ruleset.uniqueName, [])
            self.diag.info("Found ruleset tests " + repr(rulesetTests))
            if len(rulesetTests) > 0 and self.isRuleBuild(rulesetTests[0]):
                self.lock.acquire()
                if self.exited:
                    self.cancel(test)
                else:
                    jobInfo = self.getJobInfo(rulesetTests[0])
                    if len(jobInfo) > 0:
                        for jobId, jobName in jobInfo:
                            self.diag.info("Associated " + repr(test) + " with job info " + repr((jobId, jobName)))
                            self.jobs.setdefault(test, []).append((jobId, jobName))
                    else:
                        test.changeState(copy(rulesetTests[0].state))
                        self.diag.info("No previous job found, " + repr(test) + " changed to state " + test.state.category)
                        self.handleLocalError(test, previouslySubmitted=False)
                self.lock.release()
        
    def ruleBuildCompleted(self):
        self.testsForRuleBuild -= 1
        if self.testsForRuleBuild == 0:
            self.testQueue.put(None)
            
    def ruleBuildKilled(self, test, freetext):
        if hasattr(test.state, "rulecomp"):
            for ruleset in test.state.rulecomp.rulesetsForSelf:
                ruleset.failed(freetext)
                
        self.ruleBuildCompleted()
        
    def isRuleBuild(self, test):
        return test.state.category.endswith("_rulecompile") or \
               (test.state.isComplete() and test.state.freeText.find("Failed to submit rule compilation") != -1)
    def jobStarted(self, test):
        return self.isRuleBuild(test) or test.state.hasStarted()
    def shouldWaitFor(self, test):
        if self.isRuleBuild(test):
            timeStr =  plugins.localtime("%H:%M")
            briefText = "Ruleset build killed at " + timeStr
            freeText = "Ruleset compilation killed explicitly at " + timeStr
            self.ruleBuildKilled(test, freeText)
            self.cancel(test, briefText, freeText, previouslySubmitted=False)
            return False
        else:
            return QueueSystemServer.shouldWaitFor(self, test)
    def setKilledPending(self, test):
        if self.isRuleBuild(test):
            timeStr =  plugins.localtime("%H:%M")
            briefText = "killed pending rule compilation at " + timeStr
            freeText = "Rule compilation job was killed (while still pending in " + queueSystemName(test.app) +\
                     ") at " + timeStr
            self.ruleBuildKilled(test, freeText)
            self.cancel(test, freeText, briefText, previouslySubmitted=False)
        else:
            QueueSystemServer.setKilledPending(self, test)
        
    def setSlaveFailed(self, test, startNotified, wantStatus):
        if test.state.category == "complete_rulecompile":
            timeStr =  plugins.localtime("%H:%M")
            briefText = "cancelled at " + timeStr
            freeText = "Test was cancelled after rule compilation was successful, at " + timeStr
            self.cancel(test, freeText, briefText, previouslySubmitted=False)
        elif startNotified and self.isRuleBuild(test):
            failReason = "no report from rule compilation (possibly killed with SIGKILL)"
            briefText, fullText = self.getSlaveFailure(test, startNotified, wantStatus)
            fullText = failReason + "\n" + fullText
            self.ruleBuildKilled(test, fullText)
            self.changeState(test, plugins.Unrunnable(fullText, failReason), previouslySubmitted=False)
        else:
            QueueSystemServer.setSlaveFailed(self, test, startNotified, wantStatus)
    def describeJob(self, test, jobId, jobName):
        if self.isRuleBuild(test):
            postText = self.getPostText(test, jobId)
            print "T: Cancelling job", jobName, postText
        else:
            QueueSystemServer.describeJob(self, test, jobId, jobName)

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
            diag.info("Found test " + repr(test))
            if test.state.isComplete():
                continue
            if status == "start":
                test.changeState(RunningRuleCompilation(test.state, hostname))
            else:
                if status == "exitcode=0":
                    ruleset.succeeded(raveOutput)
                else:
                    ruleset.failed(raveOutput)
                if evaluator.buildsSucceeded(test) or test.state.isComplete():
                    test.notify("RulesetCompiled", hostname)

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
        self.diag.info("Evaluating rule build for " + repr(test))
        if not hasattr(test.state, "rulecomp"):
            return False
        rulecomp = test.state.rulecomp
        fileToWrite = test.makeTmpFileName("crc_compile_output", forFramework=1)
        plugins.ensureDirExistsForFile(fileToWrite)
        writeFile = open(fileToWrite, "w")
        writeFile.write(rulecomp.getRuleBuildOutput())
        writeFile.close()
        ruleset = rulecomp.findFailedRuleset()
        if ruleset:
            freeText = "Failed to build ruleset " + ruleset.name + "\n" + self.getPreview(test, ruleset.output)            
            test.changeState(plugins.Unrunnable(freeText, "Ruleset build failed"))
            return False
        elif rulecomp.allSucceeded():
            print "S: All rulesets compiled for", test, "(ruleset" + rulecomp.description() + ")"
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
        self.ensureCarmTmpExists(test)
        try:
            rulesetNames = test.app.getRuleSetNames(test)
        except plugins.TextTestError, e:
            # assume problems here are due to compilation itself not being setup, ignore
            print e
            return [], []

        self.diag.info("Making rulesets for " + repr(rulesetNames))
        for rulesetName in rulesetNames:
            ruleset = RuleSet(rulesetName, test)
            
            # If no ruleset is associated with the test anyway, or the source file isn't there, don't try to build it...
            if not ruleset.isValid():
                self.diag.info("Ruleset " + rulesetName + " not valid")
                continue

            if self.shouldCompileFor(test, ruleset):
                origRuleset = self.rulesetNamesToRulesets.get(ruleset.uniqueName)
                self.diag.info("Rule build of " + ruleset.uniqueName + " produced " + repr(origRuleset))
                if origRuleset:
                    known.append(origRuleset)
                else:
                    FilterRuleBuilds.rulesetNamesToTests[ruleset.uniqueName] = []
                    unknown.append(ruleset)
                    self.rulesetNamesToRulesets[ruleset.uniqueName] = ruleset
                self.rulesetNamesToTests[ruleset.uniqueName].append(test)
            else:
                self.diag.info("Filter rejected rule build for " + test.name)
                
        return unknown, known
    def ensureCarmTmpExists(self, test):
        carmTmp = test.getEnvironment("CARMTMP")
        if carmTmp and not os.path.isdir(carmTmp):
            carmTmp = os.path.normpath(carmTmp)
            if os.path.islink(carmTmp):
                print "CARMTMP", carmTmp, "seems to be a deadlink"
            else:
                print "CARMTMP", carmTmp, "did not exist, attempting to create it"
                plugins.ensureDirectoryExists(carmTmp)
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
        
        for ruleset in rulecomp.rulesetsForSelf:
            self.describe(test, " - ruleset " + ruleset.name)

            commandArgs = ruleset.getCompilationArgs(remote=False)
            if ruleset.modeString == "-debug":
                test.app.ensureDebugLibrariesExist(test)
            success, currRaveInfo = self.performCompile(test, commandArgs)
            if success:
                ruleset.succeeded(currRaveInfo)
            else:
                ruleset.failed(currRaveInfo)
    def performCompile(self, test, commandArgs):
        self.diag.info("Compiling with command '" + repr(commandArgs) + "' from directory " + os.getcwd())
        runEnv = test.getRunEnvironment(getCrcCompileVars())
        self.diag.info("PATH is " + runEnv.get("PATH"))
        test.changeState(RunningRuleCompilation(test.state))
        proc = subprocess.Popen(commandArgs, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=runEnv)
        raveInfo = proc.communicate()[0] # wait to finish
        if proc.returncode:
            return False, raveInfo
        else:
            return True, raveInfo

    def setUpSuite(self, suite):
        if suite.parent is None or isUserSuite(suite):
            self.describe(suite)

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
        plugins.TestState.__init__(self, "pending_rulecompile", briefText=briefText, \
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

class RuleCompilationComplete(plugins.TestState):
    def __init__(self, prevState, hostname = None):
        self.rulecomp = prevState.rulecomp
        if not hostname:
            hostname = gethostname()
        briefText = "READY"
        freeText = "Ready for submission of test. Completed compilation of ruleset" + self.rulecomp.description() + " on " + hostname
        lifecycleChange = "complete ruleset compilation"
        plugins.TestState.__init__(self, "complete_rulecompile", briefText=briefText, \
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
        self.status = self.NOT_COMPILED
        self.output = ""
        self.uniqueName = self.name + "." + test.getEnvironment("CARMTMP")
        self.targetFiles = [ self.targetPath("rule_set", raveName, self.arch, self.name) for raveName in self.raveNames ]
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
            executable = os.path.join(self.envMethod("CARMSYS"), "bin", "crc_compile")
            if not os.path.isfile(executable):
                # The text is used elsewhere to decide if this was a rule compilation
                # change only with care!!!
                raise plugins.TextTestError, "Failed to submit rule compilation, no rule compiler found at " + executable
            return executable
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
        targetPath = os.path.join(self.envMethod("CARMTMP"), "crc", type, raveName.upper(), arch, name)
        if self.modeString == "-debug":
            targetPath += "_g"
        return targetPath
    def sourcePath(self, name):
        return os.path.join(self.envMethod("CARMUSR"), "crc", "source", name)
    def backup(self):
        if self.isCompiled():
            try:
                for targetFile in self.targetFiles:
                    shutil.copyfile(targetFile, targetFile + ".bak")
            except IOError:
                plugins.printWarning("Did not have permissions to backup ruleset, continuing anyway.")            

class BuildCode:
    builtDirs = {}
    buildFailedDirs = {}
    def __init__(self, target):
        self.target = "" # no option corresponds to empty string
        if target:
            self.target = target
    def build(self, suite):
        targetDir = suite.getConfigValue("build_targets")
        if not targetDir.has_key(self.target):
            return
        arch = getArchitecture(suite.app)
        if not self.builtDirs.has_key(arch):
            self.builtDirs[arch] = []
            self.buildFailedDirs[arch] = []
        for optValue in targetDir[self.target]:
            absPath, makeTargets = self.getPathAndTargets(optValue)
            if absPath in self.builtDirs[arch]:
                print "Already built on", arch, "under", absPath, "- skipping build"
                continue
            if absPath in self.buildFailedDirs[arch]:
                raise plugins.TextTestError, "BUILD ERROR: " + repr(suite.app) + " depends on already failed build " + os.linesep \
                      + "(Build in " + absPath + " on " + arch + ")"
            
            if os.path.isdir(absPath):
                self.buildLocal(absPath, suite, makeTargets)
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
        if arch == "x86_64_solaris":
            return "sunriver"
    def getRemoteCommandLine(self, arch, absPath, makeCommand):
        commandLine = makeCommand + " -C " + absPath
        if arch == "sparc_64" or arch == "x86_64_linux":
            commandLine = "setenv BITMODE 64; " + commandLine
        return commandLine
    def buildLocal(self, absPath, suite, makeTargets):
        app = suite.app
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
        carmsys = suite.getEnvironment("CARMSYS")
        if carmsys:
            makeCommand = "gmake install " + extra + "CARMSYS=" + carmsys
            commandLine = self.getRemoteCommandLine(arch, absPath, makeCommand)
            os.system("rsh " + machine + " '" + commandLine + "' < /dev/null > /dev/null 2>&1")
            print "Making install from", absPath ,"to", carmsys
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
            raise plugins.TextTestError, "No command given"
    def __repr__(self):
        return "Traversing CARMUSR "
    def __call__(self, test):
        user = test.getEnvironment("CARMUSR")
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

class PrintRulesets(plugins.Action):
    def __repr__(self):
        return "Printing rulesets for"
    def __call__(self, test):
        rulesets = test.app.getRuleSetNames(test)
        self.describe(test, " - " + ",".join(rulesets))
    def setUpSuite(self, suite):
        self.describe(suite)
