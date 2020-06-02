# Older interface to bugzilla version 2.x. Will not work on 3.x and later versions.
# Relies on "bugcli", an open source program that appears to be abandoned, which was
# never officially part of bugzilla, and assumes the "cli.cgi" script is deployed on the bugzilla
# server. Tested on bugzilla 2.16.

import urllib.request

def findBugInfo(bugId, location, *args):
    bugzillaRequest = location + "/cli.cgi?bug=" + bugId
    try:
        reply = urllib.request.urlopen(bugzillaRequest).read().split(':jaeger:')
    except Exception as e:
        message = "Failed to open URL '" + bugzillaRequest + "': " + str(e) + \
                  ".\n\nPlease make sure that the configuration entry 'bug_system_location' " + \
                  "points to the correct script to run to extract bugzilla information. The current value is '" + location + "'."
        return "BAD SCRIPT", message, False, bugId

    if len(reply) == 1 and reply[0] == "":
        message = "Bug " + bugId + " could not be found in the Bugzilla version 2 instance at " + location + "."
        return "NONEXISTENT", message, False, bugId
    elif len(reply) < 8:
        message = "Could not parse reply from Bugzilla's cli.cgi script, maybe incompatible interface (this only works on version 2). Text of reply follows : \n" + \
            reply[0]
        return "BAD SCRIPT", message, False, bugId

    status = reply[4]
    bugText = "******************************************************\n" + \
        "BugId: " + bugId + "          Assigned: " + reply[6] + "\n" + \
        "Severity: " + reply[5] + "  Status: " + status + "\n" + \
        "Priority: " + reply[1] + "     Created: " + reply[3] + "\n" + \
        "Component: " + reply[0] + "\n" + \
        "Summary: " + reply[2] + "\n" + \
        "Description:\n" + reply[7] + "\n" + \
        "******************************************************"
    return status, bugText, status == "RESOLVED" or status == "CLOSED", bugId
