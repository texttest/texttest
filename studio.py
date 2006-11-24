#
#	Studio plug-in for Texttest framework
#
# This plug-in is derived from the ravebased configuration, to make use of CARMDATA isolation
# and rule compilation, as well as Carmen's SGE queues.
#
# $Header: /carm/2_CVS/Testing/TextTest/Attic/studio.py,v 1.37 2006/11/24 16:49:38 geoff Exp $
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
    def getWriteDirectoryPreparer(self, ignoreCatalogues):
        return ravebased.PrepareCarmdataWriteDir(ignoreCatalogues)
    def defaultBuildRules(self):
        # Overriding this assures rule builds in the nightjob and with -v rave.
        return 1
    def getPerformanceExtractor(self):
        return ExtractPerformanceFiles(self.getMachineInfoFinder())
    def getRuleSetName(self, test):
        if self.optionMap.has_key("rset"):
            return self.optionMap["rset"]
	rulesetName = ""
        subplanDir = self._getSubPlanDirName(test)
        if subplanDir:
	    headerFile = os.path.join(subplanDir, "subplanHeader")
	    origPath = self.findOrigRulePath(headerFile)
	    rulesetName = os.path.basename(origPath)
	if not rulesetName:
	    # get default ruleset from resources
	    carmSys = test.getEnvironment("CARMSYS")
	    carmUsr = test.getEnvironment("CARMUSR")
	    carmTmp = test.getEnvironment("CARMTMP")
	    userId = "nightjob"
	    if carmSys and carmUsr and carmTmp:
		script = os.path.join(carmSys, "bin", "crsutil")
		cmd = "/usr/bin/env USER=" + userId + \
			    " CARMUSR=" + carmUsr + \
			    " CARMTMP=" + carmTmp + \
			    " " + script + " -g CrcDefaultRuleSet"
		#print "cmd=",cmd
		try:
		    for l in os.popen(cmd):
			name = l[:-1]
			if name and os.path.exists(name):
			    rulesetName = os.path.basename(name)
			    break
		except Exception, x:
		    #print "crsutil failed: ", x
		    pass
        if self.macroBuildsRuleset(test, rulesetName):
            # Don't want to manage the ruleset separately if the macro is going to build it...
            return ""
	#print "returning rulesetName=", rulesetName
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
        macroFile = test.getFileName("usecase")
        if not macroFile:
            return
        useNext = 0
        for line in open(macroFile).xreadlines():
            if useNext:
                return line
            elif line.find("OPEN_PLAN") != -1:
                useNext = 1
    def macroBuildsRuleset(self, test, rulesetName):
        macroFile = test.getFileName("usecase")
        if not macroFile:
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
	    	print "line=",line
                cpuTime = int(line.split()[-2])
                realTime = int(line.split()[-6])
                if currOperations[-1]:
                    values.append( (cpuTime, realTime) )
                del currOperations[-1]
            elif line.find(entryFinder) == -1:
                currOperations.append("")
            else:
                operation = string.join(line.strip().split()[2:])
                currOperations.append(operation)
        return values
    def makeTimeLine(self, values, fileStem):
        sumCpu = 0
        sumReal = 0
        for valueCpu, valueReal in values:
            sumCpu += valueCpu
            sumReal += valueReal
        return "Total CPU time in " + fileStem + "  :      " + str(sumCpu) + " milliseconds" \
	+"\n"+ "Total REAL time in " + fileStem + "  :      " + str(sumReal) + " milliseconds"
    
# Graphical import suite. Basically the same as those used for optimizers
class ImportTestSuite(ravebased.ImportTestSuite):
    def hasStaticLinkage(self, carmUsr):
        return False
    def getCarmtmpPath(self, carmtmp):
        return os.path.join("/carm/proj/studio/carmtmps/${MAJOR_RELEASE_ID}/${ARCHITECTURE}", carmtmp)

# Graphical import test
class ImportTestCase(guiplugins.ImportTestCase):
    newMacroString = "<Record new macro>"
    def addDefinitionFileOption(self, suite):
        guiplugins.ImportTestCase.addDefinitionFileOption(self, suite)
        self.optionGroup.addOption("mac", "Macro to use", self.newMacroString)
    def updateOptionGroup(self, state):
        self.optionGroup.setOptionValue("mac", self.newMacroString)
        self.optionGroup.setPossibleValues("mac", self.getExistingMacros())
    def getExistingMacros(self):
        carmUsr = self.currentTest.getEnvironment("CARMUSR")
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
    def __init__(self, test):
        guiplugins.RecordTest.__init__(self, test)
        self.optionGroup.addOption("rset", "Compile this ruleset first")
    def updateOptionGroup(self, state):
        self.optionGroup.setOptionValue("rset", "")
        self.optionGroup.setPossibleValues("rset", self.findRuleSets())
    def findRuleSets(self):
        carmUsr = self.currentTest.getEnvironment("CARMUSR")
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
        if usecase == "record" and ruleset:
            return "-rulecomp -rset " + ruleset + " " + basicOptions
        return basicOptions
    # We want to generate a second auto-replay...
    def setTestReady(self, test, usecase=""):
        if usecase == "replay":
            self.startTextTestProcess(test, usecase="replay2")
            message = "First auto-replay completed for " + repr(test) + \
                      ". Second auto-replay now started. Don't submit the test manually!"
            self.notify("Status", message)
        else:
            guiplugins.RecordTest.setTestReady(self, test, usecase)

class ViewFile(guiplugins.ViewFile):
    def getViewCommand(self, fileName):
    	fname=os.path.basename(fileName)
        if not (fname.startswith("usecase.") \
	        or (fname.startswith("slave_") and fname.find("usecase.") > 0)):
	    return guiplugins.ViewFile.getViewCommand(self, fileName)
        carmSys = self.currentTest.getEnvironment("CARMSYS")
        carmUsr = self.currentTest.getEnvironment("CARMUSR")
	if not carmSys or not carmUsr:
	    return guiplugins.ViewFile.getViewCommand(self, fileName)
        viewProgram = os.path.join(carmSys, "bin", "startMacroRecorder")
        if not os.path.isfile(viewProgram):
            raise plugins.TextTestError, "Could not find macro editor at " + viewProgram
        envStr = "env 'USER=nightjob' 'CARMSYS=" + carmSys + "' 'CARMUSR=" + carmUsr + "' "
        commandLine = envStr + viewProgram + " " + fileName + plugins.nullRedirect()
        return commandLine, "macro editor"
    
