helpDescription = """
The RAVE configuration is based on the Matador configuration. It is set up such that rulesets are always compiled before
running any tests, because it is assumed that something fundamental has changed in RAVE. It is used as a version of the
Matador tests.""" 

helpOptions = """-skip      - Don't build any rulesets, just this time.

-debug     - Compile a debug ruleset, and rename it so that it is used instead of the normal one.
"""

import os, matador, plugins

def getConfig(optionMap):
    return RaveConfig(optionMap)

class RaveConfig(matador.MatadorConfig):
    def addToOptionGroup(self, group):
        matador.MatadorConfig.addToOptionGroup(self, group)
        if group.name.startswith("How"):
            group.addSwitch("skip", "Don't build rulesets")
    def buildRules(self):
        return matador.MatadorConfig.buildRules(self) and not self.optionMap.has_key("skip")
    def getRuleBuildFilter(self):
        return None
    def printHelpDescription(self):
        print helpDescription
        matador.MatadorConfig.printHelpDescription(self)
    def printHelpOptions(self, builtInOptions):
        matador.MatadorConfig.printHelpOptions(self, builtInOptions)
        print helpOptions
    # RAVE publisher stuff, not used currently
    def getRuleSetName(self, test):
        if test.app.name == "ravepublisher":
            return self.getRavePublisherRuleset(test)
        return matador.MatadorConfig.getRuleSetName(self, test)
    def getRavePublisherRuleset(self, test):
        headerFile = self.getSubPlanFileName(test, "subplanHeader")
        for line in open(headerFile).xreadlines():
            if line[0:4] == "554;":
                return os.path.basename(line.split(";")[21])
        return ""
    def getSubPlanFileName(self, test, sourceName):
        firstWord = test.options.split()[0]
        subPlan = firstWord[1:-1]
        return os.path.join(os.environ["CARMUSR"], "LOCAL_PLAN", subPlan, sourceName)
    
