
import gtk, entrycompletion, plugins, os, sys, shutil, time, subprocess, operator, types
from gtkusecase import RadioGroupIndexer
from jobprocess import JobProcess
from copy import copy, deepcopy
from threading import Thread
from glob import glob
from stat import *
from ndict import seqdict
from log4py import LOGLEVEL_NORMAL

guilog, guiConfig, scriptEngine = None, None, None

def setUpGlobals(dynamic, allApps):
    global guilog, guiConfig, scriptEngine
    from gtkusecase import ScriptEngine
    if dynamic:
        guilog = plugins.getDiagnostics("dynamic GUI behaviour")
    else:
        guilog = plugins.getDiagnostics("static GUI behaviour")
    guiConfig = GUIConfig(dynamic, allApps)
    scriptEngine = ScriptEngine(guilog, enableShortcuts=1)
    return guilog, guiConfig, scriptEngine

class GUIConfig:
    def __init__(self, dynamic, allApps):
        self.apps = allApps
        self.dynamic = dynamic
        self.hiddenCategories = map(self.getConfigName, self.getValue("hide_test_category"))
        self.colourDict = self.makeColourDictionary()
        self.setUpEntryCompletion()
    def makeColourDictionary(self):
        dict = {}
        for app in self.apps:
            for key, value in self.getColoursForApp(app):
                if dict.has_key(key) and dict[key] != value:
                    plugins.printWarning("Test colour for state '" + key +\
                                     "' differs between applications, ignoring that from " + repr(app) + "\n" + \
                                     "Value was " + repr(value) + ", change from " + repr(dict[key]))
                else:
                    dict[key] = value
        return dict
    def getColoursForApp(self, app):
        colours = seqdict()
        for key, value in app.getConfigValue("test_colours").items():
            colours[self.getConfigName(key)] = value
        return colours.items()
    def setUpEntryCompletion(self):
        matching = self.getValue("gui_entry_completion_matching")
        if matching != 0:
            inline = self.getValue("gui_entry_completion_inline")
            completions = self.getCompositeValue("gui_entry_completions", "", modeDependent=True)
            entrycompletion.manager.start(matching, inline, completions, guilog)
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
        return self._getFromApps(self._simpleValue, nameToUse)
    def getCompositeValue(self, sectionName, entryName, modeDependent=False, defaultKey="default"):
        nameToUse = self.getConfigName(entryName, modeDependent)
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
            return self.getCompositeValue("test_colours", "static")
    
# The purpose of this class is to provide a means to monitor externally
# started process, so that (a) code can be called when they exit, and (b)
# they can be terminated when TextTest is terminated.
class ProcessTerminationMonitor(plugins.Observable):
    def __init__(self):
        plugins.Observable.__init__(self)
        self.processes = []
    def addMonitoring(self, process, description, exitHandler, exitHandlerArgs):
        self.processes.append((process, description))
        newThread = Thread(target=self.monitor, args=(process, exitHandler, exitHandlerArgs))
        newThread.start()
    def monitor(self, process, exitHandler, exitHandlerArgs):
        try:
            process.wait()
            if exitHandler:
                exitHandler(*exitHandlerArgs)
        except OSError:
            pass # Can be thrown by wait() sometimes when the process is killed
    def listRunningProcesses(self):
        processesToCheck = guiConfig.getCompositeValue("query_kill_processes", "", modeDependent=True)
        running = []
        if len(processesToCheck) == 0:
            return running
        for process, description in self.getRunningProcesses():
            for processToCheck in processesToCheck:
                if plugins.isRegularExpression(processToCheck):
                    if plugins.findRegularExpression(processToCheck, description):
                        running.append("PID " + str(process.pid) + " : " + description)
                        break
                elif processToCheck.lower() == "all" or description.find(processToCheck) != -1:
                    running.append("PID " + str(process.pid) + " : " + description)
                    break

        return running
    
    def startProcess(self, cmdArgs, description = "", exitHandler=None, exitHandlerArgs=(),
                     scriptName="", filesEdited = "", **kwargs):
        process = subprocess.Popen(cmdArgs, stdin=open(os.devnull), startupinfo=plugins.getProcessStartUpInfo(), **kwargs)
        self.addMonitoring(process, description, exitHandler, exitHandlerArgs)
        if scriptName:
            scriptEngine.monitorProcess(scriptName, process, filesEdited)
        
    def getRunningProcesses(self):
        return filter(lambda (process, desc): process.poll() is None, self.processes)
    def notifyKillProcesses(self, sig=None):
        # Don't leak processes
        runningProcesses = self.getRunningProcesses()
        if len(runningProcesses) == 0:
            return
        self.notify("Status", "Terminating all external viewers ...")
        for process, description in runningProcesses:
            self.notify("ActionProgress", "")
            guilog.info("Killing '" + description + "' interactive process")
            JobProcess(process.pid).killAll(sig)
        

processMonitor = ProcessTerminationMonitor()
       
class InteractiveAction(plugins.Observable):
    def __init__(self, allApps, *args):
        plugins.Observable.__init__(self)
        self.currTestSelection = []
        self.currFileSelection = []
        self.currAppSelection = []
        self.diag = plugins.getDiagnostics("Interactive Actions")
        self.optionGroup = plugins.OptionGroup(self.getTabTitle())
        # convenience shortcuts...
        self.addOption = self.optionGroup.addOption
        self.addSwitch = self.optionGroup.addSwitch
        self.validApps = []
        for app in allApps:
            self.validApps.append(app)
            self.validApps += app.extras
    def __repr__(self):
        if self.optionGroup.name:
            return self.optionGroup.name
        else:
            return self.getTitle()
    def allAppsValid(self):
        for app in self.currAppSelection:
            if app not in self.validApps:
                self.diag.info("Rejecting due to invalid selected app : " + repr(app))
                return False
        return True
    def addSuites(self, suites):
        pass
    def getOptionGroups(self):
        if self.optionGroup.empty():
            return []
        else:
            return [ self.optionGroup ]
    def createOptionGroupTab(self, optionGroup):
        return optionGroup.switches or optionGroup.options
    def notifyNewTestSelection(self, tests, apps, rowCount, *args):
        self.updateSelection(tests, rowCount)
        self.currAppSelection = apps
        newActive = self.allAppsValid() and self.isActiveOnCurrent()
        self.diag.info("New test selection for " + self.getTitle() + "=" + repr(tests) + " : new active = " + repr(newActive))
        self.changeSensitivity(newActive)
        
    def notifyLifecycleChange(self, test, state, desc):
        newActive = self.isActiveOnCurrent(test, state)
        self.diag.info("State change for " + self.getTitle() + "=" + state.category + " : new active = " + repr(newActive))
        self.changeSensitivity(newActive)

    def updateFileSelection(self, files):
        self.currFileSelection = files
        newActive = self.isActiveOnCurrent()
        self.diag.info("New file selection for " + self.getTitle() + "=" + repr(files) + " : new active = " + repr(newActive))
        self.changeSensitivity(newActive)

    def changeSensitivity(self, newActive):
        self.notify("Sensitivity", newActive)
        if newActive:
            if self.updateOptions():
                self.notify("UpdateOptions")
    def singleTestOnly(self):
        return False

    def updateSelection(self, tests, rowCount):
        if rowCount != 1 and self.singleTestOnly():
            self.currTestSelection = []
        else:
            self.currTestSelection = tests
            testClass = self.correctTestClass()
            if testClass:
                self.currTestSelection = filter(lambda test: test.classId() == testClass, tests)
    
    def updateOptions(self):
        return False     
    def isActiveOnCurrent(self, *args):
        return len(self.currTestSelection) > 0
    def describeTests(self):
        if len(self.currTestSelection) == 1:
            return repr(self.currTestSelection[0])
        else:
            return str(len(self.currTestSelection)) + " tests"
    def isSelected(self, test):
        return test in self.currTestSelection
    def isNotSelected(self, test):
        return not self.isSelected(test)
    def correctTestClass(self):
        pass
    def inButtonBar(self):
        return not self.inMenuOrToolBar() and len(self.getOptionGroups()) == 0
    def testDescription(self):
        if len(self.currTestSelection) > 0:
            return " (from test " + self.currTestSelection[0].uniqueName + ")"
        else:
            return ""

    # Should we create a gtk.Action? (or connect to button directly ...)
    def inMenuOrToolBar(self): 
        return True
    def getStockId(self): # The stock ID for the action, in toolbar and menu.
        pass
    def getTooltip(self):
        return self.getScriptTitle(False)
    def getDialogType(self): # The dialog type to launch on action execution.
        try:
            self.confirmationMessage = self.getConfirmationMessage()
            if self.confirmationMessage:
                return "guidialogs.ConfirmationDialog"
            else:
                return ""
        except plugins.TextTestError, e:
            self.notify("Error", str(e))
    def getResultDialogType(self): # The dialog type to launch when the action has finished execution.
        return ""
    def getTitle(self, includeMnemonics=False):
        title = self._getTitle()
        if includeMnemonics:
            return title
        else:
            return title.replace("_", "")
    def getDirectories(self):
        return ([], None)
    def messageBeforePerform(self):
        # Don't change this by default, most of these things don't take very long
        pass
    def messageAfterPerform(self):
        return "Performed '" + self.getTooltip() + "' on " + self.describeTests() + "."
    def getConfirmationMessage(self):
        return ""
    def getTabTitle(self):
        return self.getGroupTabTitle()
    def getGroupTabTitle(self):
        # Default behaviour is not to create a group tab, override to get one...
        return "Test"
    def getScriptTitle(self, tab):
        baseTitle = self._getScriptTitle()
        if tab and self.inMenuOrToolBar():
            return baseTitle + " from tab"
        else:
            return baseTitle
    def _getScriptTitle(self):
        return self.getTitle()
    def describe(self, testObj, postText = ""):
        guilog.info(testObj.getIndent() + repr(self) + " " + repr(testObj) + postText)
    def startPerform(self):
        message = self.messageBeforePerform()
        if message != None:
            self.notify("Status", message)
        self.notify("ActionStart", message)
        try:
            self.performOnCurrent()
            message = self.messageAfterPerform()
            if message != None:
                self.notify("Status", message)
        except plugins.TextTestError, e:
            self.notify("Error", str(e))
    def endPerform(self):
        self.notify("ActionStop", "")
    def perform(self):
        try:
            self.startPerform()
        finally:
            self.endPerform()
    def cancel(self):
        self.notify("Status", "Action cancelled.")
                

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


class ActionGUI(SubGUI):
    busy = False
    def __init__(self, action):
        SubGUI.__init__(self)
        self.action = action
    def getStockId(self):
        stockId = self.action.getStockId()
        if stockId:
            return "gtk-" + stockId 
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
    def getTopWindow(self):
        pass
    def runInteractive(self, *args):
        if self.busy: # If we're busy with some other action, ignore this one ...
            return
        dialogType = self.action.getDialogType()
        if dialogType is not None:
            if dialogType:
                dialog = pluginHandler.getInstance(dialogType, self.getTopWindow(),
                                                   self._runInteractive, self.action.cancel, self.action)
                dialog.run()
            else:
                # Each time we perform an action we collect and save the current registered entries
                # Actions showing dialogs will handle this in the dialog code.
                entrycompletion.manager.collectCompletions()
                self._runInteractive()
    def _runInteractive(self):
        try:
            ActionGUI.busy = True
            self.action.startPerform()
            resultDialogType = self.action.getResultDialogType()
            if resultDialogType:
                resultDialog = pluginHandler.getInstance(resultDialogType, self.getTopWindow(), None, self.action)
                resultDialog.run()
        finally:
            self.action.endPerform()
            ActionGUI.busy = False
           
class DefaultActionGUI(ActionGUI):
    def __init__(self, action):
        ActionGUI.__init__(self, action)
        self.accelerator = None
        self.topWindow = None
        title = self.action.getTitle(includeMnemonics=True)
        actionName = self.action.getTitle(includeMnemonics=False)
        self.gtkAction = gtk.Action(actionName, title, \
                                    self.action.getTooltip(), self.getStockId())
        scriptEngine.connect(self.action.getScriptTitle(False), "activate", self.gtkAction, self.runInteractive)
        if not action.isActiveOnCurrent():
            self.gtkAction.set_property("sensitive", False)
    def notifyTopWindow(self, window):
        self.topWindow = window
    def getTopWindow(self):
        return self.topWindow
    def addToGroups(self, actionGroup, accelGroup):
        self.accelerator = self.getAccelerator()
        actionGroup.add_action_with_accel(self.gtkAction, self.accelerator)
        self.gtkAction.set_accel_group(accelGroup)
        self.gtkAction.connect_accelerator()
        
    def actionOrButton(self):
        return self.gtkAction
        
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
    def getTopWindow(self):
        return self.button.get_toplevel()
    def actionOrButton(self):
        return self.button
    def createView(self):
        self.createButton()
        if not self.action.isActiveOnCurrent():
            self.button.set_property("sensitive", False)
        return self.button
    def createButton(self):
        self.button = gtk.Button(self.action.getTitle(includeMnemonics=True))
        if self.getStockId():
            self.button.set_image(gtk.image_new_from_stock(self.getStockId(), gtk.ICON_SIZE_BUTTON))
        self.tooltips.set_tip(self.button, self.scriptTitle)
        scriptEngine.connect(self.scriptTitle, "clicked", self.button, self.runInteractive)
        self.button.show()
        return self.button

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
        entrycompletion.manager.register(entry)
        # Options in drop-down lists don't change, so we just add them once and for all.
        for text in option.listPossibleValues():
            entrycompletion.manager.addTextCompletion(text)
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
                                       self.vbox.get_toplevel(),
                                       gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER,
                                       (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                        gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        self.startChooser(dialog, entry, option)

    def showFileChooser(self, widget, entry, option):
        dialog = gtk.FileChooserDialog("Select a file",
                                       self.vbox.get_toplevel(),
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
                                             "open selected file", "cancel file selection", self.respond, respondMethodArg=entry)
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
    def respond(self, dialog, response, entry):
        if response == gtk.RESPONSE_OK:
            entry.set_text(dialog.get_filename().replace("\\", "/"))
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

# Placeholder for all classes. Remember to add them!
class InteractiveActionHandler:
    def __init__(self):
        self.diag = plugins.getDiagnostics("Interactive Actions")
    def getMenuNames(self, allApps):
        names = []
        for app in allApps:
            config = self.getIntvActionConfig(app)
            for name in config.getMenuNames():
                if name not in names:
                    names.append(name)
        return names
    def getIntvActionConfig(self, app):
        module = app.getConfigValue("interactive_action_module")
        try:
            return self._getIntvActionConfig(module)
        except ImportError:
            return self._getIntvActionConfig("default_gui")
    def _getIntvActionConfig(self, module):
        command = "from " + module + " import InteractiveActionConfig"
        exec command
        return InteractiveActionConfig()

    def getPluginGUIs(self, dynamic, allApps):
        instances = self.getInstances(dynamic, allApps)
        defaultGUIs, buttonGUIs, actionTabGUIs = [], [], []
        for action in instances:
            if action.inMenuOrToolBar():
                defaultGUIs.append(DefaultActionGUI(action))
            elif action.inButtonBar():
                buttonGUIs.append(ButtonActionGUI(action))

            optionGroups = action.getOptionGroups()
            if len(optionGroups) > 0:
                actionGUI = ButtonActionGUI(action, fromTab=True)
                for optionGroup in optionGroups:
                    if action.createOptionGroupTab(optionGroup):
                        actionTabGUIs.append(ActionTabGUI(optionGroup, action, actionGUI))

        return instances, defaultGUIs, buttonGUIs, actionTabGUIs
    
    def getInstances(self, dynamic, allApps):
        instances = []
        classNames = []
        for app in allApps:
            config = self.getIntvActionConfig(app)
            for className in config.getInteractiveActionClasses(dynamic):
                if not className in classNames:
                    for classToUse, relevantApps in self.findAllClasses(className, allApps, dynamic):
                        instances.append(self.tryMakeInstance(classToUse, relevantApps, dynamic))
                    classNames.append(className)
        return instances

    def findAllClasses(self, className, allApps, dynamic):
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
        
        
interactiveActionHandler = InteractiveActionHandler()
