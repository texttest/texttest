
""" All the standard scripts that come with the default configuration """

import plugins, sandbox, operator, os, shutil, sys
from ordereddict import OrderedDict
                    
class CountTest(plugins.Action):
    scriptDoc = "report on the number of tests selected, by application"
    appCount = OrderedDict()
    @classmethod
    def finalise(self):
        for app, count in self.appCount.items():
            print app.description(), "has", count, "tests"
        print "There are", sum(self.appCount.values()), "tests in total."

    def __repr__(self):
        return "Counting"

    def __call__(self, test):
        self.describe(test)
        self.appCount[test.app] += 1

    def setUpSuite(self, suite):
        self.describe(suite)

    def setUpApplication(self, app):
        self.appCount[app] = 0


class DocumentOptions(plugins.Action):
    multiValueOptions = [ "a", "c", "f", "funion", "fintersect", "t", "ts", "v" ]
    def setUpApplication(self, app):
        groups = app.createOptionGroups([ app ])
        keys = reduce(operator.add, (g.keys() for g in groups), [])
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
            print keyOutput + ";" + groupOutput + ";" + docOutput.replace("SGE", "SGE/LSF")

    def groupOutput(self, group):
        knownGroups = [ "Selection", "Basic", "Advanced" ]
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
        

class DocumentConfig(plugins.Action):
    def __init__(self, args=[]):
        self.onlyEntries = args

    def getEntriesToUse(self, app):
        if len(self.onlyEntries) > 0:
            return self.onlyEntries
        else:
            return sorted(app.configDir.keys() + app.configDir.aliases.keys())
        
    def setUpApplication(self, app):
        for key in self.getEntriesToUse(app):
            realKey = app.configDir.aliases.get(key, key)
            if realKey == key:
                docOutput = app.configDocs.get(realKey, "NO DOCS PROVIDED")
            else:
                docOutput = "Alias. See entry for '" + realKey + "'"
            if not docOutput.startswith("Private"):
                value = app.configDir[realKey]
                print key + "|" + str(value) + "|" + docOutput  

class DocumentEnvironment(plugins.Action):
    def __init__(self, args=[]):
        self.onlyEntries = args
        self.prefixes = [ "TEXTTEST_", "USECASE_", "STORYTEXT_" ]
        self.exceptions = [ "TEXTTEST_PERSONAL_", "STORYTEXT_HOME_LOCAL" ]
        
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
            if root.endswith("lib"):
                for dir in dirs:
                    if not sys.modules.has_key(dir):
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
        for i in range(argStr.count("(", 1)):
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
        app = FakeApp()
        try:
            argTuple = eval(argStr)
            from types import TupleType
            if type(argTuple) == TupleType:
                allArgs = list(eval(argStr))
                return [ self.interpretArgument(str(allArgs[1])) ]
            else:
                return []
        except Exception: # could be anything at all
            return []

    def interpretArgument(self, arg):
        if arg.endswith("texttest.py"):
            return "<source directory>/bin/texttest.py"
        else:
            return arg

    def isRelevant(self, var, vars, prefixes):
        if var in self.exceptions or var in prefixes or "SLEEP" in var or \
               (len(self.onlyEntries) > 0 and var not in self.onlyEntries):
            return False
        prevVal = vars.get(var, [])
        return not prevVal or not prevVal[0]
        
    def findVarsInFile(self, path, vars, prefixes):
        import re
        regexes = [ re.compile("([^/ \"'\.,\(]*)[\(]?[\"'](" + prefix + "[^/ \"'\.,]*)") for prefix in prefixes ]
        for line in open(path).xreadlines():
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
        print "The following variables may be set by the user :"
        for key in sorted(vars.keys()):
            argList = vars[key]
            if len(argList) > 1:
                print key + "|" + "|".join(argList)

        print "The following variables are set by TextTest :"
        for var in sorted(filter(lambda key: len(vars[key]) == 1, vars.keys())):
            print var + "|" + vars[var][0]


class DocumentScripts(plugins.Action):
    def setUpApplication(self, app):
        modNames = [ "batch", "comparetest", "default", "performance" ]
        for modName in modNames:
            importCommand = "import " + modName
            exec importCommand
            command = "names = dir(" + modName + ")"
            exec command
            for name in names:
                scriptName = modName + "." + name
                docFinder = "docString = " + scriptName + ".scriptDoc"
                try:
                    exec docFinder
                    print scriptName + "|" + docString
                except AttributeError:
                    pass

class ReplaceText(plugins.ScriptWithArgs):
    scriptDoc = "Perform a search and replace on all files with the given stem"
    def __init__(self, args):
        argDict = self.parseArguments(args, [ "old", "new", "file" ])
        self.oldTextTrigger = plugins.TextTrigger(argDict["old"])
        self.newText = argDict["new"].replace("\\n", "\n")
        self.stems = []
        fileStr = argDict.get("file")
        if fileStr:
            self.stems = plugins.commasplit(fileStr)

    def __repr__(self):
        return "Replacing " + self.oldTextTrigger.text + " with " + self.newText + " for"

    def __call__(self, test):
        for stem in self.stems:
            for stdFile in test.getFileNamesMatching(stem):
                if os.path.isfile(stdFile):
                    self.replaceInFile(test, stdFile)

    def replaceInFile(self, test, stdFile):
        fileName = os.path.basename(stdFile)
        self.describe(test, " - file " + fileName)
        sys.stdout.flush()
        unversionedFileName = ".".join(fileName.split(".")[:2])
        tmpFile = os.path.join(test.getDirectory(temporary=1), unversionedFileName)
        with open(tmpFile, "w") as writeFile:
            for line in open(stdFile).xreadlines():
                writeFile.write(self.oldTextTrigger.replace(line, self.newText))

    def usesComparator(self):
        return True

    def setUpSuite(self, suite):
        self.describe(suite)

    def setUpApplication(self, app):
        if len(self.stems) == 0:
            logFile = app.getConfigValue("log_file")
            if not logFile in self.stems:
                self.stems.append(logFile)                
            

class ExportTests(plugins.ScriptWithArgs):
    scriptDoc = "Export the selected tests to a different test suite"
    def __init__(self, args):
        argDict = self.parseArguments(args, [ "dest" ])
        self.otherTTHome = argDict.get("dest")
        self.otherSuites = {}
        self.placements = {}
        if not self.otherTTHome:
            raise plugins.TextTestError, "Must provide 'dest' argument to indicate where tests should be exported"
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
        stdFiles, defFiles = test.listStandardFiles(allVersions=True)
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
