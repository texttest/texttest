import ravebased_gui, default_gui, ravebased, os, shutil, subprocess

# Allow manual specification of a ruleset, and two auto-replays needed for macro recorder...
class RecordTest(default_gui.RecordTest):
    def __init__(self, *args):
        default_gui.RecordTest.__init__(self, *args)
        self.optionGroup.addOption("rulecomp", "Compile this ruleset first")
        self.changedUseCaseVersion = ""
    def updateOptions(self):
        retValue = default_gui.RecordTest.updateOptions(self)
        self.optionGroup.setOptionValue("rulecomp", "")
        self.optionGroup.setPossibleValues("rulecomp", [])
        return retValue
    def getCommandLineKeys(self, *args):
        return default_gui.RecordTest.getCommandLineKeys(self, *args) + [ "rulecomp" ]

class InteractiveActionConfig(ravebased_gui.InteractiveActionConfig):
    def getReplacements(self):
        return { default_gui.RecordTest      : RecordTest } 
