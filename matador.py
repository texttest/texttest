import carmen, os, shutil, getopt, optimization

def getConfig(optionMap):
    return MatadorConfig(optionMap)

class MatadorConfig(optimization.OptimizationConfig):
    def getLibraryFile(self):
        return os.path.join("data", "crc", "MATADOR", carmen.architecture, "matador.o")
    def getSubPlanFileName(self, test, sourceName):
        return os.path.join(os.environ["CARMUSR"], "LOCAL_PLAN", self.subPlanName(test), "APC_FILES", sourceName)
    def subPlanName(self,test):
        try:
            opts, args = getopt.getopt(test.options.split(), "s:r:")
        except getopt.GetoptError:
            # print help information and exit:
            return ""
        for o, a in opts:
            if o == "-s":
                return a
            
#    def getTestCollator(self):
#        return optimization.OptimizationConfig.getTestCollator(self) + [ MakeMatadorStatusFile() ]

class MakeMatadorStatusFile:
    def __repr__(self):
        return "Collecting status file for"
    def __call__(self, test, description):
        scriptPath = os.path.join(os.environ["CARMSYS"], "bin", "makestatusfiles.sh")
        outputFile = test.getTmpFileName("output", "r")
        os.system(scriptPath + " . " + outputFile)
        os.rename("status", test.getTmpFileName("status", "w"))
    def setUpSuite(self, suite, description):
        pass

