#
#	Studio plug-in for Texttest framework
#
# This plug-in is derived from the ravebased configuration, to make use of CARMDATA isolation
# and rule compilation, as well as Carmen's SGE queues.
#
# $Header: /carm/2_CVS/Testing/TextTest/Attic/studio.py,v 1.25 2006/04/05 14:31:52 geoff Exp $
#
import ravebased, default, plugins, guiplugins
import os, shutil, string

def getConfig(optionMap):
    return StudioConfig(optionMap)

class StudioConfig(ravebased.Config):
    def addToOptionGroups(self, app, groups):
        ravebased.Config.addToOptionGroups(self, app, groups)
        for group in groups:
            if group.name.startswith("Invisible"):
                group.addOption("rset", "Private: used for submitting ruleset compilation along with recording")
    def getWriteDirectoryPreparer(self, ignoreCatalogues, useDiagnostics):
        return ravebased.PrepareCarmdataWriteDir(ignoreCatalogues, useDiagnostics)
    def defaultBuildRules(self):
        # Overriding this assures rule builds in the nightjob and with -v rave.
        return 1
    def getPerformanceExtractor(self):
        return ExtractPerformanceFiles(self.getMachineInfoFinder())
    def getRuleSetName(self, test):
        if self.optionMap.has_key("rset"):
            return self.optionMap["rset"]
        subplanDir = self._getSubPlanDirName(test)
        if not subplanDir:
            return ""
        headerFile = os.path.join(subplanDir, "subplanHeader")
        origPath = self.findOrigRulePath(headerFile)
        rulesetName = os.path.basename(origPath)
        if self.macroBuildsRuleset(test, rulesetName):
            # Don't want to manage the ruleset separately if the macro is going to build it...
            return ""
        else:
            return rulesetName
    def findOrigRulePath(self, headerFile):
        if not os.path.isfile(headerFile):
            return ""
        index = -1
        for line in open(headerFile).xreadlines():
            if line.startswith("552"):
                index = line.split(";").index("SUB_PLAN_HEADER_RULE_SET_NAME")
            if line.startswith("554") and index > 0:
                return line.split(";")[index]
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
    def _getSubPlanDirName(self, test):
        origDirName = ravebased.Config._getSubPlanDirName(self, test)
        if origDirName and not os.path.isdir(origDirName):
            parent, local = os.path.split(origDirName)
            if os.path.isdir(parent):
                return parent
        return origDirName
    def getSubPlanLineInMacro(self, test):
        macroFile = test.makeFileName("usecase")
        if not os.path.isfile(macroFile):
            return
        useNext = 0
        for line in open(macroFile).xreadlines():
            if useNext:
                return line
            elif line.find("OPEN_PLAN") != -1:
                useNext = 1
    def macroBuildsRuleset(self, test, rulesetName):
        macroFile = test.makeFileName("usecase")
        if not os.path.isfile(macroFile):
            return False
        for line in open(macroFile).xreadlines():
            if line.find("Build ruleset " + rulesetName) != -1:
                return True
        return False

class ExtractPerformanceFiles(default.ExtractPerformanceFiles):
    def findValues(self, logFile, entryFinder):
        values = []
        currOperations = []
        for line in open(logFile).xreadlines():
            if not line.startswith("cslDispatcher"):
                continue
            if line.find("returnvalue") != -1:
                cpuTime = int(line.split()[-2])
                if currOperations[-1]:
                    values.append(cpuTime)
                del currOperations[-1]
            elif line.find(entryFinder) == -1:
                currOperations.append("")
            else:
                operation = string.join(line.strip().split()[2:])
                currOperations.append(operation)
        return values
    def makeTimeLine(self, values, fileStem):
        sum = 0
        for value in values:
            sum += value
        return "Total CPU time in " + fileStem + "  :      " + str(sum) + " milliseconds"
    
# Graphical import suite. Basically the same as those used for optimizers
class ImportTestSuite(ravebased.ImportTestSuite):
    def hasStaticLinkage(self, carmUsr):
        return False
    def getCarmtmpPath(self, carmtmp):
        return os.path.join("/carm/proj/studio/carmtmps/${MAJOR_RELEASE_ID}/${ARCHITECTURE}", carmtmp)

# Graphical import test
class ImportTestCase(guiplugins.ImportTestCase):
    newMacroString = "<Record new macro>"
    def addDefinitionFileOption(self, suite, oldOptionGroup):
        guiplugins.ImportTestCase.addDefinitionFileOption(self, suite, oldOptionGroup)
        # Don't use oldOptionGroup, we probably don't want the same macro more than once
        self.optionGroup.addOption("mac", "Macro to use", self.newMacroString, self.getExistingMacros(suite))
    def getExistingMacros(self, suite):
        carmUsr = suite.getEnvironment("CARMUSR")
        if not carmUsr:
            return []
        path = os.path.join(carmUsr, "macros")
        if not os.path.isdir(path):
            return []
        macros = []
        for userDir in os.listdir(path):
            fullUserDir = os.path.join(path, userDir)
            if os.path.isdir(fullUserDir):
                for macro in os.listdir(fullUserDir):
                    macros.append(os.path.join(userDir, macro))
        return macros
    def writeDefinitionFiles(self, suite, testDir):
        guiplugins.ImportTestCase.writeDefinitionFiles(self, suite, testDir)
        macroToImport = self.optionGroup.getOptionValue("mac")
        if macroToImport != self.newMacroString:
            usecaseFile = self.getWriteFileName("usecase", suite, testDir)
            fullMacroPath = os.path.join(suite.getEnvironment("CARMUSR"), "macros", macroToImport)
            shutil.copyfile(fullMacroPath, usecaseFile)

class RecordTest(guiplugins.RecordTest):
    def __init__(self, test, oldOptionGroup):
        guiplugins.RecordTest.__init__(self, test, oldOptionGroup)
        if self.canPerform():
            self.optionGroup.addOption("rset", "Compile this ruleset first", possibleValues=self.findRuleSets(test))
    def findRuleSets(self, test):
        carmUsr = test.getEnvironment("CARMUSR")
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

class ViewFile(guiplugins.ViewFile):
    def getViewCommand(self, fileName):
    	fname=os.path.basename(fileName)
        if not (fname.startswith("usecase.") \
	        or (fname.startswith("slave_") and fname.find("usecase.") > 0)):
	    return guiplugins.ViewFile.getViewCommand(self, fileName)
        carmSys = self.test.getEnvironment("CARMSYS")
        carmUsr = self.test.getEnvironment("CARMUSR")
        viewProgram = os.path.join(carmSys, "lib", "python", "StartMacroRecorder.py")
        if not os.path.isfile(viewProgram):
            raise plugins.TextTestError, "Could not find macro editor at " + viewProgram
        envStr = "env 'CARMSYS=" + carmSys + "' 'CARMUSR=" + carmUsr + "' "
        commandLine = envStr + "python " + viewProgram + " -v " + fileName + plugins.nullRedirect()
        return commandLine, "macro editor"
    
