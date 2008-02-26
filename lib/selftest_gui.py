
# Only used when running the self-tests

import defaultgui

# Class for importing self tests
class ImportTestCase(defaultgui.ImportTestCase):
    def addDefinitionFileOption(self):
        defaultgui.ImportTestCase.addDefinitionFileOption(self)
        self.addSwitch("GUI", "Use TextTest GUI", 1)
        self.addSwitch("sGUI", "Use TextTest Static GUI", 0)
    def getOptions(self, suite):
        options = defaultgui.ImportTestCase.getOptions(self, suite)
        if self.optionGroup.getSwitchValue("sGUI"):
            options += " -gx"
        elif self.optionGroup.getSwitchValue("GUI"):
            options += " -g"
        return options

