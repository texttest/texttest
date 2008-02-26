import ravebased, os

def getConfig(optionMap):
    return Config(optionMap)

class Config(ravebased.Config):
    def defaultBuildRules(self):
        return True

    def _getRuleSetNames(self, test):
        return [ self.getSubplanRuleset(test) ]

    def _subPlanName(self, test):
        opts = test.getWordsInFile("options")
        if opts:
            return os.path.expandvars(opts[-1][:-1], test.getEnvironment)
