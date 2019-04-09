
import os
import shutil
import operator
import logging
import time
import datetime
from texttestlib import plugins
from glob import glob
from itertools import groupby

# Trawl around for a suitable dir to reconnect to if we haven't been told one
# A tangle of side-effects: we find the run directory when asked for the extra versions,
# (so we can provide further ones accordingly), find the application directory when asked to check sanity
# (so we can bail if it's not there) and store in self.reconnDir, ready to provide to the ReconnectTest action


class ReconnectConfig:
    runDirCache = {}
    datedVersions = set()

    def __init__(self, optionMap):
        self.fullRecalculate = "reconnfull" in optionMap
        self.diag = logging.getLogger("Reconnection")
        self.reconnectTmpInfo = optionMap.get("reconnect")
        self.reconnDir = None
        self.errorMessage = ""

    def getReconnectAction(self):
        return ReconnectTest(self.reconnDir, self.fullRecalculate)

    def cacheRunDir(self, app, runDir, version=""):
        if version:
            keys = [app.fullName() + "." + version]
        else:
            keys = [app.fullName()] + app.versions
        for i in range(len(keys)):
            subKey = ".".join(keys[:i+1])
            if i == len(keys) - 1 or subKey not in self.runDirCache:
                self.runDirCache[subKey] = runDir
                self.diag.info("Caching " + subKey + " = " + runDir)

    def findRunDir(self, app):
        return self._findRunDir(repr(app))

    def _findRunDir(self, searchKey):
        self.diag.info("Searching for run directory for " + searchKey)
        entry = self.runDirCache.get(searchKey)
        if entry:
            return entry
        parts = searchKey.split(".")
        if len(parts) > 1:
            return self._findRunDir(".".join(parts[:-1]))

    def getExtraVersions(self, app, givenExtras):
        self.diag = logging.getLogger("Reconnection")
        self.diag.info("Finding reconnect 'extra versions' for " + repr(app) +
                       " given tmp info '" + repr(self.reconnectTmpInfo) + "'")
        if self.reconnectTmpInfo and os.path.isdir(self.reconnectTmpInfo):
            # See if this is an explicitly provided run directory
            dirName = os.path.normpath(self.reconnectTmpInfo)
            versionLists = self.getVersionListsTopDir(dirName)
            self.diag.info("Directory has version lists " + repr(versionLists))
            if versionLists is not None:
                return self.getVersionsFromDirs(app, [dirName], givenExtras)

        fetchDir = app.getPreviousWriteDirInfo(self.reconnectTmpInfo)
        if not os.path.isdir(fetchDir):
            if fetchDir == self.reconnectTmpInfo or not self.reconnectTmpInfo:
                self.errorMessage = "Could not find TextTest temporary directory at " + fetchDir
            else:
                self.errorMessage = "Could not find TextTest temporary directory for " + \
                                    self.reconnectTmpInfo + " at " + fetchDir
            return []

        self.diag.info("Looking for run directories under " + fetchDir)
        runDirs = self.getReconnectRunDirs(app, fetchDir)
        self.diag.info("Found run directories " + repr(runDirs))
        if len(runDirs) == 0:
            self.errorMessage = "Could not find any runs matching " + app.description() + " under " + fetchDir
            return []
        else:
            return self.getVersionsFromDirs(app, runDirs, givenExtras)

    def findAppDirUnder(self, app, runDir):
        # Don't pay attention to dated versions here...
        appVersions = frozenset(app.versions).difference(self.datedVersions)
        self.diag.info("Looking for directory with versions "
                       + repr(sorted(appVersions)))
        for f in os.listdir(runDir):
            versionSet = self.getVersionSetSubDir(f, app.name)
            if versionSet == appVersions:
                return os.path.join(runDir, f)

    def getReconnectRunDirs(self, app, fetchDir):
        correctNames = sorted(os.listdir(fetchDir))
        fullPaths = [os.path.join(fetchDir, d) for d in correctNames]
        return [d for d in fullPaths if self.isRunDirectoryFor(app, d)]

    def getFilter(self):
        return ReconnectFilter(self.reconnDir)

    @classmethod
    def all_perms(cls, items):
        # Lifted from a standard recipe
        if len(items) <= 1:
            yield items
        else:
            for perm in cls.all_perms(items[1:]):
                for i in range(len(perm)+1):
                    yield perm[:i] + items[0:1] + perm[i:]

    def versionSuffix(self, parts):
        fullVersion = ".".join(parts)
        if len(fullVersion) == 0:
            return ""
        return "." + fullVersion

    def isRunDirectoryFor(self, app, d):
        for permutation in self.all_perms(app.versions):
            appDirRoot = os.path.join(d, app.name + self.versionSuffix(permutation))
            if os.path.isdir(appDirRoot) or len(glob(appDirRoot + ".*")) > 0:
                return True
        return False

    def getVersionListsTopDir(self, fileName):
        # Show the framework how to find the version list given a file name
        # If it doesn't match, return None
        parts = os.path.basename(fileName).split(".")
        if len(parts) > 2 and parts[0] != "static_gui":
            # drop the run descriptor at the start and the date/time and pid at the end
            versionParts = ".".join(parts[1:-2]).split("++")
            return [part.split(".") for part in versionParts]

    def getVersionListSubDir(self, fileName, stem):
        # Show the framework how to find the version list given a file name
        # If it doesn't match, return None
        parts = fileName.split(".")
        if stem == parts[0]:
            # drop the application at the start
            return parts[1:]

    def getVersionSetSubDir(self, fileName, stem):
        vlist = self.getVersionListSubDir(fileName, stem)
        if vlist is not None:
            return frozenset(vlist)

    def getAllVersionLists(self, app, givenExtras, groupDirs):
        vlists = []
        for groupDir in groupDirs:
            for path in os.listdir(groupDir):
                fullPath = os.path.join(groupDir, path)
                if os.path.isdir(fullPath):
                    vlist = self.getVersionListSubDir(path, app.name)
                    if vlist is None:
                        continue
                    self.diag.info("Found list " + repr(vlist))
                    if givenExtras:
                        vset = frozenset(vlist).difference(givenExtras)
                        vlist = [v for v in vlist if v in vset]
                    if vlist not in vlists:
                        vlists.append(vlist)
        return vlists

    def expandExtraVersions(self, extras):
        expanded = set()
        for extra in extras:
            expanded.add(extra)
            expanded.update(extra.split("."))
        return expanded

    def getVersionsFromDirs(self, app, dirs, givenExtras):
        versions = []
        allGivenExtras = self.expandExtraVersions(givenExtras)
        self.diag.info("Getting extra versions from directories, versions from config = "
                       + repr(sorted(allGivenExtras)))
        appVersions = frozenset(app.versions)
        for versionLists, groupDirIter in groupby(dirs, self.getVersionListsTopDir):
            groupDirs = list(groupDirIter)
            self.diag.info("Considering version lists " + repr(versionLists) + " with dirs " + repr(groupDirs))
            for versionList in self.getAllVersionLists(app, allGivenExtras, groupDirs):
                version = ".".join(versionList)
                self.diag.info("Considering version list " + repr(versionList))
                versionSet = frozenset(versionList)
                if len(appVersions.difference(versionSet)) > 0:
                    continue  # If the given version isn't included, ignore it
                extraVersionSet = versionSet.difference(appVersions)
                # Important to preserve the order of the versions as received
                extraVersionList = [v for v in versionList if v in extraVersionSet]
                extraVersion = ".".join(extraVersionList)
                if len(groupDirs) == 1:
                    if extraVersion:
                        versions.append(extraVersion)
                        self.cacheRunDir(app, groupDirs[0], version)
                    else:
                        self.cacheRunDir(app, groupDirs[0])
                else:
                    datedVersionMap = {}
                    for dir in groupDirs:
                        datedVersionMap[os.path.basename(dir).split(".")[-2]] = dir
                    datedVersions = sorted(list(datedVersionMap.keys()), key=self.dateValue, reverse=True)
                    self.datedVersions.update(datedVersions)
                    self.diag.info("Found candidate dated versions: " + repr(datedVersions))
                    if not extraVersion:  # one of them has to be the main version...
                        mainVersion = datedVersions.pop(0)
                        self.cacheRunDir(app, datedVersionMap.get(mainVersion))
                    for datedVersion in datedVersions:
                        dir = datedVersionMap.get(datedVersion)
                        if extraVersion:
                            versions.append(extraVersion + "." + datedVersion)
                            self.cacheRunDir(app, dir, version + "." + datedVersion)
                        else:
                            versions.append(datedVersion)
                            if version:
                                self.cacheRunDir(app, dir, version + "." + datedVersion)
                            else:
                                self.cacheRunDir(app, dir, datedVersion)
        self.diag.info("Extra versions found as " + repr(versions))
        return versions

    @staticmethod
    def dateValue(version):
        yearlessDatetime = datetime.datetime.strptime(version, "%d%b%H%M%S")
        now = datetime.datetime.now()
        currYearDatetime = yearlessDatetime.replace(year=now.year)
        if currYearDatetime > now:
            return currYearDatetime.replace(year=now.year - 1)
        else:
            return currYearDatetime

    def checkSanity(self, app):
        if self.errorMessage:  # We failed already, basically
            raise plugins.TextTestError(self.errorMessage)

        runDir = self.findRunDir(app)
        if not runDir:
            raise plugins.TextTestWarning("Could not find any runs matching " + app.description())
        self.diag.info("Found run directory " + repr(runDir))
        self.reconnDir = self.findAppDirUnder(app, runDir)
        self.diag.info("Found application directory " + repr(self.reconnDir))
        if not self.reconnDir:
            raise plugins.TextTestWarning("Could not find an application directory matching " + app.description() +
                                          " for the run directory found at " + runDir)
        for datedVersion in self.datedVersions:
            app.addConfigEntry("unsaveable_version", datedVersion)


class ReconnectFilter(plugins.TextFilter):
    def __init__(self, rootDir):
        self.rootDir = rootDir

    def acceptsTestCase(self, test):
        return os.path.exists(os.path.join(self.rootDir, test.getRelPath()))

    def acceptsTestSuite(self, suite):
        return os.path.exists(os.path.join(self.rootDir, suite.getRelPath()))


class ReconnectTest(plugins.Action):
    def __init__(self, rootDirToCopy, fullRecalculate):
        self.rootDirToCopy = rootDirToCopy
        self.fullRecalculate = fullRecalculate
        self.diag = logging.getLogger("Reconnection")

    def __repr__(self):
        return "Reconnecting to"

    def __call__(self, test):
        newState = self.getReconnectState(test)
        self.describe(test, self.getStateText(newState))
        if newState:
            test.changeState(newState)

    def getReconnectState(self, test):
        reconnLocation = os.path.join(self.rootDirToCopy, test.getRelPath())
        self.diag.info("Reconnecting to test at " + reconnLocation)
        if os.path.isdir(reconnLocation):
            return self.getReconnectStateFrom(test, reconnLocation)
        else:
            return plugins.Unrunnable(briefText="no results",
                                      freeText="No file found to load results from under " + reconnLocation)

    def getStateText(self, state):
        if state:
            return " (state " + state.category + ")"
        else:
            return " (recomputing)"

    def getReconnectStateFrom(self, test, location, copyEvenIfLoadFails=True):
        stateToUse = None
        stateFile = os.path.join(location, "framework_tmp", "teststate")
        if os.path.isfile(stateFile):
            newTmpPath = os.path.dirname(self.rootDirToCopy)
            loaded, newState = test.getNewState(open(stateFile, "rb"), updatePaths=True, newTmpPath=newTmpPath)
            self.diag.info("Loaded state file at " + stateFile + " - " + repr(loaded))
            if loaded and self.modifyState(test, newState):  # if we can't read it, recompute it
                stateToUse = newState

        if (copyEvenIfLoadFails or stateToUse) and (self.fullRecalculate or not stateToUse):
            self.copyFiles(test, location)

        return stateToUse

    def copyFiles(self, test, reconnLocation):
        test.makeWriteDirectory()
        tmpDir = test.getDirectory(temporary=1)
        plugins.ensureDirectoryExists(tmpDir)
        self.diag.info("Copying files from " + reconnLocation + " to " + tmpDir)
        for file in os.listdir(reconnLocation):
            fullPath = os.path.join(reconnLocation, file)
            if os.path.isfile(fullPath):
                targetPath = os.path.join(tmpDir, os.path.basename(fullPath))
                try:
                    shutil.copyfile(fullPath, targetPath)
                except EnvironmentError as e:
                    # File could not be copied, may not have been readable
                    # Write the exception to it instead
                    targetFile = open(targetPath, "w")
                    targetFile.write("Failed to copy file - exception info follows :\n" + str(e) + "\n")
                    targetFile.close()

    def modifyState(self, test, newState):
        if self.fullRecalculate:
            # Only pick up errors here, recalculate the rest. Don't notify until
            # we're done with recalculation.
            if newState.hasResults():
                # Also pick up execution machines, we can't get them otherwise...
                test.state.executionHosts = newState.executionHosts
                return False  # don't actually change the state
            else:
                newState.lifecycleChange = ""  # otherwise it's regarded as complete
                return True
        else:
            return True

    def setUpApplication(self, app):
        plugins.log.info("Reconnecting to test results in directory " + self.rootDirToCopy)

    def setUpSuite(self, suite):
        self.describe(suite)
