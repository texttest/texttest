#!/usr/local/bin/python
import comparetest, ndiff, sys, string, os, performance
    
# Abstract base to make it easier to write test responders
class Responder:
    def __repr__(self):
        return "Responding to"
    def __call__(self, test, description):
        if os.path.isfile("core.Z"):
            os.system("uncompress core.Z")
        if os.path.isfile("core"):
            self.handleCoreFile(test)
            os.remove("core")
        if comparetest.testComparisonMap.has_key(test):
            comparisons = comparetest.testComparisonMap[test]
            print test.getIndent() + repr(test), self, "differences in", self.comparisonsString(comparisons)
            self.handleFailure(test, comparisons)
            del comparetest.testComparisonMap[test]
        else:
            self.handleSuccess(test)
    def handleSuccess(self, test):
        pass
    def comparisonsString(self, comparisons):
        return string.join([repr(x) for x in comparisons], ",")
    def setUpSuite(self, suite, description):
        pass

# Uses the python ndiff library, which should work anywhere. Override display method to use other things
class InteractiveResponder(Responder):
    def __repr__(self):
        return "FAILED :"
    def handleFailure(self, test, comparisons):
        performView = self.askUser(test, comparisons, 1)
        if performView:
            self.displayComparisons(comparisons, sys.stdout, test.app.getConfigValue("log_file"))
            self.askUser(test, comparisons, 0)
    def displayComparisons(self, comparisons, displayStream, logFile):
        for comparison in comparisons:
            displayStream.write("------------------ Differences in " + repr(comparison) + " --------------------\n")
            self.display(comparison, displayStream, logFile)
    def display(self, comparison, displayStream, logFile):
        ndiff.fcompare(comparison.stdCmpFile, comparison.tmpCmpFile)
    def askUser(self, test, comparisons, allowView):      
        options = "Save(s) or continue(any other key)?"
        if len(test.app.version) > 0:
            options = "Save Version " + test.app.version + "(z), " + options
        if allowView:
            options = "View details(v), " + options
        print test.getIndent() + options
        response = sys.stdin.readline();
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
    def display(self, comparison, displayStream, logFile):
        argumentString = " " + comparison.stdCmpFile + " " + comparison.tmpCmpFile
        if repr(comparison) == logFile and displayStream == sys.stdout:
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
    def __repr__(self):
        return "- overwriting"
    def handleFailure(self, test, comparisons):
        for comparison in comparisons:
            comparison.overwrite(self.version)

class BatchFilter:
    def __init__(self, batchSession):
        self.recipientEntry = batchSession + "_recipients"
        self.timeEntry = batchSession + "_timelimit"
        self.currentApp = None
        self.performanceFilter = None
    def acceptsTestCase(self, test):
        if self.performanceFilter == None:
            return 1
        else:
            return self.performanceFilter.acceptsTestCase(test)
    def acceptsTestSuite(self, suite):
        if suite.app == self.currentApp:
            return 1
        self.currentApp = suite.app
        # Check if the recipients are none...
        try:
            if suite.app.getConfigValue(self.recipientEntry) == "none":
                return 0
        except:
            pass
        try:
            self.performanceFilter = performance.TimeFilter(suite.app.getConfigValue(self.timeEntry))
        except:
            self.performanceFilter = None
        return 1

class BatchCategory:
    def __init__(self, description):
        self.description = description
        self.count = 0
        self.text = []
    def addTest(self, test):
        self.text.append(test.getIndent() + "- " + repr(test) + os.linesep)
        self.count += 1
    def addSuite(self, suite, description):
        line = description + ":" + os.linesep
        currentIndent = len(suite.getIndent())
        # Remove lines corresponding to suites with no entries
        if len(self.text) > 0:
            lastLine = self.text[-1]
            lastIndent = len(lastLine) - len(lastLine.lstrip())
            if lastIndent == currentIndent:
                self.text.pop()
        self.text.append(line)
    def briefText(self):
        if self.description == "succeeded" or self.count == 0:
            return ""
        else:
            return " " + str(self.count) + " " + self.description + ","
    def describe(self, mailFile):
        lastLine = self.text[-1]
        # If the last line talked about a suite, it's not interesting...
        if lastLine.find("test-suite") != -1:
            self.text.pop()
        if self.count > 0:
            mailFile.write("The following tests " + self.description + " : " + os.linesep)
            mailFile.writelines(self.text)
            mailFile.write(os.linesep)

# Works only on UNIX
class BatchResponder(Responder):
    def __repr__(self):
        return "In"
    def __init__(self, lineCount, sessionName):
        self.sessionName = sessionName
        self.failureDetail = {}
        self.crashDetail = {}
        self.categories = {}
        self.categories["crash"] = BatchCategory("CRASHED")
        self.categories["difference"] = BatchCategory("FAILED")
        self.categories["faster"] = BatchCategory("ran faster")
        self.categories["slower"] = BatchCategory("ran slower")
        self.categories["success"] = BatchCategory("succeeded")
        self.orderedCategories = self.categories.keys()
        self.orderedCategories.sort()
        self.mainSuite = None
        self.responder = UNIXInteractiveResponder(lineCount)
    def __del__(self):
        if self.testCount() > 0:
            self.sendMail()
    def sendMail(self):
        mailFile = os.popen("sendmail -t", "w")
        fromAddress = os.environ["USER"]
        toAddress = self.getRecipient(fromAddress)
        mailFile.write("From: " + fromAddress + os.linesep)
        mailFile.write("To: " + toAddress + os.linesep)
        mailFile.write("Subject: " + self.getMailTitle() + os.linesep)
        mailFile.write(os.linesep) # blank line separating headers from body
        for categoryName in self.orderedCategories:
            self.categories[categoryName].describe(mailFile)
        if len(self.crashDetail) > 0:
            self.writeCrashDetail(mailFile)
        if self.failureCount() > 0:
            self.writeFailureDetail(mailFile)
        mailFile.close()
    def getRecipient(self, fromAddress):
        # See if the session name has an entry, if not, send to the user
        try:
            return self.mainSuite.app.getConfigValue(self.sessionName + "_recipients")
        except:
            return fromAddress
    def handleSuccess(self, test):
        category = self.findSuccessCategory(test)
        self.categories[category].addTest(test)
    def handleFailure(self, test, comparisons):
        category = self.findFailureCategory(test, comparisons)
        self.categories[category].addTest(test)
        self.failureDetail[test] = comparisons
    def findFailureCategory(self, test, comparisons):
        if test in self.crashDetail.keys():
            return "crash"
        if len(comparisons) > 1:
            return "difference"
        return comparisons[0].getType()
    def findSuccessCategory(self, test):
        if test in self.crashDetail.keys():
            return "crash"
        return "success"
    def handleCoreFile(self, test):
        crashText = self.responder.getCrashText(test)
        self.crashDetail[test] = crashText
    def setUpSuite(self, suite, description):
        if self.mainSuite == None:
            self.mainSuite = suite
        for category in self.categories.values():
            category.addSuite(suite, description)
    def failureCount(self):
        return len(self.failureDetail)
    def testCount(self):
        count = 0
        for category in self.categories.values():
            count += category.count
        return count
    def getMailTitle(self):
        title = repr(self.mainSuite.app) + " Test Suite (" + self.mainSuite.name + " in " + self.mainSuite.app.checkout + ") : "
        title += str(self.testCount()) + " tests ran"
        if self.failureCount() == 0:
            return title + ", all successful"
        title += " :"
        for categoryName in self.orderedCategories:
            title += self.categories[categoryName].briefText()
        # Lose trailing comma
        return title[:-1]
    def writeCrashDetail(self, mailFile):
        mailFile.write(os.linesep + "Crash information for the tests that crashed follows..." + os.linesep)
        for test, stackTrace in self.crashDetail.items():
            mailFile.write("--------------------------------------------------------" + os.linesep)
            mailFile.write("TEST CRASHED -> " + repr(test) + "(under " + test.getRelPath() + ")" + os.linesep)
            mailFile.write(stackTrace)
    def writeFailureDetail(self, mailFile):
        mailFile.write(os.linesep + "Failure information for the tests that failed follows..." + os.linesep)
        for test, comparisons in self.failureDetail.items():
            mailFile.write("--------------------------------------------------------" + os.linesep)
            mailFile.write("TEST FAILED -> " + repr(test) + "(under " + test.getRelPath() + ")" + os.linesep)
            os.chdir(test.abspath)
            self.responder.displayComparisons(comparisons, mailFile, None)
        
