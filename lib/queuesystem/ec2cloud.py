
import local, plugins, os, sys

class QueueSystem(local.QueueSystem):
    def __init__(self, app):
        local.QueueSystem.__init__(self)
        self.nextMachineIndex = 0
        self.app = app
        self.machines = self.findMachines()
        
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
        
        remoteCmdArgs = self.app.getCommandArgsOn(machine, cmdArgs)
        return local.QueueSystem.submitSlaveJob(self, remoteCmdArgs, *args) 
        
from local import MachineInfo, getUserSignalKillInfo, getExecutionMachines
