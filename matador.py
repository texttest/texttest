helpDescription = """
The Matador configuration is based on the Carmen configuration. It will compile all static rulesets in the test
suite before running any tests, if the library file "matador.o" has changed since the static ruleset was last built.
It will also fetch the optimizer's solution from the subplan (the "best_solution" link) and write it for comparison
as the file solution.<app> after each test has run.

It also uses the temporary subplan concept, such that all tests will actually be run in different, temporary subplans
when the tests are run. These subplans should then be cleaned up afterwards. The point of this is to avoid clashes in
solution due to two runs of the same test writing to the same subplan.

In other respects, it follows the usage of the Carmen configuration.""" 

helpOptions = """-diag      - Run with diagnostics on. This will set the environment variables DIAGNOSTICS_IN and DIAGNOSTICS_OUT to
             both point at the subdirectory ./Diagnostics in the test case. It will also disable performance checking,
             as producing lots of text tends to slow down the program, and will tell the comparator to also
             compare the diagnostics found in the ./Diagnostics subdirectory.

-prrep <v> - Generate a Progress Report relative to the version <v>. This will produce some key numbers for all
             tests specified.

-kpi <ver> - Generate a Key Performance Indicator ("KPI") relative to the version <ver>. This will try to apply
             some formula to boil down the results of the tests given to a single-number "performance indicator".
             Please note that the results so far are not very reliable, as the formula itself is still under development.
"""

import carmen, os, shutil, filecmp, optimization, string, plugins, comparetest

def getConfig(optionMap):
    return MatadorConfig(optionMap)

def getOption(options, optionVal):
    optparts = options.split()
    nextWanted = 0
    for option in optparts:
        if nextWanted:
            return option
        if option == optionVal:
            nextWanted = 1
        else:
            nextWanted = 0
    return None

class MatadorConfig(optimization.OptimizationConfig):
    def __init__(self, optionMap):
        optimization.OptimizationConfig.__init__(self, optionMap)
        self.subplanManager = MatadorSubPlanDirManager(self)
        if self.optionMap.has_key("diag"):
            os.environ["DIAGNOSTICS_IN"] = "./Diagnostics"
            os.environ["DIAGNOSTICS_OUT"] = "./Diagnostics"
        if os.environ.has_key("DIAGNOSTICS_IN"):
            print "Note: Running with Diagnostics on, so performance checking is disabled!"
    def __del__(self):
        if self.optionMap.has_key("diag"):
            del os.environ["DIAGNOSTICS_IN"]
            del os.environ["DIAGNOSTICS_OUT"]
    def getTestComparator(self):
        if self.optionMap.has_key("diag"):
            return CompareTestWithDiagnostics()
        else:
            return optimization.OptimizationConfig.getTestComparator(self)
    def checkPerformance(self):
        return not self.optionMap.has_key("diag")
    def getLibraryFile(self):
        return os.path.join("data", "crc", "MATADOR", carmen.architecture, "matador.o")
    def getSubPlanFileName(self, test, sourceName):
        return self.subplanManager.getSubPlanFileName(test, sourceName)
    def subPlanName(self, test):
        subPlan = getOption(test.options, "-s")            
        if subPlan == None:
            # print help information and exit:
            return ""
        return subPlan
    def getRuleSetName(self, test):
        outputFile = test.makeFileName("output")
        if os.path.isfile(outputFile):
            for line in open(outputFile).xreadlines():
                if line.find("Loading rule set") != -1:
                    finalWord = line.split(" ")[-1]
                    return finalWord.strip()
        return getOption(test.options, "-r")
    def getExecuteCommand(self, binary, test):
        return self.subplanManager.getExecuteCommand(binary, test)
    def getTestCollator(self):
        subActions = [ optimization.OptimizationConfig.getTestCollator(self) ]
        subActions.append(optimization.RemoveTemporarySubplan(self.subplanManager))
        return plugins.CompositeAction(subActions)
    def printHelpDescription(self):
        print helpDescription
        carmen.CarmenConfig.printHelpDescription(self)
    def printHelpOptions(self, builtInOptions):
        carmen.CarmenConfig.printHelpOptions(self, builtInOptions)
        print helpOptions

class MakeMatadorStatusFile(plugins.Action):
    def __call__(self, test):
        scriptPath = os.path.join(os.environ["CARMSYS"], "bin", "makestatusfiles.sh")
        outputFile = test.getTmpFileName("output", "r")
        os.system(scriptPath + " . " + outputFile)
        os.rename("status", test.getTmpFileName("status", "w"))

class CompareTestWithDiagnostics(comparetest.MakeComparisons):
    def fileFinders(self, test):
        diagFinder = "diag", "Diagnostics"
        return comparetest.MakeComparisons.fileFinders(self, test) + [ diagFinder ]
    
class MatadorSubPlanDirManager(optimization.SubPlanDirManager):
    def __init__(self, config):
        optimization.SubPlanDirManager.__init__(self, config)
    def getSubPlanDirFromTest(self, test):
        fullPath = self.getFullPath(self.config.subPlanName(test))
        return fullPath
    def getFullPath(self, path):
        fullPath = os.path.join(os.environ["CARMUSR"], "LOCAL_PLAN", path)
        return os.path.normpath(fullPath)
    def getExecuteCommand(self, binary, test):
        self.makeTemporary(test)
        tmpDir = self.tmpDirs[test]
        tmpDir = tmpDir.replace(self.getFullPath("") + os.sep,"")
        optparts = test.options.split()
        for ix in range(len(optparts) - 1):
            if optparts[ix] == "-s" and (ix + 1) < len(optparts):
                optparts[ix+1] = tmpDir
        options = string.join(optparts, " ")
        return binary + " " + options

class MatadorTestCaseInformation(optimization.TestCaseInformation):
    def __init__(self, suite, name):
        optimization.TestCaseInformation.__init__(self, suite, name)
    def isComplete(self):
        if not os.path.isdir(self.testPath()):
            return 0
        if not os.path.isfile(self.makeFileName("options")):
            return 0
        if not os.path.isfile(self.makeFileName("performance")):
            return 0
        return 1
    def makeImport(self):
        testPath = self.testPath()
        optionPath = self.makeFileName("options")
        perfPath = self.makeFileName("performance")
        createdPath = 0
        if not os.path.isdir(testPath):
            os.mkdir(testPath)
            createdPath = 1
        if not os.path.isfile(optionPath):
            dirName = self.chooseSubPlan()
            if dirName == None:
                if createdPath == 1:
                    os.rmdir(testPath)
                return 0
            subPlanDir = os.path.join(dirName, "APC_FILES")
            ruleSet = self.getRuleSetName(subPlanDir)
            newOptions = "-s " + self.getOptionPart(dirName) + " -r " + ruleSet
            open(optionPath,"w").write(newOptions + os.linesep)
        else:
            relPath = getOption(open(optionPath).readline().strip(), "-s")
            subPlanDir = os.path.join(os.environ["CARMUSR"], "LOCAL_PLAN", relPath, "APC_FILES")
        if not os.path.isfile(perfPath):
            perfContent = self.buildPerformance(subPlanDir)
            open(perfPath, "w").write(perfContent + os.linesep)
        return 1
    def getOptionPart(self, path):
        startPath = os.path.join(os.environ["CARMUSR"], "LOCAL_PLAN") + os.sep
        if path[0:len(startPath)] == startPath:
            return os.path.join(path[len(startPath) : len(path)])
        return os.path.normpath(path)
    def buildPerformance(self, subPlanDir):
        statusPath = os.path.join(subPlanDir, "status")
        if os.path.isfile(statusPath):
            lastLines = os.popen("tail -10 " + statusPath).xreadlines()
            for line in lastLines:
                if line.find("Total time:") == 0:
                    try:
                        timeparts = line.split(":")[-3:]
                        secs = int(timeparts[0]) * 60 * 60
                        secs += int(timeparts[1]) * 60
                        secs += int(timeparts[2])
                        return "CPU time   :     " + str(secs) + ".0 sec. on heathlands"
                    except:
                        pass
# Give some default that will not end it up in the short queue
        return "CPU time   :      2500.0 sec. on heathlands"

class MatadorTestSuiteInformation(optimization.TestSuiteInformation):
    def __init__(self, suite, name):
        optimization.TestSuiteInformation.__init__(self, suite, name)
        self.onlyEnvIsLacking = 0
    def isComplete(self):
        if not os.path.isdir(self.testPath()):
            return 0
        if not os.path.isfile(self.makeFileName("testsuite")):
            return 0
        self.onlyEnvIsLacking = 1
        if not os.path.isfile(self.makeFileName("environment")):
            return 0
        return 1
    def makeImport(self):
        if optimization.TestSuiteInformation.makeImport(self) == 0:
            return 0
        envPath = self.makeFileName("environment")
        stemEnvPath = self.filePath("environment")
        if envPath == stemEnvPath:
            return 1
        if not os.path.isfile(stemEnvPath):
            shutil.copyfile(envPath, stemEnvPath)
        if filecmp.cmp(envPath, stemEnvPath, 0) == 1:
            os.remove(envPath)
            if self.onlyEnvIsLacking == 1:
                return 0
        return 1
    
class ImportTest(optimization.ImportTest):
    def getTestCaseInformation(self, suite, name):
        return MatadorTestCaseInformation(suite, name)
    def getTestSuiteInformation(self, suite, name):
        return MatadorTestSuiteInformation(suite, name)
    
