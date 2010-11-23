#!/usr/bin/env python
from distutils.core import setup
import os, shutil

def make_windows_script(src):
    outFile = open(src + ".py", "w")
    outFile.write("#!python.exe\nimport site\n\n")
    outFile.write(open(src).read())

if os.name == "nt":
    package_data= { "capturemock" : [ "python_script.exe" ]}
else:
    package_data = {}

if os.name == "nt":
    make_windows_script("capturemock_server")
    shutil.copyfile("capturemock/python_script.exe", "capturemock_server.exe")
    scripts=["capturemock_server.py", "capturemock_server.exe"]
else:
    scripts=["capturemock_server"]

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
                    "Topic :: Software Development :: Libraries :: Python Modules" ],
      scripts=scripts
      )
