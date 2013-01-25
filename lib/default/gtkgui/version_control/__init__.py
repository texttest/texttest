
import os, plugins

def getVersionControlConfig(apps, inputOptions):
    allDirs = [ app.getDirectory() for app in apps ] + inputOptions.rootDirectories
    for dir in allDirs:
        config = getConfigFromDirectory(os.path.realpath(dir))
        if config:
            return config

def getConfigFromDirectory(directory):
    for controlDirName in plugins.controlDirNames:
        controlDir = os.path.join(directory, controlDirName)
        if os.path.isdir(controlDir):
            module = controlDirName.lower().replace(".", "")
            try:
                exec "from " + module + " import InteractiveActionConfig"
                return InteractiveActionConfig(controlDir) #@UndefinedVariable
            except ImportError: # There may well be more VCSs than we have support for...
                pass
    dirname = os.path.dirname(directory)
    if dirname != directory:
        return getConfigFromDirectory(dirname)
