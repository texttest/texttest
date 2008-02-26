#
#       Studio plug-in for Texttest framework
#
# This plug-in is derived from the ravebased configuration, to make use of CARMDATA isolation
# and rule compilation, as well as Carmen's SGE queues.
#
# $Header: /carm/2_CVS/Testing/TextTest/lib/studio.py,v 1.21 2008/02/26 14:34:12 geoff Exp $
#
import ravebased, sandbox, plugins, os, shutil

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
        return True
    def getPerformanceExtractor(self):
        return ExtractPerformanceFiles(self.getMachineInfoFinder())
    def _getRuleSetNames(self, test):
        rulesets = []
        subplanRuleset = self.getSubplanRuleset(test)
        if subplanRuleset and not self.macroBuildsRuleset(test, subplanRuleset):
            # Don't want to manage the ruleset separately if the macro is going to build it..
            rulesets.append(subplanRuleset)
                
        defaultRuleset = test.getEnvironment("DEFAULT_RULESET_NAME")
        if defaultRuleset and defaultRuleset not in rulesets:
            rulesets.append(defaultRuleset)

        extraRuleset = test.getEnvironment("EXTRA_RULESET_NAME")
        if extraRuleset and extraRuleset not in rulesets:
            rulesets.append(extraRuleset)
            
        return rulesets
    def ignoreExecutable(self):
        if self.optionMap.runScript() and self.optionMap["s"].endswith("CacheDefaultRuleset"):
            return False
        return ravebased.Config.ignoreExecutable(self)  
    
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
                operation = " ".join(line.strip().split()[2:])
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

