helpDescription = """
The apc configuration is based on the Rave-based configuration. It will compile all rulesets in the test
suite before running any tests, if the library file "libapc.a" has changed since the ruleset was last built.

It uses a special ruleset building strategy on the linux platforms, such that rebuilding the APC binary
after a small change to APC will be really quick. It does so by not invoking 'crc_compile', instead
it makes its own link command. By using the "-rulecomp" flag you can avoid building the ruleset with
this special strategy.

It will fetch the optimizer's status file from the subplan (the "status" file) and write it for
comparison as the file status.<app> after each test has run."""

helpOptions = """-rundebug <options>
           - (only APC) Runs the test in the debugger (gdb) and displays the log file. The run
             is made locally, and if its successful, the debugger is exited, and texttest
             continues as usual. If the run fails, the buffer is flushed and one are left 
             in the debugger. To enter the debugger during the run, type C-c.
             The following options are avaliable:
             - xemacs
               The debugger is run in xemacs, in gdbsrc mode.
             - norun
               The debugger is started, but the test is not run, useful if breakpoints
               etc are to be set before the run is started.
             - nolog
               The log file is not displayed.

-extractlogs <option>
           - (only APC) Executes the command specified by the config value extract_logs_<option>,
             and the result is piped into a file named <option>.<app>.<ver> If no option is given or the config value
             specified does not exist, then the command specifed by extract_logs_default is used, and the result is
             saved in the file extract.<app>.<ver>
"""

helpScripts = """apc.CleanTmpFiles          - Removes all temporary files littering the test directories

apc.ImportTest             - Import new test cases and test users.
                             The general principle is to add entries to the "testsuite.apc" file and then
                             run this action, typcally 'texttest -a apc -s apc.ImportTest'. The action
                             will then find the new entries (as they have no corresponding subdirs) and
                             ask you for either new CARMUSR (for new user) or new subplan directory
                             (for new tests). Note that CARMTMP is assigned for you. Also for new tests
                             it is neccessary to have an 'APC_FILES' subdirectory created by Studio which
                             is to be used as the 'template' for temporary subplandirs as created when
                             the test is run. The action will look for available subplandirectories under
                             CARMUSR and present them to you.

apc.PrintAirport           - Prints the target AirportFile location for each user

apc.UpdateCvsIgnore        - Make the .cvsignore file in each test directory identical to 'cvsignore.master'

apc.UpdatePerformance      - Update the performance file for tests with time from the status file if the
                             status file is from a run on a performance test machine.
                             The following options are supported:
                             - v=v1,v2
                               Update for  multiple versions, ie 'v=,9' means master and version 9

"""

import default, ravebased, carmen, lsf, performance, os, sys, stat, string, shutil, KPI, optimization, plugins, math, filecmp, re, popen2, unixConfig, guiplugins, exceptions
from time import sleep

def getConfig(optionMap):
    return ApcConfig(optionMap)

class ApcConfig(optimization.OptimizationConfig):
    def addToOptionGroup(self, group):
        optimization.OptimizationConfig.addToOptionGroup(self, group)
        if group.name.startswith("How"):
            group.addOption("rundebug", "Run debugger")
            group.addOption("extractlogs", "Extract Apc Logs")
    def getActionSequence(self):
        if self.optionMap.has_key("kpi"):
            listKPIs = [KPI.cSimplePairingOptTimeKPI,
                        KPI.cWorstBestPairingOptTimeKPI,
                        KPI.cPairingQualityKPI,
                        KPI.cAverageMemoryKPI,
                        KPI.cMaxMemoryKPI]
            return [ optimization.CalculateKPIs(self.optionValue("kpi"), listKPIs) ]
        if self.optionMap.has_key("kpiData"):
            listKPIs = [KPI.cSimplePairingOptTimeKPI]
            return [ optimization.WriteKPIData(self.optionValue("kpiData"), listKPIs) ]
        return optimization.OptimizationConfig.getActionSequence(self)
    def getProgressReportBuilder(self):
        return MakeProgressReport(self.optionValue("prrep"))
    def getRuleBuildObject(self, testRunner, jobNameCreator):
        return ApcCompileRules(self.getRuleSetName, jobNameCreator, self.getRuleBuildFilter(), testRunner, \
                               self.raveMode(), self.optionValue("rulecomp"))
    def getSpecificTestRunner(self):
        return [ CheckFilesForApc(), self._getApcTestRunner() ]
    def _getApcTestRunner(self):
        if self.optionMap.has_key("rundebug"):
            return RunApcTestInDebugger(self.optionValue("rundebug"), self.optionMap.has_key("keeptmp"))
        else:
            baseRunner = optimization.OptimizationConfig.getSpecificTestRunner(self)
            if self.optionMap.slaveRun():
                return MarkApcLogDir(baseRunner, self.isExecutable, self.optionMap.has_key("extractlogs"))
            else:
                return baseRunner
    def isExecutable(self, process, test):
        # Process name starts with a dot and may be truncated or have
        # extra junk at the end added by APCbatch.sh
        processData = process[1:]
        rulesetName = self.getRuleSetName(test)
        return processData.startswith(rulesetName) or rulesetName.startswith(processData)
    def getFileCollator(self):
        subActions = []
        subActions.append(FetchApcCore())
        subActions.append(RemoveLogs())
        if self.optionMap.slaveRun():
            subActions.append(ExtractApcLogs(self.optionValue("extractlogs")))
        return subActions
    def _getSubPlanDirName(self, test):
        statusFile = os.path.normpath(os.path.expandvars(test.options.split()[1]))
        dirs = statusFile.split(os.sep)[:-2]
        return os.path.normpath(string.join(dirs, os.sep))
    def getRuleSetName(self, test):
        fileName = test.makeFileName("options")
        if os.path.isfile(fileName):
            optionLine = open(fileName).readline()
            options = optionLine.split()
            for option in options:
                if option.find("crc" + os.sep + "rule_set") != -1:
                    return option.split(os.sep)[-1]
        return None
    def updaterLSFStatus(self):
        return ApcUpdateLSFStatus()
    def printHelpDescription(self):
        print helpDescription
        optimization.OptimizationConfig.printHelpDescription(self)
    def printHelpOptions(self, builtInOptions):
        optimization.OptimizationConfig.printHelpOptions(self, builtInOptions)
        print helpOptions
    def printHelpScripts(self):
        optimization.OptimizationConfig.printHelpScripts(self)
        print helpScripts
    def setApplicationDefaults(self, app):
        optimization.OptimizationConfig.setApplicationDefaults(self, app)
        self.itemNamesInFile[optimization.memoryEntryName] = "Time:.*memory"
        self.itemNamesInFile[optimization.costEntryName] = "TOTAL cost"
        if app.name == "cas_apc":
            self.itemNamesInFile[optimization.costEntryName] = "rule cost"
        self.itemNamesInFile[optimization.newSolutionMarker] = "apc_status Solution"
        app.setConfigDefault("link_libs", "")
        app.setConfigDefault("extract_logs", {})

def verifyAirportFile(arch):
    diag = plugins.getDiagnostics("APC airport")
    etabPath = os.path.join(os.environ["CARMUSR"], "Resources", "CarmResources")
    customerEtab = os.path.join(etabPath, "Customer.etab")
    if os.path.isfile(customerEtab):
        diag.info("Reading etable at " + customerEtab)
        etab = ravebased.ConfigEtable(customerEtab)
        airportFile = etab.getValue("default", "AirpMaint", "AirportFile")
        if airportFile != None and os.path.isfile(airportFile):
            return
        diag.info("Airport file is at " + airportFile)
        srcDir = etab.getValue("default", "AirpMaint", "AirportSrcDir")
        if srcDir == None:
            srcDir = etab.getValue("default", "AirpMaint", "AirportSourceDir")
        if srcDir == None:
            srcDir = os.path.join(os.environ["CARMUSR"], "data", "Airport", "source")
        srcFile = os.path.join(srcDir, "AirportFile")
        if os.path.isfile(srcFile) and airportFile != None:
            apCompile = os.path.join(os.environ["CARMSYS"], "bin", arch, "apcomp")
            if os.path.isfile(apCompile):
                print "Missing AirportFile detected, building:", airportFile
                ravebased.ensureDirectoryExists(os.path.dirname(airportFile))
                # We need to source the CONFIG file in order to get some
                # important environment variables set, i.e. PRODUCT and BRANCH.
                configFile = os.path.join(os.environ["CARMSYS"], "CONFIG")
                os.system(". " + configFile + "; " + apCompile + " " + srcFile + " > " + airportFile)
            if os.path.isfile(airportFile):
                return
    raise plugins.TextTestError, "Failed to find AirportFile"

def verifyLogFileDir(arch):
    carmTmp = os.environ["CARMTMP"]
    if os.path.isdir(carmTmp):
        logFileDir = carmTmp + "/logfiles"
        if not os.path.isdir(logFileDir):
            os.makedirs(logFileDir)

class CheckFilesForApc(plugins.Action):
    def __call__(self, test):
        verifyAirportFile(carmen.getArchitecture(test.app))
        verifyLogFileDir(carmen.getArchitecture(test.app))        

class ViewApcLog(guiplugins.InteractiveAction):
    def __repr__(self):
        return "Viewing log of"
    def __call__(self, test):
        machine = getTestMachine(test)
        apcTmpDir = test.writeDirs[-1]
        self.showLogFile(test, machine, os.path.join(apcTmpDir, "apclog"))
    def showLogFile(self, test, machine, logFileName):
        command = "xon " + machine + " 'xterm -bg white -T " + test.name + " -e 'less +F " + logFileName + "''"
        self.startExternalProgram(command)
    def showRunStatusFile(self, test):
        # Under construction! 
        #  $CARMSYS/bin/APCstatus.sh ${SUBPLAN}/run_status
        return
    def getTitle(self):
        return "View APC Log"

guiplugins.interactiveActionHandler.testClasses.append(ViewApcLog)

#
# Runs the test in gdb and displays the log file. 
#
class RunApcTestInDebugger(default.RunTest):
    def __init__(self, options, keepTmpFiles):
        self.inXEmacs = None
        self.runPlain = None
        self.showLogFile = 1
        self.noRun = None
        self.keepTmps = keepTmpFiles;
        opts = options.split(" ")
        if opts[0] == "":
            return
        for opt in opts:
            if opt == "xemacs":
                self.inXEmacs = 1
            elif opt == "nolog":
                self.showLogFile = None
            elif opt == "plain":
                self.runPlain = 1
            elif opt == "norun":
                self.noRun = 1
            else:
                print "Ignoring unknown option " + opt
    def __repr__(self):
        return "Debugging"
    def __call__(self, test):
        if test.state.isComplete():
            return
        self.describe(test)
        # Get the options that are sent to APCbatch.sh
        opts = test.options.split(" ")
        # Create and show the log file.
        apcLog = test.makeFileName("apclog", temporary=1)
        apcLogFile = open(apcLog, "w")
        apcLogFile.write("")
        apcLogFile.close()
        if self.showLogFile:
            command = "xon " + os.environ["HOST"] + " 'xterm -bg white -fg black -T " + "APCLOG-" + test.name + "" + " -e 'less +F " + apcLog + "''"
            process = plugins.BackgroundProcess(command)
        # Create a script for gdb to run.
        gdbArgs = test.makeFileName("gdb_args", temporary=1)
        gdbArgsFile = open(gdbArgs, "w")
        gdbArgsFile.write("set pagination off" + os.linesep)
        gdbArgsFile.write("set args -D -v1 -S " + opts[0] + " -I " + opts[1] + " -U " + opts[-1] + " >& " + apcLog + os.linesep)
        if not self.noRun:
            gdbArgsFile.write("run" + os.linesep)
            gdbArgsFile.write("if $_exitcode" + os.linesep)
            gdbArgsFile.write("print fflush(0)" + os.linesep)
            gdbArgsFile.write("where" + os.linesep)
            gdbArgsFile.write("else" + os.linesep)
            gdbArgsFile.write("quit" + os.linesep)
            gdbArgsFile.write("end" + os.linesep)
        gdbArgsFile.close()
        # Create an output file. This file is read by LogFileFinder if we use PlotTest.
        out = test.makeFileName("output", temporary=1)
        outFile = open(out, "w")
        outFile.write("SUBPLAN " + opts[0] + os.linesep)
        outFile.close()
        # Create execute command.
        binName = opts[-2].replace("PUTS_ARCH_HERE", carmen.getArchitecture(test.app))
        if self.inXEmacs:
            gdbStart, gdbWithArgs = self.runInXEmacs(test, binName, gdbArgs)
            executeCommand = "xemacs -l " + gdbStart + " -f gdbwargs"
        elif self.runPlain:
            executeCommand = binName + " -D -v1 -S " + opts[0] + " -I " + opts[1] + " -U " + opts[-1] + " > " + apcLog
        else:
            executeCommand = "gdb " + binName + " -silent -x " + gdbArgs
        # Source the CONFIG file to get the environment correct and run gdb with the script.
        configFile = os.path.join(os.environ["CARMSYS"], "CONFIG")
        os.system(". " + configFile + "; " + executeCommand)
        # Remove the temp files, texttest will compare them if we dont remove them.
        os.remove(gdbArgs)
        if not self.keepTmps:
            os.remove(apcLog)
        if self.inXEmacs:
            os.remove(gdbStart)
            os.remove(gdbWithArgs)
    def runInXEmacs(self, test, binName, gdbArgs):
        gdbStart = test.makeFileName("gdb_start", temporary=1)
        gdbWithArgs = test.makeFileName("gdb_w_args", temporary=1)
        gdbStartFile = open(gdbStart, "w")
        gdbStartFile.write("(defun gdbwargs () \"\"" + os.linesep)
        gdbStartFile.write("(setq gdb-command-name \"" + gdbWithArgs + "\")" + os.linesep)
        gdbStartFile.write("(gdbsrc \"" + binName + "\"))" + os.linesep)
        gdbStartFile.close()
        gdbWithArgsFile = open(gdbWithArgs, "w")
        gdbWithArgsFile.write("#!/bin/sh" + os.linesep)
        gdbWithArgsFile.write("gdb -x " + gdbArgs + " $*" + os.linesep)
        gdbWithArgsFile.close()
        os.chmod(gdbWithArgs, stat.S_IXUSR | stat.S_IRWXU)
        return gdbStart, gdbWithArgs
    def setUpSuite(self, suite):
        self.describe(suite)
    
class ApcCompileRules(ravebased.CompileRules):
    def __init__(self, getRuleSetName, jobNameCreator, sFilter = None, testRunner = None, \
                 modeString = "-optimize", ruleCompFlags = None):
        ravebased.CompileRules.__init__(self, getRuleSetName, jobNameCreator, modeString, sFilter, testRunner)
        self.ruleCompFlags = ruleCompFlags
        self.diag = plugins.getDiagnostics("ApcCompileRules")
    def compileRulesForTest(self, test):
        self.apcLib = test.getConfigValue("rave_static_library")
        # If there is a filter we assume we aren't compelled to build rulesets properly...        
        if self.filter and carmen.getArchitecture(test.app) == "i386_linux" and self.ruleCompFlags == "apc":
            self.linuxRuleSetBuild(test)
        else:
            return ravebased.CompileRules.compileRulesForTest(self, test)
    def linuxRuleSetBuild(self, test):
        ruleset = ravebased.RuleSet(self.getRuleSetName(test), self.raveName, "i386_linux")
        if not self.ensureCarmTmpDirExists():
            #self.rulesCompileFailed.append(ruleset.name)
            raise plugins.TextTestError, "Non-existing CARMTMP"
        self.diag.info("Using linuxRuleSetBuild for building rule set " + ruleset.name)
        #if ruleset.isValid() and ruleset.name in self.rulesCompileFailed:
        #    raise plugins.TextTestError, "Trying to use ruleset '" + ruleset.name + "' that failed to build."
        if not ruleset.isValid() or ruleset.name in self.rulesCompiled:
            return
        apcExecutable = ruleset.targetFile
        ravebased.ensureDirectoryExists(os.path.dirname(apcExecutable))
        ruleLib = self.getRuleLib(ruleset.name)
        if self.isNewer(apcExecutable, self.apcLib):
            self.diag.info("APC binary is newer than libapc.a, returning.")
            return
        self.describe(test, " -  ruleset " + ruleset.name)
        ruleset.backup()
        self.rulesCompiled.append(ruleset.name)
        if not os.path.isfile(ruleLib):
            compiler = os.path.join(os.environ["CARMSYS"], "bin", "crc_compile")
            # Hack for crc_compile.
            os.chdir(test.abspath)
            self.diag.debug("Building rule set library using the command " + self.ruleCompileCommand(ruleset.sourceFile, test))
            returnValue = os.system(self.ruleCompileCommand(ruleset.sourceFile, test))
            if returnValue:
                #self.rulesCompileFailed.append(ruleset.name)
                raise plugins.TextTestError, "Failed to build rule library for APC ruleset " + ruleset.name
        commandLine = "g++ -pthread " + self.linkLibs(self.apcLib, ruleLib, test)
        commandLine += "-o " + apcExecutable
        self.diag.debug("Linking APC binary using the command " + commandLine)
        # We create a temporary file that the output goes to.
        if len(test.writeDirs) < 1:
            test.makeBasicWriteDirectory()
        compTmp = test.makeFileName("ravecompile", temporary=1)
        returnValue = os.system(commandLine + " > " + compTmp + " 2>&1")
        if returnValue:
            #self.rulesCompileFailed.append(ruleset.name)
            print "Building", ruleset.name, "failed:"
            se = open(compTmp)
            lastErrors = se.readlines()
            for line in lastErrors:
                print "   ", line.strip()
            raise plugins.TextTestError, "Failed to link APC ruleset " + ruleset.name
        os.remove(compTmp)

    def getRuleLib(self, ruleSetName):
        optArch = "i386_linux_opt"
        ruleLib = ruleSetName + ".a"
        return os.path.join(os.environ["CARMTMP"], "compile", self.raveName.upper(), optArch, ruleLib)
        
    def ruleCompileCommand(self, sourceFile, test):
        compiler = os.path.join(os.environ["CARMSYS"], "bin", "crc_compile")
        params = " -optimize -makelib -archs i386_linux"
        if "8" in test.app.versions:
            os.environ["CRC_PATH"] = os.environ["CARMUSR"] + ":" + os.environ["CARMSYS"] + "/carmusr_default"
        return compiler + " -" + self.raveName + params + " " + sourceFile

    def linkLibs(self, apcLib, ruleLib, test):
        linkLib = test.app.getConfigValue("link_libs")
        return apcLib + " " + os.path.expandvars(linkLib) + " " + ruleLib + " "

    def isNewer(self, file1, file2):
        if not os.path.isfile(file1):
            return 0
        if not os.path.isfile(file2):
            return 1
        if self.modifiedTime(file1) > self.modifiedTime(file2):
            return 1
        else:
            return 0
    def modifiedTime(self, filename):
        return os.stat(filename)[stat.ST_MTIME]

class ApcUpdateLSFStatus(lsf.UpdateTestLSFStatus):
    def getExtraRunData(self, test):
         subplanDir = test.writeDirs[-1];
         runStatusHeadFile = os.path.join(subplanDir, "run_status_head")
         if os.path.isfile(runStatusHeadFile):
             try:
                 runStatusHead = open(runStatusHeadFile).read()
                 return runStatusHead
             except (OSError,IOError):
                 return "Error opening/reading " + runStatusHeadFile                 
         else:
             return "Run status file is not avaliable yet."
                          
class RemoveLogs(plugins.Action):
    def __call__(self, test):
        self.removeFile(test, "errors")
        self.removeFile(test, "output")
    def removeFile(self, test, stem):
        filePath = test.makeFileName(stem, temporary=1)
        if os.path.isfile(filePath):
            os.remove(filePath)
    def __repr__(self):
        return "Remove logs"

def getTestMachine(test):
    diag = plugins.getDiagnostics("getTestMachineAndApcLogDir")
    # Find which machine the job was run on.
    if test.app.configObject.target.useLSF():
        job = lsf.LSFServer.instance.findJob(test)
        machine = job.machines[0]
        diag.info("Test was run using LSF on " + machine)
    else:
        machine = unixConfig.hostname()
        diag.info("Test was run locally on " + machine)
    return machine

class FetchApcCore(unixConfig.CollateUNIXFiles):
    def isApcLogFileKept(self, errorFileName):
        for line in open(errorFileName).xreadlines():
            if line.find("*** Keeping the logfiles in") != -1:
                return "Yes"
    def extractCoreFor(self, test):
        subplanDir = test.writeDirs[1]
        scriptErrorsFileName = os.path.join(subplanDir, "run_status_script_error")
        self.diag.info(scriptErrorsFileName)
        if not os.path.isfile(scriptErrorsFileName):
            return 0
        self.diag.info("Error file found.")
        # An error file can be created even if there are no kept log files
        if not self.isApcLogFileKept(scriptErrorsFileName):
            self.diag.info("APC log files are NOT kept, exiting.")
            return 0
        self.diag.info("APC log files are kept.")
        #Find out APC tmp directory.
        apcTmpDir = test.writeDirs[-1]
        # Check if there is a apc_debug file.
        if os.path.isfile(os.path.join(apcTmpDir, "apc_debug")):
            self.diag.info("apc_debug file is found. Aborting.")
            return 0
        return 1
    def getBinaryFromCore(self, path, test):
        return os.path.expandvars(test.options.split(" ")[-2].replace("PUTS_ARCH_HERE", carmen.getArchitecture(test.app)))

class MarkApcLogDir(carmen.RunWithParallelAction):
    def __init__(self, baseRunner, isExecutable, keepLogs):
        carmen.RunWithParallelAction.__init__(self, baseRunner, isExecutable)
        self.keepLogs = keepLogs
    def getApcHostTmp(self):
        configFile = os.path.join(os.environ["CARMSYS"],"CONFIG")
        resLine = os.popen("source " + configFile + "; echo ${APC_TEMP_DIR}").readlines()[-1].strip()
        if resLine.find("/") != -1:
            return resLine
        return "/tmp"
    def getApcLogDir(self, test, processId):
        # Logfile dir
        subplanName, apcFiles = os.path.split(test.writeDirs[1])
        baseSubPlan = os.path.basename(subplanName)
        return os.path.join(self.getApcHostTmp(), baseSubPlan + "_" + processId)
    def performParallelAction(self, test, processInfo):
        processId, processName = processInfo[0]
        runProcessId, runProcessName = processInfo[-1]
        apcTmpDir = self.getApcLogDir(test, processId)
        self.diag.info("APC log directory is " + apcTmpDir + " based on process " + processName)
        if not os.path.isdir(apcTmpDir):
            raise plugins.TextTestError, "ERROR : " + apcTmpDir + " does not exist - running process " + runProcessName
        test.writeDirs.append(apcTmpDir)
        self.describe(test)
        if self.keepLogs:
            fileName = os.path.join(apcTmpDir, "apc_debug")
            file = open(fileName, "w")
            file.close()

class ExtractApcLogs(plugins.Action):
    def __init__(self, args):
        self.args = args
        if not self.args:
            print "No argument given, using default value for extract_logs"
            self.args = "default"
    def __call__(self, test):
        apcTmpDir = test.writeDirs[-1]
        if not os.path.isdir(apcTmpDir):
            return

        dict = test.app.getConfigValue("extract_logs")
        if not dict.has_key(self.args):
            print "Config value " + self.args + " does not exist, using default value extract_logs"
            self.args = "default"
        extractCommand = dict[self.args]
        if self.args == "default":
            saveName = "extract"
        else:
            saveName = self.args

        self.describe(test)
        # Extract from the apclog
        cmdLine = "cd " + apcTmpDir + "; " + extractCommand + " > " + test.makeFileName(saveName, temporary = 1)
        os.system(cmdLine)
        # Remove dir
        plugins.rmtree(apcTmpDir)
        # Remove the error file (which is create because we are keeping the logfiles,
        # with the message "*** Keeping the logfiles in $APC_TEMP_DIR ***")
        errFile = test.makeFileName("script_errors", temporary=1)
        if os.path.isfile(errFile):
            os.remove(errFile)
    def __repr__(self):
        return "Extracting APC logfile for"
        
#
# TODO: Check Sami's stuff in /users/sami/work/Matador/Doc/Progress
#
class MakeProgressReport(optimization.MakeProgressReport):
    def __init__(self, referenceVersion):
        optimization.MakeProgressReport.__init__(self, referenceVersion)
        self.refMargins = {}
        self.currentMargins = {}
        self.groupQualityLimit = {}
        self.groupPenaltyQualityFactor = {}
        self.groupTimeLimit = {}
        self.kpiGroupForTest = {}
        self.testInGroupList = []
        self.finalCostsInGroup = {}
        self.weightKPI = []
        self.sumKPITime = 0.0
        self.minKPITime = 0.0
        self.sumCurTime = 0
        self.sumRefTime = 0
        self.qualKPI = 1.0
        self.qualKPICount = 0
        self.lastKPITime = 0
    def __del__(self):
        for groupName in self.finalCostsInGroup.keys():
            fcTupleList = self.finalCostsInGroup[groupName]
            refMargin, currentMargin = self._calculateMargin(fcTupleList)
            self.refMargins[groupName] = refMargin
            self.currentMargins[groupName] = currentMargin
        for testTuple in self.testInGroupList:
            test, referenceRun, currentRun, userName = testTuple
            self.doCompare(test, referenceRun, currentRun, userName)

        print os.linesep
        if self.sumRefTime > 0:
            speedKPI = 1.0 * self.sumCurTime / self.sumRefTime
            wText = "PS1 (sum of time to cost, ratio) with respect to version"
            print wText, self.referenceVersion, "=", self.percent(speedKPI)
        if self.qualKPICount > 0:
            avg = math.pow(self.qualKPI, 1.0 / float(self.qualKPICount))
            qNumber = round(avg,5) * 100.0
            wText = "PQ1 (average cost at time ratio) with respect to version"
            print wText, self.referenceVersion, "=", str(qNumber) + "%"
        optimization.MakeProgressReport.__del__(self)
        if len(self.weightKPI) > 1:
            # The weighted KPI is prodsum(KPIx * Tx / Tmin) ^ (1 / sum(Tx/Tmin))
            # Tx is the kpi time limit for a specific test case's kpi group.
            # If no such time limit is set then the average total time of the testcase is used, ie
            # Tx = (curTotalTime + refTotalTime) / 2
            #
            sumKPI = 1.0
            sumTimeParts = 0.0
            for tup in self.weightKPI:
                kpiS, kpiTime = tup
                kpi = float(kpiS.split("%")[0]) / 100
                sumKPI *= math.pow(kpi, 1.0 * kpiTime / self.minKPITime)
                sumTimeParts += 1.0 * kpiTime / self.minKPITime
            avg = math.pow(sumKPI, 1.0 / float(sumTimeParts))
            wText = "Overall time weighted KPI with respect to version"
            print wText, self.referenceVersion, "=", self.percent(avg)

    def _calculateMargin(self, fcTupleList):
        if len(fcTupleList) < 2:
            return 0.1, 0.1
        refMax = 0
        curMax = 0
        for refCost, curCost in fcTupleList:
            refMax = max(refMax, refCost)
            curMax = max(curMax, curCost)
        refMaxDiff = 0
        curMaxDiff = 0
        for refCost, curCost in fcTupleList:
            refMaxDiff = max(refMaxDiff, abs(refMax - refCost))
            curMaxDiff = max(curMaxDiff, abs(curMax - curCost))
        refMargin = round(1.0 * refMaxDiff / refMax, 5) * 100.0
        curMargin = round(1.0 * curMaxDiff / curMax, 5) * 100.0
        return refMargin, curMargin
    def setUpSuite(self, suite):
        kpiGroups = suite.makeFileName("kpi_groups")
        if not os.path.isfile(kpiGroups):
            return
        groupFile = open(kpiGroups)
        for line in groupFile.readlines():
            if line[0] == '#' or not ':' in line:
                continue
            groupKey, groupValue = line.strip().split(":",1)
            if groupKey.find("_") == -1:
                testName = groupValue
                groupName = groupKey
                self.kpiGroupForTest[testName] = groupName
            else:
                groupName, groupParameter = groupKey.split("_", 1)
                if groupParameter == "q":
                    self.groupQualityLimit[groupName] = int(groupValue)
                if groupParameter == "t":
                    self.groupTimeLimit[groupName] = int(groupValue)
                if groupParameter == "pf":
                    self.groupPenaltyQualityFactor[groupName] = float(groupValue)
    def compare(self, test, referenceRun, currentRun):
        userName = os.path.normpath(os.environ["CARMUSR"]).split(os.sep)[-1]
        if not self.kpiGroupForTest.has_key(test.name):
            return
        groupName = self.kpiGroupForTest[test.name]
        if self.groupPenaltyQualityFactor.has_key(groupName):
            referenceRun.penaltyFactor = self.groupPenaltyQualityFactor[groupName]
            currentRun.penaltyFactor = self.groupPenaltyQualityFactor[groupName]
        testTuple = test, referenceRun, currentRun, userName
        self.testInGroupList.append(testTuple)
        fcTuple = referenceRun.getCost(-1), currentRun.getCost(-1)
        if not self.finalCostsInGroup.has_key(groupName):
            self.finalCostsInGroup[groupName] = []
        self.finalCostsInGroup[groupName].append(fcTuple)
    def getMargins(self, test):
        if not self.kpiGroupForTest.has_key(test.name):
            return optimization.MakeProgressReport.getMargins(self, test)
        refMargin = self.refMargins[self.kpiGroupForTest[test.name]]
        currentMargin = self.currentMargins[self.kpiGroupForTest[test.name]]
        return currentMargin, refMargin
    def calculateWorstCost(self, test, referenceRun, currentRun):
        worstCost = self._kpiCalculateWorstCost(test, referenceRun, currentRun)
        self.sumCurTime += currentRun.timeToCost(worstCost)
        self.sumRefTime += referenceRun.timeToCost(worstCost)
        self.lastKPITime = (currentRun.getPerformance() + referenceRun.getPerformance()) / 2.0
        if self.kpiGroupForTest.has_key(test.name):
            groupName = self.kpiGroupForTest[test.name]
            if self.groupTimeLimit.has_key(groupName):
                self.lastKPITime = self.groupTimeLimit[groupName]
        return worstCost
    def _kpiCalculateWorstCost(self, test, referenceRun, currentRun):
        if self.kpiGroupForTest.has_key(test.name):
            groupName = self.kpiGroupForTest[test.name]
            if self.groupQualityLimit.has_key(groupName):
                return self.groupQualityLimit[groupName]
        return optimization.MakeProgressReport.calculateWorstCost(self, test, referenceRun, currentRun)
    def computeKPI(self, currTTWC, refTTWC):
        kpi = optimization.MakeProgressReport.computeKPI(self, currTTWC, refTTWC)
        if kpi != "NaN%":
            kpiTime = self.lastKPITime
            self.sumKPITime += kpiTime
            if len(self.weightKPI) == 0 or kpiTime < self.minKPITime:
                self.minKPITime = kpiTime
            weightKPItuple = kpi, kpiTime
            self.weightKPI.append(weightKPItuple)
        return kpi
    def reportCosts(self, test, currentRun, referenceRun):
        optimization.MakeProgressReport.reportCosts(self, test, currentRun, referenceRun)
        if self.kpiGroupForTest.has_key(test.name):
            groupName = self.kpiGroupForTest[test.name]
            if self.groupTimeLimit.has_key(groupName):
                qualTime = self.groupTimeLimit[groupName]
                curCost = currentRun.costAtTime(qualTime)
                refCost = referenceRun.costAtTime(qualTime)
                kpi = float(curCost) / float(refCost)
                if kpi > 0:
                    self.qualKPI *= kpi
                    self.qualKPICount += 1
                    qKPI = str(round(kpi - 1.0,5) * 100.0) + "%"
                self.reportLine("Cost at " + str(qualTime) + " mins, qD=" + qKPI, curCost, refCost)
        currentMargin, refMargin = self.getMargins(test)
        self.reportLine("Cost variance tolerance (%) ", currentMargin, refMargin)
                

class ApcTestCaseInformation(optimization.TestCaseInformation):
    def isComplete(self):
        if not os.path.isdir(self.testPath()):
            return 0
        if not os.path.isfile(self.makeFileName("options")):
            return 0
        if not os.path.isfile(self.makeFileName("environment")):
            return 0
        if not os.path.isfile(self.makeFileName("performance")):
            return 0
        return 1
    def makeImport(self):
        testPath = self.testPath()
        optionPath = self.makeFileName("options")
        envPath = self.makeFileName("environment")
        statusPath = self.makeFileName("status")
        perfPath = self.makeFileName("performance")
        createdPath = 0
        if not os.path.isdir(testPath):
            os.mkdir(testPath)
            createdPath = 1
        if not os.path.isfile(optionPath):
            dirName = self.chooseSubPlan()
            if dirName == None:
                if createdPath == 1:
                    os.rmdir(testPath)
                return 0
            subPlanDir = os.path.join(dirName, "APC_FILES")
            ruleSet = self.getRuleSetName(subPlanDir)
            carmUsrSubPlanDirectory = self.replaceCarmUsr(subPlanDir)
            newOptions = self.buildOptions(carmUsrSubPlanDirectory, ruleSet)
            open(optionPath,"w").write(newOptions + os.linesep)
        else:
            subPlanDir = self.subPlanFromOptions(optionPath)
            carmUsrSubPlanDirectory = self.replaceCarmUsr(subPlanDir)
        if not os.path.isfile(envPath):
            envContent = self.buildEnvironment(carmUsrSubPlanDirectory)
            open(envPath,"w").write(envContent + os.linesep)
        if not os.path.isfile(perfPath):
            perfContent = self.buildPerformance(subPlanDir)
            open(perfPath, "w").write(perfContent + os.linesep)
        return 1
    def replaceCarmUsr(self, path):
        carmUser = os.environ["CARMUSR"]
        if path[0:len(carmUser)] == carmUser:
            return "${CARMUSR}" + os.path.join("/", path[len(carmUser) : len(path)])
        return path
    def subPlanFromOptions(self, optionPath):
        path = open(optionPath).readline().split()[0]
        if path[0:10] != "${CARMUSR}":
            return path
        if not os.environ.has_key("CARMUSR"):
            return path
        carmUsr = os.environ["CARMUSR"]
        npath = os.path.join(carmUsr, path.replace("${CARMUSR}", "./"))
        return os.path.normpath(npath)

    def buildOptions(self, path, ruleSet):
        subPlan = path
        statusFile = path + os.sep + "run_status"
        ruleSetPath = "${CARMTMP}" + os.sep + os.path.join("crc", "rule_set", "APC", "PUTS_ARCH_HERE")
        ruleSetFile = ruleSetPath + os.sep + ruleSet
        return subPlan + " " + statusFile + " ${CARMSYS} " + ruleSetFile + " ${USER}"

    def buildEnvironment(self, carmUsrSubPlanDirectory):
        lpEtab = carmUsrSubPlanDirectory.split(os.sep)[0:-2]
        spEtab = carmUsrSubPlanDirectory.split(os.sep)[0:-1]
        lpEtabLine = "LP_ETAB_DIR:" + os.path.normpath(string.join(lpEtab, "/") + "/etable")
        spEtabLine = "SP_ETAB_DIR:" + os.path.normpath(string.join(spEtab, "/") + "/etable")
        return lpEtabLine + os.linesep + spEtabLine

    def buildPerformance(self, subPlanDir):
        statusPath = self.makeFileName("status")
        if not os.path.isfile(statusPath):
            shutil.copyfile(os.path.join(subPlanDir, "status"), statusPath)
        if os.path.isfile(statusPath):
            lastLines = os.popen("tail -10 " + statusPath).xreadlines()
            for line in lastLines:
                if line[0:5] == "Time:":
                    sec = line.split(":")[1].split("s")[0]
                    return "CPU time   :     " + str(int(sec)) + ".0 sec. on onepusu"
# Give some default that will not end it up in the short queue
        return "CPU time   :      2500.0 sec. on onepusu"
        

class ApcTestSuiteInformation(optimization.TestSuiteInformation):
    def __init__(self, suite, name):
        optimization.TestSuiteInformation.__init__(self, suite, name)
    def getEnvContent(self):
        carmUsrDir = self.chooseCarmDir("CARMUSR")
        usrContent = "CARMUSR:" + carmUsrDir
        tmpContent = "CARMTMP:${CARMSYS}" + os.sep + self.makeCarmTmpName()
        return usrContent + os.linesep + tmpContent

class ImportTest(optimization.ImportTest):
    def getTestCaseInformation(self, suite, name):
        return ApcTestCaseInformation(suite, name)
    def getTestSuiteInformation(self, suite, name):
        return ApcTestSuiteInformation(suite, name)

class PortApcTest(plugins.Action):
    def __repr__(self):
        return "Porting old"
    def __call__(self, test):
        testInfo = ApcTestCaseInformation(self.suite, test.name)
        hasPorted = 0
        if test.options[0] == "-":
            hasPorted = 1
            subPlanDirectory = test.options.split()[3]
            carmUsrSubPlanDirectory = testInfo.replaceCarmUsr(subPlanDirectory)
            ruleSetName = testInfo.getRuleSetName(subPlanDirectory)
            newOptions = testInfo.buildOptions(carmUsrSubPlanDirectory, ruleSetName)
            fileName = test.makeFileName("options")
            shutil.copyfile(fileName, fileName + ".oldts")
            os.remove(fileName)
            optionFile = open(fileName,"w")
            optionFile.write(newOptions + "\n")
        else:
            subPlanDirectory = test.options.split()[0]
            carmUsrSubPlanDirectory = testInfo.replaceCarmUsr(subPlanDirectory)
        envFileName = test.makeFileName("environment")
        if not os.path.isfile(envFileName):
            hasPorted = 1
            envContent = testInfo.buildEnvironment(carmUsrSubPlanDirectory)
            open(envFileName,"w").write(envContent + os.linesep)
        perfFileName = test.makeFileName("performance")
        if not os.path.isfile(perfFileName):
            hasPorted = 1
            perfContent = testInfo.buildPerformance(carmUsrSubPlanDirectory)
            open(envFileName,"w").write(perfContent + os.linesep)
        else:
            lines = open(perfFileName).readlines()
            if len(lines) > 1:
                line1 = lines[0]
                line2 = lines[1]
                if line1[0:4] == "real" and line2[0:4] == "user":
                    sec = line2.split(" ")[1]
                    perfContent = "CPU time   :     " + str(float(sec)) + " sec. on heathlands"
                    open(perfFileName,"w").write(perfContent + os.linesep)
                    hasPorted = 1
        if hasPorted != 0:
            self.describe(test, " in " + testInfo.suiteDescription())
    def setUpSuite(self, suite):
        self.suite = suite

class UpdateCvsIgnore(plugins.Action):
    def __init__(self):
        self.masterCvsIgnoreFile = None
        self.updateCount = 0
    def __repr__(self):
        return "Greping"
    def __del__(self):
        if self.updateCount > 0:
            print "Updated", self.updateCount, ".cvsignore files"
        else:
            print "No .cvsignore files updated"
    def __call__(self, test):
        if self.masterCvsIgnoreFile == None:
            return
        fileName = os.path.join(test.getDirectory(temporary=1), ".cvsignore")
        if not os.path.isfile(fileName) or filecmp.cmp(fileName, self.masterCvsIgnoreFile) == 0:
            shutil.copyfile(self.masterCvsIgnoreFile, fileName)
            self.updateCount += 1
        
    def setUpSuite(self, suite):
        pass
    def setUpApplication(self, app):
        fileName = os.path.join(test.getDirectory(temporary=1), "cvsignore.master")
        if os.path.isfile(fileName):
            self.masterCvsIgnoreFile = fileName

class PrintAirport(plugins.Action):
    def __repr__(self):
        return "Print AirportFile"
    def __call__(self, test):
        pass
    def setUpSuite(self, suite):
        if suite.name == "picador":
            return
        etabPath = os.path.join(os.environ["CARMUSR"], "Resources", "CarmResources")
        customerEtab = os.path.join(etabPath, "Customer.etab")
        if os.path.isfile(customerEtab):
            etab = ravebased.ConfigEtable(customerEtab)
            airportFile = etab.getValue("default", "AirpMaint", "AirportFile")
            if airportFile != None:
                self.describe(suite, ": " + airportFile)
                return
        self.describe(suite, " without airportfile in: " + customerEtab)
        pass
    def setUpApplication(self, app):
        pass

class UpdatePerformance(plugins.Action):
    def __init__(self, args = []):
        self.updateVersions = [ "" ]
        self.statusFileName = None
        self.interpretOptions(args)
    def __repr__(self):
        return "Updating performance"
    def __call__(self, test):
        for version in self.updateVersions:
            statusFile = self.getStatusFile(test, version)
            performanceFile = self.getPerformanceFile(test, version)
            if statusFile == None or performanceFile == None:
                continue
            lastTime = self.getLastTime(test, version, statusFile)
            runHost = self.getExecHost(statusFile)
            totPerf = int(performance.getPerformance(performanceFile))
            verText = " (master)"
            if version != "":
                verText = " (" + version + ")"
            if not runHost in test.app.getConfigList("performance_test_machine"):
                self.describe(test, verText + " no update (not perf. machine) for run on " + runHost)
                continue
            if lastTime == totPerf:
                self.describe(test, verText + " no need for update (time: %d s.)" %(lastTime))
                continue
            self.describe(test, verText + " perf:" + str(totPerf) + ", status: " + str(lastTime) + ", on " + runHost)
            updatePerformanceFile = performanceFile
            if version != "" and string.split(updatePerformanceFile, '.')[-1] != version:
                updatePerformanceFile += '.' + version
            open(updatePerformanceFile, "w").write("CPU time   :      " + str(lastTime) + ".0 sec. on " + runHost + os.linesep)
    def interpretOptions(self, args):
        for ar in args:
            arr = ar.split("=")
            if arr[0]=="v":
                self.updateVersions = arr[1].split(",")
            elif not self.setOption(arr):
                print "Unknown option " + arr[0]
    def setOption(self, arr):
        return 0
    def getExecHost(self, file):
        hostLine = os.popen("grep achine " + file + " | tail -1").readline().strip()
        return hostLine.split(":")[1].strip()
    def getLastTime(self, test, version, file):
        optRun = optimization.OptimizationRun(test, version, [ optimization.timeEntryName ], [], 0)
        times = optRun.solutions[-1][optimization.timeEntryName]
        return int(times * 60.0)
    def getStatusFile(self, test, version):
        currentFile = test.makeFileName(self.statusFileName, version)
        if not os.path.isfile(currentFile):
            return None
        return currentFile
    def getPerformanceFile(self, test, version):
        currentFile = test.makeFileName("performance", version)
        if not os.path.isfile(currentFile):
            return None
        return currentFile
    def setUpSuite(self, suite):
        pass
    def setUpApplication(self, app):
        self.statusFileName = app.getConfigValue("log_file")

#
# Create environment.apc.$ARCH files.
#

class CopyEnvironment(plugins.Action):
    def __repr__(self):
        return "Making environment.apc.ARCH for"
    def setUpSuite(self, suite):
        if ravebased.isUserSuite(suite):
            self.describe(suite)
            oldFile = os.path.join(suite.abspath, "environment.apc")
            if not os.path.isfile(oldFile):
                return

            carmTmp = self.getCarmtmp(oldFile)
            archs = self.getArchs()
            for arch in archs:
                targetFile = oldFile + "." + arch
                if os.path.isfile(targetFile):
                    continue
                print "Want to create " + targetFile
                print "with CARMTMP " + carmTmp + "." + arch
                self.makeCarmtmpFile(targetFile, carmTmp + "." + arch)
    def getArchs(self):
        archs = [ "sparc", "sparc_64"]
        return archs
    def makeCarmtmpFile(self, targetFile, carmtmp):
        file = open(targetFile, "w")
        print carmtmp
        file.write("CARMTMP:" + carmtmp + os.linesep)
        file.close()
    def getCarmtmp(self, file):
        for line in open(file).xreadlines():
            if line.startswith("CARMTMP"):
                name, carmtmp = line.strip().split(":")
                return carmtmp
