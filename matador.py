import carmen, os, shutil, KPI

def getConfig(optionMap):
    return MatadorConfig(optionMap)

class MatadorConfig(carmen.CarmenConfig):
    def getOptionString(self):
        return "k:" + carmen.CarmenConfig.getOptionString(self)
    def getActionSequence(self):
        if self.optionMap.has_key("kpi"):
            return [ CalculateKPI(self.optionValue("kpi")) ]
        if self.optionMap.has_key("rulecomp"):
            return carmen.CarmenConfig.getActionSequence(self)
        
        libraryFile = os.path.join("data", "crc", "MATADOR", carmen.architecture, "matador.o")
        staticFilter = carmen.UpdatedStaticRulesetFilter(libraryFile)
        return [ carmen.CompileRules(staticFilter) ] + carmen.CarmenConfig.getActionSequence(self)
    def getTestCollator(self):
        return carmen.CarmenConfig.getTestCollator(self) + [ MakeSolutionFile() ]

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

class CalculateKPI:
    def __init__(self, referenceVersion):
        self.referenceVersion = referenceVersion
        self.totalKPI = 0
        self.numberOfValues = 0
    def __del__(self):
        if self.numberOfValues > 0:
            print "Overall average KPI with respect to version", self.referenceVersion, "=", float(self.totalKPI / self.numberOfValues)
        else:
            print "No KPI tests were found with respect to version " + self.referenceVersion
    def __repr__(self):
        return "Calculating KPI for"
    def __call__(self, test, description):
        currentFile = test.makeFileName("status")
        referenceFile = test.makeFileName("status", self.referenceVersion)
        if currentFile != referenceFile:
            kpiValue = KPI.calculate(referenceFile, currentFile)
            print description + ", with respect to version", self.referenceVersion, "- returns", kpiValue
            self.totalKPI += kpiValue
            self.numberOfValues += 1
    def setUpSuite(self, suite, description):
        print description
