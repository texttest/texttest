helpDescription = """
It follows the usage of the Carmen configuration.""" 

helpOptions = """ No special DayOPsGUIConfig options
"""
helpScripts = """ No special DayOPsGUIConfig scripts
"""

import unixConfig, guiplugins, os, string

def getConfig(optionMap):
    return DayOPsGUIConfig(optionMap)

class DayOPsGUIConfig(unixConfig.UNIXConfig):
    def __init__(self, optionMap):
        unixConfig.UNIXConfig.__init__(self, optionMap)
    def addToOptionGroup(self, group):
        unixConfig.UNIXConfig.addToOptionGroup(self, group)
    def printHelpDescription(self):
        print helpDescription
        unixConfig.UNIXConfig.printHelpDescription(self)
    def printHelpOptions(self, builtInOptions):
        unixConfig.UNIXConfig.printHelpOptions(self, builtInOptions)
        print helpOptions
    def printHelpScripts(self):
        unixConfig.UNIXConfig.printHelpScripts(self)
        print helpScripts
    def setApplicationDefaults(self, app):
        unixConfig.UNIXConfig.setApplicationDefaults(self, app)
    def getExecuteCommand(self, binary, test):
        testName = test.name
        propFile = test.makeFileName("properties")
        simFile = test.makeFileName("simulation")
        logFile = test.makeFileName("dmserverlog", temporary=1)
        return binary + " -test " + testName + " " + propFile + " " + simFile + " " + logFile

class JavaPropertyReader:
    def __init__(self, filename):
        self.properties = {}
        if os.path.isfile(filename):
            for line in open(filename).xreadlines():
                line = line.strip()
                if line.startswith("#") or line.find("=") == -1:
                    continue
                parts = line.split("=")
                if len(parts) == 2:
                    self.properties[parts[0]] = parts[1]
    def get(self, key):
        if not self.properties.has_key(key):
            return ""
        else:
            return self.properties[key]
    def set(self, key, value):
        self.properties[key] = value
    def writeFile(self, filename):
        wFile = open(filename, "w")
        for key in self.properties.keys():
            wFile.write(key + "=" + self.properties[key] + os.linesep)

class RecordDayOpsTest(guiplugins.InteractiveAction):
    def __init__(self, test):
        guiplugins.InteractiveAction.__init__(self, test, "Record")
        self.test = test
        self.test.setUpEnvironment(1)
        baseName = os.environ["DMG_PROPS_INPUT"]
        self.propFileName = os.path.join(test.app.checkout, "Descartes", "DMG", baseName)
        defaultHTTPdir = os.environ["DMG_RECORD_HTTP_DIR"]
        self.test.tearDownEnvironment(1)
        self.props = JavaPropertyReader(self.propFileName)
        self.optionGroup.addOption("v", "Version", "")
        self.optionGroup.addOption("host", "DMServer host", self.props.get("host"))
        self.optionGroup.addOption("port", "Port", self.props.get("port"))
        self.optionGroup.addOption("w", "HTTP dir", defaultHTTPdir)
    def __repr__(self):
        return "Recording"
    def canPerformOnTest(self):
        existName = self.test.makeFileName("input")
        if os.path.isfile(existName):
            return 0
        return 1
    def getTitle(self):
        return "Test recording"
    def __call__(self, test):
        testDir = test.abspath
        testPropFile = test.makeFileName("properties")
        simFile = test.makeFileName("simulation")
        serverLog1 = test.makeFileName("input")
        serverLog2 = test.makeFileName("dmserverlog")
        outputFile = test.makeFileName(test.app.getConfigValue("log_file"))
        errorFile = test.makeFileName("errors")
        self.test.setUpEnvironment(1)
        args = [ testDir, self.propFileName, simFile, serverLog1, serverLog2 ]
        args.append(outputFile)
        args.append(errorFile)
        args.append(testPropFile)
        args.append(test.getConfigValue("view_program"))
        binary = test.getConfigValue("binary")
        os.system("cd " + test.abspath + "; " + binary + " -record " + string.join(args))
        self.test.tearDownEnvironment(1)
        
guiplugins.interactiveActionHandler.testClasses += [ RecordDayOpsTest ]

