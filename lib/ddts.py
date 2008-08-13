#!/usr/bin/env python

from os import popen

def findStatus(description):
    nextLine = False
    for line in description.split("\n"):
        words = line.split()
        if nextLine:
            return words[0]
        if len(words) > 0 and words[0] == "Bug":
            nextLine = True
    

def isResolved(status):
    return status == "RESOLVED" or status == "VERIFIED"

def findBugInfo(scriptLocation, bugId):
    bugText = popen("qrsh -l 'carmarch=*sparc*,short' -w e -now n 'dumpbug -n -r " + bugId + "' 2>&1").read()
    status = findStatus(bugText)
    if status:
        return status, bugText, isResolved(status)
    if bugText.find("Not a bug") != -1:
        return "NONEXISTENT", "DDTS could not find bug " + bugId, False
    else:
        return "UNKNOWN", "Could not contact DDTS: 'qrsh' said '" + bugText.strip() + "'", False
