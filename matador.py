helpDescription = """
The Matador configuration is based on the Carmen configuration. It will compile all static rulesets in the test
suite before running any tests, if the library file "matador.o" has changed since the static ruleset was last built.""" 

helpOptions = """-diag      - Run with diagnostics on. This will set the environment variables DIAGNOSTICS_IN and DIAGNOSTICS_OUT to
             both point at the subdirectory ./Diagnostics in the test case. It will also disable performance checking,
             as producing lots of text tends to slow down the program, and will tell the comparator to also
             compare the diagnostics found in the ./Diagnostics subdirectory.
"""

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

import carmen, os, shutil, filecmp, optimization, string, plugins, comparetest, unixConfig, sys

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
        if self.optionMap.has_key("diag"):
            os.environ["DIAGNOSTICS_IN"] = "./Diagnostics"
            os.environ["DIAGNOSTICS_OUT"] = "./Diagnostics"
        if os.environ.has_key("DIAGNOSTICS_IN"):
            print "Note: Running with Diagnostics on, so performance checking is disabled!"
    def __del__(self):
        if self.optionMap.has_key("diag"):
            del os.environ["DIAGNOSTICS_IN"]
            del os.environ["DIAGNOSTICS_OUT"]
    def addToOptionGroup(self, group):
        optimization.OptimizationConfig.addToOptionGroup(self, group)
        if group.name.startswith("How"):
            group.addSwitch("diag", "Use Matador Codebase diagnostics")
    def getPerformanceFileMaker(self):
        if self.optionMap.has_key("diag"):
            return None
        else:
            return optimization.OptimizationConfig.getPerformanceFileMaker(self)
    def getLibraryFile(self, app):
        raveName = app.getConfigValue("rave_name")
        if raveName == "matador":
            # Only matador supports dynamic linkage right now
            return os.path.join("data", "crc", string.upper(raveName), carmen.getArchitecture(app), raveName + ".o")
        else:
            return None
    def getVitalFiles(self, app):
        return optimization.OptimizationConfig.getVitalFiles(self, app) + \
               [ os.path.join(os.environ["CARMSYS"], self.getBinaryFile(app)) ]
    def getBinaryFile(self, app):
        return os.path.join("bin", carmen.getArchitecture(app), app.getConfigValue("rave_name"))
    def _getSubPlanDirName(self, test):
        subPlan = self._subPlanName(test)
        fullPath = os.path.join(os.environ["CARMUSR"], "LOCAL_PLAN", subPlan)
        return os.path.normpath(fullPath)
    def _subPlanName(self, test):
        subPlan = getOption(test.options, "-s")            
        if subPlan == None:
            # print help information and exit:
            return ""
        return subPlan
    def getRuleSetName(self, test):
        fromOptions = getOption(test.options, "-r")
        if fromOptions:
            return fromOptions
        outputFile = test.makeFileName("output")
        if os.path.isfile(outputFile):
            for line in open(outputFile).xreadlines():
                if line.find("Loading rule set") != -1:
                    finalWord = line.split(" ")[-1]
                    return finalWord.strip()
        subPlanDir = self._getSubPlanDirName(test)
        for line in open(os.path.join(subPlanDir, "APC_FILES", "problems")).xreadlines():
            if line.startswith("153"):
                return line.split(";")[3]
        return ""
    def printHelpDescription(self):
        print helpDescription
        optimization.OptimizationConfig.printHelpDescription(self)
    def printHelpOptions(self, builtInOptions):
        optimization.OptimizationConfig.printHelpOptions(self, builtInOptions)
        print helpOptions
    def printHelpScripts(self):
        optimization.OptimizationConfig.printHelpScripts(self)
        print helpScripts
    def setApplicationDefaults(self, app):
        optimization.OptimizationConfig.setApplicationDefaults(self, app)
        if os.environ.has_key("DIAGNOSTICS_IN"):
            app.addConfigEntry("copy_test_path", "Diagnostics/diagnostics.etab")
            app.addConfigEntry("compare_extension", "diag")
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

class MatadorTestCaseInformation(optimization.TestCaseInformation):
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
        outputPath = self.makeFileName("output")
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

            logFile = os.path.join(subPlanDir, "matador.log")
            if not os.path.isfile(outputPath) and os.path.isfile(logFile):
                shutil.copyfile(logFile, outputPath)
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
    def setUpSuite(self, suite):
        if suite.app.name == "cas":
            optimization.ImportTest.setUpSuite(self, suite)
        else:
            self.describe(suite, " failed: Can not import '" + suite.app.name + "' test suites!")

class ImportTestCase(optimization.ImportTestCase):
    def getOptions(self):
        return "-s " + self.getSubplanName()

class ImportTestSuite(optimization.ImportTestSuite):
    def hasStaticLinkage(self, carmUsr):
        resourceFile = os.path.join(carmUsr, "Resources", "CarmResources", "Customer.etab")
        if not os.path.isfile(resourceFile):
            return 0
        for line in open(resourceFile).xreadlines():
            if line.find("UseStaticLinking") != -1 and line.find("matador") != -1:
                parts = plugins.commasplit(line.strip())
                if parts[4].find("true") != -1:
                    return 1
        return 0
    def getCarmtmpPath(self, carmtmp, version=""):
        rootDir = "/carm/proj/matador/"
        if version == "":
            return os.path.join(rootDir, "master", carmtmp)
        elif version == "10":
            return os.path.join(rootDir, "carmen_10", "tmps_for_RD", "Matador", carmtmp)
        elif version == "9":
            return os.path.join(rootDir, "carmen_9.0_deliver", "tmps_for_Matador_9", carmtmp)

class MigrateApcTest(plugins.Action):
    def __init__(self):
        self.ruleSetMap = {}
        self.paramSetMap = {}
        self.app = None
    def __repr__(self):
        return "Migrating APC tests for"
    def migrateTest(self, testDir, optionsPath):
        os.chdir(testDir)
        apcOptionList = open("options.apc").readline().split()
        apcSubPlanDir = os.path.normpath(os.path.expandvars(apcOptionList[0]))
        dropApcFiles, apcFiles = os.path.split(apcSubPlanDir)
        matadorName = dropApcFiles + "_auto" + self.app.name
        print "Migrating test", os.path.basename(testDir)

        self.apcRulesetName = os.path.basename(apcOptionList[3])
        self.matRulesetName = self.ruleSetMap[self.apcRulesetName]
        print "Transforming ruleset from", self.apcRulesetName, "to", self.matRulesetName

        self.transform(os.path.join(dropApcFiles, "subplanHeader"), self.replaceRuleset)
        self.transform(os.path.join(apcSubPlanDir, "problems"), self.replaceRuleset)        
        self.transform(os.path.join(dropApcFiles, "subplanRules"), self.replaceParameters)
        self.transform(os.path.join(apcSubPlanDir, "rules"), self.replaceParameters)

        print "Creating subplan in dir", matadorName
        prefix = os.path.join(os.environ["CARMUSR"], "LOCAL_PLAN", "")
        shortMatName = matadorName.replace(prefix, "")
        # Commit the changes
        shutil.copytree(dropApcFiles, matadorName)
        matadorFull = os.path.join(matadorName, "APC_FILES")
        self.commitChange(dropApcFiles, matadorName, "subplanHeader")
        self.commitChange(dropApcFiles, matadorName, "subplanRules")
        self.commitChange(apcSubPlanDir, matadorFull, "problems")
        self.commitChange(apcSubPlanDir, matadorFull, "rules")
        open(optionsPath, "w").write("-s " + shortMatName + os.linesep)
        os.symlink(matadorFull, "APC_FILES")
    def transform(self, absPath, transformMethod):
        apcPath = self.getPath(absPath)
        matPath = os.path.basename(absPath) + "." + self.app.name
        file = open(matPath, "w")
        for line in open(apcPath).xreadlines():
            file.write(transformMethod(line))
        file.close()
        os.system("diff " + apcPath + " " + matPath)
        print "Changes in", os.path.basename(absPath), "OK?"
        response = sys.stdin.readline().strip()
    def commitChange(self, oldDir, newDir, fileName):
        oldPath = os.path.join(oldDir, fileName)
        if unixConfig.isCompressed(oldPath):
            os.remove(fileName)
        newFile = fileName + "." + self.app.name
        shutil.copyfile(newFile, os.path.join(newDir, fileName))
        os.remove(newFile)
    def replaceRuleset(self, line):
        return line.replace(self.apcRulesetName, self.matRulesetName)
    def replaceParameters(self, line):
        paramName = line.split()[0]
        if paramName in self.paramSetMap:
            return line.replace(paramName, self.paramSetMap[paramName])
        if paramName.find(".") != -1:
            module = paramName.split(".")[0]
            if module.find("builtin") == -1:
                return line.replace(module, self.app.fullName.lower())
        return line
    def getPath(self, absPath):
        if unixConfig.isCompressed(absPath):
            localName = os.path.basename(absPath) + ".Z"
            shutil.copyfile(absPath, localName)
            os.system("uncompress " + localName)
            return os.path.basename(absPath)
        return absPath
    def setUpSuite(self, suite):
        self.describe(suite)
        if not carmen.isUserSuite(suite):
            return
        for testline in open(suite.testCaseFile).readlines():
            if testline != '\n' and testline[0] != '#':
                testDir = os.path.join(suite.abspath, testline.strip())
                optionsPath = os.path.join(testDir, "options." + suite.app.name)
                if not os.path.isfile(optionsPath):
                    self.migrateTest(testDir, optionsPath)
    def setUpApplication(self, app):
        self.app = app
        mapFile = os.path.join(app.abspath, "remap_rulesets.etab")
        if not os.path.isfile(mapFile):
            raise plugins.TextTestError, "Cannot find ruleset mapping file at", mapFile
        self.setUpMapFile(mapFile, self.ruleSetMap)
        paramMapFile = os.path.join(os.environ["CARMSYS"], "carmusr_default", "crc", "etable", "remap_" + self.app.fullName.lower() + ".etab")
        if not os.path.isfile(paramMapFile):
            raise plugins.TextTestError, "Cannot find parameter mapping file at", paramMapFile
        self.setUpMapFile(paramMapFile, self.paramSetMap)
    def setUpMapFile(self, mapFile, mapToWrite):
        for line in open(mapFile).xreadlines():
            entries = plugins.commasplit(line)
            if len(entries) < 3:
                continue
            key = entries[0].replace('"', '')
            value = entries[1].replace('"', '')
            mapToWrite[key] = value

class PrintRuleValue(plugins.Action):
    def __repr__(self):
        return "Printing rule values for"
    def __call__(self, test):
        self.describe(test)
        rulesFile = os.path.join(os.environ["CARMUSR"], "LOCAL_PLAN", getOption(test.options, "-s"), "APC_FILES", "rules")
        for line in open(rulesFile).xreadlines():
            if line.find("index_group_generation TRUE") != -1:
                print test.getIndent() + "INDEX GROUPS"
    def setUpSuite(self, suite):
        self.describe(suite)

class CopyEnvironment(plugins.Action):
    def __repr__(self):
        return "Making environment.9 for"
    def setUpSuite(self, suite):
        targetFile = os.path.join(suite.abspath, "environment.9")
        if carmen.isUserSuite(suite) and os.path.isfile(targetFile):
            self.describe(suite)
            file = open(targetFile, "w")
            carmtmp = os.path.join("/carm/user_and_tmp/carmen_9.0_deliver/tmps_for_Matador_9", os.path.basename(os.path.normpath(os.environ["CARMTMP"])))
            print carmtmp
            file.write("CARMTMP:" + carmtmp + os.linesep)

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

