
""" Code related to building the summary page and the graphs etc. """

import testoverview, plugins, logging, os, shutil, time, operator, sys
from HTMLParser import HTMLParser
from ordereddict import OrderedDict
from glob import glob
from batchutils import BatchVersionFilter, parseFileName, convertToUrl

class GenerateFromSummaryData(plugins.ScriptWithArgs):
    locationApps = OrderedDict()
    summaryFileName = "index.html"
    basePath = ""
    def __init__(self, args=[""]):
        argDict = self.parseArguments(args, [ "basepath", "file" ])
        if argDict.has_key("basepath"):
            GenerateFromSummaryData.basePath = argDict["basepath"]
        if argDict.has_key("file"):
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
        for location, apps in cls.locationApps.items():
            if predicate is None or predicate(apps):
                if not all((rejected for app, usePie, rejected in apps)):
                    defaultUsePie = all((usePie for app, usePie, rejected in apps))
                    plugins.log.info("Generating index page at " + os.path.join(location, cls.summaryFileName) + ", from following:")
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
        from resultgraphs import GraphGenerator
        for appName, versions in appsWithVersions.items():
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
        self.colourFinder, self.inputOptions = None, None
        if len(apps) > 0:
            self.colourFinder = testoverview.ColourFinder(apps[0][0].getCompositeConfigValue)
            self.inputOptions = apps[0][0].inputOptions
        appnames = set()
        for app, usePie, _ in apps:
            appnames.add(app.name)
            self.appUsePie[app.fullName()] = usePie
            appDir = os.path.join(location, app.name)
            self.diag.info("Searching under " + repr(appDir))
            if os.path.isdir(appDir):
                self.appDirs[app.fullName()] = appDir
                
        if os.path.isdir(location):
            for dirName in os.listdir(location):
                if dirName not in appnames and not dirName.endswith("_history") and dirName not in [ "images", "javascript", "jenkins_changes" ]:
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
        templateFile = os.path.join(self.location, "summary_template.html")
        if not os.path.isfile(templateFile):
            plugins.log.info("No file at '" + templateFile + "', copying default file from installation")
            includeSite, includePersonal = self.inputOptions.configPathOptions()
            srcFile = plugins.findDataPaths([ "summary_template.html" ], includeSite, includePersonal)[-1]
            shutil.copyfile(srcFile, templateFile)
        return templateFile

    def getGraphFile(self, appName, version):        
        return os.path.join(self.location, self.getShortAppName(appName), "images", "GenerateGraphs_" + version + ".png")

    def getAppsWithVersions(self):
        appsWithVersions = OrderedDict()
        for appName, appDir in self.appDirs.items():
            versionInfo = self.getVersionInfoFor(appDir)
            if versionInfo:
                self.appVersionInfo[appName] = versionInfo
                appsWithVersions[appName] = versionInfo.keys()
        return appsWithVersions

    def getShortAppName(self, fullName):
        appDir = self.appDirs[fullName]
        return os.path.basename(appDir)

    def getVersionInfoFor(self, appDir):
        versionDates = {}
        for path in glob(os.path.join(appDir, "test_*.html")):
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

    def getMostRecentDateAndTag(self):
        allDates = []
        for appName, appInfo in self.appVersionInfo.items():
            for versionData in appInfo.values():
                mostRecentInfo = max(versionData.keys(), key=self.getDateTagKey)
                allDates.append(mostRecentInfo)
                self.diag.info("Most recent date for " + appName + " = " + repr(mostRecentInfo))
        return max(allDates)
    
    def getDateTagKey(self, info):
        return info[0], plugins.padNumbersWithZeroes(info[1])
        
    def usePieChart(self, appName):
        if self.appUsePie.get(appName):
            try:
                from resultgraphs import PieGraph #@UnusedImport
                return True
            except Exception, e:
                sys.stderr.write("Not producing pie charts for index pages: " + str(e) + "\n")
                self.appUsePie = {}
                return False # if matplotlib isn't installed or is too old
        else:
            return False

    def getLatestSummary(self, appName, version):
        versionData = self.appVersionInfo[appName][version]
        lastInfo = max(versionData.keys(), key=self.getDateTagKey)
        path = versionData[lastInfo]
        summary = self.extractSummary(path)
        self.diag.info("For version " + version + ", found summary info " + repr(summary))
        return summary, lastInfo

    def getAllSummaries(self, appName, version):
        versionData = self.appVersionInfo[appName][version]
        allDates = versionData.keys()
        allDates.sort(key=self.getDateTagKey)
        return [ (time.strftime("%d%b%Y", currInfo[0]), self.extractSummary(versionData[currInfo])) for currInfo in allDates ]

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
        colourCount = OrderedDict()
        for colourKey in [ "success", "knownbug", "performance", "failure", "incomplete" ]:
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
            for perfCat in [ "faster", "slower", "memory+", "memory-" ]:
                if categoryName.startswith(perfCat):
                    return "performance"
            if categoryName in [ "killed", "unrunnable", "cancelled", "abandoned" ]:
                return "incomplete"
            else:
                return "failure"


class SummaryGenerator:
    def __init__(self):
        self.diag = logging.getLogger("GenerateWebPages")
        self.diag.info("Generating summary...")

    def adjustLineForTitle(self, line):
        pos = line.find("</title>")
        return str(testoverview.TitleWithDateStamp(line[:pos])) + "</title>\n"
            
    def generatePage(self, dataFinder, appsWithVersions, fileToUrl):
        file = open(dataFinder.summaryPageName, "w")
        versionOrder = [ "default" ]
        appOrder = []
        mostRecentInfo = dataFinder.getMostRecentDateAndTag()
        mostRecentTag = mostRecentInfo[1]
        self.diag.info("Most recent results are from " + repr(mostRecentTag))
        for line in open(dataFinder.getTemplateFile()):
            if "<title>" in line:
                file.write(self.adjustLineForTitle(line))
            else:
                file.write(line)
            if "App order=" in line:
                appOrder += self.extractOrder(line)
            if "Version order=" in line:
                versionOrder += self.extractOrder(line)
            if "<h1" in line:
                file.write("<h3 align=\"center\">(from test run " + mostRecentTag + ")</h3>\n")
            if "Insert table here" in line:
                self.insertSummaryTable(file, dataFinder, mostRecentInfo, appsWithVersions, appOrder, versionOrder)
        file.close()
        plugins.log.info("wrote: '" + dataFinder.summaryPageName + "'") 
        if fileToUrl:
            url = convertToUrl(dataFinder.summaryPageName, fileToUrl)
            plugins.log.info("(URL is " + url + ")")
        
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

    def createPieChart(self, dataFinder, resultSummary, summaryGraphName, version, lastInfo, oldResults):
        from resultgraphs import PieGraph
        fracs = []
        colours = []
        tests = 0
        for colourKey, count in resultSummary.items():
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

    def insertSummaryTable(self, file, dataFinder, mostRecentInfo, pageInfo, appOrder, versionOrder):
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

                    resultSummary, lastInfo = dataFinder.getLatestSummary(appName, version)
                    oldResults = lastInfo != mostRecentInfo
                    fileToLink = dataFinder.getOverviewPage(appName, version)
                    if dataFinder.usePieChart(appName):
                        summaryGraphName = "summary_pie_" + version + ".png"
                        self.createPieChart(dataFinder, resultSummary, summaryGraphName, version, lastInfo, oldResults)
                        file.write('    <td><a href="' + fileToLink + '"><img border=\"0\" src=\"' + summaryGraphName + '\"></a></td>\n')
                    else:
                        file.write('    <td><h3><a href="' + fileToLink + '">' + version + '</a></h3></td>\n')
                        for colourKey, count in resultSummary.items():
                            if count:
                                colour = dataFinder.getColour(colourKey)
                                file.write('    <td bgcolor="' + colour + '"><h3>')
                                if oldResults:
                                    # Highlight old data by putting it in a paler foreground colour
                                    file.write('<font color="#999999">' + str(count) + "</font>")
                                else:
                                    file.write(str(count))
                                file.write("</h3></td>\n")
                    file.write("  </tr></table>")
                file.write("</td>\n")
            file.write("</tr>\n")

    def extractOrder(self, line):
        startPos = line.find("order=") + 6
        endPos = line.rfind("-->")
        return plugins.commasplit(line[startPos:endPos])


