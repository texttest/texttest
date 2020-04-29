#!/usr/bin/env python3

# Interface to GitHub using the JSON API.

import os
import sys
import ssl
import urllib.request
import json


def findBugInfo(bugId, location, *args):
    if location and location[-1] != '/':
        location += '/'
    request = "%sissues/%s" % (location, bugId)
    try:
        if request.startswith("https") and getattr(sys, 'frozen', False):
            certs = os.path.join(os.path.dirname(sys.executable), "etc", "cacert.pem")
            reply = urllib.request.urlopen(request, context=ssl.create_default_context(cafile=certs))
        else:
            reply = urllib.request.urlopen(request)
        content =  reply.read().decode(reply.headers.get_content_charset())
        info = json.loads(content)
    except Exception as e:
        message = ("Failed to open URL '" + request + "': " + str(e) +
                   ".\n\nPlease make sure that bug " + bugId + " exists\n" +
                   "and that the configuration entry 'bug_system_location' " +
                   "points to the correct GitHub repository.\nThe current value is '" + location +
                   "', it often looks like: 'https://api.github.com/repos/<user>/<repo>/'.")
        return "NONEXISTENT", message, False, bugId
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
