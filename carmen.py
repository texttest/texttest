#!/usr/local/bin/python

helpDescription = """
The Carmen configuration is based on the LSF configuration. Its default operation is therefore to
submit all jobs to LSF, rather than run them locally.

It determines the queue as follows: if a test takes less than 10 minutes, it will be submitted
to short_<arch>, where <arch> is the architecture where TextTest was called from. If it takes
more than 2 hours, it will go to idle_<arch>. If neither of these, or if the specified queue
does not exist, it will be submitted to the queue <arch>.

The Carmen configuration is also somewhat architecture-conscious in other ways. It reads the required config file
entry "default_architecture", to determine where the basic results are created. It also reads
"supported_architecture" to determine if the currently run architecture is OK. If the supported_architecture
list is present and the current one does not match, the configuration will exit with an error.

Running on an architecture other than default_architecture will cause the test suite to automatically
use the version <arch>, as well as any versions it was originally running.
"""

helpOptions = """
-u <texts> - select only user suites whose name contains one of the strings in <texts>. <texts> is interpreted as a
             comma-separated list. A user suite is defined as a test suite which defines CARMUSR locally.

-lprof     - Run LProf on the test concerned. This will automatically profile the job and generate the textual
             data in the test directory, in a file called lprof.<app>. It is proposed to automatically generate
             the graphical information also

-rulecomp  - Instead of running normally, compile all rule sets that are relevant to the tests selected (if any)

-build <t> - Prior to running any tests, build in the appropriate location specified by <t>. This is specified in
             the config file as the entries "build_xxx". So if my config file contains the lines
             build_codebase:Rules_and_Reports
             build_codebase:Optimization
             then specifying -build codebase will cause a build (= gmake) to be run in these places (relative to checkout
             of course), before anything else is done.

             It is expected that this option is used on linux. Note that in addition, a build is kicked off in parallel
             on sparc (sundance) and parisc_2_0 (ramechap), which run in the background while your tests run,
             and are reported on at the end. This should ensure that they don't delay the appearance of test information.
"""

batchInfo = """
             Note that, because the Carmen configuration converts non-default architectures to versions, you can also
             enable and disable architectures using <bname>_version.

             The Carmen nightjob will run TextTest on all versions and on all architectures. It will do so with the batch
             session name "nightjob" on Monday to Thursday nights, and "wkendjob" on Friday night.
             If you do not want this, you should therefore restrict or disable these session names in your config file, as
             indicated above.

             Note also that the "nightjob" sessions are killed at 8am each morning, while the "wkendjob" sessions are killed
             at 8am on Monday morning. This can cause some tests to be reported as "unfinished" in your batch report."""

import lsf, default, performance, os, string, shutil, stat, plugins, batch, sys, signal, respond, time, predict

def getConfig(optionMap):
    return CarmenConfig(optionMap)

def isUserSuite(suite):
    return suite.environment.has_key("CARMUSR")

def isCompressed(path):
    magic = open(path).read(2)
    if magic[0] == chr(0x1f) and magic[1] == chr(0x9d):
        return 1
    else:
        return 0

class UserFilter(default.TextFilter):
    def acceptsTestSuite(self, suite):
        if isUserSuite(suite):
            return self.containsText(suite)
        else:
            return 1

architecture = os.popen("arch").readline()[:-1]

class CarmenConfig(lsf.LSFConfig):
    def getOptionString(self):
        return "u:" + lsf.LSFConfig.getOptionString(self)
    def getFilterList(self):
        filters = lsf.LSFConfig.getFilterList(self)
        self.addFilter(filters, "u", UserFilter)
        return filters
    def getActionSequence(self):
        if self.optionMap.has_key("rulecomp"):
            return [ self.getRuleBuilder(0) ]
        else:
            builder = self.getAppBuilder()
            return [ builder, self.getRuleBuilder(1) ] + lsf.LSFConfig.getActionSequence(self) + [ self.getBuildChecker(builder) ]
    def getRuleBuilder(self, neededOnly):
        if neededOnly:
            return plugins.Action()
        else:
            return CompileRules(self.getRuleSetName)
    def getAppBuilder(self):
        if self.optionMap.has_key("build"):
            return BuildCode(self.optionValue("build"))
        else:
            return plugins.Action()
    def getBuildChecker(self, builder):
        if self.optionMap.has_key("build"):
            return CheckBuild(builder)
        else:
            return plugins.Action()
    def getTestRunner(self):
        if self.optionMap.has_key("lprof"):
            subActions = [ lsf.LSFConfig.getTestRunner(self), WaitForDispatch(), RunLProf() ]
            return plugins.CompositeAction(subActions)
        else:
            return lsf.LSFConfig.getTestRunner(self)
    def findLSFQueue(self, test):
        if self.queueDecided(test):
            return lsf.LSFConfig.findLSFQueue(self, test)

        return self.getQueuePerformancePrefix(test) + architecture + self.getQueuePlatformSuffix(test.app)
    def getQueuePerformancePrefix(self, test):
        if architecture == "powerpc" or architecture == "parisc_2_0":
            return ""
        cpuTime = performance.getTestPerformance(test)
        if cpuTime < 10:
            return "short_"
        elif cpuTime < 120:
            return ""
        else:
            return "idle_"
    def getQueuePlatformSuffix(self, app):
        version9 = "9" in app.versions
        if architecture == "i386_linux":
            if version9:
                return "_RH7"
            else:
                return "_RH8"
        elif architecture == "sparc":
            return "_sol8"
        elif architecture == "powerpc":
            if version9:
                return "_aix4"
            else:
                return "_aix5"
        return ""
    def isNightJob(self):
        batchSession = self.optionValue("b")
        return batchSession == "nightjob" or batchSession == "wkendjob"
    def getVersions(self, app):
        defaultArch = app.getConfigValue("default_architecture")
        if architecture == defaultArch:
            return []
        else:
            supportedArchs = app.getConfigList("supported_architecture")
            # In batch mode, don't throw exceptions. Let the Batch Filter deal with it
            if len(supportedArchs) and not architecture in supportedArchs and not self.optionMap.has_key("b"):
                raise plugins.TextTestError, "Unsupported architecture " + architecture + "!!!"
            else:
                print "Non-default architecture: using version", architecture
                return [ architecture ] 
    def printHelpOptions(self, builtInOptions):
        print lsf.helpOptions + batchInfo
        default.Config.printHelpOptions(self, builtInOptions)
        print "(Carmen-specific options...)"
        print helpOptions
    def printHelpDescription(self):
        print helpDescription, lsf.lsfGeneral, predict.helpDescription, performance.helpDescription, respond.helpDescription 
    
def getRaveName(test):
    return test.app.getConfigValue("rave_name")

class CompileRules(plugins.Action):
    def __init__(self, getRuleSetName, modeString = "-optimize", filter = None):
        self.rulesCompiled = []
        self.rulesCompileFailed = []
        self.raveName = None
        self.getRuleSetName = getRuleSetName
        self.modeString = modeString
        self.filter = filter
    def __repr__(self):
        return "Compiling rules for"
    def __call__(self, test):
        ruleset = RuleSet(self.getRuleSetName(test), self.raveName)
        if ruleset.isValid() and ruleset.name in self.rulesCompileFailed:
            raise plugins.TextTestError, "Trying to use ruleset '" + ruleset.name + "' that failed to build."
        if ruleset.isValid() and not ruleset.name in self.rulesCompiled:
            self.describe(test, " - ruleset " + ruleset.name)
            if not os.path.isdir(os.environ["CARMTMP"]):
                print "CARMTMP", os.environ["CARMTMP"], "did not exist, attempting to create it"
                os.mkdir(os.environ["CARMTMP"])
            ruleset.backup()
            compiler = os.path.join(os.environ["CARMSYS"], "bin", "crc_compile")
            commandLine = compiler + " " + self.raveName + " " + self.modeString + " -archs " + architecture + " " + ruleset.sourceFile
            self.rulesCompiled.append(ruleset.name)
            errorMessage = self.performCompile(test, commandLine)
            if errorMessage:
                self.rulesCompileFailed.append(ruleset.name)
                print "Failed to build ruleset " + ruleset.name + os.linesep + errorMessage
                raise plugins.TextTestError, "Failed to build ruleset " + ruleset.name + os.linesep + errorMessage
            if self.modeString == "-debug":
                ruleset.moveDebugVersion()
    def performCompile(self, test, commandLine):
        compTmp = test.getTmpFileName("ravecompile", "w")
        returnValue = os.system(commandLine + " > " + compTmp + " 2>&1")
        if returnValue:
            errContents = string.join(open(compTmp).readlines(),"")
            if errContents.find("already being compiled by") != -1:
                print test.getIndent() + "Waiting for other compilation to finish..."
                time.sleep(30)
                return self.performCompile(test, commandLine)
            os.remove(compTmp)
            return errContents
        os.remove(compTmp)
        return ""
    def setUpSuite(self, suite):
        self.describe(suite)
        self.rulesCompiled = []
        if self.raveName == None:
            self.raveName = getRaveName(suite)
    def getFilter(self):
        return self.filter
    
class RuleSet:
    def __init__(self, ruleSetName, raveName):
        self.name = ruleSetName
        if self.name != None:
            self.targetFile = os.path.join(os.environ["CARMTMP"], "crc", "rule_set", string.upper(raveName), architecture, self.name)
            self.sourceFile = os.path.join(os.environ["CARMUSR"], "crc", "source", self.name)
    def isValid(self):
        return self.name != None and os.path.isfile(self.sourceFile)
    def isCompiled(self):
        return os.path.isfile(self.targetFile)
    def backup(self):
        if self.isCompiled():
            try:
                shutil.copyfile(self.targetFile, self.targetFile + ".bak")
            except IOError:
                print "WARNING - did not have permissions to backup ruleset, continuing anyway"
    def moveDebugVersion(self):
        debugVersion = self.targetFile + "_g"
        if os.path.isfile(debugVersion):
            os.remove(self.targetFile)
            os.rename(debugVersion, self.targetFile)
        
class UpdatedLocalRulesetFilter(plugins.Filter):
    def __init__(self, getRuleSetName, libraryFile):
        self.getRuleSetName = getRuleSetName
        self.libraryFile = libraryFile
    def acceptsTestCase(self, test):
        ruleset = RuleSet(self.getRuleSetName(test), getRaveName(test))
        if not ruleset.isValid():
            return 0
        if not ruleset.isCompiled():
            return 1
        return self.modifiedTime(ruleset.targetFile) < self.modifiedTime(os.path.join(os.environ["CARMSYS"], self.libraryFile))
    def acceptsTestSuite(self, suite):
        if not isUserSuite(suite):
            return 1

        carmtmp = suite.environment["CARMTMP"]
        return carmtmp.find(os.environ["CARMSYS"]) != -1
    def modifiedTime(self, filename):
        return os.stat(filename)[stat.ST_MTIME]

class WaitForDispatch(lsf.Wait):
    def __init__(self):
        self.eventName = "dispatch"
    def checkCondition(self, job):
        return len(job.getProcessIds()) >= 4

class RunLProf(plugins.Action):
    def __init__(self,whichProcessId=-1):
        self.whichProcessId = whichProcessId;
    def __repr__(self):
        return "Running LProf profiler on"
    def __call__(self, test):
        job = lsf.LSFJob(test)
        executionMachine = job.getExecutionMachine()
        self.describe(test, ", executing on " + executionMachine)
        processId = job.getProcessIds()[self.whichProcessId]
        runLine = "cd " + os.getcwd() + "; /users/lennart/bin/gprofile " + processId
        outputFile = "prof." + processId
        processLine = "/users/lennart/bin/process_gprof " + outputFile + " > lprof." + test.app.name + test.app.versionSuffix()
        removeLine = "rm " + outputFile
        commandLine = "rsh " + executionMachine + " '" + runLine + "; " + processLine + "; " + removeLine + "'"
        os.system(commandLine)

class BuildCode(plugins.Action):
    def __init__(self, target):
        self.target = target
        self.childProcesses = []
    def setUpApplication(self, app):
        for relPath in app.getConfigList("build_" + self.target):
            absPath = app.makeAbsPath(relPath)
            if os.path.isdir(absPath):
                self.buildLocal(absPath, app)
            else:
                print "Not building in", absPath, "which doesn't exist!"
        self.buildRemote("sundance", "sparc", app) 
        self.buildRemote("ramechap", "parisc_2_0", app)
        self.buildRemote("naxos", "powerpc", app)
    def buildLocal(self, absPath, app):
        os.chdir(absPath)
        print "Building", app, "in", absPath, "..."
        buildFile = "build.default"
        commandLine = "cd " + absPath + "; gmake >& " + buildFile
        os.system("rsh wake '" + commandLine + "' < /dev/null")
        if self.checkBuildFile(buildFile):
            raise "Product " + repr(app) + " did not build, exiting"
        print "Product", app, "built correctly in", absPath
        os.remove(buildFile)
        commandLine = "cd " + absPath + "; gmake install CARMSYS=" + os.environ["CARMSYS"] + " >& /dev/null"
        os.system("rsh wake '" + commandLine + "' < /dev/null")
        print "Making install from", absPath ,"to", os.environ["CARMSYS"]
    def buildRemote(self, machine, arch, app):
        print "Building remotely in parallel on " + machine + " ..."
        processId = os.fork()
        if processId == 0:
            result = self.buildRemoteInChild(machine, arch, app)
            sys.exit(result)
        else:
            tuple = processId, arch
            self.childProcesses.append(tuple)
    def buildRemoteInChild(self, machine, arch, app):
        sys.stdin = open("/dev/null")
        signal.signal(1, self.killBuild)
        signal.signal(2, self.killBuild)
        signal.signal(15, self.killBuild) 
        for relPath in app.getConfigList("build_codebase"):
            absPath = app.makeAbsPath(relPath)
            if os.path.isdir(absPath):    
                commandLine = "cd " + absPath + "; gmake >& build." + arch
                os.system("rsh " + machine + " '" + commandLine + "' < /dev/null")
        return 0            
    def checkBuildFile(self, buildFile):
        for line in open(buildFile).xreadlines():
            if line.find("***") != -1 and line.find("Error") != -1:
                return 1
        return 0
    def killBuild(self):
        print "Terminating remote build."

class CheckBuild(plugins.Action):
    def __init__(self, builder):
        self.builder = builder
    def setUpApplication(self, app):
        print "Waiting for remote builds..." 
        for process, arch in self.builder.childProcesses:
            pid, status = os.waitpid(process, 0)
            # In theory we should be able to trust the status. In practice, it seems to be 0, even when the build failed.
            for relPath in app.getConfigList("build_codebase"):
                absPath = app.makeAbsPath(relPath)
                self.checkBuild(arch, absPath)
    def checkBuild(self, arch, absPath):
        if os.path.isdir(absPath):
            os.chdir(absPath)
            fileName = "build." + arch
            result = self.builder.checkBuildFile(fileName)
            resultString = " SUCCEEDED!"
            if result:
                resultString = " FAILED!"
            print "Build on " + arch + " in " + absPath + resultString
            if result == 0:
                os.remove(fileName)

#
# This class reads a CarmResources etab file and gives access to it
#
class ConfigEtable:
    def __init__(self, fileName):
        self.inFile = open(fileName)
        self.applications = {}
        self.columns = self._readColumns()
        self.parser = ConfigEtableParser(self.inFile)
        self.diag = plugins.getDiagnostics("ConfigEtable")
        lineTuple = self._readTuple()
        while lineTuple != None:
            self._storeValue(lineTuple[0], lineTuple[1], lineTuple[2], lineTuple[4])
            lineTuple = self._readTuple()
    def getValue(self, application, module, name):
        try:
            appDict = self.applications[application]
            moduleDict = appDict[module]
            value = moduleDict[name]
        except:
            return None
        return self._etabExpand(value)
    def _storeValue(self, app, module, name, value):
        if not self.applications.has_key(app):
            self.applications[app] = {}
        if not self.applications[app].has_key(module):
            self.applications[app][module] = {}
        self.applications[app][module][name] = value
    def _readTuple(self):
        tup = []
        while len(tup) < len(self.columns):
            tok = self._readConfigToken()
            if tok == None:
                break
            if tok != ",":
                tup.append(tok)
        if len(tup) == len(self.columns):
            return tup
        else:
            return None
    def _readColumns(self):
        numCols = self._readNumCols()
        cols = []
        while len(cols) < numCols:
            line = self.inFile.readline()
            parts = line.split()
            if len(parts) > 0 and len(parts[0].strip()) > 0:
                cols.append(parts[0])
        return cols
    def _readNumCols(self):
        numCols = -1
        inComment = 0
        while numCols == -1:
            line = self.inFile.readline()
            if line.startswith("/*"):
                inComment = 1
            if line.strip().endswith("*/"):
                inComment = 0
            if not inComment:
                try:
                    numCols = int(line.strip())
                except:
                    pass
        return numCols
    def _readConfigToken(self):
        tok = self.parser.get_token()
        while tok != None and tok.startswith("/*"):
            while not tok.endswith("*/"):
                tok = self.parser.get_token()
            tok = self.parser.get_token()
        return tok
    def _etabExpand(self, value):
        self.diag.info("Expanding etable value " + value)
        if not value.startswith("$("):
            return value
        lPos = value.find(")")
        if lPos == -1:
            return value
      
        parts = value[2:lPos].split(".")
        self.diag.debug("parts = " + repr(parts))
        if len(parts) == 3:
            expanded = self.getValue(parts[0], parts[1], parts[2])
            self.diag.debug("expanded = " + repr(expanded))
            whole = expanded + self._etabExpand(value[lPos + 1:])
            return self._etabExpand(whole)
        else:
            whole = "${" + value[2:lPos] + "}" + self._etabExpand(value[lPos + 1:])
            return os.path.expandvars(whole)

class ConfigEtableParser:
    def __init__(self, infile):
        self.file = infile
        self.quotes = [ '"', "'" ]
        self.specials = {}
        self.specials["n"] = "\n"
        self.specials["r"] = "\r"
        self.specials["t"] = "\t"
        self.lastChar = None
    def _readChar(self):
        ch = self.__readChar()
        return ch
    def __readChar(self):
        if self.lastChar != None:
            ch = self.lastChar
            self.lastChar = None
            return ch
        return self.file.read(1)
    def _pushBack(self, ch):
        self.lastChar = ch
    def _peekCheck(self, ch, firstChar, nextChar):
        if ch == firstChar:
            ch2 = self._readChar()
            if ch2 == nextChar:
                return 1
            self._pushBack(ch2)
        return 0
    def _readElement(self):
        ch = self._readChar()
        if self._peekCheck(ch, "/", "*"):
            return "/*"
        if self._peekCheck(ch, "*", "/"):
            return "*/"
        if len(os.linesep) > 1:
            if self._peekCheck(ch, os.linesep[0], os.linesep[1]):
                return os.linesep
        if ch == "\\":
            ch = self._readChar()
        return ch
    def _readQuote(self, quote):
        text = ""
        ch = self._readChar()
        while len(ch) > 0 and ch != quote:
            if ch == "\\":
                ch = self._readChar()
                if self.specials.has_key(ch):
                    ch = self.specials[ch]
            text += ch
            ch = self._readChar()
        return text

    def get_token(self):
        tok = ""
        ch = self._readElement()
        while len(ch) > 0:
            if ch in self.quotes:
                return tok + self._readQuote(ch)
            if ch == "/*":
                while ch != "" and ch != "*/":
                    ch = self._readElement()
                continue
            if ch == ",":
                if len(tok) > 0:
                    self._pushBack(ch)
                    return tok
                else:
                    return ch
            if not ch in [ ' ', os.linesep, '\t' ]:
                tok += ch
            else:
                if tok != "":
                    return tok
            ch = self._readElement()
        if tok == "":
            return None
        return tok

def ensureDirectoryExists(path):
    if len(path) == 0:
        return
    if os.path.isdir(path):
        return
    h, t = os.path.split(path)
    ensureDirectoryExists(h)
    if len(t) > 0:
        os.mkdir(path)

    
    
