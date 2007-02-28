
import gtk
import gobject

import guiplugins, guidialogs, plugins, os, string, sys, glob
from gtkusecase import ScriptEngine

# Show useful info about TextTest.
# I don't particularly like the standard gtk.AboutDialog, and we also want
# to show pygtk/gtk/python versions in our dialog, so we create our own ...
class AboutTextTestDialog(guidialogs.ActionResultDialog):
    def getDialogTitle(self):
        return "About TextTest"

    def createButtons(self):        
        self.creditsButton = self.dialog.add_button('texttest-stock-credits', gtk.RESPONSE_NONE)
        self.licenseButton = self.dialog.add_button('_License', gtk.RESPONSE_NONE)
        self.versionsButton = self.dialog.add_button('_Versions', gtk.RESPONSE_NONE)
        self.closeButton = self.dialog.add_button(gtk.STOCK_CLOSE, gtk.RESPONSE_CLOSE)
        guidialogs.scriptEngine.connect("press credits", "clicked", self.creditsButton, self.showCredits)
        guidialogs.scriptEngine.connect("press license", "clicked", self.licenseButton, self.showLicense)
        guidialogs.scriptEngine.connect("press versions", "clicked", self.versionsButton, self.showVersions)
        guidialogs.scriptEngine.connect("press close", "clicked", self.closeButton, self.respond, gtk.RESPONSE_CLOSE, True)

    def addContents(self):
        logo = gtk.Image()
        logo.set_from_pixbuf(gtk.gdk.pixbuf_new_from_file(
            os.path.join(plugins.installationDir("images"), "texttest-logo.jpg")))
        logoFrame = gtk.Alignment(0.5, 0.5, 0.0, 0.0)
        logoFrame.set_padding(10, 10, 10, 10)
        logoFrame.add(logo)
        mainLabel = gtk.Label()
        mainLabel.set_markup("<span size='xx-large'>TextTest 3.9</span>\n")
        messageLabel = gtk.Label()
        messageLabel.set_markup("<i>TextTest is an application-independent tool for text-based\nfunctional testing. This means running a batch-mode binary\nin lots of different ways, and using the text output produced\nas a means of controlling the behaviour of that application.</i>\n")
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
        self.dialog.set_default_response(gtk.RESPONSE_CLOSE)

    def showCredits(self, button):
        dialog = CreditsDialog(self.dialog, None, None)
        dialog.run()

    def showLicense(self, button):
        dialog = LicenseDialog(self.dialog, None, None)
        dialog.run()

    def showVersions(self, button):
        dialog = VersionsDialog(self.dialog, None, None)
        dialog.run()

class VersionsDialog(guidialogs.ActionResultDialog):
    def getDialogTitle(self):
        return "Version Information"

    def addContents(self):
        textTestVersion = "3.9"
        pythonVersion = ".".join(map(lambda l: str(l), sys.version_info))
        gtkVersion = ".".join(map(lambda l: str(l), gtk.gtk_version))
        pygtkVersion = ".".join(map(lambda l: str(l), gtk.pygtk_version))
        guidialogs.guilog.info("Showing component versions: \n TextTest: " + textTestVersion +
                               "\n Python: " + pythonVersion + "\n GTK: " + gtkVersion +
                               "\n PyGTK: " + pygtkVersion)
        
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
        vbox = gtk.VBox()
        vbox.pack_start(header, expand=True, fill=True)
        vbox.pack_start(table, expand=True, fill=True)
        frame = gtk.Alignment()
        frame.set_padding(10, 10, 10, 10)
        frame.add(vbox)
        self.dialog.vbox.pack_start(frame, expand=True, fill=True)

    def justify(self, label, leftFill):
        alignment = gtk.Alignment(leftFill, 0.0, 0.0, 0.0)
        alignment.add(gtk.Label(label))
        return alignment

class CreditsDialog(guidialogs.ActionResultDialog):
    def getDialogTitle(self):
        return "TextTest Credits"

    def addContents(self):
        authorFile = open(os.path.join(plugins.installationDir("doc"), "AUTHORS"))
        unicodeInfo = plugins.decodeText("".join(authorFile.readlines()))           
        authorFile.close()
        creditsText = plugins.encodeToUTF(unicodeInfo)
        guidialogs.guilog.info("Showing credits:\n" + creditsText)

        buffer = gtk.TextBuffer()
        buffer.set_text(creditsText)
        textView = gtk.TextView(buffer)
        textView.set_editable(False)
        textView.set_cursor_visible(False)
        textView.set_left_margin(5)
        textView.set_right_margin(5)
        notebook = gtk.Notebook()
        notebook.append_page(textView, gtk.Label("Written by"))
        self.dialog.vbox.pack_start(notebook, expand=True, fill=True)

class LicenseDialog(guidialogs.ActionResultDialog):
    def getDialogTitle(self):
        return "TextTest License"

    def addContents(self):
        licenseFile = open(os.path.join(plugins.installationDir("doc"), "LICENSE"))
        unicodeInfo = plugins.decodeText("".join(licenseFile.readlines()))           
        licenseFile.close()
        licenseText = plugins.encodeToUTF(unicodeInfo)
        guidialogs.guilog.info("Showing license:\n" + licenseText)

        buffer = gtk.TextBuffer()
        buffer.set_text(licenseText)
        textView = gtk.TextView(buffer)
        textView.set_editable(False)
        textView.set_cursor_visible(False)
        textView.set_left_margin(5)
        textView.set_right_margin(5)
        notebook = gtk.Notebook()
        notebook.append_page(textView, gtk.Label("License"))
        self.dialog.vbox.pack_start(notebook, expand=True, fill=True)

class MigrationNotesDialog(guidialogs.ActionResultDialog):
    def getDialogTitle(self):
        return "TextTest Migration Notes"

    def addContents(self):
        notebook = gtk.Notebook()
        notebook.set_scrollable(True)
        notebook.popup_enable()
        notes = glob.glob(os.path.join(plugins.installationDir("doc"), "MigrationNotes*"))
        notes.reverse() # We want the most resent file first ...
        for note in notes:
            notesFile = open(note)
            unicodeInfo = plugins.decodeText("".join(notesFile.readlines()))           
            notesFile.close()
            notesText = plugins.encodeToUTF(unicodeInfo)
            guidialogs.guilog.info("Adding migration notes from file '" + note + "':\n" + notesText)

            buffer = gtk.TextBuffer()
            buffer.set_text(notesText)
            textView = gtk.TextView(buffer)
            textView.set_editable(False)
            textView.set_cursor_visible(False)
            textView.set_left_margin(5)
            textView.set_right_margin(5)
            scrolledWindow = gtk.ScrolledWindow()
            scrolledWindow.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
            scrolledWindow.add(textView)
            scrolledWindow.set_shadow_type(gtk.SHADOW_IN)
            notesVersion = os.path.basename(note).replace("MigrationNotes_", "").replace("_", " ")
            notebook.append_page(scrolledWindow, gtk.Label(notesVersion))

        guidialogs.scriptEngine.monitorNotebook(notebook, "view migration notes in tab")
        parentSize = self.parent.get_size()
        self.dialog.resize(int(parentSize[0] * 0.9), int(parentSize[0] * 0.7))
        self.dialog.vbox.pack_start(notebook, expand=True, fill=True)
