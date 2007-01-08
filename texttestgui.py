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

import guidialogs
from guidialogs import showErrorDialog, showWarningDialog, showInformationDialog, DoubleCheckDialog

import traceback

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
        self.widget = None
    def setActive(self, newValue):
        self.active = newValue
    def activate(self):
        self.setActive(True)
        self.contentsChanged()
    def deactivate(self):
        self.setActive(False)
    def writeSeparator(self):
        guilog.info("") # blank line for demarcation
    def shouldDescribe(self):
        return self.active and self.shouldShowCurrent()
    def contentsChanged(self):
        if self.shouldDescribe():
            self.writeSeparator()
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

# base class for managing containers
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
    def shouldDescribe(self):
        return self.active
    def setActive(self, value):
        SubGUI.setActive(self, value)
        for subgui in self.subguis:
            subgui.setActive(value)
    def contentsChanged(self):
        SubGUI.contentsChanged(self)
        for subgui in self.subguis:
            subgui.contentsChanged()
    
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
class GUIStatusMonitor(SubGUI):
    def __init__(self):
        SubGUI.__init__(self)
        self.throbber = None
        self.animation = None
        self.pixbuf = None
        self.label = None

    def busy(self):
        return self.pixbuf != None
    def getWidgetName(self):
        return "_Status bar"
    def describe(self):
        guilog.info("Changing GUI status to: '" + self.label.get_text() + "'")        
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
            self.label.set_markup(message)
            self.contentsChanged()
            
    def createView(self):
        hbox = gtk.HBox()
        self.label = gtk.Label()
        self.label.set_use_markup(True)
        self.label.set_markup("TextTest started at " + plugins.localtime() + ".")
        hbox.pack_start(self.label, expand=False, fill=False)
        imageDir = os.path.join(os.path.dirname(__file__), "images")
        try:
            staticIcon = os.path.join(imageDir, "throbber_inactive.png")
            temp = gtk.gdk.pixbuf_new_from_file(staticIcon)
            self.throbber = gtk.Image()
            self.throbber.set_from_pixbuf(temp)
            animationIcon = os.path.join(imageDir, "throbber_active.gif")
            self.animation = gtk.gdk.PixbufAnimation(animationIcon)
            hbox.pack_end(self.throbber, expand=False, fill=False)
        except Exception, e:
            plugins.printWarning("Failed to create icons for the status throbber:\n" + str(e) + "\nAs a result, the throbber will be disabled.")
            self.throbber = None
        self.widget = gtk.Frame()
        self.widget.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        self.widget.add(hbox)
        self.widget.show_all()
        return self.widget

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
            self.enableHandler()
    def notifySetUpGUIComplete(self):
        self.enableHandler()
        
    def enableHandler(self):
        self.sourceId = self._enableHandler()

    def _enableHandler(self):
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
                showErrorDialog(str(e), globalTopWindow)
        
        # We must sleep for a bit, or we use the whole CPU (busy-wait)
        time.sleep(0.1)
        return True
    def notifyExit(self):
        guiplugins.processTerminationMonitor.killAll()

class TextTestGUI(Responder, plugins.Observable):
    def __init__(self, optionMap):
        self.readGtkRCFile()
        self.dynamic = not optionMap.has_key("gx")
        Responder.__init__(self, optionMap)
        plugins.Observable.__init__(self)
        guiplugins.scriptEngine = self.scriptEngine

        self.appFileGUI = ApplicationFileGUI(self.dynamic)
        self.textInfoGUI = TextInfoGUI()
        self.progressMonitor = TestProgressMonitor(self.dynamic)
        self.progressBarGUI = ProgressBarGUI(self.dynamic)
        self.idleManager = IdleHandlerManager(self.dynamic)
        self.intvActions = guiplugins.interactiveActionHandler.getInstances(self.dynamic)
        self.defaultActionGUIs, self.buttonBarGUIs = self.createActionGUIs()
        self.menuBarGUI, self.toolBarGUI, testPopupGUI = self.createMenuAndToolBarGUIs()
        self.testColumnGUI = TestColumnGUI(self.dynamic)
        self.testTreeGUI = TestTreeGUI(self.dynamic, testPopupGUI, self.testColumnGUI)
        self.testFileGUI = TestFileGUI(self.dynamic)
        self.actionTabGUIs = self.createActionTabGUIs()
        self.notebookGUIs, rightWindowGUI = self.createRightWindowGUI()
        self.shortcutBarGUI = ShortcutBarGUI()
        self.topWindowGUI = self.createTopWindowGUI(rightWindowGUI)

        self.setUpObservers() # uses the above 5
    def addActionThread(self, actionThread):
        self.topWindowGUI.addObserver(actionThread) # window closing
    def getTestTreeObservers(self):
        selectionActions = filter(lambda action: hasattr(action, "notifyNewTestSelection"), self.intvActions)
        return  selectionActions + [ self.testColumnGUI, self.testFileGUI ] + self.buttonBarGUIs + \
               [ self.textInfoGUI ] + self.actionTabGUIs + self.notebookGUIs + self.defaultActionGUIs
    def getLifecycleObservers(self):
        return [ self.textInfoGUI, self.testColumnGUI, self.testTreeGUI, self.testFileGUI, \
                 self.progressBarGUI, self.progressMonitor ] + self.actionTabGUIs  
    def getActionObservers(self):
        # These actions might change the tree view selection or the status bar, need to observe them
        return [ self.testTreeGUI, statusMonitor, self.idleManager, self.topWindowGUI ] + self.actionTabGUIs
    def getFileViewObservers(self):
        return filter(self.isFileObserver, self.intvActions)
    def isFileObserver(self, action):
        return hasattr(action, "notifyNewFileSelection") or hasattr(action, "notifyViewFile")
    def getExitObservers(self):
        return [ self, self.idleManager ]
    def getHideableGUIs(self):
        return [ self.toolBarGUI, self.shortcutBarGUI, statusMonitor ]
    def getAddSuitesObservers(self):
        return [ guiConfig, self.testColumnGUI, self.testTreeGUI, self.progressMonitor, \
                 self.appFileGUI, self.progressBarGUI, self.topWindowGUI ] + self.intvActions

    def setUpObservers(self):    
        for observer in self.getTestTreeObservers():
            self.testTreeGUI.addObserver(observer)

        for observer in self.getFileViewObservers():
            self.testFileGUI.addObserver(observer)
            self.appFileGUI.addObserver(observer)
            
        # watch for category selections
        self.progressMonitor.addObserver(self.testTreeGUI)
        for observer in self.getLifecycleObservers():        
            self.addObserver(observer) # forwarding of test observer mechanism

        for action in self.intvActions:
            for observer in self.getActionObservers():
                action.addObserver(observer)

        for observer in self.getHideableGUIs():
            self.menuBarGUI.addObserver(observer)

        for observer in self.getExitObservers():
            self.topWindowGUI.addObserver(observer)
                
    def needsOwnThread(self):
        return True
    def readGtkRCFile(self):
        file = getGtkRcFile()
        if file:
            gtk.rc_add_default_file(file)
    def setUpScriptEngine(self):
        guiplugins.setUpGlobals(self.dynamic)
        global guilog, guiConfig, scriptEngine
        from guiplugins import guilog, guiConfig
        scriptEngine = ScriptEngine(guilog, enableShortcuts=1)
        self.scriptEngine = scriptEngine
        guidialogs.setupScriptEngine(scriptEngine)
    def needsTestRuns(self):
        return self.dynamic
    def addSuites(self, suites):
        for observer in self.getAddSuitesObservers():
            observer.addSuites(suites)
            
        self.topWindowGUI.createView()
        self.topWindowGUI.activate()
        self.idleManager.enableHandler()
    def run(self):        
        gtk.main()
    def notifyExit(self, *args):
        gtk.main_quit()
    def createTopWindowGUI(self, rightWindowGUI):
        mainWindowGUI = PaneGUI(self.testTreeGUI, rightWindowGUI, horizontal=True)
        parts = [ self.menuBarGUI, self.toolBarGUI, mainWindowGUI, self.shortcutBarGUI, statusMonitor ]
        boxGUI = BoxGUI(parts, horizontal=False)
        return TopWindowGUI(boxGUI, self.dynamic)
    def createMenuAndToolBarGUIs(self):
        uiManager = gtk.UIManager()
        menu = MenuBarGUI(self.dynamic, uiManager, self.defaultActionGUIs)
        toolbar = ToolBarGUI(uiManager, self.defaultActionGUIs, self.progressBarGUI)
        popup = TestPopupMenuGUI(uiManager, self.defaultActionGUIs)
        return menu, toolbar, popup
    def createActionGUIs(self):
        defaultGUIs, buttonGUIs = [], []
        for action in self.intvActions:
            if not action.inMenuOrToolBar():
                continue

            if action.inButtonBar():
                buttonGUIs.append(ButtonActionGUI(action))
            else:
                defaultGUIs.append(DefaultActionGUI(action))
        return defaultGUIs, buttonGUIs

    def createActionGUIForTab(self, action):
        if len(action.getOptionGroups()) == 1 and action.canPerform():
            return ButtonActionGUI(action, fromTab=True)
    def createActionTabGUIs(self):
        actionTabGUIs = []
        for action in self.intvActions:
            actionGUI = self.createActionGUIForTab(action)
            for optionGroup in action.getOptionGroups():
                if optionGroup.switches or optionGroup.options:
                    actionTabGUIs.append(ActionTabGUI(optionGroup, action, actionGUI))
        return actionTabGUIs

    def createRightWindowGUI(self):
        tabGUIs = [ self.appFileGUI, self.textInfoGUI, self.progressMonitor ] + self.actionTabGUIs
        buttonBarGUI = BoxGUI(self.buttonBarGUIs, horizontal=True, reversed=True)
        topTestViewGUI = BoxGUI([ self.testFileGUI, buttonBarGUI ], horizontal=False)

        if self.dynamic:
            notebookGUI = NotebookGUI(self.classifyByTitle(tabGUIs), self.getNotebookScriptName("Top"))
            return [ notebookGUI ], PaneGUI(topTestViewGUI, notebookGUI, horizontal=False)
        else:
            subNotebookGUIs = self.createNotebookGUIs(tabGUIs)
            tabInfo = seqdict()
            for name, notebookGUI in subNotebookGUIs.items():
                if name == "Test":
                    tabInfo[name] = PaneGUI(topTestViewGUI, notebookGUI, horizontal=False)
                else:
                    tabInfo[name] = notebookGUI

            notebookGUI = NotebookGUI(tabInfo, self.getNotebookScriptName("Top"))
            return [ notebookGUI ] + subNotebookGUIs.values(), notebookGUI        

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
    def getGroupTabNames(self, tabGUIs):
        tabNames = [ "Test", "Selection", "Running" ]
        for tabGUI in tabGUIs:
            tabName = tabGUI.getGroupTabTitle()
            if not tabName in tabNames:
                tabNames.append(tabName)
        return tabNames
    def createNotebookGUIs(self, tabGUIs):
        tabInfo = seqdict()
        for tabName in self.getGroupTabNames(tabGUIs):
            currTabGUIs = filter(lambda tabGUI: tabGUI.getGroupTabTitle() == tabName, tabGUIs)
            if len(currTabGUIs) > 1:
                notebookGUI = NotebookGUI(self.classifyByTitle(currTabGUIs), self.getNotebookScriptName(tabName))
                tabInfo[tabName] = notebookGUI
            elif len(currTabGUIs) == 1:
                tabInfo[tabName] = currTabGUIs[0]
            else:
                raise plugins.TextTestError, "No contents at all found for " + tabName 
        return tabInfo
    def notifyLifecycleChange(self, test, state, changeDesc):
        # Working around python bug 853411: main thread must do all forking
        if hasattr(state, "notifyInMainThread"):
            state.notifyInMainThread()
            return

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
    def contentsChanged(self):
        pass # doesn't use this yet    
   

class TopWindowGUI(ContainerGUI):
    def __init__(self, contentGUI, dynamic):
        ContainerGUI.__init__(self, [ contentGUI ])
        self.dynamic = dynamic
        self.topWindow = None
        self.appNames = []
        self.windowSizeDescriptor = ""
    def addSuites(self, suites):
        for suite in suites:
            if not suite.app.fullName in self.appNames:
                self.appNames.append(suite.app.fullName)
    def createView(self):
        # Create toplevel window to show it all.
        self.topWindow = gtk.Window(gtk.WINDOW_TOPLEVEL)
        global globalTopWindow
        globalTopWindow = self.topWindow
        if self.dynamic:
            self.topWindow.set_title("TextTest dynamic GUI (tests started at " + plugins.startTimeString() + ")")
        else:
            self.topWindow.set_title("TextTest static GUI : management of tests for " + string.join(self.appNames, ","))
            
        self.topWindow.add(self.subguis[0].createView())
        self.topWindow.show()
        scriptEngine.connect("close window", "delete_event", self.topWindow, self.notifyExit)
        self.windowSizeDescriptor = self.adjustSize()
        return self.topWindow
    def writeSeparator(self):
        pass # Don't bother, we're at the top
    def describe(self):
        guilog.info("Top Window title is " + self.topWindow.get_title())
        guilog.info("Default widget is " + str(self.topWindow.get_focus().__class__))
        guilog.info(self.windowSizeDescriptor)
    def notifyExit(self, *args):
        self.notify("Exit")
        self.topWindow.destroy()

    def adjustSize(self):
        if guiConfig.getWindowOption("maximize"):
            self.topWindow.maximize()
            return "Maximising top window..."
        else:
            width, widthDescriptor = self.getWindowDimension("width")
            height, heightDescriptor  = self.getWindowDimension("height")
            self.topWindow.resize(width, height)
            return widthDescriptor + "\n" + heightDescriptor
    def getWindowDimension(self, dimensionName):
        pixelDimension = guiConfig.getWindowOption(dimensionName + "_pixels")
        if pixelDimension != "<not set>":
            descriptor = "Setting window " + dimensionName + " to " + pixelDimension + " pixels."
            return int(pixelDimension), descriptor
        else:
            fullSize = eval("gtk.gdk.screen_" + dimensionName + "()")
            proportion = float(guiConfig.getWindowOption(dimensionName + "_screen"))
            descriptor = "Setting window " + dimensionName + " to " + repr(int(100.0 * proportion)) + "% of screen."
            return int(fullSize * proportion), descriptor

    def getDefaultWindowProportion(self, dimensionName):
        if dimensionName == "height":
            return float(5.0) / 6
        else:
            return 0.6


class MenuBarGUI(SubGUI):
    def __init__(self, dynamic, uiManager, actionGUIs):
        SubGUI.__init__(self)
        # Create GUI manager, and a few default action groups
        self.dynamic = dynamic
        self.uiManager = uiManager
        self.actionGUIs = actionGUIs
        self.actionGroup = gtk.ActionGroup("AllActions")
        self.uiManager.insert_action_group(self.actionGroup, 0)
        self.toggleActions = []
    def setActive(self, active):
        SubGUI.setActive(self, active)
        self.widget.get_toplevel().add_accel_group(self.uiManager.get_accel_group())
        if self.shouldHide("menubar"):
            self.hide(self.widget, "Menubar")
        for toggleAction in self.toggleActions:
            if self.shouldHide(toggleAction.get_name()):
                toggleAction.set_active(False)
    def shouldHide(self, name):
        return guiConfig.getCompositeValue("hide_gui_element", name, modeDependent=True)
    def toggleVisibility(self, action, observer, *args):
        widget = observer.widget
        oldVisible = widget.get_property('visible')
        newVisible = action.get_active()
        if oldVisible and not newVisible:
            self.hide(widget, action.get_name())
        elif newVisible and not oldVisible:
            self.show(widget, action.get_name())
    def hide(self, widget, name):
        widget.hide()
        guilog.info("Hiding the " + name)
    def show(self, widget, name):
        widget.show()
        guilog.info("Showing the " + name)
    def createToggleActions(self):
        for observer in self.observers:
            actionTitle = observer.getWidgetName()
            actionName = actionTitle.replace("_", "")
            gtkAction = gtk.ToggleAction(actionName, actionTitle, None, None)
            gtkAction.set_active(True)
            self.actionGroup.add_action(gtkAction)
            gtkAction.connect("toggled", self.toggleVisibility, observer)
            scriptEngine.registerToggleButton(gtkAction, "show " + actionName, "hide " + actionName)
            self.toggleActions.append(gtkAction)
    def getInterfaceDescription(self):
        description = "<ui>\n<menubar name=\"MainMenuBar\">\n"
        for action in self.actionGUIs:
            description += self.getMenuDescription(action)
        # Special treatment for View menu ...
        description += "</menubar></ui>\n"        
        return description
    def getMenuDescription(self, action):
        menuPath = action.action.getMainMenuPath()
        if menuPath == "-":
            return ""
        pre = []
        post = []
        if menuPath != "":
            for item in menuPath.split("/"):
                itemName = item.replace("_", "").lower() + "menu"
                if not self.actionGroup.get_action(itemName):
                    self.actionGroup.add_action(gtk.Action(itemName, item, None, None))
                thisAction = self.actionGroup.get_action(itemName)
                pre.append("<menu action=\"" + thisAction.get_name() + "\">")
                post.append("</menu>")
        if action.action.hasExternalGUIDescription():
            return "" # We create the actions, but don't add anything to the description ..
        if action.action.separatorBeforeInMainMenu():
            pre.append("<separator/>\n")
        pre.append("<menuitem action=\"" + action.action.getTitle() + "\"/>")
        if action.action.separatorAfterInMainMenu():
            pre.append("<separator/>\n")
        description = ""
        for s in pre:
            description += s + "\n"
        for i in xrange(len(post) - 1, -1, -1):
            description += post[i] + "\n"
        return description
    def createView(self):
        # Initialize
        self.actionGroup.add_action(gtk.Action("filemenu", "_File", None, None))
        self.actionGroup.add_action(gtk.Action("editmenu", "_Edit", None, None))
        self.actionGroup.add_action(gtk.Action("viewmenu", "_View", None, None))
        self.actionGroup.add_action(gtk.Action("actionsmenu", "_Actions", None, None))
        self.createToggleActions()
        for actionGUI in self.actionGUIs:
            actionGUI.addToGroups(self.actionGroup, self.uiManager.get_accel_group())
            
        # Also creates default actions, so we msut do this before reading the file ...
        description = self.getInterfaceDescription() 
        if self.dynamic:
            self.uiManager.add_ui_from_file(os.path.join(os.path.dirname(__file__), "standard_gui_dynamic.xml"))
        else:
            self.uiManager.add_ui_from_file(os.path.join(os.path.dirname(__file__), "standard_gui_static.xml"))

        self.uiManager.add_ui_from_string(description)
        self.uiManager.ensure_update()
        self.widget = self.uiManager.get_widget("/MainMenuBar")
        return self.widget
    def describe(self):
        for toggleAction in self.toggleActions:
            guilog.info("Viewing toggle action with title '" + toggleAction.get_property("label") + "'")
        for actionGUI in self.actionGUIs:
            actionGUI.describe()

class ToolBarGUI(ContainerGUI):
    def __init__(self, uiManager, actionGUIs, subgui):
        ContainerGUI.__init__(self, [ subgui ])
        self.uiManager = uiManager
        self.actionGUIs = filter(lambda a: a.action.inToolBar(), actionGUIs)
    def getWidgetName(self):
        return "_Toolbar"
    def ensureVisible(self, toolbar):
        for item in toolbar.get_children(): 
            item.set_is_important(True) # Or newly added children without stock ids won't be visible in gtk.TOOLBAR_BOTH_HORIZ style
    def getInterfaceDescription(self):
        description = "<ui>\n<toolbar name=\"MainToolBar\">\n"
        for actionGUI in self.actionGUIs:
            if actionGUI.action.hasExternalGUIDescription():
                continue
            if actionGUI.action.separatorBeforeInToolBar():
                description += "<separator/>\n"
            description += "<toolitem action=\"" + actionGUI.action.getTitle() + "\"/>\n"
            if actionGUI.action.separatorAfterInToolBar():
                description += "<separator/>\n"
        description += "</toolbar>\n</ui>\n"
        return description
    def createView(self):
        self.uiManager.add_ui_from_string(self.getInterfaceDescription())
        self.uiManager.ensure_update()
        toolbar = self.uiManager.get_widget("/MainToolBar")
        self.ensureVisible(toolbar)
  
        self.widget = gtk.HandleBox()
        self.widget.add(toolbar)
        toolbar.set_orientation(gtk.ORIENTATION_HORIZONTAL)
        progressBarGUI = self.subguis[0]
        if progressBarGUI.shouldShowCurrent():
            progressBar = progressBarGUI.createView()
            width = 7 # Looks good, same as gtk.Paned border width
            alignment = gtk.Alignment()
            alignment.set(1.0, 1.0, 1.0, 1.0)
            alignment.set_padding(width, width, 1, width)
            alignment.add(progressBar)
            toolItem = gtk.ToolItem()
            toolItem.add(alignment)
            toolItem.set_expand(True)
            toolbar.insert(toolItem, -1)
            
        self.widget.show_all()
        return self.widget
    def describe(self):
        guilog.info("UI layout: \n" + self.uiManager.get_ui())

class TestPopupMenuGUI(SubGUI):
    def __init__(self, uiManager, actionGUIs):
        SubGUI.__init__(self)
        self.uiManager = uiManager
        self.actionGUIs = actionGUIs
        self.actionGroup = uiManager.get_action_groups()[0]
    def getWidgetName(self):
        return "_TestPopupMenu"
    def getInterfaceDescription(self):
        description = "<ui>\n<popup name=\"TestPopupMenu\">\n"
        for action in self.actionGUIs:
            description += self.getMenuDescription(action)
        description += "</popup></ui>\n"        
        return description
    def getMenuDescription(self, action):
        menuPath = action.action.getTestPopupMenuPath()
        if menuPath == "-":
            return ""
        pre = []
        post = []
        if menuPath != "":
            for item in menuPath.split("/"):
                itemName = item.replace("_", "").lower() + "menu"
                if not self.actionGroup.get_action(itemName):
                    self.actionGroup.add_action(gtk.Action(itemName, item, None, None))
                thisAction = self.actionGroup.get_action(itemName)
                pre.append("<menu action=\"" + thisAction.get_name() + "\">")
                post.append("</menu>")

        if action.action.hasExternalGUIDescription(): # We create the actions, but don't add anything to the description ..
            return ""
        if action.action.separatorBeforeInTestPopupMenu():
            pre.append("<separator/>\n")
        pre.append("<menuitem action=\"" + action.action.getTitle() + "\"/>")
        if action.action.separatorAfterInTestPopupMenu():
            pre.append("<separator/>\n")
        description = ""
        for s in pre:
            description += s + "\n"
        for i in xrange(len(post) - 1, -1, -1):
            description += post[i] + "\n"
        return description
    def createView(self):
        self.uiManager.add_ui_from_string(self.getInterfaceDescription())
        self.uiManager.ensure_update()
        self.widget = self.uiManager.get_widget("/TestPopupMenu")
        self.widget.show_all()
        return self.widget

class ShortcutBarGUI(SubGUI):
    def getWidgetName(self):
        return "_Shortcut bar"
    def createView(self):
        self.widget = scriptEngine.createShortcutBar()
        self.widget.show()
        return self.widget
    def contentsChanged(self):
        pass # not yet integrated

class TestColumnGUI(SubGUI):
    def __init__(self, dynamic):
        SubGUI.__init__(self)
        self.totalNofTests = 0
        self.nofSelectedTests = 0
        self.totalNofTestsShown = 0
        self.column = None
        self.dynamic = dynamic
    def addSuites(self, suites):
        size = sum([ suite.size() for suite in suites ])
        self.totalNofTests += size
        self.totalNofTestsShown += size
    def createView(self):
        testRenderer = gtk.CellRendererText()
        self.column = gtk.TreeViewColumn(self.getTitle(), testRenderer, text=0, background=1)
        self.column.set_cell_data_func(testRenderer, renderSuitesBold)
        return self.column
    def getTitle(self):
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
        return title
    def updateTitle(self):
        if self.column:
            self.column.set_title(self.getTitle())
            self.contentsChanged()
    def describe(self):
        guilog.info("Test column header set to '" + self.column.get_title() + "'")
    def notifyAdd(self, test):
        if test.classId() == "test-case":
            self.totalNofTests += 1
            self.updateTitle()
    def notifyRemove(self, test):
        self.totalNofTests -= test.size()
        self.updateTitle()
    def notifyNewTestSelection(self, tests, direct):
        testcases = filter(lambda test: test.classId() == "test-case", tests)
        newCount = len(testcases)
        if self.nofSelectedTests != newCount:
            self.nofSelectedTests = newCount
            self.updateTitle()
    def notifyVisibility(self, tests, newValue):
        if newValue:
            self.totalNofTestsShown += len(tests)
        else:
            self.totalNofTestsShown -= len(tests)
        self.updateTitle()
    
        
class TestTreeGUI(ContainerGUI):
    def __init__(self, dynamic, popupGUI, subGUI):
        ContainerGUI.__init__(self, [ subGUI ])
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT,\
                                   gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_BOOLEAN)
        self.popupGUI = popupGUI
        self.itermap = seqdict()
        self.selection = None
        self.selecting = False
        self.dynamic = dynamic
        self.collapseStatic = False
        self.successPerSuite = {} # map from suite to number succeeded
        self.collapsedRows = {}
        self.filteredModel = None
        self.treeView = None
    def setActive(self, value):
        # avoid the quit button getting initial focus, give it to the tree view (why not?)
        ContainerGUI.setActive(self, value)
        self.treeView.grab_focus()
    def describe(self):
        guilog.info("Test Tree description...")
        self.filteredModel.foreach(self.describeRow)
    def describeRow(self, model, path, iter):
        parentIter = model.iter_parent(iter)
        if not parentIter or self.treeView.row_expanded(model.get_path(parentIter)):
            test = model.get_value(iter, 2)
            guilog.info("-> " + test.getIndent() + model.get_value(iter, 0))
    def addSuites(self, suites):
        if self.dynamic:
            self.notify("NewTestSelection", [ suites[0] ], False)
        else:
            self.collapseStatic = guiConfig.getValue("static_collapse_suites")
        for suite in suites:
            size = suite.size()
            if not self.dynamic or size > 0:
                self.addSuiteWithParent(suite, None)
    def addSuiteWithParent(self, suite, parent, follower=None):    
        iter = self.model.insert_before(parent, follower)
        nodeName = suite.name
        if parent == None:
            appName = suite.app.name + suite.app.versionSuffix()
            if appName != nodeName:
                nodeName += " (" + appName + ")"
        self.model.set_value(iter, 0, nodeName)
        self.model.set_value(iter, 2, suite)
        self.model.set_value(iter, 3, suite.uniqueName)
        self.model.set_value(iter, 6, True)
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
        if self.dynamic:
            self.selection.set_select_function(self.canSelect)
        self.selection.connect("changed", self.userChangedSelection)
        testsColumn = self.subguis[0].createView()
        self.treeView.append_column(testsColumn)
        if self.dynamic:
            detailsRenderer = gtk.CellRendererText()
            perfColumn = gtk.TreeViewColumn("Details", detailsRenderer, text=4, background=5)
            self.treeView.append_column(perfColumn)

        modelIndexer = TreeModelIndexer(self.filteredModel, testsColumn, 3)
        scriptEngine.monitorExpansion(self.treeView, "show test suite", "hide test suite", modelIndexer)
        self.treeView.connect('row-expanded', self.rowExpanded)
        self.expandLevel(self.treeView, self.filteredModel.get_iter_root())
        self.treeView.connect('row-expanded', self.describeTree) # later expansions should cause description...
        self.treeView.connect("button_press_event", self.showPopupMenu)
        
        scriptEngine.monitor("set test selection to", self.selection, modelIndexer)
        self.treeView.show()
        if self.dynamic:
            self.filteredModel.connect('row-inserted', self.rowInserted)
            self.filteredModel.refilter()

        self.popupGUI.createView()
        return self.addScrollBars(self.treeView)
    def describeTree(self, *args):
        SubGUI.contentsChanged(self) # don't describe the column too...

    def showPopupMenu(self, treeview, event):
        if event.button == 3:
            if len(self.popupGUI.widget.get_children()) == 0:
                return 0
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pathInfo = treeview.get_path_at_pos(x, y)
            if pathInfo is not None:
                path, col, cellx, celly = pathInfo
                treeview.grab_focus()
                treeview.set_cursor(path, col, 0)
                self.popupGUI.widget.popup(None, None, None, event.button, time)
                return 1
        return 0

    def canSelect(self, path):
        pathIter = self.filteredModel.get_iter(path)
        test = self.filteredModel.get_value(pathIter, 2)
        return test.classId() == "test-case"

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

    def userChangedSelection(self, *args):
        if not self.selecting and not hasattr(self.selection, "unseen_changes"):
            self.selectionChanged(direct=True)
    def selectionChanged(self, direct):
        self.notify("NewTestSelection", self.getSelected(), direct)
    def getSelected(self):
        allSelected = []
        self.selection.selected_foreach(self.addSelTest, allSelected)
        return allSelected
    def addSelTest(self, model, path, iter, selected, *args):
        selected.append(model.get_value(iter, 2))
    def findIter(self, test):
        try:
            return self.filteredModel.convert_child_iter_to_iter(self.itermap[test])
        except RuntimeError:
            pass # convert_child_iter_to_iter throws RunTimeError if the row is hidden in the TreeModelFilter
    def notifySetTestSelection(self, selTests, selectCollapsed=True):
        self.selectTestRows(selTests, selectCollapsed)
        self.selectionChanged(direct=False) # Here it's been set via some indirect mechanism, might want to behave differently 
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
    def expandLevel(self, view, iter, recursive=True):
        # Make sure expanding expands everything, better than just one level as default...
        # Avoid using view.expand_row(path, open_all=True), as the open_all flag
        # doesn't seem to send the correct 'row-expanded' signal for all rows ...
        # This way, the signals are generated one at a time and we call back into here.
        model = view.get_model()
        while (iter != None):
            test = model.get_value(iter, 2)
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
        guilog.info("Selecting new test " + test.name)
        self.notifySetTestSelection([ test ])
        self.describeTree()
    def addTest(self, test):
        suite = test.parent
        suiteIter = self.itermap[suite]
        follower = suite.getFollower(test)
        followIter = self.itermap.get(follower)
        iter = self.addSuiteWithParent(test, suiteIter, followIter)
    def notifyRemove(self, test):
        self.removeTest(test)
        guilog.info("Removing test with path " + test.getRelPath())
    def removeTest(self, test):
        iter = self.itermap[test]
        filteredIter = self.findIter(test)
        if self.selection.iter_is_selected(filteredIter):
            self.selection.unselect_iter(filteredIter)
        self.model.remove(iter)
        del self.itermap[test]
    def notifyContentChange(self, suite):
        allSelected = self.getSelected()
        self.selecting = True
        self.selection.unselect_all()
        for test in suite.testcases:
            self.removeTest(test)
        for test in suite.testcases:
            self.addTest(test)
        self.expandRow(self.findIter(suite), True)
        self.selectTestRows(allSelected) # don't notify observers as nothing has changed except order
    def notifyVisibility(self, tests, newValue):
        if not newValue:
            self.selecting = True
        changedTests = []
        for test in tests:
            if self.updateVisibilityInModel(test, newValue):
                changedTests.append(test)

        if len(changedTests) > 0:
            self.selecting = False
            self.notify("Visibility", changedTests, newValue)
            if self.treeView:
                self.updateVisibilityInViews(newValue)
    def updateVisibilityInViews(self, newValue):
        self.filteredModel.refilter()
        if newValue: # if things have become visible, expand everything
            rootIter = self.filteredModel.get_iter_root()
            while rootIter != None:
                self.expandRow(rootIter, True)
                rootIter = self.filteredModel.iter_next(rootIter)
        else:
            self.selectionChanged(direct=False)

    def updateVisibilityInModel(self, test, newValue):
        allIterators = self.findVisibilityIterators(test) # returns leaf-to-root order, good for hiding
        if newValue:
            allIterators.reverse()  # but when showing, we want to go root-to-leaf

        changed = False
        for iterator in allIterators:
            if newValue or not self.hasVisibleChildren(iterator):
                changed |= self.setVisibility(iterator, newValue)
        return changed
        
    def setVisibility(self, iter, newValue):
        oldValue = self.model.get_value(iter, 6)
        if oldValue == newValue:
            return False

        test = self.model.get_value(iter, 2)
        if self.treeView:
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

class ActionGUI(SubGUI):
    def __init__(self, action):
        SubGUI.__init__(self)
        self.action = action
    def describe(self):
        message = "Viewing action with title '" + self.action.getTitle(includeMnemonics=True) + "'"
        message += self.detailDescription()
        message += self.sensitivityDescription()
        guilog.info(message)
    def notifyNewTestSelection(self, tests, direct):
        if self.updateSensitivity():
            newActive = self.actionOrButton().get_property("sensitive")
            guilog.info("Setting sensitivity of button '" + self.action.getTitle(includeMnemonics=True) + "' to " + repr(newActive))
    def updateSensitivity(self):
        actionOrButton = self.actionOrButton()
        if not actionOrButton:
            return False
        oldActive = actionOrButton.get_property("sensitive")
        newActive = self.action.isActiveOnCurrent()
        if oldActive != newActive:
            actionOrButton.set_property("sensitive", newActive)
            return True
        else:
            return False
    def detailDescription(self):
        return ""
    def sensitivityDescription(self):
        if self.actionOrButton().get_property("sensitive"):
            return ""
        else:
            return " (greyed out)"
    def runInteractive(self, *args):
        if statusMonitor.busy(): # If we're busy with some other action, ignore this one ...
            return
        doubleCheckMessage = self.action.getDoubleCheckMessage()
        if doubleCheckMessage:
            self.dialog = DoubleCheckDialog(doubleCheckMessage, self._runInteractive, self._dontRun, globalTopWindow)
        else:
            dialogType = self.action.getDialogType()
            if dialogType:
                dialogClass = eval(dialogType)
                dialog = dialogClass(globalTopWindow, self._runInteractive, self._dontRun, self.action)
                dialog.run()
            else:
                self._runInteractive()

    def _dontRun(self):
        statusMonitor.notifyStatus("Action cancelled.")
    def _runInteractive(self):
        try:
            self.action.perform()
        except plugins.TextTestError, e:
            showErrorDialog(str(e), globalTopWindow)
        except plugins.TextTestWarning, e:
            showWarningDialog(str(e), globalTopWindow)
        except plugins.TextTestInformation, e:
            showInformationDialog(str(e), globalTopWindow)
    
           
class DefaultActionGUI(ActionGUI):
    def __init__(self, action):
        ActionGUI.__init__(self, action)
        self.accelerator = None
        title = self.action.getTitle(includeMnemonics=True)
        actionName = self.action.getTitle(includeMnemonics=False)
        self.gtkAction = gtk.Action(actionName, title, \
                                    self.action.getTooltip(), self.getStockId())

        scriptEngine.connect(self.action.getScriptTitle(False), "activate", self.gtkAction, self.runInteractive)
        self.updateSensitivity()
    def addToGroups(self, actionGroup, accelGroup):
        self.accelerator = self.getAccelerator()
        actionGroup.add_action_with_accel(self.gtkAction, self.accelerator)
        self.gtkAction.set_accel_group(accelGroup)
        self.gtkAction.connect_accelerator()
        
    def actionOrButton(self):
        return self.gtkAction
    def getStockId(self):
        stockId = self.action.getStockId()
        if stockId:
            return "gtk-" + stockId 
        
    def getAccelerator(self):
        realAcc = guiConfig.getCompositeValue("gui_accelerators", self.action.getTitle().rstrip("."))
        if realAcc:
            key, mod = gtk.accelerator_parse(realAcc)
            if self.isValid(key, mod):
                return realAcc
            else:
                plugins.printWarning("Keyboard accelerator '" + realAcc + "' for action '" \
                                     + self.action.getTitle() + "' is not valid, ignoring ...")
    def isValid(self, key, mod):
        if os.name == "nt":
            # gtk.accelerator_valid appears utterly broken on Windows
            name = gtk.accelerator_name(key, mod)
            return len(name) > 0 and name != "VoidSymbol"
        else:
            return gtk.accelerator_valid(key, mod)
    def detailDescription(self):
        message = ""
        stockId = self.getStockId()
        if stockId:
            message += ", stock id '" + repr(stockId) + "'"
        if self.accelerator:
            message += ", accelerator '" + repr(self.accelerator) + "'"
        return message            
    
class ButtonActionGUI(ActionGUI):
    def __init__(self, action, fromTab=False):
        ActionGUI.__init__(self, action)
        self.scriptTitle = self.action.getScriptTitle(fromTab)
        self.button = None
        self.tooltips = gtk.Tooltips()
    def actionOrButton(self):
        return self.button
    def createView(self):
        self.button = gtk.Button(self.action.getTitle(includeMnemonics=True))
        self.tooltips.set_tip(self.button, self.scriptTitle)
        scriptEngine.connect(self.scriptTitle, "clicked", self.button, self.runInteractive)
        self.updateSensitivity()
        self.button.show()
        return self.button
    
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

    def getExpandWidgets(self):
        return [ gtk.HPaned, gtk.ScrolledWindow ]
    def contentsChanged(self):
        if not self.active:
            return
        
        if self.horizontal:
            guilog.info("")
            for subgui in self.subguis:
                subgui.describe()
        else:
            for subgui in self.subguis:
                subgui.contentsChanged()
    def createView(self):
        box = self.createBox()
        packMethod = self.getPackMethod(box)
        for subgui in self.getOrderedSubGUIs():
            view = subgui.createView()
            expand = view.__class__ in self.getExpandWidgets()
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
    def notifyReset(self):
        self.optionGroup.reset()
    def notifyLifecycleChange(self, test, state, changeDesc):
        changedContents, changedValues = self.action.updateForStateChange(test, state)
        self.handleChanges(changedContents, changedValues)     
    def notifyNewTestSelection(self, tests, direct):
        if len(tests) == 0:
            return
        changedContents, changedValues = self.action.updateForSelectionChange()
        self.handleChanges(changedContents, changedValues)
        
    def handleChanges(self, changedContents, changedValues):
        if changedContents:
            self.recreateContents()
        if changedContents or changedValues:
            self.contentsChanged()
    def recreateContents(self):
        if not self.vbox:
            return
        container = self.vbox.get_parent()
        if container:
            container.remove(self.vbox)
            container.add(self.createVBox())
            container.show()
        
    def createVBox(self):
        self.vbox = gtk.VBox()
        if len(self.optionGroup.options) > 0:
            # Creating 0-row table gives a warning ...
            table = gtk.Table(len(self.optionGroup.options), 2, homogeneous=False)
            table.set_row_spacings(1)
            rowIndex = 0        
            for option in self.optionGroup.options.values():
                newValue = self.updateForConfig(option)
                if newValue:
                    option.addPossibleValue(newValue)
                for extraOption in self.getConfigOptions(option):
                    option.addPossibleValue(extraOption)

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
        
        option.setClearMethod(combobox.get_model().clear)
        return combobox, entry
    
    def createOptionWidget(self, option):
        if option.inqNofValues() > 1:
            return self.createComboBox(option)
        else:
            entry = gtk.Entry()
            return entry, entry
    def getConfigOptions(self, option):
        return guiConfig.getCompositeValue("gui_entry_options", option.name)    
    def updateForConfig(self, option):
        fromConfig = guiConfig.getCompositeValue("gui_entry_overrides", option.name)
        if fromConfig != "<not set>":
            option.setValue(fromConfig)
            return fromConfig
    
    def createOptionEntry(self, option):
        widget, entry = self.createOptionWidget(option)
        label = gtk.EventBox()
        label.add(gtk.Label(option.name + "  "))
        if option.description:
            self.tooltips.set_tip(label, option.description)
        scriptEngine.registerEntry(entry, "enter " + option.name + " =")
        entry.set_text(option.getValue())
        option.setMethods(entry.get_text, entry.set_text)
        if option.changeMethod:
            entry.connect("changed", option.changeMethod)
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
            for index in range(len(switch.options)):
                option = switch.options[index]
                if guiConfig.getCompositeValue("gui_entry_overrides", switch.name + option) == "1":
                    switch.setValue(index)
                radioButton = gtk.RadioButton(mainRadioButton, option)
                buttons.append(radioButton)
                scriptEngine.registerToggleButton(radioButton, "choose " + option)
                if not mainRadioButton:
                    mainRadioButton = radioButton
                if switch.getValue() == index:
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
            self.updateForConfig(switch)
            checkButton = gtk.CheckButton(switch.name)
            if int(switch.getValue()):
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
    def __init__(self, tabInfo, scriptTitle):
        SubGUI.__init__(self)
        self.scriptTitle = scriptTitle
        self.diag = plugins.getDiagnostics("GUI notebook")
        self.tabInfo = tabInfo
        self.notebook = None
        self.currentPageName = ""

    def setActive(self, value):
        SubGUI.setActive(self, value)
        if self.currentPageName:
            self.tabInfo[self.currentPageName].setActive(value)

    def contentsChanged(self):
        SubGUI.contentsChanged(self)
        if self.currentPageName:
            self.tabInfo[self.currentPageName].contentsChanged()

    def shouldShowCurrent(self):
        for tabGUI in self.tabInfo.values():
            if tabGUI.shouldShowCurrent():
                return True
        return False

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

    def notifyNewTestSelection(self, tests, direct):
        if not self.notebook:
            return 

        pagesAdded = self.insertNewPages()
        pagesRemoved = self.removeOldPages()
        if direct: # only change pages around if a test is directly selected
            self.updateCurrentPage(tests)
  
        if pagesAdded or pagesRemoved:
            SubGUI.contentsChanged(self) # just the tabs will do here, the rest is described by other means
          
class PaneGUI(ContainerGUI):
    def __init__(self, gui1, gui2 , horizontal):
        ContainerGUI.__init__(self, [ gui1, gui2 ])
        self.horizontal = horizontal
        self.panedTooltips = gtk.Tooltips()
        self.paned = None
    def getSeparatorPosition(self):
        if self.horizontal:
            return float(guiConfig.getWindowOption("vertical_separator_position"))
        else:
            return float(guiConfig.getWindowOption("horizontal_separator_position"))
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
        self.adjustSeparator()
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
    def contentsChanged(self):
        self.subguis[0].contentsChanged()
        if self.adjustSeparator():
            guilog.info("")
            guilog.info("Pane separator positioned " + self.positionDescription(self.getSeparatorPosition()))
        self.subguis[1].contentsChanged()        
    def adjustSeparator(self):
        pos = int(self.getSize() * self.getSeparatorPosition())
        if pos:
            self.paned.set_position(pos)
            return True
        else:
            return False
    
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
    def notifyNewTestSelection(self, tests, direct):
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
        
    def createView(self):
        self.model.clear()
        self.addFilesToModel(self.getState())
        view = gtk.TreeView(self.model)
        self.selection = view.get_selection()
        self.selection.set_mode(gtk.SELECTION_MULTIPLE)
        self.selection.set_select_function(self.canSelect)
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
    def canSelect(self, path):
        pathIter = self.model.get_iter(path)
        return not self.model.iter_has_child(pathIter)
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
            showErrorDialog(str(e), globalTopWindow)

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
    
class ApplicationFileGUI(FileViewGUI):
    def __init__(self, dynamic):
        FileViewGUI.__init__(self, dynamic)
        self.allApps = []
    def addSuites(self, suites):
        self.allApps = [ suite.app for suite in suites ]
    def shouldShowCurrent(self):
        return not self.dynamic
    def getGroupTabTitle(self):
        return "Config"
    def getName(self):
        return "Configuration Files"
    def monitorEvents(self, indexer):
        scriptEngine.connect("select application file", "row_activated", self.selection.get_tree_view(), self.fileActivated, indexer)
    def addFilesToModel(self, state):
        colour = guiConfig.getCompositeValue("file_colours", "app_static")
        personalFiles = self.getPersonalFiles()
        if len(personalFiles) > 0:
            persiter = self.model.insert_before(None, None)
            self.model.set_value(persiter, 0, "Personal Files")
            for file in personalFiles:
                self.addFileToModel(persiter, file, None, colour)

        for app in self.allApps:
            confiter = self.model.insert_before(None, None)
            self.model.set_value(confiter, 0, "Files for " + app.fullName)
            for file in self.getConfigFiles(app):
                self.addFileToModel(confiter, file, None, colour)

    def getConfigFiles(self, app):
        configFiles = app.dircache.findAllFiles("config", [ app.name ])
        configFiles.sort()
        return configFiles
    def getPersonalFiles(self):
        personalFiles = []
        personalFile = self.allApps[0].getPersonalConfigFile()
        if personalFile:
            personalFiles.append(personalFile)
        gtkRcFile = getGtkRcFile()
        if gtkRcFile:
            personalFiles.append(gtkRcFile)
        return personalFiles

class TestFileGUI(FileViewGUI):
    def __init__(self, dynamic):
        FileViewGUI.__init__(self, dynamic)
        self.currentTest = None
    def notifyFileChange(self, test):
        if test is self.currentTest:
            self.recreateModel(test.state)
    def notifyLifecycleChange(self, test, state, changeDesc):
        if test is self.currentTest:
            self.recreateModel(state)
    def forceVisible(self, tests):
        return len(tests) == 1
    
    def notifyNewTestSelection(self, tests, direct):
        if not self.dynamic and len(tests) != 1: # multiple tests in static GUI result in removal
            self.currentTest = None
            self.nameColumn = None
            self.selection = None
            return

        if len(tests) > 1 and self.currentTest in tests:
            self.setName(tests)
            self.describeName()
        elif len(tests) > 0:
            self.currentTest = tests[0]
            self.currentTest.refreshFiles()
            self.setName(tests)
            self.recreateModel(self.getState())
    def getName(self, tests=[]):
        if len(tests) > 1:
            return "Sample from " + repr(len(tests)) + " tests"
        else:
            return self.currentTest.name.replace("_", "__")
    def getColour(self, name):
        return self.currentTest.getConfigValue("file_colours")[name]

    def shouldShowCurrent(self):
        return self.currentTest is not None
            
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
        return self.currentTest.state
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
        relPath = self.currentTest.getTestRelPath(file)
        if relPath is None:
            print "Warning: unrelated", file, "and", self.currentTest.getDirectory()
        if relPath.find(os.sep) != -1:
            dir, local = os.path.split(relPath)
            return dir
        else:
            return ""
    def getComparisonColour(self, fileComp):
        if not self.currentTest.state.hasStarted():
            return self.getStaticColour()
        if not self.currentTest.state.isComplete():
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
        tmpFiles = self.currentTest.listTmpFiles()
        tmpIter = self.model.insert_before(None, None)
        self.model.set_value(tmpIter, 0, "Temporary Files")
        self.addStandardFilesUnderIter(tmpIter, tmpFiles)
    def addStaticFilesToModel(self):
        stdFiles, defFiles = self.currentTest.listStandardFiles(allVersions=True)
        if self.currentTest.classId() == "test-case":
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
            return self.currentTest.app.configObject.extraReadFiles(self.currentTest).items()
        except:
            sys.stderr.write("WARNING - ignoring exception thrown by '" + self.currentTest.app.configObject.moduleName + \
                             "' configuration while requesting extra data files, not displaying any such files")
            plugins.printException()
            return seqdict()
    def addStaticDataFilesToModel(self):
        dataFiles = self.currentTest.listDataFiles()
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
        dirIters = { self.currentTest.getDirectory() : iter }
        parentIter = iter
        for file in files:
            parent, local = os.path.split(file)
            parentIter = dirIters[parent]
            newiter = self.addFileToModel(parentIter, file, None, colour)
            if os.path.isdir(file):
                dirIters[file] = newiter
  
class ProgressBarGUI(SubGUI):
    def __init__(self, dynamic):
        SubGUI.__init__(self)
        self.dynamic = dynamic
        self.totalNofTests = 0
        self.nofCompletedTests = 0
        self.nofFailedTests = 0
        self.widget = None
    def shouldShowCurrent(self):
        return self.dynamic
    def describe(self):
        guilog.info("Progress bar set to fraction " + str(self.widget.get_fraction()) + ", text '" + self.widget.get_text() + "'")
    def createView(self):
        self.widget = gtk.ProgressBar()
        self.resetBar()
        self.widget.show()
        return self.widget
    def addSuites(self, suites):
        self.totalNofTests = sum([ suite.size() for suite in suites ])
    def notifyLifecycleChange(self, test, state, changeDesc):
        failed = state.hasFailed()
        if changeDesc == "complete":
            self.nofCompletedTests += 1
            if failed:
                self.nofFailedTests += 1
            self.resetBar()
            self.contentsChanged()
        elif state.isComplete() and not failed: # test saved, possibly partially so still check 'failed'
            self.nofFailedTests -= 1
            self.adjustFailCount()
            
    def resetBar(self):
        message = self.getFractionMessage()
        message += self.getFailureMessage(self.nofFailedTests)
        fraction = float(self.nofCompletedTests) / float(self.totalNofTests)
        self.widget.set_text(message)
        self.widget.set_fraction(fraction)
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
        message = self.widget.get_text()
        oldFailMessage = self.getFailureMessage(self.nofFailedTests + 1)
        newFailMessage = self.getFailureMessage(self.nofFailedTests)
        message = message.replace(oldFailMessage, newFailMessage)
        guilog.info("Progress bar detected save, new text is '" + message + "'")
        self.widget.set_text(message)

class ClassificationTree(seqdict):
    def addClassification(self, path):
        prevElement = None
        for element in path:
            if not self.has_key(element):
                self[element] = []
            if prevElement and element not in self[prevElement]:
                self[prevElement].append(element)
            prevElement = element
            
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
    def shouldShowCurrent(self):
        return self.dynamic
    def createView(self):
        self.treeView = gtk.TreeView(self.treeModel)
        selection = self.treeView.get_selection()
        selection.set_mode(gtk.SELECTION_MULTIPLE)
        selection.set_select_function(self.canSelect)
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
    def canSelect(self, path):
        pathIter = self.treeModel.get_iter(path)
        return self.treeModel.get_value(pathIter, 2)
    def addSuites(self, suites):
        if self.dynamic:
            for suite in suites:
                for test in suite.testCaseList():
                    self.insertTest(test, test.state)
    def selectionChanged(self, selection):
        # For each selected row, select the corresponding rows in the test treeview
        tests = []
        selection.selected_foreach(self.selectCorrespondingTests, tests)
        self.notify("SetTestSelection", tests)
    def selectCorrespondingTests(self, treemodel, path, iter, tests , *args):
        guilog.info("Selecting all " + str(treemodel.get_value(iter, 1)) + " tests in category " + treemodel.get_value(iter, 0))
        tests += treemodel.get_value(iter, 5)
    def findTestIterators(self, test):
        return self.classifications.get(test, [])
    def getCategoryDescription(self, state, categoryName=None):
        if not categoryName:
            categoryName = state.category
        briefDesc, fullDesc = state.categoryDescriptions.get(categoryName, (categoryName, categoryName))
        return briefDesc.replace("_", " ").capitalize()
    def getClassifiers(self, state):
        classifiers = ClassificationTree()
        catDesc = self.getCategoryDescription(state)
        if not state.isComplete() or not state.hasFailed():
            classifiers.addClassification([ catDesc ])
            return classifiers

        if not state.isSaveable(): # If it's not saveable, don't classify it by the files
            overall, details = state.getTypeBreakdown()
            classifiers.addClassification([ "Failed", catDesc, details ])
            return classifiers

        for fileComp in state.getComparisons():
            classifiers.addClassification(self.getFileClassification(fileComp, state))

        return classifiers
    def getFileClassification(self, fileComp, state):
        summary = fileComp.getSummary(includeNumbers=False)
        if fileComp.getType() == "failure":
            return [ "Failed", "Differences", summary ]
        else:
            return [ "Failed", "Performance differences", self.getCategoryDescription(state, summary) ]
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
        self.classifications[test] = []
        classifiers = self.getClassifiers(state)
        nodeClassifier = classifiers.keys()[0]
        self.addTestForNode(test, state, nodeClassifier, classifiers)
        self.notify("Visibility", [ test ], self.shouldBeVisible(test))

    def addTestForNode(self, test, state, nodeClassifier, classifiers, parentIter=None):
        nodeIter = self.findIter(nodeClassifier, parentIter)
        if nodeIter:
            self.insertTestAtIter(nodeIter, test, state.category)
        else:
            nodeIter = self.addNewIter(nodeClassifier, parentIter, test, state.category)

        self.classifications[test].append(nodeIter)
        for subNodeClassifier in classifiers[nodeClassifier]:
            self.addTestForNode(test, state, subNodeClassifier, classifiers, nodeIter)
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
        iter = self.treeModel.iter_children(startIter)
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
        self.insertTest(test, state)
        self.contentsChanged()

    def shouldBeVisible(self, test):
        for nodeIter in self.findTestIterators(test):
            if self.treeModel.iter_has_child(nodeIter):
                continue # ignore the parent nodes where visibility is concerned
            visible = self.treeModel.get_value(nodeIter, 2)
            if visible:
                return True
        return False

    def describe(self):
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

        changedTests = []
        for test in self.treeModel.get_value(iter, 5):
            if self.shouldBeVisible(test) == newValue:
                changedTests.append(test)
        self.notify("Visibility", changedTests, newValue)


# Class for importing self tests
class ImportTestCase(guiplugins.ImportTestCase):
    def addDefinitionFileOption(self):
        guiplugins.ImportTestCase.addDefinitionFileOption(self)
        self.addSwitch("GUI", "Use TextTest GUI", 1)
        self.addSwitch("sGUI", "Use TextTest Static GUI", 0)
    def getOptions(self, suite):
        options = guiplugins.ImportTestCase.getOptions(self, suite)
        if self.optionGroup.getSwitchValue("sGUI"):
            options += " -gx"
        elif self.optionGroup.getSwitchValue("GUI"):
            options += " -g"
        return options
