#!/usr/local/bin/python

import os
import sys
import time
import shutil
import datetime
import logging
import re
import tarfile
import stat
from texttestlib.default.batch import testoverview
from texttestlib import plugins
from .summarypages import GenerateSummaryPage, GenerateGraphs  # only so they become package level entities
from collections import OrderedDict
from .batchutils import getBatchRunName, BatchVersionFilter, parseFileName, convertToUrl
import subprocess
from glob import glob


class BatchCategory(plugins.Filter):
    def __init__(self, state):
        self.name = state.category
        self.briefDescription, self.longDescription = state.categoryDescriptions.get(self.name, (self.name, self.name))
        self.setsFailureCode = state.getExitCode()
        self.tests = {}
        self.testSuites = []

    def addTest(self, test):
        self.tests[test.getRelPath()] = test

    def getTestLine(self, test):
        postText = test.state.getTypeBreakdown()[1]
        if len(postText) > 0:
            postText = " : " + postText
            return test.getIndent() + "- " + test.paddedRepr() + postText + "\n"
        return test.getIndent() + "- " + repr(test) + postText + "\n"

    def size(self):
        return len(self.tests)

    def acceptsTestCase(self, test):
        return test.getRelPath() in self.tests

    def acceptsTestSuiteContents(self, suite):
        return not suite.isEmpty()

    def describeBrief(self, app):
        if self.size() > 0:
            filters = [self]
            suite = app.createExtraTestSuite(filters)
            self.testSuites.append(suite)
            return "The following tests " + self.longDescription + " : \n" + \
                   self.getTestLines(suite) + "\n"

    def getTestLines(self, test):
        if test.classId() == "test-case":
            realTest = self.tests[test.getRelPath()]
            return self.getTestLine(realTest)
        else:
            lines = test.getIndent() + "In " + repr(test) + ":\n"
            for subtest in test.testcases:
                lines += self.getTestLines(subtest)
            return lines

    def getAllTests(self):
        allTests = []
        for suite in self.testSuites:
            for test in suite.testCaseList():
                allTests.append(self.tests[test.getRelPath()])
        return allTests

    def describeFull(self):
        fullDescriptionString = self.getFullDescription()
        if fullDescriptionString:
            return "\nDetailed information for the tests that " + self.longDescription + " follows...\n" + fullDescriptionString
        else:
            return ""

    def getFreeTextData(self):
        data = OrderedDict()
        for test in self.getAllTests():
            freeText = test.state.freeText
            if freeText:
                if freeText not in data:
                    data[freeText] = []
                data[freeText].append(test)
        return list(data.items())

    def testOutput(self, test):
        return repr(test) + " (under " + test.getRelPath() + ")"

    def getFullDescription(self):
        fullText = ""
        for freeText, tests in self.getFreeTextData():
            fullText += "--------------------------------------------------------" + "\n"
            if len(tests) == 1:
                test = tests[0]
                fullText += "TEST " + repr(test.state) + " " + self.testOutput(test) + "\n"
            else:
                fullText += str(len(tests)) + " TESTS " + repr(tests[0].state) + "\n"
            fullText += freeText
            if not freeText.endswith("\n"):
                fullText += "\n"
            if len(tests) > 1:
                fullText += "\n"
                for test in tests:
                    fullText += "-- " + self.testOutput(test) + "\n"
        return fullText


class BatchApplicationData:
    def __init__(self, suite):
        self.suite = suite
        self.categories = {}
        self.errorCategories = []
        self.failureCategories = []
        self.successCategories = []

    def storeCategory(self, test):
        category = test.state.category
        if category not in self.categories:
            batchCategory = BatchCategory(test.state)
            if not test.state.hasResults():
                self.errorCategories.append(batchCategory)
            elif test.state.hasSucceeded():
                self.successCategories.append(batchCategory)
            else:
                self.failureCategories.append(batchCategory)
            self.categories[category] = batchCategory
        self.categories[category].addTest(test)

    def failureCount(self):
        return self.totalTests(self.failCategories())

    def successCount(self):
        return self.totalTests(self.successCategories)

    def failCategories(self):
        return self.errorCategories + self.failureCategories

    def triggersExitCode(self):
        return any((c.setsFailureCode and c.size() for c in self.failCategories()))

    def allCategories(self):
        return self.failCategories() + self.successCategories

    def testCount(self):
        return self.totalTests(self.allCategories())

    def totalTests(self, categoryList):
        count = 0
        for category in categoryList:
            count += category.size()
        return count

    def getFailuresBrief(self):
        contents = ""
        for category in self.failCategories():
            contents += category.describeBrief(self.suite.app)
        return contents

    def getSuccessBrief(self):
        contents = ""
        for category in self.successCategories:
            contents += category.describeBrief(self.suite.app)
        return contents

    def getDetails(self):
        contents = ""
        for category in self.allCategories():
            contents += category.describeFull()
        return contents


class EmailResponder(plugins.Responder):
    def __init__(self, optionMap, *args):
        plugins.Responder.__init__(self)
        self.runId = getBatchRunName(optionMap)
        self.batchAppData = OrderedDict()
        self.allApps = OrderedDict()

    def notifyComplete(self, test):
        if test.app.emailEnabled():
            if test.app not in self.batchAppData:
                self.addApplication(test)
            self.batchAppData[test.app].storeCategory(test)

    def getRootSuite(self, test):
        if test.parent:
            return self.getRootSuite(test.parent)
        else:
            return test

    def addApplication(self, test):
        rootSuite = self.getRootSuite(test)
        app = test.app
        self.batchAppData[app] = BatchApplicationData(rootSuite)
        self.allApps.setdefault(app.name, []).append(app)

    def notifyAllComplete(self):
        mailSender = MailSender(self.runId)
        for appList in list(self.allApps.values()):
            batchDataList = list(map(self.batchAppData.get, appList))
            mailSender.send(batchDataList)


sectionHeaders = ["Summary of all Unsuccessful tests",
                  "Details of all Unsuccessful tests", "Summary of all Successful tests"]


class MailSender:
    def __init__(self, runId=""):
        self.runId = runId
        self.diag = logging.getLogger("Mail Sender")

    def send(self, batchDataList):
        app = batchDataList[0].suite.app
        mailContents = self.makeContents(batchDataList)
        self.sendOrStoreMail(app, mailContents, self.useCollection(app), not self.hasExitCodeErrors(batchDataList))

    def makeContents(self, batchDataList, headerSection=True):
        app = batchDataList[0].suite.app
        mailTitle = self.getMailTitle(app, batchDataList)
        mailContents = self.createMailHeaderSection(
            mailTitle, app, batchDataList) if headerSection else mailTitle + "\n"
        if len(batchDataList) > 1:
            for batchData in batchDataList:
                mailContents += self.getMailTitle(app, [batchData]) + "\n"
            mailContents += "\n"
        if not self.isAllSuccess(batchDataList):
            mailContents += self.performForAll(app, batchDataList,
                                               BatchApplicationData.getFailuresBrief, sectionHeaders[0])
            mailContents += self.performForAll(app, batchDataList, BatchApplicationData.getDetails, sectionHeaders[1])
        if not self.isAllFailure(batchDataList):
            mailContents += self.performForAll(app, batchDataList,
                                               BatchApplicationData.getSuccessBrief, sectionHeaders[2])
        return mailContents

    def performForAll(self, app, batchDataList, method, headline):
        contents = headline + " follows...\n" + \
            "---------------------------------------------------------------------------------" + "\n"
        for resp in batchDataList:
            if len(batchDataList) > 1:
                if headline.find("Details") != -1 and not resp is batchDataList[0]:
                    contents += "---------------------------------------------------------------------------------" + "\n"
                contents += self.getMailTitle(app, [resp]) + "\n\n"
            contents += method(resp) + "\n"
        return contents

    def storeMail(self, app, mailContents):
        localFileName = "batchreport." + app.name + app.versionSuffix()
        collFile = os.path.join(app.writeDirectory, localFileName)
        self.diag.info("Adding mail report contents to " + collFile)

        with plugins.openForWrite(collFile) as collateFile:
            collateFile.write(mailContents)
            collateFile.close()

    def sendOrStoreMail(self, app, mailContents, useCollection=False, isAllSuccess=False):
        plugins.log.info("Creating batch report for application " + app.fullName() + " ...")
        if useCollection:
            self.storeMail(app, mailContents)
            plugins.log.info("File written.")
        else:
            if not isAllSuccess or app.getBatchConfigValue("batch_mail_on_failure_only") != "true":
                errorMessage = self.sendMail(app, mailContents)
                if errorMessage:
                    plugins.log.info("FAILED. Details follow:\n" + errorMessage.strip())
                else:
                    plugins.log.info("done.")
            else:
                plugins.log.info("not sent: all tests succeeded or had known bugs.")

    def exceptionOutput(self):
        exctype, value = sys.exc_info()[:2]
        from traceback import format_exception_only
        return "".join(format_exception_only(exctype, value))

    def sendMail(self, app, mailContents):
        smtpServer = app.getConfigValue("smtp_server")
        smtpUsername = app.getConfigValue("smtp_server_username")
        smtpPassword = app.getConfigValue("smtp_server_password")
        fromAddress = app.getBatchConfigValue("batch_sender")
        recipients = app.getBatchConfigValue("batch_recipients")

        if not recipients:
            return self.getNoRecipientsMessage(app)

        toAddresses = plugins.commasplit(recipients)

        import smtplib
        smtp = smtplib.SMTP()
        try:
            smtp.connect(smtpServer)
        except Exception:  # Can't use SMTPException, because this raises socket.error usually
            return "Could not connect to SMTP server at " + smtpServer + "\n" + self.exceptionOutput()
        if smtpUsername:
            try:
                smtp.login(smtpUsername, smtpPassword)
            except smtplib.SMTPException:
                return "Failed to login as '" + smtpUsername + "' to SMTP server at " + smtpServer + \
                    "\n" + self.exceptionOutput()
        try:
            smtp.sendmail(fromAddress, toAddresses, mailContents)
        except smtplib.SMTPException:
            return "Mail could not be sent\n" + self.exceptionOutput()
        smtp.quit()

    def getNoRecipientsMessage(self, app):
        message = "Attempted to send mail, but batch_recipients is empty."
        if app.getBatchConfigValue("batch_use_collection") == "true":
            message += "\nHaving batch_use_collection set to true, but no batch_recipients indicates an erroneous configuration."
        return message

    def createMailHeaderSection(self, title, app, batchDataList):
        if self.useCollection(app):
            return self.getMachineTitle(batchDataList) + "\n" + self.runId + "\n" + \
                title + "\n\n"  # blank line separating headers from body
        else:
            return self.createMailHeaderForSend(self.runId, title, app)

    def createMailHeaderForSend(self, runId, title, app):
        fromAddress = app.getBatchConfigValue("batch_sender")
        toAddress = app.getBatchConfigValue("batch_recipients")
        return "From: " + fromAddress + "\nTo: " + toAddress + "\n" + \
               "Subject: " + runId + " " + title + "\n\n"

    def useCollection(self, app):
        return app.getBatchConfigValue("batch_use_collection") == "true"

    def getMailHeader(self, app, batchDataList):
        versions = self.findCommonVersions(app, batchDataList)
        return app.fullName() + self.getVersionString(versions) + " : "

    def getCategoryNames(self, batchDataList):
        names = []
        for resp in batchDataList:
            for cat in resp.errorCategories:
                if not cat.name in names:
                    names.append(cat.name)
        for resp in batchDataList:
            for cat in resp.failureCategories:
                if not cat.name in names:
                    names.append(cat.name)
        for resp in batchDataList:
            for cat in resp.successCategories:
                if not cat.name in names:
                    names.append(cat.name)
        return names

    def hasExitCodeErrors(self, batchDataList):
        return any((bd.triggersExitCode() for bd in batchDataList))

    def isAllSuccess(self, batchDataList):
        return self.getTotalString(batchDataList, BatchApplicationData.failureCount) == "0"

    def isAllFailure(self, batchDataList):
        return self.getTotalString(batchDataList, BatchApplicationData.successCount) == "0"

    def getMailTitle(self, app, batchDataList):
        title = self.getMailHeader(app, batchDataList)
        title += self.getTotalString(batchDataList, BatchApplicationData.testCount) + " tests"
        if self.isAllSuccess(batchDataList):
            return title + ", all successful"
        title += " :"
        for categoryName in self.getCategoryNames(batchDataList):
            totalInCategory = self.getCategoryCount(categoryName, batchDataList)
            briefDesc = self.getBriefDescription(categoryName, batchDataList)
            title += self.briefText(totalInCategory, briefDesc)
        # Lose trailing comma
        return title[:-1]

    def getMachineTitle(self, batchDataList):
        values = []
        for categoryName in self.getCategoryNames(batchDataList):
            countStr = str(self.getCategoryCount(categoryName, batchDataList))
            briefDesc = self.getBriefDescription(categoryName, batchDataList)
            values.append(briefDesc + "=" + countStr)
        return ",".join(values)

    def getTotalString(self, batchDataList, method):
        total = 0
        for resp in batchDataList:
            total += method(resp)
        return str(total)

    def getCategoryCount(self, categoryName, batchDataList):
        total = 0
        for resp in batchDataList:
            if categoryName in resp.categories:
                total += resp.categories[categoryName].size()
        return total

    def getBriefDescription(self, categoryName, batchDataList):
        for resp in batchDataList:
            if categoryName in resp.categories:
                return resp.categories[categoryName].briefDescription

    def getVersionString(self, versions):
        if len(versions) > 0:
            return " " + ".".join(versions)
        else:
            return ""

    def briefText(self, count, description):
        if count == 0 or description == "succeeded":
            return ""
        else:
            return " " + str(count) + " " + description + ","

    def findCommonVersions(self, app, batchDataList):
        if len(batchDataList) == 0:
            return app.versions
        commonVersions = []
        otherBatchData = batchDataList[1:]
        for trialVersion in batchDataList[0].suite.app.versions:
            if self.allContain(otherBatchData, trialVersion):
                commonVersions.append(trialVersion)
        return commonVersions

    def allContain(self, otherBatchData, trialVersion):
        for batchData in otherBatchData:
            if not trialVersion in batchData.suite.app.versions:
                return False
        return True


def findExtraVersionParent(app, allApps):
    for parentApp in allApps:
        if app in parentApp.extras:
            return parentApp
    return app


def getVersionName(app, allApps):
    parent = findExtraVersionParent(app, allApps)
    parentVersion = parent.getFullVersion()
    fullVersion = app.getFullVersion()
    if parentVersion:
        return fullVersion
    elif fullVersion:
        return "default." + fullVersion
    else:
        return "default"


def getBatchRepository(suite):
    repo = suite.app.getBatchConfigValue("batch_result_repository", envMapping=suite.environment)
    return os.path.expanduser(repo)


def dateInSeconds(val):
    return time.mktime(time.strptime(val, "%d%b%Y"))


def matchesApp(dir, app):
    suffix = app.versionSuffix()
    return dir.startswith(app.name + suffix) or dir.startswith(app.getBatchSession() + suffix)


def getPreviousWriteDirsUnder(rootDir, app):
    dirs = []
    for dir in sorted(os.listdir(rootDir)):
        fullDir = os.path.join(rootDir, dir)
        if os.path.isdir(fullDir) and matchesApp(dir, app):
            dirs.append(fullDir)
    return dirs


def getPreviousWriteDirs(app):
    rootDir = app.getPreviousWriteDirInfo()
    return getPreviousWriteDirsUnder(rootDir, app) if os.path.isdir(rootDir) else []


def writeSuccessLine(f, runPostfix, state):
    f.write(runPostfix)
    if state.briefText:
        f.write(" " + state.briefText)
    f.write(" " + ", ".join(state.executionHosts) + "\n")


# Allow saving results to a historical repository
class SaveState(plugins.Responder):
    def __init__(self, optionMap, allApps):
        plugins.Responder.__init__(self)
        self.runPostfix = self.getRunPostfix(optionMap)
        self.failureFileName = "teststate_" + self.runPostfix
        self.successFileName = "succeeded_runs"
        self.repositories = {}
        self.allApps = allApps
        self.diag = logging.getLogger("Save Repository")
        self.checkRunNameValid()

    def isBatchDate(self, dateStr):
        return re.match("^[0-9]{2}[A-Za-z]{3}[0-9]{4}$", dateStr)

    def getRunPostfix(self, optionMap):
        # include the date and the name, if any. Date is used for archiving, name for display
        runName = getBatchRunName(optionMap)
        parts = []
        if not self.isBatchDate(runName):
            parts.append(plugins.startTimeString("%d%b%Y"))
        parts.append(runName)
        return "_".join(parts)

    def notifyComplete(self, test):
        if test.state.isComplete():  # might look weird but this notification also comes in scripts, e.g collecting
            test.saveState()
            if test.app in self.repositories:
                self.diag.info("Saving " + repr(test) + " to repository")
                self.saveToRepository(test)
            else:
                self.diag.info("No repositories for " + repr(test.app) + " in " + repr(self.repositories))

    def saveToRepository(self, test):
        testRepository = self.repositories[test.app]
        targetDir = os.path.join(testRepository, test.app.name, getVersionName(test.app, self.allApps),
                                 test.getRelPath())
        try:
            plugins.ensureDirectoryExists(targetDir)
        except EnvironmentError:
            plugins.printWarning("Could not create directory at " + targetDir)
        # Need to store teststate files for succeeded tests if we have resource pages
        if test.state.hasSucceeded() and len(test.app.getBatchConfigValue("historical_report_resources")) == 0:
            targetFile = os.path.join(targetDir, self.successFileName)
            with open(targetFile, "a") as f:
                writeSuccessLine(f, self.runPostfix, test.state)
        else:
            targetFile = os.path.join(targetDir, self.failureFileName)
            if os.path.isfile(targetFile):
                plugins.printWarning("File already exists at " + targetFile + " - not overwriting!")
            else:
                try:
                    shutil.copyfile(test.getStateFile(), targetFile)
                except EnvironmentError:
                    plugins.printWarning("Could not write file at " + targetFile)

    def addSuite(self, suite):
        testStateRepository = getBatchRepository(suite)
        self.diag.info("Test state repository is " + repr(testStateRepository))
        if testStateRepository:
            self.repositories[suite.app] = os.path.abspath(testStateRepository)
            self.registerRunName(testStateRepository, suite.app)

    def makeInitialRunFile(self, app, runFile):
        plugins.ensureDirExistsForFile(runFile)
        with open(runFile, "w") as f:
            for envVar in ["JENKINS_URL", "JOB_NAME", "BUILD_NUMBER"]:
                if envVar in os.environ:
                    f.write(envVar + "=" + os.getenv(envVar) + "\n")
                else:
                    break

            f.write(repr(app) + "\n")

    def runAlreadyExists(self, runFile, app):
        text = repr(app)
        with open(runFile) as f:
            for line in f:
                if line.strip() == text:
                    return True
        return False

    def getRunFileName(self, repository):
        return os.path.join(repository, "run_names", self.runPostfix)

    def registerRunName(self, repository, app):
        runFile = self.getRunFileName(repository)
        if os.path.isfile(runFile):
            with open(runFile, "a") as f:
                f.write(repr(app) + "\n")
        else:
            try:
                self.makeInitialRunFile(app, runFile)
            except EnvironmentError:
                plugins.printWarning("Could not write run file at " + runFile)

    def checkRunNameValid(self):
        for app in self.allApps:
            repository = os.path.expanduser(app.getBatchConfigValue("batch_result_repository"))
            runFile = self.getRunFileName(repository)
            if os.path.isfile(runFile) and self.runAlreadyExists(runFile, app):
                raise plugins.TextTestError("ERROR: Cannot run batch tests with run name '" + self.runPostfix + "', name has already been used for a different run\n" +
                                            "See file at " + runFile + ", which contains the entry '" + repr(app) + "'")


class MigrateBatchRepository(plugins.Action):
    def __init__(self):
        self.successFileName = "succeeded_runs"

    def migrateFile(self, path):
        state = testoverview.GenerateWebPages.readState(path)
        if state.hasSucceeded():
            dirname, fn = os.path.split(path)
            runTag = fn.replace("teststate_", "")
            successFile = os.path.join(dirname, self.successFileName)
            with open(successFile, "a") as f:
                writeSuccessLine(f, runTag, state)
            os.remove(path)

    def migrate(self, repository):
        plugins.log.info("Migrating repository at " + repository)
        for root, _, files in os.walk(repository):
            for f in files:
                if f.startswith("teststate_"):
                    path = os.path.join(root, f)
                    self.migrateFile(path)

    def setUpSuite(self, suite):
        if suite.parent is None:
            resources = suite.app.getBatchConfigValue("historical_report_resources")
            if len(resources) > 0:
                raise plugins.TextTestError("Cannot migrate repository: historical_report_sources set to '" +
                                            ", ".join(resources) + "' - these require the full format")
            repository = getBatchRepository(suite)
            if not os.path.isdir(repository):
                raise plugins.TextTestError("Batch result repository " + repository + " does not exist")
            self.migrate(repository)


class ArchiveScript(plugins.ScriptWithArgs):
    def __init__(self, argDict):
        self.descriptors = []
        self.beforeDate = self.parseDate(argDict, "before")
        self.afterDate = self.parseDate(argDict, "after")
        self.descriptors.sort()
        self.repository = None
        if len(argDict) == 0:
            raise plugins.TextTestError("Cannot archive the entire repository - give cutoff dates or run names!")

    def parseDate(self, dict, key):
        return self.extractArg(dict, key, isDate=True)

    def extractArg(self, dict, key, isDate=False):
        if not key in dict:
            return
        val = dict[key]
        if isDate:
            self.descriptors.append("dated " + key + " " + val)
            return self.dateInSeconds(val)
        else:
            self.descriptors.append("with " + key + " " + val)
            return val

    def getDateFormat(self, val):
        return "%b%Y" if len(val) == 7 else "%d%b%Y"

    def dateInSeconds(self, val):
        dateFormat = self.getDateFormat(val)
        return time.mktime(time.strptime(val, dateFormat))

    def getShortDescriptorText(self):
        shortDescriptors = [d.split(" ", 1)[-1] for d in self.descriptors]
        return "_".join(shortDescriptors).replace(" ", "_")

    def makeTarArchive(self, suite, repository):
        historyDir = suite.app.name + "_history"
        fullHistoryDir = os.path.join(repository, historyDir)
        if os.path.isdir(fullHistoryDir):
            tarFileName = historyDir + "_" + self.getShortDescriptorText() + ".tar.gz"
            plugins.log.info("Archiving completed for " + self.repository + ", created tarfile at " + tarFileName)
            subprocess.call(["tar", "cfz", tarFileName, historyDir], cwd=repository)
            plugins.rmtree(fullHistoryDir)

    def archiveFiles(self, suite):
        self.archiveFilesUnder(self.repository, suite.app)

    def archiveFilesUnder(self, repository, app, *args):
        count = 0
        dirList = os.listdir(repository)
        dirList.sort()
        for file in dirList:
            fullPath = os.path.join(repository, file)
            if self.shouldArchive(file, *args):
                if self.archiveFile(fullPath, app, *args):
                    count += 1
            elif os.path.isdir(fullPath):
                self.archiveFilesUnder(fullPath, app, *args)
        if count > 0:
            plugins.log.info("Archived " + str(count) + " files " + ", ".join(self.descriptors) +
                             " under " + repository.replace(self.repository + os.sep, ""))

    def setUpSuite(self, suite):
        if suite.parent is None:
            repository = self.getRepository(suite)
            self.repository = os.path.join(repository, suite.app.name)
            if not os.path.isdir(self.repository):
                raise plugins.TextTestError("Batch result repository " + self.repository + " does not exist")
            self.archiveFiles(suite)
            if os.name == "posix":
                self.makeTarArchive(suite, repository)

    def archiveFile(self, fullPath, app, *args):
        targetPath = self.getTargetPath(fullPath, app.name)
        plugins.ensureDirExistsForFile(targetPath)
        try:
            os.rename(fullPath, targetPath)
            return True
        except EnvironmentError as e:
            plugins.log.info("Rename failed: " + fullPath + " " + targetPath)
            plugins.log.info("Error was " + str(e))
            return False

    def getTargetPath(self, fullPath, appName):
        parts = fullPath.split(os.sep)
        parts.reverse()
        appIndex = parts.index(appName)
        parts[appIndex] = appName + "_history"
        parts.reverse()
        return os.sep.join(parts)

    def shouldArchiveWithDate(self, date):
        if self.beforeDate and date >= self.beforeDate:
            return False
        if self.afterDate and date <= self.afterDate:
            return False
        return True


class ArchiveRepository(ArchiveScript):
    scriptDoc = "Archive parts of the batch result repository to a history directory"

    def __init__(self, args):
        argDict = self.parseArguments(args, ["before", "after", "weekday_pages_before", "name"])
        ArchiveScript.__init__(self, argDict)
        self.name = self.extractArg(argDict, "name")
        self.weekdayBeforeDate = self.parseDate(argDict, "weekday_pages_before")

    def getRepository(self, suite):
        return getBatchRepository(suite)

    def getWeekDays(self, suite):
        weekdayNameLists = list(suite.getConfigValue("historical_report_subpage_weekdays").values())
        weekdayNames = sum(weekdayNameLists, [])
        return list(map(plugins.weekdays.index, weekdayNames))

    def archiveFiles(self, suite):
        weekdays = self.getWeekDays(suite)
        runDir = os.path.join(os.path.dirname(self.repository), "run_names")
        if os.path.isdir(runDir):
            self.archiveFilesUnder(runDir, suite.app, weekdays, True)
        self.archiveVersionDirsUnder(self.repository, suite.app, weekdays, False)

    def archiveVersionDirsUnder(self, repository, app, *args):
        appVersions = set(app.versions)
        for directory in sorted(os.listdir(repository)):
            dirversions = set(directory.split("."))
            fullPath = os.path.join(repository, directory)
            if appVersions.issubset(dirversions) and os.path.isdir(fullPath):
                self.archiveFilesUnder(fullPath, app, *args)

    def archiveRunFile(self, fullPath, app):
        appParts = set(repr(app).split("."))
        envVars, otherAppLines = [], []
        archived = False
        with open(fullPath) as f:
            for line in f:
                if "=" in line:
                    envVars.append(line)
                else:
                    lineParts = set(line.strip().split("."))
                    if appParts.issubset(lineParts):
                        archived = True
                    else:
                        otherAppLines.append(line)
        if archived:
            if otherAppLines:
                with open(fullPath, "w") as f:
                    for line in envVars + otherAppLines:
                        f.write(line)
            else:
                os.remove(fullPath)
        return archived

    def archiveFile(self, fullPath, app, weekdays, isRunFile):
        if isRunFile:
            return self.archiveRunFile(fullPath, app)
        elif os.path.basename(fullPath).startswith("teststate"):
            return ArchiveScript.archiveFile(self, fullPath, app)
        linesToKeep = []
        archived = False
        with open(fullPath) as readFile:
            for line in readFile:
                tag = line.strip().split()[0]
                if self.shouldArchiveGivenTag(tag, weekdays):
                    archived = True
                else:
                    linesToKeep.append(line)

        if archived:
            with open(fullPath, "w") as writeFile:
                for line in linesToKeep:
                    writeFile.write(line)
        return archived

    def shouldArchiveGivenTag(self, tag, weekdays):
        parts = tag.split("_")
        dateStr = parts[0]
        if self.name:
            runName = dateStr if len(parts) == 1 else "_".join(parts[1:])
            if runName != self.name:
                return False
        return self.shouldArchiveGivenDateString(dateStr, weekdays)

    def shouldArchive(self, file, weekdays, isRunFile):
        if isRunFile:
            return self.shouldArchiveGivenTag(file, weekdays)

        if file.startswith("succeeded_"):
            return True
        if not file.startswith("teststate"):
            return False

        return self.shouldArchiveGivenTag(file.replace("teststate_", ""), weekdays)

    def shouldArchiveGivenDateString(self, dateStr, weekdays):
        timeStruct = time.strptime(dateStr, self.getDateFormat(dateStr))
        date = time.mktime(timeStruct)
        return self.shouldArchiveWithDate(date) and (not self.weekdayBeforeDate or date < self.weekdayBeforeDate or timeStruct.tm_wday not in weekdays)


class ArchiveHTML(ArchiveScript):
    scriptDoc = "Archive parts of the historical report location to a history directory"

    def __init__(self, args):
        argDict = self.parseArguments(args, ["before", "after"])
        ArchiveScript.__init__(self, argDict)

    def getRepository(self, suite):
        return os.path.expanduser(suite.app.getBatchConfigValue("historical_report_location"))

    def parseDateFromFile(self, file):
        for part in reversed(file[:-5].split("_")):
            if len(part) in [7, 9]:
                try:
                    return self.dateInSeconds(part)
                except ValueError:
                    pass

    def shouldArchive(self, file):
        if not file.endswith(".html"):
            return False
        date = self.parseDateFromFile(file)
        return self.shouldArchiveWithDate(date) if date else False


class ArchiveExtractor:
    def __init__(self, dateStr):
        self.dateStr = dateStr
        self.repositories = []

    def extract(self, suite):
        repository = getBatchRepository(suite)
        archives = self.getArchives(suite)
        for archive in archives:
            self.extractUnder(archive, repository)
        self.repositories.append(os.path.join(repository, suite.app.name + "_history"))

    def getArchives(self, suite):
        repository = getBatchRepository(suite)
        dirList = os.listdir(repository)
        return [os.path.join(repository, f) for f in dirList if f.endswith(".tar.gz") and self.shouldOpen(f)]

    def shouldOpen(self, tarFileName):
        beforePos = tarFileName.rfind("before_")
        if beforePos == -1:
            return False

        startPos = beforePos + len("before_")
        dateStr = tarFileName[startPos:startPos + 9]  # %d%b%Y dates are always of length 9
        return dateInSeconds(self.dateStr) <= dateInSeconds(dateStr)

    def extractUnder(self, archivedFile, targetPath):
        tar = tarfile.open(archivedFile)
        tar.extractall(targetPath, members=self.findFiles(tar))
        tar.close()

    def findFiles(self, members):
        for tarinfo in members:
            if self.shouldExtract(os.path.split(tarinfo.name)[1]):
                yield tarinfo

    def shouldExtract(self, fileName):
        if not fileName.startswith("teststate"):
            return False
        dateStr = fileName.split("_")[1]
        return dateInSeconds(self.dateStr) <= dateInSeconds(dateStr)

    def cleanAllExtracted(self):
        for repository in self.repositories:
            if os.path.isdir(repository):
                plugins.rmtree(repository)


class WebPageResponder(plugins.Responder):
    def __init__(self, optionMap, allApps):
        plugins.Responder.__init__(self)
        self.archiveExtractor = ArchiveExtractor(optionMap.get(
            "collarchive")) if optionMap.get("collarchive") is not None else None
        self.diag = logging.getLogger("GenerateWebPages")
        self.suitesToGenerate = []
        self.archiveUnused = "manualarchive" not in optionMap
        self.descriptionInfo = {}
        self.summaryGenerator = GenerateSummaryPage()

    def notifyAdd(self, test, *args, **kw):
        self.descriptionInfo.setdefault(test.app, {}).setdefault(
            test.getRelPath().replace(os.sep, " "), test.description)

    def addSuites(self, suites):
        # Don't blanket remove rejected apps automatically when collecting
        self.extraApps = []
        for suite in suites:
            if suite.app in self.extraApps:
                continue
            if self.summaryGenerator:
                self.summaryGenerator.setUpApplication(suite.app)
            try:
                batchFilter = BatchVersionFilter(suite.app.getBatchSession())
                batchFilter.verifyVersions(suite.app)
                self.suitesToGenerate.append(suite)
                self.extraApps += suite.app.extras
                if self.archiveExtractor is not None:
                    self.extractFromArchive()
            except (plugins.TextTestError, plugins.TextTestWarning) as e:
                plugins.log.info("Not generating web page for " + suite.app.description() + " : " + str(e))

    def notifyAllRead(self, *args):
        # Sort the suites to generate by the number of tests they contain
        # This should ensure we get small test suites' results first and anything that is slow to generate
        # won't slow down other stuff
        self.suitesToGenerate.sort(key=lambda s: s.size())

    def notifyAllComplete(self):
        appInfo = self.getAppRepositoryInfo()
        plugins.log.info("Generating web pages...")
        for pageTitle, pageInfo in list(appInfo.items()):
            plugins.log.info("Generating page for " + pageTitle)
            if len(pageInfo) == 1:
                self.generatePagePerApp(pageTitle, pageInfo)
            else:
                self.generateCommonPage(pageTitle, pageInfo)

            if self.summaryGenerator:
                appsUsed = [app for app, _, _ in pageInfo]
                self.summaryGenerator.generateForApps(appsUsed)
        if len(appInfo) == 0 and self.summaryGenerator:
            # Describe errors, if any
            self.summaryGenerator.finalise()
        plugins.log.info("Completed web page generation.")
        if self.archiveExtractor is not None:
            self.archiveExtractor.cleanAllExtracted()

    def extractFromArchive(self):
        for suite in self.suitesToGenerate:
            self.archiveExtractor.extract(suite)

    def generatePagePerApp(self, pageTitle, pageInfo):
        for app, repositories, extraApps in pageInfo:
            pageTopDir = os.path.expanduser(app.getBatchConfigValue("historical_report_location"))
            pageDir = os.path.join(pageTopDir, app.name)
            self.copyJavaScript(pageTopDir, pageDir)
            extraVersions = self.getExtraVersions(app, extraApps)
            self.diag.info("Found extra versions " + repr(extraVersions))
            relevantSubDirs = self.findRelevantSubdirectories(repositories, app, extraVersions)
            version = getVersionName(app, self.getAppsToGenerate())
            pageSubTitles = self.makePageSubTitles([app])
            self.makeAndGenerate(relevantSubDirs, self.getConfigValueMethod(app), pageDir, pageTitle, pageSubTitles,
                                 version, extraVersions, self.getDescriptionInfo([app]))

    def getConfigValueMethod(self, app):
        def getConfigValue(key, subKey=app.getBatchSession(), allSubKeys=False):
            if allSubKeys:
                return app.getConfigValue(key)
            else:
                return app.getCompositeConfigValue(key, subKey)
        return getConfigValue

    def makePageSubTitles(self, apps):
        cmdLine = self.makeCommandLine(apps)
        startText = "To start TextTest for these tests, run:"
        subtitles = [(startText, cmdLine)]
        if len(apps) == 1:
            reconnectCmdLine = self.makeReconnectCommandLine(apps[0], cmdLine)
            if reconnectCmdLine:
                reconnectText = "To reconnect the TextTest GUI to these results, run:"
                subtitles.insert(0, (reconnectText, reconnectCmdLine))
        return subtitles

    def makeCommandLine(self, apps):
        cmd = os.path.basename(plugins.getTextTestProgram())
        cmd += " -a " + ",".join((app.name for app in apps))
        version = apps[0].getFullVersion()
        if version:
            cmd += " -v " + version
        checkouts = set((app.getCheckoutForDisplay() for app in apps))
        if len(checkouts) == 1:
            checkout = checkouts.pop()
            if checkout:
                cmd += " -c " + checkout
        directories = set((app.getRootDirectory() for app in apps))
        cmd += " -d " + os.pathsep.join(directories)
        return cmd

    def makeReconnectCommandLine(self, app, cmdLine):
        previousWriteDirs = getPreviousWriteDirs(app)
        if not previousWriteDirs:
            return

        return cmdLine + " -reconnect " + previousWriteDirs[0] + " -g"

    def getAppRepositoryInfo(self):
        appInfo = OrderedDict()
        for suite in self.suitesToGenerate:
            app = suite.app
            repositories = self.getRepositories(suite)
            if len(repositories) == 0:
                continue
            pageTitle = app.getBatchConfigValue("historical_report_page_name")
            extraApps = []
            for extraApp in app.extras:
                extraPageTitle = extraApp.getBatchConfigValue("historical_report_page_name")
                if extraPageTitle != pageTitle and extraPageTitle != extraApp.getDefaultPageName():
                    appInfo.setdefault(extraPageTitle, []).append((extraApp, repositories, []))
                else:
                    extraApps.append(extraApp)
            appInfo.setdefault(pageTitle, []).append((app, repositories, extraApps))
        return appInfo

    def getRepositories(self, suite):
        repositories = []
        repositoryRoot = getBatchRepository(suite)
        if repositoryRoot:
            repos = [os.path.join(repositoryRoot, suite.app.name)]
            if self.archiveExtractor is not None:
                repos.append(os.path.join(repositoryRoot, suite.app.name + "_history"))
            repositories = [repository for repository in repos if self.checkRepository(repository, suite.app)]
        return repositories

    def checkRepository(self, repository, app):
        if not os.path.isdir(repository):
            plugins.printWarning("Batch result repository " + repository +
                                 " does not exist - not creating pages for " + repr(app))
            return False
        return True

    def getAppsToGenerate(self):
        return [suite.app for suite in self.suitesToGenerate]

    def getDescriptionInfo(self, apps):
        descriptionInfo = {}
        for app in apps:
            for appToUse in [app] + app.extras:
                descriptionInfo.update(self.descriptionInfo.get(appToUse, {}))

        return descriptionInfo

    def transformToCommon(self, pageInfo):
        # We've sorted by number of tests already, but on the same page we want applications in a more predictable order
        # Sort by name again.
        pageInfo.sort(key=lambda info: info[0].name)
        allApps = [app for app, _, _ in pageInfo]
        version = getVersionName(allApps[0], self.getAppsToGenerate())
        extraVersions, relevantSubDirs = [], OrderedDict()
        for app, repositories, extraApps in pageInfo:
            extraVersions += self.getExtraVersions(app, extraApps)
            relevantSubDirs.update(self.findRelevantSubdirectories(
                repositories, app, extraVersions, self.getVersionTitle))
        getConfigValue = plugins.ResponseAggregator([self.getConfigValueMethod(app) for app in allApps])
        pageSubTitles = self.makePageSubTitles(allApps)
        descriptionInfo = self.getDescriptionInfo(allApps)
        return relevantSubDirs, getConfigValue, version, extraVersions, pageSubTitles, descriptionInfo

    def getVersionTitle(self, app, version):
        title = app.fullName()
        if len(version) > 0 and version != "default":
            title += " version " + version
        return title

    def generateCommonPage(self, pageTitle, pageInfo):
        relevantSubDirs, getConfigValue, version, extraVersions, pageSubTitles, descriptionInfo = self.transformToCommon(
            pageInfo)
        pageDir = os.path.expanduser(getConfigValue("historical_report_location"))
        self.copyJavaScript(pageDir, pageDir)
        self.makeAndGenerate(relevantSubDirs, getConfigValue, pageDir, pageTitle,
                             pageSubTitles, version, extraVersions, descriptionInfo)

    def copyJavaScript(self, pageTopDir, pageDir):
        jsDir = os.path.join(pageTopDir, "javascript")
        srcDir = os.path.join(os.path.dirname(__file__), "testoverview_javascript")
        if not os.path.isdir(srcDir): # for example when zipped, use the installation structure
            moduleParts = self.__class__.__module__.split(".")
            pathParts = moduleParts[1:] +  [ "testoverview_javascript" ] # drop texttestlib at the start, installation is under that
            srcDir = plugins.installationPath(*pathParts)
        plugins.ensureDirectoryExists(jsDir)
        plugins.ensureDirectoryExists(pageDir)
        for fn in sorted(os.listdir(srcDir)):
            targetDir = pageDir if fn.endswith(".php") else jsDir  # Server-side stuff is per application
            targetPath = os.path.join(targetDir, fn)
            try:
                shutil.copyfile(os.path.join(srcDir, fn), targetPath)
            except EnvironmentError:
                plugins.printWarning("Could not copy Javascript-related file to " + targetPath)

    def makeAndGenerate(self, subDirs, getConfigValue, pageDir, *args):
        resourceNames = getConfigValue("historical_report_resources")
        plugins.ensureDirectoryExists(pageDir)
        try:
            self.generateWebPages(subDirs, getConfigValue, pageDir, resourceNames, *args)
        except Exception:  # pragma: no cover - robustness only, shouldn't be reachable
            sys.stderr.write("Caught exception while generating web pages :\n")
            plugins.printException()

    def getWebPageGenerator(self, getConfigValue, *args):
        return testoverview.GenerateWebPages(getConfigValue, *args)

    def generateWebPages(self, subDirs, getConfigValue, *args):
        generator = self.getWebPageGenerator(getConfigValue, *args)
        subPageNames = getConfigValue("historical_report_subpages")
        generator.generate(subDirs, subPageNames, self.archiveUnused)

    def findMatchingExtraVersion(self, dirVersions, extraVersions):
        # Check all tails that this is not an extraVersion
        for pos in range(len(dirVersions)):
            versionToCheck = ".".join(dirVersions[pos:])
            if versionToCheck in extraVersions:
                return versionToCheck
        return ""

    def findRelevantSubdirectories(self, repositories, app, extraVersions, versionTitleMethod=None):
        subdirs = OrderedDict()
        for repository in repositories:
            dirlist = os.listdir(repository)
            dirlist.sort()
            appVersions = set(app.versions)
            for dir in dirlist:
                dirVersions = dir.split(".")
                if set(dirVersions).issuperset(appVersions):
                    currExtraVersion = self.findMatchingExtraVersion(dirVersions, extraVersions)
                    if currExtraVersion:
                        version = dir.replace("." + currExtraVersion, "")
                    else:
                        version = dir
                    if versionTitleMethod:
                        versionTitle = versionTitleMethod(app, version)
                    else:
                        versionTitle = version
                    fullPath = os.path.join(repository, dir)
                    self.diag.info("Found subdirectory " + dir + " with version " + versionTitle
                                   + " and extra version '" + currExtraVersion + "'")
                    subdirs.setdefault(versionTitle, []).append((currExtraVersion, fullPath))
        return subdirs

    def getExtraVersions(self, app, extraApps):
        extraVersions = []
        length = len(app.versions)
        for extraApp in extraApps:
            version = ".".join(extraApp.versions[length:])
            if not version in app.versions:
                extraVersions.append(version)
        return extraVersions


class CollectFilesResponder(plugins.Responder):
    def __init__(self, optionMap, allApps):
        plugins.Responder.__init__(self)
        self.mailSender = MailSender()
        self.runId = ""  # depends on what we pick up from collected files
        self.diag = logging.getLogger("batch collect")
        self.allApps = allApps

    def notifyAllComplete(self):
        plugins.log.info("Collecting batch files locally...")
        for app in self.allApps:
            self.collectFilesForApp(app)

    def getMailBody(self, app, fileBodies, missingVersions):
        reportLocation = app.getBatchConfigValue("historical_report_location")
        if reportLocation:
            htmlIndex, htmlBody = self.getHtmlReportLocation(app, reportLocation)
            if htmlIndex is not None:
                return "Please see detailed results at " + htmlBody + "\n\n" + \
                    "The main index page can be found at " + htmlIndex + "\n"

        return self.getBody(fileBodies, missingVersions)

    def collectFilesForApp(self, app):
        fileBodies = []
        totalValues = OrderedDict()
        compulsoryVersions = set(app.getBatchConfigValue("batch_collect_compulsory_version"))
        versionsFound = set()
        rootDir = app.getPreviousWriteDirInfo()
        if not os.path.isdir(rootDir):
            sys.stderr.write("No temporary directory found at " + rootDir + " - not collecting batch reports.\n")
            return

        for previousWriteDir in getPreviousWriteDirsUnder(rootDir, app):
            currBodies, currVersions = self.parseDirectory(previousWriteDir, app, totalValues)
            fileBodies += currBodies
            versionsFound.update(currVersions)

        if len(fileBodies) == 0:
            return

        missingVersions = compulsoryVersions.difference(versionsFound)

        mailTitle = self.getTitle(app, totalValues)
        mailContents = self.mailSender.createMailHeaderForSend(self.runId, mailTitle, app)
        mailContents += self.getMailBody(app, fileBodies, missingVersions)
        allCats = set(totalValues.keys())
        noMailCats = set(["succeeded", "known bugs"])
        allSuccess = allCats.issubset(noMailCats)
        self.mailSender.sendOrStoreMail(app, mailContents, isAllSuccess=allSuccess)

    def getHtmlReportLocation(self, app, reportLocation):
        latestFile = self.getMostRecentFile(app, reportLocation)
        if latestFile is not None:
            fileMapping = app.getConfigValue("file_to_url")
            indexFile = os.path.join(reportLocation, "index.html")
            return convertToUrl(indexFile, fileMapping), convertToUrl(latestFile, fileMapping)
        else:
            return None, None

    def getMostRecentFile(self, app, reportLocation):
        versionName = getVersionName(app, self.allApps)
        appDir = os.path.join(reportLocation, app.name)
        bestPath, bestDate, bestTag = None, None, None
        for path in glob(os.path.join(appDir, "test_" + versionName + "_*.html")):
            fileName = os.path.basename(path)
            _, date, tag = parseFileName(fileName, self.diag)
            if date is not None:
                paddedTag = plugins.padNumbersWithZeroes(tag)
                if bestPath is None or date > bestDate or (date == bestDate and paddedTag > bestTag):
                    bestPath, bestDate, bestTag = path, date, paddedTag
        return bestPath

    def parseDirectory(self, fullDir, app, totalValues):
        basicPrefix = "batchreport." + app.name
        prefix = basicPrefix + app.versionSuffix()
        # Don't collect to more collections!
        self.diag.info("Setting up application " + app.name + " looking for " + prefix)
        filelist = os.listdir(fullDir)
        filelist.sort()
        fileBodies = []
        versionsFound = set()
        for filename in filelist:
            if filename == prefix or filename.startswith(prefix + "."):
                fullname = os.path.join(fullDir, filename)
                fileBody = self.parseFile(fullname, app, totalValues)
                if fileBody:
                    fileBodies.append(fileBody)
                    versionsFound.update(set(filename.replace(basicPrefix, "").split(".")))

        return fileBodies, versionsFound

    @staticmethod
    def runIsRelevant(runId, maxDays):
        if maxDays >= 100000:  # Default value
            return True
        try:
            runDate = datetime.date.fromtimestamp(time.mktime(time.strptime(runId, "%d%b%Y")))
        except ValueError:
            return True  # Isn't necessarily a date, in which case we have no grounds for rejecting it
        todaysDate = datetime.date.today()
        timeElapsed = todaysDate - runDate
        return timeElapsed.days <= maxDays

    def parseFile(self, fullname, app, totalValues):
        localName = os.path.basename(fullname)
        plugins.log.info("Found file called " + localName)
        file = open(fullname)
        valuesLine = file.readline()
        runId = file.readline().strip()
        maxDays = app.getBatchConfigValue("batch_collect_max_age_days")
        if self.runIsRelevant(runId, maxDays):
            self.runId = runId
            self.addValuesToTotal(localName, valuesLine, totalValues)
            fileBody = self.runId + " " + file.read()
            file.close()
            return fileBody
        else:
            plugins.log.info("Not including " + localName + " as run is more than " +
                             str(maxDays) + " days old (as determined by batch_collect_max_age_days).")

    def addValuesToTotal(self, localName, valuesLine, totalValues):
        catValues = plugins.commasplit(valuesLine.strip())
        try:
            for value in catValues:
                catName, count = value.split("=")
                if catName not in totalValues:
                    totalValues[catName] = 0
                totalValues[catName] += int(count)
        except ValueError:
            plugins.printWarning("Found truncated or old format batch report (" +
                                 localName + ") - could not parse result correctly.")

    def getTitle(self, app, totalValues):
        title = self.mailSender.getMailHeader(app, [])
        total = 0
        for value in list(totalValues.values()):
            total += value
        title += str(total) + " tests ran"
        if len(list(totalValues.keys())) == 1:
            return title + ", all " + list(totalValues.keys())[0]
        title += " :"
        for catName, count in list(totalValues.items()):
            title += self.mailSender.briefText(count, catName)
        # Lose trailing comma
        return title[:-1]

    def extractHeader(self, body):
        firstSep = body.find("\n") + 1
        header = body[0:firstSep]
        return header, body[firstSep:]

    def extractSection(self, sectionHeader, body):
        headerLoc = body.find(sectionHeader)
        if headerLoc == -1:
            return body.strip(), ""
        nextLine = body.find("\n", headerLoc) + 1
        if body[nextLine] == "-":
            nextLine = body.find("\n", nextLine) + 1
        section = body[0:headerLoc].strip()
        newBody = body[nextLine:].strip()
        return section, newBody

    def getBody(self, bodies, missingVersions):
        totalBody = ""
        for version in sorted(missingVersions):
            totalBody += "ERROR : No sufficiently recent run matching compulsory version '" + version + "' was found.\n"
        if len(bodies) == 1:
            return totalBody + bodies[0]

        parsedBodies = []
        for subBody in bodies:
            header, parsedSubBody = self.extractHeader(subBody)
            totalBody += header
            parsedBodies.append((header, parsedSubBody))
        totalBody += "\n"

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

            totalBody += self.getSectionBody(prevSectionHeader, parsedSections)
            parsedBodies = newParsedBodies
            prevSectionHeader = sectionHeader
        totalBody += self.getSectionBody(prevSectionHeader, parsedBodies)
        return totalBody

    def getSectionBody(self, sectionHeader, parsedSections):
        if len(sectionHeader) == 0 or len(parsedSections) == 0:
            return ""
        sectionBody = sectionHeader + " follows...\n"
        detailSection = sectionHeader.find("Details") != -1
        if not detailSection or len(parsedSections) == 1:
            sectionBody += "=================================================================================\n"
        for header, section in parsedSections:
            if len(parsedSections) > 1:
                if detailSection:
                    sectionBody += "=================================================================================\n"
                sectionBody += header + "\n"
            sectionBody += section + "\n\n"
        return sectionBody
