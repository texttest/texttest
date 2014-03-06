
import abstractqueuesystem, plugins
import os

class QueueSystem(abstractqueuesystem.QueueSystem):
    def __init__(self, *args):
        plugins.ensureDirectoryExists(self.getCoreFileLocation())

    def submitSlaveJob(self, cmdArgs, slaveEnv, logDir, *args, **kw):
        # Don't use log dir as working directory, it might not exist yet
        return abstractqueuesystem.QueueSystem.submitSlaveJob(self, cmdArgs, slaveEnv, self.getCoreFileLocation(), *args, **kw)

    def getCoreFileLocation(self):
        return os.path.join(os.getenv("TEXTTEST_TMP"), "grid_core_files")
