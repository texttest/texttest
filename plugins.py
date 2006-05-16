
import signal, sys, os, log4py, string, shutil, time, re, stat
from types import FileType
from ndict import seqdict
from traceback import format_exception
from threading import currentThread

# Useful utility...
def localtime(format="%d%b%H:%M:%S", seconds=None):
    if not seconds:
        seconds = time.time()
    return time.strftime(format, time.localtime(seconds))

globalStartTime = time.time()

def startTimeString():
    global globalStartTime
    return localtime(seconds=globalStartTime)

# Need somewhat different formats on Windows/UNIX
tmpString = "tmp"
if os.environ.has_key("USER"):
    tmpString = os.getenv("USER")

def makeString(char, length):
    if length <= 0:
        return ""
    result = ""
    for x in range(length):
        result += char
    return result
        
# Adjust (left/center/right) text in string of a specified length,
# i.e. pad with spaces to the left and/or right.
def adjustText(text, length, adjustment):
    if adjustment == "left":
        return text + makeString(' ', length - len(text))
    elif adjustment == "center":
        leftSpaces = (length - text) / 2
        rightSpaces = length - text - leftSpaces # To adjust for integer division (text will be exactly in the middle, or one step to the left)
        return makeString(' ', leftSpaces) + text + makeString(' ', rightSpaces)
    else:
        return makeString(' ', length - len(text)) + text        

# Parse a time string, either a HH:MM:SS string, or a single int/float,
# which is interpreted as a number of minutes, for backwards compatibility.
# Observe that in either 'field' in the HH:MM:SS case, any number is allowed,
# so e.g. 144:5.3:0.01 is interpreted as 144 hours + 5.3 minutes + 0.01 seconds.
def getNumberOfSeconds(timeString):
    parts = timeString.split(":")
    if len(parts) > 3:
        raise "Illegal time format '" + timeString + "' :  Use format HH:MM:SS or MM:SS, or a single number to denote a number of minutes."
    if len(parts) == 1:  # Backwards compatible, assume single ints/floats means minutes
        return 60 * float(timeString)
    else:                # Assume format is HH:MM:SS ...
        seconds = 0
        for i in range(len(parts) - 1, -1, -1):
            if (parts[i] != ""): # Handle empty strings (<=:10 gives empty minutes field, for example)
                seconds += float(parts[i]) * pow(60, len(parts) - 1 - i)                
        return seconds 

# Useful stuff to handle regular expressions
regexChars = re.compile("[\^\$\[\]\{\}\\\*\?\|]")    
def isRegularExpression(text):
    return (regexChars.search(text) != None)
def findRegularExpression(expr, text):
    try:
        regExpr = re.compile(expr)
        return regExpr.search(text)
    except:
        return False

# Generic configuration class
class Configuration:
    CLEAN_NONE = 0
    CLEAN_SELF = 1
    CLEAN_PREVIOUS = 2
    def __init__(self, optionMap):
        self.optionMap = optionMap
    def addToOptionGroups(self, app, groups):
        pass
    def getActionSequence(self):
        return []
    def getResponderClasses(self, allApps):
        return []
    def getFilterList(self, app):
        return []
    def setEnvironment(self, test):
        pass
    def getPossibleResultFiles(self, app):
        return []
    def getCleanMode(self):
        return self.CLEAN_SELF
    def getWriteDirectoryName(self, app):
        return app.getStandardWriteDirectoryName()
    def getRunOptions(self):
        return ""
    def useExtraVersions(self):
        return 1
    def printHelpText(self):
        pass
    def extraReadFiles(self, test):
        return {}
    def getTextualInfo(self, test):
        return ""
    def setApplicationDefaults(self, app):
        pass
    
# Filter interface: all must provide these three methods
class Filter:
    def acceptsTestCase(self, test):
        return 1
    def acceptsTestSuite(self, suite):
        return 1
    def acceptsTestSuiteContents(self, suite):
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
    # Return the actions to replace the current one if run is interrupted
    def getInterruptActions(self, fetchResults):
        if fetchResults:
            return [ self ]
        else:
            return []
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
    showExecHosts = 0
    def __init__(self, category, freeText = "", briefText = "", started = 0, completed = 0,\
                 executionHosts = [], lifecycleChange = ""):
        self.category = category
        self.freeText = freeText
        self.briefText = briefText
        self.started = started
        self.completed = completed
        self.executionHosts = executionHosts
        self.lifecycleChange = lifecycleChange
    def __str__(self):
        return self.freeText
    def __repr__(self):
        if not self.categoryDescriptions.has_key(self.category):
            return self.category + self.hostRepr()
        briefDescription, longDescription = self.categoryDescriptions[self.category]
        return longDescription + self.hostRepr()
    def hostString(self):
        if len(self.executionHosts) == 0:
            return "(no execution hosts given)"
        else:
            return "on " + string.join(self.executionHosts, ",")
    def hostRepr(self):
        if self.showExecHosts and len(self.executionHosts) > 0:
            return " " + self.hostString() + " :"
        else:
            return " :"
    def notifyInMainThread(self):
        # Hook to tell the state we're in the main thread, as some things can only be done there
        pass
    def needsRecalculation(self):
        # Is some aspect of the state out of date
        return 0
    # Used by text interface to print states
    def getDifferenceSummary(self):
        if self.freeText:
            return "not compared:  " + self.freeText
        else:
            return "not compared"
    def getTypeBreakdown(self):
        return self.category, self.briefText
    def ensureCompatible(self):
        # If loaded from old pickle files, can get out of date objects...
        pass
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
    def shouldAbandon(self):
        return self.category == "unrunnable"
    def isSaveable(self):
        return self.hasFailed() and self.hasResults()
    def updatePaths(self, newAbsPath, newWriteDir):
        pass

# Simple handle to get diagnostics object. Better than using log4py directly,
# as it ensures everything appears by default in a standard place with a standard name.
def getDiagnostics(diagName):
    return log4py.Logger().get_instance(diagName)

def getPersonalConfigDir():
    return os.getenv("TEXTTEST_PERSONAL_CONFIG", os.getenv("HOME"))

# Hacking around os.path.getcwd not working with AMD automounter
def abspath(relpath):
    if os.environ.has_key("PWD"):
        return os.path.join(os.environ["PWD"], relpath)
    else:
        return os.path.abspath(relpath)

def relpath(fullpath, parentdir):
    relPath = fullpath.replace(parentdir, "")
    if relPath == fullpath:
        # unrelated
        return None
    if relPath.startswith(os.sep):
        return relPath[1:]
    else:
        return relPath

def getTextTestName():
    return os.getenv("TEXTTEST_SLAVE_CMD", sys.argv[0])

def nullFileName():
    if os.name == "posix":
        return "/dev/null"
    else:
        return "nul"

def nullRedirect():
    stdoutRedirect = " > " + nullFileName() 
    if os.name == "posix":  
        return stdoutRedirect + " 2>&1"
    else:
        return stdoutRedirect + " 2> nul"

def canExecute(program):
    localName = program.split()[0]
    if os.name == "nt":
        localName += ".exe"
    for dir in os.environ["PATH"].split(os.pathsep):
        fullPath = os.path.join(dir, localName)
        if os.path.isfile(fullPath):
            return True
    return False

# Useful utility, free text input as comma-separated list which may have spaces
def commasplit(input):
    return map(string.strip, input.split(","))

# Another useful thing that saves an import and remembering weird stuff
def modifiedTime(filename):
    try:
        return os.stat(filename)[stat.ST_MTIME]
    except OSError:
        # Dead links etc.
        return None

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
    # Don't be somewhere under the directory when it's removed
    try:
        if os.getcwd().startswith(os.path.realpath(dir)):
            root, local = os.path.split(dir)
            os.chdir(root)
    except OSError:
        pass
    for i in range(attempts):
        try:
            shutil.rmtree(dir)
            return
        except OSError:
            if i == attempts - 1:
                print "Unable to remove directory", dir, ":"
                printException()
            else:
                print "Problems removing directory", dir, "- waiting 1 second to retry..."
                time.sleep(1)                

def readList(filename, autosort=0):
    items = []
    for longline in open(filename).readlines():
        line = longline.strip()
        if len(line) > 0 and not line.startswith("#"):
            items.append(line)
    if autosort:
        items.sort()
    return items

def inMainThread():
    return currentThread().getName() == "MainThread"

def chdir(dir):
    ensureDirectoryExists(dir)
    os.chdir(dir)

def openForWrite(path):
    ensureDirExistsForFile(path)
    return open(path, "w")

# Make sure the dir exists
def ensureDirExistsForFile(path):
    dir, localName = os.path.split(path)
    ensureDirectoryExists(dir)

def addLocalPrefix(fullPath, prefix):
    dir, file = os.path.split(fullPath)
    return os.path.join(dir, prefix + "_" + file)

def ensureDirectoryExists(path):
    if os.path.isdir(path):
        return
    try:
        os.makedirs(path)
    except OSError, detail:
        if os.path.isdir(path):
            return
        detailStr = str(detail)
        if detailStr.find("Interrupted system call") != -1 or detailStr.find("File exists") != -1:
            return ensureDirectoryExists(path)
        else:
            raise

def retryOnInterrupt(function, *args):
    try:
        return function(*args)
    except IOError, detail:
        if str(detail).find("Interrupted system call") != -1:
            return retryOnInterrupt(function, *args)
        else:
            raise

def printException():
    sys.stderr.write("Description of exception thrown :\n")
    type, value, traceback = sys.exc_info()
    exceptionString = string.join(format_exception(type, value, traceback), "")
    sys.stderr.write(exceptionString)
    return exceptionString

class PreviewGenerator:
    def __init__(self, maxWidth, maxLength, startEndRatio=1):
        self.maxWidth = maxWidth
        self.cutFromStart = int(maxLength * startEndRatio)
        self.cutFromEnd = maxLength - self.cutFromStart
    def getCutLines(self, file):
        lines = file.readlines()
        file.close()
        if len(lines) < self.cutFromEnd + self.cutFromStart:
            return lines
        
        cutLines = lines[:self.cutFromStart]
        if self.cutFromEnd > 0:
            cutLines.append("... extra data truncated by TextTest ...\n")
            cutLines += lines[-self.cutFromEnd:]    
        return cutLines
    def getPreview(self, file):
        cutLines = retryOnInterrupt(self.getCutLines, file)
        lines = map(self.getWrappedLine, cutLines)
        return string.join(lines, "")
    def getWrappedLine(self, line):
        if len(line) <= self.maxWidth:
            return line
        truncatedLine = line[:self.maxWidth]
        return truncatedLine + "\n" + self.getWrappedLine(line[self.maxWidth:])
    
# Exception to throw. It's generally good to throw this internally
class TextTestError(RuntimeError):
    pass

# Yes, we know that getopt exists. However it throws exceptions when it finds unrecognised things, and we can't do that...
class OptionFinder(seqdict):
    def __init__(self, args, defaultKey="default"):
        seqdict.__init__(self)
        self.buildOptions(args, defaultKey)
    def buildOptions(self, args, defaultKey):
        optionKey = None                                                                                         
        for item in args:    
            if item[0] == "-":                         
                optionKey = self.stripMinuses(item)
                self[optionKey] = ""
            elif optionKey:
                if len(self[optionKey]):
                    self[optionKey] += " "
                self[optionKey] += item.strip()
            else:
                self[defaultKey] = item
    def stripMinuses(self, item):
        if item[1] == "-":
            return item[2:].strip()
        else:
            return item[1:].strip()
    
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
        os.chdir(suite.getDirectory())
        self.callScript(suite, "suite_level")
    def setUpApplication(self, app):
        print self, "application", app
        os.chdir(app.getDirectory())
        os.system(self.script + " app_level " + app.name)
    def callScript(self, test, level):
        os.system(self.script + " " + level + " " + test.name + " " + test.app.name)

class TextTrigger:
    def __init__(self, text):
        self.text = text
        self.regex = None
        if isRegularExpression(text):
            try:
                self.regex = re.compile(text)
            except:
                pass
    def __repr__(self):
        return self.text
    def matches(self, line, lineNumber=0):
        if self.regex:
            return self.regex.search(line)
        else:
            return line.find(self.text) != -1
    def replace(self, line, newText):
        if self.regex:
            return re.sub(self.text, newText, line)
        else:
            return line.replace(self.text, newText)

class UNIXProcessHandler:
    def spawnProcess(self, commandLine, shellTitle, holdShell):
        if shellTitle:
            commandLine = "xterm" + self.getShellOptions(holdShell) + " -bg white -T '" + shellTitle + "' -e " + commandLine

        processId = os.fork()   
        if processId == 0:
            os.system(commandLine)
            os._exit(0)
        else:
            return processId, processId
    def getShellOptions(self, holdShell):
        if holdShell:
            return " -hold"
        else:
            return ""
    def hasTerminated(self, processId, childProcess=0):
        if childProcess:
            # This is much more efficient for forked children than calling ps...
            # Also, it doesn't leave defunct processes. Naturally, it doesn't work on other
            # processes...
            try:
                procId, status = os.waitpid(processId, os.WNOHANG)
                return procId > 0 or status > 0
            except OSError:
                return 1
        else:
            lines = os.popen("ps -p " + str(processId) + " 2> /dev/null").readlines()
            return len(lines) < 2 or lines[-1].strip().endswith("<defunct>")
    def findChildProcesses(self, pid):
        outLines = os.popen("ps -efl").readlines()
        return self.findChildProcessesInLines(pid, outLines)
    def findChildProcessesInLines(self, pid, outLines):
        processes = []
        for line in outLines:
            entries = line.split()
            if len(entries) > 4 and entries[4] == str(pid):
                childPid = int(entries[3])
                processes.append(childPid)
                processes += self.findChildProcessesInLines(childPid, outLines)
        return processes
    def findProcessName(self, pid):
        pslines = os.popen("ps -l -p " + str(pid) + " 2> /dev/null").readlines()
        if len(pslines) == 0:
            return self.findProcessName(pid)
        else:
            return pslines[-1].split()[-1]
    def kill(self, process, killSignal):
        return os.kill(process, killSignal)
    def getCpuTime(self, processId):
        # Not supported, mainly here for Windows
        return None

class WindowsProcessHandler:
    def __init__(self):
        self.processManagement = 1
        self.diag = None
        stdout = os.popen("handle none").read()
        if stdout.find("administrator") != -1:
            print "Cannot determine process IDs: possibly lack of administrator rights for 'handle'"
            self.processManagement = 0
    def spawnProcess(self, commandLine, shellTitle, holdShell):
        if not self.diag:
            self.diag = getDiagnostics("Windows Processes")
        # Start the process in a subshell so redirection works correctly
        args = [os.environ["COMSPEC"], self.getShellOptions(holdShell), commandLine ]
        processHandle = os.spawnv(os.P_NOWAIT, args[0], args)
        if not self.processManagement:
            return None, processHandle
        # As we start a shell, we have a handle on the shell itself, not
        # on the process running in it. Unlike UNIX, killing the shell is not enough!
        cmdProcId = self.findProcessId(processHandle)
        if not cmdProcId:
            self.diag.info("Process Handle " + str(processHandle) + " has already exited!")
            # The process may have already exited by this point, don't crash if so!
            return None, processHandle
        for subProcId, subProcHandle in self.findChildProcessesWithHandles(cmdProcId):
            return subProcId, processHandle
        # If no subprocesses can be found, just kill the shell
        return cmdProcId, processHandle
    def getShellOptions(self, holdShell):
        if holdShell:
            return "/K"
        else:
            return "/C"
    def findProcessId(self, processHandle):
        childProcesses = self.findChildProcessesWithHandles(str(os.getpid()))
        for subProcId, subProcHandle in childProcesses:
            if subProcHandle == processHandle:
                return subProcId
    def findChildProcesses(self, processId):
        return [ pid for pid, handle in self.findChildProcessesWithHandles(processId) ]
    def findChildProcessesWithHandles(self, processId):
        subprocesses = []
        stdout = os.popen("handle -a -p " + processId)
        for line in stdout.readlines():
            words = line.split()
            if len(words) < 2:
                continue
            if words[1] == "Process":
                processInfo = words[-1]
                idStart = processInfo.find("(")
                subprocesses.append((processInfo[idStart + 1:-1], self.getHandleId(words)))
        return subprocesses
    def findProcessName(self, processId):
        words = self.getPsWords(processId)
        return words[0]
    def getHandleId(self, words):
        try:
            # Drop trailing colon
            return int(words[0][:-1], 16)
        except ValueError:
            return
    def getPsWords(self, processId):
        stdout = os.popen("pslist " + str(processId))
        for line in stdout.readlines():
            words = line.split()
            if len(words) < 2:
                continue
            if words[1] == str(processId):
                return words
        return words
    def hasTerminated(self, processId, childProcess=0):
        words = self.getPsWords(processId)
        if len(words) > 2:
            return words[2] == "was"
        else:
            sys.stderr.write("Unexpected output from pslist for " + str(processId) + ": \n" + repr(words) + "\n")
            return 1
    def getCpuTime(self, processId):
        if not self.diag:
            self.diag = getDiagnostics("Windows Processes")
        words = self.getPsWords(processId)
        cpuEntry = words[6]
        self.diag.info("Cpu time for " + str(processId) + " is " + cpuEntry)
        try:
            hours, mins, seconds = cpuEntry.split(":")
            return 3600 * float(hours) + 60 * float(mins) + float(seconds)
        except ValueError:
            return None
    def kill(self, process, killSignal):
        return os.system("pskill " + str(process) + " > nul 2> nul")

class Process:
    if os.name == "posix":
        processHandler = UNIXProcessHandler()
    else:
        processHandler = WindowsProcessHandler()
    def __init__(self, processId):
        self.processId = processId
    def __repr__(self):
        return self.getName()
    def hasTerminated(self):
        for process in self.findAllProcesses():
            if not self.processHandler.hasTerminated(process.processId):
                return 0
        return 1
    def findAllProcesses(self):
        return [ self ] + self.findChildProcesses()
    def findChildProcesses(self):
        ids = self.processHandler.findChildProcesses(self.processId)
        return [ Process(id) for id in ids ]
    def getName(self):
        return self.processHandler.findProcessName(self.processId)
    def waitForTermination(self):
        while not self.hasTerminated():
            time.sleep(0.1)
    def runExitHandler(self):
        pass
    def killAll(self):
        processes = self.findAllProcesses()
        # Start with the deepest child process...
        processes.reverse()
        for index in range(len(processes)):
            verbose = index == 0
            processes[index].kill(verbose)
    def getCpuTime(self):
        return self.processHandler.getCpuTime(self.processId)
    def kill(self, verbose=1):
        if self.tryKill(signal.SIGINT, verbose):
            return
        if self.tryKill(signal.SIGTERM, verbose):
            return
        self.tryKill(signal.SIGKILL, verbose)
    def tryKill(self, killSignal, verbose=0):
        if verbose:
            print "Killed process", self.processId, "with signal", killSignal
        try:
            self.processHandler.kill(self.processId, killSignal)
        except OSError:
            pass
        for i in range(10):
            time.sleep(0.1)
            if self.processHandler.hasTerminated(self.processId):
                return 1
        return 0

# Generally useful class to encapsulate a background process, of which TextTest creates
# a few...
class BackgroundProcess(Process):
    def __init__(self, commandLine, description = "", testRun=0, exitHandler=None, exitHandlerArgs=(), shellTitle=None, holdShell=0):
        Process.__init__(self, None)
        self.commandLine = commandLine
        self.description = description
        if self.description == "":
            self.description = self.commandLine
        self.shellTitle = shellTitle
        self.holdShell = holdShell
        self.exitHandler = exitHandler
        self.exitHandlerArgs = exitHandlerArgs
        self.processHandle = None
        if not testRun:
            self.doFork()
    def __repr__(self):
        return self.commandLine.split()[0].lstrip()
    def doFork(self):
        self.processId, self.processHandle = self.processHandler.spawnProcess(self.commandLine, self.shellTitle, self.holdShell)
    def waitForStart(self):
        while self.processHandle is None:
            time.sleep(0.1)
    def runExitHandler(self):
        if self.exitHandler:
            self.exitHandler(*self.exitHandlerArgs)
    def waitForTermination(self):
        if self.processHandle != None:
            os.waitpid(self.processHandle, 0)
    def hasTerminated(self):
        if self.processId == None:
            return 1
        return self.processHandler.hasTerminated(self.processId, childProcess=1)
    
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
        self.possValUpdateMethod = None
        self.possValAppendMethod = None
    def setPossibleValuesUpdateMethod(self, method):
        self.possValUpdateMethod = method
        method(self.possibleValues)
    def setPossibleValuesAppendMethod(self, method):
        self.possValAppendMethod = method
        for value in self.possibleValues:
            method(value)
    def addPossibleValue(self, value):
        self.possibleValues.append(value)
        if self.possValUpdateMethod:
            self.possValUpdateMethod(self.possibleValues)
        else:
            self.possValAppendMethod(value)

class Switch(Option):
    def __init__(self, name, defaultValue, options):
        Option.__init__(self, name, defaultValue)
        self.options = options
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
            self.switches[key].defaultValue = value
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
    def addSwitch(self, key, name, value = 0, options = []):
        entryName = self.getEntryName(name)
        defaultValue = int(self.getDefault(entryName, value))
        self.switches[key] = Switch(name, defaultValue, options)
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
                commandLines.append("-" + key + " '" + option.getValue() + "'")
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
 
