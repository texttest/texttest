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
    def __call__(self, test):
        if test.state == test.FAILED:
            testComparison = test.stateDetails
            print test.getIndent() + repr(test), self.responderText(test)
            self.handleFailure(test, testComparison)
        elif test.state == test.SUCCEEDED:
            self.handleSuccess(test)
        elif test.state == test.KILLED:
            self.handleKilled(test)
        elif test.state == test.UNRUNNABLE:
            print test.getIndent() + repr(test), "Failed: ", str(test.stateDetails).split(os.linesep)[0]
            self.handleUnrunnable(test)
    def handleSuccess(self, test):
        if self.overwriteSuccess:
            self.save(test, test.app.getFullVersion(forSave=1))
    def save(self, test, version, exact=1):
        test.stateDetails.save(exact, version, self.overwriteSuccess)
    def handleUnrunnable(self, test):
        pass
    def handleKilled(self, test):
        pass
    def setUpApplication(self, app):
        self.lineCount = app.getConfigValue("lines_of_text_difference")
        self.logFile = app.getConfigValue("log_file")
        self.graphicalDiffTool = app.getConfigValue("diff_program")
        self.textDiffTool = app.getConfigValue("text_diff_program")
    def displayComparisons(self, comparisons, displayStream, app):
        for comparison in comparisons:
            if comparison.newResult():
                titleText = "New result in"
            else:
                titleText = "Differences in"
            titleText += " " + repr(comparison)
            displayStream.write("------------------ " + titleText + " --------------------\n")
            self.display(comparison, displayStream, app)
    def useGraphicalComparison(self, comparison, displayStream, app):
        if not self.graphicalDiffTool or not os.environ.has_key("DISPLAY") or plugins.BackgroundProcess.fakeProcesses:
            return 0
        return displayStream == sys.stdout and repr(comparison) == self.logFile
    def display(self, comparison, displayStream, app):
        if comparison.newResult():
            return self.writePreview(displayStream, open(comparison.tmpFile))
        
        argumentString = " " + comparison.stdCmpFile + " " + comparison.tmpCmpFile
        if self.useGraphicalComparison(comparison, displayStream, app):
            print "<See " + self.graphicalDiffTool + " window>"
            process = plugins.BackgroundProcess(self.graphicalDiffTool + argumentString)
        else:
            stdin, stdout, stderr = os.popen3(self.textDiffTool + argumentString)
            try:
                self.writePreview(displayStream, stdout)
            finally:
                # Don't wait for the garbage collector - we risk a lot of failures otherwise...
                stdin.close()
                stdout.close()
                stderr.close()
    def writePreview(self, displayStream, file):
        linesWritten = 0
        for line in file.xreadlines():
            if linesWritten >= self.lineCount:
                return
            displayStream.write(line)
            linesWritten += 1
    def responderText(self, test):
        testComparison = test.stateDetails
        diffText = testComparison.getDifferenceSummary()
        return repr(testComparison) + diffText
    def __repr__(self):
        return "Responding to"

# Generic interactive responder. Can be configured via the settings in setUpApplication method
class InteractiveResponder(Responder):
    def handleFailure(self, test, testComparison):
        if testComparison.failedPrediction:
            print testComparison.failedPrediction
        performView = self.askUser(test, allowView=1)
        if performView:
            self.displayComparisons(testComparison.getComparisons(), sys.stdout, test.app)
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
    def responderText(self, test):
        testComparison = test.stateDetails
        diffText = testComparison.getDifferenceSummary()
        return "- overwriting" + diffText
    def handleFailure(self, test, testComparison):
        self.save(test, test.app.getFullVersion(forSave=1))
