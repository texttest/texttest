import carmen, os, plugins

def getConfig(optionMap):
    return FlamencoConfig(optionMap)

class FlamencoConfig(carmen.CarmenConfig):
    def getExecuteCommand(self, binary, test):
        return binary.replace("ARCHITECTURE", carmen.architecture) + " " + test.options
    def getTestCollator(self):
        return plugins.CompositeAction([ carmen.CarmenConfig.getTestCollator(self), MakeSQLErrorFile() ])

class MakeSQLErrorFile(plugins.Action):
    def __call__(self, test):
        sqlfile = test.getTmpFileName("sqlerr", "w")
        if os.path.isfile("sqlnet.log"):
            os.rename("sqlnet.log", sqlfile)
        else:
            file = open(sqlfile, "w")
            file.write("NO ERROR" + os.linesep)
    
