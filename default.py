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

-t <text>  - only run tests whose names contain <text> as a substring

-f <file>  - only run tests whose names appear in the file <file>
"""

import os, plugins, respond, comparetest, string

def getConfig(optionMap):
    return Config(optionMap)

class Config(plugins.Configuration):
    def getOptionString(self):
        return "iot:f:"
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
    def getTestRunner(self):
        return RunTest()
    def getTestEvaluator(self):
        subParts = [ self.getTestCollator(), self.getTestComparator(), self.getTestResponder() ]
        return plugins.CompositeAction(subParts)
    def getTestCollator(self):
        # Won't do anything, of course
        return plugins.Action()
    def getTestComparator(self):
        return comparetest.MakeComparisons()
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
    def printHelpDescription(self):
        print helpDescription, comparetest.helpDescription
    def printHelpOptions(self, builtInOptions):
        print helpOptions, builtInOptions
    def printHelpText(self, builtInOptions):
        self.printHelpDescription()
        print "Command line options supported :"
        print "--------------------------------"
        self.printHelpOptions(builtInOptions)

class TextFilter(plugins.Filter):
    def __init__(self, filterText):
        self.text = filterText
    def containsText(self, test):
        return test.name.find(self.text) != -1
    def equalsText(self, test):
        return test.name == self.text
    
class TestNameFilter(TextFilter):
    def acceptsTestCase(self, test):
        return self.containsText(test)
    
class FileFilter(plugins.Filter):
    def __init__(self, filterFile):
        self.texts = map(string.strip, open(filterFile).readlines())
    def acceptsTestCase(self, test):
        return test.name in self.texts

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
