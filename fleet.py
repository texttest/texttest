import os, string, optimization, matador

def getConfig(optionMap):
    return FleetConfig(optionMap)

def subPlanInput(inputFile):
    for line in open(inputFile).xreadlines():
        entries = line.split()
        if entries[0] == "loadsp":
            return string.join(entries[1:], os.sep)
    return None

class FleetConfig(matador.MatadorConfig):
    def __init__(self, optionMap):
        matador.MatadorConfig.__init__(self, optionMap)
        self.subplanManager = FleetSubPlanDirManager(self)
    def subPlanName(self, test):
        subPlan = subPlanInput(test.inputFile)
        if subPlan == None:
            # print help information and exit:
            return ""
        return subPlan


class FleetSubPlanDirManager(optimization.SubPlanDirManager):
    def __init__(self, config):
        optimization.SubPlanDirManager.__init__(self, config)
    def getSubPlanDirFromTest(self, test):
        fullPath = self.getFullPath(self.config.subPlanName(test))
        return fullPath
    def getFullPath(self, path):
        fullPath = os.path.join(os.environ["CARMUSR"], "LOCAL_PLAN", path)
        return os.path.normpath(fullPath)
    def removeTemporary(self, test):
        optimization.SubPlanDirManager.removeTemporary(self, test)
        tmpInputFile = test.getTmpFileName("input", "r")
        if os.path.isfile(tmpInputFile):
            os.remove(tmpInputFile)
    def getExecuteCommand(self, binary, test):
        self.makeTemporary(test)
        tmpDir = self.tmpDirs[test]
        tmpDir = tmpDir.replace(self.getFullPath("") + os.sep,"")
        loadspEntry = string.join(tmpDir.split(os.sep))
        tmpInputFile = test.getTmpFileName("input", "w")
        oldFile = open(test.inputFile)
        newFile = open(tmpInputFile, "w")
        for line in oldFile.readlines():
            entries = line.split()
            if len(entries) > 1 and entries[0] == "loadsp":
                newFile.write("loadsp " + loadspEntry + os.linesep)
            else:
                newFile.write(line)
        return binary
