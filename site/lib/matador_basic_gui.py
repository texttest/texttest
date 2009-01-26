
import optimization_gui, default_gui, ravebased, os, shutil

class ImportTestCase(optimization_gui.ImportTestCase):
    def getOptions(self, suite):
        return "-s " + self.getSubplanName()

    def writeResultsFiles(self, suite, testDir):
        carmdataVar, carmdata = ravebased.getCarmdata(suite)
        subPlanPath = os.path.join(carmdata, "LOCAL_PLAN", self.getSubplanName(), "APC_FILES")
        self.copyFile(testDir, "output." + suite.app.name, subPlanPath, "matador.log")
        self.copyFile(testDir, "errors." + suite.app.name, subPlanPath, "sge.log")

    def copyFile(self, testDir, ttName, subPlan, name):
        sourceFile = os.path.join(subPlan, name)
        if os.path.isfile(sourceFile):
            targetFile = os.path.join(testDir, ttName)
            if not os.path.isfile(targetFile):
                shutil.copyfile(sourceFile, targetFile)


class InteractiveActionConfig(optimization_gui.InteractiveActionConfig):
    def getReplacements(self):
        return { default_gui.ImportTestCase : ImportTestCase } 
