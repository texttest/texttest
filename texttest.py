#!/usr/bin/env python

try:
    # For self-testing, make it easy to intercept methods by providing a natural point to do it
    # without screwing up the namespace
    import interceptor
except ImportError:
    pass

import sys, os
sys.path.insert(0, os.path.dirname(sys.argv[0]))

from engine import TextTest
program = TextTest()
program.run()
