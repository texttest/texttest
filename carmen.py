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

import lsf, default, performance, os, string, shutil, plugins, respond, predict, time
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

class CarmenConfig(lsf.LSFConfig):
    def addToOptionGroup(self, group):
        lsf.LSFConfig.addToOptionGroup(self, group)
        if group.name.startswith("How"):
            group.addSwitch("lprof", "Run with LProf profiler")
    def getLoginShell(self):
        # All of carmen's login stuff is done in tcsh starter scripts...
        return "/bin/tcsh"
    def getTestRunner(self):
        baseRunner = lsf.LSFConfig.getTestRunner(self)
        if self.optionMap.has_key("lprof"):
            return RunLprof(baseRunner, self.isExecutable)
        else:
            return baseRunner
    def isExecutable(self, process, parentProcess, test):
        binaryName = os.path.basename(test.getConfigValue("binary"))
        return binaryName.startswith(parentProcess) and process.find(".") == -1 and process.find("arch") == -1 and process.find("crsutil") == -1
    def binaryRunning(self, processNameDict):
        for name in processNameDict.values():
            if self.binaryName.startswith(name):
                return 1
        return 0
    def getTestCollator(self):
        if self.optionMap.has_key("lprof"):
            return [ self.getFileCollator(), ProcessProfilerResults() ]
        else:
            return self.getFileCollator()
    def getFileCollator(self):
        return lsf.LSFConfig.getTestCollator(self)
    def findDefaultLSFQueue(self, test):
        arch = getArchitecture(test.app)
        return self.getQueuePerformancePrefix(test, arch) + self.getArchQueueName(arch) + self.getQueuePlatformSuffix(test.app, arch)
    def getArchQueueName(self, arch):
        if arch == "sparc_64":
            return "sparc"
        else:
            return arch
    def getQueuePerformancePrefix(self, test, arch, rave = 0):
        cpuTime = performance.getTestPerformance(test)
        usePrefix = None
        if not rave and os.environ.has_key("LSF_QUEUE_PREFIX"):
            usePrefix = os.environ["LSF_QUEUE_PREFIX"]
        # Currently no short queue for powerpc_aix4
        if arch == "powerpc" and "9" in test.app.versions:
            return ""
        if usePrefix == None and (cpuTime < test.getConfigValue("maximum_cputime_for_short_queue") or rave):
            return "short_"
        elif arch == "powerpc" or arch == "parisc_2_0":
            return ""
        elif usePrefix == None and cpuTime < 120:
            return ""
        elif usePrefix == None:
            return "idle_"
        elif usePrefix == "":
            return ""
        else:
            return usePrefix + "_"
    def getQueuePlatformSuffix(self, app, arch):
        if arch == "i386_linux":
            return "_RHEL"
        elif arch == "sparc" or arch == "sparc_64":
            return "_sol8"
        elif arch == "powerpc":
            if "9" in app.versions:
                return "_aix4"
            else:
                return "_aix5"
        return ""
    def isNightJob(self):
        batchSession = self.optionValue("b")
        return batchSession == "nightjob" or batchSession == "wkendjob"
    def printHelpOptions(self, builtInOptions):
        print lsf.helpOptions + batchInfo
        default.Config.printHelpOptions(self, builtInOptions)
        print "(Carmen-specific options...)"
        print helpOptions
    def printHelpDescription(self):
        print helpDescription, lsf.lsfGeneral, predict.helpDescription, performance.helpDescription, respond.helpDescription
    def setApplicationDefaults(self, app):
        lsf.LSFConfig.setApplicationDefaults(self, app)
        app.setConfigDefault("default_architecture", "i386_linux")
        app.setConfigDefault("maximum_cputime_for_short_queue", 10)
    def getApplicationEnvironment(self, app):
        return lsf.LSFConfig.getApplicationEnvironment(self, app) + \
               [ ("ARCHITECTURE", getArchitecture(app)), ("MAJOR_RELEASE_ID", getMajorReleaseId(app)) ]
    
class RunWithParallelAction(plugins.Action):
    def __init__(self, baseRunner, isExecutable):
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
            self.baseRunner(test)
            os._exit(0)
        else:
            processInfo = self.findProcessInfo(processId, test)
            self.performParallelAction(test, processInfo)
            os.waitpid(processId, 0)
    def findProcessInfo(self, firstpid, test):
        while 1:
            processInfo = self._findProcessInfo(firstpid, test)
            if processInfo:
                return processInfo
            else:
                time.sleep(0.1)
    def _findProcessInfo(self, firstpid, test):
        self.diag.info("Looking for info from process " + str(firstpid))
        # Look for the binary process, or a child of it, that is a pure executable not a script
        allProcesses = plugins.findAllProcesses(firstpid)
        if len(allProcesses) == 0:
            raise plugins.TextTestError, "Job already finished; cannot perform process-related activities"
        if len(allProcesses) == 1:
            return
        
        processNameDict = self.getProcessNames(allProcesses)
        executableProcessName = processNameDict.values()[-1]
        parentProcessName = processNameDict.values()[-2]
        if self.isExecutable(executableProcessName, parentProcessName, test):
            self.diag.info("Chose process as executable : " + executableProcessName)
            return processNameDict.items()[-2:]
        else:
            self.diag.info("Rejected process as executable : " + executableProcessName + " in " + repr(processNameDict))
    def getProcessNames(self, allProcesses):
        dict = seqdict()
        for processId in allProcesses:
            psline = os.popen("ps -l -p " + str(processId)).readlines()[-1]
            dict[str(processId)] = psline.split()[-1]
        return dict        
                
class RunLprof(RunWithParallelAction):
    def performParallelAction(self, test, processInfo):
        processId, processName = processInfo[-1]
        self.describe(test, ", profiling process '" + processName + "'")
        runLine = "/users/lennart/bin/gprofile " + processId + " >& gprof.output"
        os.system(runLine)
    
class ProcessProfilerResults(plugins.Action):
    def __call__(self, test):
        processLine = "/users/lennart/bin/process_gprof -t 0.5 prof.*" + " > " + test.makeFileName("lprof", temporary = 1)
        os.system(processLine)
        # Compress and save the raw data.
        cmdLine = "gzip prof.[0-9]*;mv prof.[0-9]*.gz " + test.makeFileName("prof", temporary = 1, forComparison=0)
        os.system(cmdLine)
    def __repr__(self):
        return "Profiling"    

