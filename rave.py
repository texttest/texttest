helpDescription = """
The RAVE configuration is based on the Carmen configuration. It is set up such that rulesets are always compiled before
running any tests, because it is assumed that something fundamental has changed in RAVE. It is used in various RAVE
applications, but also as a version on the Matador tests.""" 

helpOptions = """-skip      - Don't build any rulesets, just this time.

-debug     - Compile a debug ruleset, and rename it so that it is used instead of the normal one.
"""

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
    def printHelpDescription(self):
        print helpDescription
        carmen.CarmenConfig.printHelpDescription(self)
    def printHelpOptions(self, builtInOptions):
        carmen.CarmenConfig.printHelpOptions(self, builtInOptions)
        print helpOptions
