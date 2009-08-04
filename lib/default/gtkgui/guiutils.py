
"""
Generic module broken out from guiplugins. Contains utility code that can be
called from anywhere in the gtkgui package
"""
import plugins, os, operator, types
from copy import copy
from locale import getdefaultlocale

try:
    import gtk
except ImportError:
    pass # We might want to document the config entries, silly to fail on lack of GTK...


guilog, guiConfig, scriptEngine = None, None, None


# gtk.accelerator_valid appears utterly broken on Windows
def windowsAcceleratorValid(key, mod):
    name = gtk.accelerator_name(key, mod)
    return len(name) > 0 and name != "VoidSymbol"

if os.name == "nt":
    gtk.accelerator_valid = windowsAcceleratorValid

class Utf8Converter:
    def convert(self, text):
        unicodeInfo = self.decodeText(text)
        return self.encodeText(unicodeInfo)

    def decodeText(self, text):
        encodings = self.getEncodings()
        for ix, encoding in enumerate(encodings):
            try:
                unicodeInfo = unicode(text, encoding, errors="strict")
                if ix > 0:
                    guilog.info("WARNING: Failed to decode string '" + text + \
                                "' using encoding(s) " + " and ".join(encodings[:ix]) + \
                                ". Encoded using " + encoding + " instead.")
                return unicodeInfo
            except:
                pass
        guilog.info("WARNING: Failed to decode string '" + text + \
                    "' using strict encodings " + " and ".join(encodings) + \
                    ".\nReverting to non-strict UTF-8 encoding but " + \
                    "replacing problematic\ncharacters with the Unicode replacement character, U+FFFD.")
        return unicode(text, 'utf-8', errors="replace")

    def getEncodings(self):
        encodings = [ 'ISO8859-1', 'utf-8' ]
        localeEncoding = getdefaultlocale()[1]
        if localeEncoding and not localeEncoding in encodings:
            encodings.insert(0, localeEncoding)
        return encodings

    def encodeText(self, unicodeInfo):
        try:
            return unicodeInfo.encode('utf-8', 'strict')
        except:
            try:
                guilog.info("WARNING: Failed to encode Unicode string '" + unicodeInfo + \
                             "' using strict UTF-8 encoding.\nReverting to non-strict UTF-8 " + \
                             "encoding but replacing problematic\ncharacters with the Unicode replacement character, U+FFFD.")
                return unicodeInfo.encode('utf-8', 'replace')
            except:
                guilog.info("WARNING: Failed to encode Unicode string '" + unicodeInfo + \
                            "' using both strict UTF-8 encoding and UTF-8 encoding with " + \
                            "replacement. Showing error message instead.")
                return "Failed to encode Unicode string."


def convertToUtf8(text): # gtk.TextViews insist we do the conversion ourselves
    return Utf8Converter().convert(text)


class RefreshTips:
    def __init__(self, name, refreshCell, refreshColumn, refreshIndex):
        self.name = name
        self.refreshIndex = refreshIndex
        self.refreshColumn = refreshColumn
        self.refreshCell = refreshCell

    def hasRefreshIcon(self, view, path):
        model = view.get_model()
        if isinstance(model, gtk.TreeModelFilter):
            childPath = model.convert_path_to_child_path(path)
            return model.get_model()[childPath][self.refreshIndex]
        else:
            return model[path][self.refreshIndex]

    def getTooltip(self, view, widget_x, widget_y, keyboard_mode, tooltip): 
        x, y = view.convert_widget_to_tree_coords(widget_x, widget_y)
        pathInfo = view.get_path_at_pos(x, y)
        if pathInfo is None:
            return False
        
        path, column, cell_x, cell_y = pathInfo
        if column is not self.refreshColumn or not self.hasRefreshIcon(view, path):
            return False

        cell_pos, cell_size = column.cell_get_position(self.refreshCell)
        if cell_x > cell_pos:
            tooltip.set_text("Indicates that this " + self.name + "'s saved result has changed since the status was calculated. " + \
                             "It's therefore recommended to recompute the status.")
            return True
        else:
            return False


def addRefreshTips(view, *args):
    if gtk.gtk_version >= (2, 12, 0): # Tree view tooltips don't exist prior to this version
        view.set_property("has-tooltip", True)
        refreshTips = RefreshTips(*args)
        view.connect("query-tooltip", refreshTips.getTooltip)


class GUIConfig:
    def __init__(self, dynamic, allApps, defaultColours, defaultAccelerators, entryCompletionLogger=None):
        self.apps = copy(allApps)
        self.dynamic = dynamic
        self.configDir = plugins.MultiEntryDictionary()
        self.configDocs = {}
        self.setConfigDefaults(defaultColours, defaultAccelerators)
        self.configDir.readValues(self.getAllPersonalConfigFiles(), insert=0, errorOnUnknown=0)

        self.hiddenCategories = map(self.getConfigName, self.configDir.get("hide_test_category"))
        self.colourDict = self.makeColourDictionary()
        if entryCompletionLogger:
            self.setUpEntryCompletion(entryCompletionLogger)

    def getAllPersonalConfigFiles(self):
        allPersonalFiles = []
        for app in self.apps:
            for fileName in app.getPersonalConfigFiles():
                if not fileName in allPersonalFiles:
                    allPersonalFiles.append(fileName)
        return allPersonalFiles
    
    def addSuites(self, suites):
        fullNames = [ app.fullName() for app in self.apps ]
        for suite in suites:
            if suite.app.fullName() not in fullNames:
                self.apps.append(suite.app)

    def makeColourDictionary(self):
        dict = {}
        for key, value in self.configDir.get("test_colours").items():
            dict[self.getConfigName(key)] = value
        return dict

    def setConfigDefaults(self, colourDict, accelerators):
        self.setConfigDefault("static_collapse_suites", 0, "Whether or not the static GUI will show everything collapsed")
        self.setConfigDefault("test_colours", colourDict, "Colours to use for each test state")
        self.setConfigDefault("file_colours", copy(colourDict), "Colours to use for each file state")
        self.setConfigDefault("auto_collapse_successful", 1, "Automatically collapse successful test suites?")
        self.setConfigDefault("window_size", self.getWindowSizeSettings(), "To set the initial size of the dynamic/static GUI.")
        self.setConfigDefault("hide_gui_element", self.getDefaultHideWidgets(), "List of widgets to hide by default")
        self.setConfigDefault("hide_test_category", [], "Categories of tests which should not appear in the dynamic GUI test view")
        self.setConfigDefault("query_kill_processes", { "default" : [] }, "Ask about whether to kill these processes when exiting texttest.")
        self.setConfigDefault("gui_accelerators", accelerators, "Custom action accelerators.")        
        self.setConfigDefault("gui_entry_completion_matching", 1, "Which matching type to use for entry completion. 0 means turn entry completions off, 1 means match the start of possible completions, 2 means match any part of possible completions")
        self.setConfigDefault("gui_entry_completion_inline", 0, "Automatically inline common completion prefix in entry.")
        self.setConfigDefault("gui_entry_completions", { "default" : [] }, "Add these completions to the entry completion lists initially")
        self.setConfigDefault("sort_test_suites_recursively", 1, "Sort subsuites when sorting test suites")
        
    def setConfigDefault(self, key, value, docString):
        self.configDir[key] = value
        self.configDocs[key] = docString

    def setUpEntryCompletion(self, entryCompletionLogger):
        matching = self.configDir.get("gui_entry_completion_matching")
        if matching != 0:
            inline = self.configDir.get("gui_entry_completion_inline")
            completions = self.getCompositeValue("gui_entry_completions", "", modeDependent=True)
            from entrycompletion import manager
            manager.start(matching, inline, completions, entryCompletionLogger)
    def _simpleValue(self, app, entryName):
        return app.getConfigValue(entryName)
    def _compositeValue(self, app, *args, **kwargs):
        return app.getCompositeConfigValue(*args, **kwargs)
    def _getFromApps(self, method, *args, **kwargs):
        prevValue = None
        for app in self.apps:
            currValue = method(app, *args, **kwargs)
            toUse = self.chooseValueFrom(prevValue, currValue)
            if toUse is None and prevValue is not None:
                plugins.printWarning("GUI configuration '" + "::".join(args) +\
                                     "' differs between applications, ignoring that from " + repr(app) + "\n" + \
                                     "Value was " + repr(currValue) + ", change from " + repr(prevValue))
            else:
                prevValue = toUse
        return prevValue
    def chooseValueFrom(self, value1, value2):
        if value1 is None or value1 == value2:
            return value2
        if value2 is None:
            return value1
        if type(value1) == types.ListType:
            return self.createUnion(value1, value2)

    def createUnion(self, list1, list2):
        result = []
        result += list1
        for entry in list2:
            if not entry in list1:
                result.append(entry)
        return result
    
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
        value = self.configDir.getComposite(sectionName, nameToUse, defaultKey)
        if value is None:
            value = self._getFromApps(self._compositeValue, sectionName, nameToUse, defaultKey=defaultKey)
        if modeDependent and value is None:
            return self.getCompositeValue(sectionName, entryName)
        else:
            return value
    def getWindowOption(self, name):
        return self.getCompositeValue("window_size", name, modeDependent=True)
    def showCategoryByDefault(self, category, parentHidden=False):
        if self.dynamic:
            if parentHidden:
                return False
            nameToUse = self.getConfigName(category)
            if nameToUse in self.hiddenCategories:
                return False
            else:
                return True
        else:
            return False    
    def getTestColour(self, category, fallback=None):
        if self.dynamic:
            nameToUse = self.getConfigName(category)
            if self.colourDict.has_key(nameToUse):
                return self.colourDict[nameToUse]
            elif fallback:
                return fallback
            else:
                return self.colourDict.get("failure")
        else:
            return self.colourDict.get("static")

    @staticmethod
    def getWindowSizeSettings():
        dict = {}
        dict["maximize"] = 0
        dict["horizontal_separator_position"] = 0.46
        dict["vertical_separator_position"] = 0.5
        dict["height_pixels"] = "<not set>"
        dict["width_pixels"] = "<not set>"
        dict["height_screen"] = float(5.0) / 6
        dict["width_screen"] = 0.6
        return dict

    @staticmethod
    def getDefaultHideWidgets():
        dict = {}
        dict["status_bar"] = 0
        dict["toolbar"] = 0
        dict["shortcut_bar"] = 0
        return dict

    @staticmethod
    def getDefaultColours():
        dict = {}
        dict["default"] = "red"
        dict["success"] = "green"
        dict["failure"] = "red"
        dict["running"] = "yellow"
        dict["not_started"] = "white"
        dict["pending"] = "white"
        dict["static"] = "grey90"
        dict["marked"] = "orange"
        return dict

    @staticmethod
    def getDefaultAccelerators():
        dict = {}
        dict["quit"] = "<control>q"
        dict["select"] = "<control>s"
        dict["filter"] = "<control>f"
        dict["save"] = "<control>s"
        dict["save_as"] = "<control><alt>s"
        dict["copy"] = "<control>c"
        dict["kill"] = "<control>Delete"
        dict["remove"] = "<control>Delete"
        dict["cut"] = "<control>x"
        dict["paste"] = "<control>v"
        dict["save_selection"] = "<control>d"
        dict["load_selection"] = "<control><shift>o"
        dict["reset"] = "<control>e"
        dict["reconnect"] = "<control><shift>r"
        dict["run"] = "<control>r"
        dict["rename"] = "<control>m"
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
    


# base class for all "GUI" classes which manage parts of the display
class SubGUI(plugins.Observable):
    def __init__(self):
        plugins.Observable.__init__(self)
        self.widget = None
    
    def createView(self):
        pass

    def shouldShow(self):
        return True # should this be shown/created at all this run

    def shouldShowCurrent(self, *args):
        return True # should this be shown or hidden in the current context?

    def getTabTitle(self):
        return "Need Title For Tab!"

    def getGroupTabTitle(self):
        return "Test"

    def forceVisible(self, rowCount):
        return False

    def addScrollBars(self, view, hpolicy):
        window = gtk.ScrolledWindow()
        window.set_policy(hpolicy, gtk.POLICY_AUTOMATIC)
        self.addToScrolledWindow(window, view)
        window.show()
        return window

    def addToScrolledWindow(self, window, widget):
        if isinstance(widget, gtk.VBox):
            window.add_with_viewport(widget)
        else:
            window.add(widget)


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

    def getGroupTabTitle(self):
        return self.subguis[0].getGroupTabTitle()
