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
             <bname>_use_collection, if equal to "true", send the batch report to an intermediate file where it
             can be collected and amalgamated with others using the script batch.CollectFiles. This avoids too
             many emails being sent by batch mode if many independent things are tested.
"""

import os, performance, plugins, respond, sys, predict, string

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
allBatchResponders = []
categoryNames = [ "badPredict", "crash", "dead", "difference", "faster", "slower", "success", "unfinished" ]
categoryDescriptions = [ "had internal errors", "CRASHED", "caused exception", "FAILED", "ran faster", "ran slower", "succeeded", "were unfinished" ]

# Works only on UNIX
class BatchResponder(respond.Responder):
    def __init__(self, lineCount):
        self.failureDetail = {}
        self.crashDetail = {}
        self.deadDetail = {}
        self.categories = {}
        for i in range(len(categoryNames)):
            self.categories[categoryNames[i]] = BatchCategory(categoryDescriptions[i])
        self.mainSuite = None
        self.responder = respond.UNIXInteractiveResponder(lineCount)
        allBatchResponders.append(self)
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
        if not test in killedTests and not test in self.crashDetail.keys():
            self.addTestToCategory("badPredict", test, desc)
    def handleCoreFile(self, test):
        crashText = self.responder.getCrashText(test)
        self.crashDetail[test] = crashText
    def handleDead(self, test):
        self.deadDetail[test] = test.stateDetails
        self.addTestToCategory("dead", test)
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
        return self.testCount() - self.categories["success"].count
    def testCount(self):
        count = 0
        for category in self.categories.values():
            count += category.count
        return count
    def writeMailBody(self, mailFile):
        for categoryName in categoryNames:
            self.categories[categoryName].describe(mailFile)
        if len(self.deadDetail) > 0:
            self.writeDeadDetail(mailFile)
        if len(self.crashDetail) > 0:
            self.writeCrashDetail(mailFile)
        if len(self.failureDetail) > 0:
            self.writeFailureDetail(mailFile)
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
        
class MailSender(plugins.Action):
    def __init__(self, sessionName):
        self.sessionName = sessionName
    def getResponders(self, app):
        appResponders = []
        for responder in allBatchResponders:
           if responder.mainSuite and responder.mainSuite.app.name == app.name and responder.testCount() > 0:
               appResponders.append(responder)
        return appResponders
    def setUpApplication(self, app):
        appResponders = self.getResponders(app)
        if len(appResponders) == 0:
            return
        mailTitle = self.getMailTitle(app, appResponders)
        mailFile = self.createMail(mailTitle, app, appResponders)
        if len(appResponders) > 1:
            for resp in appResponders:
                mailFile.write(self.getMailTitle(app, [ resp ]) + os.linesep)
            mailFile.write(os.linesep)
        for resp in appResponders:
            if len(appResponders) > 1:
                mailFile.write("---------------------------------------------------------------------------------" + os.linesep)
                mailFile.write(self.getMailTitle(app, [ resp ]) + os.linesep)
                mailFile.write(os.linesep)
            resp.writeMailBody(mailFile)
            mailFile.write(os.linesep)
        mailFile.close()
        for responder in appResponders:
            allBatchResponders.remove(responder)
    def createMail(self, title, app, appResponders):
        fromAddress = os.environ["USER"]
        toAddress = self.getRecipient(fromAddress, app)
        if self.useCollection(app):
            collFile = os.path.join(app.abspath, "batchreport." + app.name + app.versionSuffix())
            mailFile = open(collFile, "w")
            mailFile.write(toAddress + os.linesep)
            mailFile.write(self.getMachineTitle(app, appResponders) + os.linesep)
            mailFile.write(title + os.linesep)
            mailFile.write(os.linesep) # blank line separating headers from body
            return mailFile
        else:
            mailFile = os.popen("/usr/lib/sendmail -t", "w")
            mailFile.write("From: " + fromAddress + os.linesep)
            mailFile.write("To: " + toAddress + os.linesep)
            mailFile.write("Subject: " + title + os.linesep)
            mailFile.write(os.linesep) # blank line separating headers from body
            return mailFile
    def useCollection(self, app):
        try:
            return app.getConfigValue(self.sessionName + "_use_collection") == "true"
        except:
            return 0
    def getRecipient(self, fromAddress, app):
        # See if the session name has an entry, if not, send to the user
        try:
            return app.getConfigValue(self.sessionName + "_recipients")
        except:
            return fromAddress
    def getMailHeader(self, app, appResponders):
        title = repr(app) + " Test Suite "
        versions = self.findCommonVersions(app, appResponders)
        return title + self.getVersionString(versions) + ": "
    def getMailTitle(self, app, appResponders):
        title = self.getMailHeader(app, appResponders)
        title += self.getTotalString(appResponders, BatchResponder.testCount) + " tests ran"
        if self.getTotalString(appResponders, BatchResponder.failureCount) == "0":
            return title + ", all successful"
        title += " :"
        for categoryName in categoryNames:
            totalInCategory = self.getCategoryCount(categoryName, appResponders)
            title += self.briefText(totalInCategory, appResponders[0].categories[categoryName].description)
        # Lose trailing comma
        return title[:-1]
    def getMachineTitle(self, app, appResponders):
        values = []
        for categoryName in categoryNames:
            values.append(str(self.getCategoryCount(categoryName, appResponders)))
        return string.join(values, ',')
    def getTotalString(self, appResponders, method):
        total = 0
        for resp in appResponders:
            total += method(resp)
        return str(total)
    def getCategoryCount(self, categoryName, appResponders):
        total = 0
        for resp in appResponders:
            total += resp.categories[categoryName].count
        return total
    def getVersionString(self, versions):
        if len(versions) > 0:
            return "(version " + string.join(versions, ".") + ") "
        else:
            return ""
    def briefText(self, count, description):
        if count == 0 or description == "succeeded":
            return ""
        else:
            return " " + str(count) + " " + description + ","
    def findCommonVersions(self, app, appResponders):
        if len(appResponders) == 0:
            return app.versions
        versions = appResponders[0].mainSuite.app.versions
        for resp in appResponders[1:]:
            for version in versions:
                if not version in resp.mainSuite.app.versions:
                    versions.remove(version)
        return versions
    def getCleanUpAction(self):
        return SendException(self) 

class SendException(plugins.Action):
    def __init__(self, mailSender):
        self.mailSender = mailSender
    def setUpApplication(self, app):
        type, value, traceback = sys.exc_info()
        excData = str(value)
        if len(excData) == 0:
            excData = "caught exception " + str(type)
        appResponders = self.mailSender.getResponders(app)
        if len(appResponders) == 0:
            return
        mailTitle = self.mailSender.getMailHeader(app, appResponders) + "did not run : " + excData
        mailFile = self.mailSender.createMail(mailTitle, app, appResponders)
        sys.stderr = mailFile
        sys.excepthook(type, value, traceback)
        sys.stderr = sys.__stderr__
        mailFile.close()
        for responder in appResponders:
            allBatchResponders.remove(responder)
        
class CollectFiles(plugins.Action):
    def __init__(self):
        self.mailSender = MailSender("collection")
    def setUpApplication(self, app):
        fileBodies = []
        totalValues = []
        for category in categoryNames:
            totalValues.append(0)
        prefix = "batchreport." + app.name + app.versionSuffix()
        for filename in os.listdir(app.abspath):
            if filename.startswith(prefix):
                fullname = os.path.join(app.abspath, filename)
                file = open(fullname)
                app.setConfigDefault("collection_recipients", file.readline().strip())
                catValues = plugins.commasplit(file.readline().strip())
                for i in range(len(categoryNames)):
                    totalValues[i] += int(catValues[i])
                fileBodies.append(file.read())
                file.close()
                try:
                    os.remove(fullname)
                except OSError:
                    print "Don't have permissions to remove file", fullname
        if len(fileBodies) == 0:
            return
        
        mailTitle = self.getTitle(app, totalValues)
        mailFile = self.mailSender.createMail(mailTitle, app, [])
        self.writeBody(mailFile, fileBodies)
        mailFile.close()
    def getTitle(self, app, totalValues):
        title = self.mailSender.getMailHeader(app, [])
        total = 0
        for value in totalValues:
            total += value
        title += str(total) + " tests ran"
        if totalValues[categoryNames.index("success")] == total:
            return title + ", all successful"
        title += " :"
        for index in range(len(categoryNames)):
            title += self.mailSender.briefText(totalValues[index], categoryDescriptions[index])
        # Lose trailing comma
        return title[:-1]
    def writeBody(self, mailFile, bodies):
        if len(bodies) > 1:
            for body in bodies:
                firstSep = body.find(os.linesep) + 1
                mailFile.write(body[0:firstSep])
            mailFile.write(os.linesep)
        for body in bodies:
            if len(bodies) > 1:
                mailFile.write("================================================================================" + os.linesep + os.linesep)
            mailFile.write(body)
