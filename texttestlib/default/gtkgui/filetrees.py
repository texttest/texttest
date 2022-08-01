
"""
Module to handle the various file-trees in the GUI
"""
from gi.repository import Gtk, GObject
from . import guiutils
import os
import sys
import operator
import logging
import string
from texttestlib import plugins
from collections import OrderedDict
from copy import copy
from functools import reduce


class FileViewGUI(guiutils.SubGUI):
    inheritedText = "(Inherited from parent suites)"

    def __init__(self, dynamic, title="", popupGUI=None):
        guiutils.SubGUI.__init__(self)
        self.model = Gtk.TreeStore(GObject.TYPE_STRING, GObject.TYPE_STRING, GObject.TYPE_STRING,
                                   GObject.TYPE_PYOBJECT, GObject.TYPE_STRING, GObject.TYPE_STRING)
        self.popupGUI = popupGUI
        self.dynamic = dynamic
        self.title = title
        self.selection = None
        self.nameColumn = None
        self.diag = logging.getLogger("File View GUI")

    def recreateModel(self, state, preserveSelection):
        if not self.nameColumn:
            return
        # In theory we could do something clever here, but for now, just wipe and restart
        # Need to re-expand and re-select after clearing...
        if preserveSelection:
            selectionStore = self.storeSelection()
            self.diag.info("Storing " + repr(selectionStore))

        self.model.clear()
        self.addFilesToModel(state)
        view = self.selection.get_tree_view()
        if view:  # Might already be taking down the GUI
            view.expand_all()
        if preserveSelection:
            self.reselect(selectionStore)

    def storeSelection(self):
        selectionStore = []
        self.selection.selected_foreach(self.storeIter, selectionStore)
        return selectionStore

    def storeIter(self, dummyModel, dummyPath, iter, selectionStore):
        selectionStore.append(self._storeIter(iter))

    def _storeIter(self, iter):
        if iter is not None:
            parentStore = self._storeIter(self.model.iter_parent(iter))
            parentStore.append(self.model.get_value(iter, 0))
            return parentStore
        else:
            return []

    def reselect(self, selectionStore):
        for nameList in selectionStore:
            iter = self.findIter(nameList, self.model.get_iter_first())
            if iter is not None:
                self.selection.select_iter(iter)

    def findIter(self, nameList, iter):
        self.diag.info("Looking for iter for " + repr(nameList))
        while iter is not None:
            name = self.model.get_value(iter, 0)
            if name == nameList[0]:
                if len(nameList) == 1:
                    self.diag.info("Succeeded!")
                    return iter
                else:
                    return self.findIter(nameList[1:], self.model.iter_children(iter))
            else:
                iter = self.model.iter_next(iter)
        self.diag.info("Failed!")

    def getState(self):
        pass

    def createView(self):
        self.model.clear()
        state = self.getState()
        self.addFilesToModel(state)
        view = Gtk.TreeView(self.model)
        view.set_name(self.getWidgetName())
        view.set_enable_search(False)  # Shouldn't get big enough to need this
        self.selection = view.get_selection()
        self.selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        self.selection.set_select_function(self.canSelect, self.dynamic)
        renderer = Gtk.CellRendererText()
        self.nameColumn = Gtk.TreeViewColumn(self.title, renderer, text=0, background=1)
        self.nameColumn.set_cell_data_func(renderer, self.renderParentsBold)
        self.nameColumn.set_resizable(True)
        view.append_column(self.nameColumn)
        detailsColumn, recalcRenderer = self.makeDetailsColumn()
        if detailsColumn:
            view.append_column(detailsColumn)
            guiutils.addRefreshTips(view, "file", recalcRenderer, detailsColumn, 5)

        view.expand_all()
        self.monitorEvents()
        view.connect("row_activated", self.fileActivated)

        if self.popupGUI:
            view.connect("button_press_event", self.buttonPressed)
            self.popupGUI.createView()

        view.show()
        return self.addScrollBars(view, hpolicy=Gtk.PolicyType.NEVER)
        # only used in test view

    def buttonPressed(self, *args):
        self.selectionChanged(self.selection)
        self.popupGUI.showMenu(*args)

    def renderParentsBold(self, dummyColumn, cell, model, iter, data):
        if model.iter_has_child(iter):
            cell.set_property('font', "bold")
        else:
            cell.set_property('font', "")

    @staticmethod
    def canSelect(selection, model, path, is_selected, user_data):
        pathIter = model.get_iter(path)
        return not model.iter_has_child(pathIter)

    def makeDetailsColumn(self):
        if self.dynamic:
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn("Details")
            column.set_resizable(True)
            recalcRenderer = Gtk.CellRendererPixbuf()
            column.pack_start(renderer, True)
            column.pack_start(recalcRenderer, False)
            column.add_attribute(renderer, 'text', 4)
            column.add_attribute(renderer, 'background', 1)
            column.add_attribute(recalcRenderer, 'stock_id', 5)
            return column, recalcRenderer
        else:
            return None, None

    def fileActivated(self, dummy, path, *args):
        iter = self.model.get_iter(path)
        fileName = self.model.get_value(iter, 2)
        if not fileName:
            # Don't crash on double clicking the header lines...
            return
        comparison = self.model.get_value(iter, 3)
        self.notify(self.getViewFileSignal(), fileName, comparison, False)

    def addFileToModel(self, iter, fileName, colour, associatedObject=None, details=""):
        baseName = os.path.basename(fileName)
        row = [baseName, colour, fileName, associatedObject, details, ""]
        return self.model.insert_before(iter, None, row)

    def addDataFilesUnderIter(self, iter, files, colour, root, **kwargs):
        dirIters = {root: iter}
        parentIter = iter
        for file in files:
            parent = os.path.split(file)[0]
            parentIter = dirIters.get(parent)
            if parentIter is None:
                subDirIters = self.addDataFilesUnderIter(iter, [parent], colour, root)
                parentIter = subDirIters.get(parent)
            newiter = self.addFileToModel(parentIter, file, colour, **kwargs)
            if os.path.isdir(file):
                dirIters[file] = newiter
        return dirIters

    def monitorEvents(self):
        self.selectionChanged(self.selection)
        self.selection.connect("changed", self.selectionChanged)

    def selectionChanged(self, selection):
        filelist = []

        def fileSelected(dummyModel, dummyPath, iter):
            # Do not include the top level which are just headers that don't currently correspond to files
            if self.model.iter_parent(iter) is not None:
                filePath = self.model.get_value(iter, 2)
                if filePath:
                    filelist.append((filePath, self.model.get_value(iter, 3)))

        selection.selected_foreach(fileSelected)
        self.notify("NewFileSelection", filelist)
        if not self.dynamic:
            if selection.count_selected_rows() == 1:
                paths = selection.get_selected_rows()[1]
                selectedIter = self.model.get_iter(paths[0])
                dirName = self.getDirectory(selectedIter)
                fileType = self.getFileType(selectedIter)
                self.notify("FileCreationInfo", dirName, fileType)
            else:
                self.notify("FileCreationInfo", None, None)

    def getFileType(self, iter):
        parent = self.model.iter_parent(iter)
        name = self.model.get_value(iter, 0)
        if name == self.inheritedText:
            return "external"
        elif parent is not None:
            return self.getFileType(parent)
        else:
            return name.split()[0].lower()

    def getDirectory(self, iter):
        fileName = self.model.get_value(iter, 2)
        if fileName:
            if os.path.isdir(fileName):
                return fileName
            else:
                return os.path.dirname(fileName)


class ApplicationFileGUI(FileViewGUI):
    def __init__(self, dynamic, allApps, popupGUI):
        FileViewGUI.__init__(self, dynamic, "Configuration Files", popupGUI)
        self.allApps = copy(allApps)
        self.extras = reduce(operator.add, (app.extras for app in allApps), [])
        self.storytextDirs = {}
        self.testScripts = {}

    def shouldShow(self):
        return not self.dynamic

    def getTabTitle(self):
        return "Config"

    def getViewFileSignal(self):
        return "ViewApplicationFile"

    def getWidgetName(self):
        return "Application File Tree"

    def notifyShortcut(self, *args):
        self.notifyReloadConfig()

    def notifyShortcutRename(self, *args):
        self.notifyReloadConfig()

    def notifyReloadConfig(self):
        for appName, scriptArgs in list(self.testScripts.items()):
            nonexistent = [s for s in scriptArgs if not os.path.isfile(s)]
            for scriptArg in nonexistent:
                scriptArgs.remove(scriptArg)
        self.recreateModel(None, preserveSelection=True)

    def getScriptArgs(self, suite):
        scriptArgs = set()
        scriptCmds = [suite.getConfigValue("executable", expandVars=False)] + \
            list(suite.getConfigValue("interpreters", expandVars=False).values())

        for scriptCmd in scriptCmds:
            for rawScriptArg in scriptCmd.split():
                if "TEXTTEST_ROOT" in rawScriptArg:
                    scriptArg = string.Template(rawScriptArg).safe_substitute(suite.environment)
                    if os.path.isfile(scriptArg):
                        scriptArgs.add(scriptArg)
        return scriptArgs

    def addSuites(self, suites):
        for suite in suites:
            currUsecaseHome = suite.getEnvironment("STORYTEXT_HOME")
            if currUsecaseHome != os.getenv("STORYTEXT_HOME") and os.path.isdir(currUsecaseHome) and currUsecaseHome not in list(self.storytextDirs.values()):
                self.storytextDirs[suite.app] = currUsecaseHome
                if not suite.parent:
                    self.notify("UsecaseHome", suite, currUsecaseHome)

            self.testScripts.setdefault(suite.app.name, set()).update(self.getScriptArgs(suite))
            if suite.app not in self.allApps and suite.app not in self.extras:
                self.allApps.append(suite.app)
                self.recreateModel(self.getState(), preserveSelection=False)

    def getAllFiles(self, storytextDir, app):
        paths = [storytextDir]
        filesToIgnore = app.getCompositeConfigValue("test_data_ignore", os.path.basename(storytextDir))
        for root, dirs, files in os.walk(storytextDir):
            for name in sorted(files) + sorted(dirs):
                if app.fileMatches(name, filesToIgnore):
                    if name in dirs:
                        dirs.remove(name)
                else:
                    paths.append(os.path.join(root, name))
        return paths

    def addFilesToModel(self, *args):
        colour = guiutils.guiConfig.getCompositeValue("file_colours", "static")
        importedFiles = {}
        allTitles = self.getApplicationTitles()
        for index, app in enumerate(self.allApps):
            headerRow = ["Files for " + allTitles[index], None, app.getDirectory(), None, "", ""]
            confiter = self.model.insert_before(None, None, headerRow)
            for file in self.getConfigFiles(app):
                self.addFileToModel(confiter, file, colour, [app])
                for importedFile in self.getImportedFiles(file, app):
                    importedFiles[importedFile] = importedFile
            storytextDir = self.storytextDirs.get(app)
            if storytextDir:
                files = self.getAllFiles(storytextDir, app)
                self.addDataFilesUnderIter(confiter, files, colour,
                                           app.getDirectory(), associatedObject=self.allApps)
            testScripts = self.testScripts.get(app.name)
            if testScripts:
                headerRow = ["Scripts for " + allTitles[index], None, app.getDirectory(), None, "", ""]
                scriptiter = self.model.insert_before(None, None, headerRow)
                self.addDataFilesUnderIter(scriptiter, sorted(testScripts), colour,
                                           app.getDirectory(), associatedObject=self.allApps)

        # Handle recursive imports here ...

        if len(importedFiles) > 0:
            importediter = self.model.insert_before(None, None)
            self.model.set_value(importediter, 0, "Imported Files")
            sortedFiles = list(importedFiles.values())
            sortedFiles.sort()
            for importedFile in sortedFiles:
                self.addFileToModel(importediter, importedFile, colour, self.allApps)

        personalDir = plugins.getPersonalConfigDir()
        personalFiles = self.getPersonalFiles(personalDir)
        if len(personalFiles) > 0:
            headerRow = ["Personal Files", None, personalDir, None, "", ""]
            persiter = self.model.insert_before(None, None, headerRow)
            self.addDataFilesUnderIter(persiter, personalFiles, colour, personalDir, associatedObject=self.allApps)

    def getApplicationTitles(self):
        basicTitles = [repr(app) for app in self.allApps]
        if self.areUnique(basicTitles):
            return basicTitles
        else:
            return [repr(app) + " (" + app.name + " under " +
                    os.path.basename(app.getDirectory()) + ")" for app in self.allApps]

    def areUnique(self, names):
        for index, name in enumerate(names):
            for otherName in names[index + 1:]:
                if name == otherName:
                    return False
        return True

    def getConfigFiles(self, app):
        dircaches = app.getAllDirCaches("config", [app.dircache])
        return app.getAllFileNames(dircaches, "config", allVersions=True)

    def getPersonalFiles(self, personalDir):
        if not os.path.isdir(personalDir):
            return []
        allFiles = []
        for root, dirs, files in os.walk(personalDir):
            for pruneDir in ["tmp"] + plugins.controlDirNames:
                if pruneDir in dirs:
                    dirs.remove(pruneDir)
            for file in files + dirs:
                allFiles.append(os.path.join(root, file))
        return sorted(allFiles)

    def getImportedFiles(self, file, app=None):
        imports = []
        if os.path.isfile(file):
            importLines = [l for l in open(file, "r").readlines() if l.startswith("import_config_file")]
            for line in importLines:
                try:
                    file = line.split(":")[1].strip()
                    if app:
                        file = app.configPath(file)
                    if os.path.isfile(file):
                        imports.append(file)
                except Exception:  # App. file not found ...
                    continue
        return imports


class TestFileGUI(FileViewGUI):
    def __init__(self, dynamic, popupGUI):
        FileViewGUI.__init__(self, dynamic, "", popupGUI)
        self.currentTest = None

    @staticmethod
    def canSelect(selection, model, path, is_selected, user_data):
        if user_data:
            pathIter = model.get_iter(path)
            return model.iter_parent(pathIter) is not None
        else:
            return True

    def getTabTitle(self):
        return "Test"

    def getWidgetName(self):
        return "File Tree"

    def getViewFileSignal(self):
        return "ViewFile"

    def notifyNameChange(self, test, origRelPath):
        if test is not self.currentTest:
            return

        def updatePath(model, dummyPath, iter):
            origFile = model.get_value(iter, 2)
            if origFile:
                newFile = origFile.replace(origRelPath, test.getRelPath())
                model.set_value(iter, 2, newFile)

        self.model.foreach(updatePath)
        self.setName([test], 1)

    def notifyFileChange(self, test):
        if test is self.currentTest:
            self.recreateModel(test.stateInGui, preserveSelection=True)

    def notifyLifecycleChange(self, test, state, changeDesc):
        if test is self.currentTest:
            self.recreateModel(state, preserveSelection=changeDesc.find("approve") == -1)

    def notifyRecalculation(self, test, comparisons, newIcon):
        if test is not self.currentTest:
            return

        def setRecalculateIcon(model, dummyPath, iter):
            comparison = model.get_value(iter, 3)
            if comparison in comparisons:
                oldVal = model.get_value(iter, 5)
                if oldVal != newIcon:
                    self.model.set_value(iter, 5, newIcon)

        self.model.foreach(setRecalculateIcon)

    def forceVisible(self, rowCount):
        return rowCount == 1

    def notifyNewTestSelection(self, tests, dummyApps, rowCount, *args):
        if len(tests) == 0 or (not self.dynamic and rowCount > 1):  # multiple tests in static GUI result in removal
            self.currentTest = None
            self.setName(tests, rowCount)
            self.model.clear()
            return

        if len(tests) > 1 and self.currentTest in tests:
            self.setName(tests, rowCount)
        else:
            self.currentTest = tests[0]
            self.currentTest.refreshFiles()
            self.setName(tests, rowCount)
            # New test selected, keep file selection!
            # See TTT-2273. Previously we didn't keep the file selection, unclear why...
            self.recreateModel(self.getState(), preserveSelection=True)

    def notifySetFileSelection(self, fileStems):
        def trySelect(model, dummyPath, iter):
            comparison = model.get_value(iter, 3)
            if comparison is not None and comparison.stem in fileStems:
                self.selection.select_iter(iter)
            else:
                self.selection.unselect_iter(iter)

        self.model.foreach(trySelect)

    def notifyViewerStarted(self):
        self.applicationEvent("the viewer process to start", timeDelay=1)

    def notifyNewFile(self, fileName, overwrittenExisting):
        if os.path.isfile(fileName):
            self.notify(self.getViewFileSignal(), fileName, None, True)
        if not overwrittenExisting or os.path.isdir(fileName):
            self.currentTest.refreshFiles()
            self.recreateModel(self.getState(), preserveSelection=True)

    def setName(self, tests, rowCount):
        newTitle = self.getName(tests, rowCount)
        if newTitle != self.title:
            self.title = newTitle
            if self.nameColumn:
                self.nameColumn.set_title(self.title)

    def getName(self, tests, rowCount):
        if rowCount > 1:
            return "Sample from " + repr(len(tests)) + " tests"
        elif self.currentTest:
            return self.currentTest.name.replace("_", "__")
        else:
            return "No test selected"

    def getColour(self, name):
        return guiutils.guiConfig.getCompositeValue("file_colours", name)

    def shouldShowCurrent(self, *args):
        return self.currentTest is not None

    def addFilesToModel(self, state):
        if not state:
            return
        realState = state
        if state.isMarked():
            realState = state.oldState
        if self.dynamic:
            if hasattr(realState, "correctResults"):
                # failed on comparison
                self.addComparisonsToModel(realState)
            else:
                self.addTmpFilesToModel(realState)
        else:
            self.addStaticFilesToModel(realState)

    def getState(self):
        if self.currentTest:
            return self.currentTest.stateInGui

    def addComparisonsToModel(self, state):
        self.addComparisons(state, state.correctResults + state.changedResults, "Comparison Files")
        self.addComparisons(state, state.newResults, "New Files")
        self.addComparisons(state, state.missingResults, "Missing Files")

    def addComparisons(self, state, compList, title):
        if len(compList) == 0:
            return
        iter = self.model.insert_before(None, None)
        self.model.set_value(iter, 0, title)
        filelist = []
        splitlist = {}
        fileCompMap = {}
        for comp in compList:
            file = comp.getDisplayFileName()
            fileCompMap[file] = comp
            if comp.getParent():
                splitlist.setdefault(comp.getParent().getDisplayFileName(), []).append(comp)
            else:
                filelist.append(file)

        for file in sorted(filelist):
            newiter = self.addApprovedFileUnderIter(state, iter, file, fileCompMap)
            splitcomps = splitlist.get(file, [])
            # Preserve the original order of these split files
            for splitcomp in sorted(splitcomps, key=state.allResults.index):
                self.addApprovedFileUnderIter(state, newiter, splitcomp.getDisplayFileName(), fileCompMap)

    def addApprovedFileUnderIter(self, state, iter, file, compMap={}):
        comparison = compMap.get(file)
        colour = self.getComparisonColour(state, comparison)
        details = ""
        if comparison:
            details = comparison.getDetails()
        return self.addFileToModel(iter, file, colour, comparison, details)

    def getComparisonColour(self, state, fileComp):
        if not state.isComplete():
            return self.getColour("running")
        if fileComp and fileComp.hasSucceeded():
            return self.getColour("success")
        else:
            return self.getColour("failure")

    def addTmpFilesToModel(self, state):
        tmpFiles = self.currentTest.listTmpFiles()
        tmpIter = self.model.insert_before(None, None)
        self.model.set_value(tmpIter, 0, "Temporary Files")
        for file in tmpFiles:
            self.addApprovedFileUnderIter(state, tmpIter, file)

    def getRootIterAndColour(self, heading, rootDir=None):
        if not rootDir:
            rootDir = self.currentTest.getDirectory()
        headerRow = [heading + " Files", None, rootDir, None, "", ""]
        stditer = self.model.insert_before(None, None, headerRow)
        colour = guiutils.guiConfig.getCompositeValue("file_colours", "static_" + heading.lower(), defaultKey="static")
        return stditer, colour

    def addStaticFilesWithHeading(self, heading, stdFiles):
        stditer, colour = self.getRootIterAndColour(heading)
        for file in stdFiles:
            self.addFileToModel(stditer, file, colour)

    def addStaticFilesToModel(self, *args):
        stdFiles, defFiles = self.currentTest.listApprovedFiles(allVersions=True)
        if self.currentTest.classId() == "test-case":
            self.addStaticFilesWithHeading("Approved", stdFiles)

        self.addStaticFilesWithHeading("Definition", defFiles)
        self.addStaticDataFilesToModel()
        self.addExternallyEditedFilesToModel()
        self.addExternalFilesToModel()

    def getExternalDataFiles(self):
        try:
            return list(self.currentTest.app.extraReadFiles(self.currentTest).items())
        except Exception:
            sys.stderr.write("WARNING - ignoring exception thrown by '" + self.currentTest.getConfigValue("config_module") +
                             "' configuration while requesting extra data files, not displaying any such files\n")
            return OrderedDict()

    def addStaticDataFilesToModel(self):
        if len(self.currentTest.getDataFileNames()) == 0:
            return
        datiter, colour = self.getRootIterAndColour("Data")
        dataFiles, inheritedDataFiles = self.currentTest.listDataFilesWithInherited()
        currDir = self.currentTest.getDirectory()
        self.addDataFilesUnderIter(datiter, dataFiles, colour, currDir)
        if inheritedDataFiles:
            inheritedRow = [self.inheritedText, None, currDir, None, "", ""]
            inheritedIter = self.model.insert_before(datiter, None, inheritedRow)
            for suite, inherited in list(inheritedDataFiles.items()):
                self.addDataFilesUnderIter(inheritedIter, inherited, colour, suite.getDirectory())

    def addExternalFilesToModel(self):
        externalFiles = self.getExternalDataFiles()
        if len(externalFiles) == 0:
            return
        datiter, colour = self.getRootIterAndColour("External")
        for name, filelist in externalFiles:
            exiter = self.model.insert_before(datiter, None)
            self.model.set_value(exiter, 0, name)
            self.model.set_value(exiter, 1, None)  # mostly to trigger output...
            for file in filelist:
                self.addFileToModel(exiter, file, colour)

    def addExternallyEditedFilesToModel(self):
        root, files = self.currentTest.listExternallyEditedFiles()
        if root:
            datiter, colour = self.getRootIterAndColour("Externally Edited", root)
            self.addDataFilesUnderIter(datiter, files, colour, root)
