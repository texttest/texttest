# Code to generate HTML report of historical information. This report generated
# either via the -coll flag, or via -s 'batch.GenerateHistoricalReport <batchid>'

import os, plugins, time, re, HTMLgen, HTMLcolors, operator, sys, logging
from cPickle import Pickler, Unpickler, UnpicklingError
from ndict import seqdict
from glob import glob
HTMLgen.PRINTECHO = 0

def getWeekDay(tag):
    return plugins.weekdays[time.strptime(tag.split("_")[0], "%d%b%Y")[6]]
    
class ColourFinder:
    def setColourDict(self, colourDict):
        self.colourDict = colourDict
    def find(self, title):
        colourName = self.colourDict[title]
        return self.htmlColour(colourName)
    def htmlColour(self, colourName):
        if not colourName.startswith("#"):
            exec "colourName = HTMLcolors." + colourName.upper()
        return colourName

colourFinder = ColourFinder()

def getDisplayText(tag):
    displayText = "_".join(tag.split("_")[1:])
    if displayText:
        return displayText
    else:
        return tag

class TitleWithDateStamp:
    def __init__(self, title):
        self.title = title + " (generated at "
    def __str__(self):
        return self.title + plugins.localtime(format="%d%b%H:%M") + ")"
            

class GenerateWebPages(object):
    def __init__(self, pageTitle, pageVersion, pageDir, extraVersions, app):
        self.pageTitle = pageTitle
        self.pageVersion = pageVersion
        self.extraVersions = extraVersions
        self.pageDir = pageDir
        self.pagesOverview = seqdict()
        self.pagesDetails = seqdict()
        self.app = app
        self.diag = logging.getLogger("GenerateWebPages")
        colourFinder.setColourDict(app.getConfigValue("historical_report_colours"))

    def makeSelectors(self, subPageNames, tags=[]):
        allSelectors = []
        firstSubPageName = self.app.getCompositeConfigValue("historical_report_subpages", "default")[0]
        for subPageName in subPageNames:
            if subPageName == firstSubPageName:
                suffix = ""
            else:
                suffix = "_" + subPageName.lower()
            allSelectors.append(Selector(subPageName, suffix, self.app, tags))
        return allSelectors
    
    def generate(self, repositoryDirs, subPageNames):
        foundMinorVersions = HTMLgen.Container()
        details = TestDetails()
        allMonthSelectors = set()
        for version, repositoryDirInfo in repositoryDirs.items():
            self.diag.info("Generating " + version)
            allFiles, tags = self.findTestStateFilesAndTags(repositoryDirInfo)
            if len(allFiles) > 0:
                selectors = self.makeSelectors(subPageNames, tags)
                monthSelectors = SelectorByMonth.makeInstances(tags)
                allMonthSelectors.update(monthSelectors)
                allSelectors = selectors + list(reversed(monthSelectors))
                # If we already have month pages, we only regenerate the current one
                if len(self.getExistingMonthPages()) == 0:
                    selectors = allSelectors
                else:
                    selectors.append(monthSelectors[-1])
                    tags = list(reduce(set.union, (set(selector.selectedTags) for selector in selectors), set()))
                    tags.sort(self.compareTags)

                loggedTests = seqdict()
                categoryHandlers = {}
                for stateFile, repository in allFiles:
                    tag = self.getTagFromFile(stateFile)
                    if len(tags) == 0 or tag in tags:
                        testId, state, extraVersion = self.processTestStateFile(stateFile, repository)
                        loggedTests.setdefault(extraVersion, seqdict()).setdefault(testId, seqdict())[tag] = state
                        categoryHandlers.setdefault(tag, CategoryHandler()).registerInCategory(testId, state, extraVersion)

                for sel in selectors:
                    page = self.getPage(sel)
                    if len(repositoryDirs) > 1:
                        self.addVersionHeader(page, version)
                    self.addTable(page, categoryHandlers, version, loggedTests, sel)

                # put them in reverse order, most relevant first
                linkFromDetailsToOverview = [ sel.getLinkInfo(self.pageVersion) for sel in allSelectors ]
                det = details.generate(categoryHandlers, version, tags, linkFromDetailsToOverview)
                self.addDetailPages(det)
                foundMinorVersions.append(HTMLgen.Href("#" + version, self.removePageVersion(version)))

        selContainer = HTMLgen.Container()
        for sel in self.makeSelectors(subPageNames):
            target, linkName = sel.getLinkInfo(self.pageVersion)
            selContainer.append(HTMLgen.Href(target, linkName))

        monthContainer = HTMLgen.Container()
        for sel in sorted(allMonthSelectors):
            target, linkName = sel.getLinkInfo(self.pageVersion)
            monthContainer.append(HTMLgen.Href(target, linkName))
            
        for page in self.pagesOverview.values():
            if len(monthContainer.contents) > 0:
                page.prepend(HTMLgen.Heading(2, monthContainer, align = 'center'))
            page.prepend(HTMLgen.Heading(2, selContainer, align = 'center'))
            page.prepend(HTMLgen.Heading(1, foundMinorVersions, align = 'center'))
            page.prepend(HTMLgen.Heading(1, "Test results for " + self.pageTitle, align = 'center'))

        self.writePages()
        
    def getExistingMonthPages(self):
        return glob(os.path.join(self.pageDir, "test_" + self.pageVersion + "_all_???[0-9][0-9][0-9][0-9].html"))

    def compareTags(self, x, y):
        timeCmp = cmp(self.getTagTimeInSeconds(x), self.getTagTimeInSeconds(y))
        if timeCmp:
            return timeCmp
        else:
            return cmp(x, y) # If the timing is the same, sort alphabetically

    def getTagFromFile(self, fileName):
        return os.path.basename(fileName).replace("teststate_", "")
        
    def findTestStateFilesAndTags(self, repositoryDirs):
        allFiles = []
        allTags = set()
        for extraVersion, dir in repositoryDirs:
            for root, dirs, files in os.walk(dir):
                for file in files:
                    if file.startswith("teststate_"):
                        allFiles.append((os.path.join(root, file), dir))
                        allTags.add(self.getTagFromFile(file))
                                
        return allFiles, sorted(allTags, self.compareTags)
                          
    def processTestStateFile(self, stateFile, repository):
        state = self.readState(stateFile)
        testId = self.getTestIdentifier(stateFile, repository)
        extraVersion = self.findExtraVersion(repository)
        return testId, state, extraVersion
    
    def findExtraVersion(self, repository):
        versions = os.path.basename(repository).split(".")
        for i in xrange(len(versions)):
            version = ".".join(versions[i:])
            if version in self.extraVersions:
                return version
        return ""

    def findGlobal(self, modName, className):
        try:
            exec "from " + modName + " import " + className + " as _class"
            return _class
        except ImportError:
            for loadedMod in sys.modules.keys():
                if "." in loadedMod:
                    packageName = ".".join(loadedMod.split(".")[:-1] + [ modName ])
                    try:
                        exec "from " + packageName + " import " + className + " as _class" 
                        return _class
                    except ImportError:
                        pass
            raise
        
    def getNewState(self, file):
        # Would like to do load(file) here... but it doesn't work with universal line endings, see Python bug 1724366
        from cStringIO import StringIO
        unpickler = Unpickler(StringIO(file.read()))
        # Magic to keep us backward compatible in the face of packages changing...
        unpickler.find_global = self.findGlobal
        return unpickler.load()
        
    def readState(self, stateFile):
        file = open(stateFile, "rU")
        try:
            state = self.getNewState(file)
            if isinstance(state, plugins.TestState):
                state.updateAfterLoad(self.app)
                return state
            else:
                return self.readErrorState("Incorrect type for state object.")
        except (UnpicklingError, ImportError, EOFError, AttributeError), e:
            return self.readErrorState("Stack info follows:\n" + str(e))

    def readErrorState(self, errMsg):
        freeText = "Failed to read results file, possibly deprecated format. " + errMsg
        return plugins.Unrunnable(freeText, "read error")

    def removePageVersion(self, version):
        leftVersions = []
        pageSubVersions = self.pageVersion.split(".")
        for subVersion in version.split("."):
            if not subVersion in pageSubVersions:
                leftVersions.append(subVersion)
        return ".".join(leftVersions)

    def getPage(self, selector):
        fileName = selector.getLinkInfo(self.pageVersion)[0]
        return self.pagesOverview.setdefault(fileName, self.createPage())
        
    def createPage(self):
        style = "body,td {color: #000000;font-size: 11px;font-family: Helvetica;} th {color: #000000;font-size: 13px;font-family: Helvetica;}"
        title = TitleWithDateStamp("Test results for " + self.pageTitle)
        return HTMLgen.SimpleDocument(title=title, style=style)

    def addVersionHeader(self, page, version):
        page.append(HTMLgen.HR())
        page.append(HTMLgen.Name(version))
        page.append(HTMLgen.U(HTMLgen.Heading(1, version, align = 'center')))
        
    def addTable(self, page, categoryHandlers, version, loggedTests, selector):
        testTable = TestTable(self.app)
        extraVersions = loggedTests.keys()[1:]
        if len(extraVersions) > 0:
            page.append(testTable.generateExtraVersionLinks(version, extraVersions))

        table = testTable.generate(categoryHandlers, self.pageVersion, version, loggedTests, selector.selectedTags)
        page.append(table)
        
    def addDetailPages(self, details):
        for tag in details.keys():
            if not self.pagesDetails.has_key(tag):
                tagText = getDisplayText(tag)
                pageDetailTitle = "Detailed test results for " + self.pageTitle + ": " + tagText
                self.pagesDetails[tag] = HTMLgen.SimpleDocument(title=TitleWithDateStamp(pageDetailTitle))
                self.pagesDetails[tag].append(HTMLgen.Heading(1, tagText + " - detailed test results for ", self.pageTitle, align = 'center'))
            self.pagesDetails[tag].append(details[tag])
    def writePages(self):
        plugins.log.info("Writing overview pages...")
        for pageName, page in self.pagesOverview.items():
            page.write(os.path.join(self.pageDir, pageName))
            plugins.log.info("wrote: '" + pageName + "'")
        plugins.log.info("Writing detail pages...")
        for tag, page in self.pagesDetails.items():
            pageName = getDetailPageName(self.pageVersion, tag)
            page.write(os.path.join(self.pageDir, pageName))
            plugins.log.info("wrote: '" + pageName + "'")
    def getTestIdentifier(self, stateFile, repository):
        dir = os.path.dirname(stateFile)
        return dir.replace(repository + os.sep, "").replace(os.sep, " ")
    def getTagTimeInSeconds(self, tag):
        timePart = tag.split("_")[0]
        return time.mktime(time.strptime(timePart, "%d%b%Y"))

class TestTable:
    def __init__(self, app):
        self.app = app

    def generate(self, categoryHandlers, pageVersion, version, loggedTests, tagsFound):
        table = HTMLgen.TableLite(border=0, cellpadding=4, cellspacing=2,width="100%")
        table.append(self.generateTableHead(pageVersion, version, tagsFound))
        table.append(self.generateSummaries(categoryHandlers, pageVersion, version, tagsFound))
        firstVersion = loggedTests.keys()[0]
        for extraVersion, testInfo in loggedTests.items():
            # Add an extra line in the table only if there are several versions.
            if extraVersion != firstVersion:
                fullVersion = version + "." + extraVersion
                table.append(self.generateExtraVersionHeader(fullVersion, tagsFound))

            for test in sorted(testInfo.keys()):
                results = testInfo[test]
                table.append(self.generateTestRow(test, pageVersion, version, extraVersion, results, tagsFound))

        table.append(HTMLgen.BR())
        return table

    def generateSummaries(self, categoryHandlers, pageVersion, version, tags):
        bgColour = colourFinder.find("column_header_bg")
        row = [ HTMLgen.TD("Summary", bgcolor = bgColour) ]
        for tag in tags:
            categoryHandler = categoryHandlers[tag]
            detailPageName = getDetailPageName(pageVersion, tag)
            summary = categoryHandler.generateSummaryHTML(detailPageName + "#" + version)
            row.append(HTMLgen.TD(summary, bgcolor = bgColour))
        return HTMLgen.TR(*row)

    def generateExtraVersionLinks(self, version, extraVersions):
        cont = HTMLgen.Container()
        for extra in extraVersions:
            fullName = version + "." + extra
            cont.append(HTMLgen.Href("#" + fullName, extra))
        return HTMLgen.Heading(2, cont, align='center')
        
    def generateExtraVersionHeader(self, extraVersion, tagsFound):
        bgColour = colourFinder.find("column_header_bg")
        extraVersionElement = HTMLgen.Container(HTMLgen.Name(extraVersion), extraVersion)
        columnHeader = HTMLgen.TH(extraVersionElement, colspan = len(tagsFound) + 1, bgcolor=bgColour)
        return HTMLgen.TR(columnHeader)
    
    def generateTestRow(self, test, pageVersion, version, extraVersion, results, tagsFound):
        bgColour = colourFinder.find("row_header_bg")
        row = [ HTMLgen.TD(HTMLgen.Container(HTMLgen.Name(version + test + extraVersion), test), bgcolor=bgColour) ]
        for tag in tagsFound:
            if results.has_key(tag):
                state = results[tag]
                fgcol, bgcol = self.getColours(state)
                filteredState = self.filterState(repr(state))
                detail = state.getTypeBreakdown()[1]
                if state.category == "success":
                    cellContaint =  HTMLgen.Font(filteredState + detail, color = fgcol)
                else:
                    cellContaint = HTMLgen.Href(getDetailPageName(pageVersion, tag) + "#" + version + test + extraVersion,
                                                HTMLgen.Font(filteredState + detail, color = fgcol))
            else:
                bgcol = colourFinder.find("no_results_bg")
                cellContaint = "N/A"
            row.append(HTMLgen.TD(cellContaint, bgcolor = bgcol))
        return HTMLgen.TR(*row)
    def filterState(self, cellContent):
        result = cellContent
        result = re.sub(r'CRASHED.*( on .*)', r'CRASH\1', result)
        result = re.sub('(\w),(\w)', '\\1, \\2', result)
        result = re.sub(':', '', result)
        result = re.sub(' on ', ' ', result)
        result = re.sub('could not be run', '', result)
        result = re.sub('succeeded', 'ok', result)
        result = re.sub('used more memory','', result)
        result = re.sub('used less memory','', result)
        result = re.sub('ran faster','', result)
        result = re.sub('ran slower','', result)
        result = re.sub('faster\([^ ]+\) ','', result)
        result = re.sub('slower\([^ ]+\) ','', result)
        return result

    def getColours(self, state):
        bgcol = colourFinder.find("failure_bg")
        fgcol = colourFinder.find("test_default_fg")
        category = state.category
        if category.startswith("faster") or category.startswith("slower"):
            bgcol = colourFinder.find("performance_bg")
            if self.getPercent(state) >= self.app.getCompositeConfigValue("performance_variation_serious_%", "cputime"):
                fgcol = colourFinder.find("performance_fg")
        elif category == "smaller" or category == "larger":
            bgcol = colourFinder.find("memory_bg")
            if self.getPercent(state) >= self.app.getCompositeConfigValue("performance_variation_serious_%", "memory"):
                fgcol = colourFinder.find("performance_fg")
        elif category == "success":
            bgcol = colourFinder.find("success_bg")
        return fgcol, bgcol

    def getPercent(self, state):
        return state.getMostSevereFileComparison().perfComparison.percentageChange

    def findTagColour(self, tag):
        return colourFinder.find("run_" + getWeekDay(tag) + "_fg")

    def generateTableHead(self, pageVersion, version, tagsFound):
        head = [ HTMLgen.TH("Test") ]
        for tag in tagsFound:
            tagColour = self.findTagColour(tag)
            head.append(HTMLgen.TH(HTMLgen.Href(getDetailPageName(pageVersion, tag), HTMLgen.Font(getDisplayText(tag), color=tagColour))))
        heading = HTMLgen.TR()
        heading = heading + head
        return heading

        
class TestDetails:
    def generate(self, categoryHandlers, version, tags, linkFromDetailsToOverview):
        detailsContainers = seqdict()
        for tag in tags:
            container = detailsContainers[tag] = HTMLgen.Container()
            categoryHandler = categoryHandlers[tag]
            container.append(HTMLgen.HR())
            container.append(HTMLgen.Heading(2, version + ": " + categoryHandler.generateSummary()))
            for desc, testInfo in categoryHandler.getTestsWithDescriptions():
                fullDescription = self.getFullDescription(testInfo, version, linkFromDetailsToOverview)
                if fullDescription:
                    container.append(HTMLgen.Name(version + desc))
                    container.append(HTMLgen.Heading(3, "Detailed information for the tests that " + desc + ":"))
                    container.append(fullDescription)
        return detailsContainers
    
    def getFreeTextData(self, tests):
        data = seqdict()
        for testName, state, extraVersion in tests:
            freeText = state.freeText
            if freeText:
                if not data.has_key(freeText):
                    data[freeText] = []
                data[freeText].append((testName, state, extraVersion))
        return data.items()

    def getFullDescription(self, tests, version, linkFromDetailsToOverview):
        freeTextData = self.getFreeTextData(tests)
        if len(freeTextData) == 0:
            return
        fullText = HTMLgen.Container()
        for freeText, tests in freeTextData:
            for testName, state, extraVersion in tests:
                fullText.append(HTMLgen.Name(version + testName + extraVersion))
            fullText.append(self.getHeaderLine(tests, version, linkFromDetailsToOverview))
            self.appendFreeText(fullText, freeText)
            if len(tests) > 1:
                for line in self.getTestLines(tests, version, linkFromDetailsToOverview):
                    fullText.append(line)                            
        return fullText
    
    def appendFreeText(self, fullText, freeText):
        freeText = freeText.replace("<", "&lt;").replace(">", "&gt;")
        linkMarker = "URL=http://"
        if freeText.find(linkMarker) != -1:
            currFreeText = ""
            for line in freeText.splitlines():
                if line.find(linkMarker) != -1:
                    fullText.append(HTMLgen.RawText("<PRE>" + currFreeText.strip() + "</PRE>"))
                    currFreeText = ""
                    words = line.strip().split()
                    linkTarget = words[-1][4:] # strip off the URL=
                    newLine = " ".join(words[:-1]) + "\n"
                    fullText.append(HTMLgen.Href(linkTarget, newLine))
                else:
                    currFreeText += line + "\n"
        else:
            fullText.append(HTMLgen.RawText("<PRE>" + freeText + "</PRE>"))
    
    def getHeaderLine(self, tests, version, linkFromDetailsToOverview):
        testName, state, extraVersion = tests[0]
        if len(tests) == 1:
            linksToOverview = self.getLinksToOverview(version, testName, extraVersion, linkFromDetailsToOverview)
            headerText = "TEST " + repr(state) + " " + testName + " ("
            container = HTMLgen.Container(headerText, linksToOverview)
            return HTMLgen.Heading(4, container, ")")
        else:
            headerText = str(len(tests)) + " TESTS " + repr(state)
            return HTMLgen.Heading(4, headerText) 
    def getTestLines(self, tests, version, linkFromDetailsToOverview):
        lines = []
        for testName, state, extraVersion in tests:
            linksToOverview = self.getLinksToOverview(version, testName, extraVersion, linkFromDetailsToOverview)
            headerText = testName + " ("
            container = HTMLgen.Container(headerText, linksToOverview, ")<br>")
            lines.append(container)
        return lines
    def getLinksToOverview(self, version, testName, extraVersion, linkFromDetailsToOverview):
        links = HTMLgen.Container()
        for targetFile, linkName in linkFromDetailsToOverview:
            links.append(HTMLgen.Href(targetFile + "#" + version + testName + extraVersion, linkName))
        return links
        
class CategoryHandler:
    def __init__(self):
        self.testsInCategory = seqdict()

    def registerInCategory(self, testId, state, extraVersion):
        self.testsInCategory.setdefault(state.category, []).append((testId, state, extraVersion))

    def generateSummary(self):
        categoryDescs = []
        testCountSummary = self._generateSummary(categoryDescs)
        return testCountSummary + " ".join(categoryDescs)

    def generateSummaryHTML(self, detailPageRef):
        container = HTMLgen.Container()
        testCountSummary = self._generateSummary(container, self.categorySummaryHTML, detailPageRef=detailPageRef) 
        return HTMLgen.Container(HTMLgen.Text(testCountSummary), container)

    def categorySummaryHTML(self, cat, summary, longDescr, detailPageRef):
        basic = HTMLgen.Text(summary)
        if cat == "success":
            return basic
        else:
            return HTMLgen.Href(detailPageRef + longDescr, basic)

    def _generateSummary(self, container, categorySummaryMethod=None, **kwargs):
        numTests = 0
        for cat, testInfo in sorted(self.testsInCategory.items(), self.compareCategories):
            testCount = len(testInfo)
            shortDescr, longDescr = getCategoryDescription(cat)
            categorySummary = str(testCount) + " " + shortDescr
            if categorySummaryMethod:
                container.append(categorySummaryMethod(cat, categorySummary, longDescr, **kwargs))
            else:
                container.append(categorySummary)
            numTests += testCount
        return str(numTests) + " tests: "

    def getTestsWithDescriptions(self):
        return [ (getCategoryDescription(cat)[1], testInfo) for cat, testInfo in self.testsInCategory.items() ]

    def compareCategories(self, data1, data2):
        # Put success at the start, it's neater like that
        if data1[0] == data2[0]:
            return 0
        elif data1[0] == "success":
            return -1
        elif data2[0] == "success":
            return 1
        else:
            return 0
                          

def getCategoryDescription(cat):
    return plugins.TestState.categoryDescriptions.get(cat, (cat, cat))

def getDetailPageName(pageVersion, tag):
    return "test_" + pageVersion + "_" + tag + ".html"


class BaseSelector(object):
    def __init__(self, linkName, suffix):
        self.selectedTags = []
        self.linkName = linkName
        self.suffix = suffix
    def add(self, tag):
        self.selectedTags.append(tag)
    def getLinkInfo(self, pageVersion):
        return "test_" + pageVersion + self.suffix + ".html", self.linkName


class Selector(BaseSelector):
    def __init__(self, linkName, suffix, app, tags):
        super(Selector, self).__init__(linkName, suffix)
        cutoff = app.getCompositeConfigValue("historical_report_subpage_cutoff", linkName)
        weekdays = app.getCompositeConfigValue("historical_report_subpage_weekdays", linkName)
        self.selectedTags = tags[-cutoff:]
        if len(weekdays) > 0:
            self.selectedTags = filter(lambda tag: getWeekDay(tag) in weekdays, self.selectedTags)
    

class SelectorByMonth(BaseSelector):
    @classmethod
    def makeInstances(cls, tags):
        allSelectors = {}
        for tag in tags:
            month = tag[2:9]
            allSelectors.setdefault(month, SelectorByMonth(month)).add(tag)
        return sorted(allSelectors.values())
    def __init__(self, month):
        super(SelectorByMonth, self).__init__(month, "_all_" + month)
    def getMonthTime(self):
        return time.mktime(time.strptime(self.linkName, "%b%Y"))
    def __cmp__(self, other):
        return cmp(self.getMonthTime(), other.getMonthTime())
    def __eq__(self, other):
        return self.linkName == other.linkName
    def __hash__(self):
        return self.linkName.__hash__()
