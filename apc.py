import default, carmen, lsf, os, sys, stat, string, shutil, optimization, plugins

def getConfig(optionMap):
    return ApcConfig(optionMap)

class ApcConfig(optimization.OptimizationConfig):
    def __init__(self, optionMap):
        optimization.OptimizationConfig.__init__(self, optionMap)
        self.subplanManager = ApcSubPlanDirManager(self)
    def getLibraryFile(self):
        return os.path.join("data", "apc", carmen.architecture, "libapc.a")
    def getSubPlanFileName(self, test, sourceName):
        return self.subplanManager.getSubPlanFileName(test, sourceName)
    def _getTestRunner(self):
        if self.optionMap.has_key("l"):
            return ApcRunTest(self.subplanManager)
        else:
            return ApcSubmitTest(self.subplanManager, self.findLSFQueue, self.optionValue("R"))
    def getTestRunner(self):
        if self.optionMap.has_key("lprof"):
            subActions = [ self._getTestRunner(), carmen.WaitForDispatch(), carmen.RunLProf() ]
            return plugins.CompositeAction(subActions)
        else:
            return self._getTestRunner()
    def getCompileRules(self, staticFilter):
        libFile = self.getLibraryFile()
        ruleCompile = self.optionMap.has_key("rulecomp")
        return ApcCompileRules(self.getRuleSetName, libFile, staticFilter, ruleCompile)
    def getTestCollator(self):
        subActions = [ optimization.OptimizationConfig.getTestCollator(self) ]
        subActions.append(RemoveLogs())
        subActions.append(optimization.ExtractSubPlanFile(self, "status", "status"))
        subActions.append(RemoveTemporarySubplan(self.subplanManager))
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

class ApcSubPlanDirManager:
    def __init__(self, config):
        self.config = config
        self.tmpDirs = {}
    def getSubPlanFileName(self, test, sourceName):
        if not self.tmpDirs.has_key(test):
            return os.path.join(test.options.split()[0], sourceName)
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
        self.removeDir(self.tmpDirs[test])
    def getExecuteCommand(self, test):
        self.makeTemporary(test)
        binary = test.app.getExecuteCommand()
        options = test.options.split(" ")
        tmpDir = self.tmpDirs[test]
        dirName = os.path.join(self.getSubPlanDirName(test), self.getSubPlanBaseName(test))
        dirName = os.path.normpath(dirName)
        options[0] = os.path.normpath(options[0]).replace(dirName, tmpDir)
        options[1] = os.path.normpath(options[1]).replace(dirName, tmpDir)
        return binary + " " + string.join(options, " ")
    def getSubPlanDirName(self, test):
        dirs = os.path.expandvars(test.options.split()[1]).split(os.sep)[:-3]
        return os.path.normpath(string.join(dirs, os.sep))
    def getSubPlanBaseName(self, test):
        baseName = test.options.split()[1].split(os.sep)[-3]
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
                    self.removeDir(os.path.join(subDir, file))
        return dirName
    def removeDir(self, subDir):
        for file in os.listdir(subDir):
            fpath = os.path.join(subDir,file)
            try:
                # if softlinked dir, remove as file and do not recurse
                os.remove(fpath) 
            except:
                self.removeDir(fpath)
        try:
            os.remove(subDir)
        except:
            os.rmdir(subDir)
    
class ApcRunTest(default.RunTest):
    def __init__(self, subplanManager):
        self.subplanManager = subplanManager
    def getExecuteCommand(self, test):
        return self.subplanManager.getExecuteCommand(test)

class ApcSubmitTest(lsf.SubmitTest):
    def __init__(self, subplanManager, queueFunction, resource = ""):
        lsf.SubmitTest.__init__(self, queueFunction, resource)
        self.subplanManager = subplanManager
    def getExecuteCommand(self, test):
        return self.subplanManager.getExecuteCommand(test)

class RemoveTemporarySubplan(plugins.Action):
    def __init__(self, subplanManager):
        self.subplanManager = subplanManager
    def __call__(self, test):
        self.subplanManager.removeTemporary(test)
    def __repr__(self):
        return "Removing temporary subplan for"


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
        ruleLib = self.getRuleLib(ruleset.name)
        if self.isNewer(apcExecutable, self.apcLib):
            return
        self.describe(test, " -  ruleset " + ruleset.name)
        ruleset.backup()
        if not os.path.isfile(ruleLib):
            compiler = os.path.join(os.environ["CARMSYS"], "bin", "crc_compile")
            returnValue = os.system(self.ruleCompileCommand(ruleset.sourceFile))
            if returnValue:
                raise "Failed to build ruleset, exiting"
        commandLine = "g++ -pthread " + self.linkLibs(self.apcLib, ruleLib) + "-o " + apcExecutable
        si, so, se = os.popen3(commandLine)
        lastErrors = se.readlines()
        if len(lastErrors) > 0:
            if lastErrors[-1].find("exit status") != -1:
                print "Building", ruleset.name, "failed!"
                for line in lastErrors:
                    print "   ", line.strip()
                return
        self.rulesCompiled.append(ruleset.name)

    def getRuleLib(self, ruleSetName):
        optArch = carmen.architecture + "_opt"
        ruleLib = ruleSetName + ".a"
        return os.path.join(os.environ["CARMTMP"], "compile", self.raveName.upper(), optArch, ruleLib)
        
    def ruleCompileCommand(self, sourceFile):
       compiler = os.path.join(os.environ["CARMSYS"], "bin", "crc_compile")
       params = " -optimize -makelib -archs " + carmen.architecture
       return compiler + " " + self.raveName + params + " " + sourceFile
                    
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
        os.remove(test.getTmpFileName(stem, "r"))
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


        
            
