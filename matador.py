helpDescription = """
The Matador configuration is based on the Rave-based configuration. It will compile all static rulesets in the test
suite before running any tests, if the library file "matador.o" has changed since the static ruleset was last built.""" 

helpScripts = """matador.ImportTest         - Import new test cases and test users.
                             The general principle is to add entries to the "testsuite.<app>" file and then
                             run this action, typcally 'texttest -a <app> -s matador.ImportTest'. The action
                             will then find the new entries (as they have no corresponding subdirs) and
                             ask you for either new CARMUSR and CARMTMP (for new user) or new subplan
                             directory (for new tests). Also for new tests it is neccessary to have an
                             'APC_FILES' subdirectory created by Studio which is to be used as the
                             'template' for temporary subplandirs as created when the test is run.
                             The action will look for available subplandirectories under
                             CARMUSR and present them to you.
matador.TimeSummary         - Show a summary of 'useful' time in generation solutions.
                            The idea is that generation time and optimization time is considered useful and
                            compared to the total time. Output is like:
                               52% 14:45 RD_klm_cabin::index_groups_test
                            First item is how much time in percent was generation and optimization.
                            Second item is total runtime in hours:minutes of the test
                            Third item is the name of the test

                            Currently supports these options:
                             - sd
                               Display the solution details, ie useful percent for each solution
                             - v=version
                               Print result for specific version
matador.MigrateApcTest      - Take a test present in APC and migrate it to Matador/Picador. Before running
                            the script, make sure that the test is fully present for APC (use apc.ImportTest first if
                            it wasn't there yet) and that an entry is added for it in the testsuite file for Matador/Picador.
                            Also make sure that the file remap_rulesets.etab (under Testing/Automatic/<dirname>) is up to
                            date with the corresponding ruleset that you are migrating, and that the parameter transform table
                            remap_<app>.etab (installed into carmusr_default) is up to date with the latest parameter
                            settings.
                            The script will then replace the ruleset in the subplanHeader and problems
                            files, showing you the differences locally. Press ^C if anything is wrong. It will also
                            transform the module parameters in subplanRules and rules, again showing you the differences
                            as above. When all this has been accepted, it will commit the changes, copying the subplan,
                            making the changes it has shown, and writing an options.<app> file.
"""

import ravebased, os, shutil, filecmp, optimization, string, plugins, comparetest, unixonly, sys, guiplugins
from optimization import GenerateWebPages

def getConfig(optionMap):
    return MatadorConfig(optionMap)

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

class MatadorConfig(optimization.OptimizationConfig):
    def _subPlanName(self, test):
        subPlan = getOption(test, "-s")            
        if subPlan == None:
            # print help information and exit:
            return ""
        return subPlan
    def getRuleSetName(self, test):
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
        return ""
    def getRuleBuildFilterer(self):
        return FilterRuleBuilds(self.getRuleSetName, self.rebuildAllRulesets())
    def filesFromRulesFile(self, test, rulesFile):
        scriptFile = self.getRuleSetting(test, "script_file_name")
        if scriptFile:
            return [ ("Script", self.getScriptPath(test, scriptFile)) ]
        else:
            return []
    def getRuleSetting(self, test, paramName):
        raveParamName = "raveparameters." + test.app.name + test.app.versionSuffix()
        raveParamFile = test.makePathName(raveParamName)
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
    def getTestComparator(self):
        return MakeComparisons(optimization.OptimizationTestComparison, self.getRuleSetting)
    def getScriptPath(self, test, file):
        carmusr = test.getEnvironment("CARMUSR")
        fullPath = os.path.join(carmusr, "apc_scripts", file)
        if os.path.isfile(fullPath):
            return fullPath
        fullPath = os.path.join(carmusr, "matador_scripts", file)
        return fullPath
    def printHelpDescription(self):
        print helpDescription
        optimization.OptimizationConfig.printHelpDescription(self)
    def printHelpScripts(self):
        optimization.OptimizationConfig.printHelpScripts(self)
        print helpScripts
    def getDiagnosticSettings(self):
        diagDir = {}
        diagDir["configuration_file"] = "diagnostics.etab"
        diagDir["input_directory_variable"] = "DIAGNOSTICS_IN"
        diagDir["write_directory_variable"] = "DIAGNOSTICS_OUT"
        return diagDir
    def setApplicationDefaults(self, app):
        optimization.OptimizationConfig.setApplicationDefaults(self, app)
        self.itemNamesInFile[optimization.memoryEntryName] = "Memory"
        self.itemNamesInFile[optimization.newSolutionMarker] = "Creating solution"
        self.itemNamesInFile[optimization.solutionName] = "Solution\."
        self.itemNamesInFile["unassigned slots"] = "slots \(unassigned\)"
        # Add here list of entries that should not increase, paired with the methods not to check
        self.noIncreaseExceptMethods[optimization.costEntryName] = [ "SolutionLegaliser", "initial" ]
        self.noIncreaseExceptMethods["crew with illegal rosters"] = []
        self.noIncreaseExceptMethods["broken hard trip constraints"] = [ "MaxRoster" ]
        self.noIncreaseExceptMethods["broken hard leg constraints"] = [ "MaxRoster" ]
        self.noIncreaseExceptMethods["broken hard global constraints"] = [ "MaxRoster" ]
        app.setConfigDefault("diagnostics", self.getDiagnosticSettings())

class MakeComparisons(comparetest.MakeComparisons):
    def __init__(self, testComparisonClass, getRuleSetting):
        comparetest.MakeComparisons.__init__(self, testComparisonClass)
        self.getRuleSetting = getRuleSetting
    def __call__(self, test):
        if self.isSeniority(test):
            self.testComparisonClass = comparetest.TestComparison
        else:
            self.testComparisonClass = optimization.OptimizationTestComparison
        comparetest.MakeComparisons.__call__(self, test)
    def isSeniority(self, test):
        ruleVal = self.getRuleSetting(test, "map_seniority")
        return ruleVal and not ruleVal.startswith("#")

def staticLinkageInCustomerFile(carmUsr):
    resourceFile = os.path.join(carmUsr, "Resources", "CarmResources", "Customer.etab")
    if not os.path.isfile(resourceFile):
        return 0
    for line in open(resourceFile).xreadlines():
        if line.find("UseStaticLinking") != -1 and line.find("matador") != -1:
            parts = plugins.commasplit(line.strip())
            if parts[4].find("true") != -1:
                return 1
    return 0

class ImportTestCase(optimization.ImportTestCase):
    def getOptions(self, suite):
        return "-s " + self.getSubplanName()

class ImportTestSuite(ravebased.ImportTestSuite):
    def hasStaticLinkage(self, carmUsr):
        return staticLinkageInCustomerFile(carmUsr)
    def getCarmtmpPath(self, carmtmp):
        return os.path.join("${TEST_DATA_ROOT}/carmtmps/${MAJOR_RELEASE_ID}/${ARCHITECTURE}", carmtmp)

class FilterRuleBuilds(ravebased.FilterRuleBuilds):
    def assumeDynamicLinkage(self, libFile, carmUsr):
        return not staticLinkageInCustomerFile(carmUsr)

class PrintRuleValue(plugins.Action):
    def __init__(self, args = []):
        self.variable = args[0]
    def __repr__(self):
        return "Printing rule values for"
    def __call__(self, test):
        rulesFile = os.path.join(os.environ["CARMUSR"], "LOCAL_PLAN", getOption(test, "-s"), "APC_FILES", "rules")
        for line in open(rulesFile).xreadlines():
            if line.find(self.variable + " TRUE") != -1:
                print test.getIndent() + self.variable + " in " + repr(test)   
    def setUpSuite(self, suite):
        self.describe(suite)

class UpdateXpressVersion(plugins.Action):
    def __repr__(self):
        return "Updating XPRESS version for"
    def __call__(self, test):
        self.describe(test)
        errFile = test.getFileName("errors")
        newErrFile = test.getFileName("new_errors")
        writeFile = open(newErrFile, "w")
        for line in open(errFile).xreadlines():
            writeFile.write(line.replace("15.10.04", "15.10.06"))
        writeFile.close()
        os.rename(newErrFile, errFile)
        os.system("cvs diff " + errFile)
                  
class CopyEnvironment(plugins.Action):
    def __repr__(self):
        return "Making environment.ARCH for"
    def setUpSuite(self, suite):
        versions = [ "", ".10", ".9" ]
        if ravebased.isUserSuite(suite):
            self.describe(suite)
            for version in versions:
                oldFile = os.path.join(suite.abspath, "environment.cas" + version)
                if not os.path.isfile(oldFile):
                    return

                if len(version) == 0:
                    oldcarmtmp = self.getCarmtmp(oldFile)
                    root, local = os.path.split(os.path.normpath(oldcarmtmp))
                    newcarmtmp = self.getNewCarmtmp(oldcarmtmp, local)
                    self.replaceInFile(oldFile, oldcarmtmp, newcarmtmp)
                else:
                    os.system("cvs rm -f " + oldFile)
                archs = self.getArchs(version)
                for arch in archs:
                    targetFile = oldFile + "." + arch
                    if os.path.isfile(targetFile):
                        os.system("cvs rm -f " + targetFile)
    def getArchs(self, version):
        archs = [ "sparc", "parisc_2_0", "powerpc" ]
        if len(version) == 0:
            archs.append("sparc_64")
        return archs
    def getNewCarmtmp(self, oldcarmtmp, local):
        basePath = "${CARMSYS}"
        if oldcarmtmp.find("CARMSYS") == -1:
            basePath = "/carm/proj/matador/carmtmps/${MAJOR_RELEASE_ID}"
        return os.path.join(basePath, "${ARCHITECTURE}", local)
    def makeCarmtmpFile(self, targetFile, carmtmp):
        file = open(targetFile, "w")
        print carmtmp
        file.write("CARMTMP:" + carmtmp + os.linesep)
        file.close()
        os.system("cvs add " + targetFile)
    def getCarmtmp(self, file):
        for line in open(file).xreadlines():
            if line.startswith("CARMTMP"):
                name, carmtmp = line.strip().split(":")
                return carmtmp
    def replaceInFile(self, oldFile, oldVal, newVal):
        newFileName = oldFile + ".new"
        newFile = open(newFileName, "w")
        for line in open(oldFile).xreadlines():
            newFile.write(line.replace(oldVal, newVal))
        newFile.close()
        os.rename(newFileName, oldFile)
        os.system("cvs diff " + oldFile)
        
class TimeSummary(plugins.Action):
    def __init__(self, args = []):
        self.timeVersions = [ "" ]
        self.timeStates = [ "" ]
        self.scaleTime = 0
        self.useTmpStatus = 0
        self.suite = ""
        self.solutionDetail = 0
        self.genTime = 1
        self.optTime = 1
        # Must be last in the constructor
        self.interpretOptions(args)
    def __repr__(self):
        return "Timing statistics"
    def interpretOptions(self, args):
        for ar in args:
            arr = ar.split("=")
            if arr[0]=="v":
                self.timeVersions = arr[1].split(",")
            elif arr[0]=="sd":
                self.solutionDetail = 1
            elif arr[0]=="opt":
                self.genTime = 0
                self.optTime = 1
            elif arr[0]=="gen":
                self.optTime = 0
                self.genTime = 1
            else:
                print "Unknown option " + arr[0]
    def setUpSuite(self, suite):
        self.suite = suite.name
    # Interactive stuff
    def getTitle(self):
        return "Time statistics"
    def getArgumentOptions(self):
        options = {}
        options["v"] = "Versions to plot"
        return options
    def getSwitches(self):
        switches = {}
        switches["sd"] = "Solution detail(%)"
        return switches
    def __call__(self, test):
        totTime = optimization.timeEntryName
        genTime = "Generation time"
        optTime = "Optimization time"
        entries = [ genTime, optTime ]
        for version in self.timeVersions:
            try:
                optRun = optimization.OptimizationRun(test, version, [ totTime ], entries, self.scaleTime, self.useTmpStatus, self.timeStates[0])
            except plugins.TextTestError:
                print "No status file does exist for test " + test.app.name + "::" + test.name + "(" + version + ")"
                continue
            sumTot = 0
            sumGen = 0
            sumOpt = 0
            lastTotTime = 0;
            usePercent = []
            hasTimes = 0
            for solution in optRun.solutions:
                if solution.has_key(genTime) and solution.has_key(optTime):
                    hasTimes = 1
                    totalTime = int(solution[totTime] * 60) - lastTotTime
                    if totalTime > 0:
                        sumTot += totalTime
                        useFul = 0
                        if self.genTime:
                            sumGen += solution[genTime]
                            useFul = solution[genTime] + solution[optTime]
                        if self.optTime:
                            sumOpt += solution[optTime]
                            useFul += solution[optTime]
                        usePercent.append(str(int(100.0* useFul / totalTime)))
                    else:
                        usePercent.append("--")
                lastTotTime = int(solution[totTime] * 60)
            if sumTot > 0:
                sumUse = int(100.0 * (sumGen + sumOpt) / sumTot)
            else:
                sumUse = 100
            hrs = sumTot / 3600
            mins = (sumTot - hrs * 3600) / 60
            if sumTot > 60 and hasTimes:
                print str(sumUse)+"%", str(hrs) + ":" + str(mins), self.suite + "::" + test.name
                if self.solutionDetail:
                    print "   ", string.join(usePercent," ")

class CleanSubplans(plugins.Action):
    def __init__(self):
        self.config = MatadorConfig(None)
        from sets import Set
        self.preservePaths = Set([])
        self.preserveNames = [ "APC_FILES", "etable" ]
        self.preserveUsers = [ "/carm/proj/matador/carmusrs/master/RD_dl_cbs_v13", \
                               "/carm/proj/matador/carmusrs/carmen_10/RD_song_cas_v10_user", \
                               "/carm/proj/matador/carmusrs/carmen_12/RD_strict_seniority_user" ]
    def __repr__(self):
        return "Cleaning subplans for"
    def __call__(self, test):
        subplan = self.config._getSubPlanDirName(test)
        self.addAll(subplan)
        realpath = self.realpath(subplan)
        if realpath != subplan and realpath.find("LOCAL_PLAN") != -1:
            self.addAll(realpath)
    def addAll(self, path):
        self.preservePaths.add(path)
        dir, local = os.path.split(path)
        if not dir.endswith("LOCAL_PLAN"):
            self.addAll(dir)
    def setUpSuite(self, suite):
        self.describe(suite)
        if ravebased.isUserSuite(suite):
            carmdataVar, carmdata = ravebased.getCarmdata(suite)
            print suite.getIndent() + "Collecting subplans for " + carmdataVar + "=" + carmdata
            self.preservePaths.clear()
    def realpath(self, path):
        return os.path.normpath(os.path.realpath(path).replace("/nfs/vm", "/carm/proj"))
    def tearDownSuite(self, suite):
        if ravebased.isUserSuite(suite):
            if suite.getEnvironment("CARMUSR") in self.preserveUsers:
                print "Ignoring for Curt", suite
            else:
                self.removeUnused()
    def removeUnused(self):
        localplanPath = self.config._getLocalPlanPath(None)
        before = self.getDiskUsage(localplanPath)
        print "Disk usage before", before, "MB"
        self.removeUnder(localplanPath)
        after = self.getDiskUsage(localplanPath)
        print "Removed", before - after, "MB of the original", before
    def removeUnder(self, path):
        for file in os.listdir(path):
            if file in self.preserveNames or file.lower().find("env") != -1:
                continue
            fullPath = os.path.join(path, file)
            if os.path.isdir(fullPath) and not os.path.islink(fullPath):
                if fullPath in self.preservePaths:
                    self.removeUnder(fullPath)
                else:
                    print "Removing unused directory", fullPath, "..."
                    try:
                        shutil.rmtree(fullPath)
                    except:
                        print "FAILED!", str(sys.exc_value)
    def getDiskUsage(self, dir):
        output = os.popen("du -s " + dir).read()
        return int(output.split()[0]) / 1000

class PrintStrings(plugins.Action):
    def __init__(self):
        self.strings = []
    def __call__(self, test):
        logFile = test.getFileName("output")
        for line in open(logFile).readlines():
            line = line.strip()
            if len(line) == 0:
                continue
            pos = line.find(".:")
            if pos != -1:
                line = line[:pos + 2]
            if line in self.strings:
                continue
            self.strings.append(line)
            print line

class FeatureFilter(plugins.Filter):
    def __init__(self, features):
        self.grepCommand = "grep -E '" + string.join(features, "|") + "'"
    def acceptsTestCase(self, test):    
        logFile = test.getFileName("output")
        if logFile:
            commandLine = "tail -100 " + logFile + " | " + self.grepCommand + " > /dev/null 2>&1"
            return os.system(commandLine) == 0
        else:
            return False

class SelectTests(guiplugins.SelectTests):
    def __init__(self):
        guiplugins.SelectTests.__init__(self)
        self.features = []
    def addSuite(self, suite):
        guiplugins.SelectTests.addSuite(self, suite)
        featureFile = suite.getFileName("features")
        if not featureFile:
            return
        for line in open(featureFile).readlines():
            parts = line.split()
            if len(parts) > 0:
                featureName = line.replace("\n", "")
                self.addSwitch(featureName, featureName, 0)
                self.features.append(featureName)
    def getFilterList(self, app):
        filters = guiplugins.SelectTests.getFilterList(self, app)    
        selectedFeatures = self.getSelectedFeatures()
        if len(selectedFeatures) > 0:
            guiplugins.guilog.info("Selected " + str(len(selectedFeatures)) + " features...")
            filters.append(FeatureFilter(selectedFeatures))
        return filters
    def getSelectedFeatures(self):
        result = []
        for feature in self.features:
            if self.optionGroup.getSwitchValue(feature, 0):
                result.append(feature)
        return result

guiplugins.interactiveActionHandler.actionPostClasses.append(optimization.PlotTestInGUI)
