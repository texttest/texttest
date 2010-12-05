
from capturepython import interceptPython
from capturecommand import interceptCommand

import os, sys, shutil, socket, config

class CaptureMockManager:
    fileContents = "import capturemock; capturemock.interceptCommand()\n"
    def __init__(self, rcFiles, interceptDir, mode, replayFile,
                 replayEditDir, recordFile, recordEditDir,
                 sutDirectory=os.getcwd(), environment=os.environ):
        self.active = mode != config.REPLAY_ONLY_MODE or replayFile is not None
        if self.active:
            # Environment which the server should get
            environment["CAPTUREMOCK_MODE"] = str(mode)
            if replayFile:
                environment["CAPTUREMOCK_FILE"] = replayFile
            from server import startServer
            self.serverProcess = startServer(rcFiles, mode, replayFile, replayEditDir,
                                             recordFile, recordEditDir, sutDirectory, environment)
            self.serverAddress = self.serverProcess.stdout.readline().strip()
            # And environment it shouldn't get...
            environment["CAPTUREMOCK_PROCESS_START"] = ",".join(rcFiles)
            environment["CAPTUREMOCK_SERVER"] = self.serverAddress
            if self.makePathIntercepts(rcFiles, interceptDir, replayFile, mode):
                environment["PATH"] = interceptDir + os.pathsep + environment.get("PATH", "")
        else:
            self.serverProcess = None

    def makeWindowsIntercept(self, interceptName):
        file = open(interceptName + ".py", "w")    
        file.write("#!python.exe\nimport site\n")
        file.write(self.fileContents)
        file.close()
        sourceFile = os.path.join(os.path.dirname(__file__), "python_script.exe")
        destFile = interceptName + ".exe"
        shutil.copy(sourceFile, destFile)

    def makePosixIntercept(self, interceptName):
        file = open(interceptName, "w")
        file.write("#!" + sys.executable + "\n")
        file.write(self.fileContents)
        file.close()
        os.chmod(interceptName, 0775) # make executable 

    def makePathIntercept(self, cmd, interceptDir):
        if not os.path.isdir(interceptDir):
            os.makedirs(interceptDir)
        interceptName = os.path.join(interceptDir, cmd)
        if os.name == "nt":
            self.makeWindowsIntercept(interceptName)
        else:
            self.makePosixIntercept(interceptName)

    def makePathIntercepts(self, rcFiles, interceptDir, replayFile, mode):
        rcHandler = config.RcFileHandler(rcFiles)
        commands = rcHandler.getIntercepts("command line")
        if replayFile and mode == config.REPLAY_ONLY_MODE:
            import replayinfo
            commands = replayinfo.filterCommands(commands, replayFile)
        for command in commands:
            self.makePathIntercept(command, interceptDir)
        return len(commands) > 0

    def terminate(self):
        if self.serverProcess:
            if self.serverAddress:
                from server import stopServer
                stopServer(self.serverAddress)
            self.writeServerErrors()
            self.serverProcess = None
        
    def writeServerErrors(self):
        err = self.serverProcess.communicate()[1]
        if err:
            sys.stderr.write("Error from CaptureMock Server :\n" + err)


manager = None
def capturemock(*args, **kw):
    global manager
    manager = CaptureMockManager(*args, **kw)
    return manager.active

def terminate():
    if manager:
        manager.terminate()
                            
def process_startup():
    rcFileStr = os.getenv("CAPTUREMOCK_PROCESS_START")
    if rcFileStr:
        import config
        rcFiles = rcFileStr.split(",")
        rcHandler = config.RcFileHandler(rcFiles)
        pythonAttrs = rcHandler.getIntercepts("python")
        replayFile = os.getenv("CAPTUREMOCK_FILE")
        mode = int(os.getenv("CAPTUREMOCK_MODE"))
        if replayFile and mode == config.REPLAY_ONLY_MODE:
            import replayinfo
            pythonAttrs = replayinfo.filterPython(pythonAttrs, replayFile)
        interceptPython(pythonAttrs, rcHandler)
