helpDescription = """
The apc configuration is based on the Carmen configuration. It will compile all rulesets in the test
suite before running any tests, if the library file "libapc.a" has changed since the ruleset was last built.

It uses a special ruleset building strategy on the linux platforms, such that rebuilding the APC binary
after a small change to APC will be really quick. It does so by not invoking 'crc_compile', instead
it makes its own link command. By using the "-rulecomp" flag you can avoid building the ruleset with
this special strategy.

It will fetch the optimizer's status file from the subplan (the "status" file) and write it for
comparison as the file status.<app> after each test has run."""

helpOptions = """
"""

helpScripts = """apc.ImportTest             - Import new test cases and test users.
                             The general principle is to add entries to the "testsuite.apc" file and then
                             run this action, typcally 'texttest -a apc -s apc.ImportTest'. The action
                             will then find the new entries (as they have no corresponding subdirs) and
                             ask you for either new CARMUSR (for new user) or new subplan directory
                             (for new tests). Note that CARMTMP is assigned for you. Also for new tests
                             it is neccessary to have an 'APC_FILES' subdirectory created by Studio which
                             is to be used as the 'template' for temporary subplandirs as created when
                             the test is run. The action will look for available subplandirectories under
                             CARMUSR and present them to you.

apc.PlotApcTest [options]  - Displays a gnuplot graph with the cpu time (in minutes) versus total cost. 
                             The data is extracted from the status file of test(s), and if the test is
                             currently running, the temporary status file is used, see however the
                             option nt below. All tests selected are plotted in the same graph.
                             The following options are supported:
                             - r=range
                               The x-axis has the range range. Default is the whole data set. Example: 60:
                             - p=an absolute file name
                               Prints the graph to a postscript file instead of displaying it.
                             - i=item
                               Which item to plot from the status file. Note that whitespaces are replaced
                               by underscores. Default is TOTAL cost. Example: i=overcover_cost.
                             - s
                               Plot against solution number instead of cpu time.
                             - nt
                               Do not use status file from the currently running test.
                             - v=v1,v2
                               Plot multiple versions in same dia, ie 'v=,9' means master and version 9

apc.UpdateCvsIgnore        - Make the .cvsignore file in each test directory identical to 'cvsignore.master'

apc.StartStudio            - Start ${CARMSYS}/bin/studio with CARMUSR and CARMTMP set for specific test
                             This is intended to be used on a single specified test and will terminate
                             the testsuite after it starts Studio. It is a simple shortcut to set the
                             correct CARMSYS etc. environment variables for the test and run Studio.
"""

import default, carmen, lsf, performance, os, sys, stat, string, shutil, optimization, plugins, math, filecmp

def getConfig(optionMap):
    return ApcConfig(optionMap)

class ApcConfig(optimization.OptimizationConfig):
    def __init__(self, optionMap):
        optimization.OptimizationConfig.__init__(self, optionMap)
        self.subplanManager = ApcSubPlanDirManager(self)
    def getProgressReportBuilder(self):
        return MakeProgressReport(self.optionValue("prrep"))
    def getLibraryFile(self):
        return os.path.join("data", "apc", carmen.architecture, "libapc.a")
    def getSubPlanFileName(self, test, sourceName):
        return self.subplanManager.getSubPlanFileName(test, sourceName)
    def getCompileRules(self, staticFilter):
        libFile = self.getLibraryFile()
        if self.isNightJob():
            ruleCompile = 1
        else:
            ruleCompile = self.optionMap.has_key("rulecomp")
        return ApcCompileRules(self.getRuleSetName, libFile, staticFilter, ruleCompile)
    def getTestCollator(self):
        subActions = [ optimization.OptimizationConfig.getTestCollator(self) ]
        subActions.append(RemoveLogs())
        subActions.append(optimization.ExtractSubPlanFile(self, "status", "status"))
        subActions.append(optimization.RemoveTemporarySubplan(self.subplanManager))
        return plugins.CompositeAction(subActions)
    def getRuleSetName(self, test):
        fileName = test.makeFileName("options")
        if os.path.isfile(fileName):
            optionLine = open(fileName).readline()
            options = optionLine.split()
            for option in options:
                if option.find("crc" + os.sep + "rule_set") != -1:
                    return option.split(os.sep)[-1]
        return None
    def getExecuteCommand(self, binary, test):
        return self.subplanManager.getExecuteCommand(binary, test)
    def printHelpDescription(self):
        print helpDescription
        optimization.OptimizationConfig.printHelpDescription(self)
    def printHelpOptions(self, builtInOptions):
        optimization.OptimizationConfig.printHelpOptions(self, builtInOptions)
        print helpOptions
    def printHelpScripts(self):
        optimization.OptimizationConfig.printHelpScripts(self)
        print helpScripts

class ApcSubPlanDirManager(optimization.SubPlanDirManager):
    def __init__(self, config):
        optimization.SubPlanDirManager.__init__(self, config)
    def getSubPlanDirFromTest(self, test):
        statusFile = os.path.normpath(os.path.expandvars(test.options.split()[1]))
        dirs = statusFile.split(os.sep)[:-2]
        return os.path.normpath(string.join(dirs, os.sep))
    def getExecuteCommand(self, binary, test):
        self.makeTemporary(test)
        options = test.options.split(" ")
        tmpDir = self.tmpDirs[test]
        dirName = os.path.join(self.getSubPlanDirName(test), self.getSubPlanBaseName(test))
        dirName = os.path.normpath(dirName)
        options[0] = os.path.normpath(options[0]).replace(dirName, tmpDir)
        options[1] = os.path.normpath(options[1]).replace(dirName, tmpDir)
        return binary + " " + string.join(options, " ")
    
class ApcCompileRules(carmen.CompileRules):
    def __init__(self, getRuleSetName, libraryFile, sFilter = None, forcedRuleCompile = 0):
        carmen.CompileRules.__init__(self, getRuleSetName, "-optimize", sFilter)
        self.forcedRuleCompile = forcedRuleCompile
        self.libraryFile = libraryFile
    def __call__(self, test):
        self.apcLib = os.path.join(os.environ["CARMSYS"], self.libraryFile)
        carmTmpDir = os.environ["CARMTMP"]
        self.verifyAirportFile()
        if not os.path.isdir(carmTmpDir):
            os.mkdir(carmTmpDir)
        if self.forcedRuleCompile == 0 and carmen.architecture == "i386_linux":
            self.linuxRuleSetBuild(test)
        else:
            carmen.CompileRules.__call__(self, test)
    def linuxRuleSetBuild(self, test):
        ruleset = carmen.RuleSet(self.getRuleSetName(test), self.raveName)
        if not ruleset.isValid() or ruleset.name in self.rulesCompiled:
            return
        apcExecutable = ruleset.targetFile
        carmen.ensureDirectoryExists(os.path.dirname(apcExecutable))
        ruleLib = self.getRuleLib(ruleset.name)
        if self.isNewer(apcExecutable, self.apcLib):
            return
        self.describe(test, " -  ruleset " + ruleset.name)
        ruleset.backup()
        self.rulesCompiled.append(ruleset.name)
        if not os.path.isfile(ruleLib):
            compiler = os.path.join(os.environ["CARMSYS"], "bin", "crc_compile")
            returnValue = os.system(self.ruleCompileCommand(ruleset.sourceFile))
            if returnValue:
                raise EnvironmentError, "Failed to build library for APC ruleset " + ruleset.name
        commandLine = "g++ -pthread " + self.linkLibs(self.apcLib, ruleLib)
        commandLine += "-o " + apcExecutable
        si, so, se = os.popen3(commandLine)
        lastErrors = se.readlines()
        if len(lastErrors) > 0:
            if lastErrors[-1].find("exit status") != -1:
                print "Building", ruleset.name, "failed!"
                for line in lastErrors:
                    print "   ", line.strip()
                raise EnvironmentError, "Failed to link APC ruleset " + ruleset.name

    def getRuleLib(self, ruleSetName):
        optArch = carmen.architecture + "_opt"
        ruleLib = ruleSetName + ".a"
        return os.path.join(os.environ["CARMTMP"], "compile", self.raveName.upper(), optArch, ruleLib)
        
    def ruleCompileCommand(self, sourceFile):
       compiler = os.path.join(os.environ["CARMSYS"], "bin", "crc_compile")
       params = " -optimize -makelib -archs " + carmen.architecture
       return compiler + " " + self.raveName + params + " " + sourceFile
                    
    def linkLibs(self, apcLib, ruleLib):
       path1 = os.path.join(os.environ["CARMSYS"], "data", "crc", carmen.architecture)
       path2 = os.path.join(os.environ["CARMSYS"], "lib", carmen.architecture)
       paths = " -L" + path1 + " -L" + path2
       basicLibs = " -lxprs -lxprl -lm -ldl -lrave_rts -lBasics_STACK -lrave_private "
       extraLib = " `xml2-config --libs` -ldl "
       return apcLib + paths + basicLibs + ruleLib + extraLib

    def isNewer(self, file1, file2):
        if not os.path.isfile(file1):
            return 0
        if not os.path.isfile(file2):
            return 1
        if self.modifiedTime(file1) > self.modifiedTime(file2):
            return 1
        else:
            return 0
    def modifiedTime(self, filename):
        return os.stat(filename)[stat.ST_MTIME]

    def verifyAirportFile(self):
       etabPath = os.path.join(os.environ["CARMUSR"], "Resources", "CarmResources")
       customerEtab = os.path.join(etabPath, "Customer.etab")
       if os.path.isfile(customerEtab):
          etab = carmen.ConfigEtable(customerEtab)
          airportFile = etab.getValue("default", "AirpMaint", "AirportFile")
          if airportFile != None and os.path.isfile(airportFile):
             return
          srcDir = etab.getValue("default", "AirpMaint", "AirportSrcDir")
          if srcDir == None:
             srcDir = etab.getValue("default", "AirpMaint", "AirportSourceDir")
          if srcDir == None:
             srcDir = os.path.join(os.environ["CARMUSR"], "data", "Airport", "source")
          srcFile = os.path.join(srcDir, "AirportFile")
          if os.path.isfile(srcFile) and airportFile != None:
             apCompile = os.path.join(os.environ["CARMSYS"], "bin", carmen.architecture, "apcomp")
             if os.path.isfile(apCompile):
                print "Missing AirportFile detected, building:", airportFile
                carmen.ensureDirectoryExists(os.path.dirname(airportFile))
                os.system(apCompile + " " + srcFile + " > " + airportFile)
                if os.path.isfile(airportFile):
                   return
       raise EnvironmentError, "Failed to find AirportFile"

      
class RemoveLogs(plugins.Action):
    def __call__(self, test):
        self.removeFile(test, "errors")
        self.removeFile(test, "output")
    def removeFile(self, test, stem):
        filePath = test.getTmpFileName(stem, "r")
        if os.path.isfile(filePath):
            os.remove(filePath)
    def __repr__(self):
        return "Remove logs"

class StartStudio(plugins.Action):
    def __call__(self, test):
        print "CARMSYS:", os.environ["CARMSYS"]
        print "CARMUSR:", os.environ["CARMUSR"]
        print "CARMTMP:", os.environ["CARMTMP"]
        commandLine = os.path.join(os.environ["CARMSYS"], "bin", "studio")
        print os.popen(commandLine).readline()
        sys.exit(0)
        
optimization.itemNamesInFile[optimization.memoryEntryName] = "Time:.*memory"
optimization.itemNamesInFile[optimization.costEntryName] = "TOTAL cost"

class MakeProgressReport(optimization.MakeProgressReport):
    def __init__(self, referenceVersion):
        optimization.MakeProgressReport.__init__(self, referenceVersion)
        self.refMargins = {}
        self.currentMargins = {}
        self.kpiGroupForTest = {}
        self.testInGroupList = []
        self.finalCostsInGroup = {}
        self.weightKPI = []
        self.sumKPITime = 0.0
        self.minKPITime = 0.0
    def getInterestingValues(self):
        return [ optimization.costEntryName, optimization.timeEntryName, optimization.memoryEntryName ]
    def __del__(self):
        for groupName in self.finalCostsInGroup.keys():
            fcTupleList = self.finalCostsInGroup[groupName]
            refMargin, currentMargin = self._calculateMargin(fcTupleList)
            self.refMargins[groupName] = refMargin
            self.currentMargins[groupName] = currentMargin
        for testTuple in self.testInGroupList:
            test, referenceRun, currentRun, userName = testTuple
            self.doCompare(test, referenceRun, currentRun, userName)

        if len(self.weightKPI) > 1:
            # The weighted KPI is prodsum(KPIx * Tx / Tmin) ^ (1 / sum(Tx/Tmin))
            # Tx is the average of the 'time to worst cost' for a specific test case, ie
            # Tx = (curTTWC + refTTWC) / 2
            #
            sumKPI = 1.0
            sumTimeParts = 0.0
            for tup in self.weightKPI:
                kpiS, kpiTime = tup
                kpi = float(kpiS.split("%")[0]) / 100
                sumKPI *= math.pow(kpi, 1.0 * kpiTime / self.minKPITime)
                sumTimeParts += 1.0 * kpiTime / self.minKPITime
            avg = math.pow(sumKPI, 1.0 / float(sumTimeParts))
            print os.linesep, "Overall time weighted KPI with respect to version", self.referenceVersion, "=", self.percent(avg)
        optimization.MakeProgressReport.__del__(self)
    def _calculateMargin(self, fcTupleList):
        if len(fcTupleList) < 2:
            return 0.1, 0.1
        refMax = 0
        curMax = 0
        for refCost, curCost in fcTupleList:
            refMax = max(refMax, refCost)
            curMax = max(curMax, curCost)
        refMaxDiff = 0
        curMaxDiff = 0
        for refCost, curCost in fcTupleList:
            refMaxDiff = max(refMaxDiff, abs(refMax - refCost))
            curMaxDiff = max(curMaxDiff, abs(curMax - curCost))
        refMargin = round(1.0 * refMaxDiff / refMax, 5) * 100.0
        curMargin = round(1.0 * curMaxDiff / curMax, 5) * 100.0
        return refMargin, curMargin
    def setUpSuite(self, suite):
        kpiGroups = suite.makeFileName("kpi_groups")
        if not os.path.isfile(kpiGroups):
            return
        groupFile = open(kpiGroups)
        for line in groupFile.readlines():
            if line[0] == '#' or not ':' in line:
                continue
            groupName, testname = line.strip().split(":",1)
            self.kpiGroupForTest[testname] = groupName
    def compare(self, test, referenceRun, currentRun):
        userName = os.path.normpath(os.environ["CARMUSR"]).split(os.sep)[-1]
        if not self.kpiGroupForTest.has_key(test.name):
            self.doCompare(test, referenceRun, currentRun, userName)
            return
        groupName = self.kpiGroupForTest[test.name]
        testTuple = test, referenceRun, currentRun, userName
        self.testInGroupList.append(testTuple)
        fcTuple = referenceRun.getCost(-1), currentRun.getCost(-1)
        if not self.finalCostsInGroup.has_key(groupName):
            self.finalCostsInGroup[groupName] = []
        self.finalCostsInGroup[groupName].append(fcTuple)
    def getMargins(self, test):
        if self.kpiGroupForTest.has_key(test.name):
            refMargin = self.refMargins[self.kpiGroupForTest[test.name]]
            currentMargin = self.currentMargins[self.kpiGroupForTest[test.name]]
            return currentMargin, refMargin
        else:
            return optimization.MakeProgressReport.getMargins(self, test)
    def computeKPI(self, currTTWC, refTTWC):
        kpi = optimization.MakeProgressReport.computeKPI(self, currTTWC, refTTWC)
        if kpi != "NaN%":
            kpiTime = (currTTWC + refTTWC) / 2.0
            self.sumKPITime += kpiTime
            if len(self.weightKPI) == 0 or kpiTime < self.minKPITime:
                self.minKPITime = kpiTime
            weightKPItuple = kpi, kpiTime
            self.weightKPI.append(weightKPItuple)
        return kpi
    def reportCosts(self, test, currentRun, referenceRun):
        optimization.MakeProgressReport.reportCosts(self, test, currentRun, referenceRun)
        currentMargin, refMargin = self.getMargins(test)
        self.reportLine("Cost variance tolerance (%) ", currentMargin, refMargin)

class ApcTestCaseInformation(optimization.TestCaseInformation):
    def __init__(self, suite, name):
        optimization.TestCaseInformation.__init__(self, suite, name)
    def isComplete(self):
        if not os.path.isdir(self.testPath()):
            return 0
        if not os.path.isfile(self.makeFileName("options")):
            return 0
        if not os.path.isfile(self.makeFileName("environment")):
            return 0
        if not os.path.isfile(self.makeFileName("performance")):
            return 0
        return 1
    def makeImport(self):
        testPath = self.testPath()
        optionPath = self.makeFileName("options")
        envPath = self.makeFileName("environment")
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
            carmUsrSubPlanDirectory = self.replaceCarmUsr(subPlanDir)
            newOptions = self.buildOptions(carmUsrSubPlanDirectory, ruleSet)
            open(optionPath,"w").write(newOptions + os.linesep)
        else:
            subPlanDir = self.subPlanFromOptions(optionPath)
            carmUsrSubPlanDirectory = self.replaceCarmUsr(subPlanDir)
        if not os.path.isfile(envPath):
            envContent = self.buildEnvironment(carmUsrSubPlanDirectory)
            open(envPath,"w").write(envContent + os.linesep)
        if not os.path.isfile(perfPath):
            perfContent = self.buildPerformance(subPlanDir)
            open(perfPath, "w").write(perfContent + os.linesep)
        return 1
    def replaceCarmUsr(self, path):
        carmUser = os.environ["CARMUSR"]
        if path[0:len(carmUser)] == carmUser:
            return "${CARMUSR}" + os.path.join("/", path[len(carmUser) : len(path)])
        return path
    def subPlanFromOptions(self, optionPath):
        path = open(optionPath).readline().split()[0]
        if path[0:10] != "${CARMUSR}":
            return path
        if not os.environ.has_key("CARMUSR"):
            return path
        carmUsr = os.environ["CARMUSR"]
        npath = os.path.join(carmUsr, path.replace("${CARMUSR}", "./"))
        return os.path.normpath(npath)

    def buildOptions(self, path, ruleSet):
        subPlan = path
        statusFile = path + os.sep + "run_status"
        ruleSetPath = "${CARMTMP}" + os.sep + os.path.join("crc", "rule_set", "APC", "PUTS_ARCH_HERE")
        ruleSetFile = ruleSetPath + os.sep + ruleSet
        return subPlan + " " + statusFile + " ${CARMSYS} " + ruleSetFile + " ${USER}"

    def buildEnvironment(self, carmUsrSubPlanDirectory):
        lpEtab = carmUsrSubPlanDirectory.split(os.sep)[0:-2]
        spEtab = carmUsrSubPlanDirectory.split(os.sep)[0:-1]
        lpEtabLine = "LP_ETAB_DIR:" + os.path.normpath(string.join(lpEtab, "/") + "/etable")
        spEtabLine = "SP_ETAB_DIR:" + os.path.normpath(string.join(spEtab, "/") + "/etable")
        return lpEtabLine + os.linesep + spEtabLine

    def buildPerformance(self, subPlanDir):
        statusPath = self.makeFileName("status")
        if not os.path.isfile(statusPath):
            statusPath = os.path.join(subPlanDir, "status")
        if os.path.isfile(statusPath):
            lastLines = os.popen("tail -10 " + statusPath).xreadlines()
            for line in lastLines:
                if line[0:5] == "Time:":
                    sec = line.split(":")[1].split("s")[0]
                    return "CPU time   :     " + str(int(sec)) + ".0 sec. on onepusu"
# Give some default that will not end it up in the short queue
        return "CPU time   :      2500.0 sec. on heathlands"
        

class ApcTestSuiteInformation(optimization.TestSuiteInformation):
    def __init__(self, suite, name):
        optimization.TestSuiteInformation.__init__(self, suite, name)
    def getEnvContent(self):
        carmUsrDir = self.chooseCarmDir("CARMUSR")
        usrContent = "CARMUSR:" + carmUsrDir
        tmpContent = "CARMTMP:${CARMSYS}" + os.sep + self.makeCarmTmpName()
        return usrContent + os.linesep + tmpContent

class ImportTest(optimization.ImportTest):
    def getTestCaseInformation(self, suite, name):
        return ApcTestCaseInformation(suite, name)
    def getTestSuiteInformation(self, suite, name):
        return ApcTestSuiteInformation(suite, name)
    def setUpSuite(self, suite):
        if suite.app.name == "apc":
            optimization.ImportTest.setUpSuite(self, suite)
        else:
            self.describe(suite, " failed: Only imports APC test suites!")

class PortApcTest(plugins.Action):
    def __repr__(self):
        return "Porting old"
    def __call__(self, test):
        testInfo = ApcTestCaseInformation(self.suite, test.name)
        hasPorted = 0
        if test.options[0] == "-":
            hasPorted = 1
            subPlanDirectory = test.options.split()[3]
            carmUsrSubPlanDirectory = testInfo.replaceCarmUsr(subPlanDirectory)
            ruleSetName = testInfo.getRuleSetName(subPlanDirectory)
            newOptions = testInfo.buildOptions(carmUsrSubPlanDirectory, ruleSetName)
            fileName = test.makeFileName("options")
            shutil.copyfile(fileName, fileName + ".oldts")
            os.remove(fileName)
            optionFile = open(fileName,"w")
            optionFile.write(newOptions + "\n")
        else:
            subPlanDirectory = test.options.split()[0]
            carmUsrSubPlanDirectory = testInfo.replaceCarmUsr(subPlanDirectory)
        envFileName = test.makeFileName("environment")
        if not os.path.isfile(envFileName):
            hasPorted = 1
            envContent = testInfo.buildEnvironment(carmUsrSubPlanDirectory)
            open(envFileName,"w").write(envContent + os.linesep)
        perfFileName = test.makeFileName("performance")
        if not os.path.isfile(perfFileName):
            hasPorted = 1
            perfContent = testInfo.buildPerformance(carmUsrSubPlanDirectory)
            open(envFileName,"w").write(perfContent + os.linesep)
        else:
            lines = open(perfFileName).readlines()
            if len(lines) > 1:
                line1 = lines[0]
                line2 = lines[1]
                if line1[0:4] == "real" and line2[0:4] == "user":
                    sec = line2.split(" ")[1]
                    perfContent = "CPU time   :     " + str(float(sec)) + " sec. on heathlands"
                    open(perfFileName,"w").write(perfContent + os.linesep)
                    hasPorted = 1
        if hasPorted != 0:
            self.describe(test, " in " + testInfo.suiteDescription())
    def setUpSuite(self, suite):
        self.suite = suite

class PlotApcTest(optimization.PlotTest):
    def __init__(self, args = []):
        optimization.PlotTest.__init__(self, args)
        self.plotItem = " " + "TOTAL cost"
        self.plotUseTmpStatus = "t"
        self.interpretOptions(args)
    def setOption(self, arr):
        if arr[0]=="i":
            self.plotItem = " " + arr[1].replace("_"," ")
            return 1
        elif arr[0]=="nt":
            self.plotUseTmpStatus = []
        return 0
    def getCostsAndTimes(self, file, plotItem):
        optCalc = optimization.OptimizationValueCalculator( [ plotItem, optimization.timeEntryName ], file)
        costs = optCalc.getValues(plotItem)
        times = optCalc.getValues(optimization.timeEntryName)
        return costs, times
    def getStatusFile(self, test, version):
        currentFile = findTemporaryStatusFile(test, version)
        if self.plotUseTmpStatus and currentFile:
            print "Using status file in temporary subplan directory for plotting test " + test.name
            return currentFile
        else:
            return optimization.PlotTest.getStatusFile(self, test, version)

class GrepApcLog(plugins.Action):
    def __init__(self,args = ["(heuristic subselection|unfixvars time|focussing|Solv|OBJ|LBD|\*\*\*)"]):
        self.grepwhat = args[0]
    def __repr__(self):
        return "Greping"
    def __del__(self):
        pass
    def __call__(self, test):
        tmpStatusFile = findTemporaryStatusFile(test)
        if not tmpStatusFile:
            print "Test " + test.name + " is not running."
            return
        grepCommand = "grep Machine " + tmpStatusFile
        grepLines = os.popen(grepCommand).readlines()
        if len(grepLines) > 0:
            machine = grepLines[0].split()[-1]
            Command = "rsh " + machine + " 'cd /tmp/*" + test.name + "*; egrep \"" + self.grepwhat + "\" apclog'" 
            grepLines = os.popen(Command).read()
            print grepLines
    def setUpSuite(self, suite):
        pass
    def setUpApplication(self, app):
        pass
        
def findTemporaryStatusFile(test,version = ""):
    foundoutputfile = 0
    for file in os.listdir(test.abspath):
        if file.startswith("output") and file.find(version + test.getTestUser()) != -1:
            foundoutputfile = 1
            break
    if not foundoutputfile:
        return
    grepCommand = "grep -E 'SUBPLAN' " + file
    grepLines = os.popen(grepCommand).readlines()
    if len(grepLines) > 0:
        currentFile = grepLines[0].split()[1] + os.sep + "status"
        if not os.path.isfile(currentFile):
            return
        else:
            return currentFile
    else:
        print "Could not find subplan name in output file " + file + os.linesep
        return    


class UpdateCvsIgnore(plugins.Action):
    def __init__(self):
        self.masterCvsIgnoreFile = None
        self.updateCount = 0
        pass
    def __repr__(self):
        return "Greping"
    def __del__(self):
        if self.updateCount > 0:
            print "Updated", self.updateCount, ".cvsignore files"
        else:
            print "No .cvsignore files updated"
        pass
    def __call__(self, test):
        if self.masterCvsIgnoreFile == None:
            return
        fileName = os.path.join(test.abspath, ".cvsignore")
        if not os.path.isfile(fileName) or filecmp.cmp(fileName, self.masterCvsIgnoreFile) == 0:
            shutil.copyfile(self.masterCvsIgnoreFile, fileName)
            self.updateCount += 1
        
    def setUpSuite(self, suite):
        pass
    def setUpApplication(self, app):
        fileName = os.path.join(app.abspath, "cvsignore.master")
        if os.path.isfile(fileName):
            self.masterCvsIgnoreFile = fileName

