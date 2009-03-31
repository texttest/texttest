
import gtk, guiplugins, plugins, texttest_version, os, string, sys, glob
from guiplugins import scriptEngine, ActionResultDialogGUI

# Show useful info about TextTest.
# I don't particularly like the standard gtk.AboutDialog, and we also want
# to show pygtk/gtk/python versions in our dialog, so we create our own ...
class AboutTextTest(guiplugins.ActionResultDialogGUI):
    def getDialogTitle(self):
        return "About TextTest"
    def isActiveOnCurrent(self, *args):
        return True
    def _getStockId(self):
        return "about"
    def _getTitle(self):
        return "_About TextTest"
    def messageAfterPerform(self):
        return ""
    def getTooltip(self):
        return "show information about texttest"
    
    def createButtons(self):        
        self.creditsButton = self.dialog.add_button('texttest-stock-credits', gtk.RESPONSE_NONE)
        self.licenseButton = self.dialog.add_button('_License', gtk.RESPONSE_NONE)
        self.versionsButton = self.dialog.add_button('_Versions', gtk.RESPONSE_NONE)
        guiplugins.scriptEngine.connect("press credits", "clicked", self.creditsButton, self.showCredits)
        guiplugins.scriptEngine.connect("press license", "clicked", self.licenseButton, self.showLicense)
        guiplugins.scriptEngine.connect("press versions", "clicked", self.versionsButton, self.showVersions)
        guiplugins.ActionResultDialogGUI.createButtons(self)
        
    def addContents(self):
        logo = gtk.Image()
        logo.set_from_pixbuf(gtk.gdk.pixbuf_new_from_file(
            os.path.join(plugins.installationDir("images"), "texttest-logo.gif")))
        logoFrame = gtk.Alignment(0.5, 0.5, 0.0, 0.0)
        logoFrame.set_padding(10, 10, 10, 10)
        logoFrame.add(logo)
        mainLabel = gtk.Label()
        mainLabel.set_markup("<span size='xx-large'>TextTest " + texttest_version.version + "</span>\n")
        messageLabel = gtk.Label()
        message = "TextTest is an application-independent tool for text-based\nfunctional testing. This means running a batch-mode program\nin lots of different ways, and using the text output produced\nas a means of controlling the behaviour of that application."
        messageLabel.set_markup("<i>" + message + "</i>\n")
        messageLabel.set_justify(gtk.JUSTIFY_CENTER)
        urlLabel = gtk.Label()
        urlLabel.set_markup("<span foreground='blue' underline='single'>http://www.texttest.org/</span>\n")
        urlLabel.set_selectable(True)
        licenseLabel = gtk.Label()
        licenseLabel.set_markup("<span size='small'>Copyright " + u'\xa9' + " The authors</span>\n")
        self.dialog.vbox.pack_start(logoFrame, expand=False, fill=False)
        self.dialog.vbox.pack_start(mainLabel, expand=True, fill=True)
        self.dialog.vbox.pack_start(messageLabel, expand=False, fill=False)
        self.dialog.vbox.pack_start(urlLabel, expand=False, fill=False)
        self.dialog.vbox.pack_start(licenseLabel, expand=False, fill=False)
        self.dialog.set_resizable(False)
        return message

    def showCredits(self, *args):
        newDialog = CreditsDialog(self.dialog, self.validApps)
        newDialog.performOnCurrent()

    def showLicense(self, *args):
        newDialog = LicenseDialog(self.dialog, self.validApps)
        newDialog.performOnCurrent()

    def showVersions(self, *args):
        newDialog = ShowVersions(self.validApps)
        newDialog.performOnCurrent()

class ShowVersions(guiplugins.ActionResultDialogGUI):
    def isActiveOnCurrent(self, *args):
        return True
    def _getTitle(self):
        return "Component _Versions"
    def messageAfterPerform(self):
        return ""
    def getTooltip(self):
        return "show component version information"

    def getDialogTitle(self):
        return "Version Information"
    
    def addContents(self):
        textTestVersion = texttest_version.version
        pythonVersion = ".".join(map(lambda l: str(l), sys.version_info))
        gtkVersion = ".".join(map(lambda l: str(l), gtk.gtk_version))
        pygtkVersion = ".".join(map(lambda l: str(l), gtk.pygtk_version))
        
        table = gtk.Table(4, 2, homogeneous=False)
        table.set_row_spacings(1)
        table.attach(self.justify("TextTest:", 0.0), 0, 1, 0, 1, xoptions=gtk.FILL, xpadding=1)
        table.attach(self.justify("Python:", 0.0), 0, 1, 1, 2, xoptions=gtk.FILL, xpadding=1)
        table.attach(self.justify("GTK:", 0.0), 0, 1, 2, 3, xoptions=gtk.FILL, xpadding=1)
        table.attach(self.justify("PyGTK:", 0.0), 0, 1, 3, 4, xoptions=gtk.FILL, xpadding=1)
        table.attach(self.justify(textTestVersion, 1.0), 1, 2, 0, 1)
        table.attach(self.justify(pythonVersion, 1.0), 1, 2, 1, 2)
        table.attach(self.justify(gtkVersion, 1.0), 1, 2, 2, 3)
        table.attach(self.justify(pygtkVersion, 1.0), 1, 2, 3, 4)
        header = gtk.Label()
        header.set_markup("<b>You are using these versions:\n</b>")
        tableVbox = gtk.VBox()
        tableVbox.pack_start(header, expand=False, fill=False)
        tableVbox.pack_start(table, expand=True, fill=True)
        centeredTable = gtk.Alignment(0.5)
        centeredTable.add(tableVbox)
        sourceDirLabel = gtk.Label()
        sourceDirLabel.set_markup("")
        sourceDir = gtk.Label(plugins.installationRoots[0])
        vbox = gtk.VBox()
        vbox.pack_start(centeredTable, expand=True, fill=True)
        vbox.pack_start(self.justify("\n<b>TextTest source directory:</b>", 0.0, True), expand=True, fill=True)
        vbox.pack_start(sourceDir, expand=True, fill=True)
        frame = gtk.Alignment(0.5, 0.5, 1.0, 1.0)
        frame.set_padding(10, 10, 10, 10)
        frame.add(vbox)
        self.dialog.vbox.pack_start(frame, expand=True, fill=True)
        return "Showing component versions: \n TextTest: " + textTestVersion + \
               "\n Python: " + pythonVersion + "\n GTK: " + gtkVersion + \
               "\n PyGTK: " + pygtkVersion
        
    def justify(self, label, leftFill, markup = False):
        alignment = gtk.Alignment(leftFill, 0.0, 0.0, 0.0)
        if markup:
            l = gtk.Label()
            l.set_markup(label)
            alignment.add(l)
        else:
            alignment.add(gtk.Label(label))
        return alignment

class CreditsDialog(guiplugins.ActionResultDialogGUI):
    def __init__(self, parent, *args):
        guiplugins.ActionResultDialogGUI.__init__(self, *args)
        self.parent = parent

    def getParentWindow(self):
        return self.parent
    
    def _getTitle(self):
        return "TextTest Credits"

    def addContents(self):
        try:
            authorFile = open(os.path.join(plugins.installationDir("doc"), "AUTHORS"))
            unicodeInfo = plugins.decodeText("".join(authorFile.readlines()))           
            authorFile.close()
            creditsText = plugins.encodeToUTF(unicodeInfo)
            buffer = gtk.TextBuffer()
            buffer.set_text(creditsText)
        except Exception, e: #pragma : no cover - should never happen
            self.showErrorDialog("Failed to show AUTHORS file:\n" + str(e))
            return

        textView = gtk.TextView(buffer)
        textView.set_editable(False)
        textView.set_cursor_visible(False)
        textView.set_left_margin(5)
        textView.set_right_margin(5)
        notebook = gtk.Notebook()
        notebook.append_page(textView, gtk.Label("Written by"))
        self.dialog.vbox.pack_start(notebook, expand=True, fill=True)
        self.dialog.set_resizable(False)
        return "Showing credits:\n" + creditsText
            
class LicenseDialog(guiplugins.ActionResultDialogGUI):
    def __init__(self, parent, *args):
        guiplugins.ActionResultDialogGUI.__init__(self, *args)
        self.parent = parent

    def getParentWindow(self):
        return self.parent
    
    def _getTitle(self):
        return "TextTest License"
    
    def addContents(self):
        try:
            licenseFile = open(os.path.join(plugins.installationDir("doc"), "LICENSE"))
            unicodeInfo = plugins.decodeText("".join(licenseFile.readlines()))           
            licenseFile.close()
            licenseText = plugins.encodeToUTF(unicodeInfo)
            buffer = gtk.TextBuffer()
            buffer.set_text(licenseText)
        except Exception, e: #pragma : no cover - should never happen
            self.showErrorDialog("Failed to show LICENSE file:\n" + str(e))
            return

        textView = gtk.TextView(buffer)
        textView.set_editable(False)
        textView.set_cursor_visible(False)
        textView.set_left_margin(5)
        textView.set_right_margin(5)
        notebook = gtk.Notebook()
        notebook.append_page(textView, gtk.Label("License"))
        self.dialog.vbox.pack_start(notebook, expand=True, fill=True)
        return "Showing license:\n" + licenseText

class VersionInfoDialogGUI(guiplugins.ActionResultDialogGUI):
    def isActiveOnCurrent(self, *args):
        return True
    def messageAfterPerform(self):
        return ""
    def cmpVersions(self, file1, file2):
        v1 = self.makeVersions(file1)
        v2 = self.makeVersions(file2)
        return -cmp(v1, v2) # We want the most recent file first ...

    def makeVersions(self, versionStr):
        versions = []
        for stringVersion in versionStr.split("."):
            try:
                versions.append(int(stringVersion))
            except ValueError:
                versions.append(stringVersion)
        return tuple(versions)

    def addContents(self):
        notebook = gtk.Notebook()
        notebook.set_scrollable(True)
        notebook.popup_enable()
        docDir = plugins.installationDir("doc")
        versionInfo = self.readVersionInfo(docDir)
        message = ""
        for version in reversed(sorted(versionInfo.keys())):
            unicodeInfo = plugins.decodeText(versionInfo[version])
            displayText = plugins.encodeToUTF(unicodeInfo)
            endFirstSentence = displayText.find(".")
            versionStr = ".".join(map(str, version))
            message += "Adding " + self.getTitle() + " from version " + versionStr + \
                       ":\nFirst sentence :" + displayText[:endFirstSentence + 1] + "\n"

            buffer = gtk.TextBuffer()
            buffer.set_text(displayText)
            textView = gtk.TextView(buffer)
            textView.set_editable(False)
            textView.set_cursor_visible(False)
            textView.set_left_margin(5)
            textView.set_right_margin(5)
            scrolledWindow = gtk.ScrolledWindow()
            scrolledWindow.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
            scrolledWindow.add(textView)
            scrolledWindow.set_shadow_type(gtk.SHADOW_IN)
            notebook.append_page(scrolledWindow, gtk.Label(self.labelPrefix() + versionStr))

        if notebook.get_n_pages() == 0: #pragma : no cover - should never happen
            raise plugins.TextTestError, "\nNo " + self.getTitle() + " could be found in\n" + docDir + "\n"
        else:
            guiplugins.scriptEngine.monitorNotebook(notebook, "view " + self.getTitle().lower() + " in tab")
            parentSize = self.topWindow.get_size()
            self.dialog.resize(int(parentSize[0] * 0.9), int(parentSize[0] * 0.7))
            self.dialog.vbox.pack_start(notebook, expand=True, fill=True)
            return message

    def labelPrefix(self):
        return ""

            
class ShowMigrationNotes(VersionInfoDialogGUI):
    def _getTitle(self):
        return "_Migration Notes"
    def getTooltip(self):
        return "show texttest migration notes"

    def getDialogTitle(self):
        return "TextTest Migration Notes"
        
    def readVersionInfo(self, docDir):
        versionInfo = {}
        for fileName in glob.glob(os.path.join(docDir, "MigrationNotes*")):
            versions = self.makeVersions(fileName.split("_")[-1])
            versionInfo[versions] = open(fileName).read()
        return versionInfo

    def labelPrefix(self):
        return "from "

    
class ShowChangeLogs(VersionInfoDialogGUI):
    def _getTitle(self):
        return "_Change Logs"
    def getTooltip(self):
        return "show texttest change logs"

    def getDialogTitle(self):
        return "TextTest Change Logs"
    
    def readVersionInfo(self, docDir):
        versionInfo = {}
        currVersions = ()
        for line in open(os.path.join(docDir, "ChangeLog")):
            if line.startswith("Version"):
                words = line.strip().split()
                if len(words) == 2:
                    versionStr = words[-1].rstrip(":")
                    currVersions = self.makeVersions(versionStr)
                    versionInfo[currVersions] = ""
                else:
                    versionInfo[currVersions] += line
            elif len(line.strip()) == 0 or line.startswith("="):
                continue
            else:
                versionInfo[currVersions] += line
        return versionInfo
