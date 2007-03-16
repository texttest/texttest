
import sys, os, guiplugins, guidialogs, gobject, datetime, time
import default, texttestgui, gtk, plugins

from guidialogs import guilog, scriptEngine
from gtkusecase import TreeModelIndexer

# First make sure that CVSROOT is set ...
cvsRootSet = True
if "CVSROOT" not in os.environ:
    plugins.printWarning("CVSROOT must be set to use the CVS plugin. Please set this environment variable and re-start TextTest to enable the CVS commands.")
    cvsRootSet = False
elif not os.path.exists(os.environ["CVSROOT"]):
    plugins.printWarning("The CVSROOT '" + os.environ["CVSROOT"] + "' does not exist. Please correct the CVSROOT environment variable and re-start TextTest to enable the CVS commands.")
    cvsRootSet = False

#
# Todo/improvements:
#
# + Multiple dialogs confuses PyUseCase - close doesn't work correctly, for example ..
# + There is a lot of string stripping/replacing going on - perhaps this
#   could be unified and collected in a more centralized place?
# + Update on non-cvs controlled tests give no hint that tests are not in cvs.
# + Test:
#   - Each action.
#   - Dynamic GUI!
#   - For diff, there should be some differing files, but we should also test
#     the case without diffs.
#   - For status, we want to test 'U ' and 'C ' files
#   - For update, we want a 'C ' file ...
#   - For add we need some new files and dirs ... and something that can cause
#     'add aborted' ...
#   - Remove needs some removed files ... and at least one file
#     which is re-born before pressing OK.
#   - Commit needs modified, added and removed files. We also want some error
#     which can cause the commit to fail, e.g. a simultaneous commit from someone else.
# + Add 'Observe' message when diff invoked from the dynamic GUI
#   that the diffs are not related to the current test results, but to the
#   latest saved versions.
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
# + 
# V Add diff button in log dialog (diff w.r.t. different revisions?)
# V Add log button in status dialog
# V Support single-file action (if files are selected, as for save)
#   What if multiple tests are selected, in the dynamic GUI?
# V Adding cspsolver gives strange result ...
# V Should recursive actions report on files individually?
# V guilog
# V ScriptEngine! (e.g. monitor tkdiff)
# V Add tkdiff button to diff result window
# V Add success or failure icons to result dialogs ...
# V When diffing a dir, we get a message 'cvs diff: Diffing <dirname>'
#   even when no diffs occur in the dir. Annoying.
#

#
# Base class for all CVS actions.
#
class CVSMultipleAction(guiplugins.InteractiveAction):
    def __init__(self, cvsCommand):
        guiplugins.InteractiveAction.__init__(self)
        self.currTestSelection = []
        self.currFileSelection = []
        self.cvsCommand = cvsCommand
        self.recursive = False
    def notifyNewTestSelection(self, tests, direct):
        self.currTestSelection = tests
    def notifyNewFileSelection(self, files):
        self.currFileSelection = files
    def isActiveOnCurrent(self):
        return cvsRootSet and len(self.currTestSelection) > 0 
    def separatorBeforeInMainMenu(self):
        return not self.recursive
    def separatorBeforeInTestPopupMenu(self):
        return self.separatorBeforeInMainMenu()
    def inToolBar(self):
        return False
    def inButtonBar(self):
        return False
    def getMainMenuPath(self):
        return "_CVS"
    def getTestPopupMenuPath(self):
        return "_CVS"
    def messageAfterPerform(self):
        return "Performed " + self._getScriptTitle() + "."
    def getResultDialogTwoColumnsInTreeView(self):
        return False
    def getResultDialogSecondColumnTitle(self):
        return "Information"
    def getResultDialogType(self):
        return "CVSTreeViewDialog"
    def getResultDialogTitle(self):
        return self._getScriptTitle()
    def getResultDialogIconType(self):
        return gtk.STOCK_DIALOG_INFO;
    def getSelectionDialogIconType(self):
        return gtk.STOCK_DIALOG_INFO;
    def getSelectionDialogTwoColumnsInTreeView(self):
        return False
    def extraResultDialogWidgets(self):
        return []
    def viewStatus(self, file, dialog):
        status = CVSStatus()
        status.currTestSelection = [ self.fileToTest[file] ]
        status.currFileSelection = [ os.path.basename(file) ]
        status.performOnCurrent()
        dialog = CVSTreeViewDialog(dialog.parent, None, status)
        dialog.run()
    def viewLog(self, file, dialog):
        logger = CVSLog()
        logger.currTestSelection = [ self.fileToTest[file] ]
        logger.currFileSelection = [ os.path.basename(file) ]
        logger.performOnCurrent(True)
        dialog = CVSTreeViewDialog(dialog.parent, None, logger)
        dialog.run()
    def viewAnnotations(self, file, dialog):
        annotater = CVSAnnotate()
        annotater.currTestSelection = [ self.fileToTest[file] ]
        annotater.currFileSelection = [ os.path.basename(file) ]
        annotater.performOnCurrent()
        dialog = CVSTreeViewDialog(dialog.parent, None, annotater)
        dialog.run()
    def viewDiffs(self, file, revision1, revision2, dialog):
        differ = CVSDiff(revision1, revision2)
        differ.currTestSelection = [ self.fileToTest[file] ]
        differ.currFileSelection = [ os.path.basename(file) ]
        differ.performOnCurrent()
        dialog = CVSTreeViewDialog(dialog.parent, None, differ)
        dialog.run()
    def viewGraphicalDiffs(self, path, dialog):
        guilog.info("Viewing CVS differences for file '" + path + "' graphically ...")
        cvsDiffProgram = "tkdiff" # Hardcoded for now ...
        if not plugins.canExecute(cvsDiffProgram):
            guidialogs.showErrorDialog("\nCannot find graphical CVS difference program '" + cvsDiffProgram + \
                  "'.\nPlease install it somewhere on your $PATH.\n", dialog.dialog)
        command = cvsDiffProgram + " " + dialog.plugin.getRevisionOptions() + " " + path + " " + plugins.nullRedirect()
        process = self.startExternalProgram(command, "Graphical CVS diff for file " + path)
        scriptEngine.monitorProcess("shows CVS differences graphically", process)
    def getCVSRepository(self, appDir):
        # Join the dir/CVS/Root and dir/CVS/Repository files.
        try:
            rootFile = open(os.path.join(appDir, os.path.join("CVS", "Root")))
            repFile = open(os.path.join(appDir, os.path.join("CVS", "Repository")))
            return os.path.dirname(os.path.join(rootFile.read().strip(" \n\t"),
                                                repFile.read().strip(" \n\t")).rstrip(os.sep))
        except:
            return ""
    def getApplicationPath(self):
        return os.path.realpath(self.currTestSelection[0].app.getDirectory())
    def getRootPath(self):
        return os.path.realpath(os.path.split(os.path.realpath(self.currTestSelection[0].app.getDirectory()).rstrip(os.sep))[0])
    def getRelativePath(self, path, root):
        return path.replace(root, "").lstrip(os.sep).strip(" \n\t")

#
# 1 - First the methods which just check the repository and checked out files.
#


class CVSLog(CVSMultipleAction):
    def __init__(self):
        CVSMultipleAction.__init__(self, "cvs log -N -l")
    def _getTitle(self):
        return "_Log"
    def _getScriptTitle(self):
        return "cvs log for the selected files"
    def getResultDialogType(self):
        return "CVSTreeViewDialog"
    def getResultDialogIconType(self):
        if not self.notInRepository:           
            return gtk.STOCK_DIALOG_INFO
        else:
            return gtk.STOCK_DIALOG_WARNING
    def getResultDialogMessage(self):
        if self.notInRepository:
            message = "Showing logs for the CVS controlled files.\nSome directories were not under CVS control.\nCVS log command used: " + self.cvsCommand
        else:
            message = "Showing logs for the CVS controlled files.\nCVS log command used: " + self.cvsCommand
        if not self.recursive:
            message += "\nSubdirectories were ignored, use CVS Log Recursive to see logs for all subdirectories."            
        return message
    def getResultDialogTwoColumnsInTreeView(self):
        return True
    def getResultDialogSecondColumnTitle(self):
        return "Last revision committed (UTC)"
    def extraResultDialogWidgets(self):
        return ["status", "annotate", "diff"]
    def performOnCurrent(self, ignorePresence = False):
        self.pages = []
        self.fileToTest = {}
        self.notInRepository = False
        if len(self.currTestSelection) > 0:
            rootDir = self.getRootPath()
        for test in self.currTestSelection:
            testPath = os.path.realpath(test.getDirectory())
            if len(self.currFileSelection) == 0:
                files = testPath
            else:
                files = ""
                for file in self.currFileSelection:
                    filePath = os.path.join(testPath, file)
                    if ignorePresence or os.path.exists(filePath):
                        files += filePath + " "
            self.notify("Status", "Logging " + self.getRelativePath(testPath, rootDir))
            self.notify("ActionProgress", "")
            command = self.cvsCommand + " " + files
            stdin, stdouterr = os.popen4(command)
            self.parseOutput(stdouterr.readlines(), rootDir, test)
        
    def parseOutput(self, outputLines, rootDir, test):
        # The section for each file starts with
        # RCS file: ...
        # Working file: <file>
        # and ends with
        # ========================
        # To get the correct path in the treeview, we also
        # need to add the prefix to <file>
        currentOutput = ""
        currentFile = ""
        currentLastDate = ""
        now = datetime.datetime.utcnow()
        for line in outputLines:
            if line.find("there is no version here; do ") != -1:
                dir = prevLine[prevLine.find("in directory ") + 13:-2]
                relativeFilePath = self.getRelativePath(dir, rootDir)
                self.fileToTest[relativeFilePath] = test
                self.pages.append((relativeFilePath, "Not under CVS control.", "Not under CVS control."))
                self.notInRepository = True
            if line.startswith("==========") or line.startswith("cvs log: Logging"):
                continue
            if line.startswith("RCS file:"):
                if currentFile:
                    relativeFilePath = self.getRelativePath(currentFile, rootDir)
                    self.fileToTest[relativeFilePath] = test
                    self.pages.append((relativeFilePath, currentOutput, currentLastDate))
                    self.notify("Status", "Analyzing log for " + relativeFilePath.strip('\n'))
                    self.notify("ActionProgress", "")
                currentOutput = ""
                currentLastDate = ""                
            if line.startswith("Working file:"):
                currentFile = line[14:]
            if line.startswith("date:") and currentLastDate == "":
                then = datetime.datetime(*(time.strptime(line[6:25], "%Y/%m/%d %H:%M:%S")[0:6]))
                currentLastDate = plugins.getTimeDifference(now, then)
            currentOutput += line                
            prevLine = line
        if currentFile:
            relativeFilePath = self.getRelativePath(currentFile, rootDir)
            self.fileToTest[relativeFilePath] = test
            self.pages.append((relativeFilePath, currentOutput, currentLastDate))

class CVSLogRecursive(CVSLog):
    def __init__(self):
        CVSLog.__init__(self)
        self.cvsCommand = "cvs log -N"
        self.recursive = True
    def _getTitle(self):
        return "Log Recursive"
    def _getScriptTitle(self):
        return "recursive " + CVSLog._getScriptTitle(self)
    

class CVSDiff(CVSMultipleAction):
    def __init__(self, rev1 = "", rev2 = ""):
        CVSMultipleAction.__init__(self, "cvs diff -N -l")
        self.recursive = False
        self.revision1 = rev1
        self.revision2 = rev2
    def setRevisions(self, rev1, rev2):
        self.revision1 = rev1
        self.revision2 = rev2
    def _getTitle(self):
        return "_Difference"
    def _getScriptTitle(self):
        return "cvs diff for the selected files" 
    def getResultDialogType(self):
        return "CVSTreeViewDialog"
    def getResultDialogIconType(self):
        if len(self.pages) == 0 and not self.notInRepository:            
            return gtk.STOCK_DIALOG_INFO
        else:
            return gtk.STOCK_DIALOG_WARNING
    def getRevisionOptions(self):
        options = ""
        if self.revision1:
            options += " -r " + self.revision1
        if self.revision2:
            options += " -r " + self.revision2
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
    def getResultDialogMessage(self):
        if len(self.pages) > 0:
            if self.notInRepository:
                message = "Showing differences " + self.getRevisionMessage() + " for CVS controlled files.\nSome directories were not under CVS control.\nCVS command used: " + self.cvsCommand + self.getRevisionOptions()
            else:
                message = "Showing differences " + self.getRevisionMessage() + " for CVS controlled files.\nCVS command used: " + self.cvsCommand + self.getRevisionOptions()
        else:
            message = "All CVS controlled files are up-to-date and unmodified compared to the latest repository version."
        if not self.recursive:
            message += "\nSubdirectories were ignored, use CVS Difference Recursive to see differences for all subdirectories."
        return message
    def extraResultDialogWidgets(self):
        return ["status", "log", "annotate", "graphical_diff"]
    def performOnCurrent(self):
        self.pages = []
        self.fileToTest = {}
        self.notInRepository = False
        if len(self.currTestSelection) > 0:
            rootDir = self.getRootPath()
        for test in self.currTestSelection:
            testPath = os.path.realpath(test.getDirectory())
            if len(self.currFileSelection) == 0:
                files = testPath
            else:
                files = ""
                for file in self.currFileSelection:
                    filePath = os.path.join(testPath, file)
                    if os.path.exists(filePath):
                        files += filePath + " "
            self.notify("Status", "Diffing " + self.getRelativePath(testPath, rootDir))
            self.notify("ActionProgress", "")
            command = self.cvsCommand + self.getRevisionOptions() + " " + files
            stdin, stdouterr = os.popen4(command)            
            lines = stdouterr.readlines()
            self.parseOutput(lines, rootDir, test)

    def parseOutput(self, outputLines, rootDir, test):
        # The section for each file starts with
        # Index: <file>
        # ========================
        # RCS file: ...
        # To get the correct path in the treeview, we also
        # need to add the prefix to <file>
        currentOutput = ""
        currentFile = ""
        for line in outputLines:
            if line.find("there is no version here; do ") != -1:
                dir = prevLine[prevLine.find("in directory ") + 13:-2]
                relPath = self.getRelativePath(dir, rootDir)
                self.fileToTest[relPath] = test
                self.pages.append((relPath, "Not under CVS control.", ""))
                self.notInRepository = True
            if line.startswith("==========") or \
                   line.startswith("cvs diff: Diffing") or \
                   line.startswith("cvs diff: cannot find"):
                continue
            if line.startswith("Index:"):
                if currentFile:
                    relativeFilePath = self.getRelativePath(currentFile, rootDir)
                    self.fileToTest[relativeFilePath] = test
                    self.pages.append((relativeFilePath, currentOutput, currentFile))
                    self.notify("Status", "Analyzing differences for " + relativeFilePath.strip('\n'))
                    self.notify("ActionProgress", "")
                currentOutput = ""
                currentFile = line[7:].strip(" \n")
                continue
            currentOutput += line
            prevLine = line
        if currentFile:
            relPath = self.getRelativePath(currentFile, rootDir)
            self.fileToTest[relPath] = test
            self.pages.append((relPath, currentOutput, currentFile))

class CVSDiffRecursive(CVSDiff):
    def __init__(self):
        CVSDiff.__init__(self)
        self.cvsCommand = "cvs diff -N"
        self.recursive = True
    def _getTitle(self):
        return "Difference Recursive"
    def _getScriptTitle(self):
        return "recursive " + CVSDiff._getScriptTitle(self)


class CVSStatus(CVSMultipleAction):
    # Googled up.
    cvsWarningStates = [ "Locally Modified", "Locally Removed", "Locally Added" ]
    cvsErrorStates = [ "File had conflicts on merge", "Needs Checkout", "Unresolved Conflicts", "Needs Patch",
                       "Needs Merge", "Entry Invalid", "Unknown", "PROHIBITED" ]
    def __init__(self):
        CVSMultipleAction.__init__(self, "cvs status -l")
    def _getTitle(self):
        return "_Status"
    def _getScriptTitle(self):
        return "cvs status for the selected files"
    def getResultDialogType(self):
        return "CVSTreeViewDialog"
    def getResultDialogTwoColumnsInTreeView(self):
        return True
    def getResultDialogIconType(self):
        if self.needsAttention:            
            return gtk.STOCK_DIALOG_WARNING
        else:
            return gtk.STOCK_DIALOG_INFO
    def getResultDialogMessage(self):
        if self.needsAttention:
            message = "CVS status found files which are not up-to-date or which have conflicts, or\ndirectories which are not under CVS control."
        else:
            message = "CVS status shown below."
        message += "\nCVS command used: " + self.cvsCommand
        if not self.recursive:
            message += "\nSubdirectories were ignored, use CVS Status Recursive to get the status for all subdirectories."
        return message
    def extraResultDialogWidgets(self):
        return ["log", "annotate", "diff"]
    def performOnCurrent(self):
        self.pages = []
        self.fileToTest = {}
        self.needsAttention = False
        if len(self.currTestSelection) > 0:
            rootDir = self.getRootPath()
            cvsRepository = self.getCVSRepository(self.getApplicationPath())
        for test in self.currTestSelection:
            testPath = os.path.realpath(test.getDirectory())
            if len(self.currFileSelection) == 0:
                files = testPath
            else:
                files = ""
                for file in self.currFileSelection:
                    filePath = os.path.join(testPath, file)
                    if os.path.exists(filePath):
                        files += filePath + " "
            self.notify("Status", "Getting status for " + self.getRelativePath(testPath, rootDir))
            self.notify("ActionProgress", "")
            cvsCommand = self.cvsCommand + " " + files
            stdin, stdouterr = os.popen4(cvsCommand)
            outputLines = stdouterr.readlines()
            self.parseOutput(outputLines, rootDir, cvsRepository, test)
    def parseOutput(self, outputLines, rootDir, cvsRepository, test):
        # The section for each dir starts with
        # cvs status: Examining <dir>
        # ========================
        # RCS file: ...
        # To get the correct path in the treeview, we also
        # need to add the prefix to <file>
        currentOutput = ""
        currentFile = ""
        currentDir = ""
        for line in outputLines:
            if line.startswith("cvs status: Examining "):
                currentDir = line[22:].strip(" \n")
                continue
            if line.startswith("File: "):
                spaceAfterNamePos = line.find("\t", 7)
                info = line[spaceAfterNamePos:].replace("Status: ", "").strip(" \n\t")
                if info in self.cvsWarningStates:
                    info = "<span weight='bold'>" + info + "</span>"
                elif info in self.cvsErrorStates:
                    info = "<span weight='bold' foreground='red'>" + info + "</span>"
                    self.needsAttention = True
            # It is a bit hackish to find the file via the repository, but
            # unfortunately cvs status doesn't output the proper filename ...
            if line.find("Repository revision:") != -1:
                if line.find("No revision control file") == -1:
                    currentFile = line.strip(" \n\t").replace(",v", "").replace(cvsRepository, "###")
                    currentFile = currentFile[currentFile.find("###"):].replace("###", "")                
                    currentFile = os.path.join(rootDir, currentFile)
                else:
                    currentFile = ""
            if line.find("there is no version here; do ") != -1:
                dir = prevLine[prevLine.find("in directory ") + 13:-2]
                self.fileToTest[self.getRelativePath(dir, rootDir)] = test
                self.pages.append((self.getRelativePath(dir, rootDir), prevLine + line, "<span weight='bold'>Not under CVS control.</span>"))
                self.needsAttention = True
            if line.startswith("==============="):
                if currentFile:
                    relativeFilePath = self.getRelativePath(currentFile, rootDir)
                    self.fileToTest[relativeFilePath] = test
                    self.pages.append((relativeFilePath, currentOutput, info))
                    self.notify("Status", "Analyzing status for " + relativeFilePath.strip('\n'))
                    self.notify("ActionProgress", "")
                currentOutput = ""
                info = ""
                continue
            currentOutput += line
            prevLine = line
        if currentFile:
            self.fileToTest[self.getRelativePath(currentFile, rootDir)] = test
            self.pages.append((self.getRelativePath(currentFile, rootDir), currentOutput, info))    

class CVSStatusRecursive(CVSStatus):
    def __init__(self):
        CVSStatus.__init__(self)
        self.cvsCommand = "cvs status"
        self.recursive = True
    def _getTitle(self):
        return "Status Recursive"
    def _getScriptTitle(self):
        return "recursive " + CVSStatus._getScriptTitle(self)


class CVSAnnotate(CVSMultipleAction):
    def __init__(self):
        CVSMultipleAction.__init__(self, "cvs annotate -l")
    def _getTitle(self):
        return "A_nnotate"
    def _getScriptTitle(self):
        return "cvs annotate for the selected files"
    def getResultDialogIconType(self):
        if not self.notInRepository:           
            return gtk.STOCK_DIALOG_INFO
        else:
            return gtk.STOCK_DIALOG_WARNING
    def getResultDialogMessage(self):
        message = "CVS annotations shown below."
        if self.notInRepository:
            message += "\nSome directories were not under CVS control."
        message += "\nCVS command used: " + self.cvsCommand
        if not self.recursive:
            message += "\nSubdirectories were ignored, use CVS Annotate Recursive to get the annotations for all subdirectories."
        return message
    def extraResultDialogWidgets(self):
        return ["log", "status", "diff"]
    def performOnCurrent(self):
        self.pages = []
        self.fileToTest = {}
        self.notInRepository = False
        self.needsAttention = False
        if len(self.currTestSelection) > 0:
            rootDir = self.getRootPath()
        for test in self.currTestSelection:
            testPath = os.path.realpath(test.getDirectory())
            if len(self.currFileSelection) == 0:
                files = testPath
            else:
                files = ""
                for file in self.currFileSelection:
                    filePath = os.path.join(testPath, file)
                    if os.path.exists(filePath):
                        files += filePath + " "
            self.notify("Status", "Getting annotations of " + self.getRelativePath(testPath, rootDir))
            self.notify("ActionProgress", "")
            command = self.cvsCommand + " " + files
            stdin, stdouterr = os.popen4(command)
            self.parseOutput(stdouterr.readlines(), rootDir, test)            
    def parseOutput(self, outputLines, rootDir, test):
        # The section for each file starts with
        # Annotations for <file>
        # ***************
        currentOutput = ""
        currentFile = ""
        for line in outputLines:
            if line.find("there is no version here; do ") != -1:
                dir = prevLine[prevLine.find("in directory ") + 13:-2]
                relPath = self.getRelativePath(dir, rootDir)
                self.fileToTest[relPath] = test
                self.pages.append((relPath, "Not under CVS control", ""))
                self.notInRepository = True
            if line.startswith("Annotations for"):                
                if currentFile:
                    relativeFilePath = self.getRelativePath(currentFile, rootDir)                    
                    self.fileToTest[relativeFilePath] = test
                    self.pages.append((relativeFilePath, currentOutput, currentFile))
                    self.notify("Status", "Analyzing annotations of " + relativeFilePath.strip('\n'))
                    self.notify("ActionProgress", "")
                currentOutput = ""
                currentFile = line[16:]
            currentOutput += line
            prevLine = line
        if currentFile:
            relPath = self.getRelativePath(currentFile, rootDir)
            self.fileToTest[relPath] = test
            self.pages.append((relPath, currentOutput, currentFile))

class CVSAnnotateRecursive(CVSAnnotate):
    def __init__(self):
        CVSAnnotate.__init__(self)
        self.cvsCommand = "cvs annotate"
        self.recursive = True
    def _getTitle(self):
        return "Annotate Recursive"
    def _getScriptTitle(self):
        return "recursive " + CVSAnnotate._getScriptTitle(self)


#
# 2 - Then the methods which update from repository.
#

    
class CVSUpdate(CVSMultipleAction):
    def __init__(self):
        CVSMultipleAction.__init__(self, "cvs -qn up -l")
    def _getTitle(self):
        return "_Update (non-modifying)"
    def _getScriptTitle(self):
        return "cvs update  (non-modifying)  for the selected files"
    def getResultDialogIconType(self):
        if self.hasConflicts:            
            return gtk.STOCK_DIALOG_WARNING
        else:
            return gtk.STOCK_DIALOG_INFO        
    def getResultDialogMessage(self):
        if len(self.pages) > 0:
            if self.hasConflicts:
                message = "CVS update encountered conflicts, details shown below."
            else:
                message = "Non-modifying CVS update output shown below."
        else:
            message = "All files are up-to-date."
        message += "\nCVS command used: " + self.cvsCommand
        if not self.recursive:
            message += "\nSubdirectories were ignored, use CVS Update Recursive to update all subdirectories."
        if len(self.pages) > 0:
            message += "\n\nOBSERVE: No files have actually been updated!\n"
        return message
    def getResultDialogTwoColumnsInTreeView(self):
        return self.hasConflicts
    def performOnCurrent(self):
        self.pages = []
        self.hasConflicts = False
        if len(self.currTestSelection) > 0:
            rootDir = self.getRootPath()
        for test in self.currTestSelection:
            self.performOnSingle(test, rootDir)
    def performOnSingle(self, test, rootDir):
        dir = os.path.realpath(test.getDirectory())                
        self.notify("Status", "Updating " + self.getRelativePath(dir, rootDir))
        self.notify("ActionProgress", "")
        cvsCommand = self.cvsCommand + " " + dir
        stdin, stdouterr = os.popen4(cvsCommand)
        outputLines = stdouterr.readlines()
        # Making paths relative to rootDir makes output much more readable ...
        # (And we have a lot less data to parse here than e.g. when logging)
        outputLines = map(lambda l: l.replace(rootDir, "").replace(" " + os.sep, " "), outputLines)
        info = ""
        for line in outputLines:
            # Dirs not under CVS control gives no output for cvs up, unfortunately
            if line.startswith("C "):
                self.hasConflicts = True
                info = "Conflicts"
                break
            prevLine = line
        if len(outputLines) > 0:
            self.pages.append((self.getRelativePath(dir, rootDir), "".join(outputLines), info))

class CVSUpdateRecursive(CVSUpdate):
    def __init__(self):
        CVSUpdate.__init__(self)
        self.cvsCommand = "cvs -qn up"
        self.recursive = True
    def _getTitle(self):
        return "Update Recursive (non-modifying)"
    def _getScriptTitle(self):
        return "recursive " + CVSUpdate._getScriptTitle(self)


#
# Register cvs plugin at TextTest GUI 
#
texttestgui.pluginHandler.modules.append("cvs")

#
# Add actions to static action list.
#
guiplugins.interactiveActionHandler.addMenu("CVS")
guiplugins.interactiveActionHandler.actionStaticClasses.append(CVSLog)
guiplugins.interactiveActionHandler.actionStaticClasses.append(CVSLogRecursive)
guiplugins.interactiveActionHandler.actionStaticClasses.append(CVSDiff)
guiplugins.interactiveActionHandler.actionStaticClasses.append(CVSDiffRecursive)
guiplugins.interactiveActionHandler.actionStaticClasses.append(CVSStatus)
guiplugins.interactiveActionHandler.actionStaticClasses.append(CVSStatusRecursive)
guiplugins.interactiveActionHandler.actionStaticClasses.append(CVSAnnotate)
guiplugins.interactiveActionHandler.actionStaticClasses.append(CVSAnnotateRecursive)
#guiplugins.interactiveActionHandler.actionStaticClasses.append(CVSUpdate)
#guiplugins.interactiveActionHandler.actionStaticClasses.append(CVSUpdateRecursive)

#
# Add appropriate actions also to dynamic action list.
#
guiplugins.interactiveActionHandler.actionDynamicClasses.append(CVSLog)
guiplugins.interactiveActionHandler.actionDynamicClasses.append(CVSLogRecursive)
guiplugins.interactiveActionHandler.actionDynamicClasses.append(CVSDiff)
guiplugins.interactiveActionHandler.actionDynamicClasses.append(CVSDiffRecursive)
guiplugins.interactiveActionHandler.actionDynamicClasses.append(CVSStatus)
guiplugins.interactiveActionHandler.actionDynamicClasses.append(CVSStatusRecursive)
guiplugins.interactiveActionHandler.actionDynamicClasses.append(CVSAnnotate)
guiplugins.interactiveActionHandler.actionDynamicClasses.append(CVSAnnotateRecursive)

#
#
# Only dialogs and their utilities below.
#
#
    
class CVSTreeViewDialog(guidialogs.ActionResultDialog):
    def __init__(self, parent, okMethod, plugin, extraButtons = []):
        guidialogs.ActionResultDialog.__init__(self, parent, okMethod, plugin)        
        
    def isModal(self):
        return False
    
    def addContents(self):
        self.vbox = gtk.VBox()
        self.addExtraWidgets()
        self.addHeader()
        self.addTreeView()

    def addExtraWidgets(self):
        self.extraWidgetArea = gtk.HBox()
        self.extraButtonArea = gtk.HButtonBox()
        self.extraWidgetArea.pack_start(self.extraButtonArea, expand=False, fill=False)        
        if len(self.plugin.pages) > 0:
            padding = gtk.Alignment()
            padding.set_padding(3, 3, 3, 3)
            padding.add(self.extraWidgetArea)
            self.dialog.vbox.pack_end(padding, expand=False, fill=False)
            extraWidgetsToShow = self.plugin.extraResultDialogWidgets()
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
        scriptEngine.connect("show CVS status", "clicked", button, self.viewStatus)
        self.extraButtonArea.pack_start(button, expand=False, fill=False)        

    def addLogWidget(self):
        button = gtk.Button("_Log")
        scriptEngine.connect("show CVS log", "clicked", button, self.viewLog)
        self.extraButtonArea.pack_start(button, expand=False, fill=False)        

    def addAnnotateWidget(self):
        button = gtk.Button("_Annotate")
        scriptEngine.connect("show CVS annotations", "clicked", button, self.viewAnnotations)
        self.extraButtonArea.pack_start(button, expand=False, fill=False)        

    def addDiffWidget(self):
        diffButton = gtk.Button("_Differences")
        label1 = gtk.Label(" between revisions ")
        label2 = gtk.Label(" and ")
        self.revision1 = gtk.Entry()
        self.revision1.set_text("HEAD")
        self.revision2 = gtk.Entry()
        self.revision1.set_alignment(1.0)
        self.revision2.set_alignment(1.0)
        self.revision1.set_width_chars(6)
        self.revision2.set_width_chars(6)
        scriptEngine.registerEntry(self.revision1, "set first revision to ")
        scriptEngine.registerEntry(self.revision2, "set second revision to ")
        self.extraButtonArea.pack_start(diffButton, expand=False, fill=False)
        self.extraWidgetArea.pack_start(label1, expand=False, fill=False)
        self.extraWidgetArea.pack_start(self.revision1, expand=False, fill=False)
        self.extraWidgetArea.pack_start(label2, expand=False, fill=False)
        self.extraWidgetArea.pack_start(self.revision2, expand=False, fill=False)
        scriptEngine.connect("show CVS diffs", "clicked", diffButton, self.viewDiffs)

    def addGraphicalDiffWidget(self):
        button = gtk.Button("_Graphical Diffs")
        scriptEngine.connect("show CVS differences graphically", "clicked", button, self.viewGraphicalDiff)
        self.extraButtonArea.pack_start(button, expand=False, fill=False)        

    def viewStatus(self, button):
        file = self.treeModel.get_value(self.treeView.get_selection().get_selected()[1], 3)
        self.plugin.viewStatus(file, self)

    def viewLog(self, button):
        file = self.treeModel.get_value(self.treeView.get_selection().get_selected()[1], 3)
        self.plugin.viewLog(file,self)

    def viewAnnotations(self, button):
        file = self.treeModel.get_value(self.treeView.get_selection().get_selected()[1], 3)
        self.plugin.viewAnnotations(file, self)

    def viewDiffs(self, button):
        file = self.treeModel.get_value(self.treeView.get_selection().get_selected()[1], 3)
        self.plugin.viewDiffs(file,
                              self.revision1.get_text(),
                              self.revision2.get_text(), self)

    def viewGraphicalDiff(self, button):
        file = self.treeModel.get_value(self.treeView.get_selection().get_selected()[1], 2)
        self.plugin.viewGraphicalDiffs(file, self)

    def addHeader(self):
        title = self.plugin.getResultDialogTitle()
        self.dialog.set_title(title)
        message = self.plugin.getResultDialogMessage()
        guilog.info("Showing CVS tree view dialog '" + title + "' with header\n" + message)
        if message:
            hbox = gtk.HBox()
            hbox.pack_start(self.getIcon(), expand=False, fill=False)
            hbox.pack_start(gtk.Label(message), expand=False, fill=False)        
            alignment = gtk.Alignment()
            alignment.set(0.0, 1.0, 1.0, 1.0)
            alignment.set_padding(5, 5, 0, 5)
            alignment.add(hbox)
            self.vbox.pack_start(alignment, expand=False, fill=False)

    def getIcon(self):
        iconType = self.plugin.getResultDialogIconType()
        guilog.info("CVS tree view dialog: Using icon: " + repr(iconType))
        return self.getStockIcon(iconType)

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

        self.createTreeView()
        window1 = gtk.ScrolledWindow()
        window1.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
        window1.add(self.treeView)
        hpaned.pack1(window1, False, True)

        if len(self.plugin.pages) > 0:
            parentSize = self.parent.get_size()
            self.dialog.resize(parentSize[0], int(parentSize[0] / 1.5))
            self.vbox.pack_start(hpaned, expand=True, fill=True)
        self.dialog.vbox.pack_start(self.vbox, expand=True, fill=True)

    def createTreeView(self):
        # Columns are: 0 - Tree node name
        #              1 - Content (CVS output) for the corresponding file
        #              2 - Info. If the plugin wants to show two columns, this
        #                  is shown in the second column. If not, ignore.
        #              3 - Entire path of the node. Created here, used primarily
        #                  to distinguish leaf nodes with the same name in TreeModelIndexer.
        self.treeModel = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING,
                                       gobject.TYPE_STRING, gobject.TYPE_STRING)
        labelMap = {}
        for label, content, info in self.plugin.pages:
            utfContent = plugins.encodeToUTF(plugins.decodeText(content))
            path = label.split(os.sep)
            currentPath = ""
            previousPath = ""
            for element in path:
                previousPath = currentPath
                currentPath = os.path.join(currentPath, element)
                currentInfo = ""
                if currentPath == label:
                    currentInfo = info
                if not labelMap.has_key(currentPath):
                    if labelMap.has_key(previousPath):
                        guilog.info("CVS tree view dialog: Adding " + currentPath + " as child of " + previousPath + ", info " + info)
                        labelMap[currentPath] = self.treeModel.append(labelMap[previousPath], (element.strip("\n"), utfContent, currentInfo, currentPath.strip(" \n")))
                    else:
                        guilog.info("CVS tree view dialog: Adding " + currentPath + " as root, info " + info)
                        labelMap[currentPath] = self.treeModel.append(None, (element.strip("\n"), utfContent, currentInfo, currentPath.strip(" \n")))

        self.treeView = gtk.TreeView(self.treeModel)
        self.treeView.set_enable_search(False)
        fileRenderer = gtk.CellRendererText()
        fileColumn = gtk.TreeViewColumn("File", fileRenderer, text=0)
        fileColumn.set_cell_data_func(fileRenderer, texttestgui.renderParentsBold)
        self.treeView.append_column(fileColumn)
        self.treeView.set_expander_column(fileColumn)
        if self.plugin.getResultDialogTwoColumnsInTreeView():
            infoRenderer = gtk.CellRendererText()
            infoColumn = gtk.TreeViewColumn(self.plugin.getResultDialogSecondColumnTitle(), infoRenderer, markup=2)
            self.treeView.append_column(infoColumn)
            guilog.info("CVS tree view dialog: Showing two columns")
        self.treeView.get_selection().connect("changed", self.showOutput)
        self.treeView.get_selection().set_select_function(self.canSelect)
        self.treeView.expand_all()
        scriptEngine.monitor("select", self.treeView.get_selection(), TreeModelIndexer(self.treeModel, fileColumn, 3), noImplies = True)
        if len(self.plugin.pages) > 0:
            self.treeView.get_selection().select_iter(labelMap[self.plugin.pages[0][0]])
            
    def showOutput(self, selection):
        model, iter = selection.get_selected()
        if iter:
            self.extraWidgetArea.set_sensitive(True)
            text = model.get_value(iter, 1)
            self.textBuffer.set_text(text)
            guilog.info("CVS tree view dialog: Showing CVS output\n" + text)
        else:
            self.extraWidgetArea.set_sensitive(False)

    def canSelect(self, path):
        return not self.treeModel.iter_has_child(self.treeModel.get_iter(path))
