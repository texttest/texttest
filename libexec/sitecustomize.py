
import sys, os

def trySetupCoverage(): # pragma: no cover - can hardly measure coverage here :)
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
        # Capturemock uses Python 2.4 syntax, won't work on earlier versions
        from capturemock import interceptPython
        attributeNames = pythonVarStr.split(",")
        ignoreVar = os.getenv("TEXTTEST_MIM_PYTHON_IGNORE")
        ignoreCallers = []
        if ignoreVar:
            ignoreCallers = ignoreVar.split(",")
        interceptPython(attributeNames, ignoreCallers)
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
