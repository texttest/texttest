#!/usr/local/bin/python

import os, plugins, carmen
from glob import glob

#Generic test plugin which will not only compare stdout and stderr but
#also files created in the test directory that have specified extensions.
#If the files created are compressed they will automaticly be uncompressed.

#Specify file extensions to check in "config.app":
#
#check_extension:.rrl
#check_extension:.log

#To filter things that should not be used for comparison from the files
#add the file name (with dots "." changed to underscore "_") into
#"config.app" (run.log -> run_log):
#
#run_log:text to be filtered out
#run_log:text to be filtered out2

#by Christian Sandborg 2003-02-19

def getConfig(optionMap):
    return CheckExtConfig(optionMap)

def isCompressed(path):
    magic = open(path).read(2)
    if len(magic) < 2:
        return 0
    if magic[0] == chr(0x1f) and magic[1] == chr(0x9d):
        return 1
    else:
        return 0

class CheckExtConfig(carmen.CarmenConfig):
    
    def interpretBinary(self, binaryString):
        return binaryString.replace("ARCHITECTURE", carmen.architecture)
    def getTestCollator(self):
        return plugins.CompositeAction([ carmen.CarmenConfig.getTestCollator(self),  createCompareFiles() ])
    
class createCompareFiles(plugins.Action):
    def __call__(self, test):
        checkExtensions=[]
        files2Check=[]
        if test.app.configDir.has_key('check_extension'):
            checkExtensions=test.app.configDir.getListValue('check_extension')
        if not checkExtensions:
            print "(No file extensions for comparison.)"
            return
        #print "Extensions to be compared:",checkExtensions
        for ext in checkExtensions:
            files2Check+=glob('*'+ext)
        #print "These files will be compared:",(' ').join(files2Check)
        for file in files2Check:
            #the current standard compare can't handle dots in the names
            f = file.replace('.','_')
            compareFile=test.getTmpFileName(f,'w')
            if isCompressed(file):
                os.system('zcat '+file+' > '+compareFile)
                os.unlink(file)
            else:
                os.rename(file,compareFile)


