
import os, plugins, guiplugins, default_gui, optimization, time, ravebased_gui

# Graphical import test
class ImportTestCase(default_gui.ImportTestCase):
    def addDefinitionFileOption(self):
        self.addOption("sp", "Subplan name")
    def getSubplanName(self):
        return self.optionGroup.getOptionValue("sp")
    def checkName(self, suite, testName):
        default_gui.ImportTestCase.checkName(self, suite, testName)
        if not suite.getEnvironment("CARMUSR"):
            raise plugins.TextTestError, "Not allowed to create tests under a suite where CARMUSR isn't defined"
        
        if len(self.getSubplanName()) == 0:
            raise plugins.TextTestError, "No subplan name given for new " + self.testType() + "!" + "\n" + \
                  "Fill in the 'Adding " + self.testType() + "' tab below."
    def getNewTestName(self):
        nameEntered = default_gui.ImportTestCase.getNewTestName(self)
        if len(nameEntered) > 0:
            return nameEntered
        # Default test name to subplan name
        subplan = self.getSubplanName()
        if len(subplan) == 0:
            return nameEntered
        root, local = os.path.split(subplan)
        return local
    def getOptions(self, suite):
        pass
    # getOptions implemented in subclasses
        
# This is the action responsible for plotting from the GUI.
class PlotTestInGUI(guiplugins.ActionTabGUI):
    def __init__(self, allApps, dynamic):
        guiplugins.ActionTabGUI.__init__(self, allApps, dynamic)
        self.dynamic = dynamic
        self.firstApp = allApps[0]
        self.testGraph = optimization.TestGraph(self.firstApp, self.optionGroup)
    def correctTestClass(self):
        return "test-case"
    def _getTitle(self):
        return "_Plot Graph"
    def __repr__(self):
        return "Plotting"
    def _getStockId(self):
        return "clear"    
    def getTabTitle(self):
        return "Graph"
    def getGroupTabTitle(self):
        return "Graph"
    def messageBeforePerform(self):
        return "Plotting tests ..."
    def messageAfterPerform(self):
        return "Plotted " + self.describeTests() + "."    
    def performOnCurrent(self):
        for test in self.currTestSelection:
            self.createGUIPlotObjects(test)
        self.plotGraph(self.currTestSelection[0].app.writeDirectory) # This is not correct if you plot multiple applications!
    def createGUIPlotObjects(self, test):
        logFileStem = self.optionGroup.getOptionValue("l")
        if self.dynamic:
            tmpFile = self.getTmpFile(test, logFileStem)
            if tmpFile:
                self.testGraph.createPlotObjects("this run", None, tmpFile, test, None)

        stdFile = test.getFileName(logFileStem)
        if stdFile:
            self.testGraph.createPlotObjects(None, None, stdFile, test, None)
        self.testGraph.createPlotObjectsForExtraVersions(test)

    def getTmpFile(self, test, logFileStem):
        if test.state.isComplete():
            try:
                fileComp, storageList = test.state.findComparison(logFileStem, includeSuccess=True)
                if fileComp:
                    return fileComp.tmpFile
            except AttributeError:
                pass
        else:
            tmpFile = self.getRunningTmpFile(test, logFileStem)
            if os.path.isfile(tmpFile):
                return tmpFile
    def getRunningTmpFile(self, test, logFileStem):
        return test.makeTmpFileName(logFileStem)
    def plotGraph(self, writeDirectory):
        try:
            plotProcess = self.testGraph.plot(writeDirectory, self)
            if plotProcess:
                # Should really monitor this and close it when GUI closes,
                # but it isn't a child process so this means ps and load on the machine
                #self.processes.append(plotProcess)
                guiplugins.scriptEngine.monitorProcess("plots graphs", plotProcess)
        finally:
            # The TestGraph is "used", create a new one so that the user can do another plot.
            self.testGraph = optimization.TestGraph(self.firstApp, self.optionGroup)

    
class StartStudio(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("sys", "Studio CARMSYS to use")
    def singleTestOnly(self):
        return True
    def correctTestClass(self):
        return "test-case"
    def _getTitle(self):
        return "Start Studio"
    def getTooltip(self):
        return "Start Studio"
    def updateOptions(self):
        self.optionGroup.setOptionValue("sys", self.currTestSelection[0].getEnvironment("CARMSYS"))
        return False
    def performOnCurrent(self):
        environ = self.currTestSelection[0].getRunEnvironment([ "CARMUSR", "CARMTMP" ])
        environ["CARMSYS"] = self.optionGroup.getOptionValue("sys")
        print "CARMSYS:", environ["CARMSYS"]
        print "CARMUSR:", environ["CARMUSR"]
        print "CARMTMP:", environ["CARMTMP"]
        fullSubPlanPath = self.currAppSelection[0]._getSubPlanDirName(self.currTestSelection[0])
        lPos = fullSubPlanPath.find("LOCAL_PLAN/")
        subPlan = fullSubPlanPath[lPos + 11:]
        localPlan = os.sep.join(subPlan.split(os.sep)[0:-1])
        environ["PATH"] += ":" + os.path.join(environ["CARMSYS"], "bin")            
        cmdArgs = [ "studio", "-w", "-p CuiOpenSubPlan(gpc_info,\"" + localPlan + "\",\"" + subPlan + "\",0)" ]
        nullFile = open(os.devnull, "w")
        try:
            guiplugins.processMonitor.startProcess(cmdArgs, description="Studio on " + subPlan,
                                                   stdout=nullFile, exitHandler=self.studioCompleted,
                                                   stderr=nullFile, env=environ)
        except OSError:
            raise plugins.TextTestError, "Cannot start studio from CARMSYS " + environ.get("CARMSYS")
    def studioCompleted(self):
        guiplugins.scriptEngine.applicationEvent("studio process to terminate")

class InteractiveActionConfig(ravebased_gui.InteractiveActionConfig):
    def getInteractiveActionClasses(self, dynamic):
        classes = ravebased_gui.InteractiveActionConfig.getInteractiveActionClasses(self, dynamic)
        classes.append(self.getPlotClass())
        if not dynamic:
            classes.append(StartStudio)
        return classes
    
    def getMenuNames(self):
        return ravebased_gui.InteractiveActionConfig.getMenuNames(self) + [ "optimization" ]

    def getPlotClass(self):
        return PlotTestInGUI

    def getDefaultAccelerators(self):
        dict = ravebased_gui.InteractiveActionConfig.getDefaultAccelerators(self)
        dict["plot_graph"] = "<control>p"
        return dict