import datetime
import time
import os
from texttestlib import plugins


class BatchVersionFilter:
    def __init__(self, batchSession):
        self.batchSession = batchSession

    def verifyVersions(self, app):
        badVersion = self.findUnacceptableVersion(app)
        if badVersion is not None:
            raise plugins.TextTestWarning("unregistered version '" + badVersion +
                                          "' for " + self.batchSession + " session.")

    def findUnacceptableVersion(self, app):
        if app.getCompositeConfigValue("batch_use_version_filtering", self.batchSession) != "true":
            return

        allowedVersions = app.getCompositeConfigValue("batch_version", self.batchSession)
        for version in app.versions:
            if len(version) > 0 and version not in allowedVersions and not version.startswith("copy_"):
                return version


def getBatchRunName(optionMap):
    name = optionMap.get("name")
    if name is not None:
        return name

    jenkinsBuildNumber = os.getenv("BUILD_NUMBER")
    timeToUse = plugins.globalStartTime
    if jenkinsBuildNumber is None:
        # If we're not using Jenkins, assume some kind of nightjob set up (mostly for historical reasons)
        # Here we use a standardised date that give a consistent answer for night-jobs.
        # Hence midnight is a bad cutover point. The day therefore starts and ends at 8am :)
        timeToUse -= datetime.timedelta(hours=8)
    name = timeToUse.strftime("%d%b%Y")
    if jenkinsBuildNumber is not None:
        name += "." + jenkinsBuildNumber
    return name


def parseFileName(fileName, diag):
    versionStr = fileName[5:-5]
    components = versionStr.split("_")
    diag.info("Parsing file with components " + repr(components))
    for index, component in enumerate(components[1:]):
        try:
            diag.info("Trying to parse " + component + " as date")
            date = time.strptime(component, "%d%b%Y")
            version = "_".join(components[:index + 1])
            tag = "_".join(components[index + 2:]) or component
            return version, date, tag
        except ValueError:
            pass
    return None, None, None


def getEnvironmentFromRunFiles(runNameDirs, tag):
    env = {}
    for dir in runNameDirs:
        path = os.path.join(dir, tag)
        if os.path.isfile(path):
            with open(path) as f:
                for line in f:
                    if "=" in line:
                        var, val = line.strip().split("=", 1)
                        env[var] = val
    return env


def convertToUrl(path, fileMapping):
    for filePath, httpPath in list(fileMapping.items()):
        if path.startswith(filePath):
            return path.replace(filePath, httpPath)
    return "file://" + os.path.abspath(path)
