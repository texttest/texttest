#!/usr/bin/env python
from distutils.core import setup
import os

if os.name == "nt":
    package_data= { "capturemock" : [ "python_script.exe" ]}
else:
    package_data = {}

setup(name='CaptureMock',
      version="0.1",
      author="Geoff Bache",
      author_email="geoff.bache@pobox.com",
      url="http://www.texttest.org/index.php?page=faking_it_with_texttest",
      description="A tool for creating mocks via a capture-replay style approach",
      long_description='Breaking away from TextTest and coming soon',
      packages=["capturemock"],
      py_modules=["ordereddict"],
      package_data=package_data,
      classifiers=[ "Programming Language :: Python",
                    "License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)",
                    "Operating System :: OS Independent",
                    "Development Status :: 5 - Production/Stable",
                    "Environment :: Console",
                    "Intended Audience :: Developers",
                    "Intended Audience :: Information Technology",
                    "Topic :: Software Development :: Testing",
                    "Topic :: Software Development :: Libraries :: Python Modules" ]
      )
