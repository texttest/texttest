import plugins, os, re, string, math, exceptions, optimization, performance, time, texttest

try:
    import HTMLgen, barchart
except:
    raise texttest.BadConfigError, "Python modules HTMLgen and/or barchart not found. Try adding /users/johani/pythonpackages/HTMLgen to your PYTHONPATH."


class CarmenDocument(HTMLgen.SeriesDocument):
    def header(self):
        """Generate the standard header markups.
        """
        # HEADER SECTION - overload this if you don't like mine.
        s = []
        if self.banner:
            bannertype = type(self.banner)
            if bannertype in (HTMLgen.TupleType, HTMLgen.StringType):
                s.append(str(HTMLgen.Center(HTMLgen.Image(self.banner, border=0))) + '<BR>\n')
            elif bannertype == HTMLgen.InstanceType:
                s.append(str(self.banner) + '<BR>\n')
            else:
                raise TypeError, 'banner must be either a tuple, instance, or string.'
        if self.place_nav_buttons:
            s.append(self.nav_buttons())
        s.append('<HR>\n\n')
        return string.join(s, '')
    def footer(self):
        """Generate the standard footer markups.
        """
        # FOOTER SECTION - overload this if you don't like mine.
        t = time.localtime(time.time())
        #self.datetime = time.strftime("%c %Z", t)    #not available in JPython
        self.datetime = time.asctime(t)
        #self.date = time.strftime("%A %B %d, %Y", t)
        x = string.split(self.datetime)
        self.date = x[0] + ' ' + x[1] + ' ' + x[2] + ', ' + x[4]
        s =  ['\n<P><HR>\n']
        if self.place_nav_buttons:
            s.append(self.nav_buttons())
        s.append('\n<FONT SIZE="-1"><P>Copyright &#169 %s<BR>All Rights Reserved<BR>\n' \
            % self.author)
        s.append('\nComments to author: ' + str(HTMLgen.MailTo(self.email)) )
        s.append('<br>\nGenerated: %s <BR>' % self.datetime) # can use self.datetime here instead
        s.append('<hr>\n</FONT>')
        return string.join(s, '')

class BarChart:
    def __init__(self, entries):
        self.entries = entries
        
    def doMeans(self, datalist, groupname, linkgroup = None):
        if linkgroup:
            meanslink = [ HTMLgen.Href(linkgroup, groupname) ]
        means = [ groupname ]

        for keys in self.entries:
            means.append(datalist.mean(keys))
            if linkgroup:
                meanslink.append(datalist.mean(keys))
        if linkgroup:
            return means, meanslink
        else:
            return means

    def createBarChartMeans(self, chart, groupname, glob = None, linkgroupglob = None):
        means, meansglob = self.doMeans(chart.datalist, groupname, linkgroupglob)
        chart.datalist.load_tuple(tuple(means))
        if glob:
            glob.datalist.load_tuple(tuple(meansglob))
        
    def createBarChartMeansRelAbs(self, charts, groupname, globrel = None, linkgroupglob = None):
        chartabs, chartrel = charts

        means, meansglob = self.doMeans(chartrel.datalist, groupname, linkgroupglob)
        chartrel.datalist.load_tuple(tuple(means))
        if globrel:
            globrel.datalist.load_tuple(tuple(meansglob))
        
        means = self.doMeans(chartabs.datalist, groupname)
        chartabs.datalist.load_tuple(tuple(means))

    def createBC(self, title):
        chart = barchart.StackedBarChart()
        chart.title = title
        chart.datalist = barchart.DataList()
        chart.datalist.segment_names = tuple(self.entries)
        return chart

    def createRelAbsBC(self):
        chartabs = self.createBC("Absolute times")
        chartrel = self.createBC("Relative times")
        return chartabs, chartrel

    def fillData(self, vals, data):
        data.load_tuple(tuple(vals))
        
    def fillDataRelAbs(self, vals, total, data):
        dataabs, datarel = data
        dataabs.load_tuple(tuple(vals))
        relvals = []
        for val in vals:
            if len(relvals) > 0:
                relvals.append(float(val)/total)
            else:
                relvals.append(val)
        datarel.load_tuple(tuple(relvals))

class AnalyzeLProfData:
    def __init__(self):
        self.interestingFunctions = ["CGSUB::pricing",
                                     "CO_PAQS::optimize",
                                     "CGSUB::fix_variables",
                                     "CGSUB::unfix_variables",
                                     "CGSUB::feasible",
                                     "apc_setup"]
        self.raveFunctions = ["CRCExecuteAllRules",
                              "CRCComputeValue",
                              "CRCSetRotation"]
        self.hatedFunctions = {}
        self.numMeans = 0

        self.reFlat = re.compile(r'[0-9]{1,2}\.[0-9]{1} *[0-9]{1,2}\.[0-9]{1}.*')
        self.reCall = re.compile(r'-{1} *[0-9]{1,3}- *[0-9]{1,2}\.[0-9]{1} *[0-9]{1,2}\.[0-9]{1}.*')

    def doFlatProf(self, line, fcns):
         profLine = self.reFlat.search(line)
         if profLine:
            data = profLine.group().split()
            funcName = data[2]
            funcPerc = float(data[0])
            if len(self.top20) < 20:
                self.top20.append((funcName, funcPerc))
                if fcns.has_key(funcName):
                    fcns[funcName] += funcPerc
                else:
                    fcns[funcName] = funcPerc
                
    def doCallGraph(self, line):
        profLine = self.reCall.search(line)
        if profLine:
            data = profLine.group()
            minus = data.rfind("-",0,10)
            data = data[minus+1:].split()
            funcName = data[2]
            funcPerc = float(data[0])
            try:
                ind = self.interestingFunctions.index(funcName)
                #print funcName, funcPerc
                self.sum += funcPerc
            except ValueError:
                pass
            try:
                ind = self.raveFunctions.index(funcName)
                #print funcName, funcPerc
                self.rave[funcName] = funcPerc
                self.sumRave += funcPerc
            except ValueError:
                pass

    def analyze(self, lprofFileName, data):
        self.flat = None
        self.call = None
        self.top20 = []
        self.sum = 0
        self.sumRave = 0
        self.rave = {}
        file = open(lprofFileName)
        for line in file.readlines():
            if line.find("Flat profile") != -1:
                self.flat = 1
                self.call = None
                continue
            if line.find("Call graph") != -1:
                self.flat = None
                self.call = 1
                continue
            if self.flat:
                self.doFlatProf(line, data["fcns"])
            if self.call:
                self.doCallGraph(line)
        data["count"] += 1
        return self.rave
                
    def profileBarChart(self, fcns, div = None):
        rank = fcns.keys()
        rank.sort(lambda x, y: cmp(int(100*fcns[x]), int(100*fcns[y])))
        rank.reverse()

        chart = barchart.BarChart()
        chart.title = "Top 10 most time consuming functions."
        chart.datalist = barchart.DataList()

        count = 0
        for line in rank:
            if div:
                val = fcns[line] / self.numMeans
            else:
                val = fcns[line]
            chart.datalist.load_tuple((line, val))
            count += 1
            if count > 10:
                break
        return chart
        
    def doMeans(self, data):
        count = data["count"]
        for fcn in data["fcns"].keys():
            data["fcns"][fcn] /= count
            if self.hatedFunctions.has_key(fcn):
                self.hatedFunctions[fcn] += data["fcns"][fcn]
            else:
                self.hatedFunctions[fcn] = data["fcns"][fcn]
        self.numMeans += 1

        return self.profileBarChart(data["fcns"])


class GenHTML(plugins.Action):
    def setUpApplication(self, app):
        self.htmlDir = "/carm/documents/Development/Optimization/Testing"
        self.indexFile = self.htmlDir + os.sep + "testindex.html"
        self.timeSpentFile = self.htmlDir + os.sep + "timespent.html"
        self.raveSpentFile = self.htmlDir + os.sep + "ravespent.html"
        self.hatedFcnsFile = self.htmlDir + os.sep + "hatedfcns.html"

        
        self.RCFile = app.abspath + os.sep + "apcinfo.rc"
        self.idoc = CarmenDocument(self.RCFile)
        self.ilist = HTMLgen.List(style="compact")
        self.idoc.append(self.ilist)
        self.numberOfTests = 0
        self.totalCPUtime = 0

        self.definingValues = [ "Network generation time", "Generation time", "Coordination time", "DH post processing" ]
        self.interestingValues = ["Conn fixing time"]
        #self.tsValues = self.definingValues + self.interestingValues + ["Other time"]
        self.tsValues = [ "Network gen", "Generation", "Costing", "DH post", "Conn fix", "Other" ]
        self.timeSpentBC = BarChart(self.tsValues)
        
        # The global chart for relative times.
        self.chartreldoc = CarmenDocument(self.RCFile)
        self.chartreldoc.title = "Where does APC spend time?"
        self.chartrelglob = barchart.StackedBarChart()
        self.chartrelglob.title = "Relative times"
        self.chartrelglob.datalist = barchart.DataList()
        self.chartrelglob.datalist.segment_names = tuple(self.tsValues)
        self.chartreldoc.append_file(os.path.join(self.htmlDir, 'timespent-intro-txt.html'))
        self.chartreldoc.append(self.chartrelglob)
        self.chartreldoc.append(HTMLgen.Paragraph())
        self.chartreldoc.append(HTMLgen.Href('testindex.html', 'To test set page'))
        
        self.kpiGroupForTest = {}
        self.kpiGroups = []
        self.kpiGroupsList = {}

        self.suitePages = {}

        self.lprof = AnalyzeLProfData()
        self.raveBC = BarChart(self.lprof.raveFunctions)
        self.profilingGroups = HTMLgen.Container()
        self.profilingGroups.append(HTMLgen.Text("Used groups: "))

        self.chartRavedoc = CarmenDocument(self.RCFile)
        self.chartRavedoc.title = "Relative time spent by RAVE in APC"
        self.chartRaveglob = barchart.StackedBarChart()
        self.chartRaveglob.title = "Relative time spent by RAVE in APC"
        self.chartRaveglob.datalist = barchart.DataList()
        self.chartRaveglob.datalist.segment_names = tuple(self.lprof.raveFunctions)
        #self.chartreldoc.append_file(os.path.join(self.htmlDir, 'timespent-intro-txt.html'))
        self.chartRavedoc.append(self.profilingGroups)
        self.chartRavedoc.append(self.chartRaveglob)
        self.chartRavedoc.append(HTMLgen.Paragraph())
        self.chartRavedoc.append(HTMLgen.Href('testindex.html', 'To test set page'))
 
    def __del__(self):
        # Write the main page.
        self.idoc.append(HTMLgen.Text("Number of tests: " + str(self.numberOfTests)))
        self.idoc.append(HTMLgen.BR())
        self.idoc.append(HTMLgen.Text("Total CPU time:  " + str("%.1f" % (self.totalCPUtime/60)) + "h"))
        self.idoc.write(self.indexFile)

        # Write suite pages.                       
        for suites in self.suitePages.keys():
            self.buildSuitePage(self.suitePages[suites], suites)
            self.suitePages[suites]["page"].title = "APC test suite user " + suites
            self.suitePages[suites]["page"].write(self.htmlDir + os.sep + suites + ".html")

        # Write the time spent page.
        totalMeans = self.timeSpentBC.doMeans(self.chartrelglob.datalist, "ALL")
        self.chartrelglob.datalist.load_tuple(tuple(totalMeans))
        self.chartreldoc.append_file(os.path.join(self.htmlDir, 'timespent-expl-txt.html'))
        self.chartreldoc.write(self.timeSpentFile)

        # Write the Rave spent page.
        totalMeans = self.raveBC.doMeans(self.chartRaveglob.datalist, "ALL")
        self.chartRaveglob.datalist.load_tuple(tuple(totalMeans))
        #self.chartRavedoc.append_file(os.path.join(self.htmlDir, 'timespent-expl-txt.html'))
        self.chartRavedoc.write(self.raveSpentFile)
        
        # Write most hated page.
        hatedFcnsDoc = CarmenDocument(self.RCFile)
        hatedFcnsDoc.title = "The 10 most time consuming functions in APC"
        hatedFcnsDoc.append(self.profilingGroups)
        chart = self.lprof.profileBarChart(self.lprof.hatedFunctions, 1)
        hatedFcnsDoc.append(chart)
        hatedFcnsDoc.write(self.hatedFcnsFile)

    def __repr__(self):
        return "Generating HTML info for"

    # Builds the actual content for the group.
    def buildSuitePage(self, suitePage, name):
        page = suitePage["page"]
        for groups in suitePage["group"].keys():
            page.append(HTMLgen.HR())
            page.append(HTMLgen.Name(groups))
            if groups == "common":
                page.append(HTMLgen.Heading(2, "Non-grouped tests"))
            else:
                page.append(HTMLgen.Heading(2, "KPI group " + groups))

            if suitePage["group"][groups]["info"]:
                page.append(HTMLgen.Heading(3,"Short summary"))
                page.append(suitePage["group"][groups]["info"])

            if not groups == "common":
                meanvar = self.calcCostAndPerfMeanAndVariation(suitePage["group"][groups]["table"])
            table = HTMLgen.Table()
            table.body = suitePage["group"][groups]["table"]
            table.heading = ["Test", "Cost", "Perf. (min)", "Mem (MB)", "Uncov", "Overcov", "Illegal", "Date"]
            page.append(table)
            if not groups == "common":
                page.append(meanvar)

            if suitePage["group"][groups]["barcharts"]:
                charts = chartabs, chartrel = suitePage["group"][groups]["barcharts"]
                if not groups == "common":
                    self.timeSpentBC.createBarChartMeansRelAbs(charts, groups, self.chartrelglob, name + ".html" + "#" + groups)
                page.append(chartrel)
                page.append(chartabs)

            if suitePage["group"][groups]["profiling"]:
                data = suitePage["group"][groups]["profiling"]
                chart = self.lprof.doMeans(data)
                
                page.append(HTMLgen.Heading(3,"Profiling"))
                page.append(chart)
                page.append(HTMLgen.Paragraph())
                if not groups == "common":
                    self.raveBC.createBarChartMeans(data["ravebc"], groups, self.chartRaveglob, name + ".html" + "#" + groups)
                page.append(data["ravebc"])
                page.append(HTMLgen.Paragraph())
                page.append("Used tests for profiling results: " + string.join(data["tests"],", "))
                self.profilingGroups.append(HTMLgen.Href(name + ".html" + "#" + groups, HTMLgen.Text(groups)))

    def calcCostAndPerfMeanAndVariation(self, table):
        cost = []
        cost_mean = 0
        perf = []
        perf_mean = 0
        num = 0
        for tests in table:
            cost.append(tests[1])
            cost_mean += cost[-1]
            perf.append(tests[2])
            perf_mean += perf[-1]
            
            if num == 0:
                cost_max = cost_min = cost[-1]
                perf_max = perf_min = perf[-1]
            else:
                if cost[-1] > cost_max:
                    cost_max = cost[-1]
                if cost[-1] < cost_min:
                    cost_min = cost[-1]
                if perf[-1] > perf_max:
                    perf_max = perf[-1]
                if perf[-1] < perf_min:
                    perf_min = perf[-1]
            num += 1
        cost_mean /= num
        perf_mean /= num

        cost_spread = float(cost_max)/float(cost_min) - 1
        try:
            perf_spread = float(perf_max)/float(perf_min) - 1
        except exceptions.ZeroDivisionError:
            perf_spread = 0
        
        cost_var = 0
        perf_var = 0
        num = 0
        for tests in table:
            tmp = cost[num] - cost_mean
            cost_var += tmp*tmp
            
            tmp = perf[num] - perf_mean
            perf_var += tmp*tmp
            num +=1
        cost_var = math.sqrt(cost_var/num)/cost_mean
        try:
            perf_var = math.sqrt(perf_var/num)/perf_mean
        except exceptions.ZeroDivisionError:
            perf_var = 0

        meanvar = HTMLgen.Paragraph()
        meanvar.append("Cost, mean: " + str(int(cost_mean)) + ", scaled std. dev: " + str("%.4f" % cost_var) + ", spread: " + str("%.4f" % (100*cost_spread)) + "%")
        meanvar.append(HTMLgen.BR())
        meanvar.append("Performance, mean: " + str(int(perf_mean)) + ", scaled std. dev: " + str("%.4f" % perf_var) + ", spread: " + str("%.4f" % (100*perf_spread)) + "%")
        return meanvar
        
    def createGroupInfo(self, group, test):
        subplanDir = test.app.configObject.target._getSubPlanDirName(test)
        info = HTMLgen.Paragraph()

        # Info from status file
        logFile = test.makeFileName(test.app.getConfigValue("log_file"), temporary = 0)
        optRun = optimization.OptimizationRun(test.app, ["legs\.", "Period"] ,[] ,logFile)
        if optRun.solutions:
            input = optRun.solutions[0]
            period_start, period_end = input["Period"]
            date_start = time.mktime(time.strptime(period_start, "%Y%m%d"))
            date_end = time.mktime(time.strptime(period_end, "%Y%m%d"))
            
            if date_start == date_end:
                info.append("Daily")
            elif date_end == date_start + 6*1440*60:
                info.append("Weekly")
            else:
                info.append("Dated (" + str(int((date_end-date_start)/1440/60) + 1) + " days)")
            info.append(" Num legs: ", input["legs\."])
            info.append(HTMLgen.BR())
        else:
            print "Failed to find input info"


        # Info from the 'rules' file
        inter = { "apc_pac.num_col_gen_objective_components" : { 'val': None, 'text': "Cost components" },
                  "apc_pac.num_col_gen_resource_components" : { 'val': None, 'text': "Resources components" }}
        ruleFile = os.path.join(subplanDir, "APC_FILES", "rules")
        if os.path.isfile(ruleFile):
            for line in open(ruleFile).xreadlines():
                items = line.split()
                if inter.has_key(items[0]):
                    inter[items[0]]["val"] = items[1]

            for item in inter.keys():
                entry = inter[item]
                if entry["val"]:
                    info.append(entry["text"] + ": " + entry["val"] + " ")
                else:
                    info.append(entry["text"] + ": 0 ")

        self.currentSuitePage["group"][group]["info"] = info
    
    def readKPIGroupFile(self, suite):
        self.kpiGroupForTest = {}
        self.kpiGroups = []
        self.kpiGroupsList = {}
        kpiGroups = suite.makeFileName("kpi_groups")
        if not os.path.isfile(kpiGroups):
            return
        groupFile = open(kpiGroups)
        groupName = None
        for line in groupFile.readlines():
            if line[0] == '#' or not ':' in line:
                continue
            groupKey, groupValue = line.strip().split(":",1)
            if groupKey.find("_") == -1:
                if groupName:
                    groupKey = groupName
                testName = groupValue
                self.kpiGroupForTest[testName] = groupKey
                try:
                    ind = self.kpiGroups.index(groupKey)
                except ValueError:
                    self.kpiGroups.append(groupKey)
            else:
                gk = groupKey.split("_")
                kpigroup = gk[0]
                item = gk[1]
                if item == "name":
                    groupName = groupValue
                
                
    def setUpSuite(self, suite):
        if suite.name == "picador":
            return
        # Top list for this suite.
        self.suitePageName = suite.name + ".html"
        self.ilist.append(HTMLgen.Href(self.suitePageName, HTMLgen.Text(suite.name)))
        self.currentList = HTMLgen.List(style="compact")
        self.ilist.append(self.currentList)
        # Create page for suite.
        self.currentSuitePage = self.suitePages[suite.name] = { 'page': CarmenDocument(self.RCFile) , 'group': {} }
        self.currentSuitePage["page"].append(HTMLgen.Center(HTMLgen.Heading(1, suite.name)))
        # Lists for the KPI groups.
        self.readKPIGroupFile(suite)
        for kpigr in self.kpiGroups:
            self.currentList.append(HTMLgen.Href(self.suitePageName + "#" + kpigr, HTMLgen.Text("KPI group " + kpigr)))
            self.kpiGroupsList[kpigr] = HTMLgen.List(style="compact")
            self.currentList.append(self.kpiGroupsList[kpigr])
            
    def __call__(self, test):
        self.describe(test)
        title = HTMLgen.Text(test.name)
        self.numberOfTests +=1

        # Add test to index list.
        if self.kpiGroupForTest.has_key(test.name):
            self.kpiGroupsList[self.kpiGroupForTest[test.name]].append(title)
            group = self.kpiGroupForTest[test.name]
        else:
            href  = HTMLgen.Href(self.suitePageName + "#" + test.name, title)
            self.currentList.append(href)
            group = "common"
        # Create group if necessary.
        if not self.currentSuitePage["group"].has_key(group):
            self.currentSuitePage["group"][group] = { 'info': None , 'barcharts': None , 'table': [] , 'profiling': {} }
            if not group == "common":
                self.createGroupInfo(group, test)

        tableDate = "-"
        tableUncovered = -1
        tableOvercovered = -1
        tableIllegal = -1
        tableCost = 0
        logFile = test.makeFileName(test.app.getConfigValue("log_file"), temporary = 0)
        optRun = optimization.OptimizationRun(test.app,  [ optimization.timeEntryName, optimization.activeMethodEntryName, optimization.dateEntryName, optimization.costEntryName], ["uncovered legs\.", "overcovers", "^\ illegal trips"] + self.definingValues + self.interestingValues, logFile)
        if not len(optRun.solutions) == 0:
            lastSolution = optRun.solutions[-1]
            tableDate = lastSolution["Date"]
            tableCost = lastSolution[optimization.costEntryName]
            if lastSolution.has_key("uncovered legs\."):
                tableUncovered = lastSolution["uncovered legs\."]
            if lastSolution.has_key("overcovers"):
                tableOvercovered = lastSolution["overcovers"]
            if lastSolution.has_key("^\ illegal trips"):
                tableIllegal = lastSolution["^\ illegal trips"]
            self.extractTimeSpent(test, optRun.solutions, group)
        else:
            print "Warning, no solution in OptimizationRun!"

        self.extractProfiling(test, group)
        
        # Table
        testPerformance = performance.getTestPerformance(test)
        testMemory = performance.getTestMemory(test)
        if testMemory > 0:
            testMemory = str(testMemory)
        else:
            testMemory = "-"
        tableRow = [ test.name, tableCost, float(int(10*testPerformance))/10, testMemory,
                     tableUncovered, tableOvercovered, tableIllegal, tableDate ]
        self.currentSuitePage["group"][group]["table"].append(tableRow)
        self.totalCPUtime += testPerformance
        
    def extractProfiling(self, test, group):
        lprofFile = test.makeFileName("lprof", temporary = 0)
        if os.path.isfile(lprofFile):
            if not self.currentSuitePage["group"][group]["profiling"]:
                data = self.currentSuitePage["group"][group]["profiling"] = { 'fcns': {}, 'count': 0 , 'tests': [] , 'ravebc': self.raveBC.createBC("RAVE") }
            else:
                data = self.currentSuitePage["group"][group]["profiling"]
                
            data["tests"].append(test.name)
            rave = self.lprof.analyze(lprofFile, data)

            tl = [ test.name ]
            for raveFcns in self.lprof.raveFunctions:
                if rave.has_key(raveFcns):
                    tl.append(rave[raveFcns])
                else:
                    tl.append(0)
            self.raveBC.fillData(tl, data["ravebc"].datalist)

    def extractTimeSpent(self, test, solution, group):
        colgenNotFound = 1
        while solution:
            lastSolution = solution.pop()
            if lastSolution["Active method"] == "column generator":
                break
        if not lastSolution["Active method"] == "column generator":
            return
        
        totTime = int(lastSolution["cpu time"]*60)
        # Skip runs shorter than 2 minutes. 
        if totTime < 2*60:
            return
        sum = 0
        tl = [ test.name ]
        for val in self.definingValues + self.interestingValues:
            if lastSolution.has_key(val):
                sum += lastSolution[val]
                tl.append(lastSolution[val])
            else:
                tl.append(0)
        tl.append(totTime - sum)

        # Fill data into barchart
        if self.currentSuitePage["group"][group]["barcharts"]:
            chartabs, chartrel = self.currentSuitePage["group"][group]["barcharts"]
        else:
            self.currentSuitePage["group"][group]["barcharts"] = chartabs, chartrel = self.timeSpentBC.createRelAbsBC()

        chartdata = chartabs.datalist, chartrel.datalist
        self.timeSpentBC.fillDataRelAbs(tl, totTime, chartdata)

