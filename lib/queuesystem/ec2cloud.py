
import local, plugins, signal
import time, os, sys
from threading import Thread
from Queue import Queue
from fnmatch import fnmatch

class Ec2Machine:
    def __init__(self, ipAddress, cores, synchDirs, app):
        self.ip = ipAddress
        self.fullMachine = "ec2-user@" + self.ip
        self.cores = cores 
        self.synchDirs = synchDirs
        self.app = app
        self.remoteProcessInfo = {}
        self.thread = Thread(target=self.runThread)
        self.queue = Queue()
        self.errorMessage = ""
        
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
    
    def setRemoteProcessId(self, jobId, remotePid):
        localPid, _ = self.remoteProcessInfo[jobId]
        self.remoteProcessInfo[jobId] = localPid, remotePid
                
    def synchronise(self):
        parents = self.getParents(self.synchDirs)
        self.app.ensureRemoteDirExists(self.fullMachine, *parents)
        for dir in self.synchDirs:
            if not self.errorMessage:
                self.synchronisePath(dir)
            
    def synchronisePath(self, path):
        dirName = os.path.dirname(path)
        self.synchProc = self.app.getRemoteCopyFileProcess(path, "localhost", dirName, self.fullMachine)
        self.synchProc.wait()
        self.synchProc = None

    def runThread(self):
        try:
            self.synchronise()
        except plugins.TextTestError, e:
            self.errorMessage = "Failed to synchronise files with EC2 instance with private IP address '" + self.ip + "'\n" + str(e) + "\n"
            
        if self.errorMessage:
            return
        
        while True:
            jobId, submitCallable = self.queue.get()
            if jobId is None:
                return
            localPid, _ = submitCallable()
            self.remoteProcessInfo[jobId] = localPid, None
            
    def cleanup(self):
        if self.thread.isAlive():
            self.queue.put((None, None))
            self.thread.join()

    def submitSlave(self, submitter, cmdArgs, fileArgs, *args):
        jobId = self.getNextJobId()
        self.remoteProcessInfo[jobId] = None, None
        if not self.thread.isAlive():
            self.thread.start()
        remoteCmdArgs = self.app.getCommandArgsOn(self.fullMachine, cmdArgs, agentForwarding=True) + fileArgs
        self.queue.put((jobId, plugins.Callable(submitter, remoteCmdArgs, *args)))
        return jobId
    
    def killRemoteProcess(self, jobId, sig):
        if self.synchProc:
            self.errorMessage = "Terminated test during file synchronisation"
            self.synchProc.send_signal(signal.SIGTERM)
            return True, None
        # ssh doesn't forward signals to remote processes.
        # We need to find it ourselves and send it explicitly. Can assume python exists remotely, but not much else.
        localPid, remotePid = self.waitForRemoteProcessId(jobId)
        if remotePid:
            cmdArgs = [ "python", "-c", "\"import os; os.kill(" + remotePid + ", " + str(sig) + ")\"" ]
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
            for jobId, (localPid, _) in self.remoteProcessInfo.items():
                if localPid:
                    if localPid in procStatus:
                        jobStatus[jobId] = procStatus[localPid]
                else:
                    jobStatus[jobId] = "SYNCH", "Synchronizing data with " + self.fullMachine


class QueueSystem(local.QueueSystem):
    instanceTypeInfo = { "8xlarge" : 32, "4xlarge": 16, "2xlarge" : 8, "xlarge" : 4, "large" : 2, "medium" : 1 }
    def __init__(self, app):
        local.QueueSystem.__init__(self)
        self.nextMachineIndex = 0
        self.app = app
        self.fileArgs = []
        machineData = self.findMachines()
        synchDirs = self.getDirectoriesForSynch()
        self.machines = [ Ec2Machine(m, self.instanceTypeInfo.get(instanceType, 1), synchDirs, app) for m, instanceType in machineData ]
        self.capacity = sum((m.cores for m in self.machines))
        
    def findMachines(self):
        region = self.app.getConfigValue("queue_system_ec2_region")
        try:
            import boto.ec2
        except ImportError:
            sys.stderr.write("Cannot run tests in EC2 cloud. You need to install Python's boto package for this to work.\n")
            return []
        conn = boto.ec2.connect_to_region(region)
        instanceTags = self.app.getConfigValue("queue_system_resource")
        idToIp = self.findTaggedInstances(conn, instanceTags)
        if idToIp:
            machines = self.filterOnStatus(conn, idToIp)
            if not machines:
                sys.stderr.write("Cannot run tests in EC2 cloud. " + str(len(idToIp)) + " instances were found matching '" + \
                                 ",".join(instanceTags) + "' in their tags, but none are currently up.\n")
            return machines
        else:
            sys.stderr.write("Cannot run tests in EC2 cloud. No instances were found matching '" + ",".join(instanceTags) + "' in their tags.\n")
            return []
        
    def cleanup(self):
        for machine in self.machines:
            machine.cleanup()
            
    def matchesTag(self, instanceTags, tagName, tagPattern):
        tagValueForInstance = instanceTags.get(tagName, "")
        return fnmatch(tagValueForInstance, tagPattern)
        
    def findTaggedInstances(self, conn, instanceTags):
        idToIp = {}
        parsedTags = [ tag.split("=", 1) for tag in instanceTags ]
        for inst in conn.get_only_instances():
            if all((self.matchesTag(inst.tags, tagName, tagPattern) for tagName, tagPattern in parsedTags)):
                idToIp[inst.id] = inst.private_ip_address, inst.instance_type.split(".")[-1]
        return idToIp
    
    def getSortKey(self, info):
        cores = self.instanceTypeInfo.get(info[1], 0)
        return -cores, info[0]
    
    def filterOnStatus(self, conn, idToIp):
        machines = []
        for stat in conn.get_all_instance_status(idToIp.keys()):
            if stat.instance_status.status in [ "ok", "initializing" ]:
                machines.append(idToIp.get(stat.id))
                
        machines.sort(key=self.getSortKey)
        return machines
                    
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
        dirs = []
        for i, instRoot in enumerate(plugins.installationRoots):
            if i == 0 or not instRoot.startswith(plugins.installationRoots[0]):
                dirs.append(instRoot)
        appDir = self.app.getDirectory()
        dirs.append(appDir)
        checkout = self.app.checkout
        if checkout and not checkout.startswith(appDir):
            dirs.append(checkout)
            dirs += self.findVirtualEnvLinkedDirectories(checkout)
        return dirs
            
    def getArg(self, args, flag):
        index = args.index(flag)
        return args[index + 1]
    
    def getMachine(self, jobId):
        for machine in self.machines:
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
        machine = self.getMachine(jobId)
        return machine.errorMessage if machine else ""
    
    def getStatusForAllJobs(self):
        procStatus = super(QueueSystem, self).getStatusForAllJobs()
        jobStatus = {}
        for machine in self.machines:
            machine.collectJobStatus(jobStatus, procStatus)
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
                            
    def getFileArgs(self, cmdArgs):
        if not self.fileArgs:
            ipAddress = self.getArg(cmdArgs, "-servaddr").split(":")[0]
            self.fileArgs = [ "-slavefilesynch", os.getenv("USER", os.getenv("USERNAME")) + "@" + ipAddress ]
        return self.fileArgs
        
    def submitSlaveJob(self, cmdArgs, *args):
        machine = self.machines[self.nextMachineIndex]
        submitter = super(QueueSystem, self).submitSlaveJob
        jobId = machine.submitSlave(submitter, cmdArgs, self.getFileArgs(cmdArgs), *args)
        if machine.isFull():
            self.nextMachineIndex += 1
        if self.nextMachineIndex == len(self.machines):
            self.nextMachineIndex = 0
        return jobId, None

        
from local import MachineInfo, getUserSignalKillInfo, getExecutionMachines
