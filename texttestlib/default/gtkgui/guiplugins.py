from gi.repository import Gtk, GObject

import os
import subprocess
import types
import logging
import sys
from . import entrycompletion
from texttestlib import plugins
from .guiutils import guiConfig, SubGUI, GUIConfig, createApplicationEvent
from texttestlib.jobprocess import killSubProcessAndChildren
from collections import OrderedDict

# The purpose of this class is to provide a means to monitor externally
# started process, so that (a) code can be called when they exit, and (b)
# they can be terminated when TextTest is terminated.


class ProcessTerminationMonitor(plugins.Observable):
    def __init__(self):
        plugins.Observable.__init__(self)
        self.processesForKill = OrderedDict()
        self.exitHandlers = OrderedDict()

    def listQueryKillProcesses(self):
        processesToCheck = guiConfig.getCompositeValue("query_kill_processes", "", modeDependent=True)
        if "all" in processesToCheck:
            processesToCheck = [".*"]
        if len(processesToCheck) == 0:
            return []

        running = []
        triggerGroup = plugins.TextTriggerGroup(processesToCheck)
        for process, description in self.getProcesses():
            if triggerGroup.stringContainsText(description):
                running.append("PID " + str(process.pid) + " : " + description)

        return running

    def getProcesses(self):
        return list(self.processesForKill.values())

    def getProcessIdentifier(self, process):
        # Unfortunately the child_watch_add method needs different ways to
        # identify the process on different platforms...
        if os.name == "posix":
            return process.pid
        else:
            return process._handle

    def startProcess(self, cmdArgs, description="", killOnTermination=True, exitHandler=None, exitHandlerArgs=(), **kwargs):
        process = subprocess.Popen(cmdArgs, stdin=open(os.devnull), **kwargs)
        pidOrHandle = self.getProcessIdentifier(process)
        self.exitHandlers[int(pidOrHandle)] = (exitHandler, exitHandlerArgs)
        if killOnTermination:
            self.processesForKill[int(pidOrHandle)] = (process, description)
        GObject.child_watch_add(pidOrHandle, self.processExited, process.pid)

    def processExited(self, pidOrHandle, condition, pid):
        output = ""
        self.notify("ProcessExited", pid)
        if pidOrHandle in self.processesForKill:
            process = self.processesForKill[pidOrHandle][0]
            if process.stdout is not None:
                output = process.stdout.read().strip()
            del self.processesForKill[pidOrHandle]

        if pidOrHandle in self.exitHandlers:
            exitHandler, exitHandlerArgs = self.exitHandlers.pop(pidOrHandle)
            if exitHandler:
                exitHandler(*exitHandlerArgs)
                if output:
                    command, arg = output.split(" ", 1)
                    self.notify(command, arg)

    def notifyKillProcesses(self, sig=None):
        # Don't leak processes
        if len(self.processesForKill) == 0:
            return
        diag = logging.getLogger("kill processes")
        self.notify("Status", "Terminating all external viewers ...")
        for pid, (process, description) in list(self.processesForKill.items()):
            if pid in self.exitHandlers:
                self.exitHandlers.pop(pid)  # don't call exit handlers in this case, we're terminating
            self.notify("ActionProgress")
            diag.info("Killing '" + description + "' interactive process")
            killSubProcessAndChildren(process, sig)


processMonitor = ProcessTerminationMonitor()


def openLinkInBrowser(*files):
    if os.name == "nt" and "BROWSER" not in os.environ and len(files) == 1:
        os.startfile(files[0])  # @UndefinedVariable
        createApplicationEvent("the browser to be closed", "browser")
        return 'Started "<default browser> ' + files[0] + '" in background.'
    else:
        browser = os.getenv("BROWSER", "firefox")
        cmdArgs = [browser] + list(files)
        processMonitor.startProcess(cmdArgs, exitHandler=createApplicationEvent,
                                    exitHandlerArgs=("the browser to be closed", "browser"))
        return 'Started "' + " ".join(cmdArgs) + '" in background.'


class GtkActionWrapper:
    def __init__(self):
        self.accelerator = None
        self.diag = logging.getLogger("Interactive Actions")
        title = self.getTitle(includeMnemonics=True)
        actionName = self.getActionName()
        self.gtkAction = Gtk.Action(actionName, title,
                                    self.getTooltip(), self.getStockId())
        self.gtkAction.connect("activate", self.runInteractive)
        if not self.isActiveOnCurrent():
            self.gtkAction.set_property("sensitive", False)

    def getActionName(self):
        return self.getTitle(includeMnemonics=False)

    def getAccelerator(self, title):
        realAcc = guiConfig.getCompositeValue("gui_accelerators", title)
        if realAcc:
            key, mod = Gtk.accelerator_parse(realAcc)
            if Gtk.accelerator_valid(key, mod):
                return realAcc
            else:
                plugins.printWarning("Keyboard accelerator '" + realAcc + "' for action '"
                                     + title + "' is not valid, ignoring ...")

    def addToGroups(self, actionGroup, accelGroup):
        self.accelerator = self._addToGroups(self.gtkAction.get_name().rstrip("."),
                                             self.gtkAction, actionGroup, accelGroup)

    def _addToGroups(self, actionName, gtkAction, actionGroup, accelGroup):
        # GTK 2.12 got fussy about this...
        existingAction = actionGroup.get_action(actionName)
        if existingAction:
            self.diag.info("Removing action with label " + existingAction.get_property("label"))
            actionGroup.remove_action(existingAction)

        accelerator = self.getAccelerator(actionName)
        actionGroup.add_action_with_accel(gtkAction, accelerator)
        gtkAction.set_accel_group(accelGroup)
        gtkAction.connect_accelerator()
        return accelerator

    def setSensitivity(self, newValue):
        self._setSensitivity(self.gtkAction, newValue)

    def _setSensitivity(self, gtkAction, newValue):
        oldValue = gtkAction.get_property("sensitive")
        if oldValue != newValue:
            gtkAction.set_property("sensitive", newValue)


# Introduce an extra level without all the selection-dependent stuff, some actions want
# to inherit from here and it provides a separation
class BasicActionGUI(SubGUI, GtkActionWrapper):
    busy = False

    def __init__(self, *args):
        SubGUI.__init__(self)
        GtkActionWrapper.__init__(self)
        self.topWindow = None

    def checkValid(self, app):
        pass

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
            dialog = Gtk.Dialog(self.getDialogTitle(), self.getParentWindow(), flags=Gtk.DialogFlags.MODAL)
            dialog.set_modal(True)
        else:
            dialog = Gtk.Dialog(self.getDialogTitle())

        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        # may need review MB 2018-12-04
        # there may be a flag achieving the behavior, as mentioned here http://docs.adacore.com/live/wave/gtkada/html/gtkada_ug/transition.html
        # dialog.set_has_separator(False)
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

    def _getStockId(self):  # The stock ID for the action, in toolbar and menu.
        pass

    def setObservers(self, observers):
        signals = ["Status", "ActionStart"] + self.getSignalsSent()
        self.diag.info("Observing " + str(self.__class__) + " :")
        for observer in observers:
            for signal in signals:
                if hasattr(observer, "notify" + signal):
                    self.diag.info("-> " + str(observer.__class__))
                    self.addObserver(observer)
                    break

    def getSignalsSent(self):
        return []  # set up like this so every single derived class doesn't have to include it

    def createDialogMessage(self, message, stockIcon):
        buffer = Gtk.TextBuffer()
        buffer.set_text(message)
        textView = Gtk.TextView.new_with_buffer(buffer)
        textView.set_editable(False)
        textView.set_cursor_visible(False)
        textView.set_left_margin(5)
        textView.set_right_margin(5)
        hbox = Gtk.HBox()
        imageBox = Gtk.VBox()
        imageBox.pack_start(Gtk.Image.new_from_stock(stockIcon, Gtk.IconSize.DIALOG), False, True, 0)
        hbox.pack_start(imageBox, False, True, 0)
        scrolledWindow = Gtk.ScrolledWindow()
        # What we would like is that the dialog expands without scrollbars
        # until it reaches some maximum size, and then adds scrollbars. At
        # the moment I cannot make this happen without setting a fixed window
        # size, so I'll set the scrollbar policy to never instead.
        scrolledWindow.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        scrolledWindow.add(textView)
        scrolledWindow.set_shadow_type(Gtk.ShadowType.IN)
        hbox.pack_start(scrolledWindow, True, True, 0)
        alignment = Gtk.Alignment.new(0.5, 0.5, 1.0, 1.0)
        alignment.set_padding(5, 5, 0, 5)
        alignment.add(hbox)
        return alignment

    def showErrorDialog(self, message):
        self.showErrorWarningDialog(message, Gtk.STOCK_DIALOG_ERROR, "Error")

    def showWarningDialog(self, message):
        self.showErrorWarningDialog(message, Gtk.STOCK_DIALOG_WARNING, "Warning")

    def showErrorWarningDialog(self, message, stockIcon, alarmLevel):
        dialog = self.createAlarmDialog(self.getParentWindow(), message, stockIcon, alarmLevel)
        dialog.add_button(Gtk.STOCK_OK, Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        dialog.connect("response", lambda d, r: self._cleanDialog(d))
        dialog.show_all()

    def createAlarmDialog(self, parent, message, stockIcon, alarmLevel):
        dialogTitle = "TextTest " + alarmLevel
        dialog = Gtk.Dialog(dialogTitle, parent, flags=Gtk.DialogFlags.MODAL)
        dialog.set_modal(True)
        # may need review MB 2018-12-05
        # there may be a flag achieving the behavior, as mentioned here http://docs.adacore.com/live/wave/gtkada/html/gtkada_ug/transition.html
        # dialog.set_has_separator(False)

        contents = self.createDialogMessage(message, stockIcon)
        dialog.vbox.pack_start(contents, True, True, 0)
        return dialog

    def showQueryDialog(self, parent, message, stockIcon, alarmLevel, respondMethod, respondData=None):
        dialog = self.createAlarmDialog(parent, message, stockIcon, alarmLevel)
        dialog.set_default_response(Gtk.ResponseType.NO)
        dialog.add_button(Gtk.STOCK_NO, Gtk.ResponseType.NO)
        dialog.add_button(Gtk.STOCK_YES, Gtk.ResponseType.YES)
        if respondMethod:
            dialog.connect("response", respondMethod, respondData)
        dialog.show_all()
        return dialog

    def _cleanDialog(self, dialog, *args):
        entrycompletion.manager.collectCompletions()
        dialog.hide()  # Can't destroy it, we might still want to read stuff from it

    def respond(self, dialog, responseId, *args):
        saidOK = responseId in [Gtk.ResponseType.ACCEPT, Gtk.ResponseType.YES, Gtk.ResponseType.OK]
        try:
            self._respond(saidOK, dialog, *args)
        except plugins.TextTestError as e:
            self.showErrorDialog(str(e))

    def _respond(self, saidOK, dialog, *args):
        if saidOK:
            self._runInteractive()
        else:
            self.cancel()
        if dialog:
            self._cleanDialog(dialog, *args)

    def getConfirmationMessage(self):
        return ""

    def runInteractive(self, *args):
        if self.busy:  # If we're busy with some other action, ignore this one ...
            return

        try:
            confirmationMessage = self.getConfirmationMessage()
            if confirmationMessage:
                self.showQueryDialog(self.getParentWindow(), confirmationMessage,
                                     Gtk.STOCK_DIALOG_WARNING, "Confirmation", self.respond)
            else:
                # Each time we perform an action we collect and save the current registered entries
                # Actions showing dialogs will handle this in the dialog code.
                entrycompletion.manager.collectCompletions()
                self._runInteractive()
        except plugins.TextTestError as e:
            self.showErrorDialog(str(e))
        except Exception as e:
            self.showErrorDialog(plugins.getExceptionString())

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
        self.notify("ActionStart")
        self.notify("ActionProgress")
        self.performOnCurrent()
        message = self.messageAfterPerform()
        if message != None:
            self.notify("Status", message)

    def endPerform(self):
        self.notify("ActionStop")

    def cancel(self):
        self.notify("Status", "Action cancelled.")


class ActionGUI(BasicActionGUI):
    busy = False

    def __init__(self, allApps, *args):
        self.currTestSelection = []
        self.currFileSelection = []
        self.currAppSelection = []
        self.validApps = []
        BasicActionGUI.__init__(self)
        for app in allApps:
            self.checkAllValid(app)

    def checkAllValid(self, app):
        for currApp in [app] + app.extras:
            if currApp not in self.validApps:
                self.checkValid(currApp)

    def checkValid(self, app):
        if self.isValidForApp(app):
            self.validApps.append(app)
        else:
            self.diag.info(str(self.__class__) + " invalid for " + repr(app))

    def isValidForApp(self, dummyApp):
        return True

    def shouldShow(self):
        return len(self.validApps) > 0

    def notifyNewTestSelection(self, *args):
        newActive = self.updateSelection(*args)
        self.setSensitivity(newActive)

    def getTestCaseSelection(self):
        testcases = []
        for test in self.currTestSelection:
            for testCase in test.testCaseList():
                if not testCase in testcases:
                    testcases.append(testCase)
        return testcases

    def updateSelection(self, tests, apps, rowCount, *args):
        if rowCount != 1 and self.singleTestOnly():
            self.currTestSelection = []
        else:
            self.currTestSelection = tests
            testClass = self.correctTestClass()
            if testClass:
                self.currTestSelection = [test for test in tests if test.classId() == testClass]

        self.currAppSelection = apps
        newActive = self.allAppsValid() and self.isActiveOnCurrent()
        self.diag.info("New test selection for " + self.getTitle() + "=" +
                       self.describeTests() + " : new active = " + repr(newActive))
        return newActive

    def notifyLifecycleChange(self, test, state, *args):
        newActive = self.isActiveOnCurrent(test, state)
        self.setSensitivity(newActive)

    def notifyNewFileSelection(self, files):
        newActive = self.updateFileSelection(files)
        self.setSensitivity(newActive)

    def updateFileSelection(self, files):
        self.currFileSelection = files
        newActive = self.allAppsValid() and self.isActiveOnCurrent()
        self.diag.info("New file selection for " + self.getTitle() + "=" +
                       repr(files) + " : new active = " + repr(newActive))
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
            return "test " + self.currTestSelection[0].getRelPath()
        else:
            return str(len(self.currTestSelection)) + " tests"

    def correctTestClass(self):
        pass

    def messageAfterPerform(self):
        return "Performed '" + self.getTooltip() + "' on " + self.describeTests() + "."

    def createTextWidget(self, name, scroll=False):
        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.OUT)
        frame.set_border_width(1)
        view = Gtk.TextView()
        view.set_wrap_mode(Gtk.WrapMode.WORD)
        view.set_name(name)
        buffer = view.get_buffer()
        if scroll:
            view = self.addScrollBars(view, Gtk.PolicyType.AUTOMATIC)
        frame.add(view)
        return frame, buffer

    def tryResize(self, dialog):
        horfrac, verfrac = self.getSizeAsWindowFraction()
        if horfrac is not None and self.topWindow is not None:
            width, height = self.topWindow.get_size()
            dialog.resize(int(width * horfrac), int(height * verfrac))

    def getSizeAsWindowFraction(self):
        return None, None

    def createButton(self):
        return self._createButton(self.gtkAction, self.getTooltip())

    def _createButton(self, action, tooltip):
        button = Gtk.Button()
        # needs review MB 2018-12-05
        button.set_related_action(action)
        # In theory all this should be automatic, but it appears not to work
        if self.getStockId():
            image = Gtk.Image.new_from_stock(self.getStockId(), Gtk.IconSize.BUTTON)
            button.set_image(image)
            image.show()

        button.set_tooltip_text(tooltip)
        button.show()
        return button

    def findTestsToReload(self):
        tests = []
        for test in self.currTestSelection:
            for currTest in test.getAllTestsToRoot():
                if currTest not in tests:
                    currTest.refreshFiles()
                    if currTest.hasLocalConfig():
                        tests.append(currTest)
        return tests

    def reloadConfigForSelected(self):
        for appOrTest in self.currAppSelection + self.findTestsToReload():
            self.notify("Status", "Rereading configuration for " + repr(appOrTest) + " ...")
            self.notify("ActionProgress")
            appOrTest.reloadConfiguration()


# These actions consist of bringing up a dialog and only doing that
# (i.e. the dialog is not a mechanism to steer how the action should be run)
class ActionResultDialogGUI(ActionGUI):
    def __init__(self, *args, **kw):
        self.dialog = None
        ActionGUI.__init__(self, *args, **kw)

    def performOnCurrent(self):
        self.dialog = self.createDialog()
        self.addContents()
        self.createButtons()
        self.tryResize(self.dialog)
        self.dialog.show_all()

    def addContents(self):  # pragma: no cover - documentation only
        pass

    def createButtons(self):
        self.dialog.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.ACCEPT)
        self.dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        self.dialog.connect("response", self.respond)

    def respond(self, dialog, responseId):
        if responseId != Gtk.ResponseType.NONE:
            self._cleanDialog(dialog)


class ComboBoxListFinder:
    def __init__(self, combobox):
        self.model = combobox.get_model()
        self.textColumn = combobox.get_entry_text_column()

    def __call__(self):
        entries = []
        self.model.foreach(self.getText, entries)
        return entries

    def getText(self, model, dummyPath, iter, entries):
        text = model.get_value(iter, self.textColumn)
        entries.append(text)


# A utility class to set and get the indices of options in radio button groups.
class RadioGroupIndexer:
    def __init__(self, listOfButtons):
        self.buttons = listOfButtons

    def getActiveIndex(self):
        for i in range(0, len(self.buttons)):
            if self.buttons[i].get_active():
                return i

    def setActiveIndex(self, index):
        self.buttons[index].set_active(True)


class OptionGroupGUI(ActionGUI):
    def __init__(self, *args):
        ActionGUI.__init__(self, *args)
        self.groupBoxes = {}
        self.optionGroup = plugins.OptionGroup(self.getTabTitle())
        # convenience shortcuts...
        self.addOption = self.optionGroup.addOption
        self.addSwitch = self.optionGroup.addSwitch

    def updateOptions(self):
        return False

    def updateForConfig(self, option):
        fromConfig = guiConfig.getCompositeValue("gui_entry_overrides", option.name)
        # only do this if it hasn't previously been manually overwritten
        if fromConfig is not None and fromConfig != "<not set>" and option.getValue() == option.defaultValue:
            newValue = fromConfig
            if isinstance(option.getValue(), int):
                newValue = int(fromConfig)
            option.setValue(newValue)
            return fromConfig

    def createLabelEventBox(self, option, separator):
        label = Gtk.EventBox()
        label.add(Gtk.Label(label=option.name + separator))
        if option.description and type(option.description) in (str, bytes):
            label.set_tooltip_text(option.description)
        return label

    def destroyedEntry(self, entry, data):
        option, entryOrBuffer = data
        if hasattr(option.valueMethod, "__self__") and option.valueMethod.__self__ is entryOrBuffer:
            option.setMethods(None, None)

    def connectEntry(self, option, entryOrBuffer, entryWidget):
        entryWidget.connect("destroy", self.destroyedEntry, (option, entryOrBuffer))

        def setText(t):
            entryOrBuffer.set_text(str(t))
        setText(option.getValue())
        # Don't pass entry.set_text directly, it will mess up StoryText's programmatic method interception
        option.setMethods(self.getGetTextMethod(entryOrBuffer), setText)
        if option.changeMethod:
            entryOrBuffer.connect("changed", option.changeMethod)

    def getGetTextMethod(self, widget):
        if isinstance(widget, Gtk.SpinButton):
            # Would be nice to return widget.get_value_as_int but that returns the wrong answer from
            # dialogs that have been closed
            def get_text():
                text = widget.get_text()
                return float(text) if widget.get_digits() else int(text)
            return get_text
        elif isinstance(widget, Gtk.Entry):
            return widget.get_text
        else:
            def get_text():
                return widget.get_text(widget.get_start_iter(), widget.get_end_iter(), True)
            return get_text

    def addValuesFromConfig(self, option, includeOverrides=True):
        if includeOverrides:
            newValue = self.updateForConfig(option)
            if newValue:
                option.addPossibleValue(newValue)
        for extraOption in self.getConfigOptions(option):
            option.addPossibleValue(extraOption)

    def createRadioButtonCollection(self, switch, optionGroup):
        hbox = Gtk.HBox()
        if len(switch.name) > 0:
            label = self.createLabelEventBox(switch, ":")
            hbox.pack_start(label, False, False, 0)
        for button in self.createRadioButtons(switch, optionGroup):
            hbox.pack_start(button, True, False, 0)
        hbox.show_all()
        return hbox

    def setConfigOverride(self, switch, index, option, *args):
        configName = self.getNaming(switch.name, option, *args)
        if index == switch.getValue() or guiConfig.getCompositeValue("gui_entry_overrides", configName) == "1":
            switch.setValue(index)

    def getNaming(self, switchName, option, *args):
        if len(switchName) > 0:
            return switchName + ":" + option
        else:
            return option

    def createRadioButtons(self, switch, optionGroup):
        buttons = []
        mainRadioButton = None
        individualToolTips = type(switch.description) == list
        for index, option in enumerate(switch.options):
            self.setConfigOverride(switch, index, option, optionGroup)
            radioButton = Gtk.RadioButton.new_with_mnemonic_from_widget(mainRadioButton, option)
            self.setRadioButtonName(radioButton, option, optionGroup)
            if individualToolTips:
                radioButton.set_tooltip_text(switch.description[index])

            buttons.append(radioButton)
            if not mainRadioButton:
                mainRadioButton = radioButton
            if switch.getValue() == index:
                radioButton.set_active(True)
            else:
                radioButton.set_active(False)

        indexer = RadioGroupIndexer(buttons)
        switch.setMethods(indexer.getActiveIndex, indexer.setActiveIndex)
        return buttons

    def createFrame(self, group, name):
        frame = Gtk.Frame.new(name)
        frame.set_label_align(0.5, 0.5)
        frame.set_shadow_type(Gtk.ShadowType.IN)
        frame.add(self.createGroupBox(group))
        return frame

    def createGroupBox(self, group):
        frameBox = Gtk.VBox()
        frameBox.set_border_width(10)
        self.fillVBox(frameBox, group)
        self.groupBoxes[group] = frameBox
        return frameBox

    def setGroupSensitivity(self, group, *args, **kw):
        widget = self.groupBoxes.get(group)
        self.setChildSensitivity(widget, *args, **kw)

    def setChildSensitivity(self, widget, sensitive, ignoreWidget=None):
        if widget is ignoreWidget or isinstance(widget, Gtk.RadioButton):
            return
        # needs review, just replaced ComboBoxEntry by ComboBox, maybe ComboBoxText would be better? MB 2018-12-05
        elif isinstance(widget, (Gtk.Entry, Gtk.CheckButton, Gtk.ComboBox)):
            widget.set_sensitive(sensitive)
        elif hasattr(widget, "get_children"):
            for child in widget.get_children():
                self.setChildSensitivity(child, sensitive, ignoreWidget)

    def setRadioButtonName(self, *args):
        pass  # Don't bother by default, it's easy to set stupid names...

    def createComboBox(self, switch, *args):
        combobox = Gtk.ComboBoxText()
        combobox.set_name(switch.name)
        for index, option in enumerate(switch.options):
            combobox.append_text(option)
            self.setConfigOverride(switch, index, option, *args)
            if switch.getValue() == index:
                combobox.set_active(index)

        switch.setMethods(combobox.get_active, combobox.set_active)
        box = Gtk.VBox()
        box.pack_start(Gtk.Label(""), True, True, 0)
        box.pack_start(combobox, True, True, 0)
        return box

    def transferEnable(self, enabler, switch):
        if enabler.get_active():
            switch.updateMethod(True)

    def extractSwitches(self, optionGroup):
        options, switches = [], []
        for option in list(optionGroup.options.values()):
            if isinstance(option, plugins.Switch):
                switches.append(option)
            else:
                options.append(option)
        return options, switches

    def findAutoEnableInfo(self, switches):
        info = {}
        for switch in switches:
            if isinstance(switch, plugins.Switch) and switch.autoEnable:
                for enableSwitchName in switch.autoEnable:
                    enabler = self.getOption(enableSwitchName)
                    if enabler:
                        info[enabler] = switch
        return info

    def createSwitchWidget(self, switch, optionGroup, autoEnableInfo):
        if len(switch.options) >= 1:
            if switch.hideOptions:
                return self.createComboBox(switch, optionGroup)
            else:
                return self.createRadioButtonCollection(switch, optionGroup)
        else:
            return self.createCheckBox(switch, autoEnableInfo)

    def createCheckBox(self, switch, autoEnableInfo):
        self.updateForConfig(switch)
        checkButton = Gtk.CheckButton(switch.name)
        if switch.description:
            checkButton.set_tooltip_text(switch.description)

        if int(switch.getValue()):
            checkButton.set_active(True)
        # Don't pass checkButton.set_active as that will screw up StoryText's interception of it
        switch.setMethods(checkButton.get_active, lambda x: checkButton.set_active(x))
        if switch in autoEnableInfo:
            toEnable = autoEnableInfo.get(switch)
            checkButton.connect("toggled", self.transferEnable, toEnable)

        checkButton.show()
        return checkButton

    def createComboBoxEntry(self, option):
        # may need review MB 2018-12-04
        combobox = Gtk.ComboBoxText.new_with_entry()
        entry = combobox.get_child()
        combobox.set_row_separator_func(self.isRowSeparator)
        option.setPossibleValuesMethods(combobox.append_text, ComboBoxListFinder(combobox))

        option.setClearMethod(combobox.get_model().clear)
        return combobox, entry

    def isRowSeparator(self, model, iter):
        text = model.get_value(iter, 0)
        return text == "-" * 10

    def createOptionWidget(self, option):
        optionName = option.name.strip()
        if option.multilineEntry:
            return self.createTextWidget(optionName)
        else:
            box = Gtk.HBox()
            value = option.getValue()
            if isinstance(value, int) or isinstance(value, float):
                adjustment = Gtk.Adjustment(value=value, lower=option.minimum,
                                            upper=option.maximum, step_incr=1)
                digits = int(isinstance(value, float))
                widget = Gtk.SpinButton.new(adjustment, 0., digits)
                widget.set_numeric(True)
                entry = widget
            elif option.usePossibleValues():
                widget, entry = self.createComboBoxEntry(option)
                widget.set_name(optionName + " (Combo Box)")
            else:
                widget = Gtk.Entry()
                entry = widget
            box.pack_start(widget, True, True, 0)
            entry.set_name(optionName)
            if not isinstance(widget, Gtk.SpinButton):
                entrycompletion.manager.register(entry)
            # Options in drop-down lists don't change, so we just add them once and for all.
            for text in option.listPossibleValues():
                # needs review, just added str to work around expected type error, MB 2018-12-05
                entrycompletion.manager.addTextCompletion(str(text))

            return box, entry

    def createFileChooserDialog(self, box, entry, option):
        button = Gtk.Button("...")
        box.pack_start(button, False, False, 0)
        button.connect("clicked", self.showFileChooser, entry, option)

    def showFileChooser(self, dummyWidget, entry, option):
        dialog = Gtk.FileChooserDialog("Select a file",
                                       self.getParentWindow(),
                                       Gtk.FileChooserAction.OPEN,
                                       (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                        Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        self.startFileChooser(dialog, entry, option)

    def startFileChooser(self, dialog, entry, option):
        # Folders is a list of pairs (short name, absolute path),
        # where 'short name' means the name given in the config file, e.g.
        # 'temporary_filter_files' or 'filter_files' ...
        dialog.set_modal(True)
        folders, defaultFolder = option.getDirectories()
        dialog.connect("response", self.respondFileChooser, entry)
        # If current entry forms a valid path, set that as default
        currPath = entry.get_text()
        currDir = os.path.split(currPath)[0]
        if os.path.isdir(currDir):
            dialog.set_current_folder(currDir)
        elif defaultFolder and os.path.isdir(os.path.abspath(defaultFolder)):
            dialog.set_current_folder(os.path.abspath(defaultFolder))
        for folder in folders:
            dialog.add_shortcut_folder(folder)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show()

    def respondFileChooser(self, dialog, response, entry):
        if response == Gtk.ResponseType.OK:
            entry.set_text(dialog.get_filename().replace("\\", "/"))
            entry.set_position(-1)  # Sets position last, makes it possible to see the vital part of long paths
        dialog.destroy()

    def getConfigOptions(self, option):
        fromConfig = guiConfig.getCompositeValue("gui_entry_options", option.name)
        if fromConfig is None:  # Happens on initial startup with no apps...
            return []
        return fromConfig

    def getCommandLineArgs(self, optionGroup, onlyKeys=[], excludeKeys=[]):
        args = []
        for key, value in optionGroup.getOptionsForCmdLine(onlyKeys, excludeKeys):
            args.append("-" + key)
            if value:
                args.append(str(value))
        return args

    def hasPerformance(self, apps, *args):
        for app in apps:
            if app.hasPerformance(*args):
                return True
        return False

    def addApplicationOptions(self, allApps, optionGroup, inputOptions={}):
        if len(allApps) > 0:
            for app in allApps:
                app.addToOptionGroups(allApps, [optionGroup])
        else:
            configObject = self.makeDefaultConfigObject(inputOptions)
            configObject.addToOptionGroups(allApps, [optionGroup])

    def makeDefaultConfigObject(self, inputOptions):
        return plugins.importAndCall("default", "getConfig", inputOptions)


class ActionTabGUI(OptionGroupGUI):
    def __init__(self, *args):
        OptionGroupGUI.__init__(self, *args)
        self.diag.info("Creating action tab for " + self.getTabTitle() +
                       ", sensitive " + repr(self.shouldShowCurrent()))
        self.vbox = Gtk.VBox()

    def shouldShowCurrent(self, *args):
        return self.gtkAction.get_property("sensitive")

    def createView(self):
        self.fillVBox(self.vbox, self.optionGroup)
        self.createButtons(self.vbox)
        self.vbox.show_all()
        self.widget = self.addScrollBars(self.vbox, hpolicy=Gtk.PolicyType.AUTOMATIC)
        self.widget.set_name(self.getTabTitle() + " Tab")
        return self.widget

    def setSensitivity(self, newValue):
        ActionGUI.setSensitivity(self, newValue)
        self.diag.info("Sensitivity of " + self.getTabTitle() + " changed to " + repr(newValue))
        if self.shouldShowCurrent():
            self.updateOptions()

    def displayInTab(self):
        return True

    def notifyReset(self, *args):
        self.optionGroup.reset()

    def fillVBox(self, vbox, optionGroup):
        options, switches = self.extractSwitches(optionGroup)
        if len(options) > 0:
            # Creating 0-row table gives a warning ...
            table = Gtk.Table(len(options), 2, homogeneous=False)
            table.set_row_spacings(1)
            rowIndex = 0
            for option in options:
                self.addValuesFromConfig(option)

                labelEventBox = self.createLabelEventBox(option, separator="  ")
                labelEventBox.get_children()[0].set_alignment(1.0, 0.5)
                table.attach(labelEventBox, 0, 1, rowIndex, rowIndex + 1, xoptions=Gtk.AttachOptions.FILL, xpadding=1)
                entryWidget, entryOrBuffer = self.createOptionWidget(option)
                self.connectEntry(option, entryOrBuffer, entryWidget)
                if isinstance(entryOrBuffer, Gtk.Entry):
                    entryOrBuffer.connect("activate", self.runInteractive)
                table.attach(entryWidget, 1, 2, rowIndex, rowIndex + 1)
                rowIndex += 1
                table.show_all()
            vbox.pack_start(table, False, False, 0)

        autoEnableInfo = self.findAutoEnableInfo(switches)
        for switch in switches:
            widget = self.createSwitchWidget(switch, optionGroup, autoEnableInfo)
            vbox.pack_start(widget, False, False, 0)

    def createResetButton(self):
        button = Gtk.Button("Reset Tab")
        button.set_name("Reset " + self.getTabTitle() + " Tab")
        button.connect("clicked", self.notifyReset)
        button.set_tooltip_text("Reset all the settings in the current tab to their default values")
        button.show()
        return button

    def createButtons(self, vbox):
        self.addCentralButton(vbox, self.createButton(), padding=8)
        self.addCentralButton(vbox, self.createResetButton(), padding=16)

    def addCentralButton(self, vbox, button, padding):
        buttonbox = Gtk.HButtonBox()
        buttonbox.pack_start(button, True, False, 0)
        vbox.pack_start(buttonbox, False, False, padding)

    def createOptionWidget(self, option):
        box, entry = OptionGroupGUI.createOptionWidget(self, option)
        if option.selectFile:
            self.createFileChooserDialog(box, entry, option)
        return (box, entry)


class ActionDialogGUI(OptionGroupGUI):
    def runInteractive(self, *args):
        if self.busy:  # If we're busy with some other action, ignore this one ...
            return

        self.updateOptions()
        try:
            self.showConfigurationDialog()
        except plugins.TextTestError as e:
            self.showErrorDialog(str(e))

    def showConfigurationDialog(self):
        dialog = self.createDialog()
        alignment = self.createAlignment()
        vbox = Gtk.VBox()
        fileChooser, fileChooserOption = self.fillVBox(vbox, self.optionGroup)
        if self.needsScrollBars():
            vbox = self.addScrollBars(vbox, Gtk.PolicyType.AUTOMATIC)
        alignment.add(vbox)
        dialog.vbox.pack_start(alignment, True, True, 0)
        self.createButtons(dialog, fileChooser, fileChooserOption)
        self.tryResize(dialog)
        dialog.show_all()
        return dialog

    def needsScrollBars(self):
        return False

    def getConfirmationDialogSettings(self):
        return Gtk.STOCK_DIALOG_WARNING, "Confirmation"

    def _respond(self, saidOK=True, dialog=None, fileChooserOption=None):
        if saidOK:
            try:
                message = self.getConfirmationMessage()
                if message:
                    stockId, level = self.getConfirmationDialogSettings()
                    self.showQueryDialog(self.getQueryParentWindow(dialog), message, stockId, level,
                                         self.confirmationRespond, fileChooserOption)
                else:
                    self.defaultRespond(saidOK, dialog, fileChooserOption)
            except plugins.TextTestError as e:
                self.showErrorDialog(str(e))
            except Exception:
                self.showErrorDialog(plugins.getExceptionString())
        else:
            self.defaultRespond(saidOK, dialog, fileChooserOption)

    def getQueryParentWindow(self, dialog):
        if dialog:
            return dialog
        else:
            return self.getParentWindow()

    def confirmationRespond(self, dialog, responseId, fileChooserOption):
        saidOK = responseId == Gtk.ResponseType.YES
        self.defaultRespond(saidOK, dialog)
        if saidOK:
            parent = dialog.get_transient_for()
            if isinstance(parent, Gtk.Dialog):
                self._cleanDialog(parent, fileChooserOption)

    def _cleanDialog(self, dialog, fileChooserOption=None):
        if fileChooserOption:
            fileChooserOption.resetDefault()  # Must do this, because we can't rely on reading from invisible FileChoosers
        OptionGroupGUI._cleanDialog(self, dialog)

    def defaultRespond(self, *args):
        OptionGroupGUI._respond(self, *args)

    def createAlignment(self):
        alignment = Gtk.Alignment.new(1.0, 1.0, 1.0, 1.0)
        alignment.set_padding(5, 5, 5, 5)
        return alignment

    def getOkStock(self, scriptName):
        if scriptName.startswith("load"):
            return "texttest-stock-load"
        elif scriptName.startswith("save"):
            return Gtk.STOCK_SAVE
        else:
            return Gtk.STOCK_OK

    def createButtons(self, dialog, fileChooser, fileChooserOption):
        dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        actionScriptName = self.getTooltip()
        dialog.add_button(self.getOkStock(actionScriptName.lower()), Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        if fileChooser:
            fileChooser.connect("file-activated", self.simulateResponse, dialog)
            # Don't pass set_filename directly, will interfere with StoryText's attempts to intercept it
            fileChooserOption.setMethods(fileChooser.get_filename, lambda f: fileChooser.set_filename(f))

        dialog.connect("response", self.respond, fileChooserOption)

    def simulateResponse(self, dummy, dialog):
        dialog.response(Gtk.ResponseType.ACCEPT)

    def getOrderedOptions(self, optionGroup):
        return list(optionGroup.options.values())

    def fillVBox(self, vbox, optionGroup, includeOverrides=True):
        fileChooser, fileChooserOption = None, None
        allOptions = self.getOrderedOptions(optionGroup)
        autoEnableInfo = self.findAutoEnableInfo(allOptions)
        for option in allOptions:
            self.addValuesFromConfig(option, includeOverrides)

            if isinstance(option, plugins.Switch):
                widget = self.createSwitchWidget(option, optionGroup, autoEnableInfo)
                vbox.pack_start(widget, False, False, 0)
            elif option.selectFile or option.selectDir or option.saveFile:
                if not self.showFileChooserAsDialog():
                    fileChooserOption = option
                    fileChooser = self.createFileChooser(option)
                    if len(allOptions) > 1 and not option.saveFile:
                        # If there is other stuff, add a frame round the file chooser so we can see what it's for
                        # Don't do this when approving as it shouldn't be necessary
                        labelEventBox = self.createLabelEventBox(option, separator=":")
                        frame = Gtk.Frame()
                        frame.set_label_widget(labelEventBox)
                        frame.add(fileChooser)
                        vbox.pack_start(frame, True, True, 0)
                    else:
                        vbox.pack_start(fileChooser, True, True, 0)
                else:
                    widget, entry = self.createOptWidget(vbox, option)
                    self.createFileChooserDialog(widget, entry, option)
            else:
                self.createOptWidget(vbox, option)

        if fileChooser:
            # File choosers seize the focus, mostly we want to get it back and put it on the first text entry
            self.set_focus(vbox)
        return fileChooser, fileChooserOption

    def set_focus(self, vbox):
        for child in vbox.get_children():
            if isinstance(child, Gtk.Container) and not isinstance(child, Gtk.FileChooser):
                for gchild in child.get_children():  # This may cause indeterministic behavior if called on FileChoosers, see TTT-2485
                    if isinstance(gchild, Gtk.Entry):
                        gchild.get_toplevel().connect("map", lambda x: gchild.grab_focus())
                        return

    def createOptWidget(self, vbox, option):
        labelEventBox = self.createLabelEventBox(option, separator=":")
        self.addLabel(vbox, labelEventBox)
        entryWidget, entryOrBuffer = self.createOptionWidget(option)
        if isinstance(entryOrBuffer, Gtk.Entry):
            entryOrBuffer.set_activates_default(True)
            vbox.pack_start(entryWidget, False, False, 0)
        else:
            vbox.pack_start(entryWidget, True, True, 0)
        self.connectEntry(option, entryOrBuffer, entryWidget)
        return entryWidget, entryOrBuffer

    def addLabel(self, vbox, label):
        hbox = Gtk.HBox()
        hbox.pack_start(label, False, False, 0)
        vbox.pack_start(hbox, False, False, 2)

    def createRadioButtonCollection(self, switch, optionGroup):
        if optionGroup is not self.optionGroup:
            # If we're not part of the main group, we've got a frame already, store horizontally in this case
            return OptionGroupGUI.createRadioButtonCollection(self, switch, optionGroup)

        if switch.name:
            frame = Gtk.Frame.new(switch.name)
        else:
            frame = Gtk.Frame()
        frameBox = Gtk.VBox()
        for button in self.createRadioButtons(switch, optionGroup):
            frameBox.pack_start(button, True, True, 0)
        frame.add(frameBox)
        return frame

    def showFileChooserAsDialog(self):
        return False

    def getFileChooserFlag(self, option):
        if option.selectFile:
            return Gtk.FileChooserAction.OPEN
        elif option.selectDir:
            return Gtk.FileChooserAction.SELECT_FOLDER
        else:
            return Gtk.FileChooserAction.SAVE

    def createFileChooser(self, option):
        fileChooser = Gtk.FileChooserWidget.new(self.getFileChooserFlag(option))
        fileChooser.set_name("File Chooser for '" + self.getTooltip() + "'")
        # The following line has no effect until this GTK bug is fixed...
        # https://bugzilla.gnome.org/show_bug.cgi?id=440667
        fileChooser.set_show_hidden(True)
        folders, defaultFolder = option.getDirectories()
        if option.selectDir and option.getValue():
            startFolder = option.getValue()
        elif defaultFolder and os.path.isdir(os.path.abspath(defaultFolder)):
            startFolder = os.path.abspath(defaultFolder)
        else:
            startFolder = os.getcwd()  # Just to make sure we always have some dir ...

        # We want a filechooser dialog to let the user choose where, and
        # with which name, to save the selection.
        fileChooser.set_current_folder(startFolder)
        for folder in folders:
            try:
                fileChooser.add_shortcut_folder(folder)
            except GObject.GError:
                pass  # Get this if the folder is already added, e.g. if it's the home directory

        if option.selectFile and self.set_filename_is_working():
            if option.getValue():
                fileChooser.set_filename(option.getValue())
            else:
                value = self.getDefaultFileChooserValue(startFolder)
                if value:
                    fileChooser.set_filename(value)

        fileChooser.set_local_only(True)
        return fileChooser

    def set_filename_is_working(self):
        # A particularly nasty bug was introduced in GTK 2.20, and fixed in GTK 2.24
        # https://bugzilla.gnome.org/show_bug.cgi?id=643170
        # It not only prevents set_filename from working but causes GTK events to be created and never executed
        # making the GUI think it is constantly busy and sending our throbber into an infinite loop
        # See bugs TTT-3469, TTT-3483
        # this block can probably removed MB 2018-12-04
        # if Gtk.gtk_version < (2, 20) or Gtk.gtk_version >= (2, 24):
        #    return True

        fileChooserConfigFile = self.getFileChooserConfigFile()
        if not self.showHiddenFilesEnabled(fileChooserConfigFile):
            return True

        sys.stderr.write("WARNING: unable to select files in File Chooser, due to a GTK+ bug.\n" +
                         "Either upgrade GTK+ to at least version 2.24, or set 'ShowHidden=false' in your configuration file at\n" +
                         fileChooserConfigFile + "\n")
        return False

    def getFileChooserConfigFile(self):
        xdgConfigHome = os.getenv("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        return os.path.join(xdgConfigHome, "gtk-2.0", "gtkfilechooser.ini")

    def showHiddenFilesEnabled(self, configFile):
        if os.path.isfile(configFile):
            with open(configFile) as f:
                for line in f:
                    if "ShowHidden" in line and "true" in line:
                        return True
        return False

    def getDefaultFileChooserValue(self, startFolder):
        appSuffices = ["." + app.name for app in self.validApps]
        for f in sorted(os.listdir(startFolder)):
            path = os.path.join(startFolder, f)
            if not self.onlyDataFilesInFileChooser() or (os.path.isfile(path) and not any((suffix in f for suffix in appSuffices))):
                return path

    def onlyDataFilesInFileChooser(self):
        return False

    def getFilterFileDirs(self, allApps, **kw):
        if len(allApps) > 0:
            return allApps[0].getFilterFileDirectories(allApps, **kw)
        else:
            return []


class CloseWindowCancelException(plugins.TextTestException):
    pass


class InteractiveActionConfig:
    def getColourDictionary(self):
        return GUIConfig.getDefaultColours()

    def getDefaultAccelerators(self):
        return {}

    def getReplacements(self):
        # Return a dictionary mapping classes above to what to replace them with
        return {}
