import carmen, os, sys, shutil, KPI

class OptimizationConfig(carmen.CarmenConfig):
    def getOptionString(self):
        return "k:" + carmen.CarmenConfig.getOptionString(self)
    def getActionSequence(self):
        if self.optionMap.has_key("kpi"):
            return [ CalculateKPI(self.optionValue("kpi")) ]
        if self.optionMap.has_key("rulecomp"):
            return carmen.CarmenConfig.getActionSequence(self)
        
        staticFilter = carmen.UpdatedLocalRulesetFilter(self.getRuleSetName, self.getLibraryFile())
        return [ carmen.CompileRules(self.getRuleSetName, staticFilter) ] + carmen.CarmenConfig.getActionSequence(self)
    def getTestCollator(self):
        return carmen.CarmenConfig.getTestCollator(self) + [ ExtractSubPlanFile(self, "best_solution", "solution") ]

class ExtractSubPlanFile:
    def __init__(self, config, sourceName, targetName):
        self.config = config
        self.sourceName = sourceName
        self.targetName = targetName
    def __repr__(self):
        return "Extracting subplan file " + self.sourceName + " to " + self.targetName + " on"
    def __call__(self, test, description):
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
    def setUpSuite(self, suite, description):
        pass


class CalculateKPI:
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
    def __call__(self, test, description):
        currentFile = test.makeFileName("status")
        referenceFile = test.makeFileName("status", self.referenceVersion)
        if currentFile != referenceFile:
            kpiValue = KPI.calculate(referenceFile, currentFile)
            print description + ", with respect to version", self.referenceVersion, "- returns", kpiValue
            self.totalKPI += kpiValue
            self.numberOfValues += 1
    def setUpSuite(self, suite, description):
        print description

class TestSuiteInformation:
    def __init__(self, suite, name):
        self.suite = suite
        self.name = name
    def testPath(self):
        return os.path.join(self.suite.abspath, self.name)
    def filePath(self, file):
        return os.path.join(self.suite.abspath, self.name, file)
    def absPathToCarmSys(self):
        return os.path.join(self.suite.app.checkout, self.suite.environment["CARMSYS"])
    def findCarmUsrFrom(self, fileList):
        for file in fileList:
            if not os.path.isfile(self.filePath(file)):
                continue
            for line in open(self.filePath(file)).xreadlines():
                if line[0:7] == "CARMUSR":
                    return line.split(":")[1].strip()
        return None
    def chooseCarmUsr(self):
        dirName = self.findCarmUsrFrom(["environment.apc", "environment"])
        while dirName == None:
            print "Please give CARMUSR directory to use for new user '" + self.name + "'"
            dirName = sys.stdin.readline().strip();
            if not os.path.isdir(dirName):
                print "Not found: '" + dirName + "'"
                dirName = None
        return dirName
    def makeFileName(self, stem, version = None):
        return self.suite.makeFileName(self.name + os.sep + stem, version)
    def makeCarmTmpName(self):
        asFileName = self.suite.makeFileName("__tmp__")
        suffix = asFileName.replace(os.path.join(self.suite.abspath, "__tmp__"), "")
        return self.name + "_tmp" + suffix
        
class TestCaseInformation:
    def __init__(self, suite, name):
        self.suite = suite
        self.name = name
    def testPath(self):
        return os.path.join(self.suite.abspath, self.name)
    def getRuleSetName(self, subPlanDir):
        problemLines = open(os.path.join(subPlanDir,"problems")).xreadlines()
        for line in problemLines:
            if line[0:4] == "153;":
                return line.split(";")[3]
        return ""
    def replaceCarmUsr(self, path):
        carmUser = os.environ["CARMUSR"]
        if path[0:len(carmUser)] == carmUser:
            return "${CARMUSR}/" + path[len(carmUser) : len(path)]
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

class ImportTest:
    def __repr__(self):
        return "Importing into"
    def __call__(self, test, description):
        pass

    def isUserSuite(self, suite):
        return suite.environment.has_key("CARMUSR")

    def userSuiteComplete(self, userInfo, carmTmpDirInCarmSys):
        if not os.path.isdir(carmTmpDirInCarmSys):
            return 0
        if not os.path.isdir(userInfo.testPath()):
            return 0
        if not os.path.isfile(userInfo.makeFileName("testsuite")):
            return 0
        if not os.path.isfile(userInfo.makeFileName("environment")):
            return 0
        return 1
    
    def setUpSuite(self, suite, description):
        if self.isUserSuite(suite):
            for testline in open(suite.testCaseFile).readlines():
                if testline != '\n' and testline[0] != '#':
                    testInfo = TestCaseInformation(suite, testline.strip())
                    if self.testForImportTestCase(testInfo) != 0:
                        print description + ", Test: '" + testInfo.name + "'"
        else:
            for testline in open(suite.testCaseFile).readlines():
                if testline != '\n' and testline[0] != '#':
                    userInfo = TestSuiteInformation(suite, testline.strip())
                    if self.testForImportTestSuite(userInfo) != 0:
                        print description + ", User: '" + userInfo.name + "'"

    def testForImportTestSuite(self, userInfo):
        if not userInfo.suite.environment.has_key("CARMSYS"):
            return 0
        carmTmpDirInCarmSys = os.path.join(userInfo.absPathToCarmSys(), userInfo.makeCarmTmpName())
        if self.userSuiteComplete(userInfo, carmTmpDirInCarmSys):
            return 0
        envPath = userInfo.makeFileName("environment")
        if not os.path.isfile(envPath):
            carmUsrDir = userInfo.chooseCarmUsr()
        else:
            carmUsrDir = None
        if carmUsrDir != None or os.path.isfile(envPath):
            return self.makeUser(userInfo, carmUsrDir, carmTmpDirInCarmSys)
        return 0

    def makeUser(self, userInfo, carmUsrDir, carmTmpDirInCarmSys):
        return 0
    
    def testForImportTestCase(self, testInfo):
        return 0
