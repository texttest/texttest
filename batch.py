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

import os, performance, plugins, respond, sys, string, time

def getBatchConfigValue(app, entryName, sessionName):
    dict = app.getConfigValue(entryName)
    if dict.has_key(sessionName):
        return dict[sessionName]
    elif dict.has_key("default"):
        return dict["default"]
    return None

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
        badVersion = self.findUnacceptableVersion(app)
        if badVersion != None:
            print "Rejected application", app, "for", self.batchSession, "session, unregistered version '" + badVersion + "'"
            return 0
        
        self.setTimeLimit(app)
        return 1
    def setTimeLimit(self, app):
        timeLimit = getBatchConfigValue(app, "batch_timelimit", self.batchSession)
        if timeLimit:
            self.performanceFilter = performance.TimeFilter(timeLimit)
    def findUnacceptableVersion(self, app):
        allowedVersions = getBatchConfigValue(app, "batch_version", self.batchSession)
        for version in app.versions:
            if len(version) and not version in allowedVersions:
                return version
        return None

class BatchCategory(plugins.Filter):
    def __init__(self, description):
        self.description = description
        self.count = 0
        self.testLines = {}
    def addTest(self, test, postText):
        if not postText:
            postText = ""
        if len(postText) > 0:
            postText = " : " + postText
        self.testLines[test.getRelPath()] = test.getIndent() + "- " + repr(test) + postText + os.linesep
        self.count += 1
    def acceptsTestCase(self, test):
        return self.testLines.has_key(test.getRelPath())
    def describe(self, mailFile, app):
        if self.count > 0:
            mailFile.write("The following tests " + self.description + " : " + os.linesep)
            valid, suite = app.createTestSuite([ self ])
            self.writeTestLines(mailFile, suite)
            mailFile.write(os.linesep)
    def writeTestLines(self, mailFile, test):
        if test.classId() == "test-case":
            mailFile.write(self.testLines[test.getRelPath()])
        else:
            mailFile.write(test.getIndent() + "In " + repr(test) + ":" + os.linesep)
            for subtest in test.testcases:
                self.writeTestLines(mailFile, subtest)         

allBatchResponders = []
categoryNames = [ "badPredict", "crash", "dead", "difference", "faster", "slower",\
                  "larger", "smaller", "success", "unfinished" ]
categoryDescriptions = [ "had internal errors", "CRASHED", "caused exception", "FAILED", \
                         "ran faster", "ran slower", "used more memory", "used less memory", "succeeded", "were unfinished" ]

# Works only on UNIX
class BatchResponder(respond.Responder):
    def __init__(self, lineCount, sessionName):
        self.sessionName = sessionName
        self.failureDetail = {}
        self.crashDetail = {}
        self.deadDetail = {}
        self.orderedTests = []
        self.categories = {}
        for i in range(len(categoryNames)):
            self.categories[categoryNames[i]] = BatchCategory(categoryDescriptions[i])
        self.mainSuite = None
        self.responder = respond.UNIXInteractiveResponder(lineCount)
        allBatchResponders.append(self)
    def addTestToCategory(self, category, test, postText = ""):
        if category != None:
            self.orderedTests.append(test)
            self.categories[category].addTest(test, postText)
    def handleSuccess(self, test):
        self.addTestToCategory("success", test)
    def handleKilled(self, test):
        self.addTestToCategory("unfinished", test)
    def handleUnrunnable(self, test):
        self.addTestToCategory("dead", test)
        self.deadDetail[test] = test.stateDetails
    def handleFailure(self, test, testComparison):
        category = testComparison.getType()
        if category == "crash":
            self.crashDetail[test] = testComparison.failedPrediction
            self.addTestToCategory(category, test)
        else:
            self.failureDetail[test] = testComparison
            self.addTestToCategory(category, test, testComparison.failedPrediction)
    def setUpSuite(self, suite):
        if self.mainSuite == None:
            self.mainSuite = suite
    def failureCount(self):
        return self.testCount() - self.categories["success"].count
    def testCount(self):
        count = 0
        for category in self.categories.values():
            count += category.count
        return count
    def writeMailBody(self, mailFile):
        for categoryName in categoryNames:
            self.categories[categoryName].describe(mailFile, self.mainSuite.app)
        if len(self.deadDetail) > 0:
            self.writeDeadDetail(mailFile)
        if len(self.crashDetail) > 0:
            self.writeCrashDetail(mailFile)
        if len(self.failureDetail) > 0:
            self.writeFailureDetail(mailFile)
    def writeDeadDetail(self, mailFile):
        mailFile.write(os.linesep + "Exception information for the tests that did not run follows..." + os.linesep)
        for test in self.orderedTests:
            if not self.deadDetail.has_key(test):
                continue
            exc = self.deadDetail[test]
            mailFile.write("--------------------------------------------------------" + os.linesep)
            mailFile.write("TEST UNRUNNABLE -> " + repr(test) + "(under " + test.getRelPath() + ")" + os.linesep)
            mailFile.write(str(exc) + os.linesep)
    def writeCrashDetail(self, mailFile):
        mailFile.write(os.linesep + "Crash information for the tests that crashed follows..." + os.linesep)
        for test in self.orderedTests:
            if not self.crashDetail.has_key(test):
                continue
            stackTrace = self.crashDetail[test]
            mailFile.write("--------------------------------------------------------" + os.linesep)
            mailFile.write("TEST CRASHED -> " + repr(test) + "(under " + test.getRelPath() + ")" + os.linesep)
            mailFile.write(stackTrace)
    def writeFailureDetail(self, mailFile):
        mailFile.write(os.linesep + "Failure information for the tests that failed follows..." + os.linesep)
        for test in self.orderedTests:
            if not self.failureDetail.has_key(test):
                continue
            testComparison = self.failureDetail[test]
            comparisonList = testComparison.getComparisons()
            if len(comparisonList):
                mailFile.write("--------------------------------------------------------" + os.linesep)
                mailFile.write("TEST " + repr(testComparison) + " -> " + repr(test) + "(under " + test.getRelPath() + ")" + os.linesep)
                os.chdir(test.getDirectory(temporary=1))
                self.responder.displayComparisons(comparisonList, mailFile, self.mainSuite.app)
    def getCleanUpAction(self):
        return MailSender(self.sessionName) 

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
        toAddress = self.getRecipient(app)
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
        return getBatchConfigValue(app, "batch_use_collection", self.sessionName) == "true"
    def getRecipient(self, app):
        # See if the session name has an entry, if not, send to the user
        return os.path.expandvars(getBatchConfigValue(app, "batch_recipients", self.sessionName))
    def getMailHeader(self, app, appResponders):
        title = time.strftime("%y%m%d") + " " + repr(app) + " Test Suite "
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
        
class CollectFiles(plugins.Action):
    def __init__(self):
        self.mailSender = MailSender("collection")
        self.diag = plugins.getDiagnostics("batch collect")
    def setUpApplication(self, app):
        fileBodies = []
        totalValues = []
        for category in categoryNames:
            totalValues.append(0)
        prefix = "batchreport." + app.name + app.versionSuffix()
        # Don't collect to more collections!
        self.diag.info("Setting up application " + app.name + " looking for " + prefix) 
        app.addConfigEntry("collection", self.getCollectionSetting(), "batch_use_collection")
        filelist = os.listdir(app.abspath)
        filelist.sort()
        for filename in filelist:
            if filename.startswith(prefix):
                fullname = os.path.join(app.abspath, filename)
                file = open(fullname)
                app.addConfigEntry("collection", file.readline().strip(), "batch_recipients")
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
    def getCollectionSetting(self):
        if plugins.BackgroundProcess.fakeProcesses:
            return "true"
        else:
            return "false"
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
