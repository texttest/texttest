#!/usr/bin/env python2
from distutils.core import setup
import os

os.chdir("../lib")
setup(name='logconfiggen',
      version='0.1',
      py_modules=["logconfiggen"]
      )
