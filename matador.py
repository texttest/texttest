import carmen, os, shutil, getopt, optimization, string, plugins, comparetest

def getConfig(optionMap):
    return MatadorConfig(optionMap)

class MatadorConfig(optimization.OptimizationConfig):
    def __init__(self, optionMap):
        optimization.OptimizationConfig.__init__(self, optionMap)
        self.subplanManager = MatadorSubPlanDirManager(self)
        if self.optionMap.has_key("diag"):
            os.environ["DIAGNOSTICS_IN"] = "./Diagnostics"
            os.environ["DIAGNOSTICS_OUT"] = "./Diagnostics"
        if os.environ.has_key("DIAGNOSTICS_IN"):
            print "Note: Running with Diagnostics on, so performance checking is disabled!"
    def __del__(self):
        if self.optionMap.has_key("diag"):
            del os.environ["DIAGNOSTICS_IN"]
            del os.environ["DIAGNOSTICS_OUT"]
    def getTestComparator(self):
        if self.optionMap.has_key("diag"):
            return CompareTestWithDiagnostics()
        else:
            return optimization.OptimizationConfig.getTestComparator(self)
    def checkPerformance(self):
        return not self.optionMap.has_key("diag")
    def getLibraryFile(self):
        return os.path.join("data", "crc", "MATADOR", carmen.architecture, "matador.o")
    def getSubPlanFileName(self, test, sourceName):
        return os.path.join(os.environ["CARMUSR"], "LOCAL_PLAN", self.subPlanName(test), "APC_FILES", sourceName)
    def subPlanName(self,test):
        if len(test.options):
            return self.optionsSubPlanName(test)
        else:
            return self.inputSubPlanName(test)
    def optionsSubPlanName(self, test):
        optparts = test.options.split()
        nextIsSubplan = 0
        for option in optparts:
            if nextIsSubplan == 1:
                return option
            if option == "-s":
                nextIsSubplan = 1
            else:
                nextIsSubplan = 0
        # print help information and exit:
        return ""
    def inputSubPlanName(self, test):
        for line in open(test.inputFile).xreadlines():
            entries = line.split()
            if entries[0] == "loadsp":
                return string.join(entries[1:], os.sep)
    def getRuleSetName(self, test):
        fileName = test.makeFileName("output")
        if os.path.isfile(fileName):
            for line in open(fileName).xreadlines():
                if line.find("Loading rule set") != -1:
                    finalWord = line.split(" ")[-1]
                    return finalWord.strip()
        return None
    def getExecuteCommand(self, binary, test):
        return self.subplanManager.getExecuteCommand(binary, test)
            
#    def getTestCollator(self):
#        return optimization.OptimizationConfig.getTestCollator(self) + [ MakeMatadorStatusFile() ]

class MakeMatadorStatusFile(plugins.Action):
    def __call__(self, test):
        scriptPath = os.path.join(os.environ["CARMSYS"], "bin", "makestatusfiles.sh")
        outputFile = test.getTmpFileName("output", "r")
        os.system(scriptPath + " . " + outputFile)
        os.rename("status", test.getTmpFileName("status", "w"))

class CompareTestWithDiagnostics(comparetest.MakeComparisons):
    def fileFinders(self, test):
        diagFinder = "diag", "Diagnostics"
        return comparetest.MakeComparisons.fileFinders(self, test) + [ diagFinder ]
    
class MatadorSubPlanDirManager(optimization.SubPlanDirManager):
    def __init__(self, config):
        optimization.SubPlanDirManager.__init__(self, config)
    def getSubPlanDirFromTest(self, test):
        fullPath = self.getFullPath(self.config.subPlanName(test))
        return fullPath
    def getFullPath(self, path):
        fullPath = os.path.join(os.environ["CARMUSR"], "LOCAL_PLAN", path)
        return os.path.normpath(fullPath)
    def getExecuteCommand(self, binary, test):
        if len(test.options) == 0:
            return binary
        self.makeTemporary(test)
        tmpDir = self.tmpDirs[test]
        tmpDir = tmpDir.replace(self.getFullPath("") + os.sep,"")

        optparts = test.options.split()
        for ix in range(len(optparts) - 1):
            if optparts[ix] == "-s" and (ix + 1) < len(optparts):
                optparts[ix+1] = tmpDir
        options = string.join(optparts, " ")
        return binary + " " + options
    
