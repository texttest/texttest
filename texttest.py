#!/usr/bin/env python
import os, sys, types, string, getopt, types, time, re, plugins, exceptions, stat, log4py
from stat import *

helpIntro = """
Note: the purpose of this help is primarily to document the configuration you currently have,
though also to provide a full list of options supported by both your framework and your configuration.
A user guide (UserGuide.html) is available to document the framework itself.
"""

builtInOptions = """
-a <app>   - run only the application with extension <app>

-v <vers>  - use <vers> as the version name(s). Versions separated by "." characters will be aggregated.
             Versions separated by "," characters will be run one after another. See the User Guide for
             a fuller explanation of what a "version" means.

-c <chkt>  - use <chkt> as the checkout instead of the "default_checkout" entry (see User Guide)

-d <root>  - use <root> as the root directory instead of the value of TEXTTEST_HOME,
             or the current working directory, which are used otherwise.

-s <scrpt> - instead of the normal actions performed by the configuration, use the script <scpt>. If this contains
             a ".", an attempt will be made to understand it as the Python class <module>.<classname>. If this fails,
             it will be interpreted as an external script.

-m <times> - perform the actions usually performed by the configuration, but repeated <times> times.

-p         - run in parallel mode. Do not clean up any temporary files looking like they belong to other TextTest
             runs.

-help      - Do not run anything. Instead, generate useful text, such as this.

-x         - Enable log4py diagnostics for the framework. This will use a diagnostic directory from the environment
             variable TEXTTEST_DIAGNOSTICS, if defined, or the directory <root>/Diagnostics/ if not. It will read
             the log4py configuration file present in that directory and write all diagnostic files there as well.
             More details can be had from the log4py documentation.
"""

# Base class for TestCase and TestSuite
class Test:
    def __init__(self, name, abspath, app):
        self.name = name
        self.app = app
        self.abspath = abspath
        self.paddedName = self.name
        self.previousEnv = {}
        self.environment = MultiEntryDictionary(os.path.join(self.abspath, "environment"), app.name, app.getVersionFileExtensions())
        # Single pass to expand all variables (don't want multiple expansion)
        for var, value in self.environment.items():
            expValue = os.path.expandvars(value)
            if value.find(os.sep) != -1:
                self.environment[var] = self.app.makeAbsPath(expValue)
                debugLog.info("Expanded " + var + " path " + value + " to " + self.environment[var])
            else:
                self.environment[var] = expValue
                debugLog.info("Expanded variable " + var + " to " + expValue + " in " + self.name)
            if os.environ.has_key(var):
                self.previousEnv[var] = os.environ[var]
            os.environ[var] = self.environment[var]
    def isValid(self):
        return os.path.isdir(self.abspath) and self.isValidSpecific()
    def makeFileName(self, stem, refVersion = None):
        nonVersionName = os.path.join(self.abspath, stem + "." + self.app.name)
        versions = self.app.getVersionFileExtensions()
        debugLog.info("Versions available : " + repr(versions))
        if refVersion != None:
            versions = [ refVersion ]
        if len(versions) == 0:
            return nonVersionName
        
        # Prioritise finding earlier versions
        for version in versions:
            versionName = nonVersionName + "." + version
            if os.path.isfile(versionName):
                return versionName
        return nonVersionName
    def getRelPath(self):
        return string.replace(self.abspath, self.app.abspath, "")
    def performAction(self, action):
        self.setUpEnvironment()
        self.callAction(action)
        self.performOnSubTests(action)
        self.tearDownEnvironment()
    def setUpEnvironment(self):
        for var, value in self.environment.items():
            if os.environ.has_key(var):
                self.previousEnv[var] = os.environ[var]
            os.environ[var] = value
            debugLog.info("Setting " + var + " to " + os.environ[var])
    def tearDownEnvironment(self):
        # Note this has no effect on the real environment, but can be useful for internal environment
        # variables. It would be really nice if Python had a proper "unsetenv" function...
        debugLog.info("Restoring environment for " + self.name + " to " + repr(self.previousEnv))
        for var in self.environment.keys():
            if os.environ.has_key(var):
                if self.previousEnv.has_key(var):
                    os.environ[var] = self.previousEnv[var]
                else:
                    debugLog.info("Removed variable " + var)
                    del os.environ[var]
    def getIndent(self):
        dirCount = string.count(self.getRelPath(), os.sep)
        retstring = ""
        for i in range(dirCount):
            retstring = retstring + "  "
        return retstring
    def isAcceptedByAll(self, filters):
        for filter in filters:
            debugLog.debug(repr(self) + " filter " + repr(filter))
            if not self.isAcceptedBy(filter):
                debugLog.debug("REJECTED")
                return 0
        return 1
    def size(self):
        return 1
        
class TestCase(Test):
    def __init__(self, name, abspath, app):
        Test.__init__(self, name, abspath, app)
        self.isDead = 0
        self.deathReason = None
        self.inputFile = self.makeFileName("input")
        optionsFile = self.makeFileName("options")
        self.options = ""
        if (os.path.isfile(optionsFile)):
            self.options = os.path.expandvars(open(optionsFile).readline().strip())
    def __repr__(self):
        return repr(self.app) + " " + self.classId() + " " + self.paddedName
    def classId(self):
        return "test-case"
    def isValidSpecific(self):
        return os.path.isfile(self.inputFile) or len(self.options) > 0
    def callAction(self, action):
        os.chdir(self.abspath)
        try:
            if self.isDead:
                action.processUnRunnable(self)
            else:
                action(self)
        except plugins.TextTestError, e:
            self.isDead = 1
            self.deathReason = e
    def performOnSubTests(self, action):
        pass
    def getExecuteCommand(self):
        return self.app.getExecuteCommand(self)
    def getTmpExtension(self):
        return globalRunIdentifier
    def getTestUser(self):
        return tmpString()
    def getTmpFileName(self, text, mode):
        prefix = text + "." + self.app.name + self.app.versionSuffix()
        fileName = prefix + globalRunIdentifier
        # When writing files, clean up equivalent files from previous runs, unless
        # we are in parallel mode and the files are less than 2 days old
        if mode == "w":
            for file in os.listdir(self.abspath):
                if file.find(prefix + self.getTestUser()) != -1:
                    if not self.app.parallelMode or self.isOutdated(file):
                        debugLog.info("Cleaning previous file " + file)
                        os.remove(file)
        return fileName
    def isOutdated(self, filename):
        modTime = os.stat(filename)[stat.ST_MTIME]
        currTime = time.time()
        threeDaysInSeconds = 60 * 60 * 24 * 3
        return currTime - modTime > threeDaysInSeconds
    def isAcceptedBy(self, filter):
        return filter.acceptsTestCase(self)
    def getInputFileName(self):
        tmpFile = self.getTmpFileName("input", "r")
        if os.path.isfile(tmpFile):
            return tmpFile
        return self.inputFile
        
class TestSuite(Test):
    def __init__(self, name, abspath, app, filters):
        Test.__init__(self, name, abspath, app)
        self.rejected = 0
        self.testCaseFile = self.makeFileName("testsuite")
        debugLog.info("Reading test suite file " + self.testCaseFile)
        self.testcases = self.getTestCases(filters)
        if len(self.testcases):
            maxNameLength = max([len(test.name) for test in self.testcases])
            for test in self.testcases:
                test.paddedName = string.ljust(test.name, maxNameLength)
        self.tearDownEnvironment()
    def __repr__(self):
        return repr(self.app) + " " + self.classId() + " " + self.name
    def classId(self):
        return "test-suite"
    def isValidSpecific(self):
        return os.path.isfile(self.testCaseFile)
    def isEmpty(self):
        return len(self.testcases) == 0
    def callAction(self, action):
        action.setUpSuite(self)
    def performOnSubTests(self, action):
        for testcase in self.testcases:
            testcase.performAction(action)
    def isAcceptedBy(self, filter):
        return filter.acceptsTestSuite(self)
    def reFilter(self, filters):
        testCaseList = []
        debugLog.debug("Refilter for " + self.name)
        for test in self.testcases:
            debugLog.debug("Refilter check of " + test.name + " for " + self.name)
            if test.classId() == self.classId():
                test.reFilter(filters)
                testCaseList.append(test)
            elif test.isAcceptedByAll(filters):
                debugLog.debug("Refilter ok of " + test.name + " for " + self.name)
                testCaseList.append(test)
            else:
                debugLog.debug("Refilter loose " + test.name + " for " + self.name)
        self.testcases = testCaseList
    def size(self):
        size = 0
        for testcase in self.testcases:
            size += testcase.size()
        return size
# private:
    def getTestCases(self, filters):
        testCaseList = []
        if not self.isValid() or not self.isAcceptedByAll(filters):
            self.rejected = 1
            return testCaseList

        for testline in open(self.testCaseFile).xreadlines():
            testName = testline.strip()
            if len(testName) == 0  or testName[0] == '#':
                continue
            testPath = os.path.join(self.abspath, testName)
            testSuite = TestSuite(testName, testPath, self.app, filters)
            if testSuite.isValid():
                if not testSuite.rejected:
                    testCaseList.append(testSuite)
            else:
                testCase = TestCase(testName, testPath, self.app)
                testCase.tearDownEnvironment()
                if testCase.isValid() and testCase.isAcceptedByAll(filters):
                    testCaseList.append(testCase)
        return testCaseList
            
class Application:
    def __init__(self, name, abspath, configFile, version, optionMap, builtInOptions):
        self.name = name
        self.abspath = abspath
        self.versions = version.split(".")
        if self.versions[0] == "":
            self.versions = []
        self.parallelMode = optionMap.has_key("p")
        self.configDir = MultiEntryDictionary(configFile, name, self.getVersionFileExtensions(0))
        self.fullName = self._getFullName()
        debugLog.info("Found application " + repr(self))
        self.checkout = self.makeCheckout(optionMap)
        debugLog.info("Checkout set to " + self.checkout)
        self.configObject = self.makeConfigObject(optionMap)
        allowedOptions = self.configObject.getOptionString() + builtInOptions
        # Force exit if something isn't present
        getopt.getopt(sys.argv[1:], allowedOptions)    
	self.specialChars = re.compile("[\^\$\[\]\{\}\\\*\?\|]")
        self.setConfigDefault("extra_version", "none")
        self.configObject.setUpApplication(self)
    def __repr__(self):
        return self.fullName
    def __cmp__(self, other):
        return cmp(self.name, other.name)
    def _getFullName(self):
        if self.configDir.has_key("full_name"):
            return self.configDir["full_name"]
        else:
            return string.upper(self.name)
    def versionSuffix(self):
        if len(self.versions) == 0:
            return ""
        if len(self.versions) == 1:
            return "." + self.versions[0]
        return "." + string.join(self.versions, ".")
    def description(self):
        description = "Application " + self.fullName
        if len(self.versions):
            description += ", version " + string.join(self.versions, ".")
        return description
    def getVersionFileExtensions(self, baseVersion = 1):
        if len(self.versions) == 0:
            return []
        if baseVersion:
            return self._getVersionExtensions(self.getConfigList("base_version") + self.versions)
        else:
            return self._getVersionExtensions(self.versions)
    def _getVersionExtensions(self, versions):
        if len(versions) == 1:
            return versions

        fullList = []
        current = versions[0]
        fromRemaining = self._getVersionExtensions(versions[1:])
        for item in fromRemaining:
            fullList.append(current + "." + item)
        fullList.append(current)
        fullList += fromRemaining
        return fullList
    def hasREpattern(self, txt):
    	# return 1 if txt contains a regular expression meta character
	return self.specialChars.search(txt) != None
    def makeAbsPath(self, path):
        if (os.path.isabs(path)):
            return path
        else:
            return os.path.join(self.checkout, path)
    def makeConfigObject(self, optionMap):
        configModule = self.getConfigValue("config_module")
        importCommand = "from " + configModule + " import getConfig"
        try:
            exec importCommand
        except:
            errorString = "No module named " + configModule
            if sys.exc_type == exceptions.ImportError and str(sys.exc_value) == errorString:
                raise KeyError, "could not find config_module " + configModule
            else:
                printException()
                raise KeyError, "config_module " + configModule + " contained errors and could not be imported"  
        return getConfig(optionMap)
    def getActionSequence(self):
        return self.configObject.getActionSequence()
    def printHelpText(self):
        print helpIntro
        header = "Description of the " + self.getConfigValue("config_module") + " configuration"
        length = len(header)
        header += os.linesep
        for x in range(length):
            header += "-"
        print header
        self.configObject.printHelpText(builtInOptions)
    def getFilterList(self):
        filters = self.configObject.getFilterList()
        success = 1
        for filter in filters:
            if not filter.acceptsApplication(self):
                success = 0
        return success, filters
    def getConfigValue(self, key):
        if self.configDir.has_key(key):
            value = self.configDir[key]
            if type(value) == types.StringType:
                return os.path.expandvars(self.configDir[key])
            else:
                return value
        else:
            raise KeyError, "Error: " + repr(self) + " cannot find config entry " + key
    def getConfigList(self, key):
        return self.configDir.getListValue(key)
    def setConfigDefault(self, key, value):
        if not self.configDir.has_key(key):
            self.configDir[key] = value
    def filterFile(self, fileName):
        stem = fileName.split('.')[0]
        if not self.configDir.has_key(stem) or not os.path.isfile(fileName):
            debugLog.info("No filter for " + fileName)
            return fileName

        if fileName.find(globalRunIdentifier) != -1:
            newFileName = fileName + "cmp"
        else:
            newFileName = stem + "." + self.name + self.versionSuffix() + ".original." + globalRunIdentifier + "cmp"
        
        oldFile = open(fileName)
        newFile = open(newFileName, "w")
        forbiddenText = self.getConfigList(stem)
        linesToRemove = 0 
        for line in oldFile.readlines():
            linesToRemove += self.calculateLinesToRemove(line, forbiddenText)
            if linesToRemove == 0:
                newFile.write(line)
            else:
                linesToRemove -= 1
        newFile.close()
        debugLog.info("Filter for " + fileName + " returned " + newFileName)
        return newFileName
#private:
    def matchRE(self, ptn, text):
	if re.compile(ptn).search(text):
	    return 1
	return 0
    def matchPlain(self, ptn, text):
    	if text.find(ptn) != -1:
	    return 1
	return 0
    def calculateLinesToRemove(self, line, forbiddenText):
        for text in forbiddenText:
            searchText = text
            linePoint = text.find("{LINES:")
            if linePoint != -1:
                searchText = text[:linePoint]
	    if self.hasREpattern(searchText):
            	found = self.matchRE(searchText, line[:-1])
	    else:
	    	found = self.matchPlain(searchText, line[:-1])
            if found:
                if linePoint != -1:
                    var, val = text[linePoint + 1:-1].split(":")
                    return int(val)
                else:
                    return 1
        return 0
    def makeCheckout(self, optionMap):
        if optionMap.has_key("c"):
            checkout = optionMap["c"]
        else:
            checkout = self.getConfigValue("default_checkout")
        checkoutLocation = os.path.expanduser(self.getConfigValue("checkout_location"))
        return os.path.join(checkoutLocation, checkout)
    def getExecuteCommand(self, test):
        binary = self._getBinary()
        return self.configObject.getExecuteCommand(binary, test)
    def _getBinary(self):
        binary = self.makeAbsPath(self.getConfigValue("binary"))
        if self.configDir.has_key("interpreter"):
            return self.configDir["interpreter"] + " " + binary
        else:
            return binary
            
class OptionFinder:
    def __init__(self):
        self.inputOptions = self.buildOptions()
        self._setUpLogging()
        debugLog.debug(repr(self.inputOptions))
    def _setUpLogging(self):
        global debugLog
        if self.inputOptions.has_key("x"):
            diagFile = self._getDiagnosticFile()
            if os.path.isfile(diagFile):
                diagDir = os.path.dirname(diagFile)
                os.environ["TEXTTEST_DIAGDIR"] = diagDir
                print "TextTest will write diagnostics in", diagDir
                for file in os.listdir(diagDir):
                    if file.endswith("diag"):
                        os.remove(os.path.join(diagDir, file))
                # To set new config files appears to require a constructor...
                rootLogger = log4py.Logger(log4py.TRUE, diagFile)
            else:
                print "Could not find diagnostic file at", diagFile, ": cannot run with diagnostics"
                self._disableDiags()
        else:
            self._disableDiags()
        # Module level debugging logger
        global debugLog
        debugLog = plugins.getDiagnostics("texttest")
    def _disableDiags(self):
        rootLogger = log4py.Logger().get_root()        
        rootLogger.set_loglevel(log4py.LOGLEVEL_NONE)
    # Yes, we know that getopt exists. However it throws exceptions when it finds unrecognised things, and we can't do that...
    def buildOptions(self):                                                                                                              
        inputOptions = {}                                                                                                 
        optionKey = None                                                                                                                 
        for item in sys.argv[1:]:                      
            if item[0] == "-":                         
                optionKey = item[1:].strip()
                inputOptions[optionKey] = ""
            elif optionKey:
                if len(inputOptions[optionKey]):
                    inputOptions[optionKey] += " "
                inputOptions[optionKey] += item.strip()
        return inputOptions
    def findApps(self):
        dirName = self.directoryName()
        os.chdir(dirName)
        debugLog.info("Using test suite at " + dirName)
        raisedError, appList = self._findApps(dirName, 1)
        appList.sort()
        debugLog.info("Found applications : " + repr(appList))
        if len(appList) == 0 and not raisedError:
            print "Could not find any matching applications (files of the form config.<app>) under", dirName
        return appList
    def _findApps(self, dirName, recursive):
        appList = []
        raisedError = 0
        selectedAppList = self.findSelectedAppNames()
        for f in os.listdir(dirName):
            pathname = os.path.join(dirName, f)
            if os.path.isfile(pathname):
                components = string.split(f, '.')
                if len(components) > 2 or components[0] != "config":
                    continue
                appName = components[1]
                if len(selectedAppList) and not appName in selectedAppList:
                    continue
                versionList = self.findVersionList()
                try:
                    for version in versionList:
                        appList += self.addApplications(appName, dirName, pathname, version)
                except (SystemExit, KeyboardInterrupt):
                    raise sys.exc_type, sys.exc_value
                except:
                    print "Could not use application", appName, "-", sys.exc_value
                    raisedError = 1
            elif os.path.isdir(pathname) and recursive:
                subRaisedError, subApps = self._findApps(pathname, 0)
                raisedError |= subRaisedError
                for app in subApps:
                    appList.append(app)
        return raisedError, appList
    def addApplications(self, appName, dirName, pathname, version):
        appList = []
        builtInOptions = "a:c:d:h:m:s:v:xp"
        app = Application(appName, dirName, pathname, version, self.inputOptions, builtInOptions)
        appList.append(app)
        extraVersion = app.getConfigValue("extra_version")
        if extraVersion == "none":
            return appList
        aggVersion = extraVersion
        if len(version) > 0:
            aggVersion = version + "." + extraVersion
        newApp = Application(appName, dirName, pathname, aggVersion, self.inputOptions, builtInOptions)
        appList.append(newApp)
        return appList
    def findVersionList(self):
        if self.inputOptions.has_key("v"):
            return plugins.commasplit(self.inputOptions["v"])
        else:
            return [""]
    def findSelectedAppNames(self):
        if self.inputOptions.has_key("a"):
            return plugins.commasplit(self.inputOptions["a"])
        else:
            return []
    def timesToRun(self):
        if self.inputOptions.has_key("m"):
            return int(self.inputOptions["m"])
        else:
            return 1
    def helpMode(self):
        return self.inputOptions.has_key("help")
    def _getDiagnosticFile(self):
        if os.environ.has_key("TEXTTEST_DIAGNOSTICS"):
            return os.path.join(os.environ["TEXTTEST_DIAGNOSTICS"], "log4py.conf")
        else:
            return os.path.join(self.directoryName(), "Diagnostics", "log4py.conf")
    def directoryName(self):
        if self.inputOptions.has_key("d"):
            return os.path.abspath(self.inputOptions["d"])
        elif os.environ.has_key("TEXTTEST_HOME"):
            return os.environ["TEXTTEST_HOME"]
        else:
            return os.getcwd()
    def getActionSequence(self, app):
        if not self.inputOptions.has_key("s"):
            return app.getActionSequence()
            
        actionCom = self.inputOptions["s"].split(" ")[0]
        actionArgs = self.inputOptions["s"].split(" ")[1:]
        actionOption = actionCom.split(".")
        if len(actionOption) != 2:
            return self.getNonPython()
                
        module, pclass = actionOption
        importCommand = "from " + module + " import " + pclass + " as _pclass"
        try:
            exec importCommand
        except:
            return self.getNonPython()

        # Assume if we succeed in importing then a python module is intended.
        if len(actionArgs) > 0:
            return [ _pclass(actionArgs) ]
        else:
            return [ _pclass() ]
    def getNonPython(self):
        return [ plugins.NonPythonAction(self.inputOptions["s"]) ]
            
class MultiEntryDictionary:
    def __init__(self, filename, appName = "", versions = []):
        self.dict = {}
        self.entries = []
        if os.path.isfile(filename):
            configFile = open(filename)
            for line in configFile.readlines():
                if line[0] == '#' or not ':' in line:
                    continue
                self.addLine(line[:-1])
        self.updateFor(filename, appName)
        for version in versions:
            self.updateFor(filename, version)
            self.updateFor(filename, appName + "." + version)
    def updateFor(self, filename, extra):
        if len(extra) == 0:
            return
        debugLog.debug("Updating " + filename + " for version " + extra) 
        extraFileName = filename + "." + extra
        if not os.path.isfile(extraFileName):
            return
        overrideDir = MultiEntryDictionary(extraFileName)
        for key, value in overrideDir.items():
            if not key in self.entries:
                self.entries.append(key)
                self.dict[key] = value
            elif type(self.dict[key]) == types.ListType:
                if type(value) == types.ListType:
                    self.dict[key] += value
                else:
                    self.dict[key].append(value)
            else:
                self.dict[key] = value
    def addLine(self, line, separator = ':'):
        entryName, entry = string.split(line, separator, 1)
        if self.dict.has_key(entryName):
            try:
                self.dict[entryName].append(entry)
            except:
                oldEntry = self.dict[entryName]
                entryList = []
                entryList.append(oldEntry)
                entryList.append(entry)
                self.dict[entryName] = entryList
        else:
            self.dict[entryName] = entry
            self.entries.append(entryName)
    def has_key(self, key):
        return self.dict.has_key(key)
    def keys(self):
        return self.dict.keys()
    def items(self):
        itemList = []
        for key in self.entries:
            if self.dict.has_key(key):
                t = key, self.dict[key]
                itemList.append(t)
        return itemList
    def __getitem__(self, key):
        return self.dict[key]
    def __setitem__(self, key, value):
        self.dict[key] = value
        if not key in self.entries:
            self.entries.append(key)
    def __repr__(self):
        return repr(self.dict)
    def getListValue(self, key):
        if self.dict.has_key(key):
            value = self.dict[key]
            if type(value) == types.ListType:
                return value
            else:
                list = []
                list.append(value)
                return list
        else:
            return []

class ApplicationRunner:
    def __init__(self, app, inputOptions):
        self.app = app
        self.actionSequence = inputOptions.getActionSequence(app)
        debugLog.debug("Action sequence = " + repr(self.actionSequence))
        self.valid, self.filterList = app.getFilterList()
        if inputOptions.helpMode():
            app.printHelpText()
            self.valid = 0
        else:
            tmpSuite = TestSuite(os.path.basename(app.abspath), app.abspath, app, self.filterList)
            tmpSuite.reFilter(self.filterList)
            if tmpSuite.size() == 0:
                print "No tests found for", app.description()
                self.valid = 0
            else:
                self.testSuite = tmpSuite
    def actionCount(self):
        return len(self.actionSequence)
    def performAction(self, actionNum):
        debugLog.debug("Performing action number " + str(actionNum) + " of " + str(self.actionCount()))
        if actionNum < self.actionCount():
            action = self.actionSequence[actionNum]
            if action.getFilter() != None:
                debugLog.debug("Performing action with filter " + repr(action.getFilter()))
                self._performActionWithFilter(action)
            else:
                self._performAction(self.testSuite, action)
    def performCleanUp(self):
        self.valid = 0 # Make sure no future runs are made
        for action in self.actionSequence:
            cleanUp = action.getCleanUpAction()
            if cleanUp != None:
                self._performAction(self.testSuite, cleanUp)        
    def _performActionWithFilter(self, action):
        newFilterList = self.filterList
        newFilterList.append(action.getFilter())
        debugLog.info("Creating extra test suite from new filter " + repr(action.getFilter()))
        debugLog.info(os.getcwd())
        actionTests = TestSuite(os.path.basename(self.app.abspath), self.app.abspath, self.app, newFilterList)
        self._performAction(actionTests, action)
    def _performAction(self, suite, action):
        debugLog.debug("Performing action " + repr(action))
        suite.setUpEnvironment()
        action.setUpApplication(suite.app)
        suite.tearDownEnvironment()
        debugLog.debug("Current config dictionary for " + repr(suite.app) + ": " + os.linesep + repr(suite.app.configDir.dict))
        suite.performAction(action)    

def printException():
    type, value, traceback = sys.exc_info()
    sys.excepthook(type, value, traceback)
    
# Need somewhat different formats on Windows/UNIX
def tmpString():
    if os.environ.has_key("USER"):
        return os.getenv("USER")
    else:
        return "tmp"

# --- MAIN ---

class TextTest:
    def __init__(self):
        self.inputOptions = OptionFinder()
        global globalRunIdentifier
        globalRunIdentifier = tmpString() + time.strftime(self.timeFormat(), time.localtime())
        self.allApps = self.inputOptions.findApps()
    def timeFormat(self):
        # Needs to work in files - Windows doesn't like : in file names
        if os.environ.has_key("USER"):
            return "%d%b%H:%M:%S"
        else:
            return "%H%M%S"
    def run(self):
        try:
            self._run()
        except SystemExit:# Assumed to be a child thread, in any case exit silently
            pass
        except KeyboardInterrupt:
            print "Terminated due to interruption"
    def _run(self):
        applicationRunners = self.createAppRunners()
        if len(applicationRunners) == 0:
            return
        maxActionCount = max(map(lambda x: x.actionCount(), applicationRunners))
        # Run actions one at a time for each application. This should ensure a fair spread of machine time when this is limited
        for run in range(self.inputOptions.timesToRun()):
            for actionNum in range(maxActionCount):
                self.performActionOnApps(applicationRunners, actionNum)
    def createAppRunners(self):
        applicationRunners = []
        for app in self.allApps:
            try:
                appRunner = ApplicationRunner(app, self.inputOptions)
                if appRunner.valid:
                    print "Using", app.description() + ", checkout", app.checkout
                    applicationRunners.append(appRunner)
            except (SystemExit, KeyboardInterrupt):
                printException()
                raise sys.exc_type, sys.exc_value
            except:
                print "Not running tests of application", app, "due to exception in set-up:"
                printException()
        return applicationRunners
    def performActionOnApps(self, applicationRunners, actionNum):
        try:
            for appRunner in applicationRunners:
                if appRunner.valid:
                    self.performAction(appRunner, actionNum)
        except SystemExit:
            # Assumed to be a child thread, in any case exit silently
            raise sys.exc_type, sys.exc_value
        except KeyboardInterrupt:
            print "Received kill signal, cleaning up all applications..."
            for appRunner in applicationRunners:
                appRunner.performCleanUp()
            raise sys.exc_type, sys.exc_value
    def performAction(self, appRunner, actionNum):
        try:
            appRunner.performAction(actionNum)
        except (SystemExit, KeyboardInterrupt):
            raise sys.exc_type, sys.exc_value
        except:
            print "Caught exception from application", appRunner.app, ", cleaning up and terminating its tests:"
            printException()
            appRunner.performCleanUp()

if __name__ == "__main__":
    program = TextTest()
    program.run()
