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

import queuesystem, default, performance, os, plugins, respond, time, __builtin__
from ndict import seqdict
from jobprocess import JobProcess
from threading import Thread

# Use cvs plugin for all Carmen suites
from guiplugins import interactiveActionHandler
interactiveActionHandler.loadModules.append("cvs")

# All files should be opened 5 times before we conclude something is wrong
origOpen = __builtin__.open

def repeatedOpen(fileName, *args, **kwargs):
    for attempt in range(4):
        try:
            return origOpen(fileName, *args, **kwargs)
        except IOError, e:
            errMsg = str(e)
            if errMsg.find("Permission denied") != -1:
                raise
            else:
                from socket import gethostname
                print "Failed to open file", fileName, ": assuming automount trouble and trying again!"
                print "(Automount trouble:" + plugins.localtime() + ":" + gethostname() + ":" + errMsg + ")"
                time.sleep(0.1)
    return origOpen(fileName, *args, **kwargs)

__builtin__.open = repeatedOpen
            
def getConfig(optionMap):
    return CarmenConfig(optionMap)

architectures = [ "i386_linux", "sparc", "sparc_64", "powerpc", "parisc_2_0", "parisc_1_1", "i386_solaris", "ia64_hpux", "x86_64_linux" ]
majorReleases = [ "11", "12", "13", "14", "master", "tracking" ]

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
    if version == "master" or version == "tracking" or version == "none":
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
        self.cpuTime = performance.getTestPerformance(self.test)
        self.diag = plugins.getDiagnostics("Submission Rules")
    def getMajorReleaseResourceType(self):
        return "run"
    def getEnvironmentPerfCategory(self):
        return self.test.getEnvironment("QUEUE_SYSTEM_PERF_CATEGORY", "")
    def getShortQueueSeconds(self):
        return plugins.getNumberOfSeconds(str(self.test.getConfigValue("maximum_cputime_for_short_queue")))
    # Return "short", "medium" or "long"
    def getPerformanceCategory(self):
        # Hard-coded, useful at boundaries and for rave compilations
        if self.presetPerfCategory:
            return self.presetPerfCategory
        else:
            # Disabled the short queue in sparc for now, it has too many problems with overloading. See bug 17494
            timeCat = self.getPerfCategoryFromTime(self.cpuTime)
            if timeCat == "short" and self.archToUse.find("sparc") != -1:
                return "medium"
            else:
                return timeCat
    def getPerfCategoryFromTime(self, cpuTime):
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
        if self.cpuTime == -1:
            # We don't know yet...
            return 0
        shortQueueSeconds = self.getShortQueueSeconds()
        if self.cpuTime < shortQueueSeconds:
            return -self.cpuTime
        else:
            priority = -600 -self.cpuTime / 100
            # don't return less than minimum priority
            if priority > -1023:
                return priority
            else:
                return -1023
    def getSGEReleaseID(self):
        version = getMajorReleaseVersion(self.test.app)
        if version == "tracking":
            return "TRACKING_1" # SGE is a bit confused about all these branches...
        else:
            return version
    def getMajorReleaseResource(self):
        majRelease = self.getSGEReleaseID()
        if majRelease == "none":
            return ""
        else:
            return "carm" + self.getMajorReleaseResourceType() + majRelease + "=1"
    def getBasicResources(self):
        return queuesystem.SubmissionRules.findResourceList(self)
    def findConcreteResources(self):
        # architecture resources
        resources = [ "carmarch=*" + self.archToUse + "*" ]
        majRelResource = self.getMajorReleaseResource()
        if majRelResource:
            resources.append(majRelResource)
            
        resources += self.getBasicResources()
        return resources
    def findResourceList(self):
        return self.findConcreteResources() + [ self.findQueueResource() ]
    def getSubmitSuffix(self):
        name = queuesystem.queueSystemName(self.test)
        return " to " + name + " queue " + self.findQueueResource() + ", requesting " + ",".join(self.findConcreteResources())
    def allowsReuse(self, otherRules):
        if not queuesystem.SubmissionRules.allowsReuse(self, otherRules):
            return False
        # Try to make sure we don't change "performance category" by reuse
        self.diag.info("Check for reuse : old time " + repr(self.cpuTime) + ", additional time " + repr(otherRules.cpuTime))
        thisCategory = self.getPerformanceCategory()
        otherCategory = otherRules.getPerformanceCategory()
        if thisCategory != otherCategory:
            return False

        totalTime = self.cpuTime + otherRules.cpuTime
        combinedCategory = self.getPerfCategoryFromTime(totalTime)
        if combinedCategory == thisCategory:
            self.cpuTime = totalTime
            otherRules.cpuTime = totalTime
            return True
        else:
            return False

class CarmenConfig(queuesystem.QueueSystemConfig):
    def addToOptionGroups(self, app, groups):
        queuesystem.QueueSystemConfig.addToOptionGroups(self, app, groups)
        for group in groups:
            if group.name.startswith("Advanced"):
                group.addSwitch("lprof", "Run with LProf profiler")
    def getPossibleQueues(self, queuesystem):
        if queuesystem == "SGE":
            return ["short", "normal", "idle"]
        else:
            return []
    def getTestRunner(self):
        baseRunner = queuesystem.QueueSystemConfig.getTestRunner(self)
        if self.optionMap.has_key("lprof"):
            return [ RunLprof(self.isExecutable, self.hasAutomaticCputimeChecking), baseRunner ]
        else:
            return baseRunner
    def isExecutable(self, process, test):
        return not process.startswith(".") and process.find("arch") == -1 and process.find("crsutil") == -1
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
        return batchSession != "release" and batchSession in self.getFilteredBatchSessions()
    def printHelpOptions(self):
        print helpOptions
    def printHelpDescription(self):
        print helpDescription
    def defaultViewProgram(self):
        return "xemacs"
    def getFilteredBatchSessions(self):
        return [ "nightjob", "wkendjob", "release", "nightly_publish", "nightly_publish.lsf", \
                 "weekly_publish", "weekly_publish.lsf", "small_publish", "test_nightjob" ]
    def getDefaultMaxCapacity(self):
        return 70 # roughly number of R&D i386_linux machines, with a bit extra for luck
    def setApplicationDefaults(self, app):
        queuesystem.QueueSystemConfig.setApplicationDefaults(self, app)
        app.setConfigDefault("default_architecture", "i386_linux", "Which Carmen architecture to run tests on by default")
        app.setConfigDefault("default_major_release", "master", "Which Carmen major release to run by default")
        app.setConfigDefault("maximum_cputime_for_short_queue", 10, "Maximum time a test can take and be sent to the short queue")
        # plenty of people use CVS at Carmen, best to ignore it in data
        app.addConfigEntry("default", "CVS", "test_data_ignore")
        for batchSession in self.getFilteredBatchSessions():
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
    def __init__(self, isExecutable, hasAutomaticCpuTimeChecking):
        self.isExecutable = isExecutable
        self.hasAutomaticCpuTimeChecking = hasAutomaticCpuTimeChecking
        self.diag = plugins.getDiagnostics("Parallel Action")
    def __call__(self, test):
        parallelActionThread = Thread(target=self.runParallelAction, args=(test,))
        parallelActionThread.setDaemon(True)
        parallelActionThread.start()
    def runParallelAction(self, test):
        try:
            execProcess, parentProcess = self.findProcessInfo(test)
            self.performParallelAction(test, execProcess, parentProcess)
        except plugins.TextTestError:
            self.handleNoTimeAvailable(test)
    def getTestProcess(self, test):
        state = test.state # cache to avoid race conditions
        if state.isComplete():
            raise plugins.TextTestError, "Job already finished; cannot perform process-related activities"
        elif not state.hasStarted():
            time.sleep(0.1)
            return self.getTestProcess(test)
        else:
            jobProc = JobProcess(test.state.bkgProcess.pid)
            if self.hasAutomaticCpuTimeChecking(test.app):
                # Here we expect the given process to be "time", with a shell subprocess
                for attempt in range(5):
                    childProcs = jobProc.findChildProcesses()
                    if len(childProcs) > 1:
                        if childProcs[1].getName():
                            return childProcs[1]
                        else:
                            # For powerpc, there is one less process level.
                            # ChildProcs[1] is the ps process, which is dead
                            return childProcs[0]
                raise plugins.TextTestError, "Child processes didn't look as expected when running with automatic CPU time checking"
            return jobProc
    def findProcessInfo(self, test):
        parentProcess = self.getTestProcess(test)
        while 1:
            execProcess = self._findProcessInfo(parentProcess, test)
            if execProcess:
                return execProcess, parentProcess
            else:
                time.sleep(0.1)
    def _findProcessInfo(self, process, test):
        self.diag.info(" Looking for info from process " + repr(process))
        if process.poll() is not None:
            raise plugins.TextTestError, "Job already finished; cannot perform process-related activities"
        childProcesses = process.findChildProcesses()
        if len(childProcesses) != 1:
            return
        
        executableProcessName = childProcesses[0].getName()
        if len(executableProcessName) == 0:
            return# process already complete
        if self.isExecutable(executableProcessName, test):
            self.diag.info("Chose process as executable : " + executableProcessName)
            return childProcesses[0]
        else:
            self.diag.info("Rejected process as executable : " + executableProcessName)
    def handleNoTimeAvailable(self, test):
        # Do nothing by default
        pass
    def getInterruptActions(self, fetchResults):
        return self.baseRunner.getInterruptActions(fetchResults)
                
class RunLprof(RunWithParallelAction):
    def __repr__(self):
        return "Running Lprof profiler on"
    def performParallelAction(self, test, execProcess, parentProcess):
        self.describe(test, ", process '" + execProcess.getName() + "'")
        outFile = test.makeTmpFileName("gprof.output", forComparison=0)
        runLine = "/users/lennart/bin/gprofile " + str(execProcess.pid) + " >& " + outFile
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

