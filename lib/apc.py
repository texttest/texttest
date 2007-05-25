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
             - valgrind
               Run valgrind on the problem 
             - val_output=<filename>
               Dump valgrinds output in the file <filename>.pid
             - valdebug
               Instruct valgrind to attach to a debugger when encountering
               a memory problem. Note that this option means that output will
               not be redirected.
-goprof <options>
           - (only APC) Applies the Google profiler to the test, output is a profile file including
              both a flat and call graph profile, and profiledata that contains the rawdata for
              further processing. It is assumed that that binary that is supposed to be profiled
              is linked against the profile library, see also exppreload.
              - exppreload
                Experimental preload of profile library in order to avoid linking.
               
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
                             
apc.PlotKPIGroups          - A specialization of optimization.PlotTest for APC where the main feature is that tests grouped
                             in an KPI group is plotted in one window, and that one get a window per KPI group.
                             See optimization.PlotTest for details and options, this script takes all the options
                             that PlotTest supports, do however note that some of the options doesn't make sense
                             to use for several KPI groups, for example, p, print to file.

"""

import default, ravebased, queuesystem, performance, os, copy, sys, stat, string, shutil, KPI, optimization, plugins, math, filecmp, re, popen2, unixonly, guiplugins, exceptions, time, testmodel, testoverview, subprocess
from jobprocess import JobProcess
from socket import gethostname
from time import sleep
from ndict import seqdict
from tempfile import mktemp
from carmenqueuesystem import getArchitecture, getMajorReleaseVersion, RunWithParallelAction
from comparetest import ProgressTestComparison

def readKPIGroupFileCommon(suite):
    kpiGroupForTest = {}
    kpiGroups = []
    kpiGroupsScale = {}
    kpiGroupsFileName = suite.getFileName("kpi_groups")
    if not kpiGroupsFileName:
        return {}, [], {}
    groupFile = open(kpiGroupsFileName)
    groupName = None
    groupScale = None
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
            if not kpiGroupsScale.has_key(groupKey):
                kpiGroupsScale[groupKey] = groupScale
        else:
            gk = groupKey.split("_")
            kpigroup = gk[0]
            item = gk[1]
            if item == "name":
                groupName = groupValue
            if item == "percscale":
                groupScale = groupValue
    groupFile.close()
    return kpiGroupForTest, kpiGroups, kpiGroupsScale

def getConfig(optionMap):
    return ApcConfig(optionMap)

class ApcConfig(optimization.OptimizationConfig):
    def addToOptionGroups(self, app, groups):
        optimization.OptimizationConfig.addToOptionGroups(self, app, groups)
        for group in groups:
            if group.name.startswith("Basic"):
                group.addOption("rundebug", "Run debugger")
                group.addOption("extractlogs", "Extract Apc Logs")
                group.addOption("goprof", "Run with the Google profiler")
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
    def getSlaveSwitches(self):
        return optimization.OptimizationConfig.getSlaveSwitches(self) + [ "rundebug", "extractlogs", "goprof" ]
    def useQueueSystem(self):
        if self.optionMap.has_key("rundebug"):
            return 0
        return optimization.OptimizationConfig.useQueueSystem(self)
    def getProgressReportBuilder(self):
        if self.optionMap.has_key("prrepgraphical"):
            return MakeProgressReportGraphical(self.optionValue("prrep"))
        elif self.optionMap.has_key("prrephtml"):
            return MakeProgressReportHTML(self.optionValue("prrep"), self.optionValue("prrephtml"))
        else:
            return MakeProgressReport(self.optionValue("prrep"))
    def getTestRunner(self):
        runners = []
        if self.optionMap.has_key("goprof"):
            runners.append(GoogleProfilePrepare(self.optionMap["goprof"]))
        runners += [ CheckFilesForApc(), self._getApcTestRunner() ]
        return runners
    def _getApcTestRunner(self):
        if self.optionMap.has_key("rundebug"):
            return RunApcTestInDebugger(self.optionValue("rundebug"), self.optionMap.has_key("keeptmp"))
        else:
            baseRunner = optimization.OptimizationConfig.getTestRunner(self)
            if self.slaveRun():
                return MarkApcLogDir(baseRunner, self.isExecutable, self.optionMap.has_key("extractlogs"))
            else:
                return baseRunner
    def isExecutable(self, process, parentProcess, test):
        # Process name starts with a dot and may be truncated or have
        # extra junk at the end added by APCbatch.sh
        processData = process[1:]
        rulesetName = self.getRuleSetNames(test)[0]
        return processData.startswith(rulesetName) or rulesetName.startswith(processData)
    def getFileExtractor(self):
        baseExtractor = optimization.OptimizationConfig.getFileExtractor(self)
        subActions = [ baseExtractor, CreateHTMLFiles(), FetchApcCore() ]
        if self.optionMap.has_key("goprof"):
            subActions.append(GoogleProfileExtract())
        if self.slaveRun():
            useExtractLogs = self.optionValue("extractlogs")
            if useExtractLogs == "":
                useExtractLogs = "all"
            subActions.append(ExtractApcLogs(useExtractLogs, self.optionMap.has_key("keeptmp")))
        return subActions
    def getProgressComparisonClass(self):
        return ApcProgressTestComparison
    def getStatusFilePath(self, test):
        rawStatusFile = test.getWordsInFile("options")[1]
        carmdataVar, carmdata = ravebased.getCarmdata(test)
        statusFile = rawStatusFile.replace("$" + carmdataVar, carmdata).replace("${" + carmdataVar + "}", carmdata)
        return os.path.normpath(statusFile)
    def _getSubPlanDirName(self, test):
        statusFile = self.getStatusFilePath(test)
        dirs = statusFile.split(os.sep)[:-2]
        return os.path.normpath(string.join(dirs, os.sep))
    def _getRuleSetNames(self, test):
        for option in test.getWordsInFile("options"):
            if option.find("crc" + os.sep + "rule_set") != -1:
                return [ os.path.basename(option) ]
        return []
    def ensureDebugLibrariesExist(self, app):
        libraries = [ ("data/crc", "librave_rts.a", "librave_rts_g.a"),
                      ("data/crc", "librave_private.a", "librave_private_g.a"),
                      ("lib", "libDMFramework.so", "libDMFramework_g.so"),
                      ("lib", "libBasics_Foundation.so", "libBasics_Foundation_g.so"),
                      ("lib", "libBasics_errlog.so", "libBasics_errlog_g.so")]
        for libpath, orig, debug in libraries:
            debugLib = os.path.join(os.environ["CARMSYS"], libpath, getArchitecture(app), debug)
            if not os.path.exists(debugLib):
                origLib = os.path.join(os.environ["CARMSYS"], libpath, getArchitecture(app), orig)
                os.symlink(origLib, debugLib)
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
        self.itemNamesInFile[optimization.timeEntryName] = "cpu time|cpu-tid|cpu-zeit"
        self.itemNamesInFile[optimization.costEntryName] = "TOTAL cost"
        if app.name == "cas_apc":
            self.itemNamesInFile[optimization.costEntryName] = "rule cost"
        self.itemNamesInFile[optimization.newSolutionMarker] = "apc_status Solution"
        app.setConfigDefault("link_libs", "")
        app.setConfigDefault("extract_logs", {})
        app.setConfigDefault("apcinfo", {})
        app.setConfigDefault("quit_ask_for_confirm", -1)
        app.setConfigDefault("xml_script_file", "bin/APCcreatexml.sh", "")
        app.setConfigDefault("optinfo_xml_file", "data/apc/feedback/optinfo_html_xsl.xml", "")
        app.addConfigEntry("select_kpi_group", "<control>k", "gui_accelerators")
    def getDefaultCollations(self):
        return { "stacktrace" : "apc_tmp_dir/core*" }

class CheckFilesForApc(plugins.Action):
    def __call__(self, test):
        # A hack to get around that the etable reading doesn't work 100%.
        try:
            verifyAirportFile(getArchitecture(test.app))
        except TypeError:
            print "Failed to find AirportFile in etables. Not verifying airportFile."
        verifyLogFileDir(getArchitecture(test.app))
        os.environ["TEXTTEST_TEST_RELPATH"] = test.getRelPath()

def verifyAirportFile(arch):
    diag = plugins.getDiagnostics("APC airport")
    etabPath = os.path.join(os.environ["CARMUSR"], "Resources", "CarmResources")
    customerEtab = os.path.join(etabPath, "Customer.etab")
    if os.path.isfile(customerEtab):
        diag.info("Reading etable at " + customerEtab)
        etab = ConfigEtable(customerEtab)
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
                plugins.ensureDirExistsForFile(airportFile)
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

class ApcProgressTestComparison(ProgressTestComparison):
    def computeFor(self, test):
        self.makeComparisons(test)
        self.categorise()
        self.freeText += "\n" + self.runStatusInfo(test)
        test.changeState(self)
        
    def runStatusInfo(self, test):
        runStatusHeadFile = test.makeTmpFileName("APC_FILES/run_status_head")
        if os.path.isfile(runStatusHeadFile):
            try:
                return open(runStatusHeadFile).read()
            except (OSError,IOError):
                return "Error opening/reading " + runStatusHeadFile                 
        else:
            return "Run status file is not available yet."
        

class ViewApcLog(guiplugins.InteractiveTestAction):
    def __repr__(self):
        return "Viewing log of"
    def performOnCurrent(self):
        viewLogScript = self.currentTest.makeTmpFileName("view_apc_log", forFramework=1)
        if os.path.isfile(viewLogScript):
            file = open(viewLogScript)
            cmdArgs = eval(file.readlines()[0].strip())
            file.close()
            process = self.startViewer(cmdArgs, "APC log viewer")
            guiplugins.scriptEngine.monitorProcess("views the APC log", process)
        else:
            raise plugins.TextTestError, "APC log file not yet available"
    def _getTitle(self):
        return "View APC Log"

#
# Runs the test in gdb and displays the log file. 
#
class RunApcTestInDebugger(default.RunTest):
    def __init__(self, options, keepTmpFiles):
        default.RunTest.__init__(self)
        self.process = None
        self.inXEmacs = None
        self.runPlain = None
        self.runValgrind = None
        self.showLogFile = 1
        self.noRun = None
        self.keepTmps = keepTmpFiles;
        self.valOutput = None
        opts = options.split(" ")
        if opts[0] == "":
            return
        self.valopt = ""
        for opt in opts:
            if opt == "xemacs":
                self.inXEmacs = 1
            elif opt == "nolog":
                self.showLogFile = None
            elif opt == "plain":
                self.runPlain = 1
            elif opt == "norun":
                self.noRun = 1
            elif opt == "valgrind":
                self.runValgrind = 1
            elif opt.find("val_output=")==0:
                tmp = opt.split("=")
                self.valOutput = tmp[1]
                self.valopt += "--log-file=" + self.valOutput + " "
            elif opt == "valdebug":
                self.valopt += "--db-attach=yes "

            else:
                print "Ignoring unknown option " + opt
    def __repr__(self):
        return "Debugging"
    def __del__(self):
        # .nfs lock files are left if we don't kill the less process.
        if self.process:
            JobProcess(self.process.pid).killAll()
    def __call__(self, test):
        os.chdir(test.getDirectory()) # for backwards compatibility with when this was done by default...
        self.describe(test)
        # Get the options that are sent to APCbatch.sh
        opts = test.getWordsInFile("options")
        # Create and show the log file.
        apcLog = test.makeTmpFileName("apclog")
        apcLogFile = open(apcLog, "w")
        apcLogFile.write("")
        apcLogFile.close()
        if self.showLogFile:
            cmdArgs = [ "xterm", "-bg", "white", "-fg", "black", "-T", "APCLOG-" + test.name, "-e", "less +F " + apcLog ]
            self.process = subprocess.Popen(cmdArgs)
            print "Created process : log file viewer :", self.process.pid
        # Create a script for gdb to run.
        gdbArgs = test.makeTmpFileName("gdb_args")
        gdbArgsFile = open(gdbArgs, "w")
        gdbArgsFile.write("set pagination off" + os.linesep)
        gdbArgsFile.write(os.path.expandvars("set args -D -v1 -S " + opts[0] + " -I " + opts[1] + " -U " + opts[-1] + " >& " + apcLog + os.linesep))
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
        out = test.makeTmpFileName("output")
        outFile = open(out, "w")
        outFile.write("SUBPLAN " + opts[0] + os.linesep)
        outFile.close()
        # Create execute command.
        binName = os.path.expandvars(opts[-2].replace("PUTS_ARCH_HERE", getArchitecture(test.app)))
        if test.app.configObject.target.raveMode() == "-debug":
            binName += "_g"
        if self.inXEmacs:
            gdbStart, gdbWithArgs = self.runInXEmacs(test, binName, gdbArgs)
            executeCommand = "xemacs -l " + gdbStart + " -f gdbwargs"
        elif self.runPlain:
            executeCommand = binName + " -D -v1 -S " + opts[0] + " -I " + opts[1] + " -U " + opts[-1] + " > " + apcLog
        elif self.runValgrind:
            #no redirecting output when attaching to debugger
            redir = " >& " + apcLog
            if self.valopt.find("db-attach") != -1:
                redir = "";
            executeCommand = "valgrind --tool=memcheck -v " + self.valopt + binName + " -D -v1 -S " + opts[0] + " -I " + opts[1] + " -U " + opts[-1] + redir
        else:
            # I set the SHELL to be sh since if csh or tcsh is used, an init file is loaded
            # that executes "stty erase". This command hangs due to that it gets the signal SIGTOOU.
            # On the other hand, with sh, something weird happens when running with the GUI, gdb
            # don't end sucessfully. This might be due to that it's not run in the main thread.
            # It works fine when texttest is run in console mode. The problem might be related to
            # bugzilla 1659! :-)
            executeCommand = "SHELL=/bin/sh; gdb " + binName + " -silent -x " + gdbArgs
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
        # Valgrind adds a .pid in the end of the output file, this makes texttest
        # not extract the file. Now we simply change it back. In later versions of
        # valgrind, there is an --log-file-exact, we shall remove this code and use
        # that alternative when it becomes available.
        if self.valOutput:
            files = os.listdir(".")
            for file in files:
                if file.startswith(self.valOutput):
                    os.rename(file, self.valOutput + "." + test.app.name)
    def runInXEmacs(self, test, binName, gdbArgs):
        gdbStart = test.makeTmpFileName("gdb_start")
        gdbWithArgs = test.makeTmpFileName("gdb_w_args")
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
    
class FetchApcCore(default.CollateFiles):
    def extract(self, sourceFile, targetFile, collationErrFile):
        if not os.path.basename(targetFile).startswith("stacktrace") or self.extractCore():
            default.CollateFiles.extract(self, sourceFile, targetFile, collationErrFile)
    def isApcLogFileKept(self, errorFileName):
        for line in open(errorFileName).xreadlines():
            if line.find("*** Keeping the logfiles in") != -1:
                return True
        return False
    def extractCore(self):
        scriptErrorsFileName = "APC_FILES/run_status_script_error"
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
        debugFile = "apc_tmp_dir/apc_debug"
        # Check if there is a apc_debug file.
        if os.path.isfile(debugFile):
            self.diag.info("apc_debug file is found. Aborting.")
            return 0
        return 1

class CreateHTMLFiles(plugins.Action):
    def __call__(self, test):
        subplanPath = os.path.realpath(test.makeTmpFileName("APC_FILES", forComparison=0))
        xmlFile = os.path.join(subplanPath, "optinfo.xml")
        if os.path.isfile(xmlFile):
            carmsys = os.environ["CARMSYS"]
            scriptFile = os.path.join(carmsys, test.app.getConfigValue("xml_script_file"))
            runStatusFiles = os.path.join(subplanPath, "run_status")
            xmlAllFile = os.path.join(subplanPath, "optinfo_all.xml")
            os.system(scriptFile + " " + runStatusFiles + " " + xmlFile + " " + xmlAllFile)
            htmlFile = test.makeTmpFileName("optinfo")
            xslFile = os.path.join(carmsys, test.app.getConfigValue("optinfo_xml_file"))
            majorRelease = getMajorReleaseVersion(test.app)
            if majorRelease == "master":
                xsltprocArchs = [ "i386_linux", "x86_64_linux", "sparc", "sparc_64" ]
            else:
                xsltprocArchs = [ "i386_linux", "x86_64_linux" ]
            arch = getArchitecture(test.app)
            if arch in xsltprocArchs:
                os.system("xsltproc " + xslFile + " " + xmlAllFile + " > " + htmlFile)
            else:
                os.system("Xalan " + xmlAllFile + " " + xslFile + " > " + htmlFile)
            # Create links to the images dir, so we get the pics when looking
            # in mozilla.
            imagesDir = os.path.join(carmsys, "data/apc/feedback/images/")
            os.system("ln -s " + imagesDir)
            os.system("cd framework_tmp; ln -s " + imagesDir)

class GoogleProfilePrepare(plugins.Action):
    def __init__(self, arg):
        self.arg = arg
    def __call__(self, test):
        os.environ["LD_LIBRARY_PATH"] += ";/users/johani/lib/"
        os.environ["CPUPROFILE"] = test.makeTmpFileName("profiledata", forFramework=0)
        if self.arg.startswith("exppreload"):
            os.environ["LD_PRELOAD"] = "/users/johani/lib/libprofiler.so"


class GoogleProfileExtract(plugins.Action):
    def __call__(self, test):
        datafile = test.makeTmpFileName("profiledata", forFramework=0)
        profilefile = test.makeTmpFileName("profile", forFramework=0)
        opts = test.getWordsInFile("options")
        binName = os.path.expandvars(opts[-2].replace("PUTS_ARCH_HERE", getArchitecture(test.app)))
        command = "/users/johani/bin/pprof --text " + binName + " " + datafile + " > " + profilefile
        # Have to make sure it runs on a 32-bit machine.
        os.system("rsh abbeville \"" + command + "\"")
        
class MarkApcLogDir(RunWithParallelAction):
    def __init__(self, baseRunner, isExecutable, keepLogs):
        RunWithParallelAction.__init__(self, baseRunner, isExecutable)
        self.keepLogs = keepLogs
    def getApcHostTmp(self):
        configFile = os.path.join(os.environ["CARMSYS"],"CONFIG")
        resLine = os.popen(". " + configFile + "; echo ${APC_TEMP_DIR}").readlines()[-1].strip()
        if resLine.find("/") != -1:
            return resLine
        return "/tmp"
    def getApcLogDir(self, test, pid = None):
        # Logfile dir
        subplanPath = os.path.realpath(test.makeTmpFileName("APC_FILES", forComparison=0))
        subplanName, apcFiles = os.path.split(subplanPath)
        baseSubPlan = os.path.basename(subplanName)
        apcHostTmp = self.getApcHostTmp()
        if pid:
            logdir = os.path.join(apcHostTmp, baseSubPlan + "_" + gethostname() + "_" + pid)
            if os.path.isdir(logdir):
                return logdir
            # maintain backward compatibility with the old APCbatch.sh (v1.38)
            # collision prone naming scheme
            return os.path.join(apcHostTmp, baseSubPlan + "_" + pid)
        # Hmmm the code below might return something that doesn't "belong" to us
        for file in os.listdir(apcHostTmp):
            if file.startswith(baseSubPlan + "_"):
                return os.path.join(apcHostTmp, file)
    def handleNoTimeAvailable(self, test):
        # We try to pick out the log directory, at least
        apcLogDir = self.getApcLogDir(test)
        if apcLogDir:
            self.makeLinks(test, apcLogDir)
    def makeLinks(self, test, apcTmpDir):
        linkTarget = test.makeTmpFileName("apc_tmp_dir", forComparison=0)
        try:
            os.symlink(apcTmpDir, linkTarget)
        except OSError:
            print "Failed to create apc_tmp_dir link"
            
        viewLogScript = test.makeTmpFileName("view_apc_log", forFramework=1)
        file = open(viewLogScript, "w")
        logFileName = os.path.join(apcTmpDir, "apclog")
        cmdArgs = [ "xon", gethostname(), "xterm -bg white -T " + test.name + " -e \"less +F " + logFileName + "\"" ]
        file.write(repr(cmdArgs))
        file.close()
    def performParallelAction(self, test, execProcess, parentProcess):
        apcTmpDir = self.getApcLogDir(test, str(parentProcess.pid))
        self.diag.info("APC log directory is " + apcTmpDir + " based on process " + parentProcess.getName())
        if not os.path.isdir(apcTmpDir):
            raise plugins.TextTestError, "ERROR : " + apcTmpDir + " does not exist - running process " + execProcess.getName()
        self.makeLinks(test, apcTmpDir)
        self.describe(test)
        if self.keepLogs:
            fileName = os.path.join(apcTmpDir, "apc_debug")
            file = open(fileName, "w")
            file.close()

class ExtractApcLogs(plugins.Action):
    def __init__(self, args, keepTmp):
        self.diag = plugins.getDiagnostics("ExtractApcLogs")
        self.args = args
        self.keepTmp = keepTmp
        if not self.args:
            print "No argument given, using default value for extract_logs"
            self.args = "default"
    def __call__(self, test):
        if os.getenv("DONTEXTRACTAPCLOG"):
            self.diag.info("Environment DONTEXTRACTAPCLOG is set, not extracting.")
            return
        apcTmpDir = test.makeTmpFileName("apc_tmp_dir", forComparison=0)
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
        extractToFile = test.makeTmpFileName(saveName)
        cmdLine = "cd " + apcTmpDir + "; " + extractCommand + " > " + extractToFile
        os.system(cmdLine)
        # We sometimes have problems with an empty file extracted.
        if os.stat(extractToFile)[stat.ST_SIZE] == 0:
            os.remove(extractToFile)
        # Extract mpatrol files, if they are present.
        if os.path.isfile(os.path.join(apcTmpDir, "mpatrol.out")):
            cmdLine = "cd " + apcTmpDir + "; " + "cat mpatrol.out" + " > " + test.makeTmpFileName("mpatrol_out")
            os.system(cmdLine)
        if os.path.isfile(os.path.join(apcTmpDir, "mpatrol.log")):
            cmdLine = "cd " + apcTmpDir + "; " + "cat mpatrol.log" + " > " + test.makeTmpFileName("mpatrol_log")
            os.system(cmdLine)
        # Extract scprob prototype...
        #if os.path.isfile(os.path.join(apcTmpDir, "APC_rot.scprob")):
        #    cmdLine = "cd " + apcTmpDir + "; " + "cat  APC_rot.scprob" + " > " + test.makeFileName(" APC_rot.scprob", temporary = 1)
        #    os.system(cmdLine)
        
        # When apc_debug is present, we want to remove the error file
        # (which was created because we are keeping the logfiles,
        # with the message "*** Keeping the logfiles in $APC_TEMP_DIR ***"),
        # otherwise the test is flagged failed.
        if os.path.isfile(os.path.join(apcTmpDir, "apc_debug")):
            errFile = test.makeTmpFileName("script_errors")
            if os.path.isfile(errFile):
                os.remove(errFile)
        if self.keepTmp:
            apcTmpDirStored = test.makeTmpFileName("apc_tmp", forComparison=0)
            shutil.copytree(apcTmpDir, apcTmpDirStored) 
        # Remove dir
        plugins.rmtree(apcTmpDir)
    def __repr__(self):
        return "Extracting APC logfile for"
    def getInterruptActions(self, fetchResults):
        return []

class SaveTests(guiplugins.SaveTests):
    def diagnosticMode(self, apps):
        return guiplugins.SaveTests.diagnosticMode(self, apps) or apps[0].inputOptions.has_key("extractlogs")

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
        kpiGroups = suite.getFileName("kpi_groups")
        if not kpiGroups:
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

class ImportTestSuite(ravebased.ImportTestSuite):
    def getCarmtmpDirName(self, carmUsr):
        return ravebased.ImportTestSuite.getCarmtmpDirName(self, carmUsr) + ".apc"
    
# Graphical import
class ImportTestCase(optimization.ImportTestCase):
    def __init__(self):
        optimization.ImportTestCase.__init__(self)
        self.addOption("perm", "Import KPI group permutations", "aan,aat,adn,adt,dan,dat,ddn,ddt",
                       possibleValues = ["aan,aat,adn,adt"])
        self.addSwitch("kpi", "Import KPI group", 0)
        self.perm = ""
    def performOnCurrent(self):
        if not self.optionGroup.getSwitchValue("kpi"):
            optimization.ImportTestCase.performOnCurrent(self)
        else:
            self.importKPIGroup()
    def importKPIGroup(self):
        testNameSteam = self.getNewTestName()
        permutations = self.optionGroup.getOptionValue("perm").split(",")
        testNames = []
        suite = self.getDestinationSuite()
        for perm in permutations:
            testNames.append(testNameSteam + "_" + perm)
            self.checkName(suite, testNames[-1])
        # Two loops since I don't want to import half of the tests
        # and then get a failure from CheckName.
        isFirst = True
        for newTestName in testNames:
            if isFirst:
                placement = self.getPlacement()
                description = self.optionGroup.getOptionValue("desc")
                isFirst = False
            self.perm = "_" + newTestName.split("_")[-1]
            testDir = suite.writeNewTest(newTestName, description, placement)
            self.testImported = self.createTestContents(suite, testDir, description, placement)
            description = ""
            placement += 1
    def getSubplanName(self):
        return optimization.ImportTestCase.getSubplanName(self) + self.perm
    def getSubplanPath(self, carmdata):
        return os.path.join(carmdata, "LOCAL_PLAN", self.getSubplanName())
    def findRuleset(self, carmdata):
        subplanPath = self.getSubplanPath(carmdata)
        return self.getRuleSetName(subplanPath)
    # copied from TestCaseInformation...
    def getRuleSetName(self, absSubPlanDir):
        problemPath = os.path.join(absSubPlanDir, "APC_FILES", "problems")
        if not self.isCompressed(problemPath):
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
    def isCompressed(self, path):
        if os.path.getsize(path) == 0:
            return False
        magic = open(path).read(2)
        if magic[0] == chr(0x1f) and magic[1] == chr(0x9d):
            return True
        else:
            return False
    def writeResultsFiles(self, suite, testDir):
        carmdataVar, carmdata = ravebased.getCarmdata(suite)
        subPlanDir = self.getSubplanPath(carmdata)

        collationFiles = suite.app.getConfigValue("collate_file")
        for ttStem, relPath in collationFiles.items():
            origFile = os.path.join(subPlanDir, relPath)
            if os.path.isfile(origFile):
                newFile = os.path.join(testDir, ttStem + "." + suite.app.name)
                if not os.path.isfile(newFile):
                    shutil.copyfile(origFile, newFile)
        perf = self.getPerformance(os.path.join(testDir, "status." + suite.app.name))
        perfFile = self.getWriteFile("performance", suite, testDir)
        perfFile.write("CPU time   :     " + str(int(perf)) + ".0 sec. on tiptonville" + os.linesep)
        perfFile.close()
    def getEnvironment(self, suite):
        env = seqdict()
        carmdataVar, carmdata = ravebased.getCarmdata(suite)
        spDir = self.getSubplanPath(carmdata)
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
        carmdataVar, carmdata = ravebased.getCarmdata(suite)
        subplan = self.getSubplanName()
        ruleset = self.findRuleset(carmdata)
        application = self.getApplication(suite)
        return self.buildOptions(carmdataVar, subplan, ruleset, application)
    def getApplication(self, suite):
        application = suite.app.name
        if application == "cs":
            return "FANDANGO"
        else:
            return "APC"
    def buildOptions(self, carmdataVar, subplan, ruleSet, application):
        path = os.path.join("$" + carmdataVar, "LOCAL_PLAN", subplan, "APC_FILES")
        statusFile = os.path.join(path, "run_status")
        ruleSetPath = os.path.join("${CARMTMP}", "crc", "rule_set", application, "PUTS_ARCH_HERE")
        ruleSetFile = os.path.join(ruleSetPath, ruleSet)
        return path + " " + statusFile + " ${CARMSYS} " + ruleSetFile + " ${USER}"

class PortApcTest(plugins.Action):
    def __repr__(self):
        return "Porting old"
    def __call__(self, test):
        testInfo = ApcTestCaseInformation(self.suite, test.name)
        hasPorted = 0
        opts = test.getWordsInFile("options")
        if opts[0].startswith("-"):
            hasPorted = 1
            subPlanDirectory = opts[3]
            carmUsrSubPlanDirectory = testInfo.replaceCarmUsr(subPlanDirectory)
            ruleSetName = testInfo.getRuleSetName(subPlanDirectory)
            newOptions = testInfo.buildOptions(carmUsrSubPlanDirectory, ruleSetName)
            fileName = test.getFileName("options")
            shutil.copyfile(fileName, fileName + ".oldts")
            os.remove(fileName)
            optionFile = open(fileName,"w")
            optionFile.write(newOptions + "\n")
        else:
            subPlanDirectory = opts[0]
            carmUsrSubPlanDirectory = testInfo.replaceCarmUsr(subPlanDirectory)
        envFileName = test.getFileName("environment")
        if not os.path.isfile(envFileName):
            hasPorted = 1
            envContent = testInfo.buildEnvironment(carmUsrSubPlanDirectory)
            open(envFileName,"w").write(envContent + os.linesep)
        perfFileName = test.getFileName("performance")
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
            etab = ConfigEtable(customerEtab)
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
        return test.getFileName(self.statusFileName, version)
    def getPerformanceFile(self, test, version):
        return test.getFileName("performance", version)
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
            oldFile = suite.getFileName("environment")
            if not oldFile:
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
        interestingFiles = ["status","error","memory","performance","solution","warnings", "optinfo"]
        for file in interestingFiles:
            fullFileName = test.getFileName(file)
            if not fullFileName:
                continue
            fullFileNameNewVersion = test.getDirectory() + os.sep + file + "." + test.app.name + "." + self.version
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

class CopyMPSFiles(plugins.Action):
    def __init__(self, args):
        self.destination = args[0]
        if not os.path.isdir(self.destination):
            raise plugins.TextTestError, "Destination directory " + self.destination + " does not exist."
        self.cnt = 0
    def __repr__(self):
        return ""
    def getFileName(self, test):
        self.cnt += 1
        return os.path.join(self.destination, "primal_heur_" + str(self.cnt) + ".mps")
    def __call__(self, test):
        fileName = test.getFileName("mps")
        if fileName:
            newFileName = self.getFileName(test)
            print "Copying MPS file for test " + test.name + " to " + newFileName
            shutil.copyfile(fileName, newFileName)
            os.system("gzip " + newFileName)

class CreateSCSolverTestSuite(plugins.Action):
    def __init__(self, args):
        self.source = args[0]
        if not os.path.isdir(self.source):
            raise plugins.TextTestError, "Source directory " + self.source + " does not exist."
        self.newTS = args[1]
        if not os.path.isdir(self.newTS):
            os.makedirs(self.newTS)
        self.testSuiteTree = seqdict()
        self.suffix = ".sc"
    def __del__(self):
        self.writeTestSuiteFiles(self.testSuiteTree, self.newTS)
    def writeTestSuiteFiles(self, parent, dir):
        if len(parent.keys()) == 0:
            return
        testSuiteFile = open(dir + os.sep + "testsuite" + self.suffix, "w+")
        for p in parent.keys():
            testSuiteFile.write(p + os.linesep)
            self.writeTestSuiteFiles(parent[p], os.path.join(dir, p))
        testSuiteFile.close()
    def addToTree(self, parts, parent):
        if not parent.has_key(parts[0]):
            parent[parts[0]] = seqdict()
        if len(parts) >= 2:
            self.addToTree(parts[1:], parent[parts[0]])
    def __call__(self, test):
        relPath = test.getRelPath()
        rotFileDirForTest = os.path.join(self.source, relPath)
        if os.path.isdir(rotFileDirForTest):
            isFirst = True
            for file in os.listdir(rotFileDirForTest):
                if not file.find("APC_rot") == -1:
                    if isFirst:
                        rootTestDir = os.path.join(self.newTS, relPath)
                        if not os.path.isdir(rootTestDir):
                            os.makedirs(rootTestDir)
                        testsuite = []
                        self.addToTree(relPath.split(os.sep), self.testSuiteTree)
                        isFirst = False
                    testName = file.split("_")[0] + "_" + file.split("_")[-1]
                    testsuite.append(testName)
                    testDir = os.path.join(rootTestDir, testName)
                    # We might run this on an already existing testsuite.
                    # If testDir already is there, we assume the test to be created.
                    if not os.path.isdir(testDir):
                        os.mkdir(testDir)
                        optionsFile = open(os.path.join(testDir, "options" + self.suffix), "w+")
                        optionsFile.write("${SCDATA}/" + relPath + "/" + file)
                        optionsFile.close()
            if isFirst == False:
                testsuiteFile = open(os.path.join(rootTestDir, "testsuite" + self.suffix), "w+")
                for t in testsuite:
                    testsuiteFile.write(t + os.linesep)
                testsuiteFile.close()

class SaveBestSolution(guiplugins.InteractiveTestAction):
    def performOnCurrent(self):
        import shutil
        # If we have the possibility to save, we know that the current solution is best
        testdir = self.currentTest.parent.getDirectory(1)
        bestStatusFile = os.path.join(testdir, self.hostCaseName, "best_known_status");
        currentStatusFile = self.currentTest.makeTmpFileName("status")
        shutil.copyfile(currentStatusFile, bestStatusFile)

        bestSolFile = os.path.join(testdir, self.hostCaseName, "best_known_solution");
        currentSolFile = self.currentTest.makeTmpFileName("solution")
        shutil.copyfile(currentSolFile, bestSolFile)
        
    def _getTitle(self):
        return "Save best"

    def solutionIsBetter(self):
        parentDir = self.currentTest.parent.getDirectory(1)
        bestStatusFile = os.path.join(parentDir, self.hostCaseName, "best_known_status");
        statusFile = self.currentTest.makeTmpFileName("status")
        if not os.path.isfile(statusFile):
            return 0
        solutionFile = self.currentTest.makeTmpFileName("solution")
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
        self.kpiGroupForTest, self.kpiGroups, dummy = readKPIGroupFileCommon(self.currentTest.parent)
        if not self.kpiGroupForTest.has_key(self.currentTest.name):
            self.hostCaseName = self.currentTest.name
        else:
            self.hostCaseName = self.findFirstInKPIGroup()
        return self.solutionIsBetter()

    def findFirstInKPIGroup(self):
        gp=self.kpiGroupForTest[self.currentTest.name]
        tests = filter(lambda x:self.kpiGroupForTest[x] == gp, self.kpiGroupForTest.keys())
        tests.sort()
        return tests[0]

# This is the action responsible for selecting a KPI group in the GUI.
class SelectKPIGroup(guiplugins.InteractiveTestAction):
    def __init__(self, dynamic):
        guiplugins.InteractiveTestAction.__init__(self)
    def __repr__(self):
        return "Select KPI group"
    def _getTitle(self):
        return "_Select KPI group"
    def getStockId(self):
        return "index"
    def inButtonBar(self):
        return False
    def inMenuOrToolBar(self):
        return True
    def getTabTitle(self):
        return "KPI group"
    def getGroupTabTitle(self):
        return "Select KPI group"
    def messageBeforePerform(self):
        return "Selecting tests in KPI group..."
    def messageAfterPerform(self):
        return self.message
    def performOnCurrent(self):
        tests = self.getTestsToSelect()
        if tests:
            self.notify("SetTestSelection", tests)
    def getTestsToSelect(self):
        suite = self.currentTest.parent
        kpiGroupForTest, kpiGroups, percscale = readKPIGroupFileCommon(suite)
        if not kpiGroupForTest.has_key(self.currentTest.name):
            self.message = "Test " + self.currentTest.name +  " is not in an KPI group."
            return [ self.currentTest ]

        kpiGroup = kpiGroupForTest[self.currentTest.name]
        tests = filter(lambda test: kpiGroupForTest.get(test.name) == kpiGroup, suite.testcases)
        self.message = "Selected " + str(len(tests)) + " tests in KPI group " + kpiGroup + "."
        return tests

# Specialization of plotting in the GUI for APC
class PlotTestInGUIAPC(optimization.PlotTestInGUI):
    def __init__(self, dynamic):
        optimization.PlotTestInGUI.__init__(self, dynamic)
        self.addSwitch("kpi", "Plot kpi group")
        self.addSwitch("kpiscale", "Use kpi group percentage scale")
    def describeTests(self):
        return str(self.numPlottedTests) + " tests"
    def performOnCurrent(self):
        self.numPlottedTests = 0
        tests, percscale = self.findAllTests()
        for test in tests:
            self.createGUIPlotObjects(test)
            self.numPlottedTests += 1
        if self.optionGroup.getSwitchValue("per") and self.optionGroup.getSwitchValue("kpiscale"):
            if not percscale:
                percscale = "0:2"
            self.testGraph.optionGroup.setOptionValue("yr", percscale)
        self.plotGraph(self.currTestSelection[0].app.writeDirectory)
    def findAllTests(self):
        if not self.optionGroup.getSwitchValue("kpi"):
            return self.currTestSelection, None
        if len(self.currTestSelection) > 1:
            print "Only one test allowed to be selected when plotting KPI group."
            print "Ignoring 'Plot kpi group' setting and plot selected tests."
            return self.currTestSelection, None
        # Plot KPI group
        currentTest = self.currTestSelection[0] # Only one test!
        suite = currentTest.parent
        kpiGroupForTest, kpiGroups, percscale = readKPIGroupFileCommon(suite)
        if not kpiGroupForTest.has_key(currentTest.name):
            print "Test", currentTest.name, "is not in an KPI group."
            return [ currentTest ], None

        kpiGroup = kpiGroupForTest[currentTest.name]
        return filter(lambda test: kpiGroupForTest.get(test.name) == kpiGroup, suite.testcases), percscale[kpiGroup]
                
    def getRunningTmpFile(self, test, logFileStem):
        return test.makeTmpFileName("APC_FILES/" + logFileStem, forComparison=0)
    
class Quit(guiplugins.Quit):
    def __init__(self, dynamic):
        self.dynamic = dynamic
        guiplugins.InteractiveAction.__init__(self)
    def getConfirmationMessage(self):
        if self.dynamic:
            firstApp = guiplugins.guiConfig.apps[0]
            confirmTime = firstApp.getConfigValue("quit_ask_for_confirm")
            if confirmTime >= 0:
                start = plugins.globalStartTime
                now = time.time()
                elapsedTime = (now-start)/60.0
                if  elapsedTime >= confirmTime:
                    return "Tests have been runnning for %d minutes,\n are you sure you want to quit?" % elapsedTime
        return ""

guiplugins.interactiveActionHandler.actionPostClasses += [ PlotTestInGUIAPC, SelectKPIGroup ]
guiplugins.interactiveActionHandler.actionDynamicClasses += [ ViewApcLog, SaveBestSolution ]

# A script that mimics _PlotTest in optimization.py, but that is specialized for
# APC to plot all (selected) KPI groups.
class PlotKPIGroups(plugins.Action):
    def __init__(self, args = []):
        self.argsRem = copy.deepcopy(args)
        self.groupsToPlot = {}
        self.groupScale = {}
        self.timeDivision = None
        for arg in args:
            if arg.find("timediv") != -1:
                self.timeDivision = 1
                self.argsRem.remove(arg)
    def __call__(self, test):
        kpiGroupForTest, kpiGroups, kpiGroupsScale = readKPIGroupFileCommon(test.parent)
        if kpiGroupForTest.has_key(test.name):
            testInGroup = kpiGroupForTest[test.name]
            if not self.groupsToPlot.has_key(testInGroup):
                self.groupsToPlot[testInGroup] = []
            self.groupsToPlot[testInGroup].append(test)
            self.groupScale[testInGroup] = kpiGroupsScale[testInGroup]
    def __del__(self):
        self.allGroups = self.groupsToPlot.keys()
        self.allGroups.sort()
        for group in self.allGroups:
            # Create a test graph
            if not self.timeDivision:
                testGraph = optimization.TestGraph()
            else:
                testGraph = TestGraphTimeDiv()
            testGraph.readCommandLine(self.argsRem)
            testGraph.optionGroup.setValue("title", "APC user " + self.groupsToPlot[group][0].getRelPath().split(os.sep)[0] + " - KPI group " + group)
            if testGraph.optionGroup.getSwitchValue("per") and self.groupScale[group]:
                testGraph.optionGroup.setValue("yr", self.groupScale[group])
            self.setExtraOptions(testGraph.optionGroup, group)
            for test in self.groupsToPlot[group]:
                testGraph.createPlotObjectsForTest(test)
            testGraph.plot(test.app.writeDirectory)
        print "Plotted", len(self.groupsToPlot.keys()), "KPI groups."
    def setExtraOptions(self, group, average):
        pass

class TestGraphTimeDiv(optimization.TestGraph):
    def __init__(self):
        optimization.TestGraph.__init__(self)
        self.groupTimes = seqdict()
        self.numTests = {}
    def plot(self, writeDir):
        engineOpt = self.optionGroup.getOptionValue("engine")
        if engineOpt == "mpl" and mplDefined:
            engine = PlotEngineMPLTimeDiv(self)
        else:
            raise plugins.TextTestError, "Only plot engine matplotlib supports time division - aborting plotting."
        return engine.plot(writeDir)
    def createPlotObjects(self, lineName, version, logFile, test, scaling):
        identifier = ""
        if version:
            identifier += version
        if lineName:
            if identifier:
                identifier += "."
            identifier += lineName
        if not identifier:
            identifier = "std result"
        times = self.extractColgenData(test.app, logFile)
        if not self.groupTimes.has_key(identifier):
            self.groupTimes[identifier] = times
            self.numTests[identifier] = 1
        else:
            self.groupTimes[identifier] = map(lambda x,y:x+y, self.groupTimes[identifier], times)
            self.numTests[identifier] += 1
    def extractColgenData(self, app, statusFile):
        tsValues =  [ "Network generation time", "Generation time", "Coordination time", "DH post processing", "Conn fixing time", "OC to DH time"]
        optRun = optimization.OptimizationRun(app,  [ optimization.timeEntryName, optimization.activeMethodEntryName], tsValues, statusFile)
        solutions = optRun.solutions
        while solutions:
            lastSolution = solutions.pop()
            if lastSolution["Active method"] == "column generator":
                break
        if not lastSolution["Active method"] == "column generator":
            print "Warning: didn't find last colgen solution!"
            return 0, 0
        
        totTime = int(lastSolution["cpu time"]*60)

        sum = 0
        tl = []
        for val in tsValues:
            if lastSolution.has_key(val):
                sum += lastSolution[val]
                tl.append(lastSolution[val])
            else:
                tl.append(0)
        tl.append(totTime - sum)
        return tl

try:
    from matplotlib import *
    use('TkAgg')
    from matplotlib.pylab import *
    mplDefined = True
except:
    mplDefined = False

class PlotEngineMPLTimeDiv(optimization.PlotEngineMPL):
    def plot(self, writeDir):
        xrange, yrange, targetFile, printer, colour, printA3, onlyAverage, plotPercentage, userTitle, noLegend, onlyLegendAverage, terminal, plotSize = self.testGraph.getPlotOptions()
        self.createFigure(plotSize, (targetFile or printer) and printA3)
        clf()

        descAndColours = [ ('Network','brown'),  ('Generation','deepskyblue'), ('PAQS', 'green'),
                          ('Deadhead post','gray'), ('Conn. fix','gold'), ('OC->DH','magenta'), ('Other','black')]

        xstart = 0
        width = 1
        next = width*1.2
        xtik = []
        for version, times in self.testGraph.groupTimes.items():
            numTests = self.testGraph.numTests[version]
            bottom = 0
            colour = 0
            timeSum = reduce(lambda x,y:x+y, times)
            for time in times:
                height = time/60.0/numTests
                desc, col = descAndColours[colour]
                bar([xstart], height, [width], bottom, col)
                if time >= 0.05*timeSum:
                    text(xstart+0.5*width, 0.5*(2*bottom+height), desc + (" %.1f%%" % (100*float(time)/float(timeSum))),
                         horizontalalignment='center', verticalalignment='center', color = 'white')
                bottom += height
                colour += 1
            xtik.append(xstart+0.5*width)
            xstart += next
        xticks(xtik, self.testGraph.groupTimes.keys())
        gca().set_xlim(0, xstart-next+width)
        grid()
        title('Time distribution (average)')
        ylabel('CPU time (min)')

        self.showOrSave(targetFile, writeDir, printer, printA3)

# Override for webpage generation with APC-specific stuff in it
class GenerateWebPages(optimization.GenerateWebPages):
    def createTestTable(self):
        return ApcTestTable()

class ApcTestTable(optimization.TestTable):
    def getColors(self, type, detail):
        colourFinder = testoverview.colourFinder
        bgcol = colourFinder.find("failure_bg")
        fgcol = colourFinder.find("test_default_fg")
        if type == "faster" or type == "slower":
            bgcol = colourFinder.find("performance_bg")
            result = self.getPercent(detail)
            if result[0] and result[1] >= 5:
                fgcol = colourFinder.find("performance_fg")
        elif type == "smaller" or type == "larger":
            result = self.getPercent(detail)
            if result[0] and result[1] >= 3:
                fgcol = colourFinder.find("performance_fg")
            bgcol = colourFinder.find("memory_bg")
        elif type == "success":
            bgcol = colourFinder.find("success_bg")
        return fgcol, bgcol
    def getPercent(self, detail):
        potentialNumber = detail.split("%")[0] # Bad: Hard coded interpretation of texttest print-out.
        if potentialNumber.isdigit():
            return (1, int(potentialNumber))
        else:
            print "Warning: Failed to get percentage from",detail
            return (0, 0)

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
