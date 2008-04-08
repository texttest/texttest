
import guiplugins, helpdialogs, plugins, os, sys, shutil, time, subprocess, operator, types, gtk, entrycompletion
from jobprocess import JobProcess
from sets import Set
from copy import copy, deepcopy
from threading import Thread
from glob import glob
from stat import *
from ndict import seqdict
from log4py import LOGLEVEL_NORMAL
   
    
class Quit(guiplugins.BasicActionGUI):
    def _getStockId(self):
        return "quit"
    def _getTitle(self):
        return "_Quit"
    def isActiveOnCurrent(self, *args):
        return True
    def getSignalsSent(self):
        return [ "Quit" ]
    def performOnCurrent(self):
        self.notify("Quit")
    def messageAfterPerform(self):
        pass # GUI isn't there to show it
    def getConfirmationMessage(self):
        runningProcesses = guiplugins.processMonitor.listRunningProcesses()
        if len(runningProcesses) == 0:
            return ""
        else:
            return "\nThese processes are still running, and will be terminated when quitting: \n\n   + " + \
                   "\n   + ".join(runningProcesses) + "\n\nQuit anyway?\n"

        
# Plugin for saving tests (standard)
class SaveTests(guiplugins.ActionTabGUI):
    def __init__(self, allApps, *args):
        guiplugins.ActionTabGUI.__init__(self, allApps, *args)
        self.addOption("v", "Version to save")
        self.addSwitch("over", "Replace successfully compared files also", 0)
        if self.hasPerformance(allApps):
            self.addSwitch("ex", "Save", 1, ["Average performance", "Exact performance"])
    def _getStockId(self):
        return "save"
    def getTabTitle(self):
        return "Saving"
    def _getTitle(self):
        return "_Save"
    def getTooltip(self):
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
                guiplugins.guilog.info("Saving " + repr(test) + " - version " + version + saveDesc)
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

        
class MarkTest(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("brief", "Brief text", "Checked")
        self.addOption("free", "Free text", "Checked at " + plugins.localtime())
    def _getTitle(self):
        return "_Mark"
    def getTooltip(self):
        return "Mark the selected tests"
    def performOnCurrent(self):
        for test in self.currTestSelection:
            oldState = test.state
            if oldState.isComplete():
                if test.state.isMarked():
                    oldState = test.state.oldState # Keep the old state so as not to build hierarchies ...
                newState = plugins.MarkedTestState(self.optionGroup.getOptionValue("free"),
                                                   self.optionGroup.getOptionValue("brief"), oldState)
                test.changeState(newState)
                self.notify("ActionProgress", "") # Just to update gui ...            
    def isActiveOnCurrent(self, test=None, state=None):
        if state and state.isComplete():
            return True
        for seltest in self.currTestSelection:
            if seltest is not test and seltest.state.isComplete():
                return True
        return False

class UnmarkTest(guiplugins.ActionGUI):
    def _getTitle(self):
        return "_Unmark"
    def getTooltip(self):
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

class FileViewAction(guiplugins.ActionGUI):
    def __init__(self, *args):
        guiplugins.ActionGUI.__init__(self, *args)
        self.viewTools = {}
    def singleTestOnly(self):
        return True
    def isActiveOnCurrent(self, *args):
        if not guiplugins.ActionGUI.isActiveOnCurrent(self):
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
    def updateFileSelection(self, files):
        for fileName, comparison in files:
            self.viewTools[fileName] = self.getViewTool(fileName)
        return guiplugins.ActionGUI.updateFileSelection(self, files)
    
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
        if len(self.currAppSelection) > 0:
            return "\n" + self.currAppSelection[0].noFileAdvice()
        else:
            return ""
    def testDescription(self):
        if len(self.currTestSelection) > 0:
            return " (from test " + self.currTestSelection[0].uniqueName + ")"
        else:
            return ""
    def getSignalsSent(self):
        return [ "ViewerStarted" ]
    def startViewer(self, cmdArgs, description, *args, **kwargs):
        testDesc = self.testDescription()
        fullDesc = description + testDesc
        nullFile = open(os.devnull, "w")
        guiplugins.processMonitor.startProcess(cmdArgs, fullDesc, stdout=nullFile, stderr=nullFile, *args, **kwargs)
        self.notify("Status", 'Started "' + description + '" in background' + testDesc + '.')
        self.notify("ViewerStarted")

    def handleNoFile(self, fileName):
        self.showErrorDialog("File '" + os.path.basename(fileName) + "' cannot be viewed"
                             " as it has been removed in the file system." + self.noFileAdvice())
         
    def getViewTool(self, fileName):
        viewProgram = self.getViewToolName(fileName)
        if plugins.canExecute(viewProgram):
            return viewProgram
    def getViewToolName(self, fileName):
        stem = os.path.basename(fileName).split(".")[0]
        if len(self.currTestSelection) > 0:
            return self.currTestSelection[0].getCompositeConfigValue(self.getToolConfigEntry(), stem)
        else:
            return guiplugins.guiConfig.getCompositeValue(self.getToolConfigEntry(), stem)
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
    def _getStockId(self):
        return "open"
    def _getTitle(self):
        return "View File"
    def getToolConfigEntry(self):
        return "view_program"
    def viewFile(self, fileName, viewTool, exitHandler, exitHandlerArgs):
        cmdArgs, descriptor, env = self.getViewCommand(fileName, viewTool)
        description = descriptor + " " + os.path.basename(fileName)
        refresh = bool(exitHandler)
        guiplugins.guilog.info("Viewing file " + fileName + " using '" + descriptor + "', refresh set to " + str(refresh))
        self.startViewer(cmdArgs, description=description, scriptName="views and edits test files", env=env,
                         filesEdited=[ fileName ], exitHandler=exitHandler, exitHandlerArgs=exitHandlerArgs)
    def getViewerEnvironment(self, cmdArgs):
        # An absolute path to the viewer may indicate a custom tool, send the test environment along too
        # Doing this is unlikely to cause harm in any case
        if len(self.currTestSelection) > 0 and os.path.isabs(cmdArgs[0]):
            return self.currTestSelection[0].getRunEnvironment()
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
            return self.currTestSelection[0].filesChanged, ()
        elif self.isTestDefinition("testsuite", fileName):
            # refresh order of tests if this edited
            return self.currTestSelection[0].contentChanged, (fileName,)
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
                    self.showErrorDialog("Cannot find file viewing program '" + viewProgram + \
                                         "'.\nPlease install it somewhere on your PATH or\n"
                                         "change the configuration entry 'view_program'.")
                else:
                    self.showWarningDialog("No file viewing program is defined for files of type '" + \
                                           os.path.basename(fileToView).split(".")[0] + \
                                           "'.\nPlease point the configuration entry 'view_program'"
                                           " at a valid program to view the file.")
            else:
                self.handleNoFile(fileToView)
            
    def isTestDefinition(self, stem, fileName):
        if len(self.currTestSelection) == 0:
            return False
        defFile = self.currTestSelection[0].getFileName(stem)
        if defFile:
            return plugins.samefile(fileName, defFile)
        else:
            return False

class ViewFilteredInEditor(ViewInEditor):
    def _getStockId(self):
        pass # don't use same stock for both
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
        guiplugins.guilog.info("Starting graphical difference comparison using '" + diffProgram + "':")
        guiplugins.guilog.info("-- original file : " + stdFile)
        guiplugins.guilog.info("--  current file : " + tmpFile)
        cmdArgs = plugins.splitcmd(diffProgram) + [ stdFile, tmpFile ]
        self.startViewer(cmdArgs, description=description, scriptName="shows graphical differences in test files")
    
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
                    self.showErrorDialog("Cannot find graphical difference program '" + diffProgram + \
                                         "'.\nPlease install it somewhere on your PATH or change the\n"
                                         "configuration entry 'diff_program'.")
                else:
                    self.showWarningDialog("No graphical difference program is defined for files of type '" + \
                                           os.path.basename(tmpFile).split(".")[0] + \
                                           "'.\nPlease point the configuration entry 'diff_program' at a "
                                           "valid program to visualize the differences.")
            else:
                self.handleNoFile(tmpFile)

class FollowFile(FileViewAction):
    def _getTitle(self):
        return "Follow File Progress"
    def getToolConfigEntry(self):
        return "follow_program"
    def _isActiveForFile(self, fileName, comparison):
        return self.currTestSelection[0].state.hasStarted() and not self.currTestSelection[0].state.isComplete()
    def fileToFollow(self, fileName, comparison):
        if comparison:
            return comparison.tmpFile
        else:
            return fileName
    def getFollowCommand(self, followProgram, fileName):
        basic = plugins.splitcmd(followProgram) + [ fileName ]
        if followProgram.startswith("tail") and os.name == "posix":
            title = self.currTestSelection[0].name + " (" + os.path.basename(fileName) + ")"
            return [ "xterm", "-bg", "white", "-T", title, "-e" ] + basic
        else:
            return basic
    def performOnFile(self, fileName, comparison, followProgram):
        useFile = self.fileToFollow(fileName, comparison)
        guiplugins.guilog.info("Following file " + useFile + " using '" + followProgram + "'")
        description = followProgram + " " + os.path.basename(useFile)
        cmdArgs = self.getFollowCommand(followProgram, useFile)
        self.startViewer(cmdArgs, description=description, scriptName="follows progress of test files")    

class KillTests(guiplugins.ActionGUI):
    def _getStockId(self):
        return "stop"
    def _getTitle(self):
        return "_Kill"
    def getTooltip(self):
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
    def getSignalsSent(self):
        return [ "Kill" ]
    def performOnCurrent(self):
        tests = filter(lambda test: not test.state.isComplete(), self.currTestSelection)
        tests.reverse() # best to cut across the action thread rather than follow it and disturb it excessively
        testDesc = str(len(tests)) + " tests"
        self.notify("Status", "Killing " + testDesc + " ...")
        for test in tests:
            self.notify("ActionProgress", "")
            guiplugins.guilog.info("Killing " + repr(test))
            test.notify("Kill")

        self.notify("Status", "Killed " + testDesc + ".")

class ClipboardAction(guiplugins.ActionGUI):
    def correctTestClass(self):
        return "test-case"
    def getSignalsSent(self):
        return [ "Clipboard" ]
    def _getStockId(self):
        return self.getName()
    def _getTitle(self):
        return "_" + self.getName().capitalize()
    def getTooltip(self):
        return self.getName().capitalize() + " selected tests"
    def performOnCurrent(self):
        self.notify("Clipboard", self.currTestSelection, cut=self.shouldCut())

    
class CopyTests(ClipboardAction):
    def getName(self):
        return "copy"
    def shouldCut(self):
        return False
    
class CutTests(ClipboardAction):
    def getName(self):
        return "cut"
    def shouldCut(self):
        return True

class PasteTests(guiplugins.ActionGUI):
    def __init__(self, *args):
        guiplugins.ActionGUI.__init__(self, *args)
        self.clipboardTests = []
        self.removeAfter = False
    def singleTestOnly(self):
        return True
    def _getStockId(self):
        return "paste"
    def _getTitle(self):
        return "_Paste"
    def getTooltip(self):
        return "Paste tests from clipboard"
    def notifyClipboard(self, tests, cut=False):
        self.clipboardTests = tests
        self.removeAfter = cut
        self.setSensitivity(True)

    def isActiveOnCurrent(self, test=None, state=None):
        return guiplugins.ActionGUI.isActiveOnCurrent(self, test, state) and len(self.clipboardTests) > 0
    def getCurrentTestMatchingApp(self, test):
        for currTest in self.currTestSelection:
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
            guiplugins.guilog.info("Pasting test " + newName + " under test suite " + \
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

        guiplugins.guilog.info("Selecting new tests : " + repr(newTests))
        self.notify("SetTestSelection", newTests)
        if self.removeAfter:
            # After a paste from cut, subsequent pastes should behave like copies of the new tests
            self.clipboardTests = newTests
            self.removeAfter = False
        for suite, placement in destInfo.values():
            suite.contentChanged()
    def getSignalsSent(self):
        return [ "SetTestSelection" ]

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
class ImportTest(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
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
    def singleTestOnly(self):
        return True
    def correctTestClass(self):
        return "test-suite"
    def getNameTitle(self):
        return self.testType() + " Name"
    def getDescTitle(self):
        return self.testType() + " Description"
    def getPlaceTitle(self):
        return "\nPlace " + self.testType()
    def updateOptions(self):
        self.optionGroup.setOptionValue("name", self.getDefaultName())
        self.optionGroup.setOptionValue("desc", self.getDefaultDesc())
        self.setPlacements(self.currTestSelection[0])
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
            
        guiplugins.guilog.info("Adding " + self.testType() + " " + testName + " under test suite " + \
                    repr(suite) + ", placed " + self.optionGroup.getOptionValue("testpos"))
        placement = self.getPlacement()
        description = self.optionGroup.getOptionValue("desc")
        testDir = suite.writeNewTest(testName, description, placement)
        self.testImported = self.createTestContents(suite, testDir, description, placement)
        suite.contentChanged()
        guiplugins.guilog.info("Selecting new test " + self.testImported.name)
        self.notify("SetTestSelection", [ self.testImported ])
    def getSignalsSent(self):
        return [ "SetTestSelection" ]
    def getDestinationSuite(self):
        return self.currTestSelection[0]
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
        
    
class ImportTestCase(ImportTest):
    def __init__(self, *args):
        ImportTest.__init__(self, *args)
        self.addDefinitionFileOption()
    def testType(self):
        return "Test"
    def _getStockId(self):
        return "add"
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
            guiplugins.guilog.info("Setting test env: " + var + " = " + value)
            envFile.write(var + ":" + value + "\n")
        envFile.close()
    def writeDefinitionFiles(self, suite, testDir):
        optionString = self.getOptions(suite)
        if len(optionString):
            guiplugins.guilog.info("Using option string : " + optionString)
            optionFile = self.getWriteFile("options", suite, testDir)
            optionFile.write(optionString + "\n")
        else:
            guiplugins.guilog.info("Not creating options file")
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
    def _getStockId(self):
        return "directory"
    def createTestContents(self, suite, testDir, description, placement):
        return suite.addTestSuite(os.path.basename(testDir), description, placement, self.writeEnvironmentFiles)
    def addEnvironmentFileOptions(self):
        self.addSwitch("env", "Add environment file")
    def writeEnvironmentFiles(self, newSuite):
        if self.optionGroup.getSwitchValue("env"):
            envFile = os.path.join(newSuite.getDirectory(), "environment")
            file = open(envFile, "w")
            file.write("# Dictionary of environment to variables to set in test suite\n")

class SelectTests(guiplugins.ActionTabGUI):
    def __init__(self, allApps, *args):
        guiplugins.ActionTabGUI.__init__(self, allApps)
        self.selectDiag = plugins.getDiagnostics("Select Tests")
        self.rootTestSuites = []
        self.addOption("vs", "Tests for version", description="Select tests for a specific version.",
                       possibleValues=self.getPossibleVersions(allApps))
        self.addSwitch("select_in_collapsed_suites", "Select in collapsed suites", 0, description="Select in currently collapsed suites as well?")
        self.addSwitch("current_selection", "Current selection", options = [ "Discard", "Refine", "Extend", "Exclude"], description="How should we treat the currently selected tests?\n - Discard: Unselect all currently selected tests before applying the new selection criteria.\n - Refine: Apply the new selection criteria only to the currently selected tests, to obtain a subselection.\n - Extend: Keep the currently selected tests even if they do not match the new criteria, and extend the selection with all other tests which meet the new criteria.\n - Exclude: After applying the new selection criteria to all tests, unselect the currently selected tests, to exclude them from the new selection.")
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
    def getSignalsSent(self):
        return [ "SetTestSelection" ]
    def _getStockId(self):
        return "refresh"
        #return "find"
    def _getTitle(self):
        return "_Select"
    def getTooltip(self):
        return "Select indicated tests"
    def getTabTitle(self):
        return "Selection"
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
                
            guiplugins.guilog.info("Selected " + str(len(newTests)) + " out of a possible " + str(suite.size()))
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
            return filter(lambda test: test in self.currTestSelection, reqTests)
        else:
            extraRequested = filter(lambda test: test not in self.currTestSelection, reqTests)
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
        self.selectDiag.info("Trying to get test cases for " + repr(suite) + ", version " + versionToUse)
        return suite.findTestCases(versionToUse)

    def findCombinedVersion(self, version, fullVersion):
        combined = version
        if len(fullVersion) > 0 and len(version) > 0:
            parts = version.split(".")
            for appVer in fullVersion.split("."):
                if not appVer in parts:
                    combined += "." + appVer
        return combined

class ResetGroups(guiplugins.BasicActionGUI):
    def isActiveOnCurrent(self, *args):
        return True
    def _getStockId(self):
        return "revert-to-saved"
    def _getTitle(self):
        return "R_eset"
    def messageAfterPerform(self):
        return "All options reset to default values."
    def getTooltip(self):
        return "Reset running options"
    def getSignalsSent(self):
        return [ "Reset" ]
    def performOnCurrent(self):
        self.notify("Reset")

    
class SaveSelection(guiplugins.ActionDialogGUI):
    def __init__(self, allApps, dynamic):
        guiplugins.ActionDialogGUI.__init__(self, allApps, dynamic)
        self.addOption("f", "enter filter-file name =",
                       possibleDirs=allApps[0].getFilterFileDirectories(allApps, createDirs=False), saveFile=True)
        if not dynamic:
            # In the static GUI case, we also want radiobuttons specifying 
            # whether we want to save the actual tests, or the selection criteria.
            self.addSwitch("tests", "Save", options= [ "_List of selected tests", "C_riteria entered in the Selection tab\n(Might not match current selection, if it has been modified)" ])
        self.selectionCriteria = ""
        self.dynamic = dynamic
        self.rootTestSuites = []
    def correctTestClass(self):
        return "test-case"
    def addSuites(self, suites):
        self.rootTestSuites = suites
    def _getStockId(self):
        return "save-as"
    def _getTitle(self):
        return "S_ave Selection..."
    def getTooltip(self):
        return "Save selected tests in file"
        return self.folders
    def getTestPathFilterArg(self):
        selTestPaths = []
        for suite in self.rootTestSuites:
            selTestPaths.append("appdata=" + suite.app.name + suite.app.versionSuffix())
            for test in suite.testCaseList():
                if test in self.currTestSelection:
                    selTestPaths.append(test.getRelPath())
        return "-tp " + "\n".join(selTestPaths)
    def notifySetTestSelection(self, tests, criteria="", *args):
        self.selectionCriteria = criteria
    def getTextToSave(self):
        if self.dynamic or not self.optionGroup.getSwitchValue("tests"):
            return self.getTestPathFilterArg()
        else:
            return self.selectionCriteria
    def getConfirmationMessage(self):    
        fileName = self.optionGroup.getOptionValue("f")    
        if fileName and os.path.isfile(fileName):
            return "\nThe file \n" + fileName + "\nalready exists.\n\nDo you want to overwrite it?\n"

    def getConfirmationDialogSettings(self):
        return gtk.STOCK_DIALOG_QUESTION, "Query"    

    def notifySaveSelection(self, fileName):
        toSave = self.getTestPathFilterArg()
        self.writeFile(fileName, toSave)
    def performOnCurrent(self):
        toWrite = self.getTextToSave()
        fileName = self.optionGroup.getOptionValue("f")
        if not fileName:
            raise plugins.TextTestError, "Cannot save selection - no file name specified"
        elif os.path.isdir(fileName):
            raise plugins.TextTestError, "Cannot save selection - existing directory specified"
        else:
            self.writeFile(fileName, toWrite)
    def writeFile(self, fileName, toWrite):
        try:
            file = open(fileName, "w")
            file.write(toWrite + "\n")
            file.close()
        except IOError, e:
            raise plugins.TextTestError, "\nFailed to save selection:\n" + str(e) + "\n"
    def messageAfterPerform(self):
        return "Saved " + self.describeTests() + " in file '" + self.optionGroup.getOptionValue("f") + "'."


class LoadSelection(guiplugins.ActionDialogGUI):
    def __init__(self, allApps, *args):
        guiplugins.ActionDialogGUI.__init__(self, allApps, *args)
        self.addOption("f", "select filter-file", possibleDirs=allApps[0].getFilterFileDirectories(allApps, createDirs=False), selectFile=True)
        self.rootTestSuites = []
    def addSuites(self, suites):
        self.rootTestSuites = suites
    def isActiveOnCurrent(self, *args):
        return True
    def getSignalsSent(self):
        return [ "SetTestSelection" ]
    def _getStockId(self):
        return "open"
    def _getTitle(self):
        return "_Load Selection..."
    def getTooltip(self):
        return "Load test selection from file"
    def getDirectories(self):
        return self.optionGroup.getOption("f").getDirectories()
    def performOnCurrent(self):
        fileName = self.optionGroup.getOptionValue("f")
        if fileName:
            newSelection = self.makeNewSelection(fileName)
            guiplugins.guilog.info("Loaded " + str(len(newSelection)) + " tests from " + fileName)
            self.notify("SetTestSelection", newSelection, "-f " + fileName, True)
            self.notify("Status", "Loaded test selection from file '" + fileName + "'.")
        else:
            self.notify("Status", "No test selection loaded.")

    def makeNewSelection(self, fileName):
        tests = []
        for suite in self.rootTestSuites:
            filters = suite.app.getFiltersFromFile(fileName)
            tests += suite.testCaseList(filters)
        return tests
    def getResizeDivisors(self):
        # size of the dialog
        return 1.2, 1.7

    def messageBeforePerform(self):
        return "Loading test selection ..."
    def messageAfterPerform(self):
        pass
    
class RunningAction(guiplugins.ActionTabGUI):
    runNumber = 1
    def __init__(self, allApps, *args):
        guiplugins.ActionTabGUI.__init__(self, allApps)
        for app in allApps:
            for group in app.optionGroups:
                if group.name.startswith("Invisible"):
                    self.invisibleGroup = group
    def setObservers(self, observers):
        guiplugins.ActionTabGUI.setObservers(self, observers)
        # so we can notify ourselves (!) about errors...
        self.observers.append(self)
    def correctTestClass(self):
        return "test-case"
    def messageAfterPerform(self):
        return self.performedDescription() + " " + self.describeTests() + " at " + plugins.localtime() + "."
    
    def performOnCurrent(self):
        self.startTextTestProcess(self.getUseCaseName(), self.invisibleGroup.getCommandLines())
    def startTextTestProcess(self, usecase, runModeOptions):
        app = self.currAppSelection[0]
        writeDir = os.path.join(app.writeDirectory, "dynamic_run" + str(self.runNumber))
        plugins.ensureDirectoryExists(writeDir)
        filterFile = self.writeFilterFile(writeDir)
        ttOptions = runModeOptions + self.getTextTestOptions(filterFile, app)
        guiplugins.guilog.info("Starting " + usecase + " run of TextTest with arguments " + repr(ttOptions))
        logFile = os.path.join(writeDir, "output.log")
        errFile = os.path.join(writeDir, "errors.log")
        self.runNumber += 1
        description = "Dynamic GUI started at " + plugins.localtime()
        cmdArgs = self.getTextTestArgs() + ttOptions
        env = self.getNewUseCaseEnvironment(usecase)
        guiplugins.processMonitor.startProcess(cmdArgs, description, env=env,
                                               stdout=open(logFile, "w"), stderr=open(errFile, "w"),
                                               exitHandler=self.checkTestRun, 
                                               exitHandlerArgs=(errFile,self.currTestSelection,usecase))

    def getNewUseCaseEnvironment(self, usecase):
        environ = deepcopy(os.environ)
        recScript = os.getenv("USECASE_RECORD_SCRIPT")
        if recScript:
            environ["USECASE_RECORD_SCRIPT"] = plugins.addLocalPrefix(recScript, usecase)
        repScript = os.getenv("USECASE_REPLAY_SCRIPT")
        if repScript:
            # Dynamic GUI might not record anything (it might fail) - don't try to replay files that
            # aren't there...
            dynRepScript = plugins.addLocalPrefix(repScript, usecase)
            if os.path.isfile(dynRepScript):
                environ["USECASE_REPLAY_SCRIPT"] = dynRepScript
            else:
                del environ["USECASE_REPLAY_SCRIPT"]
        return environ
    def getSignalsSent(self):
        return [ "SaveSelection" ]
    def writeFilterFile(self, writeDir):
        # Because the description of the selection can be extremely long, we write it in a file and refer to it
        # This avoids too-long command lines which are a problem at least on Windows XP
        filterFileName = os.path.join(writeDir, "gui_select")
        self.notify("SaveSelection", filterFileName)
        return filterFileName
    def getTextTestArgs(self):
        if os.name == "nt" and plugins.textTestName.endswith(".py"):
            return [ "python", plugins.textTestName ] # Windows isn't clever enough to figure out how to run Python programs...
        else:
            return [ plugins.textTestName ]
    def getOptionGroups(self):
        return [ self.optionGroup ]
    def getTextTestOptions(self, filterFile, app):
        ttOptions = self.getCmdlineOptionForApps()
        for group in self.getOptionGroups():
            ttOptions += group.getCommandLines(self.getCommandLineKeys())
        ttOptions += [ "-count", str(self.getTestCount()) ]
        ttOptions += [ "-f", filterFile ]
        ttOptions += [ "-fd", self.getTmpFilterDir(app) ]
        return ttOptions
    def getCommandLineKeys(self):
        # assume everything by default
        return []
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
    def checkTestRun(self, errFile, testSel, usecase):
        if self.checkErrorFile(errFile, testSel, usecase):
            self.handleCompletion(testSel, usecase)
            if len(self.currTestSelection) >= 1 and self.currTestSelection[0] in testSel:
                self.currTestSelection[0].filesChanged()

        testSel[0].notify("CloseDynamic", usecase)

    def notifyError(self, message):
        self.showErrorDialog(message)

    def readAndFilter(self, errFile, testSel):
        errText = ""
        triggerGroup = plugins.TextTriggerGroup(testSel[0].getConfigValue("suppress_stderr_popup"))
        for line in open(errFile).xreadlines():
            if not triggerGroup.stringContainsText(line):
                errText += line
        return errText
    def checkErrorFile(self, errFile, testSel, usecase):
        if os.path.isfile(errFile):
            errText = self.readAndFilter(errFile, testSel)
            if len(errText):
                self.notify("Status", usecase.capitalize() + " run failed for " + repr(testSel[0]))
                # We're in a funny thread, don't try to create the dialog directly
                self.notify("Error", usecase.capitalize() + " run failed, with the following errors:\n" + errText)
                return False
        return True
    
    def handleCompletion(self, *args):
        pass # only used when recording

class ReconnectToTests(RunningAction):
    def __init__(self, *args):
        RunningAction.__init__(self, *args)
        self.addOption("v", "Version to reconnect to")
        self.addOption("reconnect", "Temporary result directory", os.getenv("TEXTTEST_TMP"), description="Specify a directory containing temporary texttest results. The reconnection will use a random subdirectory matching the version used.")
        self.addSwitch("reconnfull", "Results", 0, ["Display as they were", "Recompute from files"])
    def getGroupTabTitle(self):
        return "Running"
    def _getStockId(self):
        return "connect"
    def _getTitle(self):
        return "Re_connect"
    def getTooltip(self):
        return "Reconnect to previously run tests"
    def getTabTitle(self):
        return "Reconnect"
    def performedDescription(self):
        return "Reconnected to"
    def getUseCaseName(self):
        return "reconnect"
    
class RunTests(RunningAction):
    optionGroups = []
    def __init__(self, allApps, *args):
        RunningAction.__init__(self, allApps)
        self.optionGroups.append(self.optionGroup)
        for app in allApps:
            for group in app.optionGroups:
                if group.name == self.getTabTitle():
                    self.optionGroup.mergeIn(group)
    def _getTitle(self):
        return "_Run"
    def _getStockId(self):
        return "execute"
    def getTooltip(self):
        return "Run selected tests"
    def getGroupTabTitle(self):
        return "Running"
    def getOptionGroups(self):
        return self.optionGroups
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

class RunTestsBasic(RunTests):
    def getTabTitle(self):
        return "Basic"

class RunTestsAdvanced(RunTests):
    def getTabTitle(self):
        return "Advanced"

class RecordTest(RunningAction):
    def __init__(self, *args):
        RunningAction.__init__(self, *args)
        self.currentApp = None
        self.recordTime = None
        self.addOption("v", "Version to record")
        self.addOption("c", "Checkout to use for recording") 
        self.addSwitch("rep", "Automatically replay test after recording it", 1)
        self.addSwitch("repgui", "", options = ["Auto-replay invisible", "Auto-replay in dynamic GUI"])
    def _getStockId(self):
        return "media-record"
    def singleTestOnly(self):
        return True
    def inMenuOrToolBar(self):
        return False
    def getTabTitle(self):
        return "Recording"
    def messageAfterPerform(self):
        return "Started record session for " + self.describeTests()
    def performOnCurrent(self):
        self.updateRecordTime(self.currTestSelection[0])
        self.startTextTestProcess("record", self.invisibleGroup.getCommandLines() + [ "-record" ])
    def getRecordMode(self):
        return self.currTestSelection[0].getConfigValue("use_case_record_mode")
    def isActiveOnCurrent(self, *args):
        return RunningAction.isActiveOnCurrent(self, *args) and self.getRecordMode() != "disabled" and \
               self.currTestSelection[0].getConfigValue("use_case_recorder") != "none"
    def updateOptions(self):
        if self.currentApp is not self.currAppSelection[0]:
            self.currentApp = self.currAppSelection[0]
            self.optionGroup.setOptionValue("v", self.currentApp.getFullVersion(forSave=1))
            self.optionGroup.setOptionValue("c", self.currentApp.checkout)
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
        test.refreshFiles() # update cache after record run
        file = self.getUseCaseFile(test)
        if not file or not self._updateRecordTime(file):
            return

        parts = os.path.basename(file).split(".")
        return ".".join(parts[2:])
    
    def handleCompletion(self, testSel, usecase):
        test = testSel[0]
        if usecase == "record":
            changedUseCaseVersion = self.getChangedUseCaseVersion(test)
            if changedUseCaseVersion is not None and self.optionGroup.getSwitchValue("rep"):
                self.startTextTestProcess("replay", self.getReplayRunModeOptions(changedUseCaseVersion))
                message = "Recording completed for " + repr(test) + \
                          ". Auto-replay of test now started. Don't submit the test manually!"
                self.notify("Status", message)
            else:
                self.notify("Status", "Recording completed for " + repr(test) + ", not auto-replaying")
        else:
            self.notify("Status", "Recording and auto-replay completed for " + repr(test))
    def getCommandLineKeys(self):
        return [ "v", "c" ]
    def getReplayRunModeOptions(self, overwriteVersion):
        if self.optionGroup.getSwitchValue("repgui"):
            return self.invisibleGroup.getCommandLines() + [ "-autoreplay" ]
        else:
            return [ "-autoreplay", "-o", overwriteVersion ]
    def _getTitle(self):
        return "Record _Use-Case"


class CreateDefinitionFile(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        self.creationDir = None
        self.appendAppName = False
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("stem", "Type of definition file to create", allocateNofValues=2)
        self.addOption("v", "Version identifier to use")
    def singleTestOnly(self):
        return True
    def _getTitle(self):
        return "Create _File"
    def _getStockId(self):
        return "new" 
    def getDialogTitle(self):
        return "New File" 
    def getScriptTitle(self, tab):
        return "Create File"
    def isActiveOnCurrent(self, *args):
        return self.creationDir is not None and guiplugins.ActionDialogGUI.isActiveOnCurrent(self, *args) 
    def notifyFileCreationInfo(self, creationDir, fileType):
        self.creationDir = creationDir
        newActive = creationDir is not None
        self.setSensitivity(newActive)
        if newActive:
            self.updateStems(fileType)
            self.appendAppName = (fileType == "definition" or fileType == "standard")
    def findAllStems(self, fileType):
        if fileType == "definition":
            return self.getDefinitionFiles()
        elif fileType == "data":
            return self.currTestSelection[0].app.getDataFileNames()
        elif fileType == "standard":
            return self.getStandardFiles()
    def getDefinitionFiles(self):
        defFiles = []
        defFiles.append("environment")
        if self.currTestSelection[0].classId() == "test-case":
            defFiles.append("options")
            recordMode = self.currTestSelection[0].getConfigValue("use_case_record_mode")
            if recordMode == "disabled":
                defFiles.append("input")
            else:
                defFiles.append("usecase")
        # these are created via the GUI, not manually via text editors (or are already handled above)
        dontAppend = [ "testsuite", "knownbugs", "traffic", "input", "usecase", "environment", "options" ]
        for defFile in self.currTestSelection[0].getConfigValue("definition_file_stems"):
            if not defFile in dontAppend:
                defFiles.append(defFile)
        return defFiles
    def getStandardFiles(self):
        stdFiles = [ "output", "errors" ] + self.currTestSelection[0].getConfigValue("collate_file").keys()
        discarded = [ "stacktrace" ] + self.currTestSelection[0].getConfigValue("discard_file")
        return filter(lambda f: f not in discarded, stdFiles)
    def updateStems(self, fileType):
        stems = self.findAllStems(fileType)
        self.optionGroup.setValue("stem", stems[0])
        self.optionGroup.setPossibleValues("stem", stems)
    def getFileName(self, stem, version):
        fileName = stem
        if self.appendAppName:
            fileName += "." + self.currTestSelection[0].app.name
        if version:
            fileName += "." + version
        return fileName
    def getSourceFile(self, stem, version, targetFile):
        thisTestName = self.currTestSelection[0].getFileName(stem, version)
        if thisTestName and not os.path.basename(thisTestName) == targetFile:
            return thisTestName

        test = self.currTestSelection[0].parent
        while test:
            currName = test.getFileName(stem, version)
            if currName:
                return currName
            test = test.parent
    def performOnCurrent(self):
        stem = self.optionGroup.getOptionValue("stem")
        version = self.optionGroup.getOptionValue("v")
        targetFileName = self.getFileName(stem, version)
        sourceFile = self.getSourceFile(stem, version, targetFileName)
        # If the source has an app identifier in it we need to get one, or we won't get prioritised!
        stemWithApp = stem + "." + self.currTestSelection[0].app.name
        if sourceFile and os.path.basename(sourceFile).startswith(stemWithApp) and not targetFileName.startswith(stemWithApp):
            targetFileName = targetFileName.replace(stem, stemWithApp, 1)
            sourceFile = self.getSourceFile(stem, version, targetFileName)
            
        targetFile = os.path.join(self.creationDir, targetFileName)
        plugins.ensureDirExistsForFile(targetFile)
        fileExisted = os.path.exists(targetFile)
        if sourceFile and os.path.isfile(sourceFile):
            guiplugins.guilog.info("Creating new file, copying " + sourceFile)
            shutil.copyfile(sourceFile, targetFile)
        elif not fileExisted:
            file = open(targetFile, "w")
            file.close()
            guiplugins.guilog.info("Creating new empty file...")
        else:
            raise plugins.TextTestError, "Unable to create file, no possible source found and target file already exists:\n" + targetFile
        self.notify("NewFile", targetFile, fileExisted)
    def getSignalsSent(self):
        return [ "NewFile" ]
    def messageAfterPerform(self):
        pass

class RemoveTests(guiplugins.ActionGUI):
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
    def _getStockId(self):
        return "delete"
    def getTooltip(self):
        return "Remove selected files"
    def getFilesDescription(self, number = None):
        numberOfFiles = len(self.currFileSelection)
        if number is not None:
            numberOfFiles = number
        return self.pluralise(numberOfFiles, "file")
    def pluralise(self, num, name):
        if num == 1:
            return "1 " + name
        else:
            return str(num) + " " + name + "s"
    def getTestCountDescription(self):
        desc = self.pluralise(self.distinctTestCount, "test")
        diff = len(self.currTestSelection) - self.distinctTestCount
        if diff > 0:
            desc += " (with " + self.pluralise(diff, "extra instance") + ")"
        return desc
    def updateSelection(self, tests, apps, rowCount, *args):
        self.distinctTestCount = rowCount
        return guiplugins.ActionGUI.updateSelection(self, tests, apps, rowCount, *args)
    def getConfirmationMessage(self):
        extraLines = """
\nNote: This will remove files from the file system and hence may not be reversible.\n
Are you sure you wish to proceed?\n"""
        currTest = self.currTestSelection[0]
        if len(self.currFileSelection) > 0:
            return "\nYou are about to remove " + self.getFilesDescription() + \
                   " from the " + currTest.classDescription() + " '" + currTest.name + "'." + extraLines
        elif len(self.currTestSelection) == 1:                  
            if currTest.classId() == "test-case":
                return "\nYou are about to remove the test '" + currTest.name + \
                       "' and all associated files." + extraLines
            else:
                return "\nYou are about to remove the entire test suite '" + currTest.name + \
                       "' and all " + str(currTest.size()) + " tests that it contains." + extraLines
        else:
            return "\nYou are about to remove " + self.getTestCountDescription() + \
                   " and all associated files." + extraLines
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
            self.showWarningDialog(warnings)
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
            self.showWarningDialog(warnings)
    def messageAfterPerform(self):
        pass # do it as part of the method as currentTest will have changed by the end!
    
class ReportBugs(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("search_string", "Text or regexp to match")
        self.addOption("search_file", "File to search in")
        self.addOption("version", "\nVersion to report for")
        self.addOption("execution_hosts", "Trigger only when run on machine(s)")
        self.addOption("bug_system", "\nExtract info from bug system", "<none>", [ "bugzilla" ])
        self.addOption("bug_id", "Bug ID (only if bug system given)")
        self.addOption("full_description", "\nFull description (no bug system)")
        self.addOption("brief_description", "Few-word summary (no bug system)")
        self.addSwitch("trigger_on_absence", "Trigger if given text is NOT present")
        self.addSwitch("internal_error", "Trigger even if other files differ (report as internal error)")
        self.addSwitch("trigger_on_success", "Trigger even if test would otherwise succeed")
    def _getStockId(self):
        return "info"
    def singleTestOnly(self):
        return True
    def _getTitle(self):
        return "Enter Failure Information"
    def getDialogTitle(self):
        return "Enter information for automatic interpretation of test failures"
    def updateOptions(self):
        self.optionGroup.setOptionValue("search_file", self.currTestSelection[0].app.getConfigValue("log_file"))
        self.optionGroup.setPossibleValues("search_file", self.getPossibleFileStems())
        self.optionGroup.setOptionValue("version", self.currTestSelection[0].app.getFullVersion())
        return False
    def getPossibleFileStems(self):
        stems = []
        for test in self.currTestSelection[0].testCaseList():
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
        name = "knownbugs." + self.currTestSelection[0].app.name + self.versionSuffix()
        return os.path.join(self.currTestSelection[0].getDirectory(), name)
    def write(self, writeFile, message):
        writeFile.write(message)
        guiplugins.guilog.info(message)
    def getResizeDivisors(self):
        # size of the dialog
        return 1.4, 1.7
    def performOnCurrent(self):
        self.checkSanity()
        fileName = self.getFileName()
        guiplugins.guilog.info("Recording known bugs to " + fileName + " : ")
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
        self.currTestSelection[0].filesChanged()

class RecomputeTest(guiplugins.ActionGUI):
    def __init__(self, *args):
        guiplugins.ActionGUI.__init__(self, *args)
        self.recomputing = False
        self.chainReaction = False
    def singleTestOnly(self):
        return True
    def getState(self, state):
        if state:
            return state
        else:
            return self.currTestSelection[0].state
    def isActiveOnCurrent(self, test=None, state=None):
        if not guiplugins.ActionGUI.isActiveOnCurrent(self):
            return False
        
        useState = self.getState(state)
        return useState.hasStarted() and not useState.isComplete()
    def updateSelection(self, tests, apps, rowCount, *args):
        newActive = guiplugins.ActionGUI.updateSelection(self, tests, apps, rowCount, *args)
        # Prevent recomputation triggering more...
        if self.recomputing:
            self.chainReaction = True
            return newActive
        if rowCount == 1 and self.currTestSelection[0].needsRecalculation():
            self.recomputing = True
            self.currTestSelection[0].refreshFiles()
            self.perform()
            self.recomputing = False
            if self.chainReaction:
                self.chainReaction = False
        return newActive
    def inMenuOrToolBar(self):
        return False
    def _getTitle(self):
        return "_Update Info"
    def getTooltip(self):
        return "Update test progress information and compare test files so far"
    def messageBeforePerform(self):
        return "Recomputing status of " + self.describeTests() + " ..."
    def messageAfterPerform(self):
        pass
    def performOnCurrent(self):
        test = self.currTestSelection[0] # recomputing can change selection, make sure we talk about the right one...
        test.app.recomputeProgress(test, self.observers)
        self.notify("Status", "Done recomputing status of " + repr(test) + ".")

class RecomputeAllTests(guiplugins.ActionGUI):
    def __init__(self, allApps, *args):
        guiplugins.ActionGUI.__init__(self, allApps, *args)
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
    def getTooltip(self):
        return "recompute status of all tests"
    def performOnCurrent(self):
        self.latestNumberOfRecomputations = 0
        for test in self.currTestSelection:
            if test.needsRecalculation():
                self.latestNumberOfRecomputations += 1
                self.notify("Status", "Recomputing status of " + repr(test) + " ...")
                self.notify("ActionProgress", "")                
                test.app.recomputeProgress(test, self.observers)
 

class SortTestSuiteFileAscending(guiplugins.ActionGUI):
    def singleTestOnly(self):
        return True
    def correctTestClass(self):
        return "test-suite"
    def isActiveOnCurrent(self, *args):
        return guiplugins.ActionGUI.isActiveOnCurrent(self, *args) and not self.currTestSelection[0].autoSortOrder
    def _getStockId(self):
        return "sort-ascending"
    def _getTitle(self):
        return "_Sort Test Suite File"
    def messageAfterPerform(self):
        return "Sorted testsuite file for " + self.describeTests() + " in alphabetical order."
    def getTooltip(self):
        return "sort testsuite file for the selected test suite in alphabetical order"
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
        if self.hasNonDefaultTests():
            self.showWarningDialog("\nThe test suite\n'" + suite.name + "'\ncontains tests which are not present in the default version.\nTests which are only present in some versions will not be\nmixed with tests in the default version, which might lead to\nthe suite not looking entirely sorted.")

        suite.sortTests(ascending)
    def hasNonDefaultTests(self):
        if len(self.currTestSelection) == 1:
            return False

        for extraSuite in self.currTestSelection[1:]:
            for test in extraSuite.testcases:
                if not self.currTestSelection[0].findSubtest(test.name):
                    return True
        return False

class SortTestSuiteFileDescending(SortTestSuiteFileAscending):
    def _getStockId(self):
        return "sort-descending"
    def _getTitle(self):
        return "_Reversed Sort Test Suite File"
    def messageAfterPerform(self):
        return "Sorted testsuite file for " + self.describeTests() + " in reversed alphabetical order."
    def getTooltip(self):
        return "sort testsuite file for the selected test suite in reversed alphabetical order"
    def performOnCurrent(self):
        self.performRecursively(self.currTestSelection[0], False)

class RepositionTest(guiplugins.ActionGUI):
    def singleTestOnly(self):
        return True
    def _isActiveOnCurrent(self):
        return guiplugins.ActionGUI.isActiveOnCurrent(self) and \
               self.currTestSelection[0].parent and \
               not self.currTestSelection[0].parent.autoSortOrder
    def getSignalsSent(self):
        return [ "RefreshTestSelection" ]

    def performOnCurrent(self):
        newIndex = self.findNewIndex()
        if self.currTestSelection[0].parent.repositionTest(self.currTestSelection[0], newIndex):
            self.notify("RefreshTestSelection")
        else:
            raise plugins.TextTestError, "\nThe test\n'" + self.currTestSelection[0].name + "'\nis not present in the default version\nand hence cannot be reordered.\n"
    
class RepositionTestDown(RepositionTest):
    def _getStockId(self):
        return "go-down"
    def _getTitle(self):
        return "Move down"
    def messageAfterPerform(self):
        return "Moved " + self.describeTests() + " one step down in suite."
    def getTooltip(self):
        return "Move selected test down in suite"
    def findNewIndex(self):
        return min(self.currTestSelection[0].positionInParent() + 1, self.currTestSelection[0].parent.maxIndex())
    def isActiveOnCurrent(self, *args):
        if not self._isActiveOnCurrent():
            return False
        return self.currTestSelection[0].parent.testcases[self.currTestSelection[0].parent.maxIndex()] != self.currTestSelection[0]

class RepositionTestUp(RepositionTest):
    def _getStockId(self):
        return "go-up"
    def _getTitle(self):
        return "Move up"
    def messageAfterPerform(self):
        return "Moved " + self.describeTests() + " one step up in suite."
    def getTooltip(self):
        return "Move selected test up in suite"
    def findNewIndex(self):
        return max(self.currTestSelection[0].positionInParent() - 1, 0)
    def isActiveOnCurrent(self, *args):
        if not self._isActiveOnCurrent():
            return False
        return self.currTestSelection[0].parent.testcases[0] != self.currTestSelection[0]

class RepositionTestFirst(RepositionTest):
    def _getStockId(self):
        return "goto-top"
    def _getTitle(self):
        return "Move to first"
    def messageAfterPerform(self):
        return "Moved " + self.describeTests() + " to first in suite."
    def getTooltip(self):
        return "Move selected test to first in suite"
    def findNewIndex(self):
        return 0
    def isActiveOnCurrent(self, *args):
        if not self._isActiveOnCurrent():
            return False
        return self.currTestSelection[0].parent.testcases[0] != self.currTestSelection[0]

class RepositionTestLast(RepositionTest):
    def _getStockId(self):
        return "goto-bottom"
    def _getTitle(self):
        return "Move to last"
    def messageAfterPerform(self):
        return "Moved " + repr(self.currTestSelection[0]) + " to last in suite."
    def getTooltip(self):
        return "Move selected test to last in suite"
    def findNewIndex(self):
        return self.currTestSelection[0].parent.maxIndex()
    def isActiveOnCurrent(self, *args):
        if not self._isActiveOnCurrent():
            return False
        currLastTest = self.currTestSelection[0].parent.testcases[len(self.currTestSelection[0].parent.testcases) - 1]
        return currLastTest != self.currTestSelection[0]
    
class RenameTest(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("name", "\nNew name")
        self.addOption("desc", "\nNew description")
        self.oldName = ""
        self.oldDescription = ""
    def correctTestClass(self):
        return "test-case"
    def singleTestOnly(self):
        return True
    def updateOptions(self):
        self.oldName = self.currTestSelection[0].name
        self.oldDescription = plugins.extractComment(self.currTestSelection[0].description)
        self.optionGroup.setOptionValue("name", self.oldName)
        self.optionGroup.setOptionValue("desc", self.oldDescription)
        return True
    def fillVBox(self, vbox):
        header = gtk.Label()
        header.set_markup("<b>" + plugins.convertForMarkup(self.oldName) + "</b>")
        vbox.pack_start(header)
        return guiplugins.ActionDialogGUI.fillVBox(self, vbox)
    def _getStockId(self):
        return "italic"
    def _getTitle(self):
        return "_Rename..."
    def getTooltip(self):
        return "Rename selected test"
    def messageAfterPerform(self):
        newName = self.optionGroup.getOptionValue("name")
        newDesc = self.optionGroup.getOptionValue("desc")
        if self.oldName != newName:
            message = "Renamed test " + self.oldName + " to " + newName
            if self.oldDescription != newDesc:
                message += " and changed description."
            else:
                message += "."
        elif newDesc != self.oldDescription:
            message = "Changed description of test " + self.oldName + "."
        else:
            message = "Nothing changed."
        return message
    def checkNewName(self, newName):
        if len(newName) == 0:
            raise plugins.TextTestError, "Please enter a new name."
        if newName.find(" ") != -1:
            raise plugins.TextTestError, "The new name must not contain spaces, please choose another name."
        if newName != self.oldName:
            for test in self.currTestSelection[0].parent.testCaseList():
                if test.name == newName:
                    raise plugins.TextTestError, "The name '" + newName + "' is already taken, please choose another name."
            newDir = os.path.join(self.currTestSelection[0].parent.getDirectory(), newName)
            if os.path.isdir(newDir):
                raise plugins.TextTestError, "The directory " + newDir + " already exists, please choose another name."
    def performOnCurrent(self):
        try:
            newName = self.optionGroup.getOptionValue("name")
            self.checkNewName(newName)
            newDesc = self.optionGroup.getOptionValue("desc")
            if newName != self.oldName or newDesc != self.oldDescription:
                for test in self.currTestSelection:
                    test.rename(newName, newDesc)
        except IOError, e:
            self.showErrorDialog("Failed to rename test:\n" + str(e))
        except OSError, e:
            self.showErrorDialog("Failed to rename test:\n" + str(e))
        
 
class ShowFileProperties(guiplugins.ActionResultDialogGUI):
    def __init__(self, allApps, dynamic):
        self.dynamic = dynamic
        guiplugins.ActionGUI.__init__(self, allApps)
    def _getStockId(self):
        return "properties"
    def isActiveOnCurrent(self, *args):
        return ((not self.dynamic) or len(self.currTestSelection) == 1) and \
               len(self.currFileSelection) > 0
    def _getTitle(self):
        return "_File Properties"
    def getTooltip(self):
        return "Show properties of selected files"
    def describeTests(self):
        return str(len(self.currFileSelection)) + " files"
    def getAllProperties(self):
        errors, properties = [], []
        for file, comp in self.currFileSelection:
            if self.dynamic and comp:
                self.processFile(comp.tmpFile, properties, errors)
            self.processFile(file, properties, errors)
            
        if len(errors):
            self.showErrorDialog("Failed to get file properties:\n" + "\n".join(errors))

        return properties
    def processFile(self, file, properties, errors):
        try:
            prop = plugins.FileProperties(file)
            guiplugins.guilog.info("Showing properties of the file " + file + ":\n" + prop.getUnixStringRepresentation())
            properties.append(prop)
        except Exception, e:
            errors.append(str(e))          

    # xalign = 1.0 means right aligned, 0.0 means left aligned
    def justify(self, text, xalign = 0.0):
        alignment = gtk.Alignment()
        alignment.set(xalign, 0.0, 0.0, 0.0)
        label = gtk.Label(text)
        alignment.add(label)
        return alignment

    def addContents(self):
        dirToProperties = {}
        for prop in self.getAllProperties():
            dirToProperties.setdefault(prop.dir, []).append(prop)

        vbox = self.createVBox(dirToProperties)
        self.dialog.vbox.pack_start(vbox, expand=True, fill=True)              

    def createVBox(self, dirToProperties):
        vbox = gtk.VBox()
        for dir, properties in dirToProperties.items():
            expander = gtk.Expander()
            expander.set_label_widget(self.justify(dir))
            table = gtk.Table(len(properties), 7)
            table.set_col_spacings(5)
            row = 0
            for prop in properties:
                values = prop.getUnixRepresentation()
                table.attach(self.justify(values[0] + values[1], 1.0), 0, 1, row, row + 1)
                table.attach(self.justify(values[2], 1.0), 1, 2, row, row + 1)
                table.attach(self.justify(values[3], 0.0), 2, 3, row, row + 1)
                table.attach(self.justify(values[4], 0.0), 3, 4, row, row + 1)
                table.attach(self.justify(values[5], 1.0), 4, 5, row, row + 1)
                table.attach(self.justify(values[6], 1.0), 5, 6, row, row + 1)
                table.attach(self.justify(prop.filename, 0.0), 6, 7, row, row + 1)
                row += 1
            hbox = gtk.HBox()
            hbox.pack_start(table, expand=False, fill=False)
            innerBorder = gtk.Alignment()
            innerBorder.set_padding(5, 0, 0, 0)
            innerBorder.add(hbox)
            expander.add(innerBorder)
            expander.set_expanded(True)
            border = gtk.Alignment()
            border.set_padding(5, 5, 5, 5)
            border.add(expander)
            vbox.pack_start(border, expand=False, fill=False)
        return vbox

    
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
                         RunTestsBasic, RunTestsAdvanced, ResetGroups, RenameTest, RemoveTests, 
                         SortTestSuiteFileAscending, SortTestSuiteFileDescending, 
                         RepositionTestFirst, RepositionTestUp,
                         RepositionTestDown, RepositionTestLast,
                         ReconnectToTests, LoadSelection, SaveSelection ]
        classes += [ helpdialogs.ShowMigrationNotes, helpdialogs.ShowVersions, helpdialogs.AboutTextTest ]
        return classes

    def getReplacements(self):
        # Return a dictionary mapping classes above to what to replace them with
        return {}
