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

class FleetSubPlanDirManager(matador.MatadorSubPlanDirManager):
    def __init__(self, config):
        matador.MatadorSubPlanDirManager.__init__(self, config)
    def getExecuteCommand(self, binary, test):
        self.makeTemporary(test)
        tmpDir = self.tmpDirs[test]
        tmpDir = tmpDir.replace(self.getFullPath("") + os.sep, "")
        if self.usesOptionFile(test):
            return binary + " " + self.setupOptions(test, tmpDir)
        else:
            self.setupTemporaryInputFile(test, tmpDir)
            return binary;
    def usesOptionFile(self, test):
        if os.environ.has_key("FLEET_SUBPLAN_IN_INPUT"):
            return 0
        else:
            return 1
    def setupOptions(self, test, tmpDir):
        optparts = test.options.split()
        for ix in range(len(optparts) - 1):
            if optparts[ix] == "-s" and (ix + 1) < len(optparts):
                optparts[ix + 1] = tmpDir
            if optparts[ix] == "-c" and (ix + 1) < len(optparts):
                optparts[ix + 1] = test.abspath + os.sep + optparts[ix + 1]
        return string.join(optparts, " ")
    def setupTemporaryInputFile(self, test, tmpDir):
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
    def removeTemporary(self, test):
        optimization.SubPlanDirManager.removeTemporary(self, test)
        if not self.usesOptionFile(test):
            tmpInputFile = test.getTmpFileName("input", "r")
            if os.path.isfile(tmpInputFile):
                os.remove(tmpInputFile)


