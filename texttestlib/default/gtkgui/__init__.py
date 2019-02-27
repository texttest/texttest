
# One basic action that wants to bypass the GTK imports

from texttestlib.default.scripts import DocumentConfig


class DocumentGUIConfig(DocumentConfig):
    def setUpApplication(self, app):
        self.reloadForOverrideOs(app)
        from .guiutils import GUIConfig
        from .default_gui import InteractiveActionConfig
        guiConfig = GUIConfig(False, [app], GUIConfig.getDefaultColours(),
                              InteractiveActionConfig().getDefaultAccelerators())
        for key in sorted(guiConfig.configDir.keys()):
            docOutput = guiConfig.configDocs[key]
            value = guiConfig.configDir[key]
            print(key + "|" + self.getValue(value) + "|" + docOutput)

    def getValue(self, value):
        class ArgWrapper:
            def __init__(self, val):
                self.val = val

            def __repr__(self):
                return str(self.val)

        if isinstance(value, dict):
            newdict = {}
            # Avoid revolting floating point output in Python 2.6, this isn't
            # necessary in 2.7 and later
            for key, val in list(value.items()):
                if isinstance(val, float):
                    newdict[key] = ArgWrapper(val)
                else:
                    newdict[key] = val
            return str(newdict)
        else:
            return str(value)
