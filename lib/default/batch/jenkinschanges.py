
import os, sys
from xml.dom.minidom import parse
from ordereddict import OrderedDict

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
    for currString in fingerprintStrings(document):
        if prevString:
            if jobName not in prevString:
                fingerprint[prevString] = currString
            prevString = None
        else:
            prevString = currString
    return fingerprint
    
def parseAuthor(author):
    withoutEmail = author.split("<")[0].strip()
    if "." in withoutEmail:
        return " ".join([ part.capitalize() for part in withoutEmail.split(".") ])
    else:
        return withoutEmail.encode("ascii", "xmlcharrefreplace")
    
def getBug(msg, bugSystemData):
    for systemName, location in bugSystemData.items():
        try:
            exec "from default.knownbugs." + systemName + " import getBugFromText"
            ret = getBugFromText(msg, location) #@UndefinedVariable
            if ret:
                return ret
        except ImportError:
            pass
    return "", ""
    
def getProject(artefact, allProjects):
    currProject = None
    for project in allProjects:
        if project in artefact and (currProject is None or len(project) > len(currProject)):
            currProject = project
    
    return currProject


def getHash(document, artefact):
    found = False
    for currString in fingerprintStrings(document):
        if found:
            return currString
        elif currString == artefact:
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


def organiseByProject(jobRoot, differences):
    allProjects = sorted(os.listdir(jobRoot))
    projectData = OrderedDict()
    for artefact, oldHash, hash in differences:
        project = getProject(artefact, allProjects)
        if project:
            projectData.setdefault(project, []).append((artefact, oldHash, hash))
    
    return projectData

def buildFailed(document):
    for entry in document.getElementsByTagName("result"):
        result = entry.childNodes[0].nodeValue
        return result == "FAILURE"

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
            if not buildFailed(document):
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
                    bugText, bugURL = getBug(msg, bugSystemData)
                    if bugText and (bugText, bugURL) not in bugs:
                        bugs.append((bugText, bugURL))
            if authors:
                fullUrl = os.path.join(jenkinsUrl, "job", project, build, "changes")
                changes.append((",".join(authors), fullUrl, bugs))
    return changes


def _getChanges(build1, build2, workspace, jenkinsUrl, bugSystemData={}):
    rootDir, jobName = os.path.split(workspace)
    jobRoot = os.path.join(os.path.dirname(rootDir), "jobs")
    # Find what artefacts have changed between times build
    differences = getFingerprintDifferences(build1, build2, jobName, jobRoot)
    # Organise them by project
    projectData = organiseByProject(jobRoot, differences)
    # For each project, find out which builds were affected
    projectChanges = getProjectChanges(jobRoot, projectData)
    # Extract the changeset information from them
    return getChangeData(jobRoot, projectChanges, jenkinsUrl, bugSystemData)

def getChanges(build1, build2, bugSystemData):
    return _getChanges(build1, build2, os.getenv("WORKSPACE"), os.getenv("JENKINS_URL"), bugSystemData)
    
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    buildName = sys.argv[1]
    prevBuildName = str(int(buildName) - 1)
    from pprint import pprint
    pprint(_getChanges(prevBuildName, buildName, "/nfs/vm/c14n/build/PWS-x86_64_linux-6.optimize/.jenkins/workspace/cms-product-car-test",  
                     "http://gotburh03p.got.jeppesensystems.com:8080/", {"jira": "https://jira.jeppesensystems.com"}))
    