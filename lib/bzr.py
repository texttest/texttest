
import version_control, plugins, datetime, time, os
from ndict import seqdict


class BzrInterface(version_control.VersionControlInterface):
    def __init__(self, controlDir):
        warningStates = [ "Modified", "Removed", "Added", "Renamed" ]
        errorStates = [ "Unknown", "Conflicts", "Kind changed" ]
        version_control.VersionControlInterface.__init__(self, controlDir, "Bazaar", warningStates, errorStates, "-1")
        self.recursiveSettings["add"] = (True, False) # recursive, don't need directories

    def getDateFromLog(self, output):
        for line in output.splitlines():
            if line.startswith("timestamp:"):
                dateStr = " ".join(line.split()[2:4])
                return datetime.datetime(*(self.parseDateTime(dateStr)[0:6]))

    def getGraphicalDiffArgs(self, diffProgram):
        return [ "bzr", "diff", "--using=" + diffProgram ]

    def parseDateTime(self, input):
        return time.strptime(input, "%Y-%m-%d %H:%M:%S")

    def getStateFromStatus(self, output):
        for line in reversed(output.splitlines()):
            if line.endswith(":"):
                return line[:-1].capitalize()
        return "Unchanged"

    def getCombinedRevisionOptions(self, r1, r2):
        return [ "-r", r1 + ".." + r2 ]

    # Hack for bug in Bazaar, which can't handle symbolic links to the branch...
    def getArgsForFile(self, basicArgs, fileName):
        if basicArgs[1] == "add":
            return basicArgs + [ os.path.realpath(fileName) ]
        else:
            return basicArgs + [ fileName ]
        

version_control.VersionControlDialogGUI.vcsClass = BzrInterface

from version_control import InteractiveActionConfig
