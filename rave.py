import carmen, os, matador, plugins

def getConfig(optionMap):
    return RaveConfig(optionMap)

class RaveConfig(carmen.CarmenConfig):
    def getOptionString(self):
        return "k:" + carmen.CarmenConfig.getOptionString(self)
    def getRuleBuilder(self, neededOnly):
        if self.optionMap.has_key("skip"):
            return plugins.Action()

        buildMode = "-optimize"
        if self.optionMap.has_key("debug"):
            buildMode = "-debug"
            
        return carmen.CompileRules(self.getRuleSetName, buildMode)
    def getSubPlanFileName(self, test, sourceName):
        firstWord = test.options.split()[0]
        subPlan = firstWord[1:-1]
        return os.path.join(os.environ["CARMUSR"], "LOCAL_PLAN", subPlan, sourceName)
    def getRuleSetName(self, test):
        if test.app.name == "ravepublisher":
            return self.getRavePublisherRuleset(test)
        matadorConfig = matador.MatadorConfig({})
        return matadorConfig.getRuleSetName(test)
    def getRavePublisherRuleset(self, test):
        headerFile = self.getSubPlanFileName(test, "subplanHeader")
        for line in open(headerFile).xreadlines():
            if line[0:4] == "554;":
                return os.path.basename(line.split(";")[21])
        return ""
