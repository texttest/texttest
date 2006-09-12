#!/usr/bin/env python

from os import popen

def findBugText(bugId):
    return popen("qrsh -l 'carmarch=*sparc*,short' -w e 'dumpbug -n -r " + bugId + "'").read()

def findStatus(description):
    nextLine = False
    for line in description.split("\n"):
        words = line.split()
        if nextLine:
            return words[0]
        if len(words) > 0 and words[0] == "Bug":
            nextLine = True
    return "no such bug"

def isResolved(status):
    return status == "RESOLVED" or status == "VERIFIED"
