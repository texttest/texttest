
from . import texttest_version
import sys

def main():
    if sys.executable.endswith("pythonw.exe") or sys.stdout is None:
        # cx_Freeze sets sys.stdout and stderr to None leading to exceptions in print()
        sys.stdout = sys.stderr = open(os.devnull, "w")
    if getattr(sys, 'frozen', False):
        # Make sure it works with Capturemock - frozen modules don't read PYTHONPATH
        try:
            import capturemock
            capturemock.process_startup()  # doesn't do anything unless CAPTUREMOCK_PROCESS_START is set
        except Exception:
            pass    
    major, minor, micro = sys.version_info[:3]
    reqMajor, reqMinor, reqMicro = texttest_version.required_python_version
    if (major, minor, micro) >= texttest_version.required_python_version:
        from .engine import TextTest
        program = TextTest()
        program.run()
    else:
        strVersion = str(major) + "." + str(minor) + "." + str(micro)
        reqVersion = str(reqMajor) + "." + str(reqMinor) + "." + str(reqMicro)
        sys.stderr.write("Could not start TextTest due to Python version problems :\n" +
                        "TextTest " + texttest_version.version + " requires at least Python " +
                        reqVersion + ": found version " + strVersion + ".\n")
