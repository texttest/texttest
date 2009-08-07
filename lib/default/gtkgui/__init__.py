
# One basic action that wants to bypass the GTK imports

import plugins
        
class DocumentGUIConfig(plugins.Action):
    def setUpApplication(self, app):
        from guiutils import GUIConfig
        from default_gui import InteractiveActionConfig
        guiConfig = GUIConfig(False, [ app ], GUIConfig.getDefaultColours(), InteractiveActionConfig().getDefaultAccelerators())
        for key in sorted(guiConfig.configDir.keys()):
            docOutput = guiConfig.configDocs[key]
            value = guiConfig.configDir[key]
            print key + "|" + str(value) + "|" + docOutput
