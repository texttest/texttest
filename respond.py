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
    def handleSuccess(self, test):
        if self.overwriteSuccess:
            self.save(test, test.app.getFullVersion(forSave=1))
    def save(self, test, version, exact=1):
        test.state.save(exact, version, self.overwriteSuccess)
    def setUpApplication(self, app):
        self.lineCount = app.getConfigValue("lines_of_text_difference")
        self.logFile = app.getConfigValue("log_file")
        self.graphicalDiffTool = app.getConfigValue("diff_program")
        self.textDiffTool = app.getConfigValue("text_diff_program")
    def testComparisonOutput(self, test):
        fullText = ""
        for comparison in test.state.getComparisons():
            fullText += self.fileComparisonTitle(comparison) + os.linesep
            fullText += self.fileComparisonBody(comparison)
        return fullText
    def fileComparisonTitle(self, comparison):
        if comparison.newResult():
            titleText = "New result in"
        else:
            titleText = "Differences in"
        titleText += " " + repr(comparison)
        return "------------------ " + titleText + " --------------------"
    def useGraphicalComparison(self, comparison):
        if not self.graphicalDiffTool or plugins.BackgroundProcess.fakeProcesses:
            return 0
        return repr(comparison) == self.logFile
    def fileComparisonBody(self, comparison):
        if comparison.newResult():
            return self.getPreview(open(comparison.tmpFile))
        
        argumentString = " " + comparison.stdCmpFile + " " + comparison.tmpCmpFile
        if self.useGraphicalComparison(comparison):
            process = plugins.BackgroundProcess(self.graphicalDiffTool + argumentString)
            return "<See " + self.graphicalDiffTool + " window>" + os.linesep
        else:
            stdout = os.popen(self.textDiffTool + argumentString)
            return self.getPreview(stdout)
    def getPreview(self, file):
        linesWritten = 0
        fullText = ""
        for line in file.xreadlines():
            if linesWritten < self.lineCount:
                fullText += line
                linesWritten += 1
        file.close()
        return fullText

# Generic interactive responder. Can be configured via the settings in setUpApplication method
class InteractiveResponder(Responder):
    def handleFailure(self, test):
        performView = self.askUser(test, allowView=1)
        if performView:
            outputText = self.testComparisonOutput(test)
            sys.stdout.write(outputText)
            self.askUser(test, allowView=0)
    def askUser(self, test, allowView):      
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
        return 0
    
class OverwriteOnFailures(Responder):
    def __repr__(self):
        return " overwriting"
    def handleFailure(self, test):
        self.save(test, test.app.getFullVersion(forSave=1))
