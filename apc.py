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
             
-prrepgraphical
           - (only APC) Produces a graphical progress reports. Also see prrep.
           
-prrephtml <directory>
           - (only APC) Produces an html progress report with graphics.
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

apc.CVSBranchTests         - This script is useful when two versions of a test starts to differ.
                             For all relevant APC files in the current testselection, it check if the
                             files are CVS modified. If they are, the check-in result is stored in version v.
                             Example: texttest -a apc -s apc.CVSBranchTests 11

"""

import default, ravebased, carmen, queuesystem, performance, os, sys, stat, string, shutil, KPI, optimization, plugins, math, filecmp, re, popen2, unixonly, guiplugins, exceptions, time
from time import sleep
from ndict import seqdict

def readKPIGroupFileCommon(suite):
    kpiGroupForTest = {}
    kpiGroups = []
    kpiGroupsFileName = suite.makeFileName("kpi_groups")
    if not os.path.isfile(kpiGroupsFileName):
        return {},[]
    groupFile = open(kpiGroupsFileName)
    groupName = None
    for line in groupFile.readlines():
        if line[0] == '#' or not ':' in line:
            continue
        groupKey, groupValue = line.strip().split(":",1)
        if groupKey.find("_") == -1:
            if groupName:
                groupKey = groupName
            testName = groupValue
            kpiGroupForTest[testName] = groupKey
            try:
                ind = kpiGroups.index(groupKey)
            except ValueError:
                kpiGroups.append(groupKey)
        else:
            gk = groupKey.split("_")
            kpigroup = gk[0]
            item = gk[1]
            if item == "name":
                groupName = groupValue
    groupFile.close()
    return kpiGroupForTest,kpiGroups

def getConfig(optionMap):
    return ApcConfig(optionMap)

class ApcConfig(optimization.OptimizationConfig):
    def addToOptionGroups(self, app, groups):
        optimization.OptimizationConfig.addToOptionGroups(self, app, groups)
        for group in groups:
            if group.name.startswith("How"):
                group.addOption("rundebug", "Run debugger")
                group.addOption("extractlogs", "Extract Apc Logs")
            if group.name.startswith("Invisible"):
                # These need a better interface before they can be plugged in, really
                group.addOption("prrepgraphical", "Run graphical KPI progress report")
                group.addOption("prrephtml", "Generates an HTML KPI progress report with graphics")
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
        if self.optionMap.has_key("prrepgraphical"):
            return MakeProgressReportGraphical(self.optionValue("prrep"))
        elif self.optionMap.has_key("prrephtml"):
            return MakeProgressReportHTML(self.optionValue("prrep"), self.optionValue("prrephtml"))
        else:
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
    def isExecutable(self, process, parentProcess, test):
        # Process name starts with a dot and may be truncated or have
        # extra junk at the end added by APCbatch.sh
        processData = process[1:]
        rulesetName = self.getRuleSetName(test)
        return processData.startswith(rulesetName) or rulesetName.startswith(processData)
    def getFileCollator(self):
        subActions = []
        subActions.append(FetchApcCore(self.optionMap.has_key("keeptmp")))
        subActions.append(RemoveLogs())
        if self.optionMap.slaveRun():
            useExtractLogs = self.optionValue("extractlogs")
            if useExtractLogs == "":
                useExtractLogs = "all"
            subActions.append(ExtractApcLogs(useExtractLogs))
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
    def statusUpdater(self):
        return ApcUpdateStatus()
    def printHelpDescription(self):
        print helpDescription
        optimization.OptimizationConfig.printHelpDescription(self)
    def printHelpOptions(self):
        optimization.OptimizationConfig.printHelpOptions(self)
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
            try:
                os.makedirs(logFileDir)
            except OSError:
                return
                
class CheckFilesForApc(plugins.Action):
    def __call__(self, test):
        verifyAirportFile(carmen.getArchitecture(test.app))
        verifyLogFileDir(carmen.getArchitecture(test.app))        

class ViewApcLog(guiplugins.InteractiveAction):
    def __repr__(self):
        return "Viewing log of"
    def __call__(self, test):
        viewLogScript = test.makeFileName("view_apc_log", temporary=1, forComparison=0)
        if os.path.isfile(viewLogScript):
            file = open(viewLogScript)
            command = file.readlines()[0].strip()
            file.close()
            process = self.startExternalProgram(command)
            guiplugins.scriptEngine.monitorProcess("views the APC log", process)
        else:
            raise plugins.TextTestError, "APC log file not yet available"
    def getTitle(self):
        return "View APC Log"

guiplugins.interactiveActionHandler.testClasses.append(ViewApcLog)

#
# Runs the test in gdb and displays the log file. 
#
class RunApcTestInDebugger(default.RunTest):
    def __init__(self, options, keepTmpFiles):
        default.RunTest.__init__(self)
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
        # Check for personal .gdbinit.
        if os.path.isfile(os.path.join(os.environ["HOME"], ".gdbinit")):
            print "Warning: You have a personal .gdbinit. This may create unexpected behaviour."
        # Change to running state, without an associated process
        self.changeToRunningState(test, None)
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

class ApcUpdateStatus(queuesystem.UpdateTestStatus):
    def getExtraRunData(self, test):
         subplanDir = test.writeDirs[-1]
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
        machine = default.hostname()
        diag.info("Test was run locally on " + machine)
    return machine

class FetchApcCore(unixonly.CollateFiles):
    def isApcLogFileKept(self, errorFileName):
        for line in open(errorFileName).xreadlines():
            if line.find("*** Keeping the logfiles in") != -1:
                return 1
        return None
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
        resLine = os.popen(". " + configFile + "; echo ${APC_TEMP_DIR}").readlines()[-1].strip()
        if resLine.find("/") != -1:
            return resLine
        return "/tmp"
    def getApcLogDir(self, test, processId = None):
        # Logfile dir
        subplanName, apcFiles = os.path.split(test.writeDirs[1])
        baseSubPlan = os.path.basename(subplanName)
        if processId:
            return os.path.join(self.getApcHostTmp(), baseSubPlan + "_" + processId)
        for file in os.listdir(self.getApcHostTmp()):
            if file.startswith(baseSubPlan + "_"):
                return os.path.join(self.getApcHostTmp(), file)
    def handleNoTimeAvailable(self, test):
        # We try to pick out the log directory, at least
        apcLogDir = self.getApcLogDir(test)
        if apcLogDir:
            test.writeDirs.append(apcLogDir)
    def makeLinks(self, test, apcTmpDir):
        sourceName = os.path.join(test.writeDirs[1], "run_status_head")
        targetName = os.path.join(test.writeDirs[0], "run_status_head")
        try:
            os.symlink(sourceName, targetName)
        except OSError:
            print "Failed to create run_status_head link"
        viewLogScript = test.makeFileName("view_apc_log", temporary=1, forComparison=0)
        file = open(viewLogScript, "w")
        logFileName = os.path.join(apcTmpDir, "apclog")
        file.write("xon " + default.hostname() + " 'xterm -bg white -T " + test.name + " -e 'less +F " + logFileName + "''")
        file.close()
    def performParallelAction(self, test, execProcess, parentProcess):
        apcTmpDir = self.getApcLogDir(test, str(parentProcess.processId))
        self.diag.info("APC log directory is " + apcTmpDir + " based on process " + parentProcess.getName())
        if not os.path.isdir(apcTmpDir):
            raise plugins.TextTestError, "ERROR : " + apcTmpDir + " does not exist - running process " + execProcess.getName()
        self.makeLinks(test, apcTmpDir)
        test.writeDirs.append(apcTmpDir)
        self.describe(test)
        if self.keepLogs:
            fileName = os.path.join(apcTmpDir, "apc_debug")
            file = open(fileName, "w")
            file.close()

class ExtractApcLogs(plugins.Action):
    def __init__(self, args):
        self.diag = plugins.getDiagnostics("ExtractApcLogs")
        self.args = args
        if not self.args:
            print "No argument given, using default value for extract_logs"
            self.args = "default"
    def __call__(self, test):
        apcTmpDir = test.writeDirs[-1]
        if not os.path.isdir(apcTmpDir):
            return
        self.diag.info("Extracting from APC tmp directory " + apcTmpDir)

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
        extractToFile = test.makeFileName(saveName, temporary = 1)
        cmdLine = "cd " + apcTmpDir + "; " + extractCommand + " > " + extractToFile
        os.system(cmdLine)
        # We sometimes have problems with an empty file extracted.
        if os.stat(extractToFile)[stat.ST_SIZE] == 0:
            os.remove(extractToFile)
        # Extract mpatrol files, if they are present.
        if os.path.isfile(os.path.join(apcTmpDir, "mpatrol.out")):
            cmdLine = "cd " + apcTmpDir + "; " + "cat mpatrol.out" + " > " + test.makeFileName("mpatrol_out", temporary = 1)
            os.system(cmdLine)
        if os.path.isfile(os.path.join(apcTmpDir, "mpatrol.log")):
            cmdLine = "cd " + apcTmpDir + "; " + "cat mpatrol.log" + " > " + test.makeFileName("mpatrol_log", temporary = 1)
            os.system(cmdLine)
        # Extract scprob prototype...
        #if os.path.isfile(os.path.join(apcTmpDir, "APC_rot.scprob")):
        #    cmdLine = "cd " + apcTmpDir + "; " + "cat  APC_rot.scprob" + " > " + test.makeFileName(" APC_rot.scprob", temporary = 1)
        #    os.system(cmdLine)
        
        # When apc_debug is present, we want to remove the error file
        # (which is create because we are keeping the logfiles,
        # with the message "*** Keeping the logfiles in $APC_TEMP_DIR ***"),
        # otherwise the test is flagged failed.
        if os.path.isfile(os.path.join(apcTmpDir, "apc_debug")):
            errFile = test.makeFileName("script_errors", temporary=1)
            if os.path.isfile(errFile):
                os.remove(errFile)
        # Remove dir
        plugins.rmtree(apcTmpDir)
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
        self.testInGroup = {}
        self.finalCostsInGroup = {}
        self.lowestCostInGroup = {}
        self.weightKPI = []
        self.sumKPITime = 0.0
        self.minKPITime = 0.0
        self.sumCurTime = 0
        self.sumRefTime = 0
        self.qualKPI = 1.0
        self.qualKPICount = 0
        self.spreadKPI = 1.0
        self.spreadKPICount = 0
        self.lastKPITime = 0
    def __del__(self):
        for groupName in self.finalCostsInGroup.keys():
            fcTupleList = self.finalCostsInGroup[groupName]
            refMargin, currentMargin = self._calculateMargin(fcTupleList)
            self.refMargins[groupName] = refMargin
            self.currentMargins[groupName] = currentMargin

        referenceAverages = {}
        currentAverages = {}
        userNameForKPIGroup = {}
        # Iterate over all tests and add them to the relevant KPI group.
        for testName in self.testInGroup.keys():
            test, referenceRun, currentRun, userName = self.testInGroup[testName]
            app = test.app
            if not self.kpiGroupForTest.has_key(test.name):
                print "Warning: Skipping test not in KPI group:", test.name
                continue
            groupName = self.kpiGroupForTest[test.name]
            if not userNameForKPIGroup.has_key(groupName):
                userNameForKPIGroup[groupName] = userName
            
            self.addRunToAverage(referenceRun, referenceAverages, groupName)
            self.addRunToAverage(currentRun, currentAverages, groupName)

        # Calculate the KPI for each KPI group.
        for groupName in self.finalCostsInGroup.keys():
            referenceAverageRun, referenceMinRun, referenceMaxRun = self.createOptimizationRuns(referenceAverages[groupName])
            currentAverageRun, currentMinRun, currentMaxRun = self.createOptimizationRuns(currentAverages[groupName])
            self.doCompare(referenceAverageRun, currentAverageRun, app, groupName, userNameForKPIGroup[groupName], "KPI-group", (referenceMinRun, referenceMaxRun,currentMinRun, currentMaxRun))
    
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
        if self.spreadKPICount > 0:
            avg = math.pow(self.spreadKPI, 1.0 / float(self.spreadKPICount))
            qNumber = round(avg,5) * 100.0
            wText = "PV1 (spread at end) with respect to version"
            print wText, self.referenceVersion, "=", str(qNumber) + "%"
        optimization.MakeProgressReport.__del__(self)
        if len(self.weightKPI) > 1:
            # The weighted KPI is prod(KPIx ^ (Tx / Ttot)) (weighted geometric average)
            # Tx is the kpi time limit for a specific test case's kpi group.
            # If no such time limit is set then the average total time of the testcase is used, ie
            # Tx = (curTotalTime + refTotalTime) / 2
            # Ttot = sum Tx
            #
            sumkpiTime = 0.0
            for tup in self.weightKPI:
                kpiS, kpiTime = tup
                sumkpiTime += kpiTime
            self.prodKPI = 1.0
            for tup in self.weightKPI:
                kpiS, kpiTime = tup
                kpi = float(kpiS.split("%")[0]) / 100
                self.prodKPI *= math.pow(kpi, 1.0 * kpiTime / sumkpiTime)
            wText = "Overall time weighted KPI with respect to version"
            print wText, self.referenceVersion, "=", self.percent(self.prodKPI)
    def doCompare(self, referenceRun, currentRun, app, groupName, userName, groupNameDefinition = "test", minMaxRuns = None):
        kpiData = optimization.MakeProgressReport.doCompare(self, referenceRun, currentRun, app, groupName, userName, groupNameDefinition,minMaxRuns)

        self.plotKPI(self.testCount, currentRun, referenceRun, groupName, userName, kpiData, minMaxRuns)

    def getPerformance(self, test, currentVersion, referenceVersion):
        return 0.0, 0.0
    def getLogFilesForComparison(self, test):
        return self.getLogFile(test, self.currentVersion), self.getLogFile(test, self.referenceVersion)
    def getLogFile(self, test, version):
        logFileStem = test.app.getConfigValue("log_file")
        root = test.getDirectory(0, 1)
        ver = ""
        if version:
            ver = "." + version
        logFile = os.path.join(root, logFileStem + "." + test.app.name + ver)
        if not os.path.isfile(logFile):
            print "Test", test.name, "has no status file version", version, "Skipping this test."
            logFile = None
        return logFile
    def getConstantItemsToExtract(self):
        return [ "Machine", optimization.apcLibraryDateName ]
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
        self.testInGroup[test.name] = testTuple
        fcTuple = referenceRun.getCost(-1), currentRun.getCost(-1)
        if not self.finalCostsInGroup.has_key(groupName):
            self.finalCostsInGroup[groupName] = []
        self.finalCostsInGroup[groupName].append(fcTuple)
        if not self.lowestCostInGroup.has_key(groupName):
            self.lowestCostInGroup[groupName] = min(fcTuple)
            return
        self.lowestCostInGroup[groupName] = min(self.lowestCostInGroup[groupName], min(fcTuple))
    def getMargins(self, app, groupName):
        refMargin = self.refMargins[groupName]
        currentMargin = self.currentMargins[groupName]
        return currentMargin, refMargin
    def calculateWorstCost(self, referenceRun, currentRun, app, groupName):
        if self.groupQualityLimit.has_key(groupName):
            worstCost = self.groupQualityLimit[groupName]
        else:
            print "Warning, quality not defined for KPI group", groupName
            worstCost = optimization.MakeProgressReport.calculateWorstCost(self, referenceRun, currentRun, app, groupName)
        self.sumCurTime += currentRun.timeToCost(worstCost)
        self.sumRefTime += referenceRun.timeToCost(worstCost)
        self.lastKPITime = (currentRun.getPerformance() + referenceRun.getPerformance()) / 2.0
        if self.groupTimeLimit.has_key(groupName):
            self.lastKPITime = self.groupTimeLimit[groupName]
        return worstCost
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
    def reportCosts(self, currentRun, referenceRun, app, groupName, minMaxRuns=None):
        retVal = optimization.MakeProgressReport.reportCosts(self, currentRun, referenceRun, app, groupName)
        if self.groupTimeLimit.has_key(groupName):
            qualTime = self.groupTimeLimit[groupName]
            curCost = currentRun.costAtTime(qualTime)
            refCost = referenceRun.costAtTime(qualTime)
            kpi = float(curCost) / float(refCost)
            # add a line for the plot
            retVal["qualKPILine"]=((qualTime,curCost),(qualTime,refCost),1)
            if kpi > 0:
                self.qualKPI *= kpi
                self.qualKPICount += 1
                qKPI = str(round(kpi - 1.0,5) * 100.0) + "%"
            self.reportLine("Cost at " + str(qualTime) + " mins, qD=" + qKPI, curCost, refCost)
        currentMargin, refMargin = self.getMargins(app, groupName)
        self.reportLine("Cost variance tolerance (%) ", currentMargin, refMargin)
        if minMaxRuns:
            referenceMinRun, referenceMaxRun, currentMinRun, currentMaxRun = minMaxRuns
            referenceSpreadAtEnd=float(referenceMaxRun.getCost(-1))/float(referenceMinRun.getCost(-1))-1;
            currentSpreadAtEnd=float(currentMaxRun.getCost(-1))/float(currentMinRun.getCost(-1))-1;
            spreadKPI=(currentSpreadAtEnd)/(max(referenceSpreadAtEnd,0.0000000001))
            self.reportLine("Relative spread (%)", "%f"%(100*currentSpreadAtEnd), "%f"%(referenceSpreadAtEnd*100))
            self.spreadKPI *= spreadKPI;
            self.spreadKPICount += 1;
            # add lines for the plot
            endTime = referenceMinRun.getTime(-1);
            retVal["refEndLine"]=((endTime,referenceMinRun.getCost(-1)),(endTime,referenceMaxRun.getCost(-1)),0)
            endTime=currentMinRun.getTime(-1);
            retVal["currEndLine"]=((endTime,currentMinRun.getCost(-1)),(endTime,currentMaxRun.getCost(-1)),0)
        return retVal;
        
    # Extracts data from an OptimizationRun and adds it to the appropriate averager.
    def addRunToAverage(self, optRun, averagerMap, groupName):
        costGraph = {}
        memoryGraph = {}
        for solution in optRun.solutions:
            time = solution[optimization.timeEntryName]
            costGraph[time] = solution[optimization.costEntryName]
            memoryGraph[time] = solution[optimization.memoryEntryName]

        # Find what averagers to put it in.
        if averagerMap.has_key(groupName):
            averagers = averagerMap[groupName]
        else:
            averagers = averagerMap[groupName] = optimization.Averager(1), optimization.Averager(1)
        costAverager, memAverager = averagers
        costAverager.addGraph(costGraph)
        memAverager.addGraph(memoryGraph)
        
    # Creates an OptimizationRun from the averager values.
    def createOptimizationRuns(self, averages):
        costAverage, memAverage = averages
        costAverageGraph = costAverage.getAverage()
        memAverageGraph = memAverage.getAverage()
        averRun = self.createOptimizationRun(costAverageGraph, memAverageGraph)
        costMinGraph, costMaxGraph = costAverage.getMinMax()
        memMinGraph, memMaxGraph = memAverage.getMinMax()
        minRun = self.createOptimizationRun(costMinGraph, memMinGraph)
        maxRun = self.createOptimizationRun(costMaxGraph, memMaxGraph)
        return averRun, minRun, maxRun
        
    def createOptimizationRun(self, costGraph, memGraph):
        solution = []
        timeVals = costGraph.keys()
        timeVals.sort()
        for time in timeVals:
            if not memGraph.has_key(time):
                print "Errror!"
            else:
                map = {}
                map[optimization.timeEntryName] = time
                map[optimization.costEntryName] = costGraph[time]
                map[optimization.memoryEntryName] = memGraph[time]
                solution.append(map)
        return optimization.OptimizationRun("","","","", 0.0, solution)
    def plotKPI(self, testCount, currentRun, referenceRun, groupName, userName, kpiData, minMaxRuns):
        pass

# Produces graphical output for the progress report.
class MakeProgressReportGraphical(MakeProgressReport):
    def __init__(self, referenceVersion):
        MakeProgressReport.__init__(self, referenceVersion)
        self.matplotlibPresent = 0
        try:
            from matplotlib.pylab import figure, axes, plot, show, title, legend, FuncFormatter, savefig, fill
            self.figure = figure
            self.axes = axes
            self.plot = plot
            self.show = show
            self.title = title
            self.legend = legend
            self.FuncFormatter = FuncFormatter
            self.savefig = savefig
            self.fill = fill
            self.matplotlibPresent = 1
        except:
            print "The matplotlib package doesn't seem to be in PYTHONPATH." + os.linesep + "No graphical output will be avaliable."
    def __del__(self):
        MakeProgressReport.__del__(self)
        if self.matplotlibPresent:
            # Finally show the matlab plots.
            self.show()
    def plotRun(self, optRun, options, linewidth = 0.5):
        xVals = []
        yVals = []
        solutionPrev = optRun.solutions[0]
        for solution in optRun.solutions[1:]:
            xVals.append(solutionPrev[optimization.timeEntryName])
            yVals.append(solutionPrev[optimization.costEntryName])
            xVals.append(solution[optimization.timeEntryName])
            yVals.append(solutionPrev[optimization.costEntryName])
            solutionPrev = solution
        xVals.append(solutionPrev[optimization.timeEntryName])
        yVals.append(solutionPrev[optimization.costEntryName])
        self.plot(xVals, yVals, options, linewidth = linewidth)
    def fillRuns(self, optRunMin, optRunMax, axes, options, color = '#dddddd'):
        xVals = []
        yVals = []
        solutionPrev = optRunMin.solutions[0]
        for solution in optRunMin.solutions[1:]:
            xVals.append(solutionPrev[optimization.timeEntryName])
            yVals.append(solutionPrev[optimization.costEntryName])
            xVals.append(solution[optimization.timeEntryName])
            yVals.append(solutionPrev[optimization.costEntryName])
            solutionPrev = solution
        xVals.append(solutionPrev[optimization.timeEntryName])
        yVals.append(solutionPrev[optimization.costEntryName])
        solutionPrev = optRunMax.solutions[-1]
        tmpSol = optRunMax.solutions[1:]
        tmpSol.reverse()
        for solution in tmpSol:
            xVals.append(solutionPrev[optimization.timeEntryName])
            yVals.append(solutionPrev[optimization.costEntryName])
            xVals.append(solutionPrev[optimization.timeEntryName])
            yVals.append(solution[optimization.costEntryName])
            solutionPrev = solution
        axes.fill(xVals, yVals, color , linewidth = 0, edgecolor = options)
    def plotLine(self,axis,line,col="r"):
        (ax,ay),(bx,by),pullTo0=line;
        ax,bx = min(ax,bx),max(ax,bx)
        ay,by = min(ay,by),max(ay,by)
        ylim = axis.get_ylim()
        xlim = axis.get_xlim()

        dy = (ylim[1]-ylim[0])*0.07;
        dx = (xlim[1]-xlim[0])*0.07;
        if ay == by:
            dx = 0;
            if pullTo0:
                self.plot([0,bx],[ay,by],col,linewidth=1.5)
        if ax == bx:
            dy = 0
            if pullTo0:
                self.plot([ax,bx],[0,by],col,linewidth=1.5)
        self.plot([ax,bx],[ay,by],col,linewidth=1.5)
        self.plot([ax-dx,ax+dx],[ay+dy,ay-dy],col,linewidth=1.5)
        self.plot([bx-dx,bx+dx],[by+dy,by-dy],col,linewidth=1.5)
        #retain the limits (hold does not work)
        axis.set_ylim(ylim),
        axis.set_xlim(xlim)
    def plotPost(self, ax,lowestCost,maxend,kpiData):
        ax.set_ylim( (lowestCost*0.999, max(lowestCost * 1.05, maxend*1.001)) )
        self.plotLine(ax,kpiData["KPILine"],"r")
        for k,c in [("qualKPILine","k"),("refEndLine","b"),("currEndLine","g")]:
            if kpiData.has_key(k):
                self.plotLine(ax, kpiData[k], c)
        currVer = self.currentVersion
        if not self.currentVersion:
            currVer = "current"
        self.legend([self.referenceVersion, currVer])
    def plotKPI(self, testCount, currentRun, referenceRun, groupName, userName, kpiData, minMaxRuns):
        if not self.matplotlibPresent:
            return
        self.figure(testCount, facecolor = 'w', figsize = (12,5))
        axesBG  = '#f6f6f6'
        height = 0.79
        width = 0.38
        up = 0.11
        # Create a formatter for the ylabels.
        lowestCostInGroup = self.lowestCostInGroup[groupName]
        form = self.MyFormatter(lowestCostInGroup)
        majorFormatter = self.FuncFormatter(form.formatterFcn)
        # Plot the average curves on the left axes.
        ax = self.axes([0.1, up ,width, height], axisbg = axesBG)
        ax.yaxis.set_major_formatter(majorFormatter)
        self.plotRun(referenceRun, "b", 1.5)
        self.plotRun(currentRun, "g", 1.5)
        if minMaxRuns:
            referenceMinRun, referenceMaxRun, currentMinRun, currentMaxRun = minMaxRuns
            self.fillRuns(referenceMinRun, referenceMaxRun, ax, "b", '#cccccc')
            self.fillRuns(currentMinRun, currentMaxRun, ax, "g")
            self.plotRun(referenceMinRun ,"b--", 1)
            self.plotRun(referenceMaxRun ,"b--", 1)
            self.plotRun(currentMinRun ,"g--", 1)
            self.plotRun(currentMaxRun ,"g--", 1)
        self.plotRun(referenceRun, "b", 1.5)
        self.plotRun(currentRun, "g", 1.5)
        maxFinal=max(map(lambda x:max(x),self.finalCostsInGroup[groupName]))
        self.plotPost(ax, lowestCostInGroup,maxFinal, kpiData)
        self.title("User " + userName + ", KPI group " + groupName + ": " + str(kpiData["kpi"]))
        # Plot the individual curves on the right axes.
        ax = self.axes([0.585, up, width, height], axisbg = axesBG)
        ax.yaxis.set_major_formatter(majorFormatter)
        for testName in self.testInGroup.keys():
            if self.kpiGroupForTest[testName] == groupName:
                test, referenceIndividualRun, currentIndividualRun, userName = self.testInGroup[testName]
                self.plotRun(referenceIndividualRun, "b")
                self.plotRun(currentIndividualRun, "g")
        self.plotPost(ax, lowestCostInGroup, maxFinal,kpiData)
        self.title("Individual runs")
    # Tiny class to provide a UNIQUE formatter function carrying the lowest
    # value for each group (which corresponds to a plot)
    class MyFormatter:
        def __init__(self, lowestValue):
            self.lowestValue = lowestValue
        def formatterFcn(self, y, pos):
            return '%.2e(%.1f%%)' % (y, 100*y/self.lowestValue-100)     

# Class that uses the graphical progress report to produce an html report.
class MakeProgressReportHTML(MakeProgressReportGraphical):
    def __init__(self, referenceVersion, arguments):
        MakeProgressReportGraphical.__init__(self, referenceVersion)
        self.writeHTML = 0
        try:
            from HTMLgen import SimpleDocument, Text, HR, Image, Heading, Center, Container
            self.htmlText = Text
            self.htmlHR = HR
            self.htmlImage = Image
            self.htmlHeading = Heading
            self.htmlCenter = Center
            self.htmlContainer = Container
            self.writeHTML = 1
        except:
            print "The HTMLGen package doesn't seem to be in PYTHONPATH."
        self.savePlots = 0
        if arguments:
            self.dirForPlots = arguments
            if os.path.isdir(self.dirForPlots):
                self.savePlots = 1
                if self.writeHTML:
                    self.indexDoc = SimpleDocument()
                    headline = "APC version " + self.currentVersion + ", compared to version " + self.referenceVersion
                    self.indexDoc.title = "KPI: " + headline
                    self.indexDoc.append(self.htmlCenter(self.htmlHeading(1, headline)))
                    self.summaryContainer = self.htmlContainer()
                    self.indexDoc.append(self.summaryContainer)
                    self.indexDoc.append(self.htmlHR())
            else:
                print "The directory", self.dirForPlots, "doesn't exist. No plots will be saved."
                self.writeHTML = 0
        else:
            print "No directory specified for html and plots."
            self.writeHTML = 0
    def __del__(self):
        MakeProgressReport.__del__(self)
        if self.writeHTML:
            self.summaryContainer.append((self.htmlHeading(2, "Overall average KPI = " + self.percent(math.pow(self.totalKpi, 1.0 / float(self.testCount))))))
            if len(self.weightKPI) > 1:
                self.summaryContainer.append((self.htmlHeading(2, "Overall time weighted average KPI = " + self.percent(self.prodKPI))))
            self.summaryContainer.append((self.htmlHeading(2, "Best KPI = " + self.percent(self.bestKpi))))
            self.summaryContainer.append((self.htmlHeading(2, "Worst KPI = " + self.percent(self.worstKpi))))
            self.indexDoc.append(self.htmlHR())
            self.indexDoc.write(os.path.join(self.dirForPlots, "index.html"))
    def plotKPI(self, testCount, currentRun, referenceRun, groupName, userName, kpiData, minMaxRuns):
        MakeProgressReportGraphical.plotKPI(self, testCount, currentRun, referenceRun, groupName, userName, kpiData, minMaxRuns)
        if self.savePlots:
            self.savefig(os.path.join(self.dirForPlots, groupName))
            if self.writeHTML:
                self.indexDoc.append(self.htmlImage(groupName + ".png"))

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
        application = self.suite.app.name
        if application == "cs":
            application = "FANDANGO"
        else:
            application = "APC"
        ruleSetPath = "${CARMTMP}" + os.sep + os.path.join("crc", "rule_set", application, "PUTS_ARCH_HERE")
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

class ImportTestSuite(optimization.ImportTestSuite):
    def getCarmtmpDirName(self, carmUsr):
        return optimization.ImportTestSuite.getCarmtmpDirName(self, carmUsr) + ".apc"
    def getEnvironmentFileName(self, suite):
        return "environment." + suite.app.name
    
# Graphical import
class ImportTestCase(optimization.ImportTestCase):
    def getSubplanPath(self, suite, subplan):
        suite.setUpEnvironment(parents=1)
        subplanPath = os.path.join(os.environ["CARMUSR"], "LOCAL_PLAN", subplan, "APC_FILES")
        suite.tearDownEnvironment(parents=1)
        return subplanPath
    def findRuleset(self, suite, subplan):
        subplanPath = self.getSubplanPath(suite, subplan)
        return self.getRuleSetName(subplanPath)
    # copied from TestCaseInformation...
    def getRuleSetName(self, absSubPlanDir):
        problemPath = os.path.join(absSubPlanDir,"problems")
        if not unixonly.isCompressed(problemPath):
            problemLines = open(problemPath).xreadlines()
        else:
            tmpName = os.tmpnam()
            shutil.copyfile(problemPath, tmpName + ".Z")
            os.system("uncompress " + tmpName + ".Z")
            problemLines = open(tmpName).xreadlines()
            os.remove(tmpName)
        for line in problemLines:
            if line[0:4] == "153;":
                return line.split(";")[3]
        return ""
    def writeResultsFiles(self, suite, testDir):
        subPlanDir = self.getSubplanPath(suite, self.getSubplanName())
        statusPath = os.path.join(testDir, "status." + suite.app.name)
        if not os.path.isfile(statusPath):
            shutil.copyfile(os.path.join(subPlanDir, "status"), statusPath)
        perf = self.getPerformance(statusPath)
        perfFile = self.getWriteFile("performance", suite, testDir)
        perfFile.write("CPU time   :     " + str(int(perf)) + ".0 sec. on tiptonville" + os.linesep)
        perfFile.close()
    def getEnvironment(self, suite):
        env = seqdict()
        subPlanDir = self.getSubplanPath(suite, self.getSubplanName())
        spDir, local = os.path.split(subPlanDir)
        env["SP_ETAB_DIR"] = os.path.join(spDir, "etable")
        lpDir, local = os.path.split(spDir)
        env["LP_ETAB_DIR"] = os.path.join(lpDir, "etable")
        return env        
    def getPerformance(self, statusPath):
        if os.path.isfile(statusPath):
            lastLines = os.popen("tail -10 " + statusPath).xreadlines()
            for line in lastLines:
                if line[0:5] == "Time:":
                    return line.split(":")[1].split("s")[0]
        # Give some default that will not end it up in the short queue
        return "2500"
    def getOptions(self, suite):
        subplan = self.getSubplanName()
        ruleset = self.findRuleset(suite, subplan)
        application = self.getApplication(suite)
        return self.buildOptions(subplan, ruleset, application)
    def getApplication(self, suite):
        application = suite.app.name
        if application == "cs":
            return "FANDANGO"
        else:
            return "APC"
    def buildOptions(self, subplan, ruleSet, application):
        path = os.path.join("$CARMUSR", "LOCAL_PLAN", subplan, "APC_FILES")
        statusFile = os.path.join(path, "run_status")
        ruleSetPath = os.path.join("${CARMTMP}", "crc", "rule_set", application, "PUTS_ARCH_HERE")
        ruleSetFile = os.path.join(ruleSetPath, ruleSet)
        return path + " " + statusFile + " ${CARMSYS} " + ruleSetFile + " ${USER}"

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

class CVSBranchTests(plugins.Action):
    def __init__(self, args = []):
        if not len(args) == 1:
            raise plugins.TextTestError, "CVSBranchTests accepts exactly one argument (version)"
        self.version = args[0]
    def __repr__(self):
        return "CVS Branch test for"
    def __call__(self, test):
        interestingFiles = ["status","error","memory","performance","solution","warnings"]
        for file in interestingFiles:
            fullFileName = test.makeFileName(file)
            if not os.path.isfile(fullFileName):
                continue
            fullFileNameNewVersion = fullFileName + "." + self.version
            if os.path.isfile(fullFileNameNewVersion):
                self.describe(test, ": version " + self.version + " already exists of " + file)
                continue
            stdin, stdout, stderr = os.popen3("cvs -q upd " + fullFileName)
            lines = stdout.readlines()
            if lines:
                for line in lines:
                    if line[0] == "M":
                        self.describe(test, ": creating version " + self.version + " of " + file)
                        os.system("cvs -q upd -p " + fullFileName + " > " + fullFileNameNewVersion)
                        os.system("cvs add " + fullFileNameNewVersion)
                
                
class CleanSubplans(plugins.Action):
    def __init__(self):
        self.config = ApcConfig(None)
        self.user = os.environ["USER"]
        self.cleanedPlans = 0
        self.totalMem = 0
        self.timeToRemove = time.time()-30*24*3600
    def __del__(self):
        print "Removed ", self.cleanedPlans, " temporary subplan directories (" + str(self.totalMem/1024) + "M)"
    def __repr__(self):
        return "Cleaning subplans for"
    def __call__(self, test):
        subplan = self.config._getSubPlanDirName(test)
        localplan, subdir = os.path.split(subplan)
        searchStr = subdir + "." + test.app.name
        cleanedPlansTest = 0
        usedMem = 0
        for file in os.listdir(localplan):
            startsubplan = file.find(searchStr)
            if startsubplan == -1:
                continue
            if file.find(self.user, startsubplan + len(searchStr)) != -1:
                subplanName = os.path.join(localplan, file)
                fileTime = os.path.getmtime(subplanName)
                if fileTime > self.timeToRemove:
                    print "Not removing due to too new time stamp " + time.ctime(fileTime)
                    continue
                cleanedPlansTest += 1
                usedMem += int(os.popen("du -s " + subplanName).readlines()[0].split("\t")[0])
                try:
                    shutil.rmtree(subplanName)
                except OSError:
                    print "Failed to remove subplan", subplanName
        self.describe(test, " (" + str(cleanedPlansTest) + ", " +  str(usedMem/1024) + "M)")
        self.cleanedPlans += cleanedPlansTest
        self.totalMem += usedMem
    def setUpSuite(self, suite):
        self.describe(suite)


class SaveBestSolution(guiplugins.InteractiveAction):
    def __call__(self, test):
        import shutil
        # If we have the possibility to save, we know that the current solution is best
        testdir = self.test.parent.getDirectory(1)
        bestStatusFile = os.path.join(testdir, self.hostCaseName, "best_known_status");
        currentStatusFile = self.test.makeFileName("status", temporary=1)
        shutil.copyfile(currentStatusFile, bestStatusFile)

        bestSolFile = os.path.join(testdir, self.hostCaseName, "best_known_solution");
        currentSolFile = self.test.makeFileName("solution", temporary=1)
        shutil.copyfile(currentSolFile, bestSolFile)
        
    def getTitle(self):
        return "Save best"

    def solutionIsBetter(self):
        parentDir = self.test.parent.getDirectory(1)
        bestStatusFile = os.path.join(parentDir, self.hostCaseName, "best_known_status");
        statusFile = self.test.makeFileName("status", temporary=1)
        if not os.path.isfile(statusFile):
            return 0
        solutionFile = self.test.makeFileName("solution", temporary=1)
        if not os.path.isfile(solutionFile):
            return 0
        # read solutions
        items = ['uncovered legs', 'illegal pairings', 'overcovers', 'cost of plan', 'cpu time']
        itemNames = {'memory': 'Time:.*memory', 'cost of plan': 'TOTAL cost', 'new solution': 'apc_status Solution', 'illegal pairings':'illegal trips', 'uncovered legs':'uncovered legs\.', 'overcovers':'overcovers'}
        calc = optimization.OptimizationValueCalculator(items, statusFile, itemNames, []);
        sol=calc.getSolutions(items)
        if len(sol) == 0 :
            return 0
        if not os.path.isfile(bestStatusFile):
            return 1
        calcBestKnown = optimization.OptimizationValueCalculator(items, bestStatusFile, itemNames, []);
        solBest=calcBestKnown.getSolutions(items)
        #Check the 4 first items
        for i in range(4):
            if sol[-1][items[i]] < solBest[-1][items[i]]:
                return 1
            if sol[-1][items[i]] > solBest[-1][items[i]]:
                return 0
        #all equal
        return 0
        
    def canPerformOnTest(self):
        self.kpiGroupForTest, self.kpiGroups = readKPIGroupFileCommon(self.test.parent)
        if not self.kpiGroupForTest.has_key(self.test.name):
            self.hostCaseName = self.test.name
        else:
            self.hostCaseName = self.findFirstInKPIGroup()
        return self.solutionIsBetter()

    def findFirstInKPIGroup(self):
        gp=self.kpiGroupForTest[self.test.name]
        tests = filter(lambda x:self.kpiGroupForTest[x] == gp, self.kpiGroupForTest.keys())
        tests.sort()
        return tests[0]

guiplugins.interactiveActionHandler.testClasses.append(SaveBestSolution)
