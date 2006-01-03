#!/usr/bin/env python

import sys, os
sys.path.insert(0, os.path.dirname(sys.argv[0]))

from engine import TextTest
program = TextTest()
program.run()
