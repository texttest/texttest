
import os, sys
from xml.dom.minidom import parse
from ordereddict import OrderedDict
from difflib import SequenceMatcher
import re

class AbortedException(RuntimeError):
    pass

def fingerprintStrings(document):
    for obj in document.getElementsByTagName("hudson.tasks.Fingerprinter_-FingerprintAction"):
        for entry in obj.getElementsByTagName("string"):
            yield entry.childNodes[0].nodeValue
            
def getFingerprint(jobRoot, jobName, buildName):
    dirName = os.path.join(jobRoot, jobName, "builds", buildName)
    xmlFile = os.path.join(dirName, "build.xml")
    fingerprint = {}
    if not os.path.isfile(xmlFile):
        return fingerprint
    
    document = parse(xmlFile)
    prevString = None
    versionRegex = re.compile("[0-9]+\\.[0-9\\.]*")
    for currString in fingerprintStrings(document):
        if prevString:
            if jobName not in prevString:
                match = versionRegex.search(prevString)
                if match:
                    prevString = prevString.replace(match.group(0), versionRegex.pattern) + "$"
                fingerprint[prevString] = currString
            prevString = None
        else:
            prevString = currString
    if not fingerprint and getResult(document) == "ABORTED":
        raise AbortedException, "Aborted in Jenkins"
    return fingerprint
    
def parseAuthor(author):
    withoutEmail = author.split("<")[0].strip()
    if "." in withoutEmail:
        return " ".join([ part.capitalize() for part in withoutEmail.split(".") ])
    else:
        return withoutEmail.encode("ascii", "xmlcharrefreplace")
    
def addUnique(items, newItems):
    for newItem in newItems:
        if newItem not in items:
            items.append(newItem)
    
def getBugs(msg, bugSystemData):
    bugs = []
    for systemName, location in bugSystemData.items():
        try:
            exec "from default.knownbugs." + systemName + " import getBugsFromText"
            addUnique(bugs, getBugsFromText(msg, location)) #@UndefinedVariable
        except ImportError:
            pass
    return bugs
    
def getProject(artefact, allProjects):
    # Find the project with the longest name whose name is a substring of the artefact name
    currProject = None
    for project in allProjects:
        if project in artefact and (currProject is None or len(project) > len(currProject)):
            currProject = project
    
    if currProject:
        return currProject

    # Find the project with the longest common substring
    currProjectScore = 0
    for project in allProjects:
        matcher = SequenceMatcher(None, project, artefact)
        projectScore = max((block.size for block in matcher.get_matching_blocks()))
        if projectScore > currProjectScore:
            currProject = project
            currProjectScore = projectScore
    return currProject

def getHash(document, artefact):
    found = False
    regex = re.compile(artefact)
    for currString in fingerprintStrings(document):
        if found:
            return currString
        elif regex.match(currString):
            found = True

def getFingerprintDifferences(build1, build2, jobName, jobRoot):
    fingerprint1 = getFingerprint(jobRoot, jobName, build1)
    fingerprint2 = getFingerprint(jobRoot, jobName, build2)
    if not fingerprint1 or not fingerprint2:
        return []
    differences = []
    for artefact, hash2 in fingerprint2.items():
        hash1 = fingerprint1.get(artefact)
        if hash1 != hash2:
            differences.append((artefact, hash1, hash2))
    
    differences.sort()
    return differences


def organiseByProject(jobRoot, differences, markedArtefacts):
    allProjects = sorted(os.listdir(jobRoot))
    projectData = OrderedDict()
    changes = []
    for artefact, oldHash, hash in differences:
        for name, regexp in markedArtefacts.items():
            if re.match(regexp, artefact):
                changes.append((name + " was updated", "", []))
                
        project = getProject(artefact, allProjects)
        if project:
            projectData.setdefault(project, []).append((artefact, oldHash, hash))
        else:
            print "ERROR: Could not find project for artefact", artefact
    
    return changes, projectData

def getResult(document):
    for entry in document.getElementsByTagName("result"):
        return entry.childNodes[0].nodeValue

def hashesEquivalent(hashes, otherHashes):
    return any((hashes[i] == otherHashes[i] for i in range(len(hashes))))

def getProjectChanges(jobRoot, projectData):
    projectChanges = []
    for project, diffs in projectData.items():
        projectDir = os.path.join(jobRoot, project, "builds")
        allBuilds = sorted([ build for build in os.listdir(projectDir) if build.isdigit()], key=lambda b: -int(b))
        oldHashes = [ oldHash for artefact, oldHash, hash in diffs ]
        newHashes = [ hash for artefact, oldHash, hash in diffs ]    
        active = False
        for build in allBuilds:
            xmlFile = os.path.join(projectDir, build, "build.xml")
            if not os.path.isfile(xmlFile):
                continue
    
            document = parse(xmlFile)
            hashes = [ getHash(document, artefact) for artefact, oldHash, hash in diffs ]
            if getResult(document) != "FAILURE":
                if hashesEquivalent(hashes, newHashes):
                    active = True
                elif hashesEquivalent(hashes, oldHashes):
                    break       
            if active and (project, build) not in projectChanges:
                projectChanges.append((project, build))
    return projectChanges

def getChangeData(jobRoot, projectChanges, jenkinsUrl, bugSystemData):
    changes = []
    for project, build in projectChanges:
        xmlFile = os.path.join(jobRoot, project, "builds", build, "changelog.xml")
        if os.path.isfile(xmlFile):
            document = parse(xmlFile)
            authors = []
            bugs = []
            for changeset in document.getElementsByTagName("changeset"):
                author = parseAuthor(changeset.getAttribute("author"))
                if author not in authors:
                    authors.append(author)
                for msgNode in changeset.getElementsByTagName("msg"):
                    msg = msgNode.childNodes[0].nodeValue
                    addUnique(bugs, getBugs(msg, bugSystemData))
            if authors:
                fullUrl = os.path.join(jenkinsUrl, "job", project, build, "changes")
                changes.append((",".join(authors), fullUrl, bugs))
    return changes


def _getChanges(build1, build2, workspace, jenkinsUrl, bugSystemData={}, markedArtefacts={}):
    rootDir, jobName = os.path.split(workspace)
    if jobName == "workspace": # new structure
        jobRoot, jobName = os.path.split(rootDir)
    else:
        jobRoot = os.path.join(os.path.dirname(rootDir), "jobs")
    # Find what artefacts have changed between times build
    try:
        differences = getFingerprintDifferences(build1, build2, jobName, jobRoot)
    except AbortedException, e:
        # If it was aborted, say this
        return [(str(e), "", [])]
    # Organise them by project
    changes, projectData = organiseByProject(jobRoot, differences, markedArtefacts)
    # For each project, find out which builds were affected
    projectChanges = getProjectChanges(jobRoot, projectData)
    # Extract the changeset information from them
    changes += getChangeData(jobRoot, projectChanges, jenkinsUrl, bugSystemData)
    return changes

def getChanges(build1, build2, bugSystemData, markedArtefacts):
    return _getChanges(build1, build2, os.getenv("WORKSPACE"), os.getenv("JENKINS_URL"), bugSystemData, markedArtefacts)
    
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    buildName = sys.argv[1]
    if len(sys.argv) > 2:
        prevBuildName = sys.argv[2]
    else:
        prevBuildName = str(int(buildName) - 1)
    from pprint import pprint
    pprint(_getChanges(prevBuildName, buildName, "/nfs/vm/c14n/build/PWS-x86_64_linux-6.optimize/.jenkins/workspace/cms-product-car-test",  
                     "http://gotburh03p.got.jeppesensystems.com:8080/", {"jira": "https://jira.jeppesensystems.com"}, {"MAVE" : ".*mave-.*"}))
    