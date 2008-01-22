
helpDescription = """
The matador_basic configuration is intended to be a reduced version of the matador configuration,
that supports running the Matador programs in an appropriate way without all of the C++ development
support and large suite management that comes with the matador configuration"""

import optimization, ravebased, os, shutil, comparetest

def getConfig(optionMap):
    return Config(optionMap)

def getOption(test, optionVal):
    optparts = test.getWordsInFile("options")
    nextWanted = 0
    for option in optparts:
        if nextWanted:
            return option
        if option == optionVal:
            nextWanted = 1
        else:
            nextWanted = 0
    return None

class Config(optimization.OptimizationConfig):
    def _subPlanName(self, test):
        subPlan = getOption(test, "-s")            
        if subPlan == None:
            # print help information and exit:
            return ""
        return subPlan

    def _getRuleSetNames(self, test):
        return [ self.getBasicRuleSet(test) ]

    def getBasicRuleSet(self, test):
        fromOptions = getOption(test, "-r")
        if fromOptions:
            return fromOptions
        outputFile = test.getFileName("output")
        if outputFile:
            for line in open(outputFile).xreadlines():
                if line.find("Loading rule set") != -1:
                    finalWord = line.split(" ")[-1]
                    return finalWord.strip()
        subPlanDir = self._getSubPlanDirName(test)
        problemsFile = os.path.join(subPlanDir, "APC_FILES", "problems")
        if os.path.isfile(problemsFile):
            for line in open(problemsFile).xreadlines():
                if line.startswith("153"):
                    return line.split(";")[3]

    def filesFromRulesFile(self, test, rulesFile):
        scriptFile = self.getScriptFileFromPyOption(test)
        if not scriptFile:
            scriptFile = self.getRuleSetting(test, "script_file_name")
            useScriptFile = self.getRuleSetting(test, "use_script_file")
            if useScriptFile and useScriptFile == "FALSE":
                scriptFile = ""
        if scriptFile:
            return [ ("Script", self.getScriptPath(test, scriptFile)) ]
        else:
            return []

    def getRuleSetting(self, test, paramName):
        raveParamName = "raveparameters." + test.app.name + test.app.versionSuffix()
        raveParamFile = test.getPathName(raveParamName)
        setting = self.getRuleSettingFromFile(raveParamFile, paramName)
        if setting:
            return setting
        else:
            rulesFile = os.path.join(self._getSubPlanDirName(test), "APC_FILES", "rules")
            if os.path.isfile(rulesFile):
                return self.getRuleSettingFromFile(rulesFile, paramName)

    def getRuleSettingFromFile(self, fileName, paramName):
        if not fileName:
            return
        for line in open(fileName).xreadlines():
            words = line.split(" ")
            if len(words) < 2:
                continue
            if words[0].endswith(paramName):
                return words[1]

    def getScriptFileFromPyOption(self, test):
        # Rollingstock has python script as '-py <file>' in options file ...
        pyFile = getOption(test, "-py")
        if not pyFile:
            return ""
        
        envVars = [ "CARMSYS", "CARMUSR" ]
        for envVar in envVars:
            variable = test.getEnvironment(envVar)
            pyFile = pyFile.replace("$" + envVar, variable)
            pyFile = pyFile.replace("${" + envVar + "}", variable)
            pyFile = pyFile.replace("{$" + envVar + "}", variable)
        return pyFile

    def getTestComparator(self):
        return MakeComparisons(optimization.OptimizationTestComparison, self.getRuleSetting)

    def getScriptPath(self, test, file):
        if os.path.isfile(file):
            return file
        carmusr = test.getEnvironment("CARMUSR")
        fullPath = os.path.join(carmusr, "matador_scripts", file)
        if os.path.isfile(fullPath):
            return fullPath
        fullPath = os.path.join(carmusr, "tail_scripts", file)
        if os.path.isfile(fullPath):
            return fullPath
        fullPath = os.path.join(carmusr, "apc_scripts", file)
        return fullPath

    def getDefaultCollations(self):
        return { "stacktrace" : "APC_FILES/core*" }
    
    def setApplicationDefaults(self, app):
        optimization.OptimizationConfig.setApplicationDefaults(self, app)
        self.itemNamesInFile[optimization.memoryEntryName] = "Memory consumption"
        self.itemNamesInFile[optimization.newSolutionMarker] = "Creating solution"
        self.itemNamesInFile[optimization.solutionName] = "Solution\."
 
    def getConfigEnvironment(self, test):
        baseEnv, props = optimization.OptimizationConfig.getConfigEnvironment(self, test)
        if test.parent is None:
            baseEnv.append(("MATADOR_CRS_NAME", ravebased.getBasicRaveName(test)))
        return baseEnv, props


class MakeComparisons(comparetest.MakeComparisons):
    def __init__(self, testComparisonClass, getRuleSetting):
        comparetest.MakeComparisons.__init__(self, testComparisonClass)
        self.getRuleSetting = getRuleSetting
    def __call__(self, test):
        if self.isSeniority(test) and not self.isSeniorityEvaluation(test):
            self.testComparisonClass = comparetest.TestComparison
        else:
            self.testComparisonClass = optimization.OptimizationTestComparison
        comparetest.MakeComparisons.__call__(self, test)
    def isSeniority(self, test):
        ruleVal = self.getRuleSetting(test, "map_seniority")
        return ruleVal and not ruleVal.startswith("#")
    def isSeniorityEvaluation(self, test):
        output = test.getFileName("output")
        log = open(output).read()
        return log.rfind("Adjusted cost of plan") != -1



class ImportTestCase(optimization.ImportTestCase):
    def getOptions(self, suite):
        return "-s " + self.getSubplanName()

    def writeResultsFiles(self, suite, testDir):
        carmdataVar, carmdata = ravebased.getCarmdata(suite)
        subPlanPath = os.path.join(carmdata, "LOCAL_PLAN", self.getSubplanName(), "APC_FILES")
        self.copyFile(testDir, "output." + suite.app.name, subPlanPath, "matador.log")
        self.copyFile(testDir, "errors." + suite.app.name, subPlanPath, "sge.log")

    def copyFile(self, testDir, ttName, subPlan, name):
        sourceFile = os.path.join(subPlan, name)
        if os.path.isfile(sourceFile):
            targetFile = os.path.join(testDir, ttName)
            if not os.path.isfile(targetFile):
                shutil.copyfile(sourceFile, targetFile)

def getInteractiveActionClasses(dynamic):
    return [ optimization.PlotTestInGUI ]
