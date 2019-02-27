
from . import abstractqueuesystem
import os
from texttestlib import plugins


class QueueSystem(abstractqueuesystem.QueueSystem):
    def __init__(self, app):
        self.coreFileLocation = self.getCoreFileLocation(app)

    def submitSlaveJob(self, cmdArgs, slaveEnv, logDir, *args, **kw):
        # Don't use log dir as working directory, it might not exist yet
        return abstractqueuesystem.QueueSystem.submitSlaveJob(self, cmdArgs, slaveEnv, self.coreFileLocation, *args, **kw)

    def getCoreFileLocation(self, app):
        location = app.getConfigValue("queue_system_core_file_location")
        if not location or not os.path.isdir(location):
            location = os.path.join(os.getenv("TEXTTEST_TMP"), "grid_core_files")
            plugins.ensureDirectoryExists(location)
        return location
