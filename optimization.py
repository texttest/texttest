helpDescription = """
It will fetch the optimizer's solution from the subplan (the "best_solution" link) and write it for
comparison as the file solution.<app> after each test has run.

It also uses the temporary subplan concept, such that all tests will actually be run in different, temporary
subplans when the tests are run. These subplans should then be cleaned up afterwards. The point of this
is to avoid clashes in solution due to two runs of the same test writing to the same subplan.

Also, you can specify values of RAVE parameters in special raveparameters.<app>.<ver> file(s). The lines
listed in these file(s) will be insert into the rules file after the subplan is copied. Observe that
this is done hierarchiclly, i.e. lines in raveparameters suite files will be written before lines
in raveparameters test files. By doing this you can experiment with a new feature on a lot of tests
without having to manually create new tests.

In other respects, it follows the usage of the Rave-based configuration.""" 

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
                             - yr=range
                               The y-axis has the y-range range. Default is the whole data set. Example: 2e7:3e7
                             - p=an absolute file name
                               Produces a postscript file instead of displaying the graph.
                             - pc
                               The postscript file will be in color.
                             - i=item,item,...
                               Which item to plot from the status file. Note that whitespaces are replaced
                               by underscores. Default is TOTAL cost. Example: i=overcover_cost.
                               If a comma-seperated list is given, all the listed items are plotted.
                               An abreviation is 'i=apctimes', which is equivalent to specifying 'i=OC_to_DH_time,
                               Generation_time,Costing_time,Conn_fixing,Optimization_time,Network_generation_time'.
                             - av
                               Also add an average over the tests for the items and versions plotted.
                             - oav
                               Only plot the average curves, and not the individual test curves.
                             - s
                               Plot against solution number instead of cpu time.
                             - nt
                               Do not use status file from the currently running test.
                             - tu=user_name
                               Looks for temporary files in /users/user_name/texttesttmp instead of default textttesttmp. 
                             - ns
                               Do not scale times with the performance of the test.
                             - nv
                               No line type grouping for different versions of the test.
                             - v=v1,v2
                               Plot multiple versions in same dia, ie 'v=,9' means master and version 9
                             - sg
                               Plot all tests chosen on the same graph, rather than one window per test
                             - title=graphtitle
                               Sets the title of the graph to graphtitle, rather than the default generated one.
                             - ts=hours|days|minutes
                               Used as time scale on the x-axis. Default is minutes.
                               
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
                             Example: texttest -s optimization.TraverseSubPlans "pwd".
                             This will display the path of all subplan directories in the test suite.
                             Example:
                             texttest -apc -s optimization.TraverseSubPlans "grep use_column_generation_method APC_FILES/rules"
                             This will show for which APC tests the column generation method is used.
"""


import ravebased, os, sys, string, shutil, KPI, plugins, performance, math, re, predict, unixConfig, guiplugins, copy
from ndict import seqdict

itemNamesConfigKey = "_itemnames_map"
noIncreasMethodsConfigKey = "_noincrease_methods_map"

# Names of reported entries
costEntryName = "cost of plan"
timeEntryName = "cpu time"
memoryEntryName = "memory"
methodEntryName = "Running.*\.\.\."
periodEntryName = "Period"
dateEntryName = "Date"
activeMethodEntryName = "Active method"
apcLibraryDateName = "APC library date"
newSolutionMarker = "new solution"
solutionName = "solution"

class OptimizationConfig(ravebased.Config):
    def __init__(self, optionMap):
        ravebased.Config.__init__(self, optionMap)
        #Probably different for APC and matador : static data for the text in the log file
        self.itemNamesInFile = {}
        # Static data for what data to check in CheckOptimizationRun, and what methods to avoid it with
        self.noIncreaseExceptMethods = {}
    def addToOptionGroups(self, app, groups):
        ravebased.Config.addToOptionGroups(self, app, groups)
        for group in groups:
            if group.name.startswith("Invisible"):
                # These need a better interface before they can be plugged in, really
                group.addOption("prrep", "Run KPI progress report")
                group.addOption("kpiData", "Output KPI curve data etc.")
                group.addOption("kpi", "Run Henrik's old KPI")
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
        return ravebased.Config.getActionSequence(self)
    def getProgressReportBuilder(self):
        return MakeProgressReport(self.optionValue("prrep"))
    def defaultBuildRules(self):
        # Assume we always want to build at least some rules, by default...
        return 1
    def getTestRunner(self):
        return [ MakeTmpSubPlan(self._getSubPlanDirName), self.getSpecificTestRunner() ]
    def extraReadFiles(self, test):
        readDirs = seqdict()
        if test.classId() == "test-case":
            test.setUpEnvironment(parents=1)
            dirName = self._getSubPlanDirName(test)
            rulesFile = os.path.join(dirName, "APC_FILES", "rules")
            if os.path.isfile(rulesFile):
                readDirs["Subplan"] = [ rulesFile ]
                readDirs["Ruleset"] = [ os.path.join(os.environ["CARMUSR"], "crc", "source", self.getRuleSetName(test)) ]
            test.tearDownEnvironment(parents=1)
        elif test.environment.has_key("CARMUSR"):
            readDirs["Resource"] = [ os.path.join(test.environment["CARMUSR"], "Resources", "CarmResources", "Customer.etab") ]
        elif test.environment.has_key("CARMSYS"):
            readDirs["RAVE module"] = [ os.path.join(test.environment["CARMSYS"], \
            "carmusr_default", "crc", "modules", test.getConfigValue("rave_name")) ]
        return readDirs
    def getSpecificTestRunner(self):
        return ravebased.Config.getTestRunner(self) 
    def printHelpDescription(self):
        print helpDescription
        ravebased.Config.printHelpDescription(self)
    def printHelpOptions(self, builtInOptions):
        ravebased.Config.printHelpOptions(self, builtInOptions)
        print helpOptions
    def printHelpScripts(self):
        ravebased.Config.printHelpScripts(self)
        print helpScripts
    def setApplicationDefaults(self, app):
        ravebased.Config.setApplicationDefaults(self, app)
        app.setConfigDefault(itemNamesConfigKey, self.itemNamesInFile)
        app.setConfigDefault(noIncreasMethodsConfigKey, self.noIncreaseExceptMethods)
        app.setConfigDefault("kpi_cost_margin", 0.0)
        app.addConfigEntry("definition_file_stems", "raveparameters")

class MakeTmpSubPlan(plugins.Action):
    def __init__(self, subplanFunction):
        self.subplanFunction = subplanFunction
        self.raveParameters = []
        self.diag = plugins.getDiagnostics("Tmp Subplan")
    def setUpSuite(self, suite):
        self.readRaveParameters(suite.makeFileName("raveparameters"))
    def tearDownSuite(self, suite):
        self.unreadRaveParameters()
    def __call__(self, test):
        dirName = self.subplanFunction(test)
        if not os.path.isdir(dirName):
            raise plugins.TextTestError, "Cannot run test, subplan directory at " + dirName + " does not exist"
        rootDir, baseDir = os.path.split(dirName)
        tmpDir = test.makeWriteDirectory(rootDir, baseDir, "APC_FILES")
        self.readRaveParameters(test.makeFileName("raveparameters"))
        self.makeLinksIn(tmpDir, dirName)
        self.unreadRaveParameters()
    def makeLinksIn(self, inDir, fromDir):
        for file in os.listdir(fromDir):
            if file == "APC_FILES":
                apcFiles = os.path.join(inDir, file)
                self.makeLinksIn(apcFiles, os.path.join(fromDir, file))
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
            if (len(self.raveParameters) > 0) and file.find("rules") != -1:
                file = open(toPath, 'w')
                for line in open(fromPath).xreadlines():
                    if line.find("<SETS>") != -1:
                        for overrideItems in self.raveParameters:
                            for override in overrideItems:
                                file.write(override)
                    file.write(line)
            else:
                os.symlink(fromPath, toPath)            
    def readRaveParameters(self, fileName):
        if not os.path.isfile(fileName):
            self.raveParameters.append([])
        else:
            self.raveParameters.append(open(fileName).readlines())
        self.diag.info("Added to list : " + repr(self.raveParameters))    
    def unreadRaveParameters(self):
        self.raveParameters.pop()
        self.diag.info("Removed from list : " + repr(self.raveParameters))
        

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
    def __init__(self, test, tryTmpFile = 1, searchInUser = None):
        self.tryTmpFile = tryTmpFile
        self.test = test
        self.logStem = test.app.getConfigValue("log_file")
        self.diag = plugins.getDiagnostics("Log File Finder")
        self.searchInUser = searchInUser
    def findFile(self, version = None, specFile = ""):
        if len(specFile):
            return 0, self.findSpecifiedFile(version, specFile)
        if self.tryTmpFile:
            logFile, tmpDir = self.findTempFile(self.test, version) 
            if logFile and os.path.isfile(logFile):
                print "Using temporary log file (from " + tmpDir + ") for test " + self.test.name + " version " + str(version)
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
        self.diag.info("Looking for tmp file for " + test.name + " version " + str(version))
        fileInTest, tmpDir = self.findTempFileInTest(version, self.logStem)
        if fileInTest or self.logStem == "output":
            self.diag.info("Found " + str(fileInTest))
            return fileInTest, tmpDir
        # Look for output, find appropriate temp subplan, and look there
        outputInTest, tmpDir = self.findTempFileInTest(version, "output")
        if outputInTest == None:
            return None, None
        grepCommand = "grep -E 'SUBPLAN' " + outputInTest
        self.diag.info(grepCommand)
        grepLines = os.popen(grepCommand).readlines()
        if len(grepLines) > 0:
            currentFile = os.path.join(grepLines[0].split()[1], self.logStem)
            self.diag.info(currentFile)
            if os.path.isfile(currentFile):
                return currentFile, tmpDir
        else:
            print "Could not find subplan name in output file " + fileInTest + os.linesep
            return None, None
    def findTempFileInTest(self, version, stem, thisRun = 1):
        app = self.test.app
        if thisRun:
            fromThisRun = self.test.makeFileName(stem, version, temporary=1)
            self.diag.info("Looked for " + fromThisRun)
            if os.path.isfile(fromThisRun):
                return fromThisRun, app.writeDirectory
        if not version:
            version = string.join(self.test.app.versions, ".")
        versionMod = ""
        if version:
            versionMod = "." + version
        root, localDir = os.path.split(app.writeDirectory)
        searchString = app.name + versionMod
        if self.searchInUser:
            searchString += self.searchInUser
            root = "/users/" + self.searchInUser + "/texttesttmp/"
        else:
            searchString += app.getTestUser()
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
    def __init__(self, app, definingItems, interestingItems, logFile, scalePerf = 0.0, solutions = None, constantItemsToFind = []):
        self.diag = plugins.getDiagnostics("optimization")
        self.penaltyFactor = 1.0
        if solutions:
            self.diag.info("Setting solution")
            self.solutions = solutions
            return 
        self.logFile = logFile
        self.diag.info("Reading data from " + self.logFile)
        allItems = definingItems + interestingItems
        calculator = OptimizationValueCalculator(allItems, self.logFile, app.getConfigValue(itemNamesConfigKey), constantItemsToFind)
        self.solutions = calculator.getSolutions(definingItems)
        self.constantItems = calculator.constantItems
        self.diag.debug("Solutions :" + repr(self.solutions))
        if scalePerf and self.solutions and timeEntryName in allItems:
            self.scaleTimes(scalePerf)
    def scaleTimes(self, scalePerf):
        finalTime = self.solutions[-1][timeEntryName]
        if finalTime == 0.0:
            return
        scaleFactor = scalePerf / finalTime
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
        bestCost = 0
        if len(self.solutions)>0:
            bestCost=self.solutions[0][costEntryName]
        for solution in self.solutions:
            if solution[timeEntryName] > targetTime:
                timeGap = lastTime - solution[timeEntryName]
                percent = float(lastTime - targetTime) / timeGap
                cost = lastCost + (solution[costEntryName] - lastCost) * percent
                return min(bestCost,int(round(cost)))
            else:
                lastCost = solution[costEntryName]
                lastTime = solution[timeEntryName]
                bestCost=min(lastCost,bestCost)
        return bestCost;
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
    def __init__(self, items, logfile, itemNamesInFile, constantItemsToFind):
        self.diag = plugins.getDiagnostics("optimization")
        self.diag.info("Building calculator for: " + logfile + ", items:" + string.join(items,","))
        self.itemNamesInFile = itemNamesInFile
        self.regexps = {}
        for item in items:
            self.regexps[item] = self.getItemRegexp(item)
        newSolutionRegexp = self.getItemRegexp(newSolutionMarker)
        self.solutions = [{}]
        self.constantItems = {}
        for line in open(logfile).xreadlines():
            if newSolutionRegexp.search(line):
                self.solutions.append({})
                continue
            for item, regexp in self.regexps.items():
                if regexp.search(line):
                    self.solutions[-1][item] = self.calculateEntry(item, line)
            for item in constantItemsToFind:
                if not self.constantItems.has_key(item):
                    if line.find(item) != -1:
                        self.constantItems[item] = self.calculateEntry(item, line)
                        constantItemsToFind.remove(item)
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
        elif item == activeMethodEntryName:
            return self.getActiveMethod(line)
        elif item == periodEntryName:
            return self.getPeriod(line)
        elif item == dateEntryName:
            return self.getDate(line)
        elif item == apcLibraryDateName:
            return self.getAPCLibraryDate(line)
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
        timeEntry = re.findall(r'[0-9]{1,3}:[0-9]{2}:[0-9]{2}', cutLine)
	if len(timeEntry) == 0:
            # No match, return 0
	    return 0
        entries = timeEntry[0].split(":")
        timeInSeconds = int(entries[0]) * 3600 + int(entries[1]) * 60 + int(entries[2].strip()) 
        return float(timeInSeconds) / 60.0
    def getMethod(self, methodLine):
        method = methodLine.replace("Running ", "")
        return method.replace("...", "")
    def getActiveMethod(self, methodLine):
        return methodLine.split(":")[1].split(",")[0].strip()
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
    def getPeriod(self, periodLine):
        line = periodLine.split(" ")[-3:]
        return line[0], line[2]
    def getDate(self, dateLine):
        line = dateLine.split(" ")
        return line[2].strip(',')
    def getAPCLibraryDate(self, line):
        return string.join(line.split(":")[1][1:].split(" ")[:3])

class TableTest(plugins.Action):
    def __init__(self, args = []):
        self.definingValues = [ timeEntryName, costEntryName ]
        self.interestingValues = [ ]
        self.useTmpFiles = 1
        self.interpretOptions(args)
        self.values = self.definingValues + self.interestingValues
    def interpretOptions(self, args):
        for ar in args:
            arr = ar.split("=")
            if arr[0]=="nt":
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
        return switches
    def __call__(self, test):
        # Values that should be reported if present, but should not be fatal if not
        extraValues = [ "machine", "Crew Members" ]
        logFile = test.makeFileName(test.app.getConfigValue("log_file"), temporary = self.useTmpFiles)
        currentRun = OptimizationRun(test.app, self.definingValues, self.interestingValues + extraValues, logFile)
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
        currentLogFile, refLogFile = self.getLogFilesForComparison(test)
        if not (currentLogFile and refLogFile):
            return
        currPerf, refPerf = self.getPerformance(test, self.currentVersion, self.referenceVersion)
        currentRun = OptimizationRun(test.app, definingValues, interestingValues, currentLogFile, currPerf, None, self.getConstantItemsToExtract())
        referenceRun = OptimizationRun(test.app, definingValues, interestingValues, refLogFile, refPerf, None, self.getConstantItemsToExtract())
        if currentRun.logFile != referenceRun.logFile:
            self.compare(test, referenceRun, currentRun)
        else:
            print "Skipping test due to same logfile", test.name
    def getPerformance(self, test, currentVersion, referenceVersion):
        currPerf = performance.getTestPerformance(test, self.currentVersion)
        refPerf = performance.getTestPerformance(test, self.referenceVersion)
        return currPerf, refPerf
    def getLogFilesForComparison(self, test):
        currentLogFile = test.makeFileName(test.app.getConfigValue("log_file"), self.currentVersion)
        refLogFile = test.makeFileName(test.app.getConfigValue("log_file"), self.referenceVersion)
        return currentLogFile, refLogFile
    def getConstantItemsToExtract(self):
        return []

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
        self.worstKpi = 0.00001
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
        self.doCompare(referenceRun, currentRun, test.app, test.name, userName)
    def doCompare(self, referenceRun, currentRun, app, groupName, userName, groupNameDefinition = "test"):
        if currentRun.isVeryShort() or referenceRun.isVeryShort():
            return

        worstCost = self.calculateWorstCost(referenceRun, currentRun, app, groupName)
        currTTWC = currentRun.timeToCost(worstCost)
        refTTWC = referenceRun.timeToCost(worstCost)
        
        self.testCount += 1
        kpi = self.computeKPI(currTTWC, refTTWC)
        print os.linesep, "Comparison on", app, groupNameDefinition, groupName, "(in user " + userName + ") : K.P.I. = " + kpi
        self.reportLine("                         ", self.currentText(), "Version " + self.referenceVersion)
        self.reportCosts(currentRun, referenceRun, app, groupName)
        self.reportLine("Max memory (MB)", currentRun.getMaxMemory(), referenceRun.getMaxMemory())
        self.reportLine("Total time (minutes)     ", currentRun.getPerformance(), referenceRun.getPerformance())
        self.reportLine("Time to cost " + str(worstCost) + " (mins)", currTTWC, refTTWC)
        return kpi
    def calculateWorstCost(self, referenceRun, currentRun, app, groupName):
        currMargin, refMargin = self.getMargins(app, groupName)
        currSol = currentRun.getMeasuredSolution(currMargin)
        refSol = referenceRun.getMeasuredSolution(refMargin)
        currCost = currentRun.getCost(currSol)
        refCost = referenceRun.getCost(refSol)
        if currCost < refCost:
            return refCost
        else:
            return currCost
    def getMargins(self, app, groupName = None):
        refMargin = float(app.getConfigValue("kpi_cost_margin"))
        return refMargin, refMargin
    def reportCosts(self, currentRun, referenceRun, app, groupName):
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
        if not os.path.isdir(subPlanTree):
            if os.path.islink(subPlanTree):
                print "LOCAL_PLAN directory", subPlanTree, "seems to be a deadlink."
            else:
                print "LOCAL_PLAN directory", subPlanTree, "did not exist."
            return None
        
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
                if ravebased.isUserSuite(suite):
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

# Graphical import test
class ImportTestCase(guiplugins.ImportTestCase):
    def addOptionsFileOption(self, oldOptionGroup):
        self.optionGroup.addOption("sp", "Subplan name")
    def getSubplanName(self):
        return self.optionGroup.getOptionValue("sp")
    def getOptions(self):
        pass
    # getOptions implemented in subclasses

# Graphical import suite
class ImportTestSuite(guiplugins.ImportTestSuite):
    def addEnvironmentFileOptions(self, oldOptionGroup):
        self.optionGroup.addOption("usr", "CARMUSR")
    def getCarmusr(self):
        return os.path.normpath(self.optionGroup.getOptionValue("usr"))
    def hasStaticLinkage(self):
        return 1
    def openFile(self, fileName):
        guiplugins.guilog.info("Writing file " + os.path.basename(fileName))
        return open(fileName, "w")
    def writeLine(self, file, line):
        file.write(line + os.linesep)
        guiplugins.guilog.info(line)
    def writeEnvironmentFiles(self, suite, testDir):
        carmUsr = self.getCarmusr()
        envFile = os.path.join(testDir, "environment")
        file = self.openFile(envFile)
        self.writeLine(file, "CARMUSR:" + carmUsr)
        carmtmp = os.path.basename(carmUsr).replace("_user", "_tmp")
        if self.hasStaticLinkage(carmUsr):
            self.writeLine(file, "CARMTMP:$CARMSYS/" + carmtmp)
            return

        self.writeLine(file, "CARMTMP:" + self.getCarmtmpPath(carmtmp))
        envLocalFile = os.path.join(testDir, "environment.local")
        localFile = self.openFile(envLocalFile)
        self.writeLine(localFile, "CARMTMP:$CARMSYS/" + carmtmp)
    def getCarmtmpPath(self, carmtmp):
        pass
    # getCarmtmpPath implemented by subclasses
        
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
        subplanDir = test.app.configObject.target._getSubPlanDirName(test)
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
        test.makeBasicWriteDirectory()
        self.describe(test)
        commonPlotter(test)
    def setUpSuite(self, suite):
        self.describe(suite)
    def setUpApplication(self, app):
        app.makeWriteDirectory()
    def getCleanUpAction(self):
        return GraphPlot()

class Averager:
    def __init__(self, minmax = 0):
        self.average = {}
        self.numberOfGraphs = 0
        self.minmax = 0
        if  minmax:
            self.minmax = 1
            self.min = {}
            self.max = {}

    def addGraph(self, graph):
        self.numberOfGraphs += 1
        if not self.average:
            self.average = copy.deepcopy(graph)
            if self.minmax:
                self.min = copy.deepcopy(graph)
                self.max = copy.deepcopy(graph)
            return
        graphXValues = graph.keys()
        graphXValues.sort()
        averageXValues = self.average.keys()
        averageXValues.sort()
        mergedVals = self.mergeVals(averageXValues, graphXValues)
        extendedGraph = self.extendGraph(graph, mergedVals)
        extendedAverage = self.extendGraph(self.average, mergedVals)
        if self.minmax:
            extendedMin = self.extendGraph(self.min, mergedVals)
            extendedMax = self.extendGraph(self.max, mergedVals)
        for xval in extendedAverage.keys():
            extendedAverage[xval] += extendedGraph[xval]
            if self.minmax:
                extendedMin[xval] = min(extendedMin[xval], extendedGraph[xval])
                extendedMax[xval] = max(extendedMax[xval], extendedGraph[xval])
        self.average = extendedAverage
        if self.minmax:
            self.min = extendedMin
            self.max = extendedMax

    def mergeVals(self, values1, values2):
        merged = values1
        merged.extend(values2)
        merged.sort()
        mergedVals = [ merged[0] ]
        prev = merged[0]
        for val in merged[1:]:
            if not val == prev:
                mergedVals.append(val)
                prev = val
        return mergedVals

    def extendGraph(self, graph, xvalues):
        currentxvalues = graph.keys()
        currentxvalues.sort()
        extendedGraph = graph
        for xval in xvalues:
            if not graph.has_key(xval):
                extendedGraph[xval] = graph[self.findClosestEarlierVal(xval, currentxvalues)]
        return graph

    def findClosestEarlierVal(self, xval, xvalues):
        # If there is no earlier value.
        if xval < xvalues[0]:
            return xvalues[0]
        if xval > xvalues[-1]:
            return xvalues[-1]
        pos = 0
        while xvalues[pos] < xval:
            pos += 1
        return xvalues[pos-1]

    def getAverage(self):
        graph = {}
        xValues = self.average.keys()
        xValues.sort()
        for xVal in xValues:
            graph[xVal] = self.average[xVal]/self.numberOfGraphs
        return graph
    
    def getMinMax(self):
        return self.min, self.max

plotAveragerCount = 0

class PlotAverager(Averager):
    def __init__(self, tmpFileDirectory = None):
        Averager.__init__(self)
        self.plotLineRepresentant = None
        self.tmpFileDirectory = tmpFileDirectory
    
    def plotArgument(self):
        global plotAveragerCount
        plotFileName = os.path.join(self.tmpFileDirectory, "average." + str(plotAveragerCount))
        plotAveragerCount += 1
        plotFile = open(plotFileName, "w")
        xValues = self.average.keys()
        xValues.sort()
        for xVal in xValues:
            plotFile.write(str(xVal) + " " + str(self.average[xVal]/self.numberOfGraphs) + os.linesep)
        plotFile.close()
        return "'" + plotFileName + "' " + " title \"" + self.plotLineRepresentant.name + "\" with lines lt " + self.plotLineRepresentant.lineType + " lw 2"

# Class for using gnuplot to plot test curves of tests
#
class _PlotTest(plugins.Action):
    def __init__(self, args = []):
        self.testGraph = TestGraph()
        self.args = args
        self.plotForTest = None
        self.plotAveragers = {}
    def __call__(self, test):
        self.plotForTest = PlotTestInGUI(test, graph=self.testGraph, plotAveragers=self.plotAveragers)
        self.plotForTest.optionGroup.readCommandLineArguments(self.args)
        self.plotForTest(test)
    
class GraphPlot(plugins.Action):
    def setUpApplication(self, app):
        if commonPlotter.plotForTest:
            xrange, yrange, targetFile, colour, onlyAverage, title = commonPlotter.plotForTest.getPlotOptions()
            commonPlotter.plotForTest = None
            os.chdir(app.writeDirectory)
            commonPlotter.testGraph.plot(app.writeDirectory, xrange, yrange, targetFile, colour, onlyAverage, commonPlotter.plotAveragers, title, wait=1)
    
class TestGraph:
    def __init__(self):
        self.plotLines = []
        self.pointTypes = {}
        self.lineTypes = {}
        self.yLabel = ""
        self.pointTypeCounter = 1
        self.lineTypeCounter = 2
        self.users = []
        self.apps = []
    def addLine(self, plotLine):
        self.plotLines.append(plotLine)
        test = plotLine.test
        if not test.app in self.apps:
            self.apps.append(test.app)
        user = plotLine.getUserName()
        if not user in self.users:
            self.users.append(user)
        if not test.name in self.pointTypes.keys():
            plotLine.pointType = str(self.pointTypeCounter)
            self.pointTypes[test.name] = plotLine.pointType
            self.pointTypeCounter += 1
        else:
            plotLine.pointType = self.pointTypes[test.name]
        # Fill in the map for later deduction
        self.lineTypes[plotLine.name] = 0
    def getPlotArguments(self):
        multipleApps = len(self.apps) > 1
        multipleLines = (len(self.plotLines) > 1)
        multipleUsers = len(self.users) > 1
        multipleTests = len(self.pointTypes) > 1
        multipleLineTypes = len(self.lineTypes) > 1
        plotArguments = []
        for plotLine in self.plotLines:
            if not multipleTests or not multipleLineTypes or self.lineTypes[plotLine.name] == 0:
                plotLine.lineType = str(self.lineTypeCounter)
                self.lineTypes[plotLine.name] = plotLine.lineType
                self.lineTypeCounter += 1
            else:
                plotLine.lineType = self.lineTypes[plotLine.name]
            plotArguments.append(plotLine.getPlotArguments(multipleApps, multipleUsers, multipleLines, multipleTests))
        return plotArguments
    def plot(self, writeDir, xrange, yrange, targetFile, colour, onlyAverage, plotAveragers, title = None, wait=0):
        if len(self.plotLines) == 0:
            return

        gnuplotFileName = os.path.join(writeDir, "gnuplot.input")
        outputFileName = os.path.join(writeDir, "gnuplot.output")
        gnuplotFile = open(gnuplotFileName, "w")
        if targetFile:
            # The abspath is to get the testing working, I don't like the abspath...
            absTargetFile = os.path.abspath(os.path.expanduser(targetFile))
            if not os.path.isabs(absTargetFile):
                print "An absolute path must be given.", absTargetFile
                return
            gnuplotFile.write("set terminal postscript")
            if colour:
                gnuplotFile.write(" color")
            gnuplotFile.write(os.linesep)

        gnuplotFile.write("set ylabel '" + self.getAxisLabel("y") + "'" + os.linesep)
        gnuplotFile.write("set xlabel '" + self.getAxisLabel("x") + "'" + os.linesep)
        gnuplotFile.write("set time" + os.linesep)
        gnuplotFile.write("set title \"" + self.makeTitle(title) + "\"" + os.linesep)
        gnuplotFile.write("set xtics border nomirror norotate" + os.linesep)
        gnuplotFile.write("set ytics border nomirror norotate" + os.linesep)
        gnuplotFile.write("set border 3" + os.linesep)
        gnuplotFile.write("set xrange [" + xrange +"];" + os.linesep)
        if yrange:
            gnuplotFile.write("set yrange [" + yrange +"];" + os.linesep)
        plotArguments = self.getPlotArguments()
        plotCommand = "plot "
        if not onlyAverage:
            for plotArgument in plotArguments:
                gnuplotFile.write(plotCommand + plotArgument + os.linesep)
                plotCommand = "replot "
        if plotAveragers:
            for plotAverager in plotAveragers:
                plotArgument = plotAveragers[plotAverager].plotArgument()
                gnuplotFile.write(plotCommand + plotArgument + os.linesep)
                plotCommand = "replot "
        gnuplotFile.write("quit" + os.linesep)
        gnuplotFile.close()
        commandLine = "gnuplot -persist -background white < " + gnuplotFileName + " > " + outputFileName
        # This is ugly! It's only to be able to test it (we must avoid getting windows popping up where gnuplot
        # produces a window, but must call it for real when we generate a file...).
        if targetFile:
            os.system(commandLine)
            tmppf = open(outputFileName).read()
            if len(tmppf) > 0:
                open(absTargetFile, "w").write(tmppf)
        else:
            process = plugins.BackgroundProcess(commandLine)
            process.waitForTermination()
            if wait:
                process.waitForTermination()
    def getAxisLabel(self, axis):
        label = None
        for plotLine in self.plotLines:
            lineLabel = plotLine.getAxisLabel(axis)
            if not label:
                label = lineLabel
            elif label != lineLabel:
                return ""
        return label
    def makeTitle(self, title):
        if title:
            return title;
        title = ""
        firstApp = self.apps[0]
        if len(self.apps) == 1:
            title += firstApp.fullName + " "
            version = firstApp.getFullVersion(forSave=1)
            if version:
                title += "Version " + version + " "
        firstUser = self.users[0]
        if len(self.users) == 1:
            title += "(in user " + firstUser + ") " 
        firstTestName = self.pointTypes.keys()[0]
        if len(self.pointTypes) == 1:
            title += ": Test " + firstTestName
        return title

# Same as above, but from GUI. Refactor!
class PlotTestInGUI(guiplugins.InteractiveAction):
    def __init__(self, test, oldOptionGroup = None, graph = None, plotAveragers = None):
        guiplugins.InteractiveAction.__init__(self, test, oldOptionGroup, "Graph")
        self.addOption(oldOptionGroup, "r", "Horizontal range", "0:")
        self.addOption(oldOptionGroup, "yr", "Vertical range")
        self.addOption(oldOptionGroup, "ts", "Time scale to use", "minutes")
        self.addOption(oldOptionGroup, "p", "Absolute file to print to")
        self.addOption(oldOptionGroup, "i", "Log file item to plot", costEntryName)
        self.addOption(oldOptionGroup, "v", "Extra versions to plot")
        self.addSwitch(oldOptionGroup, "pc", "Print in colour")
        self.addSwitch(oldOptionGroup, "s", "Plot against solution number rather than time")
        self.addSwitch(oldOptionGroup, "av", "Plot also average")
        self.addSwitch(oldOptionGroup, "oav", "Plot only average")
        self.addOption(oldOptionGroup, "title", "Title of the plot")
        self.addOption(oldOptionGroup, "tu", "Search for temporary files in user")
        self.addSwitch(oldOptionGroup, "nt", "Don't search for temporary files")
        
        self.externalGraph = graph
        if graph:
            self.testGraph = graph
        else:
            self.testGraph = TestGraph()
        self.plotAveragers = plotAveragers
    def __repr__(self):
        return "Plotting Graph"
    def getTitle(self):
        return "Plot Graph"
    def getItemsToPlot(self):
        text = self.optionGroup.getOptionValue("i")
        if text == "apctimes":
            text = "DH_post_processing,Generation_time,Coordination_time,Conn_fixing_time,Optimization_time,Network_generation_time"
        return plugins.commasplit(text.replace("_", " "))
    def __repr__(self):
        return "Plotting"
    def __call__(self, test):
        logFileStem = test.app.getConfigValue("log_file")
        searchInUser = self.optionGroup.getOptionValue("tu")
        noTmp = self.optionGroup.getSwitchValue("nt")
        if not noTmp:
            logFileFinder = LogFileFinder(test, tryTmpFile = 1, searchInUser  = searchInUser)
            foundTmp, logFile = logFileFinder.findFile()
            if foundTmp:
                self.writePlotFiles("this run", logFile, test)
        stdFile = test.makeFileName(logFileStem)
        if os.path.isfile(stdFile):
            self.writePlotFiles("std result", stdFile, test)
        for version in plugins.commasplit(self.optionGroup.getOptionValue("v")):
            if version:
                if not noTmp:
                    logFileFinder = LogFileFinder(test, tryTmpFile = 1, searchInUser  = searchInUser)
                    foundTmp, logFile = logFileFinder.findFile(version)
                    if foundTmp:
                        self.writePlotFiles(version + "run", logFile, test)
                # Find the closest possible matching version. hack, should be done by texttest core.
                possibleVersions = test.app._getVersionExtensions(version.split("."))
                for ver in possibleVersions:
                    logFile = test.makeFileName(logFileStem, version,temporary = 0, forComparison = 0) + ".apc." + ver
                    if os.path.isfile(logFile):
                        self.writePlotFiles(version, logFile, test)
                        if not ver == version:
                            print "Using log file with version", ver, "to print test", test.name, "version", version 
                        break
        if not self.externalGraph:
            self.plotGraph()
    def plotGraph(self):
        xrange, yrange, fileName, writeColour , onlyAverage, title= self.getPlotOptions()
        self.testGraph.plot(self.test.app.writeDirectory, xrange, yrange, fileName, writeColour, onlyAverage, title, None)
        self.testGraph = TestGraph()
    def getPlotOptions(self):
        xrange = self.optionGroup.getOptionValue("r")
        yrange = self.optionGroup.getOptionValue("yr")
        fileName = self.optionGroup.getOptionValue("p")
        writeColour = self.optionGroup.getSwitchValue("pc")
        onlyAverage = self.optionGroup.getSwitchValue("oav")
        title = self.optionGroup.getOptionValue("title")
        return xrange, yrange, fileName, writeColour, onlyAverage, title
    def writePlotFiles(self, lineName, logFile, test):
        plotItems = self.getItemsToPlot()
        optRun = OptimizationRun(test.app, [ timeEntryName ], plotItems, logFile)
        if len(optRun.solutions) == 0:
            return

        for item in plotItems:
            averager = None
            if self.optionGroup.getSwitchValue("av") or self.optionGroup.getSwitchValue("oav"):
                if not self.plotAveragers.has_key(lineName+item):
                    averager = self.plotAveragers[lineName+item] = PlotAverager(self.test.app.writeDirectory)
                else:
                    averager = self.plotAveragers[lineName+item]
            plotLine = PlotLine(test, lineName, item, optRun, self.optionGroup.getSwitchValue("s"), self.optionGroup.getOptionValue("ts"), averager)
            self.testGraph.addLine(plotLine)

class StartStudio(guiplugins.InteractiveAction):
    def __repr__(self):
        return "Studio"
    def getTitle(self):
        return "Studio"
    def getScriptTitle(self):
        return "Start Studio"
    def matchesMode(self, dynamic):
        return not dynamic
    def __call__(self, test):
        test.setUpEnvironment(parents=1)
        print "CARMSYS:", os.environ["CARMSYS"]
        print "CARMUSR:", os.environ["CARMUSR"]
        print "CARMTMP:", os.environ["CARMTMP"]
        fullSubPlanPath = test.app.configObject.target._getSubPlanDirName(test)
        lPos = fullSubPlanPath.find("LOCAL_PLAN/")
        subPlan = fullSubPlanPath[lPos + 11:]
        localPlan = string.join(subPlan.split(os.sep)[0:-1], os.sep)
        studioCommand = "studio -p'CuiOpenSubPlan(gpc_info,\"" + localPlan + "\",\"" + subPlan + "\",0)'"
        commandLine = os.path.join(os.environ["CARMSYS"], "bin", studioCommand)
        self.startExternalProgram(commandLine)
        test.tearDownEnvironment(parents=1)

guiplugins.interactiveActionHandler.testClasses += [ PlotTestInGUI, StartStudio ]

class PlotLine:
    def __init__(self, test, lineName, item, optRun, plotAgainstSolution, plotTimeScale, averager):
        self.test = test
        self.name = lineName
        self.lineType = None
        self.pointType = None
        if item != costEntryName:
            self.name += "." + item
        self.axisLabels = {}
        timeScaleFactor = 0
        if plotAgainstSolution:
            self.axisLabels["x"] = "Solution number"
        else:
            if plotTimeScale == "hours":
                timeScaleFactor = 60
                self.axisLabels["x"] = "CPU time (hours)"
            elif plotTimeScale == "days":
                timeScaleFactor = 60*24
                self.axisLabels["x"] = "CPU time (days)"
            else:
                if not plotTimeScale == "minutes":
                    print "Unknown time scale unit", plotTimeScale, ", using minutes."
                timeScaleFactor = 1
                self.axisLabels["x"] = "CPU time (min)"
        self.axisLabels["y"] = item
        self.plotFileName = test.makeFileName(self.getPlotFileName(lineName, str(item)), temporary=1, forComparison=0)
        graph = self.writeFile(optRun, item, plotAgainstSolution, timeScaleFactor)
        if averager:
            averager.addGraph(graph)
            if not averager.plotLineRepresentant:
                averager.plotLineRepresentant = self
    def getAxisLabel(self, axis):
        return self.axisLabels[axis]
    def getPlotFileName(self, lineName, item):
        if item == costEntryName:
            return "plot-" + lineName.replace(" ", "-")
        else:
            return "plot-" + lineName.replace(" ", "-") + "-" + item.replace(" ", "-")
    def writeFile(self, optRun, item, plotAgainstSolution, timeScaleFactor):
        dir, localName = os.path.split(self.plotFileName)
        if not os.path.isdir(dir):
            os.makedirs(dir)
        plotFile = open(self.plotFileName, "w")
        graph = {}
        cnt = 0
        for solution in optRun.solutions:
            if solution.has_key(item):
                if plotAgainstSolution:
                    plotFile.write(str(solution[item]) + os.linesep)
                    graph[cnt] = solution[item]
                    cnt = cnt + 1
                else:
                    plotFile.write(str(solution[timeEntryName]/timeScaleFactor) + "  " + str(solution[item]) + os.linesep)
                    graph[solution[timeEntryName]/timeScaleFactor] = solution[item]
        return graph           
    def getPlotArguments(self, multipleApps, multipleUsers, multipleLines, multipleTests):
        return "'" + self.plotFileName + "' " + self.getPlotName(multipleApps, multipleUsers, multipleTests) + self.getStyle(multipleLines)
    def getPlotName(self, addAppDescriptor, addUserDescriptor, addTestDescriptor):
        title = " title \""
        if addAppDescriptor:
            title += self.test.app.fullName + "."
        if addUserDescriptor:
            title += self.getUserName() + "."
        if addTestDescriptor:
            title += self.test.name + "."
        title += self.name + "\" "
        return title
    def getUserName(self):
        return self.test.getRelPath().split(os.sep)[0]
    def getStyle(self, multipleLines):
        if multipleLines:
            style = " with linespoints lt " +  self.lineType + " pt " + self.pointType
        else:
            style = " with linespoints "
        return style
    
