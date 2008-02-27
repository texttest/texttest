
# Only used when running the self-tests

import default_gui

# Class for importing self tests
class ImportTestCase(default_gui.ImportTestCase):
    def addDefinitionFileOption(self):
        default_gui.ImportTestCase.addDefinitionFileOption(self)
        self.addSwitch("GUI", "Use TextTest GUI", 1)
        self.addSwitch("sGUI", "Use TextTest Static GUI", 0)
    def getOptions(self, suite):
        options = default_gui.ImportTestCase.getOptions(self, suite)
        if self.optionGroup.getSwitchValue("sGUI"):
            options += " -gx"
        elif self.optionGroup.getSwitchValue("GUI"):
            options += " -g"
        return options

class InteractiveActionConfig(default_gui.InteractiveActionConfig):
    def getReplacements(self):
        return { default_gui.ImportTestCase : ImportTestCase } 
