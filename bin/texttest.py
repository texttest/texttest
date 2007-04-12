#!/usr/bin/env python

try:
    # For self-testing, make it easy to intercept methods by providing a natural point to do it
    # without screwing up the namespace
    import interceptor
except ImportError:
    pass

import sys, os

install_root = os.path.dirname(os.path.dirname(sys.argv[0]))
libDir = os.path.join(install_root, "lib")
if os.path.isdir(libDir):
    sys.path.insert(0, libDir)

import texttest_version

major, minor, micro = sys.version_info[:3]
reqMajor, reqMinor, reqMicro = texttest_version.required_python_version
if (major, minor, micro) >= texttest_version.required_python_version:
    from engine import TextTest
    program = TextTest()
    program.run()
else:
    strVersion = str(major) + "." + str(minor) + "." + str(micro)
    reqVersion = str(reqMajor) + "." + str(reqMinor) + "." + str(reqMicro)
    sys.stderr.write("Could not start TextTest due to Python version problems :\n" + \
                     "TextTest " + texttest_version.version + " requires at least Python " + \
                     reqVersion + ": found version " + strVersion + ".\n")
