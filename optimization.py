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

helpOptions = """-prrep <v> - Generate a Progress Report relative to the version <v>. This will produce some
             key numbers for all tests specified.

-kpi <ver> - Generate a Key Performance Indicator ("KPI") relative to the version <ver>. This will try to apply
             some formula to boil down the results of the tests given to a single-number "performance indicator".
             Please note that the results so far are not very reliable, as the formula itself is still under development.

-keeptmp   - Keep the temporary subplan directories of the test(s). Note that once you run the test again the old
             temporary subplan dirs will be removed, unless you run in parallell mode of course.       
"""

import carmen, os, sys, string, shutil, KPI, plugins, performance, math, re

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
    def keepTemporarySubplans(self):
        if self.optionMap.has_key("keeptmp"):
            return 1
        return 0
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
            if file == "input":
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
                if self.config.keepTemporarySubplans():
                    print test.getIndent() + "Keeping subplan dir for", repr(test), "in", tmpDir
                    return
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

# Names of reported entries
costEntryName = "cost of plan"
timeEntryName = "cpu time"
memoryEntryName = "memory"

#Probably different for APC and matador
itemNamesInFile = {}

class OptimizationRun:
    def __init__(self, test, version, itemList, margin = 0.0):
        self.solutions = []
        self.performance = performance.getTestPerformance(test, version) # float value
        self.logFile = test.makeFileName(test.app.getConfigValue("log_file"), version)
        calculator = OptimizationValueCalculator(itemList, self.logFile)
        for item in itemList:
            valueList = calculator.getValues(item)
            if len(valueList) > 0:
                self.addSolutionData(item, valueList)
    def addSolutionData(self, item, valueList):
        for i in range(len(valueList)):
            if len(self.solutions) <= i:
                self.solutions.append({})
            entry = valueList[i]
            # Scale by performance
            if item == timeEntryName and valueList[-1] > 0.0:
                entry = valueList[i] / valueList[-1] * self.performance
            self.solutions[i][item] = entry
    def isVeryShort(self):
        return len(self.solutions) < 3 or self.getPerformance() == 0
    def getCost(self, solNum = -1):
        return self.solutions[solNum][costEntryName]
    def getPerformance(self, solNum = -1): # return int for presentation
        return int(round(self.solutions[solNum][timeEntryName]))
    def getMaxMemory(self):
        maxMemory = 0
        for solution in self.solutions:
            if not solution.has_key(memoryEntryName):
                return "??"
            memory = solution[memoryEntryName]
            if memory > maxMemory:
                maxMemory = memory
        return maxMemory
    def timeToCost(self, targetCost):
        lastCost = 0
        lastTime = 0
        for solution in self.solutions:
            if abs(solution[costEntryName]) < abs(targetCost):
                costGap = lastCost - solution[costEntryName]
                percent = float(lastCost - targetCost) / costGap
                performance = lastTime + (solution[timeEntryName] - lastTime) * percent
                return int(round(performance))
            else:
                lastCost = solution[costEntryName]
                lastTime = solution[timeEntryName]
        return self.getPerformance()
    def costAtTime(self, targetTime):
        lastCost = 0
        lastTime = 0
        for solution in self.solutions:
            if abs(solution[timeEntryName]) > abs(targetTime):
                timeGap = lastTime - solution[timeEntryName]
                percent = float(lastTime - targetTime) / timeGap
                cost = lastCost + (solution[costEntryName] - lastCost) * percent
                return int(round(cost))
            else:
                lastCost = solution[costEntryName]
                lastTime = solution[timeEntryName]
        return lastCost
    def getMeasuredSolution(self, margin):
        if margin == 0.0 or self.isVeryShort():
            return -1
    
        lastCost = self.getCost(-1)
        for ix in range(len(self.solutions) - 2):
            solution = self.solutions[-1 * (ix + 2)]
            diff = abs(solution[costEntryName] - lastCost)
            if (1.0 * diff / lastCost) * 100.0 > margin:
                if ix == 0:
                    return -1
                else:
                    return -1 * ix
        return 2

class OptimizationValueCalculator:
    def __init__(self, itemList, logfile):
        command = "grep -E '" + string.join(map(self.getItemName, itemList),"|") + "' " + logfile
        grepLines = os.popen(command).readlines()
        self.itemValues = {}
        lastItemLine = {}
        rexpItem = {}
        convertFuncs = {}
        for item in itemList:
            self.itemValues[item] = []
            rexpItem[item] = re.compile(self.getItemName(item))
            lastItemLine[item] = ""
            convertFuncs[item] = self.getConversionFunction(item)
        #
        # Matador needs this 'inital' hack, because it does not have a time entry for
        # the inital input analysis.
        #
        initial = 1
        lastItemLine[timeEntryName] = "cpu time:  0:00:00"
        lastItemLine[memoryEntryName] = "Memory consumption: 0 MB"
        
        for line in grepLines:
            for item in itemList:
                if rexpItem[item].search(line):
                    lastItemLine[item] = line
                    if (initial and self._hasValuesForAll(itemList, lastItemLine)) or item == timeEntryName:
                        if initial or self._hasValuesForAll(itemList, lastItemLine):
                            for it in itemList:
                                self.itemValues[it].append(convertFuncs[it](lastItemLine[it]))
                        initial = 0
                        for it in itemList:                                
                            lastItemLine[it] = ""
    def _hasValuesForAll(self, itemList, lineMap):
        for item in itemList:
            if not lineMap.has_key(item) or lineMap[item] == "":
                return 0
        return 1
    def getItemName(self, item):
        if itemNamesInFile.has_key(item):
            return itemNamesInFile[item]
        else:
            return item
    def getValues(self, item):
        if self.itemValues.has_key(item):
            return self.itemValues[item]
        return None
    def getConversionFunction(self, item):
        if item == timeEntryName:
            return self.convertTime
        elif item == memoryEntryName:
            return self.getMemory
        else: # Default assumes a numeric value as the last field of the line
            return self.getFinalNumeric
    def getFinalNumeric(self, line):
        lastField = line.split(" ")[-1]
        return int(lastField.strip())
    def convertTime(self, timeLine):
        timeEntry = self.getTimeEntry(timeLine.strip())
        entries = timeEntry.split(":")
        timeInSeconds = int(entries[0]) * 3600 + int(entries[1]) * 60 + int(entries[2].strip()) 
        return float(timeInSeconds) / 60.0
    def getTimeEntry(self, line):
        entries = line.split(" ")
        for index in range(len(entries)):
            if entries[index] == "cpu":
                sIx = index + 2
                while sIx < len(entries):
                    if entries[sIx] != "":
                        return entries[sIx]
                    sIx += 1
        return line
    def getMemory(self, memoryLine):
        entries = memoryLine.split(" ")
        for index in range(len(entries)):
            entry = entries[index].strip()
            if entry == "MB" or entry == "Mb" or entry == "Mb)":
                mem = float(entries[index - 1])
                return mem
            
class TestReport(plugins.Action):
    def __init__(self, versionString):
        versions = versionString.split(",")
        self.referenceVersion = versions[0]
        self.currentVersion = None
        if len(versions) > 1:
            self.currentVersion = versions[1]
    def __call__(self, test):
        interestingValues = self.getInterestingValues()
        currentRun = OptimizationRun(test, self.currentVersion, interestingValues)
        referenceRun = OptimizationRun(test, self.referenceVersion, interestingValues)
        if currentRun.logFile != referenceRun.logFile:
            self.compare(test, referenceRun, currentRun)
    def getInterestingValues(self):
        return [ costEntryName, timeEntryName, memoryEntryName, "cost of rosters" ]

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
        self.totalKpi = 1.0
        self.testCount = 0
        self.bestKpi = 1.0
        self.worstKpi = 1.0
    def __del__(self):
        if self.testCount > 0:
            avg = math.pow(self.totalKpi, 1.0 / float(self.testCount))
            print os.linesep, "Overall average KPI with respect to version", self.referenceVersion, "=", self.percent(avg)
            print "Best KPI with respect to version", self.referenceVersion, "=", self.percent(self.bestKpi)
            print "Worst KPI with respect to version", self.referenceVersion, "=", self.percent(self.worstKpi)
    def __repr__(self):
        return "Comparison on"
    def setUpApplication(self, app):
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
                self.totalKpi *= kpi
                if kpi > self.worstKpi:
                    self.worstKpi = kpi
                if kpi < self.bestKpi:
                    self.bestKpi = kpi
            return self.percent(kpi)
        else:
            return "NaN%"
    def compare(self, test, referenceRun, currentRun):
        userName = os.path.normpath(os.environ["CARMUSR"]).split(os.sep)[-1]
        self.doCompare(test, referenceRun, currentRun, userName)
    def doCompare(self, test, referenceRun, currentRun, userName):
        if currentRun.isVeryShort() or referenceRun.isVeryShort():
            return

        worstCost = self.calculateWorstCost(test, referenceRun, currentRun)
        currTTWC = currentRun.timeToCost(worstCost)
        refTTWC = referenceRun.timeToCost(worstCost)
        
        self.testCount += 1
        kpi = self.computeKPI(currTTWC, refTTWC)
        print os.linesep, "Comparison on", test.app, "test", test.name, "(in user " + userName + ") : K.P.I. = " + kpi
        self.reportLine("                         ", self.currentText(), "Version " + self.referenceVersion)
        self.reportCosts(test, currentRun, referenceRun)
        self.reportLine("Max memory (MB)", currentRun.getMaxMemory(), referenceRun.getMaxMemory())
        self.reportLine("Total time (minutes)     ", currentRun.getPerformance(), referenceRun.getPerformance())
        self.reportLine("Time to cost " + str(worstCost) + " (mins)", currTTWC, refTTWC)
    def calculateWorstCost(self, test, referenceRun, currentRun):
        currMargin, refMargin = self.getMargins(test)
        currSol = currentRun.getMeasuredSolution(currMargin)
        refSol = referenceRun.getMeasuredSolution(refMargin)
        currCost = currentRun.getCost(currSol)
        refCost = referenceRun.getCost(refSol)
        if abs(currCost) < abs(refCost):
            return refCost
        else:
            return currCost
    def getMargins(self, test):
        try:
            refMargin = float(test.app.getConfigValue("kpi_cost_margin"))
        except:
            refMargin = 0.0
        return refMargin, refMargin
    def reportCosts(self, test, currentRun, referenceRun):
        costEntries = []
        for entry in currentRun.solutions[0].keys():
            if entry.find("cost") != -1:
                costEntries.append(entry)
        for entry in costEntries:
            self.reportLine("Initial " + entry, currentRun.solutions[0][entry], referenceRun.solutions[0][entry])
        for entry in costEntries:
            self.reportLine("Final " + entry, currentRun.solutions[-1][entry], referenceRun.solutions[-1][entry])
    def currentText(self):
        if self.currentVersion == None:
            return "Current"
        else:
            return "Version " + self.currentVersion
    def reportLine(self, title, currEntry, refEntry):
        fieldWidth = 15
        titleWidth = 30
        print string.ljust(title, titleWidth) + ": " + string.rjust(str(currEntry), fieldWidth) + string.rjust(str(refEntry), fieldWidth)
    
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

# Base class for using gnuplot to plot test curves of tests
#
class PlotTest(plugins.Action):
    def __init__(self, args = []):
        self.plotFiles = []
        self.statusFileName = None
        self.plotItem = None
        self.plotrange = "0:"
        self.plotPrint = []
        self.plotAgainstSolNum = []
        self.plotVersions = [ "" ]
        self.plotScaleTime = "t"
    def interpretOptions(self, args):
        for ar in args:
            arr = ar.split("=")
            if arr[0]=="r":
                self.plotrange = arr[1]
            elif arr[0]=="p":
                self.plotPrint = arr[1]
            elif arr[0]=="s":
                self.plotAgainstSolNum = "t"
            elif arr[0]=="v":
                self.plotVersions = arr[1].split(",")
            elif arr[0]=="ns":
                self.plotScaleTime = None
            elif not self.setOption(arr):
                print "Unknown option " + arr[0]
    def setOption(self, arr):
        return 0
    def getYlabel(self):
        return self.plotItem
    def __repr__(self):
        return "Plotting"
    def __del__(self):
        if len(self.plotFiles) > 0:
            stdin, stdout, stderr = os.popen3("gnuplot -persist")
            fileList = []
            style = " with linespoints"
            for file in self.plotFiles:
                ver = file.split(os.sep)[-1].split(".",1)[-1]
                name = file.split(os.sep)[-3] + "::" + file.split(os.sep)[-2]
                title = " title \"" + name + " " + ver + "\" "
                fileList.append("'" + file + "' " + title + style)
            if self.plotPrint:
                absplotPrint = os.path.expanduser(self.plotPrint)
                if not os.path.isabs(absplotPrint):
                    print "An absolute path must be given."
                    return
                stdin.write("set terminal postscript" + os.linesep)

            stdin.write("set ylabel '" + self.getYlabel() + "'" + os.linesep)
            stdin.write("set xlabel 'CPU time (min)'" + os.linesep)
            stdin.write("set time" + os.linesep)
            stdin.write("set xtics border nomirror norotate" + os.linesep)
            stdin.write("set ytics border nomirror norotate" + os.linesep)
            stdin.write("set border 3" + os.linesep)
            stdin.write("set xrange [" + self.plotrange +"];" + os.linesep)
            stdin.write("plot " + string.join(fileList, ",") + os.linesep)
            stdin.write("quit" + os.linesep)
            if self.plotPrint:
                stdin.close()
                tmppf = stdout.read()
                if len(tmppf) > 0:
                    open(absplotPrint,"w").write(tmppf)

    def getCostsAndTimes(self, file, plotItem):
        costs = []
        times = []
        return costs, times
    def getStatusFile(self, test, version):
        currentFile = test.makeFileName(self.statusFileName, version)
        if not os.path.isfile(currentFile):
            return None
        return currentFile
    def scaleTimes(self, times, test, version):
        totPerf = int(performance.getTestPerformance(test, version))
        if totPerf < 1:
            return times
        scaleFactor = float(1.0 * totPerf / times[-1])
        ntimes = []
        for t in times:
            ntimes.append(t * scaleFactor)
        return ntimes
    def __call__(self, test):
        for version in self.plotVersions:
            currentFile = self.getStatusFile(test, version)
            if currentFile == None:
                print "No status file does exist for test " + test.name + "(" + version + ")"
                return
            costs, times = self.getCostsAndTimes(currentFile, self.plotItem)
            if self.plotScaleTime:
                times = self.scaleTimes(times, test, version)
            plotFileName = test.makeFileName("plot")
            if len(version) > 0:
                plotFileName += "." + version
            plotFile = open(plotFileName,"w")
            for il in range(len(costs)):
                if self.plotAgainstSolNum:
                    plotFile.write(str(costs[il]) + os.linesep)
                else:
                    plotFile.write(str(times[il]) + "  " + str(costs[il]) + os.linesep)
            self.plotFiles.append(plotFileName)
    def setUpSuite(self, suite):
        pass
    def setUpApplication(self, app):
        self.statusFileName = app.getConfigValue("log_file")
