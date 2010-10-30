
import sys, os, plugins, subprocess, colorer
from jobprocess import killSubProcessAndChildren
from time import sleep


class TextDisplayResponder(plugins.Responder):
    def __init__(self, optionMap, *args):
        plugins.Responder.__init__(self)
        self.enableColor = optionMap.has_key("zen")
        
    def notifyComplete(self, test):
        if test.state.hasFailed():
            if self.enableColor:
                self.printTestWithColorEnabled(test, colorer.RED)
            else:
                self.describe(test)  
     
    def printTestWithColorEnabled(self, test, color):
        colorer.enableOutputColor(color)
        self.describe(test)
        colorer.disableOutputColor()

    def getPrefix(self, test):
        return test.getIndent()
    
    def describe(self, test):
        plugins.log.info(self.getPrefix(test) + repr(test) + " " + test.state.description())
            
            
class InteractiveResponder(plugins.Responder):
    def __init__(self, optionMap, *args):
        plugins.Responder.__init__(self)
        self.overwriteSuccess = optionMap.has_key("n")
        self.overwriteFailure = optionMap.has_key("o")
        self.overwriteVersion = optionMap.get("o")

    def notifyComplete(self, test):
        if test.state.hasResults():
            overwriteFail = self.overwriteFailure and test.state.hasFailed()
            if overwriteFail:
                self.writeTextDiffs(test)

            if overwriteFail or (self.overwriteSuccess and test.state.hasSucceeded()):
                self.save(test, self.getOverwriteVersion(test))
            elif self.useInteractiveResponse(test):
                self.presentInteractiveDialog(test)

    def getOverwriteVersion(self, test):
        if self.overwriteVersion is None:
            return test.app.getFullVersion(forSave=1)
        else:
            return self.overwriteVersion

    def save(self, test, version, exact=1):
        saveDesc = " "
        if version:
            saveDesc += "version " + version + " "
        if exact:
            saveDesc += "(exact) "
        if self.overwriteSuccess:
            saveDesc += "(overwriting succeeded files also)"
        plugins.log.info(self.getPrefix(test) + "Saving " + repr(test) + saveDesc)
        test.state.save(test, exact, version, self.overwriteSuccess)
        newState = test.state.makeNewState(test, "saved")
        test.changeState(newState)

    def useInteractiveResponse(self, test):
        return test.state.hasFailed() and not self.overwriteFailure

    def presentInteractiveDialog(self, test):            
        performView = self.askUser(test, allowView=1)
        if performView:
            self.writeTextDiffs(test)
            process = self.viewLogFileGraphically(test)
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

    def writeTextDiffs(self, test):
        outputText = test.state.freeText
        sys.stdout.write(outputText)
        if not outputText.endswith("\n"):
            sys.stdout.write("\n")

    def viewLogFileGraphically(self, test):
        logFile = test.getConfigValue("log_file")
        logFileComparison = test.state.findComparison(logFile)[0]
        if logFileComparison:
            tool, cmdArgs = self.getViewCmdInfo(test, logFileComparison)
            if tool:
                try:
                    proc = subprocess.Popen(cmdArgs, stdout=open(os.devnull, "w"), stderr=subprocess.STDOUT)
                    plugins.log.info("<See also " + tool + " window for details of " + logFile + ">")
                    return proc
                except OSError:
                    plugins.log.info("<No window created - could not find graphical difference tool '" + tool + "'>")

    def getPrefix(self, test):
        return test.getIndent() # Mostly so we can override for queuesystem module

    def askUser(self, test, allowView, process=None):      
        versions = test.app.getSaveableVersions()
        options = ""
        for i in range(len(versions)):
            options += "Save Version " + versions[i] + "(" + str(i + 1) + "), "
        options += "Save(s) or continue(any other key)?"
        if allowView:
            options = "View details(v), " + options
        plugins.log.info(self.getPrefix(test) + options)
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
