
import ravebased_gui, default_gui, cvs, ravebased, os, shutil, subprocess

# Graphical import suite. Basically the same as those used for optimizers
class ImportTestSuite(ravebased_gui.ImportTestSuite):
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

# Graphical import test
class ImportTestCase(default_gui.ImportTestCase):
    newMacroString = "<Record new macro>"
    def addDefinitionFileOption(self):
        default_gui.ImportTestCase.addDefinitionFileOption(self)
        self.optionGroup.addOption("mac", "Macro to use", self.newMacroString)
    def updateOptions(self):
        default_gui.ImportTestCase.updateOptions(self)
        self.optionGroup.setOptionValue("mac", self.newMacroString)
        self.optionGroup.setPossibleValues("mac", self.getExistingMacros())
        return True
    def getExistingMacros(self):
        carmUsr = self.currTestSelection[0].getEnvironment("CARMUSR")
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
        default_gui.ImportTestCase.writeDefinitionFiles(self, suite, testDir)
        macroToImport = self.optionGroup.getOptionValue("mac")
        if macroToImport != self.newMacroString:
            usecaseFile = self.getWriteFileName("usecase", suite, testDir)
            fullMacroPath = os.path.join(suite.getEnvironment("CARMUSR"), "macros", macroToImport)
            shutil.copyfile(fullMacroPath, usecaseFile)

# Allow manual specification of a ruleset, and two auto-replays needed for macro recorder...
class RecordTest(default_gui.RecordTest):
    def __init__(self, *args):
        default_gui.RecordTest.__init__(self, *args)
        self.optionGroup.addOption("rulecomp", "Compile this ruleset first")
        self.changedUseCaseVersion = ""
    def updateOptions(self):
        retValue = default_gui.RecordTest.updateOptions(self)
        self.optionGroup.setOptionValue("rulecomp", "")
        self.optionGroup.setPossibleValues("rulecomp", self.findRuleSets())
        return retValue
    def findRuleSets(self):
        carmUsr = self.currTestSelection[0].getEnvironment("CARMUSR")
        if not carmUsr:
            return []
        sourceDir = os.path.join(carmUsr, "crc", "source")
        if os.path.isdir(sourceDir):
            return filter(self.isRuleSource, os.listdir(sourceDir))
        else:
            return []
    def isRuleSource(self, fileName):
        return not fileName.startswith(".")
    def getCommandLineKeys(self):
        return default_gui.RecordTest.getCommandLineKeys(self) + [ "rulecomp" ]
    def getChangedUseCaseVersion(self, test):
        ret = default_gui.RecordTest.getChangedUseCaseVersion(self, test)
        self.changedUseCaseVersion = ret # cache the result, for using in our auto-replay
        return ret
    def handleCompletion(self, testSel, usecase):
        if usecase == "replay":
            self.startTextTestProcess("replay2", self.getReplayRunModeOptions(self.changedUseCaseVersion))
            message = "First auto-replay completed for " + repr(testSel[0]) + \
                      ". Second auto-replay now started. Don't submit the test manually!"
            self.notify("Status", message)
        else:
            default_gui.RecordTest.handleCompletion(self, testSel, usecase)

class InteractiveActionConfig(cvs.InteractiveActionConfig):
    def getReplacements(self):
        return { default_gui.ImportTestCase  : ImportTestCase,
                 default_gui.ImportTestSuite : ImportTestSuite,
                 default_gui.RecordTest      : RecordTest } 
