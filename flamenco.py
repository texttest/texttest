helpDescription = """
The Flamenco configuration is based on the Carmen configuration. It is set up to replace the string "ARCHITECTURE"
with the running architecture in the name of the binary given in the config file. It will also collect the
file "sqlnet.log", and compare it as the test suite file sqlerr.<app>."""

import carmen, os, plugins

def getConfig(optionMap):
    return FlamencoConfig(optionMap)

class FlamencoConfig(carmen.CarmenConfig):
    def getExecuteCommand(self, binary, test):
        return binary.replace("ARCHITECTURE", carmen.architecture) + " " + test.options
    def getTestCollator(self):
        return plugins.CompositeAction([ carmen.CarmenConfig.getTestCollator(self), MakeSQLErrorFile() ])
    def printHelpDescription(self):
        print helpDescription
        carmen.CarmenConfig.printHelpDescription(self)

class MakeSQLErrorFile(plugins.Action):
    def __call__(self, test):
        sqlfile = test.getTmpFileName("sqlerr", "w")
        if os.path.isfile("sqlnet.log"):
            os.rename("sqlnet.log", sqlfile)
        else:
            file = open(sqlfile, "w")
            file.write("NO ERROR" + os.linesep)
    
