helpDescription = """
The MpsSolver configuration is a simple extension to the UNIX configuration. The main
purpose of it is to be able to create links to the MPS files, so that two tests using
the same MPS files will not collide""" 

import unixConfig, carmen, os

def getConfig(optionMap):
    return MpsSolverConfig(optionMap)

class MpsSolverConfig(carmen.CarmenConfig):
    def getExecuteCommand(self, binary, test):
        return binary + " " + test.options + " " + self.makeMpsSymLinks(test)
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
    def printHelpDescription(self):
        print helpDescription
        carmen.CarmenConfig.printHelpDescription(self)


        
