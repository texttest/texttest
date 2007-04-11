import ravebased
import os

def getConfig(optionMap):
    return StudioScriptConfig(optionMap)

class StudioScriptConfig(ravebased.Config):

    def defaultBuildRules(self): return True

    def _getRuleSetNames(self, test):
        opts = test.getWordsInFile("options")
        return opts and [opts[0]] or []

    def _subPlanName(self, test):
        opts = test.getWordsInFile("options")
        return opts and opts[1] or None
