
import gtk, os, entrycompletion, guidialogs

# Dialog for performance report...
class CreatePerformanceReportDialog(guidialogs.ActionConfirmationDialog):
    def __init__(self, parent, okMethod, cancelMethod, plugin):
        guidialogs.ActionConfirmationDialog.__init__(self, parent, okMethod, cancelMethod, plugin)
        self.dialog.set_default_response(gtk.RESPONSE_ACCEPT)

    def addContents(self):
        # A simple entry for the path, and one for the versions ...
        self.dirEntry = gtk.Entry()
        self.versionsEntry = gtk.Entry()
        self.objectiveTextEntry = gtk.Entry()
        entrycompletion.manager.register(self.dirEntry)
        entrycompletion.manager.register(self.versionsEntry)
        entrycompletion.manager.register(self.objectiveTextEntry)
        self.dirEntry.set_activates_default(True)
        self.versionsEntry.set_activates_default(True)
        self.objectiveTextEntry.set_activates_default(True)
        self.dirEntry.set_text(self.plugin.rootDir)
        self.versionsEntry.set_text(",".join(self.plugin.versions).rstrip(","))
        self.objectiveTextEntry.set_text(self.plugin.objectiveText)
        
        table = gtk.Table(3, 2, homogeneous=False)
        table.set_row_spacings(1)
        table.attach(gtk.Label("Save in directory:"), 0, 1, 0, 1, xoptions=gtk.FILL, xpadding=1)
        table.attach(gtk.Label("Compare versions:"), 0, 1, 1, 2, xoptions=gtk.FILL, xpadding=1)
        table.attach(gtk.Label("Objective value text:"), 0, 1, 2, 3, xoptions=gtk.FILL, xpadding=1)
        table.attach(self.dirEntry, 1, 2, 0, 1)
        table.attach(self.versionsEntry, 1, 2, 1, 2)
        table.attach(self.objectiveTextEntry, 1, 2, 2, 3)
        guidialogs.scriptEngine.registerEntry(self.dirEntry, "choose directory ")
        guidialogs.scriptEngine.registerEntry(self.versionsEntry, "choose versions ")
        guidialogs.scriptEngine.registerEntry(self.objectiveTextEntry, "choose objective text ")
        self.dialog.vbox.pack_start(table, expand = True, fill = True)
        
    def respond(self, button, saidOK, *args):
        if saidOK:
            self.plugin.rootDir = os.path.abspath(self.dirEntry.get_text())
            self.plugin.versions = self.versionsEntry.get_text().replace(" ", "").split(",")
            self.plugin.objectiveText = self.objectiveTextEntry.get_text()
        guidialogs.ActionConfirmationDialog.respond(self, button, saidOK, *args)
