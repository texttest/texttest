"""
The default configuration's worth of action GUIs, implementing the interfaces in guiplugins
"""

try:
    # For backwards compatibility, don't require derived modules to know the internal structure here
    from .helpdialogs import *
    from .adminactions import *
    from .fileviewers import *
    from .fileproperties import *
    from .selectandfilter import *
    from .runningactions import *
    from .changeteststate import *
    from .housekeeping import *

    from ..guiplugins import InteractiveActionConfig as BaseInteractiveActionConfig
except ImportError as e:
    # Might want the default accelerators, don't crash if so
    if "No module named gtk" in str(e):
        class BaseInteractiveActionConfig:
            pass
    else:  # pragma: no cover - debugging aid only
        raise


class InteractiveActionConfig(BaseInteractiveActionConfig):
    def getMenuNames(self):
        return ["file", "edit", "view", "actions", "reorder", "help"]

    def getInteractiveActionClasses(self, dynamic):
        classes = housekeeping.getInteractiveActionClasses(dynamic)
        if dynamic:
            classes += changeteststate.getInteractiveActionClasses()
        else:
            classes += adminactions.getInteractiveActionClasses()

        classes += selectandfilter.getInteractiveActionClasses(dynamic)
        classes += runningactions.getInteractiveActionClasses(dynamic)
        classes += helpdialogs.getInteractiveActionClasses()
        classes += fileproperties.getInteractiveActionClasses()
        classes += fileviewers.getInteractiveActionClasses(dynamic)
        return classes

    def getDefaultAccelerators(self):
        dict = {}
        dict["quit"] = "<control>q"
        dict["select"] = "<control><alt>f"
        dict["filter"] = "<control><shift>f"
        dict["approve"] = "<control>s"
        dict["approve_as"] = "<control><alt>s"
        dict["copy"] = "<control>c"
        dict["kill"] = "<control>Delete"
        dict["remove_tests"] = "<control>Delete"
        dict["cut"] = "<control>x"
        dict["paste"] = "<control>v"
        dict["save_selection"] = "<control>d"
        dict["load_selection"] = "<control><shift>o"
        dict["reset"] = "<control>e"
        dict["reconnect"] = "<control><shift>r"
        dict["run"] = "<control>r"
        dict["rerun"] = "<control>r"
        dict["rename_test"] = "<control>m"
        dict["refresh"] = "F5"
        dict["record_use-case"] = "F9"
        dict["recompute_status"] = "F5"
        dict["add_test"] = "<control>n"
        dict["enter_failure_information"] = "<control>i"
        dict["move_down"] = "<control>Page_Down"
        dict["move_up"] = "<control>Page_Up"
        dict["move_to_first"] = "<control>Home"
        dict["move_to_last"] = "<control>End"
        dict["mark"] = "<control><shift>m"
        dict["unmark"] = "<control><shift>u"
        return dict
