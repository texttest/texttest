
import plugins, os, sys, shutil, string

# The class to inherit from if you want test-based actions that can run from the GUI
class InteractiveAction(plugins.Action):
    processes = []    
    def __init__(self, test, optionName = ""):
        self.test = test
        self.optionGroup = plugins.OptionGroup(optionName, test.getConfigValue("gui_entry_overrides"))
    def getOptionGroups(self):
        return [ self.optionGroup ]
    def canPerformOnTest(self):
        return self.test
    def getTitle(self):
        return None
    def matchesMode(self, dynamic):
        return 1
    def getScriptTitle(self):
        return self.getTitle()
    def startExternalProgram(self, commandLine, shellTitle = None, shellOptions = ""):
        if shellTitle:
            commandLine = "xterm " + shellOptions + " -bg white -T '" + shellTitle + "' -e " + commandLine
        process = plugins.BackgroundProcess(commandLine)
        self.processes.append(process)
        return process
    def viewFile(self, fileName, wait = 0):
        viewProgram = self.test.getConfigValue("view_program")
        guilog.info("Viewing file " + os.path.basename(fileName) + " using '" + viewProgram + "'")
        process = self.startExternalProgram(viewProgram + " " + fileName)
        if wait:
            process.waitForTermination()
    def getTextTestName(self):
        return "python " + sys.argv[0]
    def describe(self, testObj, postText = ""):
        guilog.info(testObj.getIndent() + repr(self) + " " + repr(testObj) + postText)
    
# Plugin for saving tests (standard)
class SaveTest(InteractiveAction):
    def __init__(self, test):
        InteractiveAction.__init__(self, test, "Saving")
        if self.canPerformOnTest():
            extensions = test.app.getVersionFileExtensions(forSave = 1)
            self.optionGroup.addOption("v", "Version to save", test.app.getFullVersion(forSave = 1), extensions)
            self.optionGroup.addSwitch("over", "Replace successfully compared files also", 0)
            try:
                comparisonList = test.stateDetails.getComparisons()
                if self.hasPerformance(comparisonList):
                    exact = (len(comparisonList) != 1)
                    self.optionGroup.addSwitch("ex", "Exact Performance", exact, "Average Performance")
            except AttributeError:
                pass
    def __repr__(self):
        return "Saving"
    def canPerformOnTest(self):
        return self.test and self.test.state == self.test.FAILED
    def getTitle(self):
        return "Save"
    def matchesMode(self, dynamic):
        return dynamic
    def hasPerformance(self, comparisonList):
        for comparison in comparisonList:
            if comparison.getType() != "difference" and comparison.hasDifferences():
                return 1
        return 0
    def getExactness(self):
        return self.optionGroup.getSwitchValue("ex", 1)
    def __call__(self, test):
        version = self.optionGroup.getOptionValue("v")
        saveDesc = " - version " + version + ", exactness " + str(self.getExactness())
        overwriteSuccess = self.optionGroup.getSwitchValue("over")
        if overwriteSuccess:
            saveDesc += ", overwriting both failed and succeeded files"
        self.describe(test, saveDesc)
        testComparison = test.stateDetails
        if testComparison:
            testComparison.save(self.getExactness(), version, overwriteSuccess)

# Plugin for viewing files (non-standard). In truth, the GUI knows a fair bit about this action,
# because it's special and plugged into the tree view. Don't use this as a generic example!
class ViewFile(InteractiveAction):
    def __init__(self, test):
        InteractiveAction.__init__(self, test, "Viewing")
        try:
            if test.state >= test.RUNNING:
                self.optionGroup.addSwitch("rdt", "Include Run-dependent Text", 0)
                self.optionGroup.addSwitch("nf", "Show differences where present", 1)
            if test.state == test.RUNNING:
                self.optionGroup.addSwitch("f", "Follow file rather than view it", 1)
        except AttributeError:
            # Will get given applications too, don't need options there
            pass
    def __repr__(self):
        return "Viewing file"
    def canPerformOnTest(self):
        return 0
    def tmpFile(self, comparison):
        if self.optionGroup.getSwitchValue("rdt"):
            return comparison.tmpFile
        else:
            return comparison.tmpCmpFile
    def stdFile(self, comparison):
        if self.optionGroup.getSwitchValue("rdt"):
            return comparison.stdFile
        else:
            return comparison.stdCmpFile
    def followFile(self, fileName):
        baseName = os.path.basename(fileName)
        title = self.test.name + " (" + baseName + ")"
        followProgram = self.test.app.getConfigValue("follow_program")
        guilog.info("Following file " + title + " using '" + followProgram + "'")
        self.startExternalProgram(followProgram + " " + fileName, shellTitle=title)
    def view(self, comparison, fileName):
        if self.optionGroup.getSwitchValue("f"):
            return self.followFile(fileName)
        if not comparison:
            return self.viewFile(fileName)
        if self.shouldTakeDiff(comparison):
            self.takeDiff(comparison)
        else:
            self.viewFile(self.tmpFile(comparison))
    def shouldTakeDiff(self, comparison):
        if comparison.newResult() or not self.optionGroup.getSwitchValue("nf"):
            return 0
        if comparison.hasDifferences():
            return 1
        # Take diff on succeeded tests if they want run-dependent text
        return self.optionGroup.getSwitchValue("rdt")
    def takeDiff(self, comparison):
        diffProgram = self.test.app.getConfigValue("diff_program")
        stdFile = self.stdFile(comparison)
        tmpFile = self.tmpFile(comparison)
        guilog.info("Comparing file " + os.path.basename(tmpFile) + " with previous version using '" + diffProgram + "'")
        self.startExternalProgram("tkdiff " + stdFile + " " + tmpFile)

# And a generic import test. Note acts on test suites
class ImportTest(InteractiveAction):
    def __init__(self, suite):
        InteractiveAction.__init__(self, suite, "Adding " + self.testType())
        if self.canPerformOnTest():
            self.optionGroup.addOption("name", self.testType() + " Name")
            self.optionGroup.addOption("desc", self.testType() + " Description")
    def canPerformOnTest(self):
        return self.test and self.test.state == self.test.NOT_STARTED
    def getTitle(self):
        return "Add " + self.testType()
    def testType(self):
        return ""
    def setUpSuite(self, suite):
        testName = self.optionGroup.getOptionValue("name")
        if len(testName) == 0:
            raise plugins.TextTestError, "No name given for new " + self.testType() + "!" + os.linesep + \
                  "Fill in the 'Adding " + self.testType() + "' tab below."
        guilog.info("Adding " + self.testType() + testName + " under test suite " + repr(suite))
        testDir = self.createTest(suite, testName, self.optionGroup.getOptionValue("desc"))
        self.createTestContents(suite, testDir)
        newTest = suite.addTest(testName, testDir)
    def matchesMode(self, dynamic):
        return not dynamic
    def createTestContents(self, suite, testDir):
        pass
    def createTest(self, suite, testName, description):
        file = open(suite.testCaseFile, "a")
        file.write(os.linesep)
        file.write("# " + description + os.linesep)
        file.write(testName + os.linesep)
        testDir = os.path.join(suite.abspath, testName.strip())
        os.mkdir(testDir)
        return testDir

class RecordTest(InteractiveAction):
    def __call__(self, test):
        description = "Running " + test.app.fullName + " in order to capture user actions..."
        guilog.info(description)
        test.app.makeWriteDirectory()
        test.makeBasicWriteDirectory()
        test.setUpEnvironment(parents=1)
        os.chdir(test.writeDirs[0])
        logFile = os.path.join(test.app.writeDirectory, "record_run.log")
        errFile = os.path.join(test.app.writeDirectory, "record_errors.log")
        recordCommand = test.getExecuteCommand() + " --record " + test.useCaseFile + " --recinp " + test.inputFile + " > " + logFile + " 2> " + errFile
        shellTitle = None
        shellOptions = ""
        if test.getConfigValue("use_standard_input"):
            shellTitle = description
        process = self.startExternalProgram(recordCommand, shellTitle)
        process.waitForTermination()
        if os.path.isfile(errFile):
            errors = open(errFile).read()
            if len(errors):
                raise plugins.TextTestError, "Recording produced following errors: " + os.linesep + errors
        test.tearDownEnvironment(parents=1)
        test.app.removeWriteDirectory()
        ttOptions = self.getRunOptions(test)
        commandLine = self.getTextTestName() + " " + ttOptions + " > /dev/null 2>&1"
        guilog.info("Starting replay TextTest with options : " + ttOptions)
        process = self.startExternalProgram(commandLine)
        process.waitForTermination()
        test.changeState(test.UPDATED, "Recorded use case")
    def getRunOptions(self, test):
        basicOptions = "-t " + self.test.name + " -a " + self.test.app.name# + " -ts " + self.test.parent.name
        logFile = test.makeFileName(test.getConfigValue("log_file"))
        if os.path.isfile(logFile):
            return "-g " + basicOptions
        else:
            return "-o " + basicOptions
    def matchesMode(self, dynamic):
        return not dynamic
    def __repr__(self):
        return "Recording"
    def getTitle(self):
        return "Record Use-Case"
    
class ImportTestCase(ImportTest):
    def __init__(self, suite):
        ImportTest.__init__(self, suite)
        if self.canPerformOnTest():
            self.addOptionsFileOption()
    def testType(self):
        return "Test"
    def addOptionsFileOption(self):
        self.optionGroup.addOption("opt", "Command line options")
    def createTestContents(self, suite, testDir):
        self.writeOptionFile(suite, testDir)
    def writeOptionFile(self, suite, testDir):
        optionString = self.getOptions()
        guilog.info("Using option string : " + optionString)
        optionFile = open(os.path.join(testDir, "options." + suite.app.name), "w")
        optionFile.write(optionString + os.linesep)
        return optionString
    def getOptions(self):
        return self.optionGroup.getOptionValue("opt")

class ImportTestSuite(ImportTest):
    def __init__(self, suite):
        ImportTest.__init__(self, suite)
        if self.canPerformOnTest():
            self.addEnvironmentFileOptions()
    def testType(self):
        return "Suite"
    def createTestContents(self, suite, testDir):
        self.writeTestcasesFile(suite, testDir)
        self.writeEnvironmentFiles(suite, testDir)
    def writeTestcasesFile(self, suite, testDir):
        testCasesFile = os.path.join(testDir, "testsuite." + suite.app.name)        
        file = open(testCasesFile, "w")
        file.write("# Ordered list of tests in test suite. Add as appropriate" + os.linesep + os.linesep)
    def addEnvironmentFileOptions(self):
        self.optionGroup.addSwitch("env", "Add environment file")
    def writeEnvironmentFiles(self, suite, testDir):
        if self.optionGroup.getSwitchValue("env"):
            envFile = os.path.join(testDir, "environment")
            file = open(envFile, "w")
            file.write("# Dictionary of environment to variables to set in test suite" + os.linesep)

class SelectTests(InteractiveAction):
    def __init__(self, app):
        self.app = app
        self.test = app
        for group in app.optionGroups:
            if group.name.startswith("Select"):
                self.optionGroup = group
    def __repr__(self):
        return "Selecting"
    def canPerformOnTest(self):
        return 1
    def getTitle(self):
        return "Select"
    def getScriptTitle(self):
        return "Select indicated tests"
    def performOn(self, app, selTests):
        app.configObject.updateOptions(self.optionGroup)
        valid, testSuite = app.createTestSuite()
        guilog.info("Created test suite of size " + str(testSuite.size()))
        return testSuite    

class ResetGroups(InteractiveAction):
    def getTitle(self):
        return "Reset"
    def getScriptTitle(self):
        return "Reset running options"
    def performOn(self, app, selTests):
        for group in app.optionGroups:
            group.reset()
    
class RunTests(InteractiveAction):
    def __init__(self, app):
        self.app = app
        self.test = app
        self.optionGroups = []
        for group in app.optionGroups:
            if group.name.startswith("Invisible"):
                self.invisibleGroup = group
            elif not group.name.startswith("Select"):
                self.optionGroups.append(group)
    def getOptionGroups(self):
        return self.optionGroups
    def __repr__(self):
        return "Running"
    def canPerformOnTest(self):
        return 1
    def getTitle(self):
        return "Run Tests"
    def getScriptTitle(self):
        return "Run selected tests"
    def performOn(self, app, selTests):
        if len(selTests) == 0:
            raise plugins.TextTestError, "No tests selected - cannot run!"
        ttOptions = string.join(self.getTextTestOptions(app, selTests))
        app.makeWriteDirectory()
        logFile = os.path.join(app.writeDirectory, "dynamic_run.log")
        errFile = os.path.join(app.writeDirectory, "dynamic_errors.log")
        commandLine = self.getTextTestName() + " " + ttOptions + " > " + logFile + " 2> " + errFile
        print "Starting dynamic TextTest with options :", ttOptions
        self.startExternalProgram(commandLine)
    def getTextTestOptions(self, app, selTests):
        ttOptions = [ "-a " + app.name ]
        ttOptions += self.invisibleGroup.getCommandLines()
        for group in self.optionGroups:
            ttOptions += group.getCommandLines()
        ttOptions.append("-t " + string.join(selTests, ","))
        return ttOptions

# Placeholder for all classes. Remember to add them!
class InteractiveActionHandler:
    def __init__(self):
        self.testClasses =  [ SaveTest, RecordTest ]
        self.suiteClasses = [ ImportTestCase, ImportTestSuite ]
        self.appClasses = [ SelectTests, RunTests, ResetGroups ]
    def getInstances(self, test, dynamic):
        instances = []
        classList = self.getClassList(test)
        for intvActionClass in classList:
            instance = self.makeInstance(intvActionClass, test)
            if instance.matchesMode(dynamic):
                instances.append(instance)
        return instances
    def getClassList(self, test):
        if test.classId() == "test-case":
            return self.testClasses
        elif test.classId() == "test-suite":
            return self.suiteClasses
        else:
            return self.appClasses
    def makeInstance(self, className, test):
        module = test.getConfigValue("interactive_action_module")
        command = "from " + module + " import " + className.__name__ + " as realClassName"
        try:
            exec command
            return realClassName(test)
        except ImportError:
            return className(test)
        except:
            # If some invalid interactive action is provided, need to know which
            print "Error with interactive action", className.__name__
            raise sys.exc_type, sys.exc_value
        
interactiveActionHandler = InteractiveActionHandler()
guilog = None

def setUpGuiLog():
    global guilog
    guilog = plugins.getSelfTestDiagnostics("GUI behaviour", "gui_log.texttest")
