
import shutil
import datetime
import time
import os
from texttestlib import plugins
from . import vcs_independent


class HgInterface(vcs_independent.VersionControlInterface):
    def __init__(self, controlDir):
        self.warningStateInfo = {"M": "Modified", "R": "Removed", "A": "Added"}
        self.errorStateInfo = {"?": "Unknown", "!": "Missing"}
        self.allStateInfo = {"C": "Unchanged", "I": "Ignored"}
        self.allStateInfo.update(self.warningStateInfo)
        self.allStateInfo.update(self.errorStateInfo)
        vcs_independent.VersionControlInterface.__init__(self, controlDir, "Mercurial",
                                                         list(self.warningStateInfo.values()), list(self.errorStateInfo.values()), "tip")
        self.defaultArgs["rm"] = ["--force"]
        self.defaultArgs["status"] = ["-A"]  # Otherwise we can't tell difference between Unchanged and Ignored
        self.defaultArgs["log"] = ["-f"]  # "follow" renames, which isn't default
        self.defaultArgs["annotate"] = ["-f", "-n"]  # annotate -f doesn't annotate anything...
        self.defaultArgs["diff"] = ["-g"]  # "git format", which apparently is how to make it work with revisions :)
        self.defaultArgs["pull"] = ["-u"]  # Otherwise doesn't actually update the files. We "pretend to be centralised"

    def getDateFromLog(self, output):
        for line in output.splitlines():
            if line.startswith("date:"):
                dateStr = " ".join(line.split()[2:-1])
                return datetime.datetime(*(self.parseDateTime(dateStr)[0:6]))

    def getGraphicalDiffArgs(self, diffProgram):
        return ["hg", "extdiff", "-p", diffProgram]

    def parseDateTime(self, input):
        return time.strptime(input, "%b %d %H:%M:%S %Y")

    def getFileStatus(self, basicArgs, file):
        return vcs_independent.VersionControlInterface.getFileStatus(self, basicArgs, self.correctForLinks(file))

    def correctForLinks(self, file):
        # Mercurial falls over if "file" contains symbolic link references
        # But don't dereference it if it's actually a link
        if os.path.islink(file):
            return file
        else:
            return os.path.realpath(file)

    def callProgramOnFiles(self, cmdName, fileArg, recursive=False, extraArgs=[], **kwargs):
        basicArgs = self.getCmdArgs(cmdName, extraArgs)
        for fileName in self.getFileNamesForCmd(cmdName, fileArg, recursive):
            self.callProgramWithHandler(fileName, basicArgs + [self.correctForLinks(fileName)], **kwargs)

    def getStateFromStatus(self, output):
        words = output.split()
        if len(words) > 0:
            statusLetter = words[0]
            return self.allStateInfo.get(statusLetter, statusLetter)
        else:  # pragma: no cover - robustness fix only. Could be triggered before 'correctForLinks' was introduced
            # We don't really know, but we assume an error message means we probably don't control the file
            return "Unknown"

    def _movePath(self, oldPath, newPath):
        # Moving doesn't work in hg if there are symbolic links in the path to the new location!
        retCode = self.callProgram("mv", [os.path.realpath(oldPath), os.path.realpath(newPath)])
        # And it doesn't take non-versioned files with it, if there are any...
        if retCode == 0 and os.path.isdir(oldPath):
            self.copyPath(oldPath, newPath)
            shutil.rmtree(oldPath)

    def removePath(self, path):
        # Mercurial doesn't remove unknown files, nor does it return non-zero exit codes when it fails
        retValue = os.path.exists(path)
        self.callProgram("rm", [self.correctForLinks(path)])  # returns 0 whatever happens
        plugins.removePath(path)
        return retValue

    def hasLocalCommits(self, vcsDirectory):
        return self.callProgram("out", cwd=vcsDirectory) == 0


class UpdateGUI(vcs_independent.UpdateGUI):
    def getCommandName(self):
        return "pull"

    @staticmethod
    def _getTitle():
        return "Pull/Update"


vcs_independent.vcsClass = HgInterface


class AnnotateGUI(vcs_independent.AnnotateGUI):
    def commandHadError(self, retcode, stderr, *args):
        return len(stderr) > 0  # Mercurial doesn't do return codes in annotate for some reason...


class AnnotateGUIRecursive(AnnotateGUI):
    recursive = True

#
# Configuration for the Interactive Actions
#


class InteractiveActionConfig(vcs_independent.InteractiveActionConfig):
    def annotateClasses(self):
        return [AnnotateGUI, AnnotateGUIRecursive]

    def getUpdateClass(self):
        return UpdateGUI
