#
# Some useful path operations.
#

import os

# If path is relative, try to find it in one of the folders.
# If not, return the path itself.
# foldersToSearch is supposed to be a list of pairs
# (short name, absolute path), where short name is the
# short hand name (~relative path, e.g. filter_files) of
# the folder.
def getAbsolutePath(foldersToSearch, path):
    path = path.replace("\\", os.sep)# support mixed-OS paths: FileChoosers don't use the python interface...
    if os.path.isabs(path):
        return path
    for folder in foldersToSearch:
        if path.startswith(folder[0] + os.sep):
            result = os.path.join(folder[1], path.replace(folder[0], "").lstrip(os.sep))
            return result
    return path

# If path is in one of the folders, or subfolders of them, return a
# suitable relative path, using the short name (see comment above).
# If not, return absolute path.
def getRelativeOrAbsolutePath(foldersToSearch, absPath):
    absPath = absPath.replace("\\", os.sep) # support mixed-OS paths: FileChoosers don't use the python interface...
    for folder in foldersToSearch:
        realFolder = folder
        if not folder[1].endswith(os.sep):
            realFolder = (folder[0], folder[1] + os.sep)
        if isInSubDir(realFolder[1], absPath):
            relPath = os.path.join(realFolder[0], absPath.replace(realFolder[1], ""))
            return relPath
    return absPath

def commonPathPrefix(path1, path2):
    longestPrefix = os.path.commonprefix([path1, path2])
    dir = os.path.split(longestPrefix)[0]
    return dir

def isInSubDir(dir, path):
    return os.path.normpath(commonPathPrefix(dir, path)) == os.path.normpath(dir)

# (c) May 2002 Thomas Guettler http://www.thomas-guettler.de
# This code is in the public domain
# Feedback Welcome
# Downloaded from http://guettli.sourceforge.net/gthumpy/src/relative_url.py
#
# This code works for URLs as well as *nix and windows paths, as
# far as I can tell. I've renamed it from relative_url to relativePath
# to make its use more obvious in our case ...
#
import urlparse
import re
import string

def relativePath(source, target):
    su=urlparse.urlparse(source)
    tu=urlparse.urlparse(target)
    junk=tu[3:]
    if su[0]!=tu[0] or su[1]!=tu[1]:
        #scheme (http) or netloc (www.heise.de) are different
        #return absolut path of target
        return target
    su=re.split("/", su[2])
    tu=re.split("/", tu[2])
    su.reverse()
    tu.reverse()

    #remove parts which are equal   (['a', 'b'] ['a', 'c'] --> ['c'])
    while len(su)>0 and len(tu)>0 and su[-1]==tu[-1]:
        su.pop()
        last_pop=tu.pop()
    if len(su)==0 and len(tu)==0:
        #Special case: link to itself (http://foo/a http://foo/a -> a)
        tu.append(last_pop)
    if len(su)==1 and su[0]=="" and len(tu)==0:
        #Special case: (http://foo/a/ http://foo/a -> ../a)
        su.append(last_pop)
        tu.append(last_pop)
    tu.reverse()
    relative_url=[]
    for i in range(len(su)-1): 
        relative_url.append("..")
    rel_url=string.join(relative_url + tu, "/")
    rel_url=urlparse.urlunparse(["", "", rel_url, junk[0], junk[1], junk[2]])
    return rel_url
