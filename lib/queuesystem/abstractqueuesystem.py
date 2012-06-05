
""" Base class for all the queue system implementations """

import subprocess
import plugins

class QueueSystem:
    def submitSlaveJob(self, cmdArgs, slaveEnv, logDir, *args):
        try:
            process = subprocess.Popen(cmdArgs, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       cwd=logDir, env=slaveEnv)
            stdout, stderr = process.communicate()
            errorMessage = self.findErrorMessage(stderr, cmdArgs)
        except OSError:
            errorMessage = self.getFullSubmitError("local machine is not a submit host: running '" + cmdArgs[0] + "' failed.", cmdArgs)
        if errorMessage:
            return None, errorMessage
        else:
            return self.findJobId(stdout), None

    def supportsPolling(self):
        return True

    def findErrorMessage(self, stderr, cmdArgs):
        if len(stderr) > 0:
            basicError = self.findSubmitError(stderr)
            if basicError:
                return self.getFullSubmitError(basicError, cmdArgs)
            
    def getFullSubmitError(self, errorMessage, cmdArgs):
        modname = self.__class__.__module__
        qname = modname.split(".")[-1].upper()
        return "Failed to submit to " + qname + " (" + errorMessage.strip() + ")\n" + \
               "Submission command was '" + self.formatCommand(cmdArgs) + "'\n"

    def addExtraAndCommand(self, args, submissionRules, commandArgs):
        args += submissionRules.getExtraSubmitArgs()
        args.append(self.shellWrap(commandArgs))
        return args

    def formatCommand(self, cmdArgs):
        return " ".join(cmdArgs[:-1]) + " ... "
        
    def getSubmitCmdArgs(self, submissionRules, commandArgs=[]):
        return commandArgs

    def getJobFailureInfo(self, *args):
        return ""

    def shellWrap(self, commandArgs):
        # Must use exec so as not to create extra processes: SGE's qdel isn't very clever when
        # it comes to noticing extra shells
        return "exec $SHELL -c \"exec " + plugins.commandLineString(commandArgs) + "\"" if commandArgs else ""

