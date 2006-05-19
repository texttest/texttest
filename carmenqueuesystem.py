#!/usr/local/bin/python

helpDescription = """
The Carmen configuration is based on the queuesystem configuration
(see http://www.texttest.org/TextTest/docs/queuesystem). Its default operation is therefore to
submit all jobs to the queuesystem (SGE unless you request LSF), rather than run them locally.

Execution architectures are determined by versions. If any version is specified which is the name of a Carmen architecture,
that architecture will be used. Otherwise the entry "default_architecture" is read from the config file and used. This
architecture will be provided as a request for the SGE resource 'carmarch'.

It determines the SGE queue to submit to as follows: if a test takes less than 10 minutes, it will be submitted
to the short queue. If it takes more than 2 hours, it will go to the idle queue. If neither of these, or if the specified queue
does not exist, it will be submitted to the 'normal' queue. You can override this behaviour by setting the environment variable
"QUEUE_SYSTEM_PERF_CATEGORY" to "short", "medium" or "long", as appropriate, when the time taken by the test will not
be considered.

The Carmen nightjob will run TextTest on all versions and on all architectures. It will do so with the batch
session name "nightjob" on Monday to Thursday nights, and "wkendjob" on Friday night.
If you do not want this, you should therefore restrict or disable these session names in your config file, as
described in the documentation for batch mode.

Note that, because the Carmen configuration infers architectures from versions, you can also
enable and disable architectures using the config file entry "batch_version" (see the online documentation for batch mode.)

Note also that the "nightjob" sessions are killed at 8am each morning, while the "wkendjob" sessions are killed
at 8am on Monday morning. This can cause some tests to be reported as "killed" in your batch report.
"""

helpOptions = """
-lprof     - Run LProf on the test concerned. This will automatically profile the job and generate the textual
             data in the test directory, in a file called lprof.<app>. It is proposed to automatically generate
             the graphical information also
"""

import queuesystem, default, performance, os, string, shutil, plugins, respond, predict, time
from ndict import seqdict

def getConfig(optionMap):
    return CarmenConfig(optionMap)

architectures = [ "i386_linux", "sparc", "sparc_64", "powerpc", "parisc_2_0", "parisc_1_1", "i386_solaris", "ia64_hpux", "x86_64_linux" ]
majorReleases = [ "8", "9", "10", "11", "12", "master" ]

def getArchitecture(app):
    for version in app.versions:
        if version in architectures:
            return version
    return app.getConfigValue("default_architecture")

def getMajorReleaseVersion(app):
    for version in app.versions:
        if version in majorReleases:
            return version
    return app.getConfigValue("default_major_release")

def getMajorReleaseId(app):
    return fullVersionName(getMajorReleaseVersion(app))

def getBitMode(app):
    if "sparc_64" in app.versions or "x86_64_linux" in app.versions:
        return "64"
    else:
        return "32"

def fullVersionName(version):
    if version == "master":
        return version
    else:
        return "carmen_" + version

class CarmenSubmissionRules(queuesystem.SubmissionRules):
    def __init__(self, optionMap, test):
        queuesystem.SubmissionRules.__init__(self, optionMap, test)
        # Must cache all environment variables, they may not be preserved in queue system thread...
        self.presetPerfCategory = ""
        if os.environ.has_key("QUEUE_SYSTEM_PERF_CATEGORY"):
            self.presetPerfCategory = os.environ["QUEUE_SYSTEM_PERF_CATEGORY"]
        self.archToUse = getArchitecture(self.test.app)
    def getShortQueueSeconds(self):
        return plugins.getNumberOfSeconds(str(self.test.getConfigValue("maximum_cputime_for_short_queue")))
    # Return "short", "medium" or "long"
    def getPerformanceCategory(self):
        # Hard-coded, useful at boundaries and for rave compilations
        if self.presetPerfCategory:
            return self.presetPerfCategory
        cpuTime = performance.getTestPerformance(self.test)
        if cpuTime == -1:
            # This means we don't know, probably because it's not enabled
            return "short"
        elif cpuTime < self.getShortQueueSeconds():
            return "short"
        elif cpuTime > 7200:
            return "long"
        else:
            return "medium"

class SgeSubmissionRules(CarmenSubmissionRules):
    def __init__(self, optionMap, test, nightjob=False):
        CarmenSubmissionRules.__init__(self, optionMap, test)
        self.nightjob = nightjob
        self.archResources = {}
        self.archResources["i386_linux.carmen_11"]   = "carmarch=\"*linux*\""
        self.archResources["i386_linux.carmen_12"]   = "carmrun12=1,carmbuildmaster=1,carmarch=\"*linux*\""
        self.archResources["i386_linux.master"]      = "carmrunmaster=1,carmarch=\"*linux*\""
        self.archResources["x86_64_linux.carmen_12"] = "carmrun12=1,model=\"Opteron*\""
        self.archResources["boost.x86_64_linux.carmen_12"] = "carmrun12=1,model=\"Opteron*\",carmarch=\"x86_64_linux\""
        self.archResources["x86_64_linux.master"]    = "osversion=\"RHEL4\",carmarch=\"x86_64_linux\""
        
 #
 #                              R3-Pent_32 R3-Xeon_32  R3-Opteron_32 R3-Opteron_64 R4-Xeon_32 R4-Opteron_64
 #
 # i386_linux.carmen_11           X          X           X                                      x
 # i386_linux.carmen_12           x          X           X                                      X
 # i386_linux.master              x          x           X                           X?         X
 # x86_64_linux.carmen_12                                X             X                        X
 # boost.x86_64_linux.carmen_12                                        X                        X
 # x86_64_linux.master                                                                          X
 #
        
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
        elif category == "medium" or self.nightjob:
            return "normal"
        else:
            return "idle"
    def findPriority(self):
        cpuTime = performance.getTestPerformance(self.test)
        if cpuTime == -1:
            # We don't know yet...
            return 0
        shortQueueSeconds = self.getShortQueueSeconds()
        if cpuTime < shortQueueSeconds:
            return -cpuTime
        else:
            priority = -600 -cpuTime / 100
            # don't return less than minimum priority
            if priority > -1023:
                return priority
            else:
                return -1023
    def getMajorReleaseResource(self):
        majorRelease = getMajorReleaseId(self.test.app)
        if majorRelease != "carmen_9":
            # Can't build on these machines anyway - texttest won't work!
            return "carmbuild" + majorRelease.replace("carmen_", "") + "=1"
        else:
            return ""
    def findConcreteResources(self):
        # architecture resources
        resources = CarmenSubmissionRules.findResourceList(self)
        archDesc = getArchitecture(self.test.app) + "." + getMajorReleaseId(self.test.app)
        if "boost" in self.test.app.versions  and self.archResources.has_key("boost." + archDesc):
            resources.append(self.archResources["boost." + archDesc])
        elif self.archResources.has_key(archDesc):
            resources.append(self.archResources[archDesc])
        else:
            resources.append("carmarch=\"*" + self.archToUse + "*\"")
        return resources
    def findResourceList(self):
        return self.findConcreteResources() + [ self.findQueueResource() ]
    def getSubmitSuffix(self, name):
        return " to " + name + " queue " + self.findQueueResource() + ", requesting " + string.join(self.findConcreteResources(), ",")

class LsfSubmissionRules(CarmenSubmissionRules):
    def findDefaultQueue(self):
        if self.archToUse == "i386_linux" and not self.presetPerfCategory:
            cpuTime = performance.getTestPerformance(self.test)
            chunkLimit = plugins.getNumberOfSeconds(self.test.app.getConfigValue("maximum_cputime_for_chunking"))
            if cpuTime > 0 and cpuTime < chunkLimit:
                return "short_rd_testing_chunked"
        return self.getQueuePerformancePrefix() + self.getArchQueueName() +\
               self.getQueuePlatformSuffix()
    def getArchQueueName(self):
        if self.archToUse == "sparc_64":
            return "sparc"
        else:
            return self.archToUse
    def getMajorReleaseResource(self):
        return ""
    def getQueuePerformancePrefix(self):
        category = self.getPerformanceCategory()
        if category == "short":
            return "short_"
        elif category == "medium" or (self.archToUse == "powerpc" or self.archToUse == "parisc_2_0"):
            return ""
        else:
            return "idle_"
    def getQueuePlatformSuffix(self):
        if self.archToUse == "i386_linux":
            return "_RHEL"
        elif self.archToUse == "sparc" or self.archToUse == "sparc_64":
            return "_sol8"
        elif self.archToUse == "powerpc":
            return "_aix5"
        return ""

class CarmenConfig(queuesystem.QueueSystemConfig):
    def addToOptionGroups(self, app, groups):
        queuesystem.QueueSystemConfig.addToOptionGroups(self, app, groups)
        for group in groups:
            if group.name.startswith("How"):
                group.addSwitch("lprof", "Run with LProf profiler")
            elif group.name.startswith("SGE"):
                group.addOption("q", "Request " + group.name + " queue", possibleValues = ["short", "normal", "idle"])
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
    def getSubmissionRules(self, test):
        if queuesystem.queueSystemName(test.app) == "LSF":
            return LsfSubmissionRules(self.optionMap, test)
        else:
            return SgeSubmissionRules(self.optionMap, test, self.isNightJob())
    def isNightJob(self):
        batchSession = self.optionValue("b")
        return batchSession == "nightjob" or batchSession == "wkendjob" or batchSession.startswith("nightly_publish") or batchSession.startswith("weekly_publish") or batchSession.startswith("small_publish")
    def printHelpOptions(self):
        print helpOptions
    def printHelpDescription(self):
        print helpDescription
    def setApplicationDefaults(self, app):
        queuesystem.QueueSystemConfig.setApplicationDefaults(self, app)
        app.setConfigDefault("default_architecture", "i386_linux")
        app.setConfigDefault("default_major_release", "master")
        app.setConfigDefault("maximum_cputime_for_short_queue", 10)
        app.setConfigDefault("maximum_cputime_for_chunking", 0.0)
        for var, value in self.getCarmenEnvironment(app):
            os.environ[var] = value
    def defaultLoginShell(self):
        # All of carmen's login stuff is done in tcsh starter scripts...
        return "/bin/tcsh"
    def setEnvironment(self, test):
        queuesystem.QueueSystemConfig.setEnvironment(self, test)
        if test.parent is None:
            for var, value in self.getCarmenEnvironment(test.app):
                test.setEnvironment(var, value)
    def getCarmenEnvironment(self, app):
        return [ ("ARCHITECTURE", getArchitecture(app)), ("MAJOR_RELEASE_VERSION", getMajorReleaseVersion(app)), \
                 ("MAJOR_RELEASE_ID", getMajorReleaseId(app)), ("BITMODE", getBitMode(app)) ]
    
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
        processId = os.fork()
        if processId == 0:
            # Note, this is a child process, so any state changes made by baseRunner will not be reflected, and anything written will not get printed...
            try:
                self.baseRunner(test, inChild=1)
            except KeyboardInterrupt:
                # Don't allow interruptions to propagate, we want to kill this off
                pass
            os._exit(0)
        else:
            try:
                # Make the state change that would presumably be made by the baseRunner...
                self.baseRunner.changeToRunningState(test, None)
                execProcess, parentProcess = self.findProcessInfo(processId, test)
                for parallelAction in self.parallelActions:
                    parallelAction.performParallelAction(test, execProcess, parentProcess)
            except plugins.TextTestError:
                for parallelAction in self.parallelActions:
                    parallelAction.handleNoTimeAvailable(test)
            except IOError:
                # interrupted system call in I/O is no problem
                pass
            try:
                os.waitpid(processId, 0)
            except OSError:
                # Assume interrupted system call, which isn't a problem, basically.
                pass
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
        if len(childProcesses) < 2:
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
    def getInterruptActions(self, fetchResults):
        return self.baseRunner.getInterruptActions(fetchResults)
                
class RunLprof(RunWithParallelAction):
    def performParallelAction(self, test, execProcess, parentProcess):
        self.describe(test, ", profiling process '" + execProcess.getName() + "'")
        test.grabWorkingDirectory()
        runLine = "/users/lennart/bin/gprofile " + str(execProcess.processId) + " >& gprof.output"
        os.system(runLine)
    def handleNoTimeAvailable(self, test):
        raise plugins.TextTestError, "Lprof information not collected, test did not run long enough to connect to it"
    
class ProcessProfilerResults(plugins.Action):
    def __call__(self, test):
        processLine = "/users/lennart/bin/process_gprof -t 0.5 prof.*" + " > " + test.makeTmpFileName("lprof")
        os.system(processLine)
        # Compress and save the raw data.
        cmdLine = "gzip prof.[0-9]*;mv prof.[0-9]*.gz " + test.makeTmpFileName("prof", forFramework=1)
        os.system(cmdLine)
    def __repr__(self):
        return "Profiling"    

