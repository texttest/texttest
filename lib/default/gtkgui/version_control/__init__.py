
import os, plugins

def getVersionControlConfig(apps, inputOptions):
    allDirs = [ app.getDirectory() for app in apps ] + inputOptions.getRootDirectories()
    for dir in allDirs:
        config = getConfigFromDirectory(dir)
        if config:
            return config

def getConfigFromDirectory(directory):
    for dir in [ directory, os.path.dirname(directory) ]:
        for controlDirName in plugins.controlDirNames:
            controlDir = os.path.join(dir, controlDirName)
            if os.path.isdir(controlDir):
                module = controlDirName.lower().replace(".", "")
                exec "from " + module + " import InteractiveActionConfig"
                return InteractiveActionConfig(controlDir)
