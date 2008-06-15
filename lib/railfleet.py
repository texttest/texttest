#!/usr/local/bin/python
import ravebased
import os

def getConfig(optionMap):
    return RailfleetConfig(optionMap)

class RailfleetConfig(ravebased.Config):

    def defaultBuildRules(self): return True

    def _getRuleSetNames(self, test):
        rulesets = []
        defaultRuleset = test.getEnvironment("DEFAULT_RULESET_NAME")
        if defaultRuleset and defaultRuleset not in rulesets:
            rulesets.append(defaultRuleset)
        return rulesets
#    def _subPlanName(self, test):
#        opts = test.getWordsInFile("options")
#        return opts and opts[1] or None
