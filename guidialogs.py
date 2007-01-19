#!/usr/bin/env python

import gtk
import gobject

import guiplugins, plugins, os, string, time, sys, locale
from gtkusecase import ScriptEngine, TreeModelIndexer

def setupScriptEngine(engine):
    global scriptEngine, guilog
    scriptEngine = engine
    from guiplugins import guilog

def destroyDialog(dialog, *args):
    dialog.destroy()

def createDialogMessage(message, stockIcon, scrollBars=False):
    buffer = gtk.TextBuffer()
    buffer.set_text(message)
    textView = gtk.TextView(buffer)
    textView.set_editable(False)
    textView.set_cursor_visible(False)
    textView.set_left_margin(5)
    textView.set_right_margin(5)
    hbox = gtk.HBox()
    imageBox = gtk.VBox()
    imageBox.pack_start(gtk.image_new_from_stock(stockIcon, gtk.ICON_SIZE_DIALOG), expand=False)
    hbox.pack_start(imageBox, expand=False)
    scrolledWindow = gtk.ScrolledWindow()
    # What we would like is that the dialog expands without scrollbars
    # until it reaches some maximum size, and then adds scrollbars. At
    # the moment I cannot make this happen without setting a fixed window
    # size, so I'll set the scrollbar policy to never instead.
    if scrollBars:
        scrolledWindow.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
    else:
        scrolledWindow.set_policy(gtk.POLICY_NEVER, gtk.POLICY_NEVER)
    scrolledWindow.add(textView)
    scrolledWindow.set_shadow_type(gtk.SHADOW_IN)
    hbox.pack_start(scrolledWindow, expand=True, fill=True)
    alignment = gtk.Alignment()
    alignment.set_padding(5, 5, 0, 5)
    alignment.add(hbox)
    return alignment

def showErrorDialog(message, parent=None):
    guilog.info("ERROR: " + message)
    dialog = gtk.Dialog("TextTest Error", parent, buttons=(gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
    dialog.set_modal(True)
    dialog.vbox.pack_start(createDialogMessage(message, gtk.STOCK_DIALOG_ERROR), expand=True, fill=True)
    scriptEngine.connect("agree to texttest message", "response", dialog, destroyDialog, gtk.RESPONSE_ACCEPT)
    dialog.show_all()
    dialog.action_area.get_children()[len(dialog.action_area.get_children()) - 1].grab_focus()

def showWarningDialog(message, parent=None):
    guilog.info("WARNING: " + message)
    dialog = gtk.Dialog("TextTest Warning", parent, buttons=(gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
    dialog.set_modal(True)
    dialog.vbox.pack_start(createDialogMessage(message, gtk.STOCK_DIALOG_WARNING), expand=True, fill=True)
    scriptEngine.connect("agree to texttest message", "response", dialog, destroyDialog, gtk.RESPONSE_ACCEPT)
    dialog.show_all()
    dialog.action_area.get_children()[len(dialog.action_area.get_children()) - 1].grab_focus()

def showInformationDialog(message, parent=None):
    guilog.info("INFORMATION: " + message)
    dialog = gtk.Dialog("TextTest Information", parent, buttons=(gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
    dialog.set_modal(True)
    dialog.vbox.pack_start(createDialogMessage(message, gtk.STOCK_DIALOG_INFO), expand=True, fill=True)
    scriptEngine.connect("agree to texttest message", "response", dialog, destroyDialog, gtk.RESPONSE_ACCEPT)
    dialog.show_all()
    dialog.action_area.get_children()[len(dialog.action_area.get_children()) - 1].grab_focus()

class DoubleCheckDialog:
    def __init__(self, message, yesMethod, noMethod=None, parent=None):
        self.dialog = gtk.Dialog("TextTest Query", parent, flags=gtk.DIALOG_MODAL)
        self.yesMethod = yesMethod
        self.noMethod = noMethod
        guilog.info("QUERY: " + message)
        noButton = self.dialog.add_button(gtk.STOCK_NO, gtk.RESPONSE_NO)
        yesButton = self.dialog.add_button(gtk.STOCK_YES, gtk.RESPONSE_YES)
        self.dialog.set_modal(True)
        self.dialog.vbox.pack_start(createDialogMessage(message, gtk.STOCK_DIALOG_QUESTION), expand=True, fill=True)
        # ScriptEngine cannot handle different signals for the same event (e.g. response
        # from gtk.Dialog), so we connect the individual buttons instead ...
        scriptEngine.connect("answer no to texttest query", "clicked", noButton, self.respond, gtk.RESPONSE_NO, False)
        scriptEngine.connect("answer yes to texttest query", "clicked", yesButton, self.respond, gtk.RESPONSE_YES, True)
        self.dialog.show_all()
        self.dialog.set_default_response(gtk.RESPONSE_NO)
        self.dialog.action_area.get_children()[len(self.dialog.action_area.get_children()) - 1].grab_focus()

    def respond(self, button, saidYes, *args):
        self.dialog.hide()
        self.dialog.response(gtk.RESPONSE_NONE)
        if saidYes:
            self.yesMethod()
        elif self.noMethod:
            self.noMethod()

#
# A skeleton for a dialog which can replace the 'tab options' of
# today's actions. I think it should be possible to customize the
# look of the dialog, so I'll let each subclass create its widgets,
# rather than follow the TextTestGUI way to centrally decide the
# option tab page layout. I think this will only add a minor overhead,
# but will make it much easier to make the dialogs look nice.
# 
class ActionConfirmDialog:
    def __init__(self, parent, okMethod, cancelMethod, plugin):
        self.parent = parent
        self.plugin = plugin
        self.okMethod = okMethod
        self.cancelMethod = cancelMethod
        self.dialog = gtk.Dialog(self.plugin.getScriptTitle(None), parent, flags=gtk.DIALOG_MODAL)
        self.createButtons()
        self.dialog.set_modal(True)
        
    def createButtons(self):
        self.cancelButton = self.dialog.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL)
        self.okButton = self.dialog.add_button(gtk.STOCK_OK, gtk.RESPONSE_ACCEPT)       
        scriptEngine.connect("press cancel", "clicked", self.cancelButton, self.respond, gtk.RESPONSE_CANCEL, False)
        scriptEngine.connect("press ok", "clicked", self.okButton, self.respond, gtk.RESPONSE_ACCEPT, True)

    def respond(self, button, saidOK, *args):
        self.dialog.hide()
        self.dialog.response(gtk.RESPONSE_NONE)
        if saidOK:
            self.okMethod()
        else:
            self.cancelMethod()

    def run(self):
        self.addContents()
        self.dialog.show_all()

# It's a bit unfortunate that this has to be here, but unfortunately texttestgui
# cannot load dialogs from matador without some additional work. Also, having it
# here avoids matador importing guidialogs, and hence gtk.
class CreatePerformanceReportDialog(ActionConfirmDialog):
    def addContents(self):
        # A simple entry for the path, and one for the versions ...
        self.dirEntry = gtk.Entry()
        self.versionsEntry = gtk.Entry()
        self.dirEntry.set_text(self.plugin.rootDir)
        self.versionsEntry.set_text(",".join(self.plugin.versions).rstrip(","))
        
        table = gtk.Table(2, 2, homogeneous=False)
        table.set_row_spacings(1)
        table.attach(gtk.Label("Save in directory:"), 0, 1, 0, 1, xoptions=gtk.FILL, xpadding=1)
        table.attach(gtk.Label("Compare versions:"), 0, 1, 1, 2, xoptions=gtk.FILL, xpadding=1)
        table.attach(self.dirEntry, 1, 2, 0, 1)
        table.attach(self.versionsEntry, 1, 2, 1, 2)
        scriptEngine.registerEntry(self.dirEntry, "choose directory ")
        scriptEngine.registerEntry(self.versionsEntry, "choose versions ")
        table.show_all()
        self.dialog.vbox.pack_start(table, expand = True, fill = True)
        
    def respond(self, button, saidOK, *args):
        if saidOK:
            self.plugin.rootDir = os.path.abspath(self.dirEntry.get_text())
            self.plugin.versions = self.versionsEntry.get_text().replace(" ", "").split(",")
        ActionConfirmDialog.respond(self, button, saidOK, *args)
