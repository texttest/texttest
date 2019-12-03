#!/usr/bin/env python3

# Interface to GitHub using the JSON API.

import urllib.request
import json


def findBugInfo(bugId, location, *args):
    if location and location[-1] != '/':
        location += '/'
    request = "%sissues/%s" % (location, bugId)
    try:
        reply = urllib.request.urlopen(request)
        content =  reply.read().decode(reply.headers.get_content_charset())
    except Exception as e:
        message = "Failed to open URL '" + request + "': " + str(e) + \
                  ".\n\nPlease make sure that bug " + bugId + " exists\n" + \
                  "and that the configuration entry 'bug_system_location' " + \
                  "points to the correct GitHub repository.\nThe current value is '" + location + "'."
        return "NONEXISTENT", message, False, bugId
    info = json.loads(content)
    if len(info) <= 1:
        message = "Could not parse reply from GitHub, maybe incompatible interface."
        return "BAD SCRIPT", message, False, bugId
    bugText = "******************************************************\n" + \
        "Ticket #%s (%s)\n" % (bugId, info['state']) + \
        "%s\n%sticket/%s\n" % (info['title'], location, bugId) + \
        "Reported By: %s Owned by: %s\n" % (info['user']['login'], info['assignee']) + \
        "Updated: %s Milestone: %s\n" % (info['updated_at'], info['milestone']) + \
        "Description:\n" + info['body'] + "\n" + \
        "******************************************************"
    return info['state'], bugText, info['state'] == "closed", bugId


if __name__ == "__main__":  # pragma: no cover - test code
    import sys
    for item in findBugInfo(sys.argv[1], sys.argv[2]):
        print(item)
