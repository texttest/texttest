
"""
The various classes that launch external programs to view files
"""

import gtk, plugins, os
from default.gtkgui import guiplugins # from .. import guiplugins when we drop Python 2.4 support
from ndict import seqdict
from string import Template

class FileViewAction(guiplugins.ActionGUI):
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

    def getConfirmationMessage(self):
        maxFileSize = self.getMaxFileSize()
        if maxFileSize >= 0:
            largestFileSize = self.getLargestFileSize()
            
        return ""

    def getLargestFileSize(self, f, *args):
        return os.path.getsize(f)            

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
            self.showErrorDialog("Cannot find " + self.getToolDescription() + " '" + viewTool + \
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
                                  str(maxFileSize) + " bytes is set for the tool '" + viewTool + "'. Are you sure you wish to continue?"
                        return message, args
                    
                return "", args
            else:
                raise plugins.TextTestError, "No " + self.getToolDescription() + " is defined for files of type '" + \
                      os.path.basename(fileToView).split(".")[0] + \
                      "'.\nPlease point the configuration entry '" + self.getToolConfigEntry() + \
                      "' at a valid program to view the file."
        else:
            raise plugins.TextTestError, "File '" + os.path.basename(fileName) + \
                      "' cannot be viewed as it has been removed in the file system." + self.noFileAdvice()

    def isDefaultViewer(self, *args):
        return False
    
    def extraPostfix(self):
        return ""

    def notifyViewFile(self, fileName, *args):
        if self.isDefaultViewer(*args):
            allArgs = (fileName,) + args
            self.currFileSelection = [ allArgs ]
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
        if os.name == "posix" and len(self.currTestSelection) > 0:
            state = self.currTestSelection[0].stateInGui
            if hasattr(state, "executionHosts") and len(state.executionHosts) > 0:
                remoteHost = state.executionHosts[0]
                localhost = plugins.gethostname()
                if remoteHost != localhost:
                    return remoteHost

    def getFullDisplay(self):
        display = os.getenv("DISPLAY", "")
        if display.startswith(":"):
            return plugins.gethostname() + display
        else:
            return display.replace("localhost", plugins.gethostname())

    def getSignalsSent(self):
        return [ "ViewerStarted" ]

    def startViewer(self, cmdArgs, description, *args, **kwargs):
        testDesc = self.testDescription()
        fullDesc = description + testDesc
        nullFile = open(os.devnull, "w")
        self.notify("Status", 'Started "' + description + '" in background' + testDesc + '.')
        guiplugins.processMonitor.startProcess(cmdArgs, fullDesc, stdout=nullFile, stderr=nullFile, *args, **kwargs)
        self.notifyThreaded("ViewerStarted") # Don't call application events directly in the GUI thread

    def getStem(self, fileName):
        return os.path.basename(fileName).split(".")[0]

    def testRunning(self):
        return self.currTestSelection[0].stateInGui.hasStarted() and \
               not self.currTestSelection[0].stateInGui.isComplete()

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
        pass # provided by starting viewer, with message


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
        refresh = str(exitHandler != self.editingComplete)
        guiplugins.guilog.info("Viewing file " + fileName + " using '" + descriptor + "', refresh set to " + refresh)
        self.startViewer(cmdArgs, description=description, env=env,
                         exitHandler=exitHandler, exitHandlerArgs=exitHandlerArgs)
        
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

        if guiplugins.guiConfig.getCompositeValue("view_file_on_remote_machine", self.getStem(fileName)):
            remoteHost = self.getRemoteHost()
            if remoteHost:
                remoteShellProgram = guiplugins.guiConfig.getValue("remote_shell_program")
                cmdArgs = [ remoteShellProgram, remoteHost, "env DISPLAY=" + self.getFullDisplay() + " " + " ".join(cmdArgs) ]

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
        return False # only way to get at it is via the activation below...

    def notifyViewApplicationFile(self, fileName, apps):
        self.currFileSelection = [ (fileName, apps) ]
        self.runInteractive()

    def findExitHandlerInfo(self, fileName, apps):
        return self.configFileChanged, (apps,)

    def configFileChanged(self, apps):
        for app in apps:
            app.setUpConfiguration()
            suite = self.findSuite(app)
            self.refreshFilesRecursively(suite)

        self.editingComplete()

    def findSuite(self, app):
        for suite in self.rootTestSuites:
            if suite.app is app:
                return suite

    def refreshFilesRecursively(self, suite):
        suite.filesChanged()
        if suite.classId() == "test-suite":
            for subTest in suite.testcases:
                self.refreshFilesRecursively(subTest)


class ViewTestFileInEditor(ViewInEditor):
    def _getTitle(self):
        return "View File"

    def isDefaultViewer(self, comparison):
        return not self.differencesActive(comparison) and \
               (not self.testRunning() or not guiplugins.guiConfig.getValue("follow_file_by_default"))

    def findExitHandlerInfo(self, fileName, *args):
        if self.dynamic:
            return self.editingComplete, ()

        # options file can change appearance of test (environment refs etc.)
        baseName = os.path.basename(fileName)
        if baseName.startswith("options"):
            tests = self.getTestsForFile("options", fileName)
            if len(tests) > 0:
                return self.handleOptionsEdit, (tests,)
        elif baseName.startswith("testsuite"):
            tests = self.getTestsForFile("testsuite", fileName)
            if len(tests) > 0:
                # refresh tests if this edited
                return self.handleTestSuiteEdit, (tests,)

        return self.editingComplete, ()

    def getTestsForFile(self, stem, fileName):
        tests = []
        for test in self.currTestSelection:
            defFile = test.getFileName(stem)
            if defFile and plugins.samefile(fileName, defFile):
                tests.append(test)
        return tests

    def handleTestSuiteEdit(self, suites):
        for suite in suites:
            suite.refresh(suite.app.getFilterList(suites))
        self.editingComplete()

    def handleOptionsEdit(self, tests):
        for test in tests:
            test.filesChanged()
        self.editingComplete()


class ViewFilteredTestFileInEditor(ViewTestFileInEditor):
    def _getStockId(self):
        pass # don't use same stock for both
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
        description = diffProgram + " " + os.path.basename(stdFile) + " " + os.path.basename(tmpFile)
        guiplugins.guilog.info("Starting graphical difference comparison using '" + diffProgram + "':")
        guiplugins.guilog.info("-- original file : " + stdFile)
        guiplugins.guilog.info("--  current file : " + tmpFile)
        cmdArgs = plugins.splitcmd(diffProgram) + [ stdFile, tmpFile ]
        self.startViewer(cmdArgs, description=description, exitHandler=self.diffingComplete)

    def diffingComplete(self, *args):
        self.applicationEvent("the graphical diff program to terminate")


class ViewFilteredFileDifferences(ViewFileDifferences):
    def _getTitle(self):
        return "View Differences"

    def useFiltered(self):
        return True

    def isActiveForFile(self, fileName, comparison):
        return self.differencesActive(comparison)

    def isDefaultViewer(self, comparison):
        return self.differencesActive(comparison)

class ViewContentFilteredFileDifferences(ContentFilterViewer, ViewFilteredFileDifferences):
    def _getTitle(self):
        return "View Content-Filtered Differences"

    def isActiveForFile(self, fileName, comparison):
        return ViewFileDifferences.isActiveForFile(self, fileName, comparison) and self.unorderedFiltersActive(comparison)

    def isDefaultViewer(self, comparison):
        return False


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

    def isDefaultViewer(self, comparison):
        return not self.differencesActive(comparison) and self.testRunning() and \
               guiplugins.guiConfig.getValue("follow_file_by_default")

    def getFollowProgram(self, followProgram, fileName):
        title = '"' + self.currTestSelection[0].name + " (" + os.path.basename(fileName) + ')"'
        envDir = { "TEXTTEST_FOLLOW_FILE_TITLE" : title } # Title of the window when following file progress
        return Template(followProgram).safe_substitute(envDir)

    def getFollowCommand(self, program, fileName):
        remoteHost = self.getRemoteHost()
        if remoteHost:
            remoteShellProgram = guiplugins.guiConfig.getValue("remote_shell_program")
            return [ remoteShellProgram, remoteHost, "env DISPLAY=" + self.getFullDisplay() + " " + \
                     program + " " + fileName ]
        else:
            return plugins.splitcmd(program) + [ fileName ]

    def _performOnFile(self, followProgram, fileName, comparison):
        useFile = self.fileToFollow(fileName, comparison)
        useProgram = self.getFollowProgram(followProgram, fileName)
        guiplugins.guilog.info("Following file " + useFile + " using '" + useProgram + "'")
        description = useProgram + " " + os.path.basename(useFile)
        cmdArgs = self.getFollowCommand(useProgram, useFile)
        self.startViewer(cmdArgs, description=description, exitHandler=self.followComplete)

    def followComplete(self, *args):
        self.applicationEvent("the file-following program to terminate")


class ShowFileProperties(guiplugins.ActionResultDialogGUI):
    def __init__(self, allApps, dynamic, *args):
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
                self.processFile(comp.stdFile, properties, errors)
            else:
                self.processFile(file, properties, errors)

        if len(errors):
            self.showErrorDialog("Failed to get file properties:\n" + "\n".join(errors))

        return properties
    def processFile(self, file, properties, errors):
        if file:
            try:
                prop = plugins.FileProperties(file)
                properties.append(prop)
            except Exception, e:
                errors.append(plugins.getExceptionString())

    # xalign = 1.0 means right aligned, 0.0 means left aligned
    def justify(self, text, xalign = 0.0):
        alignment = gtk.Alignment()
        alignment.set(xalign, 0.0, 0.0, 0.0)
        label = gtk.Label(text)
        alignment.add(label)
        return alignment

    def addContents(self):
        dirToProperties = seqdict()
        props = self.getAllProperties()
        for prop in props:
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


def getInteractiveActionClasses(dynamic):
    classes = [ ShowFileProperties, ViewTestFileInEditor ]
    if dynamic:
        classes += [ ViewFilteredTestFileInEditor, ViewContentFilteredTestFileInEditor,
                     ViewOrigFileInEditor, ViewContentFilteredOrigFileInEditor, ViewFilteredOrigFileInEditor,
                     ViewFileDifferences, ViewContentFilteredFileDifferences, ViewFilteredFileDifferences,
                     FollowFile ]
    else:
        classes.append(ViewConfigFileInEditor)

    return classes
