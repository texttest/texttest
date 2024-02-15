import os
import urllib.parse
from texttestlib.default.batch import jenkinschanges
from pprint import pformat
from texttestlib import plugins

class CIPlatform:

    @staticmethod
    def getInstance(environment=os.environ):
        if environment.get("JENKINS_URL"):
            platform = Jenkins(environment)
        elif environment.get("SYSTEM_TEAMFOUNDATIONSERVERURI"):
            platform = Azure(environment)
        elif environment.get("GITLAB_CI"):
            platform = Gitlab(environment)
        else:
            platform = CIPlatform(environment)
        return platform

    def __init__(self, environment):
        self.environment = environment
        self.currentTag = None

    def _getEnvProperty(self, prop, defaultVal=""):
        return self.environment.get(prop, defaultVal) if self.environment else defaultVal

    """
    Some old Jenkins instances don't always have a build number set as
    an environment variable. This is a way to support backwards compat
    with those jobs, since build number can be fetched from tag name
    """
    def setCurrentTag(self, tag):
        self.currentTag = tag

    def name(self):
        return "Generic platform"

    def hasFullEnvironment(self):
        return not any((self._getEnvProperty(var, None) is None for var in self.getRunFileVars()))

    def supportsEnvironmentComparison(self):
        return False

    def getRunFileVars(self):
        return []

    def getBuildNumber(self):
        return None

    def getCiUrl(self):
        return None

    def getJobName(self):
        return None

    def getJobUrl(self):
        return None

    def getJobTitle(self):
        return None

    def getJobTooltip(self):
        return ""

    def getPrettyJobLink(self):
        return None

    def getBuildNumberFromTag(self, tag):
        return tag.split(".")[-1]

    def findChanges(self, prevTag, tag, pageDir, getConfigValue):
        return []


class Jenkins(CIPlatform):

    def name(self):
        return "Jenkins"

    def supportsEnvironmentComparison(self):
        return True

    def getRunFileVars(self):
        return ["JENKINS_URL", "JOB_NAME", "BUILD_NUMBER"]

    def getBuildNumber(self):
        if self.currentTag:
            return self.getBuildNumberFromTag(self.currentTag)
        return self._getEnvProperty("BUILD_NUMBER")

    def getCiUrl(self):
        return self._getEnvProperty("JENKINS_URL")

    def getJobName(self):
        return self._getEnvProperty("JOB_NAME")

    def getJobUrl(self):
        return os.path.join(self.getCiUrl(), "job", self.getJobName(), self.getBuildNumber())

    def getJobTitle(self):
        return "Jenkins " + self.getBuildNumber()

    def getJobTooltip(self):
        return jenkinschanges.getTimestamp(self.getBuildNumber())

    def getPrettyJobLink(self):
        return f"(built by Jenkins job '{self.getJobName()}', <a href='{self.getJobUrl()}'> build number {self.getBuildNumber()}</a>)"

    def findChanges(self, prevTag, tag, pageDir, getConfigValue):
        cacheDir = os.path.join(os.path.dirname(pageDir), "jenkins_changes")
        buildNumber = self.getBuildNumberFromTag(tag)
        cacheFileOldName = os.path.join(cacheDir, buildNumber)
        cacheFile = os.path.join(cacheDir, tag)
        if os.path.isfile(cacheFileOldName):
            os.rename(cacheFileOldName, cacheFile)
        if os.path.isfile(cacheFile):
            return eval(open(cacheFile).read().strip())
        else:
            bugSystemData = getConfigValue("bug_system_location", allSubKeys=True)
            markedArtefacts = getConfigValue("batch_jenkins_marked_artefacts")
            fileFinder = getConfigValue("batch_jenkins_archive_file_pattern")
            prevBuildNumber = self.getBuildNumberFromTag(prevTag) if prevTag else None
            if buildNumber.isdigit() and prevBuildNumber is not None:
                try:
                    allChanges = jenkinschanges.getChanges(
                        prevBuildNumber, buildNumber, bugSystemData, markedArtefacts, fileFinder, cacheDir)
                    plugins.ensureDirectoryExists(cacheDir)
                    with open(cacheFile, "w") as f:
                        f.write(pformat(allChanges) + "\n")
                    return allChanges
                except jenkinschanges.JobStillRunningException:
                    pass  # don't write to cache in this case
            return []


class Azure(CIPlatform):

    def name(self):
        return "Azure Devops"

    def getRunFileVars(self):
        return ["SYSTEM_TEAMFOUNDATIONSERVERURI", "SYSTEM_TEAMPROJECT", "BUILD_BUILDID", "BUILD_BUILDNUMBER"]

    def getBuildNumber(self):
        if self.currentTag:
            return self.getBuildNumberFromTag(self.currentTag)
        return self._getEnvProperty("BUILD_BUILDNUMBER").split(".")[-1]

    def getCiUrl(self):
        return self._getEnvProperty("SYSTEM_TEAMFOUNDATIONSERVERURI")

    def getJobName(self):
        return self._getEnvProperty("SYSTEM_DEFINITIONNAME")

    def getJobUrl(self):
        project = urllib.parse.quote(self._getEnvProperty("SYSTEM_TEAMPROJECT"))
        return os.path.join(self.getCiUrl(), project, "_build", "results?buildId=" + self._getEnvProperty("BUILD_BUILDID"))

    def getJobTitle(self):
        return "AZ DevOps " + self._getEnvProperty("BUILD_BUILDNUMBER")

    def getPrettyJobLink(self):
        builtBy = "Azure Devops Pipeline"
        fullBuildNo = self._getEnvProperty("BUILD_BUILDNUMBER")
        return f"(built by {builtBy} '{self.getJobName()}', <a href='{self.getJobUrl()}'> build number {fullBuildNo}</a>)"


class Gitlab(CIPlatform):

    def name(self):
        return "Gitlab CI"

    def getRunFileVars(self):
        return ["GITLAB_CI", "CI_JOB_ID", "CI_SERVER_URL", "CI_JOB_NAME", "CI_JOB_URL"]

    def getBuildNumber(self):
        return self._getEnvProperty("CI_JOB_ID")

    def getCiUrl(self):
        return self._getEnvProperty("CI_SERVER_URL")

    def getJobName(self):
        return self._getEnvProperty("CI_JOB_NAME")

    def getJobUrl(self):
        return self._getEnvProperty("CI_JOB_URL")

    def getJobTitle(self):
        return "Gitlab Pipeline #" + self.getBuildNumber()

    def getPrettyJobLink(self):
        return f"(built by Gitlab Pipeline '{self.getJobName()}', <a href='{self.getJobUrl()}'> job #{self.getBuildNumber()}</a>)"
