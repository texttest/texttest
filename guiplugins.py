
import plugins, os, sys, shutil

# The class to inherit from if you want test-based actions that can run from the GUI
class InteractiveAction(plugins.Action):
    def __init__(self, test):
        self.test = test
        self.options = {}
        self.switches = {}
        self.processes = []
    def killProcesses(self):
        # Don't leak processes
        for process in self.processes:
            if not process.hasTerminated():
                print "Killing '", process.program + "' interactive process"
                process.kill()
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
        process = plugins.BackgroundProcess(commandLine)
        self.processes.append(process)
        return process
    def viewFile(self, fileName, wait = 0):
        viewProgram = self.test.app.getConfigValue("view_program")
        print "Viewing file", os.path.basename(fileName), "using '" + viewProgram + "'"
        process = self.startExternalProgram(viewProgram + " " + fileName)
        if wait:
            process.waitForTermination()
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
        if test:
            if test and test.state >= test.RUNNING:
                self.switches["rdt"] = Switch("Include Run-dependent Text", 0)
                self.switches["nf"] = Switch("Show differences where present", 1)
            if test and test.state == test.RUNNING:
                self.switches["f"] = Switch("Follow file rather than view it", 1)
            self.setProgramDefaults(test.app)
    def __repr__(self):
        return "Viewing file"
    def setProgramDefaults(self, app):
        if os.name == "posix":
            app.setConfigDefault("view_program", "xemacs")
            app.setConfigDefault("diff_program", "tkdiff")
            app.setConfigDefault("follow_program", "tail -f")
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
    def followFile(self, fileName):
        baseName = os.path.basename(fileName)
        title = self.test.name + " (" + baseName + ")"
        followProgram = self.test.app.getConfigValue("follow_program")
        print "Following file", title, "using '" + followProgram + "'"
        commandLine = "xterm -bg white -T '" + title + "' -e " + followProgram + " " + fileName
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
            diffProgram = self.test.app.getConfigValue("diff_program")
            print "Comparing file", os.path.basename(newFile), "with previous version using '" + diffProgram + "'"
            self.startExternalProgram("tkdiff " + self.stdFile(comparison) + " " + newFile)

# And a generic import test. Note acts on test suites
class ImportTest(InteractiveAction):
    def __init__(self, suite):
        InteractiveAction.__init__(self, suite)
        if self.canPerformOnTest():
            self.options["name"] = TextOption(self.testType() + " Name")
            self.options["desc"] = TextOption(self.testType() + " Description")
    def canPerformOnTest(self):
        return self.test and self.test.state == self.test.NOT_STARTED
    def getTitle(self):
        return "Add " + self.testType()
    def getOptionTitle(self):
        return "Adding " + self.testType()
    def testType(self):
        return ""
    def setUpSuite(self, suite):
        testName = self.options["name"].getValue()
        print "Adding", self.testType(), testName, "under test suite", suite
        testDir = self.createTest(suite, testName, self.options["desc"].getValue())
        self.createTestContents(suite, testDir)
        newTest = suite.addTest(testName, testDir)
        self.recordResults(newTest)
    def createTestContents(self, suite, testDir):
        pass
    def recordResults(self, newTest):
        pass
    def createTest(self, suite, testName, description):
        file = open(suite.testCaseFile, "a")
        file.write(os.linesep)
        file.write("# " + description + os.linesep)
        file.write(testName + os.linesep)
        testDir = os.path.join(suite.abspath, testName.strip())
        os.mkdir(testDir)
        return testDir
    
class ImportTestCase(ImportTest):
    def __init__(self, suite):
        ImportTest.__init__(self, suite)
        if self.canPerformOnTest():
            self.addOptionsFileOption()
            suite.app.setConfigDefault("use_standard_input", not self.appIsGUI())
            if self.appIsGUI():
                self.switches["editsc"] = Switch("Change user abilities (edit GUI script)")
            if suite.app.getConfigValue("use_standard_input"):
                self.switches["editin"] = Switch("Create standard input file", not self.appIsGUI())
            self.switches["editlog"] = Switch("Change system behaviour (edit log file)")
    def testType(self):
        return "Test"
    def appIsGUI(self):
        return 0
    def addOptionsFileOption(self):
        self.options["opt"] = TextOption("Command line options")
    def createTestContents(self, suite, testDir):
        self.writeOptionFile(suite, testDir)
        self.writeInputFile(suite, testDir)
    def recordResults(self, newTest):
        if self.appIsGUI():
            self.recordGUIActions(newTest)

        self.recordStandardResult(newTest)
    def recordGUIActions(self, test):
        print "Record your actions using the", test.app.fullName, "GUI..."
        test.app.makeWriteDirectory()
        test.makeBasicWriteDirectory()
        test.setUpEnvironment(parents=1)
        os.chdir(test.writeDirs[0])
        command = test.getExecuteCommand()
        recordCommand = self.getRecordCommand(command, test.abspath)
        os.system(recordCommand)
        test.tearDownEnvironment(parents=1)
        test.app.removeWriteDirectory()
        if self.switches["editsc"].getValue():
            self.viewFile(os.path.join(test.abspath, "gui_script"), wait=1)
    def recordStandardResult(self, test):
        print "Running test", test, "to get standard behaviour..."
        progName = sys.argv[0]
        stdout = os.popen("python " + progName + " -a " + test.app.name + " -o -t " + test.name)
        for line in stdout.readlines():
            sys.stdout.write("> " + line)
        if self.switches["editlog"].getValue():
            test.app.setConfigDefault("log_file", "output")
            logFile = test.makeFileName(test.app.getConfigValue("log_file"))
            self.viewFile(logFile, wait=1)
    def writeOptionFile(self, suite, testDir):
        optionString = self.getOptions()
        print "Using option string :", optionString
        optionFile = open(os.path.join(testDir, "options." + suite.app.name), "w")
        optionFile.write(optionString)
        if self.appIsGUI():
            optionFile.write(" " + self.getReplayOption())
        optionFile.write(os.linesep)
        return optionString
    def writeInputFile(self, suite, testDir):
        if not self.switches.has_key("editin") or not self.switches["editin"].getValue():
            return
        inputFile = os.path.join(testDir, "input." + suite.app.name)
        file = open(inputFile, "w")
        file.write("<Enter standard input lines in this file>" + os.linesep)
        file.close()
        self.viewFile(inputFile, wait=1)
    def getOptions(self):
        return self.options["opt"].getValue()
    # We assume tested GUIs support record and replay. These default to command
    # line -replay and -record
    def getReplayOption(self):
        return "-replay gui_script"
    def getRecordCommand(self, command, testDir):
        return command.replace(self.getReplayOption(), "-record " + os.path.join(testDir, "gui_script"))

class ImportTestSuite(ImportTest):
    def __init__(self, suite):
        ImportTest.__init__(self, suite)
        if self.canPerformOnTest():
            self.switches["env"] = Switch("Add environment file")
    def testType(self):
        return "Suite"
    def createTestContents(self, suite, testDir):
        self.writeTestcasesFile(suite, testDir)
        if self.switches["env"].getValue():
            self.writeEnvironmentFile(suite, testDir)
    def writeTestcasesFile(self, suite, testDir):
        testCasesFile = os.path.join(testDir, "testsuite." + suite.app.name)        
        file = open(testCasesFile, "w")
        file.write("# Ordered list of tests in test suite. Add as appropriate" + os.linesep + os.linesep)
    def writeEnvironmentFile(self, suite, testDir):
        envFile = os.path.join(testDir, "environment")
        file = open(envFile, "w")
        file.write("# Dictionary of environment to variables to set in test suite" + os.linesep)

# Placeholder for all classes. Remember to add them!
class InteractiveActionHandler:
    def __init__(self):
        self.testClasses =  [ SaveTest ]
        self.suiteClasses = [ ImportTestCase, ImportTestSuite ]
    def getInstances(self, test):
        instances = []
        classList = self.getClassList(test)
        for intvActionClass in classList:
            instance = self.makeInstance(intvActionClass, test)
            instances.append(instance)
        return instances
    def getClassList(self, test):
        if test.classId() == "test-case":
            return self.testClasses
        else:
            return self.suiteClasses
    def makeInstance(self, className, test):
        test.app.setConfigDefault("interactive_action_module", test.app.getConfigValue("config_module"))
        module = test.app.getConfigValue("interactive_action_module")
        command = "from " + module + " import " + className.__name__ + " as realClassName"
        try:
            exec command
            return realClassName(test)
        except ImportError:
            return className(test)
        
interactiveActionHandler = InteractiveActionHandler()

        

