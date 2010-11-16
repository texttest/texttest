
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

def loadRealSiteCustomize(): # pragma: no cover - coverage not set up yet
    # must do this before setting up coverage as real sitecustomize might
    # manipulate PYTHONPATH in such a way that coverage can be found
    import imp
    os.environ["TEXTTEST_SITECUSTOMIZE"] = "1" # Guard against double setup when in the self-tests
    myDir = os.path.dirname(__file__)
    pos = sys.path.index(myDir)
    try:
        try:
            modInfo = imp.find_module("sitecustomize", sys.path[pos + 1:])
            imp.load_module("sitecustomize", *modInfo)
        except ImportError:
            pass
    finally:
        if os.environ.has_key("TEXTTEST_SITECUSTOMIZE"):
            del os.environ["TEXTTEST_SITECUSTOMIZE"]

loadRealSiteCustomize() # pragma: no cover - coverage not set up yet
if not os.environ.has_key("TEXTTEST_SITECUSTOMIZE"): # pragma: no cover - coverage not set up yet
    trySetupCoverage()
    loadTestCustomize()
    trySetupCaptureMock() 
