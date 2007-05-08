
import sys, os, log4py, string, shutil, time, re, stat, locale, datetime, subprocess
from ndict import seqdict
from traceback import format_exception
from threading import currentThread
from Queue import Queue, Empty

# We standardise around UNIX paths, it's all much easier that way. They work fine,
# and they don't run into weird issues in being confused with escape characters

# basically posixpath.join, adapted to be portable...
def joinpath(a, *p):
    path = a
    for b in p:
        if os.path.isabs(b) and (path[1:2] != ":" or b[1:2] == ":"):
            path = b
        elif path == '' or path.endswith('/'):
            path +=  b
        else:
            path += '/' + b
    return path

os.path.join = joinpath
if os.name == "nt":
    import posixpath
    os.sep = posixpath.sep
    os.path.sep = posixpath.sep
    os.path.normpath = posixpath.normpath

# Useful utility...
def localtime(format= "%d%b%H:%M:%S", seconds=None):
    if not seconds:
        seconds = time.time()
    return time.strftime(format, time.localtime(seconds))

globalStartTime = time.time()

def startTimeString():
    global globalStartTime
    return localtime(seconds=globalStartTime)

textTestName = os.getenv("TEXTTEST_SLAVE_CMD", sys.argv[0])

def installationDir(name):
    installationRoot = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(installationRoot, name)

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

# Same as above, but gives minutes instead of seconds ...
def getNumberOfMinutes(timeString):
    return getNumberOfSeconds(timeString) / 60

# Show a human readable time difference string. Diffs larger than farAwayLimit are
# written as the actual 'to' time, while other diffs are written e.g. 'X days ago'.
# If markup is True, diffs less than closeLimit are boldified and diffs the same
# day are red as well.
def getTimeDifference(now, then, markup = True, \
                      closeLimit = datetime.timedelta(days=3), \
                      farAwayLimit = datetime.timedelta(days=7)):
    difference = now - then # Assume this is positive ...
    if difference > farAwayLimit:
        return then.ctime()

    stringDiff = str(difference.days) + " days ago"
    yesterday = now - datetime.timedelta(days=1)
    if now.day == then.day:
        stringDiff = "Today at " + then.strftime("%H:%M:%S")
        if markup:
            stringDiff = "<span weight='bold' foreground='red'>" + stringDiff + "</span>"
    elif yesterday.day == then.day and yesterday.month == then.month and yesterday.year == then.year:
        stringDiff = "Yesterday at " + then.strftime("%H:%M:%S")
        if markup:
            stringDiff = "<span weight='bold'>" + stringDiff + "</span>"
    elif difference <= closeLimit and markup:
        stringDiff = "<span weight='bold'>" + stringDiff + "</span>"
    return stringDiff

def printWarning(message):
    print "WARNING: " + message

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

# Parse the string as a byte expression.
# Mb/mb/megabytes/mbytes
def parseBytes(text):
    lcText = text.lower()
    try:
        # Try this first, to save time if it works
        try:
            return float(text) 
        except:
            pass
        
        if lcText.endswith("kb") or lcText.endswith("kbytes") or lcText.endswith("k") or lcText.endswith("kilobytes"):
            splitText = lcText.split('k')
            if len(splitText) > 2:
                raise
            return 1000 * float(splitText[0])
        elif lcText.endswith("kib") or lcText.endswith("kibibytes"):
            splitText = lcText.split('k')
            if len(splitText) > 2:
                raise
            return 1024 * float(splitText[0])
        elif lcText.endswith("mb") or lcText.endswith("mbytes") or lcText.endswith("m") or lcText.endswith("megabytes"):
            splitText = lcText.split('m')
            if len(splitText) > 2:
                raise 
            return 1000000 * float(splitText[0])
        elif lcText.endswith("mib") or lcText.endswith("mebibytes"):
            splitText = lcText.split('m')
            if len(splitText) > 2:
                raise
            return 1048576 * float(splitText[0])
        elif lcText.endswith("gb") or lcText.endswith("gbytes") or lcText.endswith("g") or lcText.endswith("gigabytes"):
            splitText = lcText.split('g')
            if len(splitText) > 2:
                raise
            return 1000000000 * float(splitText[0])
        elif lcText.endswith("gib") or lcText.endswith("gibibytes"):
            splitText = lcText.split('g')
            if len(splitText) > 2:
                raise
            return 1073741824 * float(splitText[0])
        elif lcText.endswith("tb") or lcText.endswith("tbytes") or lcText.endswith("t") or lcText.endswith("terabytes"):
            splitText = lcText.split('t')
            if len(splitText) > 3:
                raise
            return 1000000000000 * float(splitText[0])
        elif lcText.endswith("tib") or lcText.endswith("tebibytes"):
            splitText = lcText.split('t')
            if len(splitText) > 3:
                raise
            return 1099511627776 * float(splitText[0])
        elif lcText.endswith("pb") or lcText.endswith("pbytes") or lcText.endswith("p") or lcText.endswith("petabytes"):
            splitText = lcText.split('p')
            if len(splitText) > 2:
                raise
            return 10**15 * float(splitText[0])
        elif lcText.endswith("pib") or lcText.endswith("pebibytes"):
            splitText = lcText.split('p')
            if len(splitText) > 2:
                raise
            return 2**50 * float(splitText[0])
        elif lcText.endswith("eb") or lcText.endswith("ebytes") or lcText.endswith("e") or lcText.endswith("exabytes"):
            splitText = lcText.split('e')
            if len(splitText) > 3:
                raise
            return 10**18 * float(splitText[0])
        elif lcText.endswith("eib") or lcText.endswith("exbibytes"):
            splitText = lcText.split('e')
            if len(splitText) > 3:
                raise
            return 2**60 * float(splitText[0])
        elif lcText.endswith("zb") or lcText.endswith("zbytes") or lcText.endswith("z") or lcText.endswith("zettabytes"):
            splitText = lcText.split('z')
            if len(splitText) > 2:
                raise
            return 10**21 * float(splitText[0])
        elif lcText.endswith("zib") or lcText.endswith("zebibytes"):
            splitText = lcText.split('z')
            if len(splitText) > 2:
                raise
            return 2**70 * float(splitText[0])
        elif lcText.endswith("yb") or lcText.endswith("ybytes") or lcText.endswith("y") or lcText.endswith("yottabytes"):
            splitText = lcText.split('y')
            if len(splitText) > 3:
                raise
            return 10**24 * float(splitText[0])
        elif lcText.endswith("yib") or lcText.endswith("yobibytes"):
            splitText = lcText.split('y')
            if len(splitText) > 2:
                raise
            return 2**80 * float(splitText[0])
        else:
            return float(text) 
    except:
        raise "Illegal byte format '" + text + "'"

# pango markup doesn't like <,>,& ...
def convertForMarkup(message):
    return message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            
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
    def useExtraVersions(self, app):
        return True
    def printHelpText(self):
        pass
    def extraReadFiles(self, test):
        return {}
    def recomputeProgress(self, test, observers):
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
    def callDuringAbandon(self, test):
        # set to True if tests should have this action called even after all is reckoned complete (e.g. UNRUNNABLE)
        return False
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

class ScriptWithArgs(Action):
    def parseArguments(self, args):
        currKey = ""
        dict = {}
        for arg in args:
            if arg.find("=") != -1:
                currKey, val = arg.split("=")
                dict[currKey] = val
            elif dict.has_key(currKey):
                dict[currKey] += " " + arg
        return dict

def addCategory(name, briefDesc, longDesc = ""):
    if longDesc:
        TestState.categoryDescriptions[name] = briefDesc, longDesc
    else:
        TestState.categoryDescriptions[name] = briefDesc, briefDesc

# Observer mechanism shouldn't allow for conflicting notifications. Use main thread at all times
class ThreadedNotificationHandler:
    def __init__(self):
        self.workQueue = Queue()
        self.active = False
    def enablePoll(self, idleHandleMethod):
        self.active = True
        id = idleHandleMethod(self.pollQueue)
        return id
    def disablePoll(self):
        self.active = False
    def pollQueue(self):
        try:
            observable, args = self.workQueue.get_nowait()
            observable.notify(*args)
        except Empty:
            pass
        # Idle handler. We must sleep for a bit, or we use the whole CPU (busy-wait)
        time.sleep(0.1)
        return self.active
    def transfer(self, observable, *args):
        self.workQueue.put((observable, args))

class Observable:
    threadedNotificationHandler = ThreadedNotificationHandler()
    # allow calling code to block all notifications everywhere, during a shutdown
    blocked = False
    def __init__(self, passSelf=False):
        self.observers = []
        self.passSelf = passSelf
    def addObserver(self, observer):
        self.observers.append(observer)
    def setObservers(self, observers):
        self.observers = observers
    def inMainThread(self):
        return currentThread().getName() == "MainThread"
    def notify(self, *args):
        if self.blocked:
            return
        if self.threadedNotificationHandler.active and not self.inMainThread():
            self.threadedNotificationHandler.transfer(self, *args)
        else:
            self.performNotify(*args)
    def notifyIfMainThread(self, *args):
        if self.blocked or not self.inMainThread():
            return
        else:
            self.performNotify(*args)
    def performNotify(self, name, *args):
        methodName = "notify" + name
        for observer in self.observers:
            if hasattr(observer, methodName):
                retValue = self.notifyObserver(observer, methodName, *args)
                if retValue is not None: # break off the chain if we get a non-None value back
                    break
    def notifyObserver(self, observer, methodName, *args):
        # doesn't matter if only some of the observers have the method
        method = eval("observer." + methodName)
        # unpickled objects have not called __init__, and
        # hence do not have self.passSelf ...
        if hasattr(self, "passSelf") and self.passSelf:
            return method(self, *args)
        else:
            return method(*args)
            
# Generic state which tests can be in, should be overridden by subclasses
# Acts as a static state for tests which have not run (yet)
# Free text is text of arbitrary length: it will appear in the "Text Info" GUI window when the test is viewed
# and the "details" section in batch mode
# Brief text should be at most two or three words: it appears in the details column in the main GUI window and in
# the summary of batch mode
class TestState(Observable):
    categoryDescriptions = seqdict()
    showExecHosts = 0
    def __init__(self, category, freeText = "", briefText = "", started = 0, completed = 0,\
                 executionHosts = [], lifecycleChange = ""):
        Observable.__init__(self)
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
        return self.categoryRepr() + self.hostRepr() + self.colonRepr()
    def categoryRepr(self):
        if not self.categoryDescriptions.has_key(self.category):
            return self.category
        briefDescription, longDescription = self.categoryDescriptions[self.category]
        return longDescription
    def hostString(self):
        if len(self.executionHosts) == 0:
            return "(no execution hosts given)"
        else:
            return "on " + string.join(self.executionHosts, ",")
    def hostRepr(self):
        if self.showExecHosts and len(self.executionHosts) > 0:
            return " " + self.hostString()
        else:
            return ""
    def colonRepr(self):
        if self.hasSucceeded():
            return ""
        else:
            return " :"
    def needsRecalculation(self):
        # Is some aspect of the state out of date
        return 0
    # Used by text interface to print states
    def description(self):
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
        return self.lifecycleChange == "complete"
    def isSaveable(self):
        return self.hasFailed() and self.hasResults()
    def warnOnSave(self):
        return False
    def updateAbsPath(self, newAbsPath):
        pass
    def updateTmpPath(self, newTmpPath):
        pass

addCategory("unrunnable", "unrunnable", "could not be run")

class Unrunnable(TestState):
    def __init__(self, freeText, briefText = "UNRUNNABLE", executionHosts=[]):
        TestState.__init__(self, "unrunnable", freeText, briefText, completed=1, \
                           executionHosts=executionHosts)
    def shouldAbandon(self):
        return True

# Simple handle to get diagnostics object. Better than using log4py directly,
# as it ensures everything appears by default in a standard place with a standard name.
def getDiagnostics(diagName):
    return log4py.Logger().get_instance(diagName)

def getPersonalConfigDir():
    fromEnv = os.getenv("TEXTTEST_PERSONAL_CONFIG")
    if fromEnv:
        return fromEnv
    else:
        return os.path.normpath(os.path.expanduser("~/.texttest"))

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
    
def nullRedirect():
    stdoutRedirect = " > " + os.devnull
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

selfHidden = os.getenv("TEXTTEST_VIRTUAL_DISPLAY") == "HIDE_WINDOWS"
def getProcessStartUpInfo(testProcess=False):
    # Used for hiding the windows if we're on Windows!
    if shouldHideWindows(testProcess):
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = subprocess.SW_HIDE
        return info

def shouldHideWindows(testProcess):
    if os.name != "nt":
        return False
    if not testProcess:
        return selfHidden
    # Only test windows should be hidden if we aren't hidden ourselves
    return os.getenv("TEXTTEST_VIRTUAL_DISPLAY") == "HIDE_WINDOWS"

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

def readList(filename):
    items = []
    for longline in open(filename).readlines():
        line = longline.strip()
        if len(line) > 0 and not line.startswith("#"):
            items.append(line)
    return items

emptyLineSymbol = "__EMPTYLINE__"
  
def readListWithComments(filename, duplicateMethod=None):
    items = seqdict()
    currComment = ""
    for longline in open(filename).readlines():
        line = longline.strip()
        if len(line) == 0:
            if currComment:
                currComment += emptyLineSymbol + "\n"
            continue
        if line.startswith("#"):
            currComment += longline[1:].lstrip()
        else:
            if items.has_key(line) and duplicateMethod:
                duplicateMethod(line, filename)
            else:
                items[line] = currComment.strip()
            currComment = ""
    # Rescue dangling comments in the end (but put them before last test ...)
    if currComment and len(items) > 0:
        lastPos = len(items) - 1
        items[items.keys()[lastPos]] = currComment + items[items.keys()[lastPos]]
    return items

# comment can contain lines with __EMPTYLINE__ (see above) as a separator
# from free comments, or commented out tests. This method extracts the comment
# after any __EMPTYLINE__s.
def extractComment(comment):
    lastEmptyLinePos = comment.rfind(emptyLineSymbol)
    if lastEmptyLinePos == -1:
        return comment
    else:
        return comment[lastEmptyLinePos + len(emptyLineSymbol) + 1:]

# comment can contain lines with __EMPTYLINE__ (see above) as a separator
# from free comments, or commented out tests. This method replaces the real
# comment for this test with newComment
def replaceComment(comment, newComment):
    lastEmptyLinePos = comment.rfind(emptyLineSymbol)
    if lastEmptyLinePos == -1:
        return newComment
    else:
        return comment[0:lastEmptyLinePos + len(emptyLineSymbol) + 1] + newComment

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
    def getCutLines(self, lines):
        if len(lines) < self.cutFromEnd + self.cutFromStart:
            return lines
        
        cutLines = lines[:self.cutFromStart]
        if self.cutFromEnd > 0:
            cutLines.append("... extra data truncated by TextTest ...\n")
            cutLines += lines[-self.cutFromEnd:]    
        return cutLines
    def getPreview(self, file):
        fileLines = retryOnInterrupt(self.getFileLines, file)
        return self._getPreview(fileLines)
    def getFileLines(self, file):
        lines = file.readlines()
        file.close()
        return lines
    def _getPreview(self, lines):
        cutLines = self.getCutLines(lines)
        lines = map(self.getWrappedLine, cutLines)
        return string.join(lines, "")
    def getPreviewFromText(self, text):
        truncatedLines = text.split("\n")[:-1] # drop the final endline, don't get a new line after it
        lines = [ line + "\n" for line in truncatedLines ]
        return self._getPreview(lines)
    def getWrappedLine(self, line):
        if len(line) <= self.maxWidth:
            return line
        truncatedLine = line[:self.maxWidth]
        return truncatedLine + "\n" + self.getWrappedLine(line[self.maxWidth:])
    
# Exception to throw. It's generally good to throw this internally
class TextTestError(RuntimeError):
    pass

class TextTestWarning(RuntimeError):
    pass

# Sort of a workaround to get e.g. CVSLogInGUI to show a message in a simple info dialog
class TextTestInformation(RuntimeError): 
    pass

# Yes, we know that getopt exists. However it throws exceptions when it finds unrecognised things, and we can't do that...
class OptionFinder(seqdict):
    def __init__(self, args, defaultKey = "default"):
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
        if len(item) > 1 and item[1] == "-":
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
    
class Option:    
    def __init__(self, name, value, description, changeMethod):
        self.name = name
        self.defaultValue = value
        self.valueMethod = None
        self.updateMethod = None
        self.description = description
        self.changeMethod = changeMethod
    def getValue(self):
        if self.valueMethod:
            return self.valueMethod()
        else:
            return self.defaultValue
    def setValue(self, value):
        self.defaultValue = value
        if self.updateMethod:
            self.updateMethod(value)
    def setMethods(self, valueMethod, updateMethod):
        self.valueMethod = valueMethod
        self.updateMethod = updateMethod
    def reset(self):
        if self.updateMethod:
            self.updateMethod(self.defaultValue)
        else:
            self.valueMethod = None

class TextOption(Option):
    def __init__(self, name, value, possibleValues, allocateNofValues, selectDir, selectFile, description, changeMethod):
        Option.__init__(self, name, value, description, changeMethod)
        self.possValMethod = None
        self.nofValues = allocateNofValues
        self.selectDir = selectDir
        self.selectFile = selectFile
        self.clearMethod = None
        self.setPossibleValues(possibleValues)
    def setPossibleValuesAppendMethod(self, method):
        if method:
            self.possValMethod = method
            for value in self.possibleValues:
                method(value)
    def addPossibleValue(self, value):
        if value not in self.possibleValues:
            self.possibleValues.append(value)
            if self.possValMethod:
                self.possValMethod(value)
            return True
        else:
            return False
    def setPossibleValues(self, values):
        if self.defaultValue in values:
            self.possibleValues = values
        else:
            self.possibleValues = [ self.defaultValue ] + values
    def inqNofValues(self): 
        if self.nofValues > 0:
            return self.nofValues
        else:
            return len(self.possibleValues)
    def setClearMethod(self, clearMethod):
        self.clearMethod = clearMethod
    def clear(self):
        if self.clearMethod:
            self.clearMethod()

class Switch(Option):
    def __init__(self, name, defaultValue, options, description, changeMethod):
        Option.__init__(self, name, int(defaultValue), description, changeMethod)
        self.options = options
        self.resetMethod = None
    def setValue(self, value):
        Option.setValue(self, int(value))
    def reset(self):
        if self.defaultValue == 0 and self.resetMethod:
            self.resetMethod(1)
        else:
            Option.reset(self)
    def describe(self):
        text = self.name
        if len(self.options) > 0:
            text += self.options[-1]
        return text

class OptionGroup:
    def __init__(self, name):
        self.name = name
        self.options = seqdict()
        self.switches = seqdict()
    def __repr__(self):
        return "OptionGroup " + self.name + "\n" + repr(self.options) + "\n" + repr(self.switches)
    def empty(self):
        return len(self.options) == 0 and len(self.switches) == 0
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
    def addSwitch(self, key, name, value = 0, options = [], description = "", changeMethod = None):
        if self.switches.has_key(key):
            return False
        self.switches[key] = Switch(name, value, options, description, changeMethod)
        return True
    def addOption(self, key, name, value = "", possibleValues = [], allocateNofValues = -1, selectDir = False, selectFile = False, description = "", changeMethod = None):
        if self.options.has_key(key):
            return False
        self.options[key] = TextOption(name, value, possibleValues, allocateNofValues, selectDir, selectFile, description, changeMethod)
        return True
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
    def getOption(self, key):
        return self.options[key]
    def getSwitch(self, key):
        return self.switches[key]
    def setSwitchValue(self, key, value):
        if self.switches.has_key(key):
            self.switches[key].setValue(value)
    def setPossibleValues(self, key, possibleValues):
        option = self.options.get(key)
        if option:
            option.setPossibleValues(possibleValues)
    def addPossibleValue(self, key, possibleValue):
        option = self.options.get(key)
        if option:
            return option.addPossibleValue(possibleValue)
        else:
            return False
    def setPossibleValuesUpdate(self, key, possibleValues):
        option = self.options.get(key)
        if option:
            option.setPossibleValues(possibleValues)
            option.clear()
            option.setPossibleValuesAppendMethod(option.possValMethod)
    def getOption(self, key):
        return self.options.get(key)
    def getSwitch(self, key):
        return self.switches.get(key)
    def removeOption(self, key):
        if self.options.has_key(key):
            del self.options[key]
    def removeSwitch(self, key):
        if self.switches.has_key(key):
            del self.switches[key]
    def setOptionValue(self, key, value):
        if self.options.has_key(key):
            return self.options[key].setValue(value)
    def getCommandLines(self):
        commandLines = []
        for key, option in self.options.items():
            if len(option.getValue()):
                commandLines.append("-" + key)
                commandLines.append(option.getValue())
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
 
def decodeText(text, log = None):
    localeEncoding = locale.getdefaultlocale()[1]
    if localeEncoding:
        try:
            return unicode(text, localeEncoding, errors="strict")
        except:
            if log:
                log.info("WARNING: Failed to decode string '" + text + \
                         "' using default locale encoding " + repr(localeEncoding) + \
                         ". Trying strict UTF-8 encoding ...")
                
    return decodeUtf8Text(text, localeEncoding, log)

def decodeUtf8Text(text, localeEncoding, log = None):
    try:
        return unicode(text, 'utf-8', errors="strict")
    except:
        if log:
            log.info("WARNING: Failed to decode string '" + text + \
                     "' both using strict UTF-8 and " + repr(localeEncoding) + \
                     " encodings.\nReverting to non-strict UTF-8 encoding but " + \
                     "replacing problematic\ncharacters with the Unicode replacement character, U+FFFD.")
        return unicode(text, 'utf-8', errors="replace")

def encodeToUTF(unicodeInfo, log = None):
    try:
        return unicodeInfo.encode('utf-8', 'strict')
    except:
        try:
            if log:
                log.info("WARNING: Failed to encode Unicode string '" + unicodeInfo + \
                         "' using strict UTF-8 encoding.\nReverting to non-strict UTF-8 " + \
                         "encoding but replacing problematic\ncharacters with the Unicode replacement character, U+FFFD.")
            return unicodeInfo.encode('utf-8', 'replace')
        except:
            if log:
                log.info("WARNING: Failed to encode Unicode string '" + unicodeInfo + \
                         "' using both strict UTF-8 encoding and UTF-8 encoding with " + \
                         "replacement. Showing error message instead.")
            return "Failed to encode Unicode string."
        
def encodeToLocale(unicodeInfo, log = None):
    localeEncoding = locale.getdefaultlocale()[1]
    if localeEncoding:
        try:
            return unicodeInfo.encode(localeEncoding, 'strict')
        except:
            if log:
                log.info("WARNING: Failed to encode Unicode string '" + unicodeInfo + \
                         "' using strict '" + localeEncoding + "' encoding.\nReverting to non-strict UTF-8 " + \
                         "encoding but replacing problematic\ncharacters with the Unicode replacement character, U+FFFD.")
    return unicodeInfo.encode('utf-8', 'replace')
