import carmen, os, sys, string, shutil, optimization

def getConfig(optionMap):
    return ApcConfig(optionMap)

class ApcConfig(optimization.OptimizationConfig):
    def getLibraryFile(self):
        return os.path.join("data", "apc", carmen.architecture, "libapc.a")
    def getSubPlanFileName(self, test, sourceName):
        return os.path.join(test.options.split()[0], sourceName)
    def getActionSequence(self):
        if self.optionMap.has_key("rulecomp"):
            return [ ApcCompileRules(self.getRuleSetName) ]
        
        staticFilter = carmen.UpdatedLocalRulesetFilter(self.getRuleSetName, self.getLibraryFile())
        return [ ApcCompileRules(self.getRuleSetName, staticFilter) ] + carmen.CarmenConfig.getActionSequence(self)
    def getTestCollator(self):
        return optimization.OptimizationConfig.getTestCollator(self) + [ RemoveLogs(), optimization.ExtractSubPlanFile(self, "status", "status") ]
    def getRuleSetName(self, test):
        fileName = test.makeFileName("options")
        if os.path.isfile(fileName):
            optionLine = open(fileName).readline()
            options = optionLine.split()
            for option in options:
                if option.find("crc/rule_set") != -1:
                    return option.split("/")[-1]
        return None

class ApcCompileRules(carmen.CompileRules):
    def __init__(self, getRuleSetName, filter = None):
        carmen.CompileRules.__init__(self, getRuleSetName, filter)
    def __call__(self, test, description):
        carmTmpDir = os.environ["CARMTMP"]
        if not os.path.isdir(carmTmpDir):
            os.mkdir(carmTmpDir)
        ruleset = carmen.RuleSet(self.getRuleSetName(test), self.raveName)
        if ruleset.isValid() and not ruleset.name in self.rulesCompiled:
            print description + " -  ruleset " + ruleset.name
            ruleset.backup()
            compiler = os.path.join(os.environ["CARMSYS"], "bin", "crc_compile")
            commandLine = compiler + " " + self.raveName + " -optimize -archs " + carmen.architecture + " " + ruleset.sourceFile
            self.rulesCompiled.append(ruleset.name)
            os.system(commandLine)

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

class StartStudio:
    def __repr__(self):
        return "Starting Studio for"
    def __call__(self, test, description):
        print "CARMSYS:", os.environ["CARMSYS"]
        print "CARMUSR:", os.environ["CARMUSR"]
        print "CARMTMP:", os.environ["CARMTMP"]
        commandLine = os.path.join(os.environ["CARMSYS"], "bin", "studio")
        print commandLine
        print os.popen(commandLine)
        sys.exit(0)
    def setUpSuite(self, suite, description):
        pass

class ApcTestCaseInformation(optimization.TestCaseInformation):
    def __init__(self, suite, name):
        optimization.TestCaseInformation.__init__(self, suite, name)
    def ruleSetPath(self):
        return "${CARMTMP}" + os.sep + os.path.join("crc", "rule_set", "APC", "PUTS_ARCH_HERE")
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
       ruleSetFile = self.ruleSetPath() + os.sep + ruleSet
       return subPlan + " " + statusFile + " ${CARMSYS} " + ruleSetFile + " ${USER}"

    def buildEnvironment(self, carmUsrSubPlanDirectory):
        lpEtab = carmUsrSubPlanDirectory.split(os.sep)[0:-2]
        spEtab = carmUsrSubPlanDirectory.split(os.sep)[0:-1]
        lpEtabLine = "LP_ETAB_DIR:" + os.path.normpath(string.join(lpEtab, "/") + "/etable")
        spEtabLine = "SP_ETAB_DIR:" + os.path.normpath(string.join(spEtab, "/") + "/etable")
        return lpEtabLine + os.linesep + spEtabLine

    def buildPerformance(self, subPlanDir):
        statusPath = os.path.join(subPlanDir, "status")
        if os.path.isfile(statusPath):
            lastLines = os.popen("tail -10 " + statusPath).xreadlines()
            for line in lastLines:
                if line[0:5] == "Time:":
                    sec = line.split(":")[1].split("s")[0]
                    return "CPU time   :     " + str(int(sec)) + ".0 sec. on heathlands"
# Give some default that will not end it up in the short queue
        return "CPU time   :      2500.0 sec. on heathlands"
        

class ApcTestSuiteInformation(optimization.TestSuiteInformation):
    def __init__(self, suite, name):
        optimization.TestSuiteInformation.__init__(self, suite, name)
    def getEnvContent(self, carmUsrDir):
        usrContent = "CARMUSR:" + carmUsrDir
        tmpContent = "CARMTMP:${CARMSYS}" + os.sep + self.makeCarmTmpName()
        return usrContent + os.linesep + tmpContent

class ImportTest(optimization.ImportTest):
    def getTestCaseInformation(self, suite, name):
        return ApcTestCaseInformation(suite, name)
    def getTestSuiteInformation(self, suite, name):
        return ApcTestSuiteInformation(suite, name)


class PortApcTest:
    def __repr__(self):
        return "Porting old"
    def __call__(self, test, description):
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
            print description, "in", testInfo.suiteDescription()
    def setUpSuite(self, suite, description):
        self.suite = suite


        
            
