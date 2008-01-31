#!/usr/bin/env python

import urllib2

def findBugText(scriptLocation, bugId):
    bugzillaRequest = scriptLocation + "?bug=" + bugId
    try:
        reply = urllib2.urlopen(bugzillaRequest).read().split(':jaeger:')
    except Exception, e:
        return "Failed to open URL '" + bugzillaRequest + "': " + str(e) + ".\n\nPlease make sure that the configuration entry 'bug_system_script' points to the correct script to run to extract bugzilla information. The current value is '" + scriptLocation + "'.\n\nNormally, the entry should be the DEFAULT_SERVER + DIRECTORY + CLI_URI set in the beginning of the 'bugcli' script."

    if len(reply) == 1 and reply[0] == "":
        return "Bug " + bugId + "could not be found."

    return "******************************************************\n" + \
           "BugId: " + bugId + "          Assigned: " + reply[6] + "\n" + \
           "Severity: " + reply[5] + "  Status: " + reply[4] + "\n" + \
           "Priority: " + reply[1] + "     Created: " + reply[3] + "\n" + \
           "Component: " + reply[0] + "\n" + \
           "Summary: " + reply[2] + "\n" + \
           "Description:\n" + reply[7] + "\n" + \
           "******************************************************"

def findStatus(description):
    if len(description) == 0:
        return "UNKNOWN"
    if description.startswith("Failed to open URL"):
        return "BAD SCRIPT"
    for line in description.split("\n"):
        words = line.split()
        if len(words) < 4:
            continue
        if words[2].startswith("Status"):
            return words[3]
    return "NONEXISTENT"

def isResolved(status):
    return status == "RESOLVED" or status == "CLOSED"
