
import os, plugins

def getVersionControlConfig(apps):
    for app in apps:
        config = getConfigFromDirectory(app.getDirectory())
        if config:
            return config
    return getConfigFromDirectory(os.getenv("TEXTTEST_HOME"))


def getConfigFromDirectory(directory):
    for dir in [ directory, os.path.dirname(directory) ]:
        for controlDirName in plugins.controlDirNames:
            controlDir = os.path.join(dir, controlDirName)
            if os.path.isdir(controlDir):
                module = controlDirName.lower().replace(".", "")
                exec "from " + module + " import InteractiveActionConfig"
                return InteractiveActionConfig(controlDir)
