
import optimization_gui, default_gui, ravebased, os, shutil
from ndict import seqdict

# Graphical import
class ImportTestCase(optimization_gui.ImportTestCase):
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
        ruleSetFile = os.path.join(ruleSetPath, ruleSet + "${BIN_SUFFIX}")
        return path + " " + statusFile + " ${CARMSYS} " + ruleSetFile + " ${USER}"

class InteractiveActionConfig(optimization_gui.InteractiveActionConfig):
    def getReplacements(self):
        return { default_gui.ImportTestCase : ImportTestCase } 
