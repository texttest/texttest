helpDescription = """
It follows the usage of the Carmen configuration.""" 

import lsf, guiplugins, os, string, shutil

def getConfig(optionMap):
    return DayOPsGUIConfig(optionMap)

class DayOPsGUIConfig(lsf.LSFConfig):
    def printHelpDescription(self):
        print helpDescription
        lsf.LSFConfig.printHelpDescription(self)
    def getExecuteCommand(self, binary, test):
        propFile = test.makeFileName("properties")
        logFile = test.makeFileName("dmserverlog", temporary=1)
        os.environ["DMG_RUN_TEST"] = test.abspath + "#" + propFile + "#" + logFile
        return lsf.LSFConfig.getExecuteCommand(self, binary, test)

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

class RecordTest(guiplugins.RecordTest):
    def __init__(self, test, oldOptionGroup):
        guiplugins.RecordTest.__init__(self, test, oldOptionGroup)
        self.test = test
        self.test.setUpEnvironment(1)
        baseName = os.environ["DMG_PROPS_INPUT"]
        propFileInCheckout = os.path.join(test.app.checkout, "Descartes", "DMG", baseName)
        defaultHTTPdir = os.environ["DMG_RECORD_HTTP_DIR"]
        self.test.tearDownEnvironment(1)
        self.props = JavaPropertyReader(propFileInCheckout)
        self.addOption(oldOptionGroup, "host", "DMServer host", self.props.get("host"))
        self.addOption(oldOptionGroup, "port", "Port", self.props.get("port"))
        self.addOption(oldOptionGroup, "w", "HTTP dir", defaultHTTPdir)
    def __call__(self, test):
        serverLog = test.makeFileName("input")
        propFileInTest = test.makeFileName("properties")
        newLogFile = test.makeFileName("dmserverlog")
        if os.path.isfile(test.useCaseFile):
            os.remove(test.useCaseFile)
        self.props.set("host", self.optionGroup.getOptionValue("host"))
        self.props.set("port", self.optionGroup.getOptionValue("port"))
        self.props.writeFile(propFileInTest)
        httpServerDir = self.optionGroup.getOptionValue("w")
        args = [ test.abspath, serverLog, propFileInTest, httpServerDir ]
        os.environ["DMG_RECORD_TEST"] = string.join(args,":")
        guiplugins.RecordTest.__call__(self, test)
        # Use the reran tests 'dmserverlog' as 'input' for the test not the
        # originally recorded 'input' file. i.e. copy 'dmserverlog' to 'input'
        if os.path.isfile(newLogFile):
            shutil.copyfile(newLogFile, serverLog)

        

