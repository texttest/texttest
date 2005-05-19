#!/usr/local/bin/python

helpDescription = """
The Carmen configuration is based on the LSF configuration. Its default operation is therefore to
submit all jobs to LSF, rather than run them locally.

Execution architectures are now determined by versions, not by which architecture TextTest is run on as before.
If any version is specified which is the name of a Carmen architecture, that architecture will be used.
Otherwise the entry "default_architecture" is read from the config file and used. "supported_architecture" is now
deprecated.

It determines the queue as follows: if a test takes less than 10 minutes, it will be submitted
to short_<arch>, where <arch> is the architecture as determined above. If it takes
more than 2 hours, it will go to idle_<arch>. If neither of these, or if the specified queue
does not exist, it will be submitted to the queue <arch>. If however the environment LSF_QUEUE_PREFIX is set
then that <prefix>_<arch> will be used if arch is i386_linux or sparc.
"""

helpOptions = """
-lprof     - Run LProf on the test concerned. This will automatically profile the job and generate the textual
             data in the test directory, in a file called lprof.<app>. It is proposed to automatically generate
             the graphical information also
"""

batchInfo = """
             Note that, because the Carmen configuration converts infers architectures from versions, you can also
             enable and disable architectures using <bname>_version.

             The Carmen nightjob will run TextTest on all versions and on all architectures. It will do so with the batch
             session name "nightjob" on Monday to Thursday nights, and "wkendjob" on Friday night.
             If you do not want this, you should therefore restrict or disable these session names in your config file, as
             indicated above.

             Note also that the "nightjob" sessions are killed at 8am each morning, while the "wkendjob" sessions are killed
             at 8am on Monday morning. This can cause some tests to be reported as "unfinished" in your batch report."""

import queuesystem, default, performance, os, string, shutil, plugins, respond, predict, time
from ndict import seqdict

def getConfig(optionMap):
    return CarmenConfig(optionMap)

architectures = [ "i386_linux", "sparc", "sparc_64", "powerpc", "parisc_2_0", "parisc_1_1", "i386_solaris", "ia64_hpux" ]
majorReleases = [ "8", "9", "10", "11" ]

def getArchitecture(app):
    for version in app.versions:
        if version in architectures:
            return version
    return app.getConfigValue("default_architecture")

def getMajorReleaseId(app):
    for version in app.versions:
        if version in majorReleases:
            return "carmen_" + version
    return "master"

class CarmenSubmissionRules(queuesystem.SubmissionRules):
    # Return "short", "medium" or "long"
    def getPerformanceCategory(self):
        # RAVE compilations
        if self.nonTestProcess:
            return "short"
        # Hard-coded, useful at boundaries
        if not self.nonTestProcess and os.environ.has_key("QUEUE_SYSTEM_PERF_CATEGORY"):
            return os.environ["QUEUE_SYSTEM_PERF_CATEGORY"]
        cpuTime = performance.getTestPerformance(self.test)
        if cpuTime < self.test.getConfigValue("maximum_cputime_for_short_queue"):
            return "short"
        elif cpuTime > 120:
            return "long"
        else:
            return "medium"

class SgeSubmissionRules(CarmenSubmissionRules):
    def findQueue(self):
        # Carmen's queues are all 'hidden', requesting them directly is not allowed.
        # They must be requested by their 'queue resources', that have the same names...
        return ""
    def findQueueResource(self):
        requestedQueue = CarmenSubmissionRules.findQueue(self)
        if requestedQueue:
            return requestedQueue
        category = self.getPerformanceCategory()
        if category == "short":
            return "short"
        elif category == "medium":
            return "normal"
        else:
            return "idle"
    def findConcreteResources(self):
        # architecture resources
        resources = CarmenSubmissionRules.findResourceList(self)
        arch = getArchitecture(self.test.app)
        resources.append("carmarch=\"*" + arch + "*\"")
        return resources
    def findResourceList(self):
        return self.findConcreteResources() + [ self.findQueueResource() ]
    def getSubmitSuffix(self, name):
        resourceList = self.findConcreteResources()
        return name + " queue " + self.findQueueResource() + ", requesting " + string.join(self.findConcreteResources(), ",")

class LsfSubmissionRules(CarmenSubmissionRules):
    def findDefaultQueue(self):
        arch = getArchitecture(self.test.app)
        if arch == "i386_linux" and not self.nonTestProcess:
            cpuTime = performance.getTestPerformance(self.test)
            chunkLimit = float(self.test.app.getConfigValue("maximum_cputime_for_chunking"))
            if cpuTime > 0 and cpuTime < chunkLimit:
                return "short_rd_testing_chunked"
        return self.getQueuePerformancePrefix(arch) + self.getArchQueueName(arch) +\
               self.getQueuePlatformSuffix(arch)
    def getArchQueueName(self, arch):
        if arch == "sparc_64":
            return "sparc"
        else:
            return arch
    def getQueuePerformancePrefix(self, arch):
        category = self.getPerformanceCategory()
        if category == "short":
            return "short_"
        elif category == "medium" or (arch == "powerpc" or arch == "parisc_2_0"):
            return ""
        else:
            return "idle_"
    def getQueuePlatformSuffix(self, arch):
        if arch == "i386_linux":
            return "_RHEL"
        elif arch == "sparc" or arch == "sparc_64":
            return "_sol8"
        elif arch == "powerpc":
            return "_aix5"
        return ""


class CarmenConfig(queuesystem.QueueSystemConfig):
    def addToOptionGroups(self, app, groups):
        queuesystem.QueueSystemConfig.addToOptionGroups(self, app, groups)
        for group in groups:
            if group.name.startswith("How"):
                group.addSwitch("lprof", "Run with LProf profiler")
    def getTestRunner(self):
        baseRunner = queuesystem.QueueSystemConfig.getTestRunner(self)
        if self.optionMap.has_key("lprof"):
            return RunLprof(baseRunner, self.isExecutable)
        else:
            return baseRunner
    def isExecutable(self, process, parentProcess, test):
        binaryName = os.path.basename(test.getConfigValue("binary"))
        return binaryName.startswith(parentProcess) and process.find(".") == -1 and process.find("arch") == -1 and process.find("crsutil") == -1 and process.find("CMD") == -1
    def getTestCollator(self):
        if self.optionMap.has_key("lprof"):
            return [ self.getFileCollator(), ProcessProfilerResults() ]
        else:
            return self.getFileCollator()
    def getFileCollator(self):
        return queuesystem.QueueSystemConfig.getTestCollator(self)
    def getSubmissionRules(self, test, nonTestProcess):
        if queuesystem.queueSystemName(test.app) == "LSF":
            return LsfSubmissionRules(self.optionMap, test, nonTestProcess)
        else:
            return SgeSubmissionRules(self.optionMap, test, nonTestProcess)
    def isNightJob(self):
        batchSession = self.optionValue("b")
        return batchSession == "nightjob" or batchSession == "wkendjob"
    def printHelpOptions(self, builtInOptions):
        print queuesystem.helpOptions + batchInfo
        default.Config.printHelpOptions(self, builtInOptions)
        print "(Carmen-specific options...)"
        print helpOptions
    def printHelpDescription(self):
        print helpDescription, queuesystem.queueGeneral, predict.helpDescription, performance.helpDescription, respond.helpDescription
    def setApplicationDefaults(self, app):
        queuesystem.QueueSystemConfig.setApplicationDefaults(self, app)
        app.setConfigDefault("default_architecture", "i386_linux")
        app.setConfigDefault("maximum_cputime_for_short_queue", 10)
        app.setConfigDefault("maximum_cputime_for_chunking", 0.0)
    def defaultLoginShell(self):
        # All of carmen's login stuff is done in tcsh starter scripts...
        return "/bin/tcsh"
    def getApplicationEnvironment(self, app):
        return queuesystem.QueueSystemConfig.getApplicationEnvironment(self, app) + \
               [ ("ARCHITECTURE", getArchitecture(app)), ("MAJOR_RELEASE_ID", getMajorReleaseId(app)) ]
    
class RunWithParallelAction(plugins.Action):
    def __init__(self, baseRunner, isExecutable):
        self.parallelActions = [ self ]
        if isinstance(baseRunner, RunWithParallelAction):
            self.parallelActions.append(baseRunner)
            self.baseRunner = baseRunner.baseRunner
        else:
            self.baseRunner = baseRunner
        self.isExecutable = isExecutable
        self.diag = plugins.getDiagnostics("Parallel Action")
    def __repr__(self):
        return repr(self.baseRunner)
    def __call__(self, test):
        if test.state.isComplete():
            return
        processId = os.fork()
        if processId == 0:
            # Note, this is a child process, so any state changes made by baseRunner will not be reflected, and anything written will not get printed...
            self.baseRunner(test)
            os._exit(0)
        else:
            try:
                execProcess, parentProcess = self.findProcessInfo(processId, test)
                for parallelAction in self.parallelActions:
                    parallelAction.performParallelAction(test, execProcess, parentProcess)
            except plugins.TextTestError:
                for parallelAction in self.parallelActions:
                    parallelAction.handleNoTimeAvailable(test)
            os.waitpid(processId, 0)
            # Make the state change that would presumably be made by the baseRunner...
            self.baseRunner.changeToRunningState(test, None)
    def findProcessInfo(self, firstpid, test):
        while 1:
            execProcess, parentProcess = self._findProcessInfo(plugins.Process(firstpid), test)
            if execProcess:
                return execProcess, parentProcess
            else:
                time.sleep(0.1)
    def _findProcessInfo(self, process, test):
        self.diag.info(" Looking for info from process " + repr(process))
        if process.hasTerminated():
            raise plugins.TextTestError, "Job already finished; cannot perform process-related activities"
        # Look for the binary process, or a child of it, that is a pure executable not a script
        childProcesses = process.findChildProcesses()
        if len(childProcesses) == 0:
            return None, None
        
        executableProcessName = childProcesses[-1].getName()
        parentProcessName = childProcesses[-2].getName()
        if self.isExecutable(executableProcessName, parentProcessName, test):
            self.diag.info("Chose process as executable : " + executableProcessName)
            return childProcesses[-1], childProcesses[-2]
        else:
            self.diag.info("Rejected process as executable : " + executableProcessName)
            return None, None
    def setUpSuite(self, suite):
        self.baseRunner.setUpSuite(suite)
    def setUpApplication(self, app):
        self.baseRunner.setUpApplication(app)
    def handleNoTimeAvailable(self, test):
        # Do nothing by default
        pass
                
class RunLprof(RunWithParallelAction):
    def performParallelAction(self, test, execProcess, parentProcess):
        self.describe(test, ", profiling process '" + execProcess.getName() + "'")
        os.chdir(test.writeDirs[0])
        runLine = "/users/lennart/bin/gprofile " + str(execProcess.processId) + " >& gprof.output"
        os.system(runLine)
    def handleNoTimeAvailable(self, test):
        raise plugins.TextTestError, "Lprof information not collected, test did not run long enough to connect to it"
    
class ProcessProfilerResults(plugins.Action):
    def __call__(self, test):
        processLine = "/users/lennart/bin/process_gprof -t 0.5 prof.*" + " > " + test.makeFileName("lprof", temporary = 1)
        os.system(processLine)
        # Compress and save the raw data.
        cmdLine = "gzip prof.[0-9]*;mv prof.[0-9]*.gz " + test.makeFileName("prof", temporary = 1, forComparison=0)
        os.system(cmdLine)
    def __repr__(self):
        return "Profiling"    

