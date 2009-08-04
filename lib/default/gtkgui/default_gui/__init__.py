"""
The default configuration's worth of action GUIs, implementing the interfaces in guiplugins
"""

# For backwards compatibility, don't require derived modules to know the internal structure here
from helpdialogs import *
from adminactions import *
from fileviewers import *
from selectandfilter import *
from runningactions import *
from changeteststate import *
from housekeeping import *

from default.gtkgui import guiplugins # from .. import guiplugins when we drop Python 2.4 support


class InteractiveActionConfig(guiplugins.InteractiveActionConfig):
    def getMenuNames(self):
        return [ "file", "edit", "view", "actions", "reorder", "help" ]

    def getInteractiveActionClasses(self, dynamic):
        classes = housekeeping.getInteractiveActionClasses(dynamic)
        if dynamic:
            classes += changeteststate.getInteractiveActionClasses()
        else:
            classes += adminactions.getInteractiveActionClasses()
            classes += runningactions.getInteractiveActionClasses()
            
        classes += helpdialogs.getInteractiveActionClasses()
        classes += fileviewers.getInteractiveActionClasses(dynamic)
        classes += selectandfilter.getInteractiveActionClasses(dynamic)
        return classes
