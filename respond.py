#!/usr/local/bin/python
import comparetest, ndiff, sys, string, os
    
# Abstract base to make it easier to write test responders
class Responder:
    def __repr__(self):
        return "Responding to"
    def __call__(self, test, description):
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
            self.displayComparisons(comparisons, sys.stdout)
            self.askUser(test, comparisons, 0)
    def displayComparisons(self, comparisons, displayStream):
        for comparison in comparisons:
            displayStream.write("------------------ Differences in " + repr(comparison) + " --------------------\n")
            self.display(comparison, displayStream)
    def display(self, comparison, displayStream):
        fileWritten = os.popen(ndiff.fcompare(comparison.stdCmpFile, comparison.tmpCmpFile))
        displayStream.write(fileWritten.read())
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
    def display(self, comparison, displayStream):
        argumentString = " " + comparison.stdCmpFile + " " + comparison.tmpCmpFile
        if repr(comparison) == "output" and displayStream == sys.stdout:
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

class BatchResponder(Responder):
    def __init__(self, lineCount):
        self.failures = {}
        self.successes = []
        self.mainSuite = None
        self.responder = UNIXInteractiveResponder(lineCount)
    def __del__(self):
        mailFile = os.popen("sendmail -t", "w")
        address = os.environ["USER"]
        mailFile.write("From: " + address + os.linesep)
        mailFile.write("To: " + address + os.linesep)
        mailFile.write("Subject: " + self.getMailTitle() + os.linesep)
        mailFile.write(os.linesep) # blank line separating headers from body
        if len(self.successes) > 0:
            mailFile.write("The following tests succeeded : " + os.linesep)
            mailFile.writelines(self.successes)
        if self.failureCount() > 0:
            self.reportFailures(mailFile)
        mailFile.close()
    def handleSuccess(self, test):
        self.successes.append(self.testLine(test))
    def handleFailure(self, test, comparisons):
        self.failures[test] = comparisons
    def setUpSuite(self, suite, description):
        if self.mainSuite == None:
            self.mainSuite = suite
    def failureCount(self):
        return len(self.failures)
    def testCount(self):
        return self.failureCount() + len(self.successes)
    def getMailTitle(self):
        suiteDescription = repr(self.mainSuite.app) + " Test Suite (" + self.mainSuite.name + " in " + self.mainSuite.app.checkout + ") : "
        return suiteDescription + str(self.failureCount()) + " out of " + str(self.testCount()) + " tests failed"
    def testLine(self, test):
        return repr(test) + os.linesep
    def reportFailures(self, mailFile):
        mailFile.write(os.linesep + "The following tests failed : " + os.linesep)
        mailFile.writelines(map(self.testLine, self.failures.keys()))
        mailFile.write(os.linesep + "Failure information for the tests that failed follows..." + os.linesep)
        for test in self.failures.keys():
            mailFile.write("--------------------------------------------------------" + os.linesep)
            mailFile.write("TEST FAILED -> " + repr(test) + os.linesep)
            os.chdir(test.abspath)
            self.responder.displayComparisons(self.failures[test], mailFile)
        
