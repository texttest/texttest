helpDescription = """
The apc_basic configuration is intended to be a reduced version of the APC configuration,
that supports running the APC program in an appropriate way without all of the C++ development
support and large suite management that comes with the APC configuration"""

import optimization, ravebased, plugins, os, shutil
from carmenqueuesystem import RunWithParallelAction
from comparetest import ProgressTestComparison
from socket import gethostname
from ndict import seqdict

# Don't use the "ravebased" one, which assumes suites define CARMUSRs
from guiplugins import ImportTestSuite

def getConfig(optionMap):
    return Config(optionMap)

class Config(optimization.OptimizationConfig):
    def getTestRunner(self):
        baseRunner = optimization.OptimizationConfig.getTestRunner(self)
        if self.slaveRun():
            return [ MarkApcLogDir(self.isExecutable, self.hasAutomaticCputimeChecking, baseRunner, self.optionMap), baseRunner ]
        else:
            return baseRunner
    def isExecutable(self, process, test):
        # Process name starts with a dot and may be truncated or have
        # extra junk at the end added by APCbatch.sh
        processData = process[1:]
        rulesetName = self.getRuleSetNames(test)[0]
        return processData.startswith(rulesetName) or rulesetName.startswith(processData)
    def getProgressComparisonClass(self):
        return ApcProgressTestComparison
    def getStatusFilePath(self, test):
        rawStatusFile = test.getWordsInFile("options")[1]
        statusFile = os.path.expandvars(rawStatusFile, test.getEnvironment)
        return os.path.normpath(statusFile)
    def _getSubPlanDirName(self, test):
        statusFile = self.getStatusFilePath(test)
        dirs = statusFile.split(os.sep)[:-2]
        return os.path.normpath(os.sep.join(dirs))
    def _getRuleSetNames(self, test):
        for option in test.getWordsInFile("options"):
            if option.find("crc" + os.sep + "rule_set") != -1:
                return [ os.path.basename(option) ]
        return []
    def getFileExtractor(self):
        subActions = [ optimization.OptimizationConfig.getFileExtractor(self) ]
        if self.slaveRun():
            subActions.append(self.getApcTmpDirHandler())
        return subActions
    def getApcTmpDirHandler(self):
        return HandleApcTmpDir(self.optionMap.has_key("keeptmp"))
    def getDefaultCollations(self):
        return { "stacktrace" : "apc_tmp_dir/core*" }
    def setApplicationDefaults(self, app):
        optimization.OptimizationConfig.setApplicationDefaults(self, app)
        self.itemNamesInFile[optimization.memoryEntryName] = "Time:.*memory"
        self.itemNamesInFile[optimization.timeEntryName] = "cpu time|cpu-tid|cpu-zeit"
        self.itemNamesInFile[optimization.execTimeEntryName] = "^Time: "
        self.itemNamesInFile[optimization.costEntryName] = "TOTAL cost"
        self.itemNamesInFile[optimization.newSolutionMarker] = "apc_status Solution"


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
        

class MarkApcLogDir(RunWithParallelAction):
    def __init__(self, isExecutable, hasAutomaticCpuTimeChecking, baseRunner, optionMap):
        RunWithParallelAction.__init__(self, isExecutable, hasAutomaticCpuTimeChecking, baseRunner)
        self.keepLogs = optionMap.has_key("extractlogs")
    def getApcHostTmp(self, test):
        resLine = ravebased.getEnvVarFromCONFIG("APC_TEMP_DIR", test)
        if resLine.find("/") != -1:
            return resLine
        return "/tmp"
    def getApcLogDir(self, test, pid = None):
        # Logfile dir
        subplanPath = os.path.realpath(test.makeTmpFileName("APC_FILES", forComparison=0))
        subplanName, apcFiles = os.path.split(subplanPath)
        baseSubPlan = os.path.basename(subplanName)
        apcHostTmp = self.getApcHostTmp(test)
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
        cmdArgs = [ "xon", gethostname(), "xterm -bg white -T " + test.name + " -e less +F " + logFileName ]
        file.write(repr(cmdArgs))
        file.close()
    def performParallelAction(self, test, execProcess, parentProcess):
        apcTmpDir = self.getApcLogDir(test, str(parentProcess.pid))
        self.diag.info("APC log directory is " + apcTmpDir + " based on process " + parentProcess.getName())
        if not os.path.isdir(apcTmpDir):
            raise plugins.TextTestError, "ERROR : " + apcTmpDir + " does not exist - running process " + execProcess.getName()
        self.makeLinks(test, apcTmpDir)
        if self.keepLogs:
            fileName = os.path.join(apcTmpDir, "apc_debug")
            file = open(fileName, "w")
            file.close()

# Make sure we don't leak APC tmp directories
class HandleApcTmpDir(plugins.Action):
    def __init__(self, keepTmp):
        self.diag = plugins.getDiagnostics("ExtractApcLogs")
        self.keepTmp = keepTmp
    def __call__(self, test):
        apcTmpDir = test.makeTmpFileName("apc_tmp_dir", forComparison=0)
        if not os.path.isdir(apcTmpDir):
            return

        self.extractFiles(test, apcTmpDir)
        realPath = os.path.realpath(apcTmpDir)
        os.remove(apcTmpDir)
        if self.keepTmp:
            shutil.copytree(realPath, apcTmpDir) 
        # Remove dir
        plugins.rmtree(realPath)
    def extractFiles(self, test, apcTmpDir):
        # Just here to prevent leaking. APC module does stuff :)
        pass

# Graphical import
class ImportTestCase(optimization.ImportTestCase):
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
        application = ravebased.getRaveNames(suite)[0]
        return self.buildOptions(carmdataVar, subplan, ruleset, application)
    def buildOptions(self, carmdataVar, subplan, ruleSet, application):
        path = os.path.join("$" + carmdataVar, "LOCAL_PLAN", subplan, "APC_FILES")
        statusFile = os.path.join(path, "run_status")
        ruleSetPath = os.path.join("${CARMTMP}", "crc", "rule_set", application.upper(), "PUTS_ARCH_HERE")
        ruleSetFile = os.path.join(ruleSetPath, ruleSet)
        return path + " " + statusFile + " ${CARMSYS} " + ruleSetFile + " ${USER}"
