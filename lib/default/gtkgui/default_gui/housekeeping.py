
"""
Miscellaneous actions for generally housekeeping the state of the GUI
"""

from .. import guiplugins, guiutils
from ordereddict import OrderedDict
from default.batch import BatchApplicationData, MailSender
import os, plugins, gtk

class Quit(guiplugins.BasicActionGUI):
    def __init__(self, allApps, dynamic, inputOptions):
        guiplugins.BasicActionGUI.__init__(self, allApps, dynamic, inputOptions)
        self.runName = inputOptions.get("name", "") if dynamic else None
        
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
        if self.runName is not None:
            self.runName = runName
    
    def messageAfterPerform(self):
        pass # GUI isn't there to show it
    
    def getConfirmationMessage(self):
        message = ""
        if self.runName and not self.runName.startswith("Tests started from"):
            message = "You named this run as follows : \n" + self.runName + "\n"
        runningProcesses = guiplugins.processMonitor.listRunningProcesses()
        if len(runningProcesses) > 0:
            message += "\nThese processes are still running, and will be terminated when quitting: \n\n   + " + \
                       "\n   + ".join(runningProcesses) + "\n"
        if message:
            message += "\nQuit anyway?\n"
        return message

    def notifyWindowClosed(self, *args):
        confirmationMessage = self.getConfirmationMessage()
        if confirmationMessage:
            dialog = self.showQueryDialog(self.getParentWindow(), confirmationMessage,
                                          gtk.STOCK_DIALOG_WARNING, "Confirmation", None)
            responseId = dialog.run()
            saidCancel = responseId not in [ gtk.RESPONSE_ACCEPT, gtk.RESPONSE_YES, gtk.RESPONSE_OK ]
            dialog.hide()
            dialog.destroy()
            if saidCancel:
                self.cancel()
                raise guiplugins.CloseWindowCancelException("Closing window")
        self.notify("Quit")


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
            suite.refreshFilesRecursively()
    
class ViewScreenshots(guiplugins.ActionGUI):
    def _getTitle(self):
        return "View screenshots"
    
    def isActiveOnCurrent(self, *args):
        if len(self.currTestSelection) != 1:
            return False
        
        screenshotDir = self.getScreenshotDir()
        return os.path.isdir(screenshotDir)
    
    def getScreenshotDir(self):
        return os.path.join(self.currTestSelection[0].getDirectory(temporary=True), "screenshots")
    
    def performOnCurrent(self):
        screenshotDir = self.getScreenshotDir()
        allFiles = os.listdir(screenshotDir)
        allFiles.sort(key=self.getSortKey)
        allPaths = [ os.path.join(screenshotDir, f) for f in allFiles ]
        guiplugins.openLinkInBrowser(*allPaths)
            
    def getSortKey(self, fileName):
        number = fileName[10:-4]
        return int(number) if number.isdigit() else 0
            
class GenerateTestSummary(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("generate", "",possibleDirs=[os.getenv("TEXTTEST_TMP", "")], saveFile=True)
        self.batchAppData = OrderedDict()
        self.allApps = OrderedDict()

    def performOnCurrent(self):
        fileName = self.getFileName()
        for test in self.currTestSelection:
            if test.state.isComplete():
                if not self.batchAppData.has_key(test.app):
                    self.addApplication(test)
                self.batchAppData[test.app].storeCategory(test)
        self.writeTextSummary(fileName)
        
    def writeTextSummary(self, fileName):
        mailSender = MailSender()
        with open(fileName, "w") as f:
            for appList in self.allApps.values():
                batchDataList = map(self.batchAppData.get, appList)
                f.write(mailSender.makeContents(batchDataList, False))

    def getFileName(self):
        fileName = self.optionGroup.getOptionValue("generate")
        if not fileName:
            raise plugins.TextTestError, "Cannot save selection - no file name specified"
        elif os.path.isdir(fileName):
            raise plugins.TextTestError, "Cannot save selection - existing directory specified"
        else:
            return fileName


    def _getTitle(self):
        return "Generate test summary"

    def getRootSuite(self, test):
        if test.parent:
            return self.getRootSuite(test.parent)
        else:
            return test
       
    def addApplication(self, test):
        rootSuite = self.getRootSuite(test)
        app = test.app
        self.batchAppData[app] = BatchApplicationData(rootSuite)
        self.allApps.setdefault(app.name, []).append(app)

def getInteractiveActionClasses(dynamic):
    classes = [ Quit, SetRunName ]
    if dynamic:
        classes.append(ViewScreenshots)
        classes.append(GenerateTestSummary)
    else:
        classes += [ RefreshAll, ResetGroups ]
    return classes
