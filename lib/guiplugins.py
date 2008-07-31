
import plugins, os, sys, shutil, time, subprocess, operator, types
from jobprocess import killSubProcessAndChildren
from copy import copy, deepcopy
from glob import glob
from stat import *
from ndict import seqdict
from log4py import LOGLEVEL_NORMAL

try:
    import gtk, gobject, entrycompletion
    from gtkusecase import RadioGroupIndexer
except ImportError:
    pass # We might want to document the config entries, silly to fail on lack of GTK...

guilog, guiConfig, scriptEngine = None, None, None

def setUpGlobals(dynamic, allApps):
    global guilog, guiConfig, scriptEngine
    from gtkusecase import ScriptEngine
    if dynamic:
        guilog = plugins.getDiagnostics("dynamic GUI behaviour")
    else:
        guilog = plugins.getDiagnostics("static GUI behaviour")
    guiConfig = GUIConfig(dynamic, allApps, guilog)
    scriptEngine = ScriptEngine(guilog, enableShortcuts=1)
    return guilog, guiConfig, scriptEngine

# gtk.accelerator_valid appears utterly broken on Windows
def windowsAcceleratorValid(key, mod):
    name = gtk.accelerator_name(key, mod)
    return len(name) > 0 and name != "VoidSymbol"

if os.name == "nt":
    gtk.accelerator_valid = windowsAcceleratorValid
            

class GUIConfig:
    def __init__(self, dynamic, allApps, entryCompletionLogger):
        self.apps = copy(allApps)
        self.dynamic = dynamic
        self.configDir = plugins.MultiEntryDictionary()
        self.configDocs = {}
        self.setConfigDefaults()
        personalFile = plugins.getPersonalConfigFile()
        if personalFile:
            self.configDir.readValues([ personalFile ], insert=0, errorOnUnknown=0)

        self.hiddenCategories = map(self.getConfigName, self.configDir.get("hide_test_category"))
        self.colourDict = self.makeColourDictionary()
        if entryCompletionLogger:
            self.setUpEntryCompletion(entryCompletionLogger)

    def addSuites(self, suites):
        fullNames = [ app.fullName for app in self.apps ]
        for suite in suites:
            if suite.app.fullName not in fullNames:
                self.apps.append(suite.app)

    def makeColourDictionary(self):
        dict = {}
        for key, value in self.configDir.get("test_colours").items():
            dict[self.getConfigName(key)] = value
        return dict

    def setConfigDefaults(self):
        colourDict = interactiveActionHandler.getColourDictionary(self.apps)
        self.setConfigDefault("static_collapse_suites", 0, "Whether or not the static GUI will show everything collapsed")
        self.setConfigDefault("test_colours", colourDict, "Colours to use for each test state")
        self.setConfigDefault("file_colours", copy(colourDict), "Colours to use for each file state")
        self.setConfigDefault("auto_collapse_successful", 1, "Automatically collapse successful test suites?")
        self.setConfigDefault("window_size", self.getWindowSizeSettings(), "To set the initial size of the dynamic/static GUI.")
        self.setConfigDefault("hide_gui_element", self.getDefaultHideWidgets(), "List of widgets to hide by default")
        self.setConfigDefault("hide_test_category", [], "Categories of tests which should not appear in the dynamic GUI test view")
        self.setConfigDefault("query_kill_processes", { "default" : [] }, "Ask about whether to kill these processes when exiting texttest.")
        self.setConfigDefault("gui_accelerators", interactiveActionHandler.getDefaultAccelerators(self.apps), "Custom action accelerators.")        
        self.setConfigDefault("gui_entry_completion_matching", 1, "Which matching type to use for entry completion. 0 means turn entry completions off, 1 means match the start of possible completions, 2 means match any part of possible completions")
        self.setConfigDefault("gui_entry_completion_inline", 0, "Automatically inline common completion prefix in entry.")
        self.setConfigDefault("gui_entry_completions", { "default" : [] }, "Add these completions to the entry completion lists initially")
        self.setConfigDefault("sort_test_suites_recursively", 1, "Sort subsuites when sorting test suites")
        
    def setConfigDefault(self, key, value, docString):
        self.configDir[key] = value
        self.configDocs[key] = docString

    def setUpEntryCompletion(self, entryCompletionLogger):
        matching = self.configDir.get("gui_entry_completion_matching")
        if matching != 0:
            inline = self.configDir.get("gui_entry_completion_inline")
            completions = self.getCompositeValue("gui_entry_completions", "", modeDependent=True)
            entrycompletion.manager.start(matching, inline, completions, entryCompletionLogger)
    def _simpleValue(self, app, entryName):
        return app.getConfigValue(entryName)
    def _compositeValue(self, app, *args, **kwargs):
        return app.getCompositeConfigValue(*args, **kwargs)
    def _getFromApps(self, method, *args, **kwargs):
        prevValue = None
        for app in self.apps:
            currValue = method(app, *args, **kwargs)
            toUse = self.chooseValueFrom(prevValue, currValue)
            if toUse is None and prevValue is not None:
                plugins.printWarning("GUI configuration '" + "::".join(args) +\
                                     "' differs between applications, ignoring that from " + repr(app) + "\n" + \
                                     "Value was " + repr(currValue) + ", change from " + repr(prevValue))
            else:
                prevValue = toUse
        return prevValue
    def chooseValueFrom(self, value1, value2):
        if value1 is None or value1 == value2:
            return value2
        if value2 is None:
            return value1
        if type(value1) == types.ListType:
            return self.createUnion(value1, value2)

    def createUnion(self, list1, list2):
        result = []
        result += list1
        for entry in list2:
            if not entry in list1:
                result.append(entry)
        return result
    
    def getModeName(self):
        if self.dynamic:
            return "dynamic"
        else:
            return "static"
    def getConfigName(self, name, modeDependent=False):
        formattedName = name.lower().replace(" ", "_").replace(":", "_")
        if modeDependent:
            if len(name) > 0:
                return self.getModeName() + "_" + formattedName
            else:
                return self.getModeName()
        else:
            return formattedName
        
    def getValue(self, entryName, modeDependent=False):
        nameToUse = self.getConfigName(entryName, modeDependent)
        guiValue = self.configDir.get(nameToUse)
        if guiValue is not None:
            return guiValue
        else:
            return self._getFromApps(self._simpleValue, nameToUse)
    def getCompositeValue(self, sectionName, entryName, modeDependent=False, defaultKey="default"):
        nameToUse = self.getConfigName(entryName, modeDependent)
        value = self.configDir.getComposite(sectionName, nameToUse, defaultKey)
        if value is None:
            value = self._getFromApps(self._compositeValue, sectionName, nameToUse, defaultKey=defaultKey)
        if modeDependent and value is None:
            return self.getCompositeValue(sectionName, entryName)
        else:
            return value
    def getWindowOption(self, name):
        return self.getCompositeValue("window_size", name, modeDependent=True)
    def showCategoryByDefault(self, category, fallback=None):
        if self.dynamic:
            nameToUse = self.getConfigName(category)
            if nameToUse in self.hiddenCategories:
                return False
            elif fallback is not None:
                return fallback
            else:
                return True
        else:
            return False    
    def getTestColour(self, category, fallback=None):
        if self.dynamic:
            nameToUse = self.getConfigName(category)
            if self.colourDict.has_key(nameToUse):
                return self.colourDict[nameToUse]
            elif fallback:
                return fallback
            else:
                return self.colourDict.get("failure")
        else:
            return self.colourDict.get("static")

    def getWindowSizeSettings(self):
        dict = {}
        dict["maximize"] = 0
        dict["horizontal_separator_position"] = 0.46
        dict["vertical_separator_position"] = 0.5
        dict["height_pixels"] = "<not set>"
        dict["width_pixels"] = "<not set>"
        dict["height_screen"] = float(5.0) / 6
        dict["width_screen"] = 0.6
        return dict
    
    def getDefaultHideWidgets(self):
        dict = {}
        dict["status_bar"] = 0
        dict["toolbar"] = 0
        dict["shortcut_bar"] = 0
        return dict
    
    
# The purpose of this class is to provide a means to monitor externally
# started process, so that (a) code can be called when they exit, and (b)
# they can be terminated when TextTest is terminated.
class ProcessTerminationMonitor(plugins.Observable):
    def __init__(self):
        plugins.Observable.__init__(self)
        self.processes = seqdict()

    def listRunningProcesses(self):
        processesToCheck = guiConfig.getCompositeValue("query_kill_processes", "", modeDependent=True)
        running = []
        if len(processesToCheck) == 0:
            return running
        for process, description, exitHandler, exitHandlerArgs in self.processes.values():
            for processToCheck in processesToCheck:
                if plugins.isRegularExpression(processToCheck):
                    if plugins.findRegularExpression(processToCheck, description):
                        running.append("PID " + str(process.pid) + " : " + description)
                        break
                elif processToCheck.lower() == "all" or description.find(processToCheck) != -1:
                    running.append("PID " + str(process.pid) + " : " + description)
                    break

        return running

    def getProcessIdentifier(self, process):
        # Unfortunately the child_watch_add method needs different ways to
        # identify the process on different platforms...
        if os.name == "posix":
            return process.pid
        else:
            return process._handle

    def startProcess(self, cmdArgs, description = "", exitHandler=None, exitHandlerArgs=(), **kwargs):
        process = subprocess.Popen(cmdArgs, stdin=open(os.devnull), startupinfo=plugins.getProcessStartUpInfo(), **kwargs)
        pidOrHandle = self.getProcessIdentifier(process)
        self.processes[int(pidOrHandle)] = (process, description, exitHandler, exitHandlerArgs)
        gobject.child_watch_add(pidOrHandle, self.processExited)

    def processExited(self, pid, *args):
        process, description, exitHandler, exitHandlerArgs = self.processes.pop(pid)
        if exitHandler:
            exitHandler(*exitHandlerArgs)
    
    def notifyKillProcesses(self, sig=None):
        # Don't leak processes
        if len(self.processes) == 0:
            return
        self.notify("Status", "Terminating all external viewers ...")
        for process, description, exitHandler, exitHandlerArgs in self.processes.values():
            self.notify("ActionProgress", "")
            guilog.info("Killing '" + description + "' interactive process")
            killSubProcessAndChildren(process, sig)
        
processMonitor = ProcessTerminationMonitor()


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

    def forceVisible(self, rowCount):
        return False

    def addScrollBars(self, view, hpolicy):
        window = gtk.ScrolledWindow()
        window.set_policy(hpolicy, gtk.POLICY_AUTOMATIC)
        self.addToScrolledWindow(window, view)
        window.show()
        return window

    def addToScrolledWindow(self, window, widget):
        if isinstance(widget, gtk.VBox):
            window.add_with_viewport(widget)
        else:
            window.add(widget)

class GtkActionWrapper:
    def __init__(self):
        self.accelerator = None
        self.diag = plugins.getDiagnostics("Interactive Actions")
        title = self.getTitle(includeMnemonics=True)
        actionName = self.getTitle(includeMnemonics=False)
        self.gtkAction = gtk.Action(actionName, title, \
                                    self.getTooltip(), self.getStockId())
        scriptEngine.connect(self.getTooltip(), "activate", self.gtkAction, self.runInteractive)
        if not self.isActiveOnCurrent():
            self.gtkAction.set_property("sensitive", False)

    def getAccelerator(self, title):
        realAcc = guiConfig.getCompositeValue("gui_accelerators", title)
        if realAcc:
            key, mod = gtk.accelerator_parse(realAcc)
            if gtk.accelerator_valid(key, mod):
                return realAcc
            else:
                plugins.printWarning("Keyboard accelerator '" + realAcc + "' for action '" \
                                     + title + "' is not valid, ignoring ...")

    def addToGroups(self, actionGroup, accelGroup):
        self.accelerator = self._addToGroups(self.getTitle().rstrip("."), self.gtkAction, actionGroup, accelGroup)

    def _addToGroups(self, title, gtkAction, actionGroup, accelGroup):
        # GTK 2.12 got fussy about this...
        existingAction = actionGroup.get_action(gtkAction.get_name())
        if existingAction:
            self.diag.info("Removing action with label " + existingAction.get_property("label"))
            actionGroup.remove_action(existingAction)
            
        accelerator = self.getAccelerator(title)
        actionGroup.add_action_with_accel(gtkAction, accelerator)
        gtkAction.set_accel_group(accelGroup)
        gtkAction.connect_accelerator()
        return accelerator
    
    def setSensitivity(self, newValue):
        self._setSensitivity(self.gtkAction, newValue)

    def _setSensitivity(self, gtkAction, newValue):
        oldValue = gtkAction.get_property("sensitive")
        gtkAction.set_property("sensitive", newValue)
        if oldValue != newValue:
            guilog.info("Setting sensitivity of action '" + gtkAction.get_property("label") + "' to " + repr(newValue))

    def describeAction(self):
        self._describeAction(self.gtkAction, self.accelerator)

    def _describeAction(self, gtkAction, accelerator):
        message = "Viewing action with title '" + gtkAction.get_property("label") + "'"
        message += self.detailDescription(gtkAction, accelerator)
        guilog.info(message)

    def detailDescription(self, gtkAction, accelerator):
        message = ""
        stockId = gtkAction.get_property("stock-id")
        if stockId:
            message += ", stock id '" + repr(stockId) + "'"
        if accelerator:
            message += ", accelerator '" + repr(accelerator) + "'"
        return message + self.sensitivityDescription(gtkAction)
    
    def sensitivityDescription(self, gtkAction):
        if gtkAction.get_property("sensitive"):
            return ""
        else:
            return " (greyed out)"


# Introduce an extra level without all the selection-dependent stuff, some actions want
# to inherit from here and it provides a separation
class BasicActionGUI(SubGUI,GtkActionWrapper):
    busy = False
    def __init__(self, *args):
        SubGUI.__init__(self)
        GtkActionWrapper.__init__(self)
        self.topWindow = None

    def notifyTopWindow(self, window):
        self.topWindow = window

    def getParentWindow(self):
        return self.topWindow

    def isModal(self):
        return True

    def isActiveOnCurrent(self, *args):
        return True
    
    def getDialogTitle(self):
        return self.getTooltip()

    def createDialog(self):
        if self.isModal():
            dialog = gtk.Dialog(self.getDialogTitle(), self.getParentWindow(), flags=gtk.DIALOG_MODAL) 
            dialog.set_modal(True)
        else:
            dialog = gtk.Dialog(self.getDialogTitle())

        dialog.set_default_response(gtk.RESPONSE_ACCEPT)
        return dialog
    
    def getTitle(self, includeMnemonics=False):
        title = self._getTitle()
        if includeMnemonics:
            return title
        else:
            return title.replace("_", "")

    def getTooltip(self):
        return self.getTitle(includeMnemonics=False)

    def displayInTab(self):
        return False

    def allAppsValid(self):
        return True
    
    def getStockId(self):
        stockId = self._getStockId()
        if stockId:
            return "gtk-" + stockId 

    def _getStockId(self): # The stock ID for the action, in toolbar and menu.
        pass

    def describe(self):
        self.describeAction()
                
    def setObservers(self, observers):
        if len(self.observers) > 0:
            return # still relevant?
        
        signals = [ "Status", "ActionProgress" ] + self.getSignalsSent()
        self.diag.info("Observing " + str(self.__class__) + " :")
        for observer in observers:
            for signal in signals:
                if hasattr(observer, "notify" + signal):
                    self.diag.info("-> " + str(observer.__class__))
                    self.addObserver(observer)
                    break
    def getSignalsSent(self):
        return [] # set up like this so every single derived class doesn't have to include it

    def createDialogMessage(self, message, stockIcon):
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
        scrolledWindow.set_policy(gtk.POLICY_NEVER, gtk.POLICY_NEVER)
        scrolledWindow.add(textView)
        scrolledWindow.set_shadow_type(gtk.SHADOW_IN)
        hbox.pack_start(scrolledWindow, expand=True, fill=True)
        alignment = gtk.Alignment()
        alignment.set_padding(5, 5, 0, 5)
        alignment.add(hbox)
        return alignment

    def describeDialog(self, dialog, contents, stockIcon = None):
        message = "-" * 10 + " Dialog '" + dialog.get_title() + "' " + "-" * 10
        guilog.info(message)
        defaultWidget = dialog.default_widget
        if defaultWidget:
            try:
                guilog.info("Default action is labelled '" + defaultWidget.get_label() + "'")
            except AttributeError:
                guilog.info("Default widget unlabelled, type " + str(defaultWidget.__class__))
        if stockIcon:
            guilog.info("Using stock icon '" + stockIcon + "'")
        # One blank line at the end
        guilog.info(contents.strip())
        guilog.info("-" * len(message))
            
    def showErrorDialog(self, message):
        self.showErrorWarningDialog(message, gtk.STOCK_DIALOG_ERROR, "Error") 
    def showWarningDialog(self, message):
        self.showErrorWarningDialog(message, gtk.STOCK_DIALOG_WARNING, "Warning") 
    def showErrorWarningDialog(self, message, stockIcon, alarmLevel):
        dialog = self.createAlarmDialog(self.getParentWindow(), message, stockIcon, alarmLevel)
        yesButton = dialog.add_button(gtk.STOCK_OK, gtk.RESPONSE_ACCEPT)
        dialog.set_default_response(gtk.RESPONSE_ACCEPT)
        scriptEngine.connect("agree to texttest message", "clicked", yesButton, self.cleanDialog,
                             gtk.RESPONSE_ACCEPT, True, dialog)
        dialog.show_all()
        self.describeDialog(dialog, message, stockIcon)
        
    def createAlarmDialog(self, parent, message, stockIcon, alarmLevel):
        dialogTitle = "TextTest " + alarmLevel
        dialog = gtk.Dialog(dialogTitle, parent, flags=gtk.DIALOG_MODAL) 
        dialog.set_modal(True)
        
        contents = self.createDialogMessage(message, stockIcon)
        dialog.vbox.pack_start(contents, expand=True, fill=True)
        return dialog
    
    def showQueryDialog(self, parent, message, stockIcon, alarmLevel, respondMethod):
        dialog = self.createAlarmDialog(parent, message, stockIcon, alarmLevel)
        dialog.set_default_response(gtk.RESPONSE_NO)
        noButton = dialog.add_button(gtk.STOCK_NO, gtk.RESPONSE_NO)
        yesButton = dialog.add_button(gtk.STOCK_YES, gtk.RESPONSE_YES)
        scriptEngine.connect("answer no to texttest " + alarmLevel, "clicked",
                             noButton, respondMethod, gtk.RESPONSE_NO, False, dialog)
        scriptEngine.connect("answer yes to texttest " + alarmLevel, "clicked",
                             yesButton, respondMethod, gtk.RESPONSE_YES, True, dialog)
        dialog.show_all()
        self.describeDialog(dialog, message, stockIcon)
        
    def cleanDialog(self, button, saidOK, dialog):
        self._cleanDialog(dialog)

    def _cleanDialog(self, dialog):
        entrycompletion.manager.collectCompletions()
        dialog.hide()
        dialog.response(gtk.RESPONSE_NONE)

    def respond(self, button, saidOK, dialog):
        try:
            self._respond(saidOK, dialog)
        except plugins.TextTestError, e:
            self.showErrorDialog(str(e))
            
    def _respond(self, saidOK, dialog):
        if saidOK:
            self._runInteractive()
        else:
            self.cancel()
        if dialog:
            self._cleanDialog(dialog)
        
    def getConfirmationMessage(self):
        return ""

    def runInteractive(self, *args):
        if self.busy: # If we're busy with some other action, ignore this one ...
            return
                
        try:
            confirmationMessage = self.getConfirmationMessage()
            if confirmationMessage:
                self.showQueryDialog(self.getParentWindow(), confirmationMessage,
                                     gtk.STOCK_DIALOG_WARNING, "Confirmation", self.respond)    
            else:
                # Each time we perform an action we collect and save the current registered entries
                # Actions showing dialogs will handle this in the dialog code.
                entrycompletion.manager.collectCompletions()
                self._runInteractive()
        except plugins.TextTestError, e:
            self.showErrorDialog(str(e))
            
    def _runInteractive(self):
        try:
            BasicActionGUI.busy = True
            self.startPerform()
        finally:
            self.endPerform()
            BasicActionGUI.busy = False
    
    def messageBeforePerform(self):
        # Don't change this by default, most of these things don't take very long
        pass

    def messageAfterPerform(self):
        return "Performed '" + self.getTooltip() + "'."
    
    def startPerform(self):
        message = self.messageBeforePerform()
        if message != None:
            self.notify("Status", message)
        self.notify("ActionStart", message)
        self.notify("ActionProgress")
        self.performOnCurrent()
        message = self.messageAfterPerform()
        if message != None:
            self.notify("Status", message)
        
    def endPerform(self):
        self.notify("ActionStop", "")

    def cancel(self):
        self.notify("Status", "Action cancelled.")
    
    
class ActionGUI(BasicActionGUI):
    busy = False
    def __init__(self, allApps, *args):
        self.currTestSelection = []
        self.currFileSelection = []
        self.currAppSelection = []
        self.validApps = []
        self.tooltips = gtk.Tooltips()
        self.noApps = len(allApps) == 0
        BasicActionGUI.__init__(self)
        for app in allApps:
            self.checkValid(app)
            
    def addSuites(self, suites):
        oldActive = self.isActiveOnCurrent()
        for suite in suites:
            if suite.app not in self.validApps and interactiveActionHandler.classValid(self.__class__, suite.app):
                self.checkValid(suite.app)
        self.noApps = len(suites) == 0
            
    def checkValid(self, app):
        if self.isValidForApp(app):
            self.validApps.append(app)
            self.validApps += app.extras
        else:
            self.diag.info(str(self.__class__) + " invalid for " + repr(app))
        
    def isValidForApp(self, app):
        return True

    def shouldShow(self):
        return self.noApps or len(self.validApps) > 0
    
    def notifyNewTestSelection(self, *args):
        newActive = self.updateSelection(*args)
        self.setSensitivity(newActive)

    def updateSelection(self, tests, apps, rowCount, *args):
        if rowCount != 1 and self.singleTestOnly():
            self.currTestSelection = []
        else:
            self.currTestSelection = tests
            testClass = self.correctTestClass()
            if testClass:
                self.currTestSelection = filter(lambda test: test.classId() == testClass, tests)
                
        self.currAppSelection = apps
        newActive = self.allAppsValid() and self.isActiveOnCurrent()
        self.diag.info("New test selection for " + self.getTitle() + "=" + repr(tests) + " : new active = " + repr(newActive))
        return newActive
        
    def notifyLifecycleChange(self, test, state, desc):
        newActive = self.isActiveOnCurrent(test, state)
        self.setSensitivity(newActive)

    def notifyNewFileSelection(self, files):
        newActive = self.updateFileSelection(files)
        self.setSensitivity(newActive)
        
    def updateFileSelection(self, files):
        self.currFileSelection = files
        newActive = self.isActiveOnCurrent()
        self.diag.info("New file selection for " + self.getTitle() + "=" + repr(files) + " : new active = " + repr(newActive))
        return newActive

    def allAppsValid(self):
        for app in self.currAppSelection:
            if app not in self.validApps:
                self.diag.info("Rejecting due to invalid selected app : " + repr(app))
                return False
        return True

    def isActiveOnCurrent(self, *args):
        return self.shouldShow() and len(self.currTestSelection) > 0
        
    def singleTestOnly(self):
        return False        

    def describeTests(self):
        if len(self.currTestSelection) == 1:
            return repr(self.currTestSelection[0])
        else:
            return str(len(self.currTestSelection)) + " tests"

    def correctTestClass(self):
        pass

    def pluralise(self, num, name):
        if num == 1:
            return "1 " + name
        else:
            return str(num) + " " + name + "s"

    def messageAfterPerform(self):
        return "Performed '" + self.getTooltip() + "' on " + self.describeTests() + "."

    def createButton(self):
        button = gtk.Button()
        self.gtkAction.connect_proxy(button)
        # In theory all this should be automatic, but it appears not to work
        if self.getStockId():
            button.set_image(gtk.image_new_from_stock(self.getStockId(), gtk.ICON_SIZE_BUTTON))
        self.tooltips.set_tip(button, self.getTooltip())
        button.show()
        return button

# These actions consist of bringing up a dialog and only doing that
# (i.e. the dialog is not a mechanism to steer how the action should be run)
class ActionResultDialogGUI(ActionGUI):
    def performOnCurrent(self):
        self.dialog = self.createDialog()
        textContents = self.addContents()
        self.createButtons()
        self.dialog.show_all()
        self.describeDialog(self.dialog, textContents)

    def addContents(self):
        pass
    
    def createButtons(self):
        okButton = self.dialog.add_button(gtk.STOCK_CLOSE, gtk.RESPONSE_ACCEPT)
        self.dialog.set_default_response(gtk.RESPONSE_ACCEPT)
        scriptEngine.connect("press close", "clicked", okButton, self.cleanDialog, gtk.RESPONSE_ACCEPT, True, self.dialog)


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


class OptionGroupGUI(ActionGUI):
    def __init__(self, *args):
        ActionGUI.__init__(self, *args)
        self.optionGroup = plugins.OptionGroup(self.getTabTitle())
        # convenience shortcuts...
        self.addOption = self.optionGroup.addOption
        self.addSwitch = self.optionGroup.addSwitch
        
    def updateOptions(self):
        return False     

    def updateForConfig(self, option):
        fromConfig = guiConfig.getCompositeValue("gui_entry_overrides", option.name)
        if fromConfig is not None and fromConfig != "<not set>":
            option.setValue(fromConfig)
            return fromConfig

    def createLabelEventBox(self, option, separator):
        label = gtk.EventBox()
        label.add(gtk.Label(option.name + separator))
        if option.description and type(option.description) == types.StringType:
            self.tooltips.set_tip(label, option.description)
        return label

    def createOptionEntry(self, option, separator):
        widget, entry = self.createOptionWidget(option)
        label = self.createLabelEventBox(option, separator)
        scriptEngine.registerEntry(entry, "enter " + option.name.strip() + " =")
        entry.set_text(option.getValue())
        entrycompletion.manager.register(entry)
        # Options in drop-down lists don't change, so we just add them once and for all.
        for text in option.listPossibleValues():
            entrycompletion.manager.addTextCompletion(text)
        option.setMethods(entry.get_text, entry.set_text)
        if option.changeMethod:
            entry.connect("changed", option.changeMethod)
        return label, widget, entry

    def addValuesFromConfig(self, option):
        newValue = self.updateForConfig(option)
        if newValue:
            option.addPossibleValue(newValue)
        for extraOption in self.getConfigOptions(option):
            option.addPossibleValue(extraOption)

    def addSwitches(self, vbox, optionGroup):
        for switch in optionGroup.switches.values():
            widget = self.createSwitchWidget(switch, optionGroup)
            vbox.pack_start(widget, expand=False, fill=False)

    def createRadioButtonCollection(self, switch, optionGroup):
        hbox = gtk.HBox()
        if len(switch.name) > 0:
            label = self.createLabelEventBox(switch, ":")
            hbox.pack_start(label, expand=False, fill=False)
        for button in self.createRadioButtons(switch, optionGroup):
            hbox.pack_start(button, expand=True, fill=False)
        hbox.show_all()
        return hbox

    def getNaming(self, switchName, cleanOption, *args):
        if len(switchName) > 0:
            configName = switchName + ":" + cleanOption
            useCaseName = cleanOption + " for " + switchName
            return configName, useCaseName
        else:
            return cleanOption, cleanOption

    def createRadioButtons(self, switch, optionGroup):
        buttons = []
        mainRadioButton = None
        individualToolTips = type(switch.description) == types.ListType
        for index, option in enumerate(switch.options):
            cleanOption = option.split("\n")[0].replace("_", "")
            configName, useCaseName = self.getNaming(switch.name, cleanOption, optionGroup)
            if guiConfig.getCompositeValue("gui_entry_overrides", configName) == "1":
                switch.setValue(index)
            radioButton = gtk.RadioButton(mainRadioButton, option, use_underline=True)
            if individualToolTips:
                self.tooltips.set_tip(radioButton, switch.description[index])
                
            buttons.append(radioButton)
            scriptEngine.registerToggleButton(radioButton, "choose " + useCaseName)
            if not mainRadioButton:
                mainRadioButton = radioButton
            if switch.defaultValue == index:
                switch.resetMethod = radioButton.set_active
            if switch.getValue() == index:
                radioButton.set_active(True)
            else:
                radioButton.set_active(False)
        indexer = RadioGroupIndexer(buttons)
        switch.setMethods(indexer.getActiveIndex, indexer.setActiveIndex)
        return buttons

    def createSwitchWidget(self, switch, optionGroup):
        if len(switch.options) >= 1:
            return self.createRadioButtonCollection(switch, optionGroup)
        else:
            return self.createCheckBox(switch)

    def createCheckBox(self, switch):
        self.updateForConfig(switch)
        checkButton = gtk.CheckButton(switch.name)
        if switch.description:
            self.tooltips.set_tip(checkButton, switch.description)
        
        if int(switch.getValue()):
            checkButton.set_active(True)
        scriptEngine.registerToggleButton(checkButton, "check " + switch.name, "uncheck " + switch.name)
        switch.setMethods(checkButton.get_active, checkButton.set_active)
        checkButton.show()
        return checkButton

    def createComboBox(self, option):
        combobox = gtk.combo_box_entry_new_text()
        entry = combobox.child
        option.setPossibleValuesMethods(combobox.append_text, ComboBoxListFinder(combobox))
        
        option.setClearMethod(combobox.get_model().clear)
        return combobox, entry

    def createOptionWidget(self, option):
        box = gtk.HBox()
        if option.usePossibleValues():
            (widget, entry) = self.createComboBox(option)
            box.pack_start(widget, expand=True, fill=True)
        else:
            entry = gtk.Entry()
            box.pack_start(entry, expand=True, fill=True)
        return box, entry
  
    def getConfigOptions(self, option):
        fromConfig = guiConfig.getCompositeValue("gui_entry_options", option.name)
        if fromConfig is None: #Happens on initial startup with no apps...
            return []
        return fromConfig

    def getOptionGroupDescription(self, optionGroup):
        messages = map(self.getOptionDescription, optionGroup.options.values()) + \
                   map(self.getSwitchDescription, optionGroup.switches.values())
        return "\n".join(messages)

    def getOptionDescription(self, option):
        value = option.getValue()
        text = "Viewing entry for option '" + option.name.replace("\n", "\\n") + "'"
        if len(value) > 0:
            text += " (set to '" + value + "')"
        if option.usePossibleValues():
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

    
class ActionTabGUI(OptionGroupGUI):
    def __init__(self, *args):
        OptionGroupGUI.__init__(self, *args)
        self.diag.info("Creating action tab for " + self.getTabTitle() + ", sensitive " + repr(self.shouldShowCurrent()))
    def shouldShowCurrent(self, *args):
        return self.gtkAction.get_property("sensitive")
    def createView(self):
        vbox = gtk.VBox()
        self.fillVBox(vbox, self.optionGroup)
        self.createButtons(vbox)
        vbox.show_all()
        return self.addScrollBars(vbox, hpolicy=gtk.POLICY_AUTOMATIC)
    def setSensitivity(self, newValue):
        ActionGUI.setSensitivity(self, newValue)
        self.diag.info("Sensitivity of " + self.getTabTitle() + " changed to " + repr(newValue))
        if self.shouldShowCurrent() and self.updateOptions():
            self.contentsChanged()        

    def displayInTab(self):
        return True
    
    def notifyReset(self):
        self.optionGroup.reset()
        self.contentsChanged()

    def fillVBox(self, vbox, optionGroup):
        if len(optionGroup.options) > 0:
            # Creating 0-row table gives a warning ...
            table = gtk.Table(len(optionGroup.options), 2, homogeneous=False)
            table.set_row_spacings(1)
            rowIndex = 0        
            for option in optionGroup.options.values():
                self.addValuesFromConfig(option)

                label, entryWidget, entry = self.createOptionEntry(option, separator="  ")
                scriptEngine.connect("activate from " + option.name, "activate", entry, self.runInteractive)
                if isinstance(label, gtk.Label):
                    label.set_alignment(1.0, 0.5)
                else:
                    label.get_children()[0].set_alignment(1.0, 0.5)
                table.attach(label, 0, 1, rowIndex, rowIndex + 1, xoptions=gtk.FILL, xpadding=1)
                table.attach(entryWidget, 1, 2, rowIndex, rowIndex + 1)
                rowIndex += 1
                table.show_all()
            vbox.pack_start(table, expand=False, fill=False)

        self.addSwitches(vbox, optionGroup)

    def createButtons(self, vbox):
        self.addCentralButton(vbox, self.createButton())

    def addCentralButton(self, vbox, button):
        buttonbox = gtk.HBox()
        buttonbox.pack_start(button, expand=True, fill=False)
        vbox.pack_start(buttonbox, expand=False, fill=False, padding=8)

    def createOptionWidget(self, option):
        box, entry = OptionGroupGUI.createOptionWidget(self, option)
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
    
    def showDirectoryChooser(self, widget, entry, option):
        dialog = gtk.FileChooserDialog("Select a directory",
                                       self.getParentWindow(),
                                       gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER,
                                       (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                        gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        self.startChooser(dialog, entry, option)

    def showFileChooser(self, widget, entry, option):
        dialog = gtk.FileChooserDialog("Select a file",
                                       self.getParentWindow(),
                                       gtk.FILE_CHOOSER_ACTION_OPEN,
                                       (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,                                        
                                        gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        self.startChooser(dialog, entry, option)
    
    def startChooser(self, dialog, entry, option):
        # Folders is a list of pairs (short name, absolute path),
        # where 'short name' means the name given in the config file, e.g.
        # 'temporary_filter_files' or 'filter_files' ...
        dialog.set_modal(True)
        folders, defaultFolder = option.getDirectories()
        scriptEngine.registerOpenFileChooser(dialog, "select filter-file", "look in folder", 
                                             "open selected file", "cancel file selection", self.respondChooser, respondMethodArg=entry)
        # If current entry forms a valid path, set that as default
        currPath = entry.get_text()
        currDir, currFile = os.path.split(currPath)
        if os.path.isdir(currDir):
            dialog.set_current_folder(currDir)
        elif defaultFolder and os.path.isdir(os.path.abspath(defaultFolder)):
            dialog.set_current_folder(os.path.abspath(defaultFolder))
        for folder in folders:
            dialog.add_shortcut_folder(folder)
        dialog.set_default_response(gtk.RESPONSE_OK)
        dialog.show()
    def respondChooser(self, dialog, response, entry):
        if response == gtk.RESPONSE_OK:
            entry.set_text(dialog.get_filename().replace("\\", "/"))
            entry.set_position(-1) # Sets position last, makes it possible to see the vital part of long paths 
        dialog.destroy()

    def describe(self):
        guilog.info("Viewing notebook page for '" + self.getTabTitle() + "'")
        guilog.info(self.getOptionGroupDescription(self.optionGroup))
        self.describeAction()

    def addApplicationOptions(self, allApps):
        if len(allApps) > 0:
            for app in allApps:
                app.addToOptionGroups(allApps, [ self.optionGroup ])
        else:
            configObject = plugins.importAndCall("default", "getConfig", {}) # don't care about inputOptions as we're trying to read them!
            configObject.addToOptionGroups(allApps, [ self.optionGroup ])
            

class ActionDialogGUI(OptionGroupGUI):
    def runInteractive(self, *args):
        if self.busy: # If we're busy with some other action, ignore this one ...
            return
                
        try:
            self.showConfigurationDialog()
        except plugins.TextTestError, e:
            self.showErrorDialog(str(e))
            
    def showConfigurationDialog(self):
        dialog = self.createDialog()
        alignment = self.createAlignment()
        vbox = gtk.VBox()
        fileChooser, scriptName = self.fillVBox(vbox)
        alignment.add(vbox)
        dialog.vbox.pack_start(alignment, expand=True, fill=True)
        self.createButtons(dialog, fileChooser, scriptName)
        self.tryResize(dialog)
        dialog.show_all()
        self.describeDialog(dialog, self.getOptionGroupDescription(self.optionGroup))

    def getConfirmationDialogSettings(self):
        return gtk.STOCK_DIALOG_WARNING, "Confirmation"
    
    def _respond(self, saidOK=True, dialog=None):
        if saidOK:
            try:
                message = self.getConfirmationMessage()
                if message:
                    stockId, level = self.getConfirmationDialogSettings()
                    self.showQueryDialog(self.getQueryParentWindow(dialog), message, stockId, level, self.confirmationRespond)
                else:
                    self.defaultRespond(saidOK, dialog)
            except plugins.TextTestError, e:
                self.showErrorDialog(str(e))
        else:
            self.defaultRespond(saidOK, dialog)
    def getQueryParentWindow(self, dialog):
        if dialog:
            return dialog
        else:
            return self.getParentWindow()
    def confirmationRespond(self, button, saidOK, dialog):
        self.defaultRespond(saidOK, dialog)
        if saidOK:
            parent = dialog.get_transient_for()
            if isinstance(parent, gtk.Dialog):
                self._cleanDialog(parent)
    def defaultRespond(self, *args):
        OptionGroupGUI._respond(self, *args)
    def tryResize(self, dialog):
        hordiv, verdiv = self.getResizeDivisors()
        if hordiv is not None:
            parentSize = self.topWindow.get_size()
            dialog.resize(int(parentSize[0] / hordiv), int(parentSize[0] / verdiv))
        
    def getResizeDivisors(self):
        return None, None
    
    def setSensitivity(self, newValue):
        ActionGUI.setSensitivity(self, newValue)
        if newValue:
            self.updateOptions()
            
    def createAlignment(self):
        alignment = gtk.Alignment()
        alignment.set(1.0, 1.0, 1.0, 1.0)
        alignment.set_padding(5, 5, 5, 5)
        return alignment

    def getOkStock(self, scriptName):
        if scriptName.startswith("load"):
            return "texttest-stock-load"
        elif scriptName.startswith("save"):
            return gtk.STOCK_SAVE
        else:
            return gtk.STOCK_OK

    def createButtons(self, dialog, fileChooser, scriptName):
        cancelButton = dialog.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL)
        actionScriptName = self.getTooltip()
        okButton = dialog.add_button(self.getOkStock(actionScriptName.lower()), gtk.RESPONSE_ACCEPT)
        dialog.set_default_response(gtk.RESPONSE_ACCEPT)
        if fileChooser:
            buttonScriptName = "press " + actionScriptName.split()[0]
            if fileChooser.get_property("action") == gtk.FILE_CHOOSER_ACTION_SAVE:
                scriptEngine.registerSaveFileChooser(fileChooser, scriptName,
                                                     "choose folder", buttonScriptName, "press cancel",
                                                     self.respond, okButton, cancelButton, dialog)
            else:
                scriptEngine.registerOpenFileChooser(fileChooser, scriptName,
                                                     "look in folder", buttonScriptName, "press cancel", 
                                                     self.respond, okButton, cancelButton, dialog)
        else:
            scriptEngine.connect("press cancel", "clicked", cancelButton, self.respond, gtk.RESPONSE_CANCEL, False, dialog)
            scriptEngine.connect("press ok", "clicked", okButton, self.respond, gtk.RESPONSE_ACCEPT, True, dialog)

    def fillVBox(self, vbox):
        fileChooser, scriptName = None, ""
        allOptions = self.optionGroup.options.values()
        for option in allOptions:
            self.addValuesFromConfig(option)
            
            if option.selectFile or option.selectDir or option.saveFile:
                scriptName = option.name
                fileChooser = self.createFileChooser(option)
                if len(allOptions) > 1: # If there is other stuff, add a frame round the file chooser so we can see what it's for
                    label = self.createLabelEventBox(option, separator=":")
                    frame = gtk.Frame()
                    frame.set_label_widget(label)
                    frame.add(fileChooser)
                    vbox.pack_start(frame, expand=True, fill=True)
                else:
                    vbox.pack_start(fileChooser, expand=True, fill=True)
            else:
                label, entryWidget, entry = self.createOptionEntry(option, separator=":")
                entry.set_activates_default(True)
                self.addLabel(vbox, label)
                vbox.pack_start(entryWidget, expand=False, fill=False)
                
        self.addSwitches(vbox, self.optionGroup)            
        return fileChooser, scriptName

    def addLabel(self, vbox, label):
        hbox = gtk.HBox()
        hbox.pack_start(label, expand=False, fill=False)        
        vbox.pack_start(hbox, expand=False, fill=False)
                
    def createRadioButtonCollection(self, switch, optionGroup):
        frame = gtk.Frame(switch.name)
        frameBox = gtk.VBox()
        for button in self.createRadioButtons(switch, optionGroup):
            frameBox.pack_start(button)
        frame.add(frameBox)
        return frame
    
    def getFileChooserFlag(self, option):
        if option.selectFile:
            return gtk.FILE_CHOOSER_ACTION_OPEN
        elif option.selectDir:
            return gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER
        else:
            return gtk.FILE_CHOOSER_ACTION_SAVE
    def createFileChooser(self, option):
        fileChooser = gtk.FileChooserWidget(self.getFileChooserFlag(option))
        fileChooser.set_show_hidden(True)
        folders, defaultFolder = option.getDirectories()
        startFolder = os.getcwd() # Just to make sure we always have some dir ...
        if defaultFolder and os.path.isdir(os.path.abspath(defaultFolder)):
            startFolder = os.path.abspath(defaultFolder)
            
        # We want a filechooser dialog to let the user choose where, and
        # with which name, to save the selection.
        fileChooser.set_current_folder(startFolder)
        for folder in folders:
            fileChooser.add_shortcut_folder(folder)
            
        fileChooser.set_local_only(True)
        option.setMethods(fileChooser.get_filename, fileChooser.set_filename)
        return fileChooser

    def getOptionDescription(self, option):
        if option.selectFile or option.selectDir or option.saveFile:
            text = "Viewing filechooser for option '" + option.name.replace("\n", "\\n") + "'"
            value = option.getValue()
            if value:
                text += " (set to '" + value + "')"
            possDirs = option.getPossibleDirs()
            if len(possDirs):
                text += " (choosing from directories " + repr(possDirs) + ")"
            return text
        else:
            return OptionGroupGUI.getOptionDescription(self, option)

    def getFilterFileDirs(self, allApps):
        if len(allApps) > 0:
            return allApps[0].getFilterFileDirectories(allApps, createDirs=False)
        else:
            return []
        


class MultiActionGUIForwarder(GtkActionWrapper):
    def __init__(self, actionGUIs):
        self.actionGUIs = actionGUIs
        GtkActionWrapper.__init__(self)
            
    def setObservers(self, observers):
        for actionGUI in self.actionGUIs:
            actionGUI.setObservers(observers)
            
    def addToGroups(self, *args):
        for actionGUI in self.actionGUIs:
            actionGUI.addToGroups(*args)
        GtkActionWrapper.addToGroups(self, *args)
        
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
    def __init__(self):
        self.diag = plugins.getDiagnostics("Interactive Actions")

    def getDefaultAccelerators(self, allApps):
        return self.joinDictionaries(allApps, lambda x: x.getDefaultAccelerators())

    def getColourDictionary(self, allApps):
        return self.joinDictionaries(allApps, lambda x: x.getColourDictionary())

    def joinDictionaries(self, allApps, method):
        if len(allApps) == 0:
            return method(self._getIntvActionConfig())

        dict = {}
        for app in allApps:
            config = self.getIntvActionConfig(app)
            dict.update(method(config))
        return dict
        
    def getMenuNames(self, allApps):
        if len(allApps) == 0:
            return self._getIntvActionConfig().getMenuNames()
        names = []
        for app in allApps:
            for name in self.getIntvActionConfig(app).getMenuNames():
                if name not in names:
                    names.append(name)
        return names
    
    def getPluginGUIs(self, dynamic, allApps, uiManager):
        instances = self.getInstances(dynamic, allApps)
        defaultGUIs, actionTabGUIs = [], []
        for action in instances:
            if action.displayInTab():
                self.diag.info("Tab: " + str(action.__class__))
                actionTabGUIs.append(action)
            else:
                self.diag.info("Menu/toolbar: " + str(action.__class__))
                # It's always active, always visible
                action.setActive(True)
                defaultGUIs.append(action)

        actionGroup = gtk.ActionGroup("AllActions")
        uiManager.insert_action_group(actionGroup, 0)
        accelGroup = uiManager.get_accel_group()
        for actionGUI in defaultGUIs + actionTabGUIs:
            actionGUI.addToGroups(actionGroup, accelGroup)

        return defaultGUIs, actionTabGUIs

    def getIntvActionConfig(self, app):
        module = app.getConfigValue("interactive_action_module")
        try:
            return self._getIntvActionConfig(module)
        except ImportError:
            return self._getIntvActionConfig()

    def _getIntvActionConfig(self, module="default_gui"):
        return plugins.importAndCall(module, "InteractiveActionConfig")
    
    def getInstances(self, dynamic, allApps):
        if len(allApps) == 0:
            config = self._getIntvActionConfig()
            return self.getInstancesFromConfig(config, dynamic, allApps)
        instances = []
        classNames = []
        for app in allApps:
            config = self.getIntvActionConfig(app)
            instances += self.getInstancesFromConfig(config, dynamic, allApps, classNames)
        return instances

    def getInstancesFromConfig(self, config, dynamic, allApps, classNames=[]):
        instances = []
        for className in config.getInteractiveActionClasses(dynamic):
            if className not in classNames:
                allClasses = self.findAllClasses(className, allApps, dynamic)
                subinstances = self.makeAllInstances(allClasses, dynamic)
                if len(subinstances) == 1:
                    instances.append(subinstances[0])
                else:
                    showable = filter(lambda x: x.shouldShow(), subinstances)
                    if len(showable) == 1:
                        instances.append(showable[0])
                    else:
                        instances.append(MultiActionGUIForwarder(subinstances))
                classNames.append(className)
        return instances
    
    def makeAllInstances(self, allClasses, dynamic):
        instances = []
        for classToUse, relevantApps in allClasses:
            instances.append(self.tryMakeInstance(classToUse, relevantApps, dynamic))
        return instances

    def findAllClasses(self, className, allApps, dynamic):
        if len(allApps) == 0:
            return [ (className, []) ]
        else:
            classNames = seqdict()
            for app in allApps:
                config = self.getIntvActionConfig(app)
                replacements = config.getReplacements()
                if className in config.getInteractiveActionClasses(dynamic):
                    realClassName = replacements.get(className, className)
                    classNames.setdefault(realClassName, []).append(app)
            return classNames.items()
    
    def tryMakeInstance(self, className, apps, dynamic):
        # Basically a workaround for crap error message with variable className from python...
        try:
            instance = className(apps, dynamic)
            self.diag.info("Creating " + str(instance.__class__.__name__) + " instance for " + repr(apps))
            return instance
        except:
            # If some invalid interactive action is provided, need to know which
            sys.stderr.write("Error with interactive action " + str(className.__name__) + "\n")
            raise

    def classValid(self, className, app):
        return self.getIntvActionConfig(app).isValid(className)
        
        
interactiveActionHandler = InteractiveActionHandler()
