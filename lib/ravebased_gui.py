
import default_gui, os
from guiplugins import guilog

# Graphical import suite
class ImportTestSuite(default_gui.ImportTestSuite):
    def getEnvironment(self, envVar):
        if self.currentTest:
            return self.currentTest.getEnvironment("CARMUSR", "")
        else:
            return ""
    def addEnvironmentFileOptions(self):
        usr = self.getEnvironment("CARMUSR")
        dta = self.getEnvironment("CARMDATA")
        if dta == usr:
            dta = ""
        if dta and usr:
            try:
                rdta = os.path.realpath(dta)
                rusr = os.path.realpath(usr)
                if rdta.startswith(rusr):
                    dta=""
            except:
                    dta=""
        self.optionGroup.addOption("usr", "CARMUSR", usr)
        self.optionGroup.addOption("data", "CARMDATA (only if different)", dta)
    def updateOptionGroup(self, state):
        defaultgui.ImportTestSuite.updateOptionGroup(self, state)
        self.optionGroup.setOptionValue("usr", "")
        self.optionGroup.setOptionValue("data", "")
    def getCarmValue(self, val):
        optionVal = self.optionGroup.getOptionValue(val)
        if optionVal:
            return os.path.normpath(optionVal)
    def hasStaticLinkage(self, carmUsr):
        return 1
    def openFile(self, fileName):
        guilog.info("Writing file " + os.path.basename(fileName))
        return open(fileName, "w")
    def setEnvironment(self, suite, file, var, value):
        suite.setEnvironment(var, value)
        line = var + ":" + value
        file.write(line + "\n")
        guilog.info(line)
    def getCarmtmpDirName(self, carmUsr):
        # Important not to get basename clashes - this can lead to isolation problems
        baseName = os.path.basename(carmUsr)
        if baseName.find("_user") != -1:
            return baseName.replace("_user", "_tmp")
        else:
            return baseName + "_tmp"
    def getEnvironmentFileName(self, suite):
        return "environment." + suite.app.name
    def writeEnvironmentFiles(self, suite):
        carmUsr = self.getCarmValue("usr")
        if not carmUsr:
            return
        envFile = os.path.join(suite.getDirectory(), self.getEnvironmentFileName(suite))
        file = self.openFile(envFile)
        self.setEnvironment(suite, file, "CARMUSR", carmUsr)
        carmData = self.getCarmValue("data")
        if carmData:
            self.setEnvironment(suite, file, "CARMDATA", carmData)
        carmtmp = self.getCarmtmpDirName(carmUsr)
        if self.hasStaticLinkage(carmUsr):
            self.setEnvironment(suite, file, "CARMTMP", "$CARMSYS/" + carmtmp)
            return

        self.setEnvironment(suite, file, "CARMTMP", self.getCarmtmpPath(carmtmp))
        self.cacheCarmusrInfo(suite, file)
        envLocalFile = os.path.join(suite.getDirectory(), "environment.local")
        localFile = self.openFile(envLocalFile)
        self.setEnvironment(suite, localFile, "CARMTMP", "$CARMSYS/" + carmtmp)
    def getCarmtmpPath(self, carmtmp):
        pass
    def cacheCarmusrInfo(self, suite, file):
        pass # Used by studio module for default rulesets
    # getCarmtmpPath implemented by subclasses
