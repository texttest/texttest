import carmen, os, sys, string, shutil, KPI, plugins

class OptimizationConfig(carmen.CarmenConfig):
    def getOptionString(self):
        return "k:" + carmen.CarmenConfig.getOptionString(self)
    def getActionSequence(self):
        if self.optionMap.has_key("kpi"):
            return [ CalculateKPI(self.optionValue("kpi")) ]

        return carmen.CarmenConfig.getActionSequence(self)
    def getRuleBuilder(self, neededOnly):
        if self.isNightJob() or not neededOnly:
            return self.getCompileRules(None)
        else:
            localFilter = carmen.UpdatedLocalRulesetFilter(self.getRuleSetName, self.getLibraryFile())
            return self.getCompileRules(localFilter)
    def getCompileRules(self, localFilter):
        return carmen.CompileRules(self.getRuleSetName, "-optimize", localFilter)
    def getTestCollator(self):
        return plugins.CompositeAction([ carmen.CarmenConfig.getTestCollator(self), ExtractSubPlanFile(self, "best_solution", "solution") ])

class ExtractSubPlanFile(plugins.Action):
    def __init__(self, config, sourceName, targetName):
        self.config = config
        self.sourceName = sourceName
        self.targetName = targetName
    def __repr__(self):
        return "Extracting subplan file " + self.sourceName + " to " + self.targetName + " on"
    def __call__(self, test):
        sourcePath = self.config.getSubPlanFileName(test, self.sourceName)
        if os.path.isfile(sourcePath):
            if self.isCompressed(sourcePath):
                targetFile = test.getTmpFileName(self.targetName, "w") + ".Z"
                shutil.copyfile(sourcePath, targetFile)
                os.system("uncompress " + targetFile)
            else:
                targetFile = test.getTmpFileName(self.targetName, "w")
                shutil.copyfile(sourcePath, targetFile)
    def isCompressed(self,path):
        magic = open(path).read(2)
        if magic[0] == chr(0x1f) and magic[1] == chr(0x9d):
            return 1
        else:
            return 0

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
        self.makeLinksIn(tmpDir, os.path.join(dirName, baseName))
    def makeLinksIn(self, inDir, fromDir):
        for file in os.listdir(fromDir):
            if file.find("Solution_") != -1:
                continue
            if file.find("status") != -1:
                continue
            if file.find("hostname") != -1:
                continue
            if file.find("best_solution") != -1:
                continue
            if file != "APC_FILES":
                fromPath = os.path.join(fromDir, file)
                toPath = os.path.join(inDir, file)
                os.symlink(fromPath, toPath)
            else:
                apcFiles = os.path.join(inDir, file)
                os.mkdir(apcFiles)
                self.makeLinksIn(apcFiles, os.path.join(fromDir, file))

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
        prefix = os.path.join(subDir, baseName) + "." + test.app.name
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
            os.rmdir(subDir)

class RemoveTemporarySubplan(plugins.Action):
    def __init__(self, subplanManager):
        self.subplanManager = subplanManager
    def __call__(self, test):
        self.subplanManager.removeTemporary(test)
    def __repr__(self):
        return "Removing temporary subplan for"

class CalculateKPI(plugins.Action):
    def __init__(self, referenceVersion):
        self.referenceVersion = referenceVersion
        self.totalKPI = 0
        self.numberOfValues = 0
    def __del__(self):
        if self.numberOfValues > 0:
            print "Overall average KPI with respect to version", self.referenceVersion, "=", float(self.totalKPI / self.numberOfValues)
        else:
            print "No KPI tests were found with respect to version " + self.referenceVersion
    def __repr__(self):
        return "Calculating KPI for"
    def __call__(self, test):
        currentFile = test.makeFileName("status")
        referenceFile = test.makeFileName("status", self.referenceVersion)
        if currentFile != referenceFile:
            kpiValue = KPI.calculate(referenceFile, currentFile)
            self.describe(test, ", with respect to version " + self.referenceVersion + " - returns " + str(kpiValue))
            self.totalKPI += kpiValue
            self.numberOfValues += 1
    def setUpSuite(self, suite):
        self.describe(suite)

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
            carmUsrDir = self.chooseCarmUsr()
            if carmUsrDir != None:
                open(envPath,"w").write(self.getEnvContent(carmUsrDir) + os.linesep)
    def postText(self):
        return ", User: '" + self.name + "'"
    def getEnvContent(self, carmUsrDir):
        carmTmpDir = carmUsrDir[:-4] + "tmp"
        return "CARMUSR:" + carmUsrDir + os.linesep + "CARMTMP:" + carmTmpDir
    def findCarmUsrFrom(self, fileList):
        for file in fileList:
            if not os.path.isfile(self.filePath(file)):
                continue
            for line in open(self.filePath(file)).xreadlines():
                if line[0:7] == "CARMUSR":
                    return line.split(":")[1].strip()
        return None
    def chooseCarmUsr(self):
        dirName = self.findCarmUsrFrom(self.findStems("environment"))
        while dirName == None:
            print "Please give CARMUSR directory to use for user " + self.userDesc()
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
        if not os.path.isdir(testPath):
            os.mkdir(testPath)
        if not os.path.isfile(optionPath):
            dirName = self.chooseSubPlan()
            if dirName == None:
                return
            subPlanDir = os.path.join(dirName, "APC_FILES")
            ruleSet = self.getRuleSetName(subPlanDir)
            carmUsrSubPlanDirectory = self.replaceCarmUsr(subPlanDir)
            newOptions = self.buildOptions(carmUsrSubPlanDirectory, ruleSet)
            open(optionPath,"w").write(newOptions + os.linesep)
        else:
            carmUsrSubPlanDirectory = self.subPlanFromOptions(optionPath)
        if not os.path.isfile(envPath):
            envContent = self.buildEnvironment(carmUsrSubPlanDirectory)
            open(envPath,"w").write(envContent + os.linesep)
        if not os.path.isfile(perfPath):
            perfContent = self.buildPerformance(carmUsrSubPlanDirectory)
            open(perfPath, "w").write(perfContent + os.linesep)
    def postText(self):
        return ", Test: '" + self.name + "'"
    def subPlanFromOptions(self, optionPath):
        return None
    def buildOptions(self, path, ruleSet):
        return None
    def buildEnvironment(self, carmUsrSubPlanDirectory):
        return None
    def buildPerformance(self, carmUsrSubPlanDirectory):
        return None
    def getRuleSetName(self, subPlanDir):
        problemLines = open(os.path.join(subPlanDir,"problems")).xreadlines()
        for line in problemLines:
            if line[0:4] == "153;":
                return line.split(";")[3]
        return ""
    def replaceCarmUsr(self, path):
        carmUser = os.environ["CARMUSR"]
        if path[0:len(carmUser)] == carmUser:
            return "${CARMUSR}" + os.path.join("/", path[len(carmUser) : len(path)])
        return path
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
                    testInfo.makeImport()
                    self.describe(suite, testInfo.postText())

    def makeUser(self, userInfo, carmUsrDir):
        return 0
    
    def testForImportTestCase(self, testInfo):
        return 0

