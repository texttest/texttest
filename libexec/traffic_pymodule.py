
import sys

class ModuleProxy:
    def __init__(self, moduleName):
        self.moduleName = moduleName
        
    def __getattr__(self, name):
        def f(*args, **kw):
            return self.functionCall(name, *args, **kw)
        return f

    def functionCall(self, name, *args, **kw):
        sock = self.createAndSend(name, *args, **kw)
        sock.shutdown(1)
        response = sock.makefile().read()
        if response.startswith("Instance '"):
            return self.__class__(response.split()[-1][1:-1])
        else:
            return eval(response)

    def createAndSend(self, name, *args, **kw):
        sock = self.createSocket()
        text = "SUT_PYTHON_CALL:" + self.moduleName + ":SUT_SEP:" + name + ":SUT_SEP:" + repr(args) + ":SUT_SEP:" + repr(kw)
        sock.sendall(text)
        return sock
    
    def createSocket(self):
        import os, socket
        servAddr = os.getenv("TEXTTEST_MIM_SERVER")
        if servAddr:
            host, port = servAddr.split(":")
            serverAddress = (host, int(port))
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(serverAddress)
            return sock

sys.modules[__name__] = ModuleProxy(__name__)
