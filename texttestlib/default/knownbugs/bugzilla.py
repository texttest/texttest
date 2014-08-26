#!/usr/bin/env python

# Plugin for bugzilla version 3.x that uses the new webservice interface. Tested for version 3.0.4
# but tried to make it a bit future-proof. The older "bugcli" interface is discontinued but there is
# a plugin for it too, see bugzillav2.py. Documentation can be found at e.g.
# http://www.astrogrid.org/bugzilla/docs/html/api/

# The webservice interface is still fairly primitive, there is for example no way to extract the initial
# comment. But at least it's officially part of bugzilla so will hopefully hang around for longer than
# bugcli did, and there are clearly plans to move it forward.

import xmlrpclib

def getEntry(dict, key):
    return dict.get(key, "UNKNOWN")

def filterInternals(internals, alreadyMentioned):
    accepted = []
    boringValues = [ 0, "", "---", "all", "All", "unspecified" ] + alreadyMentioned
    for key, value in internals.items():
        if key.find("accessible") == -1 and value not in boringValues:
            accepted.append((key.replace("_", " ").capitalize(), value))
    accepted.sort()
    return accepted

def isResolved(status):
    return status == "RESOLVED" or status == "CLOSED"

def parseReply(reply, location, id):
    try:
        bugInfo = reply["bugs"][0]
        internals = bugInfo["internals"] # This is marked unstable: we won't rely on its contents containing anything in particular
        bugId = getEntry(bugInfo, "id")
        summary = getEntry(bugInfo, "summary")
        status = getEntry(internals, "bug_status")
        internals = filterInternals(internals, [ bugId, summary, status ])
        ruler = "*" * 30 + "\n"
        message = ruler + "Summary: " + summary + "\nBug Status: " + status + "\n\n" 
        for fieldName, value in internals:
            message += fieldName + ": " + str(value) + "\n"
        message += ruler
        message += "\nView bug " + str(bugId) + " using bugzilla URL=" + location + "/show_bug.cgi?id=" + str(bugId) + "\n"
        return status, message, isResolved(status), id
    except (IndexError, KeyError):
        message = "Could not parse reply from bugzilla's web service, maybe incompatible interface. Text of reply follows : \n" + str(reply)
        return "BAD SCRIPT", message, False, id
    
def findBugInfo(bugId, location, *args):
    scriptLocation = location + "/xmlrpc.cgi"
    proxy = xmlrpclib.ServerProxy(scriptLocation)
    try:
        return parseReply(proxy.Bug.get_bugs({ "ids" : [ bugId ]}), location, bugId)
    except xmlrpclib.Fault, e:
        return "NONEXISTENT", e.faultString, False, bugId
    except Exception, e:
        message = "Failed to communicate with '" + scriptLocation + "': " + str(e) + ".\n\nPlease make sure that the configuration entry 'bug_system_location' points to a correct location of a Bugzilla version 3.x installation. The current value is '" + location + "'."
        return "BAD SCRIPT", message, False, bugId
