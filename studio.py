#
#	Studio plug-in for Texttest framework
#
# This plug-in is derived from the ravebased configuration, to make use of CARMDATA isolation
# and rule compilation, as well as Carmen's SGE queues.
#
# $Header: /carm/2_CVS/Testing/TextTest/Attic/studio.py,v 1.9 2005/11/28 16:41:04 geoff Exp $
#
import ravebased, os, plugins, guiplugins, shutil

def getConfig(optionMap):
    return StudioConfig(optionMap)

class StudioConfig(ravebased.Config):
    def _getLocalPlanPath(self, test):
        # Assumption to avoid reading Carmen Resource system LocalPlanPath
        return os.path.join(ravebased.getCarmdata(), "LOCAL_PLAN")
    def _getSubPlanDirName(self, test):
        subPlan = self._subPlanName(test)
        fullPath = os.path.join(self._getLocalPlanPath(test), subPlan)
        return os.path.normpath(fullPath)
    def getWriteDirectoryPreparer(self):
        return ravebased.PrepareCarmdataWriteDir()
    def getRuleSetName(self, test):
        subplanDir = self._getSubPlanDirName(test)
        headerFile = os.path.join(subplanDir, "subplanHeader")
        origPath = self.findOrigRulePath(headerFile)
        return os.path.basename(origPath)
    def findOrigRulePath(self, headerFile):
        for line in open(headerFile).xreadlines():
            if line.startswith("554"):
                return line.split(";")[22]
        return ""
    def _subPlanName(self, test):
        macroLine = self.getSubPlanLineInMacro(test)
        start = macroLine.find("value=\"")
        end = macroLine.rfind("\"")
        return macroLine[start + 7:end]
    def getSubPlanLineInMacro(self, test):
        macroFile = test.useCaseFile
        if not os.path.isfile(macroFile):
            raise plugins.TextTestError, "Cannot find ruleset name, no macro yet recorded or imported to indicate it!"
        useNext = 0
        for line in open(macroFile).xreadlines():
            if useNext:
                return line
            elif line.find("OPEN_PLAN") != -1:
                useNext = 1
    
# Graphical import suite. Basically the same as those used for optimizers
class ImportTestSuite(ravebased.ImportTestSuite):
    def hasStaticLinkage(self, carmUsr):
        return 0
    def getCarmtmpPath(self, carmtmp):
        return os.path.join("/carm/proj/studio/carmtmps/${MAJOR_RELEASE_ID}/${ARCHITECTURE}", carmtmp)

# Graphical import test
class ImportTestCase(guiplugins.ImportTestCase):
    newMacroString = "<Record new macro>"
    def addDefinitionFileOption(self, suite, oldOptionGroup):
        self.addOption(oldOptionGroup, "mac", "Macro to use", self.newMacroString, self.getExistingMacros(suite))
    def getExistingMacros(self, suite):
        carmUsr = self.getCarmUsr(suite)
        if not carmUsr:
            return []
        path = os.path.join(carmUsr, "macros")
        macros = []
        for userDir in os.listdir(path):
            fullUserDir = os.path.join(path, userDir)
            for macro in os.listdir(fullUserDir):
                macros.append(os.path.join(userDir, macro))
        return macros
    def getCarmUsr(self, suite):
        if suite.environment.has_key("CARMUSR"):
            return suite.environment["CARMUSR"]
        elif suite.parent:
            return self.getCarmUsr(suite.parent)
    def writeDefinitionFiles(self, suite, testDir):
        optionFile = self.getWriteFile("options", suite, testDir)
        optionFile.write("\n")
        macroToImport = self.optionGroup.getOptionValue("mac")
        if macroToImport != self.newMacroString:
            usecaseFile = self.getWriteFileName("usecase", suite, testDir)
            fullMacroPath = os.path.join(self.getCarmUsr(suite), "macros", macroToImport)
            shutil.copyfile(fullMacroPath, usecaseFile)
