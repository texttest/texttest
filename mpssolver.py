helpDescription = """
The MpsSolver configuration is based on the Carmen configuration. """ 

helpOptions = """
"""

helpScripts = """
"""

import unixConfig, carmen, os, shutil, filecmp, optimization, string, plugins, comparetest

def getConfig(optionMap):
    return MpsSolverConfig(optionMap)

class MpsSolverConfig(carmen.CarmenConfig):
    def __init__(self, optionMap):
        carmen.CarmenConfig.__init__(self, optionMap)
        if self.optionMap.has_key("diag"):
            os.environ["DIAGNOSTICS_IN"] = "./Diagnostics"
            os.environ["DIAGNOSTICS_OUT"] = "./Diagnostics"
        if os.environ.has_key("DIAGNOSTICS_IN"):
            print "Note: Running with Diagnostics on, so performance checking is disabled!"
    def __del__(self):
        if self.optionMap.has_key("diag"):
            del os.environ["DIAGNOSTICS_IN"]
            del os.environ["DIAGNOSTICS_OUT"]
    def getSwitches(self):
        switches = carmen.CarmenConfig.getSwitches(self)
        switches["diag"] = "Use MpsSolver Codebase diagnostics"
        return switches
    def getLibPathEnvName(self, archName):
        if archName == "sparc" or archName == "i386_linux":
            return "LD_LIBRARY_PATH"
        elif archName.startswith("parisc"):
            return "SHLIB_PATH"
        elif archName == "powerpc":
            return "LIBPATH"
        else:
            return "FOOBAR"
    def getExecuteCommand(self, binary, test):
        binary = os.path.basename(binary)
        archName = carmen.getArchitecture(test.app)
        binary = os.path.join(os.environ["CARMSYS"], "bin", archName, binary)
        ldPath1 = os.path.join(os.environ["MPSSOLVER_ROOT"], archName + os.environ["MPSSOLVER_LIBVERSION"], "lib")
        ldPath2 = os.path.join(os.environ["CARMSYS"], "lib", archName)
        ldEnv = self.getLibPathEnvName(archName)
        binary = "env " + ldEnv + "=" + "${" + ldEnv + "}:" + ldPath1 + ":" + ldPath2 + " " + binary
        mpsFiles = "";
        for file in os.listdir(test.abspath):
            if file.endswith(".mps"):
                mpsFiles += " " + file
                sourcePath = os.path.join(test.abspath, file)
                if not unixConfig.isCompressed(sourcePath):
                    os.symlink(sourcePath, file)
                else:
                    os.system("uncompress -c " + sourcePath + " > " + file)
        return binary + " " + test.options + mpsFiles
    def checkPerformance(self):
        return not self.optionMap.has_key("diag")
#    def getTestCollator(self):
#        solutionCollator = unixConfig.CollateFile("best_solution", "solution")
#        return plugins.CompositeAction([ carmen.CarmenConfig.getTestCollator(self), solutionCollator ])
    def printHelpDescription(self):
        print helpDescription
        carmen.CarmenConfig.printHelpDescription(self)
    def printHelpOptions(self, builtInOptions):
        carmen.CarmenConfig.printHelpOptions(self, builtInOptions)
        print helpOptions
    def printHelpScripts(self):
        carmen.CarmenConfig.printHelpScripts(self)
        print helpScripts
    def setUpApplication(self, app):
        carmen.CarmenConfig.setUpApplication(self, app)
        if os.environ.has_key("DIAGNOSTICS_IN"):
            app.addToConfigList("copy_test_path", "Diagnostics")
            app.addToConfigList("compare_extension", "diag")
