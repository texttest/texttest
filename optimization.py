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

-plot <++> - Displays a gnuplot graph with the cpu time (in minutes) versus total cost. 
             The data is extracted from the status file of test(s), and if the test is
             currently running, the temporary status file is used, see however the
             option nt below. All tests selected are plotted in the same graph.
             The following options are supported:
             - r=range
               The x-axis has the range range. Default is the whole data set. Example: 60:
             - yr=range
               The y-axis has the y-range range. Default is the whole data set. Example: 2e7:3e7
             - per
               Plots percentage relative to the minimal cost.
             - p=an absolute file name
               Produces a file (default postscript) instead of displaying the graph.
             - pr=printer name
               Produces postscript output and sends it to the printer specified.
             - pc
               The postscript file will be in color.
             - pa3
               The postscript will be in A3 format and landscape.
             - i=item,item,...
               Which item to plot from the status file. Note that whitespaces are replaced
               by underscores. Default is TOTAL cost. Example: i=overcover_cost.
               If a comma-seperated list is given, all the listed items are plotted.
               An abreviation is 'i=apctimes', which is equivalent to specifying 'i=OC_to_DH_time,
               Generation_time,Costing_time,Conn_fixing,Optimization_time,Network_generation_time'.
             - ix=item
               Item to plot against (use on the x axis) from the status file. Default is "cpu time".
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
             - v=v1,v2
               Plot multiple versions in same dia, ie 'v=,9' means master and version 9
               Moreover, you may supply a time scale factor for the different versions
               using the syntax v1:scale1,v2:scale2.
               You can also retrive old results from CVS using the syntax ::date where
               date is specified with 6 digits. Example: master::060101
             - oem
               Plot only exactly matching version, rather than plotting the closest
               matching version if no exact match exists.
             - title=graphtitle
               Sets the title of the graph to graphtitle, rather than the default generated one.
             - ts=hours|days|minutes
               Used as time scale on the x-axis. Default is minutes.
             - nl
               No legend.
             - olav
               Only legend for the averages.
             - engine=gnuplot|mpl
               Use as plot engine. Currently, gnuplot and matplotlib is supported, gnuplot is the default.
               The matplotlib engine doesn't have the printing options (p, pc, pr and pa3) implemented yet.
             - terminal
               Set what type of terminal gnuplot should use for plotting, effective in
               conjuction with the p option. See the gnuplot documentation for all possibilities,
               some interesting ones are: postscript, png, svg.
             - size
               Sets the size of the plot, the meaning may vary from engine to engine.
"""
             
helpScripts="""optimization.TableTest     - Displays solution data in a table. Works the same as -plot in most respects,
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
optimization.PlotSubplans
                           - Uses texttest's plotting functionality to plot arbitrary subplans that isn't
                             part of texttest's test hierarchy.'
                             Subplans are specified using the option sp=local_plan_dir/subplan_regexp1,subplan_regexp2.
                             Subplans specified with the different regexps are considered to be in different groups
                             when plotting, i.e., they get different colors etc.
                             All options for -plot (see above) that makes sense are supported.
                             Options not supported are: v, nt, oem
                             Example:
                             texttest -a apc -s optimization.PlotSubplans 'sp=/nfs/vm/csc/carmdata/dl_ifs_pac_IQ_data/LOCAL_PLAN/200512_OPTEST/standard_21octOptTest/weekly/3fa_ji_,3fa_sl_na_ji per yr=:1 ts=hours oav title=3FA_weekly'
"""


import ravebased, os, sys, string, shutil, KPI, plugins, math, re, unixonly, guiplugins, copy, testoverview, time, testmodel
from ndict import seqdict
from time import sleep
from respond import Responder
from comparetest import MakeComparisons, TestComparison
from comparefile import FileComparison
from performance import getTestPerformance

itemNamesConfigKey = "_itemnames_map"
noIncreasMethodsConfigKey = "_noincrease_methods_map"

# Names of reported entries
costEntryName = "cost of plan"
timeEntryName = "cpu time"
memoryEntryName = "memory"
methodEntryName = "Running.*\.\.\."
periodEntryName = "Period\."
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
                group.addOption("plot", "Plot Graph of selected runs")
    def getActionSequence(self):
        if self.optionMap.has_key("plot"):
            return [ self.getWriteDirectoryMaker(), DescribePlotTest() ]
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
    def useQueueSystem(self):
        if self.optionMap.has_key("plot") or self.optionMap.has_key("kpi") or \
               self.optionMap.has_key("kpiData") or self.optionMap.has_key("prrep"):
            return False
        return ravebased.Config.useQueueSystem(self)
    def getResponderClasses(self, allApps):
        if self.optionMap.has_key("plot"):
            return [ GraphPlotResponder ]
        else:
            return ravebased.Config.getResponderClasses(self, allApps)
    def getTestComparator(self):
        return MakeComparisons(OptimizationTestComparison, self.getProgressComparisonClass())
    def getProgressComparisonClass(self):
        pass # for APC
    def getProgressReportBuilder(self):
        return MakeProgressReport(self.optionValue("prrep"))
    def defaultBuildRules(self):
        # Assume we always want to build at least some rules, by default...
        return 1
    def getWriteDirectoryPreparer(self, ignoreCatalogues):
        return PrepareCarmdataWriteDir(ignoreCatalogues, self._getSubPlanDirName)
    def filesFromSubplan(self, test, subplanDir):
        rulesFile = os.path.join(subplanDir, "APC_FILES", "rules")
        if not os.path.isfile(rulesFile):
            return []

        subplanFiles = [ ("Subplan", rulesFile ) ]
        return subplanFiles + self.filesFromRulesFile(test, rulesFile)
    def filesFromRulesFile(self, test, rulesFile):
        return []
    def printHelpDescription(self):
        print helpDescription
        ravebased.Config.printHelpDescription(self)
    def printHelpOptions(self):
        ravebased.Config.printHelpOptions(self)
        print helpOptions
    def printHelpScripts(self):
        ravebased.Config.printHelpScripts(self)
        print helpScripts
    def setApplicationDefaults(self, app):
        ravebased.Config.setApplicationDefaults(self, app)
        app.setConfigDefault(itemNamesConfigKey, self.itemNamesInFile, "Private: Item name map for optimization status file parsing")
        app.setConfigDefault(noIncreasMethodsConfigKey, self.noIncreaseExceptMethods, "Private: Item names not allowed to increase")
        app.setConfigDefault("cvs_log_for_files", "", "File list that should be displayed by CVS log functionality")
        app.setConfigDefault("kpi_cost_margin", 0.0, "Cost margin for the KPI calculations")
        app.setConfigDefault("skip_comparison_if_not_present", "error", "List of files that are compared only if they are created by the test, i.e. they will not be reported as missing")
        app.addConfigEntry("definition_file_stems", "raveparameters")

# Insert the contents of all raveparameters into the temporary rules file
# Also assume the subplan will be changed, but nothing else.
class PrepareCarmdataWriteDir(ravebased.PrepareCarmdataWriteDir):
    def __init__(self, ignoreCatalogues, subplanFunction):
        ravebased.PrepareCarmdataWriteDir.__init__(self, ignoreCatalogues)
        self.subplanFunction = subplanFunction
        self.raveParameters = []
    def setUpSuite(self, suite):
        self.readRaveParameters(suite.getFileName("raveparameters"))
    def tearDownSuite(self, suite):
        self.unreadRaveParameters()
    def partialCopyTestPath(self, test, carmdataSource, carmdataTarget):
        self.readRaveParameters(test.getFileName("raveparameters"))
        ravebased.PrepareCarmdataWriteDir.partialCopyTestPath(self, test, carmdataSource, carmdataTarget)
        self.unreadRaveParameters()
    def getModifiedPaths(self, test, carmdataSource):
        modPathsBasic = ravebased.PrepareCarmdataWriteDir.getModifiedPaths(self, test, carmdataSource)
        if modPathsBasic is None:
            return self.getModPathsFromSubplan(test, carmdataSource)
        else:
            return modPathsBasic
    def getModPathsFromSubplan(self, test, carmdataSource):
        if os.environ.has_key("DISABLE_TMP_DIR_CREATION"):
            return {}

        subplan = self.subplanFunction(test)
        if not os.path.isdir(subplan):
            raise plugins.TextTestError, "Cannot run test " + test.name + " - subplan at " + subplan + " does not exist."

        currPath = os.path.join(subplan, "APC_FILES")
        self.diag.info("Modified path at " + currPath)
        modPaths = { currPath : [] }
        while currPath != carmdataSource:
            parent, local = os.path.split(currPath)
            if parent == currPath:
                raise plugins.TextTestError, "Subplan " + subplan + " is not relative to " + carmdataSource + \
                      " - probably mismatch between CARMUSR and CARMDATA"
            modPaths[parent] = [ currPath ]
            currPath = parent
        return modPaths
    def isWriteDir(self, targetPath, modPaths):
        return os.path.basename(targetPath) == "APC_FILES"
    def handleReadOnly(self, sourceFile, targetFile):
        if self.shouldLink(sourceFile) and not self.insertRaveParameters(sourceFile, targetFile):
            ravebased.PrepareCarmdataWriteDir.handleReadOnly(self, sourceFile, targetFile)
    def insertRaveParameters(self, sourceFile, targetFile):
        if os.path.basename(sourceFile) != "rules":
            return False

        overrides = self.getAllOverrides()
        if len(overrides) == 0:
            return False
        
        file = open(targetFile, 'w')
        for line in open(sourceFile).xreadlines():
            if line.find("<SETS>") != -1:
                for override in overrides:
                    file.write(override)
            file.write(line)
        return True
    def getAllOverrides(self):
        allOverrides = []
        for overrideItems in self.raveParameters:
            allOverrides += overrideItems
        return allOverrides
    def readRaveParameters(self, fileName):
        if not fileName:
            self.raveParameters.append([])
        else:
            self.raveParameters.append(open(fileName).readlines())
        self.diag.info("Added to list : " + repr(self.raveParameters))    
    def unreadRaveParameters(self):
        self.raveParameters.pop()
        self.diag.info("Removed from list : " + repr(self.raveParameters))
    def shouldLink(self, sourceFile):
        dirname, file = os.path.split(sourceFile)
        if file == "etable" or dirname.find("LOCAL_PLAN") == -1:
            return True
        if os.path.basename(dirname) != "APC_FILES":
            return False

        names = [ "input", "status", "colgen_analysis.example_rotations", "hostname", "best_solution" ]
        prefixes = [ "Solution_", "core", "run_status", "optinfo" ]
        postfixes = [ ".log" ]
        if file in names:
            return False
        for prefix in prefixes:
            if file.startswith(prefix):
                return False
        for postfix in postfixes:
            if file.endswith(postfix):
                return False
        return True   

class OptimizationTestComparison(TestComparison):
    def __init__(self, previousInfo, app, lifecycleChange=""):
        TestComparison.__init__(self, previousInfo, app, lifecycleChange)
        self.costName = costEntryName
        itemsInFile = app.getConfigValue(itemNamesConfigKey)
        if itemsInFile.has_key(costEntryName):
            self.costName = itemsInFile[costEntryName]
        self.logStem = app.getConfigValue("log_file")
    def createFileComparison(self, test, stem, standardFile, tmpFile):
        if not tmpFile and stem in test.app.getConfigValue("skip_comparison_if_not_present").split(","):
            return
        
        if stem == "solution" and tmpFile and standardFile:
            tmpLogFile = test.makeTmpFileName(self.logStem)
            stdLogFile = test.getFileName(self.logStem)
            if stdLogFile and os.path.isfile(tmpLogFile):
                oldCost = self.getCost(stdLogFile)
                newCost = self.getCost(tmpLogFile)
                if oldCost is not None and newCost is not None and oldCost != newCost:
                    return SolutionFileComparison(test, stem, standardFile, tmpFile, oldCost, newCost)
            
        return TestComparison.createFileComparison(self, test, stem, standardFile, tmpFile)
    def getCost(self, file):
        cmd = "grep '" + self.costName + "' " + file
        grepLines = os.popen(cmd).readlines()
        if len(grepLines) > 0:
            lastField = grepLines[-1].split(" ")[-1]
            return float(lastField.strip())
    
class SolutionFileComparison(FileComparison):
    def __init__(self, test, stem, standardFile, tmpFile, oldCost, newCost):
        FileComparison.__init__(self, test, stem, standardFile, tmpFile, testInProgress=0, observers=[])
        self.oldCost = oldCost
        self.newCost = newCost
    def getDifferencesSummary(self, includeNumbers=True):
        if self.oldCost < self.newCost:
            if includeNumbers:
                return "solution " + self.calculatePercentageIncrease(self.oldCost, self.newCost) + "% worse"
            else:
                return "solution worse"
        else:
            if includeNumbers:
                return "solution " + self.calculatePercentageIncrease(self.newCost, self.oldCost) + "% better"
            else:
                return "solution better"
    def calculatePercentageIncrease(self, smallest, largest):
        if smallest == 0.0:
            return 0.0

        floatVal = ((largest - smallest) / abs(smallest)) * 100
        return str(round(floatVal, 1))
    def getDetails(self):
        if self.hasDifferences():
            return self.getDifferencesSummary()
        else:
            return ""
     
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
        logFile = self.test.getFileName(self.logStem, version)
        if logFile:
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
            logFile = self.test.getFileName(self.logStem, version)
            if logFile:
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
        # Construct a search string.
        app = self.test.app
        if not version:
            version = string.join(app.versions, ".")
        versionMod = ""
        if version:
            versionMod = "." + version + "."
        searchString = app.name + versionMod 
        try:
            root = app.getPreviousWriteDirInfo(self.searchInUser)
        except plugins.TextTestError:
            # If there isn't any temp info, this will throw
            return None, None
        if thisRun:
            fromThisRun = self.test.makeTmpFileName(stem)
            self.diag.info("Looked for " + fromThisRun)
            if os.path.isfile(fromThisRun): # Temp removed, doesn't work for matador. and fromThisRun.find(searchString) != -1:
                return fromThisRun, app.writeDirectory
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
    def getTime(self, solNum = -1):
        return self.solutions[solNum][timeEntryName]
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
    def getLogFile(self, test):
        stem = test.app.getConfigValue("log_file")
        if self.useTmpFiles:
            return test.makeTmpFileName(stem)
        else:
            return test.getFileName(stem)
    def __call__(self, test):
        # Values that should be reported if present, but should not be fatal if not
        extraValues = [ "machine", "Crew Members" ]
        logFile = self.getLogFile()
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
        currPerf = getTestPerformance(test, self.currentVersion) / 60
        refPerf = getTestPerformance(test, self.referenceVersion) / 60
        return currPerf, refPerf
    def getLogFilesForComparison(self, test):
        currentLogFile = test.getFileName(test.app.getConfigValue("log_file"), self.currentVersion)
        refLogFile = test.getFileName(test.app.getConfigValue("log_file"), self.referenceVersion)
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
        floatRefPerfScale = getTestPerformance(test, self.referenceVersion) / 60
        floatNowPerfScale = getTestPerformance(test, self.currentVersion) / 60
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
        floatRefPerfScale = getTestPerformance(test, self.referenceVersion) / 60
        floatNowPerfScale = getTestPerformance(test, self.currentVersion) / 60
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
    def doCompare(self, referenceRun, currentRun, app, groupName, userName, groupNameDefinition = "test",appSpecificData=None):
        if currentRun.isVeryShort() or referenceRun.isVeryShort():
            return None
        worstCost = self.calculateWorstCost(referenceRun, currentRun, app, groupName)
        currTTWC = currentRun.timeToCost(worstCost)
        refTTWC = referenceRun.timeToCost(worstCost)
        
        self.testCount += 1
        kpi = self.computeKPI(currTTWC, refTTWC)
        print os.linesep, "Comparison on", app, groupNameDefinition, groupName, "(in user " + userName + ") : K.P.I. = " + kpi
        self.reportLine("                         ", self.currentText(), "Version " + self.referenceVersion)
        retVal2=self.reportCosts(currentRun, referenceRun, app, groupName,appSpecificData)
        self.reportLine("Max memory (MB)", currentRun.getMaxMemory(), referenceRun.getMaxMemory())
        self.reportLine("Total time (minutes)     ", currentRun.getPerformance(), referenceRun.getPerformance())
        self.reportLine("Time to cost " + str(worstCost) + " (mins)", currTTWC, refTTWC)

        # add data for plotting
        retVal={"KPILine":((currTTWC,worstCost),(refTTWC,worstCost),1)}
        retVal["kpi"]=kpi;
        retVal["worstCost"]=worstCost
        if (retVal2):
            retVal.update(retVal2);
        return retVal
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
    def reportCosts(self, currentRun, referenceRun, app, groupName,appSpecificData=None):
        costEntries = []
        for entry in currentRun.solutions[0].keys():
            if entry.find("cost") != -1 and entry in referenceRun.solutions[0].keys():
                costEntries.append(entry)
        costEntries.sort()
        for entry in costEntries:
            self.reportLine("Initial " + entry, currentRun.solutions[0][entry], referenceRun.solutions[0][entry])
        for entry in costEntries:
            self.reportLine("Final " + entry, currentRun.solutions[-1][entry], referenceRun.solutions[-1][entry])
        return {}
    def currentText(self):
        if self.currentVersion == None:
            return "Current"
        else:
            return "Version " + self.currentVersion
    def reportLine(self, title, currEntry, refEntry):
        fieldWidth = 15
        titleWidth = 30
        print string.ljust(title, titleWidth) + ": " + string.rjust(str(currEntry), fieldWidth) + string.rjust(str(refEntry), fieldWidth)

# Graphical import test
class ImportTestCase(guiplugins.ImportTestCase):
    def addDefinitionFileOption(self, suite):
        self.addOption("sp", "Subplan name")
    def getSubplanName(self):
        return self.optionGroup.getOptionValue("sp")
    def getNewTestName(self):
        nameEntered = guiplugins.ImportTestCase.getNewTestName(self)
        if len(nameEntered) > 0:
            return nameEntered
        # Default test name to subplan name
        subplan = self.getSubplanName()
        if len(subplan) == 0:
            return nameEntered
        root, local = os.path.split(subplan)
        return local
    def getOptions(self, suite):
        pass
    # getOptions implemented in subclasses
        
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

# Start of "PlotTest" functionality.
# Classes for using gnuplot to plot test curves of tests
#

# Simple description action for backwards compatibility to show what we're doing (command line only)
class DescribePlotTest(plugins.Action):
    def __repr__(self):
        return "Plotting"
    def __call__(self, test):
        self.describe(test)
    def setUpSuite(self, suite):
        self.describe(suite)

# Responder for plotting from the command line
class GraphPlotResponder(Responder):
    def __init__(self, optionMap):
        Responder.__init__(self, optionMap)
        self.testGraph = TestGraph()
        self.testGraph.readCommandLine(optionMap["plot"].split())
        self.writeDir = None
    def addSuite(self, suite):
        if not self.writeDir:
            self.writeDir = suite.app.writeDirectory
    def notifyComplete(self, test):
        self.testGraph.createPlotObjectsForTest(test)
    def notifyAllComplete(self):
        try:
            self.testGraph.plot(self.writeDir)
        except plugins.TextTestError, e:
            print e

# This is the action responsible for plotting from the GUI.
class PlotTestInGUI(guiplugins.InteractiveTestAction):
    def __init__(self, dynamic, test):
        guiplugins.InteractiveTestAction.__init__(self, test)
        self.dynamic = dynamic
        self.testGraph = TestGraph(self.optionGroup)
    def __repr__(self):
        return "Plotting Graph"
    def getTitle(self):
        return "_Plot Graph"
    def __repr__(self):
        return "Plotting"
    def inButtonBar(self):
        return True
    def getTabTitle(self):
        return "Graph"
    def performOnCurrent(self):
        self.createGUIPlotObjects(self.currentTest)
        self.plotGraph(self.currentTest.app.writeDirectory)
    def createGUIPlotObjects(self, test):
        logFileStem = test.getConfigValue("log_file")
        if self.dynamic:
            tmpFile = self.getTmpFile(test, logFileStem)
            if tmpFile:
                self.testGraph.createPlotObjects("this run", tmpFile, test, None)

        stdFile = test.getFileName(logFileStem)
        if stdFile:
            self.testGraph.createPlotObjects("std result", stdFile, test, None)
    
        if not self.dynamic:
            for version in self.testGraph.getExtraVersions():
                plotFile = test.getFileName(logFileStem, version)
                if plotFile and plotFile.endswith(test.app.name + "." + version):
                    self.testGraph.createPlotObjects(version, plotFile, test, None)

    def getTmpFile(self, test, logFileStem):
        if test.state.isComplete():
            try:
                fileComp, storageList = test.state.findComparison(logFileStem, includeSuccess=True)
                if fileComp:
                    return fileComp.tmpFile
            except AttributeError:
                pass
        else:
            tmpFile = self.getRunningTmpFile(test, logFileStem)
            if os.path.isfile(tmpFile):
                return tmpFile
    def getRunningTmpFile(self, test, logFileStem):
        return test.makeTmpFileName(logFileStem)
    def plotGraph(self, writeDirectory):
        plotProcess = self.testGraph.plot(writeDirectory)
        if plotProcess:
            # Should really monitor this and close it when GUI closes,
            # but it isn't a child process so this means ps and load on the machine
            #self.processes.append(plotProcess)
            guiplugins.scriptEngine.monitorProcess("plots graphs", plotProcess)
        # The TestGraph is "used", create a new one so that the user can do another plot.
        self.testGraph = TestGraph(self.optionGroup)

plotSubplanDone = None

class PlotSubplans(plugins.Action):
    def __init__(self, args = []):
        self.args = args
    def setUpApplication(self, app):
        # Avoid plotting several times-setUpApp is called several times when you have extra_version.
        global plotSubplanDone
        if plotSubplanDone:
            return
        plotSubplanDone = 1
        # Create a test graph
        testGraph = TestGraph()
        testGraph.optionGroup.addOption("sp", "Subplan")
        testGraph.readCommandLine(self.args)
        if not testGraph.optionGroup.getOptionValue("title"):
            testGraph.optionGroup.setValue("title", " ")
        subplan = testGraph.optionGroup.getOptionValue("sp")
        splitSP = subplan.split(",")
        dirName = os.path.dirname(splitSP[0])
        version = 1
        for sp in splitSP:
            regexp = os.path.basename(sp)
            for file in os.listdir(dirName):
                if re.findall(regexp, file):
                    subplan = os.path.join(dirName, file)
                    testTmpDir = os.path.join(app.writeDirectory, file)
                    if not os.path.isdir(testTmpDir):
                        os.makedirs(testTmpDir)
                    logFilePath = os.path.join(subplan, "APC_FILES", app.getConfigValue("log_file"))
                    desc = testGraph.getPlotLineDescriptionForSubplan(file, app)
                    testGraph.createPlotObjectsForItems(str(version), logFilePath, desc, None, testTmpDir, app)
            version += 1
        testGraph.plot(app.writeDirectory)
        
# TestGraph is the "real stuff", the PlotLine instances are created here and gnuplot is invoked here.
class TestGraph:
    def __init__(self, guiOptionGroup=None):
        self.plotLines = []
        self.pointTypes = {}
        self.lineTypes = {}
        self.pointTypeCounter = 1
        self.users = []
        self.apps = []
        self.gnuplotFile = None
        self.plotAveragers = {}
        self.axisXLabel = None
        self.xScaleFactor = 1
        # This is the options and switches that are common
        # both for the GUI and command line.
        options = [ ("r", "Horizontal range", "0:"),
                    ("yr", "Vertical range", ""),
                    ("ts", "Time scale to use", "minutes"),
                    ("p", "Absolute file to print to", ""),
                    ("pr", "Printer to print to", ""),
                    ("i", "Log file item to plot", costEntryName),
                    ("ix", "Log file item to plot against", timeEntryName),
                    ("v", "Extra versions to plot", ""),
                    ("title", "Title of the plot", ""),
                    ("size", "size of the plot", ""),
                    ("terminal", "gnuplot terminal to use", "postscript"),
                    ("engine", "Plot engine to use", "gnuplot") ]
        switches = [ ("per", "Plot percentage"),
                     ("pc", "Print in colour"),
                     ("pa3", "Print in A3"),
                     ("s", "Plot against solution number rather than time"),
                     ("av", "Plot also average"),
                     ("oav", "Plot only average"),
                     ("nl", "No legend"), 
                     ("olav", "Only legend for the averages") ]
        self.diag = plugins.getDiagnostics("Test Graph")
        self.optionGroup = guiOptionGroup
        if not self.optionGroup:
            self.optionGroup = plugins.OptionGroup("Plot", {}, {"" : []})
            self.optionGroup.addOption("tu", "Search for tmp files in user", "")
            self.optionGroup.addSwitch("oem", "Only plot exactly matching versions")
            self.optionGroup.addSwitch("nt", "Don't search for temporary files")
        # Create the options and read the command line arguments.
        for name, expl, value in options:
            self.optionGroup.addOption(name, expl, value)
        for name, expl in switches:
            self.optionGroup.addSwitch(name, expl)
    def readCommandLine(self, args):
        self.optionGroup.readCommandLineArguments(args)
    def plot(self, writeDir):
        # Add the PlotAveragers last in the PlotLine list.
        for plotAverager in self.plotAveragers:
            self.plotLines.append(self.plotAveragers[plotAverager])
        engineOpt = self.optionGroup.getOptionValue("engine")
        if engineOpt == "gnuplot":
            engine = PlotEngine(self)
        elif engineOpt == "mpl" and mplDefined:
            engine = PlotEngineMPL(self)
        else:
            raise plugins.TextTestError, "Unknown plot engine " + engineOpt + " - aborting plotting."
        return engine.plot(writeDir)
    def getExtraVersions(self):
        rawText = self.optionGroup.getOptionValue("v")
        return filter(lambda version: version, plugins.commasplit(rawText))
    def getPlotOptions(self):
        xrange = self.optionGroup.getOptionValue("r")
        yrange = self.optionGroup.getOptionValue("yr")
        fileName = self.optionGroup.getOptionValue("p")
        writeColour = self.optionGroup.getSwitchValue("pc")
        printA3 = self.optionGroup.getSwitchValue("pa3")
        onlyAverage = self.optionGroup.getSwitchValue("oav")
        title = self.optionGroup.getOptionValue("title")
        noLegend = self.optionGroup.getSwitchValue("nl")
        onlyLegendAverage = self.optionGroup.getSwitchValue("olav")
        printer = self.optionGroup.getOptionValue("pr")
        plotPercentage = self.optionGroup.getSwitchValue("per")
        terminal = self.optionGroup.getOptionValue("terminal")
        plotSize = self.optionGroup.getOptionValue("size")
        return xrange, yrange, fileName, printer, writeColour, printA3, onlyAverage, plotPercentage, title, noLegend, onlyLegendAverage, terminal, plotSize
    def findMinOverPlotLines(self):
        min = self.plotLines[0].min
        for plotLine in self.plotLines[1:]:
            if not plotLine.plotLineRepresentant:
                if plotLine.min and plotLine.min < min:
                    min = plotLine.min
        return min
    def addLine(self, plotLine):
        self.plotLines.append(plotLine)
        description = plotLine.description
        if not description["app"] in self.apps:
            self.apps.append(description["app"])
        if not description["user"] in self.users:
            self.users.append(description["user"])
        if not description["test"] in self.pointTypes.keys():
            plotLine.pointType = str(self.pointTypeCounter)
            self.pointTypes[description["test"]] = plotLine.pointType
            self.pointTypeCounter += 1
        else:
            plotLine.pointType = self.pointTypes[description["test"]]
        # Fill in the map for later deduction
        self.lineTypes[description["name"]] = 0
    def deduceLineTypes(self, nextLineType):
        self.multipleApps = len(self.apps) > 1
        self.multipleUsers = len(self.users) > 1
        self.multipleTests = len(self.pointTypes) > 1
        self.multipleLineTypes = len(self.lineTypes) > 1
        plotArguments = []
        for plotLine in self.plotLines:
            if not plotLine.plotLineRepresentant:
                if not self.multipleTests or not self.multipleLineTypes or self.lineTypes[plotLine.description["name"]] == 0:
                    plotLine.lineType = str(nextLineType())
                    self.lineTypes[plotLine.description["name"]] = plotLine.lineType
                else:
                    plotLine.lineType = self.lineTypes[plotLine.description["name"]]
    def getYAxisLabel(self):
        label = None
        for plotLine in self.plotLines:
            if not plotLine.plotLineRepresentant:
                lineLabel = plotLine.getYAxisLabel()
                if not label:
                    label = lineLabel
                elif label != lineLabel:
                    return ""
        return label
    def getPlotLineName(self, plotLine, noLegend, onlyLegendAverage):
        if noLegend:
            return None
        if onlyLegendAverage and not plotLine.plotLineRepresentant:
            return None
        if plotLine.plotLineRepresentant:
            return plotLine.plotLineRepresentant.description["name"]
        title = ""
        if self.multipleApps:
            title += plotLine.description["app"].fullName
        if self.multipleUsers:
            title += plotLine.description["user"]
        if self.multipleTests:
            title += plotLine.description["test"] + "."
        title += plotLine.description["name"]
        return title
    def getPlotLineDescriptionForSubplan(self, testName, app):
        description = {}
        description["test"] = testName
        description["user"] = "unknown"
        description["app"]  = app
        return description
    def getPlotLineDescriptionForTest(self, test):
        description = {}
        description["test"] = test.name
        description["user"] = test.getRelPath().split(os.sep)[0]
        description["app"]  = test.app
        return description
    def addItemToDescription(self, description, lineName, item):
        description["name"] = lineName
        if item != costEntryName:
            description["name"] += "." + item
    def makeTitle(self, title):
        if title:
            return title;
        title = ""
        if len(self.apps) == 1:
            firstApp = self.apps[0]
            title += firstApp.fullName + " "
            version = firstApp.getFullVersion(forSave=1)
            if version:
                title += "Version " + version + " "
        if len(self.users) == 1:
            firstUser = self.users[0]
            title += "(in user " + firstUser + ") " 
        if len(self.pointTypes) == 1:
            firstTestName = self.pointTypes.keys()[0]
            title += ": Test " + firstTestName
        return title
    def setXAxisScaleAndLabel(self):
        xItem = self.optionGroup.getOptionValue("ix").replace("_", " ")
        if not xItem:
            xItem = timeEntryName
        plotTimeScale = self.optionGroup.getOptionValue("ts")
        plotAgainstSolution = self.optionGroup.getSwitchValue("s")
        if xItem != timeEntryName:
            self.axisXLabel = xItem
        elif plotAgainstSolution:
            self.axisXLabel = "Solution number"
        else:
            if plotTimeScale == "hours":
                self.xScaleFactor = 1.0/60.0
                self.axisXLabel = "CPU time (hours)"
            elif plotTimeScale == "days":
                self.xScaleFactor = 1.0/(60.0*24.0)
                self.axisXLabel = "CPU time (days)"
            else:
                if not plotTimeScale == "minutes":
                    print "Unknown time scale unit", plotTimeScale, ", using minutes."
                self.xScaleFactor = 1.0
                self.axisXLabel = "CPU time (min)"
    def getXAxisLabel(self):
        return self.axisXLabel
    # The routines below are the ones creating all the PlotLine instances for ONE test.
    def createPlotObjectsForItems(self, lineName, logFile, description, scaling, dir, app):
        # Find out what to plot.
        plotItemsText = self.optionGroup.getOptionValue("i")
        if plotItemsText == "apctimes":
            plotItemsText = "DH_post_processing,Generation_time,Coordination_time,Conn_fixing_time,Optimization_time,Network_generation_time"
        plotItems = plugins.commasplit(plotItemsText.replace("_", " "))

        xItem = self.optionGroup.getOptionValue("ix").replace("_", " ")
        if not xItem:
            xItem = timeEntryName
        
        optRun = OptimizationRun(app, [ xItem ], plotItems, logFile)
        if len(optRun.solutions) == 0:
            return

        for item in plotItems:
            desc = copy.copy(description)
            self.addItemToDescription(desc, lineName, item)
            plotFile = os.path.join(dir, "plot-" + desc["name"].replace(" ", "-"))
            plotLine = PlotLine(plotFile, desc , xItem, item, optRun, self.optionGroup.getSwitchValue("s"), scaling)
            self.addLine(plotLine)
            # Average
            if self.optionGroup.getSwitchValue("av") or self.optionGroup.getSwitchValue("oav"):
                if not self.plotAveragers.has_key(lineName+item):
                    averager = self.plotAveragers[lineName+item] = PlotAverager(app.writeDirectory)
                else:
                    averager = self.plotAveragers[lineName+item]
                averager.addGraph(plotLine.graph)
                if not averager.plotLineRepresentant:
                    averager.plotLineRepresentant = plotLine
    def isDate(self, version):
        if len(version) != 6:
            return None
        dateEntry = re.findall(r'[0-9]{6}', version)
	if len(dateEntry) == 0:
            return None
        return dateEntry[0]
    def createPlotObjects(self, lineName, logFile, test, scaling):
        dir = test.getDirectory(temporary=1, forFramework = 1)
        description = self.getPlotLineDescriptionForTest(test)
        self.createPlotObjectsForItems(lineName, logFile, description, scaling, dir, test.app)
    def createPlotObjectsForTest(self, test):
        # for command-line plotting only
        logFileStem = test.app.getConfigValue("log_file")
        searchInUser = self.optionGroup.getOptionValue("tu")
        onlyExactMatch = self.optionGroup.getSwitchValue("oem")
        noTmp = self.optionGroup.getSwitchValue("nt")
        if not noTmp:
            logFileFinder = LogFileFinder(test, tryTmpFile = 1, searchInUser=searchInUser)
            foundTmp, logFile = logFileFinder.findFile()
            if foundTmp:
                self.createPlotObjects("this run", logFile, test, None)
        stdFile = test.getFileName(logFileStem)
        if stdFile:
            self.createPlotObjects("std result", stdFile, test, None)
        for versionItem in self.getExtraVersions():
            if versionItem.find(":") == -1:
                versionName = version = versionItem
                scaling = None
                date = None
            else:
                tmp = versionItem.split(":")
                version = tmp[0]
                if len(tmp[1]) > 0:
                    scaling = float(tmp[1])
                else:
                    scaling = None
                versionName = version + " scaling " + str(scaling)
                if len(tmp) == 3 and self.isDate(tmp[2]):
                    date = self.isDate(tmp[2])
                else:
                    date = None
            if date:
                originalLogFileName = test.getFileName(logFileStem, version)
                CVSLogFileName = test.makeTmpFileName(logFileStem + "_" + date)
                # We may already have checked out the file.
                if not os.path.isfile(CVSLogFileName):
                    try:
                        os.makedirs(os.path.dirname(CVSLogFileName))
                    except OSError:
                        pass
                    stdin, stdout, stderr = os.popen3("cvs -q upd -p -D " + date + " " + originalLogFileName + " > " + CVSLogFileName)
                    if len(stderr.readlines()) > 0:
                        print os.path.basename(originalLogFileName), "is not in the CVS repository at", date
                    else:
                        self.createPlotObjects("CVS " + date, CVSLogFileName, test, None)
            else:
                if not noTmp:
                    logFileFinder = LogFileFinder(test, tryTmpFile = 1, searchInUser=searchInUser)
                    foundTmp, logFile = logFileFinder.findFile(version)
                    if foundTmp:
                        self.createPlotObjects(versionName + "run", logFile, test, scaling)
                logFile = test.getFileName(logFileStem, version)
                isExactMatch = logFile.endswith(version)
                if not onlyExactMatch and not isExactMatch:
                    print "Using log file", os.path.basename(logFile), "to print test", test.name, "version", version
                if not (onlyExactMatch and not isExactMatch):
                    self.createPlotObjects(versionName, logFile, test, scaling)

class PlotEngineCommon:
    def __init__(self, testGraph):
        self.testGraph = testGraph
        self.diag = plugins.getDiagnostics("Test Graph")
    def doPrint(self, printer, printA3, file):
        print "Printing to", printer
        extraArgs = ""
        if printA3:
            extraArgs += "-o PageSize=A3 "
        os.system("lpr " + extraArgs + "-P" + printer + " " + file)
        
class PlotEngine(PlotEngineCommon):
    def __init__(self, testGraph):
        PlotEngineCommon.__init__(self, testGraph)
        self.lineTypeCounter = 1
        self.undesiredLineTypes = []
    def getNextLineType(self):
        self.lineTypeCounter += 1
        while self.undesiredLineTypes.count(self.lineTypeCounter) > 0:
            self.lineTypeCounter += 1
        return self.lineTypeCounter
    # Create gnuplot plot arguments.
    def getStyle(self, plotLine, multipleLines):
        if plotLine.plotLineRepresentant:
            style = " with lines lt " + plotLine.plotLineRepresentant.lineType + " lw 2"
        elif multipleLines:
            style = " with linespoints lt " +  plotLine.lineType + " pt " + plotLine.pointType
        else:
            style = " with linespoints "
        return style
    def getPlotLineTitle(self, plotLine, noLegend, onlyLegendAverage):
        label = self.testGraph.getPlotLineName(plotLine, noLegend, onlyLegendAverage)
        if label:
            return " title \"" + label + "\" "
        else:
            return " notitle "
    def getPlotArgument(self, plotLine, multipleLines, noLegend, onlyLegendAverage):
        return "'" + plotLine.plotFileName + "' " + self.getPlotLineTitle(plotLine, noLegend, onlyLegendAverage) + self.getStyle(plotLine, multipleLines)
    def writeLinesAndGetPlotArguments(self, plotLines, xScaleFactor, min, onlyAverage, noLegend, onlyLegendAverage):
        plotArguments = []
        for plotLine in plotLines:
            plotLine.writeFile(xScaleFactor, min)
            if not onlyAverage or (onlyAverage and plotLine.plotLineRepresentant):
                plotArguments.append(self.getPlotArgument(plotLine, len(plotLines) > 1,
                                                          noLegend, onlyLegendAverage))
        return plotArguments
    def plot(self, writeDir):
        xrange, yrange, targetFile, printer, colour, printA3, onlyAverage, plotPercentage, title, noLegend, onlyLegendAverage, terminal, plotSize = self.testGraph.getPlotOptions()
        if len(self.testGraph.plotLines) == 0:
            return

        # Make sure that the writeDir is there, seems important in the static GUI.
        # Before, this was done as a side effect when writing the PlotLines.
        if not os.path.isdir(writeDir):
            os.makedirs(writeDir)
            
        os.chdir(writeDir)
        errsFile = os.path.join(writeDir, "gnuplot.errors")
        self.gnuplotFile, outputFile = os.popen2("gnuplot -persist -background white 2> " + errsFile)
        absTargetFile = None
        
        if targetFile:
            absTargetFile = os.path.expanduser(targetFile)
            # Mainly for testing...
            if not os.path.isabs(absTargetFile):
                absTargetFile = os.path.join(writeDir, absTargetFile)
            self.writePlot(self.terminalLine(terminal, colour))
        if printer:
            absTargetFile = os.path.join(writeDir, "graph.ps")
            self.writePlot(self.terminalLine(terminal, colour, printA3))
            if printA3:
                self.writePlot("set size 1.45,1.45")
                self.writePlot("set origin 0,-0.43")
        if targetFile or printer:
            self.undesiredLineTypes = [5, 6]

        if not (printer and printA3) and plotSize:
            self.writePlot("set size " + plotSize)

        self.testGraph.setXAxisScaleAndLabel()
        self.testGraph.deduceLineTypes(self.getNextLineType)
        self.writePlot("set ylabel '" + self.testGraph.getYAxisLabel() + "'")
        self.writePlot("set xlabel '" + self.testGraph.getXAxisLabel() + "'")
        self.writePlot("set time")
        self.writePlot("set title \"" + self.testGraph.makeTitle(title) + "\"")
        self.writePlot("set xtics border nomirror norotate")
        self.writePlot("set ytics border nomirror norotate")
        self.writePlot("set border 3")
        self.writePlot("set xrange [" + xrange +"];")
        if yrange:
            self.writePlot("set yrange [" + yrange +"];")
        min = None
        if plotPercentage:
            min = self.testGraph.findMinOverPlotLines()
            #self.writePlot("set label \"%\" at screen 0.03,0.5 rotate")
            #self.writePlot("set label \"Percentage above " + str(min) + "\" at screen 0.97,0.02 right")
            self.writePlot("set ylabel \"" + self.testGraph.getYAxisLabel() + "\\n% above " + str(min) + "\"")
        plotArguments = self.writeLinesAndGetPlotArguments(self.testGraph.plotLines,
                                                           self.testGraph.xScaleFactor, min, onlyAverage,
                                                           noLegend, onlyLegendAverage)
        relPlotArgs = [ arg.replace(writeDir, ".") for arg in plotArguments ]
        self.writePlot("plot " + string.join(relPlotArgs, ", "))
        if not absTargetFile:
            self.gnuplotFile.flush()
            gnuplotProcess = self.findGnuplotProcess()
            self.gnuplotFile.close()
            if gnuplotProcess:
                print "Created process : gnuplot window :", gnuplotProcess.processId
            else:
                raise plugins.TextTestError, "Failed to create gnuplot process - errors from gnuplot:\n" + open(errsFile).read() 
            return gnuplotProcess
        else:
            self.gnuplotFile.close()
            tmppf = outputFile.read()
            if len(tmppf) > 0:
                open(absTargetFile, "w").write(tmppf)
            if printer:
                self.doPrint(printer, printA3, absTargetFile)
    def terminalLine(self, terminal, colour, printA3=0):
        line = "set terminal " + terminal
        if printA3:
            line += " landscape"
        if colour:
            line += " color solid"
        return line
    def writePlot(self, line):
        self.gnuplotFile.write(line + os.linesep)
        self.diag.info(line + os.linesep)
    def findGnuplotProcess(self):
        thisProc = plugins.Process(os.getpid())
        for attempt in range(10):
            for childProc in thisProc.findChildProcesses():
                name = childProc.getName()
                if name.startswith("gnuplot_x11"):
                    return childProc
            sleep(0.1)

mplDefined = None
try:
    from matplotlib import *
    use('TkAgg')
    from matplotlib.pylab import *
    from matplotlib.font_manager import FontProperties
    mplDefined = 1
except:
    pass

mplFigureNumber = 1

class PlotEngineMPL(PlotEngineCommon):
    def __init__(self, testGraph):
        PlotEngineCommon.__init__(self, testGraph)
        self.markers = ["o", "s", "x", "d", "+", "v", "1", "^"]
        # See /usr/lib/python2.2/site-packages/matplotlib/colors.py for more colors.
        self.colors = [ 'blue', 'red', 'green', 'cyan', 'magenta', 'black',
                        'orange', 'lime', 'deepskyblue', 'brown', 'purple', 'gold' ]
        self.lineTypeCounter = -1
    def getNextLineType(self):
        self.lineTypeCounter += 1
        return self.lineTypeCounter
    def parseRangeArg(self, arg, currentLim):
        entries = arg.split(":")
        if len(entries) != 2:
            return currentLim
        new = []
        for ent in [0, 1]:
            if entries[ent]:
                new.append(entries[ent])
            else:
                new.append(currentLim[ent])
        return new
    def getLineSize(self, plotLine):
        if plotLine.plotLineRepresentant:
            return 1.5
        else:
            return 0.75
    def getMarker(self, plotLine):
        if plotLine.plotLineRepresentant:
            return ""
        else:
            return self.markers[int(plotLine.pointType) % len(self.markers)]
    def getLineColor(self, plotLine):
        if plotLine.plotLineRepresentant:
            return self.colors[int(plotLine.plotLineRepresentant.lineType) % len(self.colors)]
        else:
            return self.colors[int(plotLine.lineType) % len(self.colors)]
    def getPlotArgument(self, plotLine):
        return "-" + self.getMarker(plotLine)
    def getPlotSize(self, plotSize):
        if plotSize:
            nums = plotSize.split(",")
            if len(nums) == 2:
                return (nums[0], nums[1])
        else:
            return None
    def createFigure(self, plotSize):
        global mplFigureNumber
        figure(mplFigureNumber, facecolor = 'w', figsize = self.getPlotSize(plotSize))
        mplFigureNumber += 1
        axes(axisbg = '#f6f6f6')
    def showOrSave(self, targetFile, writeDir, printer, printA3):
        if printer:
            targetFile = os.path.join(writeDir, "graph.ps")
        if targetFile:
            if not os.path.isdir(writeDir):
                os.makedirs(writeDir)
            os.chdir(writeDir)
            absTargetFile = os.path.expanduser(targetFile)
            savefig(absTargetFile)
            if printer:
                self.doPrint(printer, printA3, absTargetFile)
        else:
            show()
    def plot(self, writeDir):
        xrange, yrange, targetFile, printer, colour, printA3, onlyAverage, plotPercentage, userTitle, noLegend, onlyLegendAverage, terminal, plotSize = self.testGraph.getPlotOptions()
        self.createFigure(plotSize)
        min = None
        if plotPercentage:
            min = self.testGraph.findMinOverPlotLines()
        self.testGraph.setXAxisScaleAndLabel()
        self.testGraph.deduceLineTypes(self.getNextLineType)

        # The plotlines will be plotted in an indeterministic order
        # if we don't specify the zorder. This is not to affect the
        # apperance of the plot.
        zOrder = 0
        legendLine = []
        legendLabel = []
        for plotLine in self.testGraph.plotLines:
            if not onlyAverage or (onlyAverage and plotLine.plotLineRepresentant):
                 x, y = plotLine.getGraph(self.testGraph.xScaleFactor, min)
                 col = self.getLineColor(plotLine)
                 line = plot(x, y, self.getPlotArgument(plotLine), linewidth = self.getLineSize(plotLine),
                             linestyle = "steps", zorder = zOrder,
                             color = col, markerfacecolor = col, markeredgecolor = 'black')
                 label = self.testGraph.getPlotLineName(plotLine, noLegend, onlyLegendAverage)
                 if label:
                     legendLine.append(line)
                     legendLabel.append(label)
            zOrder += 1
        gca().set_xlim(self.parseRangeArg(xrange, gca().get_xlim()))
        gca().set_ylim(self.parseRangeArg(yrange, gca().get_ylim()))
        grid()
        title(self.testGraph.makeTitle(userTitle))
        if legendLine:
            legend(legendLine, legendLabel,
                   markerscale = 0.6, prop = FontProperties(size='smaller'), labelsep = 0.001) # Added these after migration to RHEL4.
        xlabel(self.testGraph.getXAxisLabel())
        if not plotPercentage:
            ylabel(self.testGraph.getYAxisLabel())
        else:
            ylabel(self.testGraph.getYAxisLabel() + " % above " + str(min))
            
        self.showOrSave(targetFile, writeDir, printer, printA3)

# Class representing ONE curve in plot.
class PlotLine:
    def __init__(self, plotFileName, description, xItem, item, optRun, plotAgainstSolution, scaling):
        self.description = description
        self.lineType = None
        self.pointType = None
        self.axisYLabel = None
        self.plotLineRepresentant = None
        timeScaleFactor = 1.0

        if scaling:
            timeScaleFactor *= scaling
        self.axisYLabel = item
        self.plotFileName = plotFileName 
        self.createGraph(optRun, xItem, item, plotAgainstSolution, timeScaleFactor)
    def getYAxisLabel(self):
        return self.axisYLabel
    def createGraph(self, optRun, xItem, item, plotAgainstSolution, timeScaleFactor):
        self.graph = {}
        self.min = None
        cnt = 0
        for solution in optRun.solutions:
            if solution.has_key(item) and solution.has_key(xItem):
                if cnt > 0 and (self.min == None or self.min > solution[item]):
                    self.min = solution[item]
                if plotAgainstSolution:
                    self.graph[cnt] = solution[item]
                else:
                    self.graph[solution[xItem]*timeScaleFactor] = solution[item]
            cnt = cnt + 1
    def writeFile(self, xScaleFactor, min):
        dir, localName = os.path.split(self.plotFileName)
        if not os.path.isdir(dir):
            os.makedirs(dir)
        plotFile = open(self.plotFileName, "w")
        x, y = self.getGraph(xScaleFactor, min)
        for xx in x:
            yy = y.pop(0)
            plotFile.write(str(xx) + "  " + str(yy) + os.linesep)
        plotFile.close()
    def getGraph(self, xScaleFactor, min):
        xx = self.graph.keys()
        xx.sort()
        yy = []
        xxx = []
        for x in xx:
            if min:
                y = 100.0*float(self.graph[x])/float(min)-100.0
            else:
                y = self.graph[x]
            yy.append(y)
            xxx.append(x*xScaleFactor)
        return xxx, yy

# Create averages of several graphs.
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
        # We will modify graph.
        graphCopy = copy.deepcopy(graph)
        if not self.average:
            self.average = copy.deepcopy(graphCopy)
            if self.minmax:
                self.min = copy.deepcopy(graphCopy)
                self.max = copy.deepcopy(graphCopy)
            return
        graphXValues = graphCopy.keys()
        graphXValues.sort()
        averageXValues = self.average.keys()
        averageXValues.sort()
        mergedVals = self.mergeVals(averageXValues, graphXValues)
        extendedGraph = self.extendGraph(graphCopy, mergedVals)
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
    def writeFile(self, xScaleFactor, min):
        global plotAveragerCount
        self.plotFileName = os.path.join(self.tmpFileDirectory, "average." + str(plotAveragerCount))
        plotAveragerCount += 1
        plotFile = open(self.plotFileName, "w")
        x, y = self.getGraph(xScaleFactor, min)
        for xx in x:
            yy = y.pop(0)
            plotFile.write(str(xx) + " " + str(yy) + os.linesep)
        plotFile.close()
    def getGraph(self, xScaleFactor, min):
        yValues = []
        xx = []
        xValues = self.average.keys()
        xValues.sort()
        for xVal in xValues:
            if min:
                y = 100.0*float(self.average[xVal])/float(self.numberOfGraphs*min)-100.0
            else:
                y = self.average[xVal]/self.numberOfGraphs
            yValues.append(y)
            xx.append(xScaleFactor * xVal)
        return xx, yValues

# End of "PlotTest" functionality.

# Override for webpage generation with generation of weekend page in it
class GenerateWebPages(testoverview.GenerateWebPages):
    def getSelectorClasses(self):
        return testoverview.GenerateWebPages.getSelectorClasses(self) + [ SelectorWeekend ]
    def createTestTable(self):
        return TestTable()

def isWeekend(tag):
    year, month, day, hour, minute, second, wday, yday, dummy = time.strptime(tag, "%d%b%Y")
    return wday == 4

class TestTable(testoverview.TestTable):
    def findTagColour(self, tag):
        if isWeekend(tag):
            return testoverview.colourFinder.htmlColour("red")
        else:
            return testoverview.TestTable.findTagColour(self, tag)

class SelectorWeekend(testoverview.Selector):
    def __init__(self, tags):
        self.selectedTags = filter(isWeekend, tags)
    def getFileNameExtension(self):
        return "_weekend"
    def __repr__(self):
        return "Weekend"
    
class StartStudio(guiplugins.InteractiveTestAction):
    def __init__(self, test):
        guiplugins.InteractiveTestAction.__init__(self, test)
        self.addOption("sys", "Studio CARMSYS to use", self.currentTest.getEnvironment("CARMSYS"))
    def __repr__(self):
        return "Studio"
    def getTitle(self):
        return "Studio"
    def getTabTitle(self):
        return "Studio"
    def getScriptTitle(self, tab):
        return "Start Studio"
    def performOnCurrent(self):
        self.currentTest.setUpEnvironment(parents=1)
        try:
            os.environ["CARMSYS"] = self.optionGroup.getOptionValue("sys")
            print "CARMSYS:", os.environ["CARMSYS"]
            print "CARMUSR:", os.environ["CARMUSR"]
            print "CARMTMP:", os.environ["CARMTMP"]
            fullSubPlanPath = self.currentTest.app.configObject.target._getSubPlanDirName(self.currentTest)
            lPos = fullSubPlanPath.find("LOCAL_PLAN/")
            subPlan = fullSubPlanPath[lPos + 11:]
            localPlan = string.join(subPlan.split(os.sep)[0:-1], os.sep)
            studio = os.path.join(os.environ["CARMSYS"], "bin", "studio")
            if not os.path.isfile(studio):
                raise plugins.TextTestError, "Cannot start studio, no file at " + studio
            commandLine = "exec " + studio + " -w -p'CuiOpenSubPlan(gpc_info,\"" + localPlan + "\",\"" + subPlan + \
                            "\",0)'" + plugins.nullRedirect() 
            process = self.startExternalProgram(commandLine)
            guiplugins.scriptEngine.monitorProcess("runs studio", process)
        finally:
            self.currentTest.tearDownEnvironment(parents=1)

guiplugins.interactiveActionHandler.actionStaticClasses += [ StartStudio ]

class CVSLogInGUI(guiplugins.InteractiveTestAction):
    def __init__(self, dynamic, test):
        guiplugins.InteractiveTestAction.__init__(self, test)
    def performOnCurrent(self):
        logFileStem = self.currentTest.app.getConfigValue("log_file")
        files = [ logFileStem ]
        files += self.currentTest.app.getConfigValue("cvs_log_for_files").split(",")
        cvsInfo = ""
        path = self.currentTest.getDirectory()
        for file in files:
            fileName = self.currentTest.getFileName(file)
            if fileName:
                cvsInfo += self.getCVSInfo(path, os.path.basename(fileName))
        raise  plugins.TextTestError, "CVS Logs" + os.linesep + os.linesep + cvsInfo
    def getTitle(self):
        return "CVS _Log"
    def getCVSInfo(self, path, file):
        info = os.path.basename(file) + ":" + os.linesep
        cvsCommand = "cd " + path + ";cvs log -N -rHEAD " + file
        stdin, stdouterr = os.popen4(cvsCommand)
        cvsLines = stdouterr.readlines()
        if len(cvsLines) > 0:            
            addLine = None
            for line in cvsLines:
                isMinusLine = None
                if line.startswith("-----------------"):
                    addLine = 1
                    isMinusLine = 1
                if line.startswith("================="):
                    addLine = None
                if line.find("nothing known about") != -1:
                    info += "Not CVS controlled"
                    break
                if line.find("No CVSROOT specified") != -1:
                    info += "No CVSROOT specified"
                    break
                if addLine and not isMinusLine:
                    info += line
            info += os.linesep
        return info

guiplugins.interactiveActionHandler.actionPostClasses += [ CVSLogInGUI ]
