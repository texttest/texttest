
import os
import importlib
from texttestlib import plugins


def getVersionControlConfig(apps, inputOptions):
    allDirs = [app.getDirectory() for app in apps] + inputOptions.rootDirectories
    for dir in allDirs:
        # Hack for self-testing...
        dirToCheck = dir if os.path.basename(dir) in os.getenv(
            "TEXTTEST_SELFTEST_DIR_NAMES", "").split(",") else os.path.realpath(dir)
        config = getConfigFromDirectory(dirToCheck)
        if config:
            return config


def getConfigFromDirectory(directory):
    allEntries = os.listdir(directory)
    for controlDirName in plugins.controlDirNames:
        if controlDirName in allEntries:
            module = controlDirName.lower().replace(".", "")
            try:
                controlDir = os.path.join(directory, controlDirName)
                if module != "cvs" or not os.path.isdir(os.path.join(controlDir, "CVS")):
                    # Avoid overarching directories "CVS" which are not control directories...
                    mod = importlib.import_module("." + module, __name__)
                    return mod.InteractiveActionConfig(controlDir)
            except ImportError:  # There may well be more VCSs than we have support for...
                pass
    dirname = os.path.dirname(directory)
    if dirname != directory:
        return getConfigFromDirectory(dirname)
