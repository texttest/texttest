helpDescription = """
The Fleet configuration is the same as the Matador configuration.

Note though that the 'matador.ImportTest' script is not implemeted for Fleet yet."""

helpOptions = """
"""

import os, string, optimization, matador, plugins, shutil

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
    def getTestRunner(self):
        matadorRunner = matador.MatadorConfig.getTestRunner(self)
        if not usingOptionFile():
            return matadorRunner
        else:
            return plugins.CompositeAction([ CopyCommandsFile(), matadorRunner ])
    def getTestCollator(self):
        return plugins.CompositeAction([ matador.MatadorConfig.getTestCollator(self), RemoveCommandsFile() ])
    def printHelpDescription(self):
        print helpDescription
        matador.MatadorConfig.printHelpDescription(self)
    def setUpApplication(self, app):
        matador.MatadorConfig.setUpApplication(self, app)
        self.itemNamesInFile[optimization.costEntryName] = "Optimizer cost"
        # Reset matador values
        self.noIncreaseExceptMethods = {}
        self.noIncreaseExceptMethods[optimization.costEntryName] = []

class CopyCommandsFile(plugins.Action):
    def __call__(self, test):
        fileName = "commands"
        filePath = test.makeFileName(fileName)
        tmpPath = test.makeFileName(fileName, temporary=1)
        if os.path.isfile(filePath):
            shutil.copyfile(filePath, tmpPath)

class RemoveCommandsFile(plugins.Action):
    def __call__(self, test):
        fileName = "commands"
        tmpPath = test.makeFileName(fileName, temporary=1)
        if os.path.isfile(tmpPath):
            os.remove(tmpPath)

