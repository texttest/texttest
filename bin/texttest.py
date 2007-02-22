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

from engine import TextTest
program = TextTest()
program.run()
