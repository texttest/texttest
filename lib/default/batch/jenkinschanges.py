
import os, sys
from xml.dom.minidom import parse

def _getCauses(xmlFile):
    document = parse(xmlFile)
    causes = []
    for obj in document.getElementsByTagName("upstreamProject"):
        project = obj.childNodes[0].nodeValue
        while obj.nodeName != "upstreamBuild":
            obj = obj.nextSibling
        build = obj.childNodes[0].nodeValue
        causes.append((project, build))
    return causes


def getCauses(jobRoot, jobName, buildName):
    dirName = os.path.join(jobRoot, jobName, "builds", buildName)
    xmlFile = os.path.join(dirName, "build.xml")
    if not os.path.isfile(xmlFile):
        return []
    causes = []
    for project, build in _getCauses(xmlFile):
        causes.append((project, build))
        # IF one of our causes follows on from a failed build, check out what caused all the failed builds also, it
        # will have propagated up to us just now.
        continueSearching = True
        while continueSearching:
            prevBuild = str(int(build) - 1)
            prevBuildFile = os.path.join(jobRoot, project, "builds", prevBuild, "build.xml")
            continueSearching = os.path.isfile(prevBuildFile) and "<result>FAILURE" in open(prevBuildFile).read()
            if continueSearching:
                causes += getCauses(jobRoot, project, prevBuild)
                build = prevBuild
    extraFile = os.path.join(dirName, "extracauses.txt")
    if os.path.isfile(extraFile):
        with open(extraFile) as f:
            for line in f:
                project, build = line.strip().split()
                causes.append((project, build))
    return causes
    
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
            ret = getBugFromText(msg, location)
            if ret:
                return ret
        except ImportError:
            pass
    return "", ""
    
def _getChanges(buildName, workspace, jenkinsUrl, bugSystemData={}):
    rootDir, jobName = os.path.split(workspace)
    jobRoot = os.path.join(os.path.dirname(rootDir), "jobs")
    changes = []
    for project, build in getCauses(jobRoot, jobName, buildName):
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
                    if bugText:
                        bugs.append((bugText, bugURL))
            if authors:
                fullUrl = os.path.join(jenkinsUrl, "job", project, build, "changes")
                changes.append((",".join(authors), fullUrl, bugs))
    return changes

def getChanges(buildName, bugSystemData):
    return _getChanges(buildName, os.getenv("WORKSPACE"), os.getenv("JENKINS_URL"), bugSystemData)
    
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    print _getChanges(sys.argv[1], "/nfs/vm/c14n/build/PWS-x86_64_linux-6.optimize/.jenkins/workspace/cms-product-car-test",  
                     "http://gotburh03p.got.jeppesensystems.com:8080/", {"jira": "https://jira.jeppesensystems.com"})
    