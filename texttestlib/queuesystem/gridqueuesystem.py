
from . import abstractqueuesystem
import os, shutil
from texttestlib import plugins


class QueueSystem(abstractqueuesystem.QueueSystem):
    def __init__(self, app):
        if shutil.which(self.submitProg) is None:
            raise plugins.TextTestError("Cannot submit TextTest tests to grid engine: '" + self.submitProg + "' not installed!")
        self.coreFileLocation = self.getCoreFileLocation(app)

    def fixDisplay(self, env):
        # Must make sure SGE jobs don't get a locally referencing DISPLAY
        display = os.environ.get("DISPLAY")
        if display and (display.startswith(":") or display.startswith("localhost:")):
            env["DISPLAY"] = plugins.gethostname() + ":" + display.split(":", 1)[1]

    def prepareEnvForSubmit(self, slaveEnv):
        self.fixDisplay(slaveEnv)

    def submitSlaveJob(self, cmdArgs, slaveEnv, logDir, *args, **kw):
        # Don't use log dir as working directory, it might not exist yet
        return abstractqueuesystem.QueueSystem.submitSlaveJob(self, cmdArgs, slaveEnv, self.coreFileLocation, *args, **kw)

    def getCoreFileLocation(self, app):
        location = app.getConfigValue("queue_system_core_file_location")
        if not location or not os.path.isdir(location):
            location = os.path.join(os.getenv("TEXTTEST_TMP"), "grid_core_files")
            plugins.ensureDirectoryExists(location)
        return location
