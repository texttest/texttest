#
# This file contains two scripts, ExtractTestStates and GenererateTestStatus.
# The purpose of these scripts is to generate a historical overview (in HTML) of how
# the tests has operated over a period of time.
#
# The second script reads all the data in the testoverview repository and build up the relevant
# HTML pages. These are saved in the directory pointed out by the testoverview_pages config value.
#
#   texttest -a <app> -s testoverview.GenererateTestStatus <major versions> <minor versions> 
#

import os, performance, plugins, respond, sys, string, time, types, shutil
from cPickle import Pickler, Unpickler, UnpicklingError

try:
    import HTMLgen, HTMLcolors
except:
    raise BadConfigError, "Python modules HTMLgen and/or HTMLcolors not found."

class GenererateTestStatus(plugins.Action):
    def __init__(self, args):
        self.majorVersions = args[0].split(",")
        self.minorVersions = args[1].split(",")
        if len(args) == 3:
            self.subVersions = args[2].split(",")
        else:
            self.subVersions = None
        self.diag = plugins.getDiagnostics("GenerateTestStatus")
    def setUpApplication(self, app):
        self.testStateRepository = app.getCompositeConfigValue("batch_result_repository", "default")
        if not os.path.isdir(self.testStateRepository):
            raise plugins.TextTestError, "Testoverview repository " + self.testStateRepository + " does not exist"
        pageTopDir = app.getConfigValue("testoverview_pages")
        self.pageDir = os.path.join(pageTopDir, app.name)
        plugins.ensureDirectoryExists(self.pageDir)
            
        for majorVersion in self.majorVersions:
            self.pagesOverview = {}
            foundMinorVersions = HTMLgen.Container()
            details = TestDetails()
            self.pagesDetails = {}
            usedSelectors = {}
            for minorVersion in self.minorVersions:
                version = majorVersion + "." + minorVersion
                self.diag.info("Generating " + version)
                loggedTests = {}
                tagsFound = []
                categoryHandler = CategoryHandler()
                
                baseDir = os.path.join(self.testStateRepository, app.name, version)
                self.loadTestStates(baseDir, categoryHandler, loggedTests, tagsFound)
                if self.subVersions:
                    for subVersion in self.subVersions:
                        dir = baseDir + "." + subVersion
                        self.loadTestStates(dir, categoryHandler, loggedTests, tagsFound, subVersion)
                if len(loggedTests.keys()) > 0:
                    tagsFound.sort(lambda x, y: cmp(self.getTagTimeInSeconds(x), self.getTagTimeInSeconds(y)))
                    selectors = [ SelectorLast6Days(tagsFound), SelectorAll(tagsFound), SelectorWeekend(tagsFound) ]
                    linkFromDetailsToOverview = {}
                    for sel in selectors:
                        if not usedSelectors.has_key(repr(sel)):
                            usedSelectors[repr(sel)] = sel.getFileNameExtension()
                        linkFromDetailsToOverview[repr(sel)] = self.getOverviewPageName(majorVersion, sel.getFileNameExtension())
                        testTable = TestTable()
                        table = testTable.generate(categoryHandler, majorVersion, version, loggedTests, sel.getSelectedTags())
                        self.addOverviewPages(sel.getFileNameExtension(), version, table, app)
                    det = details.generate(categoryHandler, version, tagsFound, linkFromDetailsToOverview)
                    self.addDetailPages(app, det)
                    foundMinorVersions.append(HTMLgen.Href("#" + version, minorVersion))
            selContainer = HTMLgen.Container()
            for sel in usedSelectors.keys():
                selContainer.append(HTMLgen.Href(self.getOverviewPageName(majorVersion, usedSelectors[sel]), sel))
            for sel in self.pagesOverview.keys():
                self.pagesOverview[sel].prepend(HTMLgen.Heading(2, selContainer, align = 'center'))
                self.pagesOverview[sel].prepend(HTMLgen.Heading(1, HTMLgen.Container(HTMLgen.Text("Versions " + majorVersion + "-"),
                                                                          foundMinorVersions), align = 'center'))
                self.pagesOverview[sel].prepend(HTMLgen.Heading(1, "Test results for ", repr(app), align = 'center'))
            
            self.writePages(app, majorVersion)
    def loadTestStates(self, dir, categoryHandler, loggedTests, tagsFound, subVersion = None):
        if os.path.isdir(dir):
            for entries in os.listdir(dir):
                self.traverseDirectories(categoryHandler, loggedTests, tagsFound, os.path.join(dir, entries), subVersion)
    def traverseDirectories(self, categoryHandler, loggedTests, tagsFound, dir, subVersion = None):
        for entries in os.listdir(dir):
            if os.path.isdir(os.path.join(dir, entries)):
                self.traverseDirectories(categoryHandler, loggedTests, tagsFound, os.path.join(dir, entries), subVersion)
            elif entries.startswith("teststate"):
                stateFile = os.path.join(dir, entries) 
                file = open(stateFile)
                try:
                    unpickler = Unpickler(file)
                    state = unpickler.load()
                    state.ensureCompatible()
                    tag = entries.split("_")[-1]
                    if tagsFound.count(tag) == 0:
                        tagsFound.append(tag)
                    key = self.getTestIdentifier(dir)
                    keySubVersion = subVersion
                    if not keySubVersion:
                        keySubVersion = "None"
                    if not loggedTests.has_key(keySubVersion):
                        loggedTests[keySubVersion] = {}
                    if not loggedTests[keySubVersion].has_key(key):
                        loggedTests[keySubVersion][key] = {}
                    loggedTests[keySubVersion][key][tag] = state
                    categoryHandler.registerInCategory(tag, key, state, keySubVersion)
                except UnpicklingError:
                    print "unpickling error"
                except EOFError:
                    print "EOFError in ",file
                    print "Ignoring this file"
                except AttributeError:
                    print "AttrError for ", file
            else:
                print "Unknown file", entries
    def addOverviewPages(self, item, version, table, app):
        if not self.pagesOverview.has_key(item):
            self.pagesOverview[item] = HTMLgen.SimpleDocument(title="Test results for " + repr(app),
                                                              style = "body,td,th {color: #000000;font-size: 11px;font-family: Helvetica;}")
        self.pagesOverview[item].append(HTMLgen.Name(version))
        self.pagesOverview[item].append(table)
    def addDetailPages(self, app, details):
        for tag in details.keys():
            if not self.pagesDetails.has_key(tag):
                self.pagesDetails[tag] = HTMLgen.SimpleDocument()
                self.pagesDetails[tag].append(HTMLgen.Heading(1, tag + " - detailed test results for application ", app.name, align = 'center'))
            self.pagesDetails[tag].append(details[tag])
    def writePages(self, app, majorVersion):
        for sel in self.pagesOverview.keys():
            self.pagesOverview[sel].write(os.path.join(self.pageDir, self.getOverviewPageName(majorVersion, sel)))
        for tag in self.pagesDetails.keys():
            page = self.pagesDetails[tag]
            page.write(os.path.join(self.pageDir, getDetailPageName(majorVersion, tag)))
    def getTestIdentifier(self, dir):
        return string.join(dir.split(os.sep)[len(self.testStateRepository.split(os.sep)) + 2:])
    def getTagTimeInSeconds(self, tag):
        return time.mktime(time.strptime(tag, "%d%b%Y"))
    def getOverviewPageName(self, majorVersion, sel):
        return "test_" + majorVersion + sel + ".html"

class TestTable:
    def generate(self, categoryHandler, majorVersion, version, loggedTests, tagsFound):
        t = HTMLgen.TableLite(border=0, cellpadding=4, cellspacing=2,width="100%")
        t.append(self.generateTableHead(majorVersion, version, tagsFound))

        table = []
        subVersions = loggedTests.keys()
        for subVersion in subVersions:
            tests = loggedTests[subVersion].keys()
            tests.sort()
            # Add an extra line in the table only if there are several versions.
            if len(subVersions) > 1:
                if subVersion != "None":
                    subVersionName = version + "." + subVersion
                else:
                    subVersionName = version
                table.append(HTMLgen.TR() + [HTMLgen.TH(subVersionName, colspan = len(tagsFound) + 1,
                                                    bgcolor = HTMLcolors.GRAY1 )])
            for test in tests:
                results = loggedTests[subVersion][test]
                row = [ HTMLgen.TD(HTMLgen.Container(HTMLgen.Name(version + test + subVersion), test), bgcolor = "#FFFFCC") ]
                for tag in tagsFound:
                    if results.has_key(tag):
                        state = results[tag]
                        type, detail = state.getTypeBreakdown()
                        category = state.category # Strange but correct..... (getTypeBreakdown gives "wrong" category)
                        fgcol, bgcol = self.getColors(category, detail)
                        if category == "success":
                            cellContaint =  HTMLgen.Font(repr(state) + detail, color = fgcol)
                        else:
                            cellContaint = HTMLgen.Href(getDetailPageName(majorVersion, tag) + "#" + version + test + subVersion,
                                                        HTMLgen.Font(repr(state) + detail, color = fgcol))
                    else:
                        bgcol = HTMLcolors.GRAY2
                        cellContaint = "No results avaliable"
                    row.append(HTMLgen.TD(cellContaint, bgcolor = bgcol))
                body = HTMLgen.TR()
                body = body + row
                table.append(body)
        table = categoryHandler.generateSummaries(majorVersion, version, tagsFound) + table
        t.append(table)
        t.append(HTMLgen.BR())
        return t
    def getColors(self, type, detail):
        bgcol = "#FF3118"
        fgcol = "BLACK"
        if type == "faster" or type == "slower":
            bgcol = "#FFC6A5"
            result = self.getPercent(detail)
            if result[0] and result[1] >= 5:
                fgcol = HTMLcolors.RED6
        elif type == "smaller" or type == "larger":
            result = self.getPercent(detail)
            if result[0] and result[1] >= 3:
                fgcol = HTMLcolors.RED6
            bgcol = HTMLcolors.PINK
        elif type == "success":
            bgcol = "#CEEFBD"
        return fgcol, bgcol
    def generateTableHead(self, majorVersion, version, tagsFound):
        head = [ HTMLgen.TH("Test") ]
        for tag in tagsFound:
            tagColor = HTMLcolors.BLACK
            year, month, day, hour, minute, second, wday, yday, dummy = time.strptime(tag, "%d%b%Y")
            if wday == 4: # Weekend jobs start Friday.
                tagColor = HTMLcolors.RED
            head.append(HTMLgen.TH(HTMLgen.Href(getDetailPageName(majorVersion, tag), HTMLgen.Font(tag, color = tagColor))))
        heading = HTMLgen.TR()
        heading = heading + head
        cap = HTMLgen.Caption(HTMLgen.Font(version, size = 10))
        return HTMLgen.Container(cap, heading)
    def getPercent(self, detail):
        potentialNumber = detail.split("%")[0] # Bad: Hard coded interpretation of texttest print-out.
        if potentialNumber.isdigit():
            return (1, int(potentialNumber))
        else:
            print "Warning: Failed to get percentage from",detail
            return (0, 0)
        
class TestDetails:
    def generate(self, categoryHandler, version, tags, linkFromDetailsToOverview):
        detailsContainers = {}
        for tag in tags:
            container = detailsContainers[tag] = HTMLgen.Container()
            categories = categoryHandler.testsInCategory[tag]
            container.append(HTMLgen.HR())
            container.append(HTMLgen.Heading(2, version + ": " + categoryHandler.generateSummary(categories)))
            for cat in categories.keys():
                test, state, subVersion = categories[cat][0]
                shortDescr, longDescr = getCategoryDescription(state, cat)
                fullDescription = self.getFullDescription(categories[cat], version, linkFromDetailsToOverview)
                if fullDescription:
                    container.append(HTMLgen.Name(version + longDescr))
                    container.append(HTMLgen.Heading(3, "Detailed information for the tests that " + longDescr + ":"))
                    container.append(fullDescription)
        return detailsContainers
    def getFullDescription(self, tests, version, linkFromDetailsToOverview):
        fullText = HTMLgen.Container()
        textFound = None
        for test in tests:
            testName, state, subVersion = test
            freeText = state.freeText
            if freeText:
                textFound = 1
                fullText.append(HTMLgen.Name(version + testName + subVersion))
                fullText.append(HTMLgen.Heading(4, HTMLgen.Container("TEST " + repr(state) + " " + testName + " (",
                                                                     self.getLinksToOverview(version, testName, subVersion, linkFromDetailsToOverview)),")"))
                freeText = string.replace(freeText, "\n", "<BR>")
                fullText.append(HTMLgen.RawText(freeText))
        if textFound:
            return fullText
        else:
            return None
    def getLinksToOverview(self, version, testName, subVersion, linkFromDetailsToOverview):
        links = HTMLgen.Container()
        for sel in linkFromDetailsToOverview:
            links.append(HTMLgen.Href(linkFromDetailsToOverview[sel] + "#" + version + testName + subVersion, sel))
        return links
        
class CategoryHandler:
    def __init__(self):
        self.testsInCategory = {}
    def registerInCategory(self, tag, test, state, subVersion):
        if not self.testsInCategory.has_key(tag):
            self.testsInCategory[tag] = {}
        if not self.testsInCategory[tag].has_key(state.category):
            self.testsInCategory[tag][state.category] = []
        self.testsInCategory[tag][state.category].append((test, state, subVersion))
    def generateSummaries(self, majorVersion, version, tags):
        row = [ HTMLgen.TD("Summary", bgcolor = HTMLcolors.GRAY1) ]
        for tag in tags:
            summary = self.generateSummaryHTML(tag, majorVersion, version, self.testsInCategory[tag])
            row.append(HTMLgen.TD(summary, bgcolor = HTMLcolors.GRAY1))
        return HTMLgen.TR() + row
    def generateSummaryHTML(self, tag, majorVersion, version, categories):
        summary = HTMLgen.Container()
        numTests = 0
        for cat in categories.keys():
            test, state, subVersion = categories[cat][0]
            shortDescr, longDescr = getCategoryDescription(state, cat)
            if cat == "success":
                summary.append(HTMLgen.Text("%d %s" % (len(categories[cat]), shortDescr)))
            else:
                summary.append(HTMLgen.Href(getDetailPageName(majorVersion, tag) + "#" + version + longDescr,
                                            HTMLgen.Text("%d %s" % (len(categories[cat]), shortDescr))))
            numTests += len(categories[cat])
        return HTMLgen.Container(HTMLgen.Text("%d tests: " % numTests), summary)
    def generateSummary(self, categories):
        summary = ""
        numTests = 0
        for cat in categories.keys():
            test, state, subVersion = categories[cat][0]
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
def getDetailPageName(majorVersion, tag):
    return "test_" + majorVersion + "_" + tag + ".html"


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
    
class SelectorWeekend(Selector):
    def __init__(self, tags):
        self.selectedTags = []
        for tag in tags:
            year, month, day, hour, minute, second, wday, yday, dummy = time.strptime(tag, "%d%b%Y")
            if wday == 4:
                self.selectedTags.append(tag)
    def getFileNameExtension(self):
        return "_weekend"
    def __repr__(self):
        return "Weekend"
