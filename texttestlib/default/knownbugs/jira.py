#!/usr/bin/env python2

import requests
import re

def _makeURL(location, bugText):
    return location + "/browse/" + bugText

def _getEntry(key, fields, secondaryKey="name", secondaryEntryList=False):
    entry = fields[key]
    if secondaryEntryList:
        result = []
        for item in entry:
            result.append(item[secondaryKey])
        if not result:
            entry = "N/A"
        else:
            entry = ", ".join(map(_encodeString, result))
    elif secondaryKey:
        entry = _encodeString(entry[secondaryKey])

    return key.capitalize() + ": " + _encodeString(entry)

def _parseReply(json_dict, location):
    bugId = _encodeString(json_dict["key"])
    fields = json_dict["fields"]

    ruler = "*" * 50
    message_rows = [ "\n" + ruler,
                     bugId,
                     _getEntry("summary", fields, None),
                     _getEntry("status", fields),
                     _getEntry("assignee", fields),
                     _getEntry("reporter", fields),
                     _getEntry(key="components",
                               fields=fields,
                               secondaryEntryList=True),
                     _getEntry("created", fields, None),
                     _getEntry("updated", fields, None),
                     _getEntry("priority", fields),
                     ruler,
                     "\nView bug " + bugId + " using Jira URL=" \
                     + _makeURL(location, str(bugId)) + "\n",
                     _encodeString(fields["description"]) + "\n"]

    status = _encodeString(fields["status"]["name"])

    message = "\n".join(message_rows)
    isResolved = fields["resolution"]
    return status, message, isResolved, bugId

def _interpretRequestError(exception_message):
    error_template = "40{0} Client Error"
    if error_template.format("1") in exception_message:
        return "Unauthorized action, possibly issues with user name and/or password."
    if error_template.format("4") in exception_message:
        return ("Something is wrong in the address. If 'bug_system_location' is"
                " correct, this might indicate that the jira REST api changed.")
    return ""

def _encodeString(value):
    # Get given Windows line endings but Python doesn't use them internally
    ret = value.replace("\r", "")
    if type(ret) == unicode:
        import locale
        encoding = locale.getdefaultlocale()[1] or "utf-8"
        result = ret.encode(encoding, "replace")
        return result
    else:
        return ret

def findBugInfo(bugId, location, username, password):
    fields_to_fetch = ["assignee",
                       "components",
                       "created",
                       "description",
                       "priority",
                       "reporter",
                       "resolution",
                       "status",
                       "updated",
                       "summary"]
    rest_url = location + "/rest/api/2/issue/" + bugId \
        + "?fields=" + ",".join(fields_to_fetch)

    try:
        response = requests.get(rest_url, auth=(username, password))
        response.raise_for_status()
    except Exception, e:
        exception_message = str(e)
        internal_error = False
        try:
            json_dict = response.json()
            error_key = "errorMessages"
            if error_key in json_dict:
                exception_message += " " + " ".join(json_dict[error_key])
                internal_error = True
        except:
            exception_message += "\n" + _interpretRequestError(exception_message)

        message = "Failed to access '" + rest_url + "': " + exception_message  + "\n"
        return "JIRA ERROR", message, internal_error, bugId

    try:
        return _parseReply(response.json(), location)
    except Exception, e:
        message = "Failed to parse reply from '" + rest_url + "': " + str(e) + "\n"
        return "PARSE ERROR", message, False, bugId


# Used by Jenkins plugin
def getBugsFromText(text, location):
    bugRegex = re.compile("[A-Z]{2,}-[0-9]+")
    bugs = []
    for match in bugRegex.finditer(text):
        bugText = match.group(0)
        bugs.append((bugText, _makeURL(location, bugText)))
    return bugs
