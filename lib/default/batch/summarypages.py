
""" Code related to building the summary page and the graphs etc. """

import testoverview, plugins, logging, os, shutil, time, operator
from ndict import seqdict
from glob import glob

class GenerateSummaryPage(plugins.ScriptWithArgs):
    scriptDoc = "Generate a summary page which links all the other generated pages"
    summaryFileName = "index.html"
    basePath = ""
    locationApps = seqdict()
    def __init__(self, args=[""]):
        argDict = self.parseArguments(args, [ "batch", "file", "basepath", "graphs" ])
        self.batchSession = argDict.get("batch", "default")
        if argDict.has_key("basepath"):
            GenerateSummaryPage.basePath = argDict["basepath"]
        if argDict.has_key("file"):
            GenerateSummaryPage.summaryFileName = argDict["file"]
            
    def setUpApplication(self, app):
        location = os.path.realpath(app.getCompositeConfigValue("historical_report_location", self.batchSession)).replace("\\", "/")
        self.locationApps.setdefault(location, []).append(app)

    @classmethod
    def finalise(cls):
        for location, apps in cls.locationApps.items():
            dataFinder = SummaryDataFinder(location, apps, cls.summaryFileName, cls.basePath)
            if dataFinder.hasInfo():
                generator = SummaryGenerator()
                generator.generatePage(dataFinder)


class SummaryDataFinder:
    def __init__(self, location, apps, summaryFileName, basePath):
        self.diag = logging.getLogger("GenerateWebPages")
        self.location = location
        self.basePath = basePath
        self.summaryPageName = os.path.join(location, summaryFileName)
        self.appVersionInfo = {}
        self.appDirs = seqdict()
        self.colourFinder, self.inputOptions = None, None
        if len(apps) > 0:
            self.colourFinder = testoverview.ColourFinder(apps[0].getCompositeConfigValue)
            self.inputOptions = apps[0].inputOptions
        for app in apps:
            appDir = os.path.join(location, app.name)
            self.diag.info("Searching under " + repr(appDir))
            if os.path.isdir(appDir):
                self.appDirs[app.fullName()] = appDir

    def hasInfo(self):
        return len(self.appDirs) > 0

    def getTemplateFile(self):
        templateFile = os.path.join(self.location, "summary_template.html")
        if not os.path.isfile(templateFile):
            plugins.log.info("No file at '" + templateFile + "', copying default file from installation")
            includeSite, includePersonal = self.inputOptions.configPathOptions()
            srcFile = plugins.findDataPaths([ "summary_template.html" ], includeSite, includePersonal)[-1]
            shutil.copyfile(srcFile, templateFile)
        return templateFile

    def getAppsWithVersions(self):
        appsWithVersions = seqdict()
        for appName, appDir in self.appDirs.items():
            versionInfo = self.getVersionInfoFor(appName, appDir)
            self.appVersionInfo[appName] = versionInfo
            appsWithVersions[appName] = versionInfo.keys()
        return appsWithVersions

    def getVersionInfoFor(self, app, appDir):
        versionDates = {}
        for path in glob(os.path.join(appDir, "test_*.html")):
            fileName = os.path.basename(path)
            version, date = self.parseFileName(fileName)
            if version:
                overviewPage = os.path.join(appDir, self.getOverviewPageName(version))
                if os.path.isfile(overviewPage):
                    self.diag.info("Found file with version " + version)
                    versionDates.setdefault(version, {})
                    versionDates[version][date] = path
        return versionDates

    def getOverviewPageName(self, version):
        return "test_" + version + ".html"

    def getOverviewPage(self, appName, version):
        appDir = self.appDirs[appName]
        return os.path.join(self.basePath, os.path.basename(appDir), self.getOverviewPageName(version))

    def getLatestSummary(self, appName, version):
        versionData = self.appVersionInfo[appName][version]
        lastDate = sorted(versionData.keys())[-1]
        path = versionData[lastDate]
        summary = self.extractSummary(path)
        self.diag.info("For version " + version + ", found summary info " + repr(summary))
        return summary

    def extractSummary(self, datedFile):
        for line in open(datedFile):
            if line.strip().startswith("<H2>"):
                text = line.strip()[4:-5] # drop the tags
                return self.parseSummaryText(text)
        return {}

    def parseSummaryText(self, text):
        words = text.split()[3:] # Drop "Version: 12 tests"
        index = 0
        categories = []
        while index < len(words):
            try:
                count = int(words[index])
                categories.append([ "", count ])
            except ValueError:
                categories[-1][0] += words[index]
            index += 1
        self.diag.info("Category information is " + repr(categories))
        colourCount = seqdict()
        for colourKey in [ "success_bg", "knownbug_bg", "performance_bg", "failure_bg" ]:
            colourCount[self.colourFinder.find(colourKey)] = 0
        for categoryName, count in categories:
            colourKey = self.getColourKey(categoryName)
            colourCount[self.colourFinder.find(colourKey)] += count
        return colourCount

    def getColourKey(self, categoryName):
        if categoryName == "succeeded":
            return "success_bg"
        elif categoryName == "knownbugs":
            return "knownbug_bg"
        elif categoryName in [ "faster", "slower", "memory+", "memory-" ]:
            return "performance_bg"
        else:
            return "failure_bg"

    def parseFileName(self, fileName):
        versionStr = fileName[5:-5]
        components = versionStr.split("_")
        for index, component in enumerate(components[1:]):
            try:
                self.diag.info("Trying to parse " + component + " as date.")
                date = time.strptime(component, "%d%b%Y")
                return "_".join(components[:index + 1]), date
            except ValueError:
                pass
        return None, None


class SummaryGenerator:
    def __init__(self):
        self.diag = logging.getLogger("GenerateWebPages")
        self.diag.info("Generating summary...")

    def adjustLineForTitle(self, line):
        pos = line.find("</title>")
        return str(testoverview.TitleWithDateStamp(line[:pos])) + "</title>\n"
            
    def generatePage(self, dataFinder):
        file = open(dataFinder.summaryPageName, "w")
        versionOrder = [ "default" ]
        appOrder = []
        for line in open(dataFinder.getTemplateFile()):
            if "<title>" in line:
                file.write(self.adjustLineForTitle(line))
            else:
                file.write(line)
            if "App order=" in line:
                appOrder += self.extractOrder(line)
            if "Version order=" in line:
                versionOrder += self.extractOrder(line)
            if "Insert table here" in line:
                self.insertSummaryTable(file, dataFinder, appOrder, versionOrder)
        file.close()
        plugins.log.info("wrote: '" + dataFinder.summaryPageName + "'") 
        
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
            while columnVersions.has_key(index) and columnVersions[index] != version:
                newVersions.append("")
                index += 1
            newVersions.append(version)
            index += 1
        return newVersions

    def getMinColumnIndices(self, pageInfo, versionOrder):
        # We find the maximum column number a version has on any row,
        # which is equal to the minimum value it should be given in a particular row
        versionIndices = {}
        for rowInfo in pageInfo.values():
            for index, version in enumerate(self.getOrderedVersions(versionOrder, rowInfo)):
                if not versionIndices.has_key(version) or index > versionIndices[version]:
                    versionIndices[version] = index
        return versionIndices

    def getVersionsWithColumns(self, pageInfo):
        allVersions = reduce(operator.add, pageInfo.values(), [])
        return set(filter(lambda v: allVersions.count(v) > 1, allVersions))  

    def insertSummaryTable(self, file, dataFinder, appOrder, versionOrder):
        pageInfo = dataFinder.getAppsWithVersions()
        versionWithColumns = self.getVersionsWithColumns(pageInfo)
        self.diag.info("Following versions will be placed in columns " + repr(versionWithColumns))
        minColumnIndices = self.getMinColumnIndices(pageInfo, versionOrder)
        self.diag.info("Minimum column indices are " + repr(minColumnIndices))
        columnVersions = {}
        for appName in self.getOrderedVersions(appOrder, pageInfo):
            file.write("<tr>\n")
            file.write("  <td><h3>" + appName + "</h3></td>\n")
            versions = pageInfo[appName]
            orderedVersions = self.getOrderedVersions(versionOrder, versions)
            self.diag.info("For " + appName + " found " + repr(orderedVersions))
            for columnIndex, version in enumerate(self.padWithEmpty(orderedVersions, columnVersions, minColumnIndices)):
                file.write('  <td>')
                if version:
                    file.write('<table border="1" class="version_link"><tr>\n')
                    if version in versionWithColumns:
                        columnVersions[columnIndex] = version

                    resultSummary = dataFinder.getLatestSummary(appName, version)
                    fileToLink = dataFinder.getOverviewPage(appName, version)
                    file.write('    <td><h3><a href="' + fileToLink + '">' + version + '</a></h3></td>\n')
                    for colour, count in resultSummary.items():
                        if count:
                            file.write('    <td bgcolor="' + colour + '"><h3>' + str(count) + "</h3></td>\n")
                    file.write("  </tr></table>")
                file.write("</td>\n")
            file.write("</tr>\n")

    def extractOrder(self, line):
        startPos = line.find("order=") + 6
        endPos = line.rfind("-->")
        return plugins.commasplit(line[startPos:endPos])
