
import plugins, os, sys, shutil

# The class to inherit from if you want test-based actions that can run from the GUI
class InteractiveAction(plugins.Action):
    allowExternalPrograms = 1
    def __init__(self, test):
        self.test = test
        self.options = {}
        self.switches = {}
    def canPerformOnTest(self):
        return self.test
    def getTitle(self):
        return None
    def getOptionTitle(self):
        return getTitle()
    def perform(self):
        pass
    # Often we want to start an external program. But that's not so good: in replay mode,
    # as there's nobody around to delete it afterwards and race conditions easily arise.
    # So we fake it...
    def startExternalProgram(self, commandLine):
        if self.allowExternalPrograms:
            os.system(commandLine)
        else:
            print "Faking start of external progam: '" + commandLine + "'"
    def readCommandLineArguments(self, args):
        for arg in args:
            if arg.find("=") != -1:
                option, value = arg.split("=")
                if self.options.has_key(option):
                    self.options[option].defaultValue = value
                else:
                    raise plugins.TextTestError, self.__name__ + " does not support option '" + option + "'"
            else:
                if self.switches.has_key(arg):
                    oldValue = self.switches[arg].defaultValue
                    # Toggle the value from the default
                    self.switches[arg].defaultValue = 1 - oldValue
                else:
                    raise plugins.TextTestError, self.__name__ + " does not support switch '" + arg + "'"
 
class Option:    
    def __init__(self, name, value):
        self.name = name
        self.defaultValue = value
        self.valueMethod = None
    def getValue(self):
        if self.valueMethod:
            return self.valueMethod()
        else:
            return self.defaultValue

class TextOption(Option):
    def __init__(self, name, value = "", possibleValues = None):
        Option.__init__(self, name, value)
        self.possibleValues = possibleValues

class Switch(Option):
    def __init__(self, name, value = 0, nameForOff = None):
        Option.__init__(self, name, value)
        self.nameForOff = nameForOff

# Plugin for saving tests (standard)
class SaveTest(InteractiveAction):
    def __init__(self, test):
        InteractiveAction.__init__(self, test)
        if self.canPerformOnTest():
            extensions = test.app.getVersionFileExtensions(forSave = 1)
            self.options["v"] = TextOption("Version to save", test.app.getFullVersion(forSave = 1), extensions)
            try:
                comparisonList = test.stateDetails.getComparisons()
                if self.hasPerformance(comparisonList):
                    exact = (len(comparisonList) != 1)
                    self.switches["ex"] = Switch("Exact Performance", exact, "Average Performance")
            except AttributeError:
                pass
    def __repr__(self):
        return "Saving"
    def canPerformOnTest(self):
        return self.test and self.test.state == self.test.FAILED
    def getTitle(self):
        return "Save"
    def getOptionTitle(self):
        return "Saving"
    def hasPerformance(self, comparisonList):
        for comparison in comparisonList:
            if comparison.getType() != "difference" and comparison.hasDifferences():
                return 1
        return 0
    def getExactness(self):
        if self.switches.has_key("ex"):
            return self.switches["ex"].getValue()
        else:
            return 1
    def __call__(self, test):
        self.describe(test, " - version " + self.options["v"].getValue() + ", exactness " + str(self.getExactness()))
        testComparison = test.stateDetails
        if testComparison:
            testComparison.save(self.getExactness(), self.options["v"].getValue())

# Plugin for viewing files (non-standard). In truth, the GUI knows a fair bit about this action,
# because it's special and plugged into the tree view. Don't use this as a generic example!
class ViewFile(InteractiveAction):
    def __init__(self, test):
        InteractiveAction.__init__(self, test)
        self.switches["rdt"] = Switch("Include Run-dependent Text", 0)
        self.switches["nf"] = Switch("Show differences where present", 1)
        if test and test.state == test.RUNNING:
            self.switches["f"] = Switch("Follow file rather than view it", 1)
    def __repr__(self):
        return "Viewing file"
    def canPerformOnTest(self):
        return 0
    def getOptionTitle(self):
        return "Viewing"
    def tmpFile(self, comparison):
        if self.switches["rdt"].getValue():
            return comparison.tmpFile
        else:
            return comparison.tmpCmpFile
    def stdFile(self, comparison):
        if self.switches["rdt"].getValue():
            return comparison.stdFile
        else:
            return comparison.stdCmpFile
    def viewFile(self, fileName):
        print "Viewing file", os.path.basename(fileName)
        self.startExternalProgram("xemacs " + fileName + " &")
    def followFile(self, fileName):
        baseName = os.path.basename(fileName)
        title = self.test.name + " (" + baseName + ")"
        print "Following file", title
        commandLine = "xterm -bg white -T '" + title + "' -e tail -f " + fileName + " &"
        self.startExternalProgram(commandLine)
    def view(self, comparison, fileName):
        if self.switches.has_key("f") and self.switches["f"].getValue():
            return self.followFile(fileName)
        if not comparison:
            return self.viewFile(fileName)
        newFile = self.tmpFile(comparison)
        if comparison.newResult() or not self.switches["nf"].getValue():
            self.viewFile(newFile)
        else:
            print "Comparing file", os.path.basename(newFile), "with previous version"
            self.startExternalProgram("tkdiff " + self.stdFile(comparison) + " " + newFile + " &")


# Placeholder for all classes. Remember to add them!
interactiveActionClasses = [ SaveTest ]

# And an import test for GUI tests
class ImportTest(plugins.Action):
    def setUpSuite(self, suite):
        if suite.name.find("GUI") == -1:
            return

        testDir = self.createTest(suite)
        optionString = self.writeOptionFile(suite, testDir)
        print "Record your actions using the GUI..."
        targetApp = suite.makePathName("TargetApp", suite.abspath)
        targetAppDir = os.path.join(testDir, "TargetApp")
        shutil.copytree(targetApp, targetAppDir)
        recordOptions = optionString.replace("-replay", "-record") + " -d " + testDir
        os.system("texttest " + recordOptions)
        guiScript = os.path.join(testDir, "gui_script")
        shutil.rmtree(targetAppDir)
        print "GUI script looks like:"
        for line in open(guiScript).xreadlines():
            print line.strip()
        print "OK?"
        response = sys.stdin.readline()
        print "Running test to get standard behaviour..."
        os.system("texttest -a texttest -g -t " + os.path.basename(testDir))
    def writeOptionFile(self, suite, testDir):
        optionString = self.getOptions() + " -g -replay gui_script"
        print "Using option string :", optionString
        optionFile = open(os.path.join(testDir, "options." + suite.app.name), "w")
        optionFile.write(optionString + os.linesep)
        return optionString
    def getOptions(self):
        print "Choose target tests: (f) Single failure (v) Single failure, version 2.4"
        print "(s) Single success (m) Many tests, mixed success/failure"
        selection = sys.stdin.readline().strip()
        if selection == "f":
            return "-c CodeFailures -t A03"
        if selection == "v":
            return "-c CodeFailures -t A03 -v 2.4"
        if selection == "s":
            return "-t A02"
        return "-c CodeFailures"
    def createTest(self, suite):
        print "Enter name of test:"
        testName = sys.stdin.readline()
        print "Describe test in words:"
        description = sys.stdin.readline()
        file = open(suite.testCaseFile, "a")
        file.write(os.linesep)
        file.write("# " + description)
        file.write(testName)
        testDir = os.path.join(suite.abspath, testName.strip())
        os.mkdir(testDir)
        return testDir
        

