
import sys

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


def trySetupTraffic():
    try:
        # partial traffic interception?
        import traffic_customize
    except ImportError:
        pass


def restoreOriginal():
    # Need to load the "real" sitecustomize now
    import os, sys
    # Can't store local variables beyond a module wipe
    sys.currDir = os.path.dirname(__file__)
    sys.path.remove(sys.currDir)
    del sys.modules["sitecustomize"]
    try:
        import sitecustomize
    finally:
        import sys # local variables all wiped when we invalidate the module...
        sys.path.insert(0, sys.currDir)
        delattr(sys, "currDir")

if not hasattr(sys, "currDir"): # pragma: no cover - coverage not set up yet
    # Can get called by the code above when TextTest testing itself
    # Don't allow ourselves to be restored as the 'original'
    trySetupCoverage()
    trySetupTraffic()
    restoreOriginal()
