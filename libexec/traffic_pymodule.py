
import sys

class ModuleOrObjectProxy:
    AttributeProxy = None
    def __init__(self, modOrObjName):
        self.modOrObjName = modOrObjName
        
    def __getattr__(self, name):
        return self.AttributeProxy(self, name)
        

class AttributeProxy:
    ModuleOrObjectProxy = None
    ExceptionProxy = None
    def __init__(self, modOrObjProxy, attributeName):
        self.modOrObjProxy = modOrObjProxy
        self.attributeName = attributeName
        
    def __getattr__(self, name):
        return self.__class__(self.modOrObjProxy, self.attributeName + "." + name)

    def __call__(self, *args, **kw):
        sock = self.createAndSend(*args, **kw)
        sock.shutdown(1)
        response = sock.makefile().read()
        return self.handleResponse(response, self.ModuleOrObjectProxy)

    def handleResponse(self, response, cls):
        if response.startswith("Exception: "):
            rest = response.replace("Exception: ", "")
            raise self.handleResponse(rest, self.ExceptionProxy)
        elif " Instance '" in response:
            words = response.split()
            className = words[0]
            setattr(self.modOrObjProxy, className, cls)
            instanceName = words[-1][1:-1]
            return cls(instanceName)
        else:
            return eval(response)

    def createAndSend(self, *args, **kw):
        sock = self.createSocket()
        text = "SUT_PYTHON_CALL:" + self.modOrObjProxy.modOrObjName + ":SUT_SEP:" + self.attributeName + ":SUT_SEP:" + repr(args) + ":SUT_SEP:" + repr(kw)
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
    AttributeProxy = None
    def __str__(self):
        return self.AttributeProxy(self, "__str__")()

ModuleOrObjectProxy.AttributeProxy = AttributeProxy
AttributeProxy.ModuleOrObjectProxy = ModuleOrObjectProxy
AttributeProxy.ExceptionProxy = ExceptionProxy
ExceptionProxy.AttributeProxy = AttributeProxy

sys.modules[__name__] = ModuleOrObjectProxy(__name__)
