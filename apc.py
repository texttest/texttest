import carmen, os, shutil, optimization

def getConfig(optionMap):
    return ApcConfig(optionMap)

class ApcConfig(optimization.OptimizationConfig):
    def getLibraryFile(self):
        return os.path.join("data", "apc", carmen.architecture, "libapc.a")
    def getSubPlanFileName(self, test, sourceName):
        return os.path.join(test.options.split()[0], sourceName)
    def getTestCollator(self):
        return optimization.OptimizationConfig.getTestCollator(self) + [ RemoveLogs(), optimization.ExtractSubPlanFile(self, "status", "status") ]

class RemoveLogs:
    def __repr__(self):
        return "Removing log files for"
    def __call__(self, test, description):
        self.removeFile(test, "errors")
        self.removeFile(test, "output")
    def removeFile(self, test, stem):
        os.remove(test.getTmpFileName(stem, "r"))
    def setUpSuite(self, suite, description):
        pass

