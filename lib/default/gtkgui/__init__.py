
# One basic action that wants to bypass the GTK imports

import plugins

class DocumentGUIConfig(plugins.Action):
    def setUpApplication(self, app):
        from guiplugins import GUIConfig
        guiConfig = GUIConfig(False, [ app ], None)
        for key in sorted(guiConfig.configDir.keys()):
            docOutput = guiConfig.configDocs[key]
            value = guiConfig.configDir[key]
            print key + "|" + str(value) + "|" + docOutput
