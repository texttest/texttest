#!/usr/bin/env python

import os, sys, shutil
from glob import glob

def exportDir(dirName, localOnly=False):
    cmd = "cvs -d /carm/2_CVS/ export -D 2030-01-01"
    if localOnly:
        cmd += " -l"
    cmdLine = cmd + " Testing/" + dirName
    print cmdLine
    os.system(cmdLine)

def exportFromCvs():
    for dirName in [ "TextTest", "PyUseCase", "Automatic/Diagnostics" ]:
        exportDir(dirName)
    exportDir("Automatic/texttest", localOnly=True)
    for subDirName in getTestSubDirs():
        exportDir(os.path.join("Automatic/texttest", subDirName))

def getTestSubDirs():
    checkDir = "/users/geoff/work/master/Testing/Automatic/texttest"
    ignoreDirs = [ "CVS", "carmen" ]
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

def getFrameworkFiles():
    sourceDir = "Testing/TextTest"
    imakeFile = os.path.join(sourceDir, "Imakefile")
    imgFile = os.path.join(sourceDir, "images", "Imakefile")
    return getNames(imakeFile, "FRAMEWORK_MODULES") + getNames(imakeFile, "THIRD_PARTY_MODULES") + \
           getNames(imakeFile, "FRAMEWORK_EXECUTABLES") + getNames(imgFile, "IMAGES")

def createBasic(reldir):
    if os.path.isdir(reldir):
        shutil.rmtree(reldir)
    os.mkdir(reldir)
    for fileName in [ "install.py", "readme.txt" ]:
        targetName = os.path.join(reldir, fileName)
        shutil.copy(fileName, targetName)

    shutil.copytree("doc", os.path.join(reldir, "doc"))
    print "Basic directory", reldir, "created, looks like: "
    os.system("ls -l " + reldir)

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
    extensions = [ "parisc_2_0", "powerpc", "sparc", "nonlinux", "carmen", "rhel3", "newgtk", "cover" ]
    pruneFilesWithExtensions(testDir, extensions)

def createSource(reldir):
    sourceDir = os.path.join(reldir, "source")
    os.mkdir(sourceDir)
    for fileName in glob("Testing/PyUseCase/*.py") + getFrameworkFiles():
        print "Copying", fileName
        targetPath = fileName.replace("Testing", reldir).replace("TextTest", "source").replace("PyUseCase", "source")
        dirName = os.path.dirname(targetPath)
        if not os.path.isdir(dirName):
            os.mkdir(dirName)
        shutil.copy(fileName, targetPath)

def getReleaseName():
    if len(sys.argv) > 1:
        return sys.argv[1]
    else:
        return "current"

if __name__ == "__main__":
    rootDir = os.path.dirname(sys.argv[0])
    os.chdir(rootDir)
    if os.path.isdir("Testing"):
        shutil.rmtree("Testing")
    exportFromCvs()

    releaseName = getReleaseName()
    reldir = "texttest-" + releaseName
    createBasic(reldir)
    createSource(reldir)
    createTests(reldir)
    
    shutil.rmtree("Testing")
    zipName = reldir + ".zip"
    if os.path.isfile(zipName):
        os.remove(zipName)
    os.system("zip -r " + zipName + " " + reldir)
    if releaseName != "current":
        shutil.rmtree(reldir)

#./texttest_test_install.sh ${1}
