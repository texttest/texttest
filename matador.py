import carmen, os, shutil, getopt, optimization, string, plugins

def getConfig(optionMap):
    return MatadorConfig(optionMap)

class MatadorConfig(optimization.OptimizationConfig):
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
        try:
            opts, args = getopt.getopt(test.options.split(), "s:r:")
        except getopt.GetoptError:
            # print help information and exit:
            return ""
        for o, a in opts:
            if o == "-s":
                return a
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
            
#    def getTestCollator(self):
#        return optimization.OptimizationConfig.getTestCollator(self) + [ MakeMatadorStatusFile() ]

class MakeMatadorStatusFile(plugins.Action):
    def __call__(self, test):
        scriptPath = os.path.join(os.environ["CARMSYS"], "bin", "makestatusfiles.sh")
        outputFile = test.getTmpFileName("output", "r")
        os.system(scriptPath + " . " + outputFile)
        os.rename("status", test.getTmpFileName("status", "w"))
