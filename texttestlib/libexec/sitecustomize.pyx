
import sys
import os


def trySetupCoverage():  # pragma: no cover - can hardly measure coverage here :)
    try:
        import coverage
        coverage.process_startup()  # doesn't do anything unless COVERAGE_PROCESS_START is set
    except Exception:
        pass


def loadTestCustomize():
    try:
        # Generic file name to customize the behaviour of Python per test
        import testcustomize
    except ImportError:
        pass


def trySetupCaptureMock():
    try:
        import capturemock
        capturemock.process_startup()  # doesn't do anything unless CAPTUREMOCK_PROCESS_START is set
    except Exception:
        pass


def loadRealSiteCustomize(fileName):  # pragma: no cover - coverage not set up yet
    # must do this before setting up coverage as real sitecustomize might
    # manipulate PYTHONPATH in such a way that coverage can be found
    import importlib.util
    myDir = os.path.dirname(fileName)
    pos = sys.path.index(myDir)
    try:
        for finder in sys.meta_path:
            spec = finder.find_spec("sitecustomize", sys.path[pos + 1:])
            if spec is not None:
                break
        else:
            return
                
        if os.path.basename(os.path.dirname(spec.origin)) == "traffic_intercepts":
            # For the self-tests: don't load another copy ourselves recursively
            loadRealSiteCustomize(spec.origin)
        else:
            module = importlib.util.module_from_spec(spec)
            sys.modules["sitecustomize"] = module
            spec.loader.exec_module(module)
    except ImportError:
        pass


loadRealSiteCustomize(__file__)  # pragma: no cover - coverage not set up yet
trySetupCoverage()  # pragma: no cover - coverage not set up yet
loadTestCustomize()  # pragma: no cover - coverage not set up yet
trySetupCaptureMock()  # pragma: no cover - coverage not set up yet
