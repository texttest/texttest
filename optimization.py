helpDescription = """
It will fetch the optimizer's solution from the subplan (the "best_solution" link) and write it for
comparison as the file solution.<app> after each test has run.

It also uses the temporary subplan concept, such that all tests will actually be run in different, temporary
subplans when the tests are run. These subplans should then be cleaned up afterwards. The point of this
is to avoid clashes in solution due to two runs of the same test writing to the same subplan.

Also, you can specify a "rave_parameter" entry in your config file, typically in a version file. The value
of this should be a line to insert into the rules file after the subplan is copied. By doing this you can
experiment with a new feature on a lot of tests without having to manually create new tests.

In other respects, it follows the usage of the Carmen configuration.""" 

helpOptions = """-prrep <v> - Generate a Progress Report relative to the version <v>. This will produce some key numbers for all
             tests specified.

-kpi <ver> - Generate a Key Performance Indicator ("KPI") relative to the version <ver>. This will try to apply
             some formula to boil down the results of the tests given to a single-number "performance indicator".
             Please note that the results so far are not very reliable, as the formula itself is still under development.
"""

import carmen, os, sys, string, shutil, KPI, plugins, performance, math

class OptimizationConfig(carmen.CarmenConfig):
    def getOptionString(self):
        return "k:" + carmen.CarmenConfig.getOptionString(self)
    def getActionSequence(self):
        if self.optionMap.has_key("kpi"):
	    listKPIs = [KPI.cSimpleRosteringOptTimeKPI, KPI.cFullRosteringOptTimeKPI, KPI.cWorstBestRosteringOptTimeKPI]
            return [ CalculateKPIs(self.optionValue("kpi"), listKPIs) ]
        if self.optionMap.has_key("prrep"):
            return [ self.getProgressReportBuilder() ]
        return carmen.CarmenConfig.getActionSequence(self)
    def getProgressReportBuilder(self):
        return MakeProgressReport(self.optionValue("prrep"))
    def getRuleBuilder(self, neededOnly):
        if self.isReconnecting():
            return plugins.Action()
        if self.isNightJob() or not neededOnly:
            return self.getCompileRules(None)
        else:
            localFilter = carmen.UpdatedLocalRulesetFilter(self.getRuleSetName, self.getLibraryFile())
            return self.getCompileRules(localFilter)
    def getCompileRules(self, localFilter):
        return carmen.CompileRules(self.getRuleSetName, "-optimize", localFilter)
    def getTestCollator(self):
        return plugins.CompositeAction([ carmen.CarmenConfig.getTestCollator(self), ExtractSubPlanFile(self, "best_solution", "solution") ])
    def printHelpDescription(self):
        print helpDescription
        carmen.CarmenConfig.printHelpDescription(self)
    def printHelpOptions(self, builtInOptions):
        carmen.CarmenConfig.printHelpOptions(self, builtInOptions)
        print helpOptions

class ExtractSubPlanFile(plugins.Action):
    def __init__(self, config, sourceName, targetName):
        self.config = config
        self.sourceName = sourceName
        self.targetName = targetName
    def __repr__(self):
        return "Extracting subplan file " + self.sourceName + " to " + self.targetName + " on"
    def __call__(self, test):
        if self.config.isReconnecting():
            return
        sourcePath = self.config.getSubPlanFileName(test, self.sourceName)
        targetFile = test.getTmpFileName(self.targetName, "w")
        if os.path.isfile(sourcePath):
            shutil.copyfile(sourcePath, targetFile)
            if carmen.isCompressed(targetFile):
                targetFileZ = targetFile + ".Z"
                os.rename(targetFile, targetFileZ)
                os.system("uncompress " + targetFileZ)
            return
        if os.path.isfile(test.makeFileName(self.targetName)):
            errText = "Expected file '" + sourcePath + "'not created by test"
            open(targetFile,"w").write(errText + os.linesep)
            
# Abstract base class for handling running tests in temporary subplan dirs
# see example usage in apc.py
#
class SubPlanDirManager:
    def __init__(self, config):
        self.config = config
        self.tmpDirs = {}
    def getSubPlaDirFromTest(self, test):
        pass
    def getExecuteCommand(self, test):
        pass
    def getSubPlanFileName(self, test, sourceName):
        if not self.tmpDirs.has_key(test):
            return os.path.join(self.getSubPlanDirFromTest(test), "APC_FILES", sourceName)
        else:
            return os.path.join(self.tmpDirs[test], "APC_FILES", sourceName)
    def makeTemporary(self, test):
        dirName = self.getSubPlanDirName(test)
        baseName = self.getSubPlanBaseName(test)
        tmpDir = self.getTmpSubdir(test, dirName, baseName, "w")
        self.tmpDirs[test] = tmpDir
        os.mkdir(tmpDir)
        parameterOverrides = test.app.getConfigList("rave_parameter")
        self.makeLinksIn(tmpDir, os.path.join(dirName, baseName), parameterOverrides)
    def makeLinksIn(self, inDir, fromDir, parameterOverrides):
        for file in os.listdir(fromDir):
            if file == "APC_FILES":
                apcFiles = os.path.join(inDir, file)
                os.mkdir(apcFiles)
                self.makeLinksIn(apcFiles, os.path.join(fromDir, file), parameterOverrides)
                continue
            if file.find("Solution_") != -1:
                continue
            if file.find("status") != -1:
                continue
            if file.find("hostname") != -1:
                continue
            if file.find("best_solution") != -1:
                continue

            fromPath = os.path.join(fromDir, file)
            toPath = os.path.join(inDir, file)
            if len(parameterOverrides) > 0 and file.find("rules") != -1:
                file = open(toPath, 'w')
                for line in open(fromPath).xreadlines():
                    if line.find("<SETS>") != -1:        
                        for override in parameterOverrides:
                            file.write(override + os.linesep)
                    file.write(line)
            else:
                os.symlink(fromPath, toPath)
                
    def removeTemporary(self, test):
        if self.tmpDirs.has_key(test):
            tmpDir = self.tmpDirs[test]
            if os.path.isdir(tmpDir):
                self._removeDir(tmpDir)
    def getSubPlanDirName(self, test):
        subPlanDir = self.getSubPlanDirFromTest(test)
        dirs = subPlanDir.split(os.sep)[:-1]
        return os.path.normpath(string.join(dirs, os.sep))
    def getSubPlanBaseName(self, test):
        subPlanDir = self.getSubPlanDirFromTest(test)
        baseName =  subPlanDir.split(os.sep)[-1]
        return baseName
    def getTmpSubdir(self, test, subDir, baseName, mode):
        prefix = os.path.join(subDir, baseName) + "."
        prefix += test.app.name + test.app.versionSuffix() + "_" + test.name + "_"
        dirName = prefix + test.getTmpExtension()
        if not test.parallelMode():
            currTmpString = prefix + test.getTestUser()
            for file in os.listdir(subDir):
                fpath = os.path.join(subDir,file)
                if not os.path.isdir(fpath):
                    continue
                if fpath.find(currTmpString) != -1:
                    self._removeDir(os.path.join(subDir, file))
        return dirName
    def _removeDir(self, subDir):
        for file in os.listdir(subDir):
            fpath = os.path.join(subDir,file)
            try:
                # if softlinked dir, remove as file and do not recurse
                os.remove(fpath) 
            except:
                self._removeDir(fpath)
        try:
            os.remove(subDir)
        except:
            try:
                os.rmdir(subDir)
            except:
                os.system("rm -rf " + subDir);
                

class RemoveTemporarySubplan(plugins.Action):
    def __init__(self, subplanManager):
        self.subplanManager = subplanManager
    def __call__(self, test):
        self.subplanManager.removeTemporary(test)
    def __repr__(self):
        return "Removing temporary subplan for"

class TestReport(plugins.Action):
    def __init__(self, versionString):
        versions = versionString.split(",")
        self.referenceVersion = versions[0]
        self.currentVersion = None
        if len(versions) > 1:
            self.currentVersion = versions[1]
        self.statusFileName = None
    def __call__(self, test):
        currentFile = test.makeFileName(self.statusFileName, self.currentVersion)
        referenceFile = test.makeFileName(self.statusFileName, self.referenceVersion)
        if currentFile != referenceFile:
            self.compare(test, referenceFile, currentFile)
    def setUpApplication(self, app):
        self.statusFileName = app.getConfigValue("log_file")

class CalculateKPIs(TestReport):
    def __init__(self, referenceVersion, listKPIs):
        TestReport.__init__(self, referenceVersion)
	self.KPIHandler = KPI.KPIHandler()
	self.listKPIs = listKPIs
    def __del__(self):
        if self.KPIHandler.getNrOfKPIs() > 0:
            print os.linesep, "Overall average KPI with respect to version", self.referenceVersion, ":", os.linesep, self.KPIHandler.getAllGroupsKPIAverageText()
        else:
            print os.linesep, "No KPI tests were found with respect to version " + self.referenceVersion
    def __repr__(self):
        return "KPI calc. for"
    def compare(self, test, referenceFile, currentFile):
        floatRefPerfScale = performance.getTestPerformance(test, self.referenceVersion)
        floatNowPerfScale = performance.getTestPerformance(test, self.currentVersion)
	#print 'ref: %f, now: %f' %(floatRefPerfScale, floatNowPerfScale)
        if currentFile != referenceFile:
	    aKPI = None
	    listKPIs = []
	    for aKPIConstant in self.listKPIs:
		if floatRefPerfScale > 0.0 and floatNowPerfScale > 0.0:
		    aKPI = self.KPIHandler.createKPI(aKPIConstant, referenceFile, currentFile, floatRefPerfScale, floatNowPerfScale)
		else:
		    aKPI = self.KPIHandler.createKPI(aKPIConstant, referenceFile, currentFile)
		self.KPIHandler.addKPI(aKPI)
		listKPIs.append(aKPI.getTextKPI())
            self.describe(test, ' vs ver. %s, (%d sol. KPIs: %s)' %(self.referenceVersion, aKPI.getNofSolutions(), ', '.join(listKPIs)))
    def setUpSuite(self, suite):
        self.describe(suite)


class MakeProgressReport(TestReport):
    def __init__(self, referenceVersion):
        TestReport.__init__(self, referenceVersion)
        self.kpi = 1.0
        self.testCount = 0
    def __del__(self):
        if self.testCount > 0:
            avg = math.pow(self.kpi, 1.0 / float(self.testCount))
            print os.linesep, "Overall average KPI with respect to version", self.referenceVersion, "=", self.percent(avg)
    def __repr__(self):
        return "Comparison on"
    def setUpApplication(self, app):
        TestReport.setUpApplication(self, app)
        currentText = ""
        if self.currentVersion != None:
            currentText = " Version " + self.currentVersion
        header = "Progress Report for " + repr(app) + currentText + ", compared to version " + self.referenceVersion
        underline = ""
        for i in range(len(header)):
            underline += "-"
        print os.linesep + header
        print underline
    def percent(self, fValue):
        return str(int(round(100.0 * fValue))) + "%"
    def computeKPI(self, currTTWC, refTTWC):
        if refTTWC > 0:
            kpi = float(currTTWC) / float(refTTWC)
            if kpi > 0:
                self.kpi *= kpi
            return self.percent(kpi)
        else:
            return "NaN%"
    def compare(self, test, referenceFile, currentFile):
        currPerf = int(performance.getTestPerformance(test, self.currentVersion))
        refPerf = int(performance.getTestPerformance(test, self.referenceVersion))
        referenceCosts = self.getCosts(referenceFile, "plan")
        if len(referenceCosts) < 3 or refPerf == 0 or currPerf == 0:
            return
        
        currentCosts =  self.getCosts(currentFile, "plan")
        refRosterCosts = self.getCosts(referenceFile, "roster")
        currRosterCosts = self.getCosts(currentFile, "roster")
        currTTWC = currPerf
        refTTWC = refPerf
        if abs(currentCosts[-1]) < abs(referenceCosts[-1]):
            currTTWC = self.timeToCost(currentFile, currPerf, currentCosts, referenceCosts[-1])
        else:
            refTTWC = self.timeToCost(referenceFile, refPerf, referenceCosts, currentCosts[-1])
        self.testCount += 1
        userName = os.path.normpath(os.environ["CARMUSR"]).split(os.sep)[-1]
        print os.linesep, "Comparison on", test.app, "test", test.name, "(in user " + userName + ") : K.P.I. = " + self.computeKPI(currTTWC, refTTWC)
        self.reportLine("                         ", self.currentText(), "Version " + self.referenceVersion)
        self.reportLine("Initial cost of plan     ", currentCosts[0], referenceCosts[0])
        self.reportLine("Initial cost of rosters  ", currRosterCosts[0], refRosterCosts[0])
        self.reportLine("Final cost of plan       ", currentCosts[-1], referenceCosts[-1])
        self.reportLine("Final cost of rosters    ", currRosterCosts[-1], refRosterCosts[-1])
        self.reportLine("Total time (minutes)     ", currPerf, refPerf)
        self.reportLine("Time to worst cost (mins)", currTTWC, refTTWC)
    def currentText(self):
        if self.currentVersion == None:
            return "Current"
        else:
            return "Version " + self.currentVersion
    def getCosts(self, file, type):
        costCommand = "grep 'cost of " + type + "' " + file + " | awk -F':' '{ print $2 }'"
        return map(self.makeInt, os.popen(costCommand).readlines())
    def makeInt(self, val):
        return int(string.strip(val))
    def reportLine(self, title, currEntry, refEntry):
        fieldWidth = 15
        print title + ": " + string.rjust(str(currEntry), fieldWidth) + string.rjust(str(refEntry), fieldWidth)
    def timeToCost(self, file, performanceScale, costs, targetCost):
        timeCommand = "grep 'cpu time' " + file + " | awk '{ print $6 }'"
        times = map(self.convertTime, os.popen(timeCommand).readlines())
        times.insert(0, 0.0)
        return self.timeToCostFromTimes(times, performanceScale, costs, targetCost)
    def timeToCostFromTimes(self, times, performanceScale, costs, targetCost):
        for index in range(len(costs)):
            if abs(costs[index]) < abs(targetCost):
                costGap = costs[index - 1] - costs[index]
                percent = float(costs[index -1] - targetCost) / costGap
                performance = times[index - 1] + (times[index] - times[index - 1]) * percent
                return int(performance / times[-1] * performanceScale)
        return performanceScale
    def convertTime(self, timeEntry):
        entries = timeEntry.split(":")
        timeInSeconds = int(entries[0]) * 3600 + int(entries[1]) * 60 + int(entries[2].strip())
        return float(timeInSeconds) / 60.0

# This is for importing new tests and test suites
#
class TestInformation:
    def __init__(self, suite, name):
        self.suite = suite
        self.name = name
    def isComplete(self):
        return 1
    def absPathToCarmSys(self):
        return os.path.join(self.suite.app.checkout, self.suite.environment["CARMSYS"])
    def testPath(self):
        return os.path.join(self.suite.abspath, self.name)
    def filePath(self, file):
        return os.path.join(self.suite.abspath, self.name, file)
    def makeFileName(self, stem, version = None):
        return self.suite.makeFileName(self.name + os.sep + stem, version)
    def appSuffix(self):
        asFileName = self.suite.makeFileName("__tmp__")
        return asFileName.replace(os.path.join(self.suite.abspath, "__tmp__"), "")
    def makeCarmTmpName(self):
        return self.name + "_tmp" + self.appSuffix()

# This is for importing new test suites
#
class TestSuiteInformation(TestInformation):
    def __init__(self, suite, name):
        TestInformation.__init__(self, suite, name)
    def isComplete(self):
        if not os.path.isdir(self.testPath()):
            return 0
        if not os.path.isfile(self.makeFileName("testsuite")):
            return 0
        if not os.path.isfile(self.makeFileName("environment")):
            return 0
        return 1
    def makeImport(self):
        if not os.path.isdir(self.testPath()):
            os.mkdir(self.testPath())
        suitePath = self.makeFileName("testsuite")
        if not os.path.isfile(suitePath):
            suiteContent = "# Tests for user " + self.name + os.linesep + "#"
            open(suitePath, "w").write(suiteContent + os.linesep)
        envPath = self.makeFileName("environment")
        if not os.path.isfile(envPath):
            envContent = self.getEnvContent()
            if envContent != None:
                open(envPath,"w").write(envContent + os.linesep)
        return 1
    def postText(self):
        return ", User: '" + self.name + "'"
    def getEnvContent(self):
        carmUsrDir = self.chooseCarmDir("CARMUSR")
        carmTmpDir = self.chooseCarmDir("CARMTMP")
        usrContent = "CARMUSR:" + carmUsrDir
        tmpContent = "CARMTMP:" + carmTmpDir;
        return usrContent + os.linesep + tmpContent
    def findCarmVarFrom(self, fileList, envVariableName):
        for file in fileList:
            if not os.path.isfile(self.filePath(file)):
                continue
            for line in open(self.filePath(file)).xreadlines():
                if line[0:7] == envVariableName:
                    return line.split(":")[1].strip()
        return None
    def chooseCarmDir(self, envVariableName):
        dirName = self.findCarmVarFrom(self.findStems("environment"), envVariableName)
        while dirName == None:
            print "Please give " + envVariableName + " directory to use for user " + self.userDesc()
            dirName = sys.stdin.readline().strip();
            if not os.path.isdir(dirName):
                print "Not found: '" + dirName + "'"
                dirName = None
        return dirName
    def findStems(self, baseName):
        stems = []
        totalName = baseName + self.appSuffix()
        splitName = totalName.split(".")
        splits = len(splitName)
        if splits > 1:
            stems.append(splitName[0])
        if splits > 2:
            stems.append(splitName[0] + "." + splitName[1])
        return stems;
    def userDesc(self):
        return "'" + self.name + "'(" + self.appSuffix() + ")"
        
# This is for importing new test cases
#
class TestCaseInformation(TestInformation):
    def __init__(self, suite, name):
        TestInformation.__init__(self, suite, name)
    def isComplete(self):
        return 1
    def makeImport(self):
        return 0
    def postText(self):
        return ", Test: '" + self.name + "'"
    def getRuleSetName(self, absSubPlanDir):
        problemPath = os.path.join(absSubPlanDir,"problems")
        if not carmen.isCompressed(problemPath):
            problemLines = open(problemPath).xreadlines()
        else:
            tmpName = os.tmpnam()
            shutil.copyfile(problemPath, tmpName + ".Z")
            os.system("uncompress " + tmpName + ".Z")
            problemLines = open(tmpName).xreadlines()
            os.remove(tmpName)
        for line in problemLines:
            if line[0:4] == "153;":
                return line.split(";")[3]
        return ""
    def chooseDir(self, dirs, suiteDesc, tryName):
        answer = -1
        while answer == -1:
            num = 0
            print
            print "There are", len(dirs), "possible subplans matching '" + tryName + "' in", suiteDesc
            for dir in dirs:
                num += 1
                print str(num) + ".", dir
            print "Please choose ( 1 -", num, ", or 0 for none of the above): "
            response = sys.stdin.readline();
            try:
                answer = int(response)
            except:
                pass
            if (answer < 0 or answer > num):
                answer = -1
        if answer > 0:
            return dirs[answer - 1]
        else:
            return None
    def findMatchingSubdirs(self, subPlanTree, testName):
        dirs = os.listdir(subPlanTree)
        possibleDirs = []
        while len(dirs) != 0:
            name = dirs[0]
            dirs = dirs[1:]
            fullPath = os.path.join(subPlanTree, name)
            if os.path.isfile(fullPath):
                continue
            if fullPath.find(".aborted.") != -1:
                continue
            if os.path.isdir(os.path.join(fullPath, "APC_FILES")):
                if fullPath.find(testName) != -1:
                    possibleDirs.append(fullPath)
            else:
                subdirs = os.listdir(fullPath)
                for subdir in subdirs:
                    if os.path.isdir(os.path.join(fullPath, subdir)):
                        dirs.append(os.path.join(name,subdir))
        return possibleDirs
    def suiteDescription(self):
        return repr(self.suite.app) + " " + self.suite.classId() + " " + self.suite.name
    def chooseSubPlan(self):
        suiteDescription = self.suiteDescription()        
        subPlanTree = os.path.join(self.suite.environment["CARMUSR"], "LOCAL_PLAN")
        dirs = []
        tryName = self.name
        dirName = None
        while dirName == None:
            dirs = self.findMatchingSubdirs(subPlanTree, tryName)
            if len(dirs) == 0:
                print "There are no subplans matching '" + tryName + "' in", suiteDescription
            else:
                dirName = self.chooseDir(dirs, suiteDescription, tryName);
            if dirName == None:
                print "Please input a subplan name (partial name is ok) ?"
                tryName = sys.stdin.readline().strip();
        return dirName

# Base class for importing of test cases and test suites,
# see example usage in apc.py
#
class ImportTest(plugins.Action):
    def __repr__(self):
        return "Importing into"
    def getTestCaseInformation(self, suite, name):
        return TestCaseInformation(suite, name)

    def getTestSuiteInformation(self, suite, name):
        return TestSuiteInformation(suite, name)
    
    def setUpSuite(self, suite):
        if not os.environ.has_key("CARMSYS"):
            return
        for testline in open(suite.testCaseFile).readlines():
            if testline != '\n' and testline[0] != '#':
                if carmen.isUserSuite(suite):
                    testInfo = self.getTestCaseInformation(suite, testline.strip())
                else:
                    testInfo = self.getTestSuiteInformation(suite, testline.strip())
                if not testInfo.isComplete():
                    if testInfo.makeImport() == 1:
                        self.describe(suite, testInfo.postText())

    def makeUser(self, userInfo, carmUsrDir):
        return 0
    
    def testForImportTestCase(self, testInfo):
        return 0

