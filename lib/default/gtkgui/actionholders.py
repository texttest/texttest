
""" 
The various "holders" for displaying the "ActionGUI" abstraction: i.e. menus, toolbars and popups,
to store the simple actions and the dialogs, and a notebook to store the tabs in.
"""

import gtk, guiutils, plugins, os, sys, logging, types
from ndict import seqdict

class MenuBarGUI(guiutils.SubGUI):
    def __init__(self, allApps, dynamic, uiManager, actionGUIs, menuNames, *args):
        guiutils.SubGUI.__init__(self)
        # Create GUI manager, and a few default action groups
        self.menuNames = menuNames
        self.dynamic = dynamic
        self.allFiles = plugins.findDataPaths([ "*.xml" ], *args)
        self.uiManager = uiManager
        self.actionGUIs = actionGUIs
        self.actionGroup = self.uiManager.get_action_groups()[0]
        self.toggleActions = []
        self.loadedModules = self.getLoadedModules()
        self.diag = logging.getLogger("Menu Bar")
        self.diag.info("All description files : " + repr(self.allFiles))

    def getLoadedModules(self):
        return set((module.split(".")[-1] for module in sys.modules.keys()))

    def shouldHide(self, name):
        return guiutils.guiConfig.getCompositeValue("hide_gui_element", name, modeDependent=True)

    def toggleVisibility(self, action, observer, *args):
        widget = observer.widget
        oldVisible = widget.get_property('visible')
        newVisible = action.get_active()
        if oldVisible and not newVisible:
            widget.hide()
        elif newVisible and not oldVisible:
            widget.show()

    def createToggleActions(self):
        for observer in self.observers:
            actionTitle = observer.getWidgetName()
            actionName = actionTitle.replace("_", "")
            gtkAction = gtk.ToggleAction(actionName, actionTitle, None, None)
            gtkAction.set_active(True)
            self.actionGroup.add_action(gtkAction)
            gtkAction.connect("toggled", self.toggleVisibility, observer)
            self.toggleActions.append(gtkAction)
            
    def createView(self):
        # Initialize
        for menuName in self.menuNames:
            realMenuName = menuName
            if not menuName.isupper():
                realMenuName = menuName.capitalize()
            self.actionGroup.add_action(gtk.Action(menuName + "menu", "_" + realMenuName, None, None))
        self.createToggleActions()

        for file in self.getGUIDescriptionFileNames():
            try:
                self.diag.info("Reading UI from file " + file)
                self.uiManager.add_ui_from_file(file)
            except Exception, e:
                raise plugins.TextTestError, "Failed to parse GUI description file '" + file + "': " + str(e)
        self.uiManager.ensure_update()
        self.widget = self.uiManager.get_widget("/MainMenuBar")
        return self.widget
    
    def notifyTopWindow(self, window):
        window.add_accel_group(self.uiManager.get_accel_group())
        if self.shouldHide("menubar"):
            self.widget.hide()
        for toggleAction in self.toggleActions:
            if self.shouldHide(toggleAction.get_name()):
                toggleAction.set_active(False)

    def getGUIDescriptionFileNames(self):
        # Pick up all GUI descriptions corresponding to modules we've loaded
        loadFiles = filter(self.shouldLoad, self.allFiles)
        loadFiles.sort(self.cmpDescFiles)
        return loadFiles

    def cmpDescFiles(self, file1, file2):
        base1 = os.path.basename(file1)
        base2 = os.path.basename(file2)
        default1 = base1.startswith("default")
        default2 = base2.startswith("default")
        if default1 != default2:
            return cmp(default2, default1)
        partCount1 = base1.count("-")
        partCount2 = base2.count("-")
        if partCount1 != partCount2:
            return cmp(partCount1, partCount2) # less - implies read first (not mode-specific)
        return cmp(base2, base1) # something deterministic, just to make sure it's the same for everyone
    
    def shouldLoad(self, fileName):
        # Infer whether a file should be loaded
        # The format is
        # <module_name>-<config setting>-<config setting...>-[|dynamic|static].xml
        allParts = os.path.basename(fileName)[:-4].split("-") # drop .xml, split on "-"
        moduleName = allParts[0]
        if allParts[-1] == "dynamic":
            if self.dynamic:
                allParts = allParts[:-1]
            else:
                return False
        elif allParts[-1] == "static":
            if self.dynamic:
                return False
            else:
                allParts = allParts[:-1]

        self.diag.info("Checking if we loaded module " + moduleName)
        if moduleName not in self.loadedModules:
            return False

        for configSetting in allParts[1:]:
            value = guiutils.guiConfig.getValue(configSetting)
            self.diag.info("Checking if we have set " + configSetting + " = " + repr(value))
            if not self.haveSet(value):
                return False
        return True

    def haveSet(self, val):
        if type(val) == types.DictType:
            if len(val) == 1:
                if val.has_key(""):
                    return val[""]
                elif val.has_key("default"):
                    return val["default"]
            else:
                return True
        else:
            return bool(value)

        
    

class ToolBarGUI(guiutils.ContainerGUI):
    def __init__(self, uiManager, subgui):
        guiutils.ContainerGUI.__init__(self, [ subgui ])
        self.uiManager = uiManager
    def getWidgetName(self):
        return "_Toolbar"
    def ensureVisible(self, toolbar):
        for item in toolbar.get_children():
            item.set_is_important(True) # Or newly added children without stock ids won't be visible in gtk.TOOLBAR_BOTH_HORIZ style
    def shouldShow(self):
        return True # don't care about whether we have a progress bar or not
    def createView(self):
        self.uiManager.ensure_update()
        toolbar = self.uiManager.get_widget("/MainToolBar")
        self.ensureVisible(toolbar)

        self.widget = gtk.HandleBox()
        self.widget.add(toolbar)
        toolbar.set_orientation(gtk.ORIENTATION_HORIZONTAL)
        progressBarGUI = self.subguis[0]
        if progressBarGUI.shouldShow():
            progressBar = progressBarGUI.createView()
            width = 7 # Looks good, same as gtk.Paned border width
            alignment = gtk.Alignment()
            alignment.set(1.0, 1.0, 1.0, 1.0)
            alignment.set_padding(width, width, 1, width)
            alignment.add(progressBar)
            toolItem = gtk.ToolItem()
            toolItem.add(alignment)
            toolItem.set_expand(True)
            toolbar.insert(toolItem, -1)

        self.widget.show_all()
        return self.widget

def createPopupGUIs(uiManager):
    return PopupMenuGUI("TestPopupMenu", uiManager), PopupMenuGUI("TestFilePopupMenu", uiManager)

class PopupMenuGUI(guiutils.SubGUI):
    def __init__(self, name, uiManager):
        guiutils.SubGUI.__init__(self)
        self.name = name
        self.uiManager = uiManager
    def createView(self):
        self.uiManager.ensure_update()
        self.widget = self.uiManager.get_widget("/" + self.name)
        self.widget.show_all()
        return self.widget
    def showMenu(self, treeview, event):
        if event.button == 3 and len(self.widget.get_children()) > 0:
            time = event.time
            pathInfo = treeview.get_path_at_pos(int(event.x), int(event.y))
            selection = treeview.get_selection()
            selectedRows = selection.get_selected_rows()
            # If they didnt right click on a currently selected
            # row, change the selection
            if pathInfo is not None:
                if pathInfo[0] not in selectedRows[1]:
                    selection.unselect_all()
                    selection.select_path(pathInfo[0])
                path, col, cellx, celly = pathInfo
                treeview.grab_focus()
                self.widget.popup(None, None, None, event.button, time)
                treeview.emit_stop_by_name("button-press-event")
                

class NotebookGUI(guiutils.SubGUI):
    def __init__(self, tabInfo, name):
        guiutils.SubGUI.__init__(self)
        self.name = name
        self.diag = logging.getLogger("GUI notebook")
        self.tabInfo = tabInfo
        self.notebook = None
        tabName, self.currentTabGUI = self.findInitialCurrentTab()
        self.diag.info("Current page set to '" + tabName + "'")

    def findInitialCurrentTab(self):
        return self.tabInfo[0]

    def createView(self):
        self.notebook = gtk.Notebook()
        self.notebook.set_name(self.name)
        for tabName, tabGUI in self.tabInfo:
            label = gtk.Label(tabName)
            page = self.createPage(tabGUI, tabName)
            self.notebook.append_page(page, label)

        self.notebook.set_scrollable(True)
        self.notebook.show()
        return self.notebook

    def createPage(self, tabGUI, tabName):
        self.diag.info("Adding page " + tabName)
        return tabGUI.createView()

    def shouldShowCurrent(self, *args):
        for name, tabGUI in self.tabInfo:
            if tabGUI.shouldShowCurrent(*args):
                return True
        return False


# Notebook GUI that adds and removes tabs as appropriate...
class ChangeableNotebookGUI(NotebookGUI):
    def __init__(self, tabGUIs):
        tabGUIs = filter(lambda tabGUI: tabGUI.shouldShow(), tabGUIs)
        subNotebookGUIs = self.createSubNotebookGUIs(tabGUIs)
        NotebookGUI.__init__(self, subNotebookGUIs, "main right-hand notebook")

    def classifyByTitle(self, tabGUIs):
        return map(lambda tabGUI: (tabGUI.getTabTitle(), tabGUI), tabGUIs)

    def getGroupTabNames(self, tabGUIs):
        tabNames = [ "Test", "Status", "Selection", "Running" ]
        for tabGUI in tabGUIs:
            tabName = tabGUI.getGroupTabTitle()
            if not tabName in tabNames:
                tabNames.append(tabName)
        return tabNames

    def createSubNotebookGUIs(self, tabGUIs):
        tabInfo = []
        for tabName in self.getGroupTabNames(tabGUIs):
            currTabGUIs = filter(lambda tabGUI: tabGUI.getGroupTabTitle() == tabName, tabGUIs)
            if len(currTabGUIs) > 1:
                name = "sub-notebook for " + tabName.lower()
                notebookGUI = NotebookGUI(self.classifyByTitle(currTabGUIs), name)
                tabInfo.append((tabName, notebookGUI))
            elif len(currTabGUIs) == 1:
                tabInfo.append((tabName, currTabGUIs[0]))
        return tabInfo

    def createPage(self, tabGUI, tabName):
        page = NotebookGUI.createPage(self, tabGUI, tabName)
        if not tabGUI.shouldShowCurrent():
            self.diag.info("Hiding page " + tabName)
            page.hide()
        return page

    def findInitialCurrentTab(self):
        for tabName, tabGUI in self.tabInfo:
            if tabGUI.shouldShowCurrent():
                return tabName, tabGUI

        return self.tabInfo[0]

    def findFirstRemaining(self, pagesRemoved):
        for page in self.notebook.get_children():
            if page.get_property("visible"):
                pageNum = self.notebook.page_num(page)
                if not pagesRemoved.has_key(pageNum):
                    return pageNum

    def showNewPages(self, *args):
        changed = False
        for pageNum, (name, tabGUI) in enumerate(self.tabInfo):
            page = self.notebook.get_nth_page(pageNum)
            if tabGUI.shouldShowCurrent(*args):
                if not page.get_property("visible"):
                    self.diag.info("Showing page " + name)
                    page.show()
                    changed = True
            else:
                self.diag.info("Remaining hidden " + name)
        return changed

    def createView(self):
        notebook = NotebookGUI.createView(self)
        notebook.connect("switch-page", self.pageSwitched)
        return notebook
    
    def pageSwitched(self, notebook, page, newNum, *args):
        newName, newTabGUI = self.tabInfo[newNum]
        self.diag.info("Resetting current page to page " + repr(newNum) + " = " + repr(newName))
        # Must do this afterwards, otherwise the above change doesn't propagate
        self.currentTabGUI = newTabGUI
        self.diag.info("Resetting done.")

    def findPagesToHide(self, *args):
        pages = seqdict()
        for pageNum, (name, tabGUI) in enumerate(self.tabInfo):
            page = self.notebook.get_nth_page(pageNum)
            if not tabGUI.shouldShowCurrent(*args) and page.get_property("visible"):
                pages[pageNum] = page
        return pages

    def hideOldPages(self, *args):
        # Must reset the current page before removing it if we're viewing a removed page
        # otherwise we can output lots of pages we don't really look at
        pagesToHide = self.findPagesToHide(*args)
        if len(pagesToHide) == 0:
            return False

        if pagesToHide.has_key(self.notebook.get_current_page()):
            newCurrentPageNum = self.findFirstRemaining(pagesToHide)
            if newCurrentPageNum is not None:
                self.notebook.set_current_page(newCurrentPageNum)

        # remove from the back, so we don't momentarily view them all if removing everything
        for page in reversed(pagesToHide.values()):
            self.diag.info("Hiding page " + self.notebook.get_tab_label_text(page))
            page.hide()
        return True

    def updateCurrentPage(self, rowCount):
        for pageNum, (tabName, tabGUI) in enumerate(self.tabInfo):
            if tabGUI.shouldShowCurrent() and tabGUI.forceVisible(rowCount):
                return self.notebook.set_current_page(pageNum)

    def notifyNewTestSelection(self, tests, apps, rowCount, direct):
        # This is mostly an attempt to work around the tree search problems.
        # Don't hide the tab for user-deselections of all tests because it trashes the search.
        if len(tests) > 0 or not direct:
            self.diag.info("New selection with " + repr(tests) + ", adjusting '" + self.name + "'")
            # only change pages around if a test is directly selected and we haven't already selected another important tab
            changeCurrentPage = direct and not self.currentTabGUI.forceVisible(rowCount)
            self.diag.info("Current tab gui " + repr(self.currentTabGUI.__class__) + " will change = " + repr(changeCurrentPage))
            self.updatePages(rowCount=rowCount, changeCurrentPage=changeCurrentPage)

    def updatePages(self, test=None, state=None, rowCount=0, changeCurrentPage=False):
        if not self.notebook:
            return
        pagesShown = self.showNewPages(test, state)
        pagesHidden = self.hideOldPages(test, state)
        if changeCurrentPage:
            self.updateCurrentPage(rowCount)

    def notifyLifecycleChange(self, test, state, changeDesc):
        self.updatePages(test, state)

    def addSuites(self, suites):
        self.updatePages()
