#!/usr/local/bin/python
import os, plugins, respond, string, carmen, checkExtensions

from checkExtensions import COMPRESS, UNCOMPRESS
from glob import glob

def getConfig(optionMap):
    return Ctf2RrlConfig(optionMap)

def decompressAndRename(src,dst):
    if checkExtensions.isCompressed(src):
        os.system('zcat ' + src + ' > ' + dst)
        os.unlink(src)
    else:
        os.rename(src,dst)
    
    
class Ctf2RrlConfig(checkExtensions.CheckExtConfig):
    def getTestCollator(self):
        return plugins.CompositeAction([checkExtensions.HandleCompressedFiles(UNCOMPRESS,'check_extension'),
                                        carmen.CarmenConfig.getTestCollator(self),
                                        RenamePlans(),
                                        GetEtabs(),
                                        checkExtensions.CreateCompareFiles(),
                                        checkExtensions.HandleCompressedFiles(COMPRESS)])
    
                
class RenamePlans(plugins.Action):
    def __call__(self, test):
        if os.path.isfile("./localplan"):
            decompressAndRename("./localplan","./localplan.lp")
        if os.path.isfile("./subplan"):
            decompressAndRename("./subplan","./subplan.sp")
        if os.path.isfile("./subplanHeader"):
            decompressAndRename("./subplanHeader","./subplanHeader.sp")
        if os.path.isfile("./envplan"):
            decompressAndRename("./envplan","./envplan.sp")
        if os.path.isfile("./envplanHeader"):
            decompressAndRename("./envplanHeader","./envplanHeader.sp")


class GetEtabs(plugins.Action):
    def __call__(self, test):
        lpEtabs = glob("./etable/LpLocal/*")
        for file in lpEtabs:
            os.rename(file,"./"+os.path.basename(file)+".lp")
        spEtabs = glob("./etable/SpLocal/*")
        for file in spEtabs:
            os.rename(file,"./"+os.path.basename(file)+".sp")
            


