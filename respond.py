#!/usr/local/bin/python

helpDescription = """
The interactive response presented on failure should be fairly self-explanatory. Essentially you
get the choice to view the details (with the chosen tool, as described above), save or continue.
"Continue" does nothing and leaves all files in place. Save will just overwrite the standard results
with the new ones. If you are running with a version (-v), then you also get the choice to save
the results for that version. This will create or override results files of the form <root>.<app>.<version>,
instead of files of the form <root>.<app>
"""

import comparetest, ndiff, sys, string, os, plugins, predict
    
# Abstract base to make it easier to write test responders
class Responder(plugins.Action):
    def __call__(self, test):
        self.findAndHandleCoreFiles(test)
        if predict.testBrokenPredictionMap.has_key(test):
            predictionText = predict.testBrokenPredictionMap[test]
            print test.getIndent() + "WARNING :", predictionText, "in", repr(test)
            self.handleFailedPrediction(test, predictionText)
        if test.state == test.FAILED:
            testComparison = test.stateDetails
            print test.getIndent() + repr(test), self.responderText(test)
            self.handleFailure(test, testComparison)
        else:
            self.handleSuccess(test)
    def handleSuccess(self, test):
        pass
    def handleFailedPrediction(self, test, desc):
        pass
    def findAndHandleCoreFiles(self, test):
        for filename in os.listdir(test.abspath):
            if not filename.startswith("core"):
                continue
            if filename == "core.Z":
                os.system("uncompress core.Z")
            elif filename != "core":
                os.rename(filename, "core")
        if os.path.isfile("core"):
             self.handleCoreFile(test)
             os.remove("core")
    def responderText(self, test):
        testComparison = test.stateDetails
        diffText = testComparison.getDifferenceSummary()
        return repr(testComparison) + diffText
    def processUnRunnable(self, test):
        print test.getIndent() + repr(test), "Failed: ", str(test.stateDetails).split(os.linesep)[0]
        self.handleDead(test)
    def handleDead(self, test):
        pass
    def __repr__(self):
        return "Responding to"

# Uses the python ndiff library, which should work anywhere. Override display method to use other things
class InteractiveResponder(Responder):
    def handleFailure(self, test, testComparison):
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
        versions = test.app.getVersionFileExtensions()
        options = ""
        for i in range(len(versions)):
            options += "Save Version " + versions[i] + "(" + str(i + 1) + "), "
        options += "Save(s) or continue(any other key)?"
        if allowView:
            options = "View details(v), " + options
        print test.getIndent() + options
        response = sys.stdin.readline().strip()
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
    def setUpApplication(self, app):
        app.setConfigDefault("log_file", "output")
            
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
        if comparison.newResult():
            argumentString = " /dev/null " + comparison.tmpFile
        else:
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
        testComparison = test.stateDetails
        diffText = testComparison.getDifferenceSummary()
        return "- overwriting" + diffText
    def handleFailure(self, test, testComparison):
        testComparison.save(1, self.version)
