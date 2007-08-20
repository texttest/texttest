#!/usr/bin/env python

# GUI for TextTest written with PyGTK
# First make sure we can import the GUI modules: if we can't, throw appropriate exceptions

import texttest_version

def raiseException(msg):
    from plugins import TextTestError
    raise TextTestError, "Could not start TextTest " + texttest_version.version + " GUI due to PyGTK GUI library problems :\n" + msg

try:
    import gtk
except:
    raiseException("Unable to import module 'gtk'")

pygtkVersion = gtk.pygtk_version
requiredPygtkVersion = texttest_version.required_pygtk_version
if pygtkVersion < requiredPygtkVersion:
    raiseException("TextTest " + texttest_version.version + " GUI requires at least PyGTK " +
                   ".".join(map(lambda l: str(l), requiredPygtkVersion)) + ": found version " +
                   ".".join(map(lambda l: str(l), pygtkVersion)))

try:
    import gobject
except:
    raiseException("Unable to import module 'gobject'")

import guiplugins, plugins, os, sys, operator
from gtkusecase import ScriptEngine, TreeModelIndexer, RadioGroupIndexer
from ndict import seqdict
from respond import Responder
from copy import copy
from glob import glob

import guidialogs
from guidialogs import showErrorDialog, showWarningDialog, showInformationDialog

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

class PluginHandler:
    def __init__(self):
        self.modules = []
    def getInstance(self, className, *args):
        dotPos = className.find(".")
        if dotPos == -1:
            for module in self.modules:
                command = "from " + module + " import " + className + " as realClassName"
                try:
                    exec command
                    guilog.info("Loaded class '" + className + "' from module '" + module + "'")
                except ImportError:
                    continue
            
                actionObject = self.tryMakeObject(realClassName, *args)
                if actionObject:
                    return actionObject
        else:
            module = className[0:dotPos]
            theClassName = className[dotPos + 1:]
            exec "from " + module + " import " + theClassName + " as realClassName"
            return self.tryMakeObject(realClassName, *args)

        return self.tryMakeObject(className, *args)
    def tryMakeObject(self, className, *args):
        try:
            return className(*args)
        except:
            # If some invalid interactive action is provided, need to know which
            plugins.printWarning("Problem with class " + className.__name__ + ", ignoring...")
            plugins.printException()

pluginHandler = PluginHandler()

# base class for all "GUI" classes which manage parts of the display
class SubGUI(plugins.Observable):
    def __init__(self):
        plugins.Observable.__init__(self)
        self.active = False
        self.widget = None
    def setActive(self, newValue):
        if self.shouldShow():
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

    def shouldShow(self):
        return True # should this be shown/created at all this run

    def shouldShowCurrent(self, *args):
        return True # should this be shown or hidden in the current context?

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

    def showPopupMenu(self, treeview, event):
        if event.button == 3 and len(self.popupGUI.widget.get_children()) > 0:
            time = event.time
            pathInfo = treeview.get_path_at_pos(int(event.x), int(event.y))
            selection = treeview.get_selection()
            selectedRows = selection.get_selected_rows()
            # If they didnt right click on a currently selected
            # row, change the selection
            if pathInfo is not None:
                if pathInfo[0] not in selectedRows[1]:
                    selection.unselect_all()
                    selection.select_path(pathInfo[0])
                path, col, cellx, celly = pathInfo
                treeview.grab_focus()
                self.popupGUI.widget.popup(None, None, None, event.button, time)
                return True

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
    
    def shouldShowCurrent(self, *args):
        for subgui in self.subguis:
            if not subgui.shouldShowCurrent(*args):
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
            self.label.set_markup(plugins.convertForMarkup(message))
            self.contentsChanged()

    def createView(self):
        hbox = gtk.HBox()
        self.label = gtk.Label()
        self.label.set_use_markup(True)
        self.label.set_markup(plugins.convertForMarkup("TextTest started at " + plugins.localtime() + "."))
        hbox.pack_start(self.label, expand=False, fill=False)
        imageDir = plugins.installationDir("images")
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
    def notifyActionStart(self, *args):
        # To make it possible to have an while-events-process loop
        # to update the GUI during actions, we need to make sure the idle
        # process isn't run. We hence remove that for a while here ...
        if self.sourceId > 0:
            gobject.source_remove(self.sourceId)
    def notifyActionStop(self, *args):
        # Activate idle function again, see comment in notifyActionStart
        if self.sourceId > 0:
            self.enableHandler()
            
    def enableHandler(self):
        self.sourceId = self._enableHandler()

    def _enableHandler(self):
        return plugins.Observable.threadedNotificationHandler.enablePoll(gobject.idle_add)
    
class TextTestGUI(Responder, plugins.Observable):
    EXIT_NOTIFIED = 1
    COMPLETION_NOTIFIED = 2
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
        self.menuBarGUI, self.toolBarGUI, testPopupGUI, testFilePopupGUI = self.createMenuAndToolBarGUIs()
        self.testColumnGUI = TestColumnGUI(self.dynamic)
        self.testTreeGUI = TestTreeGUI(self.dynamic, testPopupGUI, self.testColumnGUI)
        self.testFileGUI = TestFileGUI(self.dynamic, testFilePopupGUI)
        self.actionTabGUIs = self.createActionTabGUIs()
        self.notebookGUIs, rightWindowGUI = self.createRightWindowGUI()
        self.shortcutBarGUI = ShortcutBarGUI()
        self.topWindowGUI = self.createTopWindowGUI(rightWindowGUI)
        self.exitStatus = 0
        if not self.dynamic:
            self.exitStatus |= self.COMPLETION_NOTIFIED # no tests to wait for...

        self.setUpObservers()
    def getTestTreeObservers(self):
        return [ self.testColumnGUI, self.testFileGUI, self.textInfoGUI ] + self.intvActions + self.notebookGUIs
    def getLifecycleObservers(self):
        # only the things that want to know about lifecycle changes irrespective of what's selected,
        # otherwise we go via the test tree. Include add/remove as lifecycle
        return [ self.testColumnGUI, self.testTreeGUI, self.progressBarGUI, self.progressMonitor, statusMonitor ] 
    def getActionObservers(self, action):
        if str(action.__class__).find("Reset") != -1:
            # It's such a hack, but so is this action...
            return [ statusMonitor ] + self.actionTabGUIs
        else:
            # These actions might change the tree view selection or the status bar, need to observe them
            clipboardObservers = filter(lambda action: hasattr(action, "notifyClipboard"), self.intvActions)
            return clipboardObservers + [ self.testTreeGUI, self.testFileGUI, statusMonitor, self.idleManager, self.topWindowGUI ]
    def getFileViewObservers(self):
        # We should potentially let other GUIs be file observers too ...
        return filter(self.isFileObserver, self.intvActions)
    def isFileObserver(self, action):
        return hasattr(action, "notifyNewFileSelection") or hasattr(action, "notifyViewFile")
    def getExitObservers(self):
        exitActions = filter(lambda action: hasattr(action, "notifyExit"), self.intvActions)
        return exitActions + [ guiplugins.processTerminationMonitor, self ]
    def getTestColumnObservers(self):
        return [ self.testTreeGUI, statusMonitor, self.idleManager ]
    def getHideableGUIs(self):
        return [ self.toolBarGUI, self.shortcutBarGUI, statusMonitor ]
    def getAddSuitesObservers(self):
        return [ guiConfig, self.testColumnGUI, self.testTreeGUI, self.progressMonitor, \
                 self.appFileGUI, self.progressBarGUI, self.topWindowGUI ] + self.intvActions

    def setUpObservers(self):    
        for observer in self.getTestTreeObservers():
            self.testTreeGUI.addObserver(observer)

        for observer in self.getTestColumnObservers():
            self.testColumnGUI.addObserver(observer)

        for observer in self.getFileViewObservers():
            self.testFileGUI.addObserver(observer)
            self.appFileGUI.addObserver(observer)
            
        # watch for category selections
        self.progressMonitor.addObserver(self.testTreeGUI)
        guiplugins.processTerminationMonitor.addObserver(statusMonitor)
        for observer in self.getLifecycleObservers():        
            self.addObserver(observer) # forwarding of test observer mechanism

        for action in self.intvActions:
            for observer in self.getActionObservers(action):
                action.addObserver(observer)

        # Action-based GUIs should observe their actions
        for actionBasedGUI in self.defaultActionGUIs + self.buttonBarGUIs + self.actionTabGUIs:
            actionBasedGUI.action.addObserver(actionBasedGUI)

        for observer in self.getHideableGUIs():
            self.menuBarGUI.addObserver(observer)

        for observer in self.getExitObservers():
            self.topWindowGUI.addObserver(observer)
    
    def readGtkRCFile(self):
        configDir = plugins.getPersonalConfigDir()
        if not configDir:
            return

        file = os.path.join(configDir, ".gtkrc-2.0")
        if os.path.isfile(file):
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
    def createTopWindowGUI(self, rightWindowGUI):
        mainWindowGUI = PaneGUI(self.testTreeGUI, rightWindowGUI, horizontal=True)
        parts = [ self.menuBarGUI, self.toolBarGUI, mainWindowGUI, self.shortcutBarGUI, statusMonitor ]
        boxGUI = BoxGUI(parts, horizontal=False)
        return TopWindowGUI(boxGUI, self.dynamic)
    def createMenuAndToolBarGUIs(self):
        uiManager = gtk.UIManager()
        menu = MenuBarGUI(self.dynamic, uiManager, self.defaultActionGUIs)
        toolbar = ToolBarGUI(uiManager, self.defaultActionGUIs, self.progressBarGUI)
        testPopup = TestPopupMenuGUI(uiManager, self.defaultActionGUIs)
        testFilePopup = TestFilePopupMenuGUI(uiManager, self.defaultActionGUIs)
        return menu, toolbar, testPopup, testFilePopup
    def createActionGUIs(self):
        defaultGUIs, buttonGUIs = [], []
        for action in self.intvActions:
            if action.inMenuOrToolBar():
                defaultGUIs.append(DefaultActionGUI(action))
            elif action.inButtonBar():
                buttonGUIs.append(ButtonActionGUI(action))

        return defaultGUIs, buttonGUIs

    def createActionGUIForTab(self, action):
        if action.canPerform():
            return ButtonActionGUI(action, fromTab=True)
    def createActionTabGUIs(self):
        actionTabGUIs = []
        for action in self.intvActions:
            actionGUI = self.createActionGUIForTab(action)
            for optionGroup in action.getOptionGroups():
                if action.createOptionGroupTab(optionGroup):
                    actionTabGUIs.append(ActionTabGUI(optionGroup, action, actionGUI))
        return actionTabGUIs

    def createRightWindowGUI(self):
        tabGUIs = [ self.appFileGUI, self.textInfoGUI, self.progressMonitor ] + self.actionTabGUIs
        buttonBarGUI = BoxGUI(self.buttonBarGUIs, horizontal=True, reversed=True)
        topTestViewGUI = BoxGUI([ self.testFileGUI, buttonBarGUI ], horizontal=False)

        tabGUIs = filter(lambda tabGUI: tabGUI.shouldShow(), tabGUIs)
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
        return tabInfo
    def notifyLifecycleChange(self, test, state, changeDesc):
        self.notify("LifecycleChange", test, state, changeDesc)
    def notifyDescriptionChange(self, test):
        self.notify("DescriptionChange", test)
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
        self.exitStatus |= self.COMPLETION_NOTIFIED
        if self.exitStatus & self.EXIT_NOTIFIED:
            self.terminate()
    def notifyExit(self, *args):
        self.exitStatus |= self.EXIT_NOTIFIED        
        if self.exitStatus & self.COMPLETION_NOTIFIED:
            self.terminate()
        else:
            self.notify("Status", "Waiting for all tests to terminate ...")
    def terminate(self):
        self.idleManager.notifyActionStart() # disable idle handlers
        self.notify("Status", "Removing all temporary files ...")
        self.notify("ActionProgress")
        self.topWindowGUI.removeWriteDirsAndWindow()
        gtk.main_quit()

class TopWindowGUI(ContainerGUI):
    def __init__(self, contentGUI, dynamic):
        ContainerGUI.__init__(self, [ contentGUI ])
        self.dynamic = dynamic
        self.topWindow = None
        self.allApps = []
        self.windowSizeDescriptor = ""
    def addSuites(self, suites):
        for suite in suites:
            if not suite.app in self.allApps:
                self.allApps.append(suite.app)
    def allAppNames(self):
        allNames = []
        for app in self.allApps:
            if not app.fullName in allNames:
                allNames.append(app.fullName)
        return allNames
    def createView(self):
        # Create toplevel window to show it all.
        self.topWindow = gtk.Window(gtk.WINDOW_TOPLEVEL)        
        try:
            import stockitems
            stockitems.register(self.topWindow)
        except:
            plugins.printWarning("Failed to register texttest stock icons.")
            plugins.printException()
        global globalTopWindow
        globalTopWindow = self.topWindow
        self.topWindow.set_icon_from_file(self.getIcon())
        if self.dynamic:
            self.topWindow.set_title("TextTest dynamic GUI (tests started at " + plugins.startTimeString() + ")")
        else:
            self.topWindow.set_title("TextTest static GUI : management of tests for " + \
                                     ",".join(self.allAppNames()))
            
        self.topWindow.add(self.subguis[0].createView())
        self.topWindow.show()
        scriptEngine.connect("close window", "delete_event", self.topWindow, self.notifyExit)
        self.windowSizeDescriptor = self.adjustSize()
        return self.topWindow

    def getIcon(self):
        imageDir = plugins.installationDir("images")
        if self.dynamic:
            return os.path.join(imageDir, "texttest-icon-dynamic.jpg")
        else:
            return os.path.join(imageDir, "texttest-icon-static.jpg")
    def writeSeparator(self):
        pass # Don't bother, we're at the top
    def describe(self):
        guilog.info("Top Window title is " + self.topWindow.get_title())
        guilog.info("Default widget is " + str(self.topWindow.get_focus().__class__))
        guilog.info(self.windowSizeDescriptor)
    def notifyExit(self, *args):
        self.notify("Exit")
    def removeWriteDirsAndWindow(self):
        for app in self.allApps:
            app.removeWriteDirectory()
        self.topWindow.destroy()
    def notifyError(self, message):
        showErrorDialog(message, self.topWindow)
    def notifyWarning(self, message):
        showWarningDialog(message, self.topWindow)
    def notifyInformation(self, message):
        showInformationDialog(message, self.topWindow)
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
        self.diag = plugins.getDiagnostics("Menu Bar")
    def setActive(self, active):
        SubGUI.setActive(self, active)
        self.widget.get_toplevel().add_accel_group(self.uiManager.get_accel_group())
        if self.shouldHide("menubar"):
            self.hide(self.widget, "Menubar")
        for actionGUI in self.actionGUIs:
            actionGUI.setActive(active)
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
    def getMenuNames(self):
        return [ "file", "edit", "view", "actions", "site", "reorder", "help" ] + guiplugins.interactiveActionHandler.extraMenus
    def createView(self):
        # Initialize
        for menuName in self.getMenuNames():
            realMenuName = menuName
            if not menuName.isupper():
                realMenuName = menuName.capitalize()
            self.actionGroup.add_action(gtk.Action(menuName + "menu", "_" + realMenuName, None, None))
        self.createToggleActions()
        for actionGUI in self.actionGUIs:
            actionGUI.addToGroups(self.actionGroup, self.uiManager.get_accel_group())
            
        for file in self.getGUIDescriptionFileNames():
            try:
                self.diag.info("Reading UI from file " + file)
                self.uiManager.add_ui_from_file(file)
            except Exception, e: 
                raise plugins.TextTestError, "Failed to parse GUI description file '" + file + "': " + str(e)
        self.uiManager.ensure_update()
        self.widget = self.uiManager.get_widget("/MainMenuBar")
        return self.widget
    def getGUIDescriptionFileNames(self):
        return self.getDescriptionFilesInDir(plugins.installationDir("layout")) + \
               self.getDescriptionFilesInDir(plugins.getPersonalConfigDir())
    def getDescriptionFilesInDir(self, layoutDir):
        allFiles = os.path.join(layoutDir, "*_gui.xml")
        self.diag.info("All description files : " + repr(allFiles))
        # Pick up all GUI descriptions corresponding to modules we've loaded
        loadFiles = filter(self.shouldLoad, glob(allFiles))
        loadFiles.sort(self.cmpDescFiles)
        return loadFiles
    def cmpDescFiles(self, file1, file2):
        base1 = os.path.basename(file1)
        base2 = os.path.basename(file2)
        default1 = base1.startswith("default")
        default2 = base2.startswith("default")
        if default1 != default2:
            return cmp(default2, default1)
        partCount1 = base1.count("_")
        partCount2 = base2.count("_")
        if partCount1 != partCount2:
            return cmp(partCount1, partCount2) # less _ implies read first (not mode-specific)
        return cmp(base2, base1) # something deterministic, just to make sure it's the same for everyone
    def shouldLoad(self, fileName):
        parts = os.path.basename(fileName).split("_")
        moduleName = parts[0]
        mode = parts[1]
        return sys.modules.has_key(moduleName) and self.correctMode(mode)
    def correctMode(self, mode):
        if mode == "static":
            return not self.dynamic
        elif mode == "dynamic":
            return self.dynamic
        else:
            return True
    def describe(self):
        for toggleAction in self.toggleActions:
            guilog.info("Viewing toggle action with title '" + toggleAction.get_property("label") + "'")
        for actionGUI in self.actionGUIs:
            actionGUI.describe()

class ToolBarGUI(ContainerGUI):
    def __init__(self, uiManager, actionGUIs, subgui):
        ContainerGUI.__init__(self, [ subgui ])
        self.uiManager = uiManager
        self.actionGUIs = filter(lambda a: a.action.inMenuOrToolBar(), actionGUIs)
    def getWidgetName(self):
        return "_Toolbar"
    def ensureVisible(self, toolbar):
        for item in toolbar.get_children(): 
            item.set_is_important(True) # Or newly added children without stock ids won't be visible in gtk.TOOLBAR_BOTH_HORIZ style
    def createView(self):
        self.uiManager.ensure_update()
        toolbar = self.uiManager.get_widget("/MainToolBar")
        self.ensureVisible(toolbar)
  
        self.widget = gtk.HandleBox()
        self.widget.add(toolbar)
        toolbar.set_orientation(gtk.ORIENTATION_HORIZONTAL)
        progressBarGUI = self.subguis[0]
        if progressBarGUI.shouldShow():
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
    def createView(self):
        self.uiManager.ensure_update()
        self.widget = self.uiManager.get_widget("/TestPopupMenu")
        self.widget.show_all()
        return self.widget

class TestFilePopupMenuGUI(SubGUI):
    def __init__(self, uiManager, actionGUIs):
        SubGUI.__init__(self)
        self.uiManager = uiManager
        self.actionGUIs = actionGUIs
        self.actionGroup = uiManager.get_action_groups()[0]
    def getWidgetName(self):
        return "_TestFilePopupMenu"
    def createView(self):
        self.uiManager.ensure_update()
        self.widget = self.uiManager.get_widget("/TestFilePopupMenu")
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
        self.allSuites = []
    def addSuites(self, suites):
        size = sum([ suite.size() for suite in suites ])
        self.totalNofTests += size
        self.totalNofTestsShown += size
        for suite in suites:
            if not suite in self.allSuites:
                self.allSuites.append(suite)
    def createView(self):
        testRenderer = gtk.CellRendererText()
        self.column = gtk.TreeViewColumn(self.getTitle(), testRenderer, text=0, background=1)        
        self.column.set_cell_data_func(testRenderer, renderSuitesBold)
        if not self.dynamic:
            self.column.set_clickable(True)
            scriptEngine.connect("toggle test sorting order", "clicked", self.column, self.columnClicked)
        if guiConfig.getValue("auto_sort_test_suites") == 1:
            guilog.info("Initially sorting tests in alphabetical order.")
            self.column.set_sort_indicator(True)
            self.column.set_sort_order(gtk.SORT_ASCENDING)
        elif guiConfig.getValue("auto_sort_test_suites") == -1:
            guilog.info("Initially sorting tests in descending alphabetical order.")
            self.column.set_sort_indicator(True)
            self.column.set_sort_order(gtk.SORT_DESCENDING)                
        return self.column
    def columnClicked(self, treeviewcolumn):
        if not self.column.get_sort_indicator():
            self.column.set_sort_indicator(True)
            self.column.set_sort_order(gtk.SORT_ASCENDING)
            order = 1
        else:
            order = self.column.get_sort_order()
            if order == gtk.SORT_ASCENDING:
                self.column.set_sort_order(gtk.SORT_DESCENDING)
                order = -1
            else:
                self.column.set_sort_indicator(False)
                order = 0
        
        self.notify("ActionStart", "")
        self.setSortingOrder(order)
        if order == 1:
            self.notify("Status", "Tests sorted in alphabetical order.")
        elif order == -1:
            self.notify("Status", "Tests sorted in descending alphabetical order.")
        else:
            self.notify("Status", "Tests sorted according to testsuite file.")
        self.notify("RefreshTestSelection")
        self.notify("ActionStop", "")
    def setSortingOrder(self, order, suite = None):
        if not suite:
            for suite in self.allSuites:
                self.setSortingOrder(order, suite)
        else:
            self.notify("Status", "Sorting suite " + suite.name + " ...")
            self.notify("ActionProgress")
            suite.autoSortOrder = order
            suite.updateOrder(order == 0) # Re-read testsuite files if order is 0 ...
            for test in suite.testcases:
                if test.classId() == "test-suite":
                    self.setSortingOrder(order, test)
    def getTitle(self):
        title = "Tests: "
        if self.nofSelectedTests == self.totalNofTests:
            title += "All " + str(self.totalNofTests) + " selected"
        else:
            title += str(self.nofSelectedTests) + "/" + str(self.totalNofTests) + " selected"
        if self.dynamic:
            if self.totalNofTestsShown == self.totalNofTests:
                title += ", none hidden"
            elif self.totalNofTestsShown == 0:
                title += ", all hidden"
            else:
                title += ", " + str(self.totalNofTests - self.totalNofTestsShown) + " hidden"
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
        self.selectedTests = []
        self.dynamic = dynamic
        self.collapseStatic = False
        self.successPerSuite = {} # map from suite to number succeeded
        self.collapsedRows = {}
        self.filteredModel = None
        self.treeView = None
        self.diag = plugins.getDiagnostics("Test Tree")
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
        if not self.dynamic:
            self.collapseStatic = guiConfig.getValue("static_collapse_suites")
        totalSize = 0
        for suite in suites:
            size = suite.size()
            totalSize += size
            if not self.dynamic or size > 0:
                self.addSuiteWithParent(suite, None)
        if self.dynamic and totalSize == 1:
            self.selectedTests = reduce(operator.add, [ suite.testCaseList() for suite in suites ])
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
        self.selection.connect("changed", self.userChangedSelection)
        self.performStoredSelection()

        self.treeView.show()
        if self.dynamic:
            self.filteredModel.connect('row-inserted', self.rowInserted)
            self.filteredModel.refilter()

        self.popupGUI.createView()
        return self.addScrollBars(self.treeView)
    def performStoredSelection(self):
        if len(self.selectedTests) > 0:
            newSelection = self.getSelected()
            if newSelection != self.selectedTests:
                actualSelection = self.selectTestRows(self.selectedTests)
                self.notify("NewTestSelection", actualSelection, True)        
    def describeTree(self, *args):
        SubGUI.contentsChanged(self) # don't describe the column too...

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
        newSelection = self.getSelected()
        if newSelection != self.selectedTests:
            self.diag.info("Selection now changed to " + repr(newSelection))
            self.selectedTests = newSelection
            self.notify("NewTestSelection", newSelection, direct)
    def notifyRefreshTestSelection(self):
        # The selection hasn't changed, but we want to e.g.
        # recalculate the action sensitiveness.
        self.notify("NewTestSelection", self.selectedTests, True)
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
        guilog.info("Marking " + str(self.selection.count_selected_rows()) + " tests as selected")
        self.selectionChanged(direct=False) # Here it's been set via some indirect mechanism, might want to behave differently 
    def selectTestRows(self, selTests, selectCollapsed=True):
        self.selecting = True # don't respond to each individual programmatic change here
        self.selection.unselect_all()
        treeView = self.selection.get_tree_view()
        firstPath = None
        actuallySelected = []
        for test in selTests:
            iter = self.findIter(test)
            if not iter:
                continue
            actuallySelected.append(test)
            path = self.filteredModel.get_path(iter) 
            if not firstPath:
                firstPath = path
            if selectCollapsed:
                treeView.expand_to_path(path)
            self.selection.select_iter(iter)
        treeView.grab_focus()
        if firstPath is not None and treeView.get_property("visible"):
            cellArea = treeView.get_cell_area(firstPath, treeView.get_columns()[0])
            visibleArea = treeView.get_visible_rect()
            if cellArea.y < 0 or cellArea.y > visibleArea.height:
                treeView.scroll_to_cell(firstPath, use_align=True, row_align=0.1)
        self.selecting = False
        return actuallySelected
    def expandLevel(self, view, iter, recursive=True):
        # Make sure expanding expands everything, better than just one level as default...
        # Avoid using view.expand_row(path, open_all=True), as the open_all flag
        # doesn't seem to send the correct 'row-expanded' signal for all rows ...
        # This way, the signals are generated one at a time and we call back into here.
        model = view.get_model()
        while (iter != None):
            if recursive:
                view.expand_row(model.get_path(iter), open_all=False)
             
            iter = view.get_model().iter_next(iter)
    def notifyLifecycleChange(self, test, state, changeDesc):
        iter = self.itermap[test]
        self.updateStateInModel(test, iter, state)
        self.diagnoseTest(test, iter)

        # We don't want to affect the success count
        # when we unmark a previously successful test ...
        if state.hasSucceeded() and changeDesc != "unmarked":
            self.updateSuiteSuccess(test.parent)
        if test in self.selectedTests:
            self.notify("LifecycleChange", test, state, changeDesc)
    def notifyFileChange(self, test):
        if test in self.selectedTests:
            self.notify("FileChange", test)
    def notifyDescriptionChange(self, test):
        if test in self.selectedTests:
            self.notify("DescriptionChange", test)
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
        self.addSuiteWithParent(test, suiteIter, followIter)
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
        self.selecting = True
        self.selection.unselect_all()
        for test in suite.testcases:
            self.removeTest(test)
        for test in suite.testcases:
            self.addTest(test)
        self.expandRow(self.findIter(suite), True)
        self.selectTestRows(self.selectedTests) # don't notify observers as nothing has changed except order
    def notifyVisibility(self, tests, newValue):
        if not newValue:
            self.selecting = True
        changedTests = []
        for test in tests:
            if self.updateVisibilityInModel(test, newValue):
                changedTests.append(test)

        self.selecting = False
        if len(changedTests) > 0:
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
            self.performStoredSelection() # if we've stored a selection from previously, remake it.
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
    def notifySensitivity(self, newValue):
        actionOrButton = self.actionOrButton()
        if not actionOrButton:
            return
        oldValue = actionOrButton.get_property("sensitive")
        actionOrButton.set_property("sensitive", newValue)
        if self.active and oldValue != newValue:
            guilog.info("Setting sensitivity of action '" + self.action.getTitle(includeMnemonics=True) + "' to " + repr(newValue))
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
        dialogType = self.action.getDialogType()
        if dialogType is not None:
            if dialogType:
                dialog = pluginHandler.getInstance(dialogType, globalTopWindow,
                                                   self._runInteractive, self._dontRun, self.action)
                dialog.run()
            else:
                self._runInteractive()
    def _dontRun(self):
        statusMonitor.notifyStatus("Action cancelled.")
    def _runInteractive(self):
        try:
            self.action.startPerform()
            resultDialogType = self.action.getResultDialogType()
            if resultDialogType:
                resultDialog = pluginHandler.getInstance(resultDialogType, globalTopWindow, None, self.action)
                resultDialog.run()
        finally:
            self.action.endPerform()
           
class DefaultActionGUI(ActionGUI):
    def __init__(self, action):
        ActionGUI.__init__(self, action)
        self.accelerator = None
        title = self.action.getTitle(includeMnemonics=True)
        actionName = self.action.getTitle(includeMnemonics=False)
        self.gtkAction = gtk.Action(actionName, title, \
                                    self.action.getTooltip(), self.getStockId())
        scriptEngine.connect(self.action.getScriptTitle(False), "activate", self.gtkAction, self.runInteractive)
        if not action.isActiveOnCurrent():
            self.gtkAction.set_property("sensitive", False)
            
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
        self.createButton()
        if not self.action.isActiveOnCurrent():
            self.button.set_property("sensitive", False)
        return self.button
    def createButton(self):
        self.button = gtk.Button(self.action.getTitle(includeMnemonics=True))
        self.tooltips.set_tip(self.button, self.scriptTitle)
        scriptEngine.connect(self.scriptTitle, "clicked", self.button, self.runInteractive)
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

class ComboBoxListFinder:
    def __init__(self, combobox):
        self.model = combobox.get_model()
        self.textColumn = combobox.get_text_column()
    def __call__(self):
        entries = []
        self.model.foreach(self.getText, entries)
        return entries
    def getText(self, model, path, iter, entries):
        text = self.model.get_value(iter, self.textColumn)
        entries.append(text)
        
class ActionTabGUI(SubGUI):
    def __init__(self, optionGroup, action, buttonGUI):
        SubGUI.__init__(self)
        self.optionGroup = optionGroup
        self.buttonGUI = buttonGUI
        self.action = action
        self.vbox = None
        self.diag = plugins.getDiagnostics("Action Tabs")
        self.sensitive = action.isActiveOnCurrent()
        self.diag.info("Creating action tab for " + self.getTabTitle() + ", sensitive " + repr(self.sensitive))
        self.tooltips = gtk.Tooltips()
    def getGroupTabTitle(self):
        return self.action.getGroupTabTitle()
    def getTabTitle(self):
        return self.optionGroup.name
    def shouldShowCurrent(self, *args):
        return self.sensitive
    def createView(self):
        return self.addScrollBars(self.createVBox())
    def notifySensitivity(self, newValue):
        self.diag.info("Sensitivity of " + self.getTabTitle() + " changed to " + repr(newValue))
        self.sensitive = newValue
    def notifyReset(self):
        self.optionGroup.reset()
        self.contentsChanged()
    def notifyUpdateOptions(self):
        self.contentsChanged()
    def notifyAddOptions(self):
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
            button = self.buttonGUI.createButton()
            buttonbox = gtk.HBox()
            buttonbox.pack_start(button, expand=True, fill=False)
            buttonbox.show()
            self.vbox.pack_start(buttonbox, expand=False, fill=False, padding=8)
        self.vbox.show()
        return self.vbox
        
    def createComboBox(self, option):
        combobox = gtk.combo_box_entry_new_text()
        entry = combobox.child
        option.setPossibleValuesMethods(combobox.append_text, ComboBoxListFinder(combobox))
        
        option.setClearMethod(combobox.get_model().clear)
        return combobox, entry

    def createOptionWidget(self, option):
        box = gtk.HBox()
        if option.inqNofValues() > 1:
            (widget, entry) = self.createComboBox(option)
            box.pack_start(widget, expand=True, fill=True)
        else:
            entry = gtk.Entry()
            box.pack_start(entry, expand=True, fill=True)
        
        if option.selectDir:
            button = gtk.Button("...")
            box.pack_start(button, expand=False, fill=False)
            scriptEngine.connect("search for directories for '" + option.name + "'",
                                 "clicked", button, self.showDirectoryChooser, None, entry, option)
        elif option.selectFile:
            button = gtk.Button("...")
            box.pack_start(button, expand=False, fill=False)
            scriptEngine.connect("search for files for '" + option.name + "'",
                                 "clicked", button, self.showFileChooser, None, entry, option)
        return (box, entry)
  
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
        if self.buttonGUI:
            scriptEngine.connect("activate from " + option.name, "activate", entry, self.buttonGUI.runInteractive)
        entry.set_text(option.getValue())
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
            for index in range(len(switch.options)):
                option = switch.options[index]
                if guiConfig.getCompositeValue("gui_entry_overrides", switch.name + option) == "1":
                    switch.setValue(index)
                radioButton = gtk.RadioButton(mainRadioButton, option)
                buttons.append(radioButton)
                scriptEngine.registerToggleButton(radioButton, "choose " + option)
                if not mainRadioButton:
                    mainRadioButton = radioButton
                if switch.defaultValue == index:
                    switch.resetMethod = radioButton.set_active
                if switch.getValue() == index:
                    radioButton.set_active(True)
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

    def showDirectoryChooser(self, widget, entry, option):
        dialog = gtk.FileChooserDialog("Select a directory",
                                       globalTopWindow,
                                       gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER,
                                       (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                        gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        self.startChooser(dialog, entry, option)

    def showFileChooser(self, widget, entry, option):
        dialog = gtk.FileChooserDialog("Select a file",
                                       globalTopWindow,
                                       gtk.FILE_CHOOSER_ACTION_OPEN,
                                       (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,                                        
                                        gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        self.startChooser(dialog, entry, option)

    def startChooser(self, dialog, entry, option):
        # Folders is a list of pairs (short name, absolute path),
        # where 'short name' means the name given in the config file, e.g.
        # 'temporary_filter_files' or 'filter_files' ...
        folders, defaultFolder = option.getDirectories()
        scriptEngine.registerOpenFileChooser(dialog, "select filter-file", "look in folder")
        scriptEngine.connect("open selected file", "response", dialog, self.respond, gtk.RESPONSE_OK, entry, folders)
        scriptEngine.connect("cancel file selection", "response", dialog, self.respond, gtk.RESPONSE_CANCEL, entry, folders)
        dialog.connect_after("selection-changed", self.selectionChanged)
        # If current entry forms a valid path, set that as default
        currPath = entry.get_text()
        currDir, currFile = os.path.split(currPath)
        if os.path.isdir(currDir):
            dialog.set_current_folder(currDir)
        elif defaultFolder and os.path.isdir(os.path.abspath(defaultFolder)):
            dialog.set_current_folder(os.path.abspath(defaultFolder))
        for i in xrange(len(folders) - 1, -1, -1):
            dialog.add_shortcut_folder(folders[i][1])
        dialog.set_default_response(gtk.RESPONSE_OK)
        dialog.show()
    def selectionChanged(self, dialog, *args):
        if dialog.get_filename():
            scriptEngine.applicationEvent("dialog to be displayed")        
    def respond(self, dialog, response, entry, folders):
        if response == gtk.RESPONSE_OK:
            entry.set_text(dialog.get_filename())
            entry.set_position(-1) # Sets position last, makes it possible to see the vital part of long paths 
        dialog.destroy()
        
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
            text += " (drop-down list containing " + repr(option.listPossibleValues()) + ")"
        return text
    
    def getSwitchDescription(self, switch):
        value = switch.getValue()
        if len(switch.options) >= 1:
            text = "Viewing radio button for switch '" + switch.name + "', options "
            text += "/".join(switch.options)
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

    def shouldShowCurrent(self, *args):
        for tabGUI in self.tabInfo.values():
            if tabGUI.shouldShowCurrent(*args):
                return True
        return False

    def createView(self):
        self.notebook = gtk.Notebook()
        for tabName, tabGUI in self.tabInfo.items():
            label = gtk.Label(tabName)
            self.diag.info("Adding page " + tabName)
            page = tabGUI.createView()
            if not tabGUI.shouldShowCurrent():
                page.hide()
            self.notebook.append_page(page, label)

        scriptEngine.monitorNotebook(self.notebook, self.scriptTitle)
        self.notebook.set_scrollable(True)
        if not self.setCurrentPage(self.currentPageName):
            self.currentPageName = self.findInitialCurrentPage()
            self.diag.info("Current page set to '" + self.currentPageName + "'")
        self.notebook.connect("switch-page", self.handlePageSwitch)
        self.notebook.show()
        return self.notebook

    def findInitialCurrentPage(self):
        for tabName, tabGUI in self.tabInfo.items():
            if tabGUI.shouldShowCurrent():
                return tabName

        return self.tabInfo.keys()[0]
            
    def handlePageSwitch(self, notebook, ptr, pageNum, *args):
        if not self.active:
            return
        newPageName = self.getPageName(pageNum)
        if newPageName == self.currentPageName:
            return
        self.currentPageName = newPageName 
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
        visibleChildren = filter(lambda child: child.get_property("visible"), self.notebook.get_children())
        return map(self.notebook.get_tab_label_text, visibleChildren)

    def hidePage(self, name):
        oldPage = self.findPage(name)
        if oldPage:
            self.diag.info("Hiding page " + name)
            oldPage.hide()

    def describe(self):
        guilog.info("Tabs showing : " + ", ".join(self.getTabNames()))

    def findFirstRemaining(self, pageNamesRemoved):
        for tabName in self.getTabNames():
            if tabName not in pageNamesRemoved:
                return tabName
    
    def showNewPages(self, *args):
        changed = False
        for name, tabGUI in self.tabInfo.items():
            page = self.findPage(name)
            if tabGUI.shouldShowCurrent(*args) and not page.get_property("visible"):
                self.diag.info("Showing page " + name)
                page.show()
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

    def findPagesToHide(self, *args):
        return filter(lambda name: not self.tabInfo[name].shouldShowCurrent(*args), self.getTabNames())
        
    def hideOldPages(self, *args):
        # Must reset the current page before removing it if we're viewing a removed page
        # otherwise we can output lots of pages we don't really look at
        pagesToHide = self.findPagesToHide(*args)
        if len(pagesToHide) == 0:
            return False

        if self.currentPageName in pagesToHide:
            newCurrentPageName = self.findFirstRemaining(pagesToHide)
            if newCurrentPageName:
                self.setCurrentPage(newCurrentPageName)
            
        # remove from the back, so we don't momentarily view them all if removing everything
        pagesToHide.reverse()
        for name in pagesToHide:
            self.hidePage(name)
        return True
    def updateCurrentPage(self, tests):
        allNames = self.getTabNames()
        for name in allNames:
            if self.tabInfo[name].forceVisible(tests):
                self.notebook.set_current_page(allNames.index(name))

    def notifyNewTestSelection(self, tests, direct):
        if not self.notebook:
            return
        self.diag.info("New selection with " + repr(tests) + ", adjusting '" + self.scriptTitle + "'")
        pagesShown = self.showNewPages()
        pagesHidden = self.hideOldPages()
        # only change pages around if a test is directly selected
        if direct: 
            self.updateCurrentPage(tests)
  
        if pagesShown or pagesHidden:
            SubGUI.contentsChanged(self) # just the tabs will do here, the rest is described by other means
    def notifyLifecycleChange(self, test, state, changeDesc):
        if not self.notebook:
            return 
        pagesShown = self.showNewPages(test, state)
        pagesHidden = self.hideOldPages(test, state)
        if pagesShown or pagesHidden:
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
    def shouldShowCurrent(self, *args):
        return len(self.text) > 0
    def getTabTitle(self):
        return "Text Info"
    def forceVisible(self, tests):
        return len(tests) == 1
    def resetText(self, state):
        self.text = ""
        if state.isComplete():
            self.text = "Test " + repr(state) + "\n"
            if len(state.freeText) == 0:
                self.text = self.text.replace(" :", "")
        self.text += str(state.freeText)
    def describe(self):
        guilog.info("---------- Text Info Window ----------")
        buffer = self.view.get_buffer()
        guilog.info(plugins.encodeToLocale(buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter()), guilog).strip())
        guilog.info("--------------------------------------")
    def notifyNewTestSelection(self, tests, direct):
        if len(tests) == 0:
            self.currentTest = None
        elif self.currentTest not in tests:
            self.currentTest = tests[0]
            self.resetText(self.currentTest.state)
            self.updateView()
    def notifyDescriptionChange(self, test):
        self.resetText(self.currentTest.state)
        self.updateView()
    def updateView(self):
        if self.view:
            self.updateViewFromText()
            self.contentsChanged()
    def notifyLifecycleChange(self, test, state, changeDesc):
        if not test is self.currentTest:
            return
        self.resetText(state)
        self.updateView()
    def createView(self):
        self.view = gtk.TextView()
        from pango import FontDescription
        self.view.modify_font(FontDescription("courier 10"))
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
        unicodeInfo = plugins.decodeText(self.text, guilog)
        return plugins.encodeToUTF(unicodeInfo, guilog)

        
class FileViewGUI(SubGUI):
    def __init__(self, dynamic, title = "", popupGUI = None):
        SubGUI.__init__(self)
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_STRING,\
                                   gobject.TYPE_PYOBJECT, gobject.TYPE_STRING)
        self.popupGUI = popupGUI
        self.dynamic = dynamic
        self.title = title
        self.selection = None
        self.nameColumn = None

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
        state = self.getState()
        self.addFilesToModel(state)
        view = gtk.TreeView(self.model)
        self.selection = view.get_selection()
        self.selection.set_mode(gtk.SELECTION_MULTIPLE)
        self.selection.set_select_function(self.canSelect)
        renderer = gtk.CellRendererText()
        self.nameColumn = gtk.TreeViewColumn(self.title, renderer, text=0, background=1)
        self.nameColumn.set_cell_data_func(renderer, renderParentsBold)
        view.append_column(self.nameColumn)
        detailsColumn = self.makeDetailsColumn(renderer)
        if detailsColumn:
            view.append_column(detailsColumn)
        view.expand_all()
        indexer = TreeModelIndexer(self.model, self.nameColumn, 0)
        self.monitorEvents(indexer)
        if self.popupGUI:
            view.connect("button_press_event", self.showPopupMenu)
            self.popupGUI.createView()

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
            self.notify("ViewFile", fileName, comparison)
        except plugins.TextTestError, e:
            showErrorDialog(str(e), globalTopWindow)

        self.selection.unselect_all()
    def notifyNewFile(self, fileName, overwrittenExisting):
        self.notify("ViewFile", fileName, None)
        if not overwrittenExisting:
            self.currentTest.refreshFiles()
            self.recreateModel(self.getState())
    def addFileToModel(self, iter, name, comp, colour):
        fciter = self.model.insert_before(iter, None)
        baseName = os.path.basename(name)
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
        FileViewGUI.__init__(self, dynamic, "Configuration Files")
        self.allApps = []
    def addSuites(self, suites):
        self.allApps = [ suite.app for suite in suites ]
    def shouldShow(self):
        return not self.dynamic
    def getGroupTabTitle(self):
        return "Config"
    def monitorEvents(self, indexer):
        scriptEngine.connect("select application file", "row_activated", self.selection.get_tree_view(), self.fileActivated, indexer)
    def addFilesToModel(self, state):
        colour = guiConfig.getCompositeValue("file_colours", "static")
        personalFiles = self.getPersonalFiles()
        importedFiles = {}
        if len(personalFiles) > 0:
            persiter = self.model.insert_before(None, None)
            self.model.set_value(persiter, 0, "Personal Files")
            for file in personalFiles:
                self.addFileToModel(persiter, file, None, colour)
                for importedFile in self.getImportedFiles(file):
                    importedFiles[importedFile] = importedFile

        for app in self.allApps:
            confiter = self.model.insert_before(None, None)
            self.model.set_value(confiter, 0, "Files for " + app.fullName)
            for file in self.getConfigFiles(app):
                self.addFileToModel(confiter, file, None, colour)
                for importedFile in self.getImportedFiles(file, app):
                    importedFiles[importedFile] = importedFile
                    
        # Handle recursive imports here ...
        
        if len(importedFiles) > 0:
            importediter = self.model.insert_before(None, None)
            self.model.set_value(importediter, 0, "Imported Files")
            sortedFiles = importedFiles.values()
            sortedFiles.sort()
            for importedFile in sortedFiles:
                self.addFileToModel(importediter, importedFile, None, colour)
                
    def getConfigFiles(self, app):
        configFiles = app.dircache.findAllFiles("config", [ app.name ])
        configFiles.sort()
        return configFiles
    def getPersonalFiles(self):
        personalDir = plugins.getPersonalConfigDir()
        if not os.path.isdir(personalDir):
            return []
        allEntries = [ os.path.join(personalDir, file) for file in os.listdir(personalDir) ]
        allFiles = filter(os.path.isfile, allEntries)
        allFiles.sort()
        return allFiles
    def getImportedFiles(self, file, app = None):
        if os.path.isfile(file):
            imports = []
            importLines = filter(lambda l: l.startswith("import_config_file"), open(file, "r").readlines())
            for line in importLines:
                try:
                    file = line.split(":")[1].strip()
                    if app:
                        file = app.configPath(file)
                    imports.append(file)
                except Exception: # App. file not found ...
                    continue
            return imports

class TestFileGUI(FileViewGUI):
    def __init__(self, dynamic, popupGUI):
        FileViewGUI.__init__(self, dynamic, "", popupGUI)
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
        if len(tests) == 0 or (not self.dynamic and len(tests) > 1): # multiple tests in static GUI result in removal
            self.currentTest = None
            return

        if len(tests) > 1 and self.currentTest in tests:
            self.setName(tests)
            if self.active:
                self.describeName()
        else:
            self.currentTest = tests[0]
            self.currentTest.refreshFiles()
            self.setName(tests)
            self.recreateModel(self.getState())
    def setName(self, tests=[]):
        self.title = self.getName(tests)
        if self.nameColumn:
            self.nameColumn.set_title(self.title)

    def getName(self, tests=[]):
        if len(tests) > 1:
            return "Sample from " + repr(len(tests)) + " tests"
        else:
            return self.currentTest.name.replace("_", "__")
    def getColour(self, name):
        return self.currentTest.getConfigValue("file_colours")[name]

    def shouldShowCurrent(self, *args):
        return self.currentTest is not None
            
    def addFilesToModel(self, state):
        if not state:
            return
        realState = state
        if state.isMarked():
            realState = state.oldState
        if realState.hasStarted():
            if hasattr(realState, "correctResults"):
                # failed on comparison
                self.addComparisonsToModel(realState)
            elif not realState.isComplete():
                self.addTmpFilesToModel(realState)
        else:
            self.addStaticFilesToModel(realState)

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
        filelist.append((self.model.get_value(iter, 2), self.model.get_value(iter, 3)))
    def getState(self):
        if self.currentTest:
            return self.currentTest.state
    def addComparisonsToModel(self, state):
        self.addComparisons(state, state.correctResults + state.changedResults, "Comparison Files")
        self.addComparisons(state, state.newResults, "New Files")
        self.addComparisons(state, state.missingResults, "Missing Files")
    def addComparisons(self, state, compList, title):
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
        self.addStandardFilesUnderIter(state, iter, filelist, fileCompMap)    
    def addStandardFilesUnderIter(self, state, iter, files, compMap = {}):
        for file in files:
            comparison = compMap.get(file)
            colour = self.getComparisonColour(state, comparison)
            self.addFileToModel(iter, file, comparison, colour)
    def getComparisonColour(self, state, fileComp):
        if not state.hasStarted():
            return self.getStaticColour()
        if not state.isComplete():
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
    def addTmpFilesToModel(self, state):
        tmpFiles = self.currentTest.listTmpFiles()
        tmpIter = self.model.insert_before(None, None)
        self.model.set_value(tmpIter, 0, "Temporary Files")
        self.addStandardFilesUnderIter(state, tmpIter, tmpFiles)
    def addStaticFilesToModel(self, state):
        stdFiles, defFiles = self.currentTest.listStandardFiles(allVersions=True)
        if self.currentTest.classId() == "test-case":
            stditer = self.model.insert_before(None, None)
            self.model.set_value(stditer, 0, "Standard Files")
            if len(stdFiles):
                self.addStandardFilesUnderIter(state, stditer, stdFiles)

        defiter = self.model.insert_before(None, None)
        self.model.set_value(defiter, 0, "Definition Files")
        self.addStandardFilesUnderIter(state, defiter, defFiles)
        self.addStaticDataFilesToModel()
    def getDisplayDataFiles(self):
        try:
            return self.currentTest.app.extraReadFiles(self.currentTest).items()
        except:
            sys.stderr.write("WARNING - ignoring exception thrown by '" + self.currentTest.getConfigValue("config_module") + \
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
        self.widget = None

    def shouldShow(self):
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
        if changeDesc == "complete":
            self.nofCompletedTests += 1
            self.resetBar()
            self.contentsChanged()
            
    def resetBar(self):
        message = self.getFractionMessage()
        fraction = float(self.nofCompletedTests) / float(self.totalNofTests)
        self.widget.set_text(message)
        self.widget.set_fraction(fraction)

    def getFractionMessage(self):
        if self.nofCompletedTests >= self.totalNofTests:
            completionTime = plugins.localtime()
            return "All " + str(self.totalNofTests) + " tests completed at " + completionTime
        else:
            return str(self.nofCompletedTests) + " of " + str(self.totalNofTests) + " tests completed"

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
        self.diag = plugins.getDiagnostics("Progress Monitor")
    def getGroupTabTitle(self):
        return "Status"
    def shouldShow(self):
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
        if state.isMarked():
            classifiers.addClassification([ catDesc, state.briefText ])
            return classifiers

        if not state.isComplete() or not state.hasFailed():
            classifiers.addClassification([ catDesc ])
            return classifiers

        if not state.isSaveable() or state.warnOnSave(): # If it's not saveable, don't classify it by the files
            overall, details = state.getTypeBreakdown()
            self.diag.info("Adding unsaveable : " + catDesc + " " + details)
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
        self.diag.info("Adding " + repr(test) + " for node " + nodeClassifier + " (" + repr(classifiers) + ")")
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

