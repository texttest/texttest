
import gtk, version_control, default_gui, guiplugins, plugins, datetime, shutil, time, os
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


class CVSInterface(version_control.VersionControlInterface):
    def __init__(self, cvsDir):
        # Googled up.
        cvsWarningStates = [ "Locally Modified", "Locally Removed", "Locally Added" ]
        cvsErrorStates = [ "File had conflicts on merge", "Needs Checkout", "Unresolved Conflicts", "Needs Patch",
                           "Needs Merge", "Entry Invalid", "Unknown", "PROHIBITED" ]
        version_control.VersionControlInterface.__init__(self, cvsDir, "CVS", cvsWarningStates, cvsErrorStates, "HEAD")
        self.defaultArgs["log"] = [ "-N" ]
        self.defaultArgs["diff"] = [ "-N" ]
        self.recursiveSettings["add"] = (True, True)
        self.programArgs, self.errorMessage = self.setProgramArgs(cvsDir)

    def getProgramArgs(self):
        if self.errorMessage:
            raise plugins.TextTestError, self.errorMessage
        else:
            return self.programArgs
    
    def setProgramArgs(self, cvsDir):
        cvsRoot = os.getenv("CVSROOT")
        if cvsRoot:
            return [ "cvs" ], ""
        else:
            rootFile = os.path.join(cvsDir, "Root")
            if os.path.isfile(rootFile):
                cvsRoot = self.getCvsRootFromFile(rootFile)
                return [ "cvs", "-d", cvsRoot ], ""
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
    
    def getCombinedRevisionOptions(self, r1, r2):
        return [ "-r", r1, "-r", r2 ]

    # Move in source control also. In CVS this implies a remove and then an add
    def moveDirectory(self, oldDir, newDir):
        if os.path.isdir(os.path.join(oldDir, "CVS")):
            self.copyDirectory(oldDir, newDir)
            self.remove(oldDir)
            self.callProgramOnFiles("add", newDir, cwd=os.path.dirname(newDir)) # Just so we can find the CVS dirs in traffic mechanism..
        else:
            os.rename(oldDir, newDir)

    def copyDirectory(self, oldDir, newDir):
        shutil.copytree(oldDir, newDir)
        self.cleanControlDirs(newDir)

    def remove(self, oldDir):
        self.callProgram([ "rm", "-f", oldDir ])
        if os.path.isdir(oldDir):
            # CVS doesn't remove files it doesn't control, finish the job for it
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
        

     
class CVSLogLatest(version_control.LogGUI):
    def __init__(self, *args):
        version_control.LogGUI.__init__(self, *args)
        self.cmdName = "log"
    def getExtraArgs(self):
        return [ "-rHEAD" ]
    def _getTitle(self):
        return "Log Latest"
    def getResultDialogMessage(self):
        cmdArgs = self.vcs.getCmdArgs(self.cmdName, self.getExtraArgs())
        message = "Showing latest log entries for the CVS controlled files.\nCVS command used: " + " ".join(cmdArgs)
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

version_control.VersionControlDialogGUI.vcsClass = CVSInterface
            
#
# Configuration for the Interactive Actions
#
class InteractiveActionConfig(version_control.InteractiveActionConfig):
    def getInteractiveActionClasses(self, dynamic):
        return version_control.InteractiveActionConfig.getInteractiveActionClasses(self, dynamic) + [ CVSLogLatest ]
    
