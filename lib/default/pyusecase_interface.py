
import plugins, os, usecase

def makeScriptEngine(optionMap):
    if not usecase.scriptEngine:
        usecase.scriptEngine = _makeScriptEngine(optionMap)

def _makeScriptEngine(optionMap):
    if optionMap.has_key("gx") or optionMap.has_key("g"):
        try:
            from gtkusecase import ScriptEngine
            return ScriptEngine(enableShortcuts=True, uiMapFiles=plugins.findDataPaths([ "*.uimap" ])) 
        except ImportError:
            pass # Let the GUI itself print the error
    else:
        return usecase.ScriptEngine()


# Compulsory responder to generate application events. Always present. See respond module
class ApplicationEventResponder(plugins.Responder):
    def notifyLifecycleChange(self, test, state, changeDesc):
        if changeDesc.find("saved") != -1 or changeDesc.find("recalculated") != -1 or changeDesc.find("marked") != -1:
            # don't generate application events when a test is saved or recalculated or marked...
            return
        eventName = "test " + test.uniqueName + " to " + changeDesc
        category = test.uniqueName
        timeDelay = self.getTimeDelay()
        usecase.applicationEvent(eventName, category + " lifecycle", [ "lifecycle" ], timeDelay)
        
    def notifyAdd(self, test, initial):
        if initial and test.classId() == "test-case":
            eventName = "test " + test.uniqueName + " to be read"
            usecase.applicationEvent(eventName, test.uniqueName, [ test.uniqueName + " lifecycle", "read", "lifecycle" ])

    def notifyUniqueNameChange(self, test, newName):
        if test.classId() == "test-case":
            usecase.applicationEventRename("test " + test.uniqueName + " to", "test " + newName + " to",
                                                     test.uniqueName, newName)

    def getTimeDelay(self):
        try:
            return int(os.getenv("TEXTTEST_FILEWAIT_SLEEP", 1))
        except ValueError: # pragma: no cover - pathological case
            return 1

    def notifyAllRead(self, *args):
        usecase.applicationEvent("all tests to be read", "read", [ "lifecycle" ])

    def notifyAllComplete(self):
        usecase.applicationEvent("completion of test actions", "lifecycle")

    def notifyCloseDynamic(self, test, name):
        usecase.applicationEvent(name + " GUI to be closed")
