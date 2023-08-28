
""" All the standard scripts that come with the default configuration """

from . import sandbox
import operator
import os
import shutil
import sys
import random
from glob import glob
from texttestlib import plugins
from collections import OrderedDict
from configparser import RawConfigParser
from functools import reduce
from pprint import pformat


class CountTest(plugins.Action):
    scriptDoc = "report on the number of tests selected, by application"
    appCount = OrderedDict()

    @classmethod
    def finalise(self):
        for app, count in list(self.appCount.items()):
            print(app.description(), "has", count, "tests")
        print("There are", sum(self.appCount.values()), "tests in total.")

    def __repr__(self):
        return "Counting"

    def __call__(self, test):
        self.describe(test)
        self.appCount[test.app] += 1

    def setUpSuite(self, suite):
        self.describe(suite)

    def setUpApplication(self, app):
        self.appCount[app] = 0


class WriteDividedSelections(plugins.ScriptWithArgs):
    scriptDoc = "divide the test suite into equally sized selections, for parallel testing without communication possibilities"
    files = []
    counts = []

    def __init__(self, args=[]):
        if len(self.files) == 0:
            WriteDividedSelections.initialise(args)

    @classmethod
    def initialise(cls, args):
        argDict = cls.parseArguments(args, ["count", "prefix"])
        prefix = argDict["prefix"]
        for fn in glob(prefix + "_*"):
            os.remove(fn)
        for i in range(int(argDict["count"])):
            fn = prefix + "_" + str(i + 1)
            f = open(fn, "a")
            f.write("-tp ")
            cls.files.append(f)
        cls.counts = [0] * len(cls.files)

    def setUpSuite(self, suite):
        if suite.parent is None:
            for f in self.files:
                f.write("appdata=" + suite.app.name + suite.app.versionSuffix() + "\n")

    def __call__(self, test):
        minCount = min(self.counts)
        minIndices = [i for (i, count) in enumerate(self.counts) if count == minCount]
        chosenIndex = minIndices[int(random.random() * len(minIndices))] if len(minIndices) > 1 else minIndices[0]
        self.counts[chosenIndex] += 1
        self.files[chosenIndex].write(test.getRelPath() + "\n")


class DocumentOptions(plugins.Action):
    multiValueOptions = ["a", "c", "f", "funion", "fintersect", "t", "ts", "v"]

    def setUpApplication(self, app):
        groups = app.createOptionGroups([app])
        keys = reduce(operator.add, (list(g.keys()) for g in groups), [])
        keys.sort()
        for key in keys:
            self.displayKey(key, groups)

    def displayKey(self, key, groups):
        for group in groups:
            option = group.getOption(key)
            if option:
                keyOutput, docOutput = self.optionOutput(key, group, option)
                self.display(keyOutput, self.groupOutput(group), docOutput)

    def display(self, keyOutput, groupOutput, docOutput):
        if not docOutput.startswith("Private"):
            print(keyOutput + ";" + groupOutput + ";" + docOutput.replace("SGE", "SGE/LSF"))

    def groupOutput(self, group):
        knownGroups = ["Selection", "Basic", "Advanced"]
        if group.name == "Invisible":
            return "N/A"
        elif group.name in knownGroups:
            return group.name
        else:
            return "Advanced"

    def optionOutput(self, key, group, option):
        keyOutput = "-" + key
        docs = option.name
        if isinstance(option, plugins.TextOption):
            keyOutput += " <value>"
            if (docs == "Execution time"):
                keyOutput = "-" + key + " <time specification string>"
            else:
                docs += " <value>"
            if key in self.multiValueOptions:
                keyOutput += ",..."
                docs += ",..."

        if group.name.startswith("Select"):
            return keyOutput, "Select " + docs.lower()
        else:
            return keyOutput, docs


class DocumentConfig(plugins.ScriptWithArgs):
    def __init__(self, args=[]):
        argDict = self.parseArguments(args, ["os", "entries"])
        self.onlyEntries = []
        if "entries" in argDict:
            self.onlyEntries = argDict["entries"].split(",")
        self.overrideOs = argDict.get("os") if "os" in argDict else None
        
    def getEntriesToUse(self, app):
        if len(self.onlyEntries) > 0:
            return self.onlyEntries
        else:
            return sorted(list(app.configDir.keys()) + list(app.configDir.aliases.keys()))

    def reloadForOverrideOs(self, app):
        if self.overrideOs and self.overrideOs != os.name:
            realOs = self.overrideOs
            os.name = self.overrideOs
            app.reloadConfiguration()
            os.name = realOs

    def setUpApplication(self, app):
        self.reloadForOverrideOs(app)
        for key in self.getEntriesToUse(app):
            realKey = app.configDir.aliases.get(key, key)
            if realKey == key:
                docOutput = app.configDocs.get(realKey, "NO DOCS PROVIDED")
            else:
                docOutput = "Alias. See entry for '" + realKey + "'"
            if not docOutput.startswith("Private"):
                value = app.configDir[realKey]
                print(key + "|" + self.interpretArgument(value) + "|" + docOutput)

    def interpretArgument(self, arg):
        argStr = pformat(arg, width=1000) if isinstance(arg, dict) else str(arg)
        if os.sep == "\\":
            # in python strings get double backslashes, handle this
            doubleBackslashRoot = plugins.installationRoots[0].replace("\\", "\\\\")
            argStr = argStr.replace(doubleBackslashRoot, "<source library>")
        return argStr.replace(plugins.installationRoots[0], "<source library>")


class DocumentEnvironment(plugins.Action):
    def __init__(self, args=[]):
        self.onlyEntries = args
        self.prefixes = ["TEXTTEST_", "USECASE_", "STORYTEXT_"]
        self.exceptions = ["TEXTTEST_PERSONAL_", "STORYTEXT_HOME_LOCAL", "TEXTTEST_FAKE_USER"]

    def getEntriesToUse(self, app):
        rootDir = plugins.installationRoots[0]
        return self.findAllVariables(app, self.prefixes, rootDir)

    def findAllVariables(self, app, prefixes, rootDir):
        includeSite = app.inputOptions.configPathOptions()[0]
        allVars = {}
        for root, dirs, files in os.walk(rootDir):
            if "log" in dirs:
                dirs.remove("log")
            if "storytext" in dirs:
                dirs.remove("storytext")
            if not includeSite and "site" in dirs:
                dirs.remove("site")

            # We only want to document environment variables in the configuration we're using here, not every configuration we can find
            if root.endswith("lib"):
                toRemove = []
                for dir in dirs:
                    if dir != "libexec" and dir not in sys.modules and "texttestlib." + dir not in sys.modules:
                        toRemove.append(dir)
                for dir in toRemove:
                    dirs.remove(dir)
            for file in files:
                if file.endswith(".py"):
                    path = os.path.join(root, file)
                    self.findVarsInFile(path, allVars, prefixes)
        return allVars

    def getArgList(self, line, functionName):
        pos = line.find(functionName) + len(functionName)
        parts = line[pos:].strip().split("#")
        endPos = parts[0].find(")")
        argStr = parts[0][:endPos + 1]
        for _ in range(argStr.count("(", 1)):
            endPos = parts[0].find(")", endPos + 1)
            argStr = parts[0][:endPos + 1]
        allArgs = self.getActualArguments(argStr)
        if len(parts) > 1:
            allArgs.append(parts[1].strip())
        else:
            allArgs.append("")
        return allArgs

    def getActualArguments(self, argStr):
        if not argStr.startswith("("):
            return []

        # Pick up app.getConfigValue
        class FakeApp:
            def getConfigValue(self, name):
                return "Config value '" + name + "'"
        app = FakeApp()  # @UnusedVariable
        try:
            argTuple = eval(argStr)
            if type(argTuple) == tuple:
                allArgs = list(eval(argStr))
                return [ str(allArgs[1]) ]
            else:
                return []
        except Exception:  # could be anything at all
            if argStr.endswith("executable)"):
                return [ "<source directory>/bin/texttest" ]
            else:
                return []

    def isRelevant(self, var, vars, prefixes):
        if var in self.exceptions or var in prefixes or "SLEEP" in var or "SELFTEST" in var or \
                (len(self.onlyEntries) > 0 and var not in self.onlyEntries):
            return False
        prevVal = vars.get(var, [])
        return not prevVal or not prevVal[0]

    def findVarsInFile(self, path, vars, prefixes):
        import re
        regexes = [re.compile("([^/ \"'\.,\(]*)[\(]?[\"'](" + prefix + "[^/ \"'\.,]*)") for prefix in prefixes]
        for line in open(path):
            for regex in regexes:
                match = regex.search(line)
                if match is not None:
                    functionName = match.group(1)
                    var = match.group(2).strip()
                    if self.isRelevant(var, vars, prefixes):
                        argList = self.getArgList(line, functionName)
                        vars[var] = argList

    def setUpApplication(self, app):
        vars = self.getEntriesToUse(app)
        print("The following variables may be set by the user :")
        for key in sorted(vars.keys()):
            argList = vars[key]
            if len(argList) > 1:
                print(key + "|" + "|".join(argList))

        print("The following variables are set by TextTest :")
        for var in sorted([key for key in list(vars.keys()) if len(vars[key]) == 1]):
            print(var + "|" + vars[var][0])


class DocumentScripts(plugins.Action):
    def setUpApplication(self, app):
        from . import batch, comparetest, performance
        for module in [batch, comparetest, sys.modules[__name__], performance]:
            names = dir(module)
            for name in names:
                try:
                    docString = getattr(getattr(module, name), "scriptDoc")
                    scriptName = module.__name__.replace("texttestlib.default.", "").replace(
                        "scripts", "default") + "." + name
                    print(scriptName + "|" + docString)
                except AttributeError:
                    pass


class ReplaceText(plugins.ScriptWithArgs):
    scriptDoc = "Perform a search and replace on all files with the given stem"

    def __init__(self, args):
        argDict = self.parseArguments(args, ["old", "new", "file", "regexp", "argsReplacement", "includeShortcuts"])
        tryAsRegexp = "regexp" not in argDict or argDict["regexp"] == "1"
        self.argsReplacement = "argsReplacement" in argDict and argDict["argsReplacement"] == "1"
        self.oldText = argDict["old"].replace("\\n", "\n")
        self.newText = argDict["new"].replace("\\n", "\n")
        if self.newText.endswith("\n") and self.oldText.endswith("\n"):
            self.oldText = self.oldText.rstrip()
        self.newText = self.newText.rstrip()
        self.trigger = plugins.MultilineTextTrigger(self.oldText, tryAsRegexp, False) if not self.argsReplacement else plugins.TextTrigger(self.oldText, tryAsRegexp, False)
        self.newMultiLineText = self.newText.split("\n")
        self.stems = []
        fileStr = argDict.get("file")
        if fileStr:
            self.stems = plugins.commasplit(fileStr)
        self.includeShortcuts = "includeShortcuts" in argDict and argDict["includeShortcuts"] == "1"

    def __repr__(self):
        return "Replacing " + self.oldText + " with " + self.newText + " for"

    def getFilesToChange(self, test, stem):
        if self.includeShortcuts and test.app.name == "shortcut" and test.classId() == "test-case":
            return [test.dircache.pathName(f) for f in test.dircache.contents if f.endswith(".shortcut")]
        else:
            return test.getFileNamesMatching(stem)

    def __call__(self, test):
        self.replaceInFiles(test)

    def replaceInFiles(self, test):
        replaced = False
        for stem in self.stems:
            for stdFile in self.getFilesToChange(test, stem):
                if os.path.isfile(stdFile) and not plugins.containsAutoGeneratedText(stdFile):
                    self.replaceInFile(test, stdFile)
                    replaced = True
        return replaced

    def replaceInFile(self, test, stdFile):
        fileName = os.path.basename(stdFile)
        self.describe(test, " - file " + fileName)
        sys.stdout.flush()
        unversionedFileName = ".".join(fileName.split(".")[:2])
        if "." not in unversionedFileName:
            unversionedFileName += "." + test.app.name
        tmpFile = os.path.join(test.getDirectory(temporary=1), unversionedFileName)
        with open(tmpFile, "w") as writeFile:
            with open(stdFile) as readFile:
                for line in readFile:
                    newLine = self.trigger.replace(line, self.newMultiLineText if not self.argsReplacement else self.replaceArgs)
                    writeFile.write(newLine)
                if self.oldText[-1] != "\n" and not self.argsReplacement:
                    writeFile.write(self.trigger.getLeftoverText())

    def replaceArgs(self, matchobj):
        from storytext.replayer import ReplayScript
        return ReplayScript.getTextWithArgs(self.newText, [arg for arg in matchobj.groups()])

    def usesComparator(self):
        return True

    def comparesSuites(self, app):
        defStems = app.defFileStems()
        return any((stem in defStems for stem in self.stems))

    def setUpSuite(self, suite):
        if not self.replaceInFiles(suite):
            self.describe(suite)

    def setUpApplication(self, app):
        if len(self.stems) == 0:
            logFile = app.getConfigValue("log_file")
            if not logFile in self.stems:
                self.stems.append(logFile)


class ExportTests(plugins.ScriptWithArgs):
    scriptDoc = "Export the selected tests to a different test suite"

    def __init__(self, args):
        argDict = self.parseArguments(args, ["dest"])
        self.otherTTHome = argDict.get("dest")
        self.otherSuites = {}
        self.placements = {}
        if not self.otherTTHome:
            raise plugins.TextTestError("Must provide 'dest' argument to indicate where tests should be exported")

    def __repr__(self):
        return "Checking for export of"

    def __call__(self, test):
        self.tryExport(test)

    def setUpSuite(self, suite):
        self.placements[suite] = 0
        if suite.parent:
            self.tryExport(suite)

    def tryExport(self, test):
        otherRootSuite = self.otherSuites.get(test.app)
        otherTest = otherRootSuite.findSubtestWithPath(test.getRelPath())
        parent = test.parent
        if otherTest:
            self.describe(test, " - already exists")
        else:
            otherParent = otherRootSuite.findSubtestWithPath(parent.getRelPath())
            if otherParent:
                self.describe(test, " - CREATING...")
                self.copyTest(test, otherParent, self.placements[parent])
            else:
                self.describe(test, " - COULDN'T FIND PARENT")
        self.placements[parent] += 1

    def copyTest(self, test, otherParent, placement):
        # Do this first, so that if it fails due to e.g. full disk, we won't register the test either...
        testDir = otherParent.makeSubDirectory(test.name)
        self.copyTestContents(test, testDir)
        otherParent.registerTest(test.name, test.description, placement)
        otherParent.addTest(test.__class__, test.name, test.description, placement)

    def copyTestContents(self, test, newDir):
        stdFiles, defFiles = test.listApprovedFiles(allVersions=True)
        for sourceFile in stdFiles + defFiles:
            dirname, local = os.path.split(sourceFile)
            if dirname == test.getDirectory():
                targetFile = os.path.join(newDir, local)
                shutil.copy2(sourceFile, targetFile)

        extFiles = test.listExternallyEditedFiles()[1]
        dataFiles = test.listDataFiles() + extFiles
        for sourcePath in dataFiles:
            if os.path.isdir(sourcePath):
                continue
            targetPath = sourcePath.replace(test.getDirectory(), newDir)
            plugins.ensureDirExistsForFile(targetPath)
            shutil.copy2(sourcePath, targetPath)

    def setUpApplication(self, app):
        self.otherSuites[app] = app.createExtraTestSuite(otherDir=self.otherTTHome)

# A standalone action, we add description and generate the main file instead...


class ExtractStandardPerformance(sandbox.ExtractPerformanceFiles):
    scriptDoc = "update the standard performance files from the standard log files"

    def __init__(self):
        sandbox.ExtractPerformanceFiles.__init__(self, sandbox.MachineInfoFinder())

    def __repr__(self):
        return "Extracting standard performance for"

    def __call__(self, test):
        self.describe(test)
        sandbox.ExtractPerformanceFiles.__call__(self, test)

    def findLogFiles(self, test, stem):
        return test.getFileNamesMatching(stem)

    def getFileToWrite(self, test, stem):
        name = stem + "." + test.app.name + test.app.versionSuffix()
        return os.path.join(test.getDirectory(), name)

    def allMachinesTestPerformance(self, test, fileStem):
        # Assume this is OK: the current host is in any case utterly irrelevant
        return 1

    def setUpSuite(self, suite):
        self.describe(suite)

    def getMachineContents(self, test):
        return " on unknown machine (extracted)\n"


class InsertShortcuts(plugins.ScriptWithArgs):
    def __repr__(self):
        return "Inserting shortcuts into usecases for"

    def __call__(self, test):
        stdFiles = test.getFileNamesMatching("*usecase*")
        for stdFile in stdFiles:
            fileName = os.path.basename(stdFile)
            self.describe(test, " - file " + fileName)
            unversionedFileName = ".".join(fileName.split(".")[:2])
            tmpFile = os.path.join(test.getDirectory(temporary=1), unversionedFileName)
            storytextHome = test.getEnvironment("STORYTEXT_HOME")
            recordScript = self.getRecordScript(tmpFile, storytextHome)
            with open(stdFile) as readFile:
                for line in readFile:
                    recordScript.record(line.strip("\n"))

    def getRecordScript(self, stdFile, storytextHome):
        from storytext.replayer import ShortcutManager
        from storytext import scriptEngine
        from storytext.recorder import RecordScript
        return RecordScript(stdFile, scriptEngine.getShortcuts(storytextHome))

    def usesComparator(self):
        return True

    def comparesSuites(self, *args):
        return False


class FilterUIMapFile(plugins.ScriptWithArgs):
    scriptDoc = "Edit the UI map to remove all unused entries, list the unused shortcuts (GUI testing)"
    instancesByFile = OrderedDict()

    def __init__(self):
        self.uiMapFileHandler = None
        self.uiMapFileUsed = {}
        from storytext.replayer import ShortcutManager
        self.shortcutManager = ShortcutManager()
        self.shortcutsUsed = set()

    def __repr__(self):
        return "Filtering UI map file for"

    def __call__(self, test):
        storytextHome = test.getEnvironment("STORYTEXT_HOME")
        uiMapFile = os.path.join(storytextHome, "ui_map.conf")
        self.instancesByFile[uiMapFile].filterUseCaseCommands(test)

    def storeUsage(self, script):
        for command in script.commands:
            shortcut, _ = self.shortcutManager.findShortcut(command)
            if shortcut:
                self.shortcutsUsed.add(shortcut)
            else:
                for section, option in self.uiMapFileHandler.findSectionsAndOptions(command):
                    self.uiMapFileUsed.setdefault(section, []).append(option)

    def filterUseCaseCommands(self, test):
        stdFiles = test.getFileNamesMatching("*usecase*")
        from storytext.replayer import ReplayScript
        for stdFile in sorted(stdFiles):
            fileName = os.path.basename(stdFile)
            self.describe(test, " - file " + fileName)
            script = ReplayScript(stdFile, ignoreComments=True)
            self.storeUsage(script)

    def setUpSuite(self, suite):
        if suite.parent is None:
            storytextHome = suite.getEnvironment("STORYTEXT_HOME")
            uiMapFile = os.path.join(storytextHome, "ui_map.conf")
            if not uiMapFile in self.instancesByFile:
                self.instancesByFile[uiMapFile] = self
                from storytext.guishared import UIMapFileHandler
                from storytext.scriptengine import ScriptEngine
                self.uiMapFileHandler = UIMapFileHandler([uiMapFile])
                for shortcut in ScriptEngine.getShortcuts(storytextHome):
                    self.shortcutManager.add(shortcut)
        else:
            self.describe(suite)

    @classmethod
    def finalise(cls):
        for uiMapFile, instance in list(cls.instancesByFile.items()):
            instance.writeResults(uiMapFile)

    def writeResults(self, uiMapFile):
        for name, shortcut in self.shortcutManager.getShortcuts():
            if shortcut in self.shortcutsUsed:
                self.storeUsage(shortcut)
            else:
                print("Shortcut not used", shortcut.name)

        writeParser = RawConfigParser(dict_type=OrderedDict)
        writeParser.optionxform = str
        for section in self.uiMapFileHandler.sections():
            usedActions = self.uiMapFileUsed.get(section, [])
            entriesToAdd = [action_event for action_event in self.uiMapFileHandler.items(
                section) if action_event[0] in usedActions or len(action_event[1].strip()) == 0]
            if entriesToAdd:
                writeParser.add_section(section)
                for actionName, eventName in entriesToAdd:
                    writeParser.set(section, actionName, eventName)
        print("Updating UI map file...")
        writeParser.write(open(uiMapFile, "w"))
