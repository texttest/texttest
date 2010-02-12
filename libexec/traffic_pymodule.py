
import sys

class ModuleProxy:
    def __init__(self, name):
        self.name = name

    def __getattr__(self, attrname):
        return self.AttributeProxy(self, self, attrname).tryEvaluate()

    class InstanceProxy:
        moduleProxy = None
        def __init__(self, givenInstanceName=None, moduleProxy=None, *args, **kw):
            self.name = givenInstanceName
            if moduleProxy is not None:
                self.__class__.moduleProxy = moduleProxy
            if self.name is None:
                attrProxy = self.moduleProxy.AttributeProxy(self.moduleProxy, self.moduleProxy, self.__class__.__name__)
                response = attrProxy.makeResponse(*args, **kw)
                def Instance(className, instanceName):
                    return instanceName
                self.name = eval(response)

        def __getattr__(self, attrname):
            return self.moduleProxy.AttributeProxy(self, self.moduleProxy, attrname).tryEvaluate()

    class ExceptionProxy(InstanceProxy, Exception):
        def __str__(self):
            return self.__getattr__("__str__")()

        
    class AttributeProxy:
        def __init__(self, modOrObjProxy, moduleProxy, attributeName):
            self.modOrObjProxy = modOrObjProxy
            self.moduleProxy = moduleProxy
            self.attributeName = attributeName

        def tryEvaluate(self):
            sock = self.createSocket()
            text = "SUT_PYTHON_ATTR:" + self.modOrObjProxy.name + ":SUT_SEP:" + self.attributeName
            sock.sendall(text)
            sock.shutdown(1)
            response = sock.makefile().read()
            if response:
                return eval(response)
            else:
                return self

        def __getattr__(self, name):
            return self.__class__(self.modOrObjProxy, self.moduleProxy, self.attributeName + "." + name)

        def __call__(self, *args, **kw):
            response = self.makeResponse(*args, **kw)
            return self.handleResponse(response, "self.moduleProxy.InstanceProxy")

        def makeResponse(self, *args, **kw):
            sock = self.createAndSend(*args, **kw)
            sock.shutdown(1)
            return sock.makefile().read()
        
        def handleResponse(self, response, cls):
            if response.startswith("raise "):
                rest = response.replace("raise ", "")
                raise self.handleResponse(rest, "self.moduleProxy.ExceptionProxy")
            else:
                def Instance(className, instanceName):
                    # Call separate function to avoid exec problems
                    return self.makeInstance(className, instanceName, cls)
                return self.evaluateResponse(response, cls, Instance)

        def makeInstance(self, className, instanceName, baseClass):
            exec "class " + className + "(" + baseClass + "): pass"
            classObj = eval(className)
            setattr(self.moduleProxy, className, classObj)
            return classObj(instanceName, self.moduleProxy)

        def evaluateResponse(self, response, cls, Instance):
            try:
                return eval(response)
            except NameError: # standard exceptions end up here
                module = response.split(".", 1)[0]
                exec "import " + module
                return eval(response)

        def createAndSend(self, *args, **kw):
            sock = self.createSocket()
            text = "SUT_PYTHON_CALL:" + self.modOrObjProxy.name + ":SUT_SEP:" + self.attributeName + \
                   ":SUT_SEP:" + repr(self.getArgsForSend(args)) + ":SUT_SEP:" + repr(kw)
            sock.sendall(text)
            return sock

        def getArgsForSend(self, args):
            class ArgWrapper:
                def __init__(self, arg, moduleProxy):
                    self.arg = arg
                    self.moduleProxy = moduleProxy
                def __repr__(self):
                    if isinstance(self.arg, self.moduleProxy.InstanceProxy):
                        return self.arg.name
                    elif isinstance(self.arg, list):
                        return repr([ ArgWrapper(subarg, self.moduleProxy) for subarg in self.arg ])
                    out = repr(self.arg)
                    if "\\n" in out:
                        return "''" + out.replace("\\n", "\n") + "''"
                    else:
                        return out
            return tuple([ ArgWrapper(arg, self.moduleProxy) for arg in args ])

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
