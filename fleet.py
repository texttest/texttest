helpDescription = """
The Fleet configuration is the same as the Matador configuration.

Note though that the 'matador.ImportTest' script is not implemeted for Fleet yet."""

helpOptions = """
"""

import os, string, carmen, optimization, matador, plugins, shutil

def getConfig(optionMap):
    return FleetConfig(optionMap)

def usingOptionFile():
    if os.environ.has_key("FLEET_SUBPLAN_IN_INPUT"):
        return 0
    else:
        return 1

def subPlanInput(inputFile):
    for line in open(inputFile).xreadlines():
        entries = line.split()
        if entries[0] == "loadsp":
            return string.join(entries[1:], os.sep)

class FleetConfig(matador.MatadorConfig):
    def _subPlanName(self, test):
        if usingOptionFile():
          subPlan = matador.MatadorConfig._subPlanName(self, test)
        else:
          subPlan = subPlanInput(test.inputFile)
        if subPlan == None:
            # print help information and exit:
            return "" 
        return subPlan
    def printHelpDescription(self):
        print helpDescription
        matador.MatadorConfig.printHelpDescription(self)
    def getBinaryFile(self, app):
        if "9" in app.versions:
            return os.path.join("bin", carmen.getArchitecture(app), "opt_route")
        else:
            return os.path.join("bin", carmen.getArchitecture(app), "opt_tail")
    def setUpApplication(self, app):
        matador.MatadorConfig.setUpApplication(self, app)
        self.itemNamesInFile[optimization.costEntryName] = "Optimizer cost"
        self.itemNamesInFile[optimization.memoryEntryName] = "Memory consumption"
        self.itemNamesInFile[optimization.timeEntryName] = "CPU time"
        self.itemNamesInFile[optimization.newSolutionMarker] = "Creating solution"
        # Reset matador values
        self.noIncreaseExceptMethods = {}
        self.noIncreaseExceptMethods[optimization.costEntryName] = []

