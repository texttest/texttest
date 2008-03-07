
import apc_basic_gui, optimization_gui, ravebased_gui, default_gui, guiplugins, plugins, os, sys, shutil, time
from apc import readKPIGroupFileCommon

class ViewApcLog(guiplugins.InteractiveAction):
    def __repr__(self):
        return "Viewing log of"
    def singleTestOnly(self):
        return True
    def inMenuOrToolBar(self):
        return False
    def performOnCurrent(self):
        viewLogScript = self.currTestSelection[0].makeTmpFileName("view_apc_log", forFramework=1)
        if os.path.isfile(viewLogScript):
            file = open(viewLogScript)
            cmdArgs = eval(file.readlines()[0].strip())
            file.close()
            guiplugins.processMonitor.startProcess(cmdArgs, "APC log viewer", scriptName="views the APC log")
        else:
            raise plugins.TextTestError, "APC log file not yet available"
    def _getTitle(self):
        return "View APC Log"

class SaveBestSolution(guiplugins.InteractiveAction):
    def inMenuOrToolBar(self):
        return False
    def singleTestOnly(self):
        return True
    def performOnCurrent(self):
        import shutil
        # If we have the possibility to save, we know that the current solution is best
        testdir = self.currTestSelection[0].parent.getDirectory(1)
        bestStatusFile = os.path.join(testdir, self.hostCaseName, "best_known_status");
        currentStatusFile = self.currTestSelection[0].makeTmpFileName("status")
        shutil.copyfile(currentStatusFile, bestStatusFile)

        bestSolFile = os.path.join(testdir, self.hostCaseName, "best_known_solution");
        currentSolFile = self.currTestSelection[0].makeTmpFileName("solution")
        shutil.copyfile(currentSolFile, bestSolFile)
        
    def _getTitle(self):
        return "Save best"

    def solutionIsBetter(self):
        parentDir = self.currTestSelection[0].parent.getDirectory(1)
        bestStatusFile = os.path.join(parentDir, self.hostCaseName, "best_known_status");
        statusFile = self.currTestSelection[0].makeTmpFileName("status")
        if not os.path.isfile(statusFile):
            return 0
        solutionFile = self.currTestSelection[0].makeTmpFileName("solution")
        if not os.path.isfile(solutionFile):
            return 0
        # read solutions
        items = ['uncovered legs', 'illegal pairings', 'overcovers', 'cost of plan', 'cpu time']
        itemNames = {'memory': 'Time:.*memory', 'cost of plan': 'TOTAL cost', 'new solution': 'apc_status Solution', 'illegal pairings':'illegal trips', 'uncovered legs':'uncovered legs\.', 'overcovers':'overcovers'}
        calc = optimization.OptimizationValueCalculator(items, statusFile, itemNames, []);
        sol=calc.getSolutions(items)
        if len(sol) == 0 :
            return 0
        if not os.path.isfile(bestStatusFile):
            return 1
        calcBestKnown = optimization.OptimizationValueCalculator(items, bestStatusFile, itemNames, []);
        solBest=calcBestKnown.getSolutions(items)
        #Check the 4 first items
        for i in range(4):
            if sol[-1][items[i]] < solBest[-1][items[i]]:
                return 1
            if sol[-1][items[i]] > solBest[-1][items[i]]:
                return 0
        #all equal
        return 0
        
    def findFirstInKPIGroup(self):
        gp=self.kpiGroupForTest[self.currTestSelection[0].name]
        tests = filter(lambda x:self.kpiGroupForTest[x] == gp, self.kpiGroupForTest.keys())
        tests.sort()
        return tests[0]

# This is the action responsible for selecting a KPI group in the GUI.
class SelectKPIGroup(guiplugins.InteractiveAction):
    def singleTestOnly(self):
        return True
    def correctTestClass(self):
        return "test-case"
    def __repr__(self):
        return "Select KPI group"
    def _getTitle(self):
        return "_Select KPI group"
    def getStockId(self):
        return "index"
    def getTabTitle(self):
        return "KPI group"
    def getGroupTabTitle(self):
        return "Select KPI group"
    def messageBeforePerform(self):
        return "Selecting tests in KPI group..."
    def messageAfterPerform(self):
        return self.message
    def performOnCurrent(self):
        tests = self.getTestsToSelect()
        if tests:
            self.notify("SetTestSelection", tests)
    def getTestsToSelect(self):
        suite = self.currTestSelection[0].parent
        kpiGroupForTest, kpiGroups, percscale = readKPIGroupFileCommon(suite)
        if not kpiGroupForTest.has_key(self.currTestSelection[0].name):
            self.message = "Test " + self.currTestSelection[0].name +  " is not in an KPI group."
            return self.currTestSelection

        kpiGroup = kpiGroupForTest[self.currTestSelection[0].name]
        tests = filter(lambda test: kpiGroupForTest.get(test.name) == kpiGroup, suite.testcases)
        self.message = "Selected " + str(len(tests)) + " tests in KPI group " + kpiGroup + "."
        return tests

# Specialization of plotting in the GUI for APC
class PlotTestInGUI(optimization_gui.PlotTestInGUI):
    def __init__(self, *args):
        optimization_gui.PlotTestInGUI.__init__(self, *args)
        self.addSwitch("kpi", "Plot kpi group")
        self.addSwitch("kpiscale", "Use kpi group percentage scale")
    def describeTests(self):
        return str(self.numPlottedTests) + " tests"
    def performOnCurrent(self):
        self.numPlottedTests = 0
        tests, percscale = self.findAllTests()
        for test in tests:
            self.createGUIPlotObjects(test)
            self.numPlottedTests += 1
        if self.optionGroup.getSwitchValue("per") and self.optionGroup.getSwitchValue("kpiscale"):
            if not percscale:
                percscale = "0:2"
            self.testGraph.optionGroup.setOptionValue("yr", percscale)
        self.plotGraph(self.currTestSelection[0].app.writeDirectory)
    def findAllTests(self):
        if not self.optionGroup.getSwitchValue("kpi"):
            return self.currTestSelection, None
        if len(self.currTestSelection) > 1:
            print "Only one test allowed to be selected when plotting KPI group."
            print "Ignoring 'Plot kpi group' setting and plot selected tests."
            return self.currTestSelection, None
        # Plot KPI group
        currentTest = self.currTestSelection[0] # Only one test!
        suite = currentTest.parent
        kpiGroupForTest, kpiGroups, percscale = readKPIGroupFileCommon(suite)
        if not kpiGroupForTest.has_key(currentTest.name):
            print "Test", currentTest.name, "is not in an KPI group."
            return [ currentTest ], None

        kpiGroup = kpiGroupForTest[currentTest.name]
        return filter(lambda test: kpiGroupForTest.get(test.name) == kpiGroup, suite.testcases), percscale[kpiGroup]
                
    def getRunningTmpFile(self, test, logFileStem):
        return test.makeTmpFileName("APC_FILES/" + logFileStem, forComparison=0)
    
# Specialization of plotting in the GUI for APC
class PlotProfileInGUIAPC(guiplugins.InteractiveAction):
    def __init__(self, allApps, dynamic):
        path = "/carm/proj/apc/bin"
        if not sys.path.count(path):
            sys.path.append(path)
        guiplugins.InteractiveAction.__init__(self, allApps, dynamic)
        self.dynamic = dynamic
        self.sizes = ["a4","a4l","a3","a3l"]
        self.addSwitch("size", "Size of plot:     ", 0, self.sizes);
        self.addOption("focus", "Focus on function", "")
        self.addOption("base", "Baseline profile version", "")
        self.addSwitch("aggregate", "Aggregate all selections")
        self.numPlottedTests = 0
    def __repr__(self):
        return "Plotting Profile"
    def _getTitle(self):
        return "_Plot Profile"
    def __repr__(self):
        return "Plotting Profile"
    def getStockId(self):
        return "clear"    
    def getTabTitle(self):
        return "Profile"
    def getGroupTabTitle(self):
        return "Profile"
    def messageBeforePerform(self):
        return "Plotting profiles for tests ..."
    def messageAfterPerform(self):
        return "Plotted " + self.describeTests() + " profiles."
    def correctTestClass(self):
        return "test-case"
    def describeTests(self):
        return str(self.numPlottedTests) + " tests"
    def performOnCurrent(self):
        tests = self.currTestSelection
        if len(tests) == 0:
            return
        writeDir = self.currTestSelection[0].app.writeDirectory
        if self.optionGroup.getSwitchValue("aggregate"):
            extra_info = self.getExtraInfo(tests[0],True);
            data = self.getProfileObj(tests[0])
            self.numPlottedTests +=1
            for test in tests[1:]:
                d2 = self.getProfileObj(test)
                data.add_profile(d2,1)
                self.numPlottedTests +=1
            self.profileTest(data,extra_info,writeDir)
        else:
            for test in tests:
                extra_info = self.getExtraInfo(test,False);
                data = self.getProfileObj(test)
                self.profileTest(data,extra_info,writeDir)
                self.numPlottedTests +=1
        
    def setPlotOptions(self,options):
        self.optionString = ""
        options["size"] = self.sizes[self.optionGroup.getSwitchValue("size")]
        options["focus"] = self.optionGroup.getOptionValue("focus")
    
    def profileTest(self,data,extra_info,writeDir):
        import sym_analyze2
        if not os.path.isdir(writeDir):
            os.makedirs(writeDir)
        ops = sym_analyze2.get_default_options();
        self.setPlotOptions(ops)
        ops["extra info"].extend(extra_info)
        if ops["focus"] != "" and not data.has_function_name(ops["focus"]):
            raise "Failed to find focus function"
        sin,sout = os.popen2("dot -Tps")
        sym_analyze2.print_dot(data,ops,sin)
        sin.close()
        ofname = os.path.join(writeDir,"%s.ps"%extra_info[0])
        outfile = open(ofname,"w")
        outfile.writelines(sout.readlines())
        outfile.close()
        cmd = "ggv %s"%ofname
        os.system(cmd)
    def getExtraInfo(self,test,aggregate):
        logFileStem = test.app.getConfigValue("log_file")
        rv = []
        if aggregate:
            rv.append("aggregate")
        else:
            rv.append(test.name)
        if not self.dynamic:
            return rv
        dataFile = ""
        try:
            fileComp, storageList = test.state.findComparison(logFileStem, includeSuccess=True)
            if fileComp:
                dataFile= fileComp.tmpFile
        except AttributeError:
            pass
        if dataFile != "":
            sys,date=False,False
            groupFile = open(dataFile)
            lines = groupFile.readlines();
            groupFile.close()
            for l in lines:
                if sys and date:
                    break
                if not sys and " CARMSYS" == l[:8]:
                    t = l.strip().split(":")
                    rv.append("CARMSYS:"+t[1])
                    sys = True
                if not date and l.find("library date") != -1:
                    t = l.strip().split(":")
                    rv.append("libdate:"+":".join(t[1:]))
                    date = True
        return rv
            
    def getProfileObj(self,test):
        import sym_analyze2
        profileStem = "symbolicdata"
        dataFile = ""
        if self.dynamic:
            try:
                fileComp, storageList = test.state.findComparison(profileStem, includeSuccess=True)
                if fileComp:
                    dataFile= fileComp.tmpFile
            except AttributeError:
                pass
        else:
            dataFile = test.getFileName(profileStem)
        if dataFile == "" or dataFile == None:
                raise "Did not find symbolic data file"
            
        data = sym_analyze2.data_file(dataFile)
        if self.optionGroup.getOptionValue("base"):
            refFile = test.getFileName(profileStem,self.optionGroup.getOptionValue("base"))
            if refFile:
                base = sym_analyze2.data_file(refFile)
                data.add_profile(base,-1)
            else:
                raise "Did not find reference symbolic data file"
        return data
        
            
    
class Quit(default_gui.Quit):
    def __init__(self, allApps, dynamic):
        self.dynamic = dynamic
        default_gui.Quit.__init__(self, allApps)
    def getConfirmationMessage(self):
        if self.dynamic:
            firstApp = guiplugins.guiConfig.apps[0]
            confirmTime = firstApp.getConfigValue("quit_ask_for_confirm")
            if confirmTime >= 0:
                start = plugins.globalStartTime
                now = time.time()
                elapsedTime = (now-start)/60.0
                if  elapsedTime >= confirmTime:
                    return "Tests have been runnning for %d minutes,\n are you sure you want to quit?" % elapsedTime
        return ""

class CVSLogInGUI(guiplugins.InteractiveAction):
    def inMenuOrToolBar(self):
        return False
    def singleTestOnly(self):
        return True
    def correctTestClass(self):
        return "test-case"
    def performOnCurrent(self):
        logFileStem = self.currTestSelection[0].app.getConfigValue("log_file")
        files = [ logFileStem ]
        files += self.currTestSelection[0].app.getConfigValue("cvs_log_for_files").split(",")
        cvsInfo = ""
        path = self.currTestSelection[0].getDirectory()
        for file in files:
            fileName = self.currTestSelection[0].getFileName(file)
            if fileName:
                cvsInfo += self.getCVSInfo(path, os.path.basename(fileName))
        self.notify("Information", "CVS Logs" + os.linesep + os.linesep + cvsInfo)
    def _getTitle(self):
        return "CVS _Log"
    def getCVSInfo(self, path, file):
        info = os.path.basename(file) + ":" + os.linesep
        cvsCommand = "cd " + path + ";cvs log -N -rHEAD " + file
        stdin, stdouterr = os.popen4(cvsCommand)
        cvsLines = stdouterr.readlines()
        if len(cvsLines) > 0:            
            addLine = None
            for line in cvsLines:
                isMinusLine = None
                if line.startswith("-----------------"):
                    addLine = 1
                    isMinusLine = 1
                if line.startswith("================="):
                    addLine = None
                if line.find("nothing known about") != -1:
                    info += "Not CVS controlled"
                    break
                if line.find("No CVSROOT specified") != -1:
                    info += "No CVSROOT specified"
                    break
                if addLine and not isMinusLine:
                    info += line
            info += os.linesep
        return info

class SelectTests(default_gui.SelectTests):
    def __init__(self, *args):
        default_gui.SelectTests.__init__(self, *args)
        self.features = []
    def addSuites(self, suites):
        default_gui.SelectTests.addSuites(self, suites)
        for suite in suites:
            featureFile = suite.getFileName("feature_defs")
            if featureFile:
                self.addSwitch("Selection type", "Selection type", 0,["ANY","ALL"]);
                for featureEntry in plugins.readList(featureFile):
                    tmp = featureEntry.split();
                    featureName = tmp[0].replace("_"," ") + " " + tmp[1]
                    featureValues =["off"]
                    featureValues.extend(tmp[-1].split(","))
                    self.addSwitch(featureEntry, featureName, 0,featureValues);
                    self.features.append(featureEntry)
    def getFilterList(self, *args, **kwargs):
        filters = default_gui.SelectTests.getFilterList(self, *args, **kwargs)    
        selectedFeatures = self.getSelectedFeatures()
        if len(selectedFeatures) > 0:
            guiplugins.guilog.info("Selected " + str(len(selectedFeatures)) + " features...")
            andOr = self.optionGroup.getSwitchValue("Selection type", 0)
            filters.append(FeatureFilter(selectedFeatures,andOr))
        return filters
    def getSelectedFeatures(self):
        result = []
        for feature in self.features:
            val = self.optionGroup.getSwitchValue(feature, 0)
            if val:
                # -1 due to the frist option being "off"
                result.append((feature,val-1))
        return result

class ImportTestSuite(ravebased_gui.ImportTestSuite):
    def getCarmtmpDirName(self, carmUsr):
        return ravebased_gui.ImportTestSuite.getCarmtmpDirName(self, carmUsr) + ".apc"
    
# Graphical import
class ImportTestCase(apc_basic_gui.ImportTestCase):
    def __init__(self, *args):
        apc_basic_gui.ImportTestCase.__init__(self, *args)
        self.addOption("perm", "Import KPI group permutations", "aan,aat,adn,adt,dan,dat,ddn,ddt",
                       possibleValues = ["aan,aat,adn,adt"])
        self.addSwitch("kpi", "Import KPI group", 0)
        self.perm = ""
    def performOnCurrent(self):
        if not self.optionGroup.getSwitchValue("kpi"):
            apc_basic_gui.ImportTestCase.performOnCurrent(self)
        else:
            self.importKPIGroup()
    def importKPIGroup(self):
        testNameSteam = self.getNewTestName()
        permutations = self.optionGroup.getOptionValue("perm").split(",")
        testNames = []
        suite = self.getDestinationSuite()
        for perm in permutations:
            testNames.append(testNameSteam + "_" + perm)
            self.checkName(suite, testNames[-1])
        # Two loops since I don't want to import half of the tests
        # and then get a failure from CheckName.
        isFirst = True
        for newTestName in testNames:
            if isFirst:
                placement = self.getPlacement()
                description = self.optionGroup.getOptionValue("desc")
                isFirst = False
            self.perm = "_" + newTestName.split("_")[-1]
            testDir = suite.writeNewTest(newTestName, description, placement)
            self.testImported = self.createTestContents(suite, testDir, description, placement)
            description = ""
            placement += 1
    def getSubplanName(self):
        return apc_basic_gui.ImportTestCase.getSubplanName(self) + self.perm


class InteractiveActionConfig(apc_basic_gui.InteractiveActionConfig):
    def getInteractiveActionClasses(self, dynamic):
        classes = apc_basic_gui.InteractiveActionConfig.getInteractiveActionClasses(self, dynamic)
        if dynamic:
            classes += [ ViewApcLog, SaveBestSolution ]
        classes += [ CVSLogInGUI, SelectKPIGroup, PlotProfileInGUIAPC ]
        return classes

    def getPlotClass(self):
        return PlotTestInGUI
    
    def getReplacements(self):
        rep = apc_basic_gui.InteractiveActionConfig.getReplacements(self)
        rep[default_gui.SelectTests] = SelectTests
        rep[default_gui.ImportTestCase] = ImportTestCase
        rep[default_gui.ImportTestSuite] = ImportTestSuite
        rep[default_gui.Quit] = Quit
        return rep
