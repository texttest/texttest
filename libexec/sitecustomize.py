
import sys, os

def trySetupCoverage(): # pragma: no cover - can hardly measure coverage here :)
    # This check shouldn't really be there.
    # It's a workaround because coverage lives in an egg, and if it isn't installed in the default location
    # it won't have been set up yet here. Which means it needs to be linked in directly, which means
    # that e.g. Python 2.4 dumps core if it tries to execute this code.
    if sys.version_info[:2] >= (2, 6):
        try:
            import coverage
            coverage.process_startup() # doesn't do anything unless COVERAGE_PROCESS_START is set
        except Exception: 
            pass


def doInterceptions():
    try:
        # Generic file name to customize the behaviour of Python per test
        import testcustomize
    except ImportError:
        pass
    
    pythonVarStr = os.getenv("TEXTTEST_MIM_PYTHON")
    if pythonVarStr and sys.version_info[:2] >= (2, 4):
        # traffic_pymodule uses Python 2.4 syntax, won't work on earlier versions
        import traffic_pymodule
        attributeNames = pythonVarStr.split(",")
        ignoreVar = os.getenv("TEXTTEST_MIM_PYTHON_IGNORE")
        ignoreCallers = []
        if ignoreVar:
            ignoreCallers = ignoreVar.split(",")
        traffic_pymodule.interceptPython(attributeNames, ignoreCallers)
        del os.environ["TEXTTEST_MIM_PYTHON"] # Guard against double setup when in the self-tests

    # Need to load the "real" sitecustomize now
    import imp
    myDir = os.path.dirname(__file__)
    pos = sys.path.index(myDir)
    try:
        modInfo = imp.find_module("sitecustomize", sys.path[pos + 1:])
        imp.load_module("sitecustomize", *modInfo)
    finally:
        if pythonVarStr:
            os.environ["TEXTTEST_MIM_PYTHON"] = pythonVarStr

trySetupCoverage() # pragma: no cover - coverage not set up yet
doInterceptions() # pragma: no cover - coverage not set up yet
