#!/usr/bin/env python


from distutils.core import setup
from distutils.command.build_py import build_py
from distutils.command.install_scripts import install_scripts

import os
import shutil


class build_py_preserve_permissions(build_py):
    def copy_file(self, src, dst, preserve_mode=True, **kw):
        # Preserve mode of files under libexec
        if "libexec" in dst:
            return build_py.copy_file(self, src, dst, preserve_mode=True, **kw)
        else:
            return build_py.copy_file(self, src, dst, preserve_mode=preserve_mode, **kw)


# Lifted from bzr setup.py, use for Jython on Windows which has no native installer
class windows_install_scripts(install_scripts):
    """ Customized install_scripts distutils action.
    """

    def run(self):
        install_scripts.run(self)   # standard action
        src = os.path.join(self.install_dir, "texttest")
        dst = src + "c.py"
        if os.path.isfile(dst):
            os.remove(dst)
        os.rename(src, dst)
        with open(src + ".pyw", "w") as writeFile:
            with open(dst) as readFile:
                for line in readFile:
                    if line.startswith("#!"):
                        writeFile.write(line.replace("python.exe", "pythonw.exe"))
                    else:
                        writeFile.write(line)


command_classes = {"build_py": build_py_preserve_permissions}
if os.name == "nt":
    command_classes['install_scripts'] = windows_install_scripts

py_modules = []

packages = ["texttestlib", "texttestlib.default", "texttestlib.queuesystem",
            "texttestlib.default.batch", "texttestlib.default.gtkgui", "texttestlib.default.knownbugs",
            "texttestlib.default.gtkgui.default_gui", "texttestlib.default.gtkgui.version_control"]

package_data = {"texttestlib": ["doc/ChangeLog", "doc/quick_start.txt", "doc/CREDITS.txt", "doc/MigrationNotes*", "doc/LICENSE.txt",
                                "etc/*", "etc/.*", "libexec/*", "log/*", "images/*.*", "images/retro/*"],
                "texttestlib.default.batch": ["testoverview_javascript/*"]}
scripts = ["bin/texttest", "bin/filter_rundependent.py", "bin/filter_fpdiff.py"]
if os.name == "posix":
    scripts.append("texttestlib/libexec/interpretcore")

from texttestlib.texttest_version import version

setup(name='TextTest',
      version=version,
      author="Geoff Bache",
      author_email="geoff.bache@pobox.com",
      url="http://www.texttest.org",
      description="A tool for text-based Approval Testing",
      long_description="TextTest is a tool for text-based Approval Testing, which is an approach to acceptance testing/functional testing. In other words, it provides support for regression testing by means of comparing program output files against a specified approved versions of what they should look like.",
      packages=packages,
      package_dir={},
      py_modules=py_modules,
      package_data=package_data,
      classifiers=["Programming Language :: Python",
                   "License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)",
                   "Operating System :: OS Independent",
                   "Development Status :: 5 - Production/Stable",
                   "Environment :: X11 Applications :: GTK",
                   "Environment :: Win32 (MS Windows)",
                   "Environment :: Console",
                   "Intended Audience :: Developers",
                   "Intended Audience :: Information Technology",
                   "Topic :: Software Development :: Testing",
                   "Topic :: Software Development :: Libraries :: Python Modules"],
      scripts=scripts,
      cmdclass=command_classes
      )
