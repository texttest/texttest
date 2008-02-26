
import matador_basic_gui, optimization_gui, ravebased_gui, default_gui, guiplugins, plugins, os
from matador import staticLinkageInCustomerFile
from time import time, ctime

class ImportTestSuite(ravebased_gui.ImportTestSuite):
    def hasStaticLinkage(self, carmUsr):
        return staticLinkageInCustomerFile(carmUsr)
    def getCarmtmpPath(self, carmtmp):
        return os.path.join("${TEST_DATA_ROOT}/carmtmps/${MAJOR_RELEASE_ID}/${ARCHITECTURE}", carmtmp)


class FeatureFilter(plugins.Filter):
    def __init__(self, features):
        self.grepCommand = "grep -E '" + "|".join(features) + "'"
    def acceptsTestCase(self, test):    
        logFile = test.getFileName("features")
        if logFile:
            commandLine = "tail -100 " + logFile + " | " + self.grepCommand + " > /dev/null 2>&1"
            return os.system(commandLine) == 0
        else:
            return False

class SelectTests(default_gui.SelectTests):
    def __init__(self, *args):
        default_gui.SelectTests.__init__(self, *args)
        self.features = []
    def addSuites(self, suites):
        default_gui.SelectTests.addSuites(self, suites)
        for suite in suites:
            featureFile = suite.getFileName("features")
            if featureFile:
                for featureName in plugins.readList(featureFile):
                    self.addSwitch(featureName, featureName, 0)
                    self.features.append(featureName)
    def getFilterList(self, app):
        filters = default_gui.SelectTests.getFilterList(self, app)    
        selectedFeatures = self.getSelectedFeatures()
        if len(selectedFeatures) > 0:
            guiplugins.guilog.info("Selected " + str(len(selectedFeatures)) + " features...")
            filters.append(FeatureFilter(selectedFeatures))
        return filters
    def getSelectedFeatures(self):
        result = []
        for feature in self.features:
            if self.optionGroup.getSwitchValue(feature, 0):
                result.append(feature)
        return result
    

class CreatePerformanceReport(guiplugins.SelectionAction):
    def __init__(self, *args):
        guiplugins.SelectionAction.__init__(self, *args)
        self.rootDir = ""
        self.versions = ["11", "12", "13", "14", "master" ]
        self.objectiveText = "Total cost of plan"
    def inToolBar(self): 
        return False
    def getMainMenuPath(self):
        return "_Optimization"
    def separatorBeforeInMainMenu(self):
        return True
    def getDialogType(self):
        return "matadordialogs.CreatePerformanceReportDialog"
    def _getTitle(self):
        return "Create Performance Report..."
    def _getScriptTitle(self):
        return "create performance report for selected tests"
    def messageAfterPerform(self):
        return "Created performance report in " + self.rootDir
    def initialize(self):
        self.apps = {}
        self.testPaths = []
        self.timeStamp = time()
        self.createStyleFile()
    def performOnCurrent(self):
        self.initialize()
        for test in self.currTestSelection:
            self.collectTest(test)
        self.createMainIndexFile()
    def collectTest(self, test):
        self.apps[test.app.fullName] = test.app.fullName
        pathToTest = os.path.join(self.rootDir,
                                  os.path.join(test.app.fullName.lower().replace(' ', '_'),
                                               os.path.join(test.getRelPath(), "index.html")))
        dir, file = os.path.split(os.path.abspath(pathToTest))
        try:
            os.makedirs(dir)
        except:
            pass # Dir exists already ...
        self.testPaths.append((test, pathToTest))
        
    def createStyleFile(self):
        backgroundColor = "#000000"
        linkColor = "#696969"
        headerColor = "#C9CFEE"
        tableBackgroundColor = "#EEEEEE"
        
        self.styleFilePath = os.path.join(self.rootDir, os.path.join("include", "performance_style.css"))
        try:
            os.makedirs(os.path.split(self.styleFilePath)[0])
        except:
            pass # Dir exists already ...
        file = open(self.styleFilePath, "w")
        file.write("body {\n font-family: Helvetica, Georgia, \"Times New Roman\", Times, serif;\n}\n\n")
        file.write("h2 {\n padding: 0pt 0pt 0pt 0pt;\n margin: 0pt 0pt 0pt 0pt;\n}\n\n")
        file.write("a:link, a:visited, a:hover {\n color: " + linkColor + ";\n text-decoration: none;\n}\n\na:hover {\n color: " + backgroundColor + ";\n text-decoration: underline;\n}\n\n")
        file.write("#navigationheader {\n background-color: " + headerColor + ";\n font-size: 8pt;\n margin: 0pt 0pt 5pt 0pt;\n}\n\n")
        file.write("#mainheader {\n background-color: " + headerColor + ";\n padding: 0pt 0pt 10pt 0pt;\n margin: 0pt 0pt 10pt 0pt;\n}\n\n")
        file.write("#testheader {\n background-color: " + headerColor + ";\n padding: 0pt 0pt 10pt 0pt;\n margin: 0pt 0pt 10pt 0pt;\n}\n\n")
        file.write("#maintableheader {\n font-weight: bold;\n background-color: " + tableBackgroundColor + ";\n padding: 0pt 5pt 0pt 5pt;\n}\n\n")
        file.write("#maintableheaderlast {\n font-weight: bold;\n background-color: " + tableBackgroundColor + ";\n padding: 0pt 5pt 0pt 5pt;\n border-bottom: thin solid;\n}\n\n")
        file.write("#maintablecell {\n padding: 0pt 5pt 0pt 5pt;\n}\n\n")
        file.write("#maintablefooterfirst {\n padding: 5pt 0pt 0pt 0pt;\n border-top: thin solid;\n font-weight: bold;\n}\n\n")
        file.write("#maintablefootercaption {\n padding: 5pt 0pt 0pt 0pt;\n font-weight: bold;\n border-top: thin solid;\n}\n\n")
        file.write("#maintablefooter {\n padding: 0pt 0pt 0pt 0pt;\n font-weight: bold;\n}\n\n")
        file.write("#graphcaption {\n font-size: 8pt;\n font-weight: bold;\n}\n\n")
        file.write("#performancetableheader {\n font-weight: bold;\n background-color: " + tableBackgroundColor + ";\n}\n\n")
        file.write("#performancetable {\n font-size: 8pt;\n}\n\n")
        file.write("#detailstableheader {\n font-weight: bold;\n background-color: " + tableBackgroundColor + ";\n}\n\n")
        file.write("#detailstable {\n font-size: 8pt;\n}\n\n")
        file.write("#bestrowentry {\n background-color: #CEEFBD;\n}\n\n")
        file.write("#worstrowentry {\n background-color: #FF7777;\n}\n\n")
        file.write("#detailsnotext {\n font-family: courier;\n}\n\n")
        file.write("#detailstext {\n font-family: courier;\n margin: 5pt 0pt 0pt 0pt;\n padding: 5pt 0pt 0pt 5pt;\n border-left: thin solid;\n}\n\n")
        file.write("#mainpage {\n font-size: 8pt;\n}\n\n")
        file.write("#testpage {\n}\n\n")
        file.close()

    def createMainIndexFile(self):
        self.mainIndexFile = os.path.join(self.rootDir, "index.html")
        file = open(self.mainIndexFile, "w")
        file.write("<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.01 Transitional//EN\" \"http://www.w3.org/TR/html4/loose.dtd\">\n")
        file.write("<html>\n <head>\n  <meta http-equiv=\"Content-Type\" content=\"text/html; charset=iso-8859-1\">\n")
        file.write("  <title>Performance report created " + ctime(self.timeStamp) + "</title>\n  <link rel=\"stylesheet\" href=\"" + self.styleFilePath + "\" type=\"text/css\">\n </head>\n")
        file.write(" <body>\n")
        file.write("  <center><table width=\"80%\" border=\"0\"><tr><td align=\"center\">\n")
        file.write("   <div id=\"mainheader\"><h2>Performance report</h2><b>Applications:</b> ")
        for app in self.apps:
            file.write(app + " ")            
        file.write("<br><b>Created:</b> " + ctime(self.timeStamp) + "<br></div>\n")

        file.write("   <div id=\"mainpage\"><table width=\"100%\" border=\"0\">\n")        
        file.write("    <tr><td><div id=\"maintableheader\">&nbsp</div></td>")
        for version in self.versions:
            file.write("<td colspan=\"3\" align=\"center\" valign=\"middle\"><div id=\"maintableheader\">Version " + version + "</div></td>")
        file.write("</tr>\n")
        file.write("    <tr><td align=\"left\" valign=\"middle\"><div id=\"maintableheader\">Test case</div></td>")
        for version in self.versions:
            file.write("<td align=\"right\" valign=\"middle\" width=\"33%\"><div id=\"maintableheader\">Solution cost</div></td>")
            file.write("<td align=\"right\" valign=\"middle\" width=\"33%\"><div id=\"maintableheader\">CPU time</div></td>")
            file.write("<td align=\"right\" valign=\"middle\" width=\"33%\"><div id=\"maintableheader\">Time to worst (KPI)</div></td>")
        file.write("</tr>\n")

        # Init column status count vectors ...
        bestWorstColumnsCount = ({}, {}, {}, {})
        for columnIndex in xrange(0, 3 * len(self.versions), 1):
            bestWorstColumnsCount[0][columnIndex] = 0
            bestWorstColumnsCount[1][columnIndex] = 0
            bestWorstColumnsCount[2][columnIndex] = 0
            bestWorstColumnsCount[3][columnIndex] = 0
            
        for i in xrange(0, len(self.testPaths), 1):
            self.notify("Status", "Creating report for " + self.testPaths[i][0].getRelPath())
            self.notify("ActionProgress", "")
            pathToPrev = None
            if i > 0:
                pathToPrev = self.testPaths[i - 1]
            pathToNext = None
            if i < len(self.testPaths) - 1:
                pathToNext = self.testPaths[i + 1]
            performance, kpi = self.createTestFile(self.testPaths[i], pathToPrev, pathToNext, self.mainIndexFile)

            file.write("    <tr><td align=\"left\" valign=\"middle\"><div id=\"maintablecell\"><a href=\"" + self.testPaths[i][1] + "\">" + self.testPaths[i][0].getRelPath() + "</div></a></td>")
            row = []
            for version in self.versions:
                cost = "-"
                time = "-"                    
                if performance.has_key(version):
                    results = performance[version]
                    if len(results) > 0:
                        cost = results[len(results) - 1][1]
                        time = results[len(results) - 1][3]
                row.append([cost, time, kpi[version]])
            bestWorstColumns = self.outputRow(file, "<td align=\"right\" valign=\"middle\">", "<div id=\"maintablecell\">", row, "</div>", "</td>")
            for bestColumn in bestWorstColumns[0]:
                bestWorstColumnsCount[0][bestColumn] += 1
            for middleColumn in bestWorstColumns[1]:
                bestWorstColumnsCount[1][middleColumn] += 1
            for worstColumn in bestWorstColumns[2]:
                bestWorstColumnsCount[2][worstColumn] += 1
            for noResultColumn in bestWorstColumns[3]:
                bestWorstColumnsCount[3][noResultColumn] += 1
            file.write("</tr>\n")

        file.write("  <tr>\n<td align=\"left\" valign=\"middle\"><div id=\"maintablefootercaption\"><table border=\"0\" width=\"100%\"><tr><td align=\"left\">Total count</td><td align=\"right\">Better:</td></tr></table></div></td>")
        for columnIndex in xrange(0, 3 * len(self.versions), 1):
            file.write("<td align=\"right\" valign=\"top\"><div id=\"maintablefooterfirst\"><div id=\"bestrowentry\">" + str(bestWorstColumnsCount[0][columnIndex]) + "</div></div></td>")
        file.write("  </tr>")
        file.write("  <tr>\n<td align=\"left\" valign=\"middle\"><div id=\"maintablefooter\" align=\"right\">Worse:</div></td>")
        for columnIndex in xrange(0, 3 * len(self.versions), 1):
            file.write("<td align=\"right\" valign=\"middle\"><div id=\"maintablefooter\"><div id=\"worstrowentry\">" + str(bestWorstColumnsCount[2][columnIndex]) + "</div></div></td>")
        file.write("  </tr>")
        file.write("  <tr>\n<td align=\"left\" valign=\"middle\"><div id=\"maintablefooter\" align=\"right\">Neither:</div></td>")
        for columnIndex in xrange(0, 3 * len(self.versions), 1):
            file.write("<td align=\"right\" valign=\"middle\"><div id=\"maintablefooter\">" + str(bestWorstColumnsCount[1][columnIndex]) + "</div></td>")
        file.write("  </tr>")
        file.write("  <tr>\n<td align=\"left\" valign=\"middle\"><div id=\"maintablefooter\" align=\"right\">No result:</div></td>")
        for columnIndex in xrange(0, 3 * len(self.versions), 1):
            file.write("<td align=\"right\" valign=\"middle\"><div id=\"maintablefooter\">" + str(bestWorstColumnsCount[3][columnIndex]) + "</div></td>")
        file.write("  </tr>")
            
        file.write("   </table></div>\n")
        file.write("  </div></td></tr></table></center>\n </body>\n</html>\n")
        file.close()
                    
        # Create the html report for a single test case.
    def createTestFile(self, pathToTest, pathToPrev, pathToNext, pathToParent):
        # Extract info about cost, times and memory consumption at various points in time
        performance = self.getPerformance(pathToTest[0])

        # Open file, print some basic info
        file = open(pathToTest[1], "w")
        file.write("<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.01 Transitional//EN\" \"http://www.w3.org/TR/html4/loose.dtd\">\n")
        file.write("<html>\n <head>\n  <meta http-equiv=\"Content-Type\" content=\"text/html; charset=iso-8859-1\">\n")
        file.write("  <title>Performance of test " + pathToTest[0].getRelPath() + "</title>\n  <link rel=\"stylesheet\" href=\"" + self.styleFilePath + "\" type=\"text/css\">\n </head>\n")
        file.write(" <body>\n  <center><table width=\"80%\"><tr><td align=\"center\"><div id=\"testpage\">\n")
        file.write("   <div id=\"navigationheader\"><table width=\"100%\" border=\"0\"><tr><td width=\"33%\" align=\"left\">")
        if pathToPrev:
            file.write("<a href=\"" + pathToPrev[1] + "\"><< " + pathToPrev[0].getRelPath() + "</a>")
        file.write("</td><td width=\"33%\" align=\"center\"><a href=\"" + pathToParent + "\">Up</a></td><td width=\"33%\" align=\"right\">")
        if pathToNext:
            file.write("<a href=\"" + pathToNext[1] + "\">" + pathToNext[0].getRelPath() + " >></a>")
        file.write("</td></tr></table></div>\n")
        file.write("   <div id=\"testheader\"><h2>Performance report</h2><b>Test:</b> " + pathToTest[0].getRelPath() + "</b><br><b>Created:</b> " + ctime(self.timeStamp) + "</div>\n")

        self.outputGraphs(file, os.path.split(pathToTest[1])[0], performance)
        kpi = self.outputPerformance(file, performance)
        self.outputDetails(file, pathToTest)

        file.write("\n  </div></td></tr></table></center>\n </body>\n</html>\n")
        file.close()
        return performance, kpi

    def getPerformance(self, test):
        performance = {}
        for version in self.versions:            
            defaultFileName = test.getFileName("output", "master")
            fileName = test.getFileName("output", version)
            if not fileName or (fileName == defaultFileName and version != "master"):
                continue # Same as master, empty result vector ...

            file = open(fileName, "r")
            lines = file.readlines()
            latestCost = ""
            latestAssignment = ""
            latestSolution = ""
            results = []
            for line in lines:
                if line.find(self.objectiveText) != -1:
                    latestCost = line[line.rfind(":") + 2:].strip(" \n")
                elif line.find("Assignment percentage") != -1:
                    latestAssignment = line[line.rfind(":") + 2:].strip(" \n")
                elif line.find("Current Solution") != -1:
                    latestSolution = line[line.rfind(":") + 2:].strip(" \n")
                elif line.startswith("Memory consumption: "):
                    memory = line[line.find(":") + 2:line.find(" MB  ")].strip(" \n")
                    cpuTime = line[line.rfind(":  ") + 3:].strip(" \n")
                    results.append((latestSolution, latestCost, latestAssignment, cpuTime, memory))
            performance[version] = results
        return performance

    def outputGraphs(self, file, dir, performance):
        costGraphFile, assignmentGraphFile, memoryGraphFile = self.generateGraphs(dir, performance, "png")
        file.write("\n<! ===== Output comparison graphs ===== >\n\n")
        file.write("   <h3>Comparison graphs</h3>\n")
        file.write("   <table width=\"100%\" border=\"0\">\n    <tr>\n")
        file.write("     <td valign=\"center\" align=\"center\" width=\"33%\"><a href=\"" + costGraphFile + "\"><img src=\"" + costGraphFile + "\"></a></td>\n")
        file.write("     <td valign=\"center\" align=\"center\" width=\"33%\"><a href=\"" + assignmentGraphFile + "\"><img src=\"" + assignmentGraphFile + "\"></a></td>\n")
        file.write("     <td valign=\"center\" align=\"center\" width=\"33%\"><a href=\"" + memoryGraphFile + "\"><img src=\"" + memoryGraphFile + "\"></a></td>\n")
        file.write("    </tr>\n    <tr><td align=\"center\"><div id=\"graphcaption\">Solution cost progress.</div></td><td align=\"center\"><div id=\"graphcaption\">Assignment percentage progress.</div></td><td align=\"center\"><div id=\"graphcaption\">Memory consumption progress.</div></td></tr>\n   </table>\n")

    def generateGraphs(self, dir, performance, terminal):
        self.generateGraphData(dir, performance)
        return self.generateGraph(dir, "cost", "Time (minutes)", self.objectiveText, terminal), \
               self.generateGraph(dir, "assignment", "Time (minutes)", "Assignment percentage", terminal), \
               self.generateGraph(dir, "memory", "Time (minutes)", "Memory consumption (Mb)", terminal)

    def generateGraph(self, dir, name, xLabel, yLabel, terminal):
        plotFileName = os.path.join(dir, name + "." + terminal)
        plotCommandFileName = os.path.join(dir, "plot_" + name + ".commands")
        plotCommandFile = open(plotCommandFileName, "w")
        plotCommandFile.write("set grid\nset xlabel \"" + xLabel + "\"\nset ylabel \"" + yLabel + "\"\n")
        plotCommandFile.write("set terminal " + terminal + "  picsize 350 280\nset output \"" + plotFileName + "\"\nplot ")
        allPlotCommands = ""
        for version in self.versions:
            fileName = os.path.join(dir, name + "_" + version + ".data")
            if os.path.isfile(fileName) and os.stat(fileName).st_size > 0:
                allPlotCommands += "\"" + fileName + "\" using 1:2 with linespoints title \"Version " + version + "\","
        plotCommandFile.write(allPlotCommands.strip(","))
        plotCommandFile.close()

        plotCommand = "gnuplot -persist -background white " + plotCommandFileName
        stdin, stdouterr = os.popen4(plotCommand)
                
        return os.path.split(plotFileName)[1]
    
    def generateGraphData(self, dir, performance):
        # In the test dir, create files suitable for gnuplot containing
        # cost/time, assignment/time and memory/version.
        for version in self.versions:
            if not performance.has_key(version):
                continue
            
            fileNameSuffix = "_" + version + ".data"
            costFile = open(os.path.join(dir, "cost" + fileNameSuffix), "w")
            assignmentFile = open(os.path.join(dir, "assignment" + fileNameSuffix), "w")
            memoryFile = open(os.path.join(dir, "memory" + fileNameSuffix), "w")

            results = performance[version]              
            for s, cost, ass, time, memory in results:
                timeInMinutes = str(plugins.getNumberOfMinutes(time))
                costFile.write(timeInMinutes + " " + cost + "\n")
                assignmentFile.write(timeInMinutes + " " + ass + "\n")
                memoryFile.write(timeInMinutes + " " + memory + "\n")
            
            costFile.close()
            assignmentFile.close()
            memoryFile.close()
        
    def outputPerformance(self, file, performance):
        file.write("\n<! ===== Output performance measures ===== >\n\n")
        file.write("   <h3>Performance measures</h3>\n")
        columnWidth = str(int(100 / (len(self.versions) + 1)))

        file.write("   <div id=\"performancetable\">\n    <table width=\"100%\" border=\"0\">\n     <tr><td width=\"" + columnWidth + "%\"><div id=\"performancetableheader\">&nbsp</div></td>")
        for version in self.versions:
            file.write("<td align=\"center\" width=\"" + columnWidth + "%\"><div id=\"performancetableheader\">Version " + version + "</div></td>")
        file.write("</tr>\n")

        categories = ["Number of solutions:", "Best solution cost:", "Best assignment %:", "Total CPU time:", "Max. memory consumption:"]
        for i in xrange(0, len(categories), 1):
            file.write("     <tr><td align=\"right\" valign=\"middle\"><div id=\"performancetableheader\">" + categories[i] + "</div></td>")
            row = []
            for version in self.versions:
                data = "-"
                if performance.has_key(version):
                    results = performance[version]
                    if len(results) > 0:
                        data = results[len(results) - 1][i]
                row.append([data])
            self.outputRow(file, "<td align=\"right\" valign=\"top\">", "", row, "", "</td>", i > 0)
            file.write("</tr>\n")

        # 'KPI' - Time to reach a solution as good as the worst solution found by any version
        worstSolution = -1000000000
        for version in self.versions:
            if performance.has_key(version):
                results = performance[version]
                if len(results) > 0:
                    try:
                        lastSolution = int(results[len(results) - 1][1])
                        if lastSolution > worstSolution:
                            worstSolution = lastSolution
                    except:
                        pass # lastSolution might be empty (''), for example ...
            
        file.write("     <tr><td align=\"right\" valign=\"middle\"><div id=\"performancetableheader\">Time to solution " + str(worstSolution) + ":</div></td>")        
        row = []
        kpi = {}
        for version in self.versions:
            data = "-"
            if performance.has_key(version):
                results = performance[version]
                for iter in results:
                    try:
                        if int(iter[1]) <= worstSolution:
                            data = iter[3]                        
                            break
                    except:
                        pass # lastSolution might be empty (''), for example ...
            kpi[version] = data
            row.append([data])
        self.outputRow(file, "<td align=\"right\" valign=\"top\">", "", row, "", "</td>")            
        file.write("</table>\n   </div>\n")
        return kpi

    def outputDetails(self, file, pathToTest):
        file.write("\n<! ===== Output performance details ===== >\n\n")
        file.write("   <h3>Performance details</h3>\n")
        file.write("   <div id=\"detailstable\">\n    <table width=\"100%\" border=\"0\">\n     <tr>")
        for version in self.versions:
            file.write("<td align=\"center\" width=\"" + str(int(100 / len(self.versions))) + "%\"><div id=\"detailstableheader\">Version " + version + "</div></td>")
        file.write("</tr>\n     <tr>")
        for version in self.versions:
            timerInfo = self.getTimerInfo(pathToTest[0], version)
            if timerInfo == "Same as master" or timerInfo == "No detailed time information could be found":
                file.write("<td align=\"center\" valign=\"middle\"><div id=\"detailsnotext\">" + timerInfo + "</div></td>")
            else:
                file.write("<td align=\"right\" valign=\"top\"><div id=\"detailstext\">" + timerInfo + "</div></td>")
        file.write("</tr>\n    </table>\n   </div>\n")

    def getTimerInfo(self, test, version):
        # Get output file for this version
        defaultFileName = test.getFileName("output", "master")
        fileName = test.getFileName("output", version)
        if not fileName or (fileName == defaultFileName and version != "master"):
            return "Same as master"
        
        # Get lines from (but excluding) '----------Timers'
        # to '-----------Timers End' ...
        file = open(fileName, "r")
        lines = file.readlines()
        info = ""
        includeLine = False
        for line in lines:
            fixedLine = line.strip(" \n")
            if line.startswith("----------------------------Timers"):
                fixedLine = fixedLine[6:-6]
                includeLine = True
            if line.startswith("--------------------------Timers End"):
                break
            if includeLine:
                info += fixedLine.replace("............:", ":") + "<br>"
            
        if info == "":
            info = "No detailed time information could be found"
        
        return info

    # Observe: data is a vector of vectors.
    def outputRow(self, file, prefix, innerPrefix, data, innerSuffix, suffix, markExtremes = True):
        bestWorstColumns = ([], [], [], [])
        if len(data) == 0:
            return bestWorstColumns

        least = data[0][:]
        largest = data[0][:]
        for d in data:
            for i in xrange(0, len(d), 1):
                if d[i] == "-":
                    continue
                comp1 = self.compareValues(d[i], largest[i])
                comp2 = self.compareValues(least[i], d[i])
                if largest[i] == "-" or comp1 == 1:
                    largest[i] = d[i]
                if least[i] == "-" or comp2 == 1:
                    least[i] = d[i]

        columnIndex = 0
        for d in data:
            for i in xrange(0, len(d), 1):            
                if markExtremes and d[i] != "-" and d[i] == least[i]: # 'Best'
                    bestWorstColumns[0].append(columnIndex)
                    file.write(prefix + "<div id=\"bestrowentry\">" + innerPrefix + d[i] + innerSuffix + "</div>" + suffix)
                elif markExtremes and d[i] != "-" and d[i] == largest[i]: # 'Worst'
                    bestWorstColumns[2].append(columnIndex)
                    file.write(prefix + "<div id=\"worstrowentry\">" + innerPrefix + d[i] + innerSuffix + "</div>" + suffix)
                else:
                    if d[i] == "-":
                        bestWorstColumns[3].append(columnIndex)
                    else:
                        bestWorstColumns[1].append(columnIndex)
                    file.write(prefix + innerPrefix + d[i] + innerSuffix + suffix)
                columnIndex += 1
               
        return bestWorstColumns

    # -1 means v1 < v2, 0 v1 == v2, 1 v1 > v2
    def compareValues(self, v1, v2):
        try:
            # Compare as ints, if possible ...
            realV1 = int(v1)
            realV2 = int(v2)
            if realV1 < realV2:
                return -1
            elif realV1 > realV2:
                return 1
            else:
                return 0
        except:
            if v1 < v2:
                return -1
            elif v1 > v2:
                return 1
            else:
                return 0
            


class PerformanceReportScript(plugins.ScriptWithArgs):
    dirKey = "dir"
    versionsKey = "versions"
    def __init__(self, args = []):
        self.creator = CreatePerformanceReport()
        self.args = self.parseArguments(args)
        if self.args.has_key(self.dirKey):
            self.creator.rootDir = self.args[self.dirKey]
        if self.args.has_key(self.versionsKey):            
            self.creator.versions = self.args[self.versionsKey].replace(" ", "").split(",")
        self.creator.initialize()
    def __call__(self, test):
        self.creator.collectTest(test)
    def __del__(self):
        self.creator.createMainIndexFile()

class InteractiveActionConfig(matador_basic_gui.InteractiveActionConfig):
    def getInteractiveActionClasses(self, dynamic):
        classes = matador_basic_gui.InteractiveActionConfig.getInteractiveActionClasses(self, dynamic)
        if not dynamic:
            classes.append(CreatePerformanceReport)
        return classes
    
    def getReplacements(self):
        rep = matador_basic_gui.InteractiveActionConfig.getReplacements(self)
        rep[default_gui.SelectTests] = SelectTests
        rep[default_gui.ImportTestSuite] = ImportTestSuite
        return rep
    
