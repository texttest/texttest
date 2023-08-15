
"""
The various classes that launch external programs to view files
"""

import os
from texttestlib import plugins
from .. import guiplugins
from string import Template
from copy import copy
from tempfile import mkstemp
import subprocess


class FileViewAction(guiplugins.ActionGUI):
    def __init__(self, *args, **kw):
        self.performArgs = []
        guiplugins.ActionGUI.__init__(self, *args, **kw)

    def singleTestOnly(self):
        return True

    def isActiveOnCurrent(self, *args):
        if not guiplugins.ActionGUI.isActiveOnCurrent(self):
            return False
        for fileName, obj in self.currFileSelection:
            if self.isActiveForFile(fileName, obj):
                return True
        return False

    def isActiveForFile(self, fileName, *args):
        return fileName and not os.path.isdir(fileName)

    def useFiltered(self):
        return False

    def getLargestFileSize(self, f, *args):
        try:
            return os.path.getsize(f)
        except EnvironmentError:
            return 0

    def getConfirmationMessage(self):
        self.performArgs = []
        message = ""
        for fileName, associatedObject in self.currFileSelection:
            if self.isActiveForFile(fileName, associatedObject):
                message, args = self.getConfMessageForFile(fileName, associatedObject)
                self.performArgs.append(args)
        return message

    def performOnCurrent(self):
        for args in self.performArgs:
            self.performOnFile(*args)

    def performOnFile(self, viewTool, *args):
        try:
            self._performOnFile(viewTool, *args)
        except OSError:
            self.showErrorDialog("Cannot find " + self.getToolDescription() + " '" + viewTool +
                                 "'.\nPlease install it somewhere on your PATH or\n"
                                 "change the configuration entry '" + self.getToolConfigEntry() + "'.")

    def getConfMessageForFile(self, fileName, associatedObject):
        fileToView = self.getFileToView(fileName, associatedObject)
        if os.path.isfile(fileToView) or os.path.islink(fileToView):
            viewTool = self.getViewToolName(fileToView)
            if viewTool:
                args = (viewTool, fileToView, associatedObject)
                maxFileSize = plugins.parseBytes(self.getConfigValue("max_file_size", viewTool))
                if maxFileSize >= 0:
                    largestFileSize = self.getLargestFileSize(fileToView, associatedObject)
                    if largestFileSize > maxFileSize:
                        message = "You are trying to view a file of size " + str(largestFileSize) + " bytes, while a limit of " + \
                                  str(maxFileSize) + " bytes is set for the tool '" + \
                            viewTool + "'. Are you sure you wish to continue?"
                        return message, args

                return "", args
            else:
                raise plugins.TextTestError("No " + self.getToolDescription() + " is defined for files of type '" +
                                            os.path.basename(fileToView).split(".")[0] +
                                            "'.\nPlease point the configuration entry '" + self.getToolConfigEntry() +
                                            "' at a valid program to view the file.")
        else:
            raise plugins.TextTestError("File '" + os.path.basename(fileName) +
                                        "' cannot be viewed as it has been removed in the file system." + self.noFileAdvice())

    def isDefaultViewer(self, *args):
        return False

    def extraPostfix(self):
        return ""

    def notifyViewFile(self, fileName, comp, newFile):
        if self.isDefaultViewer(comp, newFile):
            allArgs = (fileName, comp)
            self.currFileSelection = [allArgs]
            self.runInteractive()

    def getFileToView(self, fileName, associatedObject):
        try:
            # associatedObject might be a comparison object, but it might not
            # Use the comparison if it's there
            return associatedObject.existingFile(self.useFiltered(), self.extraPostfix())
        except AttributeError:
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

    def getRemoteHost(self):
        if len(self.currTestSelection) > 0:
            state = self.currTestSelection[0].stateInGui
            if hasattr(state, "executionHosts") and len(state.executionHosts) > 0:
                return plugins.interpretHostname(state.executionHosts[0])
        return "localhost"

    def getRemoteArgs(self, cmdArgs):
        remoteHost = self.getRemoteHost()
        return self.currTestSelection[0].app.getCommandArgsOn(remoteHost, cmdArgs, graphical=True)

    def getSignalsSent(self):
        return ["ViewerStarted"]

    def startViewer(self, cmdArgs, description, checkOutput=False, **kwargs):
        testDesc = self.testDescription()
        fullDesc = description + testDesc
        nullFile = open(os.devnull, "w")
        stdout = subprocess.PIPE if checkOutput else nullFile
        self.notify("Status", 'Started "' + description + '" in background' + testDesc + '.')
        guiplugins.processMonitor.startProcess(cmdArgs, fullDesc, stdout=stdout, stderr=nullFile, **kwargs)
        self.notifyThreaded("ViewerStarted")  # Don't call application events directly in the GUI thread

    def getStem(self, fileName):
        return os.path.basename(fileName).split(".")[0]

    def testRunning(self):
        if len(self.currTestSelection) > 0:
            return self.currTestSelection[0].stateInGui.hasStarted() and \
                not self.currTestSelection[0].stateInGui.isComplete()
        else:
            return False

    def getViewToolName(self, fileName):
        stem = self.getStem(fileName)
        return self.getConfigValue(self.getToolConfigEntry(), stem)

    def getConfigValue(self, *args):
        if len(self.currTestSelection) > 0:
            return self.currTestSelection[0].getCompositeConfigValue(*args)
        else:
            return guiplugins.guiConfig.getCompositeValue(*args)

    def differencesActive(self, comparison):
        if not comparison or comparison.newResult() or comparison.missingResult():
            return False
        return comparison.hasDifferences()

    def messageAfterPerform(self):
        pass  # provided by starting viewer, with message


class ViewInEditor(FileViewAction):
    def __init__(self, allApps, dynamic, *args):
        FileViewAction.__init__(self, allApps)
        self.dynamic = dynamic

    def _getStockId(self):
        return "open"

    def getToolConfigEntry(self):
        return "view_program"

    def getToolDescription(self):
        return "file viewing program"

    def viewFile(self, fileName, viewTool, exitHandler, exitHandlerArgs):
        cmdArgs, descriptor, env = self.getViewCommand(fileName, viewTool)
        description = descriptor + " " + os.path.basename(fileName)
        checkOutput = cmdArgs[0] == "storytext_editor"
        self.startViewer(cmdArgs, description=description, checkOutput=checkOutput, env=env,
                         exitHandler=exitHandler, exitHandlerArgs=exitHandlerArgs)

    def getViewerEnvironment(self, cmdArgs):
        # An absolute path to the viewer may indicate a custom tool, send the test environment along too
        # Doing this is unlikely to cause harm in any case
        if len(self.currTestSelection) > 0:
            if cmdArgs[0] == "storytext_editor":
                storytextHome = self.currTestSelection[0].getEnvironment("STORYTEXT_HOME")
                return plugins.copyEnvironment({"STORYTEXT_HOME": storytextHome}, ignoreVars=["USECASE_RECORD_SCRIPT", "USECASE_REPLAY_SCRIPT"])
            elif os.path.isabs(cmdArgs[0]):
                return self.currTestSelection[0].getRunEnvironment()

    def getViewCommand(self, fileName, viewProgram):
        # viewProgram might have arguments baked into it...
        cmdArgs = plugins.splitcmd(viewProgram) + [fileName]
        program = cmdArgs[0]
        descriptor = " ".join([os.path.basename(program)] + cmdArgs[1:-1])
        env = self.getViewerEnvironment(cmdArgs)
        interpreter = plugins.getInterpreter(program)
        if interpreter:
            cmdArgs = plugins.splitcmd(interpreter) + cmdArgs

        if guiplugins.guiConfig.getCompositeValue("view_file_on_remote_machine", self.getStem(fileName)):
            cmdArgs = self.getRemoteArgs(cmdArgs)

        return cmdArgs, descriptor, env

    def _performOnFile(self, viewTool, fileName, *args):
        exitHandler, exitHandlerArgs = self.findExitHandlerInfo(fileName, *args)
        return self.viewFile(fileName, viewTool, exitHandler, exitHandlerArgs)

    def editingComplete(self):
        self.applicationEvent("file editing operations to complete")


class ViewConfigFileInEditor(ViewInEditor):
    def __init__(self, *args):
        ViewInEditor.__init__(self, *args)
        self.rootTestSuites = []

    def _getTitle(self):
        return "View In Editor"

    def addSuites(self, suites):
        self.rootTestSuites += suites

    def isActiveOnCurrent(self, *args):
        return len(self.currFileSelection) > 0

    def notifyViewApplicationFile(self, fileName, apps, *args):
        self.currFileSelection = [(fileName, apps)]
        self.runInteractive()

    def notifyViewReadonlyFile(self, fileName):
        viewTool = self.getConfigValue("view_program", "default")
        return self.viewFile(fileName, viewTool, self.applicationEvent, ("the readonly file viewer to be closed",))

    def findExitHandlerInfo(self, dummy, apps):
        return self.configFileChanged, (apps,)

    def getSignalsSent(self):
        return ["ReloadConfig"]

    def configFileChanged(self, apps):
        for app in apps:
            app.setUpConfiguration()
            suite = self.findSuite(app)
            suite.refreshFilesRecursively()

        # May have affected e.g. imported files, script references etc
        self.notify("ReloadConfig")
        self.editingComplete()

    def findSuite(self, app):
        for suite in self.rootTestSuites:
            if suite.app is app:
                return suite


class ViewTestFileInEditor(ViewInEditor):
    def _getTitle(self):
        return "View File"

    def isDefaultViewer(self, comparison, isNewFile):
        return not isNewFile and not self.differencesActive(comparison) and \
            (not self.testRunning() or not guiplugins.guiConfig.getValue("follow_file_by_default"))

    def findExitHandlerInfo(self, fileName, *args):
        if self.dynamic:
            return self.editingComplete, ()

        # options file can change appearance of test (environment refs etc.)
        baseName = os.path.basename(fileName)
        for stem in ["options", "testsuite", "config"]:
            if baseName.startswith(stem):
                tests = self.getTestsForFile(stem, fileName)
                if len(tests) > 0:
                    methodName = "handle" + stem.capitalize() + "Edit"
                    return getattr(self, methodName), (tests,)
        return self.staticGUIEditingComplete, (copy(self.currTestSelection), fileName)

    def getTestsForFile(self, stem, fileName):
        tests = []
        for test in self.currTestSelection:
            defFile = test.getFileName(stem)
            if defFile and plugins.samefile(fileName, defFile):
                tests.append(test)
        return tests

    def handleTestsuiteEdit(self, suites):
        for suite in suites:
            suite.refresh(suite.app.getFilterList(suites))
        self.editingComplete()

    def handleOptionsEdit(self, tests):
        for test in tests:
            test.filesChanged()
        self.editingComplete()

    def handleConfigEdit(self, tests):
        for test in tests:
            test.reloadTestConfigurations()
        self.editingComplete()

    def getSignalsSent(self):
        return ["RefreshFilePreviews"] + ViewInEditor.getSignalsSent(self)

    def staticGUIEditingComplete(self, tests, fileName):
        for test in tests:
            self.notify("RefreshFilePreviews", test, fileName)
        self.editingComplete()


class EditTestFileInEditor(ViewTestFileInEditor):
    def _getTitle(self):
        return "Edit File"

    def getViewToolName(self, *args):
        return self.getConfigValue(self.getToolConfigEntry(), "default")

    def isDefaultViewer(self, comp, isNewFile):
        return isNewFile

    def _getStockId(self):
        pass  # don't use same stock for both


class ViewFilteredTestFileInEditor(ViewTestFileInEditor):
    def _getStockId(self):
        pass  # don't use same stock for both

    def useFiltered(self):
        return True

    def _getTitle(self):
        return "View Filtered File"

    def isActiveForFile(self, fileName, comparison):
        return bool(comparison)

    def isDefaultViewer(self, *args):
        return False


class ContentFilterViewer:
    def extraPostfix(self):
        return ".normal"

    def unorderedFiltersActive(self, comparison):
        return len(self.currAppSelection[0].getCompositeConfigValue("unordered_text", comparison.stem)) > 0


class ViewContentFilteredTestFileInEditor(ContentFilterViewer, ViewFilteredTestFileInEditor):
    def _getTitle(self):
        return "View Content-Filtered File"

    def isActiveForFile(self, fileName, comparison):
        return ViewFilteredTestFileInEditor.isActiveForFile(self, fileName, comparison) and \
            self.unorderedFiltersActive(comparison)


class ViewFilteredOrigFileInEditor(ViewFilteredTestFileInEditor):
    def _getTitle(self):
        return "View Filtered Original File"

    def isActiveForFile(self, fileName, comparison):
        return comparison and not comparison.newResult()

    def getFileToView(self, fileName, comparison):
        return comparison.getStdFile(self.useFiltered(), self.extraPostfix())


class ViewOrigFileInEditor(ViewFilteredOrigFileInEditor):
    def _getTitle(self):
        return "View Original File"

    def useFiltered(self):
        return False


class EditOrigFileInEditor(ViewOrigFileInEditor):
    def _getTitle(self):
        return "Edit Original File"

    def getViewToolName(self, *args):
        return self.getConfigValue(self.getToolConfigEntry(), "default")


class ViewContentFilteredOrigFileInEditor(ContentFilterViewer, ViewFilteredOrigFileInEditor):
    def _getTitle(self):
        return "View Content-Filtered Original File"

    def isActiveForFile(self, fileName, comparison):
        return ViewFilteredOrigFileInEditor.isActiveForFile(self, fileName, comparison) and \
            self.unorderedFiltersActive(comparison)


class ViewFileDifferences(FileViewAction):
    def _getTitle(self):
        return "View Raw Differences"

    def getToolConfigEntry(self):
        return "diff_program"

    def getToolDescription(self):
        return "graphical difference program"

    def isActiveForFile(self, fileName, comparison):
        if bool(comparison):
            if not (comparison.newResult() or comparison.missingResult()):
                return True
        return False

    def getLargestFileSize(self, tmpFile, comparison):
        stdFile = comparison.getStdFile(self.useFiltered(), self.extraPostfix())
        return max(os.path.getsize(stdFile), os.path.getsize(tmpFile))

    def _performOnFile(self, diffProgram, tmpFile, comparison):
        stdFile = comparison.getStdFile(self.useFiltered(), self.extraPostfix())
        self.runDiff(diffProgram, stdFile, tmpFile)

    def runDiff(self, diffProgram, stdFile, tmpFile):
        description = diffProgram + " " + os.path.basename(stdFile) + " " + os.path.basename(tmpFile)
        cmdArgs = plugins.splitcmd(diffProgram) + [stdFile, tmpFile]
        self.startViewer(cmdArgs, description=description, exitHandler=self.diffingComplete)

    def diffingComplete(self, *args):
        self.applicationEvent("the " + self.getToolDescription() + " to terminate")


class PairwiseFileViewer:
    def singleTestOnly(self):
        return False

    def isActiveOnCurrent(self, *args):
        return len(self.currTestSelection) == 2 and len(self.currFileSelection) == 1 and \
            FileViewAction.isActiveOnCurrent(self, *args)

    def isActiveForFile(self, fileName, comparison):
        if bool(comparison) and not comparison.missingResult():
            otherComp = self.findOtherComparison(comparison)
            if otherComp and not otherComp.missingResult():
                return True
        return False

    def findOtherComparison(self, comparison):
        state = self.currTestSelection[-1].stateInGui
        return state.findComparison(comparison.stem, includeSuccess=True)[0] if hasattr(state, "findComparison") else None

    def _performOnFile(self, diffProgram, tmpFile, comparison):
        otherComp = self.findOtherComparison(comparison)
        file1 = comparison.getTmpFile(self.useFiltered(), self.extraPostfix())
        file2 = otherComp.getTmpFile(self.useFiltered(), self.extraPostfix())
        self.runDiff(diffProgram, file1, file2)


class ViewPairwiseDifferences(PairwiseFileViewer, ViewFileDifferences):
    def _getTitle(self):
        return "View Raw Differences (between tests)"


class ViewFilteredFileDifferences(ViewFileDifferences):
    def _getTitle(self):
        return "View Differences"

    def useFiltered(self):
        return True

    def isActiveForFile(self, fileName, comparison):
        return self.differencesActive(comparison)

    def isDefaultViewer(self, comparison, *args):
        return self.differencesActive(comparison)


class ViewFilteredPairwiseDifferences(PairwiseFileViewer, ViewFilteredFileDifferences):
    def _getTitle(self):
        return "View Differences (between tests)"

    def useFiltered(self):
        return True

    def isDefaultViewer(self, comparison, *args):
        return False


class ViewContentFilteredFileDifferences(ContentFilterViewer, ViewFilteredFileDifferences):
    def _getTitle(self):
        return "View Content-Filtered Differences"

    def isActiveForFile(self, fileName, comparison):
        return ViewFileDifferences.isActiveForFile(self, fileName, comparison) and self.unorderedFiltersActive(comparison)

    def isDefaultViewer(self, comparison, *args):
        return False


class ViewContentFilteredPairwiseDifferences(PairwiseFileViewer, ViewContentFilteredFileDifferences):
    def _getTitle(self):
        return "View Content-Filtered Differences (between tests)"


class FollowFile(FileViewAction):
    def _getTitle(self):
        return "Follow File Progress"

    def getToolConfigEntry(self):
        return "follow_program"

    def getToolDescription(self):
        return "file-following program"

    def isActiveForFile(self, *args):
        return self.testRunning()

    def fileToFollow(self, fileName, comparison):
        if comparison:
            return comparison.tmpFile
        else:
            return fileName

    def isDefaultViewer(self, comparison, *args):
        return not self.differencesActive(comparison) and self.testRunning() and \
            guiplugins.guiConfig.getValue("follow_file_by_default")

    def getFollowProgram(self, followProgram, fileName):
        title = '"File ' + os.path.basename(fileName) + " from test " + self.currTestSelection[0].name + '"'
        envDir = {"TEXTTEST_FOLLOW_FILE_TITLE": title}  # Title of the window when following file progress
        return Template(followProgram).safe_substitute(envDir)

    def getFollowCommand(self, program, fileName):
        localArgs = plugins.splitcmd(program) + [fileName]
        return self.getRemoteArgs(localArgs)

    def _performOnFile(self, followProgram, fileName, comparison):
        useFile = self.fileToFollow(fileName, comparison)
        useProgram = self.getFollowProgram(followProgram, fileName)
        program = useProgram.split()[0]
        description = useProgram + " " + os.path.basename(useFile)
        cmdArgs = self.getFollowCommand(useProgram, useFile)
        if self.canRunCommand(program):
            self.startViewer(cmdArgs, description=description, exitHandler=self.followComplete)
        else:
            self.showErrorDialog("Couldn't find " + program + " to run the " + self.getToolDescription())

    def followComplete(self, *args):
        self.applicationEvent("the " + self.getToolDescription() + " to terminate")

    def canRunCommand(self, cmd):
        if len(self.currTestSelection) > 0:
            app = self.currTestSelection[0].app
        if self.getRemoteHost() != "localhost":
            retcode = app.runCommandOn(self.getRemoteHost(), ["which", cmd], collectExitCode=True)
            return retcode == 0
        else:
            return True


class EditTestDescription(EditTestFileInEditor):
    def _getTitle(self):
        return "Edit Description"

    def isActiveOnCurrent(self, *args):
        if not guiplugins.ActionGUI.isActiveOnCurrent(self):
            return False
        return len(self.currTestSelection) == 1

    def performOnCurrent(self):
        test = self.currTestSelection[0]
        fileName = self.createTmpFile(test.description)
        _, args = self.getConfMessageForFile(fileName, test)
        self.performOnFile(*args)

    def createTmpFile(self, text):
        tmpFile, fileName = mkstemp(text=True)
        os.write(tmpFile, text.encode())
        os.close(tmpFile)
        return fileName

    def findExitHandlerInfo(self, fileName, test):
        return self.updateDescription, (fileName, test)

    def updateDescription(self, fileName, test):
        text = self.getEditedText(fileName)
        test.rename(test.name, text)
        if os.path.exists(fileName):
            os.remove(fileName)
        self.editingComplete()

    def getEditedText(self, fileName):
        text = ""
        with open(fileName, "r", encoding="utf8") as f:
            for line in f:
                text += line
        return text

    def isDefaultViewer(self, *args):
        return False


def getInteractiveActionClasses(dynamic):
    classes = [ViewTestFileInEditor, EditTestFileInEditor]
    if dynamic:
        classes += [ViewFilteredTestFileInEditor, ViewContentFilteredTestFileInEditor,
                    ViewOrigFileInEditor, EditOrigFileInEditor, ViewContentFilteredOrigFileInEditor, ViewFilteredOrigFileInEditor,
                    ViewFileDifferences, ViewContentFilteredFileDifferences, ViewFilteredFileDifferences,
                    ViewPairwiseDifferences, ViewContentFilteredPairwiseDifferences, ViewFilteredPairwiseDifferences,
                    FollowFile]
    else:
        classes.append(ViewConfigFileInEditor)
        classes.append(EditTestDescription)

    return classes
