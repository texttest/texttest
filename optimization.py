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
                             - i=[appname:]item,item,...
                               Which item to plot from the status file. Note that whitespaces are replaced
                               by underscores. Default is TOTAL cost. Example: i=overcover_cost.
                               If a comma-seperated list is given, all the listed items are plotted.
                               An abreviation is 'i=apctimes', which is equivalent to specifying 'i=OC_to_DH_time,
                               Generation_time,Costing_time,Conn_fixing,Optimization_time,Network_generation_time'.
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
                             - sg
                               Plot all tests chosen on the same graph, rather than one window per test
                               
optimization.JoinPlot      - As PlotTest above but allows plots of multiple apps in same diag

optimization.TableTest     - Displays solution data in a table. Works the same as PlotTest in most respects,
                             in terms of which data is displayed and the fact that temporary files are used if possible.
                             Currently supports these options:
                             - nt
                               Do not use status file from the currently running test.
                             - ns
                               Do not scale times with the performance of the test. 
                             - i=<item>,<item>,...
                               Which items to print in the table. Note that whitespaces are replaced
                               by underscores. Default is TOTAL cost and cpu time only.
                               Example: i=cost_of_roster,rost/sec,Generated_rosters
                             
optimization.StartStudio   - Starts up Studio (with ${CARMSYS}/bin/studio) and loads the subplan, with
                             CARMUSR and CARMTMP set for the specific test. This is intended to be used
                             on a single specified test and will terminate the testsuite after it starts
                             Studio. If serveral tests are specified, the subplan will be loaded for the
                             first one. It is a simple shortcut to set the correct CARMSYS etc. environment
                             variables for the test and run Studio.
                             
optimization.TraverseSubPlans
                           - Traverses all subplan directories associated with the selected tests,
                             and executes the command specified by argument. Be careful to quote the command
                             if you use options, otherwise texttest will try to interpret the options.
                             Example: texttest -s carmen.TraverseCarmUsers "pwd".
                             This will display the path of all subplan directories in the test suite.
                             Example:
                             texttest -apc -s carmen.TraverseCarmUsers "grep use_column_generation_method APC_FILES/rules"
                             This will show for which APC tests the column generation method is used.
"""


import carmen, os, sys, string, shutil, KPI, plugins, performance, math, re, predict, unixConfig, lsf

itemNamesConfigKey = "_itemnames_map"
noIncreasMethodsConfigKey = "_noincrease_methods_map"

# Names of reported entries
costEntryName = "cost of plan"
timeEntryName = "cpu time"
memoryEntryName = "memory"
methodEntryName = "Running.*\.\.\."
newSolutionMarker = "new solution"
solutionName = "solution"

class OptimizationConfig(carmen.CarmenConfig):
    def __init__(self, optionMap):
        carmen.CarmenConfig.__init__(self, optionMap)
        #Probably different for APC and matador : static data for the text in the log file
        self.itemNamesInFile = {}
        # Static data for what data to check in CheckOptimizationRun, and what methods to avoid it with
        self.noIncreaseExceptMethods = {}
    def getArgumentOptions(self):
        options = carmen.CarmenConfig.getArgumentOptions(self)
        options["prrep"] = "Run KPI progress report"
        options["kpiData"] = "Output KPI curve data etc."
        options["kpi"] = "Run Henrik's old KPI"
        return options
    def getSwitches(self):
        switches = carmen.CarmenConfig.getSwitches(self)
        switches["debug"] = "Build debug compiled ruleset"
        return switches
    def getActionSequence(self):
        if self.optionMap.has_key("kpi"):
            listKPIs = [KPI.cSimpleRosteringOptTimeKPI,
                        KPI.cFullRosteringOptTimeKPI,
                        KPI.cWorstBestRosteringOptTimeKPI,
                        KPI.cRosteringQualityKPI]
            return [ CalculateKPIs(self.optionValue("kpi"), listKPIs) ]
        if self.optionMap.has_key("kpiData"):
            listKPIs = [KPI.cSimpleRosteringOptTimeKPI]
            return [ WriteKPIData(self.optionValue("kpiData"), listKPIs) ]
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
            localFilter = carmen.UpdatedLocalRulesetFilter(self.getRuleSetName, self.getLibraryFile)
            return self.getCompileRules(localFilter)
    def getCompileRules(self, localFilter):
        if self.optionMap.has_key("debug"):
            modeString = "-debug"
        else:
            modeString = "-optimize"
        return carmen.CompileRules(self.getRuleSetName, modeString, localFilter)
    def getTestRunner(self):
        return plugins.CompositeAction([ MakeTmpSubPlan(self._getSubPlanDirName), self.getSpecificTestRunner() ])
    def getSpecificTestRunner(self):
        return carmen.CarmenConfig.getTestRunner(self) 
    def getTestCollator(self):
        solutionCollator = unixConfig.CollateFile("best_solution", "solution")
        return plugins.CompositeAction([ carmen.CarmenConfig.getTestCollator(self), solutionCollator ])
    def getInteractiveActions(self):
        return [ ViewLog, PlotTest, TableTest ]
    def printHelpDescription(self):
        print helpDescription
        carmen.CarmenConfig.printHelpDescription(self)
    def printHelpOptions(self, builtInOptions):
        carmen.CarmenConfig.printHelpOptions(self, builtInOptions)
        print helpOptions
    def printHelpScripts(self):
        carmen.CarmenConfig.printHelpScripts(self)
        print helpScripts
    def setUpApplication(self, app):
        app.setConfigDefault(itemNamesConfigKey, self.itemNamesInFile)
        app.setConfigDefault(noIncreasMethodsConfigKey, self.noIncreaseExceptMethods)


class MakeTmpSubPlan(plugins.Action):
    def __init__(self, subplanFunction):
        self.subplanFunction = subplanFunction
    def __call__(self, test):
        dirName = self.subplanFunction(test)
        if not os.path.isdir(dirName):
            raise plugins.TextTestError, "Cannot run test, subplan directory does not exist"
        rootDir, baseDir = os.path.split(dirName)
        tmpDir = test.makeWriteDirectory(rootDir, baseDir, "APC_FILES")
        parameterOverrides = test.app.getConfigList("rave_parameter")
        self.makeLinksIn(tmpDir, dirName, parameterOverrides)
    def makeLinksIn(self, inDir, fromDir, parameterOverrides):
        for file in os.listdir(fromDir):
            if file == "APC_FILES":
                apcFiles = os.path.join(inDir, file)
                self.makeLinksIn(apcFiles, os.path.join(fromDir, file), parameterOverrides)
                continue
            if file.find("Solution_") != -1:
                continue
            if file.find("status") != -1:
                continue
            if file.find("run_status") != -1:
                continue
            if file.find("hostname") != -1:
                continue
            if file.find("best_solution") != -1:
                continue
            if file.find("core") != -1:
                continue
            if file == "input":
                continue
            if file.endswith(".log"):
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
            
class StartStudio(plugins.Action):
    def __call__(self, test):
        print "CARMSYS:", os.environ["CARMSYS"]
        print "CARMUSR:", os.environ["CARMUSR"]
        print "CARMTMP:", os.environ["CARMTMP"]
        fullSubPlanPath = test.app.configObject._getSubPlanDirName(test)
        lPos = fullSubPlanPath.find("LOCAL_PLAN/")
        subPlan = fullSubPlanPath[lPos + 11:]
        localPlan = string.join(subPlan.split(os.sep)[0:-1], os.sep)
        studioCommand = "studio -p'CuiOpenSubPlan(gpc_info,\"" + localPlan + "\",\"" + subPlan + "\",0)'"
        commandLine = os.path.join(os.environ["CARMSYS"], "bin", studioCommand)
        print os.popen(commandLine).readline()
        sys.exit(0)

class CheckOptimizationRun(predict.CheckLogFilePredictions):
    def __repr__(self):
        return "Checking optimization values for"
    def __call__(self, test):
        self.describe(test)
        noIncreaseExceptMethods = test.app.getConfigValue(noIncreasMethodsConfigKey)
        interestingValues = noIncreaseExceptMethods.keys()
        # Note also that CSL parameter changes in rostering can cause the cost to go up
        if test.name.find("CSL_param") != -1:
            interestingValues.remove(costEntryName)
        optRun = OptimizationRun(test, "", [], interestingValues + [ methodEntryName ])
        for value in interestingValues:
            oldValue, newValue = self.findIncrease(optRun, value, noIncreaseExceptMethods)
            if oldValue != None:
                self.insertError(test, "Increase in " + value + " (from " + str(oldValue) + " to " + str(newValue) + ")")
    def findIncrease(self, optRun, entry, noIncreaseExceptMethods):
        lastEntry = None
        for solution in optRun.solutions:
            if not solution.has_key(entry):
                continue
            currEntry = solution[entry]
            optRun.diag.info("Checking solution " + repr(solution))
            if lastEntry != None and self.hasIncreased(entry, currEntry, lastEntry) and self.shouldCheckMethod(entry, solution, noIncreaseExceptMethods):
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
    def shouldCheckMethod(self, entry, solution, noIncreaseExceptMethods):
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
    def findFile(self, version = None):
        if self.tryTmpFile:
            if not version:
                version = string.join(self.test.app.versions, ".")
            logFile, tmpDir = self.findTempFile(self.test, version) 
            if logFile and os.path.isfile(logFile):
                print "Using temporary log file (from " + tmpDir + ") for test " + self.test.name + " version " + version
                return 1, logFile
        logFile = self.test.makeFileName(self.logStem, version)
        if os.path.isfile(logFile):
            return 0, logFile
        else:
            raise plugins.TextTestError, "Could not find log file for Optimization Run in test" + repr(self.test)
    def findSpecifiedFile(self, version, spec):
        if spec == "run":
            logFile, tmpDir = self.findTempFile(self.test, version)
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
        fileInTest, tmpDir = self.findTempFileInTest(version, self.logStem)
        if fileInTest or self.logStem == "output":
            return fileInTest, tmpDir
        # Look for output, find appropriate temp subplan, and look there
        outputInTest, tmpDir = self.findTempFileInTest(version, "output")
        if outputInTest == None:
            return None, None
        grepCommand = "grep -E 'SUBPLAN' " + outputInTest
        grepLines = os.popen(grepCommand).readlines()
        if len(grepLines) > 0:
            currentFile = os.path.join(grepLines[0].split()[1], self.logStem)
            if os.path.isfile(currentFile):
                return currentFile, tmpDir
        else:
            print "Could not find subplan name in output file " + fileInTest + os.linesep
    def findTempFileInTest(self, version, stem):
        versionMod = ""
        if version:
            versionMod = "." + version
        app = self.test.app
        searchString = app.name + versionMod + app.getTestUser()
        root, localDir = os.path.split(app.writeDirectory)
        for subDir in os.listdir(root):
            fullDir = os.path.join(root, subDir)
            if os.path.isdir(fullDir) and subDir.startswith(searchString):
                testDir = os.path.join(fullDir, self.test.getRelPath())
                if os.path.isdir(testDir):
                    for file in os.listdir(testDir):
                        # don't pick up comparison files
                        if file.startswith(stem) and not file.endswith("cmp"):
                            return os.path.join(testDir, file), subDir
        return None, None

class OptimizationRun:
    def __init__(self, test, version, definingItems, interestingItems, scale = 1, tryTmpFile = 0, specFile = "", givenLogFile = ""):
        self.diag = plugins.getDiagnostics("optimization")
        self.performance = performance.getTestPerformance(test, version) # float value
        if givenLogFile:
            self.logFile = givenLogFile
        else:
            logFinder = LogFileFinder(test, tryTmpFile)
            if specFile == "":
                foundTmp, self.logFile = logFinder.findFile(version)
                # Doesn't make sense to scale temporary files, as they probably aren't complete
                if foundTmp:
                    scale = 0
            else:
                self.logFile = logFinder.findSpecifiedFile(version, specFile)
        self.diag.info("Reading data from " + self.logFile)
        self.penaltyFactor = 1.0
        allItems = definingItems + interestingItems
        calculator = OptimizationValueCalculator(allItems, self.logFile, test.app.getConfigValue(itemNamesConfigKey))
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
        for solution in self.solutions[1:]:
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
    def __init__(self, items, logfile, itemNamesInFile):
        self.diag = plugins.getDiagnostics("optimization")
        self.diag.info("Building calculator for: " + logfile + ", items:" + string.join(items,","))
        self.itemNamesInFile = itemNamesInFile
        self.regexps = {}
        for item in items:
            self.regexps[item] = self.getItemRegexp(item)
        newSolutionRegexp = self.getItemRegexp(newSolutionMarker)
        self.solutions = [{}]
        for line in open(logfile).xreadlines():
            if newSolutionRegexp.search(line):
                self.solutions.append({})
                continue
            for item, regexp in self.regexps.items():
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
        if self.itemNamesInFile.has_key(item):
            return re.compile(self.itemNamesInFile[item])
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
        try:
            return int(lastField.strip())
        except ValueError:
            return lastField.strip()
    def convertTime(self, timeLine):
        # Get line _after_ timeEntryName
        position = self.regexps[timeEntryName].search(timeLine.strip())
	cutLine = timeLine[position.start():]
        # Find first pattern after timeEntryName
        timeEntry = re.findall(r'[0-9]{1,2}:[0-9]{2}:[0-9]{2}', cutLine)
	if len(timeEntry) == 0:
            # No match, return 0
	    return 0
        entries = timeEntry[0].split(":")
        timeInSeconds = int(entries[0]) * 3600 + int(entries[1]) * 60 + int(entries[2].strip()) 
        return float(timeInSeconds) / 60.0
    def getMethod(self, methodLine):
        method = methodLine.replace("Running ", "")
        return method.replace("...", "")
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

class TableTest(plugins.Action):
    def __init__(self, args = []):
        self.definingValues = [ timeEntryName, costEntryName ]
        self.interestingValues = [ ]
        self.scaleTime = 1
        self.useTmpFiles = 1
        self.interpretOptions(args)
        self.values = self.definingValues + self.interestingValues
    def interpretOptions(self, args):
        for ar in args:
            arr = ar.split("=")
            if arr[0]=="ns":
                self.scaleTime = 0
            elif arr[0]=="nt":
                self.useTmpFiles = 0
            elif arr[0]=="i":
                for entry in arr[1].split(","):
                    self.interestingValues.append(entry.replace("_", " "))
            else:
                print "Unknown option " + arr[0]
    # Interactive stuff
    def getTitle(self):
        return "Show Table"
    def getArgumentOptions(self):
        options = {}
        options["i"] = "Log file items for table columns"
        return options
    def getSwitches(self):
        switches = {}
        switches["nt"] = "Ignore temporary file"
        switches["ns"] = "Don't scale times"
        return switches
    def __call__(self, test):
        # Values that should be reported if present, but should not be fatal if not
        extraValues = [ "machine", "Crew Members" ]
        currentRun = OptimizationRun(test, None, self.definingValues, self.interestingValues + extraValues, self.scaleTime, self.useTmpFiles)
        self.displayTitle(test, currentRun.solutions[0])
        self.display(currentRun)
    def displayTitle(self, test, initialSol):
        print "Generating table for test", test.name
        print "Executed on", initialSol["machine"], ": total crew", initialSol["Crew Members"]
    def display(self, currentRun):
        underlines = []
        for value in self.values:
            underline = ""
            for i in range(len(value)):
                underline += "="
            underlines.append(underline)
        self.printRow(underlines)
        self.printRow(self.values)
        self.printRow(underlines)
        for solution in currentRun.solutions:
            solStrings = [] 
            for value in self.values:
                toPrint = self.getSolutionValue(value, solution)
                solStrings.append(string.rjust(toPrint, len(value)))
            self.printRow(solStrings)
    def printRow(self, values):
        print string.join(values, " | ")
    def getSolutionValue(self, entryName, solution):
        if solution.has_key(entryName):
            value = solution[entryName]
            if entryName == timeEntryName:
                hours = int(value) / 60
                minutes = int(value) - hours * 60
                seconds = int((value - int(value)) * 60.0)
                return string.zfill(hours, 2) + ":" + string.zfill(minutes, 2) + ":" + string.zfill(seconds, 2)
            else:
                return str(value).strip()
        else:
            return "N/A"
      
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
        print '\nKPI order:\n'
        for aKPIconst in listKPIs:
            print self.KPIHandler.getKPIname(aKPIconst)
        print ''
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
        aKPI = None
        listKPIs = []
        for aKPIConstant in self.listKPIs:
            aKPI = self.KPIHandler.createKPI(aKPIConstant, referenceFile, currentFile, floatRefPerfScale, floatNowPerfScale)
            self.KPIHandler.addKPI(aKPI)
            listKPIs.append(aKPI.getTextKPI())
        self.describe(test, ' vs ver. %s, (%d sol. KPIs: %s)' %(self.referenceVersion, aKPI.getNofSolutions(), ', '.join(listKPIs)))
    def setUpSuite(self, suite):
        self.describe(suite)

class WriteKPIData(TestReport):
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
        return ""
    def compare(self, test, referenceRun, currentRun):
        strCarmusr = '(Carmusr)%s' %(os.path.normpath(os.environ["CARMUSR"]).split(os.sep)[-1])
        listThisKPI = [strCarmusr]
        referenceFile = referenceRun.logFile
        currentFile = currentRun.logFile
        floatRefPerfScale = performance.getTestPerformance(test, self.referenceVersion)
        floatNowPerfScale = performance.getTestPerformance(test, self.currentVersion)
        aKPI = None
        listKPIData = []
        for aKPIConstant in self.listKPIs:
            aKPI = self.KPIHandler.createKPI(aKPIConstant, referenceFile, currentFile, floatRefPerfScale, floatNowPerfScale)
            self.KPIHandler.addKPI(aKPI)
            strCurve = 'REF(Curve)%s\nNOW(Curve)%s' %(aKPI.getTextCurve())
            listThisKPI.append(strCurve)
            strUncovered = 'REF(Uncovered)%s\nNOW(Uncovered)%s' %(aKPI.getTupFinalUncovered())
            listThisKPI.append(strUncovered)
            strDate = 'REF(Date)%s\nNOW(Date)%s' %(aKPI.getTupRunDate())
            listThisKPI.append(strDate)
            listKPIData.append(listThisKPI)
        self.describe(test, os.linesep + string.join(listKPIData[0], os.linesep))
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
        if fValue != 0:
            return str(int(round(100.0 * fValue))) + "% or x" + str(round(1.0 / fValue, 2))
        else:
            return "100% or x1.0"
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
    def isComplete(self):
        return 1
    def makeImport(self):
        return 0
    def postText(self):
        return ", Test: '" + self.name + "'"
    def getRuleSetName(self, absSubPlanDir):
        problemPath = os.path.join(absSubPlanDir,"problems")
        if not unixConfig.isCompressed(problemPath):
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

class ViewLog(plugins.Action):
    def __init__(self, args = []):
        self.simple = 0
    def __repr__(self):
        return "Viewing log of"
    def __call__(self, test):
        job = lsf.LSFJob(test)
        status, machine = job.getStatus()
        if status == "DONE" or status == "EXIT":
            print "Job is not running!"
            return
        if status != "PEND":
            if machine != None:
                self.showLogFile(test, machine, self.getLogFileName(test))
                self.showRunStatusFile(test)
            else:
                print "Could not find machine name."
    def getLogFileName(self, test):
        if test.app.name == "apc":
            subplanDir = test.writeDirs[-1];
            subplanName = subplanDir.split("/")[-2]
            return "/tmp/" + subplanName + "\*/apclog" 
        logFileName = test.app.getConfigValue("log_file")
        return test.makeFileName(logFileName, temporary=1)
    def showLogFile(self, test, machine, logFileName):
        command = "xon " + machine + " 'xterm -bg white -T " + test.name + " -e 'less +F " + logFileName + "''"
        os.system(command)
    def showRunStatusFile(self, test):
        # Under construction! 
        #  $CARMSYS/bin/APCstatus.sh ${SUBPLAN}/run_status
        return
    def getTitle(self):
        return "View Log"
    def getArgumentOptions(self):
        options = {}
        return options
    def getSwitches(self):
        switches = {}
        #switches["lf"] = "APC log file"
        #switches["st"] = "APC status file"
        return switches

class TraverseSubPlans(plugins.Action):
    def __init__(self, args = []):
        self.Command = string.join(args)
        if not self.Command:
            raise "No command given"
    def __repr__(self):
        return "Traversing subplan dir for"
    def __call__(self, test):
        self.describe(test)
        sys.stdout.flush()
        # Save the old dir, so we can restore it later.
        saveDir = os.getcwd()
        subplanDir = test.app.configObject._getSubPlanDirName(test)
        try:
            os.chdir(subplanDir)
            os.system(self.Command)
        except OSError, detail:
            print "Failed due to " + str(detail)
        # Restore dir
        os.chdir(saveDir)
    # Interactive stuff
    def getTitle(self):
        return "Traversing subplans"
    def getArgumentOptions(self):
        options = {}
        return options
    def getSwitches(self):
        switches = {}
        return switches

#
#
commonPlotter = 0
commonPlotCount = 0

class PlotTest(plugins.Action):
    def __init__(self, args = []):
        global commonPlotCount, commonPlotter
        if commonPlotter == 0:
            commonPlotter = _PlotTest(args)
            commonPlotCount = 1
        else:
            commonPlotCount += 1
            commonPlotter.__init__(args)
    def __del__(self):
        global commonPlotCount, commonPlotter
        commonPlotCount -= 1
        if commonPlotCount == 0:
            commonPlotter = []
    def __repr__(self):
        return "Plotting"
    def __call__(self, test):
        commonPlotter(test)
    def setUpSuite(self, suite):
        commonPlotter.setUpSuite(suite)
    # Interactive stuff
    def getTitle(self):
        return "Plot Graph"
    def getArgumentOptions(self):
        options = {}
        options["r"] = "Time range in minutes"
        options["p"] = "Absolute file to print to"
        options["i"] = "Log file item to plot"
        options["v"] = "Versions to plot"
        return options
    def getSwitches(self):
        switches = {}
        switches["pc"] = "Plot in colour"
        switches["s"] = "Plot against solution number rather than time"
        switches["nt"] = "Ignore temporary file"
        switches["b"] = "Plot original and temporary file"
        switches["ns"] = "Don't scale times"
        switches["nv"] = "No line type grouping for versions"
        return switches
        
# Class for using gnuplot to plot test curves of tests
#
class _PlotTest(plugins.Action):
    def __init__(self, args = []):
        self.plotFiles = []
        self.plotItem = [ costEntryName ]
        self.plotItemApp = {}
        self.plotrange = "0:"
        self.plotPrint = None
        self.plotPrintColor = None
        self.plotAgainstSolNum = 0
        self.plotVersions = [ "" ]
        self.plotScaleTime = 1
        self.plotVersionColoring = 1
        self.plotUseTmpStatus = 1
        self.plotStates = [ "" ]
        self.yLabel = ""
        self.plotInSameGraph = 0
        self.lastSuite = ""
        # Must be last in the constructor
        self.interpretOptions(args)
    def __del__(self):
        if self.plotInSameGraph:
            self.plotGraph()
    def setUpSuite(self, suite):
        self.lastSuite = suite.name
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
            elif arr[0]=="sg":
                self.plotInSameGraph = 1
            elif arr[0]=="i":
                if arr[1]=="apctimes":
                    arr[1] = "OC_to_DH_time,Generation_time,Costing_time,Conn_fixing,Optimization_time,Network_generation_time"
                itemsToPlot = arr[1].split(",")
                self.plotItem = []
                for item in itemsToPlot:
                    parts = item.split(":")
                    if len(parts) < 2:
                        self.plotItem.append(parts[0].replace("_"," "))
                    else:
                        self.plotItemApp[parts[0]] = parts[1].replace("_"," ")
            else:
                print "Unknown option " + arr[0]
    def getYlabel(self):
        if len(self.items) == 1:
            return self.plotItem[0]
        else:
            return ""
    def getPlotFileName(self, version, state, item):
        return "plot-" + version + "-" + state + "-" + item
    def getPlotUserAndTest(self, file):
        username = file.split(os.sep)[-4]
        testname = file.split(os.sep)[-3]
        return username, testname
    def getPlotInfo(self, file):
        plotFileName = file.split(os.sep)[-1]
        app = plotFileName.split(".")[-1]
        ver = plotFileName.split("-")[1]
        state = plotFileName.split("-")[2]
        item = int(plotFileName.split("-")[3].split(".")[0])
        username, testname = self.getPlotUserAndTest(file)
        return app,ver,state,item,username,testname
    def setPointandLineTypes(self):
        if len(self.plotVersions)>1 or len(self.plotStates)>1 or len(self.items)>1:
            # Choose line type.
            self.versionLineType = {}
            counter = 2
            for versionIndex in range(len(self.plotVersions)):
                for stateIndex in range(len(self.plotStates)):
                    for itemIndex in range(len(self.items)):
                        self.versionLineType[self.plotVersions[versionIndex], self.plotStates[stateIndex], itemIndex] = counter
                        counter = counter + 1
            # Choose point type.
            self.testPointType = {}
            counter = 1
            for file in self.plotFiles:
                username, testname = self.getPlotUserAndTest(file)
                name = username + "::" + testname
                if not self.testPointType.has_key(name):
                    self.testPointType[name] = counter
                    counter = counter + 1
    def getStyle(self, file):
        plotFileName = file.split(os.sep)[-1]
        app, ver, state, item, username, testname = self.getPlotInfo(file)
        name = username + "::" + testname
        if (len(self.plotVersions)>1 or len(self.plotStates)>1) and self.plotVersionColoring:
            style = " with linespoints lt " +  str(self.versionLineType[ver,state,item]) + " pt " + str(self.testPointType[name])
        else:
            style = " with linespoints "
        return style
    # Counts number of tests, versions etc that will be plotted.
    def count(self):
        self.appnames = {}
        self.vers = {}
        self.states = {}
        self.items ={}
        self.usernames = {}
        self.testnames = {}
        for file in self.plotFiles:
            appname, ver , state, item, username, testname = self.getPlotInfo(file)
            self.appnames[appname] = 1
            self.vers[ver] = 1
            self.states[state] = 1
            self.items[item] = 1
            self.usernames[username] = 1
            self.testnames[testname] = 1
        #print len(self.appnames),len(self.vers),len(self.states),len(self.items),len(self.usernames), len(self.testnames)
    def makeTitle(self):
        title = ""
        if len(self.usernames) == 1:
            title += "User " + self.usernames.keys()[0] + " "
        if len(self.testnames) == 1:
            title += "Test " + self.testnames.keys()[0] + " "
        if len(self.appnames) == 1:
            title += "Application " + self.appnames.keys()[0] + " "
        if len(self.vers) == 1:
            ver = self.vers.keys()[0]
            if ver == "":
                ver = "master"
            title += "Version " + ver + " "
        return title
    def makePlotName(self, file):
        appname, ver, state, item, username, testname = self.getPlotInfo(file)
        name = username + "::" + testname
        title = " title \""
        if len(self.usernames) > 1:
            title += username + "."
        if len(self.testnames) > 1:
            title += testname + "."
        if len(self.appnames) > 1:
            title += appname + "."
        if len(self.vers) > 1:
            if ver == "":
                title += "master."
            else:
                title += ver + "."
        if len(self.states) > 1:
            title += state + "."
        if len(self.items) > 1:
            title += self.plotItem[item]
        title += "\" "
        return title
    def __repr__(self):
        return "Plotting"
    def plotGraph(self):
        if len(self.plotFiles) > 0:
            stdin, stdout, stderr = os.popen3("gnuplot -persist -background white")
            self.count()
            self.setPointandLineTypes()

            fileList = []
            for file in self.plotFiles:
                fileList.append("'" + file + "' " + self.makePlotName(file) + self.getStyle(file))

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
            stdin.write("set title \"" + self.makeTitle() + "\"" + os.linesep)
            stdin.write("set xtics border nomirror norotate" + os.linesep)
            stdin.write("set ytics border nomirror norotate" + os.linesep)
            stdin.write("set border 3" + os.linesep)
            stdin.write("set xrange [" + self.plotrange +"];" + os.linesep)
            stdin.write("plot " + string.join(fileList, ",") + os.linesep)
            stdin.write("quit" + os.linesep)
            stdin.close()
            if self.plotPrint:
                tmppf = stdout.read()
                if len(tmppf) > 0:
                    open(absplotPrint,"w").write(tmppf)
            self.plotFiles = []
    def __call__(self, test):
        # In GUI mode we can rely on existing dirs
        if not os.path.isdir(test.writeDirs[0]):
            os.makedirs(test.writeDirs[0])
        os.chdir(test.writeDirs[0])
        for version in self.plotVersions:
            for state in self.plotStates:
                for item in range(len(self.plotItem)):
                    try:
                        parts = self.plotItem[item].split(":")
                        if len(parts) < 2:
                            usePlotItem = parts[0]
                        else:
                            if test.app.name == parts[0]:
                                usePlotItem = parts[1]
                            else:
                                usePlotItem = costEntryName
                        optRun = OptimizationRun(test, version, [ timeEntryName, usePlotItem], [], self.plotScaleTime, self.plotUseTmpStatus, state)
                    except plugins.TextTestError:
                        print "No status file does exist for test " + test.app.name + "::" + test.name + "(" + version + ")"
                        continue

                    plotFileName = test.makeFileName(self.getPlotFileName(version, state, str(item)), temporary = 1)
                    plotFile = open(plotFileName, "w")
                    for solution in optRun.solutions:
                        if self.plotAgainstSolNum:
                            plotFile.write(str(solution[usePlotItem]) + os.linesep)
                        else:
                            plotFile.write(str(solution[timeEntryName]) + "  " + str(solution[usePlotItem]) + os.linesep)
                    self.plotFiles.append(plotFileName)
        if not self.plotInSameGraph:
            self.plotGraph()
        
