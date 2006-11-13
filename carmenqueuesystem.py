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

import queuesystem, default, performance, os, string, shutil, plugins, respond, time
from ndict import seqdict

def getConfig(optionMap):
    return CarmenConfig(optionMap)

architectures = [ "i386_linux", "sparc", "sparc_64", "powerpc", "parisc_2_0", "parisc_1_1", "i386_solaris", "ia64_hpux", "x86_64_linux" ]
majorReleases = [ "11", "12", "13", "master" ]

def getArchitecture(app):
    for version in app.versions:
        if version in architectures:
            return version
    return app.getConfigValue("default_architecture")

def getMajorReleaseVersion(app):
    defaultMajRelease = app.getConfigValue("default_major_release")
    # If we disable this, don't re-enable it whatever the versions are...
    if defaultMajRelease == "none":
        return defaultMajRelease
    
    for version in app.versions:
        if version in majorReleases:
            return version
    return defaultMajRelease

def getMajorReleaseId(app):
    return fullVersionName(getMajorReleaseVersion(app))

def getBitMode(app):
    arch = getArchitecture(app)
    if arch.find("64") != -1:
        return "64"
    else:
        return "32"

def fullVersionName(version):
    if version == "master" or version == "none":
        return version
    else:
        return "carmen_" + version

class CarmenSgeSubmissionRules(queuesystem.SubmissionRules):
    def __init__(self, optionMap, test, nightjob=False):
        queuesystem.SubmissionRules.__init__(self, optionMap, test)
        # Must cache all environment variables, they may not be preserved in queue system thread...
        self.presetPerfCategory = self.getEnvironmentPerfCategory()
        self.archToUse = getArchitecture(self.test.app)
        self.nightjob = nightjob
    def getMajorReleaseResourceType(self):
        return "run"
    def getEnvironmentPerfCategory(self):
        return os.getenv("QUEUE_SYSTEM_PERF_CATEGORY", "")
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
    def findQueue(self):
        # Carmen's queues are all 'hidden', requesting them directly is not allowed.
        # They must be requested by their 'queue resources', that have the same names...
        return ""
    def findQueueResource(self):
        requestedQueue = queuesystem.SubmissionRules.findQueue(self)
        if requestedQueue:
            return requestedQueue
        else:
            category = self.getPerformanceCategory()
            return self.getQueueFromCategory(category)
    def getQueueFromCategory(self, category):
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
        majRelease = getMajorReleaseVersion(self.test.app)
        if majRelease == "none":
            return ""
        else:
            return "carm" + self.getMajorReleaseResourceType() + majRelease + "=1"
    def getBasicResources(self):
        return queuesystem.SubmissionRules.findResourceList(self)
    def findConcreteResources(self):
        resources = self.getBasicResources()
        # architecture resources
        resources.append("carmarch=\"*" + self.archToUse + "*\"")
        majRelResource = self.getMajorReleaseResource()
        if majRelResource:
            resources.append(majRelResource)
        return resources
    def findResourceList(self):
        return self.findConcreteResources() + [ self.findQueueResource() ]
    def getSubmitSuffix(self, name):
        return " to " + name + " queue " + self.findQueueResource() + ", requesting " + string.join(self.findConcreteResources(), ",")

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
    def getFileExtractor(self):
        baseExtractor = queuesystem.QueueSystemConfig.getFileExtractor(self)
        if self.optionMap.has_key("lprof"):
            return [ baseExtractor, ProcessProfilerResults() ]
        else:
            return baseExtractor
    def getSubmissionRules(self, test):
        if queuesystem.queueSystemName(test.app) == "LSF":
            return queuesystem.QueueSystemConfig.getSubmissionRules(self, test)
        else:
            return CarmenSgeSubmissionRules(self.optionMap, test, self.isNightJob())
    def isNightJob(self):
        batchSession = self.optionValue("b")
        return batchSession == "nightjob" or batchSession == "wkendjob" or batchSession.startswith("nightly_publish") or batchSession.startswith("weekly_publish") or batchSession.startswith("small_publish")
    def printHelpOptions(self):
        print helpOptions
    def printHelpDescription(self):
        print helpDescription
    def defaultViewProgram(self):
        return "xemacs"
    def setApplicationDefaults(self, app):
        queuesystem.QueueSystemConfig.setApplicationDefaults(self, app)
        app.setConfigDefault("default_architecture", "i386_linux", "Which Carmen architecture to run tests on by default")
        app.setConfigDefault("default_major_release", "master", "Which Carmen major release to run by default")
        app.setConfigDefault("maximum_cputime_for_short_queue", 10, "Maximum time a test can take and be sent to the short queue")
        app.setConfigDefault("maximum_cputime_for_chunking", 0.0, "(LSF) Maximum time a test can take and be chunked")
        # plenty of people use CVS at Carmen, best to ignore it in data
        app.addConfigEntry("default", "CVS", "test_data_ignore")
        for batchSession in [ "nightjob", "wkendjob", "release", "nightly_publish", "weekly_publish", "small_publish" ]:
            app.addConfigEntry(batchSession, "true", "batch_use_version_filtering")
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
        envVars = [ ("ARCHITECTURE", getArchitecture(app)), ("BITMODE", getBitMode(app)) ]
        majReleaseVersion = getMajorReleaseVersion(app)
        if majReleaseVersion != "none":
            envVars += [ ("MAJOR_RELEASE_VERSION", majReleaseVersion), \
                         ("MAJOR_RELEASE_ID", fullVersionName(majReleaseVersion)) ]
        return envVars
    
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
            self.diag.info("Chose process as executable : " + executableProcessName + " parent process " + parentProcessName)
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

