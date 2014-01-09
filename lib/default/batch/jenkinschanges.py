
import os, sys, re, hashlib, time
from xml.dom.minidom import parse
from ordereddict import OrderedDict
from glob import glob
from pprint import pprint

versionRegex = re.compile("[0-9]+(\\.[0-9]+)+")
        

class AbortedException(RuntimeError):
    pass

class JobStillRunningException(RuntimeError):
    pass

class FingerprintNotReadyException(RuntimeError):
    pass

def fingerprintStrings(document):
    for obj in document.getElementsByTagName("hudson.tasks.Fingerprinter_-FingerprintAction"):
        for entry in obj.getElementsByTagName("string"):
            yield entry.childNodes[0].nodeValue
            
def getCacheFileName(buildName, cacheDir):
    return os.path.join(cacheDir, "correct_hashes_" + buildName)
         
def getDocument(jobRoot, jobName, buildName):
    dirName = os.path.join(jobRoot, jobName, "builds", buildName)
    xmlFile = os.path.join(dirName, "build.xml")
    if os.path.isfile(xmlFile):
        return parse(xmlFile)
    
            
def getFingerprint(jobRoot, jobName, buildName, cacheDir):
    if cacheDir:
        cacheFileName = getCacheFileName(buildName, cacheDir) 
        if os.path.isfile(cacheFileName):
            return eval(open(cacheFileName).read())
    document = getDocument(jobRoot, jobName, buildName)
    fingerprint = {}
    if document is None:
        return fingerprint
    
    prevString = None
    for currString in fingerprintStrings(document):
        if prevString:
            if jobName not in prevString:
                match = versionRegex.search(prevString)
                regex = prevString
                if match:
                    regex = prevString.replace(match.group(0), versionRegex.pattern) + "$"
                fingerprint[regex] = currString, prevString
            prevString = None
        else:
            prevString = currString
    if not fingerprint:
        result = getResult(document)
        if result is None and os.getenv("BUILD_NUMBER") == buildName and os.getenv("JOB_NAME") == jobName:
            if os.getenv("BUILD_ID") == "none": 
                # Needed to prevent Jenkins from killing background jobs running after the job has exited
                # If we have this, we should wait a bit
                raise FingerprintNotReadyException()
            else:
                raise JobStillRunningException()
        # No result means aborted (hard) if we're checking a previous run, otherwise it means we haven't finished yet
        elif result == "ABORTED" or result is None:
            raise AbortedException, "Aborted in Jenkins"
    return fingerprint
    
def parseAuthor(author):
    withoutEmail = author.split("<")[0].strip().split("@")[0]
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
    
def getProjects(artefact, allProjects):
    currProjArtefact = None
    currProjects = []
    for projArtefact, projects in allProjects.items():
        if artefact.startswith(projArtefact) and (currProjArtefact is None or len(projArtefact) > len(currProjArtefact)):
            currProjArtefact = projArtefact
            currProjects = projects
    
    return currProjects

def getHash(document, artefact):
    found = False
    regex = re.compile(artefact)
    for currString in fingerprintStrings(document):
        if found:
            return currString
        elif regex.match(currString):
            found = True
            
def md5sum(filename):
    md5 = hashlib.md5()
    with open(filename,'rb') as f: 
        for chunk in iter(lambda: f.read(128*md5.block_size), b''): 
            md5.update(chunk)
    return md5.hexdigest()

def getCorrectedHash(f, hash, fileFinder):
    filePattern = f.split(":")[-1].replace("-", "?")
    paths = glob(os.path.join(fileFinder, filePattern))
    if len(paths):
        path = paths[0]
        correctHash = md5sum(path)
        if correctHash != hash:
            return correctHash

def getAndWaitForFingerprint(*args):
    for i in range(500):
        try:
            return getFingerprint(*args)
        except FingerprintNotReadyException:
            if i % 10 == 0:
                print "No Jenkins fingerprints available yet, sleeping..."
            time.sleep(1)
                
    print "Giving up waiting for fingerprints."
    raise JobStillRunningException()

def getFingerprintDifferences(build1, build2, jobName, jobRoot, fileFinder, cacheDir):
    fingerprint1 = getFingerprint(jobRoot, jobName, build1, cacheDir)
    fingerprint2 = getAndWaitForFingerprint(jobRoot, jobName, build2, cacheDir)
    if not fingerprint1 or not fingerprint2:
        return []
    differences = []
    updatedHashes = {}
    for artefact, (hash2, file2) in fingerprint2.items():
        hash1 = fingerprint1.get(artefact)
        if isinstance(hash1, tuple):
            hash1 = hash1[0]
        if hash1 != hash2:
            if fileFinder:
                fullFileFinder = os.path.join(jobRoot, jobName, "builds", build2, fileFinder)
                correctedHash = getCorrectedHash(file2, hash2, fullFileFinder)
                if correctedHash:
                    hash2 = correctedHash
                    updatedHashes[artefact] = hash2
                if hash1 == hash2:
                    continue
            differences.append((artefact, hash1, hash2))
    
    if updatedHashes:
        print "WARNING: incorrect hashes found!"
        print "This is probably due to fingerprint data being wrongly updated from artefacts produced during the build"
        print "Storing a cached file of corrected versions. The following were changed:"
        for artefact, hash in updatedHashes.items():
            print artefact, fingerprint2.get(artefact)[0], hash
            
        for artefact, (hash2, file2) in fingerprint2.items():
            if artefact not in updatedHashes:
                updatedHashes[artefact] = hash2
        with open(getCacheFileName(build2, cacheDir), "w") as f:
            pprint(updatedHashes, f) 
    
    differences.sort()
    return differences

def organiseByProject(differences, markedArtefacts, artefactProjectData):
    projectData = OrderedDict()
    changes = []
    for artefact, oldHash, hash in differences:
        projects = getProjects(artefact, artefactProjectData)
        if projects:
            for project, scopeProvided in projects:
                projectData.setdefault(project, []).append((artefact, oldHash, hash, scopeProvided))
                if project in markedArtefacts:
                    changes.append((artefact, project))
        else:
            projectName = artefact.split(":")[-1].split("[")[0][:-1]
            if projectName in markedArtefacts:
                changes.append((artefact, projectName))
    
    return changes, projectData

def getResult(document):
    for entry in document.getElementsByTagName("result"):
        return entry.childNodes[0].nodeValue

def hashesEquivalent(hashes, otherHashes):
    return any((hashes[i] == otherHashes[i] for i in range(len(hashes))))

def getProjectChanges(jobRoot, projectData):
    projectChanges = []
    recursiveChanges = []
    for project, diffs in projectData.items():
        projectDir = os.path.join(jobRoot, project, "builds")
        allBuilds = sorted([ build for build in os.listdir(projectDir) if build.isdigit()], key=lambda b: -int(b))
        oldHashes = [ oldHash for artefact, oldHash, hash, _ in diffs ]
        newHashes = [ hash for artefact, oldHash, hash, _ in diffs ]
        scopeProvided = any((s for _, _, _, s in diffs))  
        activeBuild = None
        for build in allBuilds:
            xmlFile = os.path.join(projectDir, build, "build.xml")
            if not os.path.isfile(xmlFile):
                continue
    
            document = parse(xmlFile)
            hashes = [ getHash(document, artefact) for artefact, oldHash, hash, _ in diffs ]
            if getResult(document) != "FAILURE":
                if hashesEquivalent(hashes, newHashes):
                    activeBuild = build
                elif hashesEquivalent(hashes, oldHashes):
                    if scopeProvided and activeBuild:
                        recursiveChanges.append((project, build, activeBuild))
                    break       
            if activeBuild and (project, build) not in projectChanges:
                projectChanges.append((project, build))
    return projectChanges, recursiveChanges

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

def getPomData(pomFile):
    document = parse(pomFile)
    artifactId, groupId = None, None
    modules = []
    for node in document.documentElement.childNodes:
        if artifactId is None and node.nodeName == "artifactId":
            artifactId = node.childNodes[0].nodeValue
        elif groupId is None and node.nodeName == "groupId":
            groupId = node.childNodes[0].nodeValue
        elif node.nodeName == "modules":
            for subNode in node.childNodes:
                if subNode.childNodes:
                    modules.append(subNode.childNodes[0].nodeValue)
    providedScope = any((node.childNodes[0].nodeValue == "provided" for node in document.getElementsByTagName("scope")))
    groupPrefix = groupId + ":" if groupId else ""
    return groupPrefix + artifactId, providedScope, modules

def getArtefactsFromPomFiles(workspaceDir):
    pomFile = os.path.join(workspaceDir, "pom.xml")
    if not os.path.isfile(pomFile):
        return []
        
    artefactName, providedScope, modules = getPomData(pomFile)
    artefacts = [(artefactName, providedScope)]
    for module in modules:
        moduleDir = os.path.join(workspaceDir, module)
        artefacts += getArtefactsFromPomFiles(moduleDir)
    return artefacts

def getProjectData(jobRoot):
    projectData = {}
    workspaceRoot = os.path.dirname(os.getenv("WORKSPACE"))
    for jobName in os.listdir(workspaceRoot):
        jobDir = os.path.join(jobRoot, jobName)
        if os.path.isdir(jobDir):
            workspaceDir = os.path.join(workspaceRoot, jobName)
            for artefactName, providedScope in getArtefactsFromPomFiles(workspaceDir):
                projectData.setdefault(artefactName, []).append((jobName, providedScope))
    return projectData


def getArtefactVersion(artefactRegex, build, jobName, jobRoot):
    document = getDocument(jobRoot, jobName, build)
    if document is None:
        return
    
    for currString in fingerprintStrings(document):
        if artefactRegex.match(currString):
            versionMatch = versionRegex.search(currString)
            if versionMatch:
                return versionMatch.group(0)


def getMarkChangeText(artefact, projectName, build1, build2, jobName, jobRoot):
    regex = re.compile(artefact)
    version1 = getArtefactVersion(regex, build1, jobName, jobRoot)
    version2 = getArtefactVersion(regex, build2, jobName, jobRoot)
    if version1 == version2:
        return projectName + " was updated", "", []
    else:
        return projectName + " " + version2, "", []

def getChangesRecursively(build1, build2, jobName, jobRoot, projectData, markedArtefacts=[], fileFinder="", cacheDir=None):
    # Find what artefacts have changed between times build
    differences = getFingerprintDifferences(build1, build2, jobName, jobRoot, fileFinder, cacheDir)
    # Organise them by project
    markedChanges, differencesByProject = organiseByProject(differences, markedArtefacts, projectData)
    # For each project, find out which builds were affected
    projectChanges, recursiveChanges = getProjectChanges(jobRoot, differencesByProject)
    for subProj, subBuild1, subBuild2 in recursiveChanges:
        if subProj != jobName:
            subMarkedChanges, subProjectChanges = getChangesRecursively(subBuild1, subBuild2, subProj, jobRoot, projectData)
            markedChanges += subMarkedChanges
            for subProjectChange in subProjectChanges:
                if subProjectChange not in projectChanges:
                    projectChanges.append(subProjectChange)
    return markedChanges, projectChanges
    
def _getChanges(build1, build2, jobName, jenkinsUrl, bugSystemData={}, markedArtefacts={}, fileFinder="", cacheDir=None):
    jobRoot = os.path.join(os.getenv("JENKINS_HOME"), "jobs")
    projectData = getProjectData(jobRoot)
    try:
        markedChanges, projectChanges = getChangesRecursively(build1, build2, jobName, jobRoot, projectData, markedArtefacts, fileFinder, cacheDir)
    except AbortedException, e:
        # If it was aborted, say this
        return [(str(e), "", [])]
    
    # Extract the changeset information from them
    changesFromProjects = getChangeData(jobRoot, projectChanges, jenkinsUrl, bugSystemData)
    changesFromMarking = [ getMarkChangeText(artefact, projectName, build1, build2, jobName, jobRoot) for artefact, projectName in markedChanges ]
    return changesFromMarking + changesFromProjects

def getChanges(build1, build2, *args):
    return _getChanges(build1, build2, os.getenv("JOB_NAME"), os.getenv("JENKINS_URL"), *args)
    
def getTimestamp(build):
    if hasattr(os, "readlink"):
        buildLink = os.path.join(os.getenv("JENKINS_HOME"), "jobs", os.getenv("JOB_NAME"), "builds", build)
        if os.path.exists(buildLink):
            return os.readlink(buildLink)
    
def parseEnvAsList(varName):
    if varName in os.environ:
        return os.getenv(varName).split(",")
    else:
        return []
        
def parseEnvAsDict(varName):
    ret = {}
    for pairText in parseEnvAsList(varName):
        var, value = pairText.split("=")
        ret[var] = value
    return ret
    
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    buildName = sys.argv[1]
    if len(sys.argv) > 2:
        prevBuildName = sys.argv[2]
    else:
        prevBuildName = str(int(buildName) - 1)
    pprint(getChanges(prevBuildName, buildName, parseEnvAsDict("BUG_SYSTEM_DATA"), parseEnvAsList("MARKED_ARTEFACTS"), 
                      os.getenv("FILE_FINDER", ""), os.getcwd()))
    