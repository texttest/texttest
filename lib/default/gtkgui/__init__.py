
# One basic action that wants to bypass the GTK imports

import plugins

class DocumentGUIConfig(plugins.Action):
    def setUpApplication(self, app):
        from guiutils import GUIConfig
        from guiplugins import interactiveActionHandler
        defaultColours = guiplugins.interactiveActionHandler.getColourDictionary(allApps)
        defaultAccelerators = guiplugins.interactiveActionHandler.getDefaultAccelerators(allApps)
        guiConfig = GUIConfig(False, [ app ], None)
        for key in sorted(guiConfig.configDir.keys()):
            docOutput = guiConfig.configDocs[key]
            value = guiConfig.configDir[key]
            print key + "|" + str(value) + "|" + docOutput
