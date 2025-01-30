
from . import texttest_version
import sys

def main():    
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
