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

import pango, guiplugins, plugins, os, sys, operator
from ndict import seqdict
from respond import Responder
from copy import copy
from glob import glob
from sets import Set
from TreeViewTooltips import TreeViewTooltips


def renderParentsBold(column, cell, model, iter):
    if model.iter_has_child(iter):
        cell.set_property('font', "bold")
    else:
        cell.set_property('font', "")

def renderSuitesBold(column, cell, model, iter):
    if model.get_value(iter, 2)[0].classId() == "test-case":
        cell.set_property('font', "")
    else:
        cell.set_property('font', "bold")

    
# base class for managing containers
class ContainerGUI(guiplugins.SubGUI):
    def __init__(self, subguis):
        guiplugins.SubGUI.__init__(self)
        self.subguis = subguis
    def forceVisible(self, rowCount):
        for subgui in self.subguis:
            if subgui.forceVisible(rowCount):
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
        guiplugins.SubGUI.setActive(self, value)
        for subgui in self.subguis:
            subgui.setActive(value)
    def contentsChanged(self):
        guiplugins.SubGUI.contentsChanged(self)
        for subgui in self.subguis:
            subgui.contentsChanged()
                    
#
# A class responsible for putting messages in the status bar.
# It is also responsible for keeping the throbber rotating
# while actions are under way.
# 
class GUIStatusMonitor(guiplugins.SubGUI):
    def __init__(self):
        guiplugins.SubGUI.__init__(self)
        self.throbber = None
        self.animation = None
        self.pixbuf = None
        self.label = None
        
    def getWidgetName(self):
        return "_Status bar"
    def describe(self):
        guilog.info("Changing GUI status to: '" + self.label.get_text() + "'")        
    def notifyActionStart(self, message="", lock = True):        
        if self.throbber:
            if self.pixbuf: # We didn't do ActionStop ...
                self.notifyActionStop()
            self.pixbuf = self.throbber.get_pixbuf()
            self.throbber.set_from_animation(self.animation)
            if lock:
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
        self.label.set_ellipsize(pango.ELLIPSIZE_END)
        # It seems difficult to say 'ellipsize when you'd otherwise need
        # to enlarge the window', so we'll have to settle for a fixed number
        # of max char's ... The current setting (90) is just a good choice
        # based on my preferred window size, on the test case I used to
        # develop this code. (since different chars have different widths,
        # the optimal number depends on the string to display) \ Mattias++
        self.label.set_max_width_chars(90)
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
    def __init__(self):
        self.sourceId = -1
        self.diag = plugins.getDiagnostics("Idle Handlers")
    def notifyActionStart(self, message="", lock=True):
        # To make it possible to have an while-events-process loop
        # to update the GUI during actions, we need to make sure the idle
        # process isn't run. We hence remove that for a while here ...
        if lock:
            self.disableHandler()
    def notifyActionProgress(self, *args):
        if self.sourceId >= 0:
            raise plugins.TextTestError, "No Action currently exists to have progress on!"

    def notifyActionStop(self, *args):
        # Activate idle function again, see comment in notifyActionStart
        self.enableHandler()
            
    def enableHandler(self):
        if self.sourceId == -1:
            self.sourceId = plugins.Observable.threadedNotificationHandler.enablePoll(gobject.idle_add)
            self.diag.info("Adding idle handler")
            
    def disableHandler(self):
        if self.sourceId >= 0:
            self.diag.info("Removing idle handler")
            gobject.source_remove(self.sourceId)
            self.sourceId = -1

    def notifyAllComplete(self):
        self.diag.info("Disabling thread-based polling")
        plugins.Observable.threadedNotificationHandler.disablePoll()
    def notifyExit(self):
        self.disableHandler()
        
    
class TextTestGUI(Responder, plugins.Observable):
    def __init__(self, optionMap, allApps):
        self.readGtkRCFiles()
        self.dynamic = not optionMap.has_key("gx")
        global guilog, guiConfig, scriptEngine
        guilog, guiConfig, scriptEngine = guiplugins.setUpGlobals(self.dynamic, allApps)
        Responder.__init__(self, optionMap)
        plugins.Observable.__init__(self)
        testCount = int(optionMap.get("count", 0))
        
        self.appFileGUI = ApplicationFileGUI(self.dynamic, allApps)
        self.textInfoGUI = TextInfoGUI()
        self.progressMonitor = TestProgressMonitor(self.dynamic, testCount)
        self.progressBarGUI = ProgressBarGUI(self.dynamic, testCount)
        self.idleManager = IdleHandlerManager()
        uiManager = gtk.UIManager()
        self.defaultActionGUIs, self.actionTabGUIs = \
                                guiplugins.interactiveActionHandler.getPluginGUIs(self.dynamic, allApps, uiManager)
        self.menuBarGUI, self.toolBarGUI, testPopupGUI, testFilePopupGUI = self.createMenuAndToolBarGUIs(allApps, uiManager)
        self.testColumnGUI = TestColumnGUI(self.dynamic, testCount)
        self.testTreeGUI = TestTreeGUI(self.dynamic, allApps, testPopupGUI, self.testColumnGUI)
        self.testFileGUI = TestFileGUI(self.dynamic, testFilePopupGUI)
        self.rightWindowGUI = self.createRightWindowGUI()
        self.shortcutBarGUI = ShortcutBarGUI()
        self.topWindowGUI = self.createTopWindowGUI(allApps)

    def getTestTreeObservers(self):
        return [ self.testColumnGUI, self.testFileGUI, self.textInfoGUI ] + self.allActionGUIs() + [ self.rightWindowGUI ]
    def allActionGUIs(self):
        return self.defaultActionGUIs + self.actionTabGUIs
    def getLifecycleObservers(self):
        # only the things that want to know about lifecycle changes irrespective of what's selected,
        # otherwise we go via the test tree. Include add/remove as lifecycle, also final completion
        return [ self.progressBarGUI, self.progressMonitor, self.testTreeGUI, 
                 statusMonitor, self.idleManager, self.topWindowGUI ]
    def getActionObservers(self):
        return [ self.testTreeGUI, self.testFileGUI, statusMonitor, self.idleManager, self.topWindowGUI ]
    def getFileViewObservers(self):
        return self.defaultActionGUIs + self.actionTabGUIs
    def isFrameworkExitObserver(self, obs):
        return (hasattr(obs, "notifyExit") or hasattr(obs, "notifyKillProcesses")) and obs is not self
    def getExitObservers(self, frameworkObservers):
        # Don't put ourselves in the observers twice or lots of weird stuff happens.
        # Important that closing the GUI is the last thing to be done, so make sure we go at the end...
        frameworkExitObservers = filter(self.isFrameworkExitObserver, frameworkObservers)
        return self.defaultActionGUIs + [ guiplugins.processMonitor, statusMonitor ] + \
               frameworkExitObservers + [ self.idleManager, self ] 
    def getTestColumnObservers(self):
        return [ self.testTreeGUI, statusMonitor, self.idleManager ]
    def getHideableGUIs(self):
        return [ self.toolBarGUI, self.shortcutBarGUI, statusMonitor ]
    def getAddSuitesObservers(self):
        return [ self.testColumnGUI ] + filter(lambda obs: hasattr(obs, "addSuites"),
                                               self.defaultActionGUIs + self.actionTabGUIs)
    def setObservers(self, frameworkObservers):
        # We don't actually have the framework observe changes here, this causes duplication. Just forward
        # them as appropriate to where they belong. This is a bit of a hack really.
        for observer in self.getTestTreeObservers():
            self.testTreeGUI.addObserver(observer)

        for observer in self.getTestColumnObservers():
            self.testColumnGUI.addObserver(observer)

        for observer in self.getFileViewObservers():
            self.testFileGUI.addObserver(observer)
            self.appFileGUI.addObserver(observer)
            
        # watch for category selections
        self.progressMonitor.addObserver(self.testTreeGUI)
        guiplugins.processMonitor.addObserver(statusMonitor)
        for observer in self.getLifecycleObservers():        
            self.addObserver(observer) # forwarding of test observer mechanism

        actionGUIs = self.allActionGUIs()
        observers = actionGUIs + self.getActionObservers()
        for actionGUI in actionGUIs:
            actionGUI.setObservers(observers)

        for observer in self.getHideableGUIs():
            self.menuBarGUI.addObserver(observer)

        for observer in self.getExitObservers(frameworkObservers):
            self.topWindowGUI.addObserver(observer)
    
    def readGtkRCFiles(self):
        self.readGtkRCFile(plugins.installationDir("layout"))
        self.readGtkRCFile(plugins.getPersonalConfigDir())

    def readGtkRCFile(self, configDir):
        if not configDir:
            return

        file = os.path.join(configDir, ".gtkrc-2.0")
        if os.path.isfile(file):
            gtk.rc_add_default_file(file)
    
    def addSuites(self, suites):
        for observer in self.getAddSuitesObservers():
            observer.addSuites(suites)
            
        self.topWindowGUI.createView()
        self.topWindowGUI.activate()
        self.idleManager.enableHandler()
        
    def shouldShrinkMainPanes(self):
        # If we maximise there is no point in banning pane shrinking: there is nothing to gain anyway and
        # it doesn't seem to work very well :)
        return not self.dynamic or guiConfig.getWindowOption("maximize")

    def createTopWindowGUI(self, allApps):
        mainWindowGUI = PaneGUI(self.testTreeGUI, self.rightWindowGUI, horizontal=True, shrink=self.shouldShrinkMainPanes())
        parts = [ self.menuBarGUI, self.toolBarGUI, mainWindowGUI, self.shortcutBarGUI, statusMonitor ]
        boxGUI = BoxGUI(parts, horizontal=False)
        return TopWindowGUI(boxGUI, self.dynamic, allApps)

    def createMenuAndToolBarGUIs(self, allApps, uiManager):
        menu = MenuBarGUI(allApps, self.dynamic, uiManager, self.allActionGUIs())
        toolbar = ToolBarGUI(uiManager, self.progressBarGUI)
        testPopup = PopupMenuGUI("TestPopupMenu", uiManager)
        testFilePopup = PopupMenuGUI("TestFilePopupMenu", uiManager)
        return menu, toolbar, testPopup, testFilePopup
    
    def createRightWindowGUI(self):
        testTab = PaneGUI(self.testFileGUI, self.textInfoGUI, horizontal=False)
        tabGUIs = [ self.appFileGUI, testTab, self.progressMonitor ] + self.actionTabGUIs
        
        tabGUIs = filter(lambda tabGUI: tabGUI.shouldShow(), tabGUIs)
        subNotebookGUIs = self.createNotebookGUIs(tabGUIs)
        return ChangeableNotebookGUI(subNotebookGUIs, self.getNotebookScriptName("Top"))
    
    def getNotebookScriptName(self, tabName):
        if tabName == "Top":
            return "view options for"
        else:
            return "view sub-options for " + tabName.lower() + " :"

    def classifyByTitle(self, tabGUIs):
        return map(lambda tabGUI: (tabGUI.getTabTitle(), tabGUI), tabGUIs)
    def getGroupTabNames(self, tabGUIs):
        tabNames = [ "Test", "Selection", "Running" ]
        for tabGUI in tabGUIs:
            tabName = tabGUI.getGroupTabTitle()
            if not tabName in tabNames:
                tabNames.append(tabName)
        return tabNames
    def createNotebookGUIs(self, tabGUIs):
        tabInfo = []
        for tabName in self.getGroupTabNames(tabGUIs):
            currTabGUIs = filter(lambda tabGUI: tabGUI.getGroupTabTitle() == tabName, tabGUIs)
            if len(currTabGUIs) > 1:
                notebookGUI = NotebookGUI(self.classifyByTitle(currTabGUIs), self.getNotebookScriptName(tabName))
                tabInfo.append((tabName, notebookGUI))
            elif len(currTabGUIs) == 1:
                tabInfo.append((tabName, currTabGUIs[0]))
        return tabInfo
    def run(self):
        gtk.main()
    def notifyExit(self):
        gtk.main_quit()
    def notifyLifecycleChange(self, test, state, changeDesc):
        self.notify("LifecycleChange", test, state, changeDesc)
    def notifyDescriptionChange(self, test):
        self.notify("DescriptionChange", test)
    def notifyFileChange(self, test):
        self.notify("FileChange", test)
    def notifyContentChange(self, *args, **kwargs):
        self.notify("ContentChange", *args, **kwargs)
    def notifyNameChange(self, *args, **kwargs):
        self.notify("NameChange", *args, **kwargs)
    def notifyStartRead(self):
        if not self.dynamic:
            self.notify("Status", "Reading tests ...")
            self.notify("ActionStart", "", False)
    def notifyAllRead(self, suites):
        if not self.dynamic:
            self.notify("Status", "Reading tests completed at " + plugins.localtime() + ".")
            self.notify("ActionStop")
        self.notify("AllRead", suites)
        if self.dynamic and len(suites) == 0:
            guilog.info("There weren't any tests to run, terminating...")
            self.topWindowGUI.forceQuit()
            
    def notifyAdd(self, *args, **kwargs):
        self.notify("Add", *args, **kwargs)
    def notifyStatus(self, *args, **kwargs):
        self.notify("Status", *args, **kwargs)
    def notifyRemove(self, test):
        self.notify("Remove", test)
    def notifyAllComplete(self):
        self.notify("AllComplete")
    
class TopWindowGUI(ContainerGUI):
    EXIT_NOTIFIED = 1
    COMPLETION_NOTIFIED = 2
    def __init__(self, contentGUI, dynamic, allApps):
        ContainerGUI.__init__(self, [ contentGUI ])
        self.dynamic = dynamic
        self.topWindow = None
        self.allApps = allApps
        self.windowSizeDescriptor = ""
        self.exitStatus = 0
        if not self.dynamic:
            self.exitStatus |= self.COMPLETION_NOTIFIED # no tests to wait for...

    def getCheckoutTitle(self):
        allCheckouts = []
        for app in self.allApps:
            checkout = app.checkout
            if checkout and not checkout in allCheckouts:
                allCheckouts.append(checkout)
        if len(allCheckouts) == 0:
            return ""
        elif len(allCheckouts) == 1:
            return " under " + allCheckouts[0]
        else:
            return " from various checkouts"
        
    def createView(self):
        # Create toplevel window to show it all.
        self.topWindow = gtk.Window(gtk.WINDOW_TOPLEVEL)        
        try:
            import stockitems
            stockitems.register(self.topWindow)
        except:
            plugins.printWarning("Failed to register texttest stock icons.")
            plugins.printException()
        self.topWindow.set_icon_from_file(self.getIcon())
        allAppNames = [ app.fullName + app.versionSuffix() for app in self.allApps ]
        appNames = ",".join(allAppNames)
        if self.dynamic:
            checkoutTitle = self.getCheckoutTitle()
            self.topWindow.set_title("TextTest dynamic GUI : testing " + appNames + checkoutTitle + \
                                     " (started at " + plugins.startTimeString() + ")")
        else:
            self.topWindow.set_title("TextTest static GUI : management of tests for " + \
                                     appNames)
            
        self.topWindow.add(self.subguis[0].createView())
        self.windowSizeDescriptor = self.adjustSize()
        self.topWindow.show()
        self.topWindow.set_default_size(-1, -1)

        self.notify("TopWindow", self.topWindow)
        scriptEngine.connect("close window", "delete_event", self.topWindow, self.notifyQuit)
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
    def forceQuit(self):
        self.exitStatus |= self.COMPLETION_NOTIFIED
        self.notifyQuit()
    def notifyAllComplete(self, *args):
        self.exitStatus |= self.COMPLETION_NOTIFIED
        if self.exitStatus & self.EXIT_NOTIFIED:
            self.terminate()
    def notifyQuit(self, *args):
        self.exitStatus |= self.EXIT_NOTIFIED        
        self.notify("KillProcesses")
        if self.exitStatus & self.COMPLETION_NOTIFIED:
            self.terminate()
        else:
            statusMonitor.notifyStatus("Waiting for all tests to terminate ...")
            # When they have, we'll get notifyAllComplete
    def terminate(self):
        self.notify("Exit")
        self.topWindow.destroy()

    def adjustSize(self):
        if guiConfig.getWindowOption("maximize"):
            self.topWindow.maximize()
            return "Maximising top window..."
        else:
            width, widthDescriptor = self.getWindowDimension("width")
            height, heightDescriptor  = self.getWindowDimension("height")
            self.topWindow.set_default_size(width, height)
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
        

class MenuBarGUI(guiplugins.SubGUI):
    def __init__(self, allApps, dynamic, uiManager, actionGUIs):
        guiplugins.SubGUI.__init__(self)
        # Create GUI manager, and a few default action groups
        self.menuNames = guiplugins.interactiveActionHandler.getMenuNames(allApps)
        self.dynamic = dynamic
        self.uiManager = uiManager
        self.actionGUIs = actionGUIs
        self.actionGroup = self.uiManager.get_action_groups()[0]
        self.toggleActions = []
        self.diag = plugins.getDiagnostics("Menu Bar")
    def setActive(self, active):
        guiplugins.SubGUI.setActive(self, active)
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
    def createView(self):
        # Initialize
        for menuName in self.menuNames:
            realMenuName = menuName
            if not menuName.isupper():
                realMenuName = menuName.capitalize()
            self.actionGroup.add_action(gtk.Action(menuName + "menu", "_" + realMenuName, None, None))
        self.createToggleActions()
        
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
        allFiles = os.path.join(layoutDir, "*.xml")
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
        partCount1 = base1.count("-")
        partCount2 = base2.count("-")
        if partCount1 != partCount2:
            return cmp(partCount1, partCount2) # less - implies read first (not mode-specific)
        return cmp(base2, base1) # something deterministic, just to make sure it's the same for everyone
    def shouldLoad(self, fileName):
        baseName = os.path.basename(fileName)
        if (baseName.endswith("-dynamic.xml") and self.dynamic) or \
               (baseName.endswith("-static.xml") and not self.dynamic):
            moduleName = "-".join(baseName.split("-")[:-1])
        else:
            moduleName = baseName[:-4]
        self.diag.info("Checking if we loaded module " + moduleName)
        return sys.modules.has_key(moduleName)
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
            actionGUI.describeAction()

class ToolBarGUI(ContainerGUI):
    def __init__(self, uiManager, subgui):
        ContainerGUI.__init__(self, [ subgui ])
        self.uiManager = uiManager
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

class PopupMenuGUI(guiplugins.SubGUI):
    def __init__(self, name, uiManager):
        guiplugins.SubGUI.__init__(self)
        self.name = name
        self.uiManager = uiManager
    def getWidgetName(self):
        return "_" + self.name
    def createView(self):
        self.uiManager.ensure_update()
        self.widget = self.uiManager.get_widget("/" + self.name)
        self.widget.show_all()
        return self.widget
    def showMenu(self, treeview, event):
        if event.button == 3 and len(self.widget.get_children()) > 0:
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
                self.widget.popup(None, None, None, event.button, time)
                return True


class ShortcutBarGUI(guiplugins.SubGUI):
    def getWidgetName(self):
        return "_Shortcut bar"
    def createView(self):
        self.widget = scriptEngine.createShortcutBar()
        self.widget.show()
        return self.widget
    def contentsChanged(self):
        pass # not yet integrated

class TestColumnGUI(guiplugins.SubGUI):
    def __init__(self, dynamic, testCount):
        guiplugins.SubGUI.__init__(self)
        self.addedCount = 0
        self.totalNofTests = testCount
        self.totalNofDistinctTests = testCount
        self.nofSelectedTests = 0
        self.nofDistinctSelectedTests = 0
        self.totalNofTestsShown = 0
        self.column = None
        self.dynamic = dynamic
        self.diag = plugins.getDiagnostics("Test Column GUI")
        self.allSuites = []
    def addSuites(self, suites):
        self.allSuites = suites
    def createView(self):
        testRenderer = gtk.CellRendererText()
        self.column = gtk.TreeViewColumn(self.getTitle(), testRenderer, text=0, background=1)
        self.column.set_resizable(True)
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
            suite.updateOrder() 
            for test in suite.testcases:
                if test.classId() == "test-suite":
                    self.setSortingOrder(order, test)
    def getTitle(self):
        title = "Tests: "
        if self.nofSelectedTests == self.totalNofTests:
            title += "All " + str(self.totalNofTests) + " selected"
        else:
            title += str(self.nofSelectedTests) + "/" + str(self.totalNofTests) + " selected"

        if not self.dynamic:
            if self.totalNofDistinctTests != self.totalNofTests:
                if self.nofDistinctSelectedTests == self.totalNofDistinctTests:
                    title += ", all " + str(self.totalNofDistinctTests) + " distinct"
                else:
                    title += ", " + str(self.nofDistinctSelectedTests) + "/" + str(self.totalNofDistinctTests) + " distinct"
        
        if self.totalNofTestsShown == self.totalNofTests:
            if self.dynamic and self.totalNofTests > 0:
                title += ", none hidden"
        elif self.totalNofTestsShown == 0:
            title += ", all hidden"
        else:
            title += ", " + str(self.totalNofTests - self.totalNofTestsShown) + " hidden"
            
        return title
    def updateTitle(self, initial=False):
        if self.column:
            self.column.set_title(self.getTitle())
            if not initial:
                self.contentsChanged()
    def describe(self):
        guilog.info("Test column header set to '" + self.column.get_title() + "'")
    def notifyTestTreeCounters(self, totalDelta, totalShownDelta, totalRowsDelta, initial=False):
        self.addedCount += totalDelta
        if not initial or self.totalNofTests < self.addedCount:
            self.totalNofTests += totalDelta
            self.totalNofDistinctTests += totalRowsDelta
        self.totalNofTestsShown += totalShownDelta
        self.updateTitle(initial)
    def notifyAllRead(self):
        if self.addedCount != self.totalNofTests:
            self.totalNofTests = self.addedCount
            self.updateTitle()
      
    def notifyNewTestSelection(self, tests, apps, distinctTestCount, direct=False):
        testcases = filter(lambda test: test.classId() == "test-case", tests)
        newCount = len(testcases)
        if distinctTestCount > newCount:
            distinctTestCount = newCount
        if self.nofSelectedTests != newCount or self.nofDistinctSelectedTests != distinctTestCount:
            self.diag.info("New selection " + repr(tests) + " distinct " + str(distinctTestCount))
            self.nofSelectedTests = newCount
            self.nofDistinctSelectedTests = distinctTestCount
            self.updateTitle()
    def notifyVisibility(self, tests, newValue):
        if newValue:
            self.totalNofTestsShown += len(tests)
        else:
            self.totalNofTestsShown -= len(tests)
        self.updateTitle()

class TestIteratorMap:
    def __init__(self, dynamic, allApps):
        self.dict = seqdict()
        self.dynamic = dynamic
        self.parentApps = {}
        for app in allApps:
            for extra in [ app ] + app.extras:
                self.parentApps[extra] = app
    def getKey(self, test):
        if self.dynamic:
            return test
        elif test is not None:
            return self.parentApps.get(test.app), test.getRelPath()
    def store(self, test, iter):
        self.dict[self.getKey(test)] = iter
    def updateIterator(self, test, oldRelPath):
        if self.dynamic:
            return self.getIterator(test)
        # relative path of test has changed
        key = self.parentApps.get(test.app), oldRelPath
        iter = self.dict.get(key)
        if iter is not None:
            self.store(test, iter)
            del self.dict[key]
            return iter
        else:
            return self.getIterator(test)
    
    def getIterator(self, test):
        return self.dict.get(self.getKey(test))

    def remove(self, test):
        key = self.getKey(test)
        if self.dict.has_key(key):
            del self.dict[key]

class RefreshTips(TreeViewTooltips):
    def __init__(self, name, refreshColumn, refreshIndex):
        TreeViewTooltips.__init__(self)
        self.name = name
        self.refreshColumn = refreshColumn
        self.refreshIndex = refreshIndex
        
    def get_tooltip(self, view, column, path):
        if column is self.refreshColumn:
            model = view.get_model()
            refreshIcon = model[path][self.refreshIndex]
            if refreshIcon:
                return "Indicates that this " + self.name + "'s saved result has changed since the status was calculated. " + \
                       "It's therefore recommended to recompute the status."

        
class TestTreeGUI(ContainerGUI):
    def __init__(self, dynamic, allApps, popupGUI, subGUI):
        ContainerGUI.__init__(self, [ subGUI ])
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT,\
                                   gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_BOOLEAN, \
                                   gobject.TYPE_STRING)
        self.popupGUI = popupGUI
        self.itermap = TestIteratorMap(dynamic, allApps)
        self.selection = None
        self.selecting = False
        self.selectedTests = []
        self.dynamic = dynamic
        self.collapseStatic = self.getCollapseStatic()
        self.successPerSuite = {} # map from suite to tests succeeded
        self.collapsedRows = {}
        self.filteredModel = None
        self.treeView = None
        self.newTestsVisible = guiConfig.showCategoryByDefault("not_started")
        self.diag = plugins.getDiagnostics("Test Tree")
    def notifyDefaultVisibility(self, newValue):
        self.newTestsVisible = newValue
        
    def setActive(self, value):
        # avoid the quit button getting initial focus, give it to the tree view (why not?)
        ContainerGUI.setActive(self, value)
        self.treeView.grab_focus()
    def describe(self):
        guilog.info("Test Tree description...")
        self.filteredModel.foreach(self.describeRow)
    def isExpanded(self, iter):
        parentIter = self.filteredModel.iter_parent(iter)
        return not parentIter or self.treeView.row_expanded(self.filteredModel.get_path(parentIter))
    def describeRow(self, model, path, iter):
        if self.isExpanded(iter):
            test = model.get_value(iter, 2)[0]
            if test:
                guilog.info("-> " + test.getIndent() + model.get_value(iter, 0))
    def getCollapseStatic(self):
        if self.dynamic:
            return False
        else:
            return guiConfig.getValue("static_collapse_suites")
    def notifyAllRead(self, suites):
        if self.dynamic:
            self.filteredModel.connect('row-inserted', self.rowInserted)
        else:
            self.newTestsVisible = True
            self.model.foreach(self.makeRowVisible)
            if self.collapseStatic:
                self.expandLevel(self.treeView, self.filteredModel.get_iter_root())
            else:
                self.treeView.expand_all()
        self.treeView.connect('row-expanded', self.describeTree) # later expansions should cause description...
        self.contentsChanged()
        self.notify("AllRead")
    def makeRowVisible(self, model, path, iter):
        self.model.set_value(iter, 5, True)
    def getNodeName(self, suite, parent):
        nodeName = suite.name
        if parent == None:
            appName = suite.app.name + suite.app.versionSuffix()
            if appName != nodeName:
                nodeName += " (" + appName + ")"
        return nodeName
    
    def addSuiteWithParent(self, suite, parent, follower=None):
        nodeName = self.getNodeName(suite, parent)
        colour = guiConfig.getTestColour("not_started")
        visible = self.newTestsVisible or not suite.parent
        row = [ nodeName, colour, [ suite ], "", colour, visible, "" ] 
        iter = self.model.insert_before(parent, follower, row)
        storeIter = iter.copy()
        self.itermap.store(suite, storeIter)
        path = self.model.get_path(iter)
        if self.newTestsVisible and parent is not None:
            filterPath = self.filteredModel.convert_child_path_to_path(path)
            self.treeView.expand_to_path(filterPath)
        return iter
    def createView(self):
        self.filteredModel = self.model.filter_new()
        self.filteredModel.set_visible_column(5)
        self.treeView = gtk.TreeView(self.filteredModel)
        self.treeView.expand_all()

        self.selection = self.treeView.get_selection()
        self.selection.set_mode(gtk.SELECTION_MULTIPLE)
        if self.dynamic:
            self.selection.set_select_function(self.canSelect)
            
        testsColumn = self.subguis[0].createView()
        self.treeView.append_column(testsColumn)
        if self.dynamic:
            detailsRenderer = gtk.CellRendererText()
            detailsRenderer.set_property('wrap-width', 350)
            detailsRenderer.set_property('wrap-mode', pango.WRAP_WORD_CHAR)
            recalcRenderer = gtk.CellRendererPixbuf()
            detailsColumn = gtk.TreeViewColumn("Details")
            detailsColumn.pack_start(detailsRenderer, expand=True)
            detailsColumn.pack_start(recalcRenderer, expand=False)
            detailsColumn.add_attribute(detailsRenderer, 'text', 3)
            detailsColumn.add_attribute(detailsRenderer, 'background', 4)
            detailsColumn.add_attribute(recalcRenderer, 'stock_id', 6)
            detailsColumn.set_resizable(True)
            self.tips = RefreshTips("test", detailsColumn, 6)
            self.tips.add_view(self.treeView)
            self.treeView.append_column(detailsColumn)

        scriptEngine.monitorExpansion(self.treeView, "show test suite", "hide test suite")
        self.treeView.connect('row-expanded', self.rowExpanded)
        self.expandLevel(self.treeView, self.filteredModel.get_iter_root())
        self.treeView.connect("button_press_event", self.popupGUI.showMenu)
        
        scriptEngine.monitor("set test selection to", self.selection)
        self.selection.connect("changed", self.userChangedSelection)
        
        self.treeView.show()
        self.popupGUI.createView()
        return self.addScrollBars(self.treeView, hpolicy=gtk.POLICY_NEVER)
    def describeTree(self, *args):
        guiplugins.SubGUI.contentsChanged(self) # don't describe the column too...

    def canSelect(self, path):
        pathIter = self.filteredModel.get_iter(path)
        test = self.filteredModel.get_value(pathIter, 2)[0]
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
            self.diag.info("Expanding path at " + repr(realPath))
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
            self.sendSelectionNotification(newSelection, direct)
            if self.dynamic:
                self.selection.selected_foreach(self.updateRecalculationMarker)
            
    def notifyRefreshTestSelection(self):
        # The selection hasn't changed, but we want to e.g.
        # recalculate the action sensitiveness.
        self.sendSelectionNotification(self.selectedTests)
    def notifyRecomputed(self, test):
        iter = self.itermap.getIterator(test)
        # If we've recomputed, clear the recalculation icons
        self.setNewRecalculationStatus(iter, test, [])
    
    def updateRecalculationMarker(self, model, path, iter):
        tests = model.get_value(iter, 2)
        if not tests[0].state.isComplete():
            return
        
        recalcComparisons = tests[0].state.getComparisonsForRecalculation()
        childIter = self.filteredModel.convert_iter_to_child_iter(iter)
        self.setNewRecalculationStatus(childIter, tests[0], recalcComparisons)

    def setNewRecalculationStatus(self, iter, test, recalcComparisons):
        oldVal = self.model.get_value(iter, 6)
        newVal = self.getRecalculationIcon(recalcComparisons)
        if newVal != oldVal:
            guilog.info("Setting recalculation icon to '" + newVal + "'")
            self.model.set_value(iter, 6, newVal)
        self.notify("Recalculation", test, recalcComparisons, newVal)

    def getRecalculationIcon(self, recalc):
        if recalc:
            return "gtk-refresh"
        else:
            return ""
    def checkRelatedForRecalculation(self, test):
        self.filteredModel.foreach(self.checkRecalculationIfMatches, test)
    def checkRecalculationIfMatches(self, model, path, iter, test):
        tests = model.get_value(iter, 2)
        if tests[0] is not test and tests[0].getRelPath() == test.getRelPath():
            self.updateRecalculationMarker(model, path, iter)
        
    def getSelectedApps(self, tests):
        apps = []
        for test in tests:
            if test.app not in apps:
                apps.append(test.app)
        return apps
    def sendSelectionNotification(self, tests, direct=True):
        self.diag.info("Selection now changed to " + repr(tests))
        apps = self.getSelectedApps(tests)
        self.selectedTests = tests
        self.notify("NewTestSelection", tests, apps, self.selection.count_selected_rows(), direct)
    def getSelected(self):
        allSelected = []
        self.selection.selected_foreach(self.addSelTest, (allSelected, Set(self.selectedTests)))
        self.diag.info("Selected tests are " + repr(allSelected))
        return allSelected
    def addSelTest(self, model, path, iter, args):
        selected, prevSelected = args
        selected += self.getNewSelected(model.get_value(iter, 2), prevSelected)
    def getNewSelected(self, tests, prevSelected):
        intersection = prevSelected.intersection(Set(tests))
        if len(intersection) == 0 or len(intersection) == len(tests):
            return tests
        else:
            return list(intersection)
    def findIter(self, test):
        try:
            childIter = self.itermap.getIterator(test)
            if childIter:
                return self.filteredModel.convert_child_iter_to_iter(childIter)
        except RuntimeError:
            pass # convert_child_iter_to_iter throws RunTimeError if the row is hidden in the TreeModelFilter
    def notifySetTestSelection(self, selTests, criteria="", selectCollapsed=True):
        actualSelection = self.selectTestRows(selTests, selectCollapsed)
        guilog.info("Marking " + str(self.selection.count_selected_rows()) + " tests as selected")
        # Here it's been set via some indirect mechanism, might want to behave differently 
        self.sendSelectionNotification(actualSelection, direct=False) 
    def selectTestRows(self, selTests, selectCollapsed=True):
        self.selecting = True # don't respond to each individual programmatic change here
        self.selection.unselect_all()
        treeView = self.selection.get_tree_view()
        firstPath = None
        actuallySelected = []
        for test in selTests:
            iter = self.findIter(test)
            if not iter or (not selectCollapsed and not self.isExpanded(iter)):
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
    def notifyTestAppearance(self, test, detailText, colour1, colour2, updateSuccess, saved):
        iter = self.itermap.getIterator(test)
        self.model.set_value(iter, 1, colour1) 
        self.model.set_value(iter, 3, detailText)
        self.model.set_value(iter, 4, colour2)
        self.diagnoseTest(test, iter)
        if updateSuccess:
            self.updateSuiteSuccess(test, colour1)
        if saved:
            self.checkRelatedForRecalculation(test)

    def notifyLifecycleChange(self, test, *args):
        if test in self.selectedTests:
            self.notify("LifecycleChange", test, *args)
    def notifyFileChange(self, test, *args):
        if test in self.selectedTests:
            self.notify("FileChange", test, *args)
    def notifyDescriptionChange(self, test, *args):
        if test in self.selectedTests:
            self.notify("DescriptionChange", test, *args)

    def updateSuiteSuccess(self, test, colour):
        suite = test.parent
        if not suite:
            return
        
        self.successPerSuite.setdefault(suite, Set()).add(test)
        successCount = len(self.successPerSuite.get(suite))
        suiteSize = len(filter(lambda subtest: not subtest.isEmpty(), suite.testcases))
        if successCount == suiteSize:
            self.setAllSucceeded(suite, colour)
            self.updateSuiteSuccess(suite, colour)
            
    def diagnoseTest(self, test, iter):
        self.writeSeparator()
        guilog.info("Redrawing test " + test.name + " coloured " + self.model.get_value(iter, 1))
        secondColumnText = self.model.get_value(iter, 3)
        if secondColumnText:
            guilog.info("(Second column '" + secondColumnText + "' coloured " + self.model.get_value(iter, 4) + ")")
            
    def setAllSucceeded(self, suite, colour):
        # Print how many tests succeeded, color details column in success color,
        # collapse row, and try to collapse parent suite.
        detailText = "All " + str(suite.size()) + " tests successful"
        iter = self.itermap.getIterator(suite)
        self.model.set_value(iter, 3, detailText)
        self.model.set_value(iter, 4, colour)
        guilog.info("Redrawing suite " + suite.name + " : second column '" + detailText +  "' coloured " + colour)

        if suite.getConfigValue("auto_collapse_successful") == 1:
            self.collapseRow(iter)

    def isVisible(self, test):
        iter = self.findIter(test)
        if iter:
            path = self.filteredModel.get_path(self.filteredModel.iter_parent(iter))
            return not self.collapsedRows.has_key(path)
        else:
            return False
    def findAllTests(self):
        tests = []
        self.model.foreach(self.appendTest, tests)
        return tests
    def appendTest(self, model, path, iter, tests):
        for test in model.get_value(iter, 2):
            if test.classId() == "test-case":
                tests.append(test)
    def getTestForAutoSelect(self):
        allTests = self.findAllTests()
        if len(allTests) == 1:
            test = allTests[0]
            if self.isVisible(test):
                return test
            
    def notifyAllComplete(self):
        test = self.getTestForAutoSelect()
        if test:
            guilog.info("Only one test found, selecting " + test.uniqueName)
            actualSelection = self.selectTestRows([ test ])
            self.sendSelectionNotification(actualSelection)
    
    def notifyAdd(self, test, initial):
        if test.classId() == "test-case":
            self.notify("TestTreeCounters", initial=initial, totalDelta=1,
                        totalShownDelta=self.getTotalShownDelta(), totalRowsDelta=self.getTotalRowsDelta(test))
        elif self.dynamic and test.isEmpty():
            return # don't show empty suites in the dynamic GUI

        self.diag.info("Adding test " + repr(test))
        self.tryAddTest(test, initial)
        if not initial:
            self.describeTree()
    def getTotalRowsDelta(self, test):
        if self.itermap.getIterator(test):
            return 0
        else:
            return 1
    def getTotalShownDelta(self):
        if self.dynamic:
            return int(self.newTestsVisible)
        else:
            return 1 # we hide them temporarily for performance reasons, so can't do as above
    def tryAddTest(self, test, initial=False):
        iter = self.itermap.getIterator(test)
        if iter:
            self.addAdditional(iter, test)
            return iter
        suite = test.parent
        suiteIter = None
        if suite:
            suiteIter = self.tryAddTest(suite, initial)
        followIter = self.findFollowIter(suite, test, initial)
        return self.addSuiteWithParent(test, suiteIter, followIter)
    def findFollowIter(self, suite, test, initial):
        if not initial:
            follower = suite.getFollower(test)
            if follower:
                return self.itermap.getIterator(follower)
        
    def addAdditional(self, iter, test):
        currTests = self.model.get_value(iter, 2)
        if not test in currTests:
            currTests.append(test)
            
    def notifyRemove(self, test):
        delta = -test.size()
        iter = self.itermap.getIterator(test)
        allTests = self.model.get_value(iter, 2)
        if len(allTests) == 1:
            self.notify("TestTreeCounters", totalDelta=delta, totalShownDelta=delta, totalRowsDelta=delta)
            self.removeTest(test, iter)
            guilog.info("Removing test with path " + test.getRelPath())
        else:
            self.notify("TestTreeCounters", totalDelta=delta, totalShownDelta=delta, totalRowsDelta=0)
            allTests.remove(test)
            guilog.info("Removing additional test from path " + test.getRelPath())

    def removeTest(self, test, iter):
        filteredIter = self.findIter(test)
        if self.selection.iter_is_selected(filteredIter):
            self.selection.unselect_iter(filteredIter)
        self.model.remove(iter)
        self.itermap.remove(test)

    def notifyNameChange(self, test, origRelPath):
        iter = self.itermap.updateIterator(test, origRelPath)
        self.model.set_value(iter, 0, test.name)
        filteredIter = self.filteredModel.convert_child_iter_to_iter(iter)
        self.describeTree()
        if self.selection.iter_is_selected(filteredIter):
            self.notify("NameChange", test, origRelPath)
    def notifyContentChange(self, suite):
        suiteIter = self.itermap.getIterator(suite)
        newOrder = self.findNewOrder(suite, suiteIter)
        self.model.reorder(suiteIter, newOrder)
        self.describeTree()
    def findNewOrder(self, suite, suiteIter):
        child = self.model.iter_children(suiteIter)
        index = 0
        posMap = {}
        while (child != None):
            subTestName = self.model.get_value(child, 0)
            posMap[subTestName] = index
            child = self.model.iter_next(child)
            index += 1
        newOrder = []
        for currSuite in self.model.get_value(suiteIter, 2):
            for subTest in currSuite.testcases:
                oldIndex = posMap.get(subTest.name)
                if oldIndex not in newOrder:
                    newOrder.append(oldIndex)
        return newOrder
    
    def notifyVisibility(self, tests, newValue):
        self.diag.info("Visibility change for " + repr(tests) + " to " + repr(newValue))
        if not newValue:
            self.selecting = True
        changedTests = []
        for test in tests:
            if self.updateVisibilityInModel(test, newValue):
                changedTests.append(test)

        self.selecting = False
        if len(changedTests) > 0:
            self.diag.info("Actually changed tests " + repr(changedTests))
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
        visibleTests = self.model.get_value(self.itermap.getIterator(test), 2)
        isVisible = test in visibleTests
        changed = False
        if newValue and not isVisible:
            visibleTests.append(test)
            changed = True
        elif not newValue and isVisible:
            visibleTests.remove(test)
            changed = True
    
        if (newValue and len(visibleTests) > 1) or (not newValue and len(visibleTests) > 0):
            self.diag.info("Other tests mean no row visibility change : " + repr(test))
            return changed
        
        allIterators = self.findVisibilityIterators(test) # returns leaf-to-root order, good for hiding
        if newValue:
            allIterators.reverse()  # but when showing, we want to go root-to-leaf

        changed = False
        for iterator, currTest in allIterators:
            if newValue or not self.hasVisibleChildren(iterator):
                changed |= self.setVisibility(iterator, currTest, newValue)
        return changed
        
    def setVisibility(self, iter, test, newValue):
        oldValue = self.model.get_value(iter, 5)
        if oldValue == newValue:
            self.diag.info("Not changing test : " + repr(test))
            return False

        if self.treeView:
            if newValue:
                guilog.info("Making test visible : " + repr(test))
            else:
                guilog.info("Hiding test : " + repr(test))
        self.model.set_value(iter, 5, newValue)
        return True
    def findVisibilityIterators(self, test):
        iter = self.itermap.getIterator(test)
        parents = []
        parent = self.model.iter_parent(iter)
        currTest = test
        while parent != None:
            currTest = currTest.parent
            parents.append((parent, currTest))                    
            parent = self.model.iter_parent(parent)
        # Don't include the root which we never hide
        return [ (iter, test) ] + parents[:-1]

    def hasVisibleChildren(self, iter):
        child = self.model.iter_children(iter)
        while (child != None):
            if self.model.get_value(child, 5):
                return True
            else:
                child = self.model.iter_next(child)
        return False
    
    
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
        

class NotebookGUI(guiplugins.SubGUI):
    def __init__(self, tabInfo, scriptTitle):
        guiplugins.SubGUI.__init__(self)
        self.scriptTitle = scriptTitle
        self.diag = plugins.getDiagnostics("GUI notebook")
        self.tabInfo = tabInfo
        self.notebook = None
        tabName, self.currentTabGUI = self.findInitialCurrentTab()
        self.diag.info("Current page set to '" + tabName + "'")

    def findInitialCurrentTab(self):
        return self.tabInfo[0]
    
    def setActive(self, value):
        guiplugins.SubGUI.setActive(self, value)
        if self.currentTabGUI:
            self.diag.info("Setting active flag " + repr(value) + " for '" + self.currentTabGUI.getTabTitle() + "'")
            self.currentTabGUI.setActive(value)

    def contentsChanged(self):
        guiplugins.SubGUI.contentsChanged(self)
        if self.currentTabGUI:
            self.currentTabGUI.contentsChanged()

    def createView(self):
        self.notebook = gtk.Notebook()
        for tabName, tabGUI in self.tabInfo:
            label = gtk.Label(tabName)
            page = self.createPage(tabGUI, tabName)
            self.notebook.append_page(page, label)

        scriptEngine.monitorNotebook(self.notebook, self.scriptTitle)
        self.notebook.set_scrollable(True)
        self.notebook.connect("switch-page", self.handlePageSwitch)
        self.notebook.show()
        return self.notebook

    def createPage(self, tabGUI, tabName):
        self.diag.info("Adding page " + tabName)
        return tabGUI.createView()

    def handlePageSwitch(self, notebook, ptr, pageNum, *args):
        if not self.active:
            return
        newPageName, newTabGUI = self.tabInfo[pageNum]
        if newTabGUI is self.currentTabGUI:
            return
        self.currentTabGUI = newTabGUI 
        self.diag.info("Switching to page " + newPageName)
        for tabName, tabGUI in self.tabInfo:
            if tabGUI is self.currentTabGUI:
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

    def describe(self):
        guilog.info("Tabs showing : " + ", ".join(self.getTabNames()))

    def getVisiblePages(self):
        return filter(lambda child: child.get_property("visible"), self.notebook.get_children())

    def getTabNames(self):
        return map(self.notebook.get_tab_label_text, self.getVisiblePages())
    
    def shouldShowCurrent(self, *args):
        for name, tabGUI in self.tabInfo:
            if tabGUI.shouldShowCurrent(*args):
                return True
        return False
    


# Notebook GUI that adds and removes tabs as appropriate...
class ChangeableNotebookGUI(NotebookGUI):
    def createPage(self, tabGUI, tabName):
        page = NotebookGUI.createPage(self, tabGUI, tabName)
        if not tabGUI.shouldShowCurrent():
            self.diag.info("Hiding page " + tabName)
            page.hide()
        return page

    def findInitialCurrentTab(self):
        for tabName, tabGUI in self.tabInfo:
            if tabGUI.shouldShowCurrent():
                return tabName, tabGUI

        return self.tabInfo[0]
            
    def findFirstRemaining(self, pagesRemoved):
        for page in self.getVisiblePages():
            pageNum = self.notebook.page_num(page)
            if not pagesRemoved.has_key(pageNum):
                return pageNum
    
    def showNewPages(self, *args):
        changed = False
        for pageNum, (name, tabGUI) in enumerate(self.tabInfo):
            page = self.notebook.get_nth_page(pageNum)
            if tabGUI.shouldShowCurrent(*args):
                if not page.get_property("visible"):
                    self.diag.info("Showing page " + name)
                    page.show()
                    changed = True
            else:
                self.diag.info("Remaining hidden " + name)
        return changed
    def setCurrentPage(self, newNum):
        newName, newTabGUI = self.tabInfo[newNum]
        self.diag.info("Resetting for current page " + repr(self.notebook.get_current_page()) + \
                       " to page " + repr(newNum) + " = " + repr(newName))
        self.notebook.set_current_page(newNum)
        # Must do this afterwards, otherwise the above change doesn't propagate
        self.currentTabGUI = newTabGUI
        self.diag.info("Resetting done.")
        
    def findPagesToHide(self, *args):
        pages = seqdict()
        for pageNum, (name, tabGUI) in enumerate(self.tabInfo):
            page = self.notebook.get_nth_page(pageNum)
            if not tabGUI.shouldShowCurrent(*args) and page.get_property("visible"):
                pages[pageNum] = page
        return pages
        
    def hideOldPages(self, *args):
        # Must reset the current page before removing it if we're viewing a removed page
        # otherwise we can output lots of pages we don't really look at
        pagesToHide = self.findPagesToHide(*args)
        if len(pagesToHide) == 0:
            return False

        if pagesToHide.has_key(self.notebook.get_current_page()):
            newCurrentPageNum = self.findFirstRemaining(pagesToHide)
            if newCurrentPageNum is not None:
                self.setCurrentPage(newCurrentPageNum)
            
        # remove from the back, so we don't momentarily view them all if removing everything
        for page in reversed(pagesToHide.values()):
            self.diag.info("Hiding page " + self.notebook.get_tab_label_text(page))
            page.hide()
        return True
    def updateCurrentPage(self, rowCount):
        for pageNum, (tabName, tabGUI) in enumerate(self.tabInfo):            
            if tabGUI.shouldShowCurrent() and tabGUI.forceVisible(rowCount):
                self.setCurrentPage(pageNum)

    def notifyNewTestSelection(self, tests, apps, rowCount, direct):
        if not self.notebook:
            return
        self.diag.info("New selection with " + repr(tests) + ", adjusting '" + self.scriptTitle + "'")
        pagesShown = self.showNewPages()
        pagesHidden = self.hideOldPages()
        # only change pages around if a test is directly selected
        if direct: 
            self.updateCurrentPage(rowCount)
  
        if pagesShown or pagesHidden:
            guiplugins.SubGUI.contentsChanged(self) # just the tabs will do here, the rest is described by other means
    def notifyLifecycleChange(self, test, state, changeDesc):
        if not self.notebook:
            return 
        pagesShown = self.showNewPages(test, state)
        pagesHidden = self.hideOldPages(test, state)
        if pagesShown or pagesHidden:
            guiplugins.SubGUI.contentsChanged(self) # just the tabs will do here, the rest is described by other means
        
          
class PaneGUI(ContainerGUI):
    def __init__(self, gui1, gui2 , horizontal, shrink=True):
        ContainerGUI.__init__(self, [ gui1, gui2 ])
        self.horizontal = horizontal
        self.panedTooltips = gtk.Tooltips()
        self.paned = None
        self.separatorHandler = None
        self.position = 0
        self.shrink = shrink
        self.initialMaxSize = None
    def getSeparatorPositionFromConfig(self):
        if self.horizontal:
            return float(guiConfig.getWindowOption("vertical_separator_position"))
        else:
            return float(guiConfig.getWindowOption("horizontal_separator_position"))
    def createPaned(self):
        if self.horizontal:
            return gtk.HPaned()
        else:
            return gtk.VPaned()

    def scriptCommand(self):
        if self.horizontal:
            return "drag vertical pane separator so left half uses"
        else:
            return "drag horizonal pane separator so top half uses"
        
    def createView(self):
        self.paned = self.createPaned()
        self.separatorHandler = self.paned.connect('notify::max-position', self.adjustSeparator)
        scriptEngine.registerPaned(self.paned, self.scriptCommand())
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
        
    def positionDescription(self, proportion):
        message = str(int(100 * proportion + 0.5)) + "% from the "
        if self.horizontal:
            return message + "left edge"
        else:
            return message + "top"

    def contentsChanged(self):
        self.subguis[0].contentsChanged()
        self.describeSeparator()
        self.subguis[1].contentsChanged()

    def describeSeparator(self):
        guilog.info("")
        perc = self.getSeparatorPosition()
        guilog.info("Pane separator positioned " + self.positionDescription(perc))

    def getSeparatorPosition(self):
        # We print the real position if we have it, and the intended one if we don't
        if self.initialMaxSize:
            return float(self.paned.get_position()) / self.initialMaxSize
        else:
            return self.getSeparatorPositionFromConfig()

    def getMaximimumSize(self):
        if self.horizontal:
            return self.paned.allocation.width
        else:
            return self.paned.allocation.height

    def adjustSeparator(self, *args):
        self.initialMaxSize = self.paned.get_property("max-position")
        self.paned.child_set_property(self.paned.get_child1(), "shrink", self.shrink)
        self.paned.child_set_property(self.paned.get_child2(), "shrink", self.shrink)
        self.position = int(self.initialMaxSize * self.getSeparatorPositionFromConfig())
        self.paned.set_position(self.position)
        # Only want to do this once, providing we actually change something
        if self.position > 0:
            self.paned.disconnect(self.separatorHandler)
            # subsequent changes are hopefully manual, and in these circumstances we don't want to prevent shrinking
            if not self.shrink:
                self.paned.connect('notify::position', self.checkShrinkSetting)

    def checkShrinkSetting(self, *args):
        oldPos = self.position
        self.position = self.paned.get_position()
        if self.position > oldPos and self.position == self.paned.get_property("min-position"):
            self.paned.set_position(self.position + 1)
        elif self.position < oldPos and self.position == self.paned.get_property("max-position"):
            self.paned.set_position(self.position - 1)
        elif self.position <= oldPos and self.position <= self.paned.get_property("min-position"):
            self.paned.child_set_property(self.paned.get_child1(), "shrink", True)
        elif self.position >= oldPos and self.position >= self.paned.get_property("max-position"):
            self.paned.child_set_property(self.paned.get_child2(), "shrink", True)
        
    
class TextInfoGUI(guiplugins.SubGUI):
    def __init__(self):
        guiplugins.SubGUI.__init__(self)
        self.currentTest = None
        self.text = ""
        self.view = None
    def shouldShowCurrent(self, *args):
        return len(self.text) > 0
    def getTabTitle(self):
        return "Text Info"
    def forceVisible(self, rowCount):
        return rowCount == 1
    def resetText(self, state):
        self.text = ""
        freeText = state.getFreeText()
        if state.isComplete():
            self.text = "Test " + repr(state) + "\n"
            if len(freeText) == 0:
                self.text = self.text.replace(" :", "")
        self.text += str(freeText)
        if state.hasStarted() and not state.isComplete():
            self.text += "\n\nTo obtain the latest progress information and an up-to-date comparison of the files above, " + \
                         "perform 'recompute status' (press '" + guiConfig.getCompositeValue("gui_accelerators", "recompute_status") + "')"
    def describe(self):
        guilog.info("---------- Text Info Window ----------")
        buffer = self.view.get_buffer()
        guilog.info(plugins.encodeToLocale(buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter()), guilog).strip())
        guilog.info("--------------------------------------")
    def notifyNewTestSelection(self, tests, *args):
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
        self.view.set_name(self.getTabTitle())
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

        
class FileViewGUI(guiplugins.SubGUI):
    def __init__(self, dynamic, title = "", popupGUI = None):
        guiplugins.SubGUI.__init__(self)
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_STRING,\
                                   gobject.TYPE_PYOBJECT, gobject.TYPE_STRING, gobject.TYPE_STRING)
        self.popupGUI = popupGUI
        self.dynamic = dynamic
        self.title = title
        self.selection = None
        self.nameColumn = None
        self.diag = plugins.getDiagnostics("File View GUI")

    def recreateModel(self, state, preserveSelection):
        if not self.nameColumn:
            return
        # In theory we could do something clever here, but for now, just wipe and restart
        # Need to re-expand and re-select after clearing...
        if preserveSelection:
            selectionStore = self.storeSelection()
            self.diag.info("Storing " + repr(selectionStore))

        self.model.clear()
        self.addFilesToModel(state)
        self.selection.get_tree_view().expand_all()
        if preserveSelection:
            self.reselect(selectionStore)
        self.contentsChanged()

    def storeSelection(self):
        selectionStore = []
        self.selection.selected_foreach(self.storeIter, selectionStore)
        return selectionStore

    def storeIter(self, model, path, iter, selectionStore):
        selectionStore.append(self._storeIter(iter))

    def _storeIter(self, iter):
        if iter is not None:
            parentStore = self._storeIter(self.model.iter_parent(iter))
            parentStore.append(self.model.get_value(iter, 0))
            return parentStore
        else:
            return []

    def reselect(self, selectionStore):
        for nameList in selectionStore:
            iter = self.findIter(nameList, self.model.get_iter_root())
            if iter is not None:
                self.selection.select_iter(iter)

    def findIter(self, nameList, iter):
        self.diag.info("Looking for iter for " + repr(nameList))
        while iter is not None:
            name = self.model.get_value(iter, 0)
            if name == nameList[0]:
                if len(nameList) == 1:
                    self.diag.info("Succeeded!")
                    return iter
                else:
                    return self.findIter(nameList[1:], self.model.iter_children(iter))
            else:
                iter = self.model.iter_next(iter)
        self.diag.info("Failed!")

    def getState(self):
        pass
     
    def describe(self):
        self.describeName()
        self.model.foreach(self.describeIter)

    def describeName(self):
        if self.nameColumn:
            guilog.info("Setting file-view title to '" + self.nameColumn.get_title() + "'")
            
    def describeIter(self, model, path, currIter):
        parentIter = self.model.iter_parent(currIter)
        if parentIter:
            fileName = self.model.get_value(currIter, 0)
            colour = self.model.get_value(currIter, 1)
            if colour:
                parentDesc = self.model.get_value(parentIter, 0)
                guilog.info("Adding file " + fileName + " under heading '" + parentDesc + "', coloured " + colour)
            details = self.model.get_value(currIter, 4)
            if details:
                guilog.info("(Second column '" + details + "' coloured " + colour + ")")
            recalcIcon = self.model.get_value(currIter, 5)
            if recalcIcon:
                guilog.info("(Recalculation icon showing '" + recalcIcon + "')")
            
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
        self.nameColumn.set_resizable(True)
        view.append_column(self.nameColumn)            
        detailsColumn = self.makeDetailsColumn(renderer)
        if detailsColumn:
            view.append_column(detailsColumn)
            self.tips = RefreshTips("file", detailsColumn, 5)
            self.tips.add_view(view)

        view.expand_all()
        self.monitorEvents()
        if self.popupGUI:
            view.connect("button_press_event", self.popupGUI.showMenu)
            self.popupGUI.createView()

        view.show()
        return self.addScrollBars(view)
        # only used in test view
        
    def canSelect(self, path):
        pathIter = self.model.get_iter(path)
        return not self.model.iter_has_child(pathIter)

    def makeDetailsColumn(self, renderer):
        if self.dynamic:
            column = gtk.TreeViewColumn("Details")
            column.set_resizable(True)
            recalcRenderer = gtk.CellRendererPixbuf()
            column.pack_start(renderer, expand=True)
            column.pack_start(recalcRenderer, expand=False)
            column.add_attribute(renderer, 'text', 4)
            column.add_attribute(renderer, 'background', 1)
            column.add_attribute(recalcRenderer, 'stock_id', 5)
            return column

    def fileActivated(self, view, path, column, *args):
        iter = self.model.get_iter(path)
        fileName = self.model.get_value(iter, 2)
        if not fileName:
            # Don't crash on double clicking the header lines...
            return
        comparison = self.model.get_value(iter, 3)
        self.notify(self.getViewFileSignal(), fileName, comparison)

    def notifyViewerStarted(self):
        self.selection.unselect_all()

    def notifyNewFile(self, fileName, overwrittenExisting):
        self.notify(self.getViewFileSignal(), fileName, None)
        if not overwrittenExisting:
            self.currentTest.refreshFiles()
            self.recreateModel(self.getState(), preserveSelection=True)

    def addFileToModel(self, iter, fileName, colour, associatedObject=None, details=""):
        baseName = os.path.basename(fileName)
        row = [ baseName, colour, fileName, associatedObject, details, "" ]
        return self.model.insert_before(iter, None, row)

  
class ApplicationFileGUI(FileViewGUI):
    def __init__(self, dynamic, allApps):
        FileViewGUI.__init__(self, dynamic, "Configuration Files")
        self.allApps = allApps
    def shouldShow(self):
        return not self.dynamic
    def getGroupTabTitle(self):
        return "Config"
    def getViewFileSignal(self):
        return "ViewApplicationFile"
    def monitorEvents(self):
        scriptEngine.connect("select application file", "row_activated", self.selection.get_tree_view(), self.fileActivated)
    def addFilesToModel(self, state):
        colour = guiConfig.getCompositeValue("file_colours", "static")
        personalFiles = self.getPersonalFiles()
        importedFiles = {}
        if len(personalFiles) > 0:
            persiter = self.model.insert_before(None, None)
            self.model.set_value(persiter, 0, "Personal Files")
            for file in personalFiles:
                self.addFileToModel(persiter, file, colour, self.allApps)
                for importedFile in self.getImportedFiles(file):
                    importedFiles[importedFile] = importedFile

        allTitles = self.getApplicationTitles()
        for index, app in enumerate(self.allApps):
            confiter = self.model.insert_before(None, None)
            self.model.set_value(confiter, 0, "Files for " + allTitles[index])
            for file in self.getConfigFiles(app):
                self.addFileToModel(confiter, file, colour, [ app ])
                for importedFile in self.getImportedFiles(file, app):
                    importedFiles[importedFile] = importedFile
                    
        # Handle recursive imports here ...
        
        if len(importedFiles) > 0:
            importediter = self.model.insert_before(None, None)
            self.model.set_value(importediter, 0, "Imported Files")
            sortedFiles = importedFiles.values()
            sortedFiles.sort()
            for importedFile in sortedFiles:
                self.addFileToModel(importediter, importedFile, colour, self.allApps)
    def getApplicationTitles(self):
        basicTitles = [ app.fullName + app.versionSuffix() for app in self.allApps ]
        if self.areUnique(basicTitles):
            return basicTitles
        else:
            return [ app.fullName + app.versionSuffix() + " (" + app.name + " under " +
                     os.path.basename(app.getDirectory()) + ")" for app in self.allApps ]
    def areUnique(self, names):
        for index, name in enumerate(names):
            for otherName in names[index + 1:]:
                if name == otherName:
                    return False
        return True
                
    def getConfigFiles(self, app):
        return app._getAllFileNames([ app.dircache ], "config", allVersions=True)
    def getPersonalFiles(self):
        personalDir = plugins.getPersonalConfigDir()
        if not os.path.isdir(personalDir):
            return []
        allEntries = [ os.path.join(personalDir, file) for file in os.listdir(personalDir) ]
        allFiles = filter(os.path.isfile, allEntries)
        allFiles.sort()
        return allFiles
    def getImportedFiles(self, file, app = None):
        imports = []
        if os.path.isfile(file):
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

    def canSelect(self, path):
        if self.dynamic:
            return FileViewGUI.canSelect(self, path)
        else:
            return True

    def getViewFileSignal(self):
        return "ViewFile"

    def notifyNameChange(self, test, origRelPath):
        if test is self.currentTest:
            self.setName( [ test ], 1)
            self.model.foreach(self.updatePath, (origRelPath, test.getRelPath()))
            self.describeName()

    def updatePath(self, model, path, iter, data):
        origPath, newPath = data
        origFile = model.get_value(iter, 2)
        if origFile:
            model.set_value(iter, 2, origFile.replace(origPath, newPath))

    def notifyFileChange(self, test):
        if test is self.currentTest:
            self.recreateModel(test.state, preserveSelection=True)

    def notifyLifecycleChange(self, test, state, changeDesc):
        if test is self.currentTest:
            self.recreateModel(state, preserveSelection=changeDesc.find("save") == -1)

    def notifyRecalculation(self, test, comparisons, newIcon):
        if test is self.currentTest:
            # slightly ugly hack with "global data": this way we don't have to return any iterators
            # and can avoid the bug in PyGTK 2.10.3 in this area
            self.recalculationCausedChange = False
            self.model.foreach(self.setRecalculateIcon, [ comparisons, newIcon ])
            if self.recalculationCausedChange:
                self.contentsChanged()

    def setRecalculateIcon(self, model, path, iter, data):
        comparisons, newIcon = data
        comparison = model.get_value(iter, 3)
        if comparison in comparisons:
            oldVal = model.get_value(iter, 5)
            if oldVal != newIcon:
                self.model.set_value(iter, 5, newIcon)
                self.recalculationCausedChange = True
                            
    def forceVisible(self, rowCount):
        return rowCount == 1
    
    def notifyNewTestSelection(self, tests, apps, rowCount, *args):
        if len(tests) == 0 or (not self.dynamic and rowCount > 1): # multiple tests in static GUI result in removal
            self.currentTest = None
            return

        if len(tests) > 1 and self.currentTest in tests:
            self.setName(tests, rowCount)
            if self.active:
                self.describeName()
        else:
            self.currentTest = tests[0]
            self.currentTest.refreshFiles()
            self.setName(tests, rowCount)
            # New test selected, don't keep file selection
            self.recreateModel(self.getState(), preserveSelection=False)

    def setName(self, tests, rowCount):
        self.title = self.getName(tests, rowCount)
        if self.nameColumn:
            self.nameColumn.set_title(self.title)

    def getName(self, tests, rowCount):
        if rowCount > 1:
            return "Sample from " + repr(len(tests)) + " tests"
        else:
            return self.currentTest.name.replace("_", "__")
    def getColour(self, name):
        return guiConfig.getCompositeValue("file_colours", name)

    def shouldShowCurrent(self, *args):
        return self.currentTest is not None
            
    def addFilesToModel(self, state):
        if not state:
            return
        realState = state
        if state.isMarked():
            realState = state.oldState
        if self.dynamic:
            if hasattr(realState, "correctResults"):
                # failed on comparison
                self.addComparisonsToModel(realState)
            elif not realState.isComplete():
                self.addTmpFilesToModel(realState)
        else:
            self.addStaticFilesToModel(realState)

    def monitorEvents(self):
        scriptEngine.connect("select file", "row_activated", self.selection.get_tree_view(), self.fileActivated)
        scriptEngine.monitor("set file selection to", self.selection)
        self.selectionChanged(self.selection)
        self.selection.connect("changed", self.selectionChanged)

    def selectionChanged(self, selection):
        filelist = []
        selection.selected_foreach(self.fileSelected, filelist)
        self.notify("NewFileSelection", filelist)
        if not self.dynamic:
            if selection.count_selected_rows() == 1:
                model, paths = selection.get_selected_rows()
                selectedIter = self.model.get_iter(paths[0])
                dirName = self.getDirectory(selectedIter)
                fileType = self.getFileType(selectedIter)
                self.notify("FileCreationInfo", dirName, fileType)
            else:
                self.notify("FileCreationInfo", None, None)

    def getDirectory(self, iter):
        fileName = self.model.get_value(iter, 2)
        if fileName:
            if os.path.isdir(fileName):
                return fileName
            else:
                return os.path.dirname(fileName)

    def getFileType(self, iter):
        parent = self.model.iter_parent(iter)
        if parent is not None:
            return self.getFileType(parent)
        else:
            name = self.model.get_value(iter, 0)
            return name.split()[0].lower()

    def fileSelected(self, treemodel, path, iter, filelist):
        # files are leaves, not including the top level which might be empty headers
        if self.model.iter_parent(iter) is not None and not self.model.iter_has_child(iter):
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
            details = ""
            if comparison:
                details = comparison.getDetails()
            self.addFileToModel(iter, file, colour, comparison, details)
    def getComparisonColour(self, state, fileComp):
        if not state.hasStarted():
            return self.getColour("not_started")
        if not state.isComplete():
            return self.getColour("running")
        if fileComp.hasSucceeded():
            return self.getColour("success")
        else:
            return self.getColour("failure")
    def addTmpFilesToModel(self, state):
        tmpFiles = self.currentTest.listTmpFiles()
        tmpIter = self.model.insert_before(None, None)
        self.model.set_value(tmpIter, 0, "Temporary Files")
        self.addStandardFilesUnderIter(state, tmpIter, tmpFiles)
        
    def getRootIterAndColour(self, heading, rootDir=None):
        if not rootDir:
            rootDir = self.currentTest.getDirectory()
        headerRow = [ heading + " Files", "white", rootDir, None, "", "" ]
        stditer = self.model.insert_before(None, None, headerRow)
        colour =  guiConfig.getCompositeValue("file_colours", "static_" + heading.lower(), defaultKey="static")
        return stditer, colour
    
    def addStaticFilesWithHeading(self, heading, stdFiles):
        stditer, colour = self.getRootIterAndColour(heading)
        for file in stdFiles:
            self.addFileToModel(stditer, file, colour)

    def addStaticFilesToModel(self, state):
        stdFiles, defFiles = self.currentTest.listStandardFiles(allVersions=True)
        if self.currentTest.classId() == "test-case":
            self.addStaticFilesWithHeading("Standard", stdFiles)

        self.addStaticFilesWithHeading("Definition", defFiles)
        self.addStaticDataFilesToModel()
        self.addExternallyEditedFilesToModel()
        self.addExternalFilesToModel()

    def getExternalDataFiles(self):
        try:
            return self.currentTest.app.extraReadFiles(self.currentTest).items()
        except:
            sys.stderr.write("WARNING - ignoring exception thrown by '" + self.currentTest.getConfigValue("config_module") + \
                             "' configuration while requesting extra data files, not displaying any such files")
            plugins.printException()
            return seqdict()
        
    def addStaticDataFilesToModel(self):
        if len(self.currentTest.getDataFileNames()) == 0:
            return
        datiter, colour = self.getRootIterAndColour("Data")
        self.addDataFilesUnderIter(datiter, self.currentTest.listDataFiles(), colour, self.currentTest.getDirectory())

    def addExternalFilesToModel(self):
        externalFiles = self.getExternalDataFiles()
        if len(externalFiles) == 0:
            return
        datiter, colour = self.getRootIterAndColour("External")
        for name, filelist in externalFiles:
            exiter = self.model.insert_before(datiter, None)
            self.model.set_value(exiter, 0, name)
            self.model.set_value(exiter, 1, "white") # mostly to trigger output...
            for file in filelist:
                self.addFileToModel(exiter, file, colour)

    def addExternallyEditedFilesToModel(self):
        root, files = self.currentTest.listExternallyEditedFiles()
        if root:
            datiter, colour = self.getRootIterAndColour("Externally Edited", root)
            self.addDataFilesUnderIter(datiter, files, colour, root)

    def addDataFilesUnderIter(self, iter, files, colour, root):
        dirIters = { root : iter }
        parentIter = iter
        for file in files:
            parent, local = os.path.split(file)
            parentIter = dirIters.get(parent)
            if parentIter is None:
                subDirIters = self.addDataFilesUnderIter(iter, [ parent ], colour, root)
                parentIter = subDirIters.get(parent)
            newiter = self.addFileToModel(parentIter, file, colour)
            if os.path.isdir(file):
                dirIters[file] = newiter
        return dirIters

class ProgressBarGUI(guiplugins.SubGUI):
    def __init__(self, dynamic, testCount):
        guiplugins.SubGUI.__init__(self)
        self.dynamic = dynamic
        self.totalNofTests = testCount
        self.addedCount = 0
        self.nofCompletedTests = 0
        self.widget = None
        
    def shouldShow(self):
        return self.dynamic
    def shouldDescribe(self):
        return self.dynamic and self.addedCount > 0

    def describe(self):
        guilog.info("Progress bar set to fraction " + str(self.widget.get_fraction()) + ", text '" + self.widget.get_text() + "'")

    def createView(self):
        self.widget = gtk.ProgressBar()
        self.resetBar()
        self.widget.show()
        return self.widget

    def notifyAdd(self, test, initial):
        if test.classId() == "test-case":
            self.addedCount += 1
            if self.addedCount > self.totalNofTests:
                self.totalNofTests += 1
                self.resetBar()
    def notifyAllRead(self, *args):
        # The initial number was told be the static GUI, treat it as a guess
        # Can be wrong in case versions are defined by testsuite files.
        self.totalNofTests = self.addedCount
        self.resetBar()
        self.contentsChanged()

    def notifyLifecycleChange(self, test, state, changeDesc):
        if changeDesc == "complete":
            self.nofCompletedTests += 1
            self.resetBar()
            self.contentsChanged()
    def computeFraction(self):
        if self.totalNofTests > 0:
            return float(self.nofCompletedTests) / float(self.totalNofTests)
        else:
            return 0 # No tests yet, haven't read them in
    
    def resetBar(self):
        if self.widget:
            self.widget.set_text(self.getFractionMessage())
            self.widget.set_fraction(self.computeFraction())

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
class TestProgressMonitor(guiplugins.SubGUI):
    def __init__(self, dynamic, testCount):
        guiplugins.SubGUI.__init__(self)
        self.classifications = {} # map from test to list of iterators where it exists
                
        # Each row has 'type', 'number', 'show', 'tests'
        self.treeModel = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_INT, gobject.TYPE_BOOLEAN, \
                                       gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT)
        self.diag = plugins.getDiagnostics("Progress Monitor")
        self.progressReport = None
        self.treeView = None
        self.dynamic = dynamic
        self.testCount = testCount
        self.diffStore = {}
        # It isn't really a gui configuration, and this could cause bugs when several apps
        # using differnt diff tools are run together. However, this isn't very likely and we prefer not
        # to recalculate all the time...
        diffTool = guiConfig.getValue("text_diff_program")
        self.diffFilterGroup = plugins.TextTriggerGroup(guiConfig.getCompositeValue("text_diff_program_filters", diffTool))
        if testCount > 0:
            colour = guiConfig.getTestColour("not_started")
            visibility = guiConfig.showCategoryByDefault("not_started")
            self.addNewIter("Not started", None, colour, visibility, testCount)
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
        textRenderer.set_property('wrap-width', 350)
        textRenderer.set_property('wrap-mode', pango.WRAP_WORD_CHAR)
        numberRenderer = gtk.CellRendererText()
        numberRenderer.set_property('xalign', 1)
        statusColumn = gtk.TreeViewColumn("Status", textRenderer, text=0, background=3, font=4)
        numberColumn = gtk.TreeViewColumn("Number", numberRenderer, text=1, background=3, font=4)
        statusColumn.set_resizable(True)
        numberColumn.set_resizable(True)
        self.treeView.append_column(statusColumn)
        self.treeView.append_column(numberColumn)
        toggle = gtk.CellRendererToggle()
        toggle.set_property('activatable', True)
        scriptEngine.registerCellToggleButton(toggle, "toggle progress report category", self.treeView)
        toggle.connect("toggled", self.showToggled)
        scriptEngine.monitor("set progress report filter selection to", selection)
        toggleColumn = gtk.TreeViewColumn("Visible", toggle, active=2)
        toggleColumn.set_resizable(True)
        toggleColumn.set_alignment(0.5)
        self.treeView.append_column(toggleColumn)
        self.treeView.show()
        return self.addScrollBars(self.treeView, hpolicy=gtk.POLICY_NEVER)
    def canSelect(self, path):
        pathIter = self.treeModel.get_iter(path)
        return self.treeModel.get_value(pathIter, 2)
    def notifyAdd(self, test, initial):
        if self.dynamic and test.classId() == "test-case":
            incrementCount = self.testCount == 0
            self.insertTest(test, test.state, incrementCount)
            if incrementCount:
                self.contentsChanged()
    def notifyAllRead(self, *args):
        # Fix the not started count in case the initial guess was wrong
        if self.testCount > 0:
            self.diag.info("Reading complete, updating not-started count to actual answer")
            iter = self.treeModel.get_iter_root()
            self.treeModel.set_value(iter, 1, len(self.treeModel.get_value(iter, 5)))
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

    def filterDiff(self, test, diff):
        filteredDiff = ""
        for line in diff.split("\n"):
            if self.diffFilterGroup.stringContainsText(line):
                filteredDiff += line + "\n"
        return filteredDiff
    
    def getClassifiers(self, test, state):
        classifiers = ClassificationTree()
        catDesc = self.getCategoryDescription(state)
        if state.isMarked():
            if state.briefText == catDesc:
                # Just in case - otherwise we get an infinite loop...
                classifiers.addClassification([ catDesc, "Marked as Marked" ])
            else:
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

        comparisons = state.getComparisons()
        for fileComp in filter(lambda c: c.getType() == "failure", comparisons):
            summary = fileComp.getSummary(includeNumbers=False)
            fileClass = [ "Failed", "Differences", summary ]

            filteredDiff = self.filterDiff(test, fileComp.getFreeTextBody())
            summaryDiffs = self.diffStore.setdefault(summary, seqdict())
            testList = summaryDiffs.setdefault(filteredDiff, [])
            if test not in testList:
                testList.append(test)
            if len(summaryDiffs.get(filteredDiff)) > 1:
                group = summaryDiffs.index(filteredDiff) + 1
                fileClass.append("Group " + str(group))
            self.diag.info("Adding file classification for " + repr(fileComp) + " = " + repr(fileClass))
            classifiers.addClassification(fileClass)
            
        for fileComp in filter(lambda c: c.getType() != "failure", comparisons):
            summary = fileComp.getSummary(includeNumbers=False)
            fileClass = [ "Failed", "Performance differences", self.getCategoryDescription(state, summary) ]
            self.diag.info("Adding file classification for " + repr(fileComp) + " = " + repr(fileClass))
            classifiers.addClassification(fileClass)
            
        return classifiers
    
    def removeFromModel(self, test):
        for iter in self.findTestIterators(test):
            testCount = self.treeModel.get_value(iter, 1)
            self.treeModel.set_value(iter, 1, testCount - 1)
            if testCount == 1:
                self.treeModel.set_value(iter, 3, "white")
                self.treeModel.set_value(iter, 4, "")
            allTests = self.treeModel.get_value(iter, 5)
            allTests.remove(test)
            self.diag.info("Removing test " + repr(test) + " from node " + self.treeModel.get_value(iter, 0))
            self.treeModel.set_value(iter, 5, allTests)

    def removeFromDiffStore(self, test):
        for fileInfo in self.diffStore.values():
            for testList in fileInfo.values():
                if test in testList:
                    testList.remove(test)
                    
    def insertTest(self, test, state, incrementCount):
        self.classifications[test] = []
        classifiers = self.getClassifiers(test, state)
        nodeClassifier = classifiers.keys()[0]
        defaultColour, defaultVisibility = self.getCategorySettings(state.category, nodeClassifier, classifiers)
        return self.addTestForNode(test, defaultColour, defaultVisibility, nodeClassifier, classifiers, incrementCount)
    def getCategorySettings(self, category, nodeClassifier, classifiers):
        # Use the category description if there is only one level, otherwise rely on the status names
        if len(classifiers.get(nodeClassifier)) == 0 or category == "failure":
            return guiConfig.getTestColour(category), guiConfig.showCategoryByDefault(category)
        else:
            return None, True
    def updateTestAppearance(self, test, state, changeDesc, colour):
        resultType, summary = state.getTypeBreakdown()
        catDesc = self.getCategoryDescription(state, resultType)
        mainColour = guiConfig.getTestColour(catDesc, guiConfig.getTestColour(resultType))
        # Don't change suite states when unmarking tests
        updateSuccess = state.hasSucceeded() and changeDesc != "unmarked"
        saved = changeDesc.find("save") != -1
        self.notify("TestAppearance", test, summary, mainColour, colour, updateSuccess, saved)
        self.notify("Visibility", [ test ], self.shouldBeVisible(test))

    def getInitialTestsForNode(self, test, parentIter, nodeClassifier):
        try:
            if nodeClassifier.startswith("Group "):
                diffNumber = int(nodeClassifier[6:]) - 1 
                parentName = self.treeModel.get_value(parentIter, 0)
                testLists = self.diffStore.get(parentName)
                return copy(testLists.values()[diffNumber])
        except ValueError:
            pass
        return [ test ]
    
    def addTestForNode(self, test, defaultColour, defaultVisibility, nodeClassifier, classifiers, incrementCount, parentIter=None):
        nodeIter = self.findIter(nodeClassifier, parentIter)
        colour = guiConfig.getTestColour(nodeClassifier, defaultColour)
        visibility = guiConfig.showCategoryByDefault(nodeClassifier, defaultVisibility)
        if nodeIter:
            self.diag.info("Adding " + repr(test) + " for node " + nodeClassifier + ", visible = " + repr(visibility))
            self.insertTestAtIter(nodeIter, test, colour, incrementCount)
            self.classifications[test].append(nodeIter)
        else:
            initialTests = self.getInitialTestsForNode(test, parentIter, nodeClassifier)
            nodeIter = self.addNewIter(nodeClassifier, parentIter, colour, visibility, len(initialTests), initialTests)
            for initTest in initialTests:
                self.diag.info("New node " + nodeClassifier + ", visible = " + repr(visibility) + " : add " + repr(initTest))
                self.classifications[initTest].append(nodeIter)

        subColours = []
        for subNodeClassifier in classifiers[nodeClassifier]:
            subColour = self.addTestForNode(test, colour, visibility, subNodeClassifier, classifiers, incrementCount, nodeIter)
            subColours.append(subColour)
            
        if len(subColours) > 0:
            return subColours[0]
        else:
            return colour
    def insertTestAtIter(self, iter, test, colour, incrementCount):
        allTests = self.treeModel.get_value(iter, 5)
        testCount = self.treeModel.get_value(iter, 1)
        if testCount == 0:
            self.treeModel.set_value(iter, 3, colour)
            self.treeModel.set_value(iter, 4, "bold")
        if incrementCount:
            self.treeModel.set_value(iter, 1, testCount + 1)
        self.diag.info("Tests for node " + self.treeModel.get_value(iter, 0) + " " + repr(allTests))
        allTests.append(test)
        self.treeModel.set_value(iter, 5, allTests)
        self.diag.info("Tests for node " + self.treeModel.get_value(iter, 0) + " " + repr(allTests))
    def addNewIter(self, classifier, parentIter, colour, visibility, testCount, tests=[]):
        modelAttributes = [classifier, testCount, visibility, colour, "bold", tests]
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
    def notifyLifecycleChange(self, test, state, changeDesc):
        self.removeFromModel(test)
        if changeDesc.find("save") != -1:
            self.removeFromDiffStore(test)
        colourInserted = self.insertTest(test, state, incrementCount=True)
        self.updateTestAppearance(test, state, changeDesc, colourInserted)
        self.contentsChanged()

    def removeParentIters(self, iters):
        noParents = []
        for iter1 in iters:
            if not self.isParent(iter1, iters):
                noParents.append(iter1)
        return noParents

    def isParent(self, iter1, iters):
        path1 = self.treeModel.get_path(iter1)
        for iter2 in iters:
            parent = self.treeModel.iter_parent(iter2)
            if parent is not None and self.treeModel.get_path(parent) == path1:
                return True
        return False

    def shouldBeVisible(self, test):
        iters = self.findTestIterators(test)
        # ignore the parent nodes where visibility is concerned
        visibilityIters = self.removeParentIters(iters)
        self.diag.info("Visibility for " + repr(test) + " : iters " + repr(map(self.treeModel.get_path, visibilityIters)))
        for nodeIter in visibilityIters:
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
            visible = self.treeModel.get_value(childIter, 2)
            bg = self.treeModel.get_value(childIter, 3)
            font = self.treeModel.get_value(childIter, 4)
            guilog.info(indentation + name + " : " + count + ", colour '" + bg +
                        "', font '" + font + "'" + "', visible=" + repr(visible))
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
        categoryName = self.treeModel.get_value(iter, 0)
        if self.treeModel.get_value(iter, 2) == 1:
            guilog.info("Selecting to show tests in the '" + categoryName + "' category.")
        else:
            guilog.info("Selecting not to show tests in the '" + categoryName + "' category.")
            
        for childIter in self.getAllChildIters(iter):
            self.treeModel.set_value(childIter, 2, newValue)

        if categoryName == "Not started":
            self.notify("DefaultVisibility", newValue)

        changedTests = []
        for test in self.treeModel.get_value(iter, 5):
            if self.shouldBeVisible(test) == newValue:
                changedTests.append(test)
        self.notify("Visibility", changedTests, newValue)
