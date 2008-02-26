
import plugins, os, sys, shutil, time, subprocess, operator, types
from jobprocess import JobProcess
from copy import copy, deepcopy
from threading import Thread
from glob import glob
from stat import *
from ndict import seqdict
from log4py import LOGLEVEL_NORMAL

guilog, guiConfig, scriptEngine = None, None, None

def setUpGlobals(dynamic, allApps):
    global guilog, guiConfig, scriptEngine
    from gtkusecase import ScriptEngine
    guiConfig = GUIConfig(dynamic, allApps)
    if dynamic:
        guilog = plugins.getDiagnostics("dynamic GUI behaviour")
    else:
        guilog = plugins.getDiagnostics("static GUI behaviour")
    scriptEngine = ScriptEngine(guilog, enableShortcuts=1)
    return guilog, guiConfig, scriptEngine

class GUIConfig:
    def __init__(self, dynamic, allApps):
        self.apps = allApps
        self.dynamic = dynamic
        self.hiddenCategories = map(self.getConfigName, self.getValue("hide_test_category"))
        self.colourDict = self.makeColourDictionary()
    def makeColourDictionary(self):
        dict = {}
        for app in self.apps:
            for key, value in self.getColoursForApp(app):
                if dict.has_key(key) and dict[key] != value:
                    plugins.printWarning("Test colour for state '" + key +\
                                     "' differs between applications, ignoring that from " + repr(app) + "\n" + \
                                     "Value was " + repr(value) + ", change from " + repr(dict[key]))
                else:
                    dict[key] = value
        return dict
    def getColoursForApp(self, app):
        colours = seqdict()
        for key, value in app.getConfigValue("test_colours").items():
            colours[self.getConfigName(key)] = value
        return colours.items()
    def _simpleValue(self, app, entryName):
        return app.getConfigValue(entryName)
    def _compositeValue(self, app, *args, **kwargs):
        return app.getCompositeConfigValue(*args, **kwargs)
    def _getFromApps(self, method, *args, **kwargs):
        prevValue = None
        for app in self.apps:
            currValue = method(app, *args, **kwargs)
            toUse = self.chooseValueFrom(prevValue, currValue)
            if toUse is None and prevValue is not None:
                plugins.printWarning("GUI configuration '" + "::".join(args) +\
                                     "' differs between applications, ignoring that from " + repr(app) + "\n" + \
                                     "Value was " + repr(currValue) + ", change from " + repr(prevValue))
            else:
                prevValue = toUse
        return prevValue
    def chooseValueFrom(self, value1, value2):
        if value1 is None or value1 == value2:
            return value2
        if value2 is None:
            return value1
        if type(value1) == types.ListType:
            return self.createUnion(value1, value2)

    def createUnion(self, list1, list2):
        result = []
        result += list1
        for entry in list2:
            if not entry in list1:
                result.append(entry)
        return result
    
    def getModeName(self):
        if self.dynamic:
            return "dynamic"
        else:
            return "static"
    def getConfigName(self, name, modeDependent=False):
        formattedName = name.lower().replace(" ", "_").replace(":", "_")
        if modeDependent:
            if len(name) > 0:
                return self.getModeName() + "_" + formattedName
            else:
                return self.getModeName()
        else:
            return formattedName
        
    def getValue(self, entryName, modeDependent=False):
        nameToUse = self.getConfigName(entryName, modeDependent)
        return self._getFromApps(self._simpleValue, nameToUse)
    def getCompositeValue(self, sectionName, entryName, modeDependent=False, defaultKey="default"):
        nameToUse = self.getConfigName(entryName, modeDependent)
        value = self._getFromApps(self._compositeValue, sectionName, nameToUse, defaultKey=defaultKey)
        if modeDependent and value is None:
            return self.getCompositeValue(sectionName, entryName)
        else:
            return value
    def getWindowOption(self, name):
        return self.getCompositeValue("window_size", name, modeDependent=True)
    def showCategoryByDefault(self, category):
        if self.dynamic:
            nameToUse = self.getConfigName(category)
            return nameToUse not in self.hiddenCategories
        else:
            return False    
    def getTestColour(self, category, fallback=None):
        if self.dynamic:
            nameToUse = self.getConfigName(category)
            if self.colourDict.has_key(nameToUse):
                return self.colourDict[nameToUse]
            elif fallback:
                return fallback
            else:
                return self.colourDict.get("failure")
        else:
            return self.getCompositeValue("test_colours", "static")
    
# The purpose of this class is to provide a means to monitor externally
# started process, so that (a) code can be called when they exit, and (b)
# they can be terminated when TextTest is terminated.
class ProcessTerminationMonitor(plugins.Observable):
    def __init__(self):
        plugins.Observable.__init__(self)
        self.processes = []
    def addMonitoring(self, process, description, exitHandler, exitHandlerArgs):
        self.processes.append((process, description))
        newThread = Thread(target=self.monitor, args=(process, exitHandler, exitHandlerArgs))
        newThread.start()
    def monitor(self, process, exitHandler, exitHandlerArgs):
        try:
            process.wait()
            if exitHandler:
                exitHandler(*exitHandlerArgs)
        except OSError:
            pass # Can be thrown by wait() sometimes when the process is killed
    def listRunning(self, processesToCheck):
        running = []
        if len(processesToCheck) == 0:
            return running
        for process, description in self.getRunningProcesses():
            for processToCheck in processesToCheck:
                if plugins.isRegularExpression(processToCheck):
                    if plugins.findRegularExpression(processToCheck, description):
                        running.append("PID " + str(process.pid) + " : " + description)
                        break
                elif processToCheck.lower() == "all" or description.find(processToCheck) != -1:
                    running.append("PID " + str(process.pid) + " : " + description)
                    break

        return running
    def getRunningProcesses(self):
        return filter(lambda (process, desc): process.poll() is None, self.processes)
    def notifyKillProcesses(self, sig=None):
        # Don't leak processes
        runningProcesses = self.getRunningProcesses()
        if len(runningProcesses) == 0:
            return
        self.notify("Status", "Terminating all external viewers ...")
        for process, description in runningProcesses:
            self.notify("ActionProgress", "")
            guilog.info("Killing '" + description + "' interactive process")
            JobProcess(process.pid).killAll(sig)
        

processTerminationMonitor = ProcessTerminationMonitor()
       
class InteractiveAction(plugins.Observable):
    def __init__(self, allApps, *args):
        plugins.Observable.__init__(self)
        self.currFileSelection = []
        self.currAppSelection = []
        self.diag = plugins.getDiagnostics("Interactive Actions")
        self.optionGroup = plugins.OptionGroup(self.getTabTitle())
        self.validApps = []
        for app in allApps:
            self.validApps.append(app)
            self.validApps += app.extras
    def __repr__(self):
        if self.optionGroup.name:
            return self.optionGroup.name
        else:
            return self.getTitle()
    def allAppsValid(self):
        for app in self.currAppSelection:
            if app not in self.validApps:
                self.diag.info("Rejecting due to invalid selected app : " + repr(app))
                return False
        return True
    def addSuites(self, suites):
        pass
    def getOptionGroups(self):
        if self.optionGroup.empty():
            return []
        else:
            return [ self.optionGroup ]
    def createOptionGroupTab(self, optionGroup):
        return optionGroup.switches or optionGroup.options
    def notifyNewTestSelection(self, tests, apps, rowCount, *args):
        self.updateSelection(tests, rowCount)
        self.currAppSelection = apps
        newActive = self.allAppsValid() and self.isActiveOnCurrent()
        self.diag.info("New test selection for " + self.getTitle() + "=" + repr(tests) + " : new active = " + repr(newActive))
        self.changeSensitivity(newActive)
        
    def notifyLifecycleChange(self, test, state, desc):
        newActive = self.isActiveOnCurrent(test, state)
        self.diag.info("State change for " + self.getTitle() + "=" + state.category + " : new active = " + repr(newActive))
        self.changeSensitivity(newActive)

    def updateFileSelection(self, files):
        self.currFileSelection = files
        newActive = self.isActiveOnCurrent()
        self.diag.info("New file selection for " + self.getTitle() + "=" + repr(files) + " : new active = " + repr(newActive))
        self.changeSensitivity(newActive)

    def changeSensitivity(self, newActive):
        self.notify("Sensitivity", newActive)
        if newActive:
            if self.updateOptions():
                self.notify("UpdateOptions")

    def updateSelection(self, tests, rowCount):
        pass
    def updateOptions(self):
        return False     
    def isActiveOnCurrent(self, *args):
        return True
    def canPerform(self):
        return True # do we want a button on the tab for this?

    # Should we create a gtk.Action? (or connect to button directly ...)
    def inMenuOrToolBar(self): 
        return True
    # Put the action in a button bar?
    def inButtonBar(self):
        return False
    def getStockId(self): # The stock ID for the action, in toolbar and menu.
        pass
    def getTooltip(self):
        return self.getScriptTitle(False)
    def getDialogType(self): # The dialog type to launch on action execution.
        try:
            self.confirmationMessage = self.getConfirmationMessage()
            if self.confirmationMessage:
                return "guidialogs.ConfirmationDialog"
            else:
                return ""
        except plugins.TextTestError, e:
            self.notify("Error", str(e))
    def getResultDialogType(self): # The dialog type to launch when the action has finished execution.
        return ""
    def getTitle(self, includeMnemonics=False):
        title = self._getTitle()
        if includeMnemonics:
            return title
        else:
            return title.replace("_", "")
    def getDirectories(self):
        return ([], None)
    def messageBeforePerform(self):
        # Don't change this by default, most of these things don't take very long
        pass
    def messageAfterPerform(self):
        return "Performed '" + self.getTooltip() + "' on " + self.describeTests() + "."
    def getConfirmationMessage(self):
        return ""
    def getTabTitle(self):
        return self.getGroupTabTitle()
    def getGroupTabTitle(self):
        # Default behaviour is not to create a group tab, override to get one...
        return "Test"
    def getScriptTitle(self, tab):
        baseTitle = self._getScriptTitle()
        if tab and self.inMenuOrToolBar():
            return baseTitle + " from tab"
        else:
            return baseTitle
    def _getScriptTitle(self):
        return self.getTitle()
    def addOption(self, key, name, value = "", possibleValues = [],
                  allocateNofValues = -1, description = "",
                  selectDir = False, selectFile = False):
        self.optionGroup.addOption(key, name, value, possibleValues,
                                   allocateNofValues, selectDir,
                                   selectFile, description)
    def addSwitch(self, key, name, defaultValue = 0, options = [], description = ""):
        self.optionGroup.addSwitch(key, name, defaultValue, options, description)
    def getTextTestArgs(self):
        if os.name == "nt" and plugins.textTestName.endswith(".py"):
            return [ "python", plugins.textTestName ] # Windows isn't clever enough to figure out how to run Python programs...
        else:
            return [ plugins.textTestName ]
    def listRunningProcesses(self):
        processesToReport = guiConfig.getCompositeValue("query_kill_processes", "", modeDependent=True)
        return processTerminationMonitor.listRunning(processesToReport)

    def startExternalProgram(self, cmdArgs, description = "", env=None, outfile=os.devnull, errfile=os.devnull, \
                             exitHandler=None, exitHandlerArgs=()):
        process = subprocess.Popen(cmdArgs, env=env, stdin=open(os.devnull), stdout=open(outfile, "w"), stderr=open(errfile, "w"), \
                                   startupinfo=plugins.getProcessStartUpInfo())
        processTerminationMonitor.addMonitoring(process, description, exitHandler, exitHandlerArgs)
        return process
    def startExtProgramNewUsecase(self, cmdArgs, usecase, outfile, errfile, \
                                  exitHandler, exitHandlerArgs, description = ""):
        environ = deepcopy(os.environ)
        recScript = os.getenv("USECASE_RECORD_SCRIPT")
        if recScript:
            environ["USECASE_RECORD_SCRIPT"] = plugins.addLocalPrefix(recScript, usecase)
        repScript = os.getenv("USECASE_REPLAY_SCRIPT")
        if repScript:
            # Dynamic GUI might not record anything (it might fail) - don't try to replay files that
            # aren't there...
            dynRepScript = plugins.addLocalPrefix(repScript, usecase)
            if os.path.isfile(dynRepScript):
                environ["USECASE_REPLAY_SCRIPT"] = dynRepScript
            else:
                del environ["USECASE_REPLAY_SCRIPT"]
        return self.startExternalProgram(cmdArgs, description, environ, outfile, errfile, exitHandler, exitHandlerArgs)
    def describe(self, testObj, postText = ""):
        guilog.info(testObj.getIndent() + repr(self) + " " + repr(testObj) + postText)
    def startPerform(self):
        message = self.messageBeforePerform()
        if message != None:
            self.notify("Status", message)
        self.notify("ActionStart", message)
        try:
            self.performOnCurrent()
            message = self.messageAfterPerform()
            if message != None:
                self.notify("Status", message)
        except plugins.TextTestError, e:
            self.notify("Error", str(e))
    def endPerform(self):
        self.notify("ActionStop", "")
    def perform(self):
        try:
            self.startPerform()
        finally:
            self.endPerform()
    
class SelectionAction(InteractiveAction):
    def __init__(self, allApps, *args):
        InteractiveAction.__init__(self, allApps)
        self.currTestSelection = []
        self.rootTestSuites = []
    def addSuites(self, suites):
        self.rootTestSuites = suites
    def updateSelection(self, tests, rowCount):
        self.currTestSelection = filter(lambda test: test.classId() == "test-case", tests)
    def isActiveOnCurrent(self, *args):
        return len(self.currTestSelection) > 0
    def describeTests(self):
        return str(len(self.currTestSelection)) + " tests"
    def isSelected(self, test):
        return test in self.currTestSelection
    def isNotSelected(self, test):
        return not self.isSelected(test)
    def findSelectGroup(self, app):
        for group in app.optionGroups:
            if group.name.startswith("Select"):
                return group
            
    def getCmdlineOption(self):
        selTestPaths = []
        for suite in self.rootTestSuites:
            selTestPaths.append("appdata=" + suite.app.name + suite.app.versionSuffix())
            for test in suite.testCaseList():
                if self.isSelected(test):
                    selTestPaths.append(test.getRelPath())
        return "-tp " + "\n".join(selTestPaths)
    
# The class to inherit from if you want test-based actions that can run from the GUI
class InteractiveTestAction(InteractiveAction):
    def __init__(self, validApps, *args):
        InteractiveAction.__init__(self, validApps, *args)
        self.currentTest = None
    def isActiveOnCurrent(self, *args):
        return self.currentTest is not None and self.correctTestClass()
    def correctTestClass(self):
        return self.currentTest.classId() == "test-case"
    def describeTests(self):
        return repr(self.currentTest)
    def inButtonBar(self):
        return not self.inMenuOrToolBar() and len(self.getOptionGroups()) == 0
    def updateSelection(self, tests, rowCount):
        if rowCount == 1:
            self.currentTest = tests[0]
        else:
            self.currentTest = None
    def startViewer(self, cmdArgs, description = "", env=None, exitHandler=None, exitHandlerArgs=()):
        testDesc = self.testDescription()
        fullDesc = description + testDesc
        process = self.startExternalProgram(cmdArgs, fullDesc, env=env, exitHandler=exitHandler, exitHandlerArgs=exitHandlerArgs)
        self.notify("Status", 'Started "' + description + '" in background' + testDesc + '.')
        return process
    def testDescription(self):
        if self.currentTest:
            return " (from test " + self.currentTest.uniqueName + ")"
        else:
            return ""
        

# Placeholder for all classes. Remember to add them!
class InteractiveActionHandler:
    def __init__(self):
        self.diag = plugins.getDiagnostics("Interactive Actions")
    def getMenuNames(self, allApps):
        names = []
        for app in allApps:
            config = self.getIntvActionConfig(app)
            for name in config.getMenuNames():
                if name not in names:
                    names.append(name)
        return names
    def getIntvActionConfig(self, app):
        module = app.getConfigValue("interactive_action_module")
        try:
            return self._getIntvActionConfig(module)
        except ImportError:
            return self._getIntvActionConfig("default_gui")
    def _getIntvActionConfig(self, module):
        command = "from " + module + " import InteractiveActionConfig"
        exec command
        return InteractiveActionConfig()
        
    def getInstances(self, dynamic, allApps):
        instances = []
        classNames = []
        for app in allApps:
            config = self.getIntvActionConfig(app)
            for className in config.getInteractiveActionClasses(dynamic):
                if not className in classNames:
                    for classToUse, relevantApps in self.findAllClasses(className, allApps, dynamic):
                        instances.append(self.tryMakeInstance(classToUse, relevantApps, dynamic))
                    classNames.append(className)
        return instances

    def findAllClasses(self, className, allApps, dynamic):
        classNames = seqdict()
        for app in allApps:
            config = self.getIntvActionConfig(app)
            replacements = config.getReplacements()
            if className in config.getInteractiveActionClasses(dynamic):
                realClassName = replacements.get(className, className)
                classNames.setdefault(realClassName, []).append(app)
        return classNames.items()
    
    def tryMakeInstance(self, className, apps, dynamic):
        # Basically a workaround for crap error message with variable className from python...
        try:
            instance = className(apps, dynamic)
            self.diag.info("Creating " + str(instance.__class__.__name__) + " instance for " + repr(apps))
            return instance
        except:
            # If some invalid interactive action is provided, need to know which
            sys.stderr.write("Error with interactive action " + str(className.__name__) + "\n")
            raise
        
        
interactiveActionHandler = InteractiveActionHandler()
