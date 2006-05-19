import plugins, os, re, string, math, exceptions, optimization, performance, time, copy, apc, sys
from testmodel import BadConfigError

try:
    import HTMLgen, barchart
except:
    raise BadConfigError, "Python modules HTMLgen and/or barchart not found. Try adding /users/johani/pythonpackages/HTMLgen to your PYTHONPATH."

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

# We extend this class in order to be able to use more than 6 colors....
class CarmenStackedBarChart(barchart.StackedBarChart):
    def initialize(self):
        barchart.StackedBarChart.initialize(self)
        self.colors = ('blue','red','yellow','purple','orange','green','black')
        barchart.barfiles['black'] = '../image/bar-black.gif'

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
        chart = CarmenStackedBarChart()
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
                              "CRCComputeValueArgs",
                              "CRCSetRotation",
                              "CRCModifyRotation",
                              "CRCCollectInfo",
                              "CRCApplicationRetrieveValue"]
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
    def __init__(self, args = None):
        htmlDir = None
        if args:
            htmlDir = args[0]
        self.htmlDir = "/carm/documents/Development/Optimization/Testing"
        if htmlDir and os.path.isdir(htmlDir):
            self.htmlDir = htmlDir
        else:
            print "No html dir specified/the dir does not exist, uses", self.htmlDir

        self.profilesDir = "/carm/documents/Development/Optimization/APC/profiles"
        self.profilesDirAsHtml = "http://www-oint.carmen.se/Development/Optimization/APC/profiles"
        self.indexFile = self.htmlDir + os.sep + "testindex.html"
        self.timeSpentFile = self.htmlDir + os.sep + "timespent.html"
        self.raveSpentFile = self.htmlDir + os.sep + "ravespent.html"
        self.hatedFcnsFile = self.htmlDir + os.sep + "hatedfcns.html"
        self.variationFile = self.htmlDir + os.sep + "variation.html"
        self.ruleFailureFile = self.htmlDir + os.sep + "rulefailures.html"
        self.interParamsFile = self.htmlDir + os.sep + "deadheadparams.html"
        
    def setUpApplication(self, app):
        # Override some setting with what's specified in the config file.
        dict = app.getConfigValue("apcinfo")
        if dict.has_key("profilesDir"):
            self.profilesDir = dict["profilesDir"]
        if dict.has_key("profilesDirAsHtml"):
            self.profilesDirAsHtml = dict["profilesDirAsHtml"]
        
        self.RCFile = app.dircache.pathName("apcinfo.rc")
        self.idoc = CarmenDocument(self.RCFile)
        self.ilist = HTMLgen.List(style="compact")
        self.idoc.append(self.ilist)
        self.numberOfTests = 0
        self.totalCPUtime = 0

        self.definingValues = [ "Network generation time", "Generation time", "Coordination time", "DH post processing" ]
        self.interestingValues = ["Conn fixing time", "OC to DH time"]
        #self.tsValues = self.definingValues + self.interestingValues + ["Other time"]
        self.tsValues = [ "Network gen", "Generation", "Coordination", "DH post", "Conn fix", "OC->DH", "Other" ]
        self.interestingParameters = [ "add_tight_deadheads_active_copies",
                                       "add_tight_deadheads_other",
                                       "add_all_passive_copies_of_active_flights",
                                       "add_all_other_local_plan_deadheads",
                                       "search_for_double_deadheads",
                                       "optimize_deadhead_chains",
                                       "use_ground_transport",
                                       "use_long_haul_preprocess",
                                       "search_oag_deadheads",
                                       "allow_oag_deadheads"]
        self.timeSpentBC = BarChart(self.tsValues)
        
        # The global chart for relative times.
        self.chartreldoc = CarmenDocument(self.RCFile)
        self.chartreldoc.title = "Where does APC spend time?"
        self.chartrelglob = CarmenStackedBarChart()
        self.chartrelglob.title = "Relative times"
        self.chartrelglob.datalist = barchart.DataList()
        self.chartrelglob.datalist.segment_names = tuple(self.tsValues)
        timeIntroFileName = os.path.join(self.htmlDir, 'timespent-intro-txt.html')
        if os.path.isfile(timeIntroFileName):
            self.chartreldoc.append_file(timeIntroFileName)
        self.chartreldoc.append(self.chartrelglob)
        self.chartreldoc.append(HTMLgen.Paragraph())
        self.chartreldoc.append(HTMLgen.Href('testindex.html', 'To test set page'))

        # Variation
        self.variationChart = barchart.BarChart()
        self.variationChart.datalist = barchart.DataList()
        self.variationChart.thresholds = (5, 10)
        self.variationChart.title = "Variation in per mil"
        self.variationDoc = CarmenDocument(self.RCFile)
        self.variationDoc.title = "Cost variation for different groups"
        variationIntroFileName = os.path.join(self.htmlDir, 'variation-intro-txt.html')
        if os.path.isfile(variationIntroFileName):
            self.variationDoc.append_file(variationIntroFileName)
        self.variationDoc.append(self.variationChart)
        
        # Rule failures
        self.ruleFailureChart = barchart.BarChart()
        self.ruleFailureChart.datalist = barchart.DataList()
        self.ruleFailureChart.thresholds = (20, 60)
        self.ruleFailureChart.title = "Rule failures in percent"
        self.ruleFailureDoc = CarmenDocument(self.RCFile)
        self.ruleFailureDoc.title = "Rule failures for different groups"
        ruleFailureIntroFileName = os.path.join(self.htmlDir, 'rulefailures-intro-txt.html')
        if os.path.isfile(ruleFailureIntroFileName):
            self.ruleFailureDoc.append_file(ruleFailureIntroFileName)
        self.ruleFailureDoc.append(self.ruleFailureChart)

        # Table with interesting parameters
        self.interParamsDoc = CarmenDocument(self.RCFile)
        self.interParamsDoc.title = "Deadhead parameter settings"
        self.interParamsTable = HTMLgen.Table()
        self.interParamsTable.heading = copy.deepcopy(self.interestingParameters)
        self.interParamsTable.heading.insert(0, "KPI group")
        self.interParamsTable.body = []
        self.interParamsDoc.append(self.interParamsTable)
        
        self.kpiGroupForTest = {}
        self.kpiGroups = []
        self.kpiGroupsList = {}

        self.suitePages = {}

        # Profiling data.
        self.lprof = AnalyzeLProfData()
        self.raveBC = BarChart(self.lprof.raveFunctions) # Extract RAVE functions from profiling data.
        self.profilingGroups = HTMLgen.Container()
        self.profilingGroups.append(HTMLgen.Text("Used groups: "))

        # Global chart for relative RAVE times.
        self.chartRavedoc = CarmenDocument(self.RCFile)
        self.chartRavedoc.title = "Relative time spent by RAVE in APC"
        self.chartRaveglob = CarmenStackedBarChart()
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
        timeExplFileName = os.path.join(self.htmlDir, 'timespent-expl-txt.html')
        if os.path.isfile(timeExplFileName):
            self.chartreldoc.append_file(timeExplFileName)
        self.chartreldoc.write(self.timeSpentFile)

        # Write the Rave spent page.
        totalMeans = self.raveBC.doMeans(self.chartRaveglob.datalist, "ALL")
        self.chartRaveglob.datalist.load_tuple(tuple(totalMeans))
        #self.chartRavedoc.append_file(os.path.join(self.htmlDir, 'timespent-expl-txt.html'))
        self.chartRavedoc.write(self.raveSpentFile)

        # Write variation page
        self.variationDoc.write(self.variationFile)

        # Write rule failure page
        self.ruleFailureDoc.write(self.ruleFailureFile)

        # Write interesting parameters page
        self.interParamsDoc.write(self.interParamsFile)

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
                linkToTest = HTMLgen.Href(name + ".html" + "#" + groups, groups)
                
                # append cost_spread to variationChart
                cost_spread, meanvar = self.calcCostAndPerfMeanAndVariation(suitePage["group"][groups]["table"])
                if cost_spread*1000 <= 20:
                    self.variationChart.datalist.load_tuple((linkToTest, cost_spread*1000))
                
                ruleFailureAvg = suitePage["group"][groups]["rulecheckfailureavg"]/suitePage["group"][groups]["numtests"]
                self.ruleFailureChart.datalist.load_tuple((linkToTest, 100*ruleFailureAvg))
                # Insert interesting params into table.
                row = [ linkToTest ]
                for params in self.interestingParameters:
                    if suitePage["group"][groups]["interestingParameters"].has_key(params):
                        row.append(suitePage["group"][groups]["interestingParameters"][params])
                    else:
                        row.append("-")
                self.interParamsTable.body.append(row)
            table = HTMLgen.Table()
            table.body = suitePage["group"][groups]["table"]
            table.heading = ["Test", "Cost", "Perf. (min)", "Mem (MB)", "Uncov", "Overcov", "Illegal", "Rule checks/failures", "Date"]
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
                page.append("Used tests for profiling results: ")
                page.append(self.findProfilingGraph(name, data["tests"]))
                self.profilingGroups.append(HTMLgen.Href(name + ".html" + "#" + groups, HTMLgen.Text(groups)))

    def findProfilingGraph(self, suite, tests):
        profTests = HTMLgen.Container()
        if not os.path.isdir(self.profilesDir):
            return profTests
        filesInProfileDir = os.listdir(self.profilesDir)
        for test in tests:
            foundProfile = 0
            lookForFileStartingWith = suite + "__" + test + "_t5_prof.ps"
            for file in filesInProfileDir:
                if file.find(lookForFileStartingWith) != -1:
                    foundProfile = 1
                    break
            if foundProfile:
                profTests.append(HTMLgen.Href(self.profilesDirAsHtml + os.sep + file, HTMLgen.Text(test)))
            else:
                profTests.append(HTMLgen.Text(test))
        return profTests

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
        return cost_spread, meanvar
        
    def createGroupInfo(self, group, test):
        subplanDir = test.app.configObject.target._getSubPlanDirName(test)
        info = HTMLgen.Paragraph()

        # Info from status file
        logFile = test.getFileName(test.app.getConfigValue("log_file"))
        optRun = optimization.OptimizationRun(test.app, ["legs\.", optimization.periodEntryName] ,[] ,logFile)
        if optRun.solutions:
            input = optRun.solutions[0]
            period_start, period_end = input[optimization.periodEntryName]
            date_start = time.mktime(time.strptime(period_start.strip(), "%Y%m%d"))
            date_end = time.mktime(time.strptime(period_end.strip(), "%Y%m%d"))
            
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
        interestingParametersFound = {}
        inter = { "num_col_gen_objective_components" : { 'val': None, 'text': "Cost components" },
                  "num_col_gen_resource_components" : { 'val': None, 'text': "Resources components" }}
        ruleFile = os.path.join(subplanDir, "APC_FILES", "rules")
        if os.path.isfile(ruleFile):
            for line in open(ruleFile).xreadlines():
                items = line.split()
                parameter = items[0].split(".")[-1]
                if inter.has_key(parameter):
                    inter[parameter]["val"] = items[1]
                if self.interestingParameters.count(parameter) > 0:
                    interestingParametersFound[parameter] = items[1]

            for item in inter.keys():
                entry = inter[item]
                if entry["val"]:
                    info.append(entry["text"] + ": " + entry["val"] + " ")
                else:
                    info.append(entry["text"] + ": 0 ")

        self.currentSuitePage["group"][group]["info"] = info
        self.currentSuitePage["group"][group]["interestingParameters"] = interestingParametersFound
    
    def readKPIGroupFile(self, suite):
        self.kpiGroupForTest, self.kpiGroups, scales = apc.readKPIGroupFileCommon(suite)
        self.kpiGroupsList = {}
                
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
        self.currentSuite = suite
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
            self.currentSuitePage["group"][group] = { 'info': None , 'barcharts': None , 'table': [] , 'profiling': {} , 'rulecheckfailureavg': 0 , 'numtests': 0, 'interestingParameters': None}
            if not group == "common":
                self.createGroupInfo(group, test)

        tableDate = "-"
        tableUncovered = -1
        tableOvercovered = -1
        tableIllegal = -1
        tableCost = 0
        tableRuleChecks = 0
        tableRuleFailures = 0
        logFile = test.getFileName(test.app.getConfigValue("log_file"))
        ruleFailureItems = ["Rule checks\.", "Failed due to rule violation\."]
        optRun = optimization.OptimizationRun(test.app,  [ optimization.timeEntryName, optimization.activeMethodEntryName, optimization.dateEntryName, optimization.costEntryName], ["uncovered legs\.", "overcovers", "^\ illegal trips"] + self.definingValues + self.interestingValues + ruleFailureItems, logFile)
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
            # Rule checks
            tableRuleChecks, tableRuleFailures = self.extractFromLastColGenSol(test, optRun.solutions, group)
            avg = 0
            if tableRuleChecks > 0:
                avg = float(tableRuleFailures)/float(tableRuleChecks)
                self.currentSuitePage["group"][group]["rulecheckfailureavg"] += avg
            tableRuleStr = "%d/%d (%.2f)" % (tableRuleChecks, tableRuleFailures, avg)
        else:
            print "Warning, no solution in OptimizationRun!"

        self.extractProfiling(test, group)
        
        # Table
        testPerformance = performance.getTestPerformance(test) / 60 # getTestPerformance is seconds now ...
        testMemory = performance.getTestMemory(test)
        if testMemory > 0:
            testMemory = str(testMemory)
        else:
            testMemory = "-"
        tableRow = [ test.name, tableCost, float(int(10*testPerformance))/10, testMemory,
                     tableUncovered, tableOvercovered, tableIllegal, tableRuleStr, tableDate ]
        self.currentSuitePage["group"][group]["table"].append(tableRow)
        self.currentSuitePage["group"][group]["numtests"] += 1
        self.totalCPUtime += testPerformance
        
    def extractProfiling(self, test, group):
        lprofFile = os.path.join(self.profilesDir, self.currentSuite.name + "__" + test.name + "_lprof.apc")
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

    def extractFromLastColGenSol(self, test, solution, group):
        while solution:
            lastSolution = solution.pop()
            if lastSolution["Active method"] == "column generator":
                break
        if not lastSolution["Active method"] == "column generator":
            print "Warning: didn't find last colgen solution!"
            return 0, 0
        
        totTime = int(lastSolution["cpu time"]*60)
        # Skip runs shorter than 2 minutes. 
        if totTime < 2*60:
            return 0, 0
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

        ruleChecks = 0
        ruleFailures = 0
        if lastSolution.has_key("Rule checks\."):
            ruleChecks = lastSolution["Rule checks\."]
        if lastSolution.has_key("Failed due to rule violation\."):
            ruleFailures = lastSolution["Failed due to rule violation\."]
        return ruleChecks, ruleFailures


class PlotKPIGroupsAndGeneratePage(apc.PlotKPIGroups):
    def __init__(self, args = []):
        self.dir = None
        for arg in args:
            if arg.find("d=") != -1:
                self.dir = arg
        if not self.dir:
            raise plugins.TextTestError, "No directory specified"
        args.remove(self.dir)
        self.dir = os.path.expanduser(self.dir[2:])
        if not os.path.isdir(self.dir):
            try:
                os.mkdir(self.dir)
            except:
                raise plugins.TextTestError, "Failed to create dir " + self.dir
        apc.PlotKPIGroups.__init__(self, args)
    def __del__(self):
        self.onlyAverage = 0
        apc.PlotKPIGroups.__del__(self)
        self.onlyAverage = 1
        apc.PlotKPIGroups.__del__(self)
        # Now generate a simple HTML doc.
        doc = HTMLgen.SimpleDocument(title="")
        introFile = os.path.join(self.dir, "intro.html")
        if os.path.isfile(introFile):
            doc.append_file(introFile)
        table = HTMLgen.TableLite(border=2, cellpadding=4, cellspacing=1,width="100%")
        for group in self.allGroups:
            table.append(HTMLgen.TR() + [HTMLgen.TH("KPI group " + group, colspan = 2)])
            table.append(HTMLgen.TR() + [ HTMLgen.TD(HTMLgen.Image(self.getPlotName(group, 0, None))),
                                          HTMLgen.TD(HTMLgen.Image(self.getPlotName(group, 1, None)))])
        doc.append(table)
        doc.append(HTMLgen.Heading(5, "Generated by " + string.join(sys.argv)))
        doc.write(os.path.join(self.dir, "index.html"))
    def setExtraOptions(self, optionGroup, group):
        optionGroup.setValue("av", not self.onlyAverage)
        optionGroup.setValue("oav", self.onlyAverage)
        optionGroup.setValue("pc", 1)
        optionGroup.setValue("p", self.getPlotName(group, self.onlyAverage))
        optionGroup.setValue("terminal", "png")
        if optionGroup.getOptionValue("engine") == "mpl":
            optionGroup.setValue("size", "5,5")
        else:
            optionGroup.setValue("size", "0.65,0.65")
        optionGroup.setValue("olav", 1)
    def getPlotName(self, group, average, fullPath = 1):
        plotName = group + str(average) + ".png"
        if fullPath:
            return os.path.join(self.dir, plotName)
        else:
            return plotName
