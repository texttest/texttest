helpDescription = """
It follows the usage of the Carmen configuration.""" 

import carmen, guiplugins, os, string, shutil

def getConfig(optionMap):
    return DayOPsGUIConfig(optionMap)

class DayOPsGUIConfig(carmen.CarmenConfig):
    def printHelpDescription(self):
        print helpDescription
        carmen.CarmenConfig.printHelpDescription(self)
    def getExecuteCommand(self, binary, test):
        propFile = test.makeFileName("properties")
        logFile = test.makeFileName("dmserverlog", temporary=1)
        os.environ["DMG_RUN_TEST"] = test.abspath + "#" + propFile + "#" + logFile
        return carmen.CarmenConfig.getExecuteCommand(self, binary, test)
    def setApplicationDefaults(self, app):
        carmen.CarmenConfig.setApplicationDefaults(self, app)
        app.addConfigEntry("definition_file_stems", "properties")

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
        self.addOption(oldOptionGroup, "desmond_host", "Desmond host", self.props.get("desmond_host"))
        self.addOption(oldOptionGroup, "desmond_port", "Desmond port", self.props.get("desmond_port"))
        self.addOption(oldOptionGroup, "w", "HTTP dir", defaultHTTPdir)
    def __call__(self, test):
        serverLog = test.makeFileName("input")
        propFileInTest = test.makeFileName("properties")
        newLogFile = test.makeFileName("dmserverlog")
        if os.path.isfile(test.useCaseFile):
            os.remove(test.useCaseFile)
        self.props.set("host", self.optionGroup.getOptionValue("desmond_host"))
        self.props.set("port", self.optionGroup.getOptionValue("desmond_port"))
        self.props.writeFile(propFileInTest)
        httpServerDir = self.optionGroup.getOptionValue("w")
        args = [ test.abspath, propFileInTest, serverLog, httpServerDir ]
        os.environ["DMG_RECORD_TEST"] = string.join(args,":")
        guiplugins.RecordTest.__call__(self, test)
        # Use the reran tests 'dmserverlog' as 'input' for the test not the
        # originally recorded 'input' file. i.e. copy 'dmserverlog' to 'input'
        if os.path.isfile(newLogFile):
            shutil.copyfile(newLogFile, serverLog)
    def getRunOptions(self, test, usecase):
        baseOptions = guiplugins.RecordTest.getRunOptions(self, test, usecase)
        os.environ["DMG_RECORD_TEST"] = ""
        return baseOptions + " -l "
