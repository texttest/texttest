helpDescription = """
The MpsSolver configuration is a simple extension to the UNIX configuration. The main
purpose of it is to be able to create links to the MPS files, so that two tests using
the same MPS files will not collide""" 

import unixConfig, carmen, os, shutil, filecmp, string, plugins, comparetest, performance

def getConfig(optionMap):
    return MpsSolverConfig(optionMap)

class MpsSolverConfig(carmen.CarmenConfig):
    def getQueuePerformancePrefix(self, test, arch):
        if not os.environ.has_key("MPSSOLVER_LSFQUEUE_PREFIX"):
            return carmen.CarmenConfig.getQueuePerformancePrefix(self, test, arch)
        if arch == "powerpc" or arch == "parisc_2_0":
            return ""
        else:
            return os.environ["MPSSOLVER_LSFQUEUE_PREFIX"] + "_";
    def getExecuteCommand(self, binary, test):
        mpsFiles = self.makeMpsSymLinks(test)
        return binary + " " + self.getExecuteArguments(test, mpsFiles)
    def makeMpsSymLinks(self, test):
        #
        # We need to symlink in a temp testdir to the actual .mps files
        # so as to have unique dirs for writing .sol files etc. This is so that two tests
        # using the same .mps file has its own .sol (and .glb) file
        #
        mpsFiles = "";
        if os.environ.has_key("MPSDATA_PROBLEMS"):
            mpsFilePath = os.environ["MPSDATA_PROBLEMS"]
            for file in os.listdir(mpsFilePath):
                filecmp = file.lower()
                sourcePath = os.path.join(mpsFilePath, file)
                if filecmp.endswith(".mps"):
                    if not unixConfig.isCompressed(sourcePath):
                        mpsFiles += " " + file
                        os.symlink(sourcePath, file)
        return mpsFiles
    def getExecuteArguments(self, test, files):
        solverVersion = "1429"
        problemType = "ROSTERING"
        timeoutValue = "60"
        presolveValue = "0"
        if os.environ.has_key("MPSSOLVER_VERSION"):
            solverVersion = os.environ["MPSSOLVER_VERSION"]
        if os.environ.has_key("MPSSOLVER_PROBLEM_TYPE"):
            problemType = os.environ["MPSSOLVER_PROBLEM_TYPE"]
        if len(test.options) > 0:
            parts = test.options.split(":")
            if len(parts) > 0:
                timeoutValue = parts[0]
            if len(parts) > 1:
                presolveValue = parts[1]
        args = solverVersion + " " + problemType + " " + presolveValue + " " + timeoutValue
        return args + " " + files
    def printHelpDescription(self):
        print helpDescription
        carmen.CarmenConfig.printHelpDescription(self)


        
