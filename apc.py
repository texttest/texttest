import carmen, os, shutil, optimization

def getConfig(optionMap):
    return ApcConfig(optionMap)

class ApcConfig(optimization.OptimizationConfig):

    def getLibraryFile(self):
        return os.path.join("data", "apc", carmen.architecture, "libapc.a")

    def getSubPlanFileName(self, test, sourceName):
        return os.path.join(test.options, "APC_FILES", sourceName)
    def getTestCollator(self):
        return optimization.OptimizationConfig.getTestCollator(self) + [ optimization.ExtractSubPlanFile(self, "status", "status") ]


