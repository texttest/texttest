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
    
# Abstract base to make it easier to write test responders
class Responder(plugins.Action):
    def __call__(self, test):
        if os.path.isfile("core.Z"):
            os.system("uncompress core.Z")
        if os.path.isfile("core"):
            self.handleCoreFile(test)
            os.remove("core")
        if comparetest.testComparisonMap.has_key(test):
            testComparison = comparetest.testComparisonMap[test]
            print test.getIndent() + repr(test), self.responderText(test)
            self.handleFailure(test, testComparison)
            del comparetest.testComparisonMap[test]
        else:
            self.handleSuccess(test)
    def handleSuccess(self, test):
        pass
    def comparisonsString(self, comparisons):
        return string.join([repr(x) for x in comparisons], ",")
    def responderText(self, test):
        testComparison = comparetest.testComparisonMap[test]
        diffText = " differences in " + self.comparisonsString(testComparison.comparisons)
        return repr(testComparison) + diffText

# Uses the python ndiff library, which should work anywhere. Override display method to use other things
class InteractiveResponder(Responder):
    def handleFailure(self, test, testComparison):
        performView = self.askUser(test, testComparison.comparisons, 1)
        if performView:
            self.displayComparisons(testComparison.comparisons, sys.stdout, test.app)
            self.askUser(test, testComparison.comparisons, 0)
    def displayComparisons(self, comparisons, displayStream, app):
        for comparison in comparisons:
            displayStream.write("------------------ Differences in " + repr(comparison) + " --------------------\n")
            self.display(comparison, displayStream, app)
    def display(self, comparison, displayStream, app):
        ndiff.fcompare(comparison.stdCmpFile, comparison.tmpCmpFile)
    def askUser(self, test, comparisons, allowView):      
        options = "Save(s) or continue(any other key)?"
        if len(test.app.version) > 0:
            options = "Save Version " + test.app.version + "(z), " + options
        if allowView:
            options = "View details(v), " + options
        print test.getIndent() + options
        response = sys.stdin.readline()
        if 's' in response:
            for comparison in comparisons:
                comparison.overwrite()
        elif allowView and 'v' in response:
            return 1
        elif 'z' in response:
            for comparison in comparisons:
                comparison.overwrite(test.app.version)
        return 0
            
# Uses UNIX tkdiff
class UNIXInteractiveResponder(InteractiveResponder):
    def __init__(self, lineCount):
        self.lineCount = lineCount
    def handleCoreFile(self, test):
        print self.getCrashText(test)
    def getCrashText(self, test):
        fileName = "coreCommands.gdb"
        file = open(fileName, "w")
        file.write("bt\nq\n")
        file.close()
        # Yes, we know this is horrible. Does anyone know a better way of getting the binary out of a core file???
        # Unfortunately running gdb is not the answer, because it truncates the data...
        binary = os.popen("csh -c 'echo `tail -c 1024 core`'").read().split(" ")[-1].strip()        
        gdbData = os.popen("gdb -q -x " + fileName + " " + binary + " core")
        crashText = ""
        for line in gdbData.xreadlines():
            if line.find("Program terminated") != -1:
                crashText += test.getIndent() + repr(test) + " CRASHED (" + line.strip() + ") : stack trace from gdb follows" + os.linesep
            if line[0] == "#":
                crashText += line
        os.remove(fileName)
        return crashText
    def display(self, comparison, displayStream, app):
        argumentString = " " + comparison.stdCmpFile + " " + comparison.tmpCmpFile
        if displayStream == sys.stdout and repr(comparison) == app.getConfigValue("log_file"):
            print "<See tkdiff window>"
            os.system("tkdiff" + argumentString + " &")
        else:
            stdin, stdout, stderr = os.popen3("diff" + argumentString)
            linesWritten = 0
            for line in stdout.xreadlines():
                if linesWritten >= self.lineCount:
                    return
                displayStream.write(line)
                linesWritten += 1
    
class OverwriteOnFailures(Responder):
    def __init__(self, version):
        self.version = version
    def responderText(self, test):
        testComparison = comparetest.testComparisonMap[test]
        diffText = " differences in " + self.comparisonsString(testComparison.comparisons)
        return "- overwriting" + diffText
    def handleFailure(self, test, testComparison):
        for comparison in testComparison.comparisons:
            comparison.overwrite(self.version)
