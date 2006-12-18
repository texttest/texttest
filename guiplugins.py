
import plugins, os, sys, shutil, string, types, time
from copy import copy
from threading import Thread
from glob import glob
from Queue import Queue, Empty
global scriptEngine
global processTerminationMonitor
from log4py import LOGLEVEL_NORMAL

# The purpose of this class is to provide a means to monitor externally
# started process, so that (a) code can be called when they exit, and (b)
# they can be terminated when TextTest is terminated.
class ProcessTerminationMonitor:
    def __init__(self):
        self.processes = []
        self.termQueue = Queue()
    def addMonitoring(self, process):
        self.processes.append(process)
        newThread = Thread(target=self.monitor, args=(process,))
        newThread.start()
    def monitor(self, process):
        process.waitForTermination()
        self.termQueue.put(process)
    def getTerminatedProcess(self):
        try:
            process = self.termQueue.get_nowait()
            self.processes.remove(process)
            return process
        except Empty:
            return None
    def listRunning(self, processesToCheck):
        running = []
        if len(processesToCheck) == 0:
            return running
        for process in self.processes:
            if not process.hasTerminated():
                for processToCheck in processesToCheck:
                    if plugins.isRegularExpression(processToCheck):
                        if plugins.findRegularExpression(processToCheck, process.description):
                            running.append("PID " + str(process.processId) + " : " + process.description)
                            break
                    elif processToCheck.lower() == "all" or process.description.find(processToCheck) != -1:
                            running.append("PID " + str(process.processId) + " : " + process.description)
                            break

        return running
    def killAll(self):
        # Don't leak processes
        for process in self.processes:
            if not process.hasTerminated():
                guilog.info("Killing '" + process.description.split()[0] + "' interactive process")
                process.killAll()

processTerminationMonitor = ProcessTerminationMonitor()
       
class InteractiveAction(plugins.Observable):
    stdInterfaceDescription = """
<menubar>
    <menu action=\"actionmenu\">
       <menuitem action=\"%s\"/>
    </menu>
</menubar>
<toolbar> 
   <toolitem action=\"%s\"/>
</toolbar>
"""
    def __init__(self, rootTestSuites):
        plugins.Observable.__init__(self)
        self.optionGroup = None
        self.apps = map(lambda suite: suite.app, rootTestSuites)
        optionName = self.getTabTitle()
        if optionName:
            self.optionGroup = plugins.OptionGroup(optionName, self.getConfigValue("gui_entry_overrides"), \
                                                   self.getConfigValue("gui_entry_options"))
    def __repr__(self):
        if self.optionGroup != None:
            return self.optionGroup.name
        else:
            return self.getSecondaryTitle()
    def getConfigValue(self, entryName):
        prevValue = None
        for app in self.apps:
            currValue = app.getConfigValue(entryName)
            if not prevValue is None and currValue != prevValue:
                plugins.printWarning("GUI configuration differs between applications, ignoring that from " + repr(app))
            else:
                prevValue = currValue
        return prevValue
    def getOptionGroups(self):
        if self.optionGroup:
            return [ self.optionGroup ]
        else:
            return []
    def updateDefaults(self, test, state):
        return False
    def isActive(self):
        return True
    def isActiveOnCurrent(self):
        return True
    def canPerform(self):
        return True # do we activate this via performOnCurrent() ?
    def getInterfaceDescription(self):
        if self.inToolBar():
            title = self.getSecondaryTitle()
            return self.stdInterfaceDescription % (title, title)    
        else:
            return ""
    def isRadio(self):
        return False;
    def isToggle(self):
        return False;
    def getStartValue(self): # For radio/toggle actions.
        return 0
    def getAccelerator(self):
        configName = self.getTitle().replace("_", "").replace(" ", "_").lower()
        accelerators = self.getConfigValue("gui_accelerators")
        return accelerators.get(configName, self.getDefaultAccelerator())
    def getDefaultAccelerator(self):
        pass
    def getStockId(self):
        pass
    def getTitle(self):
        pass
    def getSecondaryTitle(self):
        return self.getTitle().replace("_", "")
    def getTooltip(self):
        return self.getScriptTitle(False)
    def messageBeforePerform(self):
        # Don't change this by default, most of these things don't take very long
        pass
    def messageAfterPerform(self):
        return "Performed '" + self.getTooltip() + "' on " + self.describeTests() + "."
    def isFrequentUse(self):
        # Decides how accessible to make it...
        return False
    def getDoubleCheckMessage(self):
        return ""
    def inButtonBar(self):
        return False
    def inToolBar(self):
        return True
    def getTabTitle(self):
        return ""
    def getGroupTabTitle(self):
        # Default behaviour is not to create a group tab, override to get one...
        return "Test"
    def getScriptTitle(self, tab):
        baseTitle = self._getScriptTitle().replace("_", "")
        if tab and self.isFrequentUse():
            return baseTitle + " from tab"
        else:
            return baseTitle
    def _getScriptTitle(self):
        return self.getTitle()
    def addOption(self, key, name, value = "", possibleValues = [], allocateNofValues = -1, description = ""):
        self.optionGroup.addOption(key, name, value, possibleValues, allocateNofValues, description)
    def addSwitch(self, key, name, defaultValue = 0, options = [], description = ""):
        self.optionGroup.addSwitch(key, name, defaultValue, options, description)
    def startExternalProgram(self, commandLine, description = "", shellTitle = None, holdShell = 0, exitHandler=None, exitHandlerArgs=()):
        process = plugins.BackgroundProcess(commandLine, description=description, shellTitle=shellTitle, \
                                            holdShell=holdShell, exitHandler=exitHandler, exitHandlerArgs=exitHandlerArgs)
        processTerminationMonitor.addMonitoring(process)
        return process
    def startExtProgramNewUsecase(self, commandLine, usecase, \
                                  exitHandler, exitHandlerArgs, shellTitle=None, holdShell=0, description = ""): 
        recScript = os.getenv("USECASE_RECORD_SCRIPT")
        if recScript:
            os.environ["USECASE_RECORD_SCRIPT"] = plugins.addLocalPrefix(recScript, usecase)
        repScript = os.getenv("USECASE_REPLAY_SCRIPT")
        if repScript:
            # Dynamic GUI might not record anything (it might fail) - don't try to replay files that
            # aren't there...
            dynRepScript = plugins.addLocalPrefix(repScript, usecase)
            if os.path.isfile(dynRepScript):
                os.environ["USECASE_REPLAY_SCRIPT"] = dynRepScript
            else:
                del os.environ["USECASE_REPLAY_SCRIPT"]
        process = self.startExternalProgram(commandLine, description, shellTitle, holdShell, exitHandler, exitHandlerArgs)
        if recScript:
            os.environ["USECASE_RECORD_SCRIPT"] = recScript
        if repScript:
            os.environ["USECASE_REPLAY_SCRIPT"] = repScript
        return process
    def describe(self, testObj, postText = ""):
        guilog.info(testObj.getIndent() + repr(self) + " " + repr(testObj) + postText)
    def perform(self):
        message = self.messageBeforePerform()
        if message != None:
            self.notify("Status", message)
        self.notify("ActionStart", message)
        try:
            self.performOnCurrent()
            message = self.messageAfterPerform()
            if message != None:
                self.notify("Status", message)
        finally:
            self.notify("ActionStop", message)
    
class SelectionAction(InteractiveAction):
    def __init__(self, rootTestSuites):
        self.rootTestSuites = rootTestSuites
        self.currTestSelection = []
        InteractiveAction.__init__(self, rootTestSuites)
    def addFilterFile(self, fileName):
        selectionGroups = interactiveActionHandler.optionGroupMap.get(SelectTests)
        if selectionGroups:
            filterFileOption = selectionGroups[0].options["f"]
            filterFileOption.addPossibleValue(os.path.basename(fileName))
    def notifyNewTestSelection(self, tests):
        self.currTestSelection = filter(lambda test: test.classId() == "test-case", tests)
    def isActiveOnCurrent(self):
        return len(self.currTestSelection) > 0
    def describeTests(self):
        return str(len(self.currTestSelection)) + " tests"
    def getAnyApp(self):
        if len(self.currTestSelection) > 0:
            return self.currTestSelection[0].app
    def isSelected(self, test):
        return test in self.currTestSelection
    def isNotSelected(self, test):
        return not self.isSelected(test)
    def inToolBar(self):
        return self.isFrequentUse() or len(self.getOptionGroups()) == 0
    def getCmdlineOption(self):
        selTestPaths = []
        for test in self.currTestSelection:
            relPath = test.getRelPath()
            if not relPath in selTestPaths:
                selTestPaths.append(relPath)
        return "-tp " + string.join(selTestPaths, ",")
    def getCmdlineOptionForApps(self):
        apps = []
        for test in self.currTestSelection:
            if not test.app.name in apps:
                apps.append(test.app.name)
        return "-a " + string.join(apps, ",")

class Quit(InteractiveAction):
    def __init__(self, dynamic, rootSuites):
        InteractiveAction.__init__(self, rootSuites)
        self.dynamic = dynamic
    def getInterfaceDescription(self): # override for separator in toolbar
        description = "<menubar>\n<menu action=\"filemenu\">\n<menuitem action=\"" + self.getSecondaryTitle() + "\"/>\n</menu>\n</menubar>\n"
        description += "<toolbar>\n<toolitem action=\"" + self.getSecondaryTitle() + "\"/>\n<separator/>\n</toolbar>\n"
        return description
    def getStockId(self):
        return "quit"
    def getDefaultAccelerator(self):
        return "<control>q"
    def getTitle(self):
        return "_Quit"
    def messageAfterPerform(self):
        # Don't provide one, the GUI isn't there to show it :)
        pass
    def performOnCurrent(self):
        # Generate a window closedown, so that the quit button behaves the same as closing the window
        self.notify("Exit")
    def getDoubleCheckMessage(self):
        processesToReport = self.processesToReport()
        runningProcesses = processTerminationMonitor.listRunning(processesToReport)
        if len(runningProcesses) == 0:
            return ""
        else:
            return "\nThese processes are still running, and will be terminated when quitting: \n\n   + " + string.join(runningProcesses, "\n   + ") + "\n\nQuit anyway?\n"
    def processesToReport(self):
        queryValues = self.getConfigValue("query_kill_processes")
        processes = []
        if queryValues.has_key("default"):
            processes += queryValues["default"]
        if self.dynamic and queryValues.has_key("dynamic"):
            processes += queryValues["dynamic"]
        elif queryValues.has_key("static"):        
            processes += queryValues["static"]
        return processes


# The class to inherit from if you want test-based actions that can run from the GUI
class InteractiveTestAction(InteractiveAction):
    def __init__(self, rootTestSuites):
        self.currentTest = rootTestSuites[0]
        InteractiveAction.__init__(self, rootTestSuites)
    def isActiveOnCurrent(self):
        return self.currentTest is not None and self.correctTestClass()
    def correctTestClass(self):
        return self.currentTest.classId() == "test-case"
    def describeTests(self):
        return repr(self.currentTest)
    def getConfigValue(self, entryName):
        return self.currentTest.getConfigValue(entryName)
    def inToolBar(self):
        return False
    def inButtonBar(self):
        return len(self.getOptionGroups()) == 0
    def getViewCommand(self, fileName):
        stem = os.path.basename(fileName).split(".")[0]
        viewProgram = self.currentTest.getCompositeConfigValue("view_program", stem)
        if not plugins.canExecute(viewProgram):
            raise plugins.TextTestError, "Cannot find file editing program '" + viewProgram + \
                  "'\nPlease install it somewhere on your PATH or point the view_program setting at a different tool"
        cmd = viewProgram + " \"" + fileName + "\"" + plugins.nullRedirect()
        if os.name == "posix":
            cmd = "exec " + cmd # best to avoid shell messages etc.
        return cmd, viewProgram
    def getRelativeFilename(self, filename):
        # Trim the absolute filename to be relative to the application home dir
        # (TEXTTEST_HOME is more difficult to obtain, see testmodel.OptionFinder.getDirectoryName)
        return os.path.join(self.currentTest.getRelPath(), os.path.basename(filename))
    def notifyNewTestSelection(self, tests):
        if len(tests) == 1:
            self.currentTest = tests[0]
        elif len(tests) > 1:
            self.currentTest = None
    def updateDefaults(self, test, state):
        if test is self.currentTest:
            return self.updateOptionGroup(state)
        else:
            return False
    def updateOptionGroup(self, state):
        return False
    def viewFile(self, fileName, refreshContents=False, refreshFiles=False):
        exitHandler = None
        if refreshFiles:
            exitHandler = self.currentTest.filesChanged
        elif refreshContents:
            exitHandler = self.currentTest.contentChanged

        commandLine, descriptor = self.getViewCommand(fileName)
        description = descriptor + " " + self.getRelativeFilename(fileName)
        refresh = str(int(refreshContents or refreshFiles))
        guilog.info("Viewing file " + fileName.replace(os.sep, "/") + " using '" + descriptor + "', refresh set to " + str(refresh))
        process = self.startExternalProgram(commandLine, description=description, exitHandler=exitHandler)
        scriptEngine.monitorProcess("views and edits test files", process, [ fileName ])
    
# Plugin for saving tests (standard)
class SaveTests(SelectionAction):
    def __init__(self, rootTestSuites):
        SelectionAction.__init__(self, rootTestSuites)
        self.addOption("v", "Version to save", self.getDefaultSaveOption(), self.getPossibleVersions())
        self.addSwitch("over", "Replace successfully compared files also", 0)
        self.currFileSelection = []
        self.currTestDescription = ""
        if self.hasPerformance():
            self.addSwitch("ex", "Save: ", 1, ["Average performance", "Exact performance"])
    def isFrequentUse(self):
        return True
    def getStockId(self):
        return "save"
    def getTabTitle(self):
        return "Saving"
    def getDefaultAccelerator(self):
        return "<control>s"
    def getTitle(self):
        return "_Save"
    def _getScriptTitle(self):
        return "Save results for selected tests"
    def messageBeforePerform(self):
        self.currTestDescription = self.describeTests()
        return "Saving " + self.currTestDescription + " ..."
    def messageAfterPerform(self):
        # Test selection is reset after a save, use the description from before 
        return "Saved " + self.currTestDescription + "."
    def getDefaultSaveOption(self):
        saveVersions = self.getSaveVersions()
        if saveVersions.find(",") != -1:
            return "<default> - " + saveVersions
        else:
            return saveVersions
    def getPossibleVersions(self):
        extensions = []
        for app in self.apps:
            for ext in app.getSaveableVersions():
                if not ext in extensions:
                    extensions.append(ext)
        # Include the default version always
        extensions.append("")
        return extensions
    def getSaveVersions(self):
        saveVersions = []
        for app in self.apps:
            ver = self.getDefaultSaveVersion(app)
            if not ver in saveVersions:
                saveVersions.append(ver)
        return string.join(saveVersions, ",")
    def getDefaultSaveVersion(self, app):
        return app.getFullVersion(forSave = 1)
    def hasPerformance(self):
        for app in self.apps:
            if app.hasPerformance():
                return True
        return False
    def getExactness(self):
        return int(self.optionGroup.getSwitchValue("ex", 1))
    def getVersion(self, test):
        versionString = self.optionGroup.getOptionValue("v")
        if versionString.startswith("<default>"):
            return self.getDefaultSaveVersion(test.app)
        else:
            return versionString
    def notifyNewFileSelection(self, files):
        self.currFileSelection = files
    def performOnCurrent(self):
        saveDesc = ", exactness " + str(self.getExactness())
        if len(self.currFileSelection) > 0:
            saveDesc += ", only " + string.join(self.currFileSelection, ",")
        overwriteSuccess = self.optionGroup.getSwitchValue("over")
        if overwriteSuccess:
            saveDesc += ", overwriting both failed and succeeded files"

        fileSel = copy(self.currFileSelection) # Saving can cause it to be updated, meaning we don't save what we intend
        for test in self.currTestSelection:
            if not test.state.isSaveable():
                continue
            version = self.getVersion(test)
            fullDesc = " - version " + version + saveDesc
            self.describe(test, fullDesc)
            testComparison = test.state
            testComparison.setObservers(self.observers)
            if testComparison:
                if len(fileSel) > 0:
                    testComparison.savePartial(fileSel, test, self.getExactness(), version)
                else:
                    testComparison.save(test, self.getExactness(), version, overwriteSuccess)
                newState = testComparison.makeNewState(test.app)
                test.changeState(newState)
          
# Plugin for viewing files (non-standard). In truth, the GUI knows a fair bit about this action,
# because it's special and plugged into the tree view. Don't use this as a generic example!
class ViewFile(InteractiveTestAction):
    def __init__(self, dynamic, test):
        InteractiveTestAction.__init__(self, test)
        self.dynamic = dynamic
        if dynamic:
            self.addDifferenceSwitches()
    def isActiveOnCurrent(self):
        return not self.dynamic or InteractiveTestAction.isActiveOnCurrent(self)
    def getTabTitle(self):
        return "Viewing"
    def canPerform(self):
        return False # activate when a file is viewed, not via the performOnCurrent method
    def hasButton(self):
        return False
    def addDifferenceSwitches(self):
        self.addSwitch("rdt", "Include run-dependent text", 0)
        self.addSwitch("nf", "Show differences where present", 1)
    def updateOptionGroup(self, state):
        if not self.dynamic:
            return False

        origCount = len(self.optionGroup.switches)
        if self.isActiveOnCurrent():
            followDefault = self.optionGroup.getSwitchValue("f", 1)
            self.optionGroup.removeSwitch("f")
            if not state.hasResults():
                self.optionGroup.removeSwitch("rdt")
                self.optionGroup.removeSwitch("nf")
            if state.hasResults():
                self.addDifferenceSwitches()
            if not state.isComplete():
                self.addSwitch("f", "Follow file rather than view it", followDefault)
        return len(self.optionGroup.switches) != origCount
    def notifyNewTestSelection(self, tests):
        if len(tests) > 0 and self.currentTest not in tests:
            self.currentTest = tests[0]
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
    def fileToFollow(self, comparison, fileName):
        if comparison:
            return comparison.tmpFile
        else:
            return fileName
    def followFile(self, fileName):
        followProgram = self.currentTest.app.getConfigValue("follow_program")
        if not plugins.canExecute(followProgram):
            raise plugins.TextTestError, "Cannot find file-following program '" + followProgram + \
                  "'\nPlease install it somewhere on your PATH or point the follow_program setting at a different tool"
        guilog.info("Following file " + fileName + " using '" + followProgram + "'")
        description = followProgram + " " + self.getRelativeFilename(fileName)
        baseName = os.path.basename(fileName)
        title = self.currentTest.name + " (" + baseName + ")"
        process = self.startExternalProgram(followProgram + " " + fileName, description=description, shellTitle=title)
        scriptEngine.monitorProcess("follows progress of test files", process)
    def notifyViewFile(self, comparison, fileName):
        if self.optionGroup.getSwitchValue("f"):
            return self.followFile(self.fileToFollow(comparison, fileName))
        if not comparison:
            baseName = os.path.basename(fileName)
            refreshContents = baseName.startswith("testsuite.") # re-read which tests we have
            refreshFiles = baseName.startswith("options.") # options file can change appearance of test (environment refs etc.)
            return self.viewFile(fileName, refreshContents, refreshFiles)
        if self.shouldTakeDiff(comparison):
            self.takeDiff(comparison)
        elif comparison.missingResult():
            self.viewFile(self.stdFile(comparison))
        else:
            self.viewFile(self.tmpFile(comparison))
    def shouldTakeDiff(self, comparison):
        if comparison.newResult() or comparison.missingResult() or not self.optionGroup.getSwitchValue("nf"):
            return 0
        if comparison.hasDifferences():
            return 1
        # Take diff on succeeded tests if they want run-dependent text
        return self.optionGroup.getSwitchValue("rdt")
    def takeDiff(self, comparison):
        diffProgram = self.currentTest.app.getConfigValue("diff_program")
        if not plugins.canExecute(diffProgram):
            raise plugins.TextTestError, "Cannot find graphical difference program '" + diffProgram + \
                  "'\nPlease install it somewhere on your PATH or point the diff_program setting at a different tool"
        stdFile = self.stdFile(comparison)
        tmpFile = self.tmpFile(comparison)
        description = diffProgram + " " + stdFile + "\n                                   " + tmpFile
        guilog.info("Comparing file " + os.path.basename(tmpFile) + " with previous version using '" + diffProgram + "'")
        process = self.startExternalProgram(diffProgram + " '" + stdFile + "' '" + tmpFile + "' " + plugins.nullRedirect(), description=description)
        scriptEngine.monitorProcess("shows graphical differences in test files", process)

# And a generic import test. Note acts on test suites
class ImportTest(InteractiveTestAction):
    def __init__(self, suite):
        InteractiveTestAction.__init__(self, suite)
        self.optionGroup.addOption("name", self.getNameTitle(), self.getDefaultName())
        self.optionGroup.addOption("desc", self.getDescTitle(), self.getDefaultDesc(), description="Enter a description of the new " + self.testType().lower() + " which will be inserted as a comment in the testsuite file.")
        self.optionGroup.addOption("testpos", self.getPlaceTitle(), "last in suite", allocateNofValues=2, description="Where in the test suite should the test be placed?")
        self.testImported = None
        self.setPlacements(self.currentTest)
    def correctTestClass(self):
        return self.currentTest.classId() == "test-suite"
    def getNameTitle(self):
        return self.testType() + " Name"
    def getDescTitle(self):
        return self.testType() + " Description"
    def getPlaceTitle(self):
        return "Place " + self.testType()
    def updateOptionGroup(self, state):
        self.optionGroup.setOptionValue("name", self.getDefaultName())
        self.optionGroup.setOptionValue("desc", self.getDefaultDesc())
        self.setPlacements(self.currentTest)
        return True
    def setPlacements(self, suite):
        if suite.classId() == "test-case":
            suite = suite.parent
        # Add suite and its children
        placements = [ "first in suite" ]
        for test in suite.testcases:
            placements = placements + [ "after " + test.name ]
        self.optionGroup.setPossibleValuesUpdate("testpos", placements)
        self.optionGroup.getOption("testpos").reset()                    
    def getDefaultName(self):
        return ""
    def getDefaultDesc(self):
        return ""
    def getTabTitle(self):
        return "Adding " + self.testType()
    def getTitle(self):
        return "Add " + self.testType()
    def testType(self):
        return ""
    def messageAfterPerform(self):
        if self.testImported:
            return "Added new " + repr(self.testImported)
    def getNewTestName(self):
        # Overwritten in subclasses - occasionally it can be inferred
        return self.optionGroup.getOptionValue("name").strip()
    def performOnCurrent(self):
        testName = self.getNewTestName()
        if len(testName) == 0:
            raise plugins.TextTestError, "No name given for new " + self.testType() + "!" + "\n" + \
                  "Fill in the 'Adding " + self.testType() + "' tab below."
        if testName.find(" ") != -1:
            raise plugins.TextTestError, "The new " + self.testType() + " name is not permitted to contain spaces, please specify another"
        suite = self.getDestinationSuite()
        for test in suite.testCaseList():
            if test.name == testName:
                raise plugins.TextTestError, "A " + self.testType() + " with the name '" + testName + "' already exists, please choose another name"
        guilog.info("Adding " + self.testType() + " " + testName + " under test suite " + repr(suite) + ", placed " + self.optionGroup.getOptionValue("testpos"))
        testDir = suite.writeNewTest(testName, self.optionGroup.getOptionValue("desc"), self.optionGroup.getOptionValue("testpos"))
        self.testImported = self.createTestContents(suite, testDir, self.optionGroup.getOptionValue("testpos"))
    def createTestContents(self, suite, testDir, placement):
        pass
    def getDestinationSuite(self):
        return self.currentTest

class RecordTest(InteractiveTestAction):
    def __init__(self, test):
        InteractiveTestAction.__init__(self, test)
        self.recordMode = self.currentTest.getConfigValue("use_case_record_mode")
        self.recordTime = None
        if self.isActive():
            self.addOption("v", "Version to record", self.currentTest.app.getFullVersion(forSave=1))
            self.addOption("c", "Checkout to use for recording", self.currentTest.app.checkout) 
            self.addSwitch("rep", "Automatically replay test after recording it", 1)
            self.addSwitch("repgui", "", defaultValue = 0, options = ["Auto-replay invisible", "Auto-replay in dynamic GUI"])
        if self.recordMode == "console":
            self.addSwitch("hold", "Hold record shell after recording")
    def getTabTitle(self):
        return "Recording"
    def messageAfterPerform(self):
        return "Started record session for " + repr(self.currentTest)
    def performOnCurrent(self):
        guilog.info("Starting dynamic GUI in record mode...")
        self.updateRecordTime(self.currentTest)
        self.startTextTestProcess(self.currentTest, "record")
    def updateRecordTime(self, test):
        if self.updateRecordTimeForFile(test, "usecase", "USECASE_RECORD_SCRIPT", "target_record"):
            return True
        if self.recordMode == "console" and self.updateRecordTimeForFile(test, "input", "USECASE_RECORD_STDIN", "target"):
            return True
        return False
    def updateRecordTimeForFile(self, test, stem, envVar, prefix):
        file = test.getFileName(stem, self.optionGroup.getOptionValue("v"))
        if not file:
            return False
        newTime = plugins.modifiedTime(file)
        if newTime != self.recordTime:
            self.recordTime = newTime
            if os.environ.has_key(envVar):
                # If we have an "outer" record going on, provide the result as a target recording...
                target = plugins.addLocalPrefix(os.getenv(envVar), prefix)
                shutil.copyfile(file, target)
            return True
        return False
    def startTextTestProcess(self, test, usecase):
        ttOptions = self.getRunOptions(test, usecase)
        guilog.info("Starting " + usecase + " run of TextTest with arguments " + ttOptions)
        commandLine = plugins.textTestName + " " + ttOptions
        writeDir = self.getWriteDir(test)
        plugins.ensureDirectoryExists(writeDir)
        logFile = self.getLogFile(writeDir, usecase, "output")
        errFile = self.getLogFile(writeDir, usecase)
        commandLine +=  " < " + plugins.nullFileName() + " > " + logFile + " 2> " + errFile
        process = self.startExtProgramNewUsecase(commandLine, usecase, \
                                                 exitHandler=self.textTestCompleted, exitHandlerArgs=(test,usecase))
    def getLogFile(self, writeDir, usecase, type="errors"):
        return os.path.join(writeDir, usecase + "_" + type + ".log")
    def isActive(self):
        return self.recordMode != "disabled"
    def textTestCompleted(self, test, usecase):
        scriptEngine.applicationEvent(usecase + " texttest to complete")
        # Refresh the files before changed the data
        test.refreshFiles()
        if usecase == "record":
            self.setTestRecorded(test, usecase)
        else:
            self.setTestReady(test, usecase)
        test.filesChanged()
    def getWriteDir(self, test):
        return os.path.join(test.app.writeDirectory, "record")
    def setTestRecorded(self, test, usecase):
        writeDir = self.getWriteDir(test)
        errFile = self.getLogFile(writeDir, usecase)
        if os.path.isfile(errFile):
            errText = open(errFile).read()
            if len(errText):
                self.notify("Status", "Recording failed for " + repr(test))
                raise plugins.TextTestError, "Recording use-case failed, with the following errors:\n" + errText
 
        if self.updateRecordTime(test) and self.optionGroup.getSwitchValue("rep"):
            self.startTextTestProcess(test, usecase="replay")
            message = "Recording completed for " + repr(test) + \
                      ". Auto-replay of test now started. Don't submit the test manually!"
            self.notify("Status", message)
        else:
            self.notify("Status", "Recording completed for " + repr(test) + ", not auto-replaying")
    def setTestReady(self, test, usecase=""):
        self.notify("Status", "Recording and auto-replay completed for " + repr(test))
    def getRunOptions(self, test, usecase):
        version = self.optionGroup.getOptionValue("v")
        checkout = self.optionGroup.getOptionValue("c")
        basicOptions = self.getRunModeOption(usecase) + " -tp " + test.getRelPath() + \
                       " " + test.app.getRunOptions(version, checkout)
        if usecase == "record":
            basicOptions += " -record"
            if self.optionGroup.getSwitchValue("hold"):
                basicOptions += " -holdshell"
        return basicOptions
    def getRunModeOption(self, usecase):
        if usecase == "record" or self.optionGroup.getSwitchValue("repgui"):
            return "-g"
        else:
            return "-o"
    def getTitle(self):
        return "Record _Use-Case"
    
class ImportTestCase(ImportTest):
    def __init__(self, suite):
        ImportTest.__init__(self, suite)
        self.addDefinitionFileOption(suite)
    def testType(self):
        return "Test"
    def addDefinitionFileOption(self, suite):
        self.addOption("opt", "Command line options")
    def createTestContents(self, suite, testDir, placement):
        self.writeDefinitionFiles(suite, testDir)
        self.writeEnvironmentFile(suite, testDir)
        self.writeResultsFiles(suite, testDir)
        return suite.addTestCase(os.path.basename(testDir), placement)
    def getWriteFileName(self, name, suite, testDir):
        fileName = os.path.join(testDir, name + "." + suite.app.name)
        if os.path.isfile(fileName):
            raise plugins.TextTestError, "Test already exists for application " + suite.app.fullName + " : " + os.path.basename(testDir)
        return fileName
    def getWriteFile(self, name, suite, testDir):
        return open(self.getWriteFileName(name, suite, testDir), "w")
    def writeEnvironmentFile(self, suite, testDir):
        envDir = self.getEnvironment(suite)
        if len(envDir) == 0:
            return
        envFile = self.getWriteFile("environment", suite, testDir)
        for var, value in envDir.items():
            guilog.info("Setting test env: " + var + " = " + value)
            envFile.write(var + ":" + value + "\n")
        envFile.close()
    def writeDefinitionFiles(self, suite, testDir):
        optionString = self.getOptions(suite)
        if len(optionString):
            guilog.info("Using option string : " + optionString)
            optionFile = self.getWriteFile("options", suite, testDir)
            optionFile.write(optionString + "\n")
        else:
            guilog.info("Not creating options file")
        return optionString
    def getOptions(self, suite):
        return self.optionGroup.getOptionValue("opt")
    def getEnvironment(self, suite):
        return {}
    def writeResultsFiles(self, suite, testDir):
        # Cannot do anything in general
        pass

class ImportTestSuite(ImportTest):
    def __init__(self, suite):
        ImportTest.__init__(self, suite)
        self.addEnvironmentFileOptions()
    def testType(self):
        return "Suite"
    def createTestContents(self, suite, testDir, placement):
        self.writeEnvironmentFiles(suite, testDir)
        return suite.addTestSuite(os.path.basename(testDir), placement)
    def addEnvironmentFileOptions(self):
        self.addSwitch("env", "Add environment file")
    def writeEnvironmentFiles(self, suite, testDir):
        if self.optionGroup.getSwitchValue("env"):
            envFile = os.path.join(testDir, "environment")
            file = open(envFile, "w")
            file.write("# Dictionary of environment to variables to set in test suite" + "\n")

class SelectTests(SelectionAction):
    def __init__(self, rootSuites):
        SelectionAction.__init__(self, rootSuites)
        self.diag = plugins.getDiagnostics("Select Tests")
        self.addOption("vs", "Tests for version", "", self.getPossibleVersions())
        self.addSwitch("select_in_collapsed_suites", "Select in collapsed suites", 0)
        self.addSwitch("current_selection", "Current selection:", options = [ "Discard", "Refine", "Extend", "Exclude"], description="How should we treat the currently selected tests?\n - Discard: Unselect all currently selected tests before applying the new selection criteria.\n - Refine: Apply the new selection criteria only to the currently selected tests, to obtain a subselection.\n - Extend: Keep the currently selected tests even if they do not match the new criteria, and extend the selection with all other tests which meet the new criteria.\n - Exclude: After applying the new selection criteria to all tests, unselect the currently selected tests, to exclude them from the new selection.")
        
        self.appSelectGroup = self.findSelectGroup()
        self.optionGroup.options += self.appSelectGroup.options
        self.optionGroup.switches += self.appSelectGroup.switches
    def isActiveOnCurrent(self):
        return True
    def getPossibleVersions(self):
        versions = []
        for app in self.apps:
            appVer = app.getFullVersion()
            if len(appVer) == 0:
                appVer = "<default>"
            if not appVer in versions:
                versions.append(appVer)
        return versions
    def findSelectGroup(self):
        for group in self.apps[0].optionGroups:
            if group.name.startswith("Select"):
                return group
    def getDefaultAccelerator(self):
        return "<control>s"
    def getStockId(self):
        return "refresh"
    def getTitle(self):
        return "_Select"
    def _getScriptTitle(self):
        return "Select indicated tests"
    def getTabTitle(self):
        return "Select Tests"
    def getGroupTabTitle(self):
        return "Selection"
    def messageBeforePerform(self):
        return "Selecting tests ..."
    def messageAfterPerform(self):
        return "Selected " + self.describeTests() + "."    
    # No messageAfterPerform necessary - we update the status bar when the selection changes inside TextTestGUI
    def isFrequentUse(self):
        return True
    def getFilterList(self, app):
        app.configObject.updateOptions(self.appSelectGroup)
        return app.configObject.getFilterList(app)
    def performOnCurrent(self):
        # Get strategy. 0 = discard, 1 = refine, 2 = extend, 3 = exclude
        strategy = self.optionGroup.getSwitchValue("current_selection")
        selectedTests = []                
        for suite in self.getSuitesToTry():
            filters = self.getFilterList(suite.app)            
            for filter in filters:
                if not filter.acceptsApplication(suite.app):
                    continue
                
            reqTests = self.getRequestedTests(suite, filters)
            newTests = self.combineWithPrevious(reqTests, strategy)
            guilog.info("Selected " + str(len(newTests)) + " out of a possible " + str(suite.size()))
            selectedTests += newTests
        self.notify("NewTestSelection", selectedTests, self.optionGroup.getSwitchValue("select_in_collapsed_suites"))
    def getSuitesToTry(self):
        # If only some of the suites present match the version selection, only consider them.
        # If none of them do, try to filter them all
        versionSelection = self.optionGroup.getOptionValue("vs")
        if len(versionSelection) == 0:
            return self.rootTestSuites
        versions = versionSelection.split(".")
        toTry = []
        for suite in self.rootTestSuites:
            if self.allVersionsMatch(versions, suite.app.versions):
                toTry.append(suite)
        if len(toTry) == 0:
            return self.rootTestSuites
        else:
            return toTry
    def allVersionsMatch(self, versions, appVersions):
        for version in versions:
            if version == "<default>":
                if len(appVersions) > 0:
                    return False
            else:
                if not version in appVersions:
                    return False
        return True
    def getRequestedTests(self, suite, filters):
        self.notify("ActionProgress", "") # Just to update gui ...            
        if not suite.isAcceptedByAll(filters):
            return []
        if suite.classId() == "test-suite":
            tests = []
            for subSuite in self.findTestCaseList(suite):
                tests += self.getRequestedTests(subSuite, filters)
            return tests
        else:
            return [ suite ]
    def combineWithPrevious(self, reqTests, strategy):
        # Strategies: 0 - discard, 1 - refine, 2 - extend, 3 - exclude
        # If we want to extend selection, we include test if it was previsouly selected,
        # even if it doesn't fit the current criterion
        if strategy == 0:
            return reqTests
        elif strategy == 1:
            return filter(self.isSelected, reqTests)
        elif strategy == 2:
            return reqTests + self.currTestSelection
        elif strategy == 3:
            return filter(self.isNotSelected, reqTests)
    def findTestCaseList(self, suite):
        testcases = suite.testcases
        version = self.optionGroup.getOptionValue("vs")
        if len(version) == 0:
            return testcases

        if version == "<default>":
            version = ""
        fullVersion = suite.app.getFullVersion()
        self.diag.info("Trying to get test cases for version " + fullVersion)
        if len(fullVersion) > 0 and len(version) > 0:
            parts = version.split(".")
            for appVer in suite.app.versions:
                if not appVer in parts:
                    version += "." + appVer

        self.diag.info("Finding test case list for " + repr(suite) + ", version " + version)
        versionFile = suite.getFileName("testsuite", version)        
        self.diag.info("Reading test cases from " + versionFile)
        newTestNames = plugins.readList(versionFile)
        newTestList = []
        for testCase in testcases:
            if testCase.name in newTestNames:
                newTestList.append(testCase)
        return newTestList

class ResetGroups(InteractiveAction):
    def getStockId(self):
        return "revert-to-saved"
    def getDefaultAccelerator(self):
        return '<control>e'
    def getTitle(self):
        return "R_eset"
    def messageAfterPerform(self):
        return "All options reset to default values."
    def _getScriptTitle(self):
        return "Reset running options"
    def performOnCurrent(self):
        for optionGroups in interactiveActionHandler.optionGroupMap.values():
            for group in optionGroups:
                group.reset()

class SaveSelection(SelectionAction):
    def __init__(self, dynamic, rootSuites):
        self.dynamic = dynamic
        SelectionAction.__init__(self, rootSuites)
        self.addOption("name", "Name to give selection")
        if not dynamic:
            self.addSwitch("tests", "Store actual tests selected", 1)
            for group in self.apps[0].optionGroups:
                if group.name.startswith("Select"):
                    self.selectionGroup = group
    def getTitle(self):
        return "S_ave selection"
    def _getScriptTitle(self):
        return "Save selected tests in file"
    def getTabTitle(self):
        if self.dynamic:
            return "Save Selection"
        else:
            return "Saving"
    def getGroupTabTitle(self):
        if self.dynamic:
            return "Test" # 'Test' gives us no group tab ...
        else:
            return "Selection"
    def getFileName(self):
        localName = self.optionGroup.getOptionValue("name")
        if not localName:
            raise plugins.TextTestError, "Please provide a file name to save the selection to."
        
        app = self.getAnyApp()
        return app.configObject.getFilterFilePath(app, localName, True)
    def saveActualTests(self):
        return self.dynamic or self.optionGroup.getSwitchValue("tests")
    def getTextToSave(self):
        actualTests = self.saveActualTests()
        if actualTests:
            return self.getCmdlineOption()
        else:
            commandLines = self.selectionGroup.getCommandLines()
            return string.join(commandLines)
    def performOnCurrent(self):
        fileName = self.getFileName()
        toWrite = self.getTextToSave()
        file = open(fileName, "w")
        file.write(toWrite + "\n")
        file.close()
        self.addFilterFile(fileName)
    def messageAfterPerform(self):
        return "Saved " + self.describeTests() + " in file '" + self.getFileName() + "'."
                  
class RunTests(SelectionAction):
    runNumber = 1
    def __init__(self, rootSuites):
        SelectionAction.__init__(self, rootSuites)
        self.optionGroups = []
        for group in self.apps[0].optionGroups:
            if group.name.startswith("Invisible"):
                self.invisibleGroup = group
            elif not group.name.startswith("Select"):
                self.optionGroups.append(group)
    def getOptionGroups(self):
        return self.optionGroups
    def getTitle(self):
        return "_Run"
    def getStockId(self):
        return "execute"
    def getDefaultAccelerator(self):
        return "<control>r"
    def _getScriptTitle(self):
        return "Run selected tests"
    def getGroupTabTitle(self):
        return "Running"
    def messageAfterPerform(self):
        return "Started " + self.describeTests() + " at " + plugins.localtime() + "."
    def isFrequentUse(self):
        return True
    def getUseCaseName(self):
        if self.runNumber == 1:
            return "dynamic"
        else:
            return "dynamic_" + str(self.runNumber)
    def performOnCurrent(self):
        writeDir = os.path.join(self.apps[0].writeDirectory, "dynamic_run" + str(self.runNumber))
        plugins.ensureDirectoryExists(writeDir)
        filterFile = self.writeFilterFile(writeDir)
        ttOptions = self.getTextTestOptions(filterFile)
        logFile = os.path.join(writeDir, "output.log")
        errFile = os.path.join(writeDir, "errors.log")
        usecase = self.getUseCaseName()
        self.runNumber += 1
        description = "Dynamic GUI started at " + plugins.localtime()
        commandLine = plugins.textTestName + " " + ttOptions + " < " + plugins.nullFileName() + " > " + logFile + " 2> " + errFile
        identifierString = "started at " + plugins.localtime()
        self.startExtProgramNewUsecase(commandLine, usecase, exitHandler=self.checkTestRun, exitHandlerArgs=(identifierString,errFile,self.currTestSelection), description = description)
    def writeFilterFile(self, writeDir):
        # Because the description of the selection can be extremely long, we write it in a file and refer to it
        # This avoids too-long command lines which are a problem at least on Windows XP
        filterFileName = os.path.join(writeDir, "gui_select")
        writeFile = open(filterFileName, "w")
        writeFile.write(self.getCmdlineOption() + "\n")
        writeFile.close()
        return filterFileName
    def getTextTestOptions(self, filterFile):
        ttOptions = [ self.getCmdlineOptionForApps() ]
        ttOptions += self.invisibleGroup.getCommandLines()
        for group in self.optionGroups:
            ttOptions += group.getCommandLines()
        filterDir, filterFileName = os.path.split(filterFile)
        ttOptions.append("-f " + filterFileName)
        ttOptions.append("-fd " + filterDir)
        return string.join(ttOptions)
    def checkTestRun(self, identifierString, errFile, testSel):
        try:
            self.notifyIfMainThread("ActionStart", "")
            writeDir, local = os.path.split(errFile)
            prelist = [ "output.log", "errors.log", "gui_select" ]
            for fileName in os.listdir(writeDir):
                if not fileName in prelist:
                    self.notifyIfMainThread("Status", "Adding filter " + fileName + " ...")
                    self.notifyIfMainThread("ActionProgress", "")
                    self.addFilterFile(fileName)
            for test in testSel:
                self.notifyIfMainThread("Status", "Updating files for " + repr(test) + " ...")
                self.notifyIfMainThread("ActionProgress", "")
                test.filesChanged()
            runNumber = int(os.path.basename(writeDir).replace("dynamic_run", ""))
            if runNumber == 1:
                scriptEngine.applicationEvent("dynamic GUI to be closed")
            else:
                scriptEngine.applicationEvent("dynamic GUI " + str(runNumber) + " to be closed")
            if os.path.isfile(errFile):
                errText = open(errFile).read()
                if len(errText):
                    raise plugins.TextTestError, "Dynamic run failed, with the following errors:\n" + errText
        finally:
            self.notifyIfMainThread("Status", "Done updating after dynamic run " + identifierString + ".")
            self.notifyIfMainThread("ActionStop", "")

class CreateDefinitionFile(InteractiveTestAction):
    def __init__(self, rootSuites):
        InteractiveTestAction.__init__(self, rootSuites)
        configDir = self.currentTest.getConfigValue("diagnostics")
        self.configFile = None
        if configDir.has_key("configuration_file"):
            self.configFile = configDir["configuration_file"]
            self.addSwitch("diag", "Affect diagnostic mode only")
        defFiles = self.getDefinitionFiles()
        self.addOption("type", "Type of definition file to create", defFiles[0], defFiles, allocateNofValues=2)
    def correctTestClass(self):
        return True
    def getTitle(self):
        return "Create _File"
    def getTabTitle(self):
        return "New File" 
    def getScriptTitle(self, tab):
        return "Create File"
    def getDefinitionFiles(self):
        defFiles = []
        if self.configFile:
            defFiles.append(self.configFile)
        defFiles.append("environment")
        if self.currentTest.classId() == "test-case":
            defFiles.append("options")
            recordMode = self.currentTest.getConfigValue("use_case_record_mode")
            if recordMode == "disabled" or recordMode == "console":
                defFiles.append("input")
            else:
                defFiles.append("usecase")
        return defFiles + self.currentTest.app.getDataFileNames()
    def updateOptionGroup(self, state):
        self.optionGroup.setPossibleValues("type", self.getDefinitionFiles())
        return True
    def getFileName(self):
        stem = self.optionGroup.getOptionValue("type")
        if stem != self.configFile and stem in self.currentTest.getConfigValue("definition_file_stems"):
            return stem + "." + self.currentTest.app.name
        else:
            return stem
    def getTargetDirectory(self):
        if self.optionGroup.getSwitchValue("diag"):
            return self.currentTest.makeSubDirectory("Diagnostics")
        else:
            return self.currentTest.getDirectory()
        
    def performOnCurrent(self):
        fileName = self.getFileName()
        sourceFile = self.currentTest.makePathName(fileName)
        targetFile = os.path.join(self.getTargetDirectory(), fileName)
        plugins.ensureDirExistsForFile(targetFile)
        if sourceFile:
            guilog.info("Creating new file, copying " + sourceFile)
            shutil.copyfile(sourceFile, targetFile)
        else:
            guilog.info("Creating new empty file...")
        self.viewFile(targetFile, refreshFiles=True)

class RemoveTest(SelectionAction):
    def notifyNewTestSelection(self, tests):
        self.currTestSelection = tests # interested in suites, unlike most SelectionActions
    def getTitle(self):
        return "Remove"
    def getStockId(self):
        return "delete"
    def _getScriptTitle(self):
        return "Remove selected tests"
    def getDoubleCheckMessage(self):
        if len(self.currTestSelection) == 1:
            currTest = self.currTestSelection[0]
            if currTest.classId() == "test-case":
                return "You are about to remove the test '" + currTest.name + \
                       "' and all associated files.\nAre you sure you wish to proceed?"
            else:
                return "You are about to remove the entire test suite '" + currTest.name + \
                       "' and all " + str(currTest.size()) + " tests that it contains!\nAre you VERY sure you wish to proceed??"
        else:
            return "You are about to remove " + repr(len(self.currTestSelection)) + \
                   " tests with associated files!\nAre you VERY sure you wish to proceed??"
    def performOnCurrent(self):
        for test in self.currTestSelection:
            dir = test.getDirectory()
            if os.path.isdir(dir): # might have already removed the enclosing suite
                plugins.rmtree(dir)
                self.removeTest(test)
    def removeTest(self, test):
        suite = test.parent
        testName = test.name
        self.removeFromTestFile(suite, testName)
        suite.removeTest(test)
        self.notify("Status", "Removed test " + testName)
    def messageAfterPerform(self):
        pass # do it as part of the method as currentTest will have changed by the end!
    def removeFromTestFile(self, suite, testName):
        newFileName = os.path.join(suite.app.writeDirectory, "tmptestsuite")
        newFile = plugins.openForWrite(newFileName)
        description = ""
        contentFileName = suite.getContentFileName()
        for line in open(contentFileName).xreadlines():
            stripLine = line.strip()
            description += line
            if line.startswith("#") or len(stripLine) == 0:
                continue
            
            if stripLine != testName:
                newFile.write(description)
            description = ""
        newFile.close()
        if guilog.get_loglevel() >= LOGLEVEL_NORMAL:
            difftool = suite.getConfigValue("text_diff_program")
            diffInfo = os.popen(difftool + " " + contentFileName + " " + newFileName).read()
            guilog.info("Changes made to testcase file : \n" + diffInfo)
            guilog.info("") # blank line
        plugins.movefile(newFileName, contentFileName)

class CopyTest(ImportTest):
    def __init__(self, rootSuites):
        self.rootSuites = rootSuites
        self.testToCopy = None
        self.remover = None
        ImportTest.__init__(self, rootSuites)
        self.optionGroup.removeOption("testpos")
        self.optionGroup.addOption("suite", "Copy to suite", "current", allocateNofValues = 2, description = "Which suite should the test be copied to?", changeMethod = self.updatePlacements)
        self.optionGroup.addOption("testpos", self.getPlaceTitle(), "last in suite", allocateNofValues = 2, description = "Where in the test suite should the test be placed?")
        self.optionGroup.addSwitch("keeporig", "Keep original", value = 1, description = "Should the original test be kept or removed?")
    def getDoubleCheckMessage(self):
        if not self.optionGroup.getSwitchValue("keeporig"):
            self.remover = RemoveTest(self.rootSuites)
            self.remover.notifyNewTestSelection([self.testToCopy])
            return self.remover.getDoubleCheckMessage()
        else:
            return ""
    def isActiveOnCurrent(self):
        return self.testToCopy
    def testType(self):
        return "Test"
    def getTabTitle(self):
        return "Copying"
    def getNameTitle(self):
        return "Name of copy"
    def getDescTitle(self):
        return "Description"
    def getPlaceTitle(self):
        return "Place copy"
    def getDefaultName(self):
        if self.testToCopy:
            return self.testToCopy.name + "_copy"
        else:
            return ""
    def getDefaultDesc(self):
        if self.testToCopy:
            return "Copy of " + self.testToCopy.name
        else:
            return ""
    def getTitle(self):
        return "_Copy"
    def getScriptTitle(self, tab):
        return "Copy Test"
    def updateOptionGroup(self, state):
        self.optionGroup.setOptionValue("name", self.getDefaultName())
        self.optionGroup.setOptionValue("desc", self.getDefaultDesc())
        self.fillSuiteList()
        self.setPlacements(self.currentTest)
        return True
    def updatePlacements(self, w):
        # Get the suite from the 'suite' option, adjust placement possibilities
        chosenSuite = self.optionGroup.getOptionValue("suite")
        if chosenSuite: # We first catch an event for an empty gtk.Entry ..
            suite = self.suiteMap[chosenSuite]
            self.setPlacements(suite)
    def fillSuiteList(self):
        suiteNames = [ "current" ]
        self.suiteMap = { "current" : self.currentTest }
        root = self.currentTest       
        while root.parent != None:
            root = root.parent

        toCheck = [ root ]
        path = { root : root.name }
        while len(toCheck) > 0:
            suite = toCheck[len(toCheck) - 1]
            toCheck = toCheck[0:len(toCheck) - 1]
            if suite.classId() == "test-suite":
                thisPath = path[suite]
                suiteNames.append(thisPath)
                self.suiteMap[thisPath] = suite
                for i in xrange(len(suite.testcases) - 1, -1, -1):
                    path[suite.testcases[i]] = path[suite] + "/" + suite.testcases[i].name
                    toCheck.append(suite.testcases[i])
        self.optionGroup.setPossibleValues("suite", suiteNames)
        self.optionGroup.getOption("suite").reset()
    def getDestinationSuite(self):
        return self.suiteMap[self.optionGroup.getOptionValue("suite")]
    def notifyNewTestSelection(self, tests):
        # apply to parent
        ImportTest.notifyNewTestSelection(self, tests)
        if self.currentTest and self.currentTest.classId() == "test-case":
            self.testToCopy = self.currentTest
            self.currentTest = self.currentTest.parent
        else:
            self.testToCopy = None
    def updateDefaults(self, test, state):
        if test is self.testToCopy:
            return self.updateOptionGroup(state)
        else:
            return False
    def createTestContents(self, suite, testDir, placement):
        stdFiles, defFiles = self.testToCopy.listStandardFiles(allVersions=True)
        for sourceFile in stdFiles + defFiles:
            dirname, local = os.path.split(sourceFile)
            if dirname == self.testToCopy.getDirectory():
                targetFile = os.path.join(testDir, local)
                shutil.copyfile(sourceFile, targetFile)
        dataFiles = self.testToCopy.listDataFiles()
        for sourcePath in dataFiles:
            if os.path.isdir(sourcePath):
                continue
            targetPath = sourcePath.replace(self.testToCopy.getDirectory(), testDir)
            plugins.ensureDirExistsForFile(targetPath)
            shutil.copyfile(sourcePath, targetPath)
        originalTest = self.testToCopy # Set to new test in call below ...
        ret =  suite.addTestCase(os.path.basename(testDir), placement)
        if self.remover:
            self.remover.performOnCurrent()
        return ret
    
class ReportBugs(InteractiveTestAction):
    def __init__(self, test):
        InteractiveTestAction.__init__(self, test)
        self.addOption("search_string", "Text or regexp to match")
        self.addOption("search_file", "File to search in", self.currentTest.app.getConfigValue("log_file"),
                       self.getPossibleFileStems())
        self.addOption("version", "Version to report for", self.currentTest.app.getFullVersion())
        self.addOption("execution_hosts", "Trigger only when run on machine(s)")
        self.addOption("bug_system", "Extract info from bug system", "<none>", [ "bugzilla" ])
        self.addOption("bug_id", "Bug ID (only if bug system given)")
        self.addOption("full_description", "Full description (no bug system)")
        self.addOption("brief_description", "Few-word summary (no bug system)")
        self.addSwitch("trigger_on_absence", "Trigger if given text is NOT present")
        self.addSwitch("internal_error", "Trigger even if other files differ (report as internal error)")
        self.addSwitch("trigger_on_success", "Trigger even if test would otherwise succeed")
    def correctTestClass(self):
        return True
    def getTitle(self):
        return "Report"
    def getScriptTitle(self, tab):
        return "Report Described Bugs"
    def getTabTitle(self):
        return "Bugs"
    def getPossibleFileStems(self):
        stems = []
        for test in self.currentTest.testCaseList():
            resultFiles, defFiles = test.listStandardFiles(allVersions=False)
            for fileName in resultFiles:
                stem = os.path.basename(fileName).split(".")[0]
                if not stem in stems:
                    stems.append(stem)
        # use for unrunnable tests...
        stems.append("free_text")
        return stems
    def checkSanity(self):
        if len(self.optionGroup.getOptionValue("search_string")) == 0:
            raise plugins.TextTestError, "Must fill in the field 'text or regexp to match'"
        if self.optionGroup.getOptionValue("bug_system") == "<none>":
            if len(self.optionGroup.getOptionValue("full_description")) == 0 or \
               len(self.optionGroup.getOptionValue("brief_description")) == 0:
                raise plugins.TextTestError, "Must either provide a bug system or fill in both description and summary fields"
        else:
            if len(self.optionGroup.getOptionValue("bug_id")) == 0:
                raise plugins.TextTestError, "Must provide a bug ID if bug system is given"
    def versionSuffix(self):
        version = self.optionGroup.getOptionValue("version")
        if len(version) == 0:
            return ""
        else:
            return "." + version
    def getFileName(self):
        name = "knownbugs." + self.currentTest.app.name + self.versionSuffix()
        return os.path.join(self.currentTest.getDirectory(), name)
    def write(self, writeFile, message):
        writeFile.write(message)
        guilog.info(message)
    def performOnCurrent(self):
        self.checkSanity()
        fileName = self.getFileName()
        guilog.info("Recording known bugs to " + fileName + " : ")
        writeFile = open(fileName, "a")
        self.write(writeFile, "\n[Reported by " + os.getenv("USER", "Windows") + " at " + plugins.localtime() + "]\n")
        for name, option in self.optionGroup.options.items():
            value = option.getValue()
            if name != "version" and len(value) != 0 and value != "<none>":
                self.write(writeFile, name + ":" + value + "\n")
        for name, switch in self.optionGroup.switches.items():
            if switch.getValue():
                self.write(writeFile, name + ":1\n")
        writeFile.close()
        self.currentTest.filesChanged()

class RecomputeTest(InteractiveTestAction):
    def isActiveOnCurrent(self):
        return InteractiveTestAction.isActiveOnCurrent(self) and \
               self.currentTest.state.hasStarted() and not self.currentTest.state.isComplete()
    def notifyNewTestSelection(self, tests):
        InteractiveTestAction.notifyNewTestSelection(self, tests)
        if self.currentTest and self.currentTest.needsRecalculation():
            self.perform()
    def getTitle(self):
        return "Progress"
    def getScriptTitle(self, tab):
        return "Recompute progress"
    def messageBeforePerform(self):
        return "Recomputing status of " + repr(self.currentTest) + " ..."
    def messageAfterPerform(self):
        return "Done recomputing status of " + repr(self.currentTest) + "."
    def performOnCurrent(self):
        self.currentTest.app.configObject.recomputeProgress(self.currentTest, self.observers)
    
# Placeholder for all classes. Remember to add them!
class InteractiveActionHandler:
    def __init__(self):
        self.actionPreClasses = [ Quit, ViewFile ]
        self.actionDynamicClasses = [ SaveTests, RecomputeTest ]
        self.actionStaticClasses = [ RecordTest, CopyTest, ImportTestCase, ImportTestSuite, \
                                     CreateDefinitionFile, ReportBugs, SelectTests, \
                                     RunTests, ResetGroups, RemoveTest ]
        self.actionPostClasses = [ SaveSelection ]
        self.optionGroupMap = {}
        self.diag = plugins.getDiagnostics("Interactive Actions")
    def storeOptionGroup(self, className, instance):
        self.optionGroupMap[className] = instance.getOptionGroups()
    def getMode(self, dynamic):
        if dynamic:
            return "Dynamic"
        else:
            return "Static"
    def getListedInstances(self, list, *args):
        instances = []
        for intvActionClass in list:
            instance = self.makeInstance(intvActionClass, *args)
            if instance:
                instances.append(instance)
        return instances
    def getInstances(self, dynamic, *args):
        instances = self.getListedInstances(self.actionPreClasses, dynamic, *args)
        modeClassList = eval("self.action" + self.getMode(dynamic) + "Classes")
        instances += self.getListedInstances(modeClassList, *args)
        instances += self.getListedInstances(self.actionPostClasses, dynamic, *args)
        return instances
    def makeInstance(self, intvActionClass, *args):
        instance = self.makeInstanceObject(intvActionClass, *args)
        if instance.isActive():
            self.storeOptionGroup(intvActionClass, instance)
            return instance
    def makeInstanceObject(self, intvActionClass, *args):
        self.diag.info("Trying to create action for " + intvActionClass.__name__)
        basicInstance = intvActionClass(*args)
        module = basicInstance.getConfigValue("interactive_action_module")
        command = "from " + module + " import " + intvActionClass.__name__ + " as realClassName"
        try:
            exec command
            self.diag.info("Used derived version from module " + module)
            return realClassName(*args)
        except ImportError:
            self.diag.info("Used basic version")
            return basicInstance
        except:
            # If some invalid interactive action is provided, need to know which
            print "Error with interactive action", intvActionClass.__name__
            raise sys.exc_type, sys.exc_value
        
interactiveActionHandler = InteractiveActionHandler()
guilog = None

def setUpGuiLog(dynamic):
    global guilog
    if dynamic:
        guilog = plugins.getDiagnostics("dynamic GUI behaviour")
    else:
        guilog = plugins.getDiagnostics("static GUI behaviour")
