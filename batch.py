#!/usr/local/bin/python

helpOptions = """
-b <bname> - run in batch mode, using batch session name <bname>. This will replace the interactive
             dialogue with an email report, which is sent to $USER if the session name <bname> is
             not recognised by the config file.

             There is also a possibility to define batch sessions in the config file. The following
             entries are understood:
             <bname>_timelimit,  if present, will run only tests up to that limit
             <bname>_recipients, if present, ensures that mail is sent to those addresses instead of $USER.
             If set to "none", it ensures that that batch session will ignore that application.
             <bname>_version, these entries form a list and ensure that only the versions listed are accepted.
             If the list is empty, all versions are allowed.
"""

import os, performance, plugins, respond, sys, predict

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
        badVersion = self.findUnacceptableVersion(app)
        if badVersion != None:
            print "Rejected application", app, "for", self.batchSession, "session, unregistered version '" + badVersion + "'"
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
    def findUnacceptableVersion(self, app):
        allowedVersions = app.getConfigList(self.batchSession + "_version")
        if len(allowedVersions) == 0:
            return None
        for version in app.versions:
            if not version in allowedVersions:
                return version
        return None

class BatchCategory:
    def __init__(self, description):
        self.description = description
        self.count = 0
        self.text = []
    def addTest(self, test, postText):
        if len(postText) > 0:
            postText = " : " + postText
        self.text.append(test.getIndent() + "- " + repr(test) + postText + os.linesep)
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

killedTests = []

# Works only on UNIX
class BatchResponder(respond.Responder):
    def __init__(self, lineCount, sessionName):
        self.sessionName = sessionName
        self.failureDetail = {}
        self.crashDetail = {}
        self.deadDetail = {}
        self.categories = {}
        self.categories["crash"] = BatchCategory("CRASHED")
        self.categories["difference"] = BatchCategory("FAILED")
        self.categories["faster"] = BatchCategory("ran faster")
        self.categories["slower"] = BatchCategory("ran slower")
        self.categories["success"] = BatchCategory("succeeded")
        self.categories["unfinished"] = BatchCategory("were unfinished")
        self.categories["badPredict"] = BatchCategory("had internal errors")
        self.orderedCategories = self.categories.keys()
        self.orderedCategories.sort()
        self.mainSuite = None
        self.responder = respond.UNIXInteractiveResponder(lineCount)
    def __del__(self):
        if self.testCount() > 0:
            self.sendMail()
    def sendMail(self):
        mailFile = self.createMail(self.getMailTitle(), self.mainSuite.app)
        for categoryName in self.orderedCategories:
            self.categories[categoryName].describe(mailFile)
        if len(self.deadDetail) > 0:
            self.writeDeadDetail(mailFile)
        if len(self.crashDetail) > 0:
            self.writeCrashDetail(mailFile)
        if len(self.failureDetail) > 0:
            self.writeFailureDetail(mailFile)
        mailFile.close()
    def createMail(self, title, app):
        mailFile = os.popen("/usr/lib/sendmail -t", "w")
        fromAddress = os.environ["USER"]
        toAddress = self.getRecipient(fromAddress, app)
        mailFile.write("From: " + fromAddress + os.linesep)
        mailFile.write("To: " + toAddress + os.linesep)
        mailFile.write("Subject: " + title + os.linesep)
        mailFile.write(os.linesep) # blank line separating headers from body
        return mailFile
    def getRecipient(self, fromAddress, app):
        # See if the session name has an entry, if not, send to the user
        try:
            return app.getConfigValue(self.sessionName + "_recipients")
        except:
            return fromAddress
    def addTestToCategory(self, category, test, postText = ""):
        if category != None:
            self.categories[category].addTest(test, postText)
    def handleSuccess(self, test):
        category = self.findSuccessCategory(test)
        self.addTestToCategory(category, test)
    def handleFailure(self, test, testComparison):
        category = self.findFailureCategory(test, testComparison)
        self.addTestToCategory(category, test)
    def handleFailedPrediction(self, test, desc):
        self.addTestToCategory("badPredict", test, desc)
    def handleCoreFile(self, test):
        crashText = self.responder.getCrashText(test)
        self.crashDetail[test] = crashText
    def handleDead(self, test):
        self.deadDetail[test] = test.deathReason
    def findFailureCategory(self, test, testComparison):
        successCategory = self.findSuccessCategory(test)
        if successCategory != "success":
            return successCategory
        # Don't provide failure information on crashes and unfinished tests, it's confusing...
        self.failureDetail[test] = testComparison
        return testComparison.getType()
    def findSuccessCategory(self, test):
        if test in killedTests:
            return "unfinished"
        if test in self.crashDetail.keys():
            return "crash"
        # Already added it in this case
        if predict.testBrokenPredictionMap.has_key(test):
            return None
        return "success"
    def setUpSuite(self, suite):
        if self.mainSuite == None:
            self.mainSuite = suite
        for category in self.categories.values():
            category.addSuite(suite)
    def failureCount(self):
        return len(self.failureDetail) + len(self.crashDetail) + len(self.deadDetail) + self.categories["badPredict"].count
    def testCount(self):
        count = 0
        for category in self.categories.values():
            count += category.count
        return count + len(self.deadDetail)
    def getMailHeader(self, app):
        versionString = ""
        if len(app.versions) == 1:
            versionString = "(version " + app.versions[0] + ") "
        elif len(app.versions) > 1:
            versionString = "(versions " + repr(app.versions) + ") "
        return repr(app) + " Test Suite " + versionString + ": "
    def getMailTitle(self):
        title = self.getMailHeader(self.mainSuite.app)
        title += str(self.testCount()) + " tests ran"
        if self.failureCount() == 0:
            return title + ", all successful"
        title += " :"
        for categoryName in self.orderedCategories:
            title += self.categories[categoryName].briefText()
        if len(self.deadDetail) > 0:
            title += " " + str(len(self.deadDetail)) + " caused exception,"
        # Lose trailing comma
        return title[:-1]
    def writeDeadDetail(self, mailFile):
        mailFile.write(os.linesep + "Exception information for the tests that did not run follows..." + os.linesep)
        for test, exc in self.deadDetail.items():
            mailFile.write("--------------------------------------------------------" + os.linesep)
            mailFile.write("TEST UNRUNNABLE -> " + repr(test) + "(under " + test.getRelPath() + ")" + os.linesep)
            mailFile.write(str(exc) + os.linesep)
    def writeCrashDetail(self, mailFile):
        mailFile.write(os.linesep + "Crash information for the tests that crashed follows..." + os.linesep)
        for test, stackTrace in self.crashDetail.items():
            mailFile.write("--------------------------------------------------------" + os.linesep)
            mailFile.write("TEST CRASHED -> " + repr(test) + "(under " + test.getRelPath() + ")" + os.linesep)
            mailFile.write(stackTrace)
    def writeFailureDetail(self, mailFile):
        mailFile.write(os.linesep + "Failure information for the tests that failed follows..." + os.linesep)
        for test, testComparison in self.failureDetail.items():
            mailFile.write("--------------------------------------------------------" + os.linesep)
            mailFile.write("TEST " + repr(testComparison) + " -> " + repr(test) + "(under " + test.getRelPath() + ")" + os.linesep)
            os.chdir(test.abspath)
            self.responder.displayComparisons(testComparison.getComparisons(), mailFile, self.mainSuite.app)
    def getCleanUpAction(self):
        return SendException(self) 

class SendException(plugins.Action):
    def __init__(self, batchResponder):
        self.batchResponder = batchResponder
    def setUpApplication(self, app):
        type, value, traceback = sys.exc_info()
        excData = str(value)
        if len(excData) == 0:
            excData = "caught exception " + str(type)
        mailTitle = self.batchResponder.getMailHeader(app) + "did not run : " + excData
        mailFile = self.batchResponder.createMail(mailTitle, app)
        sys.stderr = mailFile
        sys.excepthook(type, value, traceback)
        sys.stderr = sys.__stderr__
        mailFile.close()
        
