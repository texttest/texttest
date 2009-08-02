#!/usr/bin/env python

# GUI for TextTest written with PyGTK
# First make sure we can import the GUI modules: if we can't, throw appropriate exceptions

import texttest_version

def raiseException(msg):
    from plugins import TextTestError
    raise TextTestError, "Could not start TextTest " + texttest_version.version + " GUI due to PyGTK GUI library problems :\n" + msg

try:
    import gtk
except Exception, e:
    raiseException("Unable to import module 'gtk' - " + str(e))

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

import gtkusecase, pango, testtree, filetrees, statusviews, textinfo, guiplugins, plugins, os, sys, logging
from ndict import seqdict
from copy import copy


class IdleHandlerManager:
    def __init__(self):
        self.sourceId = -1
        self.diag = logging.getLogger("Idle Handlers")
    def notifyActionStart(self, message="", lock=True):
        # To make it possible to have an while-events-process loop
        # to update the GUI during actions, we need to make sure the idle
        # process isn't run. We hence remove that for a while here ...
        if lock:
            self.disableHandler()
            scriptEngine.replayer.disableIdleHandlers()

    def shouldShow(self):
        return True # nothing to show, but we need to observe...

    def notifyActionProgress(self, *args):
        if self.sourceId >= 0:
            raise plugins.TextTestError, "No Action currently exists to have progress on!"

    def notifyActionStop(self, *args):
        # Activate idle function again, see comment in notifyActionStart
        self.enableHandler()
        scriptEngine.replayer.reenableIdleHandlers()

    def addSuites(self, *args):
        self.enableHandler()

    def enableHandler(self):
        if self.sourceId == -1:
            # Same priority as PyUseCase replay, so they get called interchangeably
            # Non-default as a workaround for bugs in filechooser handling in GTK
            self.sourceId = plugins.Observable.threadedNotificationHandler.enablePoll(gobject.idle_add,
                                                                                      priority=gtkusecase.PRIORITY_PYUSECASE_IDLE)
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


class TextTestGUI(plugins.Responder, plugins.Observable):
    scriptEngine = None
    def __init__(self, optionMap, allApps):
        vanilla = optionMap.has_key("vanilla")
        self.readGtkRCFiles(vanilla)
        self.dynamic = not optionMap.has_key("gx")
        self.setUpGlobals(allApps)
        plugins.Responder.__init__(self)
        plugins.Observable.__init__(self)
        testCount = int(optionMap.get("count", 0))

        self.appFileGUI = filetrees.ApplicationFileGUI(self.dynamic, allApps)
        self.textInfoGUI = textinfo.TextInfoGUI()
        self.runInfoGUI = textinfo.RunInfoGUI(self.dynamic)
        self.testRunInfoGUI = textinfo.TestRunInfoGUI(self.dynamic)
        self.progressMonitor = statusviews.TestProgressMonitor(self.dynamic, testCount)
        self.progressBarGUI = statusviews.ProgressBarGUI(self.dynamic, testCount)
        self.idleManager = IdleHandlerManager()
        uiManager = gtk.UIManager()
        self.defaultActionGUIs, self.actionTabGUIs = \
                                guiplugins.interactiveActionHandler.getPluginGUIs(self.dynamic, allApps, uiManager)
        self.menuBarGUI, self.toolBarGUI, testPopupGUI, testFilePopupGUI = self.createMenuAndToolBarGUIs(allApps, vanilla, uiManager)
        self.testColumnGUI = testtree.TestColumnGUI(self.dynamic, testCount)
        self.testTreeGUI = testtree.TestTreeGUI(self.dynamic, allApps, testPopupGUI, self.testColumnGUI)
        self.testFileGUI = filetrees.TestFileGUI(self.dynamic, testFilePopupGUI)
        self.rightWindowGUI = self.createRightWindowGUI()
        self.shortcutBarGUI = ShortcutBarGUI()
        self.statusMonitor = statusviews.StatusMonitorGUI()

        self.topWindowGUI = self.createTopWindowGUI(allApps)

    def setUpGlobals(self, allApps):
        global guilog, guiConfig, scriptEngine
        scriptEngine = self.scriptEngine
        guilog = logging.getLogger("gui log")
        guiConfig = guiplugins.GUIConfig(self.dynamic, allApps, guilog)

        guiplugins.guilog = guilog
        guiplugins.scriptEngine = scriptEngine
        guiplugins.guiConfig = guiConfig

    def getTestTreeObservers(self):
        return [ self.testColumnGUI, self.testFileGUI, self.textInfoGUI, self.testRunInfoGUI ] + self.allActionGUIs() + [ self.rightWindowGUI ]
    def allActionGUIs(self):
        return self.defaultActionGUIs + self.actionTabGUIs
    def getLifecycleObservers(self):
        # only the things that want to know about lifecycle changes irrespective of what's selected,
        # otherwise we go via the test tree. Include add/remove as lifecycle, also final completion
        return [ self.progressBarGUI, self.progressMonitor, self.testTreeGUI,
                 self.statusMonitor, self.runInfoGUI, self.idleManager, self.topWindowGUI ]
    def getActionObservers(self):
        return [ self.testTreeGUI, self.testFileGUI, self.statusMonitor, self.runInfoGUI, 
                 self.idleManager, self.topWindowGUI ]

    def getFileViewObservers(self):
        observers = self.defaultActionGUIs + self.actionTabGUIs
        if self.dynamic:
            observers.append(self.textInfoGUI)
        return observers
    
    def isFrameworkExitObserver(self, obs):
        return hasattr(obs, "notifyExit") or hasattr(obs, "notifyKillProcesses")
    def getExitObservers(self, frameworkObservers):
        # Don't put ourselves in the observers twice or lots of weird stuff happens.
        # Important that closing the GUI is the last thing to be done, so make sure we go at the end...
        frameworkExitObservers = filter(self.isFrameworkExitObserver, frameworkObservers)
        return self.defaultActionGUIs + [ guiplugins.processMonitor, self.statusMonitor, self.testTreeGUI, self.menuBarGUI ] + \
               frameworkExitObservers + [ self.idleManager, self ]
    def getTestColumnObservers(self):
        return [ self.testTreeGUI, self.statusMonitor, self.idleManager ]
    def getHideableGUIs(self):
        return [ self.toolBarGUI, self.shortcutBarGUI, self.statusMonitor ]
    def getAddSuitesObservers(self):
        actionObservers = filter(lambda obs: hasattr(obs, "addSuites"), self.defaultActionGUIs + self.actionTabGUIs)
        return [ guiplugins.guiConfig, self.testColumnGUI, self.appFileGUI ] + actionObservers + \
               [ self.rightWindowGUI, self.topWindowGUI, self.idleManager ]
    def setObservers(self, frameworkObservers):
        # We don't actually have the framework observe changes here, this causes duplication. Just forward
        # them as appropriate to where they belong. This is a bit of a hack really.
        for observer in self.getTestTreeObservers():
            if observer.shouldShow():
                self.testTreeGUI.addObserver(observer)

        for observer in self.getTestColumnObservers():
            self.testColumnGUI.addObserver(observer)

        for observer in self.getFileViewObservers():
            self.testFileGUI.addObserver(observer)
            self.appFileGUI.addObserver(observer)

        # watch for category selections
        self.progressMonitor.addObserver(self.testTreeGUI)
        guiplugins.processMonitor.addObserver(self.statusMonitor)
        self.textInfoGUI.addObserver(self.statusMonitor)
        for observer in self.getLifecycleObservers():
            if observer.shouldShow():
                self.addObserver(observer) # forwarding of test observer mechanism

        actionGUIs = self.allActionGUIs()
        # mustn't send ourselves here otherwise signals get duplicated...
        frameworkObserversToUse = filter(lambda obs: obs is not self, frameworkObservers)
        observers = actionGUIs + self.getActionObservers() + frameworkObserversToUse
        for actionGUI in actionGUIs:
            actionGUI.setObservers(observers)

        for observer in self.getHideableGUIs():
            self.menuBarGUI.addObserver(observer)

        for observer in self.getExitObservers(frameworkObserversToUse):
            self.topWindowGUI.addObserver(observer)

    def readGtkRCFiles(self, vanilla):
        for file in plugins.findDataPaths([ ".gtkrc-2.0" ], vanilla, includePersonal=True):
            gtk.rc_add_default_file(file)

    def addSuites(self, suites):
        for observer in self.getAddSuitesObservers():
            observer.addSuites(suites)

    def shouldShrinkMainPanes(self):
        # If we maximise there is no point in banning pane shrinking: there is nothing to gain anyway and
        # it doesn't seem to work very well :)
        return not self.dynamic or guiConfig.getWindowOption("maximize")

    def createTopWindowGUI(self, allApps):
        mainWindowGUI = PaneGUI(self.testTreeGUI, self.rightWindowGUI, horizontal=True, shrink=self.shouldShrinkMainPanes())
        parts = [ self.menuBarGUI, self.toolBarGUI, mainWindowGUI, self.shortcutBarGUI, self.statusMonitor ]
        boxGUI = VBoxGUI(parts)
        return TopWindowGUI(boxGUI, self.dynamic, allApps)

    def createMenuAndToolBarGUIs(self, allApps, vanilla, uiManager):
        menu = MenuBarGUI(allApps, self.dynamic, vanilla, uiManager, self.allActionGUIs())
        toolbar = ToolBarGUI(uiManager, self.progressBarGUI)
        testPopup = PopupMenuGUI("TestPopupMenu", uiManager)
        testFilePopup = PopupMenuGUI("TestFilePopupMenu", uiManager)
        return menu, toolbar, testPopup, testFilePopup

    def createRightWindowGUI(self):
        testTab = PaneGUI(self.testFileGUI, self.textInfoGUI, horizontal=False)
        runInfoTab = PaneGUI(self.runInfoGUI, self.testRunInfoGUI, horizontal=False)
        tabGUIs = [ self.appFileGUI, testTab, self.progressMonitor, runInfoTab ] + self.actionTabGUIs

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
        test.stateInGui = state
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

    def notifyAdd(self, test, *args, **kwargs):
        test.stateInGui = test.state
        self.notify("Add", test, *args, **kwargs)
    def notifyStatus(self, *args, **kwargs):
        self.notify("Status", *args, **kwargs)
    def notifyRemove(self, test):
        self.notify("Remove", test)
    def notifyAllComplete(self):
        self.notify("AllComplete")

class TopWindowGUI(guiplugins.ContainerGUI):
    EXIT_NOTIFIED = 1
    COMPLETION_NOTIFIED = 2
    def __init__(self, contentGUI, dynamic, allApps):
        guiplugins.ContainerGUI.__init__(self, [ contentGUI ])
        self.dynamic = dynamic
        self.topWindow = None
        self.allApps = copy(allApps)
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

    def addSuites(self, suites):
        for suite in suites:
            if suite.app.fullName() not in [ app.fullName() for app in self.allApps ]:
                self.allApps.append(suite.app)
                self.setWindowTitle()
                
        if not self.topWindow:
            # only do this once, not when new suites are added...
            self.createView()
            
    def createView(self):
        # Create toplevel window to show it all.
        self.topWindow = gtk.Window(gtk.WINDOW_TOPLEVEL)
        try:
            import stockitems
            stockitems.register(self.topWindow)
        except: #pragma : no cover - should never happen
            plugins.printWarning("Failed to register texttest stock icons.")
            plugins.printException()
        self.topWindow.set_icon_from_file(self.getIcon())
        self.setWindowTitle()

        self.topWindow.add(self.subguis[0].createView())
        self.adjustSize()
        self.topWindow.show()
        self.topWindow.set_default_size(-1, -1)

        self.notify("TopWindow", self.topWindow)
        scriptEngine.connect("close window", "delete_event", self.topWindow, self.notifyQuit)
        return self.topWindow

    def setWindowTitle(self):
        allAppNames = [ repr(app) for app in self.allApps ]
        appNameDesc = ",".join(allAppNames)
        if self.dynamic:
            checkoutTitle = self.getCheckoutTitle()
            self.topWindow.set_title("TextTest dynamic GUI : testing " + appNameDesc + checkoutTitle + \
                                     " (started at " + plugins.startTimeString() + ")")
        else:
            if len(appNameDesc) > 0:
                appNameDesc = " for " + appNameDesc
            self.topWindow.set_title("TextTest static GUI : management of tests" + appNameDesc)

    def getIcon(self):
        imageDir = plugins.installationDir("images")
        if self.dynamic:
            return os.path.join(imageDir, "texttest-icon-dynamic.jpg")
        else:
            return os.path.join(imageDir, "texttest-icon-static.jpg")

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
            self.notify("Status", "Waiting for all tests to terminate ...")
            # When they have, we'll get notifyAllComplete

    def notifyAnnotate(self, annotation):
        self.topWindow.set_title("TextTest dynamic GUI : " + annotation)
        guilog.info("Top Window title is " + self.topWindow.get_title())

    def terminate(self):
        self.notify("Exit")
        self.topWindow.destroy()

    def adjustSize(self):
        if guiConfig.getWindowOption("maximize"):
            self.topWindow.maximize()
            guilog.info("Maximising top window...")
        else:
            width, widthDescriptor = self.getWindowDimension("width")
            height, heightDescriptor  = self.getWindowDimension("height")
            self.topWindow.set_default_size(width, height)
            guilog.info(widthDescriptor)
            guilog.info(heightDescriptor)

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
    def __init__(self, allApps, dynamic, vanilla, uiManager, actionGUIs):
        guiplugins.SubGUI.__init__(self)
        # Create GUI manager, and a few default action groups
        self.menuNames = guiplugins.interactiveActionHandler.getMenuNames(allApps)
        self.dynamic = dynamic
        self.vanilla = vanilla
        self.uiManager = uiManager
        self.actionGUIs = actionGUIs
        self.actionGroup = self.uiManager.get_action_groups()[0]
        self.toggleActions = []
        self.diag = logging.getLogger("Menu Bar")
    def shouldHide(self, name):
        return guiConfig.getCompositeValue("hide_gui_element", name, modeDependent=True)
    def toggleVisibility(self, action, observer, *args):
        widget = observer.widget
        oldVisible = widget.get_property('visible')
        newVisible = action.get_active()
        if oldVisible and not newVisible:
            widget.hide()
        elif newVisible and not oldVisible:
            widget.show()
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
    
    def notifyTopWindow(self, window):
        window.add_accel_group(self.uiManager.get_accel_group())
        if self.shouldHide("menubar"):
            self.widget.hide()
        for toggleAction in self.toggleActions:
            if self.shouldHide(toggleAction.get_name()):
                toggleAction.set_active(False)

    def getGUIDescriptionFileNames(self):
        allFiles = plugins.findDataPaths([ "*.xml" ], self.vanilla, includePersonal=True)
        self.diag.info("All description files : " + repr(allFiles))
        # Pick up all GUI descriptions corresponding to modules we've loaded
        loadFiles = filter(self.shouldLoad, allFiles)
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
        packageName = ".".join(__name__.split(".")[:-1])
        return sys.modules.has_key(moduleName) or sys.modules.has_key(packageName + "." + moduleName)
    

class ToolBarGUI(guiplugins.ContainerGUI):
    def __init__(self, uiManager, subgui):
        guiplugins.ContainerGUI.__init__(self, [ subgui ])
        self.uiManager = uiManager
    def getWidgetName(self):
        return "_Toolbar"
    def ensureVisible(self, toolbar):
        for item in toolbar.get_children():
            item.set_is_important(True) # Or newly added children without stock ids won't be visible in gtk.TOOLBAR_BOTH_HORIZ style
    def shouldShow(self):
        return True # don't care about whether we have a progress bar or not
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


class PopupMenuGUI(guiplugins.SubGUI):
    def __init__(self, name, uiManager):
        guiplugins.SubGUI.__init__(self)
        self.name = name
        self.uiManager = uiManager
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
        self.widget.set_name(self.getWidgetName().replace("_", ""))
        self.widget.show()
        return self.widget
    


class VBoxGUI(guiplugins.ContainerGUI):    
    def createView(self):
        box = gtk.VBox()
        expandWidgets = [ gtk.HPaned, gtk.ScrolledWindow ]
        for subgui in self.subguis:
            view = subgui.createView()
            expand = view.__class__ in expandWidgets
            box.pack_start(view, expand=expand, fill=expand)

        box.show()
        return box


class NotebookGUI(guiplugins.SubGUI):
    def __init__(self, tabInfo, scriptTitle):
        guiplugins.SubGUI.__init__(self)
        self.scriptTitle = scriptTitle
        self.diag = logging.getLogger("GUI notebook")
        self.tabInfo = tabInfo
        self.notebook = None
        tabName, self.currentTabGUI = self.findInitialCurrentTab()
        self.diag.info("Current page set to '" + tabName + "'")

    def findInitialCurrentTab(self):
        return self.tabInfo[0]

    def createView(self):
        self.notebook = gtk.Notebook()
        for tabName, tabGUI in self.tabInfo:
            label = gtk.Label(tabName)
            page = self.createPage(tabGUI, tabName)
            self.notebook.append_page(page, label)

        scriptEngine.monitorNotebook(self.notebook, self.scriptTitle)
        self.notebook.set_scrollable(True)
        self.notebook.show()
        return self.notebook

    def createPage(self, tabGUI, tabName):
        self.diag.info("Adding page " + tabName)
        return tabGUI.createView()

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
        for page in self.notebook.get_children():
            if page.get_property("visible"):
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
        self.diag.info("New selection with " + repr(tests) + ", adjusting '" + self.scriptTitle + "'")
        # only change pages around if a test is directly selected
        self.updatePages(rowCount=rowCount, changeCurrentPage=direct)

    def updatePages(self, test=None, state=None, rowCount=0, changeCurrentPage=False):
        if not self.notebook:
            return
        pagesShown = self.showNewPages(test, state)
        pagesHidden = self.hideOldPages(test, state)
        if changeCurrentPage:
            self.updateCurrentPage(rowCount)

    def notifyLifecycleChange(self, test, state, changeDesc):
        self.updatePages(test, state)

    def addSuites(self, suites):
        self.updatePages()



class PaneGUI(guiplugins.ContainerGUI):
    def __init__(self, gui1, gui2 , horizontal, shrink=True):
        guiplugins.ContainerGUI.__init__(self, [ gui1, gui2 ])
        self.horizontal = horizontal
        self.panedTooltips = gtk.Tooltips()
        self.paned = None
        self.separatorHandler = None
        self.position = 0
        self.maxPosition = 0
        self.shrink = shrink

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
            frame = gtk.Frame()
            frame.set_shadow_type(gtk.SHADOW_IN)
            frame.add(subgui.createView())
            frame.show()
            frames.append(frame)

        self.paned.pack1(frames[0], resize=True)
        self.paned.pack2(frames[1], resize=True)
        self.paned.show()
        return self.paned

    def adjustSeparator(self, *args):
        self.initialMaxSize = self.paned.get_property("max-position")
        self.paned.child_set_property(self.paned.get_child1(), "shrink", self.shrink)
        self.paned.child_set_property(self.paned.get_child2(), "shrink", self.shrink)
        self.position = int(self.initialMaxSize * self.getSeparatorPositionFromConfig())

        self.paned.set_position(self.position)
        # Only want to do this once, when we're visible...
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
