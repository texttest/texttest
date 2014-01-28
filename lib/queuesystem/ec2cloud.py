
import local, plugins, os, sys

class QueueSystem(local.QueueSystem):
    def __init__(self, app):
        local.QueueSystem.__init__(self)
        self.nextMachineIndex = 0
        self.app = app
        self.machines = self.findMachines()
        self.remoteProcessInfo = {}
        
    def findMachines(self):
        region = self.app.getConfigValue("queue_system_ec2_region")
        try:
            import boto.ec2
        except ImportError:
            sys.stderr.write("Cannot run tests in EC2 cloud. You need to install Python's boto package for this to work.\n")
            return []
        conn = boto.ec2.connect_to_region(region)
        idToIp = self.findTaggedInstances(conn)
        if idToIp:
            return self.filterOnStatus(conn, idToIp)
        else:
            sys.stderr.write("Cannot run tests in EC2 cloud. No machines were found with 'texttest' in their name tag.\n")
            return []
        
    def findTaggedInstances(self, conn):
        idToIp = {}
        for inst in conn.get_only_instances():
            tag = inst.tags.get("Name", "")
            if "texttest" in tag:
                idToIp[inst.id] = inst.private_ip_address
        return idToIp
    
    def filterOnStatus(self, conn, idToIp):
        machines = []
        for stat in conn.get_all_instance_status(idToIp.keys()):
            if stat.instance_status.status == "ok":
                machines.append(idToIp.get(stat.id))
        return sorted(machines)
                    
    def getCapacity(self):
        return len(self.machines)
    
    def slavesOnRemoteSystem(self):
        return True
    
    def synchronisePath(self, path, machine):
        dirName = os.path.dirname(path)
        return self.app.copyFileRemotely(path, "localhost", dirName, machine)
    
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
        return dirs

    def getParents(self, dirs):
        parents = []
        for dir in dirs:
            parent = os.path.dirname(dir)
            if parent not in parents:
                parents.append(parent)
        return parents

    def synchroniseMachine(self, machine):
        dirs = self.getDirectoriesForSynch()
        parents = self.getParents(dirs)
        self.app.ensureRemoteDirExists(machine, *parents)
        for dir in dirs:
            self.synchronisePath(dir, machine)
            
    def getArg(self, args, flag):
        index = args.index(flag)
        return args[index + 1]
    
    def setRemoteProcessId(self, localPid, remotePid):
        if localPid in self.remoteProcessInfo:
            machine = self.remoteProcessInfo[localPid][0]
            self.remoteProcessInfo[localPid] = machine, remotePid
            
    def getRemoteTestMachine(self, localPid):
        if localPid in self.remoteProcessInfo:
            return self.remoteProcessInfo[localPid][0]
            
    def sendSignal(self, process, sig):
        # ssh doesn't forward signals to remote processes.
        # We need to find it ourselves and send it explicitly. Can assume python exists remotely, but not much else.
        localPid = str(process.pid)
        if localPid in self.remoteProcessInfo:
            machine, remotePid = self.remoteProcessInfo[localPid]
            if remotePid:
                cmdArgs = [ "python", "-c", "\"import os; os.kill(" + remotePid + ", " + str(sig) + ")\"" ]
                self.app.runCommandOn(machine, cmdArgs)
        # Hack for self-tests. Shouldn't normally be needed. Need to kill the process locally as well when replaying CaptureMock.
        if os.getenv("CAPTUREMOCK_MODE") == "0":
            local.QueueSystem.sendSignal(self, process, sig)
        
    def submitSlaveJob(self, cmdArgs, *args):
        ip = self.machines[self.nextMachineIndex]
        machine = "ec2-user@" + ip
        self.nextMachineIndex += 1
        if self.nextMachineIndex == len(self.machines):
            self.nextMachineIndex = 0
        try:
            self.synchroniseMachine(machine)
        except plugins.TextTestError, e:
            errorMsg = "Failed to synchronise files with EC2 instance with private IP address '" + ip + "'\n" + str(e) + "\n"
            return None, errorMsg
        
        ipAddress = self.getArg(cmdArgs, "-servaddr").split(":")[0]
        fileArgs = [ "-slavefilesynch", os.getenv("USER") + "@" + ipAddress ]
        remoteCmdArgs = self.app.getCommandArgsOn(machine, cmdArgs, agentForwarding=True) + fileArgs
        localPid, jobName = local.QueueSystem.submitSlaveJob(self, remoteCmdArgs, *args) 
        self.remoteProcessInfo[localPid] = (machine, None)
        return localPid, jobName
        
from local import MachineInfo, getUserSignalKillInfo, getExecutionMachines
