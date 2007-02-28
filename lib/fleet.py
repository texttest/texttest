helpDescription = """
The Fleet configuration is the same as the Matador configuration.

Note though that the 'matador.ImportTest' script is not implemeted for Fleet yet."""

helpOptions = """
"""

import os, string, optimization, matador, plugins, shutil

def getConfig(optionMap):
    return FleetConfig(optionMap)

# This seems to exist entirely for Tail Assignment plotting graphs.
# Fleet/RollingStock don't work here anyway...
class FleetConfig(matador.MatadorConfig):
    def printHelpDescription(self):
        print helpDescription
        matador.MatadorConfig.printHelpDescription(self)
    def setUpApplication(self, app):
        matador.MatadorConfig.setUpApplication(self, app)
        self.itemNamesInFile[optimization.costEntryName] = "Optimizer cost"
        self.itemNamesInFile[optimization.memoryEntryName] = "Memory consumption"
        self.itemNamesInFile[optimization.timeEntryName] = "cpu time"
        self.itemNamesInFile[optimization.newSolutionMarker] = "Creating solution"
        # Reset matador values
        self.noIncreaseExceptMethods = {}
        self.noIncreaseExceptMethods[optimization.costEntryName] = []
    def  setApplicationDefaults(self, app):
	matador.MatadorConfig.setApplicationDefaults(self, app)
        self.itemNamesInFile[optimization.costEntryName] = "Optimizer cost"
        self.itemNamesInFile[optimization.memoryEntryName] = "Memory consumption"
        self.itemNamesInFile[optimization.timeEntryName] = "cpu time"
        self.itemNamesInFile[optimization.newSolutionMarker] = "Creating solution"
        # Reset matador values
        self.noIncreaseExceptMethods = {}
        self.noIncreaseExceptMethods[optimization.costEntryName] = []
	

