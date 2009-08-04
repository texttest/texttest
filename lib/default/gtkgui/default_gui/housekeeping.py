
"""
Miscellaneous actions for generally housekeeping the state of the GUI
"""

from default.gtkgui import guiplugins # from .. import guiplugins when we drop Python 2.4 support

class Quit(guiplugins.BasicActionGUI):
    def __init__(self, *args):
        guiplugins.BasicActionGUI.__init__(self, *args)
        self.annotation = ""
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
    def notifyAnnotate(self, annotation):
        self.annotation = annotation
    def messageAfterPerform(self):
        pass # GUI isn't there to show it
    def getConfirmationMessage(self):
        message = ""
        if self.annotation:
            message = "You annotated this GUI, using the following message : \n" + self.annotation + "\n"
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


class AnnotateGUI(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("desc", "\nDescription of this run")
    def isActiveOnCurrent(self, *args):
        return True
    def _getStockId(self):
        return "index"
    def _getTitle(self):
        return "Annotate"
    def messageAfterPerform(self):
        pass
    def getDialogTitle(self):
        return "Annotate this run"
    def getTooltip(self):
        return "Provide an annotation for this run and warn before closing it"
    def getSignalsSent(self):
        return [ "Annotate" ]
    def performOnCurrent(self):
        description = self.optionGroup.getOptionValue("desc")
        self.notify("Annotate", description)
        self.notify("Status", "Annotated GUI as '" + description + "'")


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
    def performOnCurrent(self):
        for suite in self.rootTestSuites:
            self.notify("ActionProgress", "")
            suite.app.setUpConfiguration()
            self.notify("ActionProgress", "")
            filters = suite.app.getFilterList(self.rootTestSuites)
            suite.refresh(filters)


def getInteractiveActionClasses(dynamic):
    classes = [ Quit ]
    if dynamic:
        classes.append(AnnotateGUI)
    else:
        classes += [ RefreshAll, ResetGroups ]
    return classes
