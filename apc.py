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

class PortApcTest:
    def __repr__(self):
        return "Porting old test"
    def __call__(self, test, description):
        if test.options[0] == "-":
            print description
            subPlanDirectory = test.options.split()[3]
            carmUsrSubPlanDirectory = self.replaceCarmUsr(subPlanDirectory)
            ruleSetName = self.getRuleSetName(subPlanDirectory)
            newOptions = self.buildApcOptions(carmUsrSubPlanDirectory, ruleSetName)
            fileName = test.makeFileName("options")
            shutil.copyfile(fileName, fileName + ".oldts")
            os.remove(fileName)
            optionFile = open(fileName,"w")
            optionFile.write(newOptions + "\n")
        else:
            subPlanDirectory = test.options.split()[0]
            carmUsrSubPlanDirectory = self.replaceCarmUsr(subPlanDirectory)
        envFileName = test.makeFileName("environment")
        if not os.path.isfile(envFileName):
            lpEtab = carmUsrSubPlanDirectory.split(os.sep)[0:-2]
            spEtab = carmUsrSubPlanDirectory.split(os.sep)[0:-1]
            envFile = open(envFileName,"w")
            envFile.write("LP_ETAB_DIR:" + os.path.normpath(string.join(lpEtab, "/") + "/etable\n"))
            envFile.write("SP_ETAB_DIR:" + os.path.normpath(string.join(spEtab, "/") + "/etable\n"))

    def buildApcOptions(self, path, ruleSet):
       subPlan = path
       statusFile = path + os.sep + "run_status"
       ruleSetFile = self.ruleSetPath() + os.sep + ruleSet
       return subPlan + " " + statusFile + " ${CARMSYS} " + ruleSetFile + " ${USER}"
    def getRuleSetName(self, subPlanDir):
        problemLines = open(os.path.join(subPlanDir,"problems")).xreadlines()
        for line in problemLines:
            if line[0:4] == "153;":
                return line.split(";")[3]
        return ""
    def ruleSetPath(self):
        return "${CARMTMP}" + os.sep + os.path.join("crc", "rule_set", "APC", "i386_linux")
    def replaceCarmUsr(self, path):
        carmUser = os.environ["CARMUSR"]
        if path[0:len(carmUser)] == carmUser:
            return "${CARMUSR}/" + path[len(carmUser) : len(path)]
        return path
                
    def setUpSuite(self, suite, description):
        print description

