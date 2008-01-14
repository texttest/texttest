#
#       Studio plug-in for Texttest framework
#
# This plug-in is derived from the ravebased configuration, to make use of CARMDATA isolation
# and rule compilation, as well as Carmen's SGE queues.
#
# $Header: /carm/2_CVS/Testing/TextTest/lib/studio.py,v 1.15 2008/01/14 15:52:28 geoff Exp $
#
import ravebased, sandbox, plugins, guiplugins, subprocess
import os, shutil, string

def getConfig(optionMap):
    return StudioConfig(optionMap)

class StudioConfig(ravebased.Config):
    def addToOptionGroups(self, app, groups):
        for group in groups:
            if group.name.startswith("Basic"):
                group.addSwitch("stepmacro", "Step through macro using the Macro Recorder")
        ravebased.Config.addToOptionGroups(self, app, groups)
    def getWriteDirectoryPreparer(self, ignoreCatalogues):
        return ravebased.PrepareCarmdataWriteDir(ignoreCatalogues)
    def defaultBuildRules(self):
        # Overriding this assures rule builds in the nightjob and with -v rave, without
        # requiring constant checking if rulesets exist before running tests
        return self.rebuildAllRulesets()
    def getPerformanceExtractor(self):
        return ExtractPerformanceFiles(self.getMachineInfoFinder())
    def _getRuleSetNames(self, test):
        rulesets = []
        subplanRuleset = self.getSubplanRuleset(test)
        if subplanRuleset:
            rulesets.append(subplanRuleset)
                
        defaultRuleset = test.getEnvironment("DEFAULT_RULESET_NAME")
        if defaultRuleset and defaultRuleset not in rulesets:
            rulesets.append(defaultRuleset)

        extraRuleset = test.getEnvironment("EXTRA_RULESET_NAME")
        if extraRuleset and extraRuleset not in rulesets:
            rulesets.append(extraRuleset)
            
        return rulesets
    def ignoreBinary(self):
        if self.optionMap.runScript() and self.optionMap["s"].endswith("CacheDefaultRuleset"):
            return False
        return ravebased.Config.ignoreBinary(self)  
    def getSubplanRuleset(self, test):
        subplanDir = self._getSubPlanDirName(test)
        if subplanDir:
            headerFile = os.path.join(subplanDir, "subplanHeader")
            origPath = self.findOrigRulePath(headerFile)
            subplanRuleset = os.path.basename(origPath)
            # Don't want to manage the ruleset separately if the macro is going to build it...
            if not self.macroBuildsRuleset(test, subplanRuleset):
                return subplanRuleset    
                
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
    def getConfigEnvironment(self, test):
        baseEnv, props = ravebased.Config.getConfigEnvironment(self, test)
        if not test.parent and self.optionMap.has_key("stepmacro"):
            baseEnv.append(("USECASE_REPLAY_SINGLESTEP", "1"))
        return baseEnv, props
    def getInteractiveReplayOptions(self):
        return ravebased.Config.getInteractiveReplayOptions(self) + [ ("stepmacro", "single-step") ]
        
class ExtractPerformanceFiles(sandbox.ExtractPerformanceFiles):
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

    def cacheCarmusrInfo(self, suite, file):
        defaultRuleset = self.calculateDefaultRuleset(suite)
        if defaultRuleset:
            self.setEnvironment(suite, file, "DEFAULT_RULESET_NAME", defaultRuleset)

    def calculateDefaultRuleset(self, test):
        # We cache this when importing the test suite, because it's very slow to recompute
        # and crsutil isn't always present and correct
        runEnv = test.getRunEnvironment(ravebased.getCrcCompileVars())
        runEnv["CARMTMP"] = "/" # It's not important but it must exist!
        script = os.path.join(runEnv.get("CARMSYS"), "bin", "crsutil")
        cmdArgs = [ script, "-f", "CrcDefaultRuleSet: %s\n", "-g", "CrcDefaultRuleSet" ]
        try:
            proc = subprocess.Popen(cmdArgs, stdout=subprocess.PIPE, stderr=open(os.devnull, "w"), env=runEnv)
            output = proc.communicate()[0]
            for line in output.splitlines():
                if line.startswith("CrcDefaultRuleSet:"):
                    rulesetName = os.path.basename(line.strip().split()[-1])
                    if len (rulesetName) == 0 or rulesetName == "NO": # seems to some magic way to say there isn't one
                        return
                    else:
                        return rulesetName

            print "crsutil didn't return anything, hence default ruleset not found"
        except OSError:
            # If crsutil isn't there we won't get the default ruleset
            print "Warning - could not run crsutil, hence default ruleset not found!"
        
class CacheDefaultRuleset(plugins.Action):
    def __repr__(self):
        return "Caching default ruleset"
    def setUpSuite(self, suite):
        if ravebased.isUserSuite(suite) and not suite.hasEnvironment("DEFAULT_RULESET_NAME"):
            self.describe(suite)
            envFile = suite.getFileName("environment")
            file = open(envFile, "a")
            importer = ImportTestSuite()
            importer.cacheCarmusrInfo(suite, file)

# Graphical import test
class ImportTestCase(guiplugins.ImportTestCase):
    newMacroString = "<Record new macro>"
    def addDefinitionFileOption(self):
        guiplugins.ImportTestCase.addDefinitionFileOption(self)
        self.optionGroup.addOption("mac", "Macro to use", self.newMacroString)
    def updateOptions(self):
        guiplugins.ImportTestCase.updateOptions(self)
        self.optionGroup.setOptionValue("mac", self.newMacroString)
        self.optionGroup.setPossibleValues("mac", self.getExistingMacros())
        return True
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
    def __init__(self):
        guiplugins.RecordTest.__init__(self)
        self.optionGroup.addOption("rset", "Compile this ruleset first")
        self.changedUseCaseVersion = ""
    def updateOptions(self):
        retValue = guiplugins.RecordTest.updateOptions(self)
        self.optionGroup.setOptionValue("rset", "")
        self.optionGroup.setPossibleValues("rset", self.findRuleSets())
        return retValue
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
    def getRunOptions(self, test, usecase, overwriteVersion):
        basicOptions = guiplugins.RecordTest.getRunOptions(self, test, usecase, overwriteVersion)
        ruleset = self.optionGroup.getOptionValue("rset")
        if usecase == "record" and ruleset:
            return [ "-rulecomp", "-rset", ruleset ] + basicOptions
        return basicOptions
    def getChangedUseCaseVersion(self, test):
        ret = guiplugins.RecordTest.getChangedUseCaseVersion(self, test)
        self.changedUseCaseVersion = ret # cache the result, for using in our auto-replay
        return ret
    # We want to generate a second auto-replay...
    def setTestReady(self, test, usecase=""):
        if usecase == "replay":
            self.startTextTestProcess(test, "replay2", self.changedUseCaseVersion)
            message = "First auto-replay completed for " + repr(test) + \
                      ". Second auto-replay now started. Don't submit the test manually!"
            self.notify("Status", message)
        else:
            guiplugins.RecordTest.setTestReady(self, test, usecase)

class ViewInEditor(guiplugins.ViewInEditor):
    def getViewCommand(self, fileName, stdViewProgram):
        fname=os.path.basename(fileName)
        if not (fname.startswith("usecase.") \
                or (fname.startswith("slave_") and fname.find("usecase.") > 0)):
            return guiplugins.ViewInEditor.getViewCommand(self, fileName, stdViewProgram)
        carmSys = self.currentTest.getEnvironment("CARMSYS")
        carmUsr = self.currentTest.getEnvironment("CARMUSR")
        if not carmSys or not carmUsr:
            return guiplugins.ViewInEditor.getViewCommand(self, fileName, stdViewProgram)
        viewProgram = os.path.join(carmSys, "bin", "startMacroRecorder")
        if not os.path.isfile(viewProgram):
            raise plugins.TextTestError, "Could not find macro editor at " + viewProgram
        envArgs = [ "env", "USER=nightjob", "CARMSYS=" + carmSys, "CARMUSR=" + carmUsr ]
        cmdArgs = envArgs + [ viewProgram, fileName ]
        return cmdArgs, "macro editor"
