
from capturepython import interceptPython
from capturecommand import interceptCommand

import os, sys

def makePathIntercept(cmd, interceptDir):
    if not os.path.isdir(interceptDir):
        os.makedirs(interceptDir)
    interceptName = os.path.join(interceptDir, cmd)
    executable = sys.executable
    if os.name == "nt":
        interceptName += ".py"
        executable = "python.exe"
    file = open(interceptName, "w")    
    file.write("#!" + executable + "\n")
    file.write("import capturemock; capturemock.interceptCommand()\n")
    file.close()
    if os.name == "nt":
        sourceFile = os.path.join(os.path.dirname(__file__), "python_script.exe")
        destFile = interceptName[:-3] + ".exe"
        shutil.copy(sourceFile, destFile)
    else:
        os.chmod(interceptName, 0775) # make executable 
