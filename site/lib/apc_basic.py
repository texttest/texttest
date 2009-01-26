helpDescription = """
The apc_basic configuration is intended to be a reduced version of the APC configuration,
that supports running the APC program in an appropriate way without all of the C++ development
support and large suite management that comes with the APC configuration"""

import optimization, ravebased, plugins, os, shutil
from carmenqueuesystem import RunWithParallelAction
from comparetest import ProgressTestComparison
from socket import gethostname

def getConfig(optionMap):
    return Config(optionMap)

class Config(optimization.OptimizationConfig):
    def getTestRunner(self):
        baseRunner = optimization.OptimizationConfig.getTestRunner(self)
        if self.slaveRun():
            return [ self.getApcLogDirMarker(baseRunner), baseRunner ]
        else:
            return baseRunner
    def getApcLogDirMarker(self, baseRunner):
        return MarkApcLogDir(self.isExecutable, self.hasAutomaticCputimeChecking, baseRunner, self.optionMap)
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
                ruleSetName = os.path.basename(option)
                hasBinSuf = ruleSetName.find("${BIN_SUFFIX}")
                if hasBinSuf != -1:
                    ruleSetName = ruleSetName[:hasBinSuf]
                return [ ruleSetName ]
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
        self.makeLink(apcTmpDir, linkTarget)
    def makeLink(self, source, target):
        try:
            os.symlink(source, target)
        except OSError:
            print "Failed to create link", os.path.basename(target)

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

