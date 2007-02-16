
import plugins, os, sys, shutil, string, types, time
from copy import copy
from threading import Thread
from glob import glob
from Queue import Queue, Empty
global scriptEngine
global processTerminationMonitor
from log4py import LOGLEVEL_NORMAL

class GUIConfig:
    def __init__(self, dynamic):
        self.apps = []
        self.dynamic = dynamic
    def addSuites(self, suites):
        self.apps = [ suite.app for suite in suites ]
    def _simpleValue(self, app, entryName):
        return app.getConfigValue(entryName)
    def _compositeValue(self, app, sectionName, entryName):
        return app.getCompositeConfigValue(sectionName, entryName)
    def _getFromApps(self, method, *args):
        prevValue = None
        for app in self.apps:
            currValue = method(app, *args)
            if not prevValue is None and currValue != prevValue:
                plugins.printWarning("GUI configuration differs between applications, ignoring that from " + repr(app))
            else:
                prevValue = currValue
        return prevValue
    def getModeName(self):
        if self.dynamic:
            return "dynamic"
        else:
            return "static"
    def getConfigName(self, name, modeDependent):
        formattedName = name.lower().replace(" ", "_").replace(":", "_")
        if modeDependent:
            if len(name) > 0:
                return self.getModeName() + "_" + formattedName
            else:
                return self.getModeName()
        else:
            return formattedName
        
    def getValue(self, entryName, modeDependent=False):
        nameToUse = self.getConfigName(entryName, modeDependent)
        return self._getFromApps(self._simpleValue, nameToUse)
    def getCompositeValue(self, sectionName, entryName, modeDependent=False):
        nameToUse = self.getConfigName(entryName, modeDependent)
        value = self._getFromApps(self._compositeValue, sectionName, nameToUse)
        if modeDependent and value is None:
            return self.getCompositeValue(sectionName, entryName)
        else:
            return value
    def getWindowOption(self, name):
        return self.getCompositeValue("window_size", name, modeDependent=True)

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
    def __init__(self):
        plugins.Observable.__init__(self)
        self.optionGroup = plugins.OptionGroup(self.getTabTitle())
    def __repr__(self):
        if self.optionGroup.name:
            return self.optionGroup.name
        else:
            return self.getTitle()
    def addSuites(self, suites):
        pass
    def getOptionGroups(self):
        if self.optionGroup.empty():
            return []
        else:
            return [ self.optionGroup ]
    def updateForStateChange(self, test, state):
        return False, False
    def updateForSelectionChange(self):
        if self.isActiveOnCurrent():
            return self.updateForSelection()
        else:
            return False, False
    def updateForSelection(self):
        return False, False
    def isActiveOnCurrent(self):
        return True
    def canPerform(self):
        return True # do we activate this via performOnCurrent() ?

    # Should we create a gtk.Action? (or connect to button directly ...)
    def inMenuOrToolBar(self): 
        return self.hasBuiltInGUIDescription() or self.getMainMenuPath() != "-" or self.inToolBar() or self.getTestPopupMenuPath() != "-" or self.inButtonBar()
    # Is this a built-in action? If so, we'll assume the appropriate XML code
    # is given by an outside definition file.
    def hasBuiltInGUIDescription(self):
        return False
    # Put the action in a menu/submenu? Use / to separate submenus.
    def getMainMenuPath(self):
        return "_Actions" # '-' is special, and means 'don't put in menu'.
    # Put the action in the test popup menu?  Use / to separate submenus.
    def getTestPopupMenuPath(self):
        return "-" # '-' is special, and means 'don't put in popup menu'.
    # Put the action in the (main) toolbar?
    def inToolBar(self): 
        return True
    # Put the action in a button bar?
    def inButtonBar(self):
        return False
    def separatorBeforeInToolBar(self):
        return False
    def separatorAfterInToolBar(self):
        return False
    def separatorBeforeInMainMenu(self):
        return False
    def separatorAfterInMainMenu(self):
        return False
    def separatorBeforeInTestPopupMenu(self):
        return False
    def separatorAfterInTestPopupMenu(self):
        return False
    def getStockId(self): # The stock ID for the action, in toolbar and menu.
        pass
    def getTooltip(self):
        return self.getScriptTitle(False)
    def getDialogType(self): # The dialog type to launch on action execution.
        return ""
    def getTitle(self, includeMnemonics=False):
        title = self._getTitle()
        if includeMnemonics:
            return title
        else:
            return title.replace("_", "")
    def getDirectories(self, inputDirs=[], name=""):
	return ([], None)
    def messageBeforePerform(self):
        # Don't change this by default, most of these things don't take very long
        pass
    def messageAfterPerform(self):
        return "Performed '" + self.getTooltip() + "' on " + self.describeTests() + "."
    def getDoubleCheckMessage(self):
        return ""
    def getTabTitle(self):
        return self.getGroupTabTitle()
    def getGroupTabTitle(self):
        # Default behaviour is not to create a group tab, override to get one...
        return "Test"
    def getScriptTitle(self, tab):
        baseTitle = self._getScriptTitle()
        if tab and self.inMenuOrToolBar():
            return baseTitle + " from tab"
        else:
            return baseTitle
    def _getScriptTitle(self):
        return self.getTitle()
    def addOption(self, key, name, value = "", possibleValues = [],
                  allocateNofValues = -1, description = "",
                  selectDir = False, selectFile = False):
        self.optionGroup.addOption(key, name, value, possibleValues,
                                   allocateNofValues, selectDir,
                                   selectFile, description)
    def addSwitch(self, key, name, defaultValue = 0, options = [], description = ""):
        self.optionGroup.addSwitch(key, name, defaultValue, options, description)
    def startExternalProgram(self, *args):
        process = plugins.BackgroundProcess(*args)
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
        process = self.startExternalProgram(commandLine, description, exitHandler, exitHandlerArgs, shellTitle, holdShell)
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
    def __init__(self):
        InteractiveAction.__init__(self)
        self.currTestSelection = []
    def notifyNewTestSelection(self, tests, direct):
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
    def getCmdlineOption(self):
        selTestPaths = []
        for test in self.currTestSelection:
            relPath = test.getRelPath()
            if not relPath in selTestPaths:
                selTestPaths.append(relPath)
        return "-tp " + string.join(selTestPaths, ",")
    
class Quit(InteractiveAction):
    def __init__(self, dynamic):
        InteractiveAction.__init__(self)
    # We'll assume the appropriate XML code is given by an outside definition file.
    def hasBuiltInGUIDescription(self):
        return True
    def getStockId(self):
        return "quit"
    def _getTitle(self):
        return "_Quit"
    def messageAfterPerform(self):
        # Don't provide one, the GUI isn't there to show it :)
        pass
    def performOnCurrent(self):
        # Generate a window closedown, so that the quit button behaves the same as closing the window
        self.notify("Exit")
    def getDoubleCheckMessage(self):
        processesToReport = guiConfig.getCompositeValue("query_kill_processes", "", modeDependent=True)
        runningProcesses = processTerminationMonitor.listRunning(processesToReport)
        if len(runningProcesses) == 0:
            return ""
        else:
            return "\nThese processes are still running, and will be terminated when quitting: \n\n   + " + string.join(runningProcesses, "\n   + ") + "\n\nQuit anyway?\n"

# The class to inherit from if you want test-based actions that can run from the GUI
class InteractiveTestAction(InteractiveAction):
    def __init__(self):
        InteractiveAction.__init__(self)
        self.currentTest = None
    def getCompositeConfigValue(self, section, name):
        if self.currentTest:
            return self.currentTest.getCompositeConfigValue(section, name)
        else:
            return guiConfig.getCompositeValue(section, name)
    def isActiveOnCurrent(self):
        return self.currentTest is not None and self.correctTestClass()
    def correctTestClass(self):
        return self.currentTest.classId() == "test-case"
    def describeTests(self):
        return repr(self.currentTest)
    def inToolBar(self):
        return False
    def inButtonBar(self):
        return len(self.getOptionGroups()) == 0
    def getViewCommand(self, fileName):
        stem = os.path.basename(fileName).split(".")[0]
        viewProgram = self.getCompositeConfigValue("view_program", stem)
        if not plugins.canExecute(viewProgram):
            raise plugins.TextTestError, "Cannot find file editing program '" + viewProgram + \
                  "'\nPlease install it somewhere on your PATH or point the view_program setting at a different tool"
        cmd = viewProgram + " \"" + fileName + "\"" + plugins.nullRedirect()
        if os.name == "posix":
            cmd = "exec " + cmd # best to avoid shell messages etc.
        return cmd, viewProgram
    def notifyNewTestSelection(self, tests, direct):
        if len(tests) == 1:
            self.currentTest = tests[0]
        elif len(tests) > 1:
            self.currentTest = None
    def viewFile(self, fileName, refreshContents=False, refreshFiles=False):
        exitHandler = None
        if refreshFiles:
            exitHandler = self.currentTest.filesChanged
        elif refreshContents:
            exitHandler = self.currentTest.contentChanged

        commandLine, descriptor = self.getViewCommand(fileName)
        description = descriptor + " " + os.path.basename(fileName)
        refresh = str(int(refreshContents or refreshFiles))
        guilog.info("Viewing file " + fileName + " using '" + descriptor + "', refresh set to " + str(refresh))
        process = self.startViewer(commandLine, description=description, exitHandler=exitHandler)
        scriptEngine.monitorProcess("views and edits test files", process, [ fileName ])
    def startViewer(self, commandLine, description = "", exitHandler=None, exitHandlerArgs=(), \
                    shellTitle = None, holdShell = 0):
        testDesc = self.testDescription()
        fullDesc = description + testDesc
        process = self.startExternalProgram(commandLine, fullDesc, exitHandler, exitHandlerArgs, shellTitle, holdShell)
        self.notify("Status", 'Started "' + description + '" in background' + testDesc + '.')
        return process
    def testDescription(self):
        if self.currentTest:
            return " (from test " + self.currentTest.uniqueName + ")"
        else:
            return ""
        
# Plugin for saving tests (standard)
class SaveTests(SelectionAction):
    def __init__(self):
        SelectionAction.__init__(self)
        self.addOption("v", "Version to save")
        self.addSwitch("over", "Replace successfully compared files also", 0)
        self.currFileSelection = []
        self.currApps = []
        self.currTestDescription = ""
    # We'll assume the appropriate XML code is given by an outside definition file.
    def hasBuiltInGUIDescription(self):
        return True
    def getStockId(self):
        return "save"
    def getTabTitle(self):
        return "Saving"
    def _getTitle(self):
        return "_Save"
    def _getScriptTitle(self):
        return "Save results for selected tests"
    def messageBeforePerform(self):
        self.currTestDescription = self.describeTests()
        return "Saving " + self.currTestDescription + " ..."
    def messageAfterPerform(self):
        # Test selection is reset after a save, use the description from before 
        return "Saved " + self.currTestDescription + "."
    def getSelectedApps(self):
        apps = []
        for test in self.currTestSelection:
            if test.app not in apps:
                apps.append(test.app)
        return apps
    def updateForSelection(self):
        apps = self.getSelectedApps()
        if apps == self.currApps:
            return False, False
        self.currApps = apps
        self.optionGroup.setOptionValue("v", self.getDefaultSaveOption(apps))
        self.optionGroup.setPossibleValues("v", self.getPossibleVersions(apps))
        if self.diagnosticMode(apps):
            self.addSwitch("newdiag", "Save all new files as diagnostics", 1)
            return True, True
        elif self.hasPerformance(apps) and not self.optionGroup.switches.has_key("ex"):
            self.addSwitch("ex", "Save: ", 1, ["Average performance", "Exact performance"])
            return True, True
        else:
            return False, True
    def diagnosticMode(self, apps):
        return apps[0].inputOptions.has_key("diag")
    def getDefaultSaveOption(self, apps):
        saveVersions = self.getSaveVersions(apps)
        if saveVersions.find(",") != -1:
            return "<default> - " + saveVersions
        else:
            return saveVersions
    def getPossibleVersions(self, apps):
        extensions = []
        for app in apps:
            for ext in app.getSaveableVersions():
                if not ext in extensions:
                    extensions.append(ext)
        # Include the default version always
        extensions.append("")
        return extensions
    def getSaveVersions(self, apps):
        saveVersions = []
        for app in apps:
            ver = self.getDefaultSaveVersion(app)
            if not ver in saveVersions:
                saveVersions.append(ver)
        return string.join(saveVersions, ",")
    def getDefaultSaveVersion(self, app):
        return app.getFullVersion(forSave = 1)
    def hasPerformance(self, apps):
        for app in apps:
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
    def newFilesAsDiags(self):
        return int(self.optionGroup.getSwitchValue("newdiag", 0))
    def performOnCurrent(self):
        saveDesc = ", exactness " + str(self.getExactness())
        if len(self.currFileSelection) > 0:
            saveDesc += ", only " + string.join(self.currFileSelection, ",")
        overwriteSuccess = self.optionGroup.getSwitchValue("over")
        if overwriteSuccess:
            saveDesc += ", overwriting both failed and succeeded files"

        stemsToSave = [ fileName.split(".")[0] for fileName in self.currFileSelection ] 
        for test in self.currTestSelection:
            if not test.state.isSaveable():
                continue
            version = self.getVersion(test)
            fullDesc = " - version " + version + saveDesc
            self.describe(test, fullDesc)
            testComparison = test.state
            testComparison.setObservers(self.observers)
            if testComparison:
                testComparison.save(test, self.getExactness(), version, overwriteSuccess, self.newFilesAsDiags(), stemsToSave)
                newState = testComparison.makeNewState(test.app)
                test.changeState(newState)
          
# Plugin for viewing files (non-standard). In truth, the GUI knows a fair bit about this action,
# because it's special and plugged into the tree view. Don't use this as a generic example!
class ViewFile(InteractiveTestAction):
    def __init__(self, dynamic):
        InteractiveTestAction.__init__(self)
        self.dynamic = dynamic
        if dynamic:
            self.addDifferenceSwitches()
    def inMenuOrToolBar(self):
        return False
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
    def updateForStateChange(self, test, state):
        if test is self.currentTest:
            return self.updateForState(state)
        else:
            return False, False
    def updateForSelection(self):
        return self.updateForState(self.currentTest.state)
    def updateForState(self, state):
        if not self.dynamic:
            return False, False

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
        changed = len(self.optionGroup.switches) != origCount
        return changed, changed
    def notifyNewTestSelection(self, tests, direct):
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
        followProgram = self.currentTest.getConfigValue("follow_program")
        if not plugins.canExecute(followProgram):
            raise plugins.TextTestError, "Cannot find file-following program '" + followProgram + \
                  "'\nPlease install it somewhere on your PATH or point the follow_program setting at a different tool"
        guilog.info("Following file " + fileName + " using '" + followProgram + "'")
        description = followProgram + " " + os.path.basename(fileName)
        baseName = os.path.basename(fileName)
        title = self.currentTest.name + " (" + baseName + ")"
        process = self.startViewer(followProgram + " " + fileName, description=description, shellTitle=title)
        scriptEngine.monitorProcess("follows progress of test files", process)
    def isTestDefinition(self, stem, fileName):
        if not self.currentTest:
            return False
        defFile = self.currentTest.getFileName(stem)
        if defFile:
            return plugins.samefile(fileName, defFile)
        else:
            return False
    def notifyViewFile(self, comparison, fileName):
        if self.optionGroup.getSwitchValue("f"):
            return self.followFile(self.fileToFollow(comparison, fileName))
        if not comparison:
            # refresh order of tests if this edited
            refreshContents = self.isTestDefinition("testsuite", fileName)
            # options file can change appearance of test (environment refs etc.)
            refreshFiles = self.isTestDefinition("options", fileName)
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
        diffProgram = self.currentTest.getConfigValue("diff_program")
        if not plugins.canExecute(diffProgram):
            raise plugins.TextTestError, "Cannot find graphical difference program '" + diffProgram + \
                  "'\nPlease install it somewhere on your PATH or point the diff_program setting at a different tool"
        stdFile = self.stdFile(comparison)
        tmpFile = self.tmpFile(comparison)
        description = diffProgram + " " + os.path.basename(stdFile) + " " + os.path.basename(tmpFile)
        guilog.info("Starting graphical difference comparison using '" + diffProgram + "':")
        guilog.info("-- original file : " + stdFile)
        guilog.info("--  current file : " + tmpFile)
        commandLine = diffProgram + ' "' + stdFile + '" "' + tmpFile + '" ' + plugins.nullRedirect()
        process = self.startViewer(commandLine, description=description)
        scriptEngine.monitorProcess("shows graphical differences in test files", process)

# And a generic import test. Note acts on test suites
class ImportTest(InteractiveTestAction):
    def __init__(self):
        InteractiveTestAction.__init__(self)
        self.optionGroup.addOption("name", self.getNameTitle())
        self.optionGroup.addOption("desc", self.getDescTitle(), description="Enter a description of the new " + self.testType().lower() + " which will be inserted as a comment in the testsuite file.")
        self.optionGroup.addOption("testpos", self.getPlaceTitle(), "last in suite", allocateNofValues=2, description="Where in the test suite should the test be placed?")
        self.testImported = None
    def getDoubleCheckMessage(self):
        testName = self.getNewTestName()
        suite = self.getDestinationSuite()
        self.checkName(suite, testName)
        newDir = os.path.join(suite.getDirectory(), testName)
        if os.path.isdir(newDir):
            if self.testFilesExist(newDir, suite.app):
                raise plugins.TextTestError, "Test already exists for application " + suite.app.fullName + \
                      " : " + os.path.basename(newDir)
            
            return "Test directory already exists for '" + testName + "'\nAre you sure you want to use this name?"
        else:
            return ""
    def testFilesExist(self, dir, app):
        for fileName in os.listdir(dir):
            parts = fileName.split(".")
            if len(parts) > 1 and parts[1] == app.name:
                return True
        return False
    def inMenuOrToolBar(self):
        return False
    def correctTestClass(self):
        return self.currentTest.classId() == "test-suite"
    def getNameTitle(self):
        return self.testType() + " Name"
    def getDescTitle(self):
        return self.testType() + " Description"
    def getPlaceTitle(self):
        return "Place " + self.testType()
    def updateForSelection(self):
        self.optionGroup.setOptionValue("name", self.getDefaultName())
        self.optionGroup.setOptionValue("desc", self.getDefaultDesc())
        self.setPlacements(self.currentTest)
        return False, True
    def setPlacements(self, suite):
        if suite.classId() == "test-case":
            suite = suite.parent
        # Add suite and its children
        placements = [ "first in suite" ]
        for test in suite.testcases:
            placements += [ "after " + test.name ]
        placements.append("last in suite")

        self.optionGroup.setPossibleValuesUpdate("testpos", placements)
        self.optionGroup.getOption("testpos").reset()                    
    def getDefaultName(self):
        return ""
    def getDefaultDesc(self):
        return ""
    def getTabTitle(self):
        return "Adding " + self.testType()
    def _getTitle(self):
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
        suite = self.getDestinationSuite()
            
        guilog.info("Adding " + self.testType() + " " + testName + " under test suite " + \
                    repr(suite) + ", placed " + self.optionGroup.getOptionValue("testpos"))
        placement = self.getPlacement()
        description = self.optionGroup.getOptionValue("desc")
        testDir = suite.writeNewTest(testName, description, placement)
        self.testImported = self.createTestContents(suite, testDir, description, placement)
    def getDestinationSuite(self):
        return self.currentTest
    def getPlacement(self):
        option = self.optionGroup.getOption("testpos")
        return option.possibleValues.index(option.getValue())
    def checkName(self, suite, testName):
        if len(testName) == 0:
            raise plugins.TextTestError, "No name given for new " + self.testType() + "!" + "\n" + \
                  "Fill in the 'Adding " + self.testType() + "' tab below."
        if testName.find(" ") != -1:
            raise plugins.TextTestError, "The new " + self.testType() + \
                  " name is not permitted to contain spaces, please specify another"
        for test in suite.testcases:
            if test.name == testName:
                raise plugins.TextTestError, "A " + self.testType() + " with the name '" + \
                      testName + "' already exists, please choose another name"


class RecordTest(InteractiveTestAction):
    def __init__(self):
        InteractiveTestAction.__init__(self)
        self.recordTime = None
        self.addOption("v", "Version to record")
        self.addOption("c", "Checkout to use for recording") 
        self.addSwitch("rep", "Automatically replay test after recording it", 1)
        self.addSwitch("repgui", "", defaultValue = 0, options = ["Auto-replay invisible", "Auto-replay in dynamic GUI"])            
    def inMenuOrToolBar(self):
        return False
    def getTabTitle(self):
        return "Recording"
    def messageAfterPerform(self):
        return "Started record session for " + repr(self.currentTest)
    def performOnCurrent(self):
        guilog.info("Starting dynamic GUI in record mode...")
        self.updateRecordTime(self.currentTest)
        self.startTextTestProcess(self.currentTest, "record")
    def getRecordMode(self):
        return self.currentTest.getConfigValue("use_case_record_mode")
    def isActiveOnCurrent(self):
        return InteractiveTestAction.isActiveOnCurrent(self) and self.getRecordMode() != "disabled"
    def updateForSelection(self):
        self.optionGroup.setOptionValue("v", self.currentTest.app.getFullVersion(forSave=1))
        self.optionGroup.setOptionValue("c", self.currentTest.app.checkout)
        if self.getRecordMode() == "console" and not self.optionGroup.switches.has_key("hold"):
            self.addSwitch("hold", "Hold record shell after recording")
            return True, True
        else:
            return False, False
    def updateRecordTime(self, test):
        if self.updateRecordTimeForFile(test, "usecase", "USECASE_RECORD_SCRIPT", "target_record"):
            return True
        if self.getRecordMode() == "console" and self.updateRecordTimeForFile(test, "input", "USECASE_RECORD_STDIN", "target"):
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
    def _getTitle(self):
        return "Record _Use-Case"
    
class ImportTestCase(ImportTest):
    def __init__(self):
        ImportTest.__init__(self)
        self.addDefinitionFileOption()
    def testType(self):
        return "Test"
    def addDefinitionFileOption(self):
        self.addOption("opt", "Command line options")
    def createTestContents(self, suite, testDir, description, placement):
        self.writeDefinitionFiles(suite, testDir)
        self.writeEnvironmentFile(suite, testDir)
        self.writeResultsFiles(suite, testDir)
        return suite.addTestCase(os.path.basename(testDir), description, placement)
    def getWriteFileName(self, name, suite, testDir):
        return os.path.join(testDir, name + "." + suite.app.name)
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
    def __init__(self):
        ImportTest.__init__(self)
        self.addEnvironmentFileOptions()
    def testType(self):
        return "Suite"
    def createTestContents(self, suite, testDir, description, placement):
        self.writeEnvironmentFiles(suite, testDir)
        return suite.addTestSuite(os.path.basename(testDir), description, placement)
    def addEnvironmentFileOptions(self):
        self.addSwitch("env", "Add environment file")
    def writeEnvironmentFiles(self, suite, testDir):
        if self.optionGroup.getSwitchValue("env"):
            envFile = os.path.join(testDir, "environment")
            file = open(envFile, "w")
            file.write("# Dictionary of environment to variables to set in test suite\n")

class SelectTests(SelectionAction):
    def __init__(self, commandOptionGroups):
        SelectionAction.__init__(self)
        self.rootTestSuites = []
        self.diag = plugins.getDiagnostics("Select Tests")
        self.addOption("vs", "Tests for version")
        self.addSwitch("select_in_collapsed_suites", "Select in collapsed suites", 0)
        self.addSwitch("current_selection", "Current selection:", options = [ "Discard", "Refine", "Extend", "Exclude"], description="How should we treat the currently selected tests?\n - Discard: Unselect all currently selected tests before applying the new selection criteria.\n - Refine: Apply the new selection criteria only to the currently selected tests, to obtain a subselection.\n - Extend: Keep the currently selected tests even if they do not match the new criteria, and extend the selection with all other tests which meet the new criteria.\n - Exclude: After applying the new selection criteria to all tests, unselect the currently selected tests, to exclude them from the new selection.")
        
        self.appSelectGroup = commandOptionGroups[0]
        self.optionGroup.options += self.appSelectGroup.options
        self.optionGroup.switches += self.appSelectGroup.switches
    def addSuites(self, suites):
        self.rootTestSuites = suites
        possVersions = []
        for suite in suites:
            for possVersion in self.getPossibleVersions(suite.app):
                if possVersion not in possVersions:
                    possVersions.append(possVersion)
        self.optionGroup.setPossibleValues("vs", possVersions)
    def getPossibleVersions(self, app):
        fullVersion = app.getFullVersion()
        extraVersions = app.getExtraVersions(forUse=False)
        if len(fullVersion) == 0:
            return [ "<default>" ] + extraVersions
        else:
            return [ fullVersion ] + [ fullVersion + "." + extra for extra in extraVersions ]
    def isActiveOnCurrent(self):
        return True
    def hasBuiltInGUIDescription(self):
        return True
    def getStockId(self):
        return "refresh"
    def _getTitle(self):
        return "_Select"
    def _getScriptTitle(self):
        return "Select indicated tests"
    def getGroupTabTitle(self):
        return "Selection"
    def getDirectories(self, name=""):
        if name == "Tests listed in file":
            apps = guiConfig.apps
            if len(apps) > 0:
                dirs = apps[0].configObject.getFilterFileDirectories(apps)
                # Set first non-empty dir as default ...)
                for dir in dirs:
                    if os.path.isdir(os.path.abspath(dir[1])) and \
                       len(os.listdir(os.path.abspath(dir[1]))) > 0:
                        return (dirs, dir[1])
                return (dirs, dirs[0][1])
            else:
                return ([], None)
        else:
            return ([], None)
    def messageBeforePerform(self):
        return "Selecting tests ..."
    def messageAfterPerform(self):
        return "Selected " + self.describeTests() + "."    
    # No messageAfterPerform necessary - we update the status bar when the selection changes inside TextTestGUI
    def getFilterList(self, app):
        app.configObject.updateOptions(self.appSelectGroup)
        return app.configObject.getFilterList(app, False)
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
        self.notify("SetTestSelection", selectedTests, self.optionGroup.getSwitchValue("select_in_collapsed_suites"))
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
    # We'll assume the appropriate XML code is given by an outside definition file.
    def hasBuiltInGUIDescription(self):
        return True
    def getStockId(self):
        return "revert-to-saved"
    def _getTitle(self):
        return "R_eset"
    def messageAfterPerform(self):
        return "All options reset to default values."
    def _getScriptTitle(self):
        return "Reset running options"
    def performOnCurrent(self):
        self.notify("Reset")

class SaveSelection(SelectionAction):
    def __init__(self, commandOptionGroups):
        SelectionAction.__init__(self)
        self.selectionGroup = commandOptionGroups[0]
        self.fileName = ""
        self.saveTestList = ""
    def hasBuiltInGUIDescription(self):
        return True
    def getStockId(self):
        return "save-as"
    def getDialogType(self):
        return "guidialogs.SaveSelectionDialog" # Since guiplugins cannot depend on gtk, we cannot call dialog ourselves ...
    def _getTitle(self):
        return "S_ave Selection..."
    def _getScriptTitle(self):
        return "Save selected tests in file"
    def dialogEnableOptions(self):
        return not guiConfig.dynamic
    def getDirectories(self, name=""):
        apps = guiConfig.apps
        dirs = apps[0].configObject.getFilterFileDirectories(apps)
        if len(dirs) > 0:
            return (dirs, dirs[0][1])
        else:
            return (dirs, None)
    def saveActualTests(self):
        return guiConfig.dynamic or self.saveTestList
    def getTextToSave(self):
        actualTests = self.saveActualTests()
        if actualTests:
            return self.getCmdlineOption()
        else:
            return string.join(self.selectionGroup.getCommandLines(useQuotes=False))
    def performOnCurrent(self):
        toWrite = self.getTextToSave()
        try:
            file = open(self.fileName, "w")
            file.write(toWrite + "\n")
            file.close()
        except IOError, e:
            raise plugins.TextTestError, "\nFailed to save selection:\n" + str(e) + "\n"
    def messageAfterPerform(self):
        return "Saved " + self.describeTests() + " in file '" + self.fileName+ "'."


class RunningAction(SelectionAction):
    runNumber = 1
    def __init__(self, commandOptionGroups):
        SelectionAction.__init__(self)
        for group in commandOptionGroups:
            if group.name.startswith("Invisible"):
                self.invisibleGroup = group
            elif group.name.startswith("Select"):
                self.selectionGroup = group
    def messageAfterPerform(self):
        return self.performedDescription() + " " + self.describeTests() + " at " + plugins.localtime() + "."
    def performOnCurrent(self):
        app = self.currTestSelection[0].app
        writeDir = os.path.join(app.writeDirectory, "dynamic_run" + str(self.runNumber))
        plugins.ensureDirectoryExists(writeDir)
        filterFile = self.writeFilterFile(writeDir)
        ttOptions = self.getTextTestOptions(filterFile, app)
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
    def getTextTestOptions(self, filterFile, app):
        ttOptions = [ self.getCmdlineOptionForApps() ]
        ttOptions += self.invisibleGroup.getCommandLines(useQuotes=True)
        for group in self.getOptionGroups():
            ttOptions += group.getCommandLines(useQuotes=True)
        ttOptions.append("-f " + filterFile)
        ttOptions.append("-fd " + self.getTmpFilterDir(app))
        return string.join(ttOptions)
    def getTmpFilterDir(self, app):
        return os.path.join(app.writeDirectory, "temporary_filter_files")
    def getCmdlineOptionForApps(self):
        apps = []
        for test in self.currTestSelection:
            if not test.app.name in apps:
                apps.append(test.app.name)
        return "-a " + string.join(apps, ",")
    def checkTestRun(self, identifierString, errFile, testSel):
        try:
            self.notifyIfMainThread("ActionStart", "")
            for test in testSel:
                self.notifyIfMainThread("Status", "Updating files for " + repr(test) + " ...")
                self.notifyIfMainThread("ActionProgress", "")
                test.filesChanged()
            scriptEngine.applicationEvent(self.getUseCaseName() + " GUI to be closed")
            if os.path.isfile(errFile):
                errText = open(errFile).read()
                if len(errText):
                    raise plugins.TextTestError, "Dynamic run failed, with the following errors:\n" + errText
        finally:
            self.notifyIfMainThread("Status", "Done updating after dynamic run " + identifierString + ".")
            self.notifyIfMainThread("ActionStop", "")


class ReconnectToTests(RunningAction):
    def __init__(self, commandOptionGroups):
        RunningAction.__init__(self, commandOptionGroups)
        self.addOption("v", "Version to reconnect to")
        self.addOption("reconnect", "Temporary result directory", os.getenv("TEXTTEST_TMP"), description="Specify a directory containing temporary texttest results. The reconnection will use a random subdirectory matching the version used.")
        self.addSwitch("reconnfull", "Results:", 0, ["Display as they were", "Recompute from files"])
    def getGroupTabTitle(self):
        return "Running"
    def hasBuiltInGUIDescription(self):
        return True
    def getStockId(self):
        return "connect"
    def _getTitle(self):
        return "Re_connect"
    def _getScriptTitle(self):
        return "Reconnect to previously run tests"
    def getTabTitle(self):
        return "Reconnect"
    def performedDescription(self):
        return "Reconnected to"
    def getUseCaseName(self):
        return "reconnect"

class RunTests(RunningAction):
    def __init__(self, commandOptionGroups):
        RunningAction.__init__(self, commandOptionGroups)
        self.optionGroups = []
        for group in commandOptionGroups:
            if not group.name.startswith("Invisible") and not group.name.startswith("Select"):
                self.optionGroups.append(group)
    def getOptionGroups(self):
        return self.optionGroups
    # We'll assume the appropriate XML code is given by an outside definition file.
    def hasBuiltInGUIDescription(self):
        return True
    def _getTitle(self):
        return "_Run"
    def getStockId(self):
        return "execute"
    def _getScriptTitle(self):
        return "Run selected tests"
    def getGroupTabTitle(self):
        return "Running"
    def performedDescription(self):
        return "Started"
    def getUseCaseName(self):
        return "dynamic"

class CreateDefinitionFile(InteractiveTestAction):
    def __init__(self):
        InteractiveTestAction.__init__(self)
        self.configFile = None
        self.addOption("type", "Type of definition file to create", allocateNofValues=2)
    def inMenuOrToolBar(self):
        return False
    def correctTestClass(self):
        return True
    def _getTitle(self):
        return "Create _File"
    def getTabTitle(self):
        return "New File" 
    def getScriptTitle(self, tab):
        return "Create File"
    def getDiagConfigFileName(self):
        return self.currentTest.getCompositeConfigValue("diagnostics", "configuration_file")
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
    def updateForSelection(self):
        self.configFile = self.getDiagConfigFileName()
        defFiles = self.getDefinitionFiles()
        self.optionGroup.setValue("type", defFiles[0])
        self.optionGroup.setPossibleValues("type", defFiles)

        if self.configFile and not self.optionGroup.switches.has_key("diag"):
            self.addSwitch("diag", "Affect diagnostic mode only")
            return True, True
        else:
            return False, True
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

    def getSourceFile(self, fileName, targetFile):
        # Use the file from the level above, if possible
        if not self.currentTest.parent:
            return None

        if self.optionGroup.getSwitchValue("diag"):
            thisTestName = self.currentTest.makePathName(fileName)
            if not plugins.samefile(thisTestName, targetFile):
                return thisTestName

        return self.currentTest.parent.makePathName(fileName)            
    def performOnCurrent(self):
        fileName = self.getFileName()
        targetFile = os.path.join(self.getTargetDirectory(), fileName)
        sourceFile = self.getSourceFile(fileName, targetFile)
        plugins.ensureDirExistsForFile(targetFile)
        if sourceFile and os.path.isfile(sourceFile):
            guilog.info("Creating new file, copying " + sourceFile)
            shutil.copyfile(sourceFile, targetFile)
        elif not os.path.exists(targetFile):
            file = open(targetFile, "w")
            file.close()
            guilog.info("Creating new empty file...")
        else:
            raise plugins.TextTestError, "Unable to create file, no possible source found and target file already exists:\n" + targetFile 
        self.viewFile(targetFile, refreshFiles=True)

class RemoveTests(SelectionAction):
    def __init__(self):
        SelectionAction.__init__(self)
    def notifyNewTestSelection(self, tests, direct):
        self.currTestSelection = tests # interested in suites, unlike most SelectionActions
    def isActiveOnCurrent(self):
        for test in self.currTestSelection:
            if test.parent:
                return True
        return False
    def hasBuiltInGUIDescription(self):
        return True
    def _getTitle(self):
        return "Remove..."
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
        namesRemoved = []
        warnings = ""
        for test in self.currTestSelection:
            if not test.parent:
                warnings += "\nThe root suite\n'" + test.name + " (" + test.app.name + ")'\ncannot be removed.\n"
            else:
                dir = test.getDirectory()
                if os.path.isdir(dir): # might have already removed the enclosing suite
                    test.parent.removeTest(test)
                    namesRemoved.append(test.name)
        self.notify("Status", "Removed test(s) " + string.join(namesRemoved, ","))
        if warnings:
            raise plugins.TextTestWarning, warnings
        
    def messageAfterPerform(self):
        pass # do it as part of the method as currentTest will have changed by the end!

class CopyTest(ImportTest):
    def __init__(self):
        ImportTest.__init__(self)
        self.testToCopy = None
        self.optionGroup.removeOption("testpos")
        self.optionGroup.addOption("suite", "Copy to suite", "current", allocateNofValues = 2, description = "Which suite should the test be copied to?", changeMethod = self.updatePlacements)
        self.optionGroup.addOption("testpos", self.getPlaceTitle(), "last in suite", allocateNofValues = 2, description = "Where in the test suite should the test be placed?")
        self.optionGroup.addSwitch("keeporig", "Keep original", value = 1, description = "Should the original test be kept or removed?")
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
            if len(self.testToCopy.description) > 0:
                return self.testToCopy.description
            else:
                return "Copy of " + self.testToCopy.name
        else:
            return ""
    def _getTitle(self):
        return "_Copy"
    def getScriptTitle(self, tab):
        return "Copy Test"
    def updateForSelection(self):
        self.fillSuiteList()
        return ImportTest.updateForSelection(self)
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
    def notifyNewTestSelection(self, tests, direct):
        # apply to parent
        ImportTest.notifyNewTestSelection(self, tests, direct)
        if self.currentTest and self.currentTest.classId() == "test-case":
            self.testToCopy = self.currentTest
            self.currentTest = self.currentTest.parent
        else:
            self.testToCopy = None
    def createTestContents(self, suite, testDir, description, placement):
        stdFiles, defFiles = self.testToCopy.listStandardFiles(allVersions=True)
        for sourceFile in stdFiles + defFiles:
            dirname, local = os.path.split(sourceFile)
            if dirname == self.testToCopy.getDirectory():
                targetFile = os.path.join(testDir, local)
                shutil.copy2(sourceFile, targetFile)
        dataFiles = self.testToCopy.listDataFiles()
        for sourcePath in dataFiles:
            if os.path.isdir(sourcePath):
                continue
            targetPath = sourcePath.replace(self.testToCopy.getDirectory(), testDir)
            plugins.ensureDirExistsForFile(targetPath)
            shutil.copy2(sourcePath, targetPath)
        originalTest = self.testToCopy # Set to new test in call below ...
        originalSuite = self.currentTest # Also reset
        ret =  suite.addTestCase(os.path.basename(testDir), description, placement)
        if not self.optionGroup.getSwitchValue("keeporig"):
            originalSuite.removeTest(originalTest)
        return ret
    
class ReportBugs(InteractiveTestAction):
    def __init__(self):
        InteractiveTestAction.__init__(self)
        self.addOption("search_string", "Text or regexp to match")
        self.addOption("search_file", "File to search in")
        self.addOption("version", "Version to report for")
        self.addOption("execution_hosts", "Trigger only when run on machine(s)")
        self.addOption("bug_system", "Extract info from bug system", "<none>", [ "bugzilla" ])
        self.addOption("bug_id", "Bug ID (only if bug system given)")
        self.addOption("full_description", "Full description (no bug system)")
        self.addOption("brief_description", "Few-word summary (no bug system)")
        self.addSwitch("trigger_on_absence", "Trigger if given text is NOT present")
        self.addSwitch("internal_error", "Trigger even if other files differ (report as internal error)")
        self.addSwitch("trigger_on_success", "Trigger even if test would otherwise succeed")
    def inMenuOrToolBar(self):
        return False
    def correctTestClass(self):
        return True
    def _getTitle(self):
        return "Report"
    def _getScriptTitle(self):
        return "Report Described Bugs"
    def getTabTitle(self):
        return "Bugs"
    def updateForSelection(self):
        self.optionGroup.setOptionValue("search_file", self.currentTest.app.getConfigValue("log_file"))
        self.optionGroup.setPossibleValues("search_file", self.getPossibleFileStems())
        self.optionGroup.setOptionValue("version", self.currentTest.app.getFullVersion())
        return False, False
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
    def __init__(self):
        InteractiveTestAction.__init__(self)
        self.recomputing = False
        self.chainReaction = False
    def isActiveOnCurrent(self):
        return InteractiveTestAction.isActiveOnCurrent(self) and \
               self.currentTest.state.hasStarted() and not self.currentTest.state.isComplete()
    def notifyNewTestSelection(self, tests, direct):
        InteractiveTestAction.notifyNewTestSelection(self, tests, direct)
        # Prevent recomputation triggering more...
        if self.recomputing:
            self.chainReaction = True
            return
        if self.currentTest and self.currentTest.needsRecalculation():
            self.recomputing = True
            self.currentTest.refreshFiles()
            self.perform()
            self.recomputing = False
            if self.chainReaction:
                self.chainReaction = False
                return "Recomputation chain reaction!"
    def inButtonBar(self):
        return True
    def _getTitle(self):
        return "_Update Info"
    def _getScriptTitle(self):
        return "Update test progress information and compare test files so far"
    def messageBeforePerform(self):
        return "Recomputing status of " + repr(self.currentTest) + " ..."
    def messageAfterPerform(self):
        return "Done recomputing status of " + repr(self.currentTest) + "."
    def performOnCurrent(self):
        self.currentTest.app.configObject.recomputeProgress(self.currentTest, self.observers)

class SortTestsAscending(InteractiveAction):
    def __init__(self):
        InteractiveAction.__init__(self)
        self.currTestSelection = []
    def hasBuiltInGUIDescription(self):
        return True
    def notifyNewTestSelection(self, tests, direct):
        self.currTestSelection = tests # interested in suites, unlike most SelectionActions
    def isActiveOnCurrent(self):
        return len(self.currTestSelection) == 1 and \
               self.currTestSelection[0].classId() == "test-suite" and \
               not self.currTestSelection[0].getConfigValue("auto_sort_test_suites")
    def getStockId(self):
        return "sort-ascending"
    def _getTitle(self):
        return "_Sort Suite"
    def messageAfterPerform(self):
        return "Sorted " + repr(self.currTestSelection[0]) + " in alphabetical order."
    def _getScriptTitle(self):
        return "sort selected test suite in alphabetical order"
    def performOnCurrent(self):
        self.performRecursively(self.currTestSelection[0], True)
    def performRecursively(self, suite, ascending):        
        # First ask all sub-suites to sort themselves
        errors = ""
        if self.currTestSelection[0].getConfigValue("sort_test_suites_recursively"):
            for test in suite.testcases:
                if test.classId() == "test-suite":
                    try:
                        self.performRecursively(test, ascending)
                    except Exception, e:
                        errors += str(e) + "\n" 

        self.notify("Status", "Sorting " + repr(suite))
        self.notify("ActionProgress", "")
        try:
            suite.sortTests(ascending)
        except Exception, e:
            errors += str(e) + "\n" 
        if errors:
            raise plugins.TextTestWarning, errors

class SortTestsDescending(SortTestsAscending):
    def getStockId(self):
        return "sort-descending"
    def _getTitle(self):
        return "_Reversed Sort Suite"
    def messageAfterPerform(self):
        return "Sorted " + repr(self.currTestSelection[0]) + " in reversed alphabetical order."
    def _getScriptTitle(self):
        return "sort selected test suite in reversed alphabetical order"
    def performOnCurrent(self):
        self.performRecursively(self.currTestSelection[0], False)

class RepositionTest(InteractiveAction):
    def __init__(self, position):
        InteractiveAction.__init__(self)
        self.position = position
        self.currTestSelection = []
        self.testToMove = None
    def hasBuiltInGUIDescription(self):
        return True
    def notifyNewTestSelection(self, tests, direct):
        self.currTestSelection = tests # interested in suites, unlike most SelectionActions
        if len(tests) == 1:
            self.testToMove = tests[0]
        else:
            self.testToMove = None
    def _isActiveOnCurrent(self):
        return len(self.currTestSelection) == 1 and \
               self.currTestSelection[0].parent and \
               not self.currTestSelection[0].parent.getConfigValue("auto_sort_test_suites")
    def performOnCurrent(self):
        self.testToMove.parent.repositionTest(self.testToMove, self.position)
        self.notify("RefreshTestSelection")
    
class RepositionTestDown(RepositionTest):
    def __init__(self):
        RepositionTest.__init__(self, "down")
    def getStockId(self):
        return "go-down"
    def _getTitle(self):
        return "Move down"
    def messageAfterPerform(self):
        return "Moved " + repr(self.testToMove) + " one step down in suite."
    def _getScriptTitle(self):
        return "Move selected test down in suite"
    def isActiveOnCurrent(self):
        if not self._isActiveOnCurrent():
            return False
        return self.currTestSelection[0].parent.testcases[len(self.currTestSelection[0].parent.testcases) - 1] != self.currTestSelection[0]

class RepositionTestUp(RepositionTest):
    def __init__(self):
        RepositionTest.__init__(self, "up")
    def getStockId(self):
        return "go-up"
    def _getTitle(self):
        return "Move up"
    def messageAfterPerform(self):
        return "Moved " + repr(self.testToMove) + " one step up in suite."
    def _getScriptTitle(self):
        return "Move selected test up in suite"
    def isActiveOnCurrent(self):
        if not self._isActiveOnCurrent():
            return False
        return self.currTestSelection[0].parent.testcases[0] != self.currTestSelection[0]

class RepositionTestFirst(RepositionTest):
    def __init__(self):
        RepositionTest.__init__(self, "first")
    def getStockId(self):
        return "goto-top"
    def _getTitle(self):
        return "Move to first"
    def messageAfterPerform(self):
        return "Moved " + repr(self.testToMove) + " to first in suite."
    def _getScriptTitle(self):
        return "Move selected test to first in suite"
    def isActiveOnCurrent(self):
        if not self._isActiveOnCurrent():
            return False
        return self.currTestSelection[0].parent.testcases[0] != self.currTestSelection[0]

class RepositionTestLast(RepositionTest):
    def __init__(self):
        RepositionTest.__init__(self, "last")
    def getStockId(self):
        return "goto-bottom"
    def _getTitle(self):
        return "Move to last"
    def messageAfterPerform(self):
        return "Moved " + repr(self.testToMove) + " to last in suite."
    def _getScriptTitle(self):
        return "Move selected test to last in suite"
    def isActiveOnCurrent(self):
        if not self._isActiveOnCurrent():
            return False
        return self.currTestSelection[0].parent.testcases[len(self.currTestSelection[0].parent.testcases) - 1] != self.currTestSelection[0]
    
class RenameTest(InteractiveAction):
    def __init__(self):
        InteractiveAction.__init__(self)
        self.currTestSelection = []
        self.newName = ""
        self.oldName = ""
        self.newDescription = ""
        self.oldDescription = ""
    def hasBuiltInGUIDescription(self):
        return True
    def notifyNewTestSelection(self, tests, direct):
        self.currTestSelection = tests # interested in suites, unlike most SelectionActions
    def isActiveOnCurrent(self):
        return len(self.currTestSelection) == 1 and \
               self.currTestSelection[0].parent and \
               self.currTestSelection[0].classId() == "test-case"
    def getDialogType(self):
        if len(self.currTestSelection) == 1:
            self.newName = self.currTestSelection[0].name
            self.newDescription = self.currTestSelection[0].description
        else:
            self.newName = ""
            self.newDescription = ""
        self.oldName = self.newName
        self.oldDescription = self.newDescription
        return "guidialogs.RenameDialog"
    def getStockId(self):
        return "italic"
    def _getTitle(self):
        return "_Rename..."
    def _getScriptTitle(self):
        return "Rename selected test"
    def messageAfterPerform(self):
        message = "Renamed test " + self.oldName + " to " + self.newName
        if self.oldDescription != self.newDescription:
            message += " and changed description"
        return message
    def checkNewName(self):
        if self.newName == self.currTestSelection[0].name:
            return ("", False)
        if len(self.newName) == 0:
            return ("Please enter a new name.", True)
        if self.newName.find(" ") != -1:
            return ("The new name must not contain spaces, please choose another name.", True)
        for test in self.currTestSelection[0].parent.testCaseList():
            if test.name == self.newName:
                return ("The name '" + self.newName + "' is already taken, please choose another name.", True)
        newDir = os.path.join(self.currTestSelection[0].parent.getDirectory(), self.newName)
        if os.path.isdir(newDir):
            return ("The directory '" + newDir + "' already exists.\n\nDo you want to overwrite it?", False)
        return ("", False)
    def performOnCurrent(self):
        try:
            self.currTestSelection[0].rename(self.newName, self.newDescription)
        except IOError, e:
            raise plugins.TextTestError, "Failed to rename test:\n" + str(e)
        except OSError, e:
            raise plugins.TextTestError, "Failed to rename test:\n" + str(e)
   
# Placeholder for all classes. Remember to add them!
class InteractiveActionHandler:
    def __init__(self):
        self.actionPreClasses = [ Quit, ViewFile ]
        self.actionDynamicClasses = [ SaveTests, SaveSelection, RecomputeTest ]
        self.actionStaticClasses = [ RecordTest, CopyTest, ImportTestCase, ImportTestSuite, \
                                     CreateDefinitionFile, ReportBugs, SelectTests, \
                                     RunTests, ResetGroups, RenameTest, RemoveTests, \
                                     SortTestsAscending, SortTestsDescending, \
                                     RepositionTestFirst, RepositionTestUp, \
                                     RepositionTestDown, RepositionTestLast, \
                                     ReconnectToTests, SaveSelection ]
        self.actionPostClasses = []
        self.loadModules = [] # derived configurations add to this on being imported...
        self.optionGroupMap = {}
        self.diag = plugins.getDiagnostics("Interactive Actions")
    def setCommandOptionGroups(self, optionGroups):
        if len(self.optionGroupMap) > 0:
            return

        self.optionGroupMap[RunTests] = optionGroups
        self.optionGroupMap[ReconnectToTests] = optionGroups
        for group in optionGroups:
            if group.name.startswith("Select"):
                self.optionGroupMap[SelectTests] = [ group ]
                self.optionGroupMap[SaveSelection] = [ group ]
    def getMode(self, dynamic):
        if dynamic:
            return "Dynamic"
        else:
            return "Static"
    def getListedInstances(self, list, *args):
        instances = []
        for intvActionClass in list:
            commandOptionGroups = self.optionGroupMap.get(intvActionClass)
            if commandOptionGroups:
                instance = self.makeInstance(intvActionClass, commandOptionGroups, *args)
            else:
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
        self.diag.info("Trying to create action for " + intvActionClass.__name__)
        for module in self.loadModules:
            command = "from " + module + " import " + intvActionClass.__name__ + " as realClassName"
            try:
                exec command
                self.diag.info("Used derived version from module " + module)
            except ImportError:
                continue
            
            actionObject = self.tryMakeObject(realClassName, *args)
            if actionObject:
                return actionObject
        
        self.diag.info("Used basic version")
        return self.tryMakeObject(intvActionClass, *args)
    def tryMakeObject(self, actionClass, *args):
        try:
            return actionClass(*args)
        except:
            # If some invalid interactive action is provided, need to know which
            print "Error with interactive action", actionClass.__name__, "ignoring..."
            plugins.printException()

        
interactiveActionHandler = InteractiveActionHandler()
guilog, guiConfig = None, None

def setUpGlobals(dynamic):
    global guilog, guiConfig
    guiConfig = GUIConfig(dynamic)
    if dynamic:
        guilog = plugins.getDiagnostics("dynamic GUI behaviour")
    else:
        guilog = plugins.getDiagnostics("static GUI behaviour")
