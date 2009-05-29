
import sys, os, plugins, subprocess
from jobprocess import killSubProcessAndChildren
from time import sleep


class TextDisplayResponder(plugins.Responder):
    def notifyComplete(self, test):
        if test.state.hasFailed():
            self.describe(test)
    def describe(self, test):
        plugins.log.info(test.getIndent() + repr(test) + " " + test.state.description())
            
            
class InteractiveResponder(plugins.Responder):
    def __init__(self, optionMap, *args):
        self.overwriteSuccess = optionMap.has_key("n")
        self.overwriteFailure = optionMap.has_key("o")
        self.overwriteVersion = optionMap.get("o")
    def notifyComplete(self, test):
        if self.shouldSave(test):
            self.save(test, self.getOverwriteVersion(test))
        elif self.useInteractiveResponse(test):
            self.presentInteractiveDialog(test)
    def getOverwriteVersion(self, test):
        if self.overwriteVersion is None:
            return test.app.getFullVersion(forSave=1)
        else:
            return self.overwriteVersion
    def shouldSave(self, test):
        if not test.state.hasResults():
            return 0
        if self.overwriteSuccess and test.state.hasSucceeded():
            return 1
        return self.overwriteFailure and test.state.hasFailed()
    def save(self, test, version, exact=1):
        saveDesc = " "
        if version:
            saveDesc += "version " + version + " "
        if exact:
            saveDesc += "(exact) "
        if self.overwriteSuccess:
            saveDesc += "(overwriting succeeded files also)"
        self.describeSave(test, saveDesc)
        test.state.save(test, exact, version, self.overwriteSuccess)
        newState = test.state.makeNewState(test.app, "saved")
        test.changeState(newState)
    def describeSave(self, test, saveDesc):
        plugins.log.info(test.getIndent() + "Saving " + repr(test) + saveDesc)
    def describeViewOptions(self, test, options):
        plugins.log.info(test.getIndent() + options)
    def useInteractiveResponse(self, test):
        return test.state.hasFailed() and test.state.hasResults() and not self.overwriteFailure
    def presentInteractiveDialog(self, test):            
        performView = self.askUser(test, allowView=1)
        if performView:
            process = self.viewTest(test)
            self.askUser(test, allowView=0, process=process)
    def getViewCmdInfo(self, test, comparison):
        if comparison.missingResult():
            # Don't fire up GUI tools for missing results...
            return None, None
        if comparison.newResult():
            tool = test.getCompositeConfigValue("view_program", comparison.stem)
            cmdArgs = [ tool, comparison.tmpCmpFile ]
        else:
            tool = test.getCompositeConfigValue("diff_program", comparison.stem)
            cmdArgs = [ tool, comparison.stdCmpFile, comparison.tmpCmpFile ]
        return tool, cmdArgs        

    def viewTest(self, test):
        outputText = test.state.freeText
        sys.stdout.write(outputText)
        if not outputText.endswith("\n"):
            sys.stdout.write("\n")
        logFile = test.getConfigValue("log_file")
        logFileComparison, list = test.state.findComparison(logFile)
        if logFileComparison:
            tool, cmdArgs = self.getViewCmdInfo(test, logFileComparison)
            if tool:
                try:
                    proc = subprocess.Popen(cmdArgs, stdout=open(os.devnull, "w"),
                                            stderr=subprocess.STDOUT, startupinfo=plugins.getProcessStartUpInfo())
                    plugins.log.info("<See also " + tool + " window for details of " + logFile + ">")
                    return proc
                except OSError:
                    plugins.log.info("<No window created - could not find graphical difference tool '" + tool + "'>")

    def askUser(self, test, allowView, process=None):      
        versions = test.app.getSaveableVersions()
        options = ""
        for i in range(len(versions)):
            options += "Save Version " + versions[i] + "(" + str(i + 1) + "), "
        options += "Save(s) or continue(any other key)?"
        if allowView:
            options = "View details(v), " + options
        self.describeViewOptions(test, options)
        response = sys.stdin.readline()
        exactSave = response.find('+') != -1
        if response.startswith('s'):
            self.save(test, version="", exact=exactSave)
        elif allowView and response.startswith('v'):
            return 1
        else:
            for i in range(len(versions)):
                versionOption = str(i + 1)
                if response.startswith(versionOption):
                    self.save(test, versions[i], exactSave)
        if process:
            sleep(int(os.getenv("TEXTTEST_KILL_GRAPHICAL_CONSOLE_SLEEP", "0")))
            plugins.log.info("Terminating graphical viewer...")
            killSubProcessAndChildren(process)
        return 0
