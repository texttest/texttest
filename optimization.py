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
helpScripts = """optimization.PlotTest [++] - Displays a gnuplot graph with the cpu time (in minutes) versus total cost. 
                             The data is extracted from the status file of test(s), and if the test is
                             currently running, the temporary status file is used, see however the
                             option nt below. All tests selected are plotted in the same graph.
                             The following options are supported:
                             - r=range
                               The x-axis has the range range. Default is the whole data set. Example: 60:
                             - p=an absolute file name
                               Produces a postscript file instead of displaying the graph.
                             - pc
                               The postscript file will be in color.
                             - i=item
                               Which item to plot from the status file. Note that whitespaces are replaced
                               by underscores. Default is TOTAL cost. Example: i=overcover_cost.
                             - s
                               Plot against solution number instead of cpu time.
                             - nt
                               Do not use status file from the currently running test.
                             - b
                               Plots both the original and the currently running test. 
                             - ns
                               Do not scale times with the performance of the test.
                             - nv
                               No line type grouping for different versions of the test.
                             - v=v1,v2
                               Plot multiple versions in same dia, ie 'v=,9' means master and version 9
                               
optimization.StartStudio   - Start ${CARMSYS}/bin/studio with CARMUSR and CARMTMP set for specific test
                             This is intended to be used on a single specified test and will terminate
                             the testsuite after it starts Studio. It is a simple shortcut to set the
                             correct CARMSYS etc. environment variables for the test and run Studio.
"""


import carmen, os, sys, string, shutil, KPI, plugins, performance, math, re, predict

class OptimizationConfig(carmen.CarmenConfig):
    def getOptionString(self):
        return "k:" + carmen.CarmenConfig.getOptionString(self)
    def getActionSequence(self):
        if self.optionMap.has_key("kpi"):
	    listKPIs = [KPI.cSimpleRosteringOptTimeKPI,
			KPI.cFullRosteringOptTimeKPI,
			KPI.cWorstBestRosteringOptTimeKPI,
			KPI.cRosteringQualityKPI]
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
    def printHelpScripts(self):
        carmen.CarmenConfig.printHelpScripts(self)
        print helpScripts

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
        diag = plugins.getDiagnostics("Extract subplan")
        targetFile = test.getTmpFileName(self.targetName, "w")
        diag.info("Extracting " + sourcePath + " to " + targetFile)
        if os.path.isfile(sourcePath):
            shutil.copyfile(sourcePath, targetFile)
            if carmen.isCompressed(targetFile):
                targetFileZ = targetFile + ".Z"
                os.rename(targetFile, targetFileZ)
                os.system("uncompress " + targetFileZ)
            return
        if os.path.isfile(test.makeFileName(self.targetName)):
            errText = "Expected file '" + sourcePath + "' not created by test"
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
        if not test.app.parallelMode:
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

class StartStudio(plugins.Action):
    def __call__(self, test):
        print "CARMSYS:", os.environ["CARMSYS"]
        print "CARMUSR:", os.environ["CARMUSR"]
        print "CARMTMP:", os.environ["CARMTMP"]
        commandLine = os.path.join(os.environ["CARMSYS"], "bin", "studio")
        print os.popen(commandLine).readline()
        sys.exit(0)

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
methodEntryName = "Running.*\.\.\."
newSolutionMarker = "new solution"

#Probably different for APC and matador : static data for the text in the log file
itemNamesInFile = {}

# Static data for what data to check in CheckOptimizationRun, and what methods to avoid it with
noIncreaseExceptMethods = {}
class CheckOptimizationRun(predict.CheckLogFilePredictions):
    def __repr__(self):
        return "Checking optimization values for"
    def __call__(self, test):
        self.describe(test)
        interestingValues = noIncreaseExceptMethods.keys()
        # Note also that CSL parameter changes in rostering can cause the cost to go up
        if test.name.find("CSL_param") != -1:
            interestingValues.remove(costEntryName)
        optRun = OptimizationRun(test, "", [], interestingValues + [ methodEntryName ])
        for value in interestingValues:
            oldValue, newValue = self.findIncrease(optRun, value)
            if oldValue != None:
                self.insertError(test, "Increase in " + value + " (from " + str(oldValue) + " to " + str(newValue) + ")")
    def findIncrease(self, optRun, entry):
        lastEntry = None
        for solution in optRun.solutions:
            if not solution.has_key(entry):
                continue
            currEntry = solution[entry]
            optRun.diag.info("Checking solution " + repr(solution))
            if lastEntry != None and self.hasIncreased(entry, currEntry, lastEntry) and self.shouldCheckMethod(entry, solution):
                return lastEntry, currEntry
            lastEntry = currEntry
        return None, None
    def hasIncreased(self, entry, currEntry, lastEntry):
        if currEntry <= lastEntry:
            return 0
        # For cost, allow a certain tolerance corresponding to CPLEX's tolerance
        if entry != costEntryName:
            return 1
        percIncrease = float(currEntry - lastEntry) / float(lastEntry)
        return percIncrease > 0.00001
    def shouldCheckMethod(self, entry, solution):
        currMethod = solution.get(methodEntryName, "")
        for skipMethod in noIncreaseExceptMethods[entry]:
            if currMethod.find(skipMethod) != -1:
                return 0
        return 1
    
class LogFileFinder:
    def __init__(self, test, tryTmpFile = 1):
        self.tryTmpFile = tryTmpFile
        self.test = test
        test.app.setConfigDefault("log_file", "output")
        self.logStem = test.app.getConfigValue("log_file")
    def findFile(self, version = ""):
        if self.tryTmpFile:
            logFile = self.findTempFile(self.test, version) 
            if logFile and os.path.isfile(logFile):
                print "Using temporary log file for test " + self.test.name + " version " + version
                return logFile
        logFile = self.test.makeFileName(self.logStem, version)
        if os.path.isfile(logFile):
            return logFile
        else:
            raise plugins.TextTestError, "Could not find log file for Optimization Run in test" + repr(self.test)
    def findSpecifiedFile(self, version, spec):
        if spec == "run":
            logFile = self.findTempFile(self.test, version)
            if logFile and os.path.isfile(logFile):
                return logFile
            else:
                raise plugins.TextTestError, ""
        elif spec == "orig":
            logFile = self.test.makeFileName(self.logStem, version)
            if os.path.isfile(logFile):
                return logFile
            else:
                raise plugins.TextTestError, ""
        else:
            print "Wrong spec"
            return None
    def findTempFile(self, test, version):
        fileInTest = self.findTempFileInTest(version, self.logStem)
        if fileInTest or self.logStem == "output":
            return fileInTest
        # Look for output, find appropriate temp subplan, and look there
        outputInTest = self.findTempFileInTest(version, "output")
        if outputInTest == None:
            return None
        grepCommand = "grep -E 'SUBPLAN' " + outputInTest
        grepLines = os.popen(grepCommand).readlines()
        if len(grepLines) > 0:
            currentFile = os.path.join(grepLines[0].split()[1], self.logStem)
            if os.path.isfile(currentFile):
                return currentFile
        else:
            print "Could not find subplan name in output file " + fileInTest + os.linesep
    def findTempFileInTest(self, version, stem):                           
        for file in os.listdir(self.test.abspath):
            versionMod = ""
            if version:
                versionMod = "." + version
            if file.startswith(stem) and file.find(self.test.app.name + versionMod + self.test.getTestUser()) != -1:
                return file
        return None

class OptimizationRun:
    def __init__(self, test, version, definingItems, interestingItems, scale = 1, tryTmpFile = 0, specFile = ""):
        self.diag = plugins.getDiagnostics("optimization")
        self.performance = performance.getTestPerformance(test, version) # float value
        logFinder = LogFileFinder(test, tryTmpFile)
        if specFile == "":
            self.logFile = logFinder.findFile(version)
        else:
            self.logFile = logFinder.findSpecifiedFile(version, specFile)
        self.diag.info("Reading data from " + self.logFile)
        self.penaltyFactor = 1.0
        allItems = definingItems + interestingItems
        calculator = OptimizationValueCalculator(allItems, self.logFile)
        self.solutions = calculator.getSolutions(definingItems)
        if scale and self.solutions and timeEntryName in allItems:
            self.scaleTimes()
        self.diag.debug("Solutions :" + repr(self.solutions))
    def scaleTimes(self):
        finalTime = self.solutions[-1][timeEntryName]
        if finalTime == 0.0:
            return
        scaleFactor = self.performance / finalTime
        self.diag.info("Scaling times by factor " + str(scaleFactor))
        for solution in self.solutions:
            solution[timeEntryName] *= scaleFactor    
    def isVeryShort(self):
        return len(self.solutions) < 3 or self.getPerformance() == 0
    def getCost(self, solNum = -1):
        return self.solutions[solNum][costEntryName]
    def getPerformance(self, solNum = -1): # return int for presentation
        return int(round(self.solutions[solNum][timeEntryName]))
    def getMaxMemory(self):
        maxMemory = "??"
        for solution in self.solutions:
            if not solution.has_key(memoryEntryName):
                continue
            memory = solution[memoryEntryName]
            if maxMemory == "??" or memory > maxMemory:
                maxMemory = memory
        return maxMemory
    def timeToCost(self, targetCost):
        if len(self.solutions) < 2 or self.solutions[-1][costEntryName] < targetCost:
            return self._timeToCostNoPenalty(targetCost)
        penalizedTime = self.getPerformance() * self.penaltyFactor
        return int(penalizedTime)
    def _timeToCostNoPenalty(self, targetCost):
        lastCost = 0
        lastTime = 0
        for solution in self.solutions:
            if solution[costEntryName] < targetCost:
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
            if solution[timeEntryName] > targetTime:
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
            diff = solution[costEntryName] - lastCost
            if (1.0 * diff / lastCost) * 100.0 > margin:
                if ix == 0:
                    return -1
                else:
                    return -1 * ix
        return 2

class OptimizationValueCalculator:
    def __init__(self, items, logfile):
        regexps = {}
        for item in items:
            regexps[item] = self.getItemRegexp(item)
        newSolutionRegexp = self.getItemRegexp(newSolutionMarker)
        self.solutions = [{}]
        for line in open(logfile).xreadlines():
            if newSolutionRegexp.search(line):
                self.solutions.append({})
                continue
            for item, regexp in regexps.items():
                if regexp.search(line):
                     self.solutions[-1][item] = self.calculateEntry(item, line)
    def getSolutions(self, definingItems):
        solutions = []
        for solution in self.solutions:
            if self.isComplete(solution, definingItems):
                solutions.append(solution)
        return solutions
    def isComplete(self, solution, definingItems):
        for item in definingItems:
            if not item in solution.keys():
                if solution is self.solutions[0] and item == timeEntryName:
                    solution[timeEntryName] = 0.0
                else:
                    return 0
        return 1
    def getItemRegexp(self, item):
        if itemNamesInFile.has_key(item):
            return re.compile(itemNamesInFile[item])
        else:
            return re.compile(item)
    def calculateEntry(self, item, line):
        if item == timeEntryName:
            return self.convertTime(line)
        elif item == memoryEntryName:
            return self.getMemory(line)
        elif item == methodEntryName:
            return self.getMethod(line)
        else: # Default assumes a numeric value as the last field of the line
            return self.getFinalNumeric(line)
    def getFinalNumeric(self, line):
        lastField = line.split(" ")[-1]
        return int(lastField.strip())
    def convertTime(self, timeLine):
        timeEntry = self.getTimeEntry(timeLine.strip())
        entries = timeEntry.split(":")
        timeInSeconds = int(entries[0]) * 3600 + int(entries[1]) * 60 + int(entries[2].strip()) 
        return float(timeInSeconds) / 60.0
    def getMethod(self, methodLine):
        method = methodLine.replace("Running ", "")
        return method.replace("...", "")
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
                memNum = entries[index - 1]
                if memNum.find(".") == -1:
                    return int(memNum)
                else:
                    return float(memNum)
        return 0
    
class TestReport(plugins.Action):
    def __init__(self, versionString):
        versions = versionString.split(",")
        self.referenceVersion = versions[0]
        self.currentVersion = None
        if len(versions) > 1:
            self.currentVersion = versions[1]
    def __call__(self, test):
        # Values that must be present for a solution to be considered
        definingValues = [ costEntryName, timeEntryName ]
        # Values that should be reported if present, but should not be fatal if not
        interestingValues = [ memoryEntryName, "cost of rosters" ]
        currentRun = OptimizationRun(test, self.currentVersion, definingValues, interestingValues)
        referenceRun = OptimizationRun(test, self.referenceVersion, definingValues, interestingValues)
        if currentRun.logFile != referenceRun.logFile:
            self.compare(test, referenceRun, currentRun)
    
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
    def compare(self, test, referenceRun, currentRun):
	referenceFile = referenceRun.logFile
	currentFile = currentRun.logFile
        floatRefPerfScale = performance.getTestPerformance(test, self.referenceVersion)
        floatNowPerfScale = performance.getTestPerformance(test, self.currentVersion)
	#print 'ref: %f, now: %f' %(floatRefPerfScale, floatNowPerfScale)
	#print 'Ref : ' + referenceFile
	#print 'Curr: ' + currentFile
        if currentFile != referenceFile:
	    aKPI = None
	    listKPIs = []
	    for aKPIConstant in self.listKPIs:
		aKPI = self.KPIHandler.createKPI(aKPIConstant, referenceFile, currentFile, floatRefPerfScale, floatNowPerfScale)
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
        if currCost < refCost:
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
            if entry.find("cost") != -1 and entry in referenceRun.solutions[0].keys():
                costEntries.append(entry)
        costEntries.sort()
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

# Class for using gnuplot to plot test curves of tests
#
class PlotTest(plugins.Action):
    def __init__(self, args = []):
        self.plotFiles = []
        self.plotItem = costEntryName
        self.plotrange = "0:"
        self.plotPrint = None
        self.plotPrintColor = None
        self.plotAgainstSolNum = 0
        self.plotVersions = [ "" ]
        self.plotScaleTime = 1
        self.plotVersionColoring = 1
        self.plotUseTmpStatus = 1
        self.plotStates = [ "" ]
        self.interpretOptions(args)
    def interpretOptions(self, args):
        for ar in args:
            arr = ar.split("=")
            if arr[0]=="r":
                self.plotrange = arr[1]
            elif arr[0]=="p":
                self.plotPrint = arr[1]
            elif arr[0]=="pc":
                self.plotPrintColor = 1
            elif arr[0]=="s":
                self.plotAgainstSolNum = 1
            elif arr[0]=="v":
                self.plotVersions = arr[1].split(",")
            elif arr[0]=="b":
                self.plotStates = [ "run" , "orig" ]
            elif arr[0]=="ns":
                self.plotScaleTime = 0
            elif arr[0]=="nt":
                self.plotUseTmpStatus = 0
            elif arr[0]=="nv":
                self.plotVersionColoring = 0
            elif arr[0]=="i":
                self.plotItem = arr[1].replace("_"," ")
            else:
                print "Unknown option " + arr[0]
    def getYlabel(self):
        if itemNamesInFile.has_key(self.plotItem):
            return itemNamesInFile[self.plotItem]
        else:
            return self.plotItem
    def setPointandLineTypes(self):
        if len(self.plotVersions)>1 or len(self.plotStates)>1:
            # Choose line type.
            self.versionLineType = {}
            counter = 2
            for versionIndex in range(len(self.plotVersions)):
                for stateIndex in range(len(self.plotStates)):
                    self.versionLineType[self.plotVersions[versionIndex],self.plotStates[stateIndex]] = counter
                    counter = counter + 1
            # Choose point type.
            self.testPointType = {}
            counter = 1
            for file in self.plotFiles:
                name = file.split(os.sep)[-3] + "::" + file.split(os.sep)[-2]
                if not self.testPointType.has_key(name):
                    self.testPointType[name] = counter
                    counter = counter + 1
    def getStyle(self,ver,state,name):
        if (len(self.plotVersions)>1 or len(self.plotStates)>1) and self.plotVersionColoring:
            style = " with linespoints lt " +  str(self.versionLineType[ver,state]) + " pt " + str(self.testPointType[name])
        else:
            style = " with linespoints "
        return style
    def __repr__(self):
        return "Plotting"
    def __del__(self):
        if len(self.plotFiles) > 0:
            stdin, stdout, stderr = os.popen3("gnuplot -persist -background white")
            self.setPointandLineTypes()

            fileList = []
            for file in self.plotFiles:
                ver = file.split(os.sep)[-1].split(".")[-2]
                state = file.split(os.sep)[-1].split(".")[-1]
                name = file.split(os.sep)[-3] + "::" + file.split(os.sep)[-2]
                title = " title \"" + name + " " + ver + " " + state + "\" "
                fileList.append("'" + file + "' " + title + self.getStyle(ver,state,name))

            if self.plotPrint:
                absplotPrint = os.path.expanduser(self.plotPrint)
                if not os.path.isabs(absplotPrint):
                    print "An absolute path must be given."
                    return
                stdin.write("set terminal postscript")
                if self.plotPrintColor:
                    stdin.write(" color")
                stdin.write(os.linesep)

            stdin.write("set ylabel '" + self.getYlabel() + "'" + os.linesep)
            if self.plotAgainstSolNum:
                stdin.write("set xlabel 'Solution number'" + os.linesep)
            else: 
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
    def __call__(self, test):
        for version in self.plotVersions:
            for state in self.plotStates:
                try:
                    optRun = OptimizationRun(test, version, [ self.plotItem, timeEntryName ], [], self.plotScaleTime, self.plotUseTmpStatus, state)
                except plugins.TextTestError:
                    print "No status file does exist for test " + test.name + "(" + version + ")"
                    continue

                plotFileName = test.makeFileName("plot") + "." + version + "." + state
                plotFile = open(plotFileName, "w")
                for solution in optRun.solutions:
                    if self.plotAgainstSolNum:
                        plotFile.write(str(solution[self.plotItem]) + os.linesep)
                    else:
                        plotFile.write(str(solution[timeEntryName]) + "  " + str(solution[self.plotItem]) + os.linesep)
                self.plotFiles.append(plotFileName)

