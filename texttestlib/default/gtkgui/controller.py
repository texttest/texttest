
"""
GUI for TextTest written with PyGTK. Formerly known as texttestgui.py
Contains the main control code and is the only point of contact with the core framework
"""

# First make sure we can import the GUI modules: if we can't, throw appropriate exceptions

from texttestlib import texttest_version
from functools import reduce


def raiseException(msg):
    from texttestlib.plugins import TextTestError
    raise TextTestError("Could not start TextTest " + texttest_version.version +
                        " GUI due to PyGI/PyGObject GUI library problems :\n" + msg)


try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
except Exception as e:
    raiseException("Unable to import PyGI module 'Gtk' - " + str(e))

pygtkVersion = (Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version())
requiredPygtkVersion = texttest_version.required_pygtk_version
if pygtkVersion < requiredPygtkVersion:
    raiseException("TextTest " + texttest_version.version + " GUI requires at least PyGTK " +
                   ".".join(map(str, requiredPygtkVersion)) + ": found version " +
                   ".".join(map(str, pygtkVersion)))

try:
    from gi.repository import GObject
except Exception as e:
    raiseException("Unable to import module 'gobject' - " + str(e))

from . import testtree, filetrees, statusviews, textinfo, actionholders, version_control, guiplugins, guiutils
import os
import sys
import logging
from texttestlib import plugins
from copy import copy
from collections import OrderedDict
from texttestlib.default.gtkgui.guiplugins import CloseWindowCancelException


class IdleHandlerManager:
    def __init__(self):
        self.diag = logging.getLogger("Idle Handlers")

    def notifyActionStart(self, lock=True):
        # To make it possible to have an while-events-process loop
        # to update the GUI during actions, we need to make sure the idle
        # process isn't run. We hence remove that for a while here ...
        if lock:
            self.disableHandler()

    def shouldShow(self):
        return True  # nothing to show, but we need to observe...

    def notifyActionProgress(self, *args):
        if plugins.Observable.threadedNotificationHandler.idleHandler is not None:
            raise plugins.TextTestError("No Action currently exists to have progress on!")

    def notifyActionStop(self, *args):
        # Activate idle function again, see comment in notifyActionStart
        self.enableHandler()

    def addSuites(self, *args):
        self.enableHandler()

    def getIdlePriority(self):
        try:
            # this should be removed after storytext got ported! MB 2018-12-05
            raise ImportError()
            # Same priority as StoryText replay, so they get called interchangeably
            # Non-default as a workaround for bugs in filechooser handling in GTK
            from storytext.gtktoolkit import PRIORITY_STORYTEXT_IDLE
            return PRIORITY_STORYTEXT_IDLE
        except ImportError:
            # It should still work if we can't find StoryText
            # so we hardcode the right answer...
            return GObject.PRIORITY_DEFAULT_IDLE + 20

    def enableHandler(self):
        if plugins.Observable.threadedNotificationHandler.idleHandler is None:
            plugins.Observable.threadedNotificationHandler.enablePoll(GObject.idle_add, priority=self.getIdlePriority())
            self.diag.info("Adding idle handler")

    def disableHandler(self):
        if plugins.Observable.threadedNotificationHandler.idleHandler is not None:
            self.diag.info("Removing idle handler")
            plugins.Observable.threadedNotificationHandler.disablePoll(GObject.source_remove)

    def notifyWindowClosed(self):
        if plugins.Observable.threadedNotificationHandler.idleHandler is not None:
            plugins.Observable.threadedNotificationHandler.blockEventsExcept(["Complete", "AllComplete"])

    def notifyExit(self):
        self.disableHandler()


class GUIController(plugins.Responder, plugins.Observable):
    def __init__(self, optionMap, allApps):
        includeSite, includePersonal = optionMap.configPathOptions()
        self.readGtkRCFiles(includeSite, includePersonal)
        self.dynamic = "gx" not in optionMap
        self.initialApps = self.storeInitial(allApps)
        self.interactiveActionHandler = InteractiveActionHandler(self.dynamic, allApps, optionMap)
        self.setUpGlobals(allApps, includePersonal)
        self.shortcutBarGUI = ShortcutBarGUI(includeSite, includePersonal)
        plugins.Responder.__init__(self)
        plugins.Observable.__init__(self)
        testCount = int(optionMap.get("count", 0))
        initialStatus = "TextTest started at " + plugins.localtime() + "."
        # This is perhaps not an ideal design, throwing up the application creation dialog from the middle of a constructor.
        # Would possibly be better to move this, and all the code below, to a later call
        # At the moment that would be setObservers, not fantastic as a side-effect there either
        # Perhaps an entirely new call would be needed? [GB 20130524]
        if len(allApps) == 0:
            newApp, initialStatus = self.createNewApplication(optionMap)
            allApps.append(newApp)

        self.statusMonitor = statusviews.StatusMonitorGUI(initialStatus)
        self.textInfoGUI = textinfo.TextInfoGUI(self.dynamic)
        runName = optionMap.get("name", "").replace("<time>", plugins.startTimeString())
        reconnect = "reconnect" in optionMap
        self.runInfoGUI = textinfo.RunInfoGUI(self.dynamic, runName, reconnect)
        self.testRunInfoGUI = textinfo.TestRunInfoGUI(self.dynamic, reconnect)
        self.progressMonitor = statusviews.TestProgressMonitor(self.dynamic, testCount)
        self.progressBarGUI = statusviews.ProgressBarGUI(self.dynamic, testCount)
        self.idleManager = IdleHandlerManager()
        uiManager = Gtk.UIManager()
        self.defaultActionGUIs, self.actionTabGUIs = self.interactiveActionHandler.getPluginGUIs(uiManager)
        self.menuBarGUI, self.toolBarGUI, testPopupGUI, testFilePopupGUI, appFilePopupGUI = self.createMenuAndToolBarGUIs(
            uiManager, includeSite, includePersonal)
        self.testColumnGUI = testtree.TestColumnGUI(self.dynamic, testCount)
        self.testTreeGUI = testtree.TestTreeGUI(self.dynamic, allApps, testPopupGUI, self.testColumnGUI)
        self.testFileGUI = filetrees.TestFileGUI(self.dynamic, testFilePopupGUI)
        self.appFileGUI = filetrees.ApplicationFileGUI(self.dynamic, allApps, appFilePopupGUI)
        self.rightWindowGUI = self.createRightWindowGUI()

        self.topWindowGUI = self.createTopWindowGUI(allApps, runName, optionMap.get("rerun"))

    def createNewApplication(self, optionMap):
        from .default_gui import ImportApplication
        return ImportApplication([], False, optionMap).runDialog()

    def storeInitial(self, allApps):
        initial = set()
        for app in allApps:
            initial.add(app)
            initial.update(set(app.extras))
        return initial

    def setUpGlobals(self, allApps, includePersonal):
        global guiConfig
        defaultColours = self.interactiveActionHandler.getColourDictionary()
        defaultAccelerators = self.interactiveActionHandler.getDefaultAccelerators()
        guiConfig = guiutils.GUIConfig(self.dynamic, allApps, defaultColours, defaultAccelerators, includePersonal)
        self.setUpEntryCompletion(guiConfig)

        for module in [guiutils, guiplugins]:
            module.guiConfig = guiConfig

    def setUpEntryCompletion(self, guiConfig):
        matching = guiConfig.getValue("gui_entry_completion_matching")
        if matching != 0:
            inline = guiConfig.getValue("gui_entry_completion_inline")
            completions = guiConfig.getCompositeValue("gui_entry_completions", "", modeDependent=True)
            from .entrycompletion import manager
            manager.start(matching, inline, completions)

    def getTestTreeObservers(self):
        return [self.testColumnGUI, self.textInfoGUI, self.testFileGUI, self.testRunInfoGUI] + \
            self.allActionGUIs() + [self.rightWindowGUI]

    def allActionGUIs(self):
        return self.defaultActionGUIs + self.actionTabGUIs

    def getLifecycleObservers(self):
        # only the things that want to know about lifecycle changes irrespective of what's selected,
        # otherwise we go via the test tree. Include add/remove as lifecycle, also final completion
        return [self.progressBarGUI, self.progressMonitor, self.textInfoGUI.timeMonitor, self.testTreeGUI,
                self.statusMonitor, self.runInfoGUI, self.idleManager, self.topWindowGUI] + \
            [obs for obs in self.defaultActionGUIs if hasattr(obs, "notifyAllComplete")]

    def getActionObservers(self):
        return [self.progressMonitor, self.testTreeGUI, self.testFileGUI, self.appFileGUI, self.statusMonitor,
                self.runInfoGUI, self.idleManager, self.topWindowGUI]

    def getFileViewObservers(self):
        return self.defaultActionGUIs + self.actionTabGUIs + [self.textInfoGUI]

    def getProgressMonitorObservers(self):
        return [self.testTreeGUI, self.testFileGUI]

    def getProcessMonitorObservers(self):
        return [self.statusMonitor, self.appFileGUI] + self.defaultActionGUIs

    def isFrameworkExitObserver(self, obs):
        return hasattr(obs, "notifyExit") or hasattr(obs, "notifyKillProcesses")

    def getExitObservers(self, frameworkObservers):
        # Don't put ourselves in the observers twice or lots of weird stuff happens.
        # Important that closing the GUI is the last thing to be done, so make sure we go at the end...
        frameworkExitObservers = list(filter(self.isFrameworkExitObserver, frameworkObservers))
        return [self.statusMonitor] + self.defaultActionGUIs + [guiplugins.processMonitor, self.testTreeGUI, self.menuBarGUI] + \
            frameworkExitObservers + [self.idleManager, self]

    def getTestColumnObservers(self):
        return [self.testTreeGUI, self.statusMonitor, self.idleManager]

    def getHideableGUIs(self):
        return [self.toolBarGUI, self.shortcutBarGUI, self.statusMonitor]

    def getAddSuitesObservers(self):
        actionObservers = [obs for obs in self.allActionGUIs() if hasattr(obs, "addSuites")]
        return [guiutils.guiConfig, self.testColumnGUI, self.appFileGUI] + actionObservers + \
               [self.rightWindowGUI, self.topWindowGUI, self.idleManager]

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

        for observer in self.getProgressMonitorObservers():
            self.progressMonitor.addObserver(observer)

        for observer in self.getProcessMonitorObservers():
            guiplugins.processMonitor.addObserver(observer)

        self.textInfoGUI.addObserver(self.statusMonitor)
        for observer in self.getLifecycleObservers():
            if observer.shouldShow():
                self.addObserver(observer)  # forwarding of test observer mechanism

        actionGUIs = self.allActionGUIs()
        # mustn't send ourselves here otherwise signals get duplicated...
        frameworkObserversToUse = [obs for obs in frameworkObservers if obs is not self]
        observers = actionGUIs + self.getActionObservers() + frameworkObserversToUse
        for actionGUI in actionGUIs:
            actionGUI.setObservers(observers)

        for observer in self.getHideableGUIs():
            self.menuBarGUI.addObserver(observer)

        for observer in self.getExitObservers(frameworkObserversToUse):
            self.topWindowGUI.addObserver(observer)

    def readGtkRCFiles(self, *args):
        for file in plugins.findDataPaths([".gtkrc-2.0*"], *args):
            Gtk.rc_parse(file)

    def addSuites(self, suites):
        for observer in self.getAddSuitesObservers():
            observer.addSuites(suites)

        currApps = set([suite.app for suite in suites])
        newApps = currApps.difference(self.initialApps)
        self.updateValidApps(newApps)

    def updateValidApps(self, newApps):
        for actionGUI in self.allActionGUIs():
            for app in newApps:
                actionGUI.checkValid(app)

    def shouldShrinkMainPanes(self):
        # If we maximise there is no point in banning pane shrinking: there is nothing to gain anyway and
        # it doesn't seem to work very well :)
        return not self.dynamic or guiConfig.getWindowOption("maximize")

    def createTopWindowGUI(self, *args):
        mainWindowGUI = PaneGUI(self.testTreeGUI, self.rightWindowGUI,
                                horizontal=True, shrink=self.shouldShrinkMainPanes())
        parts = [self.menuBarGUI, self.toolBarGUI, mainWindowGUI, self.shortcutBarGUI, self.statusMonitor]
        boxGUI = VBoxGUI(parts)
        return TopWindowGUI(boxGUI, self.dynamic, *args)

    def createMenuAndToolBarGUIs(self, uiManager, *args):
        menuNames = self.interactiveActionHandler.getMenuNames()
        menu = actionholders.MenuBarGUI(self.dynamic, uiManager, self.allActionGUIs(), menuNames, *args)
        toolbar = actionholders.ToolBarGUI(uiManager, self.progressBarGUI)
        testPopup, testFilePopup, appFilePopup = actionholders.createPopupGUIs(uiManager)
        return menu, toolbar, testPopup, testFilePopup, appFilePopup

    def createRightWindowGUI(self):
        testTab = PaneGUI(self.testFileGUI, self.textInfoGUI, horizontal=False)
        runInfoTab = PaneGUI(self.runInfoGUI, self.testRunInfoGUI, horizontal=False)
        tabGUIs = [testTab, self.progressMonitor] + self.actionTabGUIs + [self.appFileGUI, runInfoTab]
        return actionholders.NotebookGUI(tabGUIs)

    def run(self):
        Gtk.main()

    def notifyExit(self):
        Gtk.main_quit()

    def notifyLifecycleChange(self, test, state, changeDesc):
        test.stateInGui = state
        if state.isComplete():
            # Don't allow GUI-related changes to override the completed status
            test.state = state
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
        if not self.dynamic and self.initialApps:
            self.notify("Status", "Reading tests ...")
            self.notify("ActionStart", False)

    def notifyAllRead(self, suites):
        if not self.dynamic and self.initialApps:
            self.notify("Status", "Reading tests completed at " + plugins.localtime() + ".")
            self.notify("ActionStop", False)
        self.notify("AllRead", suites)
        for suite in suites:
            if suite.app not in self.initialApps:
                # We've added a new suite, we should also select it as it's likely the user wants to add stuff under it
                # Also include the knock-on effects, i.e. selecting the test tab etc
                self.notify("SetTestSelection", [suite], direct=True)
        if self.dynamic and len(suites) == 0:
            self.topWindowGUI.forceQuit()

    def notifyAdd(self, test, initial):
        test.stateInGui = test.state
        self.notify("Add", test, initial)

    def notifyStatus(self, *args, **kwargs):
        self.notify("Status", *args, **kwargs)

    def notifyRemove(self, test):
        self.notify("Remove", test)

    def notifyAllComplete(self):
        return self.LAST_OBSERVER  # Make sure all the framework classes get to respond before we take down the GUI...

    def notifyLastObserver(self, *args):
        # Called via the above, when all other observers have been notified
        self.notify("AllComplete")

    def notifyQuit(self, *args):
        self.notify("Quit", *args)


class TopWindowGUI(guiutils.ContainerGUI):
    EXIT_NOTIFIED = 1
    COMPLETION_NOTIFIED = 2

    def __init__(self, contentGUI, dynamic, allApps, name, rerunId):
        guiutils.ContainerGUI.__init__(self, [contentGUI])
        self.dynamic = dynamic
        self.topWindow = None
        self.name = name
        self.rerunId = rerunId
        self.allApps = copy(allApps)
        self.exitStatus = 0
        self.diag = logging.getLogger("Top Window")
        if not self.dynamic:
            self.exitStatus |= self.COMPLETION_NOTIFIED  # no tests to wait for...

    def getCheckoutTitle(self):
        allCheckouts = []
        for topApp in self.allApps:
            for app in [topApp] + topApp.extras:
                checkout = app.getCheckoutForDisplay()
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
            if suite.app.fullName() not in [app.fullName() for app in self.allApps]:
                self.allApps.append(suite.app)
                self.setWindowTitle()

        if not self.topWindow:
            # only do this once, not when new suites are added...
            self.createView()

    def createView(self):
        # Create toplevel window to show it all.
        self.topWindow = Gtk.Window(Gtk.WindowType.TOPLEVEL)
        self.topWindow.set_name("Top Window")
        try:
            from . import stockitems
            stockitems.register(self.topWindow)
        except Exception:  # pragma : no cover - should never happen
            plugins.printWarning("Failed to register texttest stock icons.")
            plugins.printException()
        iconFile = self.getIcon()
        try:
            self.topWindow.set_icon_from_file(iconFile)
        except Exception as e:
            plugins.printWarning("Failed to set texttest window icon.\n" + str(e), stdout=True)
        self.setWindowTitle()

        self.topWindow.add(self.subguis[0].createView())
        self.adjustSize()
        self.topWindow.show()
        self.topWindow.set_default_size(-1, -1)

        self.notify("TopWindow", self.topWindow)
        self.topWindow.connect("delete-event", self.windowClosed)
        return self.topWindow

    def setWindowTitle(self):
        guiText = "dynamic" if self.dynamic else "static"
        trailer = " - TextTest " + guiText + " GUI"
        if self.name:
            title = self.name
            if self.rerunId:
                title += " (rerun " + self.rerunId + ")"
        elif self.dynamic:
            appNameDesc = self.dynamicAppNameTitle()
            checkoutTitle = self.getCheckoutTitle()
            title = appNameDesc + " tests" + checkoutTitle
            if self.rerunId:
                title += " (rerun " + self.rerunId + ")"
            else:
                title += " (started at " + plugins.startTimeString() + ")"
        else:
            appNameDesc = self.staticAppNameTitle()
            basicTitle = "test management"
            if len(appNameDesc) > 0:
                title = appNameDesc + " " + basicTitle
            else:
                title = basicTitle.capitalize()
        self.topWindow.set_title(title + trailer)

    def staticAppNameTitle(self):
        allAppNames = [repr(app) for app in self.allApps]
        return ",".join(allAppNames)

    def dynamicAppNameTitle(self):
        appsWithVersions = self.organiseApps()
        allAppNames = [self.appRepresentation(appName, versionSuffices)
                       for appName, versionSuffices in list(appsWithVersions.items())]
        return ",".join(allAppNames)

    def appRepresentation(self, appName, versionSuffices):
        if len(versionSuffices) == 1:
            return appName + versionSuffices[0]
        else:
            return appName

    def organiseApps(self):
        appsWithVersions = OrderedDict()
        for app in self.allApps:
            appsWithVersions.setdefault(app.fullName(), []).append(app.versionSuffix())
        return appsWithVersions

    def getIcon(self):
        imageDir, retro = guiutils.getImageDir()
        imageType = "jpg" if retro else "png"
        if self.dynamic:
            return os.path.join(imageDir, "texttest-icon-dynamic." + imageType)
        else:
            return os.path.join(imageDir, "texttest-icon-static." + imageType)

    def forceQuit(self):
        self.exitStatus |= self.COMPLETION_NOTIFIED
        self.notifyQuit()

    def notifyAllComplete(self, *args):
        self.exitStatus |= self.COMPLETION_NOTIFIED
        if self.exitStatus & self.EXIT_NOTIFIED:
            self.notify("Exit")

    def windowClosed(self, *args):
        try:
            self.notify("WindowClosed")
        except CloseWindowCancelException:
            return not self.topWindow.stop_emission("delete_event")

    def notifyQuit(self, *args):
        self.exitStatus |= self.EXIT_NOTIFIED
        self.notify("KillProcesses", *args)
        if self.exitStatus & self.COMPLETION_NOTIFIED:
            self.notify("Exit")
        else:
            self.notify("Status", "Waiting for all tests to terminate ...")
            # When they have, we'll get notifyAllComplete

    def notifySetRunName(self, newName):
        self.name = newName
        self.setWindowTitle()

    def adjustSize(self):
        if guiConfig.getWindowOption("maximize"):
            self.topWindow.maximize()
        else:
            width = guiConfig.getWindowDimension("width", self.diag)
            height = guiConfig.getWindowDimension("height", self.diag)
            self.topWindow.set_default_size(width, height)


class ShortcutBarGUI(guiutils.SubGUI):
    def __init__(self, *args):
        guiutils.SubGUI.__init__(self)
        # Do this first, so we set up interceptors and so on early on
        try:
            # this should be removed after storytext got ported! MB 2018-12-05
            raise ImportError()
            from storytext import createShortcutBar
            from .version_control.custom_widgets_storytext import customEventTypes
            uiMapFiles = plugins.findDataPaths(["*.uimap"], *args)
            self.widget = createShortcutBar(uiMapFiles=uiMapFiles, customEventTypes=customEventTypes)
            self.widget.show()
        except ImportError:
            self.widget = None

    def shouldShow(self):
        return self.widget is not None

    def getWidgetName(self):
        return "_Shortcut bar"

    def createView(self):
        return self.widget


class VBoxGUI(guiutils.ContainerGUI):
    def createView(self):
        box = Gtk.VBox()
        expandWidgets = [Gtk.HPaned, Gtk.ScrolledWindow]
        for subgui in self.subguis:
            if subgui.shouldShow():
                view = subgui.createView()
                expand = view.__class__ in expandWidgets
                box.pack_start(view, expand, expand, 0)

        box.show()
        return box


class PaneGUI(guiutils.ContainerGUI):
    def __init__(self, gui1, gui2, horizontal, shrink=True):
        guiutils.ContainerGUI.__init__(self, [gui1, gui2])
        self.horizontal = horizontal
        self.paned = None
        self.separatorHandler = None
        self.position = 0
        self.maxPosition = 0
        self.initialMaxSize = 0
        self.shrink = shrink

    def getSeparatorPositionFromConfig(self):
        if self.horizontal:
            return float(guiConfig.getWindowOption("vertical_separator_position"))
        else:
            return float(guiConfig.getWindowOption("horizontal_separator_position"))

    def createPaned(self):
        if self.horizontal:
            return Gtk.HPaned()
        else:
            return Gtk.VPaned()

    def createView(self):
        frames = []
        for subgui in self.subguis:
            if subgui.shouldShow():
                frame = Gtk.Frame()
                frame.set_shadow_type(Gtk.ShadowType.IN)
                frame.add(subgui.createView())
                frame.show()
                frames.append(frame)

        if len(frames) > 1:
            self.paned = self.createPaned()
            self.paned.pack1(frames[0], resize=True)
            self.paned.pack2(frames[1], resize=True)
            self.separatorHandler = self.paned.connect('notify::max-position', self.adjustSeparator)
            self.paned.show()
            return self.paned
        else:
            frames[0].show()
            return frames[0]

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


class MultiActionGUIForwarder(guiplugins.GtkActionWrapper):
    def __init__(self, actionGUIs):
        self.actionGUIs = actionGUIs
        guiplugins.GtkActionWrapper.__init__(self)

    def setObservers(self, observers):
        for actionGUI in self.actionGUIs:
            actionGUI.setObservers(observers)

    def addToGroups(self, *args):
        for actionGUI in self.actionGUIs:
            actionGUI.addToGroups(*args)
        guiplugins.GtkActionWrapper.addToGroups(self, *args)

    def notifyNewTestSelection(self, *args):
        if not hasattr(self.actionGUIs[0], "notifyNewTestSelection"):
            return

        newActive = False
        for actionGUI in self.actionGUIs:
            if actionGUI.updateSelection(*args):
                newActive = True

        self.setSensitivity(newActive)

    def notifyTopWindow(self, *args):
        for actionGUI in self.actionGUIs:
            actionGUI.notifyTopWindow(*args)

    def addSuites(self, suites):
        for actionGUI in self.actionGUIs:
            if hasattr(actionGUI, "addSuites"):
                actionGUI.addSuites(suites)

    def runInteractive(self, *args):
        # otherwise it only gets computed once...
        actionGUI = self.findActiveActionGUI()
        self.diag.info("Forwarder executing " + str(actionGUI.__class__))
        actionGUI.runInteractive(*args)

    def __getattr__(self, name):
        actionGUI = self.findActiveActionGUI()
        self.diag.info("Forwarding " + name + " to " + str(actionGUI.__class__))
        return getattr(actionGUI, name)

    def findActiveActionGUI(self):
        for actionGUI in self.actionGUIs:
            if actionGUI.allAppsValid():
                return actionGUI
        return self.actionGUIs[0]


# Placeholder for all classes. Remember to add them!
class InteractiveActionHandler:
    def __init__(self, dynamic, allApps, inputOptions):
        self.diag = logging.getLogger("Interactive Actions")
        self.dynamic = dynamic
        self.allApps = allApps
        self.inputOptions = inputOptions
        self.rejectedModules = ["cvs "]  # For back-compatibility, don't try to load this module here.

    def getDefaultAccelerators(self):
        return plugins.ResponseAggregator([x.getDefaultAccelerators for x in self.getAllIntvConfigs(self.allApps)])()

    def getColourDictionary(self):
        return plugins.ResponseAggregator([x.getColourDictionary for x in self.getAllIntvConfigs(self.allApps)])()

    def getMenuNames(self):
        return reduce(set.union, (c.getMenuNames() for c in self.getAllIntvConfigs(self.allApps)), set())

    def getAllIntvConfigs(self, apps):
        configs = self.getAllConfigs(apps)
        vcsConfig = version_control.getVersionControlConfig(apps, self.inputOptions)
        if vcsConfig:
            configs.insert(0, vcsConfig)
        return configs

    def getAllConfigs(self, allApps):
        configs = []
        modules = set()
        for app in allApps:
            module = self.getExplicitConfigModule(app)
            if module and module not in modules:
                modules.add(module)
                config = self._getIntvActionConfig(module)
                if config:
                    self.diag.info("Loading GUI configuration from module " + repr(module) + " succeeded.")
                    configs.append(config)
        if len(configs) == 0:
            defaultModule = self.getExplicitConfigModule()
            if defaultModule:
                defaultConfig = self._getIntvActionConfig(defaultModule)
                if defaultConfig:
                    return [defaultConfig]
                else:
                    return []
        return configs

    def getPluginGUIs(self, uiManager):
        instances = self.getInstances()
        defaultGUIs, actionTabGUIs = [], []
        for action in instances:
            if action.displayInTab():
                self.diag.info("Tab: " + str(action.__class__))
                actionTabGUIs.append(action)
            else:
                self.diag.info("Menu/toolbar: " + str(action.__class__))
                defaultGUIs.append(action)

        actionGroup = Gtk.ActionGroup("AllActions")
        uiManager.insert_action_group(actionGroup, 0)
        accelGroup = uiManager.get_accel_group()
        for actionGUI in defaultGUIs + actionTabGUIs:
            actionGUI.addToGroups(actionGroup, accelGroup)

        return defaultGUIs, actionTabGUIs

    def getExplicitConfigModule(self, app=None):
        if app:
            module = app.getConfigValue("interactive_action_module")
            if module in self.rejectedModules:  # for back compatibility...
                return "default_gui"
            else:
                return module
        else:
            return "default_gui"

    def _getIntvActionConfig(self, module):
        namespace = {}
        try:
            exec("from " + module + " import InteractiveActionConfig", globals(), namespace)
            return namespace["InteractiveActionConfig"]()
        except ImportError:
            try:
                exec("from ." + module + " import InteractiveActionConfig", globals(), namespace)
                return namespace["InteractiveActionConfig"]()
            except:
                self.diag.info("Rejected GUI configuration from module " +
                               repr(module) + "\n" + plugins.getExceptionString())
                self.rejectedModules.append(module)  # Make sure we don't try and import it again
                if module == "default_gui":  # pragma: no cover - only to aid debugging default_gui
                    raise

    def getInstances(self):
        instances = []
        classNames = []
        for config in self.getAllIntvConfigs(self.allApps):
            instances += self.getInstancesFromConfig(config, classNames)
        return instances

    def getInstancesFromConfig(self, config, classNames=[]):
        instances = []
        for className in config.getInteractiveActionClasses(self.dynamic):
            if className not in classNames:
                self.diag.info("Making instances for " + repr(className))
                allClasses = self.findAllClasses(className)
                subinstances = self.makeAllInstances(allClasses)
                if len(subinstances) == 1:
                    instances.append(subinstances[0])
                else:
                    showable = [x for x in subinstances if x.shouldShow()]
                    if len(showable) == 1:
                        instances.append(showable[0])
                    else:
                        instances.append(MultiActionGUIForwarder(subinstances))
                classNames.append(className)
        return instances

    def makeAllInstances(self, allClasses):
        instances = []
        for classToUse, relevantApps in allClasses:
            instances.append(self.tryMakeInstance(classToUse, relevantApps))
        return instances

    def findAllClasses(self, className):
        if len(self.allApps) == 0:
            return [(className, [])]
        else:
            classNames = OrderedDict()
            for app in self.allApps:
                allConfigsForApp = self.getAllIntvConfigs([app])
                replacements = plugins.ResponseAggregator([x.getReplacements for x in allConfigsForApp])()
                for config in allConfigsForApp:
                    if className in config.getInteractiveActionClasses(self.dynamic):
                        realClassName = replacements.get(className, className)
                        classNames.setdefault(realClassName, []).append(app)
            return list(classNames.items())

    def tryMakeInstance(self, className, apps):
        # Basically a workaround for crap error message with variable className from python...
        try:
            instance = className(apps, self.dynamic, self.inputOptions)
            self.diag.info("Creating " + str(instance.__class__.__name__) + " instance for " + repr(apps))
            return instance
        except:
            # If some invalid interactive action is provided, need to know which
            sys.stderr.write("Error with interactive action " + str(className) + "\n")
            raise
