
import os, log4py, string, signal, shutil, time, re, stat
from types import FileType
from ndict import seqdict

# Generic configuration class
class Configuration:
    CLEAN_NONE = 0
    CLEAN_BASIC = 1
    CLEAN_NONBASIC = 2
    CLEAN_PREVIOUS = 4
    def __init__(self, optionMap):
        self.optionMap = optionMap
    def addToOptionGroups(self, app, groups):
        pass
    def getActionSequence(self):
        return []
    def getFilterList(self):
        return []
    def getExecuteCommand(self, binary, test):
        return binary + " " + test.options
    def getApplicationEnvironment(self, app):
        return []
    def getCleanMode(self):
        return self.CLEAN_BASIC | self.CLEAN_NONBASIC
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

def addCategory(name, briefDesc, longDesc = ""):
    if longDesc:
        TestState.categoryDescriptions[name] = briefDesc, longDesc
    else:
        TestState.categoryDescriptions[name] = briefDesc, briefDesc

# Generic state which tests can be in, should be overridden by subclasses
# Acts as a static state for tests which have not run (yet)
# Free text is text of arbitrary length: it will appear in the "Text Info" GUI window when the test is viewed
# and the "details" section in batch mode
# Brief text should be at most two or three words: it appears in the details column in the main GUI window and in
# the summary of batch mode
class TestState:
    categoryDescriptions = seqdict()
    def __init__(self, category, freeText = "", briefText = "", started = 0, completed = 0):
        self.category = category
        self.freeText = freeText
        self.briefText = briefText
        self.started = started
        self.completed = completed
    def __str__(self):
        return self.freeText
    def __repr__(self):
        if not self.categoryDescriptions.has_key(self.category):
            return self.category + " :"
        briefDescription, longDescription = self.categoryDescriptions[self.category]
        return longDescription + " :"
    def notifyInMainThread(self):
        # Hook to tell the state we're in the main thread, as some things can only be done there
        pass
    def needsRecalculation(self):
        # Is some aspect of the state out of date
        return 0
    def displayDataChange(self, oldState):
        return self.category != oldState.category or self.briefText != oldState.briefText
    def timeElapsedSince(self, oldState):
        return (self.isComplete() != oldState.isComplete()) or (self.hasStarted() != oldState.hasStarted())
    # Used by text interface to print states
    def getDifferenceSummary(self, actionDesc):
        if self.freeText:
            return "not compared:  " + self.freeText
        else:
            return "not compared"
    def getTypeBreakdown(self):
        return self.category, self.briefText
    def hasStarted(self):
        return self.started or self.completed
    def isComplete(self):
        return self.completed
    def hasSucceeded(self):
        return 0
    def hasFailed(self):
        return self.isComplete() and not self.hasSucceeded()
    def hasResults(self):
        # Do we have actual results that can be compared
        return 0
    def isSaveable(self):
        return self.hasFailed() and self.hasResults()
    def updateAbsPath(self, newAbsPath):
        pass
    def changeDescription(self):
        if self.isComplete():
            return "complete"
        elif self.hasStarted():
            return "start"
        return "become " + self.category

# Simple handle to get diagnostics object. Better than using log4py directly,
# as it ensures everything appears by default in a standard place with a standard name.
def getDiagnostics(diagName):
    return log4py.Logger().get_instance(diagName)

# Hacking around os.path.getcwd not working with AMD automounter
def abspath(relpath):
    if os.name == "posix":
        return os.path.join(os.environ["PWD"], relpath)
    else:
        return os.path.abspath(relpath)

# Useful utility, free text input as comma-separated list which may have spaces
def commasplit(input):
    return map(string.strip, input.split(","))

# Another useful thing that saves an import and remembering weird stuff
def modifiedTime(filename):
    return os.stat(filename)[stat.ST_MTIME]

# Another useful utility, for moving files around and copying where not possible
def movefile(sourcePath, targetFile):
    try:
        # This generally fails due to cross-device link problems
        os.rename(sourcePath, targetFile)
        os.utime(targetFile, None)
    except:
        shutil.copyfile(sourcePath, targetFile)
        try:
            # This can also fail due to permissions, but we don't care
            os.remove(sourcePath)
        except OSError:
            pass

# portable version of os.path.samefile
def samefile(writeDir, currDir):
    try:
        return os.path.samefile(writeDir, currDir)
    except:
        # samefile doesn't exist on Windows, but nor do soft links so we can
        # do a simpler version
        return os.path.normpath(writeDir) == os.path.normpath(currDir)

# Version of rmtree not prone to crashing if directory in use or externally removed
def rmtree(dir, attempts=5):
    if not os.path.isdir(dir):
        print "Write directory", dir, "externally removed"
        return
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

class TextTrigger:
    specialChars = re.compile("[\^\$\[\]\{\}\\\*\?\|]")    
    def __init__(self, text):
        self.text = text
        self.regex = None
        if self.specialChars.search(text) != None:
            try:
                self.regex = re.compile(text)
            except:
                pass
    def matches(self, line):
        if self.regex:
            return self.regex.search(line)
        else:
            return line.find(self.text) != -1

class UNIXProcessHandler:
    def spawnProcess(self, commandLine):
        processId = os.fork()   
        if processId == 0:
            os.system(commandLine)
            os._exit(0)
        else:
            return processId
    def hasTerminated(self, processId):
        # Works on child processes only. Do not use while killing...
        try:
            procId, status = os.waitpid(processId, os.WNOHANG)
            return procId > 0 or status > 0
        except OSError:
            return 1
    def kill(self, process, killSignal):
        return os.kill(process, killSignal)


class WindowsProcessHandler:
    def __init__(self):
        for dir in os.environ["PATH"].split(";"):
            fullPath = os.path.join(dir, "cmd.exe")
            if os.path.isfile(fullPath):
                self.cmdStarter = fullPath
    def spawnProcess(self, commandLine):
        # Start the process in a subshell so redirection works correctly
        args = [self.cmdStarter, "/C", commandLine ]
        processHandle = os.spawnv(os.P_NOWAIT, self.cmdStarter, args)
        return self.findProcessId(processHandle)
    def findProcessId(self, processHandle):
        stdout = os.popen("handle -a -p " + str(os.getpid()))
        for line in stdout.readlines():
            words = line.split()
            handleId = self.getHandleId(words)
            if handleId == processHandle:
                processInfo = words[-1]
                idStart = processInfo.find("(")
                return processInfo[idStart + 1:-1]
    def getHandleId(self, words):
        if len(words) == 0:
            return
        try:
            # Drop trailing colon
            return int(words[0][:-1], 16)
        except ValueError:
            return
    def hasTerminated(self, processId):
        stdout = os.popen("pslist " + str(processId))
        for line in stdout.readlines():
            if line.find("was not found") != -1:
                return 1
        return 0
    def kill(self, process, killSignal):
        return os.system("pskill " + str(process))

# Generally useful class to encapsulate a background process, of which TextTest creates
# a few... seems it only works on UNIX right now.
class BackgroundProcess:
    fakeProcesses = os.environ.has_key("TEXTTEST_NO_SPAWN")
    if os.name == "posix":
        processHandler = UNIXProcessHandler()
    else:
        processHandler = WindowsProcessHandler()
    def __init__(self, commandLine, testRun=0, exitHandler=None, exitHandlerArgs=()):
        self.commandLine = commandLine
        self.processId = None
        self.exitHandler = exitHandler
        self.exitHandlerArgs = exitHandlerArgs
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
        self.processId = self.processHandler.spawnProcess(self.commandLine)
    def waitForStart(self):
        while self.processId == None:
            time.sleep(0.1)
    def checkTermination(self):
        if not self.hasTerminated():
            return 0
        if self.exitHandler:
            self.exitHandler(*self.exitHandlerArgs)
        return 1
    def hasTerminated(self):
        if self.processId == None:
            return 1
        if not self.processHandler.hasTerminated(self.processId):
            return 0
        for process in findAllProcesses(self.processId):
            if process != self.processId and not self.processHandler.hasTerminated(process):
                return 0
        return 1
    def waitForTermination(self):
        if self.processId == None:
            return
        for process in findAllProcesses(self.processId):
            try:
                os.waitpid(process, 0)
            except OSError:
                pass
    def kill(self):
        processes = findAllProcesses(self.processId)
        # Just kill the deepest child process, that seems to work best...
        if len(processes) > 0:
            self.tryKillProcess(processes[-1])
        else:
            print "All child processes under", self.processId, "terminated, could not kill"
    def tryKillProcess(self, process):
        if self.tryKillProcessWithSignal(process, signal.SIGINT):
            return
        if self.tryKillProcessWithSignal(process, signal.SIGTERM):
            return
        self.tryKillProcessWithSignal(process, signal.SIGKILL)
    def tryKillProcessWithSignal(self, process, killSignal):
        try:
            self.processHandler.kill(process, killSignal)
            print "Killed process", process, "with signal", killSignal
        except OSError:
            print "Process", process, "already terminated, could not kill with signal", killSignal
            pass
        for i in range(10):
            time.sleep(0.1)
            if self._hasTerminatedNotChild(process):
                return 1
        return 0
    def _hasTerminatedNotChild(self, processId):
        lines = os.popen("ps -p " + str(processId)).readlines()
        return len(lines) < 2


# Find child processes. Note that this concept doesn't really exist on Windows, so we just return the process
def findAllProcesses(pid):
    if os.name != "posix":
        return [ pid ]
    processes = []
    stdin, stdout, stderr = os.popen3("ps -efl | grep " + str(pid))
    errMsg = stderr.read()
    outLines = stdout.readlines()
    if len(errMsg) > 0 and len(outLines) == 0:
        return findAllProcesses(pid)
    
    for line in outLines:
        entries = line.split()
        if entries[3] == str(pid) and line.find("<defunct>") == -1:
            processes.insert(0, pid)
        if entries[4] == str(pid):
            processes += findAllProcesses(int(entries[3]))
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
        self.resetMethod = None
    def reset(self):
        if self.defaultValue == 0 and self.resetMethod:
            self.resetMethod(1)
        else:
            Option.reset(self)

class OptionGroup:
    def __init__(self, name, defaultDict, possibleValueDict):
        self.name = name
        self.options = seqdict()
        self.switches = seqdict()
        self.defaultDict = defaultDict
        self.possibleValueDict = possibleValueDict
    def __repr__(self):
        return "OptionGroup " + self.name + "\n" + repr(self.options) + "\n" + repr(self.switches)
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
    def getDefault(self, name, value):
        if self.defaultDict.has_key(name):
            return self.defaultDict[name]
        else:
            return value
    def getDefaultPossiblilities(self, name, defaultValue, values):
        if self.possibleValueDict.has_key(name):
            return [ defaultValue ] + self.possibleValueDict[name] + values
        if not defaultValue in values:
            return [ defaultValue ] + values
        else:
            return values
    def getEntryName(self, name):
        return name.lower().replace(" ", "_")
    def addSwitch(self, key, name, value = 0, nameForOff = None):
        entryName = self.getEntryName(name)
        defaultValue = int(self.getDefault(entryName, value))
        self.switches[key] = Switch(name, defaultValue, nameForOff)
    def addOption(self, key, name, value = "", possibleValues = []):
        entryName = self.getEntryName(name)
        defaultValue = self.getDefault(entryName, value)
        defaultPossValues = self.getDefaultPossiblilities(entryName, defaultValue, possibleValues)
        self.options[key] = TextOption(name, defaultValue, defaultPossValues)
    def getSwitchValue(self, key, defValue = None):
        if self.switches.has_key(key):
            return self.switches[key].getValue()
        else:
            return self.getDefault(key, defValue)
    def getOptionValue(self, key, defValue = None):
        if self.options.has_key(key):
            return self.options[key].getValue()
        else:
            return self.getDefault(key, defValue)
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
 
