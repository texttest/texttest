#!/usr/bin/env python

import gtk

import plugins, os, sys
scriptEngine = None
guilog = None
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
    dialog.set_default_response(gtk.RESPONSE_ACCEPT)

def showWarningDialog(message, parent=None):
    guilog.info("WARNING: " + message)
    dialog = gtk.Dialog("TextTest Warning", parent, buttons=(gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
    dialog.set_modal(True)
    dialog.vbox.pack_start(createDialogMessage(message, gtk.STOCK_DIALOG_WARNING), expand=True, fill=True)
    scriptEngine.connect("agree to texttest message", "response", dialog, destroyDialog, gtk.RESPONSE_ACCEPT)
    dialog.show_all()
    dialog.set_default_response(gtk.RESPONSE_ACCEPT)

def showInformationDialog(message, parent=None):
    guilog.info("INFORMATION: " + message)
    dialog = gtk.Dialog("TextTest Information", parent, buttons=(gtk.STOCK_CLOSE, gtk.RESPONSE_CLOSE))
    dialog.set_modal(True)
    dialog.vbox.pack_start(createDialogMessage(message, gtk.STOCK_DIALOG_INFO), expand=True, fill=True)
    scriptEngine.connect("press close", "response", dialog, destroyDialog, gtk.RESPONSE_CLOSE)
    dialog.show_all()
    dialog.set_default_response(gtk.RESPONSE_CLOSE)

#
# A generic action dialog, containing stuff which is shared between ActionConfirmationDialog
# and ActionResultDialog. It is recommended to inherit from those instead of directly
# from this class.
#
class GenericActionDialog:
    def __init__(self, parent, plugin):
        self.parent = parent
        self.plugin = plugin

    def getDialogTitle(self):
        return self.plugin.getScriptTitle(None)        

    def isModal(self):
        return True

    def isResizeable(self):
        return True
    
    def run(self):
        self.addContents()
        # Show if we've added something. This'll let us leave the dialog
        # empty and e.g. pop up an error dialog if that is more suitable ...
        if len(self.dialog.vbox.get_children()) > 2: # Separator and buttonbox are always there ...
            self.dialog.show_all()
        
    def getStockIcon(self, stockItem):
        imageBox = gtk.VBox()
        imageBox.pack_start(gtk.image_new_from_stock(stockItem, gtk.ICON_SIZE_DIALOG), expand=False)
        return imageBox

#
# A skeleton for a dialog which can replace the 'tab options' of
# today's actions. I think it should be possible to customize the
# look of the dialog, so I'll let each subclass create its widgets,
# rather than follow the TextTestGUI way to centrally decide the
# option tab page layout. I think this will only add a minor overhead,
# but will make it much easier to make the dialogs look nice.
# 
class ActionConfirmationDialog(GenericActionDialog):
    def __init__(self, parent, okMethod, cancelMethod, plugin):
        GenericActionDialog.__init__(self, parent, plugin)
        self.okMethod = okMethod
        self.cancelMethod = cancelMethod
        if self.isModal():
            self.dialog = gtk.Dialog(self.getDialogTitle(), parent, flags=gtk.DIALOG_MODAL) 
            self.dialog.set_modal(True)
        else:
            self.dialog = gtk.Dialog(self.plugin.getScriptTitle(None))
        self.dialog.set_resizable(self.isResizeable())
        self.createButtons()

    def createButtons(self):
        self.cancelButton = self.dialog.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL)
        self.okButton = self.dialog.add_button(gtk.STOCK_OK, gtk.RESPONSE_ACCEPT)       
        scriptEngine.connect("press cancel", "clicked", self.cancelButton, self.respond, gtk.RESPONSE_CANCEL, False)
        scriptEngine.connect("press ok", "clicked", self.okButton, self.respond, gtk.RESPONSE_ACCEPT, True)

    def respond(self, button, saidOK, *args):
        self.dialog.hide()
        self.dialog.response(gtk.RESPONSE_NONE)
        if saidOK and self.okMethod:
            self.okMethod()
        elif self.cancelMethod:
            self.cancelMethod()


# A skeleton for a dialog which can show results of actions. 
class ActionResultDialog(GenericActionDialog):
    def __init__(self, parent, okMethod, plugin):
        GenericActionDialog.__init__(self, parent, plugin)
        self.okMethod = okMethod
        if self.isModal():
            self.dialog = gtk.Dialog(self.getDialogTitle(), parent, flags=gtk.DIALOG_MODAL) 
            self.dialog.set_modal(True)
        else:
            self.dialog = gtk.Dialog(self.getDialogTitle())             
        self.dialog.set_resizable(self.isResizeable())
        self.createButtons()

    def createButtons(self):
        self.okButton = self.dialog.add_button(gtk.STOCK_CLOSE, gtk.RESPONSE_ACCEPT)       
        scriptEngine.connect("press close", "clicked", self.okButton, self.respond, gtk.RESPONSE_ACCEPT, True)
        self.dialog.set_default_response(gtk.RESPONSE_ACCEPT)

    def respond(self, button, saidOK, *args):
        self.dialog.hide()
        self.dialog.response(gtk.RESPONSE_NONE)
        if self.okMethod:
            self.okMethod()

#
#
# Put specific dialog implementations below.
#
#
       
class YesNoDialog(ActionConfirmationDialog):
    def __init__(self, parent, okMethod, cancelMethod, plugin, message=None):
        ActionConfirmationDialog.__init__(self, parent, okMethod, cancelMethod, plugin)
        if self.plugin:
            self.message = self.plugin.confirmationMessage
        else:
            self.message = message
        guilog.info(self.alarmLevel().upper() + ": " + self.message)
        self.dialog.set_default_response(gtk.RESPONSE_NO)

    def getDialogTitle(self):
        return "TextTest " + self.alarmLevel()

    def createButtons(self):
        noButton = self.dialog.add_button(gtk.STOCK_NO, gtk.RESPONSE_NO)
        yesButton = self.dialog.add_button(gtk.STOCK_YES, gtk.RESPONSE_YES)
        scriptEngine.connect("answer no to texttest " + self.alarmLevel(), "clicked",
                             noButton, self.respond, gtk.RESPONSE_NO, False)
        scriptEngine.connect("answer yes to texttest " + self.alarmLevel(), "clicked", yesButton,
                             self.respond, gtk.RESPONSE_YES, True)

    def addContents(self):
        contents = createDialogMessage(self.message, self.stockIcon())
        self.dialog.vbox.pack_start(contents, expand=True, fill=True)

class QueryDialog(YesNoDialog):
    def alarmLevel(self):
        return "Query"
    def stockIcon(self):
        return gtk.STOCK_DIALOG_QUESTION

class ConfirmationDialog(YesNoDialog):
    def alarmLevel(self):
        return "Confirmation"
    def stockIcon(self):
        return gtk.STOCK_DIALOG_WARNING
        
class SaveSelectionDialog(ActionConfirmationDialog):
    def __init__(self, parent, okMethod, cancelMethod, plugin):
        self.fileChooser = gtk.FileChooserWidget(gtk.FILE_CHOOSER_ACTION_SAVE)
        self.fileChooser.set_show_hidden(True)
        self.plugin = plugin
        self.folders, defaultFolder = self.plugin.getDirectories()
        self.startFolder = os.getcwd() # Just to make sure we always have some dir ...
        if defaultFolder and os.path.isdir(os.path.abspath(defaultFolder)):
            self.startFolder = os.path.abspath(defaultFolder)
        self.enableOptions = self.plugin.dialogEnableOptions()
        ActionConfirmationDialog.__init__(self, parent, okMethod, cancelMethod, plugin)
        self.dialog.set_modal(True)
        self.dialog.set_default_response(gtk.RESPONSE_ACCEPT)
    def folderChanged(self, *args):
        scriptEngine.applicationEvent("dialog to be displayed")
        return False
    def createButtons(self):
        self.cancelButton = self.dialog.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL)
        self.okButton = self.dialog.add_button(gtk.STOCK_SAVE, gtk.RESPONSE_ACCEPT)
        scriptEngine.registerSaveFileChooser(self.fileChooser, self.okButton, "enter filter-file name =", "choose folder")
        scriptEngine.connect("press cancel", "clicked", self.cancelButton, self.respond, gtk.RESPONSE_CANCEL, False)
        scriptEngine.connect("press save", "clicked", self.okButton, self.respond, gtk.RESPONSE_ACCEPT, True)
        
    def addContents(self):
        alignment = gtk.Alignment()
        alignment.set(1.0, 1.0, 1.0, 1.0)
        alignment.set_padding(5, 5, 5, 5)
        vbox = gtk.VBox()
        alignment.add(vbox)
        self.dialog.vbox.pack_start(alignment, expand=True, fill=True)

        # We want a filechooser dialog to let the user choose where, and
        # with which name, to save the selection.
        self.fileChooser.set_current_folder(self.startFolder)
        for i in xrange(len(self.folders) - 1, -1, -1):
            self.fileChooser.add_shortcut_folder(self.folders[i][1])
        self.fileChooser.set_local_only(True)
        self.fileChooser.connect_after("current-folder-changed", self.folderChanged)
        vbox.pack_start(self.fileChooser, expand=True, fill=True)

        # In the static GUI case, we also want radiobuttons specifying 
        # whether we want to save the actual tests, or the selection criteria.
        frame = gtk.Frame("Save")
        frameBox = gtk.VBox()
        self.radio1 = gtk.RadioButton(label="_List of selected tests", use_underline=True)
        self.radio2 = gtk.RadioButton(self.radio1, label="C_riteria entered in the Selection tab\n(Might not match current selection, if it has been modified)", use_underline=True) # Letting C be mnemonic conflicts with cancel button ...
        scriptEngine.registerToggleButton(self.radio1, "choose to save list of selected tests")
        scriptEngine.registerToggleButton(self.radio2, "choose to save selection criteria")
        frameBox.pack_start(self.radio1)
        frameBox.pack_start(self.radio2)
        frame.add(frameBox)
        if not self.enableOptions:
            frame.set_sensitive(False)
        self.fileChooser.set_extra_widget(frame)
    def respond(self, button, saidOK, *args):
        if saidOK:
            if not self.fileChooser.get_filename():
                self.fileChooser.set_current_name("filename_mandatory")
                return
            if os.path.isdir(self.fileChooser.get_filename()):
                self.fileChooser.set_current_folder(self.fileChooser.get_filename())
                self.fileChooser.set_current_name("filename_mandatory")
                return                
            if os.path.exists(self.fileChooser.get_filename()):
                confirmation = QueryDialog(self.dialog, lambda : self.setOptionsAndExit(saidOK), None, None, "\nThe file \n" + self.fileChooser.get_filename().replace("\\", "/") + "\nalready exists.\n\nDo you want to overwrite it?\n")
                confirmation.run()
            else:
                self.setOptionsAndExit(saidOK)
        else:
            self.doExit(saidOK)

    def setOptionsAndExit(self, saidOK):
        # Transfer file name and options back to plugin
        self.plugin.fileName = self.fileChooser.get_filename().replace("\\", "/")
        if self.enableOptions:
            self.plugin.saveTestList = self.radio1.get_active()
        self.doExit(saidOK)
        
    def doExit(self, saidOK):
        self.dialog.hide()
        self.dialog.response(gtk.RESPONSE_NONE)
        if saidOK:
            self.okMethod()
        else:
            self.cancelMethod()

class LoadSelectionDialog(ActionConfirmationDialog):
    def __init__(self, parent, okMethod, cancelMethod, plugin):
        self.fileChooser = gtk.FileChooserWidget(gtk.FILE_CHOOSER_ACTION_OPEN)
        self.fileChooser.set_show_hidden(True)
        self.plugin = plugin
        self.folders, defaultFolder = self.plugin.getDirectories()
        self.startFolder = os.getcwd() # Just to make sure we always have some dir ...
        if defaultFolder and os.path.isdir(os.path.abspath(defaultFolder)):
            self.startFolder = os.path.abspath(defaultFolder)
        ActionConfirmationDialog.__init__(self, parent, okMethod, cancelMethod, plugin)
        self.dialog.set_modal(True)
        self.dialog.set_default_response(gtk.RESPONSE_ACCEPT)

    def createButtons(self):
        self.cancelButton = self.dialog.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL)
        self.okButton = self.dialog.add_button("texttest-stock-load", gtk.RESPONSE_ACCEPT)
        scriptEngine.registerOpenFileChooser(self.fileChooser, "select filter-file", "look in folder")
        scriptEngine.connect("press cancel", "clicked", self.cancelButton, self.respond, gtk.RESPONSE_CANCEL, False)
        scriptEngine.connect("press load", "clicked", self.okButton, self.respond, gtk.RESPONSE_ACCEPT, True)
        self.fileChooser.connect("file-activated", self.simulateOKClick)
        self.fileChooser.connect_after("selection-changed", self.selectionChanged)
        # The OK button is what we monitor in the scriptEngine, so simulate that it is pressed ...
    def simulateOKClick(self, filechooser):
        self.okButton.clicked()
    def selectionChanged(self, *args):
        if self.fileChooser.get_filename():
            scriptEngine.applicationEvent("dialog to be displayed")
        
    def addContents(self):
        alignment = gtk.Alignment()
        alignment.set(1.0, 1.0, 1.0, 1.0)
        alignment.set_padding(5, 5, 5, 5)
        vbox = gtk.VBox()
        alignment.add(vbox)
        self.dialog.vbox.pack_start(alignment, expand=True, fill=True)

        # We want a filechooser dialog to let the user choose where, and
        # with which name, to save the selection.
        self.fileChooser.set_current_folder(self.startFolder)
        for i in xrange(len(self.folders) - 1, -1, -1):
            self.fileChooser.add_shortcut_folder(self.folders[i][1])
        self.fileChooser.set_local_only(True)
        vbox.pack_start(self.fileChooser, expand=True, fill=True)
        parentSize = self.parent.get_size()
        self.dialog.resize(int(parentSize[0] / 1.2), int(parentSize[0] / 1.7))

    def respond(self, button, saidOK, *args):
        if saidOK:
            self.setOptionsAndExit(saidOK)
        else:
            self.doExit(saidOK)

    def setOptionsAndExit(self, saidOK):
        self.plugin.fileName = self.fileChooser.get_filename().replace("\\", "/")
        self.doExit(saidOK)
        
    def doExit(self, saidOK):
        self.dialog.hide()
        self.dialog.response(gtk.RESPONSE_NONE)
        if saidOK:
            self.okMethod()
        else:
            self.cancelMethod()
           
class RenameDialog(ActionConfirmationDialog):
    def __init__(self, parent, okMethod, cancelMethod, plugin):
        ActionConfirmationDialog.__init__(self, parent, okMethod, cancelMethod, plugin)
        self.dialog.set_default_response(gtk.RESPONSE_ACCEPT)
        
    def addContents(self):        
        alignment = gtk.Alignment()
        alignment.set(1.0, 1.0, 1.0, 1.0)
        alignment.set_padding(5, 5, 5, 5)
        vbox = gtk.VBox()
        alignment.add(vbox)
        self.dialog.vbox.pack_start(alignment, expand=True, fill=True)

        header = gtk.Label()
        header.set_markup("<b>" + plugins.convertForMarkup(self.plugin.oldName) + "</b>")
        vbox.pack_start(header)
        hbox2 = gtk.HBox()
        hbox2.pack_start(gtk.Label("\nNew name:"), expand=False, fill=False)        
        vbox.pack_start(hbox2)
        self.entry = gtk.Entry()
        self.entry.set_activates_default(True)
        self.entry.set_text(self.plugin.newName)
        scriptEngine.registerEntry(self.entry, "enter new name ")
        vbox.pack_start(self.entry)
        hbox3 = gtk.HBox()
        hbox3.pack_start(gtk.Label("\nNew description:"), expand=False, fill=False)
        vbox.pack_start(hbox3)
        self.descriptionEntry = gtk.Entry()
        self.descriptionEntry.set_activates_default(True)
        self.descriptionEntry.set_text(self.plugin.newDescription)
        scriptEngine.registerEntry(self.descriptionEntry, "enter new description ")
        vbox.pack_start(self.descriptionEntry)
        
    def respond(self, button, saidOK, *args):
        if saidOK:
            self.plugin.newName = self.entry.get_text()
            self.plugin.newDescription = self.descriptionEntry.get_text()
            message, error = self.plugin.checkNewName()
            if error:
                showErrorDialog(message, self.dialog)
                return
            elif message:
                dialog = QueryDialog(self.dialog, lambda: ActionConfirmationDialog.respond(self, button, saidOK, *args), None, None, message)
                dialog.run()
                return
        ActionConfirmationDialog.respond(self, button, saidOK, *args)
        
class MarkTestDialog(ActionConfirmationDialog):
    def __init__(self, parent, okMethod, cancelMethod, plugin):
        ActionConfirmationDialog.__init__(self, parent, okMethod, cancelMethod, plugin)
        self.dialog.set_default_response(gtk.RESPONSE_ACCEPT)
        
    def addContents(self):        
        alignment = gtk.Alignment()
        alignment.set(1.0, 1.0, 1.0, 1.0)
        alignment.set_padding(5, 5, 5, 5)
        vbox = gtk.VBox()
        alignment.add(vbox)
        self.dialog.vbox.pack_start(alignment, expand=True, fill=True)

        hbox = gtk.HBox()
        hbox.pack_start(gtk.Label("Brief text:"), expand=False, fill=False)
        vbox.pack_start(hbox)
        self.briefEntry = gtk.Entry()
        self.briefEntry.set_text("Marked")
        self.briefEntry.set_activates_default(True)
        scriptEngine.registerEntry(self.briefEntry, "enter new test state brief text ")
        vbox.pack_start(self.briefEntry)

        hbox2 = gtk.HBox()
        hbox2.pack_start(gtk.Label("Free text:"), expand=False, fill=False)
        vbox.pack_start(hbox2)
        self.freeEntry = gtk.Entry()
        self.freeEntry.set_text("Marked at " + plugins.localtime("%d%b%H:%M"))
        self.freeEntry.set_activates_default(True)
        scriptEngine.registerEntry(self.freeEntry, "enter new test state free text ")
        vbox.pack_start(self.freeEntry)
        
    def respond(self, button, saidOK, *args):
        if saidOK:
            self.plugin.newBriefText = self.briefEntry.get_text()
            self.plugin.newFreeText = self.freeEntry.get_text()
        ActionConfirmationDialog.respond(self, button, saidOK, *args)

class FilePropertiesDialog(ActionResultDialog):
    def __init__(self, parent, okMethod, plugin):
        ActionResultDialog.__init__(self, parent, okMethod, plugin)
        self.dialog.set_default_response(gtk.RESPONSE_ACCEPT)

    # xalign = 1.0 means right aligned, 0.0 means left aligned
    def justify(self, text, xalign = 0.0):
        alignment = gtk.Alignment()
        alignment.set(xalign, 0.0, 0.0, 0.0)
        from pango import FontDescription
        label = gtk.Label(text)
        alignment.add(label)
        return alignment

    def addContents(self):
        dirToProperties = {}
        for prop in self.plugin.properties:
            if not dirToProperties.has_key(prop.dir):
                dirToProperties[prop.dir] = [ prop ]
            else:
                dirToProperties[prop.dir].append(prop)

        vbox = gtk.VBox()
        for dir, properties in dirToProperties.items():
            expander = gtk.Expander()
            expander.set_label_widget(self.justify(dir))
            table = gtk.Table(len(properties), 7)
            table.set_col_spacings(5)
            row = 0
            for prop in properties:
                values = prop.getUnixRepresentation()
                table.attach(self.justify(values[0] + values[1], 1.0), 0, 1, row, row + 1)
                table.attach(self.justify(values[2], 1.0), 1, 2, row, row + 1)
                table.attach(self.justify(values[3], 0.0), 2, 3, row, row + 1)
                table.attach(self.justify(values[4], 0.0), 3, 4, row, row + 1)
                table.attach(self.justify(values[5], 1.0), 4, 5, row, row + 1)
                table.attach(self.justify(values[6], 1.0), 5, 6, row, row + 1)
                table.attach(self.justify(prop.filename, 0.0), 6, 7, row, row + 1)
                row += 1
            hbox = gtk.HBox()
            hbox.pack_start(table, expand=False, fill=False)
            innerBorder = gtk.Alignment()
            innerBorder.set_padding(5, 0, 0, 0)
            innerBorder.add(hbox)
            expander.add(innerBorder)
            expander.set_expanded(True)
            border = gtk.Alignment()
            border.set_padding(5, 5, 5, 5)
            border.add(expander)
            vbox.pack_start(border, expand=False, fill=False)
        self.dialog.vbox.pack_start(vbox, expand=True, fill=True)
        
# It's a bit unfortunate that this has to be here, but unfortunately texttestgui
# cannot load dialogs from matador without some additional work. Also, having it
# here avoids matador importing guidialogs, and hence gtk.
class CreatePerformanceReportDialog(ActionConfirmationDialog):
    def __init__(self, parent, okMethod, cancelMethod, plugin):
        ActionConfirmationDialog.__init__(self, parent, okMethod, cancelMethod, plugin)
        self.dialog.set_default_response(gtk.RESPONSE_ACCEPT)

    def addContents(self):
        # A simple entry for the path, and one for the versions ...
        self.dirEntry = gtk.Entry()
        self.versionsEntry = gtk.Entry()
        self.dirEntry.set_activates_default(True)
        self.versionsEntry.set_activates_default(True)
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
        self.dialog.vbox.pack_start(table, expand = True, fill = True)
        
    def respond(self, button, saidOK, *args):
        if saidOK:
            self.plugin.rootDir = os.path.abspath(self.dirEntry.get_text())
            self.plugin.versions = self.versionsEntry.get_text().replace(" ", "").split(",")
        ActionConfirmationDialog.respond(self, button, saidOK, *args)
