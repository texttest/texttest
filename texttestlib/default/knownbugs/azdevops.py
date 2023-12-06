import urllib.request
import base64
import json
import re
import os

def _makeURL(location, bugText):
    return location + "/_workitems/edit/" + bugText

def _getEntry(key, fields, secondaryKey=None, fallback=None):
    entry = fields.get(key)
    if entry and secondaryKey:
        entry = _encodeString(entry[secondaryKey])
    if not entry and fallback:
        entry = fallback

    return key.rsplit(".", 1)[-1] + ": " + _encodeString(entry)

def _parseReply(json_dict, location, bugId):
    count = json_dict["count"]
    if count == 1:
        fields = json_dict["value"][0]["fields"]
    
        ruler = "*" * 50
        message_rows = [ "\n" + ruler,
                         "Id: " + bugId,
                         _getEntry("System.Title", fields),
                         _getEntry("System.State", fields),
                         _getEntry("System.AssignedTo", fields, "displayName", "Unassigned"),
                         _getEntry("System.CreatedBy", fields, "displayName"),
                         _getEntry("System.AreaPath", fields),
                         _getEntry("System.CreatedDate", fields),
                         _getEntry("System.ChangedDate", fields),
                         _getEntry("Microsoft.VSTS.Common.Severity", fields, fallback="N/A"),
                         ruler,
                         "\nView bug " + bugId + " using AZ Devops URL=" \
                         + _makeURL(location, str(bugId)) + "\n"]
    
        status = _encodeString(fields["System.State"])
    
        message = "\n".join(message_rows)
        isResolved = status in [ "Done", "Ready for test", "Testing", "Rejected", "Removed" ]
        return status, message, isResolved, bugId

def findBugInfoWithoutLogin(bugId, location):
    ruler = "*" * 50
    message_rows = [ "\n" + ruler,
                     "Id: " + bugId,
                     "State: PAT not set",
                     ruler,
                     "\nView bug " + bugId + " using AZ Devops URL=" \
                         + _makeURL(location, str(bugId)) + "\n" ]
                     
    return "PAT not set", "\n".join(message_rows), False, bugId

# For python2 this function contains locale related encoding that didn't work
# in python3. Bugs related to encoding is probably related to this.
def _encodeString(value):
    # Get given Windows line endings but Python doesn't use them internally.
    return value.replace("\r", "")

def get_request_context():
    try:
        # Needed in msys2 environment. If we have certifi installed, use it.
        # On Linux appears to work without this
        import certifi, ssl
        return ssl.create_default_context(cafile=certifi.where())
    except ModuleNotFoundError:
        return 

def _getJson(query_url, username, password):
    # Setting up password managers and using openers as described in the
    # documentation for urllib did not work.
    credentials = ('%s:%s' % (username, password))
    encoded_credentials = base64.b64encode(credentials.encode('ascii'))
    request = urllib.request.Request(query_url)
    request.add_header('Authorization', 'Basic %s' % encoded_credentials.decode('ascii'))
    response = urllib.request.urlopen(request, context=get_request_context())
    response_text = response.read()
    return json.loads(response_text.decode())

def _handleHTTPError(http_error, location, rest_url):
    message = ""
    internal_error = False
    if http_error.getcode() == 401:
        message = "Authentication failure for '" + location + "':\n" + \
            str(http_error) + \
            "\nPossibly issues with AZ Devops PAT.\n"
        return message, False
    elif http_error.getcode() == 404:
        try:
            json_dict = json.loads(http_error.read())
            error_key = "message"
            if error_key in json_dict:
                message = "Message from AZ Devops: " + json_dict[error_key]
                internal_error = True
        except:
            message = str(http_error) + \
                ("\nIf 'bug_system_location' is correct and the AZ Devops workitem exists,"
                 " this might indicate that the AZ Devops REST API changed.")
    if not message:
        message = str(http_error)
    return "Failure while accessing '" + rest_url + "': \n" + message + "\n", internal_error


def findBugInfo(bugId, location, username, password):
    fields_to_fetch = ["System.AssignedTo",
                       "System.AreaPath",
                       "System.CreatedDate",
                       "Microsoft.VSTS.Common.Severity",
                       "System.CreatedBy",
                       "System.State",
                       "System.ChangedDate",
                       "System.Title"]
    rest_url = location + "/_apis/wit/workitems?ids=" + bugId + "&api-version=7.1-preview.3&fields=" + ",".join(fields_to_fetch)
    if not password:
        # This variable is set in azure devops pipelines, make use of it
        password = os.getenv("SYSTEM_ACCESSTOKEN")
    if not username and not password:
        # We have no means of logging in, perhaps the user didn't want to. Be nice...
        return findBugInfoWithoutLogin(bugId, location)

    error_label = "AZURE DEVOPS ERROR"
    try:
        json_dict = _getJson(rest_url, username, password)
    except urllib.request.HTTPError as h:
        message, internal_error = _handleHTTPError(h, location, rest_url)
        return error_label, message, internal_error, bugId
    except Exception as e:
        message = "Exception while accessing '" + rest_url + "':\n" + str(e)  + "\n"
        return error_label, message, False, bugId

    try:
        return _parseReply(json_dict, location, bugId)
    except Exception as e:
        message = "Failed to parse reply from '" + rest_url + "':\n" + str(e) + "\n"
        raise
        return "PARSE ERROR", message, False, bugId


# Used by Jenkins plugin
def getBugsFromText(text, location):
    bugRegex = re.compile("[A-Z]{2,}-[0-9]+")
    bugs = []
    for match in bugRegex.finditer(text):
        bugText = match.group(0)
        bugs.append((bugText, _makeURL(location, bugText)))
    return bugs
