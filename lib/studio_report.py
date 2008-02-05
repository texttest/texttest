import ravebased, guiplugins, os

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


# Graphical import test
class ImportTestCase(guiplugins.ImportTestCase):
    def addDefinitionFileOption(self):
        self.addOption("sp", "Subplan name")
        self.addOption("dir", "Report directory", "", self.getPossibleReportDirs())
        self.addOption("rep", "Report name")

    def getPossibleReportDirs(self):
        dirs = [ "hidden" ]
        for objectType in [ "leg", "rtd", "acrot", "crr", "crew" ]:
            dirs.append(objectType + "_window_general")
            dirs.append(objectType + "_window_object")
        return dirs
    
    def getOptions(self, suite):
        return '-w -P "carmtest/reportTests.py -d ' + self.optionGroup.getOptionValue("dir") + \
               ' -r ' + self.optionGroup.getOptionValue("rep") + \
               ' -n OutputReport.txt ' + self.optionGroup.getOptionValue("sp") + '"'
 
