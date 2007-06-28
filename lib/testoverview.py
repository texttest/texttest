# Code to generate HTML report of historical information. This report generated
# either via the -coll flag, or via -s 'batch.GenerateHistoricalReport <batchid>'

import os, performance, plugins, respond, sys, string, time, types, shutil, HTMLgen, HTMLcolors, re
from cPickle import Pickler, loads, UnpicklingError
from ndict import seqdict
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
    displayText = string.join(tag.split("_")[1:], "_")
    if displayText:
        return displayText
    else:
        return tag

class GenerateWebPages:
    def __init__(self, pageAppName, pageVersion, pageDir, extraVersions):
        self.pageAppName = pageAppName
        self.pageVersion = pageVersion
        self.extraVersions = extraVersions
        self.pageDir = pageDir
        self.pagesOverview = seqdict()
        self.pagesDetails = seqdict()
        self.diag = plugins.getDiagnostics("GenerateWebPages")
    def createTestTable(self):
        # Hook for configurations to inherit from
        return TestTable()
    def getSelectorClasses(self):
        return [ SelectorLast6Days, SelectorAll ]
    def generate(self, repositoryDirs):            
        foundMinorVersions = HTMLgen.Container()
        details = TestDetails()
        usedSelectors = seqdict()
        for repositoryDir in repositoryDirs:
            version = os.path.basename(repositoryDir)
            self.diag.info("Generating " + version)
            loggedTests = seqdict()
            tagsFound = []
            categoryHandler = CategoryHandler()
            self.processTestStateFiles(categoryHandler, loggedTests, tagsFound, repositoryDir)
    
            if len(loggedTests.keys()) > 0:
                tagsFound.sort(lambda x, y: cmp(self.getTagTimeInSeconds(x), self.getTagTimeInSeconds(y)))
                selectors = map(lambda selClass : selClass(tagsFound), self.getSelectorClasses())
                linkFromDetailsToOverview = seqdict()
                for sel in selectors:
                    if not usedSelectors.has_key(repr(sel)):
                        usedSelectors[repr(sel)] = sel.getFileNameExtension()
                    linkFromDetailsToOverview[repr(sel)] = self.getOverviewPageName(sel.getFileNameExtension())
                    testTable = self.createTestTable()
                    table = testTable.generate(categoryHandler, self.pageVersion, version, loggedTests, sel.getSelectedTags())
                    self.addOverviewPages(sel.getFileNameExtension(), version, table)
                det = details.generate(categoryHandler, version, tagsFound, linkFromDetailsToOverview)
                self.addDetailPages(det)
                foundMinorVersions.append(HTMLgen.Href("#" + version, self.removePageVersion(version)))
        selContainer = HTMLgen.Container()
        for selKey, usedSel in usedSelectors.items():
            selContainer.append(HTMLgen.Href(self.getOverviewPageName(usedSel), selKey))
        for page in self.pagesOverview.values():
            page.prepend(HTMLgen.Heading(2, selContainer, align = 'center'))
            page.prepend(HTMLgen.Heading(1, HTMLgen.Container(HTMLgen.Text("Versions " + self.pageVersion + "-"),
                                                                      foundMinorVersions), align = 'center'))
            page.prepend(HTMLgen.Heading(1, "Test results for ", self.pageAppName, align = 'center'))

        self.writePages()
    def processTestStateFiles(self, categoryHandler, loggedTests, tagsFound, repositoryDir):
        dirs = [ repositoryDir ]
        for extra in self.extraVersions:
            extraDir = repositoryDir + "." + extra
            if os.path.isdir(extraDir):
                dirs.append(extraDir)
        for dir in dirs:
            for testStateFile in self.findTestStateFiles(dir):
                self.processTestStateFile(testStateFile, categoryHandler, loggedTests, tagsFound, dir)
    def findTestStateFiles(self, dir):
        allFiles = []
        for root, dirs, files in os.walk(dir):
            currFiles = filter(lambda file: file.startswith("teststate"), files)
            allFiles += [ os.path.join(root, file) for file in currFiles ]
        allFiles.sort()
        return allFiles
    def removePageVersion(self, version):
        leftVersions = []
        pageSubVersions = self.pageVersion.split(".")
        for subVersion in version.split("."):
            if not subVersion in pageSubVersions:
                leftVersions.append(subVersion)
        return string.join(leftVersions, ".")
    def processTestStateFile(self, stateFile, categoryHandler, loggedTests, tagsFound, repository):
        state = self.readState(stateFile)
        if not state:
            print "Ignoring file at", stateFile
            return

        tag = os.path.basename(stateFile).replace("teststate_", "")
        if tagsFound.count(tag) == 0:
            tagsFound.append(tag)
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
        for version in os.path.basename(repository).split("."):
            if version in self.extraVersions:
                return version
        return "None"
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
    def addOverviewPages(self, item, version, table):
        if not self.pagesOverview.has_key(item):
            pageOverviewTitle = "Test results for " + self.pageAppName + " - version " + self.pageVersion
            self.pagesOverview[item] = HTMLgen.SimpleDocument(title = pageOverviewTitle,
                                                              style = "body,td,th {color: #000000;font-size: 11px;font-family: Helvetica;}")
        self.pagesOverview[item].append(HTMLgen.Name(version))
        self.pagesOverview[item].append(table)
    def addDetailPages(self, details):
        for tag in details.keys():
            if not self.pagesDetails.has_key(tag):
                tagText = getDisplayText(tag)
                pageDetailTitle = "Detailed test results for " + self.pageAppName + " - version " + \
                                  self.pageVersion + ": " + tagText
                self.pagesDetails[tag] = HTMLgen.SimpleDocument(title = pageDetailTitle)
                self.pagesDetails[tag].append(HTMLgen.Heading(1, tagText + " - detailed test results for ", self.pageAppName, align = 'center'))
            self.pagesDetails[tag].append(details[tag])
    def writePages(self):
        print "Writing overview pages..."
        for sel, page in self.pagesOverview.items():
            pageName = self.getOverviewPageName(sel)
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
        try:
            return time.mktime(time.strptime(timePart, "%d%b%Y"))
        except ValueError:
            # As the Python docs say, strptime is buggy on some platforms (e.g. parisc)
            # Seems to work if you insert spaces though...
            spacedTimePart = timePart[:2] + " " + timePart[2:5] + " " + timePart[5:]
            return time.mktime(time.strptime(spacedTimePart, "%d %b %Y"))
    def getOverviewPageName(self, sel):
        return "test_" + self.pageVersion + sel + ".html"

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
        if extraVersion != "None":
            extraVersionName = version + "." + extraVersion
        else:
            extraVersionName = version
        bgColour = colourFinder.find("column_header_bg")
        columnHeader = HTMLgen.TH(extraVersionName, colspan = len(tagsFound) + 1, bgcolor=bgColour)
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
            freeText = freeText.replace("<", "&lt;").replace(">", "&gt;")
            fullText.append(HTMLgen.RawText("<PRE>" + freeText + "</PRE>"))
            if len(tests) > 1:
                for line in self.getTestLines(tests, version, linkFromDetailsToOverview):
                    fullText.append(line)                            
        return fullText
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
        for sel, value in linkFromDetailsToOverview.items():
            links.append(HTMLgen.Href(value + "#" + version + testName + extraVersion, sel))
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


class Selector:
    def __init__(self, tags):
        self.selectedTags = tags
    def getSelectedTags(self):
        return self.selectedTags
    def getFileNameExtension(self):
        return ""
    def __repr__(self):
        return "default"

class SelectorLast6Days(Selector):
    def __init__(self, tags):
        if len(tags) > 6:
            self.selectedTags = tags[-6:]
        else:
            self.selectedTags = tags
    def __repr__(self):
        return "Last six days"

class SelectorAll(Selector):
    def getFileNameExtension(self):
        return "_all"
    def __repr__(self):
        return "All"
