#!/usr/local/bin/python

import os, plugins, carmen
from glob import glob

#Generic test plugin which will not only compare stdout and stderr but
#also files created in the test directory that have specified extensions.
#If the files created are compressed they will automatically be uncompressed.

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

#The plugin will automatcally compress the comparison files if they have
#a size over 50000 or a over size defined by your entry in "config.app"
#like this:
#compress_bytesize_over:15000
#If this size is set to 0 no compression is made

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
    def getExecuteCommand(self, binary, test):
        return binary.replace("ARCHITECTURE", carmen.architecture) + " " + test.options
    def getTestCollator(self):
        return plugins.CompositeAction([ HandleCompressedFiles(0), carmen.CarmenConfig.getTestCollator(self),  createCompareFiles() ])

    def getTestEvaluator(self):
        return plugins.CompositeAction([  carmen.CarmenConfig.getTestEvaluator(self) , HandleCompressedFiles(1) ])
        
class HandleCompressedFiles(plugins.Action):
    def __init__(self,compress=0):
        self.compressIfOverSize=50000
        self.zext=".Z"
        if compress:
            self.zext=""
    def __call__(self, test):
        checkExtensions=[]
        files=[]
        if test.app.configDir.has_key('compress_bytesize_over'):
            self.compressIfOverSize=int(test.app.configDir['compress_bytesize_over'])
        if test.app.configDir.has_key('check_extension'):
            checkExtensions=test.app.configDir.getListValue('check_extension')
        if not checkExtensions:
            return
        checkExtensions=[ x.replace('.','_')+"."+ test.app.name+self.zext for x in checkExtensions ]
        for ext in checkExtensions:
            files+=glob('*'+ext)
        #print test.app.name, os.path.basename(os.getcwd()), os.listdir('.'), files, self.zext
        for file in files:
            if self.zext :
                if isCompressed(file):
                    #print "uncompressing:", file
                    os.system('uncompress '+file)
            elif os.stat(file)[6] > self.compressIfOverSize:
                #0 as size means do not compress at all
                if 0 == self.compressIfOverSize:
                    return
                #print "compressing:", file
                os.system('compress '+file)
                
class createCompareFiles(plugins.Action):
    def __call__(self, test):
        checkExtensions=[]
        files2Check=[]
        if test.app.configDir.has_key('check_extension'):
            checkExtensions=test.app.configDir.getListValue('check_extension')
        if not checkExtensions:
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


