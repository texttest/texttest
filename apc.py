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

helpScripts = """
apc.ImportTest             - Import new test cases and test users.
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

apc.StartStudio            - Start ${CARMSYS}/bin/studio with CARMUSR and CARMTMP set for specific test
                             This is intended to be used on a single specified test and will terminate
                             the testsuite after it starts Studio. It is a simple shortcut to set the
                             correct CARMSYS etc. environment variables for the test and run Studio.
"""

import default, carmen, lsf, performance, os, sys, stat, string, shutil, optimization, plugins

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
       return compiler + " -" + self.raveName + params + " " + sourceFile
                    
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

class MakeProgressReport(optimization.MakeProgressReport):
    def __init__(self, referenceVersion):
        optimization.MakeProgressReport.__init__(self, referenceVersion)
    def compare(self, test, referenceFile, currentFile):
        try:
            margin = float(test.app.getConfigValue("kpi_cost_margin"))
        except:
            margin = 0.0
        refMaxMemory, referenceCosts, refTimes = getSolutionStatistics(referenceFile, " TOTAL cost", margin)
        currentMaxMemory, currentCosts, curTimes = getSolutionStatistics(currentFile, " TOTAL cost", margin)
        currPerf = int(performance.getTestPerformance(test))
        refPerf = int(performance.getTestPerformance(test, self.referenceVersion))
        currTTWC = currPerf
        refTTWC = refPerf
        if currentCosts[-1] < referenceCosts[-1]:
            currTTWC = self.timeToCostFromTimes(curTimes, currPerf, currentCosts, referenceCosts[-1])
            refTTWC = refTimes[-1]
        else:
            refTTWC = self.timeToCostFromTimes(refTimes, refPerf, referenceCosts, currentCosts[-1])
            currTTWC = curTimes[-1]
        if float(refTTWC) < 1:
            return
        kpi = float(currTTWC) / float(refTTWC)
        self.testCount += 1
        self.kpi *= kpi
        userName = os.path.normpath(os.environ["CARMUSR"]).split(os.sep)[-1]
        print os.linesep, "Comparison on", test.app, "test", test.name, "(in user " + userName + ") : K.P.I. = " + self.percent(kpi)
        self.reportLine("                         ", "Current", "Version " + self.referenceVersion)
        self.reportLine("Initial cost of plan     ", currentCosts[0], referenceCosts[0])
        self.reportLine("Final cost of plan       ", currentCosts[-1], referenceCosts[-1])
        self.reportLine("Memory used (Mb)         ", currentMaxMemory, refMaxMemory)
        self.reportLine("Total time (minutes)     ", currPerf, refPerf)
        self.reportLine("Time to worst cost (mins)", int(currTTWC), int(refTTWC))
    def getCosts(self, file, type):
        costCommand = "grep '" + type + "' " + file + " | awk '{ print $3 }'"
        return map(self.makeInt, os.popen(costCommand).readlines())


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

def convertTime(timeEntry):
    entries = timeEntry.split(":")
    timeInSeconds = int(entries[0]) * 3600 + int(entries[1]) * 60 + int(entries[2].strip())
    return float(timeInSeconds) / 60.0

def filterLastCosts(costs, times, margin):
    if margin == 0.0 or len(costs) < 3:
        return costs, times
    
    lastCost = costs[-1]
    for ix in range(len(costs) - 2):
        cost = costs[-1 * (ix + 2)]
        diff = abs(cost - lastCost)
        if (1.0 * diff / lastCost) * 100.0 > margin:
            if ix == 0:
                return costs, times
            else:
                return costs[:-1 * ix], times[:-1 * ix]
    return costs[0:2], times[0:2]
    
def getSolutionStatistics(currentFile, statistics, margin = 0.0):
    grepCommand = "grep -E 'memory|" + statistics + "|cpu time' " + currentFile
    grepLines = os.popen(grepCommand).readlines()
    costs = []
    times = []
    lastTime = 0
    maxMemory = 0.0
    for line in grepLines:
        if line.startswith("Time:"):
            parts = line.split()
            if parts[-1].startswith("Mb"):
                mem = float(parts[-2])
                if mem > maxMemory:
                    maxMemory = mem
        if line.startswith("Total time"):
            lastTime = convertTime(line.split()[-1])
        if line.startswith(statistics):
            costs.append(int(line.split()[-1]))
            times.append(lastTime)
    costs, times = filterLastCosts(costs, times, margin)
    return maxMemory, costs, times

class PlotApcTest(plugins.Action):
    def __init__(self, args = ["0:"]):
        self.plotFiles = []
        self.statusFileName = None
        self.plotItem = " " + "TOTAL cost"
        self.plotrange = "0:"
        self.plotPrint = []
        self.plotUseTmpStatus = "t"
        self.plotAgainstSolNum = []
        for ar in args:
            arr = ar.split("=")
            if arr[0]=="r":
                self.plotrange = arr[1]
            elif arr[0]=="p":
                self.plotPrint = arr[1]
            elif arr[0]=="i":
                self.plotItem = " " + arr[1].replace("_"," ")
            elif arr[0]=="nt":
                self.plotUseTmpStatus = []
            elif arr[0]=="s":
                self.plotAgainstSolNum = "t"
            else:
                print "Unknown option " + arr[0]
    def __repr__(self):
        return "Plotting"
    def __del__(self):
        if len(self.plotFiles) > 0:
            stdin, stdout, stderr = os.popen3("gnuplot -persist")
            fileList = []
            style = " with linespoints"
            for file in self.plotFiles:
                title = " title \"" + file.split(os.sep)[-2] + "_" + self.plotItem.strip().replace(" ","_") + "\" "
                fileList.append("'" + file + "' " + title + style)
#            print "plot " + string.join(fileList, ",") + os.linesep
            if self.plotPrint:
                absplotPrint = os.path.expanduser(self.plotPrint)
                if not os.path.isabs(absplotPrint):
                    print "An absolute path must be given."
                    return
                stdin.write("set terminal postscript" + os.linesep)
            stdin.write("set xrange [" + self.plotrange +"];" + os.linesep)
            stdin.write("plot " + string.join(fileList, ",") + os.linesep)
            stdin.write("quit" + os.linesep)
            if self.plotPrint:
                stdin.close()
                tmppf = stdout.read()
                if len(tmppf) > 0:
                    open(absplotPrint,"w").write(tmppf)
                    
    def __call__(self, test):
        currentFile = findTemporaryStatusFile(test)
        if self.plotUseTmpStatus and currentFile:
            print "Using status file in temporary subplan directory for plotting test " + test.name
        else:
            currentFile = test.makeFileName(self.statusFileName)
            if not os.path.isfile(currentFile):
                print "No status file does exist for test " + test.name
                return
        maxMem, costs, times = getSolutionStatistics(currentFile,self.plotItem)
        plotFileName = test.makeFileName("plot")
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

class GrepApcLog(plugins.Action):
    def __init__(self):
        pass
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
            Command = "rsh " + machine + " 'cd /tmp/*" + test.name + "*; egrep \"(heuristic subselection|unfixvars time|focussing|Solv|OBJ|LBD|\*\*\*)\" apclog'" 
            grepLines = os.popen(Command).read()
            print grepLines
    def setUpSuite(self, suite):
        pass
    def setUpApplication(self, app):
        pass
        
def findTemporaryStatusFile(test):
    foundoutputfile = 0
    for file in os.listdir(test.abspath):
        if file.startswith("output") and file.find(test.getTestUser()) != -1:
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
