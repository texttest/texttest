#!/usr/local/bin/python

helpDescription = """
The default configuration is the simplest and most portable. It is intended to run on
any architecture. Therefore, differences in results are displayed using Python's ndiff
module, the most portable differencing tool I can find, anyway.

Its default behaviour is to run all tests on the local machine.
"""

helpOptions = """
-i         - run in interactive mode. This means that the framework will interleave running and comparing
             the tests, so that test 2 is not run until test 1 has been run and compared.

-o         - run in overwrite mode. This means that the interactive dialogue is replaced by simply
             overwriting all previous results with new ones.

-n         - run in new-file mode. Tests that succeed will still overwrite the standard file, rather than
             leaving it, as is the deafult behaviour.

-reconnect <fetchdir:user>
            - Reconnect to already run tests, optionally takes a directory and user from which to
              fetch temporary files.

-t <text>  - only run tests whose names contain <text> as a substring

-f <file>  - only run tests whose names appear in the file <file>
"""

import os, re, shutil, plugins, respond, comparetest, string

def getConfig(optionMap):
    return Config(optionMap)

class Config(plugins.Configuration):
    def getOptionString(self):
        return "iont:f:"
    def getActionSequence(self):
        actions = [ self.getTestRunner(), self.getTestEvaluator() ]
        if self.optionMap.has_key("i"):
            return [ plugins.CompositeAction(actions) ]
        else:
            return actions
    def getFilterList(self):
        filters = []
        self.addFilter(filters, "t", TestNameFilter)
        self.addFilter(filters, "f", FileFilter)
        return filters
    def isReconnecting(self):
        return self.optionMap.has_key("reconnect")
    def getTestRunner(self):
        if self.isReconnecting():
            return ReconnectTest(self.optionValue("reconnect"))
        else:
            return RunTest()
    def getTestEvaluator(self):
        subParts = [ self.getTestCollator(), self.getTestComparator(), self.getTestResponder() ]
        return plugins.CompositeAction(subParts)
    def getTestCollator(self):
        # Won't do anything, of course
        return plugins.Action()
    def getTestComparator(self):
        return comparetest.MakeComparisons(self.optionMap.has_key("n"))
    def getTestResponder(self):
        if self.optionMap.has_key("o"):
            return respond.OverwriteOnFailures(self.optionValue("v"))
        else:
            return respond.InteractiveResponder()
    # Utilities, which prove useful in many derived classes
    def optionValue(self, option):
        if self.optionMap.has_key(option):
            return self.optionMap[option]
        else:
            return ""
    def addFilter(self, list, optionName, filterObj):
        if self.optionMap.has_key(optionName):
            list.append(filterObj(self.optionMap[optionName]))
    def printHelpScripts(self):
        pass
    def printHelpDescription(self):
        print helpDescription, comparetest.helpDescription, respond.helpDescription
    def printHelpOptions(self, builtInOptions):
        print helpOptions, builtInOptions
    def printHelpText(self, builtInOptions):
        self.printHelpDescription()
        print "Command line options supported :"
        print "--------------------------------"
        self.printHelpOptions(builtInOptions)
        print "Python scripts: (as given to -s <module>.<class> [args])"
        print "--------------------------------"
        self.printHelpScripts()

class TextFilter(plugins.Filter):
    def __init__(self, filterText):
        self.texts = filterText.split(",")
    def containsText(self, test):
        for text in self.texts:
            if test.name.find(text) != -1:
                return 1
        return 0
    def equalsText(self, test):
        return test.name in self.texts
    
class TestNameFilter(TextFilter):
    def acceptsTestCase(self, test):
        return self.containsText(test)
    
class FileFilter(TextFilter):
    def __init__(self, filterFile):
        self.texts = map(string.strip, open(filterFile).readlines())
    def acceptsTestCase(self, test):
        return self.equalsText(test)

# Use communication channels for stdin and stderr (because we don't know how to redirect these on windows).
# Tried to use communication channels on all three, but read() blocks and deadlock between stderr and stdout can result.
class RunTest(plugins.Action):
    def __repr__(self):
        return "Running"
    def __call__(self, test):
        self.describe(test)
        outfile = test.getTmpFileName("output", "w")
        stdin, stdout, stderr = os.popen3(self.getExecuteCommand(test) + " > " + outfile)
        inputFileName = test.getInputFileName()
        if os.path.isfile(inputFileName):
            inputData = open(inputFileName).read()
            stdin.write(inputData)
        stdin.close()
        errfile = open(test.getTmpFileName("errors", "w"), "w")
        errfile.write(stderr.read())
        errfile.close()
        #needed to be sure command is finished
        try:
            os.wait()
        except AttributeError:
            pass # Wait doesn't exist on Windows, but seems necessary on UNIX
    def getExecuteCommand(self, test):
        return test.getExecuteCommand()
    def setUpSuite(self, suite):
        self.describe(suite)

class ReconnectTest(plugins.Action):
    def __init__(self, fetchOption):
        self.fetchDir = None
        self.fetchUser = None
        if len(fetchOption) > 0:
            if fetchOption.find(":") != -1:
                parts = fetchOption.split(":")
                self.fetchDir = parts[0]
                self.fetchUser = parts[1]
            else:
                self.fetchDir = fetchOption
    def __repr__(self):
        return "Reconnect to"
    def findTestDir(self, test):
        configFile = "config." + test.app.name
        testCaseDir = test.abspath.replace(test.app.abspath + os.sep, "")
        parts = test.app.abspath.split(os.sep)
        for ix in range(len(parts)):
            if ix == 0:
                findDir = self.fetchDir
            else:
                backIx = -1 * (ix + 1)
                findDir = os.path.join(self.fetchDir, string.join(parts[backIx:], os.sep))
            if os.path.isfile(os.path.join(findDir, configFile)):
                return os.path.join(findDir, testCaseDir)
        return None
    def newResult(self, test, file):
        if file.find("." + test.app.name) == -1:
            return 0
        stem = file.split(".")[0]
        pathStandardFile = test.makeFileName(stem)
        if pathStandardFile.split(os.sep)[-1] != file:
            return 0
        if os.path.isfile(pathStandardFile):
            return 0
        return 1
    def __call__(self, test):
        translateUser = 0
        okFlag = 1
        if self.fetchDir == None or not os.path.isdir(self.fetchDir):
            testDir = test.abspath
        else:
            testDir = self.findTestDir(test)
        if testDir == None:
            self.describe(test, "Failed!")
            return
        pattern = "." + test.app.name
        if self.fetchUser != None:
            pattern += self.fetchUser
            translateUser = 1
        else:
            pattern += test.getTestUser()
        rexp = re.compile(pattern + "[0-9][0-9]:[0-9][0-9]:[0-9][0-9]$")
        stemsFound = []
        multiStems = []
        for file in os.listdir(testDir):
            if rexp.search(file, 1) or self.newResult(test, file):
                srcFile = os.path.join(testDir, file)
                stem = file.split(".")[0]
                targetFile = stem + "." + test.app.name + test.getTmpExtension()
                if stem in stemsFound:
                    okFlag = 0
                    if not stem in multiStems:
                        multiStems.append(stem)
                    try:
                        os.remove(os.path.join(test.abspath, targetFile))
                    except:
                        pass
                else:
                    if translateUser == 1:
                        targetFile = test.getTmpFileName(stem, "w")
                    targetFile = os.path.join(test.abspath, targetFile)
                    if srcFile != targetFile:
                        shutil.copyfile(srcFile, targetFile)
                stemsFound.append(stem)
        if okFlag:
            self.describe(test)
        else:
            self.describe(test, ", failed for multiple: " + string.join(multiStems, ",") + " files")

    def setUpSuite(self, suite):
        self.describe(suite)
