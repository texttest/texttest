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

import os
import sys
import shutil
import subprocess
import stat
import time
from glob import glob
from getopt import getopt


def getSfUser():
    userMap = {"geoff": "gjb1002", "E601429": "gjb1002", "dgalda": "dagal"}
    user = os.getenv("USER", os.getenv("USERNAME"))
    return userMap.get(user, user)


def system(args):
    print(" ".join(args))
    subprocess.call(args)


def getBzrLocation(product, artefact):
    # If $BZRROOT set, use the local repositories as laid out at Jeppesen, otherwise use Launchpad
    bzrRoot = os.getenv("BZRROOT", "/carm/proj/texttest/bzr")
    if bzrRoot and os.path.isdir(bzrRoot):
        return os.path.join(bzrRoot, product, artefact, "branches/HEAD")
    else:
        launchpadNames = {"source": "trunk", "tests": "selftest-trunk"}
        return "lp:~geoff.bache/" + product.lower() + "/" + launchpadNames.get(artefact)


def exportFromBzr(dest, tagName):
    args = ["bzr", "checkout", "--lightweight"]
    if tagName:
        args.append("-rtag:" + tagName)
    args.append(getBzrLocation("TextTest", "source"))
    args.append(dest)
    system(args)


def createSource(reldir, debug):
    versionFile = os.path.join(reldir, "texttestlib", "texttest_version.py")
    updateVersionFile(versionFile, releaseName)
    args = ["python", "setup.py", "sdist"]
    if not debug:
        args.append("upload")
    subprocess.call(args, cwd=reldir)


def updateVersionFile(versionFile, releaseName):
    newFileName = versionFile + ".new"
    with open(newFileName, "w") as newFile:
        for line in open(versionFile):
            newFile.write(line.replace("trunk", releaseName))
    os.remove(versionFile)
    os.rename(newFileName, versionFile)


def getCommandLine():
    options, leftovers = getopt(sys.argv[1:], "d:v:t:x")
    optDict = dict(options)
    return optDict.get("-d", os.getcwd()), optDict.get("-v", "current"), optDict.get("-t", ""), "-x" in optDict


def readmeUpdated(readme):
    if not os.path.isfile(readme):
        return False

    mtime = os.stat(readme)[stat.ST_MTIME]
    currTime = time.time()
    hoursSinceEdit = (currTime - mtime) / 3600
    return hoursSinceEdit < 24


if __name__ == "__main__":
    rootDir, releaseName, tagName, debug = getCommandLine()
    devRelease = "dev" in releaseName
    readme = os.path.join(rootDir, "readme.txt")
    if not devRelease and not readmeUpdated(readme):
        print("Cannot make external release, readme file at", readme, "has not been updated recently.")
        sys.exit(1)
    reldir = "texttest-" + releaseName
    actualRoot = os.path.join(rootDir, reldir)
    if os.path.isdir(actualRoot):
        shutil.rmtree(actualRoot)
    os.makedirs(actualRoot)

    exportFromBzr(actualRoot, tagName)
    createSource(actualRoot, debug)

    if not devRelease:
        tarball = os.path.join(actualRoot, "dist", "TextTest-" + releaseName + ".tar.gz")
        target = os.path.join("/home/frs/project/texttest/texttest", releaseName)
        args = ["rsync", "-av", "--rsh=ssh", tarball, readme, getSfUser() + "@web.sourceforge.net:" + target]
        print(" ".join(args))
        if not debug:
            subprocess.call(args)
