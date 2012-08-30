
import os, sys
from xml.dom.minidom import parse

def getCauses(jobRoot, jobName, buildName):
    xmlFile = os.path.join(jobRoot, jobName, "builds", buildName, "build.xml")
    if not os.path.isfile(xmlFile):
        return []
    document = parse(xmlFile)
    causes = []
    for obj in document.getElementsByTagName("upstreamProject"):
        project = obj.childNodes[0].nodeValue
        while obj.nodeName != "upstreamBuild":
            obj = obj.nextSibling
        build = obj.childNodes[0].nodeValue
        causes.append((project, build))
    return causes
    
def parseAuthor(author):
    withoutEmail = author.split("<")[0].strip()
    if "." in withoutEmail:
        return " ".join([ part.capitalize() for part in withoutEmail.split(".") ])
    else:
        return withoutEmail.encode("ascii", "xmlcharrefreplace")
    
def _getChanges(buildName, workspace, jenkinsUrl):
    rootDir, jobName = os.path.split(workspace)
    jobRoot = os.path.join(os.path.dirname(rootDir), "jobs")
    changes = []
    for project, build in getCauses(jobRoot, jobName, buildName):
        xmlFile = os.path.join(jobRoot, project, "builds", build, "changelog.xml")
        if os.path.isfile(xmlFile):
            document = parse(xmlFile)
            authors = []
            for changeset in document.getElementsByTagName("changeset"):
                author = parseAuthor(changeset.getAttribute("author"))
                if author not in authors:
                    authors.append(author)
            if authors:
                fullUrl = os.path.join(jenkinsUrl, "job", project, build, "changes")
                changes.append((",".join(authors), fullUrl))
    return changes

def getChanges(buildName):
    return _getChanges(buildName, os.getenv("WORKSPACE"), os.getenv("JENKINS_URL"))
    
if __name__ == "__main__":
    print _getChanges(sys.argv[1], "/nfs/vm/c14n/build/PWS-x86_64_linux-6.optimize/.jenkins/workspace/cms-product-car-test",  
                     "http://gotburh03p.got.jeppesensystems.com:8080/")
    