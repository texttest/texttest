# Code to generate HTML report of historical information. This report generated
# either via the -coll flag, or via -s 'batch.GenerateHistoricalReport <batchid>'

import os, plugins, time, re, HTMLgen, HTMLcolors, operator
from cPickle import Pickler, loads, UnpicklingError
from ndict import seqdict
from sets import Set
from glob import glob
HTMLgen.PRINTECHO = 0

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
    def getDefaultDict(self):
        colours = {}
        colours["column_header_fg"] = "black"
        colours["column_header_bg"] = "gray1"
        colours["row_header_bg"] = "#FFFFCC"
        colours["performance_fg"] = "red6"
        colours["memory_bg"] = "pink"
        colours["success_bg"] = "#CEEFBD"
        colours["failure_bg"] = "#FF3118"
        colours["no_results_bg"] = "gray2"
        colours["performance_bg"] = "#FFC6A5"
        colours["test_default_fg"] = "black"
        return colours

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
    def __init__(self, pageTitle, pageVersion, pageDir, extraVersions, colourDict, buildAllPage):
        self.pageTitle = pageTitle
        self.pageVersion = pageVersion
        self.extraVersions = extraVersions
        self.pageDir = pageDir
        self.buildAllPage = buildAllPage
        self.pagesOverview = seqdict()
        self.pagesDetails = seqdict()
        self.diag = plugins.getDiagnostics("GenerateWebPages")
        colourFinder.setColourDict(colourDict)
    def createTestTable(self):
        # Hook for configurations to inherit from
        return TestTable()
    def getSelectorClasses(self):
        if self.buildAllPage:
            return [ SelectorLast6Days, SelectorAll ]
        else:
            return [ SelectorLast6Days ]
    def generate(self, repositoryDirs):            
        foundMinorVersions = HTMLgen.Container()
        details = TestDetails()
        allMonthSelectors = Set()
        for repositoryDir, version in repositoryDirs:
            self.diag.info("Generating " + version)
            allFiles, tags = self.findTestStateFilesAndTags(repositoryDir)
            if len(allFiles) > 0:
                selectors = [ cls(tags) for cls in self.getSelectorClasses() ]
                monthSelectors = SelectorByMonth.makeInstances(tags, self.buildAllPage)
                allMonthSelectors.update(monthSelectors)
                allSelectors = selectors + list(reversed(monthSelectors))
                # If we already have month pages, we only regenerate the current one
                if self.buildAllPage or len(self.getExistingMonthPages()) == 0:
                    selectors = allSelectors
                else:
                    selectors.append(monthSelectors[-1])
                    tags = list(reduce(Set.union, (Set(selector.selectedTags) for selector in selectors), Set()))
                    tags.sort(self.compareTags)

                loggedTests = seqdict()
                categoryHandler = CategoryHandler()
                for stateFile, repository in allFiles:
                    self.processTestStateFile(stateFile, categoryHandler, loggedTests, repository, tags)
                        
                for sel in selectors:
                    self.generateAndAddTable(categoryHandler, version, loggedTests, sel)

                # put them in reverse order, most relevant first
                linkFromDetailsToOverview = [ sel.getLinkInfo(self.pageVersion) for sel in allSelectors ]
                det = details.generate(categoryHandler, version, tags, linkFromDetailsToOverview)
                self.addDetailPages(det)
                foundMinorVersions.append(HTMLgen.Href("#" + version, self.removePageVersion(version)))

        selContainer = HTMLgen.Container()
        for selClass in self.getSelectorClasses():
            target, linkName = selClass().getLinkInfo(self.pageVersion)
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

    def findAllRepositories(self, repositoryDir):
        dirs = [ repositoryDir ]
        for extra in self.extraVersions:
            extraDir = repositoryDir + "." + extra
            if os.path.isdir(extraDir):
                dirs.append(extraDir)
        return dirs

    def compareTags(self, x, y):
        timeCmp = cmp(self.getTagTimeInSeconds(x), self.getTagTimeInSeconds(y))
        if timeCmp:
            return timeCmp
        else:
            return cmp(x, y) # If the timing is the same, sort alphabetically
        
    def findTestStateFilesAndTags(self, repositoryDir):
        allFiles = []
        allTags = Set()
        for dir in self.findAllRepositories(repositoryDir):
            for root, dirs, files in os.walk(dir):
                for file in files:
                    if file.startswith("teststate_"):
                        allFiles.append((os.path.join(root, file), dir))
                        allTags.add(file.replace("teststate_", ""))
                                
        return allFiles, sorted(allTags, self.compareTags)
                          
    def processTestStateFile(self, stateFile, categoryHandler, loggedTests, repository, useTags):
        tag = os.path.basename(stateFile).replace("teststate_", "")
        if len(useTags) > 0 and tag not in useTags:
            return
        state = self.readState(stateFile)
        key = self.getTestIdentifier(stateFile, repository)
        self.diag.info(tag + " : reading " + key)
        keyExtraVersion = self.findExtraVersion(repository)
        if not loggedTests.has_key(keyExtraVersion):
            loggedTests[keyExtraVersion] = seqdict()
        if not loggedTests[keyExtraVersion].has_key(key):
            loggedTests[keyExtraVersion][key] = seqdict()

        loggedTests[keyExtraVersion][key][tag] = state
        categoryHandler.registerInCategory(tag, key, state, keyExtraVersion)

    def findExtraVersion(self, repository):
        versions = os.path.basename(repository).split(".")
        for i in xrange(len(versions)):
            version = ".".join(versions[i:])
            if version in self.extraVersions:
                return version
        return ""

    def readState(self, stateFile):
        file = open(stateFile, "rU")
        try:
            # Would like to do load(file) here... but it doesn't work, see Python bug 1724366
            # http://sourceforge.net/tracker/index.php?func=detail&aid=1724366&group_id=5470&atid=105470
            state = loads(file.read())
            if isinstance(state, plugins.TestState):
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

    def generateAndAddTable(self, categoryHandler, version, loggedTests, selector):
        testTable = self.createTestTable()
        table = testTable.generate(categoryHandler, self.pageVersion, version, loggedTests, selector.selectedTags)
        fileName = selector.getLinkInfo(self.pageVersion)[0]
        self.addOverviewPages(fileName, version, table)
    
    def addOverviewPages(self, fileName, version, table):
        if not self.pagesOverview.has_key(fileName):
            style = "body,td,th {color: #000000;font-size: 11px;font-family: Helvetica;}"
            title = TitleWithDateStamp("Test results for " + self.pageTitle) 
            self.pagesOverview[fileName] = HTMLgen.SimpleDocument(title=title, style=style)
        self.pagesOverview[fileName].append(HTMLgen.Name(version))
        self.pagesOverview[fileName].append(table)
        
    def addDetailPages(self, details):
        for tag in details.keys():
            if not self.pagesDetails.has_key(tag):
                tagText = getDisplayText(tag)
                pageDetailTitle = "Detailed test results for " + self.pageTitle + ": " + tagText
                self.pagesDetails[tag] = HTMLgen.SimpleDocument(title=TitleWithDateStamp(pageDetailTitle))
                self.pagesDetails[tag].append(HTMLgen.Heading(1, tagText + " - detailed test results for ", self.pageTitle, align = 'center'))
            self.pagesDetails[tag].append(details[tag])
    def writePages(self):
        print "Writing overview pages..."
        for pageName, page in self.pagesOverview.items():
            page.write(os.path.join(self.pageDir, pageName))
            print "wrote: '" + pageName + "'"
        print "Writing detail pages..."
        for tag, page in self.pagesDetails.items():
            pageName = getDetailPageName(self.pageVersion, tag)
            page.write(os.path.join(self.pageDir, pageName))
            print "wrote: '" + pageName + "'"
    def getTestIdentifier(self, stateFile, repository):
        dir = os.path.dirname(stateFile)
        return dir.replace(repository + os.sep, "").replace(os.sep, " ")
    def getTagTimeInSeconds(self, tag):
        timePart = tag.split("_")[0]
        return time.mktime(time.strptime(timePart, "%d%b%Y"))

class TestTable:
    def generate(self, categoryHandler, pageVersion, version, loggedTests, tagsFound):
        table = HTMLgen.TableLite(border=0, cellpadding=4, cellspacing=2,width="100%")
        table.append(self.generateTableHead(pageVersion, version, tagsFound))
        table.append(categoryHandler.generateSummaries(pageVersion, version, tagsFound))
        extraVersions = loggedTests.keys()
        for extraVersion in extraVersions:
            # Add an extra line in the table only if there are several versions.
            if len(extraVersions) > 1:
                table.append(self.generateExtraVersionHeader(extraVersion, version, tagsFound))

            tests = loggedTests[extraVersion].keys()
            tests.sort()
            for test in tests:
                results = loggedTests[extraVersion][test]
                table.append(self.generateTestRow(test, pageVersion, version, extraVersion, results, tagsFound))

        table.append(HTMLgen.BR())
        return table
    def generateExtraVersionHeader(self, extraVersion, version, tagsFound):
        fullName = version
        if len(extraVersion):
            fullName += "." + extraVersion
        bgColour = colourFinder.find("column_header_bg")
        columnHeader = HTMLgen.TH(fullName, colspan = len(tagsFound) + 1, bgcolor=bgColour)
        return HTMLgen.TR(columnHeader)
    def generateTestRow(self, test, pageVersion, version, extraVersion, results, tagsFound):
        bgColour = colourFinder.find("row_header_bg")
        row = [ HTMLgen.TD(HTMLgen.Container(HTMLgen.Name(version + test + extraVersion), test), bgcolor=bgColour) ]
        for tag in tagsFound:
            if results.has_key(tag):
                state = results[tag]
                type, detail = state.getTypeBreakdown()
                category = state.category # Strange but correct..... (getTypeBreakdown gives "wrong" category)
                fgcol, bgcol = self.getColors(category, detail)
                filteredState = self.filterState(repr(state))
                if category == "success":
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
    
    def getColors(self, type, detail):
        fgcol = colourFinder.find("test_default_fg")
        if type == "faster" or type == "slower":
            bgcol = colourFinder.find("performance_bg")
            fgcol = colourFinder.find("performance_fg")
        elif type == "smaller" or type == "larger":
            bgcol = colourFinder.find("memory_bg")
            fgcol = colourFinder.find("performance_fg")
        elif type == "success":
            bgcol = colourFinder.find("success_bg")
        else:
            bgcol = colourFinder.find("failure_bg")
        return fgcol, bgcol
    def generateTableHead(self, pageVersion, version, tagsFound):
        head = [ HTMLgen.TH("Test") ]
        for tag in tagsFound:
            tagColour = self.findTagColour(tag)
            head.append(HTMLgen.TH(HTMLgen.Href(getDetailPageName(pageVersion, tag), HTMLgen.Font(getDisplayText(tag), color=tagColour))))
        heading = HTMLgen.TR()
        heading = heading + head
        cap = HTMLgen.Caption(HTMLgen.Font(version, size = 10))
        return HTMLgen.Container(cap, heading)
    def findTagColour(self, tag):
        return colourFinder.find("column_header_fg")
        
class TestDetails:
    def generate(self, categoryHandler, version, tags, linkFromDetailsToOverview):
        detailsContainers = seqdict()
        for tag in tags:
            container = detailsContainers[tag] = HTMLgen.Container()
            categories = categoryHandler.testsInCategory[tag]
            container.append(HTMLgen.HR())
            container.append(HTMLgen.Heading(2, version + ": " + categoryHandler.generateSummary(categories)))
            for cat in categories.keys():
                test, state, extraVersion = categories[cat][0]
                shortDescr, longDescr = getCategoryDescription(state, cat)
                fullDescription = self.getFullDescription(categories[cat], version, linkFromDetailsToOverview)
                if fullDescription:
                    container.append(HTMLgen.Name(version + longDescr))
                    container.append(HTMLgen.Heading(3, "Detailed information for the tests that " + longDescr + ":"))
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
    def registerInCategory(self, tag, test, state, extraVersion):
        if not self.testsInCategory.has_key(tag):
            self.testsInCategory[tag] = seqdict()
        if not self.testsInCategory[tag].has_key(state.category):
            self.testsInCategory[tag][state.category] = []
        self.testsInCategory[tag][state.category].append((test, state, extraVersion))
    def generateSummaries(self, pageVersion, version, tags):
        bgColour = colourFinder.find("column_header_bg")
        row = [ HTMLgen.TD("Summary", bgcolor = bgColour) ]
        for tag in tags:
            summary = self.generateSummaryHTML(tag, pageVersion, version, self.testsInCategory[tag])
            row.append(HTMLgen.TD(summary, bgcolor = bgColour))
        return HTMLgen.TR(*row)
    def generateSummaryHTML(self, tag, pageVersion, version, categories):
        summary = HTMLgen.Container()
        numTests = 0
        for cat in categories.keys():
            test, state, extraVersion = categories[cat][0]
            shortDescr, longDescr = getCategoryDescription(state, cat)
            if cat == "success":
                summary.append(HTMLgen.Text("%d %s" % (len(categories[cat]), shortDescr)))
            else:
                summary.append(HTMLgen.Href(getDetailPageName(pageVersion, tag) + "#" + version + longDescr,
                                            HTMLgen.Text("%d %s" % (len(categories[cat]), shortDescr))))
            numTests += len(categories[cat])
        return HTMLgen.Container(HTMLgen.Text("%d tests: " % numTests), summary)
    def generateSummary(self, categories):
        summary = ""
        numTests = 0
        for cat in categories.keys():
            test, state, extraVersion = categories[cat][0]
            shortDescr, longDescr = getCategoryDescription(state, cat)
            summary += "%d %s " % (len(categories[cat]), shortDescr)
            numTests += len(categories[cat])
        summary = "%d tests: " % numTests + summary
        return summary

def getCategoryDescription(state, cat):
    if state.categoryDescriptions.has_key(cat):
        shortDescr, longDescr = state.categoryDescriptions[cat]
    else:
        shortDescr, longDescr = cat, cat
    return shortDescr, longDescr
def getDetailPageName(pageVersion, tag):
    return "test_" + pageVersion + "_" + tag + ".html"


class Selector(object):
    def __init__(self, tags=[]):
        self.selectedTags = tags
    def getLinkInfo(self, pageVersion):
        return "test_" + pageVersion + self.getFileNameExtension() + ".html", self.linkName()
    def getFileNameExtension(self):
        return ""
    def linkName(self):
        return ""

class SelectorLast6Days(Selector):
    def __init__(self, tags=[]):
        if len(tags) > 6:
            self.selectedTags = tags[-6:]
        else:
            self.selectedTags = tags
            
    def linkName(self):
        return "Last six days"

class SelectorAll(Selector):
    def linkName(self):
        return "All"
    def getFileNameExtension(self):
        return "_all"

class SelectorByMonth(Selector):
    @classmethod
    def makeInstances(cls, tags, buildAllPage):
        if buildAllPage:
            return [] # Don't do the months if we build an All page currently...
        allSelectors = {}
        for tag in tags:
            month = tag[2:9]
            allSelectors.setdefault(month, SelectorByMonth(month)).add(tag)
        return sorted(allSelectors.values())
    def __init__(self, month):
        self.month = month
        self.selectedTags = []
    def add (self, tag):
        self.selectedTags.append(tag)
    def getMonthTime(self):
        return time.mktime(time.strptime(self.month, "%b%Y"))
    def __cmp__(self, other):
        return cmp(self.getMonthTime(), other.getMonthTime())
    def linkName(self):
        return self.month
    def getFileNameExtension(self):
        return "_all_" + self.month
    def __eq__(self, other):
        return self.month == other.month
    def __hash__(self):
        return self.month.__hash__()
