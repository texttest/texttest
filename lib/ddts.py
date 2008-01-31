#!/usr/bin/env python

from os import popen

def findBugText(scriptLocation, bugId):
    return popen("qrsh -l 'carmarch=*sparc*,short' -w e -now n 'dumpbug -n -r " + bugId + "' 2>&1").read()

def findStatus(description):
    nextLine = False
    for line in description.split("\n"):
        words = line.split()
        if nextLine:
            return words[0]
        if len(words) > 0 and words[0] == "Bug":
            nextLine = True
    if description.find("Not a bug") != -1:
        return "NONEXISTENT"
    else:
        return "UNKNOWN"

def isResolved(status):
    return status == "RESOLVED" or status == "VERIFIED"
