
from . import local
import signal
import logging
import errno
import time
import os
import sys
from texttestlib import plugins
from texttestlib.utils import getPortListenErrorCode, getUserName
from threading import Thread, Lock
from queue import Queue
from fnmatch import fnmatch


class Ec2Machine:
    instanceTypeInfo = {"8xlarge": 32, "4xlarge": 16, "2xlarge": 8, "xlarge": 4, "large": 2, "medium": 1}

    def __init__(self, inst, synchDirs, app, subprocessLock, alreadyRunning):
        self.id = inst.id
        self.ip = inst.private_ip_address
        self.fullMachine = "ec2-user@" + self.ip
        self.cores = self.instanceTypeInfo.get(inst.instance_type.split(".")[-1], 1)
        self.synchDirs = synchDirs
        self.synchProc = None
        self.app = app
        self.remoteProcessInfo = {}
        self.remoteProcessInfoLock = Lock()
        self.thread = Thread(target=self.runThread)
        self.thread.setName("Machine_" + self.ip)
        self.startWaitCounter = 0
        self.diag = logging.getLogger("Ec2Machine")
        self.queue = Queue()
        self.errorMessage = ""
        self.subprocessLock = subprocessLock
        self.startMethod = None if alreadyRunning else inst.start

    def getNextJobId(self):
        return "job" + str(len(self.remoteProcessInfo)) + "_" + self.ip

    def getParents(self, dirs):
        parents = []
        for dir in dirs:
            parent = os.path.dirname(dir)
            if parent not in parents:
                parents.append(parent)
        return parents

    def isFull(self):
        return len(self.remoteProcessInfo) >= self.cores

    def hasJob(self, jobId):
        return jobId in self.remoteProcessInfo

    def setLocalProcessId(self, jobId, localPid):
        with self.remoteProcessInfoLock:
            remotePid = None
            if jobId in self.remoteProcessInfo:
                _, remotePid = self.remoteProcessInfo[jobId]
            self.remoteProcessInfo[jobId] = localPid, remotePid
        self.diag.info("Job ID " + jobId + " now got local PID " + localPid)

    def setRemoteProcessId(self, jobId, remotePid):
        with self.remoteProcessInfoLock:
            localPid, _ = self.remoteProcessInfo[jobId]
            self.remoteProcessInfo[jobId] = localPid, remotePid
        self.diag.info("Job ID " + jobId + " now got remote PID " + remotePid)

    def synchronise(self):
        parents = self.getParents(self.synchDirs)
        self.app.ensureRemoteDirExists(self.fullMachine, *parents)
        for dir in self.synchDirs:
            if not self.errorMessage:
                self.synchronisePath(dir)

    def synchronisePath(self, path):
        dirName = os.path.dirname(path)
        for _ in range(5):
            with self.subprocessLock:
                self.synchProc = self.app.getRemoteCopyFileProcess(path, "localhost", dirName, self.fullMachine)
            errorCode = self.synchProc.wait()
            if errorCode == 0:
                self.synchProc = None
                return
            else:
                time.sleep(1)

    def waitForStart(self):
        timeout = 1000
        self.diag.info("Waiting for response to ssh...")
        while self.startWaitCounter < timeout:
            ret = getPortListenErrorCode(self.ip, 22)
            if ret == 0 or self.errorMessage:
                self.startWaitCounter = 0
                break
            self.startWaitCounter += 1
            timedout = ret in [errno.EWOULDBLOCK, errno.ETIMEDOUT]
            if not timedout:
                time.sleep(1)

    def runThread(self):
        if self.startMethod:
            self.startMethod()  # should be self.waitForStart that is called here, not instance.start. Don't use boto methods in a thread!

        if self.errorMessage:
            return
        try:
            self.diag.info("Synchronising files with EC2 instance with private IP address '" + self.ip + "'...")
            self.synchronise()
        except plugins.TextTestError as e:
            self.errorMessage = "Failed to synchronise files with EC2 instance with private IP address '" + self.ip + "'\n" + \
                "Intended usage is to start an ssh-agent, and add the keypair for this instance to it, in your shell before starting TextTest from it.\n\n(" + str(
                    e) + ")\n"

        if self.errorMessage:
            return

        while True:
            self.diag.info("Waiting for new job for IP '" + self.ip + "'...")
            jobId, submitCallable = self.queue.get()
            if jobId is None:
                self.diag.info("No more tests for IP '" + self.ip + "', exiting.")
                return
            self.diag.info("Got job with ID " + jobId)
            localPid = self.doSubmit(submitCallable)
            self.setLocalProcessId(jobId, localPid)

    def doSubmit(self, submitCallable):
        with self.subprocessLock:
            localPid, _ = submitCallable()
            return localPid

    def cleanup(self, processes):
        # Return whether we are still using the machine in some way
        # i.e. if our thread is running or any of our processes are
        if self.thread.is_alive():
            self.queue.put((None, None))
            return True

        for localPid, _ in list(self.remoteProcessInfo.values()):
            if localPid in processes:
                proc = processes.get(localPid)
                if proc.poll() is None:
                    return True
        return False

    def getCommandArgsWithEnvironment(self, cmdArgs, slaveEnv):
        return [envVar + "=" + value for (envVar, value) in list(slaveEnv.items())] + cmdArgs

    def submitSlave(self, submitter, cmdArgs, slaveEnv, *args):
        jobId = self.getNextJobId()
        self.remoteProcessInfo[jobId] = None, None
        if not self.thread.is_alive():
            if self.startMethod:
                self.diag.info("Starting EC2 instance with private IP address '" + self.ip + "'...")
                try:
                    self.startMethod()
                except Exception as e:
                    sys.stderr.write("WARNING: failed to start instance with private IP address '" +
                                     self.ip + "'\n" + str(e))
                    return
                self.startMethod = self.waitForStart

            self.thread.start()
        argsWithEnv = self.getCommandArgsWithEnvironment(cmdArgs, slaveEnv)
        remoteCmdArgs = self.app.getCommandArgsOn(self.fullMachine, argsWithEnv, agentForwarding=True)
        self.queue.put((jobId, plugins.Callable(submitter, remoteCmdArgs, slaveEnv, *args)))
        return jobId

    def killRemoteProcess(self, jobId, sig):
        if self.synchProc:
            self.errorMessage = "Terminated test during file synchronisation"
            self.synchProc.send_signal(signal.SIGTERM)
            return True, None
        if self.startWaitCounter:
            self.errorMessage = "Terminated test while waiting for instance to start up"
            return True, None
        # ssh doesn't forward signals to remote processes.
        # We need to find it ourselves and send it explicitly. Can assume python exists remotely, but not much else.
        localPid, remotePid = self.waitForRemoteProcessId(jobId)
        if remotePid:
            cmdArgs = ["python", "-c", "\"import os; os.kill(" + remotePid + ", " + str(sig) + ")\""]
            self.app.runCommandOn(self.fullMachine, cmdArgs)
            return True, localPid
        else:
            return False, localPid

    def waitForRemoteProcessId(self, jobId):
        for _ in range(10):
            localPid, remotePid = self.remoteProcessInfo[jobId]
            if remotePid:
                return localPid, remotePid
            # Remote process exists but has not yet told us its process ID. Wait a bit and try again.
            time.sleep(1)
        return None, None

    def collectJobStatus(self, jobStatus, procStatus):
        if not self.errorMessage:
            for jobId, (localPid, _) in list(self.remoteProcessInfo.items()):
                if localPid:
                    if localPid in procStatus:
                        jobStatus[jobId] = procStatus[localPid]
                else:
                    jobStatus[jobId] = "SYNCH", "Synchronizing data with " + self.fullMachine


class QueueSystem(local.QueueSystem):
    userTagName = "TextTest user"

    def __init__(self, app):
        local.QueueSystem.__init__(self)
        self.nextMachineIndex = 0
        self.app = app
        self.subprocessLock = Lock()
        instances, runningIds = self.findInstances()
        synchDirs = self.getDirectoriesForSynch()
        self.machines = [Ec2Machine(inst, synchDirs, app, self.subprocessLock,
                                    inst.id in runningIds) for inst in instances]
        self.releasedMachines = []
        self.capacity = self.calculateCapacity()

    def calculateCapacity(self):
        return sum((m.cores for m in self.machines))

    def makeEc2Connection(self):
        import boto.ec2
        region = boto.ec2.connection.EC2Connection.DefaultRegionName  # stick to single region for now
        return boto.ec2.connect_to_region(region)

    def makeCloudwatchConnection(self):
        import boto.ec2.cloudwatch
        region = boto.ec2.connection.EC2Connection.DefaultRegionName  # stick to single region for now
        return boto.ec2.cloudwatch.connect_to_region(region)

    def getCores(self, inst, defValue=0):
        instanceSize = inst.instance_type.split(".")[-1]
        return Ec2Machine.instanceTypeInfo.get(instanceSize, defValue)

    def findInstances(self):
        if not self.app.getConfigValue("remote_copy_program"):
            sys.stderr.write(
                "Cannot run tests in EC2 cloud. You need to set 'remote_copy_program' in your config file to a program such as 'rsync'.\n")
            return [], []
        try:
            conn = self.makeEc2Connection()
        except ImportError:
            sys.stderr.write(
                "Cannot run tests in EC2 cloud. You need to install Python's boto package for this to work.\n")
            return [], []
        except:
            sys.stderr.write(
                "Failed to establish a connection to the EC2 cloud. Make sure your credentials are available in your .boto file.\n")
            return [], []
        instanceTags = self.app.getConfigValue("queue_system_resource")
        if "R" in self.app.inputOptions:
            instanceTags.append(self.app.inputOptions["R"])
        instances = self.findTaggedInstances(conn, instanceTags)
        if instances:
            running = self.getRunningIds(conn, instances)

            def getSortKey(inst):
                isRunning = inst.id in running
                cores = self.getCores(inst)
                return not isRunning, -cores, inst.private_ip_address

            instances.sort(key=getSortKey)
            maxCapacity = self.app.getConfigValue("queue_system_max_capacity")
            freeInstances, otherOwners = self.takeOwnership(conn, instances, maxCapacity)
            if freeInstances:
                self.disableAlarmActions(self.getAlarmNames(freeInstances))
            else:
                sys.stderr.write("Cannot run tests in EC2 cloud. " + str(len(instances)) + " running instances were found matching '" +
                                 ",".join(instanceTags) + "' in their tags, \nbut all are currently being used by the following users:\n" +
                                 "\n".join(otherOwners) + "\n\n")
            return freeInstances, running
        else:
            sys.stderr.write("Cannot run tests in EC2 cloud. No instances were found matching '" +
                             ",".join(instanceTags) + "' in their tags.\n")
            return [], []

    def cleanup(self, final=False):
        if final:
            # Processes might not be quite terminated, so we just hardcode that we release everything anyway
            self.releaseOwnership(self.machines)
        else:
            unusedMachines, usedMachines = [], []
            for machine in self.machines:
                if machine.cleanup(self.processes):
                    usedMachines.append(machine)
                else:
                    unusedMachines.append(machine)
            self.releaseOwnership(unusedMachines)
            self.machines = usedMachines
            self.releasedMachines = unusedMachines
        return False  # Submission is not really complete, as it happens in threads

    def matchesTag(self, instanceTags, tagName, tagPattern):
        tagValueForInstance = instanceTags.get(tagName, "")
        return fnmatch(tagValueForInstance, tagPattern)

    def parseTag(self, tag):
        return tag.split("=", 1) if "=" in tag else [tag, "1"]

    def findTaggedInstances(self, conn, instanceTags):
        instances = []
        parsedTags = [self.parseTag(tag) for tag in instanceTags]
        for inst in conn.get_only_instances():
            if inst.private_ip_address is not None and \
                    all((self.matchesTag(inst.tags, tagName, tagPattern) for tagName, tagPattern in parsedTags)):
                instances.append(inst)
        return instances

    def getRunningIds(self, conn, instances):
        ids = [inst.id for inst in instances]
        running = []
        for stat in conn.get_all_instance_status(ids):
            if stat.instance_status.status in ["ok", "initializing"]:
                running.append(stat.id)

        return running

    def tryAddTag(self, conn, instances, maxCapacity, myTag, otherOwners):
        # inst.tags is only a local cache. Try to avoid race conditions by getting the most up-to-date info possible.
        instanceIds = [instance.id for instance in instances]
        idsInUse = set()
        for inst in conn.get_only_instances(instance_ids=instanceIds):
            owner = inst.tags.get(self.userTagName, "")
            if owner:
                otherOwners.add(owner.split("_")[0])
                idsInUse.add(inst.id)

        tryOwnInstances, fallbackInstances = [], []
        capacity = 0
        for inst in instances:
            if inst.id not in idsInUse:
                if capacity < maxCapacity:
                    tryOwnInstances.append(inst.id)
                    inst.add_tag(self.userTagName, myTag)
                else:
                    fallbackInstances.append(inst)
                cores = self.getCores(inst, 1)
                capacity += cores

        return tryOwnInstances, fallbackInstances

    def getAlarmNames(self, instances):
        return ["stop-" + self.getInstanceName(iId) for iId in instances]

    def getInstanceName(self, instance):
        return instance if isinstance(instance, str) else instance.id

    def enableAlarmActions(self, alarmNames):
        conn = self.makeCloudwatchConnection()
        try:
            conn.enable_alarm_actions(alarmNames)
        except:
            pass

    def disableAlarmActions(self, alarmNames):
        conn = self.makeCloudwatchConnection()
        try:
            conn.disable_alarm_actions(alarmNames)
        except:
            plugins.printWarning("Could not disable CloudWatch alarms. Your user does not have permission for this.\n" +
                                 "The risk is that an instance will be shut down while you are using it, so it is suggested your request this permission from your administrator.\n")

    def takeOwnership(self, conn, instances, maxCapacity):
        myTag = getUserName() + "_" + plugins.startTimeString()
        otherOwners = set()
        tryOwnInstances, fallbackInstances = self.tryAddTag(conn, instances, maxCapacity, myTag, otherOwners)

        if not tryOwnInstances:
            return [], sorted(otherOwners)

        currTryInstances = tryOwnInstances
        ownInstances = []
        lostCapacity = 0
        time.sleep(0.5)  # add and check too close together makes racing more likely
        for _ in range(20):
            newInsts = conn.get_only_instances(instance_ids=currTryInstances)
            currTryInstances = []
            for inst in newInsts:
                owner = inst.tags.get(self.userTagName, "")
                if owner == myTag:
                    ownInstances.append(inst)
                elif owner:
                    # There's a race condition, somebody else grabbed it first, we drop it
                    otherOwners.add(owner.split("_")[0])
                    lostCapacity += self.getCores(inst, 1)
                else:
                    currTryInstances.append(inst.id)
            if currTryInstances:
                time.sleep(0.1)
            else:
                break

        def getOrigOrder(inst):
            return tryOwnInstances.index(inst.id)
        ownInstances.sort(key=getOrigOrder)

        if lostCapacity:
            fallbackInstances, fallbackOwners = self.takeOwnership(conn, fallbackInstances, lostCapacity)
            ownInstances += fallbackInstances
            otherOwners.update(fallbackOwners)

        return ownInstances, sorted(otherOwners)

    def releaseOwnership(self, machines):
        if machines:
            conn = self.makeEc2Connection()
            instanceIds = [machine.id for machine in machines]
            for inst in conn.get_only_instances(instance_ids=instanceIds):
                inst.remove_tag(self.userTagName)
            self.enableAlarmActions(self.getAlarmNames(instanceIds))

    def getCapacity(self):
        return self.capacity

    def slavesOnRemoteSystem(self):
        return True

    @classmethod
    def findSetUpDirectory(cls, dir):
        # Egg-link points at the Python package code, which may not be all of the checkout
        # Assume the setup.py is where it all starts
        while not os.path.isfile(os.path.join(dir, "setup.py")):
            newDir = os.path.dirname(dir)
            if newDir == dir:
                return
            else:
                dir = newDir
        return dir

    @classmethod
    def findVirtualEnvLinkedDirectories(cls, checkout):
        # "Egg-links" are something found in Python virtual environments
        # They are a sort of portable symbolic link, but of course tools like rsync don't understand them
        # Virtual environments can also point out another environment they were created from, which we may also need to copy
        linkedDirs = []
        realPythonPrefix = sys.real_prefix if hasattr(sys, "real_prefix") else sys.prefix
        for root, _, files in os.walk(checkout):
            for f in sorted(files):
                if f.endswith(".egg-link"):
                    path = os.path.join(root, f)
                    newDir = open(path).read().splitlines()[0].strip()
                    setupDir = cls.findSetUpDirectory(newDir)
                    if setupDir and setupDir not in linkedDirs:
                        linkedDirs.append(setupDir)
                elif f == "orig-prefix.txt":
                    path = os.path.join(root, f)
                    newDir = open(path).read().strip()
                    # Don't try to synch the system Python!
                    if newDir != realPythonPrefix and newDir not in linkedDirs:
                        linkedDirs.append(newDir)
        return linkedDirs

    def getDirectoriesForSynch(self):
        appDir = self.app.getDirectory()
        dirs = [appDir]
        if self.synchSlaveCode():
            dirs.append(plugins.installationRoots[0])
            personalLog = os.getenv("TEXTTEST_PERSONAL_LOG")
            if personalLog:
                dirs.append(personalLog)
        checkout = self.app.getCheckoutForDisplay()
        if checkout and not checkout.startswith(appDir):
            dirs.append(checkout)
            dirs += self.findVirtualEnvLinkedDirectories(checkout)
        return dirs

    def getMachine(self, jobId, includeReleased=False):
        machines = self.machines
        if includeReleased:
            machines = self.machines + self.releasedMachines
        for machine in machines:
            if machine.hasJob(jobId):
                return machine

    def setRemoteProcessId(self, jobId, remotePid):
        machine = self.getMachine(jobId)
        if machine:
            machine.setRemoteProcessId(jobId, remotePid)

    def getRemoteTestMachine(self, jobId):
        machine = self.getMachine(jobId)
        if machine:
            return machine.fullMachine

    def killRemoteProcess(self, jobId):
        machine = self.getMachine(jobId)
        if machine:
            return machine.killRemoteProcess(jobId, self.getSignal())
        else:
            return False, None

    def getJobFailureInfo(self, jobId):
        machine = self.getMachine(jobId, includeReleased=True)
        return machine.errorMessage if machine else ""

    def getStatusForAllJobs(self):
        procStatus = super(QueueSystem, self).getStatusForAllJobs()
        jobStatus = {}
        for machine in self.machines:
            machine.collectJobStatus(jobStatus, procStatus)
        self.cleanup()  # Try to release any machines we're not using
        return jobStatus

    def killJob(self, jobId):
        # ssh doesn't forward signals to remote processes.
        # We need to find it ourselves and send it explicitly. Can assume python exists remotely, but not much else.
        killed, localPid = self.killRemoteProcess(jobId)
        # Hack for self-tests. Shouldn't normally be needed. Need to kill the process locally as well when replaying CaptureMock.
        # Also kill the local process if we can't find the remote one for some reason...
        if localPid and (not killed or os.getenv("CAPTUREMOCK_MODE") == "0"):
            return super(QueueSystem, self).killJob(localPid)
        else:
            return True

    def synchSlaveCode(self):
        # If we're running our self-diagnostics on the slaves, make sure we copy our local code across and run it as the slaves
        return "xs" in self.app.inputOptions

    def getTextTestArgs(self):
        if self.synchSlaveCode():
            return super(QueueSystem, self).getTextTestArgs()
        else:
            return ["texttest"]  # Assume remote nodes are UNIX-based with TextTest installed centrally

    def submitSlaveJob(self, cmdArgs, *args):
        if self.nextMachineIndex >= len(self.machines):
            return None, "No more available machines to submit EC2 jobs to - existing jobs have failed"

        machine = self.machines[self.nextMachineIndex]
        submitter = super(QueueSystem, self).submitSlaveJob
        jobId = machine.submitSlave(submitter, cmdArgs, *args)
        if jobId is None:
            self.releaseOwnership([machine])
            self.machines.remove(machine)
            self.capacity = self.calculateCapacity()
            return self.submitSlaveJob(cmdArgs, *args)
        if machine.isFull():
            self.nextMachineIndex += 1
        return jobId, None


from .local import MachineInfo, getUserSignalKillInfo, getExecutionMachines
