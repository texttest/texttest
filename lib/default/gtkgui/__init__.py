
# One basic action that wants to bypass the GTK imports

import guiplugins, plugins

class DocumentGUIConfig(plugins.Action):
    def setUpApplication(self, app):
        guiConfig = guiplugins.GUIConfig(False, [ app ], None)
        for key in sorted(guiConfig.configDir.keys()):
            docOutput = guiConfig.configDocs[key]
            value = guiConfig.configDir[key]
            print key + "|" + str(value) + "|" + docOutput
