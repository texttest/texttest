import carmen, os

def getConfig(optionMap):
    return FlamencoConfig(optionMap)

class FlamencoConfig(carmen.CarmenConfig):
    def interpret(self, binaryString):
        return binaryString.replace("ARCHITECTURE", carmen.architecture)
    def getTestCollator(self):
        return carmen.CarmenConfig.getTestCollator(self) + [ MakeSQLErrorFile() ]

class MakeSQLErrorFile:
    def __repr__(self):
        return "Creating SQL error file for"
    def __call__(self, test, description):
        sqlfile = test.getTmpFileName("sqlerr", "w")
        if os.path.isfile("sqlnet.log"):
            os.rename("sqlnet.log", sqlfile)
        else:
            file = open(sqlfile, "w")
            file.write("NO ERROR" + os.linesep)
    def setUpSuite(self, suite, description):
        pass
    
