
"""
Miscellaneous actions for generally housekeeping the state of the GUI
"""

from .. import guiplugins

class Quit(guiplugins.BasicActionGUI):
    def __init__(self, allApps, dynamic, inputOptions):
        guiplugins.BasicActionGUI.__init__(self, allApps, dynamic, inputOptions)
        self.runName = inputOptions.get("name", "")
    def _getStockId(self):
        return "quit"
    def _getTitle(self):
        return "_Quit"
    def isActiveOnCurrent(self, *args):
        return True
    def getSignalsSent(self):
        return [ "Quit" ]
    def performOnCurrent(self):
        self.notify("Quit")
    def notifySetRunName(self, runName):
        self.runName = runName
    def messageAfterPerform(self):
        pass # GUI isn't there to show it
    def getConfirmationMessage(self):
        message = ""
        if self.runName:
            message = "You named this run as follows : \n" + self.runName + "\n"
        runningProcesses = guiplugins.processMonitor.listRunningProcesses()
        if len(runningProcesses) > 0:
            message += "\nThese processes are still running, and will be terminated when quitting: \n\n   + " + \
                       "\n   + ".join(runningProcesses) + "\n"
        if message:
            message += "\nQuit anyway?\n"
        return message


class ResetGroups(guiplugins.BasicActionGUI):
    def isActiveOnCurrent(self, *args):
        return True
    def _getStockId(self):
        return "revert-to-saved"
    def _getTitle(self):
        return "R_eset"
    def messageAfterPerform(self):
        return "All options reset to default values."
    def getTooltip(self):
        return "Reset running options"
    def getSignalsSent(self):
        return [ "Reset" ]
    def performOnCurrent(self):
        self.notify("Reset")


class SetRunName(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("name", "\nNew name for this run")
    def isActiveOnCurrent(self, *args):
        return True
    def _getStockId(self):
        return "index"
    def _getTitle(self):
        return "Set Run Name"
    def messageAfterPerform(self):
        pass
    def getDialogTitle(self):
        return "Set a new name for this run"
    def getTooltip(self):
        return "Provide a name for this run and warn before closing it"
    def getSignalsSent(self):
        return [ "SetRunName" ]
    def performOnCurrent(self):
        name = self.optionGroup.getOptionValue("name")
        self.notify("SetRunName", name)
        self.notify("Status", "Set name of run to '" + name + "'")


class RefreshAll(guiplugins.BasicActionGUI):
    def __init__(self, *args):
        guiplugins.BasicActionGUI.__init__(self, *args)
        self.rootTestSuites = []
    def _getTitle(self):
        return "Refresh"
    def _getStockId(self):
        return "refresh"
    def getTooltip(self):
        return "Refresh the whole test suite so that it reflects file changes"
    def messageBeforePerform(self):
        return "Refreshing the whole test suite..."
    def messageAfterPerform(self):
        return "Refreshed the test suite from the files"
    def addSuites(self, suites):
        self.rootTestSuites += suites
    def notifyRefresh(self):
        # when done indirectly
        self.performOnCurrent()
    def performOnCurrent(self):
        for suite in self.rootTestSuites:
            self.notify("ActionProgress")
            suite.app.setUpConfiguration()
            self.notify("ActionProgress")
            filters = suite.app.getFilterList(self.rootTestSuites)
            suite.refresh(filters)


def getInteractiveActionClasses(dynamic):
    classes = [ Quit ]
    if dynamic:
        classes.append(SetRunName)
    else:
        classes += [ RefreshAll, ResetGroups ]
    return classes
