
# This file (at the moment) has the sole purpose of specifying the texttest version number.
# It's in a separate file to make it easy to find.

import os
version = "master"

# Note: Decided it's not a good idea to require debug versions here. Even if we have Python 2.4.3 it's
# pretty likely 2.4.2 works OK unless we know otherwise. The interface shouldn't be different at least.

# Which python version do we require?

if os.name == "posix":
    required_python_version = (2, 4, 0)
else:
    # We depend on Python 2.5's ctypes module now to kill processes on Windows.
    # Python 2.5.0 known to have serious issues around subprocess handling.
    required_python_version = (2, 5, 1)
    
# Which pygtk version do we require?
required_pygtk_version = (2, 10, 0)
