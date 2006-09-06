
import sys, os, log4py, string, shutil, time, re, stat
from ndict import seqdict
from process import Process
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

textTestName = os.getenv("TEXTTEST_SLAVE_CMD", sys.argv[0])

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
    def hasPerformance(self, app):
        return False
    def getCleanMode(self):
        return self.CLEAN_SELF
    def getWriteDirectoryName(self, app):
        return app.getStandardWriteDirectoryName()
    def getCheckoutPath(self, app):
        return ""
    def getRunOptions(self, checkout):
        return ""
    def getFilterFilePath(self, app, localName, forWrite):
        return localName
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
            if self.freeText.find("\n") == -1:
                return "not compared:  " + self.freeText
            else:
                return "not compared:\n" + self.freeText
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
    normFull = os.path.normpath(fullpath)
    relPath = normFull.replace(os.path.normpath(parentdir), "")
    if relPath == normFull:
        # unrelated
        return None
    if relPath.startswith(os.sep):
        return relPath[1:]
    else:
        return relPath

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
def rmtree(dir, attempts=100):
    realDir = os.path.realpath(dir)
    if not os.path.isdir(realDir):
        print "Write directory", dir, "externally removed"
        return
    # Don't be somewhere under the directory when it's removed
    try:
        if os.getcwd().startswith(realDir):
            root, local = os.path.split(dir)
            os.chdir(root)
    except OSError:
        pass
    for i in range(attempts):
        try:
            shutil.rmtree(realDir)
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
            try:
                os.waitpid(self.processHandle, 0)
            except OSError:
                # if it's not there to wait for, don't throw...
                pass
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
        self.possValMethod = None
    def setPossibleValuesAppendMethod(self, method):
        self.possValMethod = method
        for value in self.possibleValues:
            method(value)
    def addPossibleValue(self, value):
        self.possibleValues.append(value)
        self.possValMethod(value)

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
    def description(self):
        description = self.name
        if len(self.options) > 0:
            description += self.options[-1]
        return description

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
                commandLines.append("-" + key + " \"" + option.getValue() + "\"")
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
 
