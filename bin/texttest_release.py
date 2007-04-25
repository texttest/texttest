#!/usr/bin/env python

# texttest_release.py

# Extracts the code and tests from Jeppesen's CVS into a zip file
# and removes everything that is Jeppesen-specific
# Not useful outside Jeppesen currently

# Usage texttest_release.py [ -v <release_name> ] [ -x ] [ -d <working_dir> ] [ -D <export_date> ] 

# <working_dir> indicates where temporary files are written and the final zip file will end up.
# It defaults to the current working directory.

# <export_date> indicates the date tag to use from CVS when exporting. It defaults to a date in 2030,
# i.e. as up to date as possible.

# <release_name> defaults to "current" and should be overridden when making external releases

# The -x flag should be provided if the temporary files are to be left. Mostly useful for testing.

import os, sys, shutil
from glob import glob
from getopt import getopt

def exportDir(dirName, date, localOnly=False):
    cmd = "cvs -d /carm/2_CVS/ export -D " + date
    if localOnly:
        cmd += " -l"
    cmdLine = cmd + " Testing/" + dirName
    print cmdLine
    os.system(cmdLine)

def exportFromCvs(date):
    for dirName in [ "TextTest", "PyUseCase", "Automatic/Diagnostics" ]:
        exportDir(dirName, date)
    exportDir("Automatic/texttest", date, localOnly=True)
    for subDirName in getTestSubDirs():
        exportDir(os.path.join("Automatic/texttest", subDirName), date)

def getTestSubDirs():
    checkDir = "/users/geoff/work/master/Testing/Automatic/texttest"
    ignoreDirs = [ "CVS", "carmen", "CurrentRelease", "ExternalWithOldFiles" ]
    subDirs = []
    for fileName in os.listdir(checkDir):
        fullPath = os.path.join(checkDir, fileName)
        if os.path.isdir(fullPath) and fileName not in ignoreDirs:
            subDirs.append(fileName)
    return subDirs

def pruneFilesWithExtensions(dir, extensions):
    for fileName in os.listdir(dir):
        fullPath = os.path.join(dir, fileName)
        if os.path.isdir(fullPath):
            pruneFilesWithExtensions(fullPath, extensions)
        else:
            extension = fileName.split(".")[-1]
            if extension in extensions:
                print "Removing", fullPath
                os.remove(fullPath)

def getNames(fileName, key):
    sourceDir, local = os.path.split(fileName)
    for line in open(fileName).xreadlines():
        if line.startswith(key):
            fileStr = line.strip().split("=")[-1]
            return [ os.path.join(sourceDir, fileName) for fileName in fileStr.split() ]

disallowedPrefixes = [ "optimization", "apc", "matador", "studio" ]
disallowedFiles = [ "texttest", "texttest_release.py", ".cvsignore", "carmenqueuesystem.py", "ravebased.py", "barchart.py", "ddts.py" ]

def isAllowed(file):
    if file in disallowedFiles:
        return False
    for prefix in disallowedPrefixes:
        if file.startswith(prefix):
            return False
    return True

def getFrameworkFiles():
    sourceDir = "Testing/TextTest"
    fullFiles = []
    for dirpath, subdirs, files in os.walk(sourceDir):
        allowedFiles = filter(isAllowed, files)
        fullFiles += [ os.path.join(dirpath, file) for file in allowedFiles ]
    return fullFiles

def updateConfigFile(configFile):
    newFileName = configFile + ".new"
    newFile = open(newFileName, "w")
    writeSection = False
    for line in open(configFile).xreadlines():
        if line.startswith("## ==="):
            writeSection = not writeSection
        elif writeSection:
            newFile.write(line)
    newFile.close()
    os.rename(newFileName, configFile)

def createTests(reldir):
    testDir = os.path.join(reldir, "tests")
    os.rename("Testing/Automatic", testDir)
    updateConfigFile(os.path.join(testDir, "texttest", "config.texttest"))
    extensions = [ "parisc_2_0", "powerpc", "sparc", "nonlinux", "carmen", "rhel3", "newgtk", "cover", "ttrel" ]
    pruneFilesWithExtensions(testDir, extensions)

def createSource(reldir):
    if os.path.isdir(reldir):
        shutil.rmtree(reldir)
    sourceDir = os.path.join(reldir, "source")
    os.makedirs(sourceDir)
    for fileName in glob("Testing/PyUseCase/*.py") + getFrameworkFiles():
        print "Copying", fileName
        targetPath = fileName.replace("Testing", reldir).replace("TextTest", "source").replace("PyUseCase", "source/lib")
        dirName = os.path.dirname(targetPath)
        if not os.path.isdir(dirName):
            os.makedirs(dirName)

        shutil.copy(fileName, targetPath)

def getCommandLine():
    options, leftovers = getopt(sys.argv[1:], "d:D:v:x")
    optDict = dict(options)
    return optDict.get("-d", os.getcwd()), optDict.get("-D", "2030-01-01"), optDict.get("-v", "current"), optDict.has_key("-x")
    
if __name__ == "__main__":
    rootDir, cvsDate, releaseName, leaveDir = getCommandLine()
    os.chdir(rootDir)
    if os.path.isdir("Testing"):
        shutil.rmtree("Testing")
    exportFromCvs(cvsDate)

    reldir = "texttest-" + releaseName
    createSource(reldir)
    createTests(reldir)
    
    shutil.rmtree("Testing")
    zipName = reldir + ".zip"
    if os.path.isfile(zipName):
        os.remove(zipName)
    os.system("zip -r " + zipName + " " + reldir)
    if not leaveDir:
        shutil.rmtree(reldir)
