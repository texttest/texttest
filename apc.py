import carmen, os, string, shutil, optimization

def getConfig(optionMap):
    return ApcConfig(optionMap)

class ApcConfig(optimization.OptimizationConfig):
    def getLibraryFile(self):
        return os.path.join("data", "apc", carmen.architecture, "libapc.a")
    def getSubPlanFileName(self, test, sourceName):
        return os.path.join(test.options.split()[0], sourceName)
    def getTestCollator(self):
        return optimization.OptimizationConfig.getTestCollator(self) + [ RemoveLogs(), optimization.ExtractSubPlanFile(self, "status", "status") ]
    def getRuleSetName(self, test):
        fileName = test.makeFileName("options")
        if os.path.isfile(fileName):
            optionLine = open(fileName).readline()
            options = optionLine.split();
            for option in options:
                if option.find("crc/rule_set") != -1:
                    return option.split("/")[-1]
        return None

class RemoveLogs:
    def __repr__(self):
        return "Removing log files for"
    def __call__(self, test, description):
        self.removeFile(test, "errors")
        self.removeFile(test, "output")
    def removeFile(self, test, stem):
        os.remove(test.getTmpFileName(stem, "r"))
    def setUpSuite(self, suite, description):
        pass


class ImportTest(optimization.ImportTest):
    def ruleSetPath(self):
        return "${CARMTMP}" + os.sep + os.path.join("crc", "rule_set", "APC", "i386_linux")

    def buildApcOptions(self, path, ruleSet):
       subPlan = path
       statusFile = path + os.sep + "run_status"
       ruleSetFile = self.ruleSetPath() + os.sep + ruleSet
       return subPlan + " " + statusFile + " ${CARMSYS} " + ruleSetFile + " ${USER}"

    def buildApcEnvironment(self, carmUsrSubPlanDirectory):
        lpEtab = carmUsrSubPlanDirectory.split(os.sep)[0:-2]
        spEtab = carmUsrSubPlanDirectory.split(os.sep)[0:-1]
        lpEtabLine = "LP_ETAB_DIR:" + os.path.normpath(string.join(lpEtab, "/") + "/etable")
        spEtabLine = "SP_ETAB_DIR:" + os.path.normpath(string.join(spEtab, "/") + "/etable")
        return lpEtabLine + os.linesep + spEtabLine

    def makeUser(self, userInfo, carmUsrDir, carmTmpDirInCarmSys):
        if not os.path.isdir(userInfo.testPath()):
            os.mkdir(userInfo.testPath())
        if not os.path.isdir(carmTmpDirInCarmSys):
            os.mkdir(carmTmpDirInCarmSys)
        if carmUsrDir != None:
            usrContent = "CARMUSR:" + carmUsrDir
            tmpContent = "CARMTMP:${CARMSYS}" + os.sep + userInfo.makeCarmTmpName()
            envContent = usrContent + os.linesep + tmpContent
            open(os.path.join(userInfo.testPath(), "environment.apc"),"w").write(envContent + os.linesep)
        suitePath = os.path.join(userInfo.testPath(), "testsuite.apc")
        if not os.path.isfile(suitePath):
            suiteContent = "# Tests for user " + userInfo.name + os.linesep + "#"
            open(suitePath, "w").write(suiteContent + os.linesep)
        return 1
            
    def testForImportTestCase(self, testInfo):
        testPath = testInfo.testPath()
        optionPath = os.path.join(testPath, "options.apc")
        suitePath = os.path.join(testPath, "testsuite.apc")
        if os.path.isdir(testPath) and (os.path.isfile(optionPath) or os.path.isfile(suitePath)):
            return 0
        dirName = testInfo.chooseSubPlan()
        if dirName != None:
            return self.makeImport(testInfo, dirName)
        return 0

    def makeImport(self, testInfo, dirName):
        if not os.path.isdir(testInfo.testPath()):
            os.mkdir(testInfo.testPath())
        subPlanDir = os.path.join(dirName, "APC_FILES")
        ruleSet = testInfo.getRuleSetName(subPlanDir)
        carmUsrSubPlanDirectory = testInfo.replaceCarmUsr(subPlanDir)
        newOptions = self.buildApcOptions(carmUsrSubPlanDirectory, ruleSet)
        optionFile = open(os.path.join(testInfo.testPath(), "options.apc"),"w")
        optionFile.write(newOptions + os.linesep)
        envContent = self.buildApcEnvironment(carmUsrSubPlanDirectory)
        open(os.path.join(testInfo.testPath(), "environment.apc"),"w").write(envContent + os.linesep)
        return 1
            
