
"""
The various text info views, i.e. the bottom right-corner "Text Info" and
the "Run Info" tab from the dynamic GUI
"""

import gtk, pango, guiutils, plugins, os, sys, subprocess


class TextViewGUI(guiutils.SubGUI):
    hovering_over_link = False
    hand_cursor = gtk.gdk.Cursor(gtk.gdk.HAND2)
    regular_cursor = gtk.gdk.Cursor(gtk.gdk.XTERM)
    linkMarker = "URL=http"

    def __init__(self, dynamic):
        guiutils.SubGUI.__init__(self)
        self.dynamic = dynamic
        self.text = ""
        self.showingSubText = False
        self.view = None
        
    def shouldShowCurrent(self, *args):
        return len(self.text) > 0        

    def forceVisible(self, rowCount):
        # Both TextInfo and RunInfo should stay visible when tests are selected
        return rowCount == 1

    def updateView(self):
        if self.view:
            self.updateViewFromText(self.text)

    def createView(self):
        self.view = gtk.TextView()
        self.view.set_name(self.getTabTitle())
        self.view.set_editable(False)
        self.view.set_cursor_visible(False)
        self.view.set_wrap_mode(gtk.WRAP_WORD)
        self.updateViewFromText(self.text)
        self.view.show()
        return self.addScrollBars(self.view, hpolicy=gtk.POLICY_AUTOMATIC)

    def updateViewFromText(self, text):
        textbuffer = self.view.get_buffer()
        # Encode to UTF-8, necessary for gtk.TextView
        textToUse = guiutils.convertToUtf8(text)
        if self.linkMarker in textToUse:
            self.view.connect("event-after", self.event_after)
            self.view.connect("motion-notify-event", self.motion_notify_event)
            self.setHyperlinkText(textbuffer, textToUse)
        else:
            textbuffer.set_text(textToUse)

    # Links can be activated by clicking. Low-level code lifted from Maik Hertha's
    # GTK hypertext demo
    def event_after(self, text_view, event): # pragma : no cover - external code and untested browser code
        if event.type != gtk.gdk.BUTTON_RELEASE:
            return False
        if event.button != 1:
            return False
        buffer = text_view.get_buffer()

        # we shouldn't follow a link if the user has selected something
        try:
            start, end = buffer.get_selection_bounds()
        except ValueError:
            # If there is nothing selected, None is return
            pass
        else:
            if start.get_offset() != end.get_offset():
                return False

        x, y = text_view.window_to_buffer_coords(gtk.TEXT_WINDOW_WIDGET, int(event.x), int(event.y))
        iter = text_view.get_iter_at_location(x, y)
        target = self.findLinkTarget(iter)
        if target:
            statusMessage = guiutils.openLinkInBrowser(target)
            self.notify("Status", statusMessage)

        return False

    # Looks at all tags covering the position (x, y) in the text view,
    # and if one of them is a link, change the cursor to the "hands" cursor
    # typically used by web browsers.
    def set_cursor_if_appropriate(self, text_view, x, y): # pragma : no cover - external code
        hovering = False

        buffer = text_view.get_buffer()
        iter = text_view.get_iter_at_location(x, y)

        hovering = bool(self.findLinkTarget(iter))
        if hovering != self.hovering_over_link:
            self.hovering_over_link = hovering

        if self.hovering_over_link:
            text_view.get_window(gtk.TEXT_WINDOW_TEXT).set_cursor(self.hand_cursor)
        else:
            text_view.get_window(gtk.TEXT_WINDOW_TEXT).set_cursor(self.regular_cursor)

    def findLinkTarget(self, iter): # pragma : no cover - called by external code
        tags = iter.get_tags()
        for tag in tags:
            target = tag.get_data("target")
            if target:
                return target

    # Update the cursor image if the pointer moved.
    def motion_notify_event(self, text_view, event): # pragma : no cover - external code
        x, y = text_view.window_to_buffer_coords(gtk.TEXT_WINDOW_WIDGET,
            int(event.x), int(event.y))
        self.set_cursor_if_appropriate(text_view, x, y)
        text_view.window.get_pointer()
        return False

    def setHyperlinkText(self, buffer, text):
        buffer.set_text("", 0)
        iter = buffer.get_iter_at_offset(0)
        for line in text.splitlines():
            if self.linkMarker in line:
                self.insertLinkLine(buffer, iter, line)
            else:
                buffer.insert(iter, line + "\n")

    def insertLinkLine(self, buffer, iter, line):
        # Assumes text description followed by link
        tag = buffer.create_tag(None, foreground="blue", underline=pango.UNDERLINE_SINGLE)
        words = line.strip().split()
        linkTarget = words[-1][4:] # strip off the URL=
        newLine = " ".join(words[:-1]) + "\n"
        tag.set_data("target", linkTarget)
        buffer.insert_with_tags(iter, newLine, tag)

    def getDescriptionText(self, test):
        paragraphs = [ self.getDescription(test) ]
        for stem in sorted(set([ "performance" ] + test.getConfigValue("performance_logfile_extractor").keys())):
            fileName = test.getFileName(stem)
            if fileName:
                paragraphs.append(test.app.getFilePreview(fileName))

        return "\n\n".join(paragraphs)

    def getDescription(self, test):
        header = "Description:\n"
        if test.description:
            return header + test.description
        else:
            return header + "<No description provided>"


class RunInfoGUI(TextViewGUI):
    def __init__(self, dynamic, runName):
        TextViewGUI.__init__(self, dynamic)
        self.text = "Information will be available here when all tests have been read..."
        self.runName = runName

    def getTabTitle(self):
        return "Run Info"

    def getGroupTabTitle(self):
        return self.getTabTitle()

    def shouldShow(self):
        return self.dynamic

    def appInfo(self, suite):
        textToUse  = "Application name : " + suite.app.fullName() + "\n"
        textToUse += "Version          : " + suite.app.getFullVersion() + "\n"
        textToUse += "Number of tests  : " + str(suite.size()) + "\n"
        textToUse += "Executable       : " + suite.getConfigValue("executable") + "\n"
        return textToUse

    def notifySetRunName(self, name):
        self.runName = name
        self.updateView()

    def updateView(self):
        if self.runName:
            self.updateViewFromText("Run Name         : " + self.runName + "\n\n" + self.text)
        else:
            self.updateViewFromText(self.text)

    def notifyAllRead(self, suites):
        self.text = ""
        self.text += "\n".join(map(self.appInfo, suites)) + "\n"
        self.text += "Command line     : " + plugins.commandLineString(sys.argv) + "\n\n"
        self.text += "Start time       : " + plugins.startTimeString() + "\n"
        self.updateView()

    def notifyAllComplete(self):
        self.text += "End time         : " + plugins.localtime() + "\n"
        self.updateView()


class TestRunInfoGUI(TextViewGUI):
    def __init__(self, *args):
        TextViewGUI.__init__(self, *args)
        self.currentTest = None
        self.resetText()

    def shouldShow(self):
        return self.dynamic

    def getTabTitle(self):
        return "Test Run Info"

    def notifyNewTestSelection(self, tests, *args):
        if len(tests) == 0:
            self.currentTest = None
            self.resetText()
        elif self.currentTest not in tests:
            self.currentTest = tests[0]
            self.resetText()

    def resetText(self):
        self.text = "Selected test  : "
        if self.currentTest:
            self.text += self.currentTest.name + "\n"
            self.appendTestInfo(self.currentTest)
        else:
            self.text += "none\n"
        self.updateView()

    def appendTestInfo(self, test):
        self.text += "\n" + self.getDescriptionText(test)
        self.text += "\n\n" + test.app.getRunDescription(test)


class TextInfoGUI(TextViewGUI):
    def __init__(self, *args):
        TextViewGUI.__init__(self, *args)
        self.currentTest = None

    def getTabTitle(self):
        return "Text Info"

    def resetText(self, state):
        if state.category == "not_started":
            self.text = "\n" + self.getDescriptionText(self.currentTest)
        else:
            self.text = ""
            freeText = state.getFreeText()
            if state.isComplete():
                self.text = "Test " + repr(state) + "\n"
                if len(freeText) == 0:
                    self.text = self.text.replace(" :", "")
            self.text += str(freeText)
            if state.hasStarted() and not state.isComplete():
                self.text += "\n\nTo obtain the latest progress information and an up-to-date comparison of the files above, " + \
                             "perform 'recompute status' (press '" + \
                             guiutils.guiConfig.getCompositeValue("gui_accelerators", "recompute_status") + "')"

    def notifyNewTestSelection(self, tests, *args):
        if len(tests) == 0:
            self.currentTest = None
            self.text = "No test currently selected"
            self.updateView()
        elif self.currentTest not in tests:
            self.currentTest = tests[0]
            self.resetText(self.currentTest.stateInGui)
            self.updateView()

    def notifyDescriptionChange(self, test):
        self.resetText(self.currentTest.stateInGui)
        self.updateView()

    def notifyLifecycleChange(self, test, state, changeDesc):
        if not test is self.currentTest:
            return
        self.resetText(state)
        self.updateView()

    def hasStem(self, line, files):
        for fileName, comp in files:
            if comp.stem and line.find(" " + repr(comp) + " ") != -1:
                return True
        return False

    def makeSubText(self, files):
        enabled = True
        usedSection, ignoredSection = False, False
        newText = ""
        for line in self.text.splitlines():
            if line.startswith("----"):
                enabled = self.hasStem(line, files)
                if enabled:
                    usedSection = True
                else:
                    ignoredSection = True
            if enabled:
                newText += line + "\n"
        return newText, usedSection and ignoredSection

    def notifyNewFileSelection(self, files):
        if self.dynamic:
            self.updateSubText(files)
        # TODO: static GUI could show some information here...

    def updateSubText(self, files):
        if len(files) == 0:
            if self.showingSubText:
                self.showingSubText = False
                self.updateViewFromText(self.text)
        else:
            newText, changed = self.makeSubText(files)
            if changed:
                self.showingSubText = True
                self.updateViewFromText(newText)
            elif self.showingSubText:
                self.showingSubText = False
                self.updateViewFromText(self.text)

    
