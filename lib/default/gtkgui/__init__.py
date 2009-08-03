
# One basic action that wants to bypass the GTK imports

import plugins
from guiutils import GUIConfig
        
class DocumentGUIConfig(plugins.Action):
    def setUpApplication(self, app):
        guiConfig = GUIConfig(False, [ app ], GUIConfig.getDefaultColours(), GUIConfig.getDefaultAccelerators())
        for key in sorted(guiConfig.configDir.keys()):
            docOutput = guiConfig.configDocs[key]
            value = guiConfig.configDir[key]
            print key + "|" + str(value) + "|" + docOutput
