import carmen, os, shutil

def getConfig(optionMap):
    return MatadorConfig(optionMap)

class MatadorConfig(carmen.CarmenConfig):
    def getActionSequence(self):
        libraryFile = os.path.join("data", "crc", "MATADOR", carmen.architecture, "matador.o")
        staticFilter = carmen.UpdatedStaticRulesetFilter(libraryFile, "matador")
        return [ carmen.CompileRules(staticFilter) ] + carmen.CarmenConfig.getActionSequence(self)
    def getTestCollator(self):
        return carmen.CarmenConfig.getTestCollator(self) + [ MakeMatadorStatusFile(), MakeSolutionFile() ]

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

class MakeSolutionFile:
    def __repr__(self):
        return "Collecting solution file for"
    def __call__(self, test, description):
        solutionPath = os.path.join(os.environ["CARMUSR"], "LOCAL_PLAN", test.options[3:], "APC_FILES", "best_solution")
        if os.path.isfile(solutionPath):
            solutionFile = test.getTmpFileName("solution", "w") + ".Z"
            shutil.copyfile(solutionPath, solutionFile)
            os.system("uncompress " + solutionFile)
    def setUpSuite(self, suite, description):
        pass

