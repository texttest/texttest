import os, string, matador

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


class FleetSubPlanDirManager(matador.MatadorSubPlanDirManager):
    def __init__(self, config):
        matador.MatadorSubPlanDirManager.__init__(self, config)
    def getExecuteCommand(self, binary, test):
        return binary
