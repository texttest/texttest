#
#	Studio plug-in for Texttest framework
#
# This plug-in is derived from the ravebased configuration, to make use of CARMDATA isolation
# and rule compilation, as well as Carmen's SGE queues.
#
# $Header: /carm/2_CVS/Testing/TextTest/Attic/studio.py,v 1.12 2005/11/29 16:46:16 geoff Exp $
#
import ravebased, os, plugins, guiplugins, shutil

def getConfig(optionMap):
    return StudioConfig(optionMap)

class StudioConfig(ravebased.Config):
    def addToOptionGroups(self, app, groups):
        ravebased.Config.addToOptionGroups(self, app, groups)
        for group in groups:
            if group.name.startswith("Invisible"):
                group.addOption("rset", "Private: used for submitting ruleset compilation along with recording")
    def getWriteDirectoryPreparer(self, ignoreCatalogues):
        return ravebased.PrepareCarmdataWriteDir(ignoreCatalogues)
    def getRuleSetName(self, test):
        if self.optionMap.has_key("rset"):
            return self.optionMap["rset"]
        subplanDir = self._getSubPlanDirName(test)
        if not subplanDir:
            return ""
        headerFile = os.path.join(subplanDir, "subplanHeader")
        origPath = self.findOrigRulePath(headerFile)
        return os.path.basename(origPath)
    def findOrigRulePath(self, headerFile):
        for line in open(headerFile).xreadlines():
            if line.startswith("554"):
                return line.split(";")[22]
        return ""
    def filesFromSubplan(self, test, subplanDir):
        rulesFile = os.path.join(subplanDir, "subplanRules")
        if not os.path.isfile(rulesFile):
            return []

        return [ ("Subplan", rulesFile ) ]
    def _subPlanName(self, test):
        macroLine = self.getSubPlanLineInMacro(test)
        if not macroLine:
            return
        start = macroLine.find("value=\"")
        end = macroLine.rfind("\"")
        return macroLine[start + 7:end]
    def getSubPlanLineInMacro(self, test):
        macroFile = test.useCaseFile
        if not os.path.isfile(macroFile):
            return
        useNext = 0
        for line in open(macroFile).xreadlines():
            if useNext:
                return line
            elif line.find("OPEN_PLAN") != -1:
                useNext = 1
    
# Graphical import suite. Basically the same as those used for optimizers
class ImportTestSuite(ravebased.ImportTestSuite):
    def hasStaticLinkage(self, carmUsr):
        return False
    def getCarmtmpPath(self, carmtmp):
        return os.path.join("/carm/proj/studio/carmtmps/${MAJOR_RELEASE_ID}/${ARCHITECTURE}", carmtmp)

def getCarmUsr(suite):
    if suite.environment.has_key("CARMUSR"):
        return suite.environment["CARMUSR"]
    elif suite.parent:
        return getCarmUsr(suite.parent)

# Graphical import test
class ImportTestCase(guiplugins.ImportTestCase):
    newMacroString = "<Record new macro>"
    def addDefinitionFileOption(self, suite, oldOptionGroup):
        self.addOption(oldOptionGroup, "mac", "Macro to use", self.newMacroString, self.getExistingMacros(suite))
    def getExistingMacros(self, suite):
        carmUsr = getCarmUsr(suite)
        if not carmUsr:
            return []
        path = os.path.join(carmUsr, "macros")
        macros = []
        for userDir in os.listdir(path):
            fullUserDir = os.path.join(path, userDir)
            for macro in os.listdir(fullUserDir):
                macros.append(os.path.join(userDir, macro))
        return macros
    def writeDefinitionFiles(self, suite, testDir):
        optionFile = self.getWriteFile("options", suite, testDir)
        optionFile.write("\n")
        macroToImport = self.optionGroup.getOptionValue("mac")
        if macroToImport != self.newMacroString:
            usecaseFile = self.getWriteFileName("usecase", suite, testDir)
            fullMacroPath = os.path.join(getCarmUsr(suite), "macros", macroToImport)
            shutil.copyfile(fullMacroPath, usecaseFile)

class RecordTest(guiplugins.RecordTest):
    def __init__(self, test, oldOptionGroup):
        guiplugins.RecordTest.__init__(self, test, oldOptionGroup)
        if self.canPerformOnTest():
            self.addOption(oldOptionGroup, "rset", "Compile this ruleset first", possibleValues=self.findRuleSets(test))
    def findRuleSets(self, test):
        carmUsr = getCarmUsr(test)
        if not carmUsr:
            return []
        sourceDir = os.path.join(carmUsr, "crc", "source")
        if os.path.isdir(sourceDir):
            return filter(self.isRuleSource, os.listdir(sourceDir))
        else:
            return []
    def isRuleSource(self, fileName):
        return not fileName.startswith(".")
    def getRunOptions(self, test, usecase):
        basicOptions = guiplugins.RecordTest.getRunOptions(self, test, usecase)
        ruleset = self.optionGroup.getOptionValue("rset")
        if usecase == "record":
            # We want the dynamic GUI up for recording, so we can see what we create
            basicOptions = basicOptions.replace("-o ", "-g ")
            if ruleset:
                return "-rulecomp -rset " + ruleset + " " + basicOptions
        return basicOptions
    # We want to generate a second auto-replay...
    def setTestReady(self, test, usecase=""):
        if usecase == "replay":
            self.startTextTestProcess(test, usecase="replay2")
            test.state.freeText = "First auto-replay completed - second now in progress to collect standard files" + \
                                  "\n" + "These will appear shortly. You do not need to submit the test manually."
        else:
            guiplugins.RecordTest.setTestReady(self, test, usecase)
