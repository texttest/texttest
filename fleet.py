helpDescription = """
The Fleet configuration is the same as the Matador configuration.

Note though that the 'matador.ImportTest' script is not implemeted for Fleet yet."""

helpOptions = """
"""

import os, string, optimization, matador

def getConfig(optionMap):
    return FleetConfig(optionMap)

def getOption(options, optionVal):
    optparts = options.split()
    nextWanted = 0
    for option in optparts:
        if nextWanted:
            return option
        if option == optionVal:
            nextWanted = 1
        else:
            nextWanted = 0
    return None

class FleetConfig(matador.MatadorConfig):
    def __init__(self, optionMap):
        matador.MatadorConfig.__init__(self, optionMap)
        self.subplanManager = FleetSubPlanDirManager(self)
    def subPlanName(self, test):
        subPlan = getOption(test.options, "-s")
        if subPlan == None:
            # print help information and exit:
            return ""
        return subPlan
    def printHelpDescription(self):
        print helpDescription
        matador.MatadorConfig.printHelpDescription(self)
    def setUpApplication(self, app):
        matador.MatadorConfig.setUpApplication(self, app)
        self.itemNamesInFile[optimization.costEntryName] = "Optimizer cost"
        # Reset matador values
        self.noIncreaseExceptMethods = {}
        self.noIncreaseExceptMethods[optimization.costEntryName] = []

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
        optparts = test.options.split()
        for ix in range(len(optparts) - 1):
            if optparts[ix] == "-s" and (ix + 1) < len(optparts):
                optparts[ix + 1] = tmpDir
            if optparts[ix] == "-c" and (ix + 1) < len(optparts):
                optparts[ix + 1] = test.abspath + os.sep + optparts[ix + 1]
        options = string.join(optparts, " ")
        return binary + " " + options


