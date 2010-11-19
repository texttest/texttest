
import sys, os

def trySetupCoverage(): # pragma: no cover - can hardly measure coverage here :)
    try:
        import coverage
        coverage.process_startup() # doesn't do anything unless COVERAGE_PROCESS_START is set
    except Exception: 
        pass


def loadTestCustomize():
    try:
        # Generic file name to customize the behaviour of Python per test
        import testcustomize
    except ImportError:
        pass

def trySetupCaptureMock():
    pythonVarStr = os.getenv("TEXTTEST_MIM_PYTHON")
    if pythonVarStr and sys.version_info[:2] >= (2, 4):
        # Capturemock uses Python 2.4 syntax, won't work on earlier versions
        from capturemock import interceptPython
        attributeNames = pythonVarStr.split(",")
        ignoreVar = os.getenv("TEXTTEST_MIM_PYTHON_IGNORE")
        ignoreCallers = []
        if ignoreVar:
            ignoreCallers = ignoreVar.split(",")
        interceptPython(attributeNames, ignoreCallers)

def loadRealSiteCustomize(fileName): # pragma: no cover - coverage not set up yet
    # must do this before setting up coverage as real sitecustomize might
    # manipulate PYTHONPATH in such a way that coverage can be found
    import imp
    myDir = os.path.dirname(fileName)
    pos = sys.path.index(myDir)
    try:
        file, pathname, description = imp.find_module("sitecustomize", sys.path[pos + 1:])
        if os.path.basename(os.path.dirname(pathname)) == "traffic_intercepts":
            # For the self-tests: don't load another copy ourselves recursively
            loadRealSiteCustomize(pathname)
        else:
            imp.load_module("sitecustomize", file, pathname, description)
    except ImportError:
        pass

loadRealSiteCustomize(__file__) # pragma: no cover - coverage not set up yet
trySetupCoverage() # pragma: no cover - coverage not set up yet
loadTestCustomize() # pragma: no cover - coverage not set up yet
trySetupCaptureMock() # pragma: no cover - coverage not set up yet
