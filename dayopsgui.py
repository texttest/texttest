helpDescription = """
It follows the usage of the Carmen configuration.""" 

import guiplugins, plugins, os, string, shutil
from carmenqueuesystem import CarmenConfig

def getConfig(optionMap):
    return DayOPsGUIConfig(optionMap)

class DayOPsGUIConfig(CarmenConfig):
    def printHelpDescription(self):
        print helpDescription
        CarmenConfig.printHelpDescription(self)
    def setEnvironment(self, test):
        if test.classId() == "test-case":
            propFile = test.getFileName("properties")
            logFile = test.makeTmpFileName("dmserverlog")
            test.setEnvironment("DMG_RUN_TEST", test.getDirectory() + "#" + propFile + "#" + logFile)
    def setApplicationDefaults(self, app):
        CarmenConfig.setApplicationDefaults(self, app)
        app.addConfigEntry("definition_file_stems", "properties")

class JavaPropertyReader:
    def __init__(self, filename=None):
        self.properties = {}
        if filename and os.path.isfile(filename):
            self.parseFile(filename)
    def parseFile(self, filename):
        for line in plugins.readList(filename):
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
        wFile = open(filename, "a")
        for key in self.properties.keys():
            wFile.write(key + "=" + self.properties[key] + os.linesep)

class ImportTestCase(guiplugins.ImportTestCase):
    def __init__(self, test, oldOptionGroup):
        guiplugins.ImportTestCase.__init__(self, test, oldOptionGroup)
        defaultHTTPdir = test.getEnvironment("DMG_RECORD_HTTP_DIR")
        baseName = test.getEnvironment("DMG_PROPS_INPUT")
        propFileInCheckout = os.path.join(test.app.checkout, "Descartes", "DMG", baseName)
        self.props = JavaPropertyReader(propFileInCheckout)
        self.addOption(oldOptionGroup, "desmond_host", "Desmond host", self.props.get("desmond_host"))
        self.addOption(oldOptionGroup, "desmond_port", "Desmond port", self.props.get("desmond_port"))
        self.addOption(oldOptionGroup, "w", "HTTP dir", defaultHTTPdir)
    def writeEnvironmentFile(self, suite, testDir):
        self.props.set("host", self.optionGroup.getOptionValue("desmond_host"))
        self.props.set("port", self.optionGroup.getOptionValue("desmond_port"))
        propsFile = os.path.join(testDir, "properties." + suite.app.name)
        self.props.writeFile(propsFile)
