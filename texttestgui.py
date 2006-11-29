#!/usr/bin/env python

# GUI for TextTest written with PyGTK
# First make sure we can import the GUI modules: if we can't, throw appropriate exceptions

def raiseException(msg):
    from plugins import TextTestError
    raise TextTestError, "Could not start TextTest GUI due to PyGTK GUI library problems :\n" + msg

try:
    import gtk
except:
    raiseException("Unable to import module 'gtk'")

major, minor, debug = gtk.pygtk_version
if major < 2 or minor < 4:
    raiseException("TextTest GUI requires at least PyGTK 2.4 : found version " + str(major) + "." + str(minor))

try:
    import gobject
except:
    raiseException("Unable to import module 'gobject'")

import guiplugins, plugins, os, string, time, sys, locale
from threading import Thread, currentThread
from gtkusecase import ScriptEngine, TreeModelIndexer, RadioGroupIndexer
from ndict import seqdict
from respond import Responder
from copy import copy

import traceback

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

def showError(message, parent=None):
    guilog.info("ERROR: " + message)
    dialog = gtk.Dialog("TextTest Error", parent, buttons=(gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
    dialog.set_modal(True)
    dialog.vbox.pack_start(createDialogMessage(message, gtk.STOCK_DIALOG_ERROR), expand=True, fill=True)
    scriptEngine.connect("agree to texttest message", "response", dialog, destroyDialog, gtk.RESPONSE_ACCEPT)
    dialog.show_all()
    dialog.action_area.get_children()[len(dialog.action_area.get_children()) - 1].grab_focus()

def showWarning(message, parent=None):
    guilog.info("WARNING: " + message)
    dialog = gtk.Dialog("TextTest Warning", parent, buttons=(gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
    dialog.set_modal(True)
    dialog.vbox.pack_start(createDialogMessage(message, gtk.STOCK_DIALOG_WARNING), expand=True, fill=True)
    scriptEngine.connect("agree to texttest message", "response", dialog, destroyDialog, gtk.RESPONSE_ACCEPT)
    dialog.show_all()
    dialog.action_area.get_children()[len(dialog.action_area.get_children()) - 1].grab_focus()

class DoubleCheckDialog:
    def __init__(self, message, yesMethod, parent=None):
        self.dialog = gtk.Dialog("TextTest Query", parent, flags=gtk.DIALOG_MODAL)
        self.yesMethod = yesMethod
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
        self.dialog.action_area.get_children()[len(self.dialog.action_area.get_children()) - 1].grab_focus()

    def respond(self, button, saidYes, *args):
        if saidYes:
            self.yesMethod()
        self.dialog.destroy()

def renderParentsBold(column, cell, model, iter):
    if model.iter_has_child(iter):
        cell.set_property('font', "bold")
    else:
        cell.set_property('font', "")

def renderSuitesBold(column, cell, model, iter):
    if model.get_value(iter, 2).classId() == "test-case":
        cell.set_property('font', "")
    else:
        cell.set_property('font', "bold")

def getTestColour(test, category):
    colours = test.getConfigValue("test_colours")
    if colours.has_key(category):
        return colours[category]
    else:
        # Everything unknown is assumed to be a new type of failure...
        return colours["failure"]

# base class for all "GUI" classes which manage parts of the display
class SubGUI(plugins.Observable):
    def __init__(self):
        plugins.Observable.__init__(self)
        self.active = False
    def setActive(self, newValue):
        self.active = newValue
    def activate(self):
        self.setActive(True)
        self.contentsChanged()
    def deactivate(self):
        self.setActive(False)
    def contentsChanged(self):
        if self.active and self.shouldShowCurrent():
            guilog.info("") # blank line for demarcation
            self.describe()
    def describe(self):
        pass
    def createView(self):
        pass
    def shouldShowCurrent(self):
        return True # sometimes these things don't have anything to display
    def getTabTitle(self):
        return "Need Title For Tab!"
    def getGroupTabTitle(self):
        return "Test"
    def forceVisible(self, tests):
        return False
    def addScrollBars(self, view):
        window = gtk.ScrolledWindow()
        window.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.addToScrolledWindow(window, view)
        window.show()
        return window

    def addToScrolledWindow(self, window, widget):
        if isinstance(widget, gtk.VBox):
            window.add_with_viewport(widget)
        else:
            window.add(widget)

class ToggleVisibilityGUI(guiplugins.InteractiveAction):
    def __init__(self, rootSuites, title, startValue):
        guiplugins.InteractiveAction.__init__(self, rootSuites)
        self.title = title
        self.startValue = startValue
    def getInterfaceDescription(self):
        description = "<menubar>\n<menu action=\"viewmenu\">\n<menuitem action=\"" + self.getSecondaryTitle() + "\"/>\n</menu>\n</menubar>\n"
        return description
    def getStartValue(self):
        return self.startValue
    def getTitle(self):
        return self.title
    def getScriptTitle(self, tab):
        return "Toggle " + self.getTitle().replace("_", "").lower() + " visibility" 
    def isToggle(self):
        return True;
    def performOnCurrent(self):
        self.notify("Toggle" + self.getTitle().replace("_", "").replace(" ", ""))
    def messageAfterPerform(self):
        pass

def getGtkRcFile():
    configDir = plugins.getPersonalConfigDir()
    if not configDir:
        return
    
    file = os.path.join(configDir, ".texttest_gtk")
    if os.path.isfile(file):
        return file
        
#
# A class responsible for putting messages in the status bar.
# It is also responsible for keeping the throbber rotating
# while actions are under way.
# 
class GUIStatusMonitor:
    def __init__(self):
        self.throbber = None
        self.animation = None
        self.pixbuf = None
        self.label = None

    def busy(self):
        return self.pixbuf != None
        
    def notifyActionStart(self, message=""):
        if self.throbber:
            if self.pixbuf: # We didn't do ActionStop ...
                self.notifyActionStop()
            self.pixbuf = self.throbber.get_pixbuf()
            self.throbber.set_from_animation(self.animation)
            self.throbber.grab_add()
            
    def notifyActionProgress(self, message=""):
        while gtk.events_pending():
            gtk.main_iteration(False)

    def notifyActionStop(self, message=""):
        if self.throbber:
            self.throbber.set_from_pixbuf(self.pixbuf)
            self.pixbuf = None
            self.throbber.grab_remove()
        
    def notifyStatus(self, message):
        if self.label:
            guilog.info("")
            guilog.info("Changing GUI status to: '" + message + "'")
            self.label.set_markup(message)
            
    def createStatusbar(self, staticIcon, animationIcon):
        hbox = gtk.HBox()
        self.label = gtk.Label()
        self.label.set_use_markup(True)
        hbox.pack_start(self.label, expand=False, fill=False)
        try:
            temp = gtk.gdk.pixbuf_new_from_file(staticIcon)
            self.throbber = gtk.Image()
            self.throbber.set_from_pixbuf(temp)
            self.animation = gtk.gdk.PixbufAnimation(animationIcon)
            hbox.pack_end(self.throbber, expand=False, fill=False)
        except Exception, e:
            plugins.printWarning("Failed to create icons for the status throbber:\n" + str(e) + "\nAs a result, the throbber will be disabled.")
            self.throbber = None
        self.notifyStatus("TextTest started at " + plugins.localtime() + ".")
        frame = gtk.Frame()
        frame.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        frame.add(hbox)
        frame.show_all()
        frame.hide()
        return frame

# To make it easier for all sorts of things to connect
# to the status bar, let it be global, at least for now ...
statusMonitor = GUIStatusMonitor()

class IdleHandlerManager:
    def __init__(self, dynamic):
        self.dynamic = dynamic
        self.sourceId = -1
    def notifyActionStart(self, message):
        # To make it possible to have an while-events-process loop
        # to update the GUI during actions, we need to make sure the idle
        # process isn't run. We hence remove that for a while here ...
        if self.sourceId > 0:
            gobject.source_remove(self.sourceId)
    def notifyActionStop(self, message):
        # Activate idle function again, see comment in notifyActionStart
        if self.sourceId > 0:
            self.sourceId = self.enableHandler()
    def notifySetUpGUIComplete(self):
        self.sourceId = self.enableHandler()

    def enableHandler(self):
        if self.dynamic:
            return plugins.Observable.threadedNotificationHandler.enablePoll(gobject.idle_add)
        else:
            return gobject.idle_add(self.pickUpProcess)
        
    def pickUpProcess(self):
        process = guiplugins.processTerminationMonitor.getTerminatedProcess()
        if process:
            try:
                process.runExitHandler()
            except plugins.TextTestError, e:
                showError(str(e), globalTopWindow)
        
        # We must sleep for a bit, or we use the whole CPU (busy-wait)
        time.sleep(0.1)
        return True
    def notifyExit(self):
        guiplugins.processTerminationMonitor.killAll()

class TextTestGUI(Responder, plugins.Observable):
    defaultGUIDescription = '''
<ui>
  <menubar>
    <menu action="filemenu"></menu>
    <menu action="viewmenu"></menu>
    <menu action="actionmenu"></menu>
  </menubar>
  <toolbar>
  </toolbar>
</ui>
'''
    def __init__(self, optionMap):
        self.readGtkRCFile()
        self.dynamic = not optionMap.has_key("gx")
        Responder.__init__(self, optionMap)
        plugins.Observable.__init__(self)
        guiplugins.scriptEngine = self.scriptEngine
        self.rootSuites = []

        self.testTreeGUI = TestTreeGUI(self.dynamic)
        self.testFileGUI = TestFileGUI(self.dynamic)
        self.appFileGUI = ApplicationFileGUI(self.dynamic)
        self.textInfoGUI = TextInfoGUI()
        self.progressMonitor = TestProgressMonitor(self.dynamic)
        self.progressBar = TestProgressBar()
        self.idleManager = IdleHandlerManager(self.dynamic)

        self.setUpObservers() # uses the above 5
        self.topWindow = None

        self.uiManager = gtk.UIManager()
        self.setUpUIManager()
    def setUpObservers(self):
        # watch for test selection and test count
        for observer in [ self.testFileGUI, self.appFileGUI, self.textInfoGUI ]:
            self.testTreeGUI.addObserver(observer)
        # watch for category selections
        self.progressMonitor.addObserver(self.testTreeGUI)
        for observer in [ self.textInfoGUI, self.testTreeGUI, self.testFileGUI, \
                          self.progressBar, self.progressMonitor, self.idleManager ]:            
            self.addObserver(observer) # forwarding of test observer mechanism
    def setUpUIManager(self):
        # Create GUI manager, and a few default action groups
        basicActions = gtk.ActionGroup("Basic")
        basicActions.add_actions([("filemenu", None, "_File"),
                                  ("viewmenu", None, "_View"),
                                  ("actionmenu", None, "_Actions")])
        self.uiManager.insert_action_group(basicActions, 0)
        self.uiManager.insert_action_group(gtk.ActionGroup("Suite"), 1)
        self.uiManager.insert_action_group(gtk.ActionGroup("Case"), 2)
    def needsOwnThread(self):
        return True
    def readGtkRCFile(self):
        file = getGtkRcFile()
        if file:
            gtk.rc_add_default_file(file)
    def setUpScriptEngine(self):
        guiplugins.setUpGuiLog(self.dynamic)
        global guilog, scriptEngine
        from guiplugins import guilog
        scriptEngine = ScriptEngine(guilog, enableShortcuts=1)
        self.scriptEngine = scriptEngine
    def needsTestRuns(self):
        return self.dynamic
    def addSuite(self, suite):
        self.rootSuites.append(suite)
        self.testTreeGUI.addSuite(suite)
        self.progressBar.addSuite(suite)
    def createInteractiveActions(self):
        actions = self.createVisibilityActions()
        actions += guiplugins.interactiveActionHandler.getInstances(self.dynamic, self.rootSuites)
        for action in actions:
            # These actions might change the tree view selection or the status bar, need to observe them
            action.addObserver(self.testTreeGUI)
            action.addObserver(statusMonitor)
            action.addObserver(self.idleManager)
            action.addObserver(self) # watch for quits, size changes etc.
            # Some depend on the test selection or currently viewed test also
            if hasattr(action, "notifyNewTestSelection"):
                self.testTreeGUI.addObserver(action)
            if hasattr(action, "notifyNewFileSelection") or hasattr(action, "notifyViewFile"):
                self.testFileGUI.addObserver(action)
                self.appFileGUI.addObserver(action)
        return actions
    def createVisibilityActions(self):
        toolbarVisible = (self.dynamic and self.getConfigValue("dynamic_gui_show_toolbar")) or \
                             (not self.dynamic and self.getConfigValue("static_gui_show_toolbar"))
        toggleToolbar = ToggleVisibilityGUI(self.rootSuites, "_Toolbar", toolbarVisible)
        toggleShortcutbar = ToggleVisibilityGUI(self.rootSuites, "_Shortcut bar", self.getConfigValue("add_shortcut_bar"))
        toggleStatusbar = ToggleVisibilityGUI(self.rootSuites, "_Status bar", self.getConfigValue("add_status_bar"))
        return [ toggleToolbar, toggleShortcutbar, toggleStatusbar ]
    
    def getConfigValue(self, configName):
        return self.rootSuites[0].app.getConfigValue(configName)
    
    def run(self):        
        intvActions = self.createInteractiveActions()

        rightWindowGUI = self.createRightWindowGUI(intvActions)
        mainWindowGUI = self.createPaned(self.testTreeGUI, rightWindowGUI, horizontal=True)
        
        self.createTopWindow(mainWindowGUI, intvActions)
        mainWindowGUI.activate()

        guilog.info("") # for demarcation
        self.notify("SetUpGUIComplete")
        guilog.info("Default widget is " + str(self.topWindow.get_focus().__class__))
        gtk.main()
    def notifyExit(self, *args):
        self.notify("Exit")
        self.topWindow.destroy()
        sys.stdout.flush()
        gtk.main_quit()
    def createActionGUIForTab(self, action):
        if len(action.getOptionGroups()) == 1 and action.canPerform():
            return ActionGUI(action, self.uiManager, fromTab=True)
    def createActionTabGUIs(self, actions):
        actionTabGUIs = []
        for action in actions:
            actionGUI = self.createActionGUIForTab(action)
            for optionGroup in action.getOptionGroups():
                if optionGroup.switches or optionGroup.options:
                    tabGUI = ActionTabGUI(optionGroup, action, actionGUI)
                    self.testTreeGUI.addObserver(tabGUI)
                    self.addObserver(tabGUI) # pick up lifecycle changes
                    actionTabGUIs.append(tabGUI)
        return actionTabGUIs
    def getSeparatorPosition(self, horizontal):
        if horizontal:
            return float(self.getWindowOption("vertical_separator_position", 0.5))
        else:
            return float(self.getWindowOption("horizontal_separator_position", 0.46))
    def getWindowOption(self, name, default):
        optionDir = self.getConfigValue("window_size")
        if self.dynamic:
            return optionDir.get("dynamic_" + name, default)
        else:
            return optionDir.get("static_" + name, default)

    def createPaned(self, gui1, gui2, horizontal):
        paneGUI = PaneGUI([ gui1, gui2 ], self.getSeparatorPosition(horizontal), horizontal)
        self.addObserver(paneGUI)
        return paneGUI

    def createRightWindowGUI(self, intvActions):
        tabGUIs = [ self.textInfoGUI, self.progressMonitor ] + self.createActionTabGUIs(intvActions)
        buttonBarGUI = self.createButtonBarGUI(intvActions)
        topTestViewGUI = BoxGUI([ self.testFileGUI, buttonBarGUI ], horizontal=False)

        if self.dynamic:
            notebookGUI = NotebookGUI(self.classifyByTitle(tabGUIs), self.getNotebookScriptName("Top"))
            self.testTreeGUI.addObserver(notebookGUI)
            return self.createPaned(topTestViewGUI, notebookGUI, horizontal=False)
        else:
            subNotebookGUIs = self.createNotebookGUIs(tabGUIs)
            tabInfo = seqdict()
            tabInfo["Test"] = self.createPaned(topTestViewGUI, subNotebookGUIs["Test"], horizontal=False)
            tabInfo["Selection"] = subNotebookGUIs["Selection"]
            tabInfo["Running"] = self.createPaned(self.appFileGUI, subNotebookGUIs["Running"], horizontal=False)
            notebookGUI = NotebookGUI(tabInfo, self.getNotebookScriptName("Top"), self.getDefaultPage())
            self.testTreeGUI.addObserver(notebookGUI)
            for subNotebookGUI in subNotebookGUIs.values():
                self.testTreeGUI.addObserver(subNotebookGUI)
            return notebookGUI

    def getDefaultPage(self):
        if self.testTreeGUI.totalNofTests >= 10:
            return "Selection"
        else:
            return "Test"
        
    def createButtonBarGUI(self, intvActions):
        buttonBarGUIs = []
        for action in intvActions:
            if action.inButtonBar():
                buttonBarGUI = ActionGUI(action, self.uiManager)
                self.testTreeGUI.addObserver(buttonBarGUI)
                buttonBarGUIs.append(buttonBarGUI)
        return BoxGUI(buttonBarGUIs, horizontal=True, reversed=True)

    def getNotebookScriptName(self, tabName):
        if tabName == "Top":
            return "view options for"
        else:
            return "view sub-options for " + tabName.lower() + " :"

    def classifyByTitle(self, tabGUIs):
        tabInfo = seqdict()
        for tabGUI in tabGUIs:
            tabInfo[tabGUI.getTabTitle()] = tabGUI
        return tabInfo
    def createNotebookGUIs(self, tabGUIs):
        tabInfo = seqdict()
        for tabName in [ "Test", "Selection", "Running" ]:
            currTabGUIs = filter(lambda tabGUI: tabGUI.getGroupTabTitle() == tabName, tabGUIs)
            notebookGUI = NotebookGUI(self.classifyByTitle(currTabGUIs), self.getNotebookScriptName(tabName))
            tabInfo[tabName] = notebookGUI
        return tabInfo
    def notifyLifecycleChange(self, test, state, changeDesc):
        # Working around python bug 853411: main thread must do all forking
        state.notifyInMainThread()

        self.notify("LifecycleChange", test, state, changeDesc)
    def notifyFileChange(self, test):
        self.notify("FileChange", test)
    def notifyContentChange(self, suite):
        self.notify("ContentChange", suite)
    def notifyAdd(self, test):
        self.notify("Add", test)
    def notifyRemove(self, test):
        self.notify("Remove", test)
    def notifyAllComplete(self):
        plugins.Observable.threadedNotificationHandler.disablePoll()
    def createTopWindow(self, mainWindowGUI, intvActions):
        # Create toplevel window to show it all.
        self.topWindow = gtk.Window(gtk.WINDOW_TOPLEVEL)
        global globalTopWindow
        globalTopWindow = self.topWindow
        if self.dynamic:
            self.topWindow.set_title("TextTest dynamic GUI (tests started at " + plugins.startTimeString() + ")")
        else:
            self.topWindow.set_title("TextTest static GUI : management of tests for " + self.getAppNames())
            
        guilog.info("Top Window title set to " + self.topWindow.get_title())
        self.topWindow.add_accel_group(self.uiManager.get_accel_group())
        self.topWindow.add(self.createVBox(mainWindowGUI, intvActions))
        self.topWindow.show()
        self.adjustSize()
        scriptEngine.connect("close window", "delete_event", self.topWindow, self.notifyExit)
        return self.topWindow
    def contentsChanged(self):
        pass # doesn't use this yet
    def getAppNames(self):
        names = []
        for suite in self.rootSuites:
            if not suite.app.fullName in names:
                names.append(suite.app.fullName)
        return string.join(names, ",")
    def createVBox(self, mainWindowGUI, intvActions):
        vbox = gtk.VBox()
        self.placeTopWidgets(vbox, intvActions)
        vbox.pack_start(mainWindowGUI.createView(), expand=True, fill=True)
        self.shortcutBar = scriptEngine.createShortcutBar()
        vbox.pack_start(self.shortcutBar, expand=False, fill=False)
        if self.getConfigValue("add_shortcut_bar"):            
            self.shortcutBar.show()
            
        inactiveThrobberIcon = self.getConfigValue("gui_throbber_inactive")
        activeThrobberIcon = self.getConfigValue("gui_throbber_active")
        self.statusBar = statusMonitor.createStatusbar(inactiveThrobberIcon, activeThrobberIcon)
        if self.getConfigValue("add_status_bar"):
            self.statusBar.show()
        vbox.pack_start(self.statusBar, expand=False, fill=False)

        vbox.show()
        return vbox
        
    def adjustSize(self):
        if int(self.getWindowOption("maximize", 0)):
            guilog.info("Maximising top window...")
            self.topWindow.maximize()
        else:
            width = self.getWindowDimension("width")
            height = self.getWindowDimension("height")
            self.topWindow.resize(width, height)

    def getInterfaceDescription(self, toolBarActions):
        description = "<ui>\n"
        for instance in toolBarActions:
            description += instance.getInterfaceDescription()
        description += "</ui>"
        return description

    def ensureWholeToolbarVisible(self):
        toolbar = self.uiManager.get_widget("/toolbar")
        if toolbar:
            for item in toolbar.get_children(): 
                item.set_is_important(True) # Or newly added children without stock ids won't be visible in gtk.TOOLBAR_BOTH_HORIZ style
       
    def placeTopWidgets(self, vbox, intvActions):
        # Initialize
        self.uiManager.add_ui_from_string(self.defaultGUIDescription)
        toolBarActions = filter(lambda instance : instance.inToolBar(), intvActions)
        guilog.info("") # blank line for demarcation
        for action in toolBarActions:
            toolBarGUI = ActionGUI(action, self.uiManager)
            self.testTreeGUI.addObserver(toolBarGUI)
            toolBarGUI.describe()
    
        self.uiManager.add_ui_from_string(self.getInterfaceDescription(toolBarActions))
        self.uiManager.ensure_update()
        self.ensureWholeToolbarVisible()
  
        # We always create toolbar and menu, we just don't show them if we
        # don't want them. That way, we can e.g. turn the toolbar on from
        # the view menu
        menubar = self.uiManager.get_widget("/menubar")
        toolbar = self.uiManager.get_widget("/toolbar")

        toolbarHandle = gtk.HandleBox()
        toolbarHandle.add(toolbar)
        for item in toolbar.get_children():
            item.set_is_important(True)
        toolbar.set_orientation(gtk.ORIENTATION_HORIZONTAL)

        hbox = gtk.HBox()
        vbox.pack_start(menubar, expand=False, fill=False)
        hbox.pack_start(toolbarHandle, expand=True, fill=True)

        showToolbar = (self.dynamic and self.getConfigValue("dynamic_gui_show_toolbar")) or \
                      (not self.dynamic and self.getConfigValue("static_gui_show_toolbar"))
        showMenu = (self.dynamic and self.getConfigValue("dynamic_gui_show_menubar")) or \
                   (not self.dynamic and self.getConfigValue("static_gui_show_menubar"))

        if self.dynamic:
            progressBar = self.progressBar.createView()
            progressBar.show()
            if showToolbar:
                width = 7 # Looks good, same as gtk.Paned border width
            else:
                width = 0                
            alignment = gtk.Alignment()
            alignment.set(1.0, 1.0, 1.0, 1.0)
            alignment.set_padding(width, width, 1, width)
            alignment.add(progressBar)
            if showToolbar:
                toolItem = gtk.ToolItem()
                toolItem.add(alignment)
                toolItem.set_expand(True)
                toolbar.insert(toolItem, -1)
            else:
                hbox.pack_start(alignment, expand=True, fill=True)

        vbox.pack_start(hbox, expand=False, fill=False)
        vbox.show_all()
        if not showToolbar:
            toolbarHandle.hide()
        if not showMenu:
            menubar.hide()
    def getConfigValue(self, configName):
        return self.rootSuites[0].app.getConfigValue(configName)
    def getWindowDimension(self, dimensionName):
        pixelDimension = self.getWindowOption(dimensionName + "_pixels", None)
        if pixelDimension is not None:
            guilog.info("Setting window " + dimensionName + " to " + pixelDimension + " pixels.") 
            return int(pixelDimension)
        else:
            fullSize = eval("gtk.gdk.screen_" + dimensionName + "()")
            defaultProportion = self.getDefaultWindowProportion(dimensionName)
            proportion = float(self.getWindowOption(dimensionName + "_screen", defaultProportion))
            guilog.info("Setting window " + dimensionName + " to " + repr(int(100.0 * proportion)) + "% of screen.")
            return int(fullSize * proportion)
    def getDefaultWindowProportion(self, dimensionName):
        if dimensionName == "height":
            return float(5.0) / 6
        else:
            return 0.6
    def widgetToggleVisibility(self, widget):
        if widget.get_property('visible'):
            widget.hide()
            return False
        else:
            widget.show()
            return True    
    def notifyToggleToolbar(self):
        toolbar = self.uiManager.get_widget("/toolbar")
        # actual toolbar lives in a handle, which is what we want to hide/show ...
        visible = self.widgetToggleVisibility(toolbar.get_parent())
        guilog.info("Toggled visibility of toolbar: " + str(visible))
    def notifyToggleShortcutbar(self):
        visible = self.widgetToggleVisibility(self.shortcutBar)
        guilog.info("Toggled visibility of shortcut bar: " + str(visible))
    def notifyToggleStatusbar(self):
        visible = self.widgetToggleVisibility(self.statusBar)    
        guilog.info("Toggled visibility of status bar: " + str(visible))
        
class TestTreeGUI(SubGUI):
    def __init__(self, dynamic):
        SubGUI.__init__(self)
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT,\
                                   gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_BOOLEAN)
        self.itermap = seqdict()
        self.selection = None
        self.selecting = False
        self.dynamic = dynamic
        self.totalNofTests = 0
        self.nofSelectedTests = 0
        self.totalNofTestsShown = 0
        self.collapseStatic = False
        self.successPerSuite = {} # map from suite to number succeeded
        self.collapsedRows = {}
    def contentsChanged(self):
        pass # Not really integrated into the description mechanism
    def addSuite(self, suite):
        if not self.dynamic:
            self.collapseStatic = suite.getConfigValue("static_collapse_suites")
        if self.totalNofTests == 0:
            self.notify("NewTestSelection", [ suite ])
        size = suite.size()
        self.totalNofTests += size
        if not self.dynamic or size > 0:
            self.addSuiteWithParent(suite, None)
    def visibleByDefault(self, suite, parent):
        if parent == None or not self.dynamic:
            return True
        hideCategories = suite.getConfigValue("hide_test_category")
        return "non_started" not in hideCategories
    def addSuiteWithParent(self, suite, parent):    
        iter = self.model.insert_before(parent, None)
        nodeName = suite.name
        if parent == None:
            appName = suite.app.name + suite.app.versionSuffix()
            if appName != nodeName:
                nodeName += " (" + appName + ")"
        self.model.set_value(iter, 0, nodeName)
        self.model.set_value(iter, 2, suite)
        self.model.set_value(iter, 3, suite.uniqueName)
        self.model.set_value(iter, 6, self.visibleByDefault(suite, parent))
        storeIter = iter.copy()
        self.itermap[suite] = storeIter
        self.updateStateInModel(suite, iter, suite.state)
        if suite.classId() == "test-suite":
            for test in suite.testcases:
                self.addSuiteWithParent(test, iter)
        return iter
    def updateStateInModel(self, test, iter, state):
        if not self.dynamic:
            return self.modelUpdate(iter, getTestColour(test, "static"))

        resultType, summary = state.getTypeBreakdown()
        return self.modelUpdate(iter, getTestColour(test, resultType), summary, getTestColour(test, state.category))
    def modelUpdate(self, iter, colour, details="", colour2=None):
        if not colour2:
            colour2 = colour
        self.model.set_value(iter, 1, colour)
        if self.dynamic:
            self.model.set_value(iter, 4, details)
            self.model.set_value(iter, 5, colour2)
    def createView(self):
        self.filteredModel = self.model.filter_new()
        # It seems that TreeModelFilter might not like new
        # rows being added to the original model - the AddUsers
        # test crashed/produced a gtk warning before I added
        # this if statement (for the dynamic GUI we never add rows)
        if self.dynamic:
            self.filteredModel.set_visible_column(6)
        self.treeView = gtk.TreeView(self.filteredModel)
        self.selection = self.treeView.get_selection()
        self.selection.set_mode(gtk.SELECTION_MULTIPLE)
        self.selection.connect("changed", self.selectionChanged)
        testRenderer = gtk.CellRendererText()
        testsColumnTitle = "Tests: 0/" + str(self.totalNofTests) + " selected"
        if self.dynamic:
            testsColumnTitle = "Tests: 0/" + str(self.totalNofTests) + " selected, all visible"
        self.testsColumn = gtk.TreeViewColumn(testsColumnTitle, testRenderer, text=0, background=1)
        self.testsColumn.set_cell_data_func(testRenderer, renderSuitesBold)
        self.treeView.append_column(self.testsColumn)
        if self.dynamic:
            detailsRenderer = gtk.CellRendererText()
            perfColumn = gtk.TreeViewColumn("Details", detailsRenderer, text=4, background=5)
            self.treeView.append_column(perfColumn)

        modelIndexer = TreeModelIndexer(self.filteredModel, self.testsColumn, 3)
        scriptEngine.monitorExpansion(self.treeView, "show test suite", "hide test suite", modelIndexer)
        self.treeView.connect('row-expanded', self.rowExpanded)
        guilog.info("") # demarcation
        guilog.info("Expanding tests in tree view...")
        self.expandLevel(self.treeView, self.filteredModel.get_iter_root())
        
        scriptEngine.monitor("set test selection to", self.selection, modelIndexer)
        self.treeView.show()
        if self.dynamic:
            self.filteredModel.connect('row-inserted', self.rowInserted)
            self.reFilter()

        return self.addScrollBars(self.treeView)
    
    def notifySetUpGUIComplete(self):
        # avoid the quit button getting initial focus, give it to the tree view (why not?)
        self.treeView.grab_focus()
    def rowCollapsed(self, treeview, iter, path):
        if self.dynamic:
            realPath = self.filteredModel.convert_path_to_child_path(path)
            self.collapsedRows[realPath] = 1
    def rowExpanded(self, treeview, iter, path):
        if self.dynamic:
            realPath = self.filteredModel.convert_path_to_child_path(path)
            if self.collapsedRows.has_key(realPath):
                del self.collapsedRows[realPath]
        self.expandLevel(treeview, self.filteredModel.iter_children(iter), not self.collapseStatic)
    def rowInserted(self, model, path, iter):
        realPath = self.filteredModel.convert_path_to_child_path(path)
        self.expandRow(self.filteredModel.iter_parent(iter), False)
        self.visibilityChanged()
    def expandRow(self, iter, recurse):
        if iter == None:
            return
        path = self.filteredModel.get_path(iter)
        realPath = self.filteredModel.convert_path_to_child_path(path)
        
        # Iterate over children, call self if they have children
        if not self.collapsedRows.has_key(realPath):
            self.treeView.expand_row(path, open_all=False)
        if recurse:
            childIter = self.filteredModel.iter_children(iter)
            while (childIter != None):
                if self.filteredModel.iter_has_child(childIter):
                    self.expandRow(childIter, True)
                childIter = self.filteredModel.iter_next(childIter)
                
    def collapseRow(self, iter):
        # To make sure that the path is marked as 'collapsed' even if the row cannot be collapsed
        # (if the suite is empty, or not shown at all), we set self.collapsedRow manually, instead of
        # waiting for rowCollapsed() to do it at the 'row-collapsed' signal (which will not be emitted
        # in the above cases)
        path = self.model.get_path(iter)
        self.collapsedRows[path] = 1
        try:
            filterPath = self.filteredModel.convert_child_path_to_path(path)
            self.selection.get_tree_view().collapse_row(filterPath)
        except:
            pass

    def selectionChanged(self, *args):
        if self.selecting or hasattr(self.selection, "unseen_changes"):
            return
        
        allSelected, selectedTests = self.getSelected()
        self.nofSelectedTests = len(selectedTests)
        self.updateColumnTitle(printToLog=True)
        self.notify("NewTestSelection", allSelected)
    def visibilityChanged(self):
        self.totalNofTestsShown = 0
        self.filteredModel.foreach(self.countVisible)
        self.updateColumnTitle(printToLog=False)        
    def updateColumnTitle(self, printToLog=True):
        title = "Tests: "
        if self.nofSelectedTests == self.totalNofTests:
            title += "All " + str(self.totalNofTests) + " selected"
        else:
            title += str(self.nofSelectedTests) + "/" + str(self.totalNofTests) + " selected"
        if self.dynamic:
            if self.totalNofTestsShown == self.totalNofTests:
                title += ", all visible"
            else:
                title += ", " + str(self.totalNofTestsShown) + " visible"
        self.testsColumn.set_title(title)
        if printToLog:
            guilog.info(title)
    def getSelected(self):
        # add self as an observer
        allSelected, selectedTests = [], []
        self.selection.selected_foreach(self.addSelTest, (allSelected, selectedTests))
        return allSelected, selectedTests
    def addSelTest(self, model, path, iter, lists, *args):
        test = model.get_value(iter, 2)
        allSelected, selectedTests = lists
        allSelected.append(test)
        if test.classId() == "test-case":
            selectedTests.append(test)
    def findIter(self, test):
        try:
            return self.filteredModel.convert_child_iter_to_iter(self.itermap[test])
        except RuntimeError:
            pass # convert_child_iter_to_iter throws RunTimeError if the row is hidden in the TreeModelFilter
    def notifyNewTestSelection(self, selTests, selectCollapsed=True):
        self.selectTestRows(selTests, selectCollapsed)
        self.selectionChanged()
    def selectTestRows(self, selTests, selectCollapsed=True):
        self.selecting = True # don't respond to each individual programmatic change here
        self.selection.unselect_all()
        firstPath = None
        for test in selTests:
            iter = self.findIter(test)
            if not iter:
                continue
            path = self.filteredModel.get_path(iter) 
            if not firstPath:
                firstPath = path
            if selectCollapsed:
                self.selection.get_tree_view().expand_to_path(path)
            self.selection.select_iter(iter)
        self.selection.get_tree_view().grab_focus()
        if firstPath is not None:
            self.selection.get_tree_view().scroll_to_cell(firstPath, None, True, 0.1)
        guilog.info("Marking " + str(self.selection.count_selected_rows()) + " tests as selected")
        self.selecting = False
    def countVisible(self, model, path, iter):
        # When rows are added, they are first empty, and asking for
        # classId on NoneType gives an error. See e.g.
        # http://www.async.com.br/faq/pygtk/index.py?req=show&file=faq13.028.htp
        if model.get_value(iter, 2) == None:
            return
        if model.get_value(iter, 2).classId() == "test-case":
            self.totalNofTestsShown = self.totalNofTestsShown + 1
    def expandLevel(self, view, iter, recursive=True):
        # Make sure expanding expands everything, better than just one level as default...
        # Avoid using view.expand_row(path, open_all=True), as the open_all flag
        # doesn't seem to send the correct 'row-expanded' signal for all rows ...
        # This way, the signals are generated one at a time and we call back into here.
        model = view.get_model()
        while (iter != None):
            test = model.get_value(iter, 2)
            guilog.info("-> " + test.getIndent() + "Added " + repr(test) + " to test tree view.")
            if recursive:
                view.expand_row(model.get_path(iter), open_all=False)
             
            iter = view.get_model().iter_next(iter)
    def notifyLifecycleChange(self, test, state, changeDesc):
        iter = self.itermap[test]
        self.updateStateInModel(test, iter, state)
        self.diagnoseTest(test, iter)

        if state.hasSucceeded():
            self.updateSuiteSuccess(test.parent)
    def updateSuiteSuccess(self, suite):
        successCount = self.successPerSuite.get(suite, 0) + 1
        self.successPerSuite[suite] = successCount
        suiteSize = suite.size()
        if successCount == suiteSize:
            self.setAllSucceeded(suite, suiteSize)

        if suite.parent:
            self.updateSuiteSuccess(suite.parent)
            
    def diagnoseTest(self, test, iter):
        guilog.info("Redrawing test " + test.name + " coloured " + self.model.get_value(iter, 1))
        secondColumnText = self.model.get_value(iter, 4)
        if secondColumnText:
            guilog.info("(Second column '" + secondColumnText + "' coloured " + self.model.get_value(iter, 5) + ")")
            
    def setAllSucceeded(self, suite, suiteSize):
        # Print how many tests succeeded, color details column in success color,
        # collapse row, and try to collapse parent suite.
        detailText = "All " + str(suiteSize) + " tests successful"
        successColour = getTestColour(suite, "success")
        iter = self.itermap[suite]
        self.model.set_value(iter, 4, detailText)
        self.model.set_value(iter, 5, successColour)
        guilog.info("Redrawing suite " + suite.name + " : second column '" + detailText +  "' coloured " + successColour)

        if suite.getConfigValue("auto_collapse_successful") == 1:
            self.collapseRow(iter)
            
    def notifyAdd(self, test):
        self.addTest(test)
        if test.classId() == "test-case":
            self.totalNofTests += 1
        guilog.info("Selecting new test " + test.name)
        self.notifyNewTestSelection([ test ])
    def addTest(self, test):
        suiteIter = self.itermap[test.parent]
        iter = self.addSuiteWithParent(test, suiteIter)
    def notifyRemove(self, test):
        # This test is currently selected. View the suite (its parent) instead!
        guilog.info("Selecting " + repr(test.parent) + " as test " + test.name + " removed")
        self.notifyNewTestSelection([ test.parent ])

        self.removeTest(test)
        self.totalNofTests -= test.size()
        self.updateColumnTitle()
    def removeTest(self, test):
        guilog.info("-> " + test.getIndent() + "Removed " + repr(test) + " from test tree view.")
        iter = self.itermap[test]
        filteredIter = self.findIter(test)
        if self.selection.iter_is_selected(filteredIter):
            self.selection.unselect_iter(filteredIter)
        self.model.remove(iter)
        del self.itermap[test]
    def notifyContentChange(self, suite):
        allSelected, selectedTests = self.getSelected()
        self.selecting = True
        self.selection.unselect_all()
        guilog.info("-> " + suite.getIndent() + "Recreating contents of " + repr(suite) + ".")
        for test in suite.testcases:
            self.removeTest(test)
        for test in suite.testcases:
            self.addTest(test)
        self.expandRow(self.findIter(suite), True)
        self.selectTestRows(allSelected) # don't notify observers as nothing has changed except order
    def notifyVisibility(self, test, newValue):
        allIterators = self.findVisibilityIterators(test) # returns leaf-to-root order, good for hiding
        if newValue:
            allIterators.reverse()  # but when showing, we want to go root-to-leaf

        changed = False
        for iterator in allIterators:
            if newValue or not self.hasVisibleChildren(iterator):
                changed |= self.setVisibility(iterator, newValue)

        if changed:
            self.reFilter()
            if newValue: # if things have become visible, expand everything
                rootIter = self.filteredModel.get_iter_root()
                while rootIter != None:
                    self.expandRow(rootIter, True)
                    rootIter = self.filteredModel.iter_next(rootIter)
        
    def setVisibility(self, iter, newValue):
        oldValue = self.model.get_value(iter, 6)
        if oldValue == newValue:
            return False

        test = self.model.get_value(iter, 2)
        if newValue:
            guilog.info("Making test visible : " + repr(test))
        else:
            guilog.info("Hiding test : " + repr(test))
        self.model.set_value(iter, 6, newValue)
        return True
    def findVisibilityIterators(self, test):
        iter = self.itermap[test]
        parents = []
        parent = self.model.iter_parent(iter)
        while parent != None:
            parents.append(parent)                    
            parent = self.model.iter_parent(parent)
        # Don't include the root which we never hide
        return [ iter ] + parents[:-1]

    def hasVisibleChildren(self, iter):
        child = self.model.iter_children(iter)
        while (child != None):
            if self.model.get_value(child, 6):
                return True
            else:
                child = self.model.iter_next(child)
        return False
    
    def reFilter(self):
        self.filteredModel.refilter()
        self.visibilityChanged()
           
class ActionGUI(SubGUI):
    def __init__(self, action, uiManager, fromTab=False):
        SubGUI.__init__(self)
        self.action = action
        self.accelerator = self.getAccelerator()
        if self.action.isToggle():
            self.gtkAction = gtk.ToggleAction(self.action.getSecondaryTitle(), self.action.getTitle(), \
                                              self.action.getTooltip(), self.getStockId())
            self.gtkAction.set_active(self.action.getStartValue())
        elif self.action.isRadio():
            self.gtkAction = gtk.RadioAction(self.action.getSecondaryTitle(), self.action.getTitle(), \
                                             self.action.getTooltip(), self.getStockId(), self.getStartValue())
        else:
            self.gtkAction = gtk.Action(self.action.getSecondaryTitle(), self.action.getTitle(), \
                                        self.action.getTooltip(), self.getStockId())

        self.getActionGroup(uiManager).add_action_with_accel(self.gtkAction, self.accelerator)
        self.gtkAction.set_accel_group(uiManager.get_accel_group())
        self.gtkAction.connect_accelerator()
        scriptEngine.connect(self.action.getScriptTitle(fromTab), "activate", self.gtkAction, self.runInteractive)
        if not fromTab and not self.action.isActiveOnCurrent():
            self.gtkAction.set_property("sensitive", False) # tab guis are always sensitive, we manage this by removing the tab!

    def getActionGroupIndex(self):
        return 0
    def getActionGroup(self, uiManager):
        return uiManager.get_action_groups()[self.getActionGroupIndex()]

    def getStockId(self):
        stockId = self.action.getStockId()
        if stockId:
            return "gtk-" + stockId 
        
    def getAccelerator(self):
        realAcc = self.action.getAccelerator()
        if realAcc:
            key, mod = gtk.accelerator_parse(realAcc)
            if gtk.accelerator_valid(key, mod):
                return realAcc
            else:
                plugins.printWarning("Keyboard accelerator '" + realAcc + "' for action '" \
                                     + self.action.getSecondaryTitle() + "' is not valid, ignoring ...")
    def describe(self):
        type = "action"
        if self.action.isToggle():
            type = "toggle action"
        elif self.action.isRadio():
            type = "radio action"
        message = "Viewing " + type + " with title '" + self.action.getTitle() + "'"

        stockId = self.getStockId()
        if stockId:
            message += ", stock id '" + repr(stockId) + "'"
        if self.accelerator:
            message += ", accelerator '" + repr(self.accelerator) + "'"
        if not self.gtkAction.is_sensitive():
            message += " (greyed out)"
            
        if self.action.isRadio() or self.action.isToggle():
            message += ". Start value is " + str(self.action.getStartValue())                
        guilog.info(message)

    def notifyNewTestSelection(self, tests):
        oldActive = self.gtkAction.is_sensitive()
        newActive = self.action.isActiveOnCurrent()
        if oldActive != newActive:
            self.gtkAction.set_property("sensitive", newActive)
            guilog.info("Setting sensitivity of button '" + self.action.getTitle() + "' to " + repr(newActive))
    def createView(self):
        button = gtk.Button()
        self.gtkAction.connect_proxy(button)
        button.show()
        return button
    def runInteractive(self, *args):
        if statusMonitor.busy(): # If we're busy with some other action, ignore this one ...
            return        
        doubleCheckMessage = self.action.getDoubleCheckMessage()
        if doubleCheckMessage:
            self.dialog = DoubleCheckDialog(doubleCheckMessage, self._runInteractive, globalTopWindow)
        else:
            self._runInteractive()
    def _runInteractive(self):
        try:
            self.action.perform()
        except plugins.TextTestError, e:
            showError(str(e), globalTopWindow)
        except plugins.TextTestWarning, e:
            showWarning(str(e), globalTopWindow)
        

class ContainerGUI(SubGUI):
    def __init__(self, subguis):
        SubGUI.__init__(self)
        self.subguis = subguis
    def forceVisible(self, tests):
        for subgui in self.subguis:
            if subgui.forceVisible(tests):
                return True
        return False
    
    def shouldShowCurrent(self):
        for subgui in self.subguis:
            if not subgui.shouldShowCurrent():
                return False
        return True
    
    def setActive(self, value):
        SubGUI.setActive(self, value)
        for subgui in self.subguis:
            subgui.setActive(value)
    def contentsChanged(self):
        for subgui in self.subguis:
            subgui.contentsChanged()
    def describe(self):
        for subgui in self.subguis:
            subgui.describe()
    
class BoxGUI(ContainerGUI):
    def __init__(self, subguis, horizontal, reversed=False):
        ContainerGUI.__init__(self, subguis)
        self.horizontal = horizontal
        self.reversed = reversed

    def createBox(self):
        if self.horizontal:
            return gtk.HBox()
        else:
            return gtk.VBox()
    def getPackMethod(self, box):
        if self.reversed:
            return box.pack_end
        else:
            return box.pack_start
    def getOrderedSubGUIs(self):
        if self.reversed:
            reversedGUIs = copy(self.subguis)
            reversedGUIs.reverse()
            return reversedGUIs
        else:
            return self.subguis

    def shouldExpand(self, view):
        if isinstance(view, gtk.Box) or isinstance(view, gtk.Button):
            return False
        else:
            return True
    def contentsChanged(self):
        if self.horizontal:
            SubGUI.contentsChanged(self)
        else:
            ContainerGUI.contentsChanged(self)
        
    def createView(self):
        box = self.createBox()
        packMethod = self.getPackMethod(box)
        for subgui in self.getOrderedSubGUIs():
            view = subgui.createView()
            expand = self.shouldExpand(view)
            packMethod(view, expand=expand, fill=expand)
            
        box.show()
        return box
        
class ActionTabGUI(SubGUI):
    def __init__(self, optionGroup, action, buttonGUI):
        SubGUI.__init__(self)
        self.optionGroup = optionGroup
        self.action = action
        self.buttonGUI = buttonGUI
        self.vbox = None
        self.tooltips = gtk.Tooltips()
    def getGroupTabTitle(self):
        return self.action.getGroupTabTitle()
    def getTabTitle(self):
        return self.optionGroup.name
    def shouldShowCurrent(self):
        return self.action.isActiveOnCurrent()
    def createView(self):
        return self.addScrollBars(self.createVBox())

    def notifyLifecycleChange(self, test, state, changeDesc):
        if self.action.updateDefaults(test, state):
            self.updateView()

    def notifyNewTestSelection(self, tests):
        if len(tests) == 0:
            return
        if self.action.updateDefaults(tests[0], tests[0].state):
            self.updateView()
            
    def updateView(self):
        if not self.vbox:
            return
        container = self.vbox.get_parent()
        if container:
            container.remove(self.vbox)
            container.add(self.createVBox())
            container.show()
            self.contentsChanged()
        
    def createVBox(self):
        self.vbox = gtk.VBox()
        if len(self.optionGroup.options) > 0:
            # Creating 0-row table gives a warning ...
            table = gtk.Table(len(self.optionGroup.options), 2, homogeneous=False)
            table.set_row_spacings(1)
            rowIndex = 0        
            for option in self.optionGroup.options.values():
                label, entry = self.createOptionEntry(option)
                if isinstance(label, gtk.Label):
                    label.set_alignment(1.0, 0.5)
                else:
                    label.get_children()[0].set_alignment(1.0, 0.5)
                table.attach(label, 0, 1, rowIndex, rowIndex + 1, xoptions=gtk.FILL, xpadding=1)
                table.attach(entry, 1, 2, rowIndex, rowIndex + 1)
                rowIndex += 1
                table.show_all()
            self.vbox.pack_start(table, expand=False, fill=False)
        
        for switch in self.optionGroup.switches.values():
            hbox = self.createSwitchBox(switch)
            self.vbox.pack_start(hbox, expand=False, fill=False)
        if self.buttonGUI:
            button = self.buttonGUI.createView()
            buttonbox = gtk.HBox()
            buttonbox.pack_start(button, expand=True, fill=False)
            buttonbox.show()
            self.vbox.pack_start(buttonbox, expand=False, fill=False, padding=8)
        self.vbox.show()
        return self.vbox
        
    def createComboBox(self, option):
        combobox = gtk.combo_box_entry_new_text()
        entry = combobox.child
        option.setPossibleValuesAppendMethod(combobox.append_text)
        return combobox, entry
    
    def createOptionWidget(self, option):
        if option.inqNofValues() > 1:
            return self.createComboBox(option)
        else:
            entry = gtk.Entry()
            return entry, entry
        
    def createOptionEntry(self, option):
        widget, entry = self.createOptionWidget(option)
        label = gtk.EventBox()
        label.add(gtk.Label(option.name + "  "))
        if option.description:
            self.tooltips.set_tip(label, option.description)
        entry.set_text(option.getValue())
        scriptEngine.registerEntry(entry, "enter " + option.name + " =")
        option.setMethods(entry.get_text, entry.set_text)
        return label, widget
    
    def createSwitchBox(self, switch):
        if len(switch.options) >= 1:
            hbox = gtk.HBox()
            label = gtk.EventBox()
            label.add(gtk.Label(switch.name))
            if switch.description:
                self.tooltips.set_tip(label, switch.description)
            hbox.pack_start(label, expand=False, fill=False)
            count = 0
            buttons = []
            mainRadioButton = None
            for option in switch.options:
                radioButton = gtk.RadioButton(mainRadioButton, option)
                buttons.append(radioButton)
                scriptEngine.registerToggleButton(radioButton, "choose " + option)
                if not mainRadioButton:
                    mainRadioButton = radioButton
                if count == switch.getValue():
                    radioButton.set_active(True)
                    switch.resetMethod = radioButton.set_active
                else:
                    radioButton.set_active(False)
                hbox.pack_start(radioButton, expand=True, fill=True)
                count = count + 1
            indexer = RadioGroupIndexer(buttons)
            switch.setMethods(indexer.getActiveIndex, indexer.setActiveIndex)
            hbox.show_all()
            return hbox  
        else:
            checkButton = gtk.CheckButton(switch.name)
            if switch.getValue():
                checkButton.set_active(True)
            scriptEngine.registerToggleButton(checkButton, "check " + switch.name, "uncheck " + switch.name)
            switch.setMethods(checkButton.get_active, checkButton.set_active)
            checkButton.show()
            return checkButton

    def describe(self):
        guilog.info("Viewing notebook page for '" + self.getTabTitle() + "'")
        for option in self.optionGroup.options.values():
            guilog.info(self.getOptionDescription(option))
        for switch in self.optionGroup.switches.values():
            guilog.info(self.getSwitchDescription(switch))

        if self.buttonGUI:
            self.buttonGUI.describe()
        
    def getOptionDescription(self, option):
        value = option.getValue()
        text = "Viewing entry for option '" + option.name + "'"
        if len(value) > 0:
            text += " (set to '" + value + "')"
        if option.inqNofValues() > 1:
            text += " (drop-down list containing " + repr(option.possibleValues) + ")"
        return text
    
    def getSwitchDescription(self, switch):
        value = switch.getValue()
        if len(switch.options) >= 1:
            text = "Viewing radio button for switch '" + switch.name + "', options "
            text += string.join(switch.options, "/")
            text += "'. Default value " + str(value) + "."
        else:
            text = "Viewing check button for switch '" + switch.name + "'"
            if value:
                text += " (checked)"
        return text

class NotebookGUI(SubGUI):
    def __init__(self, tabInfo, scriptTitle, defaultPage=""):
        SubGUI.__init__(self)
        self.scriptTitle = scriptTitle
        self.diag = plugins.getDiagnostics("GUI notebook")
        self.tabInfo = tabInfo
        self.notebook = None
        self.currentPageName = defaultPage

    def setActive(self, value):
        SubGUI.setActive(self, value)
        if self.currentPageName:
            self.tabInfo[self.currentPageName].setActive(value)

    def contentsChanged(self):
        SubGUI.contentsChanged(self)
        if self.currentPageName:
            self.tabInfo[self.currentPageName].contentsChanged()

    def createView(self):
        self.notebook = gtk.Notebook()
        for tabName, tabGUI in self.tabInfo.items():
            if tabGUI.shouldShowCurrent():
                label = gtk.Label(tabName)
                self.diag.info("Adding page " + tabName)
                self.notebook.append_page(tabGUI.createView(), label)

        scriptEngine.monitorNotebook(self.notebook, self.scriptTitle)
	self.notebook.set_scrollable(True)
        if not self.setCurrentPage(self.currentPageName):
            self.currentPageName = self.getPageName(0)
        self.notebook.connect("switch-page", self.handlePageSwitch)
        self.notebook.show()
        return self.notebook
    
    def handlePageSwitch(self, notebook, ptr, pageNum, *args):
        if not self.active:
            return
        self.currentPageName = self.getPageName(pageNum)
        self.diag.info("Switching to page " + self.currentPageName)
        for tabName, tabGUI in self.tabInfo.items():
            if tabName == self.currentPageName:
                self.diag.info("Activating " + tabName)
                tabGUI.activate()
            else:
                self.diag.info("Deactivating " + tabName)
                tabGUI.deactivate()

    def getPageName(self, pageNum):
        page = self.notebook.get_nth_page(pageNum)
        if page:
            return self.notebook.get_tab_label_text(page)
        else:
            return ""

    def findPage(self, name):
        for child in self.notebook.get_children():
            text = self.notebook.get_tab_label_text(child)
            if text == name:
                return child

    def getTabNames(self):
        return map(self.notebook.get_tab_label_text, self.notebook.get_children())

    def removePage(self, name):
        oldPage = self.findPage(name)
        if oldPage:
            self.diag.info("Removing page " + name)
            self.notebook.remove(oldPage)

    def insertNewPage(self, name, insertPosition=0):
        if self.notebook.get_n_pages() == 0:
            self.currentPageName = name
        tabGUI = self.tabInfo[name]
        self.diag.info("Inserting new page " + name)
        page = tabGUI.createView()
        label = gtk.Label(name)
        self.notebook.insert_page(page, label, insertPosition)

    def describe(self):
        guilog.info("Tabs showing : " + string.join(self.getTabNames(), ", "))

    def findFirstRemaining(self, pageNamesRemoved):
        for tabName in self.getTabNames():
            if tabName not in pageNamesRemoved:
                return tabName
    
    def insertNewPages(self):
        currTabNames = self.getTabNames()
        insertIndex = 0
        changed = False
        for name, tabGUI in self.tabInfo.items():
            if name in currTabNames:
                insertIndex += 1
            elif tabGUI.shouldShowCurrent():
                self.insertNewPage(name, insertIndex)
                insertIndex += 1
                changed = True
        return changed

    def setCurrentPage(self, newName):
        self.diag.info("Resetting for current page " + self.currentPageName + " to page " + repr(newName))
        try:
            index = self.getTabNames().index(newName)
            self.notebook.set_current_page(index)
            self.currentPageName = newName
            self.diag.info("Resetting done.")
            return True
        except ValueError:
            return False

    def findPagesToRemove(self):
        return filter(lambda name: not self.tabInfo[name].shouldShowCurrent(), self.getTabNames())
        
    def removeOldPages(self):
        # Must reset the current page before removing it if we're viewing a removed page
        # otherwise we can output lots of pages we don't really look at
        pageNamesRemoved = self.findPagesToRemove()
        if len(pageNamesRemoved) == 0:
            return False

        if self.currentPageName in pageNamesRemoved:
            newCurrentPageName = self.findFirstRemaining(pageNamesRemoved)
            if newCurrentPageName:
                self.setCurrentPage(newCurrentPageName)
            
        # remove from the back, so we don't momentarily view them all if removing everything
        pageNamesRemoved.reverse()
        for name in pageNamesRemoved:
            self.removePage(name)
        return True
    def updateCurrentPage(self, tests):
        allNames = self.getTabNames()
        for name in allNames:
            if self.tabInfo[name].forceVisible(tests):
                self.notebook.set_current_page(allNames.index(name))

    def notifyNewTestSelection(self, tests):
        if not self.notebook:
            return 

        pagesAdded = self.insertNewPages()
        pagesRemoved = self.removeOldPages()
        self.updateCurrentPage(tests)
  
        if pagesAdded or pagesRemoved:
            SubGUI.contentsChanged(self) # just the tabs will do here, the rest is described by other means
          
class PaneGUI(ContainerGUI):
    def __init__(self, subguis, separatorPosition, horizontal):
        SubGUI.__init__(self)
        self.subguis = subguis
        self.horizontal = horizontal
        self.separatorPosition = separatorPosition
        self.panedTooltips = gtk.Tooltips()
        self.paned = None
    def createPaned(self):
        if self.horizontal:
            return gtk.HPaned()
        else:
            return gtk.VPaned()
    def getSize(self):
        if self.horizontal:
            return self.paned.allocation.width
        else:
            return self.paned.allocation.height
    def createView(self):
        self.paned = self.createPaned()
        self.paned.connect('notify', self.paneHasChanged)
        frames = []
        for subgui in self.subguis:
            widget = subgui.createView()
            if isinstance(subgui, PaneGUI):
                frames.append(widget)
            else:
                frame = gtk.Frame()
                frame.set_shadow_type(gtk.SHADOW_IN)
                frame.add(widget)
                frame.show()
                frames.append(frame)

        self.paned.pack1(frames[0], resize=True)
        self.paned.pack2(frames[1], resize=True)
        self.paned.show()
        return self.paned
        
    def paneHasChanged(self, pane, gparamspec):
        pos = pane.get_position()
        size = self.getSize()
        self.panedTooltips.set_tip(pane, "Position: " + str(pos) + "/" + str(size) + \
                                   " (" + self.positionDescription(float(pos) / size) + ")")
    def positionDescription(self, proportion):
        message = str(int(100 * proportion)) + "% from the "
        if self.horizontal:
            return message + "left edge"
        else:
            return message + "top"
    def notifySetUpGUIComplete(self):
        if self.active:
            guilog.info("Pane separator moved to " + self.positionDescription(self.separatorPosition))
        pos = int(self.getSize() * self.separatorPosition)
        self.paned.set_position(pos)                
    
class TextInfoGUI(SubGUI):
    def __init__(self):
        SubGUI.__init__(self)
        self.currentTest = None
        self.text = ""
        self.view = None
    def shouldShowCurrent(self):
        return len(self.text) > 0
    def getTabTitle(self):
        return "Text Info"
    def forceVisible(self, tests):
        return len(tests) == 1
    def resetText(self, test, state):
        self.text = ""
        if state.isComplete():
            self.text = "Test " + repr(state) + "\n"
            if len(state.freeText) == 0:
                self.text = self.text.replace(" :", "")
        self.text += str(state.freeText)
    def getActualText(self):
        buffer = self.view.get_buffer()
        utf8Text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter())
        localeEncoding = locale.getdefaultlocale()[1]
        if not localeEncoding:
            return utf8Text

        unicodeInfo = unicode(utf8Text, "utf-8", errors="strict")
        return unicodeInfo.encode(localeEncoding, "strict")
    def describe(self):
        guilog.info("---------- Text Info Window ----------")
        guilog.info(self.getActualText().strip())
        guilog.info("--------------------------------------")
    def notifyNewTestSelection(self, tests):
        if len(tests) > 0 and self.currentTest not in tests:
            self.currentTest = tests[0]
            if self.currentTest.classId() == "test-case":
                self.resetText(self.currentTest, self.currentTest.state)
            else:
                self.text = ""
            self.updateView()
    def updateView(self):
        if self.view:
            self.updateViewFromText()
            self.contentsChanged()
    def notifyLifecycleChange(self, test, state, changeDesc):
        if not test is self.currentTest:
            return
        self.resetText(test, state)
        self.updateView()
    def createView(self):
        if not self.shouldShowCurrent():
            return
        self.view = gtk.TextView()
        self.view.set_editable(False)
        self.view.set_cursor_visible(False)
        self.view.set_wrap_mode(gtk.WRAP_WORD)
        self.updateViewFromText()
        self.view.show()
        return self.addScrollBars(self.view)
    def updateViewFromText(self):
        textbuffer = self.view.get_buffer()
        textToUse = self.getTextForView()
        textbuffer.set_text(textToUse)        
    def getTextForView(self):
        # Encode to UTF-8, necessary for gtk.TextView
        # First decode using most appropriate encoding ...
        unicodeInfo = self.decodeText()
        return self.encodeToUTF(unicodeInfo)
    def decodeText(self):
        localeEncoding = locale.getdefaultlocale()[1]
        if localeEncoding:
            try:
                return unicode(self.text, localeEncoding, errors="strict")
            except:
                guilog.info("WARNING: Failed to decode string '" + self.text + \
                            "' using default locale encoding " + repr(localeEncoding) + \
                            ". Trying strict UTF-8 encoding ...")
            
        return self.decodeUtf8Text(localeEncoding)
    def decodeUtf8Text(self, localeEncoding):
        try:
            return unicode(self.text, 'utf-8', errors="strict")
        except:
            guilog.info("WARNING: Failed to decode string '" + self.text + \
                        "' both using strict UTF-8 and " + repr(localeEncoding) + \
                        " encodings.\nReverting to non-strict UTF-8 encoding but " + \
                        "replacing problematic\ncharacters with the Unicode replacement character, U+FFFD.")
            return unicode(self.text, 'utf-8', errors="replace")
    def encodeToUTF(self, unicodeInfo):
        try:
            return unicodeInfo.encode('utf-8', 'strict')
        except:
            try:
                guilog.info("WARNING: Failed to encode Unicode string '" + unicodeInfo + \
                            "' using strict UTF-8 encoding.\nReverting to non-strict UTF-8 " + \
                            "encoding but replacing problematic\ncharacters with the Unicode replacement character, U+FFFD.")
                return unicodeInfo.encode('utf-8', 'replace')
            except:
                guilog.info("WARNING: Failed to encode Unicode string '" + unicodeInfo + \
                            "' using both strict UTF-8 encoding and UTF-8 encoding with " + \
                            "replacement. Showing error message instead.")
                return "Failed to encode Unicode string."


        
class FileViewGUI(SubGUI):
    def __init__(self, dynamic):
        SubGUI.__init__(self)
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_STRING,\
                                   gobject.TYPE_PYOBJECT, gobject.TYPE_STRING)
        self.currentObject = None
        self.dynamic = dynamic
        self.selection = None
        self.nameColumn = None

    def setName(self, tests=[]):
        if self.nameColumn:
            title = self.getName(tests)
            self.nameColumn.set_title(title)

    def recreateModel(self, state):
        if not self.nameColumn:
            return
        # In theory we could do something clever here, but for now, just wipe and restart
        # Need to re-expand after clearing...
        self.model.clear()
        self.addFilesToModel(state)
        self.selection.get_tree_view().expand_all()
        self.contentsChanged()
    def getState(self):
        pass
     
    def describe(self):
        self.describeName()
        self.describeLevel(self.model.get_iter_root())
    def describeName(self):
        if self.nameColumn:
            guilog.info("Setting file-view title to '" + self.nameColumn.get_title() + "'")
    def describeLevel(self, currIter, parentDesc=""): 
        while currIter is not None:
            subIter = self.model.iter_children(currIter)
            if parentDesc:
                fileName = self.model.get_value(currIter, 0)
                colour = self.model.get_value(currIter, 1)
                if colour:
                    guilog.info("Adding file " + fileName + " under heading '" + parentDesc + "', coloured " + colour)
                details = self.model.get_value(currIter, 4)
                if details:
                    guilog.info("(Second column '" + details + "' coloured " + colour + ")")
            if subIter:
                self.describeLevel(subIter, self.model.get_value(currIter, 0))
            currIter = self.model.iter_next(currIter)
        
    def getName(self, tests=[]):
        if len(tests) > 1:
            return "Sample from " + repr(len(tests)) + " tests"
        else:
            return self.currentObject.name.replace("_", "__")
    def createView(self):
        self.model.clear()
        self.addFilesToModel(self.getState())
        view = gtk.TreeView(self.model)
        self.selection = view.get_selection()
        self.selection.set_mode(gtk.SELECTION_MULTIPLE)
        renderer = gtk.CellRendererText()
        self.nameColumn = gtk.TreeViewColumn(self.getName(), renderer, text=0, background=1)
        self.nameColumn.set_cell_data_func(renderer, renderParentsBold)
        view.append_column(self.nameColumn)
        detailsColumn = self.makeDetailsColumn(renderer)
        if detailsColumn:
            view.append_column(detailsColumn)
        view.expand_all()
        indexer = TreeModelIndexer(self.model, self.nameColumn, 0)
        self.monitorEvents(indexer)
        view.show()
        return self.addScrollBars(view)
        # only used in test view
    def makeDetailsColumn(self, renderer):
        if self.dynamic:
            return gtk.TreeViewColumn("Details", renderer, text=4)
    def fileActivated(self, view, path, column, *args):
        iter = self.model.get_iter(path)
        fileName = self.model.get_value(iter, 2)
        if not fileName:
            # Don't crash on double clicking the header lines...
            return
        comparison = self.model.get_value(iter, 3)
        try:
            self.notify("ViewFile", comparison, fileName)
        except plugins.TextTestError, e:
            showError(str(e), globalTopWindow)

        self.selection.unselect_all()
    def addFileToModel(self, iter, name, comp, colour):
        fciter = self.model.insert_before(iter, None)
        baseName = os.path.basename(name)
        heading = self.model.get_value(iter, 0)
        self.model.set_value(fciter, 0, baseName)
        self.model.set_value(fciter, 1, colour)
        self.model.set_value(fciter, 2, name)
        if comp:
            self.model.set_value(fciter, 3, comp)
            details = comp.getDetails()
            if len(details) > 0:
                self.model.set_value(fciter, 4, details)
        return fciter
    def getColour(self, name):
        return self.currentObject.getConfigValue("file_colours")[name]
    
class ApplicationFileGUI(FileViewGUI):
    def notifyNewTestSelection(self, tests):
        if len(tests) > 0 and self.currentObject != tests[0].app:
            self.currentObject = tests[0].app
            self.setName()
            self.recreateModel(self.getState())
    def monitorEvents(self, indexer):
        scriptEngine.connect("select application file", "row_activated", self.selection.get_tree_view(), self.fileActivated, indexer)
    def addFilesToModel(self, state):
        confiter = self.model.insert_before(None, None)
        self.model.set_value(confiter, 0, "Application Files")
        colour = self.getColour("app_static")
        for file in self.getConfigFiles():
            self.addFileToModel(confiter, file, None, colour)

        personalFiles = self.getPersonalFiles()
        if len(personalFiles) > 0:
            persiter = self.model.insert_before(None, None)
            self.model.set_value(persiter, 0, "Personal Files")
            for file in personalFiles:
                self.addFileToModel(persiter, file, None, colour)
    def getConfigFiles(self):
        configFiles = self.currentObject.dircache.findAllFiles("config", [ self.currentObject.name ])
        configFiles.sort()
        return configFiles
    def getPersonalFiles(self):
        personalFiles = []
        personalFile = self.currentObject.getPersonalConfigFile()
        if personalFile:
            personalFiles.append(personalFile)
        gtkRcFile = getGtkRcFile()
        if gtkRcFile:
            personalFiles.append(gtkRcFile)
        return personalFiles

class TestFileGUI(FileViewGUI):
    def notifyFileChange(self, test):
        if test is self.currentObject:
            self.recreateModel(test.state)
    def notifyLifecycleChange(self, test, state, changeDesc):
        if test is self.currentObject:
            self.recreateModel(state)
    def forceVisible(self, tests):
        return len(tests) == 1
    
    def notifyNewTestSelection(self, tests):
        if len(tests) == 0: 
            return

        if not self.dynamic and len(tests) > 1: # multiple tests in static GUI result in removal
            self.currentObject = None
            self.nameColumn = None
            self.selection = None
            return

        if len(tests) > 1 and self.currentObject in tests:
            self.setName(tests)
            self.describeName()
        else:
            self.currentObject = tests[0]
            self.currentObject.refreshFiles()
            self.setName(tests)
            self.recreateModel(self.getState())

    def shouldShowCurrent(self):
        return self.currentObject is not None
            
    def addFilesToModel(self, state):
        if state.hasStarted():
            if hasattr(state, "correctResults"):
                # failed on comparison
                self.addComparisonsToModel(state)
            elif not state.isComplete():
                self.addTmpFilesToModel()
        else:
            self.addStaticFilesToModel()

    def monitorEvents(self, indexer):
        scriptEngine.connect("select file", "row_activated", self.selection.get_tree_view(), self.fileActivated, indexer)
        scriptEngine.monitor("set file selection to", self.selection, indexer)
        self.selectionChanged(self.selection)
        self.selection.connect("changed", self.selectionChanged)
    def selectionChanged(self, selection):
        filelist = []
        selection.selected_foreach(self.fileSelected, filelist)
        self.notify("NewFileSelection", filelist)
    def fileSelected(self, treemodel, path, iter, filelist):
        filelist.append(self.model.get_value(iter, 0))
    def getState(self):
        return self.currentObject.state
    def addComparisonsToModel(self, state):
        self.addComparisons(state.correctResults + state.changedResults, "Comparison Files")
        self.addComparisons(state.newResults, "New Files")
        self.addComparisons(state.missingResults, "Missing Files")
    def addComparisons(self, compList, title):
        if len(compList) == 0:
            return
        iter = self.model.insert_before(None, None)
        self.model.set_value(iter, 0, title)
        filelist = []
        fileCompMap = {}
        for comp in compList:
            file = comp.getDisplayFileName()
            fileCompMap[file] = comp
            filelist.append(file)
        filelist.sort()
        self.addStandardFilesUnderIter(iter, filelist, fileCompMap)    
    def addStandardFilesUnderIter(self, iter, files, compMap = {}):
        for relDir, relDirFiles in self.classifyByRelDir(files).items():
            iterToUse = iter
            if relDir:
                iterToUse = self.addFileToModel(iter, relDir, None, self.getStaticColour())
            for file in relDirFiles:
                comparison = compMap.get(file)
                colour = self.getComparisonColour(comparison)
                self.addFileToModel(iterToUse, file, comparison, colour)
    def classifyByRelDir(self, files):
        dict = {}
        for file in files:
            relDir = self.getRelDir(file)
            if not dict.has_key(relDir):
                dict[relDir] = []
            dict[relDir].append(file)
        return dict
    def getRelDir(self, file):
        relPath = self.currentObject.getTestRelPath(file)
        if relPath.find(os.sep) != -1:
            dir, local = os.path.split(relPath)
            return dir
        else:
            return ""
    def getComparisonColour(self, fileComp):
        if not self.currentObject.state.hasStarted():
            return self.getStaticColour()
        if not self.currentObject.state.isComplete():
            return self.getColour("running")
        if fileComp.hasSucceeded():
            return self.getColour("success")
        else:
            return self.getColour("failure")
    def getStaticColour(self):
        if self.dynamic:
            return self.getColour("not_started")
        else:
            return self.getColour("static")
    def addTmpFilesToModel(self):
        tmpFiles = self.currentObject.listTmpFiles()
        tmpIter = self.model.insert_before(None, None)
        self.model.set_value(tmpIter, 0, "Temporary Files")
        self.addStandardFilesUnderIter(tmpIter, tmpFiles)
    def addStaticFilesToModel(self):
        stdFiles, defFiles = self.currentObject.listStandardFiles(allVersions=True)
        if self.currentObject.classId() == "test-case":
            stditer = self.model.insert_before(None, None)
            self.model.set_value(stditer, 0, "Standard Files")
            if len(stdFiles):
                self.addStandardFilesUnderIter(stditer, stdFiles)

        defiter = self.model.insert_before(None, None)
        self.model.set_value(defiter, 0, "Definition Files")
        self.addStandardFilesUnderIter(defiter, defFiles)
        self.addStaticDataFilesToModel()
    def getDisplayDataFiles(self):
        try:
            return self.currentObject.app.configObject.extraReadFiles(self.currentObject).items()
        except:
            sys.stderr.write("WARNING - ignoring exception thrown by '" + self.currentObject.app.configObject.moduleName + \
                             "' configuration while requesting extra data files, not displaying any such files")
            plugins.printException()
            return seqdict()
    def addStaticDataFilesToModel(self):
        dataFiles = self.currentObject.listDataFiles()
        displayDataFiles = self.getDisplayDataFiles()
        if len(dataFiles) == 0 and len(displayDataFiles) == 0:
            return
        datiter = self.model.insert_before(None, None)
        self.model.set_value(datiter, 0, "Data Files")
        colour = self.getStaticColour()
        self.addDataFilesUnderIter(datiter, dataFiles, colour)
        for name, filelist in displayDataFiles:
            exiter = self.model.insert_before(datiter, None)
            self.model.set_value(exiter, 0, name)
            for file in filelist:
                self.addFileToModel(exiter, file, None, colour)
    def addDataFilesUnderIter(self, iter, files, colour):
        dirIters = { self.currentObject.getDirectory() : iter }
        parentIter = iter
        for file in files:
            parent, local = os.path.split(file)
            parentIter = dirIters[parent]
            newiter = self.addFileToModel(parentIter, file, None, colour)
            if os.path.isdir(file):
                dirIters[file] = newiter
  
class TestProgressBar:
    def __init__(self):
        self.totalNofTests = 0
        self.nofCompletedTests = 0
        self.nofFailedTests = 0
        self.progressBar = None
    def createView(self):
        self.progressBar = gtk.ProgressBar()
        self.resetBar()
        self.progressBar.show()
        return self.progressBar
    def adjustToSpace(self, windowWidth):
        self.progressBar.set_size_request(int(windowWidth * 0.75), 1)
    def addSuite(self, suite):
        self.totalNofTests += suite.size()
    def notifyLifecycleChange(self, test, state, changeDesc):
        failed = state.hasFailed()
        if changeDesc == "complete":
            self.nofCompletedTests += 1
            if failed:
                self.nofFailedTests += 1
            self.resetBar()
        elif state.isComplete() and not failed: # test saved, possibly partially so still check 'failed'
            self.nofFailedTests -= 1
            self.adjustFailCount()
            
    def resetBar(self):
        message = self.getFractionMessage()
        message += self.getFailureMessage(self.nofFailedTests)
        fraction = float(self.nofCompletedTests) / float(self.totalNofTests)
        guilog.info("Progress bar set to fraction " + str(fraction) + ", text '" + message + "'")
        self.progressBar.set_text(message)
        self.progressBar.set_fraction(fraction)
    def getFractionMessage(self):
        if self.nofCompletedTests >= self.totalNofTests:
            completionTime = plugins.localtime()
            return "All " + str(self.totalNofTests) + " tests completed at " + completionTime
        else:
            return str(self.nofCompletedTests) + " of " + str(self.totalNofTests) + " tests completed"
    def getFailureMessage(self, failCount):
        if failCount != 0:
            return " (" + str(failCount) + " tests failed)"
        else:
            return ""
    def adjustFailCount(self):
        message = self.progressBar.get_text()
        oldFailMessage = self.getFailureMessage(self.nofFailedTests + 1)
        newFailMessage = self.getFailureMessage(self.nofFailedTests)
        message = message.replace(oldFailMessage, newFailMessage)
        guilog.info("Progress bar detected save, new text is '" + message + "'")
        self.progressBar.set_text(message)
            
# Class that keeps track of (and possibly shows) the progress of
# pending/running/completed tests
class TestProgressMonitor(SubGUI):
    def __init__(self, dynamic):
        SubGUI.__init__(self)
        self.classifications = {} # map from test to list of iterators where it exists
                
        # Each row has 'type', 'number', 'show', 'tests'
        self.treeModel = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_INT, gobject.TYPE_BOOLEAN, \
                                       gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT)
        self.progressReport = None
        self.treeView = None
        self.dynamic = dynamic
    def getTabTitle(self):
        return "Progress"
    def contentsChanged(self):
        pass # We don't worry about whether we're visible, we think we're important enough to write lots anyway!
    def shouldShowCurrent(self):
        return self.dynamic
    def createView(self):
        self.treeView = gtk.TreeView(self.treeModel)
        selection = self.treeView.get_selection()
        selection.set_mode(gtk.SELECTION_MULTIPLE)
        selection.connect("changed", self.selectionChanged)
        textRenderer = gtk.CellRendererText()
        numberRenderer = gtk.CellRendererText()
        numberRenderer.set_property('xalign', 1)
        statusColumn = gtk.TreeViewColumn("Status", textRenderer, text=0, background=3, font=4)
        numberColumn = gtk.TreeViewColumn("Number", numberRenderer, text=1, background=3, font=4)
        self.treeView.append_column(statusColumn)
        self.treeView.append_column(numberColumn)
        toggle = gtk.CellRendererToggle()
        toggle.set_property('activatable', True)
        indexer = TreeModelIndexer(self.treeModel, statusColumn, 0)
        scriptEngine.connect("toggle progress report category ", "toggled", toggle, self.showToggled, indexer)
        scriptEngine.monitor("set progress report filter selection to", selection, indexer)
        toggleColumn = gtk.TreeViewColumn("Visible", toggle, active=2)
        toggleColumn.set_alignment(0.5)
        self.treeView.append_column(toggleColumn)
        self.treeView.show()
        return self.addScrollBars(self.treeView)
            
    def selectionChanged(self, selection):
        # For each selected row, select the corresponding rows in the test treeview
        tests = []
        selection.selected_foreach(self.selectCorrespondingTests, tests)
        self.notify("NewTestSelection", tests)
    def selectCorrespondingTests(self, treemodel, path, iter, tests , *args):
        guilog.info("Selecting all " + str(treemodel.get_value(iter, 1)) + " tests in category " + treemodel.get_value(iter, 0))
        tests += treemodel.get_value(iter, 5)
    def findTestIterators(self, test):
        return self.classifications.get(test, [])
    def getCategoryDescription(self, state):
        briefDesc, fullDesc = state.categoryDescriptions.get(state.category, (state.category, state.category))
        return briefDesc.replace("_", " ").capitalize()
    def getClassifiers(self, state):
        catDesc = self.getCategoryDescription(state)
        if not state.isComplete() or not state.hasFailed():
            return [ catDesc ]
        classifiers = [ "Failed" ]
        if self.isPerformance(catDesc):
            classifiers += [ "Performance differences", catDesc ]
        else:
            briefText = state.getBriefClassifier()
            if catDesc == "Failed":
                classifiers += [ "Differences", briefText ]
            else:
                classifiers += [ catDesc, briefText ]
        return classifiers
    def isPerformance(self, catDesc):
        for perfCat in [ "Slower", "Faster", "Memory" ]:
            if catDesc.find(perfCat) != -1:
                return True
        return False
    def removeTest(self, test):
        for iter in self.findTestIterators(test):
            testCount = self.treeModel.get_value(iter, 1)
            self.treeModel.set_value(iter, 1, testCount - 1)
            if testCount == 1:
                self.treeModel.set_value(iter, 3, "white")
                self.treeModel.set_value(iter, 4, "")
            allTests = self.treeModel.get_value(iter, 5)
            allTests.remove(test)
            self.treeModel.set_value(iter, 5, allTests)
    def insertTest(self, test, state):
        searchIter = self.treeModel.get_iter_root()
        parentIter = None
        self.classifications[test] = []
        classifiers = self.getClassifiers(state)
        for classifier in classifiers:
            iter = self.findIter(classifier, searchIter)
            if iter:
                self.insertTestAtIter(iter, test, state.category)
                searchIter = self.treeModel.iter_children(iter)
            else:
                iter = self.addNewIter(classifier, parentIter, test, state.category)
                searchIter = None
            parentIter = iter
            self.classifications[test].append(iter)
        return iter
    def insertTestAtIter(self, iter, test, category):
        allTests = self.treeModel.get_value(iter, 5)
        testCount = self.treeModel.get_value(iter, 1)
        if testCount == 0:
            self.treeModel.set_value(iter, 3, getTestColour(test, category))
            self.treeModel.set_value(iter, 4, "bold")
        self.treeModel.set_value(iter, 1, testCount + 1)
        allTests.append(test)
        self.treeModel.set_value(iter, 5, allTests)
    def addNewIter(self, classifier, parentIter, test, category):
        showThis = self.showByDefault(test, category)
        modelAttributes = [classifier, 1, showThis, getTestColour(test, category), "bold", [ test ]]
        newIter = self.treeModel.append(parentIter, modelAttributes)
        if parentIter:
            self.treeView.expand_row(self.treeModel.get_path(parentIter), open_all=0)
        return newIter
    def findIter(self, classifier, startIter):
        iter = startIter
        while iter != None:
            name = self.treeModel.get_value(iter, 0)
            if name == classifier:
                return iter
            else:
                iter = self.treeModel.iter_next(iter)
    # Set default values for toggle buttons in the TreeView, based
    # on the config files.
    def showByDefault(self, test, category):
        # Check config files
        return category.lower() not in test.getConfigValue("hide_test_category")
    def notifyLifecycleChange(self, test, state, changeDesc):
        self.removeTest(test)
        newIter = self.insertTest(test, state)
        self.notify("Visibility", test, self.treeModel.get_value(newIter, 2)) 
        self.diagnoseTree()   
    def diagnoseTree(self):
        guilog.info("Test progress:")
        childIters = []
        childIter = self.treeModel.get_iter_root()

        # Put all children in list to be treated
        while childIter != None:
            childIters.append(childIter)
            childIter = self.treeModel.iter_next(childIter)

        while len(childIters) > 0:
            childIter = childIters[0]
            # If this iter has children, add these to the list to be treated
            if self.treeModel.iter_has_child(childIter):                            
                subChildIter = self.treeModel.iter_children(childIter)
                pos = 1
                while subChildIter != None:
                    childIters.insert(pos, subChildIter)
                    pos = pos + 1
                    subChildIter = self.treeModel.iter_next(subChildIter)
            # Print the iter
            indentation = ("--" * (self.getIterDepth(childIter) + 1)) + "> "
            name = self.treeModel.get_value(childIter, 0)
            count = str(self.treeModel.get_value(childIter, 1))
            bg = self.treeModel.get_value(childIter, 3)
            font = self.treeModel.get_value(childIter, 4)
            guilog.info(indentation + name + " : " + count + ", colour '" + bg + "', font '" + font + "'")
            childIters = childIters[1:len(childIters)]

    def getIterDepth(self, iter):
        parent = self.treeModel.iter_parent(iter)
        depth = 0
        while parent != None:
            depth = depth + 1
            parent = self.treeModel.iter_parent(parent)
        return depth
   
    def getAllChildIters(self, iter):
         # Toggle all children too
        childIters = []
        childIter = self.treeModel.iter_children(iter)
        while childIter != None:
            childIters.append(childIter)
            childIters += self.getAllChildIters(childIter)
            childIter = self.treeModel.iter_next(childIter)
        return childIters
    def showToggled(self, cellrenderer, path):
        # Toggle the toggle button
        newValue = not self.treeModel[path][2]
        self.treeModel[path][2] = newValue

        # Print some gui log info
        iter = self.treeModel.get_iter_from_string(path)
        if self.treeModel.get_value(iter, 2) == 1:
            guilog.info("Selecting to show tests in the '" + self.treeModel.get_value(iter, 0) + "' category.")
        else:
            guilog.info("Selecting not to show tests in the '" + self.treeModel.get_value(iter, 0) + "' category.")

        for childIter in self.getAllChildIters(iter):
            self.treeModel.set_value(childIter, 2, newValue)

        # Now, re-filter the main treeview to be consistent with
        # the chosen progress report options.
        for test in self.treeModel.get_value(iter, 5):
            self.notify("Visibility", test, newValue)

# Class for importing self tests
class ImportTestCase(guiplugins.ImportTestCase):
    def addDefinitionFileOption(self, suite):
        guiplugins.ImportTestCase.addDefinitionFileOption(self, suite)
        self.addSwitch("GUI", "Use TextTest GUI", 1)
        self.addSwitch("sGUI", "Use TextTest Static GUI", 0)
    def getOptions(self, suite):
        options = guiplugins.ImportTestCase.getOptions(self, suite)
        if self.optionGroup.getSwitchValue("sGUI"):
            options += " -gx"
        elif self.optionGroup.getSwitchValue("GUI"):
            options += " -g"
        return options
