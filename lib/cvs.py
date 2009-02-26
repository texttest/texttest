
import os, gobject, guiplugins, datetime, time, subprocess, default_gui
import gtk, plugins, custom_widgets, entrycompletion
from ndict import seqdict

#
# Todo/improvements:
#
# + Multiple dialogs confuses PyUseCase - close doesn't work correctly, for example ..
# + There is a lot of string stripping/replacing going on - perhaps this
#   could be unified and collected in a more centralized place?
# + Update on non-cvs controlled tests give no hint that tests are not in cvs.
# + Test:
#   - For update, we want a 'C ' file ...
#   - For add we need some new files and dirs ... and something that can cause
#     'add aborted' ...
#   - Remove needs some removed files ... and at least one file
#     which is re-born before pressing OK.
#   - Commit needs modified, added and removed files. We also want some error
#     which can cause the commit to fail, e.g. a simultaneous commit from someone else.
# + Commit
#   -r rev      Commit to this branch or trunk revision?
# + Fix update
#   - cvsrevertlast (cvs up -j <old> -j <new> ? (/usr/bin/cvsrevertlast))
#   - Non-modifying version should be available (-n) Maybe not necessary, cvs stat handles this nicely ...
#   - Overwrite local modifications should be available (-C)
#   -d
#   -P      Prune empty directories.
#   - Other date/revision options. Should we care?
# + What happens when we add a test which already has a CVS dir? (e.g.
#   when a test case/suite has been copied with plain 'cp -r' ...
#

#
# Base class for all CVS actions.
#
class CVSAction(guiplugins.ActionResultDialogGUI):
    recursive = False
    def __init__(self, cvsArgs, allApps=[], dynamic=False):
        guiplugins.ActionResultDialogGUI.__init__(self, allApps)
        self.cvsArgs = cvsArgs
        self.dynamic = dynamic
        self.needsAttention = False
        self.notInRepository = False
    def getTitle(self, includeMnemonics=False, adjectiveAfter=True):
        title = self._getTitle()
        if self.recursive or not includeMnemonics:
            title = title.replace("_", "")
        if not includeMnemonics:
            # distinguish these from other actions that may have these names
            title = "CVS " + title
        if self.recursive:
            if adjectiveAfter:
                title += " Recursive"
            else:
                title = "Recursive " + title
        return title
            
    def getTooltip(self):
        return self.getTitle(adjectiveAfter=False).lower() + " for the selected files"

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
        message = "CVS " + self.getFullResultTitle() + " shown below."
        if self.needsAttention:
            message += "\nCVS " + self.getResultTitle() + " found files which are not up-to-date or which have conflicts"
        if self.notInRepository:
            message += "\nSome files/directories were not under CVS control."
        message += "\nCVS command used: " + " ".join(self.getCVSCmdArgs())
        if not self.recursive:
            message += "\nSubdirectories were ignored, use " + self.getTitle() + " Recursive to get the " + self.getResultTitle() + " for all subdirectories."
        return message

    def extraResultDialogWidgets(self):
        all = ["log", "status", "diff", "annotate" ]
        all.remove(self.cvsArgs[0])
        return all
    
    def getCVSCmdArgs(self):
        cvsRoot = os.getenv("CVSROOT")
        if cvsRoot:
            return [ "cvs" ] + self.cvsArgs
        else:
            cvsRoot = self.getCvsRootFromFile()
            return [ "cvs", "-d", cvsRoot ] + self.cvsArgs
        
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
            fileArgs = self.getFilesForCVS(test)
            if len(fileArgs) > 0:
                self.notify("Status", "Getting " + self.getResultTitle() + " for " + self.getTestDescription(test))
                self.notify("ActionProgress", "")
                for fileArg in fileArgs:
                    for fileName in self.getFileNames(fileArg):
                        self.runAndParseFile(fileName, rootDir, test)
        
    def runAndParseFile(self, fileName, rootDir, test):
        args = self.getCVSCmdArgs() + [ fileName ]
        try:
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        except OSError:
            raise plugins.TextTestError, "Could not run CVS: make sure you have it installed locally"

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
    def getResultDialogTitle(self):
        return self.getTooltip()
    def getSelectedFile(self):
        return self.filteredTreeModel.get_value(self.treeView.get_selection().get_selected()[1], 3)
    def viewStatus(self, button):
        file = self.getSelectedFile()
        status = CVSStatus()
        status.notifyTopWindow(self.topWindow)
        status.currTestSelection = [ self.fileToTest[file] ]
        status.currFileSelection = [ (file, None) ]
        status.performOnCurrent()

    def viewLog(self, button):
        file = self.getSelectedFile()
        logger = CVSLog(self.validApps, self.dynamic)
        logger.topWindow = self.topWindow
        logger.currTestSelection = [ self.fileToTest[file] ]
        logger.currFileSelection = [ (file, None) ]
        logger.performOnCurrent()

    def viewAnnotations(self, button):
        file = self.getSelectedFile()
        annotater = CVSAnnotate()
        annotater.topWindow = self.topWindow
        annotater.currTestSelection = [ self.fileToTest[file] ]
        annotater.currFileSelection = [ (file, None) ]
        annotater.performOnCurrent()

    def viewDiffs(self, button):
        file = self.getSelectedFile()
        differ = CVSDiff()
        differ.topWindow = self.topWindow
        differ.setRevisions(self.revision1.get_text(), self.revision2.get_text())
        differ.currTestSelection = [ self.fileToTest[file] ]
        differ.currFileSelection = [ (file, None) ]
        differ.performOnCurrent()

    def viewGraphicalDiff(self, button):
        path = self.filteredTreeModel.get_value(self.treeView.get_selection().get_selected()[1], 2)
        guiplugins.guilog.info("Viewing CVS differences for file '" + path + "' graphically ...")
        pathStem = os.path.basename(path).split(".")[0]
        cvsDiffProgram = guiplugins.guiConfig.getCompositeValue("diff_program", pathStem)
        try:
            cmdArgs = [ cvsDiffProgram ] + self.getRevisionOptions() + [ path ]
            guiplugins.processMonitor.startProcess(cmdArgs, description="Graphical CVS diff for file " + path,
                                    stderr=open(os.devnull, "w"))
        except OSError:
            self.showErrorDialog("\nCannot find graphical CVS difference program '" + cvsDiffProgram + \
                                 "'.\nPlease install it somewhere on your $PATH.\n")
        
    def getCvsRootFromFile(self):
        fullPath = os.path.join(self.getApplicationPath(), "CVS", "Root")
        if not os.path.isfile(fullPath):
            raise plugins.TextTestError, "Could not determine $CVSROOT: environment variable not set and no file present at:\n" + fullPath    

        info = open(fullPath).read()  
        return info.strip().rstrip(os.sep)
            
    def getApplicationPath(self):
        return self.currTestSelection[0].app.getDirectory()
    def getRootPath(self):
        return os.path.split(self.getApplicationPath().rstrip(os.sep))[0]
    def getFilesForCVS(self, test):
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
        guiplugins.scriptEngine.connect("show CVS status", "clicked", button, self.viewStatus)
        self.extraButtonArea.pack_start(button, expand=False, fill=False)        

    def addLogWidget(self):
        button = gtk.Button("_Log")
        guiplugins.scriptEngine.connect("show CVS log", "clicked", button, self.viewLog)
        self.extraButtonArea.pack_start(button, expand=False, fill=False)        

    def addAnnotateWidget(self):
        button = gtk.Button("_Annotate")
        guiplugins.scriptEngine.connect("show CVS annotations", "clicked", button, self.viewAnnotations)
        self.extraButtonArea.pack_start(button, expand=False, fill=False)        

    def addDiffWidget(self):
        diffButton = gtk.Button("_Differences")
        label1 = gtk.Label(" between revisions ")
        label2 = gtk.Label(" and ")
        self.revision1 = gtk.Entry()
        entrycompletion.manager.register(self.revision1)
        self.revision1.set_text("HEAD")
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
        guiplugins.scriptEngine.connect("show CVS differences", "clicked", diffButton, self.viewDiffs)

    def addGraphicalDiffWidget(self):
        button = gtk.Button("_Graphical Diffs")
        guiplugins.scriptEngine.connect("show CVS differences graphically", "clicked", button, self.viewGraphicalDiff)
        self.extraButtonArea.pack_start(button, expand=False, fill=False)        

    def addHeader(self):
        title = self.getResultDialogTitle()
        self.dialog.set_title(title)
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
        #              1 - Content (CVS output) for the corresponding file
        #              2 - Info. If the plugin wants to show two columns, this
        #                  is shown in the second column. If not, ignore.
        #              3 - Relative path of the node. Mainly for testing as recorded traffic
        #                  from CVS can give paths other than the local test tree, of course
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
                        message += "CVS tree view dialog: Adding " + currentPath + \
                                   " as child of " + previousPath + ", info " + info.strip() + "\n"
                        labelMap[currentPath] = self.treeModel.append(labelMap[previousPath],
                                                                      (currentElement, utfContent,
                                                                       currentInfo, currentPath.strip(" \n"), True))
                    else:
                        message += "CVS tree view dialog: Adding " + currentPath + " as root, info " + info.strip() + "\n"
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
            message += "CVS tree view dialog: Showing two columns\n"
        self.treeView.get_selection().set_select_function(self.canSelect)
        self.treeView.expand_all()
        guiplugins.scriptEngine.monitor("select", self.treeView.get_selection())

        if len(self.pages) > 0:
            firstIter = self.filteredTreeModel.convert_child_iter_to_iter(labelMap[self.pages[0][0]])
            text = self.updateForIter(firstIter)
            self.treeView.get_selection().select_iter(firstIter)
            message += "CVS tree view dialog: Showing CVS output\n" + text + "\n"

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
            guiplugins.guilog.info("CVS tree view dialog: Showing CVS output\n" + text)
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
            if "CVS" in dirs:
                dirs.remove("CVS")
            for f in files:
                allFiles.append(os.path.join(root, f))
        return sorted(allFiles)

#
# 1 - First the methods which just check the repository and checked out files.
#


class CVSLog(CVSAction):
    def __init__(self, *args):
        CVSAction.__init__(self, [ "log", "-N" ], *args)
    def _getTitle(self):
        return "_Log"
    def getResultTitle(self):
        return "logs"
    def getResultDialogTwoColumnsInTreeView(self):
        return True
    def getResultDialogSecondColumnTitle(self):
        return "Last revision committed (UTC)"
        
    def parseOutput(self, output, fileName):
        for line in output.splitlines():
            if line.startswith("date:"):
                then = datetime.datetime(*(self.parseCvsDateTime(line[6:25])[0:6]))
                now = datetime.datetime.utcnow()
                return self.getTimeDifference(now, then)
        return "Not in CVS"

    def parseCvsDateTime(self, input):
        # Different CVS versions produce different formats...
        try:
            return time.strptime(input, "%Y/%m/%d %H:%M:%S")
        except ValueError:
            return time.strptime(input, "%Y-%m-%d %H:%M:%S")

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
        
     
class CVSLogLatest(CVSLog):
    def __init__(self, *args):
        CVSLog.__init__(self, *args)
        self.cvsArgs = [ "log", "-N", "-rHEAD" ]
    def _getTitle(self):
        return "Log Latest"
    def getResultDialogMessage(self):
        message = "Showing latest log entries for the CVS controlled files.\nCVS log command used: " + " ".join(self.cvsArgs)
        if not self.recursive:
            message += "\nSubdirectories were ignored."            
        return message

    def storeResult(self, fileName, rootDir, output, test):
        # Each file has something like:
        #
        # RCS file ...
        # Working file:
        # head ...
        # ...
        # description ...
        # ------------
        # revision ...
        # date ...
        # <comments>
        # ============
        #
        # We only want to show the Working file and the stuff from ----- to ===== ...        
        linesToShow = ""
        enabled = False
        for line in output.splitlines():
            if line.startswith("Working file"):
                linesToShow += "\nFile: " + os.path.basename(line[14:]) + "\n"
                continue
            if line.startswith("--------------------"):
                enabled = True
            elif line.startswith("===================="):
                linesToShow += "====================\n"
                enabled = False
            if enabled:
                linesToShow += line + "\n"
        self.pages.setdefault(test.uniqueName, "")
        self.pages[test.uniqueName] += linesToShow
    
    def addContents(self):
        self.pages = seqdict()
        self.runAndParse() 
        self.vbox = gtk.VBox()
        headerMessage = self.addHeader()
        notebookMessage = self.addNotebook()
        return headerMessage + "\n\n" + notebookMessage
        
    def addHeader(self):
        title = self.getResultDialogTitle()
        self.dialog.set_title(title)
        message = self.getResultDialogMessage()
        if message:
            hbox = gtk.HBox()
            icon = gtk.STOCK_DIALOG_INFO
            hbox.pack_start(self.getStockIcon(icon), expand=False, fill=False)
            hbox.pack_start(gtk.Label(message), expand=False, fill=False)        
            alignment = gtk.Alignment()
            alignment.set(0.0, 1.0, 1.0, 1.0)
            alignment.set_padding(5, 5, 0, 5)
            alignment.add(hbox)
            self.vbox.pack_start(alignment, expand=False, fill=False)
            return "Using notebook layout with icon '" + icon + "', header :\n" + message
    
    def addNotebook(self):
        notebook = gtk.Notebook()
        notebook.set_scrollable(True)
        notebook.popup_enable()
        message = ""
        for label, content in self.pages.items():
            buffer = gtk.TextBuffer()
            # Encode to UTF-8, necessary for gtk.TextView
            # First decode using most appropriate encoding ...
            unicodeInfo = plugins.decodeText(content)
            text = plugins.encodeToUTF(unicodeInfo)
            buffer.set_text(text)
            textView = gtk.TextView(buffer)
            textView.set_editable(False)
            window = gtk.ScrolledWindow()
            window.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
            window.add(textView)
            message += "Adding notebook tab '" + label + "' with contents\n" + text + "\n"
            notebook.append_page(window, gtk.Label(label))
        notebook.show_all()
        guiplugins.scriptEngine.monitorNotebook(notebook, "view tab")
        if len(notebook.get_children()) > 0: # Resize to a nice-looking dialog window ...
            parentSize = self.topWindow.get_size()
            self.dialog.resize(int(parentSize[0] / 1.5), int(parentSize[0] / 2))
        self.vbox.pack_start(notebook, expand=True, fill=True)
        self.dialog.vbox.pack_start(self.vbox, expand=True, fill=True)
        return message


class CVSDiff(CVSAction):
    def __init__(self, *args):
        CVSAction.__init__(self, [ "diff", "-N" ], *args)
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
            return CVSAction.getResultDialogMessage(self)

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
    def getRevisionOptions(self):
        options = []
        if self.revision1:
            options += [ "-r", self.revision1 ]
        if self.revision2:
            options += [ "-r", self.revision2 ]
        return options
    def getRevisionMessage(self):
        if self.revision1 == "" and self.revision2 == "":
            return "compared to the latest revision"
        elif self.revision1 == "":
            return "between the local file and revision " + self.revision2
        elif self.revision2 == "":
            return "between revision " + self.revision1 + " and the local file"
        else:
            return "between revisions " + self.revision1 + " and " + self.revision2

    def getCVSCmdArgs(self):
        return CVSAction.getCVSCmdArgs(self) + self.getRevisionOptions()
    
    def extraResultDialogWidgets(self):
        return CVSAction.extraResultDialogWidgets(self) + ["graphical_diff"]

        
class CVSStatus(CVSAction):
    # Googled up.
    cvsWarningStates = [ "Locally Modified", "Locally Removed", "Locally Added" ]
    cvsErrorStates = [ "File had conflicts on merge", "Needs Checkout", "Unresolved Conflicts", "Needs Patch",
                       "Needs Merge", "Entry Invalid", "Unknown", "PROHIBITED" ]
    popupMenuUI = '''<ui>
      <popup name='Info'>
      </popup>
    </ui>'''
    def __init__(self, *args):
        CVSAction.__init__(self, [ "status" ], *args)
        self.uiManager = gtk.UIManager()
        self.popupMenu = None
    def _getTitle(self):
        return "_Status"
    def getResultDialogTwoColumnsInTreeView(self):
        return True
    
    def findStatus(self, output):
        for line in output.splitlines():
            if line.startswith("File: "):
                spaceAfterNamePos = line.find("\t", 7)
                return line[spaceAfterNamePos:].replace("Status: ", "").strip(" \n\t")
        return "Parse Failure" # pragma: no cover - should never reach here unless CVS output format changes

    def getStatusMarkup(self, status):
        if status in self.cvsWarningStates:
            return "<span weight='bold'>" + status + "</span>"
        elif status in self.cvsErrorStates:
            return "<span weight='bold' foreground='red'>" + status + "</span>"
        else:
            return status
 
    def parseOutput(self, output, fileName):
        status = self.findStatus(output)
        if status == "Unknown":
            self.notInRepository = True
        elif status in self.cvsErrorStates:
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
        CVSAction.notifyTopWindow(self, topWindow)
        topWindow.add_accel_group(self.uiManager.get_accel_group())
        self.uiManager.insert_action_group(gtk.ActionGroup("infovisibilitygroup"), 0)
        self.uiManager.get_action_groups()[0].add_actions([("Info", None, "Info", None, None, None)])
        self.uiManager.add_ui_from_string(self.popupMenuUI)
        self.popupMenu = self.uiManager.get_widget("/Info")
        
    def addContents(self):
        message = CVSAction.addContents(self)
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

class CVSAnnotate(CVSAction):
    def __init__(self, *args):
        CVSAction.__init__(self, [ "annotate" ], *args)
    def _getTitle(self):
        return "A_nnotate"
    def getResultTitle(self):
        return "annotations"

class CVSLogRecursive(CVSLog):
    recursive = True

class CVSDiffRecursive(CVSDiff):
    recursive = True

class CVSStatusRecursive(CVSStatus):
    recursive = True
        
class CVSAnnotateRecursive(CVSAnnotate):
    recursive = True    


#
# Configuration for the Interactive Actions
#
class InteractiveActionConfig(default_gui.InteractiveActionConfig):
    def getMenuNames(self):
        return [ "CVS" ]

    def getInteractiveActionClasses(self, dynamic):
        return [ CVSLog, CVSLogRecursive, CVSLogLatest, CVSDiff, CVSDiffRecursive, CVSStatus,
                 CVSStatusRecursive, CVSAnnotate, CVSAnnotateRecursive ]


