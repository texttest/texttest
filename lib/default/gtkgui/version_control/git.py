import plugins, vcs_independent, datetime, time, os

class GitInterface(vcs_independent.VersionControlInterface):
    def __init__(self, controlDir):
        self.warningStateInfo = { "M": "Modified", "D":"Deleted", "A":"Added", "R":"Renamed"}
        self.errorStateInfo = { "??": "Unknown"}
        self.allStateInfo = { "C": "Copied", "U": "Unmerged" } # "!!" for ignored files is only available on git versions < 1.7.4
        self.allStateInfo.update(self.warningStateInfo)
        self.allStateInfo.update(self.errorStateInfo)
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
