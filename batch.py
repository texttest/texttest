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

import os, performance, plugins, respond, sys, string, time, types
from ndict import seqdict

def getBatchConfigValue(app, entryName, sessionName):
    dict = app.getConfigValue(entryName)
    if dict.has_key(sessionName):
        retVal = dict[sessionName]
        if type(retVal) == types.ListType:
            return retVal + dict["default"]
        else:
            return retVal
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
    def __init__(self, state):
        self.name = state.category
        if state.categoryDescriptions.has_key(self.name):
            self.briefDescription, self.longDescription = state.categoryDescriptions[self.name]
        else:
            self.briefDescription, self.longDescription = self.name, self.name
        self.allTests = []
        self.testLines = {}
    def addTest(self, test):
        overall, postText = test.state.getTypeBreakdown()
        if postText == self.name.upper():
            # Don't double report here
            postText = ""
        elif len(postText) > 0:
            postText = " : " + postText
        self.testLines[test.getRelPath()] = test.getIndent() + "- " + repr(test) + postText + os.linesep
        self.allTests.append(test)
    def acceptsTestCase(self, test):
        return self.testLines.has_key(test.getRelPath())
    def describeBrief(self, mailFile, app):
        if len(self.allTests) > 0:
            mailFile.write("The following tests " + self.longDescription + " : " + os.linesep)
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
    def describeFull(self, mailFile):
        fullDescriptionString = self.getFullDescription()
        if fullDescriptionString:
            mailFile.write(os.linesep + "Detailed information for the tests that " + self.longDescription + " follows..." + os.linesep)
            mailFile.write(fullDescriptionString)
    def getFullDescription(self):
        fullText = ""
        for test in self.allTests:
            freeText = test.state.freeText
            if freeText:
                fullText += "--------------------------------------------------------" + os.linesep
                fullText += "TEST " + repr(test.state) + " " + repr(test) + " (under " + test.getRelPath() + ")" + os.linesep
                fullText += freeText
                if not freeText.endswith(os.linesep):
                    fullText += os.linesep
        return fullText

allBatchResponders = []

# Works only on UNIX
class BatchResponder(respond.Responder):
    def __init__(self, sessionName):
        respond.Responder.__init__(self, 0)
        self.sessionName = sessionName
        self.categories = {}
        self.errorCategories = []
        self.failureCategories = []
        self.successCategories = []
        self.mainSuite = None
        allBatchResponders.append(self)
    def writeState(self, test):
        state = test.state
        stateFileName = test.makeFileName("teststate", temporary=1, forComparison=0)
        # Ensure directory exists, it may not
        dir, local = os.path.split(stateFileName)
        if not os.path.isdir(dir):
            os.makedirs(dir)
        stateFile = open(stateFileName, "w")
        stateFile.write(state.category + ":" + state.briefText + os.linesep)
        stateFile.write(state.freeText)
    def handleAll(self, test):
        category = test.state.category
        self.writeState(test)
        if not self.categories.has_key(category):
            batchCategory = BatchCategory(test.state)
            if not test.state.hasResults():
                self.errorCategories.append(batchCategory)
            elif test.state.hasSucceeded():
                self.successCategories.append(batchCategory)
            else:
                self.failureCategories.append(batchCategory)
            self.categories[category] = batchCategory
        self.categories[category].addTest(test)
    def handleFailure(self, test):
        # If free text is brief, override it with difference details
        if test.state.freeText.find(os.linesep) == -1:
            test.state.freeText = self.testComparisonOutput(test)
    def useGraphicalComparison(self, comparison):
        return 0
    def setUpSuite(self, suite):
        if self.mainSuite == None:
            self.mainSuite = suite
    def failureCount(self):
        return self.totalTests(self.failCategories())
    def successCount(self):
        return self.totalTests(self.successCategories)
    def failCategories(self):
        return self.errorCategories + self.failureCategories
    def allCategories(self):
        return self.failCategories() + self.successCategories
    def testCount(self):
        return self.totalTests(self.allCategories())
    def totalTests(self, categoryList):
        count = 0
        for category in categoryList:
            count += len(category.allTests)
        return count
    def writeFailuresBrief(self, mailFile):
        for category in self.failCategories():
            category.describeBrief(mailFile, self.mainSuite.app)        
    def writeSuccessBrief(self, mailFile):
        for category in self.successCategories:
            category.describeBrief(mailFile, self.mainSuite.app)        
    def writeDetails(self, mailFile):
        for category in self.allCategories():
            category.describeFull(mailFile)
    def getCleanUpAction(self):
        return MailSender(self.sessionName)

sectionHeaders = [ "Summary of all Unsuccessful tests", "Details of all Unsuccessful tests", "Summary of all Successful tests" ]

class MailSender(plugins.Action):
    def __init__(self, sessionName):
        self.sessionName = sessionName
        self.diag = plugins.getDiagnostics("Mail Sender")
    def getResponders(self, app):
        appResponders = []
        for responder in allBatchResponders:
            if responder.mainSuite:
                self.diag.info("Responder for " + responder.mainSuite.app.name + " has " + str(responder.testCount()) + " tests.")
            else:
                self.diag.info("Responder with main suite " + str(responder.mainSuite))
            if responder.mainSuite and responder.mainSuite.app.name == app.name and responder.testCount() > 0:
                appResponders.append(responder)
        return appResponders
    def setUpApplication(self, app):
        appResponders = self.getResponders(app)
        if len(appResponders) == 0:
            self.diag.info("No responders for " + repr(app))
            return
        sys.stdout.write("At " + time.strftime("%H:%M") + " creating batch report for application " + repr(app) + " ...")
        sys.stdout.flush()
        mailTitle = self.getMailTitle(app, appResponders)
        mailFile = self.createMail(mailTitle, app, appResponders)
        if len(appResponders) > 1:
            for resp in appResponders:
                mailFile.write(self.getMailTitle(app, [ resp ]) + os.linesep)
            mailFile.write(os.linesep)
        if not self.isAllSuccess(appResponders):
            self.performForAll(mailFile, app, appResponders, BatchResponder.writeFailuresBrief, sectionHeaders[0])
            self.performForAll(mailFile, app, appResponders, BatchResponder.writeDetails, sectionHeaders[1])
        if not self.isAllFailure(appResponders):
            self.performForAll(mailFile, app, appResponders, BatchResponder.writeSuccessBrief, sectionHeaders[2])
        mailFile.close()
        for responder in appResponders:
            allBatchResponders.remove(responder)
        sys.stdout.write("done." + os.linesep)
    def performForAll(self, mailFile, app, appResponders, method, headline):
        mailFile.write(headline + " follows..." + os.linesep)
        mailFile.write("---------------------------------------------------------------------------------" + os.linesep)
        for resp in appResponders:
            if len(appResponders) > 1:
                if headline.find("Details") != -1 and not resp is appResponders[0]:
                    mailFile.write("---------------------------------------------------------------------------------" + os.linesep)
                mailFile.write(self.getMailTitle(app, [ resp ]) + os.linesep)
                mailFile.write(os.linesep)
            method(resp, mailFile)
            mailFile.write(os.linesep)
    def createMail(self, title, app, appResponders):
        fromAddress = os.environ["USER"]
        toAddress = self.getRecipient(app)
        if self.useCollection(app):
            collFile = os.path.join(app.abspath, "batchreport." + app.name + app.versionSuffix())
            self.diag.info("Sending mail to", collFile)
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
        title = time.strftime("%y%m%d") + " " + repr(app)
        versions = self.findCommonVersions(app, appResponders)
        return title + self.getVersionString(versions) + " : "
    def getCategoryNames(self, appResponders):
        names = []
        for resp in appResponders:
            for cat in resp.errorCategories:
                if not cat.name in names:
                    names.append(cat.name)
        for resp in appResponders:
            for cat in resp.failureCategories:
                if not cat.name in names:
                    names.append(cat.name)
        for resp in appResponders:
            for cat in resp.successCategories:
                if not cat.name in names:
                    names.append(cat.name)
        return names
    def isAllSuccess(self, appResponders):
        return self.getTotalString(appResponders, BatchResponder.failureCount) == "0"
    def isAllFailure(self, appResponders):
        return self.getTotalString(appResponders, BatchResponder.successCount) == "0"
    def getMailTitle(self, app, appResponders):
        title = self.getMailHeader(app, appResponders)
        title += self.getTotalString(appResponders, BatchResponder.testCount) + " tests"
        if self.isAllSuccess(appResponders):
            return title + ", all successful"
        title += " :"
        for categoryName in self.getCategoryNames(appResponders):
            totalInCategory = self.getCategoryCount(categoryName, appResponders)
            briefDesc = self.getBriefDescription(categoryName, appResponders) 
            title += self.briefText(totalInCategory, briefDesc)
        # Lose trailing comma
        return title[:-1]
    def getMachineTitle(self, app, appResponders):
        values = []
        for categoryName in self.getCategoryNames(appResponders):
            countStr = str(self.getCategoryCount(categoryName, appResponders))
            briefDesc = self.getBriefDescription(categoryName, appResponders)
            values.append(briefDesc + "=" + countStr)
        return string.join(values, ',')
    def getTotalString(self, appResponders, method):
        total = 0
        for resp in appResponders:
            total += method(resp)
        return str(total)
    def getCategoryCount(self, categoryName, appResponders):
        total = 0
        for resp in appResponders:
            if resp.categories.has_key(categoryName):
                total += len(resp.categories[categoryName].allTests)
        return total
    def getBriefDescription(self, categoryName, appResponders):
        for resp in appResponders:
            if resp.categories.has_key(categoryName):
                return resp.categories[categoryName].briefDescription
    def getVersionString(self, versions):
        if len(versions) > 0:
            return " " + string.join(versions, ".")
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
        totalValues = seqdict()
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
                recipient = file.readline().strip()
                if recipient:
                    app.addConfigEntry("collection", recipient, "batch_recipients")
                catValues = plugins.commasplit(file.readline().strip())
                try:
                    for value in catValues:
                        catName, count = value.split("=")
                        if not totalValues.has_key(catName):
                            totalValues[catName] = 0
                        totalValues[catName] += int(count)
                except ValueError:
                    print "WARNING : found truncated or old format batch report (" + filename + ") - could not parse result correctly"
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
        for value in totalValues.values():
            total += value
        title += str(total) + " tests ran"
        if len(totalValues.keys()) == 1:
            return title + ", all " + totalValues.keys()[0]
        title += " :"
        for catName, count in totalValues.items():
            title += self.mailSender.briefText(count, catName)
        # Lose trailing comma
        return title[:-1]
    def extractHeader(self, body, mailFile):
        firstSep = body.find(os.linesep) + 1
        header = body[0:firstSep]
        mailFile.write(header)
        return header, body[firstSep:]
    def extractSection(self, sectionHeader, body):
        headerLoc = body.find(sectionHeader)
        if headerLoc == -1:
            return body.strip(), ""
        nextLine = body.find(os.linesep, headerLoc) + 1
        if body[nextLine] == "-":
            nextLine = body.find(os.linesep, nextLine) + 1
        section = body[0:headerLoc].strip()
        newBody = body[nextLine:].strip()
        return section, newBody
    def writeBody(self, mailFile, bodies):
        if len(bodies) == 1:
            return mailFile.write(bodies[0])

        parsedBodies = [ self.extractHeader(body, mailFile) for body in bodies ]
        mailFile.write(os.linesep)

        sectionMap = {}
        prevSectionHeader = ""
        for sectionHeader in sectionHeaders:
            parsedSections = []
            newParsedBodies = []
            for header, body in parsedBodies:
                section, newBody = self.extractSection(sectionHeader, body)
                if len(newBody) != 0:
                    newParsedBodies.append((header, newBody))
                if len(section) != 0:
                    parsedSections.append((header, section))

            self.writeSection(mailFile, prevSectionHeader, parsedSections)
            parsedBodies = newParsedBodies
            prevSectionHeader = sectionHeader
        self.writeSection(mailFile, prevSectionHeader, parsedBodies)
    def writeSection(self, mailFile, sectionHeader, parsedSections):
        if len(sectionHeader) == 0 or len(parsedSections) == 0:
            return
        mailFile.write(sectionHeader + " follows..." + os.linesep)
        detailSection = sectionHeader.find("Details") != -1
        if not detailSection or len(parsedSections) == 1: 
            mailFile.write("=================================================================================" + os.linesep)
        for header, section in parsedSections:
            if len(parsedSections) > 1:
                if detailSection:
                    mailFile.write("=================================================================================" + os.linesep)
                mailFile.write(header + os.linesep)
            mailFile.write(section + os.linesep + os.linesep)
