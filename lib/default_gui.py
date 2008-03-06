
import plugins, os, sys, shutil, time, subprocess, operator, types
from guiplugins import SelectionAction, InteractiveAction, InteractiveTestAction, guilog, guiConfig, scriptEngine
from jobprocess import JobProcess
from sets import Set
from copy import copy, deepcopy
from threading import Thread
from glob import glob
from stat import *
from ndict import seqdict
from log4py import LOGLEVEL_NORMAL
   
    
class Quit(InteractiveAction):
    def getStockId(self):
        return "quit"
    def _getTitle(self):
        return "_Quit"
    def notifyNewTestSelection(self, *args):
        pass # we don't care and don't want to screw things up...
    def performOnCurrent(self):
        self.notify("Quit")
    def messageAfterPerform(self):
        pass # GUI isn't there to show it
    def getConfirmationMessage(self):
        runningProcesses = self.listRunningProcesses()
        if len(runningProcesses) == 0:
            return ""
        else:
            return "\nThese processes are still running, and will be terminated when quitting: \n\n   + " + \
                   "\n   + ".join(runningProcesses) + "\n\nQuit anyway?\n"

        
# Plugin for saving tests (standard)
class SaveTests(SelectionAction):
    def __init__(self, allApps, *args):
        SelectionAction.__init__(self, allApps, *args)
        self.addOption("v", "Version to save")
        self.addSwitch("over", "Replace successfully compared files also", 0)
        if self.hasPerformance(allApps):
            self.addSwitch("ex", "Save: ", 1, ["Average performance", "Exact performance"])
    def getStockId(self):
        return "save"
    def getTabTitle(self):
        return "Saving"
    def _getTitle(self):
        return "_Save"
    def _getScriptTitle(self):
        return "Save results for selected tests"
    def messageAfterPerform(self):
        pass # do it in the method
    def getConfirmationMessage(self):
        testsForWarn = filter(lambda test: test.state.warnOnSave(), self.currTestSelection)
        if len(testsForWarn) == 0:
            return ""
        message = "You have selected tests whose results are partial or which are registered as bugs:\n"
        for test in testsForWarn:
            message += "  Test '" + test.uniqueName + "' " + test.state.categoryRepr() + "\n"
        message += "Are you sure you want to do this?\n"
        return message
    
    def getSaveableTests(self):
        return filter(lambda test: test.state.isSaveable(), self.currTestSelection)       
    def updateOptions(self):
        defaultSaveOption = self.getDefaultSaveOption()
        currOption = self.optionGroup.getOption("v").defaultValue
        if defaultSaveOption == currOption:
            return False
        self.optionGroup.setOptionValue("v", defaultSaveOption)
        self.diag.info("Setting default save version to " + defaultSaveOption)
        self.optionGroup.setPossibleValues("v", self.getPossibleVersions())
        return True
    def getDefaultSaveOption(self):
        saveVersions = self.getSaveVersions()
        if saveVersions.find(",") != -1:
            return "<default> - " + saveVersions
        else:
            return saveVersions
    def getPossibleVersions(self):
        extensions = []
        for app in self.currAppSelection:
            for ext in app.getSaveableVersions():
                if not ext in extensions:
                    extensions.append(ext)
        # Include the default version always
        extensions.append("")
        return extensions
    def getSaveVersions(self):
        saveVersions = []
        for app in self.currAppSelection:
            ver = self.getDefaultSaveVersion(app)
            if not ver in saveVersions:
                saveVersions.append(ver)
        return ",".join(saveVersions)
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
        if test.state.isAllNew():
            return ""
        versionString = self.optionGroup.getOptionValue("v")
        if versionString.startswith("<default>"):
            return self.getDefaultSaveVersion(test.app)
        else:
            return versionString
    def notifyNewFileSelection(self, files):
        self.updateFileSelection(files)
    def newFilesAsDiags(self):
        return int(self.optionGroup.getSwitchValue("newdiag", 0))
    def isActiveOnCurrent(self, test=None, state=None):
        if state and state.isSaveable():
            return True
        for seltest in self.currTestSelection:
            if seltest is not test and seltest.state.isSaveable():
                return True
        return False
    def performOnCurrent(self):
        saveDesc = ", exactness " + str(self.getExactness())
        stemsToSave = [ os.path.basename(fileName).split(".")[0] for fileName, comparison in self.currFileSelection ]
        if len(stemsToSave) > 0:
            saveDesc += ", only " + ",".join(stemsToSave)
        overwriteSuccess = self.optionGroup.getSwitchValue("over")
        if overwriteSuccess:
            saveDesc += ", overwriting both failed and succeeded files"

        tests = self.getSaveableTests()
        testDesc = str(len(tests)) + " tests"
        self.notify("Status", "Saving " + testDesc + " ...")
        try:
            for test in tests:
                version = self.getVersion(test)
                fullDesc = " - version " + version + saveDesc
                self.describe(test, fullDesc)
                testComparison = test.state
                testComparison.setObservers(self.observers)
                testComparison.save(test, self.getExactness(), version, overwriteSuccess, self.newFilesAsDiags(), stemsToSave)
                newState = testComparison.makeNewState(test.app, "saved")
                test.changeState(newState)

            self.notify("Status", "Saved " + testDesc + ".")
        except OSError, e:
            self.notify("Status", "Failed to save " + testDesc + ".")
            errorStr = str(e)
            if errorStr.find("Permission") != -1:
                raise plugins.TextTestError, "Failed to save " + testDesc + \
                      " : didn't have sufficient write permission to the test files"
            else:
                raise plugins.TextTestError, errorStr
        
class MarkTest(SelectionAction):
    def __init__(self, *args):
        SelectionAction.__init__(self, *args)
        self.newBriefText = ""
        self.newFreeText = ""
    def _getTitle(self):
        return "_Mark"
    def _getScriptTitle(self):
        return "Mark the selected tests"
    def getDialogType(self):
        return "guidialogs.MarkTestDialog" # Since guiplugins cannot depend on gtk, we cannot call dialog ourselves ...
    def performOnCurrent(self):
        for test in self.currTestSelection:
            oldState = test.state
            if oldState.isComplete():
                if test.state.isMarked():
                    oldState = test.state.oldState # Keep the old state so as not to build hierarchies ...
                newState = plugins.MarkedTestState(self.newFreeText, self.newBriefText, oldState)
                test.changeState(newState)
                self.notify("ActionProgress", "") # Just to update gui ...            
    def isActiveOnCurrent(self, test=None, state=None):
        if state and state.isComplete():
            return True
        for seltest in self.currTestSelection:
            if seltest is not test and seltest.state.isComplete():
                return True
        return False

class UnmarkTest(SelectionAction):
    def _getTitle(self):
        return "_Unmark"
    def _getScriptTitle(self):
        return "Unmark the selected tests"
    def performOnCurrent(self):
        for test in self.currTestSelection:
            if test.state.isMarked():
                test.state.oldState.lifecycleChange = "unmarked" # To avoid triggering completion ...
                test.changeState(test.state.oldState)
                self.notify("ActionProgress", "") # Just to update gui ...            
    def isActiveOnCurrent(self, *args):
        for test in self.currTestSelection:
            if test.state.isMarked():
                return True
        return False

class FileViewAction(InteractiveTestAction):
    def __init__(self, *args):
        InteractiveTestAction.__init__(self, *args)
        self.viewTools = {}
    def correctTestClass(self):
        return True # enable for both tests and suites
    def isActiveOnCurrent(self, *args):
        if not InteractiveTestAction.isActiveOnCurrent(self):
            return False
        for fileName, comparison in self.currFileSelection:
            if self.isActiveForFile(fileName, comparison):
                return True
        return False
    def isActiveForFile(self, fileName, comparison):
        if not self.viewTools.get(fileName):
            return False
        return self._isActiveForFile(fileName, comparison)
    def _isActiveForFile(self, fileName, comparison):
        return True
    def notifyNewFileSelection(self, files):
        for fileName, comparison in files:
            self.viewTools[fileName] = self.getViewTool(fileName)
        self.updateFileSelection(files)
    
    def useFiltered(self):
        return False
    def performOnCurrent(self):
        for fileName, comparison in self.currFileSelection:
            fileToView = self.getFileToView(fileName, comparison)
            if os.path.isfile(fileToView):
                if self.isActiveForFile(fileName, comparison):
                    viewTool = self.viewTools.get(fileName)
                    self.performOnFile(fileToView, comparison, viewTool)
            else:
                self.handleNoFile(fileToView)
    def getFileToView(self, fileName, comparison):
        if comparison:
            return comparison.existingFile(self.useFiltered())
        else:
            return fileName
    def noFileAdvice(self):
        if self.currentTest:
            return "\n" + self.currentTest.app.noFileAdvice()
        else:
            return ""
    
    def handleNoFile(self, fileName):
        self.notify("Error", "File '" + os.path.basename(fileName) + "' cannot be viewed"
                    " as it has been removed in the file system." + self.noFileAdvice())
         
    def getViewTool(self, fileName):
        viewProgram = self.getViewToolName(fileName)
        if plugins.canExecute(viewProgram):
            return viewProgram
    def getViewToolName(self, fileName):
        stem = os.path.basename(fileName).split(".")[0]
        if self.currentTest:
            return self.currentTest.getCompositeConfigValue(self.getToolConfigEntry(), stem)
        else:
            return guiConfig.getCompositeValue(self.getToolConfigEntry(), stem)
    def differencesActive(self, comparison):
        if not comparison or comparison.newResult() or comparison.missingResult(): 
            return False
        return comparison.hasDifferences()
    def messageAfterPerform(self):
        pass # provided by starting viewer, with message
        

class ViewInEditor(FileViewAction):
    def __init__(self, allApps, dynamic):
        FileViewAction.__init__(self, allApps)
        self.dynamic = dynamic
    def _getTitle(self):
        return "View File"
    def getToolConfigEntry(self):
        return "view_program"
    def viewFile(self, fileName, viewTool, exitHandler, exitHandlerArgs):
        cmdArgs, descriptor, env = self.getViewCommand(fileName, viewTool)
        description = descriptor + " " + os.path.basename(fileName)
        refresh = bool(exitHandler)
        guilog.info("Viewing file " + fileName + " using '" + descriptor + "', refresh set to " + str(refresh))
        process = self.startViewer(cmdArgs, description=description, env=env,
                                   exitHandler=exitHandler, exitHandlerArgs=exitHandlerArgs)
        scriptEngine.monitorProcess("views and edits test files", process, [ fileName ])
    def getViewerEnvironment(self, cmdArgs):
        # An absolute path to the viewer may indicate a custom tool, send the test environment along too
        # Doing this is unlikely to cause harm in any case
        if self.currentTest and os.path.isabs(cmdArgs[0]):
            return self.currentTest.getRunEnvironment()
    def getViewCommand(self, fileName, viewProgram):
        # viewProgram might have arguments baked into it...
        cmdArgs = plugins.splitcmd(viewProgram) + [ fileName ]
        program = cmdArgs[0]
        descriptor = " ".join([ os.path.basename(program) ] + cmdArgs[1:-1])
        env = self.getViewerEnvironment(cmdArgs)
        interpreter = plugins.getInterpreter(program)
        if interpreter:
            cmdArgs = [ interpreter ] + cmdArgs
        return cmdArgs, descriptor, env
    
    def findExitHandlerInfo(self, fileName):
        if self.dynamic:
            return None, ()

        # options file can change appearance of test (environment refs etc.)
        if self.isTestDefinition("options", fileName):
            return self.currentTest.filesChanged, ()
        elif self.isTestDefinition("testsuite", fileName):
            # refresh order of tests if this edited
            return self.currentTest.contentChanged, (fileName,)
        else:
            return None, ()
    def performOnFile(self, fileName, comparison, viewTool):
        exitHandler, exitHandlerArgs = self.findExitHandlerInfo(fileName)
        return self.viewFile(fileName, viewTool, exitHandler, exitHandlerArgs)
    def notifyViewFile(self, fileName, comparison):
        if not self.differencesActive(comparison):
            fileToView = self.getFileToView(fileName, comparison)
            if os.path.isfile(fileToView):
                viewProgram = self.getViewToolName(fileToView)
                if plugins.canExecute(viewProgram):
                    self.performOnFile(fileToView, comparison, viewProgram)
                elif viewProgram:
                    self.notify("Error", "Cannot find file viewing program '" + viewProgram + \
                                "'.\nPlease install it somewhere on your PATH or\nchange the configuration entry 'view_program'.")
                else:
                    self.notify("Warning", "No file viewing program is defined for files of type '" + \
                                os.path.basename(fileToView).split(".")[0] + \
                                "'.\nPlease point the configuration entry 'view_program' at a valid program to view the file.")
            else:
                self.handleNoFile(fileToView)
            
    def isTestDefinition(self, stem, fileName):
        if not self.currentTest:
            return False
        defFile = self.currentTest.getFileName(stem)
        if defFile:
            return plugins.samefile(fileName, defFile)
        else:
            return False

class ViewFilteredInEditor(ViewInEditor):
    def useFiltered(self):
        return True
    def _getTitle(self):
        return "View Filtered File"
    def _isActiveForFile(self, fileName, comparison):
        return bool(comparison)
    def notifyViewFile(self, *args):
        pass
        
class ViewFileDifferences(FileViewAction):
    def _getTitle(self):
        return "View Raw Differences"
    def getToolConfigEntry(self):
        return "diff_program"
    def _isActiveForFile(self, fileName, comparison):
        if bool(comparison):
            if not (comparison.newResult() or comparison.missingResult()):
                return True
        return False
    def performOnFile(self, tmpFile, comparison, diffProgram):
        stdFile = comparison.getStdFile(self.useFiltered())
        description = diffProgram + " " + os.path.basename(stdFile) + " " + os.path.basename(tmpFile)
        guilog.info("Starting graphical difference comparison using '" + diffProgram + "':")
        guilog.info("-- original file : " + stdFile)
        guilog.info("--  current file : " + tmpFile)
        cmdArgs = plugins.splitcmd(diffProgram) + [ stdFile, tmpFile ]
        process = self.startViewer(cmdArgs, description=description)
        scriptEngine.monitorProcess("shows graphical differences in test files", process)
    
class ViewFilteredFileDifferences(ViewFileDifferences):
    def _getTitle(self):
        return "View Differences"
    def useFiltered(self):
        return True
    def _isActiveForFile(self, fileName, comparison):
        return self.differencesActive(comparison)
    def notifyViewFile(self, fileName, comparison):
        if self.differencesActive(comparison):
            tmpFile = self.getFileToView(fileName, comparison)
            if os.path.isfile(tmpFile):
                diffProgram = self.getViewToolName(tmpFile)
                if plugins.canExecute(diffProgram):
                    self.performOnFile(tmpFile, comparison, diffProgram)
                elif diffProgram:
                    self.notify("Error", "Cannot find graphical difference program '" + diffProgram + \
                                "'.\nPlease install it somewhere on your PATH or change the\nconfiguration entry 'diff_program'.")
                else:
                    self.notify("Warning", "No graphical difference program is defined for files of type '" + \
                                os.path.basename(tmpFile).split(".")[0] + \
                                "'.\nPlease point the configuration entry 'diff_program' at a valid program to visualize the differences.")
            else:
                self.handleNoFile(tmpFile)

class FollowFile(FileViewAction):
    def _getTitle(self):
        return "Follow File Progress"
    def getToolConfigEntry(self):
        return "follow_program"
    def _isActiveForFile(self, fileName, comparison):
        return self.currentTest.state.hasStarted() and not self.currentTest.state.isComplete()
    def fileToFollow(self, fileName, comparison):
        if comparison:
            return comparison.tmpFile
        else:
            return fileName
    def getFollowCommand(self, followProgram, fileName):
        basic = plugins.splitcmd(followProgram) + [ fileName ]
        if followProgram.startswith("tail") and os.name == "posix":
            title = self.currentTest.name + " (" + os.path.basename(fileName) + ")"
            return [ "xterm", "-bg", "white", "-T", title, "-e" ] + basic
        else:
            return basic
    def performOnFile(self, fileName, comparison, followProgram):
        useFile = self.fileToFollow(fileName, comparison)
        guilog.info("Following file " + useFile + " using '" + followProgram + "'")
        description = followProgram + " " + os.path.basename(useFile)
        process = self.startViewer(self.getFollowCommand(followProgram, useFile), description=description)
        scriptEngine.monitorProcess("follows progress of test files", process)    

class KillTests(SelectionAction):
    def getStockId(self):
        return "stop"
    def _getTitle(self):
        return "_Kill"
    def __repr__(self):
        return "Killing"
    def _getScriptTitle(self):
        return "Kill selected tests"
    def isActiveOnCurrent(self, test=None, state=None):
        for seltest in self.currTestSelection:
            if seltest is test:
                if not state.isComplete():
                    return True
            else:
                if not seltest.state.isComplete():
                    return True
        return False
    def performOnCurrent(self):
        tests = filter(lambda test: not test.state.isComplete(), self.currTestSelection)
        tests.reverse() # best to cut across the action thread rather than follow it and disturb it excessively
        testDesc = str(len(tests)) + " tests"
        self.notify("Status", "Killing " + testDesc + " ...")
        for test in tests:
            self.notify("ActionProgress", "")
            self.describe(test)
            test.notify("Kill")

        self.notify("Status", "Killed " + testDesc + ".")
    
class CopyTests(SelectionAction):
    def getStockId(self):
        return "copy"
    def _getTitle(self):
        return "_Copy"
    def _getScriptTitle(self):
        return "Copy selected tests"
    def performOnCurrent(self):
        self.notify("Clipboard", self.currTestSelection, cut=False)

class CutTests(SelectionAction):
    def getStockId(self):
        return "cut"
    def _getTitle(self):
        return "_Cut"
    def _getScriptTitle(self):
        return "Cut selected tests"
    def performOnCurrent(self):
        self.notify("Clipboard", self.currTestSelection, cut=True)

class PasteTests(InteractiveTestAction):
    def __init__(self, *args):
        InteractiveTestAction.__init__(self, *args)
        self.clipboardTests = []
        self.allSelected = []
        self.removeAfter = False
    def updateSelection(self, tests, rowCount):
        self.allSelected = tests
        InteractiveTestAction.updateSelection(self, tests, rowCount)
    def getStockId(self):
        return "paste"
    def _getTitle(self):
        return "_Paste"
    def _getScriptTitle(self):
        return "Paste tests from clipboard"
    def notifyClipboard(self, tests, cut=False):
        self.clipboardTests = tests
        self.removeAfter = cut
        self.notify("Sensitivity", True)
    def correctTestClass(self):
        return True # Can paste after suites also
    def isActiveOnCurrent(self, test=None, state=None):
        return InteractiveTestAction.isActiveOnCurrent(self, test, state) and len(self.clipboardTests) > 0
    def getCurrentTestMatchingApp(self, test):
        for currTest in self.allSelected:
            if currTest.app == test.app:
                return currTest
            
    def getDestinationInfo(self, test):
        currTest = self.getCurrentTestMatchingApp(test)
        if currTest is None:
            return None, 0
        if currTest.classId() == "test-suite":
            return currTest, 0
        else:
            return currTest.parent, currTest.positionInParent() + 1

    def getNewTestName(self, suite, oldName):
        existingTest = suite.findSubtest(oldName)
        if not existingTest or self.willBeRemoved(existingTest):
            return oldName

        nextNameCandidate = self.findNextNameCandidate(oldName)
        return self.getNewTestName(suite, nextNameCandidate)
    def willBeRemoved(self, test):
        return self.removeAfter and test in self.clipboardTests
    def findNextNameCandidate(self, name):
        copyPos = name.find("_copy_")
        if copyPos != -1:
            copyEndPos = copyPos + 6
            number = int(name[copyEndPos:])
            return name[:copyEndPos] + str(number + 1)
        elif name.endswith("copy"):
            return name + "_2"
        else:
            return name + "_copy"
    def getNewDescription(self, test):
        if len(test.description) or self.removeAfter:
            return test.description
        else:
            return "Copy of " + test.name
    def getRepositionPlacement(self, test, placement):
        currPos = test.positionInParent()
        if placement > currPos:
            return placement - 1
        else:
            return placement
    def performOnCurrent(self):
        newTests = []
        destInfo = seqdict()
        for test in self.clipboardTests:
            suite, placement = self.getDestinationInfo(test)
            if suite:
                destInfo[test] = suite, placement
        if len(destInfo) == 0:
            raise plugins.TextTestError, "Cannot paste test there, as the copied test and currently selected test have no application/version in common"

        suiteDeltas = {} # When we insert as we go along, need to update subsequent placements
        for test in self.clipboardTests:
            if not destInfo.has_key(test):
                continue
            suite, placement = destInfo[test]
            realPlacement = placement + suiteDeltas.get(suite, 0)
            newName = self.getNewTestName(suite, test.name)
            guilog.info("Pasting test " + newName + " under test suite " + \
                        repr(suite) + ", in position " + str(realPlacement))
            if self.removeAfter and newName == test.name and suite is test.parent:
                # Cut + paste to the same suite is basically a reposition, do it as one action
                test.parent.repositionTest(test, self.getRepositionPlacement(test, realPlacement))
                newTests.append(test)
            else:
                newDesc = self.getNewDescription(test)
                testDir = suite.writeNewTest(newName, newDesc, realPlacement)
                testImported = self.createTestContents(test, suite, testDir, newDesc, realPlacement)
                if suiteDeltas.has_key(suite):
                    suiteDeltas[suite] += 1
                else:
                    suiteDeltas[suite] = 1
                newTests.append(testImported)
                if self.removeAfter:
                    test.remove()

        guilog.info("Selecting new tests : " + repr(newTests))
        self.notify("SetTestSelection", newTests)
        if self.removeAfter:
            # After a paste from cut, subsequent pastes should behave like copies of the new tests
            self.clipboardTests = newTests
            self.removeAfter = False
        for suite, placement in destInfo.values():
            suite.contentChanged()
    def createTestContents(self, testToCopy, suite, testDir, description, placement):
        stdFiles, defFiles = testToCopy.listStandardFiles(allVersions=True)
        for sourceFile in stdFiles + defFiles:
            dirname, local = os.path.split(sourceFile)
            if dirname == testToCopy.getDirectory():
                targetFile = os.path.join(testDir, local)
                shutil.copy2(sourceFile, targetFile)
        dataFiles = testToCopy.listDataFiles()
        for sourcePath in dataFiles:
            if os.path.isdir(sourcePath):
                continue
            targetPath = sourcePath.replace(testToCopy.getDirectory(), testDir)
            plugins.ensureDirExistsForFile(targetPath)
            shutil.copy2(sourcePath, targetPath)
        return suite.addTestCase(os.path.basename(testDir), description, placement)
        
# And a generic import test. Note acts on test suites
class ImportTest(InteractiveTestAction):
    def __init__(self, *args):
        InteractiveTestAction.__init__(self, *args)
        self.optionGroup.addOption("name", self.getNameTitle())
        self.optionGroup.addOption("desc", self.getDescTitle(), description="Enter a description of the new " + self.testType().lower() + " which will be inserted as a comment in the testsuite file.")
        self.optionGroup.addOption("testpos", self.getPlaceTitle(), "last in suite", allocateNofValues=2, description="Where in the test suite should the test be placed?")
        self.testImported = None
    def getConfirmationMessage(self):
        testName = self.getNewTestName()
        suite = self.getDestinationSuite()
        self.checkName(suite, testName)
        newDir = os.path.join(suite.getDirectory(), testName)
        if os.path.isdir(newDir):
            if self.testFilesExist(newDir, suite.app):
                raise plugins.TextTestError, "Test already exists for application " + suite.app.fullName + \
                          " : " + os.path.basename(newDir)
            else:
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
    def updateOptions(self):
        self.optionGroup.setOptionValue("name", self.getDefaultName())
        self.optionGroup.setOptionValue("desc", self.getDefaultDesc())
        self.setPlacements(self.currentTest)
        return True
    def setPlacements(self, suite):
        # Add suite and its children
        placements = [ "first in suite" ]
        for test in suite.testcases:
            placements += [ "after " + test.name ]
        placements.append("last in suite")

        self.optionGroup.setPossibleValues("testpos", placements)
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
        suite.contentChanged()
        guilog.info("Selecting new test " + self.testImported.name)
        self.notify("SetTestSelection", [ self.testImported ])       
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
    def __init__(self, *args):
        InteractiveTestAction.__init__(self, *args)
        self.recordTime = None
        self.currentApp = None
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
    def isActiveOnCurrent(self, *args):
        return InteractiveTestAction.isActiveOnCurrent(self, *args) and self.getRecordMode() != "disabled" and \
               self.currentTest.getConfigValue("use_case_recorder") != "none"
    def updateOptions(self):
        if self.currentApp is not self.currentTest.app:
            self.currentApp = self.currentTest.app
            self.optionGroup.setOptionValue("v", self.currentTest.app.getFullVersion(forSave=1))
            self.optionGroup.setOptionValue("c", self.currentTest.app.checkout)
            return True
        else:
            return False
    def getUseCaseFile(self, test):
        return test.getFileName("usecase", self.optionGroup.getOptionValue("v"))
    def updateRecordTime(self, test):
        file = self.getUseCaseFile(test)
        if file:
            self._updateRecordTime(file)
    def _updateRecordTime(self, file):
        newTime = plugins.modifiedTime(file)
        if newTime != self.recordTime:
            self.recordTime = newTime
            outerRecord = os.getenv("USECASE_RECORD_SCRIPT")
            if outerRecord:
                # If we have an "outer" record going on, provide the result as a target recording...
                target = plugins.addLocalPrefix(outerRecord, "target_record")
                shutil.copyfile(file, target)
            return True
        else:
            return False
    def getChangedUseCaseVersion(self, test):
        file = self.getUseCaseFile(test)
        if not file or not self._updateRecordTime(file):
            return

        parts = os.path.basename(file).split(".")
        return ".".join(parts[2:])
    def startTextTestProcess(self, test, usecase, overwriteVersion=""):
        ttOptions = self.getRunOptions(test, usecase, overwriteVersion)
        guilog.info("Starting " + usecase + " run of TextTest with arguments " + repr(ttOptions))
        cmdArgs = self.getTextTestArgs() + ttOptions
        writeDir = self.getWriteDir(test)
        plugins.ensureDirectoryExists(writeDir)
        logFile = self.getLogFile(writeDir, usecase, "output")
        errFile = self.getLogFile(writeDir, usecase)
        self.startExtProgramNewUsecase(cmdArgs, usecase, logFile, errFile, \
                                       exitHandler=self.textTestCompleted, exitHandlerArgs=(test,usecase))
    def getLogFile(self, writeDir, usecase, type="errors"):
        return os.path.join(writeDir, usecase + "_" + type + ".log")
    def textTestCompleted(self, test, usecase):
        # Refresh the files before changed the data
        test.refreshFiles()
        if usecase == "record":
            self.setTestRecorded(test, usecase)
        else:
            self.setTestReady(test, usecase)
        test.filesChanged()
        test.notify("CloseDynamic", usecase)
    def getWriteDir(self, test):
        return os.path.join(test.app.writeDirectory, "record")
    def setTestRecorded(self, test, usecase):
        writeDir = self.getWriteDir(test)
        errFile = self.getLogFile(writeDir, usecase)
        if os.path.isfile(errFile):
            errText = open(errFile).read()
            if len(errText):
                self.notify("Status", "Recording failed for " + repr(test))
                return self.notify("Error", "Recording use-case failed, with the following errors:\n" + errText)

        changedUseCaseVersion = self.getChangedUseCaseVersion(test)
        if changedUseCaseVersion is not None and self.optionGroup.getSwitchValue("rep"):
            self.startTextTestProcess(test, "replay", changedUseCaseVersion)
            message = "Recording completed for " + repr(test) + \
                      ". Auto-replay of test now started. Don't submit the test manually!"
            self.notify("Status", message)
        else:
            self.notify("Status", "Recording completed for " + repr(test) + ", not auto-replaying")
    def setTestReady(self, test, usecase=""):
        self.notify("Status", "Recording and auto-replay completed for " + repr(test))
    def getRunOptions(self, test, usecase, overwriteVersion):
        version = self.optionGroup.getOptionValue("v")
        checkout = self.optionGroup.getOptionValue("c")
        basicOptions = self.getRunModeOptions(usecase, overwriteVersion) + [ "-tp", test.getRelPath() ] + \
                       test.app.getRunOptions(version, checkout)
        if usecase == "record":
            basicOptions.append("-record")
        return basicOptions
    def getRunModeOptions(self, usecase, overwriteVersion):
        if usecase == "record" or self.optionGroup.getSwitchValue("repgui"):
            return [ "-g" ]
        else:
            return [ "-o", overwriteVersion ]
    def _getTitle(self):
        return "Record _Use-Case"
    
class ImportTestCase(ImportTest):
    def __init__(self, *args):
        ImportTest.__init__(self, *args)
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
    def __init__(self, *args):
        ImportTest.__init__(self, *args)
        self.addEnvironmentFileOptions()
    def testType(self):
        return "Suite"
    def createTestContents(self, suite, testDir, description, placement):
        return suite.addTestSuite(os.path.basename(testDir), description, placement, self.writeEnvironmentFiles)
    def addEnvironmentFileOptions(self):
        self.addSwitch("env", "Add environment file")
    def writeEnvironmentFiles(self, newSuite):
        if self.optionGroup.getSwitchValue("env"):
            envFile = os.path.join(newSuite.getDirectory(), "environment")
            file = open(envFile, "w")
            file.write("# Dictionary of environment to variables to set in test suite\n")

class SelectTests(SelectionAction):
    def __init__(self, allApps, *args):
        SelectionAction.__init__(self, allApps)
        self.diag = plugins.getDiagnostics("Select Tests")
        self.rootTestSuites = []
        self.addOption("vs", "Tests for version", description="Select tests for a specific version.",
                       possibleValues=self.getPossibleVersions(allApps))
        self.addSwitch("select_in_collapsed_suites", "Select in collapsed suites", 0, description="Select in currently collapsed suites as well?")
        self.addSwitch("current_selection", "Current selection:", options = [ "Discard", "Refine", "Extend", "Exclude"], description="How should we treat the currently selected tests?\n - Discard: Unselect all currently selected tests before applying the new selection criteria.\n - Refine: Apply the new selection criteria only to the currently selected tests, to obtain a subselection.\n - Extend: Keep the currently selected tests even if they do not match the new criteria, and extend the selection with all other tests which meet the new criteria.\n - Exclude: After applying the new selection criteria to all tests, unselect the currently selected tests, to exclude them from the new selection.")
        self.appKeys = Set()
        for app in allApps:
            appSelectGroup = self.findSelectGroup(app)
            self.appKeys.update(Set(appSelectGroup.keys()))
            self.optionGroup.mergeIn(appSelectGroup)
    def findSelectGroup(self, app):
        for group in app.optionGroups:
            if group.name.startswith("Select"):
                return group
    def addSuites(self, suites):
        self.rootTestSuites = suites
    def getPossibleVersions(self, allApps):
        possVersions = []
        for app in allApps:
            for possVersion in self._getPossibleVersions(app):
                if possVersion not in possVersions:
                    possVersions.append(possVersion)
        return possVersions
    def _getPossibleVersions(self, app):
        fullVersion = app.getFullVersion()
        extraVersions = app.getExtraVersions()
        if len(fullVersion) == 0:
            return [ "<default>" ] + extraVersions
        else:
            return [ fullVersion ] + [ fullVersion + "." + extra for extra in extraVersions ]
    def isActiveOnCurrent(self, *args):
        return True
    def getStockId(self):
        return "refresh"
        #return "find"
    def _getTitle(self):
        return "_Select"
    def _getScriptTitle(self):
        return "Select indicated tests"
    def getGroupTabTitle(self):
        return "Selection"
    def messageBeforePerform(self):
        return "Selecting tests ..."
    def messageAfterPerform(self):
        return "Selected " + self.describeTests() + "."    
    # No messageAfterPerform necessary - we update the status bar when the selection changes inside TextTestGUI
    def getFilterList(self, app):
        return app.getFilterList(self.optionGroup.getOptionValueMap())
    def makeNewSelection(self):
        # Get strategy. 0 = discard, 1 = refine, 2 = extend, 3 = exclude
        strategy = self.optionGroup.getSwitchValue("current_selection")
        selectedTests = []
        suitesToTry = self.getSuitesToTry()
        for suite in self.rootTestSuites:
            if suite in suitesToTry:
                filters = self.getFilterList(suite.app)            
                reqTests = self.getRequestedTests(suite, filters)
                newTests = self.combineWithPrevious(reqTests, suite.app, strategy)
            else:
                newTests = self.combineWithPrevious([], suite.app, strategy)
                
            guilog.info("Selected " + str(len(newTests)) + " out of a possible " + str(suite.size()))
            selectedTests += newTests
        return selectedTests

    def performOnCurrent(self):
        newSelection = self.makeNewSelection()
        criteria = " ".join(self.optionGroup.getCommandLines(onlyKeys=self.appKeys))
        self.notify("SetTestSelection", newSelection, criteria, self.optionGroup.getSwitchValue("select_in_collapsed_suites"))
        
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
    def combineWithPrevious(self, reqTests, app, strategy):
        # Strategies: 0 - discard, 1 - refine, 2 - extend, 3 - exclude
        # If we want to extend selection, we include test if it was previsouly selected,
        # even if it doesn't fit the current criterion
        if strategy == 0:
            return reqTests
        elif strategy == 1:
            return filter(self.isSelected, reqTests)
        else:
            extraRequested = filter(self.isNotSelected, reqTests)
            if strategy == 2:
                selectedThisApp = filter(lambda test: test.app is app, self.currTestSelection)
                return extraRequested + selectedThisApp
            elif strategy == 3:
                return extraRequested 
    def findTestCaseList(self, suite):
        version = self.optionGroup.getOptionValue("vs")
        if len(version) == 0:
            return suite.testcases

        if version == "<default>":
            version = ""

        fullVersion = suite.app.getFullVersion()
        versionToUse = self.findCombinedVersion(version, fullVersion)       
        self.diag.info("Trying to get test cases for " + repr(suite) + ", version " + versionToUse)
        return suite.findTestCases(versionToUse)

    def findCombinedVersion(self, version, fullVersion):
        combined = version
        if len(fullVersion) > 0 and len(version) > 0:
            parts = version.split(".")
            for appVer in fullVersion.split("."):
                if not appVer in parts:
                    combined += "." + appVer
        return combined

class ResetGroups(InteractiveAction):
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
    def notifyNewTestSelection(self, *args):
        pass # we don't care and don't want to screw things up...
    
class SaveSelection(SelectionAction):
    def __init__(self, allApps, *args):
        SelectionAction.__init__(self, allApps, *args)
        self.selectionCriteria = ""
        self.fileName = ""
        self.saveTestList = ""
        self.rootTestSuites = []
    def addSuites(self, suites):
        self.rootTestSuites = suites
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
    def getDirectories(self):
        apps = guiConfig.apps
        dirs = apps[0].getFilterFileDirectories(apps)
        if len(dirs) > 0:
            self.folders = (dirs, dirs[0][1])
        else:
            self.folders = (dirs, None)
        return self.folders
    def saveActualTests(self):
        return guiConfig.dynamic or self.saveTestList
    def getTestPathFilterArg(self):
        selTestPaths = []
        for suite in self.rootTestSuites:
            selTestPaths.append("appdata=" + suite.app.name + suite.app.versionSuffix())
            for test in suite.testCaseList():
                if self.isSelected(test):
                    selTestPaths.append(test.getRelPath())
        return "-tp " + "\n".join(selTestPaths)
    def notifySetTestSelection(self, tests, criteria="", *args):
        self.selectionCriteria = criteria
    def getTextToSave(self):
        actualTests = self.saveActualTests()
        if actualTests:
            return self.getTestPathFilterArg()
        else:
            return self.selectionCriteria
    def notifySaveSelection(self, fileName):
        self.fileName = fileName
        self.saveTestList = True
        self.performOnCurrent()
    def performOnCurrent(self):
        toWrite = self.getTextToSave()
        try:
            file = open(self.fileName, "w")
            file.write(toWrite + "\n")
            file.close()
        except IOError, e:
            self.notify("Error", "\nFailed to save selection:\n" + str(e) + "\n")
    def messageAfterPerform(self):
        return "Saved " + self.describeTests() + " in file '" + self.fileName + "'."

class LoadSelection(SelectTests):
    def __init__(self, *args):
        SelectTests.__init__(self, *args)
        self.fileName = ""
    def getStockId(self):
        return "open"
    def _getTitle(self):
        return "_Load Selection..."
    def _getScriptTitle(self):
        return "Load test selection from file"
    def getGroupTabTitle(self):
        return ""
    def createOptionGroupTab(self, optionGroup):
        return False
    def getDialogType(self):
        return "guidialogs.LoadSelectionDialog"
    def getDirectories(self):
        self.folders = self.optionGroup.getOption("f").getDirectories()
        return self.folders
    def getFilterList(self, app):
        return app.getFiltersFromFile(self.fileName)
    def performOnCurrent(self):
        if self.fileName:
            newSelection = self.makeNewSelection()
            self.notify("SetTestSelection", newSelection, "-f " + self.fileName, True)
    def messageBeforePerform(self):
        return "Loading test selection ..."
    def messageAfterPerform(self):
        if self.fileName:
            return "Loaded test selection from file '" + self.fileName + "'."
        else:
            return "No test selection loaded."

class RunningAction(SelectionAction):
    runNumber = 1
    def __init__(self, allApps, *args):
        SelectionAction.__init__(self, allApps)
        for app in allApps:
            for group in app.optionGroups:
                if group.name.startswith("Invisible"):
                    self.invisibleGroup = group
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
        cmdArgs = self.getTextTestArgs() + ttOptions
        identifierString = "started at " + plugins.localtime()
        self.startExtProgramNewUsecase(cmdArgs, usecase, logFile, errFile, exitHandler=self.checkTestRun, \
                                       exitHandlerArgs=(identifierString,errFile,self.currTestSelection), description = description)
    def writeFilterFile(self, writeDir):
        # Because the description of the selection can be extremely long, we write it in a file and refer to it
        # This avoids too-long command lines which are a problem at least on Windows XP
        filterFileName = os.path.join(writeDir, "gui_select")
        self.notify("SaveSelection", filterFileName)
        return filterFileName
    def getTextTestOptions(self, filterFile, app):
        ttOptions = self.getCmdlineOptionForApps()
        ttOptions += self.invisibleGroup.getCommandLines()
        for group in self.getOptionGroups():
            ttOptions += group.getCommandLines()
        ttOptions += [ "-count", str(self.getTestCount()) ]
        ttOptions += [ "-f", filterFile ]
        ttOptions += [ "-fd", self.getTmpFilterDir(app) ]
        return ttOptions
    def getTestCount(self):
        return len(self.currTestSelection) 
    def getTmpFilterDir(self, app):
        return os.path.join(app.writeDirectory, "temporary_filter_files")
    def getAppsSelectedNoExtras(self):
        apps = copy(self.currAppSelection)
        for app in self.currAppSelection:
            for extra in app.extras:
                if extra in apps:
                    apps.remove(extra)
        return apps
    def getCmdlineOptionForApps(self):
        appDescs = [ app.name + app.versionSuffix() for app in self.getAppsSelectedNoExtras() ]
        return [ "-a", ",".join(appDescs) ]
    def checkTestRun(self, identifierString, errFile, testSel):
        if len(self.currTestSelection) >= 1 and self.currTestSelection[0] in testSel:
            self.currTestSelection[0].filesChanged()
        testSel[0].notify("CloseDynamic", self.getUseCaseName())
        if os.path.isfile(errFile):
            errText = open(errFile).read()
            if len(errText):
                self.notify("Error", "Dynamic run failed, with the following errors:\n" + errText)
            

class ReconnectToTests(RunningAction):
    def __init__(self, *args):
        RunningAction.__init__(self, *args)
        self.addOption("v", "Version to reconnect to")
        self.addOption("reconnect", "Temporary result directory", os.getenv("TEXTTEST_TMP"), description="Specify a directory containing temporary texttest results. The reconnection will use a random subdirectory matching the version used.")
        self.addSwitch("reconnfull", "Results:", 0, ["Display as they were", "Recompute from files"])
    def getGroupTabTitle(self):
        return "Running"
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
    def __init__(self, allApps, *args):
        RunningAction.__init__(self, allApps)
        self.optionGroups = []
        for app in allApps:
            for group in app.optionGroups:
                if not group.name.startswith("Invisible") and not group.name.startswith("Select"):
                    self.insertGroup(group)
    def insertGroup(self, group):
        groupToUse = self.findPreviousGroup(group.name)
        if not groupToUse:
            groupToUse = plugins.OptionGroup(group.name)
            self.optionGroups.append(groupToUse)
        groupToUse.mergeIn(group)
    def findPreviousGroup(self, name):
        for group in self.optionGroups:
            if group.name == name:
                return group
    def getOptionGroups(self):
        return self.optionGroups
    def _getTitle(self):
        return "_Run"
    def getStockId(self):
        return "execute"
    def _getScriptTitle(self):
        return "Run selected tests"
    def getGroupTabTitle(self):
        return "Running"
    def getTestCount(self):
        return len(self.currTestSelection) * self.getCopyCount() * self.getVersionCount()
    def getCopyCount(self):
        return int(self.optionGroups[0].getOptionValue("cp"))
    def getVersionCount(self):
        return self.optionGroups[0].getOptionValue("v").count(",") + 1
    def performedDescription(self):
        timesToRun = self.getCopyCount()
        numberOfTests = len(self.currTestSelection)
        if timesToRun != 1:
            if numberOfTests > 1:
                return "Started " + str(timesToRun) + " copies each of"
            else:
                return "Started " + str(timesToRun) + " copies of"
        else:
            return "Started"
    def getUseCaseName(self):
        return "dynamic"
    def getInteractiveReplayDescription(self):
        app = self.currTestSelection[0].app
        for group in self.optionGroups:
            for switchName, desc in app.getInteractiveReplayOptions():
                if group.getSwitchValue(switchName, False):
                    return desc
    def getConfirmationMessage(self):
        if len(self.currTestSelection) > 1:
            interactiveDesc = self.getInteractiveReplayDescription()
            if interactiveDesc:
                return "You are trying to run " + str(len(self.currTestSelection)) + " tests with " + \
                       interactiveDesc + " replay enabled.\nThis will mean lots of target application GUIs " + \
                       "popping up and may be hard to follow.\nAre you sure you want to do this?"
        else:
            return ""

class CreateDefinitionFile(InteractiveTestAction):
    def __init__(self, *args):
        InteractiveTestAction.__init__(self, *args)
        self.addOption("type", "Type of definition file to create", allocateNofValues=2)
        self.addOption("v", "Version identifier to use") 
    def inMenuOrToolBar(self):
        return False
    def correctTestClass(self):
        return True
    def _getTitle(self):
        return "Create _File"
    def getStockId(self):
        return "new" 
    def getTabTitle(self):
        return "New File" 
    def getScriptTitle(self, tab):
        return "Create File"
    def getDefinitionFiles(self):
        defFiles = []
        defFiles.append("environment")
        if self.currentTest.classId() == "test-case":
            defFiles.append("options")
            recordMode = self.currentTest.getConfigValue("use_case_record_mode")
            if recordMode == "disabled":
                defFiles.append("input")
            else:
                defFiles.append("usecase")
        # these are created via the GUI, not manually via text editors (or are already handled above)
        dontAppend = [ "testsuite", "knownbugs", "traffic", "input", "usecase", "environment", "options" ]
        for defFile in self.currentTest.getConfigValue("definition_file_stems"):
            if not defFile in dontAppend:
                defFiles.append(defFile)
        return defFiles + self.currentTest.app.getDataFileNames()
    def updateOptions(self):
        defFiles = self.getDefinitionFiles()
        self.optionGroup.setValue("type", defFiles[0])
        self.optionGroup.setPossibleValues("type", defFiles)
        return True
    def getFileName(self, stem, version):
        fileName = stem
        if stem in self.currentTest.getConfigValue("definition_file_stems"):
            fileName += "." + self.currentTest.app.name
        if version:
            fileName += "." + version
        return fileName
    def getSourceFile(self, stem, version, targetFile):
        thisTestName = self.currentTest.getFileName(stem, version)
        if thisTestName and not os.path.basename(thisTestName) == targetFile:
            return thisTestName

        test = self.currentTest.parent
        while test:
            currName = test.getFileName(stem, version)
            if currName:
                return currName
            test = test.parent
    def performOnCurrent(self):
        stem = self.optionGroup.getOptionValue("type")
        version = self.optionGroup.getOptionValue("v")
        targetFileName = self.getFileName(stem, version)
        sourceFile = self.getSourceFile(stem, version, targetFileName)
        # If the source has an app identifier in it we need to get one, or we won't get prioritised!
        stemWithApp = stem + "." + self.currentTest.app.name
        if sourceFile and os.path.basename(sourceFile).startswith(stemWithApp) and not targetFileName.startswith(stemWithApp):
            targetFileName = targetFileName.replace(stem, stemWithApp, 1)
            sourceFile = self.getSourceFile(stem, version, targetFileName)
            
        targetFile = os.path.join(self.currentTest.getDirectory(), targetFileName)
        plugins.ensureDirExistsForFile(targetFile)
        fileExisted = os.path.exists(targetFile)
        if sourceFile and os.path.isfile(sourceFile):
            guilog.info("Creating new file, copying " + sourceFile)
            shutil.copyfile(sourceFile, targetFile)
        elif not fileExisted:
            file = open(targetFile, "w")
            file.close()
            guilog.info("Creating new empty file...")
        else:
            raise plugins.TextTestError, "Unable to create file, no possible source found and target file already exists:\n" + targetFile
        self.notify("NewFile", targetFile, fileExisted)
    def messageAfterPerform(self):
        pass

class RemoveTests(SelectionAction):
    def updateSelection(self, tests, rowCount):
        self.currTestSelection = tests # interested in suites, unlike most SelectionActions
    def notifyNewFileSelection(self, files):
        self.updateFileSelection(files)
    def isActiveOnCurrent(self, *args):
        for test in self.currTestSelection:
            if test.parent:
                return True
        # Only root selected. Any file?
        if len(self.currFileSelection) > 0:
            return True
        else:
            return False
    def _getTitle(self):
        return "Remove..."
    def getStockId(self):
        return "delete"
    def _getScriptTitle(self):
        return "Remove selected files"
    def getFilesDescription(self, number = None):
        numberOfFiles = len(self.currFileSelection)
        if number is not None:
            numberOfFiles = number
        if numberOfFiles == 1:
            return "1 file"
        else:
            return str(numberOfFiles) + " files"
    def getConfirmationMessage(self):
        extraLines = """
\nNote: This will remove files from the file system and hence may not be reversible.\n
Are you sure you wish to proceed?\n"""
        if len(self.currTestSelection) == 1:
            currTest = self.currTestSelection[0]
            if len(self.currFileSelection) > 0:
                return "\nYou are about to remove " + self.getFilesDescription() + \
                       " from the " + currTest.classDescription() + " '" + currTest.name + "'." + extraLines                
            if currTest.classId() == "test-case":
                return "\nYou are about to remove the test '" + currTest.name + \
                       "' and all associated files." + extraLines
            else:
                return "\nYou are about to remove the entire test suite '" + currTest.name + \
                       "' and all " + str(currTest.size()) + " tests that it contains." + extraLines
        else:
            return "\nYou are about to remove " + repr(len(self.currTestSelection)) + \
                   " tests with associated files." + extraLines
    def performOnCurrent(self):
        if len(self.currFileSelection) > 0:
            self.removeFiles()
        else:
            self.removeTests()
    def getTestsToRemove(self, list):
        toRemove = []
        warnings = ""
        for test in list:
            if not test.parent:
                warnings += "\nThe root suite\n'" + test.name + " (" + test.app.name + ")'\ncannot be removed.\n"
                continue
            if test.classId() == "test-suite":
                subTests, subWarnings = self.getTestsToRemove(test.testcases)
                warnings += subWarnings
                for subTest in subTests:
                    if not subTest in toRemove:
                        toRemove.append(subTest)
            if not test in toRemove:
                toRemove.append(test)

        return toRemove, warnings
    def removeTests(self):
        namesRemoved = []
        toRemove, warnings = self.getTestsToRemove(self.currTestSelection)
        for test in toRemove:
            if test.remove():
                namesRemoved.append(test.name)
        self.notify("Status", "Removed test(s) " + ",".join(namesRemoved))
        if warnings:
            self.notify("Warning", warnings)
    def removeFiles(self):
        test = self.currTestSelection[0]
        warnings = ""
        removed = 0
        for filePath, comparison in self.currFileSelection:
            try:
                self.notify("Status", "Removing file " + os.path.basename(filePath))
                self.notify("ActionProgress", "")
                os.remove(filePath)
                removed += 1
            except OSError, e:
                warnings += "Failed to remove file '" + filePath + "':\n" + str(e)
        test.filesChanged()
        self.notify("Status", "Removed " + self.getFilesDescription(removed) + " from the " +
                    test.classDescription() + " " + test.name + "")
        if warnings:
            self.notify("Warning", warnings)
    def messageAfterPerform(self):
        pass # do it as part of the method as currentTest will have changed by the end!
    
class ReportBugs(InteractiveTestAction):
    def __init__(self, *args):
        InteractiveTestAction.__init__(self, *args)
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
    def updateOptions(self):
        self.optionGroup.setOptionValue("search_file", self.currentTest.app.getConfigValue("log_file"))
        self.optionGroup.setPossibleValues("search_file", self.getPossibleFileStems())
        self.optionGroup.setOptionValue("version", self.currentTest.app.getFullVersion())
        return False
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
    def __init__(self, *args):
        InteractiveTestAction.__init__(self, *args)
        self.recomputing = False
        self.chainReaction = False
    def getState(self, state):
        if state:
            return state
        else:
            return self.currentTest.state
    def isActiveOnCurrent(self, test=None, state=None):
        if not InteractiveTestAction.isActiveOnCurrent(self):
            return False
        
        useState = self.getState(state)
        return useState.hasStarted() and not useState.isComplete()
    def updateSelection(self, tests, rowCount):
        InteractiveTestAction.updateSelection(self, tests, rowCount)
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
    def inMenuOrToolBar(self):
        return False
    def _getTitle(self):
        return "_Update Info"
    def _getScriptTitle(self):
        return "Update test progress information and compare test files so far"
    def messageBeforePerform(self):
        return "Recomputing status of " + repr(self.currentTest) + " ..."
    def messageAfterPerform(self):
        pass
    def performOnCurrent(self):
        test = self.currentTest # recomputing can change selection, make sure we talk about the right one...
        test.app.recomputeProgress(test, self.observers)
        self.notify("Status", "Done recomputing status of " + repr(test) + ".")

class RecomputeAllTests(SelectionAction):
    def __init__(self, allApps, *args):
        SelectionAction.__init__(self, allApps, *args)
        self.latestNumberOfRecomputations = 0
    def isActiveOnCurrent(self, test=None, state=None):
        for test in self.currTestSelection:
            if test.needsRecalculation():
                return True
        return False
    def _getTitle(self):
        return "Recompute Status"
    def messageAfterPerform(self):
        if self.latestNumberOfRecomputations == 0:            
            return "No test needed recomputation."
        elif self.latestNumberOfRecomputations == 1:
            return "Recomputed status of 1 test."
        else:
            return "Recomputed status of " + str(self.latestNumberOfRecomputations) + " tests."
    def _getScriptTitle(self):
        return "recompute status of all tests"
    def performOnCurrent(self):
        self.latestNumberOfRecomputations = 0
        for test in self.currTestSelection:
            if test.needsRecalculation():
                self.latestNumberOfRecomputations += 1
                self.notify("Status", "Recomputing status of " + repr(test) + " ...")
                self.notify("ActionProgress", "")                
                test.app.recomputeProgress(test, self.observers)
 

class SortTestSuiteFileAscending(InteractiveTestAction):
    def __init__(self, *args):
        InteractiveTestAction.__init__(self, *args)
        self.currSuites = []
    def updateSelection(self, tests, *args):
        InteractiveTestAction.updateSelection(self, tests, *args)
        self.currSuites = tests
    def correctTestClass(self):
        return self.currentTest.classId() == "test-suite"
    def isActiveOnCurrent(self, *args):
        return InteractiveTestAction.isActiveOnCurrent(self, *args) and not self.currentTest.autoSortOrder
    def getStockId(self):
        return "sort-ascending"
    def _getTitle(self):
        return "_Sort Test Suite File"
    def messageAfterPerform(self):
        return "Sorted testsuite file for " + repr(self.currentTest) + " in alphabetical order."
    def _getScriptTitle(self):
        return "sort testsuite file for the selected test suite in alphabetical order"
    def performOnCurrent(self):
        self.performRecursively(self.currentTest, True)
    def performRecursively(self, suite, ascending):        
        # First ask all sub-suites to sort themselves
        errors = ""
        if self.currentTest.getConfigValue("sort_test_suites_recursively"):
            for test in suite.testcases:
                if test.classId() == "test-suite":
                    try:
                        self.performRecursively(test, ascending)
                    except Exception, e:
                        errors += str(e) + "\n" 

        self.notify("Status", "Sorting " + repr(suite))
        self.notify("ActionProgress", "")
        if self.hasNonDefaultTests():
            self.notify("Warning", "\nThe test suite\n'" + suite.name + "'\ncontains tests which are not present in the default version.\nTests which are only present in some versions will not be\nmixed with tests in the default version, which might lead to\nthe suite not looking entirely sorted.")

        suite.sortTests(ascending)
    def hasNonDefaultTests(self):
        if len(self.currSuites) == 1:
            return False

        for extraSuite in self.currSuites[1:]:
            for test in extraSuite.testcases:
                if not self.currentTest.findSubtest(test.name):
                    return True
        return False

class SortTestSuiteFileDescending(SortTestSuiteFileAscending):
    def getStockId(self):
        return "sort-descending"
    def _getTitle(self):
        return "_Reversed Sort Test Suite File"
    def messageAfterPerform(self):
        return "Sorted testsuite file for " + repr(self.currentTest) + " in reversed alphabetical order."
    def _getScriptTitle(self):
        return "sort testsuite file for the selected test suite in reversed alphabetical order"
    def performOnCurrent(self):
        self.performRecursively(self.currentTest, False)

class RepositionTest(InteractiveTestAction):
    def correctTestClass(self):
        return True
    def _isActiveOnCurrent(self):
        return InteractiveTestAction.isActiveOnCurrent(self) and \
               self.currentTest.parent and \
               not self.currentTest.parent.autoSortOrder

    def performOnCurrent(self):
        newIndex = self.findNewIndex()
        if self.currentTest.parent.repositionTest(self.currentTest, newIndex):
            self.notify("RefreshTestSelection")
        else:
            raise plugins.TextTestError, "\nThe test\n'" + self.currentTest.name + "'\nis not present in the default version\nand hence cannot be reordered.\n"
    
class RepositionTestDown(RepositionTest):
    def getStockId(self):
        return "go-down"
    def _getTitle(self):
        return "Move down"
    def messageAfterPerform(self):
        return "Moved " + repr(self.currentTest) + " one step down in suite."
    def _getScriptTitle(self):
        return "Move selected test down in suite"
    def findNewIndex(self):
        return min(self.currentTest.positionInParent() + 1, self.currentTest.parent.maxIndex())
    def isActiveOnCurrent(self, *args):
        if not self._isActiveOnCurrent():
            return False
        return self.currentTest.parent.testcases[self.currentTest.parent.maxIndex()] != self.currentTest

class RepositionTestUp(RepositionTest):
    def getStockId(self):
        return "go-up"
    def _getTitle(self):
        return "Move up"
    def messageAfterPerform(self):
        return "Moved " + repr(self.currentTest) + " one step up in suite."
    def _getScriptTitle(self):
        return "Move selected test up in suite"
    def findNewIndex(self):
        return max(self.currentTest.positionInParent() - 1, 0)
    def isActiveOnCurrent(self, *args):
        if not self._isActiveOnCurrent():
            return False
        return self.currentTest.parent.testcases[0] != self.currentTest

class RepositionTestFirst(RepositionTest):
    def getStockId(self):
        return "goto-top"
    def _getTitle(self):
        return "Move to first"
    def messageAfterPerform(self):
        return "Moved " + repr(self.currentTest) + " to first in suite."
    def _getScriptTitle(self):
        return "Move selected test to first in suite"
    def findNewIndex(self):
        return 0
    def isActiveOnCurrent(self, *args):
        if not self._isActiveOnCurrent():
            return False
        return self.currentTest.parent.testcases[0] != self.currentTest

class RepositionTestLast(RepositionTest):
    def getStockId(self):
        return "goto-bottom"
    def _getTitle(self):
        return "Move to last"
    def messageAfterPerform(self):
        return "Moved " + repr(self.currentTest) + " to last in suite."
    def _getScriptTitle(self):
        return "Move selected test to last in suite"
    def findNewIndex(self):
        return self.currentTest.parent.maxIndex()
    def isActiveOnCurrent(self, *args):
        if not self._isActiveOnCurrent():
            return False
        currLastTest = self.currentTest.parent.testcases[len(self.currentTest.parent.testcases) - 1]
        return currLastTest != self.currentTest
    
class RenameTest(InteractiveTestAction):
    def __init__(self, *args):
        InteractiveTestAction.__init__(self, *args)
        self.newName = ""
        self.oldName = ""
        self.newDescription = ""
        self.oldDescription = ""
        self.allSelected = []
    def updateSelection(self, tests, rowCount):
        self.allSelected = tests
        InteractiveTestAction.updateSelection(self, tests, rowCount)
    
    def getDialogType(self):
        if self.currentTest:
            self.newName = self.currentTest.name
            self.newDescription = plugins.extractComment(self.currentTest.description)
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
        if self.oldName != self.newName:
            message = "Renamed test " + self.oldName + " to " + self.newName
            if self.oldDescription != self.newDescription:
                message += " and changed description."
            else:
                message += "."
        elif self.newDescription != self.oldDescription:
            message = "Changed description of test " + self.oldName + "."
        else:
            message = "Nothing changed."
        return message
    def checkNewName(self):
        if self.newName == self.currentTest.name:
            return ("", False)
        if len(self.newName) == 0:
            return ("Please enter a new name.", True)
        if self.newName.find(" ") != -1:
            return ("The new name must not contain spaces, please choose another name.", True)
        for test in self.currentTest.parent.testCaseList():
            if test.name == self.newName:
                return ("The name '" + self.newName + "' is already taken, please choose another name.", True)
        newDir = os.path.join(self.currentTest.parent.getDirectory(), self.newName)
        if os.path.isdir(newDir):
            return ("The directory '" + newDir + "' already exists.\n\nDo you want to overwrite it?", False)
        return ("", False)
    def performOnCurrent(self):
        try:
            if self.newName != self.oldName or self.newDescription != self.oldDescription:
                for test in self.allSelected:
                    test.rename(self.newName, self.newDescription)
        except IOError, e:
            self.notify("Error", "Failed to rename test:\n" + str(e))
        except OSError, e:
            self.notify("Error", "Failed to rename test:\n" + str(e))
 
class ShowFileProperties(SelectionAction):
    def __init__(self, allApps, dynamic):
        SelectionAction.__init__(self, allApps)
        self.dynamic = dynamic
    def isActiveOnCurrent(self, *args):
        return ((not self.dynamic) or len(self.currTestSelection) == 1) and \
               len(self.currFileSelection) > 0
    def updateSelection(self, tests, *args):
        self.currTestSelection = tests # interested in suites, unlike most SelectionActions
    def notifyNewFileSelection(self, files):
        self.updateFileSelection(files)
    def getResultDialogType(self):
        return "guidialogs.FilePropertiesDialog"
    def _getTitle(self):
        return "_File Properties"
    def _getScriptTitle(self):
        return "Show properties of selected files"
    def describeTests(self):
        return str(len(self.currFileSelection)) + " files"
    def performOnCurrent(self):
        self.properties = []
        errors = []
        for file, comp in self.currFileSelection:
            if self.dynamic and comp:
                self.performOnFile(comp.tmpFile, self.properties, errors)
            self.performOnFile(file, self.properties, errors)
            
        if len(errors):
            self.notify("Error", "Failed to get file properties:\n" + "\n".join(errors))
                
    def performOnFile(self, file, properties, errors):
        try:
            prop = plugins.FileProperties(file)
            guilog.info("Showing properties of the file " + file + ":\n" + prop.getUnixStringRepresentation())
            properties.append(prop)
        except Exception, e:
            errors.append(str(e))          
        
            
class VersionInformation(InteractiveAction):
    def _getTitle(self):
        return "Component _Versions"
    def messageAfterPerform(self):
        return ""
    def _getScriptTitle(self):
        return "show component version information"
    def getResultDialogType(self):
        return "helpdialogs.VersionsDialog"
    def performOnCurrent(self):
        pass # The only result is the result popup dialog ...

class AboutTextTest(InteractiveAction):
    def getStockId(self):
        return "about"
    def _getTitle(self):
        return "_About TextTest"
    def messageAfterPerform(self):
        return ""
    def _getScriptTitle(self):
        return "show information about texttest"
    def getResultDialogType(self):
        return "helpdialogs.AboutTextTestDialog"
    def performOnCurrent(self):
        pass # The only result is the result popup dialog ...

class MigrationNotes(InteractiveAction):
    def _getTitle(self):
        return "_Migration Notes"
    def messageAfterPerform(self):
        return ""
    def _getScriptTitle(self):
        return "show texttest migration notes"
    def getResultDialogType(self):
        return "helpdialogs.MigrationNotesDialog"
    def performOnCurrent(self):
        pass # The only result is the result popup dialog ...

class InteractiveActionConfig:
    def getMenuNames(self):
        return [ "file", "edit", "view", "actions", "site", "reorder", "help" ]

    def getInteractiveActionClasses(self, dynamic):
        classes = [ Quit, ViewInEditor, ShowFileProperties ]
        if dynamic:
            classes += [ ViewFilteredInEditor, ViewFileDifferences, 
                         ViewFilteredFileDifferences, FollowFile, 
                         SaveTests, SaveSelection, RecomputeTest, 
                         RecomputeAllTests, KillTests, MarkTest, UnmarkTest ]
        else:
            classes += [ RecordTest, CopyTests, CutTests, 
                         PasteTests, ImportTestCase, ImportTestSuite, 
                         CreateDefinitionFile, ReportBugs, SelectTests, 
                         RunTests, ResetGroups, RenameTest, RemoveTests, 
                         SortTestSuiteFileAscending, SortTestSuiteFileDescending, 
                         RepositionTestFirst, RepositionTestUp,
                         RepositionTestDown, RepositionTestLast,
                         ReconnectToTests, LoadSelection, SaveSelection ]
        classes += [ MigrationNotes, VersionInformation, AboutTextTest ]
        return classes

    def getReplacements(self):
        # Return a dictionary mapping classes above to what to replace them with
        return {}
