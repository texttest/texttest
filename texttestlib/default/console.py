
import sys
import os
import subprocess
from texttestlib.default import colorer
from texttestlib import plugins
from texttestlib.jobprocess import killProcessAndChildren
from time import sleep
from collections import OrderedDict


class TextDisplayResponder(plugins.Responder):
    def __init__(self, optionMap, *args):
        plugins.Responder.__init__(self)
        self.enableColor = "zen" in optionMap
        self.enableSummary = "b" in optionMap and "s" not in optionMap and "coll" not in optionMap
        self.failedTests = []
        self.resultSummary = OrderedDict()
        self.resultSummary["Tests Run"] = 0

    def getSummaryKey(self, category):
        if category == "success":
            return ""
        elif category == "bug":
            return "Known Bugs"
        elif category.startswith("faster") or category.startswith("slower") or category == "smaller" or category == "larger":
            return "Performance Differences"
        elif category in ["killed", "unrunnable", "cancelled", "abandoned"]:
            return "Incomplete"
        else:
            return "Failures"

    def shouldDescribe(self, test):
        return test.state.hasFailed()

    def writeDescription(self, test, summary):
        if self.enableColor and test.state.hasFailed():
            self.printTestWithColorEnabled(test, colorer.RED, summary)
        else:
            self.describe(test, summary)

    def notifyComplete(self, test):
        if self.enableSummary:
            self.resultSummary["Tests Run"] += 1
            summaryKey = self.getSummaryKey(test.state.category)
            if summaryKey:
                self.failedTests.append(test)
                if summaryKey not in self.resultSummary:
                    self.resultSummary[summaryKey] = 0
                self.resultSummary[summaryKey] += 1

        if self.shouldDescribe(test):
            self.writeDescription(test, summary=False)

    def notifyAllComplete(self):
        if self.enableSummary:
            plugins.log.info("Results:")
            plugins.log.info("")
            if len(self.failedTests):
                plugins.log.info("Tests that did not succeed:")
                for test in self.failedTests:
                    self.writeDescription(test, summary=True)
                plugins.log.info("")
            parts = [summaryKey + ": " + str(count) for summaryKey, count in list(self.resultSummary.items())]
            plugins.log.info(", ".join(parts))

    def printTestWithColorEnabled(self, test, color, summary):
        colorer.enableOutputColor(color)
        self.describe(test, summary)
        colorer.disableOutputColor()

    def getPrefix(self, test):
        return test.getIndent()

    def getTestRepr(self, test):
        return repr(test)

    def describe(self, test, summary):
        prefix = "  " if summary else self.getPrefix(test)
        state_desc = test.state.description()
        if summary and "\n" in state_desc:
            state_desc = " ".join(state_desc.splitlines()[:2])
        plugins.log.info(prefix + self.getTestRepr(test) + " " + state_desc)


class InteractiveResponder(plugins.Responder):
    def __init__(self, optionMap, *args):
        plugins.Responder.__init__(self)
        self.overwriteSuccess = "n" in optionMap
        self.overwriteFailure = "o" in optionMap
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
        plugins.log.info(self.getPrefix(test) + "Approving " + repr(test) + saveDesc)
        test.state.save(test, exact, version, self.overwriteSuccess)
        newState = test.state.makeNewState(test, "approved")
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
            cmdArgs = [tool, comparison.tmpCmpFile]
        else:
            tool = test.getCompositeConfigValue("diff_program", comparison.stem)
            cmdArgs = [tool, comparison.stdCmpFile, comparison.tmpCmpFile]
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
        return test.getIndent()  # Mostly so we can override for queuesystem module

    def askUser(self, test, allowView, process=None):
        versions = test.app.getSaveableVersions()
        options = ""
        for i in range(len(versions)):
            options += "Approve Version " + versions[i] + "(" + str(i + 1) + "), "
        options += "Approve(a) or continue(any other key)?"
        if allowView:
            options = "View details(v), " + options
        plugins.log.info(self.getPrefix(test) + options)
        response = sys.stdin.readline()
        exactSave = response.find('+') != -1
        if response.startswith('a'):
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
            killProcessAndChildren(process.pid)
        return 0
