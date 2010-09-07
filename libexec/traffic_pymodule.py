
import sys

class ModuleProxy:
    def __init__(self, name):
        self.name = name
        self.tryImport() # make sure "our module" can really be imported

    def __getattr__(self, attrname):
        return self.AttributeProxy(self, self, attrname).tryEvaluate()

    @staticmethod
    def createSocket():
        import os, socket
        servAddr = os.getenv("TEXTTEST_MIM_SERVER")
        if servAddr:
            host, port = servAddr.split(":")
            serverAddress = (host, int(port))
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(serverAddress)
            return sock

    def tryImport(self):
        sock = self.createSocket()
        text = "SUT_PYTHON_IMPORT:" + self.name
        sock.sendall(text)
        sock.shutdown(1)
        response = sock.makefile().read()
        if response:
            self.handleResponse(response, "self.InstanceProxy")

    def handleResponse(self, response, cls):
        if response.startswith("raise "):
            rest = response.replace("raise ", "")
            raise self.handleResponse(rest, "self.ExceptionProxy")
        else:
            def Instance(className, instanceName):
                # Call separate function to avoid exec problems
                return self.makeInstance(className, instanceName, cls)
            def NewStyleInstance(className, instanceName):
                return self.makeInstance(className, instanceName, "self.NewStyleInstanceProxy")
            return self.evaluateResponse(response, cls, Instance, NewStyleInstance)

    def makeInstance(self, className, instanceName, baseClass):
        exec "class " + className + "(" + baseClass + "): pass"
        classObj = eval(className)
        setattr(self, className, classObj)
        return classObj(givenInstanceName=instanceName, moduleProxy=self)

    @staticmethod
    def evaluateResponse(response, cls, Instance, NewStyleInstance):
        try:
            return eval(response)
        except NameError: # standard exceptions end up here
            module = response.split(".", 1)[0]
            exec "import " + module
            return eval(response)

    class InstanceProxy:
        moduleProxy = None
        def __init__(self, *args, **kw):
            self.name = kw.get("givenInstanceName")
            moduleProxy = kw.get("moduleProxy")
            if moduleProxy is not None:
                self.__class__.moduleProxy = moduleProxy
            if self.name is None:
                attrProxy = self.moduleProxy.AttributeProxy(self.moduleProxy, self.moduleProxy, self.__class__.__name__)
                response = attrProxy.makeResponse(*args, **kw)
                def Instance(className, instanceName):
                    return instanceName
                NewStyleInstance = Instance
                self.name = eval(response)

        def getRepresentationForSendToTrafficServer(self):
            return self.name

        def __getattr__(self, attrname):
            return self.moduleProxy.AttributeProxy(self, self.moduleProxy, attrname).tryEvaluate()

        def __setattr__(self, attrname, value):
            self.__dict__[attrname] = value
            if attrname != "name":
                self.moduleProxy.AttributeProxy(self, self.moduleProxy, attrname).setValue(value)

    class NewStyleInstanceProxy(InstanceProxy, object):
        # Must intercept these as they are defined in "object"
        def __repr__(self):
            return self.__getattr__("__repr__")()

        def __str__(self):
            return self.__getattr__("__str__")()
        
    class ExceptionProxy(InstanceProxy, Exception):
        def __str__(self):
            return self.__getattr__("__str__")()

        # Only used in Python >= 2.5 where Exception is a new-style class
        def __getattribute__(self, attrname):
            if attrname in [ "name", "moduleProxy", "__dict__", "__class__", "__getattr__" ]:
                return object.__getattribute__(self, attrname)
            else:
                return self.__getattr__(attrname)

    
    class AttributeProxy:
        def __init__(self, modOrObjProxy, moduleProxy, attributeName):
            self.modOrObjProxy = modOrObjProxy
            self.moduleProxy = moduleProxy
            self.attributeName = attributeName

        def getRepresentationForSendToTrafficServer(self):
            return self.modOrObjProxy.name + "." + self.attributeName

        def tryEvaluate(self):
            sock = self.moduleProxy.createSocket()
            text = "SUT_PYTHON_ATTR:" + self.modOrObjProxy.name + ":SUT_SEP:" + self.attributeName
            sock.sendall(text)
            sock.shutdown(1)
            response = sock.makefile().read()
            if response:
                return self.moduleProxy.handleResponse(response, "self.InstanceProxy")
            else:
                return self

        def setValue(self, value):
            sock = self.moduleProxy.createSocket()
            text = "SUT_PYTHON_SETATTR:" + self.modOrObjProxy.name + ":SUT_SEP:" + self.attributeName + \
                   ":SUT_SEP:" + repr(self.getArgForSend(value))
            sock.sendall(text)
            sock.shutdown(2)

        def __getattr__(self, name):
            return self.__class__(self.modOrObjProxy, self.moduleProxy, self.attributeName + "." + name).tryEvaluate()

        def __call__(self, *args, **kw):
            response = self.makeResponse(*args, **kw)
            if response:
                return self.moduleProxy.handleResponse(response, "self.InstanceProxy")

        def makeResponse(self, *args, **kw):
            sock = self.createAndSend(*args, **kw)
            sock.shutdown(1)
            return sock.makefile().read()
        
        def createAndSend(self, *args, **kw):
            sock = self.moduleProxy.createSocket()
            text = "SUT_PYTHON_CALL:" + self.modOrObjProxy.name + ":SUT_SEP:" + self.attributeName + \
                   ":SUT_SEP:" + repr(self.getArgsForSend(args)) + ":SUT_SEP:" + repr(self.getArgForSend(kw))
            sock.sendall(text)
            return sock

        def getArgForSend(self, arg):
            class ArgWrapper:
                def __init__(self, arg, moduleProxy):
                    self.arg = arg
                    self.moduleProxy = moduleProxy
                def __repr__(self):
                    if hasattr(self.arg, "getRepresentationForSendToTrafficServer"):
                        # We choose a long and obscure name to avoid accident clashes with something else
                        return self.arg.getRepresentationForSendToTrafficServer()
                    elif isinstance(self.arg, list):
                        return repr([ ArgWrapper(subarg, self.moduleProxy) for subarg in self.arg ])
                    elif isinstance(self.arg, dict):
                        newDict = {}
                        for key, val in self.arg.items():
                            newDict[key] = ArgWrapper(val, self.moduleProxy)
                        return repr(newDict)
                    else:
                        return repr(self.arg)
            return ArgWrapper(arg, self.moduleProxy)
                    
        def getArgsForSend(self, args):
            return tuple(map(self.getArgForSend, args))


# Workaround for stuff where we can't do setattr
class TransparentProxy:
    def __init__(self, obj):
        self.obj = obj
        
    def __getattr__(self, name):
        return getattr(self.obj, name)


class PartialModuleProxy(ModuleProxy):
    def tryImport(self):
        # We do this locally rather than remotely: if the module can't be found, there's not much point...
        try:
            exec "import " + self.name + " as realModule"
            self.realModule = realModule
        except ImportError:
            self.realModule = None

    def interceptAttributes(self, attrNames):
        if self.realModule:
            for attrName in attrNames:
                self.interceptAttribute(self, self.realModule, attrName)

    def interceptAttribute(self, proxyObj, realObj, attrName):
        parts = attrName.split(".", 1)
        currAttrName = parts[0]
        currAttrProxy = getattr(proxyObj, currAttrName)
        if len(parts) == 1:
            setattr(realObj, currAttrName, currAttrProxy)
        else:
            currRealAttr = getattr(realObj, currAttrName)
            try:
                self.interceptAttribute(currAttrProxy, currRealAttr, parts[1])
            except TypeError: # it's a builtin (assume setattr threw), so we hack around...
                realAttrProxy = TransparentProxy(currRealAttr)
                self.interceptAttribute(currAttrProxy, realAttrProxy, parts[1])
                setattr(realObj, currAttrName, realAttrProxy)


if __name__ != "traffic_pymodule":
    sys.modules[__name__] = ModuleProxy(__name__)
