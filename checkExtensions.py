#!/usr/local/bin/python

import os, plugins, carmen
from glob import glob

helpDescription="""
Generic test plugin which will not only compare stdout and stderr but
also files created in the test directory that have specified extensions.
If the files created are compressed they will automatically be uncompressed.
The comparison and input files will be compressed after the test and
uncompressed when needed (see below).

Specify file extensions to check in "config.app":

check_extension:.rrl
check_extension:.log

To filter things that should not be used for comparison from the files
add the file name (with dots "." changed to underscore "_") into
"config.app" (example run.log -> run_log):

run_log:text to be filtered out
run_log:text to be filtered out2

The plugin will automatcally compress the comparison files and input files
if they have a size over 50000 or over size defined by your entry in
"config.app" like this:
compress_bytesize_over:15000
If this size is set to 0 no compression is made

To define which input files that should be compressed after each run, add
entries to the "config.app" like this:
compress_extension:.ssim
compress_extension:.SSIM
compress_extension:.ctf

by Christian Sandborg 2003-02-19
"""

#constants
COMPRESS=1
UNCOMPRESS=0

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
        return plugins.CompositeAction([ HandleCompressedFiles(UNCOMPRESS,'check_extension'),
                                         carmen.CarmenConfig.getTestCollator(self),
                                         CreateCompareFiles(),
                                         HandleCompressedFiles(COMPRESS) ])

    def getTestEvaluator(self):
        return plugins.CompositeAction([ carmen.CarmenConfig.getTestEvaluator(self) ,
                                         HandleCompressedFiles(COMPRESS,'check_extension') ])

    def getTestRunner(self):
        return plugins.CompositeAction([ HandleCompressedFiles(UNCOMPRESS),
                                         carmen.CarmenConfig.getTestRunner(self)])
    def printHelpDescription(self):
        print helpDescription
        carmen.CarmenConfig.printHelpDescription(self)
    

class HandleCompressedFiles(plugins.Action):
    def __init__(self,compress,keyInConfig='compress_extension',compressIfOverSize=50000):
        self.compressIfOverSize=compressIfOverSize
        self.compress=compress
        self.zext=".Z"
        if compress:
            self.zext=""
        self.keyInConfig=keyInConfig
    
    def __call__(self, test):
        extensions=[]
        files=[]
        if test.app.configDir.has_key('compress_bytesize_over'):
            self.compressIfOverSize=int(test.app.configDir['compress_bytesize_over'])
        extensions=test.app.configDir.getListValue(self.keyInConfig)
        if not extensions:
            return
        #special case for 'check_extensions' (they are used for comparison)
        if 'check_extension' == self.keyInConfig:
            extensions=[ x.replace('.','_')+"."+ test.app.name \
                         for x in extensions ]
        for ext in extensions:
            files+=glob('*'+ext+self.zext)
        for file in files:
            if not self.compress:
                if isCompressed(file):
                    #print "uncompressing:", file
                    os.system('uncompress -f '+file)
            elif os.stat(file)[6] > self.compressIfOverSize:
                #0 as size means do not compress at all
                if 0 == self.compressIfOverSize:
                    return
                #print "compressing:", file
                os.system('compress -f '+file)
                    
                
class CreateCompareFiles(plugins.Action):
    def __call__(self, test):
        checkExtensions=[]
        files2Check=[]
        if test.app.configDir.has_key('check_extension'):
            checkExtensions=test.app.configDir.getListValue('check_extension')
        if not checkExtensions:
            return
        #print "Extensions to be compared:",checkExtensions
        for ext in checkExtensions:
            flist=glob('*'+ext)
            if flist:
                files2Check+=flist
            else:
                #Special check to see if a file was not created at all
                #(but has a stored compare file)
                #It should also be reported as an error
                missing=glob(('*'+ext).replace('.','_')+'.'+test.app.name)
                for file in missing:
                    dummyErrFileName=file.split('.')[0]
                    f=open(test.getTmpFileName(dummyErrFileName,'w'),'w')
                    f.write("File %s was not created!\nThis dummy file was created by the test framework.\n"\
                            %(dummyErrFileName))
                    f.close()                    
        #print "These files will be compared:",(' ').join(files2Check)
        for file in files2Check:
            #the current standard compare can't handle dots in the names
            f = file.replace('.','_')
            compareFile=test.getTmpFileName(f,'w')
            #the program might create compressed files
            if isCompressed(file):
                os.system('zcat -f '+file+' > '+compareFile)
                os.unlink(file)
            else:
                os.rename(file,compareFile)
        

