
"""
GUI for TextTest written with PyGTK. Formerly known as texttestgui.py
Contains the main control code and is the only point of contact with the core framework
"""

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

import gtkusecase, testtree, filetrees, statusviews, textinfo, actionholders, guiplugins, guiutils, plugins, os, logging
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


class GUIController(plugins.Responder, plugins.Observable):
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
        defaultColours = guiplugins.interactiveActionHandler.getColourDictionary(allApps)
        defaultAccelerators = guiplugins.interactiveActionHandler.getDefaultAccelerators(allApps)
        guiConfig = guiutils.GUIConfig(self.dynamic, allApps, defaultColours, defaultAccelerators, guilog)

        guiutils.guilog = guilog
        guiutils.scriptEngine = scriptEngine
        guiutils.guiConfig = guiConfig

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
        return [ guiutils.guiConfig, self.testColumnGUI, self.appFileGUI ] + actionObservers + \
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
        menuNames = guiplugins.interactiveActionHandler.getMenuNames(allApps)
        menu = actionholders.MenuBarGUI(allApps, self.dynamic, vanilla, uiManager, self.allActionGUIs(), menuNames)
        toolbar = actionholders.ToolBarGUI(uiManager, self.progressBarGUI)
        testPopup, testFilePopup = actionholders.createPopupGUIs(uiManager)
        return menu, toolbar, testPopup, testFilePopup

    def createRightWindowGUI(self):
        testTab = PaneGUI(self.testFileGUI, self.textInfoGUI, horizontal=False)
        runInfoTab = PaneGUI(self.runInfoGUI, self.testRunInfoGUI, horizontal=False)
        tabGUIs = [ self.appFileGUI, testTab, self.progressMonitor, runInfoTab ] + self.actionTabGUIs
        return actionholders.ChangeableNotebookGUI(tabGUIs)

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

class TopWindowGUI(guiutils.ContainerGUI):
    EXIT_NOTIFIED = 1
    COMPLETION_NOTIFIED = 2
    def __init__(self, contentGUI, dynamic, allApps):
        guiutils.ContainerGUI.__init__(self, [ contentGUI ])
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


class ShortcutBarGUI(guiutils.SubGUI):
    def getWidgetName(self):
        return "_Shortcut bar"
    def createView(self):
        self.widget = scriptEngine.createShortcutBar()
        self.widget.set_name(self.getWidgetName().replace("_", ""))
        self.widget.show()
        return self.widget
    

class VBoxGUI(guiutils.ContainerGUI):    
    def createView(self):
        box = gtk.VBox()
        expandWidgets = [ gtk.HPaned, gtk.ScrolledWindow ]
        for subgui in self.subguis:
            view = subgui.createView()
            expand = view.__class__ in expandWidgets
            box.pack_start(view, expand=expand, fill=expand)

        box.show()
        return box


class PaneGUI(guiutils.ContainerGUI):
    def __init__(self, gui1, gui2 , horizontal, shrink=True):
        guiutils.ContainerGUI.__init__(self, [ gui1, gui2 ])
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
