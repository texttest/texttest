#!/usr/bin/env python

# Plugin for Jira as per the instructions at http://confluence.atlassian.com/pages/viewpage.action?pageId=9623

# Sample returned value from getIssue

"""
{'affectsVersions': [],
 'assignee': 'geoff',
 'components': [{'name': 'The Component Name', 'id': '10551'}],
 'created': '2009-04-20 16:31:08.0',
 'customFieldValues': [],
 'description': 'A long string \nwith lots of linebreaks\n',
 'fixVersions': [],
 'id': '22693',
 'key': 'JIR-470',
 'priority': '3',
 'project': 'JIR',
 'reporter': 'geoff',
 'status': '1',
 'summary': 'Sample issue',
 'type': '4',
 'updated': '2009-09-25 13:16:21.0',
 'votes': '0'}
"""

import xmlrpc.client
import re
import urllib.request
import urllib.parse
import urllib.error
from collections import OrderedDict


def convertToString(value):
    if type(value) in (str, bytes):
        if type(value) == str:
            value = value.replace("\r", "")  # Get given Windows line endings but Python doesn't use them internally
        return value
    else:
        return ", ".join(map(convertDictToString, value))


def convertDictToString(dict):
    if "name" in dict:
        return dict["name"]
    elif "values" in dict:
        return dict["values"]
    else:
        return "No value defined"


def transfer(oldDict, newDict, key, postfix=""):
    if key in oldDict:
        newDict[key] = convertToString(oldDict[key]) + postfix


def findId(info, currId):
    for item in info:
        if item["id"] == currId:
            return item["name"]


def isInteresting(value):
    return value and value != "0"


def filterReply(bugInfo, statuses, resolutions):
    ignoreFields = ["id", "type", "description", "project"]
    newBugInfo = OrderedDict()
    transfer(bugInfo, newBugInfo, "key")
    transfer(bugInfo, newBugInfo, "summary")
    newBugInfo["status"] = findId(statuses, bugInfo["status"])
    if "resolution" in bugInfo:
        newBugInfo["resolution"] = findId(resolutions, bugInfo["resolution"]) + "\n"
    else:
        transfer(bugInfo, newBugInfo, "assignee", "\n")
    newBugInfo["components"] = convertToString(bugInfo["components"])
    priorityStr = convertToString(bugInfo["priority"])
    priorityStr = str(int(priorityStr) - 1) if priorityStr.isdigit() else priorityStr
    remainder = [k for k in list(bugInfo.keys()) if k not in ignoreFields and (
        k not in newBugInfo or k == "priority") and isInteresting(bugInfo[k])]
    remainder.sort()
    for key in remainder:
        if key == "priority":
            newBugInfo["priority"] = str(priorityStr)
        else:
            transfer(bugInfo, newBugInfo, key)
    return newBugInfo


def makeURL(location, bugText):
    return location + "/browse/" + bugText


def parseReply(bugInfo, statuses, resolutions, location, id):
    try:
        newBugInfo = filterReply(bugInfo, statuses, resolutions)
        ruler = "*" * 50 + "\n"
        message = ruler
        for fieldName, value in list(newBugInfo.items()):
            message += fieldName.capitalize() + ": " + str(value) + "\n"
        message += ruler + "\n"
        bugId = newBugInfo['key']
        message += "View bug " + bugId + " using Jira URL=" + makeURL(location, str(bugId)) + "\n\n"
        message += convertToString(bugInfo.get("description", ""))
        isResolved = "resolution" in newBugInfo
        statusText = newBugInfo["resolution"].strip() if isResolved else newBugInfo['status']
        return statusText, message, isResolved, id
    except (IndexError, KeyError):
        message = "Could not parse reply from Jira's web service, maybe incompatible interface. Text of reply follows : \n" + \
            str(bugInfo)
        return "BAD SCRIPT", message, False, id


def findBugInfo(bugId, location, username, password):
    scriptLocation = location + "/rpc/xmlrpc"
    proxy = xmlrpc.client.ServerProxy(scriptLocation)
    try:
        auth = proxy.jira1.login(username, password)
    except xmlrpc.client.Fault as e:
        return "LOGIN FAILED", e.faultString, False, bugId
    except Exception as e:
        message = "Failed to log in to '" + scriptLocation + "': " + \
            str(e) + ".\n\nPlease make sure that the configuration entry 'bug_system_location' points to a correct location of a Jira version 3.x installation. The current value is '" + location + "'."
        return "BAD SCRIPT", message, False, bugId

    try:
        bugInfo = proxy.jira1.getIssue(auth, bugId)
        statuses = proxy.jira1.getStatuses(auth)
        if "resolution" in bugInfo:
            resolutions = proxy.jira1.getResolutions(auth)
        else:
            resolutions = []
        return parseReply(bugInfo, statuses, resolutions, location, bugId)
    except xmlrpc.client.Fault as e:
        renamedBug = getRenamedBug(bugId, location)
        if renamedBug:
            return findBugInfo(renamedBug, location, username, password)
        else:
            return "NONEXISTENT", e.faultString, True, bugId
    except Exception as e:
        message = "Failed to fetch data from '" + scriptLocation + "': " + str(e)
        return "BAD SCRIPT", message, False, bugId


def getRenamedBug(bugId, location):
    try:
        url = urllib.request.urlopen(makeURL(location, bugId))
    except IOError:
        return None
    bugs = getBugsFromText(urllib.request.url2pathname(url.geturl()), "")
    if len(bugs) == 1:
        renamed, _ = bugs[0]
        if renamed != bugId:
            return renamed

# Used by Jenkins plugin


def getBugsFromText(text, location):
    bugRegex = re.compile("[A-Z]{2,}-[0-9]+")
    bugs = []
    for match in bugRegex.finditer(text):
        bugText = match.group(0)
        bugs.append((bugText, makeURL(location, bugText)))
    return bugs
