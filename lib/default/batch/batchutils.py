import plugins, datetime, time, os

class BatchVersionFilter:
    def __init__(self, batchSession):
        self.batchSession = batchSession

    def verifyVersions(self, app):
        badVersion = self.findUnacceptableVersion(app)
        if badVersion is not None:
            raise plugins.TextTestError, "unregistered version '" + badVersion + "' for " + self.batchSession + " session."

    def findUnacceptableVersion(self, app):
        if app.getCompositeConfigValue("batch_use_version_filtering", self.batchSession) != "true":
            return
        
        allowedVersions = app.getCompositeConfigValue("batch_version", self.batchSession)
        for version in app.versions:
            if len(version) > 0 and version not in allowedVersions and not version.startswith("copy_"):
                return version


def calculateBatchDate():
    # Batch mode uses a standardised date that give a consistent answer for night-jobs.
    # Hence midnight is a bad cutover point. The day therefore starts and ends at 8am :)
    timeToUse = plugins.globalStartTime - datetime.timedelta(hours=8)
    return timeToUse.strftime("%d%b%Y")

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

def convertToUrl(path, fileMapping):
    for filePath, httpPath in fileMapping.items():
        if path.startswith(filePath):
            return path.replace(filePath, httpPath)
    return "file://" + os.path.abspath(path)
