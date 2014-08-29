#!/usr/bin/env python


from distutils.core import setup
from distutils.command.build_py import build_py

class build_py_preserve_permissions(build_py):
    def copy_file(self, src, dst, preserve_mode=True, **kw):
        # Preserve mode of files under libexec
        if "libexec" in dst:
            return build_py.copy_file(self, src, dst, preserve_mode=True, **kw)
        else:
            return build_py.copy_file(self, src, dst, preserve_mode=preserve_mode, **kw)

import os, shutil

command_classes = {"build_py" : build_py_preserve_permissions }
packages = ["texttestlib", "texttestlib.default", "texttestlib.queuesystem",
            "texttestlib.default.batch", "texttestlib.default.gtkgui", "texttestlib.default.knownbugs",
            "texttestlib.default.gtkgui.default_gui", "texttestlib.default.gtkgui.version_control"]

package_data = {"texttestlib" : ["doc/ChangeLog", "doc/quick_start.txt", "doc/CREDITS.txt", "doc/MigrationNotes*", "doc/LICENSE.txt", 
                                 "etc/*", "etc/.*", "libexec/*", "log/*", "images/*" ], 
                "texttestlib.default.batch":["testoverview_javascript/*"]}
scripts = ["bin/texttest", "bin/filter_rundependent.py", "bin/filter_fpdiff.py", "texttestlib/libexec/interpretcore" ]

setup(name='TextTest',
      version="trunk",
      author="Geoff Bache",
      author_email="geoff.bache@pobox.com",
      url="http://www.texttest.org",
      description="A tool for text-based functional testing",
      long_description="",
      packages=packages,
      package_dir={},
      py_modules=[],
      package_data=package_data,
      classifiers=[ "Programming Language :: Python",
                    "License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)",
                    "Operating System :: OS Independent",
                    "Development Status :: 5 - Production/Stable",
                    "Environment :: X11 Applications :: GTK",
                    "Environment :: Win32 (MS Windows)",
                    "Environment :: Console",
                    "Intended Audience :: Developers",
                    "Intended Audience :: Information Technology",
                    "Topic :: Software Development :: Testing",
                    "Topic :: Software Development :: Libraries :: Python Modules" ],
      scripts=scripts,
      cmdclass=command_classes
      )
