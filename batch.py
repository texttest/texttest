#!/usr/local/bin/python
import os, performance, plugins, respond

class BatchFilter(plugins.Filter):
    def __init__(self, batchSession):
        self.batchSession = batchSession
        self.performanceFilter = None
    def acceptsTestCase(self, test):
        if self.performanceFilter == None:
            return 1
        else:
            return self.performanceFilter.acceptsTestCase(test)
    def acceptsApplication(self, app):
        if not self.hasRecipients(app):
            print "Rejected application", app, "for", self.batchSession, "session"
            return 0
        if not self.acceptsVersion(app):
            print "Rejected application", app, "for", self.batchSession, "session, unregistered version '" + app.version + "'"
            return 0
        
        self.setTimeLimit(app)
        return 1
    def hasRecipients(self, app):
        try:
            return app.getConfigValue(self.batchSession + "_recipients") != "none"
        except:
            return 1
    def setTimeLimit(self, app):
        try:
            timeLimit = app.getConfigValue(self.batchSession + "_timelimit")
            self.performanceFilter = performance.TimeFilter(timeLimit)
        except:
            self.performanceFilter = None
    def acceptsVersion(self, app):
        allowedVersions = app.getConfigList(self.batchSession + "_version")
        return len(allowedVersions) == 0 or app.version in allowedVersions

class BatchCategory:
    def __init__(self, description):
        self.description = description
        self.count = 0
        self.text = []
    def addTest(self, test):
        self.text.append(test.getIndent() + "- " + repr(test) + os.linesep)
        self.count += 1
    def addSuite(self, suite):
        line = suite.getIndent() + "In " + repr(suite) + ":" + os.linesep
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
class BatchResponder(respond.Responder):
    def __repr__(self):
        return "Batch mode response to"
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
        self.responder = respond.UNIXInteractiveResponder(lineCount)
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
    def setUpSuite(self, suite):
        if self.mainSuite == None:
            self.mainSuite = suite
        for category in self.categories.values():
            category.addSuite(suite)
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
        
