"""
Queue system module for HashiCorp Nomad (https://www.nomadproject.io).

Each TextTest slave runs as a Nomad batch job with the raw_exec driver, talking to Nomad
via its HTTP API (see nomadapi.py). The standard Nomad environment variables NOMAD_ADDR
(default http://127.0.0.1:4646) and NOMAD_TOKEN are respected.

TextTest's generic queue system settings are mapped onto Nomad concepts as follows:

- the queue (default_queue, -q) is the Nomad node pool. If none is given, "default" is used.
- each resource (queue_system_resource, -R) is a job constraint, e.g.
  "meta.optimiser=true" becomes ${meta.optimiser} = "true". "!=" is also accepted, as is
  a bare attribute such as "meta.gpu", meaning only that it must be set. Anything that is
  not already of the form ${...} is wrapped in it.
- performance test machines, and the -m flag, constrain the node name (${node.unique.name}),
  which Nomad sets to the host name unless configured otherwise.
- queue_system_processes is the number of CPU cores to reserve. Nomad schedules CPU in MHz,
  so this is converted using the MHz per core of the smallest eligible node. Setting it to
  the core count of the worker machines therefore gives one test at a time per machine,
  provided the machines are of similar size.

The number of slaves (capacity) is how many such jobs fit on the eligible nodes of the node
pool at once. Resource constraints are not considered when calculating this, so if they
exclude some nodes, surplus jobs simply wait in Nomad until a slave becomes free.

Nomad doesn't forward the master's environment: as with Condor, list any
variables the slaves need in queue_system_environment. Slaves exit with a non-zero code
when tests fail, so Nomad will show such jobs as failed.
"""

import re
import secrets
import urllib.parse
from . import gridqueuesystem
# Not "from . import nomadapi", which bypasses the import hooks CaptureMock uses to intercept it in the self-tests
import texttestlib.queuesystem.nomadapi as nomadapi
from texttestlib import plugins

DEFAULT_NODE_POOL = "default"
TASK_NAME = "slave"
JOB_PREFIX = "texttest-"
STDERR_TAIL_BYTES = 4096


class QueueSystem(gridqueuesystem.QueueSystem):
    # Only the generic grid behaviour (e.g. fixing DISPLAY) is relevant: we don't need a
    # submission program on the PATH, nor a core file directory as Nomad runs each job
    # in its own allocation directory.
    def __init__(self, testOrApp):
        self.app = getattr(testOrApp, "app", testOrApp)
        # Identifies the jobs of this TextTest run, so that concurrent runs don't collide
        self.runId = secrets.token_hex(4)

    def getQueueSystemName(self):
        return "Nomad"

    def formatCommand(self, cmdArgs):
        return " ".join(cmdArgs)

    def getCapacity(self):
        processes = self.app.getConfigValue("queue_system_processes")
        nodePool = self.findDefaultNodePool()
        try:
            nodes = self.findEligibleNodes(nodePool)
        except nomadapi.NomadError as e:
            raise plugins.TextTestError("Cannot use Nomad: " + str(e))
        if not nodes:
            raise plugins.TextTestError("Cannot use Nomad: " + describeNoNodes(nodePool))
        cpu = self.getCpuRequest(nodes, processes)
        return sum((getAvailableCpu(node) // cpu for node in nodes))

    def findDefaultNodePool(self):
        queue = self.app.inputOptions.get("q")
        if not queue:
            queue = self.app.getConfigValue("default_queue")
        return self.getNodePool(queue)

    def getNodePool(self, queue):
        return queue if queue and queue != "texttest_default" else DEFAULT_NODE_POOL

    def findEligibleNodes(self, nodePool, machines=[]):
        nodes = nomadapi.get("/v1/nodes", resources="true")
        return [node for node in nodes if self.isEligible(node, nodePool, machines)]

    def isEligible(self, node, nodePool, machines):
        rawExec = (node.get("Drivers") or {}).get("raw_exec") or {}
        return node.get("Status") == "ready" and node.get("SchedulingEligibility") == "eligible" and \
            node.get("NodePool", DEFAULT_NODE_POOL) == nodePool and \
            rawExec.get("Detected", False) and rawExec.get("Healthy", False) and \
            (not machines or matchesMachine(node.get("Name", ""), machines))

    def getCpuRequest(self, nodes, processes):
        """ CPU to request in MHz, for the given number of cores on the smallest node """
        smallest = min(nodes, key=getAvailableCpu)
        cpuInfo = smallest["NodeResources"]["Cpu"]
        cores = cpuInfo.get("TotalCpuCores") or 1
        perCore = cpuInfo["CpuShares"] // cores
        return max(1, min(processes * perCore, getAvailableCpu(smallest)))

    def submitSlaveJob(self, cmdArgs, slaveEnv, logDir, submissionRules, jobType):
        jobId = self.makeJobId(submissionRules.getJobName())
        nodePool = self.getNodePool(submissionRules.findQueue())
        machines = submissionRules.findMachineList()
        try:
            nodes = self.findEligibleNodes(nodePool, machines)
            if not nodes:
                return None, self.getFullSubmitError(describeNoNodes(nodePool, machines), cmdArgs, jobType)
            job = self.makeJob(jobId, cmdArgs, slaveEnv, submissionRules, nodePool, machines, nodes)
            nomadapi.request("POST", "/v1/jobs", {"Job": job})
        except nomadapi.NomadError as e:
            return None, self.getFullSubmitError(str(e), cmdArgs, jobType)
        return jobId, None

    def makeJobId(self, jobName):
        return JOB_PREFIX + self.runId + "-" + re.sub("[^A-Za-z0-9_.-]", "_", jobName)

    def makeJob(self, jobId, cmdArgs, slaveEnv, submissionRules, nodePool, machines, nodes):
        constraints = [makeConstraint(resource) for resource in submissionRules.findResourceList()]
        if machines:
            constraints.append(makeMachineConstraint(machines))
        task = {"Name": TASK_NAME,
                "Driver": "raw_exec",
                "Config": {"command": cmdArgs[0], "args": cmdArgs[1:]},
                "Env": dict(slaveEnv),
                "Resources": {"CPU": self.getCpuRequest(nodes, submissionRules.processesNeeded)}}
        # TextTest handles failures and reruns itself, so Nomad shouldn't restart anything
        group = {"Name": TASK_NAME,
                 "Count": 1,
                 "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                 "ReschedulePolicy": {"Attempts": 0, "Unlimited": False},
                 "Tasks": [task]}
        return {"ID": jobId,
                "Name": submissionRules.getJobName(),
                "Type": "batch",
                "NodePool": nodePool,
                "Constraints": constraints,
                "TaskGroups": [group]}

    def getStatusForAllJobs(self):
        try:
            jobs = nomadapi.get("/v1/jobs", prefix=JOB_PREFIX + self.runId + "-")
        except nomadapi.NomadError:
            return None  # Nomad unavailable for the moment, don't update the job status
        statusDict = {}
        for job in jobs:
            if job["Status"] == "pending":
                statusDict[job["ID"]] = "PEND", "Waiting for a suitable Nomad node to become free"
            elif job["Status"] == "running":
                statusDict[job["ID"]] = "RUN", "Running"
        return statusDict

    def killJob(self, jobId):
        path = "/v1/job/" + urllib.parse.quote(jobId)
        try:
            if nomadapi.get(path)["Status"] == "dead":
                return False
            nomadapi.request("DELETE", path)
            return True
        except nomadapi.NomadError:
            return False

    def _getJobFailureInfo(self, jobId):
        try:
            allocations = nomadapi.get("/v1/job/" + urllib.parse.quote(jobId) + "/allocations")
        except nomadapi.NomadError as e:
            return "Could not get information about job " + jobId + " from Nomad: " + str(e)
        if not allocations:
            return "Nomad never placed job " + jobId + " on a node"
        return "\n".join((self.describeAllocation(alloc) for alloc in allocations))

    def describeAllocation(self, alloc):
        text = "Allocation " + alloc["ID"] + " on node " + alloc.get("NodeName", "?") + \
               " is " + alloc.get("ClientStatus", "?") + "\n"
        taskState = (alloc.get("TaskStates") or {}).get(TASK_NAME) or {}
        for event in taskState.get("Events") or []:
            text += "  " + event.get("Type", "") + ": " + event.get("DisplayMessage", "") + "\n"
        if taskState.get("Failed"):
            stderr = self.getStderrTail(alloc["ID"])
            if stderr:
                text += self.makeHeader("End of slave standard error") + stderr
        return text

    def getStderrTail(self, allocId):
        try:
            return nomadapi.request("GET", "/v1/client/fs/logs/" + allocId, parseJson=False,
                                    params={"task": TASK_NAME, "type": "stderr", "origin": "end",
                                            "offset": STDERR_TAIL_BYTES, "plain": "true"})
        except nomadapi.NomadError:
            return ""


def describeNoNodes(nodePool, machines=[]):
    text = "no ready nodes with the raw_exec driver in node pool '" + nodePool + "'"
    if machines:
        text += " among machines " + ",".join(machines)
    return text


def getAvailableCpu(node):
    total = node["NodeResources"]["Cpu"]["CpuShares"]
    reserved = ((node.get("ReservedResources") or {}).get("Cpu") or {}).get("CpuShares", 0)
    return total - reserved


def makeTarget(attribute):
    attribute = attribute.strip()
    return attribute if attribute.startswith("${") else "${" + attribute + "}"


def makeConstraint(resource):
    """ Translate a TextTest resource like 'meta.optimiser=true' into a Nomad constraint """
    match = re.match("^([^!=]+?)\\s*(!=|==|=)\\s*(.*)$", resource)
    if not match:
        return {"LTarget": makeTarget(resource), "Operand": "is_set"}
    attribute, operator, value = match.groups()
    if attribute.strip() == "hostname":  # from the -m flag
        return makeMachineConstraint(value.split("|"))
    return {"LTarget": makeTarget(attribute), "RTarget": value.strip(), "Operand": "!=" if operator == "!=" else "="}


def makeMachineConstraint(machines):
    return {"LTarget": "${node.unique.name}", "RTarget": makeMachinePattern(machines), "Operand": "regexp"}


def makeMachinePattern(machines):
    # Allow for short machine names matching fully qualified host names
    return "(?i)^(" + "|".join((re.escape(machine) for machine in machines)) + ")(\\..*)?$"


def matchesMachine(name, machines):
    return re.match(makeMachinePattern(machines), name) is not None


# Interpret what the limit signals mean...
def getUserSignalKillInfo(userSignalNumber, explicitKillMethod):
    return explicitKillMethod()


# Used by slave for producing performance data
class MachineInfo:
    def findActualMachines(self, machineOrGroup):
        return [machineOrGroup]

    def findResourceMachines(self, resource):
        return []

    def findRunningJobs(self, machine):
        return []


# Used by slave to find all execution machines
def getExecutionMachines():
    return [plugins.gethostname()]
