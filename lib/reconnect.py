
import os, shutil, plugins
from sets import ImmutableSet

# Trawl around for a suitable dir to reconnect to if we haven't been told one
class ReconnectApp:
    def findReconnectDir(self, app, reconnectTmpInfo):
        fetchDir = app.getPreviousWriteDirInfo(reconnectTmpInfo)
        if not os.path.isdir(fetchDir):
            if fetchDir == reconnectTmpInfo or not reconnectTmpInfo:
                raise plugins.TextTestError, "Could not find TextTest temporary directory at " + fetchDir
            else:
                raise plugins.TextTestError, "Could not find TextTest temporary directory for " + reconnectTmpInfo + " at " + fetchDir

        rootDirs = app.getAllFileNames([ fetchDir ], "", self.getVersionSetTopDir)
        if len(rootDirs) == 0:
            raise plugins.TextTestError, "Could not find any runs matching " + app.description() + " under " + fetchDir

        for rootDirToCopy in reversed(rootDirs):
            appRoot = app.getFileName([ rootDirToCopy ], app.name, self.getVersionSetSubDir)
            if appRoot:
                return appRoot

        raise plugins.TextTestError, "Could not find an application directory matching " + app.description() + \
              " for any of the runs found under " + fetchDir
    def getVersionSetTopDir(self, fileName, *args):
        # Show the framework how to find the version list given a file name
        # If it doesn't match, return None
        parts = fileName.split(".")
        if len(parts) > 1 and parts[0] != "static_gui":
            # drop the run descriptor at the start and the date/time and pid at the end
            return ImmutableSet(parts[1:-2])
    def getVersionSetSubDir(self, fileName, stem):
        # Show the framework how to find the version list given a file name
        # If it doesn't match, return None
        parts = fileName.split(".")
        if stem == parts[0]:
            # drop the application at the start 
            return ImmutableSet(parts[1:])

class ReconnectTest(plugins.Action):
    def __init__(self, rootDirToCopy, fullRecalculate):
        self.rootDirToCopy = rootDirToCopy
        self.fullRecalculate = fullRecalculate
        self.diag = plugins.getDiagnostics("Reconnection")
    def __repr__(self):
        return "Reconnecting to"
    def __call__(self, test):
        newState = self.getReconnectState(test)
        self.describe(test, self.getStateText(newState))
        if newState:
            test.changeState(newState)
    def getReconnectState(self, test):
        reconnLocation = os.path.join(self.rootDirToCopy, test.getRelPath())
        self.diag.info("Reconnecting to test at " + reconnLocation)
        if os.path.isdir(reconnLocation):
            return self.getReconnectStateFrom(test, reconnLocation)
        else:
            return plugins.Unrunnable(briefText="no results", \
                                      freeText="No file found to load results from under " + reconnLocation)
    def getStateText(self, state):
        if state:
            return " (state " + state.category + ")"
        else:
            return " (recomputing)"
    def getReconnectStateFrom(self, test, location):
        stateToUse = None
        stateFile = os.path.join(location, "framework_tmp", "teststate")
        if os.path.isfile(stateFile):
            loaded, newState = test.getNewState(open(stateFile, "rU"))
            if loaded and self.modifyState(test, newState): # if we can't read it, recompute it
                stateToUse = newState

        if self.fullRecalculate or not stateToUse:
            self.copyFiles(test, location)

        return stateToUse    
    def copyFiles(self, test, reconnLocation):
        test.makeWriteDirectory()
        for file in os.listdir(reconnLocation):
            fullPath = os.path.join(reconnLocation, file)
            if os.path.isfile(fullPath):
                shutil.copyfile(fullPath, test.makeTmpFileName(file, forComparison=0))

    def modifyState(self, test, newState):            
        # State will refer to TEXTTEST_HOME in the original (which we may not have now,
        # and certainly don't want to save), try to fix this...
        newState.updateAbsPath(test.app.getDirectory())

        if self.fullRecalculate:                
            # Only pick up errors here, recalculate the rest. Don't notify until
            # we're done with recalculation.
            if newState.hasResults():
                # Also pick up execution machines, we can't get them otherwise...
                test.state.executionHosts = newState.executionHosts
                return False # don't actually change the state
            else:
                newState.lifecycleChange = "" # otherwise it's regarded as complete
                return True
        else:
            newState.updateTmpPath(os.path.dirname(self.rootDirToCopy))
            return True
    def setUpApplication(self, app):
        print "Reconnecting to test results in directory", self.rootDirToCopy

    def setUpSuite(self, suite):
        self.describe(suite)
