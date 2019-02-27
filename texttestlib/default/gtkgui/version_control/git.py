import datetime
import time
import os
from texttestlib import plugins
from . import vcs_independent


DATE_FORMAT = '%Y-%m-%dT%H:%M:%S'


class GitInterface(vcs_independent.VersionControlInterface):
    def __init__(self, controlDir):
        self.warningStateInfo = {"M": "Modified", "D": "Deleted", "A": "Added", "R": "Renamed"}
        self.errorStateInfo = {"??": "Unknown"}
        # "!!" for ignored files is only available on git versions < 1.7.4
        self.allStateInfo = {"C": "Copied", "U": "Unmerged"}
        self.allStateInfo.update(self.warningStateInfo)
        self.allStateInfo.update(self.errorStateInfo)
        self.vcsDirectory = os.path.dirname(controlDir)
        vcs_independent.VersionControlInterface.__init__(self, controlDir, "Git",
                                                         list(self.warningStateInfo.values()), list(self.errorStateInfo.values()), "HEAD")
        self.defaultArgs["rm"] = ["--force", "-r"]
        # Would like to use --ignored but it is not available on git versions < 1.7.4
        self.defaultArgs["status"] = ["--porcelain"]
        self.defaultArgs["log"] = ["-p", "--follow", "--date=format:%s" % DATE_FORMAT]

    def getDateFromLog(self, output):
        for line in output.splitlines():
            if line.startswith("Date:"):
                return datetime.datetime.strptime(line.split()[1], DATE_FORMAT)

    def getGraphicalDiffArgs(self, diffProgram):
        return ["git", "difftool", "-t", diffProgram, "-y"]

    def startGUIProcess(self, cmdArgs, **kw):
        relArgs = list(map(self.makeRelPath, cmdArgs))
        vcs_independent.VersionControlInterface.startGUIProcess(self, relArgs, **kw)

    def getStateFromStatus(self, output):
        words = output.split()
        if len(words) > 0:
            statusLetter = words[0]
            return self.allStateInfo.get(statusLetter, statusLetter)
        else:
            return "Unchanged"

    def getFileNames(self, fileArg, recursive, forStatus=False, **kwargs):
        # Git handles ignored files different. We have to remove all ignored files to avoid doing status on them
        fileNames = vcs_independent.VersionControlInterface.getFileNames(self, fileArg, recursive, **kwargs)
        if not forStatus:
            return fileNames

        ignored = self.getIgnoredFiles(fileArg)
        return [f for f in fileNames if self.makeRelPath(f) not in ignored]

    def getIgnoredFiles(self, path):
        if not os.path.isdir(path):
            return []
        _, stdout, _ = self.getProcessResults(["git", "ls-files", "--other", "-i", "--exclude-standard",  path])
        return stdout.split()

    def makeRelPath(self, arg):
        if os.path.isabs(arg):
            relpath = plugins.relpath(arg, self.vcsDirectory)
            if relpath:
                return relpath
        return arg

    def getProcessResults(self, args, cwd=None, **kwargs):
        workingDir = cwd if cwd else self.vcsDirectory
        if workingDir == self.vcsDirectory:
            args = list(map(self.makeRelPath, args))
        return vcs_independent.VersionControlInterface.getProcessResults(self, args, cwd=workingDir, **kwargs)

    def callProgram(self, cmdName, fileArgs=[], **kwargs):
        if fileArgs:
            fileArgs = list(map(os.path.realpath, fileArgs))
        return vcs_independent.VersionControlInterface.callProgram(self, cmdName, fileArgs, cwd=self.vcsDirectory, **kwargs)

    def getCombinedRevisionOptions(self, r1, r2):
        return [r1 + ".." + r2, "--"]

    def getSingleRevisionOptions(self, r1):
        return [r1]

    def removePath(self, path):
        # Git doesn't remove unknown files
        retCode = self.callProgram("rm", [path])
        plugins.removePath(path)
        return retCode == 0

    def hasLocalCommits(self, vcsDirectory):
        retCode, _, stderr = self.getProcessResults(["git", "push", "-n"], cwd=vcsDirectory)
        return retCode == 0 and stderr.strip() != "Everything up-to-date"


vcs_independent.vcsClass = GitInterface


class FilteredDiffGUI(vcs_independent.FilteredDiffGUI):
    def __init__(self, *args):
        vcs_independent.FilteredDiffGUI.__init__(self, *args)
        self.cmdName = "show"

    def getTmpFileArgs(self, fileName, revision):
        revStr = revision or "master"
        return [revStr + ":" + vcs_independent.vcs.makeRelPath(fileName)]


class FilteredDiffGUIRecursive(FilteredDiffGUI):
    recursive = True


class UpdateGUI(vcs_independent.UpdateGUI):
    def getCommandName(self):
        return "pull"

    @staticmethod
    def _getTitle():
        return "Pull"


class InteractiveActionConfig(vcs_independent.InteractiveActionConfig):
    def diffClasses(self):
        return [vcs_independent.DiffGUI, vcs_independent.DiffGUIRecursive, FilteredDiffGUI, FilteredDiffGUIRecursive]

    def getUpdateClass(self):
        return UpdateGUI
