import urllib.request
import base64
import json
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

# For python2 this function contains locale related encoding that didn't work
# in python3. Bugs related to encoding is probably related to this.
def _encodeString(value):
    # Get given Windows line endings but Python doesn't use them internally.
    return value.replace("\r", "")

def _getJson(query_url, username, password):
    # Setting up password managers and using openers as described in the
    # documentation for urllib did not work.
    credentials = ('%s:%s' % (username, password))
    encoded_credentials = base64.b64encode(credentials.encode('ascii'))
    request = urllib.request.Request(query_url)
    request.add_header('Authorization', 'Basic %s' % encoded_credentials.decode('ascii'))
    response = urllib.request.urlopen(request)
    response_text = response.read()
    return json.loads(response_text.decode())

def _handleHTTPError(http_error, location, rest_url):
    message = ""
    internal_error = False
    if http_error.getcode() == 401:
        message = "Authentication failure for '" + location + "':\n" + \
            str(http_error) + \
            "\nPossibly issues with Jira user name and/or password.\n"
        return message, False
    elif http_error.getcode() == 404:
        try:
            json_dict = json.loads(http_error.read())
            error_key = "errorMessages"
            if error_key in json_dict:
                message = "Message from Jira: " + " ".join(json_dict[error_key])
                internal_error = True
        except:
            message = str(http_error) + \
                ("\nIf 'bug_system_location' is correct and the Jira issue exists,"
                 " this might indicate that the Jira REST API changed.")
    if not message:
        message = str(http_error)
    return "Failure while accessing '" + rest_url + "': \n" + message + "\n", internal_error


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

    jira_error_label = "JIRA ERROR"
    try:
        json_dict = _getJson(rest_url, username, password)
    except urllib.request.HTTPError as h:
        message, internal_error = _handleHTTPError(h, location, rest_url)
        return jira_error_label, message, internal_error, bugId
    except Exception as e:
        message = "Exception while accessing '" + rest_url + "':\n" + str(e)  + "\n"
        return jira_error_label, message, False, bugId

    try:
        return _parseReply(json_dict, location)
    except Exception as e:
        message = "Failed to parse reply from '" + rest_url + "':\n" + str(e) + "\n"
        return "PARSE ERROR", message, False, bugId


# Used by Jenkins plugin
def getBugsFromText(text, location):
    bugRegex = re.compile("[A-Z]{2,}-[0-9]+")
    bugs = []
    for match in bugRegex.finditer(text):
        bugText = match.group(0)
        bugs.append((bugText, _makeURL(location, bugText)))
    return bugs
