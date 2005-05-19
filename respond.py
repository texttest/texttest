#!/usr/local/bin/python

helpDescription = """
The interactive response presented on failure should be fairly self-explanatory. Essentially you
get the choice to view the details (with the chosen tool, as described above), save or continue.
"Continue" does nothing and leaves all files in place. Save will just overwrite the standard results
with the new ones. If you are running with a version (-v), then you also get the choice to save
the results for that version. This will create or override results files of the form <root>.<app>.<version>,
instead of files of the form <root>.<app>
"""

import comparetest, sys, string, os, plugins
from usecase import ScriptEngine
    
# Abstract base to make it easier to write test responders
class Responder(plugins.Action):
    def __init__(self, overwriteSuccess):
        self.overwriteSuccess = overwriteSuccess
        self.lineCount = None
        self.logFile = None
        self.graphicalDiffTool = None
        self.graphicalViewTool = None
        self.textDiffTool = None
    def __repr__(self):
        # Default, don't comment what we're doing with failures
        return ""
    def __call__(self, test):
        if test.state.hasFailed():
            print test.getIndent() + repr(test), test.state.getDifferenceSummary(repr(self))
            if test.state.hasResults():
                self.handleFailure(test)
        else:
            self.handleSuccess(test)
        self.handleAll(test)
    def handleAll(self, test):
        pass
    def handleFailure(self, test):
        pass
    def handleSuccess(self, test):
        if self.overwriteSuccess:
            self.save(test, test.app.getFullVersion(forSave=1))
    def save(self, test, version, exact=1):
        test.state.save(exact, version, self.overwriteSuccess)
    def setUpApplication(self, app):
        self.logFile = app.getConfigValue("log_file")
        self.graphicalDiffTool = app.getConfigValue("diff_program")
        self.graphicalViewTool = app.getConfigValue("view_program")
        
# Generic interactive responder. Can be configured via the settings in setUpApplication method
class InteractiveResponder(Responder):
    def handleFailure(self, test):
        performView = self.askUser(test, allowView=1)
        if performView:
            process = self.viewTest(test)
            self.askUser(test, allowView=0, process=process)
    def viewTest(self, test):
        outputText = test.state.freeText
        sys.stdout.write(outputText)
        logFileComparison, list = test.state.findComparison(self.logFile)
        if logFileComparison:
            tool = self.graphicalDiffTool
            cmdLine = tool + " " + logFileComparison.stdCmpFile + " " +\
                      logFileComparison.tmpCmpFile + plugins.nullRedirect()
            if logFileComparison.newResult():
                tool = self.graphicalViewTool
                cmdLine = tool + " " + logFileComparison.tmpCmpFile + plugins.nullRedirect()
            if tool:
                print "<See also " + tool + " window for details of " + self.logFile + ">"
                return plugins.BackgroundProcess(cmdLine)
    def askUser(self, test, allowView, process=None):      
        versions = test.app.getVersionFileExtensions(forSave=1)
        options = ""
        for i in range(len(versions)):
            options += "Save Version " + versions[i] + "(" + str(i + 1) + "), "
        options += "Save(s) or continue(any other key)?"
        if allowView:
            options = "View details(v), " + options
        print test.getIndent() + options
        response = ScriptEngine.instance.readStdin()
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
            process.killAll()
        return 0
    
class OverwriteOnFailures(Responder):
    def __repr__(self):
        return " overwriting"
    def handleFailure(self, test):
        self.save(test, test.app.getFullVersion(forSave=1))
