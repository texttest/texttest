
import version_control, plugins, datetime, time, os
from ndict import seqdict


class BzrInterface(version_control.VersionControlInterface):
    def __init__(self):
        warningStates = [ "Modified", "Removed", "Added", "Renamed" ]
        errorStates = [ "Unknown", "Conflicts", "Kind changed" ]
        version_control.VersionControlInterface.__init__(self, "bzr", "Bazaar", warningStates, errorStates, "-1")

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

    def getRevisionOptions(self, r1, r2):
        if r1 and r2:
            return [ "-r", r1 + ".." + r2 ]
        elif r1:
            return [ "-r", r1 ]
        elif r2:
            return [ "-r", r2 ]
        else:
            return []


version_control.VersionControlDialogGUI.vcs = BzrInterface()


from version_control import InteractiveActionConfig
