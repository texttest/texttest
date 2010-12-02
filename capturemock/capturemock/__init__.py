
from capturepython import interceptPython
from capturecommand import interceptCommand

import os, sys, shutil

fileContents = "import capturemock; capturemock.interceptCommand()\n"   

def makeWindowsIntercept(interceptName):
    file = open(interceptName + ".py", "w")    
    file.write("#!python.exe\nimport site\n")
    file.write(fileContents)
    file.close()
    sourceFile = os.path.join(os.path.dirname(__file__), "python_script.exe")
    destFile = interceptName + ".exe"
    shutil.copy(sourceFile, destFile)

def makePosixIntercept(interceptName):
    file = open(interceptName, "w")
    file.write("#!" + sys.executable + "\n")
    file.write(fileContents)
    file.close()
    os.chmod(interceptName, 0775) # make executable 
    
def makePathIntercept(cmd, interceptDir):
    if not os.path.isdir(interceptDir):
        os.makedirs(interceptDir)
    interceptName = os.path.join(interceptDir, cmd)
    if os.name == "nt":
        makeWindowsIntercept(interceptName)
    else:
        makePosixIntercept(interceptName)

def makePathIntercepts(rcFiles, interceptDir, replayFile, mode):
    import config
    rcHandler = config.RcFileHandler(rcFiles)
    commands = rcHandler.getIntercepts("command line")
    if replayFile and mode == config.REPLAY_ONLY_MODE:
        import replayinfo
        commands = replayinfo.filterCommands(commands, replayFile)
    for command in commands:
        makePathIntercept(command, interceptDir)
    return len(commands) > 0

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
