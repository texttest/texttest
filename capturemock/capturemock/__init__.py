
from capturepython import interceptPython
from capturecommand import interceptCommand

import os, sys, shutil, socket, config, filecmp

class CaptureMockReplayError(RuntimeError):
    pass

class CaptureMockManager:
    fileContents = "import capturemock; capturemock.interceptCommand()\n"
    def __init__(self):
        self.serverProcess = None
        self.serverAddress = None

    def isActive(self, mode, replayFile):
        return mode != config.REPLAY_ONLY_MODE or (replayFile is not None and os.path.isfile(replayFile))
        
    def start(self, mode, recordFile, replayFile=None, pythonAttrs=[], 
              recordEditDir=None, replayEditDir=None, rcFiles=[], interceptDir=None,
              sutDirectory=os.getcwd(), environment=os.environ, useServer=False):
        if self.isActive(mode, replayFile):
            # Environment which the server should get
            environment["CAPTUREMOCK_MODE"] = str(mode)
            if replayFile:
                environment["CAPTUREMOCK_FILE"] = replayFile
            rcHandler = config.RcFileHandler(rcFiles)
            commands = rcHandler.getIntercepts("command line")
            if useServer or len(commands) > 0: # command line has to go via server
                from server import startServer
                self.serverProcess = startServer(rcFiles, mode, replayFile, replayEditDir,
                                                 recordFile, recordEditDir, sutDirectory,
                                                 environment)
                self.serverAddress = self.serverProcess.stdout.readline().strip()
                # And environment it shouldn't get...
                environment["CAPTUREMOCK_PROCESS_START"] = ",".join(rcFiles)
                environment["CAPTUREMOCK_SERVER"] = self.serverAddress
                if self.makePathIntercepts(commands, interceptDir, replayFile, mode):
                    environment["PATH"] = interceptDir + os.pathsep + environment.get("PATH", "")
            else:
                pythonAttrs += rcHandler.getIntercepts("python")
                # not ready yet
                ## if replayFile and mode != config.RECORD_ONLY_MODE:
##                     import replayinfo
##                     pythonAttrs = replayinfo.filterPython(pythonAttrs, replayFile)
##                 interceptPython(pythonAttrs, rcHandler)
            return True
        else:
            return False
        
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

    def makePathIntercepts(self, commands, interceptDir, replayFile, mode):
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
def setUp(*args, **kw):
    global manager
    manager = CaptureMockManager()
    return manager.start(*args, **kw)

def terminate():
    if manager:
        manager.terminate()

# For use as a decorator in coded tests
class capturemock(object):
    def __init__(self, pythonAttrs=[], **kw):
        self.pythonAttrs = pythonAttrs
        if not isinstance(pythonAttrs, list):
            self.pythonAttrs = [ pythonAttrs ]
        self.kw = kw
        self.mode = int(os.getenv("CAPTUREMOCK_MODE", "0"))

    def __call__(self, func):
        from inspect import stack
        callingFile = stack()[1][1]
        fileNameRoot = self.getFileNameRoot(func.__name__, callingFile)
        if self.mode == config.RECORD_ONLY_MODE:
            recordFile = fileNameRoot
            replayFile = None
        else:
            replayFile = fileNameRoot
            recordFile = fileNameRoot + ".tmp"
        def wrapped_func(*funcargs, **funckw):
            try:
                setUp(self.mode, recordFile, replayFile, self.pythonAttrs, useServer=True, **self.kw)
                process_startup()
                func(*funcargs, **funckw)
                if replayFile:
                    self.checkMatching(recordFile, replayFile)
            finally:
                terminate()
        return wrapped_func

    def checkMatching(self, recordFile, replayFile):
        if filecmp.cmp(recordFile, replayFile, 0):
            os.remove(recordFile)
        else:
            # files don't match
            raise CaptureMockReplayError("Replayed calls do not match those recorded. " +
                                         "Either rerun with capturemock in record mode " +
                                         "or update the stored mock file by hand.")

    def getFileNameRoot(self, funcName, callingFile):
        dirName = os.path.join(os.path.dirname(callingFile), "capturemock")
        if not os.path.isdir(dirName):
            os.makedirs(dirName)
        return os.path.join(dirName, funcName.replace("test_", "") + ".mock")
    
                            
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
