import vcs_independent, datetime, time, os
from texttestlib import plugins

class GitInterface(vcs_independent.VersionControlInterface):
    def __init__(self, controlDir):
        self.warningStateInfo = { "M": "Modified", "D":"Deleted", "A":"Added", "R":"Renamed"}
        self.errorStateInfo = { "??": "Unknown"}
        self.allStateInfo = { "C": "Copied", "U": "Unmerged" } # "!!" for ignored files is only available on git versions < 1.7.4
        self.allStateInfo.update(self.warningStateInfo)
        self.allStateInfo.update(self.errorStateInfo)
        self.vcsDirectory = os.path.dirname(controlDir)
        vcs_independent.VersionControlInterface.__init__(self, controlDir, "Git",
                                                         self.warningStateInfo.values(), self.errorStateInfo.values(), "HEAD")
        self.defaultArgs["rm"] = [ "--force", "-r" ]
        self.defaultArgs["status"] = [ "--porcelain" ] # Would like to use --ignored but it is not available on git versions < 1.7.4
        self.defaultArgs["log"] = [ "-p", "--follow" ]

    def getDateFromLog(self, output):
        for line in output.splitlines():
            if line.startswith("Date:"):
                dateStr = " ".join(line.split()[2:-1])
                return datetime.datetime(*(self.parseDateTime(dateStr)[0:6]))

    def getGraphicalDiffArgs(self, diffProgram):
        return [ "git", "difftool", "-t", diffProgram, "-y"]

    def parseDateTime(self, input):
        return time.strptime(input, "%b %d %H:%M:%S %Y")
    
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
        _, stdout,_ = self.getProcessResults(["git", "ls-files", "--other", "-i", "--exclude-standard",  path])
        return stdout.split()

    def makeRelPath(self, arg):
        if os.path.isabs(arg):
            relpath = plugins.relpath(arg, self.vcsDirectory)
            if relpath:
                return relpath
        return arg
        
    def getProcessResults(self, args, cwd=None, **kwargs):
        workingDir = cwd if cwd else self.vcsDirectory
        return vcs_independent.VersionControlInterface.getProcessResults(self, args, cwd=workingDir, **kwargs)
    
    def callProgram(self, cmdName, fileArgs=[], **kwargs):
        return vcs_independent.VersionControlInterface.callProgram(self, cmdName, fileArgs, cwd=self.vcsDirectory, **kwargs)

    def getCombinedRevisionOptions(self, r1, r2):
        return [ r1 + ".." + r2, "--" ]
    
    def removePath(self, path):
        # Git doesn't remove unknown files
        retCode = self.callProgram("rm", [ path ])
        plugins.removePath(path)
        return retCode == 0
    
    def hasLocalCommits(self, vcsDirectory):
        retCode, _, stderr = self.getProcessResults(["git", "push", "-n"], cwd=vcsDirectory)
        return retCode == 0 and stderr.strip() != "Everything up-to-date" 

vcs_independent.vcsClass = GitInterface

class DiffGUI(vcs_independent.DiffGUI):
    def getExtraArgs(self):
        if self.revision1 and self.revision2:
            return vcs_independent.vcs.getCombinedRevisionOptions(self.revision1, self.revision2)
        if self.revision1:
            return [ self.revision1 ]
        elif self.revision2:
            return [ self.revision2 ]
        else:
            return []

class DiffGUIRecursive(DiffGUI):
    recursive = True

class UpdateGUI(vcs_independent.UpdateGUI):
    def getCommandName(self):
        return "pull"
    
    @staticmethod
    def _getTitle():
        return "Pull"

    
class InteractiveActionConfig(vcs_independent.InteractiveActionConfig):
    def diffClasses(self):
        return [ DiffGUI, DiffGUIRecursive ]
    
    def getUpdateClass(self):
        return UpdateGUI
