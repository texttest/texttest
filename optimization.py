import carmen, os, shutil, KPI

class OptimizationConfig(carmen.CarmenConfig):
    def getOptionString(self):
        return "k:" + carmen.CarmenConfig.getOptionString(self)
    def getActionSequence(self):
        if self.optionMap.has_key("kpi"):
            return [ CalculateKPI(self.optionValue("kpi")) ]
        if self.optionMap.has_key("rulecomp"):
            return carmen.CarmenConfig.getActionSequence(self)
        
        libraryFile = self.getLibraryFile()
        staticFilter = carmen.UpdatedStaticRulesetFilter(libraryFile)
        return [ carmen.CompileRules(staticFilter) ] + carmen.CarmenConfig.getActionSequence(self)
    def getTestCollator(self):
        return carmen.CarmenConfig.getTestCollator(self) + [ ExtractSubPlanFile(self, "best_solution", "solution") ]

class ExtractSubPlanFile:
    def __init__(self, config, sourceName, targetName):
        self.config = config
        self.sourceName = sourceName
        self.targetName = targetName
    def __repr__(self):
        return "Extracting subplan file " + self.sourceName + " to " + self.targetName + " on"
    def __call__(self, test, description):
        sourcePath = self.config.getSubPlanFileName(test, self.sourceName)
        if os.path.isfile(sourcePath):
            if self.isCompressed(sourcePath):
                targetFile = test.getTmpFileName(self.targetName, "w") + ".Z"
                shutil.copyfile(sourcePath, targetFile)
                os.system("uncompress " + targetFile)
            else:
                targetFile = test.getTmpFileName(self.targetName, "w")
                shutil.copyfile(sourcePath, targetFile)
    def isCompressed(self,path):
        magic = open(path).read(2)
        if magic[0] == chr(0x1f) and magic[1] == chr(0x9d):
            return 1
        else:
            return 0
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
