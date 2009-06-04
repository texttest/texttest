
import plugins, os

def makeScriptEngine(optionMap):
    if ApplicationEventResponder.scriptEngine:
        return ApplicationEventResponder.scriptEngine
    else:
        scriptEngine = _makeScriptEngine(optionMap)
        ApplicationEventResponder.scriptEngine = scriptEngine
        return scriptEngine

def _makeScriptEngine(optionMap):
    logger = plugins.getDiagnostics("usecase log")
    if optionMap.has_key("gx") or optionMap.has_key("g"):
        try:
            from gtkusecase import ScriptEngine
            return ScriptEngine(logger, enableShortcuts=True) 
        except ImportError:
            pass # Let the GUI itself print the error
    else:
        from usecase import ScriptEngine
        return ScriptEngine(logger)


# Compulsory responder to generate application events. Always present. See respond module
class ApplicationEventResponder(plugins.Responder):
    scriptEngine = None
    def notifyLifecycleChange(self, test, state, changeDesc):
        if changeDesc.find("saved") != -1 or changeDesc.find("recalculated") != -1 or changeDesc.find("marked") != -1:
            # don't generate application events when a test is saved or recalculated or marked...
            return
        eventName = "test " + test.uniqueName + " to " + changeDesc
        category = test.uniqueName
        timeDelay = self.getTimeDelay()
        self.scriptEngine.applicationEvent(eventName, category, timeDelay)
    def notifyAdd(self, test, initial):
        if initial and test.classId() == "test-case":
            eventName = "test " + test.uniqueName + " to be read"
            self.scriptEngine.applicationEvent(eventName, test.uniqueName)
    def notifyUniqueNameChange(self, test, newName):
        if test.classId() == "test-case":
            self.scriptEngine.applicationEventRename("test " + test.uniqueName + " to", "test " + newName + " to")

    def getTimeDelay(self):
        try:
            return int(os.getenv("TEXTTEST_FILEWAIT_SLEEP", 1))
        except ValueError:
            return 1
    def notifyAllRead(self, *args):
        self.scriptEngine.applicationEvent("all tests to be read")
    def notifyAllComplete(self):
        self.scriptEngine.applicationEvent("completion of test actions")
    def notifyCloseDynamic(self, test, name):
        self.scriptEngine.applicationEvent(name + " GUI to be closed")
