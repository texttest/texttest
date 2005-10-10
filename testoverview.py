#
# This file contains two scripts, ExtractTestStates and GenererateTestStatus.
# The purpose of these scripts is to generate a historical overview (in HTML) of how
# the tests has operated over a period of time.
#
# The first script scans through the texttesttmp directory for the specified user
# and copies the relevant data to the testoverview repository. The testoverview repository
# is specified by the config value testoverview_repository that must be set by the application.
#
#   texttest -a <app> -s testoverview.ExtractTestStates <username to extract from, typically nightjob>
#            <major versions:master,12,11 etc> <minor versions, arch:i386_linux,sparc etc>
#
# The second script reads all the data in the testoverview repository and build up the relevant
# HTML pages. These are saved in the directory pointed out by the testoverview_pages config value.
#
#   texttest -a <app> -s testoverview.GenererateTestStatus <major versions> <minor versions> 
#

import os, performance, plugins, respond, sys, string, time, types, smtplib, shutil
from cPickle import Pickler, Unpickler, UnpicklingError

try:
    import HTMLgen, HTMLcolors
except:
    raise BadConfigError, "Python modules HTMLgen and/or HTMLcolors not found."


class ExtractTestStates(plugins.Action):
    def __init__(self,args):
        self.user = args[0]
        self.extractDir = "/users/" + self.user + "/texttesttmp"
        self.numExtracted = 0
        self.majorVersions = args[1].split(",")
        self.minorVersions = args[2].split(",")
    def setUpApplication(self, app):
        self.testStateRepository = app.getConfigValue("testoverview_repository")
        if not os.path.isdir(self.testStateRepository):
            raise plugins.TextTestError, "Testoverview repository " + self.testStateRepository + " does not exist"
        for majorVersion in self.majorVersions:
            for minorVersion in self.minorVersions:
                version = majorVersion + "." + minorVersion
                for entries in os.listdir(self.extractDir):
                    if entries.startswith(app.name + "." + version + self.user):
                        print "Extracting from", os.path.join(self.extractDir, entries)
                        date = self.getDate(entries)
                        if os.path.isdir(os.path.join(self.extractDir, entries)):
                            self.extract(app, version, date, os.path.join(self.extractDir, entries))
    def extract(self, app, version, date, dir):
        for entries in os.listdir(dir):
            name = os.path.join(dir, entries)
            if os.path.isdir(name):
                self.extract(app, version, date, name)
            elif entries == "teststate":
                testIdentifier = self.getTestIdentifier(name)
                testDir = os.path.join(app.name, version, testIdentifier)
                if not os.path.isdir(os.path.join(self.testStateRepository, testDir)):
                    self.createTestDir(self.testStateRepository, testDir)
                shutil.copy(name, os.path.join(self.testStateRepository, testDir, "teststate_" + date))
                self.numExtracted += 1
    def createTestDir(self, root, testDir):
        checkDir = root
        for parts in testDir.split(os.sep):
            checkDir += os.sep + parts
            if not os.path.isdir(checkDir):
                os.mkdir(checkDir)
    def getTestIdentifier(self, name):
        # Use everything after the application/version dir as identifier for the test.
        return string.join(name.split(os.sep)[len(self.extractDir.split(os.sep)) + 1:-2], os.sep)
    def getDate(self, texttesttmp):
        year, month, day, hour, minute, second, wday, yday, dummy = time.strptime(texttesttmp[-11:], "%d%b%H%M%S")
        year = 2005
        timeinseconds = time.mktime((year, month, day, hour, minute, second, wday, yday, dummy))
        # The normal thing is that the tests starts before midnight.
        # However, this is not true sometimes, this try to correct that.
        if hour < 12:
            timeinseconds -= 12*60*60
        return time.strftime("%d%b%Y", time.gmtime(timeinseconds))
    def __del__(self):
        print "Extracted state for", self.numExtracted, " tests"

class GenererateTestStatus(plugins.Action):
    def __init__(self, args):
        self.majorVersions = args[0].split(",")
        self.minorVersions = args[1].split(",")
    def setUpApplication(self, app):
        self.testStateRepository = app.getConfigValue("testoverview_repository")
        if not os.path.isdir(self.testStateRepository):
            raise plugins.TextTestError, "Testoverview repository " + self.testStateRepository + " does not exist"
        pageTopDir = app.getConfigValue("testoverview_pages")
        if not os.path.isdir(pageTopDir):
            raise plugins.TextTestError, "Testoverview pages directory " + pageOverview + " does not exist"
        self.pageDir = os.path.join(pageTopDir, app.name)
        if not os.path.isdir(self.pageDir):
            try:
                os.mkdir(self.pageDir)
            except:
                raise plugins.TextTestError, "Failed to create application page directory" + self.pageDir
            
        for majorVersion in self.majorVersions:
            self.pagesOverview = {}
            foundMinorVersions = HTMLgen.Container()
            details = TestDetails()
            self.pagesDetails = {}
            usedSelectors = {}
            for minorVersion in self.minorVersions:
                version = majorVersion + "." + minorVersion
                loggedTests = {}
                tagsFound = []
                categoryHandler = CategoryHandler()
                baseDir = os.path.join(self.testStateRepository, app.name, version)
                if os.path.isdir(baseDir):
                    for entries in os.listdir(baseDir):
                        self.traverseDirectories(categoryHandler, loggedTests, tagsFound, os.path.join(baseDir, entries))
                if len(loggedTests.keys()) > 0:
                    tagsFound.sort(lambda x, y: cmp(self.getTagTimeInSeconds(x), self.getTagTimeInSeconds(y)))
                    selectors = [ SelectorLast6Days(tagsFound), SelectorAll(tagsFound), SelectorWeekend(tagsFound) ]
                    for sel in selectors:
                        selTags = sel.getSelectedTags()
                        if not usedSelectors.has_key(repr(sel)):
                            usedSelectors[repr(sel)] = sel.getFileNameExtension()
                        testTable = TestTable()
                        table = testTable.generate(categoryHandler, majorVersion, version, loggedTests, selTags)
                        self.addOverviewPages(sel.getFileNameExtension(), version, table)
                    det = details.generate(categoryHandler, version, tagsFound)
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
    def traverseDirectories(self, categoryHandler, loggedTests, tagsFound, dir):
        for entries in os.listdir(dir):
            if os.path.isdir(os.path.join(dir, entries)):
                self.traverseDirectories(categoryHandler, loggedTests, tagsFound, os.path.join(dir, entries))
            elif entries.startswith("teststate"):
                stateFile = os.path.join(dir, entries) 
                file = open(stateFile)
                try:
                    unpickler = Unpickler(file)
                    state = unpickler.load()
                    tag = entries.split("_")[-1]
                    if tagsFound.count(tag) == 0:
                        tagsFound.append(tag)
                    key = self.getTestIdentifier(dir)
                    if not loggedTests.has_key(key):
                        loggedTests[key] = {}
                    loggedTests[key][tag] = state
                    categoryHandler.registerInCategory(tag, key, state)
                except UnpicklingError:
                    print "unpickling error"
                except EOFError:
                    print "EOFError in ",file
                    print "Ignoring this file"
            else:
                print "Unknown file", entries
    def addOverviewPages(self, item, version, table):
        if not self.pagesOverview.has_key(item):
            self.pagesOverview[item] = HTMLgen.SimpleDocument()
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
        t = HTMLgen.TableLite(border=2, cellpadding=4, cellspacing=1,width="100%")
        t.append(self.generateTableHead(majorVersion, version, tagsFound))

        table = []
        tests = loggedTests.keys()
        tests.sort()
        for test in tests:
            results = loggedTests[test]
            row = [ HTMLgen.TD(test, bgcolor = "#FFFFCC") ]
            for tag in tagsFound:
                if results.has_key(tag):
                    state = results[tag]
                    type, detail = state.getTypeBreakdown()
                    category = state.category # Strange but correct..... (getTypeBreakdown gives "wrong" category)
                    fgcol, bgcol = self.getColors(category, detail)
                    if category == "success":
                        cellContaint =  HTMLgen.Font(repr(state) + detail, color = fgcol)
                    else:
                        cellContaint = HTMLgen.Href(getDetailPageName(majorVersion, tag) + "#" + version + test,
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
        bgcol = "RED"
        fgcol = "BLACK"
        if type == "faster" or type == "slower":
            bgcol = HTMLcolors.TAN
            if self.getPercent(detail) >= 5:
                fgcol = HTMLcolors.RED6
        elif type == "smaller" or type == "larger":
            if self.getPercent(detail) >= 3:
                fgcol = HTMLcolors.RED6
            bgcol = HTMLcolors.PINK
        elif type == "success":
            bgcol = "LIME"
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
        return int(detail.split("%")[0]) # Bad: Hard coded interpretation of texttest print-out.

class TestDetails:
    def generate(self, categoryHandler, version, tags):
        detailsContainers = {}
        for tag in tags:
            container = detailsContainers[tag] = HTMLgen.Container()
            categories = categoryHandler.testsInCategory[tag]
            container.append(HTMLgen.HR())
            container.append(HTMLgen.Heading(2, version + ": " + categoryHandler.generateSummary(categories)))
            for cat in categories.keys():
                test, state = categories[cat][0]
                shortDescr, longDescr = getCategoryDescription(state, cat)
                fullDescription = self.getFullDescription(categories[cat], version)
                if fullDescription:
                    container.append(HTMLgen.Name(version + longDescr))
                    container.append(HTMLgen.Heading(3, "Detailed information for the tests that " + longDescr + ":"))
                    container.append(fullDescription)
        return detailsContainers
    def getFullDescription(self, tests, version):
        fullText = HTMLgen.Container()
        textFound = None
        for test in tests:
            testName, state = test
            freeText = state.freeText
            if freeText:
                textFound = 1
                fullText.append(HTMLgen.Name(version + testName))
                fullText.append(HTMLgen.Heading(4, "TEST " + repr(state) + " " + testName))
                freeText = string.replace(freeText, "\n", "<BR>")
                fullText.append(HTMLgen.RawText(freeText))
        if textFound:
            return fullText
        else:
            return None

class CategoryHandler:
    def __init__(self):
        self.testsInCategory = {}
    def registerInCategory(self, tag, test, state):
        if not self.testsInCategory.has_key(tag):
            self.testsInCategory[tag] = {}
        if not self.testsInCategory[tag].has_key(state.category):
            self.testsInCategory[tag][state.category] = []
        self.testsInCategory[tag][state.category].append((test, state))
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
            test, state = categories[cat][0]
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
            test, state = categories[cat][0]
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
