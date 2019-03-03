
import gtk, gobject, os, sys, glob
from texttestlib import plugins, texttest_version
from .. import guiplugins, guiutils
from types import StringType

# Show useful info about TextTest.
# I don't particularly like the standard gtk.AboutDialog, and we also want
# to show pygtk/gtk/python versions in our dialog, so we create our own ...
class AboutTextTest(guiplugins.ActionResultDialogGUI):
    website = "http://www.texttest.org"
    def __init__(self, *args, **kw):
        self.creditsButton = None
        self.licenseButton = None
        self.versionsButton = None
        guiplugins.ActionResultDialogGUI.__init__(self, *args, **kw)
        
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
        self.creditsButton.connect("clicked", self.showCredits)
        self.licenseButton.connect("clicked", self.showLicense)
        self.versionsButton.connect("clicked", self.showVersions)
        guiplugins.ActionResultDialogGUI.createButtons(self)
        
    def addContents(self):
        imageDir, retro = guiutils.getImageDir()
        imageType = "gif" if retro else "png"
        logoFile = os.path.join(imageDir, "texttest-logo." + imageType)
        logoPixbuf = gtk.gdk.pixbuf_new_from_file(logoFile)
        logo = gtk.Image()
        logo.set_from_pixbuf(logoPixbuf)
        logoFrame = gtk.Alignment(0.5, 0.5, 0.0, 0.0)
        logoFrame.set_padding(10, 10, 10, 10)
        logoFrame.add(logo)
        mainLabel = gtk.Label()
        mainLabel.set_markup("<span size='xx-large'>TextTest " + texttest_version.version + "</span>\n")
        messageLabel = gtk.Label()
        message = "TextTest is an application-independent tool for text-based\nfunctional testing. This means running a batch-mode program\nin lots of different ways, and using the text output produced\nas a means of controlling the behaviour of that application."
        messageLabel.set_markup("<i>" + message + "</i>\n")
        messageLabel.set_justify(gtk.JUSTIFY_CENTER)
        # On Windows the default URI hook fails and causes trouble...
        # According to the docs you can set "None" here but that doesn't seem to work...
        gtk.link_button_set_uri_hook(lambda x, y : None) 
        urlButton = gtk.LinkButton(self.website, self.website)
        urlButton.set_property("border-width", 0)
        urlButtonbox = gtk.HBox()
        urlButtonbox.pack_start(urlButton, expand=True, fill=False)
        urlButton.connect("clicked", self.urlClicked)
        licenseLabel = gtk.Label()
        licenseLabel.set_markup("<span size='small'>Copyright " + u'\xa9' + " The authors</span>\n")
        self.dialog.vbox.pack_start(logoFrame, expand=False, fill=False)
        self.dialog.vbox.pack_start(mainLabel, expand=True, fill=True)
        self.dialog.vbox.pack_start(messageLabel, expand=False, fill=False)
        self.dialog.vbox.pack_start(urlButtonbox, expand=False, fill=False)
        self.dialog.vbox.pack_start(licenseLabel, expand=False, fill=False)
        self.dialog.set_resizable(False)

    def urlClicked(self, *args): 
        status = guiplugins.openLinkInBrowser(self.website)
        self.notify("Status", status)
        
    def showCredits(self, *args):
        newDialog = TextFileDisplayDialog(self.validApps, False, {}, "CREDITS.txt", self.dialog)
        newDialog.performOnCurrent()

    def showLicense(self, *args):
        newDialog = TextFileDisplayDialog(self.validApps, False, {}, "LICENSE.txt", self.dialog)
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

    def makeString(self, versionTuple):
        if type(versionTuple) == StringType:
            return versionTuple
        else:
            return ".".join(map(str, versionTuple))

    def addTable(self, vbox, name, data, alignRight, columnSpacings, **kw):
        table = gtk.Table(len(data), 2, homogeneous=False)
        table.set_row_spacings(1)
        table.set_col_spacings(columnSpacings)
        for rowNo, (title, versionTuple) in enumerate(data):
            table.attach(self.justify(title + ":", 0.0), 0, 1, rowNo, rowNo + 1, xoptions=gtk.FILL, xpadding=1)
            table.attach(self.justify(self.makeString(versionTuple), float(alignRight)), 1, 2, rowNo, rowNo + 1)

        header = gtk.Label()
        header.set_markup("<b>You are using these " + name + "s:\n</b>")
        tableVbox = gtk.VBox()
        tableVbox.pack_start(header, expand=False, fill=False)
        tableVbox.pack_start(table, expand=True, fill=True)
        centeredTable = gtk.Alignment(0.5)
        centeredTable.add(tableVbox)
        vbox.pack_start(centeredTable, expand=True, fill=True, **kw)
    
    def addContents(self):
        versionList = [ ("TextTest", texttest_version.version),
                        ("Python", sys.version_info),
                        ("GTK", gtk.gtk_version),
                        ("PyGTK",  gtk.pygtk_version),
                        ("PyGObject", gobject.pygobject_version),
                        ("GLib", gobject.glib_version) ]

        installationList = [ ("Test Suite", os.getenv("TEXTTEST_HOME")),
                             ("TextTest", plugins.installationRoots[0]),
                             ("Python", sys.executable) ]
        
        vbox = gtk.VBox()
        self.addTable(vbox, "version", versionList, alignRight=True, columnSpacings=0)
        self.addTable(vbox, "installation", installationList, alignRight=False, columnSpacings=5, padding=10)
        frame = gtk.Alignment(0.5, 0.5, 1.0, 1.0)
        frame.set_padding(10, 10, 10, 10)
        frame.add(vbox)
        self.dialog.vbox.pack_start(frame, expand=True, fill=True)
        
    def justify(self, label, leftFill, markup = False):
        alignment = gtk.Alignment(leftFill, 0.0, 0.0, 0.0)
        if markup:
            l = gtk.Label()
            l.set_markup(label)
            alignment.add(l)
        else:
            alignment.add(gtk.Label(label))
        return alignment

class TextFileDisplayDialog(guiplugins.ActionResultDialogGUI):
    def __init__(self, allApps, dynamic, inputOptions, fileName, parent=None):
        self.parent = parent
        self.fileName = fileName
        self.title = self.makeTitleFromFileName(fileName)
        guiplugins.ActionResultDialogGUI.__init__(self, allApps, dynamic)
        
    def getParentWindow(self):
        if self.parent:
            return self.parent
        else:
            return self.topWindow

    def makeTitleFromFileName(self, fileName):
        words = fileName.replace(".txt", "").split("_")
        return " ".join([ word.capitalize() for word in words ])

    def messageAfterPerform(self):
        return ""
        
    def _getTitle(self):
        return self.title

    def getTooltip(self):
        return "Show TextTest " + self.title

    def isActiveOnCurrent(self, *args):
        return True
    
    def getDialogTitle(self):
        return "TextTest " + self.title

    def getTabTitle(self):
        if self.title == "Credits":
            return "Written by"
        else:
            return self.title

    def addContents(self):
        try:
            file = open(plugins.installationPath("doc", self.fileName))
            text = file.read()
            file.close()
            buffer = gtk.TextBuffer()
            buffer.set_text(text)
        except Exception, e: #pragma : no cover - should never happen
            self.showErrorDialog("Failed to show " + self.fileName + " file:\n" + str(e))
            return

        textView = gtk.TextView(buffer)
        textView.set_editable(False)
        textView.set_cursor_visible(False)
        textView.set_left_margin(5)
        textView.set_right_margin(5)
        useScrollbars = not self.parent and text.count("\n") > 30
        notebook = gtk.Notebook()
        label = gtk.Label(self.getTabTitle())
        if useScrollbars:
            window = gtk.ScrolledWindow()
            window.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
            window.add(textView)
            notebook.append_page(window, label)        
            parentSize = self.topWindow.get_size()
            self.dialog.resize(int(parentSize[0] * 0.9), int(parentSize[1] * 0.7))
        else:
            notebook.append_page(textView, label)
            
        self.dialog.vbox.pack_start(notebook, expand=True, fill=True)
        
        
class VersionInfoDialogGUI(guiplugins.ActionResultDialogGUI):
    def isActiveOnCurrent(self, *args):
        return True

    def messageAfterPerform(self):
        return ""

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
        for version in reversed(sorted(versionInfo.keys())):
            buffer = gtk.TextBuffer()
            buffer.set_text(versionInfo[version])
            textView = gtk.TextView(buffer)
            textView.set_editable(False)
            textView.set_cursor_visible(False)
            textView.set_left_margin(5)
            textView.set_right_margin(5)
            scrolledWindow = gtk.ScrolledWindow()
            scrolledWindow.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
            scrolledWindow.add(textView)
            scrolledWindow.set_shadow_type(gtk.SHADOW_IN)
            versionStr = ".".join(map(str, version))
            notebook.append_page(scrolledWindow, gtk.Label(self.labelPrefix() + versionStr))

        if notebook.get_n_pages() == 0: #pragma : no cover - should never happen
            raise plugins.TextTestError, "\nNo " + self.getTitle() + " could be found in\n" + docDir + "\n"
        else:
            parentSize = self.topWindow.get_size()
            self.dialog.resize(int(parentSize[0] * 0.9), int(parentSize[1] * 0.7))
            self.dialog.vbox.pack_start(notebook, expand=True, fill=True)
            
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


def getInteractiveActionClasses():
    classes = [ ShowMigrationNotes, ShowChangeLogs, ShowVersions, AboutTextTest ]
    for fileName in plugins.findDataPaths([ "*.txt" ], dataDirName="doc"):
        classes.append(plugins.Callable(TextFileDisplayDialog, os.path.basename(fileName)))
    return classes
