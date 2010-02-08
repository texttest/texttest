
import sys

class ModuleOrObjectProxy:
    exceptionClass = None
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
        return self.handleResponse(response, self.__class__)

    def handleResponse(self, response, cls):
        if response.startswith("Exception: "):
            rest = response.replace("Exception: ", "")
            raise self.handleResponse(rest, self.exceptionClass)
        elif " Instance '" in response:
            words = response.split()
            className = words[0]
            setattr(self, className, cls)
            instanceName = words[-1][1:-1]
            return cls(instanceName)
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

class ExceptionProxy(ModuleOrObjectProxy, Exception):
    def __str__(self):
        return self.functionCall("__str__")

ModuleOrObjectProxy.exceptionClass = ExceptionProxy

sys.modules[__name__] = ModuleOrObjectProxy(__name__)
