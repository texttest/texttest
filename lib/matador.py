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
from time import time, ctime
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
    def _getRuleSetNames(self, test):
        rulesets = []
        basicRuleSet = self.getBasicRuleSet(test)
        if basicRuleSet:
            rulesets.append(basicRuleSet)
        for extra in self.getExtraRollingStockRulesets(test):
            if not extra in rulesets:
                rulesets.append(extra)
        return rulesets
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
    def getExtraRollingStockRulesets(self, test):
        extras = []
        compRules = test.getEnvironment("COMPOSITION_OPTIMIZATION_RULESET")
        if compRules:
            extras.append(compRules)
        rotRules = test.getEnvironment("ROTATION_OPTIMIZATION_RULESET")
        if rotRules:
            extras.append(rotRules)
        return extras
    def getRuleBuildFilterer(self):
        return FilterRuleBuilds(self.getRuleSetNames, self.raveMode(), self.rebuildAllRulesets())
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
        diagDir["configuration_file_variable"] = "DIAGNOSTICS_FILE"
        diagDir["write_directory_variable"] = "DIAGNOSTICS_OUT"
        return diagDir
    def setApplicationDefaults(self, app):
        optimization.OptimizationConfig.setApplicationDefaults(self, app)
        self.itemNamesInFile[optimization.memoryEntryName] = "Memory consumption"
        self.itemNamesInFile[optimization.newSolutionMarker] = "Creating solution"
        self.itemNamesInFile[optimization.solutionName] = "Solution\."
        app.setConfigDefault("diagnostics", self.getDiagnosticSettings())
    def getCarmenEnvironment(self, app):
        envVars = optimization.OptimizationConfig.getCarmenEnvironment(self, app)
        envVars += [ ("CARMEN_PRODUCT", self.getProductName(app)) ]
        return envVars
    def getProductName(self, app):
        if app.name in [ "rso", "rot", "depot" ]:
            return "RailFleet"
        else:
            return "standard_gpc"
    def setEnvironment(self, test):
        optimization.OptimizationConfig.setEnvironment(self, test)
        if test.parent is None:
            test.setEnvironment("MATADOR_CRS_NAME", ravebased.getBasicRaveName(test))
        
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
        logFile = test.getFileName("features")
        if logFile:
            commandLine = "tail -100 " + logFile + " | " + self.grepCommand + " > /dev/null 2>&1"
            return os.system(commandLine) == 0
        else:
            return False

class SelectTests(guiplugins.SelectTests):
    def __init__(self, commandOptionGroup):
        guiplugins.SelectTests.__init__(self, commandOptionGroup)
        self.features = []
    def addSuites(self, suites):
        guiplugins.SelectTests.addSuites(self, suites)
        for suite in suites:
            featureFile = suite.getFileName("features")
            if featureFile:
                for featureName in plugins.readList(featureFile):
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

class MigrateFeatures(plugins.Action):
    def __call__(self, test):
        logFile = test.getFileName("output")
        if not logFile:
            return

        testDir = test.getDirectory()
        featuresFileName = os.path.join(testDir, "features." + test.app.name)
        if os.path.isfile(featuresFileName):
            return
        featuresFile = open(featuresFileName, "w")
        self.migrateFile(logFile, featuresFile)
        featuresFile.close()
        os.system("cvs add " + featuresFileName)
        import glob
        for versionFile in glob.glob(os.path.join(testDir, "output." + test.app.name + ".*")):
            self.migrateFile(versionFile)
    def migrateFile(self, logFile, featuresFile=None):
        newLogFileName = "output.new" 
        newLogFile = open(newLogFileName, "w")
        inSection = False
        for line in open(logFile).readlines():
            if line.find("---------Features") != -1:
                inSection = not inSection
            elif inSection:
                if featuresFile:
                    featuresFile.write(line)
            else:
                newLogFile.write(line)
        newLogFile.close()
        os.rename(newLogFileName, logFile)

class MigrateDiagnostics(plugins.Action):
    def __call__(self, test):
        os.chdir(test.getDirectory())
        if os.path.isfile("diagnostics.etab"):
            os.system("cvsmv.py diagnostics.etab logging." + test.app.name)

class CollectFeatures(plugins.Action):
    def __init__(self):
        self.allFeatures = []
        self.fileToWrite = None
    def __call__(self, test):
        logFile = test.getFileName("features")
        if not logFile:
            return
        for feature in plugins.readList(logFile):
            if feature not in self.allFeatures:
                self.allFeatures.append(feature)
    def setUpApplication(self, app):
        if not self.fileToWrite:
            self.fileToWrite = os.path.join(app.getDirectory(), "features." + app.name)
    def __del__(self):
        self.allFeatures.sort()
        file = open(self.fileToWrite, "w")
        for feature in self.allFeatures:
            file.write(feature + "\n")
    
class CreatePerformanceReport(guiplugins.SelectionAction):
    def __init__(self):
        guiplugins.SelectionAction.__init__(self)
        self.rootDir = ""
        self.versions = ["11", "12", "13", "master" ]
    def inToolBar(self): 
        return False
    def getMainMenuPath(self):
        return "_Optimization"
    def separatorBeforeInMainMenu(self):
        return True
    def getDialogType(self):
        return "guidialogs.CreatePerformanceReportDialog"
    def _getTitle(self):
        return "Create Performance Report..."
    def _getScriptTitle(self):
        return "create performance report for selected tests"
    def messageAfterPerform(self):
        return "Created performance report in " + self.rootDir
    def initialize(self):
        self.apps = {}
        self.testPaths = []
        self.timeStamp = time()
        self.createStyleFile()
    def performOnCurrent(self):
        self.initialize()
        for test in self.currTestSelection:
            self.collectTest(test)
        self.createMainIndexFile()
    def collectTest(self, test):
        self.apps[test.app.fullName] = test.app.fullName
        pathToTest = os.path.join(self.rootDir,
                                  os.path.join(test.app.fullName.lower(),
                                               os.path.join(test.getRelPath(), "index.html")))
        dir, file = os.path.split(os.path.abspath(pathToTest))
        try:
            os.makedirs(dir)
        except:
            pass # Dir exists already ...
        self.testPaths.append((test, pathToTest))
        
    def createStyleFile(self):
        backgroundColor = "#000000"
        linkColor = "#696969"
        headerColor = "#C9CFEE"
        tableBackgroundColor = "#EEEEEE"
        
        self.styleFilePath = os.path.join(self.rootDir, os.path.join("include", "performance_style.css"))
        try:
            os.makedirs(os.path.split(self.styleFilePath)[0])
        except:
            pass # Dir exists already ...
        file = open(self.styleFilePath, "w")
        file.write("body {\n font-family: Helvetica, Georgia, \"Times New Roman\", Times, serif;\n}\n\n")
        file.write("h2 {\n padding: 0pt 0pt 0pt 0pt;\n margin: 0pt 0pt 0pt 0pt;\n}\n\n")
        file.write("a:link, a:visited, a:hover {\n color: " + linkColor + ";\n text-decoration: none;\n}\n\na:hover {\n color: " + backgroundColor + ";\n text-decoration: underline;\n}\n\n")
        file.write("#navigationheader {\n background-color: " + headerColor + ";\n font-size: 8pt;\n margin: 0pt 0pt 5pt 0pt;\n}\n\n")
        file.write("#mainheader {\n background-color: " + headerColor + ";\n padding: 0pt 0pt 10pt 0pt;\n margin: 0pt 0pt 10pt 0pt;\n}\n\n")
        file.write("#testheader {\n background-color: " + headerColor + ";\n padding: 0pt 0pt 10pt 0pt;\n margin: 0pt 0pt 10pt 0pt;\n}\n\n")
        file.write("#maintableheader {\n font-weight: bold;\n background-color: " + tableBackgroundColor + ";\n padding: 0pt 5pt 0pt 5pt;\n}\n\n")
        file.write("#maintableheaderlast {\n font-weight: bold;\n background-color: " + tableBackgroundColor + ";\n padding: 0pt 5pt 0pt 5pt;\n border-bottom: thin solid;\n}\n\n")
        file.write("#maintablecell {\n padding: 0pt 5pt 0pt 5pt;\n}\n\n")
        file.write("#graphcaption {\n font-size: 8pt;\n font-weight: bold;\n}\n\n")
        file.write("#performancetableheader {\n font-weight: bold;\n background-color: " + tableBackgroundColor + ";\n}\n\n")
        file.write("#performancetable {\n font-size: 8pt;\n}\n\n")
        file.write("#detailstableheader {\n font-weight: bold;\n background-color: " + tableBackgroundColor + ";\n}\n\n")
        file.write("#detailstable {\n font-size: 8pt;\n}\n\n")
        file.write("#bestrowentry {\n background-color: #CEEFBD;\n}\n\n")
        file.write("#worstrowentry {\n background-color: #FF7777;\n}\n\n")
        file.write("#detailsnotext {\n font-family: courier;\n}\n\n")
        file.write("#detailstext {\n font-family: courier;\n margin: 5pt 0pt 0pt 0pt;\n padding: 5pt 0pt 0pt 5pt;\n border-left: thin solid;\n}\n\n")
        file.write("#mainpage {\n font-size: 8pt;\n}\n\n")
        file.write("#testpage {\n}\n\n")
        file.close()

    def createMainIndexFile(self):
        self.mainIndexFile = os.path.join(self.rootDir, "index.html")
        file = open(self.mainIndexFile, "w")
        file.write("<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.01 Transitional//EN\" \"http://www.w3.org/TR/html4/loose.dtd\">\n")
        file.write("<html>\n <head>\n  <meta http-equiv=\"Content-Type\" content=\"text/html; charset=iso-8859-1\">\n")
        file.write("  <title>Performance report created " + ctime(self.timeStamp) + "</title>\n  <link rel=\"stylesheet\" href=\"" + self.styleFilePath + "\" type=\"text/css\">\n </head>\n")
        file.write(" <body>\n")
        file.write("  <center><table width=\"80%\" border=\"0\"><tr><td align=\"center\">\n")
        file.write("   <div id=\"mainheader\"><h2>Performance report</h2><b>Applications:</b> ")
        for app in self.apps:
            file.write(app + " ")            
        file.write("<br><b>Created:</b> " + ctime(self.timeStamp) + "<br></div>\n")

        file.write("   <div id=\"mainpage\"><table width=\"100%\" border=\"0\">\n")        
        file.write("    <tr><td><div id=\"maintableheader\">&nbsp</div></td>")
        for version in self.versions:
            file.write("<td colspan=\"3\" align=\"center\" valign=\"middle\"><div id=\"maintableheader\">Version " + version + "</div></td>")
        file.write("</tr>\n")
        file.write("    <tr><td align=\"left\" valign=\"middle\"><div id=\"maintableheader\">Test case</div></td>")
        for version in self.versions:
            file.write("<td align=\"right\" valign=\"middle\"><div id=\"maintableheader\">Solution cost</div></td>")
            file.write("<td align=\"right\" valign=\"middle\"><div id=\"maintableheader\">CPU time</div></td>")
            file.write("<td align=\"right\" valign=\"middle\"><div id=\"maintableheader\">Time to worst (KPI)</div></td>")
        file.write("</tr>\n")
        for i in xrange(0, len(self.testPaths), 1):
            self.notify("Status", "Creating report for " + self.testPaths[i][0].getRelPath())
            self.notify("ActionProgress", "")
            pathToPrev = None
            if i > 0:
                pathToPrev = self.testPaths[i - 1]
            pathToNext = None
            if i < len(self.testPaths) - 1:
                pathToNext = self.testPaths[i + 1]
            performance, kpi = self.createTestFile(self.testPaths[i], pathToPrev, pathToNext, self.mainIndexFile)

            file.write("    <tr><td align=\"left\" valign=\"middle\"><div id=\"maintablecell\"><a href=\"" + self.testPaths[i][1] + "\">" + self.testPaths[i][0].getRelPath() + "</div></a></td>")
            row = []
            for version in self.versions:
                cost = "-"
                time = "-"                    
                if performance.has_key(version):
                    results = performance[version]
                    if len(results) > 0:
                        cost = results[len(results) - 1][1]
                        time = results[len(results) - 1][3]
                row.append([cost, time, kpi[version]])
            self.outputRow(file, "<td align=\"right\" valign=\"middle\">", "<div id=\"maintablecell\">", row, "</div>", "</td>")
            file.write("</tr>\n")
        file.write("   </table></div>\n")
        file.write("  </div></td></tr></table></center>\n </body>\n</html>\n")
        file.close()
                    
        # Create the html report for a single test case.
    def createTestFile(self, pathToTest, pathToPrev, pathToNext, pathToParent):
        # Extract info about cost, times and memory consumption at various points in time
        performance = self.getPerformance(pathToTest[0])

        # Open file, print some basic info
        file = open(pathToTest[1], "w")
        file.write("<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.01 Transitional//EN\" \"http://www.w3.org/TR/html4/loose.dtd\">\n")
        file.write("<html>\n <head>\n  <meta http-equiv=\"Content-Type\" content=\"text/html; charset=iso-8859-1\">\n")
        file.write("  <title>Performance of test " + pathToTest[0].getRelPath() + "</title>\n  <link rel=\"stylesheet\" href=\"" + self.styleFilePath + "\" type=\"text/css\">\n </head>\n")
        file.write(" <body>\n  <center><table width=\"80%\"><tr><td align=\"center\"><div id=\"testpage\">\n")
        file.write("   <div id=\"navigationheader\"><table width=\"100%\" border=\"0\"><tr><td width=\"33%\" align=\"left\">")
        if pathToPrev:
            file.write("<a href=\"" + pathToPrev[1] + "\"><< " + pathToPrev[0].getRelPath() + "</a>")
        file.write("</td><td width=\"33%\" align=\"center\"><a href=\"" + pathToParent + "\">Up</a></td><td width=\"33%\" align=\"right\">")
        if pathToNext:
            file.write("<a href=\"" + pathToNext[1] + "\">" + pathToNext[0].getRelPath() + " >></a>")
        file.write("</td></tr></table></div>\n")
        file.write("   <div id=\"testheader\"><h2>Performance report</h2><b>Test:</b> " + pathToTest[0].getRelPath() + "</b><br><b>Created:</b> " + ctime(self.timeStamp) + "</div>\n")

        self.outputGraphs(file, os.path.split(pathToTest[1])[0], performance)
        kpi = self.outputPerformance(file, performance)
        self.outputDetails(file, pathToTest)

        file.write("\n  </div></td></tr></table></center>\n </body>\n</html>\n")
        file.close()
        return performance, kpi

    def getPerformance(self, test):
        performance = {}
        for version in self.versions:            
            defaultFileName = test.getFileName("output", "master")
            fileName = test.getFileName("output", version)
            if not fileName or (fileName == defaultFileName and version != "master"):
                continue # Same as master, empty result vector ...

            file = open(fileName, "r")
            lines = file.readlines()
            latestCost = ""
            latestAssignment = ""
            latestSolution = ""
            results = []
            for line in lines:
                if line.find("Total cost of plan") != -1:
                    latestCost = line[line.rfind(":") + 2:].strip(" \n")
                elif line.find("Assignment percentage") != -1:
                    latestAssignment = line[line.rfind(":") + 2:].strip(" \n")
                elif line.find("Current Solution") != -1:
                    latestSolution = line[line.rfind(":") + 2:].strip(" \n")
                elif line.startswith("Memory consumption: "):
                    memory = line[line.find(":") + 2:line.find(" MB  ")].strip(" \n")
                    cpuTime = line[line.rfind(":  ") + 3:].strip(" \n")
                    results.append((latestSolution, latestCost, latestAssignment, cpuTime, memory))
            performance[version] = results
        return performance

    def outputGraphs(self, file, dir, performance):
        costGraphFile, assignmentGraphFile, memoryGraphFile = self.generateGraphs(dir, performance, "png")
        file.write("\n<! ===== Output comparison graphs ===== >\n\n")
        file.write("   <h3>Comparison graphs</h3>\n")
        file.write("   <table width=\"100%\" border=\"0\">\n    <tr>\n")
        file.write("     <td valign=\"center\" align=\"center\" width=\"33%\"><a href=\"" + costGraphFile + "\"><img src=\"" + costGraphFile + "\"></a></td>\n")
        file.write("     <td valign=\"center\" align=\"center\" width=\"33%\"><a href=\"" + assignmentGraphFile + "\"><img src=\"" + assignmentGraphFile + "\"></a></td>\n")
        file.write("     <td valign=\"center\" align=\"center\" width=\"33%\"><a href=\"" + memoryGraphFile + "\"><img src=\"" + memoryGraphFile + "\"></a></td>\n")
        file.write("    </tr>\n    <tr><td align=\"center\"><div id=\"graphcaption\">Solution cost progress.</div></td><td align=\"center\"><div id=\"graphcaption\">Assignment percentage progress.</div></td><td align=\"center\"><div id=\"graphcaption\">Memory consumption progress.</div></td></tr>\n   </table>\n")

    def generateGraphs(self, dir, performance, terminal):
        self.generateGraphData(dir, performance)
        return self.generateGraph(dir, "cost", "Time (minutes)", "Total cost of plan", terminal), \
               self.generateGraph(dir, "assignment", "Time (minutes)", "Assignment percentage", terminal), \
               self.generateGraph(dir, "memory", "Time (minutes)", "Memory consumption (Mb)", terminal)

    def generateGraph(self, dir, name, xLabel, yLabel, terminal):
        plotFileName = os.path.join(dir, name + "." + terminal)
        plotCommandFileName = os.path.join(dir, "plot_" + name + ".commands")
        plotCommandFile = open(plotCommandFileName, "w")
        plotCommandFile.write("set grid\nset xlabel \"" + xLabel + "\"\nset ylabel \"" + yLabel + "\"\n")
        plotCommandFile.write("set terminal " + terminal + "  picsize 350 280\nset output \"" + plotFileName + "\"\nplot ")
        allPlotCommands = ""
        for version in self.versions:
            fileName = os.path.join(dir, name + "_" + version + ".data")
            if os.path.isfile(fileName) and os.stat(fileName).st_size > 0:
                allPlotCommands += "\"" + fileName + "\" using 1:2 with linespoints title \"Version " + version + "\","
        plotCommandFile.write(allPlotCommands.strip(","))
        plotCommandFile.close()

        plotCommand = "gnuplot -persist -background white " + plotCommandFileName
        stdin, stdouterr = os.popen4(plotCommand)
                
        return os.path.split(plotFileName)[1]
    
    def generateGraphData(self, dir, performance):
        # In the test dir, create files suitable for gnuplot containing
        # cost/time, assignment/time and memory/version.
        for version in self.versions:
            if not performance.has_key(version):
                continue
            
            fileNameSuffix = "_" + version + ".data"
            costFile = open(os.path.join(dir, "cost" + fileNameSuffix), "w")
            assignmentFile = open(os.path.join(dir, "assignment" + fileNameSuffix), "w")
            memoryFile = open(os.path.join(dir, "memory" + fileNameSuffix), "w")

            results = performance[version]              
            for s, cost, ass, time, memory in results:
                timeInMinutes = str(plugins.getNumberOfMinutes(time))
                costFile.write(timeInMinutes + " " + cost + "\n")
                assignmentFile.write(timeInMinutes + " " + ass + "\n")
                memoryFile.write(timeInMinutes + " " + memory + "\n")
            
            costFile.close()
            assignmentFile.close()
            memoryFile.close()
        
    def outputPerformance(self, file, performance):
        file.write("\n<! ===== Output performance measures ===== >\n\n")
        file.write("   <h3>Performance measures</h3>\n")
        columnWidth = str(int(100 / (len(self.versions) + 1)))

        file.write("   <div id=\"performancetable\">\n    <table width=\"100%\" border=\"0\">\n     <tr><td width=\"" + columnWidth + "%\"><div id=\"performancetableheader\">&nbsp</div></td>")
        for version in self.versions:
            file.write("<td align=\"center\" width=\"" + columnWidth + "%\"><div id=\"performancetableheader\">Version " + version + "</div></td>")
        file.write("</tr>\n")

        categories = ["Number of solutions:", "Best solution cost:", "Best assignment %:", "Total CPU time:", "Max. memory consumption:"]
        for i in xrange(0, len(categories), 1):
            file.write("     <tr><td align=\"right\" valign=\"middle\"><div id=\"performancetableheader\">" + categories[i] + "</div></td>")
            row = []
            for version in self.versions:
                data = "-"
                if performance.has_key(version):
                    results = performance[version]
                    if len(results) > 0:
                        data = results[len(results) - 1][i]
                row.append([data])
            self.outputRow(file, "<td align=\"right\" valign=\"top\">", "", row, "", "</td>", i > 0)
            file.write("</tr>\n")

        # 'KPI' - Time to reach a solution as good as the worst solution found by any version
        worstSolution = -1000000000
        for version in self.versions:
            if performance.has_key(version):
                results = performance[version]
                if len(results) > 0:
                    lastSolution = int(results[len(results) - 1][1])
                    if lastSolution > worstSolution:
                           worstSolution = lastSolution
            
        file.write("     <tr><td align=\"right\" valign=\"middle\"><div id=\"performancetableheader\">Time to solution " + str(worstSolution) + ":</div></td>")        
        row = []
        kpi = {}
        for version in self.versions:
            data = "-"
            if performance.has_key(version):
                results = performance[version]
                for iter in results:
                    if int(iter[1]) <= worstSolution:
                        data = iter[3]                        
                        break
            kpi[version] = data
            row.append([data])
        self.outputRow(file, "<td align=\"right\" valign=\"top\">", "", row, "", "</td>")            
        file.write("</table>\n   </div>\n")
        return kpi

    def outputDetails(self, file, pathToTest):
        file.write("\n<! ===== Output performance details ===== >\n\n")
        file.write("   <h3>Performance details</h3>\n")
        file.write("   <div id=\"detailstable\">\n    <table width=\"100%\" border=\"0\">\n     <tr>")
        for version in self.versions:
            file.write("<td align=\"center\" width=\"" + str(int(100 / len(self.versions))) + "%\"><div id=\"detailstableheader\">Version " + version + "</div></td>")
        file.write("</tr>\n     <tr>")
        for version in self.versions:
            timerInfo = self.getTimerInfo(pathToTest[0], version)
            if timerInfo == "Same as master" or timerInfo == "No detailed time information could be found":
                file.write("<td align=\"center\" valign=\"middle\"><div id=\"detailsnotext\">" + timerInfo + "</div></td>")
            else:
                file.write("<td align=\"right\" valign=\"top\"><div id=\"detailstext\">" + timerInfo + "</div></td>")
        file.write("</tr>\n    </table>\n   </div>\n")

    def getTimerInfo(self, test, version):
        # Get output file for this version
        defaultFileName = test.getFileName("output", "master")
        fileName = test.getFileName("output", version)
        if not fileName or (fileName == defaultFileName and version != "master"):
            return "Same as master"
        
        # Get lines from (but excluding) '----------Timers'
        # to '-----------Timers End' ...
        file = open(fileName, "r")
        lines = file.readlines()
        info = ""
        includeLine = False
        for line in lines:
            fixedLine = line.strip(" \n")
            if line.startswith("----------------------------Timers"):
                fixedLine = fixedLine[6:-6]
                includeLine = True
            if line.startswith("--------------------------Timers End"):
                break
            if includeLine:
                info += fixedLine.replace("............:", ":") + "<br>"
            
        if info == "":
            info = "No detailed time information could be found"
        
        return info

    # Observe: data is a vector of vectors.
    def outputRow(self, file, prefix, innerPrefix, data, innerSuffix, suffix, markExtremes = True):
        if len(data) == 0:
            return 

        least = data[0][:]
        largest = data[0][:]
        for d in data:
            for i in xrange(0, len(d), 1):
                if d[i] == "-":
                    continue
                comp1 = self.compareValues(d[i], largest[i])
                comp2 = self.compareValues(least[i], d[i])
                if largest[i] == "-" or comp1 == 1:
                    largest[i] = d[i]
                if least[i] == "-" or comp2 == 1:
                    least[i] = d[i]

        for d in data:
            for i in xrange(0, len(d), 1):            
                if markExtremes and d[i] != "-" and d[i] == least[i]: # 'Best'
                    file.write(prefix + "<div id=\"bestrowentry\">" + innerPrefix + d[i] + innerSuffix + "</div>" + suffix)
                elif markExtremes and d[i] != "-" and d[i] == largest[i]: # 'Worst'
                    file.write(prefix + "<div id=\"worstrowentry\">" + innerPrefix + d[i] + innerSuffix + "</div>" + suffix)
                else:
                    file.write(prefix + innerPrefix + d[i] + innerSuffix + suffix)                

    # -1 means v1 < v2, 0 v1 == v2, 1 v1 > v2
    def compareValues(self, v1, v2):
        try:
            # Compare as ints, if possible ...
            realV1 = int(v1)
            realV2 = int(v2)
            if realV1 < realV2:
                return -1
            elif realV1 > realV2:
                return 1
            else:
                return 0
        except:
            if v1 < v2:
                return -1
            elif v1 > v2:
                return 1
            else:
                return 0
            
class PerformanceReportScript(plugins.ScriptWithArgs):
    dirKey = "dir"
    versionsKey = "versions"
    def __init__(self, args = []):
        self.creator = CreatePerformanceReport()
        self.args = self.parseArguments(args)
        if self.args.has_key(self.dirKey):
            self.creator.rootDir = self.args[self.dirKey]
        if self.args.has_key(self.versionsKey):            
            self.creator.versions = self.args[self.versionsKey].replace(" ", "").split(",")
        self.creator.initialize()
    def __call__(self, test):
        self.creator.collectTest(test)
    def __del__(self):
        self.creator.createMainIndexFile()

guiplugins.interactiveActionHandler.actionStaticClasses.append(CreatePerformanceReport)
guiplugins.interactiveActionHandler.actionExternalClasses.append(optimization.PlotTestInGUI)
