#!/usr/local/bin/python

helpDescription = """
The interactive response presented on failure should be fairly self-explanatory. Essentially you
get the choice to view the details (with the chosen tool, as described above), save or continue.
"Continue" does nothing and leaves all files in place. Save will just overwrite the standard results
with the new ones. If you are running with a version (-v), then you also get the choice to save
the results for that version. This will create or override results files of the form <root>.<app>.<version>,
instead of files of the form <root>.<app>
"""

import comparetest, ndiff, sys, string, os, plugins
from usecase import ScriptEngine
    
# Abstract base to make it easier to write test responders
class Responder(plugins.Action):
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
        pass
    def handleUnrunnable(self, test):
        pass
    def handleKilled(self, test):
        pass
    def responderText(self, test):
        testComparison = test.stateDetails
        diffText = testComparison.getDifferenceSummary()
        return repr(testComparison) + diffText
    def __repr__(self):
        return "Responding to"

# Uses the python ndiff library, which should work anywhere. Override display method to use other things
class InteractiveResponder(Responder):
    def handleFailure(self, test, testComparison):
        if testComparison.failedPrediction:
            print testComparison.failedPrediction
        performView = self.askUser(test, testComparison, 1)
        if performView:
            self.displayComparisons(testComparison.getComparisons(), sys.stdout, test.app)
            self.askUser(test, testComparison, 0)
    def displayComparisons(self, comparisons, displayStream, app):
        for comparison in comparisons:
            if comparison.newResult():
                titleText = "New result in"
            else:
                titleText = "Differences in"
            titleText += " " + repr(comparison)
            displayStream.write("------------------ " + titleText + " --------------------\n")
            self.display(comparison, displayStream, app)
    def display(self, comparison, displayStream, app):
        ndiff.fcompare(comparison.stdCmpFile, comparison.tmpCmpFile)
    def getInstructions(self, test):
        return []
    def askUser(self, test, testComparison, allowView):      
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
            testComparison.save(exactSave)
        elif allowView and response.startswith('v'):
            return 1
        else:
            for i in range(len(versions)):
                versionOption = str(i + 1)
                if response.startswith(versionOption):
                    testComparison.save(exactSave, versions[i])
        return 0
            
# Uses UNIX tkdiff
class UNIXInteractiveResponder(InteractiveResponder):
    def __init__(self, lineCount):
        self.lineCount = lineCount
    def display(self, comparison, displayStream, app):
        if comparison.newResult():
            argumentString = " /dev/null " + comparison.tmpFile
        else:
            argumentString = " " + comparison.stdCmpFile + " " + comparison.tmpCmpFile
        if os.environ.has_key("DISPLAY") and displayStream == sys.stdout and repr(comparison) == app.getConfigValue("log_file"):
            print "<See tkdiff window>"
            os.system("tkdiff" + argumentString + " &")
        else:
            stdin, stdout, stderr = os.popen3("diff" + argumentString)
            try:
                linesWritten = 0
                for line in stdout.xreadlines():
                    if linesWritten >= self.lineCount:
                        return
                    displayStream.write(line)
                    linesWritten += 1
            finally:
                # Don't wait for the garbage collector - we risk a lot of failures otherwise...
                stdin.close()
                stdout.close()
                stderr.close()
    
class OverwriteOnFailures(Responder):
    def responderText(self, test):
        testComparison = test.stateDetails
        diffText = testComparison.getDifferenceSummary()
        return "- overwriting" + diffText
    def handleFailure(self, test, testComparison):
        testComparison.save(1, test.app.getFullVersion())
