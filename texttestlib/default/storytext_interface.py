
import os
from texttestlib import plugins

try:
    import storytext
    applicationEvent = storytext.applicationEvent
    applicationEventRename = storytext.applicationEventRename
except ImportError:
    def applicationEventRename(*args, **kw):
        pass

    def applicationEvent(*args, **kw):
        pass


# Compulsory responder to generate application events. Always present. See respond module
class ApplicationEventResponder(plugins.Responder):
    def __init__(self, *args):
        plugins.Responder.__init__(self)
        applicationEvent("test configuration to be read", "read")
        self.rerunTests = []

    def notifyLifecycleChange(self, test, state, changeDesc):
        if changeDesc.find("approved") != -1 or changeDesc.find("recalculated") != -1 or changeDesc.find("marked") != -1:
            # don't generate application events when a test is approved or recalculated or marked...
            return
        eventName = "test " + test.uniqueName + " to " + changeDesc
        if test in self.rerunTests:
            eventName += " rerun"
        category = test.uniqueName
        timeDelay = self.getTimeDelay()
        applicationEvent(eventName, category + " lifecycle", ["lifecycle"], timeDelay)

    def notifyAdd(self, test, initial):
        if initial and test.classId() == "test-case":
            eventName = "test " + test.uniqueName + " to be read"
            applicationEvent(eventName, test.uniqueName, [test.uniqueName + " lifecycle", "read", "lifecycle"])

    def notifyUniqueNameChange(self, test, newName):
        if test.classId() == "test-case":
            applicationEventRename("test " + test.uniqueName + " to", "test " + newName + " to",
                                   test.uniqueName, newName)

    def notifyRerunTriggered(self, test):
        self.rerunTests.append(test)

    def getTimeDelay(self):
        try:
            return int(os.getenv("TEXTTEST_FILEWAIT_SLEEP", 1))
        except ValueError:  # pragma: no cover - pathological case
            return 1

    def notifyBackgroundActionCompleted(self, *args):
        applicationEvent("completion of background actions", "background")

    def notifyAllRead(self, *args):
        applicationEvent("all tests to be read", "read", ["lifecycle"])

    def notifyAllComplete(self):
        applicationEvent("completion of test actions", "lifecycle")

    def notifyCloseDynamic(self, testArg, name):
        applicationEvent(name + " GUI to be closed")
