
"""
Generic module broken out from guiplugins. Contains utility code that can be
called from anywhere in the gtkgui package
"""
import os
import operator
import locale
from texttestlib import plugins
from copy import copy
from functools import reduce

# Gtk.accelerator_valid appears utterly broken on Windows


def windowsAcceleratorValid(key, mod):
    name = Gtk.accelerator_name(key, mod)
    return len(name) > 0 and name != "VoidSymbol"


try:
    from gi.repository import Gtk
    if os.name == "nt":
        Gtk.accelerator_valid = windowsAcceleratorValid
except ImportError:
    pass  # We might want to document the config entries, silly to fail on lack of GTK...


def createApplicationEvent(name, category, **kw):
    try:
        from storytext import applicationEvent
        # Everything that comes from here is to do with editing files in external programs
        applicationEvent(name, category, **kw)
    except ImportError:
        pass


guiConfig = None


class Utf8Converter:
    langVars = ('LC_ALL', 'LC_CTYPE', 'LANG', 'LANGUAGE')

    def __init__(self):
        self.encodings = self.getEncodings()

    def getEncodings(self):
        encodings = ['utf-8']
        localeEncoding = locale.getdefaultlocale()[1]
        if localeEncoding and not localeEncoding in encodings:
            encodings.insert(0, localeEncoding)
        return encodings

    def convert(self, text, extraEncodingLookup=None):
        unicodeInfo = self.decodeText(text, extraEncodingLookup)
        return unicodeInfo.encode('utf-8', 'replace')

    def getExtraEncodings(self, extraEncodingLookup):
        # Calling undocumented method to save copying it, best not to crash if it has been renamed.
        # Don't do this on Windows, the variables concerned don't apply there anyway
        if extraEncodingLookup and os.name != "nt" and hasattr(locale, "_parse_localename"):
            # Copied from locale.getdefaultlocale, would be nice if we could actually call this code
            for variable in self.langVars:
                localename = extraEncodingLookup(variable)
                if localename:
                    if variable == 'LANGUAGE':
                        localename = localename.split(':')[0]
                    extraEncoding = locale._parse_localename(localename)[1]
                    if extraEncoding and extraEncoding not in self.encodings and extraEncoding.lower() not in self.encodings:
                        return [extraEncoding]
        return []

    def decodeText(self, text, extraEncodingLookup):
        encodingsToTry = self.encodings + self.getExtraEncodings(extraEncodingLookup)
        for encoding in encodingsToTry:
            try:
                return str(text, encoding, errors="strict")
            except Exception:
                pass

        return str(text, encodingsToTry[0], errors="replace")


def getImageDir():
    retro = guiConfig.getValue("retro_icons")
    currImageDir = plugins.installationDir("images")
    retroDir = os.path.join(currImageDir, "retro")
    return (retroDir, True) if retro != 0 else (currImageDir, False)


class RefreshTips:
    def __init__(self, name, refreshCell, refreshColumn, refreshIndex):
        self.name = name
        self.refreshIndex = refreshIndex
        self.refreshColumn = refreshColumn
        self.refreshCell = refreshCell

    def hasRefreshIcon(self, view, path):  # pragma: no cover - StoryText cannot test tooltips (future?)
        model = view.get_model()
        if isinstance(model, Gtk.TreeModelFilter):
            childPath = model.convert_path_to_child_path(path)
            return model.get_model()[childPath][self.refreshIndex]
        else:
            return model[path][self.refreshIndex]

    def getTooltip(self, view, widget_x, widget_y, dummy, tooltip):  # pragma: no cover - StoryText cannot test tooltips (future?)
        x, y = view.convert_widget_to_tree_coords(widget_x, widget_y)
        pathInfo = view.get_path_at_pos(x, y)
        if pathInfo is None:
            return False

        path, column, cell_x, _ = pathInfo
        if column is not self.refreshColumn or not self.hasRefreshIcon(view, path):
            return False

        cell_pos = column.cell_get_position(self.refreshCell)[0]
        if cell_x > cell_pos:
            tooltip.set_text("Indicates that this " + self.name + "'s approved result has changed since the status was calculated. " +
                             "It's therefore recommended to recompute the status.")
            return True
        else:
            return False


def addRefreshTips(view, *args):
    view.set_property("has-tooltip", True)
    refreshTips = RefreshTips(*args)
    view.connect("query-tooltip", refreshTips.getTooltip)


class GUIConfig:
    def __init__(self, dynamic, allApps, defaultColours, defaultAccelerators, includePersonal=True):
        self.apps = copy(allApps)
        self.dynamic = dynamic
        self.configDir = plugins.MultiEntryDictionary()
        self.configDocs = {}
        self.setConfigDefaults(defaultColours, defaultAccelerators)
        if includePersonal:
            self.configDir.readValues(self.getAllPersonalConfigFiles(), insert=0, errorOnUnknown=0)
        self.shownCategories = list(map(self.getConfigName, self.configDir.get("show_test_category")))
        self.hiddenCategories = list(map(self.getConfigName, self.configDir.get("hide_test_category")))
        self.colourDict = self.makeColourDictionary()

    def getAllPersonalConfigFiles(self):
        allPersonalFiles = []
        # Always include app-independent version
        appIndep = os.path.join(plugins.getPersonalConfigDir(), "config")
        if os.path.isfile(appIndep):
            allPersonalFiles.append(appIndep)
        for app in self.apps:
            for fileName in app.getPersonalConfigFiles():
                if not fileName in allPersonalFiles:
                    allPersonalFiles.append(fileName)
        return allPersonalFiles

    def addSuites(self, suites):
        fullNames = [app.fullName() for app in self.apps]
        for suite in suites:
            if suite.app.fullName() not in fullNames:
                self.apps.append(suite.app)

    def makeColourDictionary(self):
        d = {}
        if self.configDir.get("test_colours") is None:
            return d
        for key, value in list(self.configDir.get("test_colours").items()):
            d[self.getConfigName(key)] = value
        return d

    def setConfigDefaults(self, colourDict, accelerators):
        self.setConfigDefault("static_collapse_suites", 100,
                              "Starting at this level the static GUI will show the suites collapsed")
        self.setConfigDefault("test_colours", colourDict, "Colours to use for each test state")
        self.setConfigDefault("file_colours", copy(colourDict), "Colours to use for each file state")
        self.setConfigDefault("window_size", self.getWindowSizeSettings(),
                              "To set the initial size of the dynamic/static GUI.")
        self.setConfigDefault("hide_gui_element", self.getDefaultHideWidgets(), "List of widgets to hide by default")
        self.setConfigDefault("hide_test_category", [
                              "cancelled"], "Categories of tests which should not appear in the dynamic GUI test view")
        self.setConfigDefault("show_test_category", ["failed"],
                              "Categories of tests which should appear in the dynamic GUI test view")
        self.setConfigDefault("query_kill_processes", {"default": [], "static": [
                              "Dynamic GUI"]}, "Ask about whether to kill these processes when exiting texttest.")
        self.setConfigDefault("gui_accelerators", accelerators, "Custom action accelerators.")
        self.setConfigDefault("gui_entry_completion_matching", 1,
                              "Which matching type to use for entry completion. 0 means turn entry completions off, 1 means match the start of possible completions, 2 means match any part of possible completions")
        self.setConfigDefault("gui_entry_completion_inline", 0,
                              "Automatically inline common completion prefix in entry.")
        self.setConfigDefault("gui_entry_completions", {"default": []},
                              "Add these completions to the entry completion lists initially")
        self.setConfigDefault("sort_test_suites_recursively", 1, "Sort subsuites when sorting test suites")
        self.setConfigDefault("retro_icons", 0, "Use the old TextTest icons in the dynamic and static GUIs")

    def setConfigDefault(self, key, value, docString):
        self.configDir[key] = value
        self.configDocs[key] = docString

    def _simpleValue(self, app, entryName):
        return app.getConfigValue(entryName)

    def _compositeValue(self, app, *args, **kwargs):
        return app.getCompositeConfigValue(*args, **kwargs)

    def _getFromApps(self, method, *args, **kwargs):
        callables = [plugins.Callable(method, app, *args) for app in self.apps]
        aggregator = plugins.ResponseAggregator(callables)
        try:
            return aggregator(**kwargs)
        except plugins.AggregationError as e:
            app = self.apps[e.index]
            plugins.printWarning("GUI configuration '" + "::".join(args) +
                                 "' differs between applications, ignoring that from " + repr(app) + "\n" +
                                 "Value was " + repr(e.value2) + ", change from " + repr(e.value1), stdout=True)
            return e.value1

    def getModeName(self):
        if self.dynamic:
            return "dynamic"
        else:
            return "static"

    def getConfigName(self, name, modeDependent=False):
        formattedName = name.lower().replace(" ", "_").replace(":", "_")
        if modeDependent:
            if len(name) > 0:
                return self.getModeName() + "_" + formattedName
            else:
                return self.getModeName()
        else:
            return formattedName

    def getValue(self, entryName, modeDependent=False):
        nameToUse = self.getConfigName(entryName, modeDependent)
        guiValue = self.configDir.get(nameToUse)
        if guiValue is not None:
            return guiValue
        else:
            return self._getFromApps(self._simpleValue, nameToUse)

    def getCompositeValue(self, sectionName, entryName, modeDependent=False, defaultKey="default"):
        nameToUse = self.getConfigName(entryName, modeDependent)
        value = self.configDir.getComposite(sectionName, nameToUse, defaultKey=defaultKey)
        if value is None:
            value = self._getFromApps(self._compositeValue, sectionName, nameToUse, defaultKey=defaultKey)
        if modeDependent and value is None:
            return self.getCompositeValue(sectionName, entryName)
        else:
            return value

    def getWindowOption(self, name):
        return self.getCompositeValue("window_size", name, modeDependent=True)

    def getWindowDimension(self, dimensionName, diag):
        pixelDimension = self.getWindowOption(dimensionName + "_pixels")
        if pixelDimension != "<not set>":
            diag.info("Setting window " + dimensionName + " to " + pixelDimension + " pixels.")
            return int(pixelDimension)
        else:
            # needs review MB 2018-12-04
            from gi.repository import Gdk
            fullSize = getattr(Gdk.Screen.get_default(), "get_" + dimensionName)()
            proportion = float(self.getWindowOption(dimensionName + "_screen"))
            diag.info("Setting window " + dimensionName + " to " + repr(int(100.0 * proportion)) + "% of screen.")
            return int(fullSize * proportion)

    def showCategoryByDefault(self, category, parentShown=False):
        if self.dynamic:
            nameToUse = self.getConfigName(category)
            if nameToUse in self.hiddenCategories:
                return False
            elif nameToUse in self.shownCategories:
                return True
            else:
                return parentShown
        else:
            return False

    def getTestColour(self, category, fallback=None):
        if self.dynamic:
            nameToUse = self.getConfigName(category)
            if nameToUse in self.colourDict:
                return self.colourDict[nameToUse]
            elif fallback:
                return fallback
            else:
                return self.colourDict.get("failure")
        else:
            if category.startswith("clipboard"):
                return self.colourDict.get(category)
            else:
                return self.colourDict.get("static")

    @staticmethod
    def getWindowSizeSettings():
        d = {}
        d["maximize"] = 0
        d["horizontal_separator_position"] = 0.46
        d["vertical_separator_position"] = 0.5
        d["height_pixels"] = "<not set>"
        d["width_pixels"] = "<not set>"
        d["height_screen"] = float(5.0) / 6
        d["width_screen"] = 0.6
        return d

    @staticmethod
    def getDefaultHideWidgets():
        d = {}
        d["status_bar"] = 0
        d["toolbar"] = 0
        d["shortcut_bar"] = 0
        return d

    @staticmethod
    def getDefaultColours():
        d = {}
        d["default"] = "salmon"
        d["success"] = "DarkSeaGreen2"
        d["failure"] = "salmon"
        d["running"] = "LightGoldenrod1"
        d["initial_filter"] = "LightGoldenrod1"
        d["final_filter"] = "LightGoldenrod1"
        d["not_started"] = "white"
        d["pending"] = "grey80"
        d["static"] = "grey90"
        d["clipboard_cut"] = "red"
        d["clipboard_copy"] = "grey60"
        d["bug"] = "orange"
        d["marked"] = "lightblue"
        return d


# base class for all "GUI" classes which manage parts of the display
class SubGUI(plugins.Observable):
    def __init__(self):
        plugins.Observable.__init__(self)
        self.widget = None

    def createView(self):  # pragma: no cover - implemented in all subclasses
        pass

    def shouldShow(self):
        return True  # should this be shown/created at all this run

    def shouldShowCurrent(self, *args):
        return True  # should this be shown or hidden in the current context?

    def getTabTitle(self):
        return ""

    def forceVisible(self, *args):
        return False

    def addScrollBars(self, view, hpolicy):
        window = Gtk.ScrolledWindow()
        window.set_policy(hpolicy, Gtk.PolicyType.AUTOMATIC)
        self.addToScrolledWindow(window, view)
        window.show()
        return window

    def addToScrolledWindow(self, window, widget):
        if isinstance(widget, Gtk.VBox):
            window.add_with_viewport(widget)
        else:
            window.add(widget)

    def applicationEvent(self, name, **kw):
        createApplicationEvent(name, "files", **kw)

# base class for managing containers


class ContainerGUI(SubGUI):
    def __init__(self, subguis):
        SubGUI.__init__(self)
        self.subguis = subguis

    def forceVisible(self, rowCount):
        return reduce(operator.or_, (subgui.forceVisible(rowCount) for subgui in self.subguis))

    def shouldShow(self):
        return reduce(operator.or_, (subgui.shouldShow() for subgui in self.subguis))

    def shouldShowCurrent(self, *args):
        return reduce(operator.and_, (subgui.shouldShowCurrent(*args) for subgui in self.subguis))

    def getTabTitle(self):
        return self.subguis[0].getTabTitle()
