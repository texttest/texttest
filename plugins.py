
import os, log4py, string, signal, shutil, time
from types import FileType
from ndict import seqdict

# Generic configuration class
class Configuration:
    def __init__(self, optionMap):
        self.optionMap = optionMap
    def addToOptionGroup(self, group):
        pass
    def getActionSequence(self, useGui):
        return []
    def getFilterList(self):
        return []
    def getExecuteCommand(self, binary, test):
        return binary + " " + test.options
    def getVitalFiles(self, app):
        return [ app.getBinary() ]
    def hasPerformanceComparison(self, app):
        return 0
    def keepTmpFiles(self):
        return 0
    def printHelpText(self):
        pass
    def extraReadFiles(self, test):
        return {}
    def setApplicationDefaults(self, app):
        pass
    
# Filter interface: all must provide these three methods
class Filter:
    def acceptsTestCase(self, test):
        return 1
    def acceptsTestSuite(self, suite):
        return 1
    def acceptsApplication(self, app):
        return 1

# Generic action to be performed: all actions need to provide these methods
class Action:
    RETRY = 1
    WAIT = 2
    def __call__(self, test):
        pass
    def setUpSuite(self, suite):
        pass
    def setUpApplication(self, app):
        pass
    def tearDownSuite(self, suite):
        pass
    def getCleanUpAction(self):
        return None
    # Useful for printing in a certain format...
    def describe(self, testObj, postText = ""):
        print testObj.getIndent() + repr(self) + " " + repr(testObj) + postText
    def __repr__(self):
        return "Doing nothing on"
    def __str__(self):
        return str(self.__class__)

# Simple handle to get diagnostics object. Better than using log4py directly,
# as it ensures everything appears by default in a standard place with a standard name.
def getDiagnostics(diagName):
    return log4py.Logger().get_instance(diagName)

def getSelfTestDiagnostics(diagName, fileName):
    diag = getDiagnostics(diagName)
    if os.environ.has_key("TEXTTEST_NO_SPAWN"):
        diag.set_loglevel(log4py.LOGLEVEL_NORMAL)
        diag.set_target(os.path.abspath(fileName))
        diag.set_formatstring("%M")
    return diag

# Useful utility, free text input as comma-separated list which may have spaces
def commasplit(input):
    return map(string.strip, input.split(","))

# Another useful utility, for moving files around
def movefile(sourcePath, targetFile):
    try:
        # This generally fails due to cross-device link problems
        os.rename(sourcePath, targetFile)
    except:
        shutil.copyfile(sourcePath, targetFile)
        os.remove(sourcePath)

# portable version of os.path.samefile
def samefile(writeDir, currDir):
    try:
        return os.path.samefile(writeDir, currDir)
    except:
        # samefile doesn't exist on Windows, but nor do soft links so we can
        # do a simpler version
        return os.path.normpath(writeDir) == os.path.normpath(currDir)

# Version of rmtree not prone to crashing if directory in use
def rmtree(dir, attempts=5):
    for i in range(attempts):
        try:
            shutil.rmtree(dir)
            return
        except OSError:
            print "Write directory still in use, waiting 1 second to remove..."
            time.sleep(1)
    print "Something still using write directory", dir, ": leaving it"

# Exception to throw. It's generally good to throw this internally
class TextTestError(RuntimeError):
    pass

# Action for wrapping an executable that isn't Python, or can't be imported in the usual way
class NonPythonAction(Action):
    def __init__(self, actionText):
        self.script = os.path.abspath(actionText)
        if not os.path.isfile(self.script):
            raise TextTestError, "Could not find non-python script " + self.script
    def __repr__(self):
        return "Running script " + os.path.basename(self.script) + " for"
    def __call__(self, test):
        self.describe(test)
        self.callScript(test, "test_level")
    def setUpSuite(self, suite):
        self.describe(suite)
        os.chdir(suite.abspath)
        self.callScript(suite, "suite_level")
    def setUpApplication(self, app):
        print self, "application", app
        os.chdir(app.abspath)
        os.system(self.script + " app_level " + app.name)
    def callScript(self, test, level):
        os.system(self.script + " " + level + " " + test.name + " " + test.app.name)

# Generally useful class to encapsulate a background process, of which TextTest creates
# a few... seems it only works on UNIX right now.
class BackgroundProcess:
    fakeProcesses = os.environ.has_key("TEXTTEST_NO_SPAWN")
    def __init__(self, commandLine, testRun=0):
        self.commandLine = commandLine
        self.processId = None
        if not testRun:
            if not self.fakeProcesses:
                self.doFork()
            else:
                # When running self tests, we don't have time to start external programs and stop them
                # again, so we provide an environment variable to fake them all
                print "Faking start of external progam: '" + commandLine + "'"
    def __repr__(self):
        return self.commandLine.split()[0].lstrip()
    def doFork(self):
        processId = os.fork()
        if processId == 0:
            os.system(self.commandLine)
            os._exit(0)
        else:
            self.processId = processId
    def waitForStart(self):
        while self.processId == None:
            time.sleep(0.1)
    def hasTerminated(self):
        if self.processId == None:
            return 1
        if not self._hasTerminated(self.processId):
            return 0
        for process in self.findAllProcesses(self.processId):
            if process != self.processId and not self._hasTerminated(process):
                return 0
        return 1
    def _hasTerminated(self, processId):
        try:
            procId, status = os.waitpid(processId, os.WNOHANG)
            return procId > 0 or status > 0
        except OSError:
            return 1
    def waitForTermination(self):
        if self.processId == None:
            return
        for process in self.findAllProcesses(self.processId):
            try:
                os.waitpid(process, 0)
            except OSError:
                pass
    def kill(self):
        self.killWithSignal(signal.SIGTERM)
    def killWithSignal(self, killSignal):
        for process in self.findAllProcesses(self.processId):
            try:
                os.kill(process, killSignal)
                print "Killed process", process, "with signal", killSignal
            except OSError:
                pass
    def findAllProcesses(self, pid):
        processes = []
        processes.append(pid)
        for line in os.popen("ps -efl | grep " + str(pid)).xreadlines():
            entries = line.split()
            if entries[4] == str(pid):
                processes += self.findAllProcesses(int(entries[3]))
        return processes

class Option:    
    def __init__(self, name, value):
        self.name = name
        self.defaultValue = value
        self.valueMethod = None
        self.updateMethod = None
    def getValue(self):
        if self.valueMethod:
            return self.valueMethod()
        else:
            return self.defaultValue
    def setMethods(self, valueMethod, updateMethod):
        self.valueMethod = valueMethod
        self.updateMethod = updateMethod
    def reset(self):
        if self.updateMethod:
            self.updateMethod(self.defaultValue)
        else:
            self.valueMethod = None

class TextOption(Option):
    def __init__(self, name, value, possibleValues):
        Option.__init__(self, name, value)
        self.possibleValues = possibleValues

class Switch(Option):
    def __init__(self, name, value, nameForOff):
        Option.__init__(self, name, value)
        self.nameForOff = nameForOff

class OptionGroup:
    def __init__(self, name):
        self.name = name
        self.options = seqdict()
        self.switches = seqdict()
    def __repr__(self):
        return "OptionGroup " + self.name + os.linesep + repr(self.options) + os.linesep + repr(self.switches)
    def reset(self):
        for option in self.options.values():
            option.reset()
        for switch in self.switches.values():
            switch.reset()
    def setValue(self, key, value):
        if self.options.has_key(key):
            self.options[key].defaultValue = value
            return 1
        elif self.switches.has_key(key):
            self.switches[key].defaultValue = 1
            return 1
        return 0
    def addSwitch(self, key, name, value = 0, nameForOff = None):
        self.switches[key] = Switch(name, value, nameForOff)
    def addOption(self, key, name, value = "", possibleValues = None):
        self.options[key] = TextOption(name, value, possibleValues)
    def getSwitchValue(self, key, defValue = None):
        if self.switches.has_key(key):
            return self.switches[key].getValue()
        else:
            return defValue
    def getOptionValue(self, key, defValue = None):
        if self.options.has_key(key):
            return self.options[key].getValue()
        else:
            return defValue
    def getCommandLines(self):
        commandLines = []
        for key, option in self.options.items():
            if len(option.getValue()):
                commandLines.append("-" + key + " " + option.getValue())
        for key, switch in self.switches.items():
            if switch.getValue():
                commandLines.append("-" + key)
        return commandLines
    def readCommandLineArguments(self, args):
        for arg in args:
            if arg.find("=") != -1:
                option, value = arg.split("=")
                if self.options.has_key(option):
                    self.options[option].defaultValue = value
                else:
                    raise TextTestError, self.name + " does not support option '" + option + "'"
            else:
                if self.switches.has_key(arg):
                    oldValue = self.switches[arg].defaultValue
                    # Toggle the value from the default
                    self.switches[arg].defaultValue = 1 - oldValue
                else:
                    raise TextTestError, self.name + " does not support switch '" + arg + "'"
 
