import sys
import datetime
import shutil
import time
import os
from collections import OrderedDict
from gi.repository import Gtk
from texttestlib import plugins
from .. import guiutils
from . import vcs_independent

#
# Todo/improvements:
#
# + Multiple dialogs confuses StoryText - close doesn't work correctly, for example ..
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


class CVSInterface(vcs_independent.VersionControlInterface):
    def __init__(self, cvsDir):
        # Googled up.
        cvsWarningStates = ["Locally Modified", "Locally Removed", "Locally Added"]
        cvsErrorStates = ["File had conflicts on merge", "Needs Checkout", "Unresolved Conflicts", "Needs Patch",
                          "Needs Merge", "Entry Invalid", "Unknown", "PROHIBITED"]
        vcs_independent.VersionControlInterface.__init__(self, cvsDir, "CVS", cvsWarningStates, cvsErrorStates, "HEAD")
        self.defaultArgs["log"] = ["-N"]
        self.defaultArgs["diff"] = ["-N"]
        self.defaultArgs["rm"] = ["-f"]
        self.defaultArgs["update"] = ["-dP"]
        self.programArgs, self.errorMessage = self.setProgramArgs(cvsDir)

    def getProgramArgs(self):
        if self.errorMessage:
            raise plugins.TextTestError(self.errorMessage)
        else:
            return self.programArgs

    def setProgramArgs(self, cvsDir):
        cvsRoot = os.getenv("CVSROOT")
        if cvsRoot:
            return ["cvs", "-q"], ""
        else:
            rootFile = os.path.join(cvsDir, "Root")
            if os.path.isfile(rootFile):
                cvsRoot = self.getCvsRootFromFile(rootFile)
                return ["cvs", "-q", "-d", cvsRoot], ""
            else:
                return [], "Could not determine $CVSROOT: environment variable not set and no file present at:\n" + rootFile

    def getCvsRootFromFile(self, rootFile):
        info = open(rootFile).read()
        return info.strip().rstrip(os.sep)

    def getDateFromLog(self, output):
        for line in output.splitlines():
            if line.startswith("date:"):
                return datetime.datetime(*(self.parseCvsDateTime(line[6:25])[0:6]))

    def parseCvsDateTime(self, input):
        # Different CVS versions produce different formats...
        try:
            return time.strptime(input, "%Y/%m/%d %H:%M:%S")
        except ValueError:
            return time.strptime(input, "%Y-%m-%d %H:%M:%S")

    def getStateFromStatus(self, output):
        for line in output.splitlines():
            if line.startswith("File: "):
                spaceAfterNamePos = line.find("\t", 7)
                return line[spaceAfterNamePos:].replace("Status: ", "").strip(" \n\t")

    def isVersionControlled(self, path):
        if os.path.isdir(path):
            return os.path.isdir(os.path.join(path, "CVS"))
        else:
            return vcs_independent.VersionControlInterface.isVersionControlled(self, path)

    # Move in source control also. In CVS this implies a remove and then an add
    def _movePath(self, oldPath, newPath):
        self.checkInstalled()  # throws if it isn't, avoid moving paths around
        self.copyPath(oldPath, newPath)
        self.removePath(oldPath)
        self.callProgramOnFiles("add", newPath, recursive=True)

    def getMoveCommand(self):
        return "cvs rm' and 'cvs add"

    def copyPath(self, oldPath, newPath):
        createNewDir = os.path.isdir(oldPath) and not os.path.exists(newPath)
        vcs_independent.VersionControlInterface.copyPath(self, oldPath, newPath)
        if createNewDir:
            self.cleanControlDirs(newPath)

    def removePath(self, path):
        if os.path.isdir(path):
            retCode = self.callProgram("rm", [path])
        else:
            # removing a file affects the directory it lives in, whereas removing a directory shouldn't
            # affect the parent...
            retCode = self.callProgram("rm", [path], cwd=os.path.dirname(path))
        if retCode > 0:
            # Wasn't in version control, probably
            return plugins.removePath(path)
        else:
            self.cleanUnknownFiles(path)
            return True

    def cleanUnknownFiles(self, oldDir):
        for root, dirs, files in os.walk(oldDir):
            if "CVS" in dirs:
                dirs.remove("CVS")
            for file in files:
                os.remove(os.path.join(root, file))

    def cleanControlDirs(self, newDir):
        for root, dirs, files in os.walk(newDir):
            if "CVS" in dirs:
                dirs.remove("CVS")
                shutil.rmtree(os.path.join(root, "CVS"))

    # CVS add doesn't implicitly add directories, and it modifies its control dirs which are spread
    # throughout the tree (hence we need to change cwd so our traffic mechanism picks this up when testing)
    def callProgramOnFiles(self, cmdName, fileArg, recursive=False, extraArgs=[], **kwargs):
        if cmdName == "add":
            basicArgs = self.getCmdArgs(cmdName, extraArgs)
            for fileName in self.getFileNames(fileArg, recursive, includeDirs=True):
                self.callProgramWithHandler(fileName, basicArgs + [fileName], cwd=os.path.dirname(fileName), **kwargs)
        else:
            vcs_independent.VersionControlInterface.callProgramOnFiles(
                self, cmdName, fileArg, recursive, extraArgs, **kwargs)


class CVSLogLatest(vcs_independent.LogGUI):
    def __init__(self, *args):
        vcs_independent.LogGUI.__init__(self, *args)
        self.cmdName = "log"

    def getExtraArgs(self):
        return ["-rHEAD"]

    def _getTitle(self):
        return "Log Latest"

    def getResultDialogMessage(self):
        cmdArgs = vcs_independent.vcs.getCmdArgs(self.cmdName, self.getExtraArgs())
        message = "Showing latest log entries for the CVS controlled files.\nCVS command used: " + " ".join(cmdArgs)
        if not self.recursive:
            message += "\nSubdirectories were ignored."
        return message

    def storeResult(self, fileName, output, test):
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
        self.pages = OrderedDict()
        self.runAndParse()
        self.vbox = Gtk.VBox()
        self.addHeader()
        self.addNotebook()

    def addHeader(self):
        message = self.getResultDialogMessage()
        if message:
            hbox = Gtk.HBox()
            icon = Gtk.STOCK_DIALOG_INFO
            hbox.pack_start(self.getStockIcon(icon), False, False, 0)
            hbox.pack_start(Gtk.Label(message), False, False, 0)
            alignment = Gtk.Alignment.new(0.0, 1.0, 1.0, 1.0)
            alignment.set_padding(5, 5, 0, 5)
            alignment.add(hbox)
            self.vbox.pack_start(alignment, False, False, 0)

    def addNotebook(self):
        notebook = Gtk.Notebook()
        notebook.set_scrollable(True)
        notebook.popup_enable()
        for label, content in list(self.pages.items()):
            buffer = Gtk.TextBuffer()
            # Encode to UTF-8, necessary for Gtk.TextView
            buffer.set_text(content)
            textView = Gtk.TextView.new_with_buffer(buffer)
            textView.set_editable(False)
            window = Gtk.ScrolledWindow()
            window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            window.add(textView)
            notebook.append_page(window, Gtk.Label(label=label))
        notebook.show_all()
        if len(notebook.get_children()) > 0:  # Resize to a nice-looking dialog window ...
            parentSize = self.topWindow.get_size()
            self.dialog.resize(int(parentSize[0] / 1.5), int(parentSize[0] / 2))
        self.vbox.pack_start(notebook, True, True, 0)
        self.dialog.vbox.pack_start(self.vbox, True, True, 0)


vcs_independent.vcsClass = CVSInterface


class RenameTest(vcs_independent.RenameTest):
    def handleExistingDirectory(self, dir):
        if os.listdir(dir) == ["CVS"]:
            # There is only a CVS control dir, i.e. it's probably been removed in CVS.
            # Revert it in CVS and continue
            shutil.rmtree(dir)
            dirname, local = os.path.split(dir)
            vcs_independent.vcs.callProgram("update", [local], cwd=dirname)
        else:
            vcs_independent.RenameTest.handleExistingDirectory(self, dir)


class FilteredDiffGUI(vcs_independent.FilteredDiffGUI):
    def __init__(self, *args):
        vcs_independent.FilteredDiffGUI.__init__(self, *args)
        self.cmdName = "update"

    def getTmpFileArgs(self, fileName, revision):
        revArgs = vcs_independent.vcs.getSingleRevisionOptions(revision) if revision else []
        return ["-p"] + revArgs + [fileName]

    def commandHadError(self, retcode, stderr, stdout):
        # Diff returns an error code for differences, not just for errors
        return retcode or (len(stderr) > 0 and len(stdout) == 0)


class FilteredDiffGUIRecursive(FilteredDiffGUI):
    recursive = True

#
# Configuration for the Interactive Actions
#


class InteractiveActionConfig(vcs_independent.InteractiveActionConfig):
    def diffClasses(self):
        return [vcs_independent.DiffGUI, vcs_independent.DiffGUIRecursive, FilteredDiffGUI, FilteredDiffGUIRecursive]

    def getInteractiveActionClasses(self, dynamic):
        return vcs_independent.InteractiveActionConfig.getInteractiveActionClasses(self, dynamic) + [CVSLogLatest]

    def getRenameTestClass(self):
        return RenameTest
