#!/usr/bin/env python

# texttest_release.py : makes a release from Bazaar source control. Can do so from a local setup using the
# environment variable BZRROOT (modelled on the layout at Jeppesen), or directly from Launchpad.

# Usage texttest_release.py [ -v <release_name> ] [ -t <tag> ] [ -x ] [ -d <working_dir> ]

# <working_dir> indicates where temporary files are written and the final zip file will end up.
# It defaults to the current working directory.

# <release_name> defaults to "current" and should be overridden when making external releases

# <tag> indicates a version control tag to use. This should be a pre-existing one that is set
# in both the TextTest source and the self-tests (but not StoryText, currently)

# The -x flag should be provided if the temporary files are to be left. Mostly useful for testing.

import os, sys, shutil
from glob import glob
from getopt import getopt

def getBzrLocation(product, artefact):
    # If $BZRROOT set, use the local repositories as laid out at Jeppesen, otherwise use Launchpad
    bzrRoot = os.getenv("BZRROOT")
    if bzrRoot:
        return os.path.join(bzrRoot, product, artefact, "branches/HEAD")
    else:
        launchpadNames = { "source" : "trunk", "tests": "selftest-trunk" }
        return "lp:~geoff.bache/" + product.lower() + "/" + launchpadNames.get(artefact)

def exportDir(product, artefact, targetName, dest, tag=""):
    destDir = os.path.join(dest, targetName)
    tagStr = tag
    if tag:
        tagStr = " -rtag:" + tag
    cmdLine = "bzr checkout" + tagStr + " --lightweight " + getBzrLocation(product, artefact) + " " + destDir
    print cmdLine
    os.system(cmdLine)
    shutil.rmtree(os.path.join(destDir, ".bzr"))

def exportFromBzr(dest, tagName):
    exportDir("TextTest", "source", "source", dest, tagName)
    os.mkdir(os.path.join(dest, "tests"))
    exportDir("TextTest", "tests", "tests/texttest", dest, tagName)
    exportDir("StoryText", "source", "source/storytext", dest)
        
def createSource(reldir):
    versionFile = os.path.join(reldir, "source", "lib", "texttest_version.py")
    updateVersionFile(versionFile, releaseName)
    os.rename(os.path.join(reldir, "source", "readme.txt"), os.path.join(reldir, "readme.txt"))
    
def updateVersionFile(versionFile, releaseName):
    newFileName = versionFile + ".new"
    newFile = open(newFileName, "w")
    for line in open(versionFile).xreadlines():
        newFile.write(line.replace("trunk", releaseName))
    newFile.close()
    os.rename(newFileName, versionFile)

def getCommandLine():
    options, leftovers = getopt(sys.argv[1:], "d:v:t:x")
    optDict = dict(options)
    return optDict.get("-d", os.getcwd()), optDict.get("-v", "current"), optDict.get("-t", ""), optDict.has_key("-x")
    
if __name__ == "__main__":
    rootDir, releaseName, tagName, leaveDir = getCommandLine()
    reldir = "texttest-" + releaseName
    actualRoot = os.path.join(rootDir, reldir)
    if os.path.isdir(actualRoot):
        shutil.rmtree(actualRoot)
    os.makedirs(actualRoot)
    
    exportFromBzr(actualRoot, tagName)
    createSource(actualRoot)
    
    os.chdir(rootDir)
    zipName = reldir + ".zip"
    if os.path.isfile(zipName):
        os.remove(zipName)
    print "Creating zip file", zipName
    os.system("zip -r " + zipName + " " + reldir)
    if not leaveDir:
        shutil.rmtree(reldir)
