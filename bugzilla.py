#!/usr/bin/env python

from os import popen

def findBugText(bugId):
    return popen("bugcli -b " + bugId).read()

def findStatus(description):
    if len(description) == 0:
        return "UNKNOWN"
    for line in description.split("\n"):
        words = line.split()
        if len(words) < 4:
            continue
        if words[2].startswith("Status"):
            return words[3]
    return "NONEXISTENT"

def isResolved(status):
    return status == "RESOLVED" or status == "CLOSED"
