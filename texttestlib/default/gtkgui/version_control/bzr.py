
import datetime
import time
import os
from . import vcs_independent


class BzrInterface(vcs_independent.VersionControlInterface):
    def __init__(self, controlDir):
        warningStates = ["Modified", "Removed", "Added", "Renamed"]
        errorStates = ["Unknown", "Conflicts", "Kind changed"]
        vcs_independent.VersionControlInterface.__init__(self, controlDir, "Bazaar", warningStates, errorStates, "-1")
        self.defaultArgs["rm"] = ["--force"]

    def isVersionControlled(self, dirname):
        args = self.getCmdArgs("status") + [dirname]
        returncode, output, err = self.getProcessResults(args)
        # Unless the result is "unknown:" followed by the relpath of the dirname, it's version controlled, at least a bit...
        if returncode and err:
            return False
        lines = output.splitlines()
        if len(lines) != 2:
            return True
        if lines[0].strip() != "unknown:":
            return True
        pathname = os.path.normpath(lines[1].strip())
        return not dirname.endswith(pathname)

    def getDateFromLog(self, output):
        for line in output.splitlines():
            if line.startswith("timestamp:"):
                dateStr = " ".join(line.split()[2:4])
                return datetime.datetime(*(self.parseDateTime(dateStr)[0:6]))

    def getGraphicalDiffArgs(self, diffProgram):
        return ["bzr", "diff", "--using=" + diffProgram]

    def parseDateTime(self, input):
        return time.strptime(input, "%Y-%m-%d %H:%M:%S")

    def getStateFromStatus(self, output):
        for line in reversed(output.splitlines()):
            if line.endswith(":"):
                return line[:-1].capitalize()
        return "Unchanged"

    def getCombinedRevisionOptions(self, r1, r2):
        return ["-r", r1 + ".." + r2]

    def removePath(self, path):
        retCode = self.callProgram("rm", [path])  # Always removes
        return retCode == 0

    # Hack for bug in Bazaar, which can't handle symbolic links to the branch...
    def callProgramOnFiles(self, cmdName, fileArg, recursive=False, extraArgs=[], **kwargs):
        if cmdName == "add":
            basicArgs = self.getCmdArgs(cmdName, extraArgs)
            for fileName in self.getFileNamesForCmd(cmdName, fileArg, recursive):
                self.callProgramWithHandler(fileName, basicArgs + [os.path.realpath(fileName)], **kwargs)
        else:
            vcs_independent.VersionControlInterface.callProgramOnFiles(
                self, cmdName, fileArg, recursive, extraArgs, **kwargs)


vcs_independent.vcsClass = BzrInterface
InteractiveActionConfig = vcs_independent.InteractiveActionConfig
