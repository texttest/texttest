#!/usr/bin/env python3

import glob
import os.path
import pathlib
import platform
import sys
import sysconfig
import certifi
#import setuptools  # setuptools patches distutils, which needs to be finished before cx_Freeze to avoid https://bugs.python.org/issue23102

import cx_Freeze
from cx_Freeze import Executable, setup

from texttestlib.texttest_version import version


def get_non_python_libs():
    """Returns list of tuples containing extra dependencies required to run
    meld on current platform.
    Every pair corresponds to a single library file.
    First tuple item is path in local filesystem during build.
    Second tuple item correspond to path expected in meld installation
    relative to meld prefix.
    Note that for returned dynamic libraries and executables dependencies
    are expected to be resolved by caller, for example by cx_freeze.
    """
    local_bin = os.path.join(sys.prefix, "bin")

    inst_root = []  # local paths of files "to put at freezed root"
    inst_lib = []  # local paths of files "to put at freezed 'lib' subdir"

    if 'mingw' in sysconfig.get_platform():
        # dll imported by dll dependencies expected to be auto-resolved later
        inst_root = [os.path.join(local_bin, 'libgtksourceview-4-0.dll'),
                     os.path.join(local_bin, "diff.exe")]

        # required for communicating multiple instances
        inst_lib.append(os.path.join(local_bin, 'gdbus.exe'))

        # gspawn-helper is needed for Gtk.show_uri function
        if platform.architecture()[0] == '32bit':
            inst_lib.append(os.path.join(local_bin, 'gspawn-win32-helper.exe'))
        else:
            inst_lib.append(os.path.join(local_bin, 'gspawn-win64-helper.exe'))

    return [
        (f, os.path.basename(f)) for f in inst_root
    ] + [
        (f, os.path.join('lib', os.path.basename(f))) for f in inst_lib
    ]


gtk_data_dirs = [
    'etc/fonts',
    'etc/gtk-3.0',
    'lib/gdk-pixbuf-2.0',
    'lib/girepository-1.0',
    'share/fontconfig',
    'share/glib-2.0',
    'share/gtksourceview-4',
    'share/icons',
]

gtk_data_files = []
for data_dir in gtk_data_dirs:
    local_data_dir = os.path.join(sys.prefix, data_dir)

    for local_data_subdir, dirs, files in os.walk(local_data_dir):
        data_subdir = os.path.relpath(local_data_subdir, local_data_dir)
        gtk_data_files.append((
            os.path.join(data_dir, data_subdir),
            [os.path.join(local_data_subdir, file) for file in files],
        ))

manually_added_libs = {
    # add libgdk_pixbuf-2.0-0.dll manually to forbid auto-pulling of gdiplus.dll
    "libgdk_pixbuf-2.0-0.dll": os.path.join(sys.prefix, 'bin'),
    # librsvg is needed for SVG loading in gdkpixbuf
    "librsvg-2-2.dll": os.path.join(sys.prefix, 'bin'),
    "libcroco-0.6-3.dll": os.path.join(sys.prefix, 'bin'),
    "libsigsegv-2.dll": os.path.join(sys.prefix, 'bin'),
    "libwinpthread-1.dll": os.path.join(sys.prefix, 'bin'),
    }

for lib, possible_path in manually_added_libs.items():
    local_lib = os.path.join(possible_path, lib)
    if os.path.isfile(local_lib):
        gtk_data_files.append((os.path.dirname(lib), [local_lib]))

build_exe_options = {
    "includes": ['gi', '_sysconfigdata__win32_', 'xmlrpc.server'] if 'mingw' in sysconfig.get_platform() else ['gi', 'xmlrpc.server'],
    "excludes": ["tkinter"],
    "packages": ["gi", "weakref", "filecmp", "cgi", "certifi", "texttestlib", "yaml"],
    "include_files": get_non_python_libs(),
    "bin_excludes": list(manually_added_libs.keys()),
    "zip_exclude_packages": [],
    "zip_include_packages": ["*"],
}


# Create our registry key, and fill with install directory and exe
registry_table = [
    ('MeldKLM', 2, r'SOFTWARE\Meld', '*', None, 'TARGETDIR'),
    ('MeldInstallDir', 2, r'SOFTWARE\Meld', 'InstallDir', '[TARGETDIR]', 'TARGETDIR'),
    ('MeldExecutable', 2, r'SOFTWARE\Meld', 'Executable', '[TARGETDIR]Meld.exe', 'TARGETDIR'),
]

# Provide the locator and app search to give MSI the existing install directory
# for future upgrades
reg_locator_table = [
    ('MeldInstallDirLocate', 2, r'SOFTWARE\Meld', 'InstallDir', 0),
]
app_search_table = [('TARGETDIR', 'MeldInstallDirLocate')]

msi_data = {
    'Registry': registry_table,
    'RegLocator': reg_locator_table,
    'AppSearch': app_search_table,
}

bdist_msi_options = {
    "upgrade_code": "{1d303789-b4e2-4d6e-9515-c301e155cd50}",
    "data": msi_data,
    "add_to_path": True,
    "all_users": True
}

executable_options = {
    "script": "bin/meld",
    "icon": "data/icons/org.gnome.meld.ico",
}

texttest_executable_options = {
    "script": "bin/texttest",
    "icon": "data/icons/texttest-icon.ico",
}

texttestc_executable_options = {
    "script": "bin/texttest",
    "icon": "data/icons/texttest-icon.ico",
}

if 'mingw' in sysconfig.get_platform():
    executable_options.update({
         "base": "Win32GUI",  # comment to build console version to see stderr
         "targetName": "Meld.exe",
         "shortcutName": "Meld",
         "shortcutDir": "ProgramMenuFolder",
    })
    texttest_executable_options.update({
         "base": "Win32GUI",
         "targetName": "texttest.exe",
         "shortcutName": "Texttest",
         "shortcutDir": "ProgramMenuFolder",
    })
    texttestc_executable_options.update({
         "targetName": "texttestc.exe",
         "shortcutName": "Texttestc",
    })

# Copy conf.py in place if necessary
base_path = pathlib.Path(__file__).parent
conf_path = base_path / 'meld' / 'conf.py'

if not conf_path.exists():
    import shutil
    shutil.copyfile(conf_path.with_suffix('.py.in'), conf_path)

import meld.build_helpers  # noqa: E402
import meld.conf  # noqa: E402

 
setup(
    name="TextTest",
    version=version,
    description='Text-based functional testing tool including the Meld diff and merge tool',
    author='The TextTest project',
    author_email='texttest-users@lists.sourceforge.net',
    maintainer='Geoff Bache, Michael Behrisch',
    url='http://texttest.org',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: X11 Applications :: GTK',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU Lesser General Public License v2 or later (LGPLv2+)',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: Desktop Environment :: Gnome',
        'Topic :: Software Development',
    ],
    options={
        "build_exe": build_exe_options,
        "bdist_msi": bdist_msi_options,
        #  cx_freeze + bdist_dumb fails on non-empty prefix
        "install": {"prefix": "."},
        #  freezed binary doesn't use source files, they are only for humans
        "install_lib": {"compile": False},
    },
    executables=[
        Executable(**texttest_executable_options),
        Executable(**texttestc_executable_options),
        Executable(**executable_options)
    ],
    packages=[
        'meld',
        'meld.matchers',
        'meld.ui',
        'meld.vc',
        "texttestlib", "texttestlib.default", "texttestlib.queuesystem",
            "texttestlib.default.batch", "texttestlib.default.gtkgui", "texttestlib.default.knownbugs",
            "texttestlib.default.gtkgui.default_gui", "texttestlib.default.gtkgui.version_control"
    ],
    package_data={
        'meld': ['README', 'COPYING', 'NEWS'],
        "texttestlib": ["doc/ChangeLog", "doc/quick_start.txt", "doc/CREDITS.txt", "doc/MigrationNotes*", "doc/LICENSE.txt",
                                "etc/*", "etc/.*", "libexec/*", "log/*", "images/*.*", "images/retro/*"],
        "texttestlib.default.batch": ["testoverview_javascript/*"]
    },
    scripts=['bin/meld', "bin/texttest"],
    data_files=[
        ('share/man/man1',
         ['data/meld.1']
         ),
        ('share/doc/meld-' + meld.conf.__version__,
         ['COPYING', 'NEWS']
         ),
        ('share/meld/icons',
         glob.glob("data/icons/*.png") +
         glob.glob("data/icons/COPYING*")
         ),
        ('share/meld/styles',
         glob.glob("data/styles/*.xml")
         ),
        ('share/meld/ui',
         glob.glob("data/ui/*.ui") + glob.glob("data/ui/*.xml")
         ),
        ('etc',
         [certifi.where()]
         ),
    ] + gtk_data_files,
    cmdclass={
        "build_i18n": meld.build_helpers.build_i18n,
        "build_help": meld.build_helpers.build_help,
        "build_icons": meld.build_helpers.build_icons,
        "build_data": meld.build_helpers.build_data,
    }
)
