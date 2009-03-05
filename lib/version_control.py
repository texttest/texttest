
# Generic interface to version control systems. We try to keep it as general as possible.

import gtk, gobject, guiplugins, default_gui, plugins, custom_widgets, entrycompletion, os, datetime, subprocess

# All VCS specific stuff goes in this class
class VersionControlInterface:
    def __init__(self, program, name, warningStates, errorStates, latestRevisionName, controlDirName = ""):
        self.name = name
        self.program = program
        self.warningStates = warningStates
        self.errorStates = errorStates
        self.latestRevisionName = latestRevisionName
        self.defaultArgs = {}
        if controlDirName:
            self.controlDirName = controlDirName
        else:
            self.controlDirName = "." + self.program

    def getDefaultArgs(self, cmdArgs):
        return self.defaultArgs.get(cmdArgs[0], [])

    def getGraphicalDiffArgs(self, diffProgram):
        return [ diffProgram ] # brittle but general...
    
    def getCmdArgs(self, appPath, cmdArgs):
        return [ self.program ] + cmdArgs + self.getDefaultArgs(cmdArgs)

    def getDateFromLog(self, output):
        pass # pragma: no cover - implemented in all derived classes

    def parseStateFromStatus(self, output):
        pass # pragma: no cover - implemented in all derived classes

    def getCombinedRevisionOptions(self, r1, r2):
        return [] # pragma: no cover - implemented in all derived classes


# Base class for all version control actions.
class VersionControlDialogGUI(guiplugins.ActionResultDialogGUI):
    recursive = False
    vcs = None
    def __init__(self, cmdArgs, allApps=[], dynamic=False):
        guiplugins.ActionResultDialogGUI.__init__(self, allApps)
        self.cmdArgs = cmdArgs
        self.dynamic = dynamic
        self.needsAttention = False
        self.notInRepository = False
    def getTitle(self, includeMnemonics=False, adjectiveAfter=True):
        title = self._getTitle()
        if self.recursive or not includeMnemonics:
            title = title.replace("_", "")
        if not includeMnemonics:
            # distinguish these from other actions that may have these names
            title = self.vcs.name + " " + title
        if self.recursive:
            if adjectiveAfter:
                title += " Recursive"
            else:
                title = "Recursive " + title
        return title

    def getDialogTitle(self):
        return self.getTitle(adjectiveAfter=False) + " for the selected files"
            
    def getTooltip(self):
        from copy import copy
        return copy(self.getDialogTitle()).replace(self.vcs.name, "version control").lower()

    def showWarning(self):
        return self.notInRepository or self.needsAttention

    def getResultDialogIconType(self):
        if self.showWarning():
            return gtk.STOCK_DIALOG_WARNING
        else:
            return gtk.STOCK_DIALOG_INFO

    def getFullResultTitle(self):
        return self.getResultTitle()
    
    def getResultDialogMessage(self):
        message = self.vcs.name + " " + self.getFullResultTitle() + " shown below."
        if self.needsAttention:
            message += "\n" + self.vcs.name + " " + self.getResultTitle() + " found files which are not up-to-date or which have conflicts"
        if self.notInRepository:
            message += "\nSome files/directories were not under " + self.vcs.name + " control."
        message += "\n" + self.vcs.name + " command used: " + " ".join(self.getCmdArgs())
        if not self.recursive:
            message += "\nSubdirectories were ignored, use " + self.getTitle() + " Recursive to get the " + self.getResultTitle() + " for all subdirectories."
        return message

    def extraResultDialogWidgets(self):
        all = ["log", "status", "diff", "annotate" ]
        all.remove(self.cmdArgs[0])
        return all
    
    def getCmdArgs(self):
        return self.vcs.getCmdArgs(self.getApplicationPath(), self.cmdArgs)
        
    def commandHadError(self, retcode, stderr):
        return retcode

    def outputIsInteresting(self, stdout):
        return True

    def getResultTitle(self):
        return self._getTitle().replace("_", "").lower()

    def getTestDescription(self, test):
        relpath = test.getRelPath()
        if relpath:
            return relpath
        else:
            return "the root test suite"
    def runAndParse(self):
        self.notInRepository = False
        self.needsAttention = False
        if len(self.currTestSelection) > 0:
            rootDir = self.getRootPath()
        for test in self.currTestSelection:
            fileArgs = self.getFilesForCmd(test)
            if len(fileArgs) > 0:
                self.notify("Status", "Getting " + self.getResultTitle() + " for " + self.getTestDescription(test))
                self.notify("ActionProgress", "")
                for fileArg in fileArgs:
                    for fileName in self.getFileNames(fileArg):
                        self.runAndParseFile(fileName, rootDir, test)
        
    def runAndParseFile(self, fileName, rootDir, test):
        args = self.getCmdArgs() + [ fileName ]
        try:
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        except OSError:
            raise plugins.TextTestError, "Could not run " + self.vcs.name + ": make sure you have it installed locally"

        stdout, stderr = process.communicate()
        if self.commandHadError(process.returncode, stderr):
            self.notInRepository = True
            self.storeResult(fileName, rootDir, stderr, test)
        elif self.outputIsInteresting(stdout):
            self.storeResult(fileName, rootDir, stdout, test)

    def storeResult(self, fileName, rootDir, output, test):
        info = self.parseOutput(output, fileName)
        relativeFilePath = plugins.relpath(fileName.strip(), rootDir)
        self.fileToTest[relativeFilePath] = test
        self.pages.append((relativeFilePath, output, info))
        self.notify("Status", "Analyzing " + self.getResultTitle() + " for " + relativeFilePath.strip('\n'))
        self.notify("ActionProgress", "")
                        
    def parseOutput(self, output, fileName):
        return fileName        
    
    def updateSelection(self, *args):
        newActive = guiplugins.ActionResultDialogGUI.updateSelection(self, *args)
        if not self.dynamic: # See bugzilla 17653
            self.currFileSelection = []
        return newActive
    def notifyNewFileSelection(self, files):
        self.updateFileSelection(files)
    def isActiveOnCurrent(self, *args):
        return len(self.currTestSelection) > 0 
    def messageAfterPerform(self):
        return "Performed " + self.getTooltip() + "."
    def getResultDialogTwoColumnsInTreeView(self):
        return False
    def getResultDialogSecondColumnTitle(self):
        return "Information"
    def getSelectedFile(self):
        return self.filteredTreeModel.get_value(self.treeView.get_selection().get_selected()[1], 3)
    def viewStatus(self, button):
        file = self.getSelectedFile()
        status = StatusGUI()
        status.notifyTopWindow(self.topWindow)
        status.currTestSelection = [ self.fileToTest[file] ]
        status.currFileSelection = [ (file, None) ]
        status.performOnCurrent()

    def viewLog(self, button):
        file = self.getSelectedFile()
        logger = LogGUI(self.validApps, self.dynamic)
        logger.topWindow = self.topWindow
        logger.currTestSelection = [ self.fileToTest[file] ]
        logger.currFileSelection = [ (file, None) ]
        logger.performOnCurrent()

    def viewAnnotations(self, button):
        file = self.getSelectedFile()
        annotater = AnnotateGUI()
        annotater.topWindow = self.topWindow
        annotater.currTestSelection = [ self.fileToTest[file] ]
        annotater.currFileSelection = [ (file, None) ]
        annotater.performOnCurrent()

    def viewDiffs(self, button):
        file = self.getSelectedFile()
        differ = DiffGUI()
        differ.topWindow = self.topWindow
        differ.setRevisions(self.revision1.get_text(), self.revision2.get_text())
        differ.currTestSelection = [ self.fileToTest[file] ]
        differ.currFileSelection = [ (file, None) ]
        differ.performOnCurrent()

    def getRevisionOptions(self):
        if self.revision1 and self.revision2:
            return self.vcs.getCombinedRevisionOptions(self.revision1, self.revision2)
        elif self.revision1:
            return [ "-r", self.revision1 ]
        elif self.revision2:
            return [ "-r", self.revision2 ]
        else:
            return []

    def viewGraphicalDiff(self, button):
        path = self.filteredTreeModel.get_value(self.treeView.get_selection().get_selected()[1], 2)
        guiplugins.guilog.info("Viewing " + self.vcs.name + " differences for file '" + path + "' graphically ...")
        pathStem = os.path.basename(path).split(".")[0]
        diffProgram = guiplugins.guiConfig.getCompositeValue("diff_program", pathStem)
        revOptions = self.getRevisionOptions()
        graphDiffArgs = self.vcs.getGraphicalDiffArgs(diffProgram)
        try:
            if not graphDiffArgs[0] == diffProgram:
                subprocess.call([ diffProgram, "--help" ], stderr=open(os.devnull, "w"), stdout=open(os.devnull, "w"))
            cmdArgs = graphDiffArgs + revOptions + [ path ]
            guiplugins.processMonitor.startProcess(cmdArgs, description="Graphical " + self.vcs.name + " diff for file " + path,
                                                   stderr=open(os.devnull, "w"), stdout=open(os.devnull, "w"))
        except OSError:
            self.showErrorDialog("\nCannot find graphical " + self.vcs.name + " difference program '" + diffProgram + \
                                     "'.\nPlease install it somewhere on your $PATH.\n")
                                
    def getApplicationPath(self):
        return self.currTestSelection[0].app.getDirectory()
    def getRootPath(self):
        return os.path.split(self.getApplicationPath().rstrip(os.sep))[0]
    def getFilesForCmd(self, test):
        testPath = test.getDirectory()
        if len(self.currFileSelection) == 0:
            if self.dynamic:
                return sorted([ fileComp.stdFile for fileComp in self.getComparisons(test) ])
            else:
                return [ testPath ]
        else:
            return [ self.getAbsPath(f, testPath) for f, comp in self.currFileSelection ]

    def getComparisons(self, test):
        try:
            # Leave out new ones
            return test.state.changedResults + test.state.correctResults + test.state.missingResults
        except AttributeError:
            raise plugins.TextTestError, "Cannot establish which files should be compared as no comparison information exists.\n" + \
                  "To create this information, perform 'recompute status' (press '" + \
                         guiplugins.guiConfig.getCompositeValue("gui_accelerators", "recompute_status") + "') and try again."
            
    def getAbsPath(self, filePath, testPath):
        if os.path.isabs(filePath):
            return filePath
        else:
            # internal structures store relative paths
            return os.path.join(testPath, os.path.basename(filePath))
        
    def isModal(self):
        return False
    
    def addContents(self):
        self.pages = []
        self.fileToTest = {}
        self.runAndParse() # will write to the above two structures
        self.vbox = gtk.VBox()
        self.addExtraWidgets()
        headerMessage = self.addHeader()
        treeViewMessage = self.addTreeView()
        return headerMessage + "\n\n" + treeViewMessage
    
    def addExtraWidgets(self):
        self.extraWidgetArea = gtk.HBox()
        self.extraButtonArea = gtk.HButtonBox()
        self.extraWidgetArea.pack_start(self.extraButtonArea, expand=False, fill=False)        
        if len(self.pages) > 0:
            padding = gtk.Alignment()
            padding.set_padding(3, 3, 3, 3)
            padding.add(self.extraWidgetArea)
            self.dialog.vbox.pack_end(padding, expand=False, fill=False)
            extraWidgetsToShow = self.extraResultDialogWidgets()
            if "status" in extraWidgetsToShow:
                self.addStatusWidget()
            if "log" in extraWidgetsToShow:
                self.addLogWidget()
            if "annotate" in extraWidgetsToShow:
                self.addAnnotateWidget()
            if "graphical_diff" in extraWidgetsToShow:
                self.addGraphicalDiffWidget()
            if "diff" in extraWidgetsToShow:
                self.addDiffWidget()

    def addStatusWidget(self):
        button = gtk.Button("_Status")
        guiplugins.scriptEngine.connect("show version control status", "clicked", button, self.viewStatus)
        self.extraButtonArea.pack_start(button, expand=False, fill=False)        

    def addLogWidget(self):
        button = gtk.Button("_Log")
        guiplugins.scriptEngine.connect("show version control log", "clicked", button, self.viewLog)
        self.extraButtonArea.pack_start(button, expand=False, fill=False)        

    def addAnnotateWidget(self):
        button = gtk.Button("_Annotate")
        guiplugins.scriptEngine.connect("show version control annotations", "clicked", button, self.viewAnnotations)
        self.extraButtonArea.pack_start(button, expand=False, fill=False)        

    def addDiffWidget(self):
        diffButton = gtk.Button("_Differences")
        label1 = gtk.Label(" between revisions ")
        label2 = gtk.Label(" and ")
        self.revision1 = gtk.Entry()
        entrycompletion.manager.register(self.revision1)
        self.revision1.set_text(self.vcs.latestRevisionName)
        self.revision2 = gtk.Entry()
        entrycompletion.manager.register(self.revision2)
        self.revision1.set_alignment(1.0)
        self.revision2.set_alignment(1.0)
        self.revision1.set_width_chars(6)
        self.revision2.set_width_chars(6)
        guiplugins.scriptEngine.registerEntry(self.revision1, "set first revision to ")
        guiplugins.scriptEngine.registerEntry(self.revision2, "set second revision to ")
        self.extraButtonArea.pack_start(diffButton, expand=False, fill=False)
        self.extraWidgetArea.pack_start(label1, expand=False, fill=False)
        self.extraWidgetArea.pack_start(self.revision1, expand=False, fill=False)
        self.extraWidgetArea.pack_start(label2, expand=False, fill=False)
        self.extraWidgetArea.pack_start(self.revision2, expand=False, fill=False)
        guiplugins.scriptEngine.connect("show version control differences", "clicked", diffButton, self.viewDiffs)

    def addGraphicalDiffWidget(self):
        button = gtk.Button("_Graphical Diffs")
        guiplugins.scriptEngine.connect("show version control differences graphically", "clicked", button, self.viewGraphicalDiff)
        self.extraButtonArea.pack_start(button, expand=False, fill=False)        

    def addHeader(self):
        message = self.getResultDialogMessage()
        if message:
            hbox = gtk.HBox()
            iconType = self.getResultDialogIconType()
            hbox.pack_start(self.getStockIcon(iconType), expand=False, fill=False)
            hbox.pack_start(gtk.Label(message), expand=False, fill=False)        
            alignment = gtk.Alignment()
            alignment.set(0.0, 1.0, 1.0, 1.0)
            alignment.set_padding(5, 5, 0, 5)
            alignment.add(hbox)
            self.vbox.pack_start(alignment, expand=False, fill=False)
            return "Using Tree View layout with icon '" + iconType + "', header :\n" + message

    def getStockIcon(self, stockItem):
        imageBox = gtk.VBox()
        imageBox.pack_start(gtk.image_new_from_stock(stockItem, gtk.ICON_SIZE_DIALOG), expand=False)
        return imageBox

    def addTreeView(self):
        hpaned = gtk.HPaned()

        # We need buffer when creating treeview, so create right-hand side first ...
        self.textBuffer = gtk.TextBuffer()
        textView = gtk.TextView(self.textBuffer)
        textView.set_editable(False)
        window2 = gtk.ScrolledWindow()
        window2.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        window2.add(textView)
        hpaned.pack2(window2, True, True)

        messages = self.createTreeView()
        window1 = gtk.ScrolledWindow()
        window1.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
        window1.add(self.treeView)
        hpaned.pack1(window1, False, True)

        if len(self.pages) > 0:
            parentSize = self.topWindow.get_size()
            self.dialog.resize(parentSize[0], int(parentSize[0] / 1.5))
            self.vbox.pack_start(hpaned, expand=True, fill=True)
        self.dialog.vbox.pack_start(self.vbox, expand=True, fill=True)
        return messages
    
    def createTreeView(self):
        # Columns are: 0 - Tree node name
        #              1 - Content (output from VCS) for the corresponding file
        #              2 - Info. If the plugin wants to show two columns, this
        #                  is shown in the second column. If not, ignore.
        #              3 - Relative path of the node. Mainly for testing as recorded traffic
        #                  from CVS could give paths other than the local test tree, of course.
        #                  We don't use that any more but this still seems necessary...
        #              4 - Should the row be visible?
        self.treeModel = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING,
                                       gobject.TYPE_STRING, gobject.TYPE_STRING,
                                       gobject.TYPE_BOOLEAN)
        self.filteredTreeModel = self.treeModel.filter_new()
        self.filteredTreeModel.set_visible_column(4)
        
        labelMap = {}
        message = ""
        for label, content, info in self.pages:
            utfContent = plugins.encodeToUTF(plugins.decodeText(content))
            path = label.split(os.sep)
            currentPath = ""
            previousPath = ""
            for element in path:
                previousPath = currentPath
                currentPath = os.path.join(currentPath, element)
                currentInfo = ""
                currentElement = element.strip(" \n")
                if currentPath == label:
                    currentInfo = info
                else:
                    currentElement = "<span weight='bold'>" + currentElement + "</span>"
                if not labelMap.has_key(currentPath):
                    if labelMap.has_key(previousPath):
                        message += self.vcs.name + " tree view dialog: Adding " + currentPath + \
                                   " as child of " + previousPath + ", info " + info.strip() + "\n"
                        labelMap[currentPath] = self.treeModel.append(labelMap[previousPath],
                                                                      (currentElement, utfContent,
                                                                       currentInfo, currentPath.strip(" \n"), True))
                    else:
                        message += self.vcs.name + " tree view dialog: Adding " + currentPath + " as root, info " + info.strip() + "\n"
                        labelMap[currentPath] = self.treeModel.append(None,
                                                                      (currentElement, utfContent,
                                                                       currentInfo, currentPath.strip(" \n"), True))

        self.treeView = gtk.TreeView(self.filteredTreeModel)
        self.treeView.set_enable_search(False)
        fileRenderer = gtk.CellRendererText()
        fileColumn = gtk.TreeViewColumn("File", fileRenderer, markup=0)
        fileColumn.set_resizable(True)
        self.treeView.append_column(fileColumn)
        self.treeView.set_expander_column(fileColumn)
        if self.getResultDialogTwoColumnsInTreeView():
            infoRenderer = gtk.CellRendererText()
            self.infoColumn = custom_widgets.ButtonedTreeViewColumn(self.getResultDialogSecondColumnTitle(), infoRenderer, markup=2)
            self.infoColumn.set_resizable(True)
            self.treeView.append_column(self.infoColumn)
            message += self.vcs.name + " tree view dialog: Showing two columns\n"
        self.treeView.get_selection().set_select_function(self.canSelect)
        self.treeView.expand_all()
        guiplugins.scriptEngine.monitor("select", self.treeView.get_selection())

        if len(self.pages) > 0:
            firstIter = self.filteredTreeModel.convert_child_iter_to_iter(labelMap[self.pages[0][0]])
            text = self.updateForIter(firstIter)
            self.treeView.get_selection().select_iter(firstIter)
            message += self.vcs.name + " tree view dialog: Showing " + self.vcs.name + " output\n" + text + "\n"

        self.treeView.get_selection().connect("changed", self.showOutput)
        return message

    def updateForIter(self, iter):
        self.extraWidgetArea.set_sensitive(True)
        text = self.filteredTreeModel.get_value(iter, 1)
        self.textBuffer.set_text(text)
        return text
        
    def showOutput(self, selection):
        model, iter = selection.get_selected()
        if iter:
            text = self.updateForIter(iter)
            guiplugins.guilog.info(self.vcs.name + " tree view dialog: Showing " + self.vcs.name + " output\n" + text)
        else:
            self.extraWidgetArea.set_sensitive(False)

    def canSelect(self, path):
        return not self.treeModel.iter_has_child(
            self.treeModel.get_iter(self.filteredTreeModel.convert_path_to_child_path(path)))

    def getFileNames(self, fileArg):
        if os.path.isfile(fileArg):
            return [ fileArg ]
        elif os.path.isdir(fileArg):
            if self.recursive:
                return self.getFilesFromDirRecursive(fileArg)
            else:
                return self.getFilesFromDir(fileArg)
            
    def getFilesFromDir(self, dirName):
        files = []
        for f in sorted(os.listdir(dirName)):
            fullPath = os.path.join(dirName, f)
            if os.path.isfile(fullPath):
                files.append(fullPath)
        return files

    def getFilesFromDirRecursive(self, dirName):
        allFiles = []
        for root, dirs, files in os.walk(dirName):
            if self.vcs.controlDirName in dirs:
                dirs.remove(self.vcs.controlDirName)
            for f in files:
                allFiles.append(os.path.join(root, f))
        return sorted(allFiles)

#
# 1 - First the methods which just check the repository and checked out files.
#


class LogGUI(VersionControlDialogGUI):
    def __init__(self, *args):
        VersionControlDialogGUI.__init__(self, [ "log" ], *args)
    def _getTitle(self):
        return "_Log"
    def getResultTitle(self):
        return "logs"
    def getResultDialogTwoColumnsInTreeView(self):
        return True
    def getResultDialogSecondColumnTitle(self):
        return "Last revision committed (UTC)"
        
    def parseOutput(self, output, fileName):
        then = self.vcs.getDateFromLog(output)
        if then is None:
            return "Not in " + self.vcs.name

        now = datetime.datetime.utcnow()
        return self.getTimeDifference(now, then)

    # Show a human readable time difference string. Diffs larger than farAwayLimit are
    # written as the actual 'to' time, while other diffs are written e.g. 'X days ago'.
    # If markup is True, diffs less than closeLimit are boldified and diffs the same
    # day are red as well.
    def getTimeDifference(self, now, then, markup = True, \
                          closeLimit = datetime.timedelta(days=3), \
                          farAwayLimit = datetime.timedelta(days=7)):
        difference = now - then # Assume this is positive ...
        if difference > farAwayLimit:
            return then.ctime()

        stringDiff = str(difference.days) + " days ago"
        yesterday = now - datetime.timedelta(days=1)
        if now.day == then.day:
            stringDiff = "Today at " + then.strftime("%H:%M:%S")
            if markup:
                stringDiff = "<span weight='bold' foreground='red'>" + stringDiff + "</span>"
        elif yesterday.day == then.day and yesterday.month == then.month and yesterday.year == then.year:
            stringDiff = "Yesterday at " + then.strftime("%H:%M:%S")
            if markup:
                stringDiff = "<span weight='bold'>" + stringDiff + "</span>"
        elif difference <= closeLimit and markup:
            stringDiff = "<span weight='bold'>" + stringDiff + "</span>"
        return stringDiff     


class DiffGUI(VersionControlDialogGUI):
    def __init__(self, *args):
        VersionControlDialogGUI.__init__(self, [ "diff" ], *args)
        self.revision1 = ""
        self.revision2 = ""
    def setRevisions(self, rev1, rev2):
        self.revision1 = rev1
        self.revision2 = rev2
    def _getTitle(self):
        return "_Difference"
    def getResultTitle(self):
        return "differences"
    def getResultDialogMessage(self):
        if len(self.pages) == 0:
            return "All files are up-to-date and unmodified compared to the latest repository version."
        else:
            return VersionControlDialogGUI.getResultDialogMessage(self)

    def getFullResultTitle(self):
        return "differences " + self.getRevisionMessage()
    def showWarning(self):
        return len(self.pages) > 0
    def commandHadError(self, retcode, stderr):
        # Diff returns an error code for differences, not just for errors
        return retcode and len(stderr) > 0
    def outputIsInteresting(self, stdout):
        # Don't show diffs if they're empty
        return len(stdout) > 0
    def getRevisionMessage(self):
        if self.revision1 == "" and self.revision2 == "":
            return "compared to the latest revision"
        elif self.revision1 == "":
            return "between the local file and revision " + self.revision2
        elif self.revision2 == "":
            return "between revision " + self.revision1 + " and the local file"
        else:
            return "between revisions " + self.revision1 + " and " + self.revision2

    def getCmdArgs(self):
        return VersionControlDialogGUI.getCmdArgs(self) + self.getRevisionOptions()
    
    def extraResultDialogWidgets(self):
        return VersionControlDialogGUI.extraResultDialogWidgets(self) + ["graphical_diff"]

        
class StatusGUI(VersionControlDialogGUI):
    popupMenuUI = '''<ui>
      <popup name='Info'>
      </popup>
    </ui>'''
    def __init__(self, *args):
        VersionControlDialogGUI.__init__(self, [ "status" ], *args)
        self.uiManager = gtk.UIManager()
        self.popupMenu = None
    def _getTitle(self):
        return "_Status"
    def getResultDialogTwoColumnsInTreeView(self):
        return True
    
    def getStatusMarkup(self, status):
        if status in self.vcs.warningStates:
            return "<span weight='bold'>" + status + "</span>"
        elif status in self.vcs.errorStates:
            return "<span weight='bold' foreground='red'>" + status + "</span>"
        else:
            return status
 
    def parseOutput(self, output, fileName):
        status = self.vcs.getStateFromStatus(output)
        if status == "Unknown":
            self.notInRepository = True
        elif status in self.vcs.errorStates:
            self.needsAttention = True
        return self.getStatusMarkup(status)
            
    def addToggleItems(self):
        # Each unique info column (column 2) gets its own toggle action in the popup menu
        uniqueInfos = []
        self.treeModel.foreach(self.collectInfos, uniqueInfos)
        actionGroup = self.uiManager.get_action_groups()[0]
        for info in uniqueInfos:
            # Don't add the same action lots of time, GTK 2.12 protests...
            if actionGroup.get_action(info):
                continue
            action = gtk.ToggleAction(info, info, None, None)
            action.set_active(True)
            actionGroup.add_action(action)
            self.uiManager.add_ui_from_string("<popup name='Info'><menuitem name='" + info + "' action='" + info + "'/></popup>")
            action.connect("toggled", self.toggleVisibility)
            guiplugins.scriptEngine.registerToggleButton(action, "show category " + action.get_name(), "hide category " + action.get_name())
        self.uiManager.ensure_update()

    def toggleVisibility(self, action):
        self.treeModel.foreach(self.setVisibility, (action.get_name(), action.get_active()))
        self.treeView.expand_row(self.filteredTreeModel.get_path(self.filteredTreeModel.get_iter_root()), True)

    def setVisibility(self, model, path, iter, (actionName, actionState)):
        if model.iter_parent(iter) is not None and (
            actionName == "" or
            model.get_value(iter, 2).lstrip("<span weight='bold'>").lstrip("<span weight='bold' foreground='red'>").rstrip("</span>").strip(" ") == actionName):
            model.set_value(iter, 4, actionState)
            parentIter = model.iter_parent(iter)
            if actionState or self.hasNoVisibleChildren(model, parentIter):
                self.setVisibility(model, model.get_path(parentIter), parentIter, ("", actionState))

    def hasNoVisibleChildren(self, model, iter):
        i = model.iter_children(iter)
        while i:
            if model.get_value(i, 4):
                return False
            i = model.iter_next(i)
        return True
        
    def collectInfos(self, model, path, iter, infos):
        info = model.get_value(iter, 2)
        if info != "":
            rawInfo = info.replace("<span weight='bold'>", "").replace("<span weight='bold' foreground='red'>",
                                                                       "").replace("</span>", "").strip()
            if rawInfo not in infos:
                infos.append(rawInfo)
            
    def notifyTopWindow(self, topWindow):
        VersionControlDialogGUI.notifyTopWindow(self, topWindow)
        topWindow.add_accel_group(self.uiManager.get_accel_group())
        self.uiManager.insert_action_group(gtk.ActionGroup("infovisibilitygroup"), 0)
        self.uiManager.get_action_groups()[0].add_actions([("Info", None, "Info", None, None, None)])
        self.uiManager.add_ui_from_string(self.popupMenuUI)
        self.popupMenu = self.uiManager.get_widget("/Info")
        
    def addContents(self):
        message = VersionControlDialogGUI.addContents(self)
        self.addToggleItems()
        self.infoColumn.set_clickable(True)
        if self.infoColumn.get_button():
            self.infoColumn.get_button().connect("button-press-event", self.showPopupMenu)
        self.treeView.grab_focus() # Or the column button gets focus ...
        return message
    
    def showPopupMenu(self, treeview, event):
        if event.button == 3: # pragma: no cover - replaying doesn't actually press the button
            self.popupMenu.popup(None, None, None, event.button, event.time)
            return True

class AnnotateGUI(VersionControlDialogGUI):
    def __init__(self, *args):
        VersionControlDialogGUI.__init__(self, [ "annotate" ], *args)
    def _getTitle(self):
        return "A_nnotate"
    def getResultTitle(self):
        return "annotations"

class LogGUIRecursive(LogGUI):
    recursive = True

class DiffGUIRecursive(DiffGUI):
    recursive = True

class StatusGUIRecursive(StatusGUI):
    recursive = True
        
class AnnotateGUIRecursive(AnnotateGUI):
    recursive = True    

# Rename in source control also.
# Most systems can do this directly, override again for CVS
class RenameTest(default_gui.RenameTest):
    def renameDir(self, oldDir, newDir):
        retCode = self.callVcs([ "mv", oldDir, newDir ])
        if retCode > 0:
            # Wasn't in version control, probably
            default_gui.RenameTest.renameDir(self, oldDir, newDir)

    def callVcs(self, cmdArgs):
        return subprocess.call([ VersionControlDialogGUI.vcs.program ] + cmdArgs,
                               stdout=open(os.devnull, "w"), stderr=open(os.devnull, "w"))


#
# Configuration for the Interactive Actions
#
class InteractiveActionConfig(default_gui.InteractiveActionConfig):
    def getMenuNames(self):
        return [ VersionControlDialogGUI.vcs.name ]

    def getInteractiveActionClasses(self, dynamic):
        return [ LogGUI, LogGUIRecursive, DiffGUI, DiffGUIRecursive, StatusGUI,
                 StatusGUIRecursive, AnnotateGUI, AnnotateGUIRecursive ]

    def getReplacements(self):
        return { default_gui.RenameTest : RenameTest }
