
import plugins, os, sys, shutil, string

# The class to inherit from if you want test-based actions that can run from the GUI
class InteractiveAction(plugins.Action):
    processes = []    
    def __init__(self, test, oldOptionGroup, optionName = ""):
        self.test = test
        self.optionGroup = plugins.OptionGroup(optionName, test.getConfigValue("gui_entry_overrides"), test.getConfigValue("gui_entry_options"))
    def getOptionGroups(self):
        return [ self.optionGroup ]
    def addOption(self, oldOptionGroup, key, name, value = "", possibleValues = []):
        if oldOptionGroup and oldOptionGroup.options.has_key(key):
            self.optionGroup.addOption(key, name, oldOptionGroup.getOptionValue(key), possibleValues)
        else:
            self.optionGroup.addOption(key, name, value, possibleValues)
    def addSwitch(self, oldOptionGroup, key, name, value = 0, nameForOff = None):
        if oldOptionGroup and oldOptionGroup.switches.has_key(key):
            self.optionGroup.addSwitch(key, name, oldOptionGroup.getSwitchValue(key), nameForOff)
        else:
            self.optionGroup.addSwitch(key, name, value, nameForOff)
    def canPerformOnTest(self):
        return self.test
    def getTitle(self):
        return None
    def matchesMode(self, dynamic):
        return 1
    def getScriptTitle(self):
        return self.getTitle()
    def startExternalProgram(self, commandLine, shellTitle = None, shellOptions = "", exitHandler=None, exitHandlerArgs=()):
        if shellTitle:
            commandLine = "xterm " + shellOptions + " -bg white -T '" + shellTitle + "' -e " + commandLine
        process = plugins.BackgroundProcess(commandLine, exitHandler=exitHandler, exitHandlerArgs=exitHandlerArgs)
        self.processes.append(process)
        return process
    def viewFile(self, fileName, wait = 0, refresh=0):
        viewProgram = self.test.getConfigValue("view_program")
        baseName = os.path.basename(fileName)
        guilog.info("Viewing file " + baseName + " using '" + viewProgram + "', refresh set to " + str(refresh))
        exitHandler = None
        if refresh:
            exitHandler = self.test.filesChanged
        commandLine = viewProgram + " " + fileName
        if viewProgram.endswith("emacs"):
            # Emacs dumps junk on standard error - this is annoying!
            commandLine += " 2> /dev/null"
        process = self.startExternalProgram(commandLine, exitHandler=exitHandler)
        if wait:
            process.waitForTermination()
    def getTextTestName(self):
        return "python " + sys.argv[0]
    def describe(self, testObj, postText = ""):
        guilog.info(testObj.getIndent() + repr(self) + " " + repr(testObj) + postText)
    
# Plugin for saving tests (standard)
class SaveTest(InteractiveAction):
    def __init__(self, test, oldOptionGroup):
        InteractiveAction.__init__(self, test, oldOptionGroup, "Saving")
        self.comparisons = []
        if self.canPerformOnTest():
            extensions = test.app.getVersionFileExtensions(forSave = 1)
            # Include the default version always
            extensions.append("")
            self.addOption(oldOptionGroup, "v", "Version to save", test.app.getFullVersion(forSave = 1), extensions)
            self.addSwitch(oldOptionGroup, "over", "Replace successfully compared files also", 0)
            self.comparisons = test.state.getComparisons()
            multipleComparisons = (len(self.comparisons) > 1)
            if self.hasPerformance():
                self.addSwitch(oldOptionGroup, "ex", "Exact Performance", multipleComparisons, "Average Performance")
            if multipleComparisons:
                failedStems = [ comp.stem for comp in self.comparisons]
                self.addOption(oldOptionGroup, "sinf", "Save single file", possibleValues=failedStems)
    def __repr__(self):
        return "Saving"
    def canPerformOnTest(self):
        return self.isSaveable(self.test)
    def isSaveable(self, test):
        return test and test.state.isSaveable()
    def getTitle(self):
        return "Save"
    def matchesMode(self, dynamic):
        return dynamic
    def hasPerformance(self):
        for comparison in self.comparisons:
            if comparison.getType() != "failure" and comparison.hasDifferences():
                return 1
        return 0
    def getExactness(self):
        return self.optionGroup.getSwitchValue("ex", 1)
    def __call__(self, test):
        version = self.optionGroup.getOptionValue("v")
        saveDesc = " - version " + version + ", exactness " + str(self.getExactness())
        singleFile = self.optionGroup.getOptionValue("sinf")
        if singleFile:
            saveDesc += ", only file with stem " + singleFile
        overwriteSuccess = self.optionGroup.getSwitchValue("over")
        if overwriteSuccess:
            saveDesc += ", overwriting both failed and succeeded files"
        self.describe(test, saveDesc)
        testComparison = test.state
        if testComparison:
            if singleFile:
                testComparison.saveSingle(singleFile, self.getExactness(), version)
            else:
                testComparison.save(self.getExactness(), version, overwriteSuccess)
            test.notifyChanged()

# Plugin for viewing files (non-standard). In truth, the GUI knows a fair bit about this action,
# because it's special and plugged into the tree view. Don't use this as a generic example!
class ViewFile(InteractiveAction):
    def __init__(self, test, oldOptionGroup):
        InteractiveAction.__init__(self, test, oldOptionGroup, "Viewing")
        try:
            if test.state.hasStarted():
                self.addSwitch(oldOptionGroup, "rdt", "Include Run-dependent Text", 0)
                self.addSwitch(oldOptionGroup, "nf", "Show differences where present", 1)
                if not test.state.isComplete():
                    self.addSwitch(oldOptionGroup, "f", "Follow file rather than view it", 1)
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
            baseName = os.path.basename(fileName)
            refresh = baseName.startswith("testsuite.") or baseName.startswith("options.")
            return self.viewFile(fileName, refresh=refresh)
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
    def __init__(self, suite, oldOptionGroup):
        InteractiveAction.__init__(self, suite, oldOptionGroup, self.getTabTitle())
        if self.canPerformOnTest():
            self.optionGroup.addOption("name", self.getNameTitle(), self.getDefaultName(suite))
            self.optionGroup.addOption("desc", self.getDescTitle(), self.getDefaultDesc(suite))
    def getNameTitle(self):
        return self.testType() + " Name"
    def getDescTitle(self):
        return self.testType() + " Description"
    def getDefaultName(self, suite):
        return ""
    def getDefaultDesc(self, suite):
        return ""
    def getTabTitle(self):
        return "Adding " + self.testType()
    def getTitle(self):
        return "Add " + self.testType()
    def testType(self):
        return ""
    def getNewTestName(self):
        # Overwritten in subclasses - occasionally it can be inferred
        return self.optionGroup.getOptionValue("name")
    def setUpSuite(self, suite):
        testName = self.getNewTestName()
        if len(testName) == 0:
            raise plugins.TextTestError, "No name given for new " + self.testType() + "!" + os.linesep + \
                  "Fill in the 'Adding " + self.testType() + "' tab below."
        guilog.info("Adding " + self.testType() + " " + testName + " under test suite " + repr(suite))
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
    def __init__(self, test, oldOptionGroup):
        InteractiveAction.__init__(self, test, oldOptionGroup, "Recording")
        self.addSwitch(oldOptionGroup, "hold", "Hold record shell after recording")
    def __call__(self, test):
        description = "Running " + test.app.fullName + " in order to capture user actions..."
        guilog.info(description)
        test.app.makeWriteDirectory()
        test.makeBasicWriteDirectory()
        test.setRecordEnvironment()
        test.prepareBasicWriteDirectory()
        test.setUpEnvironment(parents=1)
        os.chdir(test.writeDirs[0])
        recordCommand = test.getExecuteCommand()
        shellTitle = None
        shellOptions = ""
        if test.getConfigValue("use_standard_input"):
            shellTitle = description
        else:
            logFile = os.path.join(test.app.writeDirectory, "record_run.log")
            errFile = os.path.join(test.app.writeDirectory, "record_errors.log")
            recordCommand +=  " > " + logFile + " 2> " + errFile
        shellOptions = ""
        if self.optionGroup.getSwitchValue("hold"):
            shellOptions = "-hold"
        process = self.startExternalProgram(recordCommand, shellTitle, shellOptions)
        process.waitForTermination()
        test.tearDownEnvironment(parents=1)
        test.app.removeWriteDirectory()
        if not os.path.isfile(test.useCaseFile):
            if not plugins.BackgroundProcess.fakeProcesses: # do not make this check when running self tests
                raise plugins.TextTestError, "Recording did not produce a usecase file"

        test.state.freeText = "Recorded use case - now attempting to replay in the background to collect standard files" + \
                              os.linesep + "These will appear shortly. You do not need to submit the test manually."
        test.notifyChanged()
        ttOptions = self.getRunOptions(test)
        commandLine = self.getTextTestName() + " " + ttOptions + " > /dev/null 2>&1"
        guilog.info("Starting replay TextTest with options : " + ttOptions)
        process = self.startExternalProgram(commandLine, exitHandler=self.setTestReady, exitHandlerArgs=(test,))
    def setTestReady(self, test):
        test.state.freeText = "Recorded use case and collected all standard files"
        test.notifyChanged()
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
    def __init__(self, suite, oldOptionGroup):
        ImportTest.__init__(self, suite, oldOptionGroup)
        if self.canPerformOnTest():
            self.addOptionsFileOption(oldOptionGroup)
    def testType(self):
        return "Test"
    def addOptionsFileOption(self, oldOptionGroup):
        self.addOption(oldOptionGroup, "opt", "Command line options")
    def createTestContents(self, suite, testDir):
        self.writeOptionFile(suite, testDir)
        self.writeEnvironmentFile(suite, testDir)
        self.writeResultsFiles(suite, testDir)
    def getWriteFile(self, name, suite, testDir):
        return open(os.path.join(testDir, name + "." + suite.app.name), "w")
    def writeEnvironmentFile(self, suite, testDir):
        envDir = self.getEnvironment(suite)
        if len(envDir) == 0:
            return
        envFile = self.getWriteFile("environment", suite, testDir)
        for var, value in envDir.items():
            guilog.info("Setting test env: " + var + " = " + value)
            envFile.write(var + ":" + value + os.linesep)
        envFile.close()
    def writeOptionFile(self, suite, testDir):
        optionString = self.getOptions(suite)
        guilog.info("Using option string : " + optionString)
        optionFile = self.getWriteFile("options", suite, testDir)
        optionFile.write(optionString + os.linesep)
        return optionString
    def getOptions(self, suite):
        return self.optionGroup.getOptionValue("opt")
    def getEnvironment(self, suite):
        return {}
    def writeResultsFiles(self, suite, testDir):
        # Cannot do anything in general
        pass

class ImportTestSuite(ImportTest):
    def __init__(self, suite, oldOptionGroup):
        ImportTest.__init__(self, suite, oldOptionGroup)
        if self.canPerformOnTest():
            self.addEnvironmentFileOptions(oldOptionGroup)
    def testType(self):
        return "Suite"
    def createTestContents(self, suite, testDir):
        self.writeTestcasesFile(suite, testDir)
        self.writeEnvironmentFiles(suite, testDir)
    def writeTestcasesFile(self, suite, testDir):
        testCasesFile = os.path.join(testDir, "testsuite." + suite.app.name)        
        file = open(testCasesFile, "w")
        file.write("# Ordered list of tests in test suite. Add as appropriate" + os.linesep + os.linesep)
    def addEnvironmentFileOptions(self, oldOptionGroup):
        self.addSwitch(oldOptionGroup, "env", "Add environment file")
    def writeEnvironmentFiles(self, suite, testDir):
        if self.optionGroup.getSwitchValue("env"):
            envFile = os.path.join(testDir, "environment")
            file = open(envFile, "w")
            file.write("# Dictionary of environment to variables to set in test suite" + os.linesep)

class SelectTests(InteractiveAction):
    def __init__(self, app, oldOptionGroup):
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
        version = self.optionGroup.getOptionValue("vs")
        appToUse = app
        fullVersion = app.getFullVersion()
        if fullVersion.find(version) == -1:
            if len(fullVersion) > 0:
                version += "." + fullVersion
            appToUse = app.createCopy(version)
        appToUse.configObject.updateOptions(self.optionGroup)
        valid, testSuite = appToUse.createTestSuite()
        for test in testSuite.testCaseList():
            test.app = app
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
    def __init__(self, app, oldOptionGroup):
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
        self.startExternalProgram(commandLine, exitHandler=self.checkTestRun, exitHandlerArgs=(errFile,))
    def checkTestRun(self, errFile):
        if os.path.isfile(errFile):
            errText = open(errFile).read()
            if len(errText):
                raise plugins.TextTestError, "Dynamic run failed, with the following errors:" + os.linesep + errText
    def getTextTestOptions(self, app, selTests):
        ttOptions = [ "-a " + app.name ]
        ttOptions += self.invisibleGroup.getCommandLines()
        for group in self.optionGroups:
            ttOptions += group.getCommandLines()
        selTestPaths = []
        for test in selTests:
            relPath = test.getRelPath()
            if not relPath in selTestPaths:
                selTestPaths.append(relPath)
        ttOptions.append("-tp " + string.join(selTestPaths, ","))
        return ttOptions

class EnableDiagnostics(InteractiveAction):
    def __init__(self, test, oldOptionGroup):
        InteractiveAction.__init__(self, test, oldOptionGroup)
        configDir = test.app.getConfigValue("diagnostics")
        self.configFile = None
        if configDir.has_key("configuration_file"):
            self.configFile = configDir["configuration_file"]
    def __repr__(self):
        return "Diagnostics"
    def getTitle(self):
        return "Diagnostics"
    def getScriptTitle(self):
        return "Enable Diagnostics"
    def matchesMode(self, dynamic):
        return not dynamic
    def canPerformOnTest(self):
        return self.test and self.configFile
    def __call__(self, test):
        diagDir = os.path.join(test.abspath, "Diagnostics")
        if not os.path.isdir(diagDir):
            os.mkdir(diagDir)
        diagFile = os.path.join(test.app.abspath, self.configFile)
        targetDiagFile = os.path.join(diagDir, self.configFile)
        shutil.copyfile(diagFile, targetDiagFile)
        self.viewFile(targetDiagFile, refresh=1)

class CopyTest(ImportTest):
    def __repr__(self):
        return "Copy"
    def testType(self):
        return "Test"
    def getTabTitle(self):
        return "Copying"
    def getNameTitle(self):
        return "Name of copied test"
    def getDescTitle(self):
        return "Description of new test"
    def getDefaultName(self, test):
        return test.name + "_copy"
    def getDefaultDesc(self, test):
        return "Copy of " + test.name
    def getTitle(self):
        return "Copy"
    def getScriptTitle(self):
        return "Copy Test"
    def __call__(self, test):
        suite = test.parent
        self.setUpSuite(suite)
    def createTestContents(self, suite, testDir):
        for file in os.listdir(self.test.abspath):
            if suite.app.ownsFile(file):
                sourceFile = os.path.join(self.test.abspath, file)
                targetFile = os.path.join(testDir, file)
                shutil.copyfile(sourceFile, targetFile)
    
# Placeholder for all classes. Remember to add them!
class InteractiveActionHandler:
    def __init__(self):
        self.testClasses =  [ SaveTest, RecordTest, EnableDiagnostics, CopyTest ]
        self.suiteClasses = [ ImportTestCase, ImportTestSuite ]
        self.appClasses = [ SelectTests, RunTests, ResetGroups ]
        self.optionGroupMap = {}
    def getInstance(self, test, className):
        instance = self.makeInstance(className, test)
        self.storeOptionGroup(className, instance)
        return instance
    def storeOptionGroup(self, className, instance):
        if len(instance.getOptionGroups()) == 1:
            self.optionGroupMap[className] = instance.getOptionGroups()[0]
    def getInstances(self, test, dynamic):
        instances = []
        classList = self.getClassList(test)
        for intvActionClass in classList:
            instance = self.makeInstance(intvActionClass, test)
            if instance.matchesMode(dynamic):
                self.storeOptionGroup(intvActionClass, instance)
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
        oldOptionGroup = []
        if self.optionGroupMap.has_key(className):
            oldOptionGroup = self.optionGroupMap[className]
        try:
            exec command
            return realClassName(test, oldOptionGroup)
        except ImportError:
            return className(test, oldOptionGroup)
        except:
            # If some invalid interactive action is provided, need to know which
            print "Error with interactive action", className.__name__
            raise sys.exc_type, sys.exc_value
        
interactiveActionHandler = InteractiveActionHandler()
guilog = None

def setUpGuiLog():
    global guilog
    guilog = plugins.getDiagnostics("GUI behaviour")
