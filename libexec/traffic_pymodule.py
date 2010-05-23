
import sys

class ModuleProxy:
    def __init__(self, name, fileName):
        self.name = name
        self.__file__ = fileName
        self.realModule = None
        self.AttributeProxy(self, self).tryImport() # make sure "our module" can really be imported

    def __getattr__(self, attrname):
        return self.AttributeProxy(self, self, attrname).tryEvaluate()

    def getRealModule(self):
        if self.realModule is not None:
            return self.realModule
        import sys, os
        currDir = os.path.dirname(self.__file__)
        sys.path.remove(currDir)
        del sys.modules[self.name]
        exec "import " + self.name + " as moduleName"
        sys.modules[self.name] = self
        sys.path.insert(0, currDir)
        self.realModule = moduleName
        return moduleName

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
        def __init__(self, modOrObjProxy, moduleProxy, attributeName=None):
            self.modOrObjProxy = modOrObjProxy
            self.moduleProxy = moduleProxy
            self.attributeName = attributeName

        def argRepr(self):
            return self.modOrObjProxy.name + "." + self.attributeName

        def tryEvaluate(self):
            sock = self.createSocket()
            text = "SUT_PYTHON_ATTR:" + self.modOrObjProxy.name + ":SUT_SEP:" + self.attributeName
            sock.sendall(text)
            sock.shutdown(1)
            response = sock.makefile().read()
            if response:
                return self.handleResponse(response, "self.moduleProxy.InstanceProxy")
            else:
                return self

        def tryImport(self):
            sock = self.createSocket()
            text = "SUT_PYTHON_IMPORT:" + self.modOrObjProxy.name
            sock.sendall(text)
            sock.shutdown(1)
            response = sock.makefile().read()
            if response:
                self.handleResponse(response, "self.moduleProxy.InstanceProxy")

        def setValue(self, value):
            sock = self.createSocket()
            text = "SUT_PYTHON_SETATTR:" + self.modOrObjProxy.name + ":SUT_SEP:" + self.attributeName + \
                   ":SUT_SEP:" + repr(self.getArgForSend(value))
            sock.sendall(text)
            sock.shutdown(2)

        def __getattr__(self, name):
            return self.__class__(self.modOrObjProxy, self.moduleProxy, self.attributeName + "." + name).tryEvaluate()

        def __call__(self, *args, **kw):
            response = self.makeResponse(*args, **kw)
            if response:
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
                def NewStyleInstance(className, instanceName):
                    return self.makeInstance(className, instanceName, "self.moduleProxy.NewStyleInstanceProxy")
                return self.evaluateResponse(response, cls, Instance, NewStyleInstance)

        def makeInstance(self, className, instanceName, baseClass):
            exec "class " + className + "(" + baseClass + "): pass"
            classObj = eval(className)
            setattr(self.moduleProxy, className, classObj)
            return classObj(givenInstanceName=instanceName, moduleProxy=self.moduleProxy)

        def evaluateResponse(self, response, cls, Instance, NewStyleInstance):
            try:
                return eval(response)
            except NameError: # standard exceptions end up here
                module = response.split(".", 1)[0]
                if module == self.moduleProxy.name:
                    realModule = self.moduleProxy.getRealModule()
                    exec module + " = realModule"
                else:
                    exec "import " + module
                return eval(response)

        def createAndSend(self, *args, **kw):
            sock = self.createSocket()
            text = "SUT_PYTHON_CALL:" + self.modOrObjProxy.name + ":SUT_SEP:" + self.attributeName + \
                   ":SUT_SEP:" + repr(self.getArgsForSend(args)) + ":SUT_SEP:" + repr(kw)
            sock.sendall(text)
            return sock

        def getArgForSend(self, arg):
            class ArgWrapper:
                def __init__(self, arg, moduleProxy):
                    self.arg = arg
                    self.moduleProxy = moduleProxy
                def __repr__(self):
                    if isinstance(self.arg, self.moduleProxy.InstanceProxy):
                        return self.arg.name
                    elif isinstance(self.arg, self.moduleProxy.AttributeProxy):
                        return self.arg.argRepr()
                    elif isinstance(self.arg, list):
                        return repr([ ArgWrapper(subarg, self.moduleProxy) for subarg in self.arg ])
                    elif isinstance(self.arg, dict):
                        newDict = {}
                        for key, val in self.arg.items():
                            newDict[key] = ArgWrapper(val, self.moduleProxy)
                        return repr(newDict)
                    
                    out = repr(self.arg)
                    if "\\n" in out:
                        pos = out.find("'", 0, 2)
                        if pos != -1:
                            return out[:pos] + "''" + out[pos:].replace("\\n", "\n") + "''"
                        else:
                            pos = out.find('"', 0, 2)
                            return out[:pos] + '""' + out[pos:].replace("\\n", "\n") + '""'
                    else:
                        return out
            return ArgWrapper(arg, self.moduleProxy)
                    
        def getArgsForSend(self, args):
            return tuple(map(self.getArgForSend, args))

        def createSocket(self):
            import os, socket
            servAddr = os.getenv("TEXTTEST_MIM_SERVER")
            if servAddr:
                host, port = servAddr.split(":")
                serverAddress = (host, int(port))
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect(serverAddress)
                return sock



sys.modules[__name__] = ModuleProxy(__name__, __file__)
