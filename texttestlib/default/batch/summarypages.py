""" Code related to building the summary page and the graphs etc. """

from . import testoverview
import logging
import os
import shutil
import time
import operator
import sys
from texttestlib import plugins
from html.parser import HTMLParser
from collections import OrderedDict
from glob import glob
from .batchutils import BatchVersionFilter, parseFileName, convertToUrl, getEnvironmentFromRunFiles
import datetime
from functools import reduce


class GenerateFromSummaryData(plugins.ScriptWithArgs):
    locationApps = OrderedDict()
    summaryFileName = "index.html"
    basePath = ""

    def __init__(self, args=[""]):
        argDict = self.parseArguments(args, ["basepath", "file"])
        if "basepath" in argDict:
            GenerateFromSummaryData.basePath = argDict["basepath"]
        if "file" in argDict:
            GenerateFromSummaryData.summaryFileName = argDict["file"]

    def setUpApplication(self, app):
        location = os.path.realpath(app.getBatchConfigValue("historical_report_location"))
        usePie = app.getBatchConfigValue("historical_report_piechart_summary") == "true"
        versionFilter = BatchVersionFilter(app.getBatchSession())
        rejected = bool(versionFilter.findUnacceptableVersion(app))
        self.locationApps.setdefault(location, []).append((app, usePie, rejected))

    def generateForApps(self, apps):
        def shouldGenerate(currApps):
            for app in apps:
                for currApp, _, _ in currApps:
                    if app is currApp or app in currApp.extras:
                        return True
            return False
        return self.finalise(shouldGenerate)

    @classmethod
    def finalise(cls, predicate=None):
        for location, apps in list(cls.locationApps.items()):
            if predicate is None or predicate(apps):
                if not all((rejected for app, usePie, rejected in apps)):
                    defaultUsePie = all((usePie for app, usePie, rejected in apps))
                    plugins.log.info("Generating index page at " + os.path.join(location,
                                                                                cls.summaryFileName) + ", from following:")
                    for app, _, rejected in apps:
                        text = "- " + app.description()
                        if rejected:
                            text += " (rejected)"
                        plugins.log.info(text)
                    dataFinder = SummaryDataFinder(location, apps, cls.summaryFileName, cls.basePath, defaultUsePie)
                    appsWithVersions = dataFinder.getAppsWithVersions()
                    if appsWithVersions:
                        cls.generate(dataFinder, appsWithVersions, apps[0][0].getConfigValue("file_to_url"))
                else:
                    plugins.log.info("No applications generated for index page at " +
                                     repr(os.path.join(location, cls.summaryFileName)) + ".")


class GenerateSummaryPage(GenerateFromSummaryData):
    scriptDoc = "Generate a summary page which links all the other generated pages"

    @classmethod
    def generate(cls, *args):
        generator = SummaryGenerator()
        generator.generatePage(*args)


class GenerateGraphs(GenerateFromSummaryData):
    scriptDoc = "Generate standalone graphs along the lines of the ones that appear in the HTML report"

    @classmethod
    def generate(cls, dataFinder, appsWithVersions, *args):
        from .resultgraphs import GraphGenerator
        for appName, versions in sorted(list(appsWithVersions.items())):
            for version in versions:
                results = dataFinder.getAllSummaries(appName, version)
                if len(results) > 1:
                    fileName = dataFinder.getGraphFile(appName, version)
                    graphTitle = "Test results for Application: '" + appName + "'  Version: '" + version + "'"
                    graphGenerator = GraphGenerator()
                    graphGenerator.generateGraph(fileName, graphTitle, results, dataFinder.colourFinder)


class TitleFinder(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.active = False
        self.title = None

    def handle_starttag(self, rawname, attrs):
        self.active = rawname.lower() == "title"

    def handle_data(self, content):
        if self.active:
            self.title = content
            self.active = False


class SummaryDataFinder:
    def __init__(self, location, apps, summaryFileName, basePath, defaultUsePie):
        self.diag = logging.getLogger("GenerateWebPages")
        self.location = location
        self.basePath = basePath
        self.summaryPageName = os.path.join(location, summaryFileName)
        self.appVersionInfo = {}
        self.appUsePie = {}
        self.appDirs = OrderedDict()
        self.appRuns = {}
        self.colourFinder, self.inputOptions = None, None
        if len(apps) > 0:
            self.colourFinder = testoverview.ColourFinder(apps[0][0].getCompositeConfigValue)
            self.inputOptions = apps[0][0].inputOptions
        appnames = set()
        for app, usePie, _ in apps:
            appnames.add(app.name)
            self.appUsePie[app.fullName()] = usePie
            repo = app.getBatchConfigValue("batch_result_repository")
            if repo:
                runDir = os.path.join(repo, "run_names")
                if os.path.isdir(runDir):
                    self.appRuns[app.fullName()] = runDir
            appDir = os.path.join(location, app.name)
            self.diag.info("Searching under " + repr(appDir))
            if os.path.isdir(appDir):
                self.appDirs[app.fullName()] = appDir

        if os.path.isdir(location):
            for dirName in os.listdir(location):
                if dirName not in appnames and not dirName.endswith("_history") and dirName not in ["images", "javascript", "jenkins_changes"]:
                    fullDir = os.path.join(location, dirName)
                    if os.path.isdir(fullDir):
                        appFullName = self.findFullName(fullDir)
                        if appFullName and appFullName not in self.appDirs:
                            self.appUsePie[appFullName] = defaultUsePie
                            self.appDirs[appFullName] = fullDir

    @staticmethod
    def findFullName(dirName):
        # All files have the application in the title attribute
        htmlFiles = glob(os.path.join(dirName, "test_*.html"))
        if len(htmlFiles) == 0:
            return
        anyFile = os.path.join(dirName, htmlFiles[0])
        finder = TitleFinder()
        finder.feed(open(anyFile).read())
        title = finder.title
        if title is not None:
            prefix = "est results for"
            pos = title.find(prefix) + len(prefix) + 1
            if pos != -1:
                endPos = title.find(" - ", pos)
                if endPos != -1:
                    return title[pos:endPos]

    def getTemplateFile(self):
        return self.ensureLocationFileExists("summary_template.html", "etc")

    def ensureLocationFileExists(self, fileName, dataDirName=""):
        locationFile = os.path.join(self.location, fileName)
        if not os.path.isfile(locationFile):
            plugins.ensureDirExistsForFile(locationFile)
            plugins.log.info("No file at '" + locationFile + "', copying default file from installation")
            includeSite, includePersonal = self.inputOptions.configPathOptions()
            srcFile = plugins.findDataPaths([fileName], includeSite, includePersonal, dataDirName)[-1]
            shutil.copyfile(srcFile, locationFile)
        return locationFile

    def getLink(self, path):
        relpath = plugins.relpath(self.summaryPageName, self.location, normalise=False)
        if "/" not in relpath:
            return path

        currLocation = self.location
        newParts = []
        for part in reversed(os.path.dirname(relpath).split("/")):
            if part == "..":
                currLocation, localName = os.path.split(currLocation)
                newParts.append(localName)
            else:
                newParts.append("..")
        return "/".join(newParts) + "/" + path

    def getGraphFile(self, appName, version):
        return os.path.join(self.location, self.getShortAppName(appName), "images", "GenerateGraphs_" + version + ".png")

    def getAppsWithVersions(self):
        appsWithVersions = OrderedDict()
        for appName, appDir in self.appDirs.items():
            self.diag.info("adding app " + appName + " with dir " + appDir)
            versionInfo = self.getVersionInfoFor(appDir)
            if versionInfo:
                self.appVersionInfo[appName] = versionInfo
                appsWithVersions[appName] = list(versionInfo.keys())
        return appsWithVersions

    def getShortAppName(self, fullName):
        appDir = self.appDirs[fullName]
        return os.path.basename(appDir)

    def getVersionInfoFor(self, appDir):
        versionDates = {}
        for path in sorted(glob(os.path.join(appDir, "test_*.html"))):
            fileName = os.path.basename(path)
            version, date, tag = parseFileName(fileName, self.diag)
            if version:
                overviewPage = os.path.join(appDir, self.getOverviewPageName(version))
                if os.path.isfile(overviewPage):
                    self.diag.info("Found file with version " + version)
                    versionDates.setdefault(version, {})
                    versionDates[version][(date, tag)] = path
        return versionDates

    def getOverviewPageName(self, version):
        return "test_" + version + ".html"

    def getOverviewPage(self, appName, version):
        return os.path.join(self.basePath, self.getShortAppName(appName), self.getOverviewPageName(version))

    def getAppRunDirectory(self, appName):
        if appName in self.appRuns:
            return self.appRuns.get(appName)
        else:
            # application in question might not be loaded right now
            allRunDirs = set(self.appRuns.values())
            if len(allRunDirs) == 1:
                return allRunDirs.pop()
            else:
                self.diag.info("No log dir found for " + appName + " stored are " + repr(self.appRuns))

    def getMostRecentDateAndTags(self):
        allInfo = {}
        for appName, appInfo in self.appVersionInfo.items():
            for version, versionData in appInfo.items():
                lastInfoPerEnv = self.getLastInfoPerEnvironment(list(versionData.keys()), self.getAppRunDirectory(appName))
                for envData, lastInfo in lastInfoPerEnv:
                    allInfo.setdefault(envData, []).append(lastInfo[0])
                self.diag.info("Most recent date for " + appName + " version " + version + " = " + repr(lastInfoPerEnv))
        mostRecent = set()
        for envData, lastInfoList in list(allInfo.items()):
            mostRecent.add(max(lastInfoList, key=self.getDateTagKey))
        return sorted(mostRecent, key=self.getDateTagKey)

    def getDateTagKey(self, info):
        return info[0], plugins.padNumbersWithZeroes(info[1])

    def usePieChart(self, appName):
        if self.appUsePie.get(appName):
            try:
                from .resultgraphs import PieGraph  # @UnusedImport
                return True
            except Exception as e:
                sys.stderr.write("Not producing pie charts for index pages: " + str(e) + "\n")
                self.appUsePie = {}
                return False  # if matplotlib isn't installed or is too old
        else:
            return False

    def extractLast(self, tags, count=1):
        if count == 1:
            return [max(tags, key=self.getDateTagKey)]
        else:
            return sorted(tags, key=self.getDateTagKey)[-count:]

    def getLastInfoPerEnvironment(self, allTags, runDir, count=1):
        if runDir is None:
            value = self.extractLast(allTags, count)
            return [((None, None), value)] if value is not None else []

        def getEnvironmentData(tag):
            date, actualTag = tag
            fullTag = time.strftime("%d%b%Y", date) + "_" + actualTag
            runEnv = getEnvironmentFromRunFiles([runDir], fullTag)
            return runEnv.get("JENKINS_URL"), runEnv.get("JOB_NAME")

        groupedData = {}
        for tag in allTags:
            envData = getEnvironmentData(tag)
            groupedData.setdefault(envData, []).append(tag)

        mostRecentDate = self.toDate(max(allTags, key=self.getDateTagKey)[0])
        oneDay = datetime.timedelta(days=1)
        allLastInfo = {}
        for envData, tags in groupedData.items():
            last = self.extractLast(tags, count)
            lastDate = self.toDate(last[-1][0])
            if last and mostRecentDate - lastDate <= oneDay:
                allLastInfo[envData] = last

        if len(allLastInfo) > 1 and (None, None) in allLastInfo:
            del allLastInfo[(None, None)]

        return list(allLastInfo.items())

    def toDate(self, timeStruct):
        return datetime.date.fromtimestamp(time.mktime(timeStruct))

    def getMax(self, values, ignoreItems, **kw):
        if ignoreItems == 0:
            return max(values, **kw)
        elif len(values) > ignoreItems:
            values.sort(**kw)
            return values[-1 - ignoreItems]

    def getLatestSummaries(self, appName, version):
        versionData = self.appVersionInfo[appName][version]
        summary, prevSummary = OrderedDict(), OrderedDict()
        infoPerEnv = self.getLastInfoPerEnvironment(list(versionData.keys()), self.getAppRunDirectory(appName), count=2)
        lastInfo, nextLastInfo = None, None
        for envData, lastInfoList in infoPerEnv:
            lastInfo = lastInfoList[-1]
            path = versionData[lastInfo]
            self.diag.info("Extracting summary information from " + path)
            self.extractSummary(path, summary)
            self.diag.info("For app " + appName + " version " + version + " environment " +
                           repr(envData) + ", found summary info " + repr(summary))
            if len(lastInfoList) == 2:
                nextLastInfo = lastInfoList[0]
                path = versionData[nextLastInfo]
                self.diag.info("Extracting previous summary information from " + path)
                self.extractSummary(path, prevSummary)
                self.diag.info("For app " + appName + " version " + version + " environment " +
                               repr(envData) + ", found previous summary info " + repr(prevSummary))
        self.diag.info("Last Info for version " + version + " = " +
                       repr(lastInfo) + ", previous = " + repr(nextLastInfo))
        return summary, lastInfo, prevSummary, nextLastInfo

    def getAllSummaries(self, appName, version):
        versionData = self.appVersionInfo[appName][version]
        allDates = list(versionData.keys())
        allDates.sort(key=self.getDateTagKey)
        summaries = [(time.strftime("%d%b%Y", currInfo[0]), self.extractSummary(
            versionData[currInfo], OrderedDict())) for currInfo in allDates]
        self.diag.info("All Summaries = " + repr(summaries))
        return summaries

    def extractSummary(self, datedFile, summary):
        for line in open(datedFile):
            if line.strip().startswith("<H2>"):
                text = line.strip()[4:-5]  # drop the tags
                for cat, num in list(self.parseSummaryText(text).items()):
                    if cat in summary:
                        summary[cat] += num
                    else:
                        summary[cat] = num
                return summary
        return summary

    def parseSummaryText(self, text):
        words = text.split()[3:]  # Drop "Version: 12 tests"
        index = 0
        categories = []
        while index < len(words):
            try:
                count = int(words[index])
                categories.append(["", count])
            except ValueError:
                categories[-1][0] += words[index]
            index += 1
        self.diag.info("Category information is " + repr(categories))
        colourCount = OrderedDict()
        for colourKey in ["success", "knownbug", "performance", "failure", "incomplete"]:
            colourCount[colourKey] = 0
        for categoryName, count in categories:
            colourKey = self.getColourKey(categoryName)
            colourCount[colourKey] += count
        return colourCount

    def getColour(self, colourKey):
        return self.colourFinder.find(colourKey + "_bg")

    def getColourKey(self, categoryName):
        if categoryName == "succeeded":
            return "success"
        elif categoryName == "knownbugs":
            return "knownbug"
        else:
            for perfCat in ["faster", "slower", "memory+", "memory-", "larger", "smaller"]:
                if categoryName.startswith(perfCat):
                    return "performance"
            if categoryName in ["killed", "unrunnable", "cancelled", "abandoned"]:
                return "incomplete"
            else:
                return "failure"


class SummaryGenerator:
    def __init__(self):
        self.diag = logging.getLogger("GenerateWebPages")
        self.diag.info("Generating summary...")
        self.oldTimeFormat = "%Y%m%d_%H%M%S"
        self.timeFormat = self.oldTimeFormat + "_%f"

    def adjustLineForColours(self, line, dataFinder):
        mainPart = line.rsplit(";", 1)[0].rstrip()
        var, template = mainPart.rsplit(" ", 1)
        colourKey = template.split(".")[-1]
        return var + " " + dataFinder.getColour(colourKey) + ";\n"

    def getDateRangeText(self, info):
        dates = [i[0] for i in info]
        if len(dates) == 0:
            return ""
        firstDate = min(dates)
        lastDate = max(dates)
        text = " dated " + time.strftime("%d%b%Y", firstDate)
        if firstDate != lastDate:
            text += " - " + time.strftime("%d%b%Y", lastDate)
        return text

    def getRecentTagText(self, mostRecentInfo):
        if len(mostRecentInfo) > 2:
            return str(len(mostRecentInfo)) + " test runs" + self.getDateRangeText(mostRecentInfo)
        else:
            suffix = "s" if len(mostRecentInfo) > 1 else ""
            mostRecentTags = [i[1] for i in mostRecentInfo]
            return "test run" + suffix + " " + ", ".join(mostRecentTags)

    def generatePage(self, dataFinder, appsWithVersions, fileToUrl):
        jobLink = ""
        creationDate = testoverview.TitleWithDateStamp("").__str__().strip()
        if os.getenv("JENKINS_URL") and os.getenv("JOB_NAME") and os.getenv("BUILD_NUMBER"):
            jobPath = os.path.join(os.getenv("JENKINS_URL"), "job", os.getenv("JOB_NAME"), os.getenv("BUILD_NUMBER"))
            if jobPath:
                jobLink = "<br>(built by Jenkins job '" + os.getenv("JOB_NAME") + "', " + "<a href='" + \
                    jobPath + "'> " + "build number " + os.getenv("BUILD_NUMBER") + "</a>" + ")"

        summaryPageTimeStamp = dataFinder.summaryPageName + "." + plugins.startTimeString(self.timeFormat)
        with open(summaryPageTimeStamp, "w") as f:
            versionOrder = ["default"]
            appOrder = []
            mostRecentInfo = dataFinder.getMostRecentDateAndTags()
            mostRecentTags = [i[1] for i in mostRecentInfo]
            self.diag.info("Most recent results are from " + repr(mostRecentTags))
            cssColours = []
            for line in open(dataFinder.getTemplateFile()):
                if "<title>" in line:
                    f.write(line)
                elif "historical_report_colours" in line:
                    f.write(self.adjustLineForColours(line, dataFinder))
                else:
                    f.write(line)
                if "td.cell_" in line:
                    cssColours.append(line.rsplit("_", 1)[-1].split()[0])
                if "App order=" in line:
                    appOrder += self.extractOrder(line)
                if "Version order=" in line:
                    versionOrder += self.extractOrder(line)
                if "<h1" in line:
                    f.write("<h3 align=\"center\">(from " + self.getRecentTagText(mostRecentInfo) + ")</h3>\n")
                if "Insert table here" in line:
                    self.insertSummaryTable(f, dataFinder, mostRecentInfo, appsWithVersions,
                                            appOrder, versionOrder, cssColours)
                if "Insert footer here" in line:
                    f.write(creationDate + (jobLink if jobLink else ""))

        fileNames = self.getSortedFileNames(dataFinder.summaryPageName)
        self.linkOrCopy(fileNames[-1][1],
                        dataFinder.summaryPageName)
        self.cleanOldest(fileNames)

        plugins.log.info("wrote: '" + summaryPageTimeStamp + "'")
        if fileToUrl:
            url = convertToUrl(dataFinder.summaryPageName, fileToUrl)
            plugins.log.info("(URL is " + url + ")")

    def linkOrCopy(self, src, dst):
        if os.path.exists(dst):
            os.remove(dst)
        if os.name == "posix":
            os.symlink(os.path.basename(src), dst)
        else:
            shutil.copy(src, dst)

    def getTimeStampFromIndexFile(self, fileName):
        timeStampString = fileName.rsplit(".", 1)[-1]
        try:
            return datetime.datetime.strptime(timeStampString, self.timeFormat)
        except ValueError:
            try:
                return datetime.datetime.strptime(timeStampString, self.oldTimeFormat)
            except ValueError:
                pass  # Might not be the right format

    def cleanOldest(self, fileNames):
        numberOfFilesToKeep = 5
        anythingToRemove = len(fileNames) - numberOfFilesToKeep > 0
        if anythingToRemove:
            numberOfFilesToRemove = len(fileNames) - numberOfFilesToKeep

            # Don't remove newer files in order to mitigate the risk of
            # removing index.html links created by a job running at the
            # same time.
            deleteOlderThan = datetime.datetime.now() - datetime.timedelta(minutes=5)
            for _ in range(numberOfFilesToRemove):
                timeStamp, fileName = fileNames.pop(0)
                if timeStamp >= deleteOlderThan:
                    # fileNames is sorted by time stamps, so no
                    # more files can be removed.
                    break
                os.remove(fileName)

    def getSortedFileNames(self, root):
        allFileNames = glob(root + ".*")
        withTimeStamps = []
        for fileName in allFileNames:
            timeStamp = self.getTimeStampFromIndexFile(fileName)
            if timeStamp is not None:
                withTimeStamps.append((timeStamp, fileName))

        withTimeStamps.sort()
        return withTimeStamps

    def getOrderedVersions(self, predefined, info):
        fullList = sorted(info)
        versions = []
        for version in predefined:
            if version in fullList:
                versions.append(version)
                fullList.remove(version)
        return versions + fullList

    def padWithEmpty(self, versions, columnVersions, minColumnIndices):
        newVersions = []
        index = 0
        for version in versions:
            minIndex = minColumnIndices.get(version, 0)
            while index < minIndex:
                self.diag.info("Index = " + repr(index) + " but min index = " + repr(minIndex))
                newVersions.append("")
                index += 1
            while index in columnVersions and columnVersions[index] != version:
                newVersions.append("")
                index += 1
            newVersions.append(version)
            index += 1
        return newVersions

    def getMinColumnIndices(self, pageInfo, versionOrder):
        # We find the maximum column number a version has on any row,
        # which is equal to the minimum value it should be given in a particular row
        versionIndices = {}
        for rowInfo in list(pageInfo.values()):
            for index, version in enumerate(self.getOrderedVersions(versionOrder, rowInfo)):
                if version not in versionIndices or index > versionIndices[version]:
                    versionIndices[version] = index
        return versionIndices

    def getVersionsWithColumns(self, pageInfo):
        allVersions = reduce(operator.add, list(pageInfo.values()), [])
        return set([v for v in allVersions if allVersions.count(v) > 1])

    def createPieChart(self, dataFinder, resultSummary, summaryGraphName, version, lastInfo, oldResults):
        from .resultgraphs import PieGraph
        fracs = []
        colours = []
        tests = 0
        for colourKey, count in list(resultSummary.items()):
            if count:
                colour = dataFinder.getColour(colourKey)
                fracs.append(count)
                colours.append(colour)
                tests += count
        title = lastInfo[1] + " - " + str(tests) + " tests"
        pg = PieGraph(version, title, size=5)
        pg.pie(fracs, colours)
        summaryGraphFile = os.path.join(dataFinder.location, summaryGraphName)
        if oldResults:
            pg.save(summaryGraphFile, facecolor="#999999")
        else:
            pg.save(summaryGraphFile)

    def showResultAsOld(self, info, mostRecentInfo):
        # Only do this for timed results, i.e. nightjobs etc. From CI/Jenkins etc we can't really tell
        # - it depends on the schedule which we can't see and may not even exist
        if not self.isDate(info[1]):
            return False
        return all((info[0] != i[0] for i in mostRecentInfo))

    def isDate(self, tag):
        return len(tag) == 9 and tag[:2].isdigit() and tag[2:5].isalpha() and tag[5:].isdigit()

    def getTrendImage(self, summary, prevSummary):
        text = self.getTrendText(summary, prevSummary)
        return "images/" + text + ".png"

    def getTrendText(self, summary, prevSummary):
        currSuccess = summary.get("success", 0)
        prevSuccess = prevSummary.get("success", 0)
        if currSuccess > prevSuccess:
            return "arrow_up"
        elif currSuccess < prevSuccess:
            return "arrow_down"
        elif summary.get("failure") > 0:
            return "red_arrow_across"
        else:
            return "green_arrow_across"

    def getTooltipForPrevious(self, prevSummary, prevTag):
        text = "Comparing to " + prevTag + " :\n"
        for colourKey, count in list(prevSummary.items()):
            if count:
                text += colourKey + "=" + str(count) + "\n"
        return text

    def getColourAttribute(self, colourKey, cssColours, dataFinder):
        if colourKey in cssColours:
            return 'class="cell_' + colourKey + '"'
        else:
            colour = dataFinder.getColour(colourKey)
            return 'bgcolor="' + colour + '"'

    def insertSummaryTable(self, file, dataFinder, mostRecentInfo, pageInfo, appOrder, versionOrder, cssColours):
        versionWithColumns = self.getVersionsWithColumns(pageInfo)
        self.diag.info("Following versions will be placed in columns " + repr(versionWithColumns))
        minColumnIndices = self.getMinColumnIndices(pageInfo, versionOrder)
        self.diag.info("Minimum column indices are " + repr(minColumnIndices))
        columnVersions = {}
        for appName in self.getOrderedVersions(appOrder, pageInfo):
            file.write('<tr class="application_row">\n')
            file.write('  <td class="application_name"><h3>' + appName + "</h3></td>\n")
            versions = pageInfo[appName]
            orderedVersions = self.getOrderedVersions(versionOrder, versions)
            self.diag.info("For " + appName + " found " + repr(orderedVersions))
            for columnIndex, version in enumerate(self.padWithEmpty(orderedVersions, columnVersions, minColumnIndices)):
                file.write('  <td class="version_table">')
                if version:
                    file.write('<table border="1" class="version_link"><tr>\n')
                    if version in versionWithColumns:
                        columnVersions[columnIndex] = version

                    resultSummary, lastInfo, prevResultSummary, nextLastInfo = dataFinder.getLatestSummaries(
                        appName, version)
                    oldResults = self.showResultAsOld(lastInfo, mostRecentInfo)
                    fileToLink = dataFinder.getOverviewPage(appName, version)
                    if dataFinder.usePieChart(appName):
                        summaryGraphName = "summary_pie_" + version + ".png"
                        self.createPieChart(dataFinder, resultSummary, summaryGraphName, version, lastInfo, oldResults)
                        file.write('    <td><a href="' + fileToLink + '"><img border=\"0\" src=\"' +
                                   summaryGraphName + '\"></a></td>\n')
                    else:
                        file.write('    <td><h3><a href="' + fileToLink + '">' + version + '</a></h3></td>\n')
                        for colourKey, count in list(resultSummary.items()):
                            if count:
                                file.write('    <td ' + self.getColourAttribute(colourKey,
                                                                                cssColours, dataFinder) + '><h3>')
                                if oldResults:
                                    # Highlight old data by putting it in a paler foreground colour
                                    file.write('<font color="#999999">' + str(count) + "</font>")
                                else:
                                    file.write(str(count))
                                file.write("</h3></td>\n")
                    if prevResultSummary:
                        image = self.getTrendImage(resultSummary, prevResultSummary)
                        dataFinder.ensureLocationFileExists(image)
                        tooltip = self.getTooltipForPrevious(prevResultSummary, nextLastInfo[1])
                        file.write('    <td class="arrow_cell"><img src="' +
                                   dataFinder.getLink(image) + '" title="' + tooltip + '"/></td>\n')
                    file.write("  </tr></table>")
                file.write("</td>\n")
            file.write("</tr>\n")

    def extractOrder(self, line):
        startPos = line.find("order=") + 6
        endPos = line.rfind("-->")
        return plugins.commasplit(line[startPos:endPos])
