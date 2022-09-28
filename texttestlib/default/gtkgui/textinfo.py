
"""
The various text info views, i.e. the bottom right-corner "Text Info" and
the "Run Info" tab from the dynamic GUI
"""
from gi.repository import Gtk, GObject, Gdk, Pango
import os
import sys
import datetime
from . import guiutils, guiplugins
from texttestlib import plugins
from texttestlib.default import performance


class TimeMonitor:
    def __init__(self):
        self.timingInfo = {}

    def notifyLifecycleChange(self, test, dummyState, changeDesc):
        if changeDesc in ["start", "complete"]:
            self.timingInfo.setdefault(test, []).append((changeDesc, datetime.datetime.now()))

    def shouldShow(self):
        # Nothing to show, but needed to be a GUI observer
        return True

    def getElapsedTime(self, test):
        timingInfo = self.timingInfo.get(test)
        if timingInfo:
            delta = datetime.datetime.now() - timingInfo[0][1]
            return delta.seconds + delta.days * 60 * 60 * 24
        else:
            return -1

    def getTimingReport(self, test):
        timingInfo = self.timingInfo.get(test)
        text = ""
        if timingInfo:
            text += "\n"
            for desc, timestamp in timingInfo:
                descToUse = self.getTimeDescription(desc)
                text += descToUse + ": " + timestamp.strftime(plugins.datetimeFormat) + "\n"
        return text

    def getTimeDescription(self, changeDesc):
        descToUse = changeDesc.replace("complete", "end").capitalize() + " time"
        return descToUse.ljust(17)


class TextViewGUI(guiutils.SubGUI):
    hovering_over_link = False
    hand_cursor = Gdk.Cursor.new(Gdk.CursorType.HAND2)
    regular_cursor = Gdk.Cursor.new(Gdk.CursorType.XTERM)
    linkMarker = "URL=http"
    timeMonitor = TimeMonitor()

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
        self.view = Gtk.TextView()
        self.view.set_name(self.getTabTitle())
        self.view.set_editable(False)
        self.view.set_cursor_visible(False)
        self.view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.updateViewFromText(self.text)
        self.view.show()
        return self.addScrollBars(self.view, hpolicy=Gtk.PolicyType.AUTOMATIC)

    def updateViewFromText(self, text):
        textbuffer = self.view.get_buffer()
        if self.linkMarker in text:
            self.view.connect("event-after", self.event_after)
            self.view.connect("motion-notify-event", self.motion_notify_event)
            self.setHyperlinkText(textbuffer, text)
        else:
            textbuffer.set_text(text)

    def getEnvironmentLookup(self):
        pass

    # Links can be activated by clicking. Low-level code lifted from Maik Hertha's
    # GTK hypertext demo
    def event_after(self, text_view, event):  # pragma : no cover - external code and untested browser code
        if event.type != Gdk.EventType.BUTTON_RELEASE:
            return False
        if event.button.button != 1:
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

        x, y = text_view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(event.x), int(event.y))
        _, iter = text_view.get_iter_at_location(x, y)
        target = self.findLinkTarget(iter)
        if target:
            statusMessage = guiplugins.openLinkInBrowser(target)
            self.notify("Status", statusMessage)

        return False

    # Looks at all tags covering the position (x, y) in the text view,
    # and if one of them is a link, change the cursor to the "hands" cursor
    # typically used by web browsers.
    def set_cursor_if_appropriate(self, text_view, x, y):  # pragma : no cover - external code
        hovering = False

        _, iter = text_view.get_iter_at_location(x, y)

        hovering = bool(self.findLinkTarget(iter))
        if hovering != self.hovering_over_link:
            self.hovering_over_link = hovering

        if self.hovering_over_link:
            text_view.get_window(Gtk.TextWindowType.TEXT).set_cursor(self.hand_cursor)
        else:
            text_view.get_window(Gtk.TextWindowType.TEXT).set_cursor(self.regular_cursor)

    def findLinkTarget(self, iter):  # pragma : no cover - called by external code
        tags = iter.get_tags()
        for tag in tags:
            target = tag.target
            if target:
                return target

    # Update the cursor image if the pointer moved.
    def motion_notify_event(self, text_view, event):  # pragma : no cover - external code
        x, y = text_view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET,
                                                 int(event.x), int(event.y))
        self.set_cursor_if_appropriate(text_view, x, y)
        text_view.get_window(Gtk.TextWindowType.TEXT).get_pointer()
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
        tag = buffer.create_tag(None, foreground="blue", underline=Pango.Underline.SINGLE)
        words = line.strip().split()
        linkTarget = words[-1][4:]  # strip off the URL=
        newLine = " ".join(words[:-1]) + "\n"
        tag.target = linkTarget
        buffer.insert_with_tags(iter, newLine, tag)

    def getDescriptionText(self, test):
        paragraphs = self.getDescriptionParagraphs(test)
        return "\n\n".join(paragraphs)

    def getDescriptionParagraphs(self, test):
        paragraphs = [self.getDescription(test)]
        for stem in sorted(set(["performance"] + list(test.getConfigValue("performance_logfile_extractor").keys()))):
            fileName = test.getFileName(stem)
            if fileName and os.path.isfile(fileName):
                paragraphs.append(self.getFilePreview(fileName))
        return paragraphs

    def getFilePreview(self, fileName):
        return "Expected " + os.path.basename(fileName).split(".")[0] + " for the default version:\n" + \
               performance.describePerformance(fileName)

    def getDescription(self, test):
        header = "Description:\n"
        if test.description:
            return header + test.description
        else:
            return header + "<No description provided>"


class RunInfoGUI(TextViewGUI):
    def __init__(self, dynamic, runName, reconnect):
        TextViewGUI.__init__(self, dynamic)
        self.reconnect = reconnect
        self.text = "Information will be available here when all tests have been read..."
        self.runName = runName

    def getTabTitle(self):
        return "Run Info"

    def shouldShow(self):
        return self.dynamic

    def appInfo(self, suite):
        textToUse = "Application name : " + suite.app.fullName() + "\n"
        textToUse += "Version          : " + suite.app.getFullVersion() + "\n"
        textToUse += "Number of tests  : " + str(suite.size()) + "\n"
        if not self.reconnect:
            textToUse += "Executable       : " + suite.getConfigValue("executable") + "\n"
        return textToUse

    def notifySetRunName(self, name):
        self.runName = name
        if self.view:
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
    def __init__(self, dynamic, reconnect):
        TextViewGUI.__init__(self, dynamic)
        self.currentTest = None
        self.reconnect = reconnect
        self.resetText()

    def shouldShow(self):
        return self.dynamic and not self.reconnect

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
            self.text += self.currentTest.getRelPath() + "\n"
            self.appendTestInfo(self.currentTest)
        else:
            self.text += "none\n"
        self.updateView()

    def appendTestInfo(self, test):
        self.text += self.timeMonitor.getTimingReport(test)
        self.text += "\n" + self.getDescriptionText(test)
        if test.classId() == "test-case":
            self.text += "\n\n" + test.app.getRunDescription(test)


class TextInfoGUI(TextViewGUI):
    def __init__(self, *args):
        TextViewGUI.__init__(self, *args)
        self.currentTest = None
        self.currFileSelection = []
        self.preambleText = ""

    def getTabTitle(self):
        return "Text Info"

    def resetText(self, test, state):
        if state.category == "not_started":
            self.text = "\n" + self.getDescriptionText(self.currentTest)
            self.preambleText = self.text
        else:
            self.text = ""
            freeText = state.getFreeText()
            if state.isComplete():
                self.text = "Test " + repr(state) + "\n"
                if len(freeText) == 0:
                    self.text = self.text.replace(" :", "")
                self.preambleText = self.text
            self.text += str(freeText)
            if state.hasStarted() and not state.isComplete():
                self.text += self.getPerformanceEstimate(test)
                self.text += "\n\nTo obtain the latest progress information and an up-to-date comparison of the files above, " + \
                             "perform 'recompute status' (press '" + \
                             guiutils.guiConfig.getCompositeValue("gui_accelerators", "recompute_status") + "')"

    def getPerformanceEstimate(self, test):
        expected = performance.getTestPerformance(test)
        if expected > 0:
            elapsed = self.timeMonitor.getElapsedTime(test)
            if elapsed >= 0:
                perc = (elapsed * 100) / expected
                return "\nReckoned to be " + str(int(perc)) + "% complete comparing elapsed time with expected performance.\n" + \
                       "(" + performance.getTimeDescription(elapsed) + \
                    " of " + performance.getTimeDescription(expected) + ")"
        return ""

    def getDescriptionParagraphs(self, test):
        paragraphs = TextViewGUI.getDescriptionParagraphs(self, test)
        testPath = test.getRelPath()
        if testPath:  # Don't include this for root suite
            paragraphs.insert(1, "Full path:\n" + testPath)
        return paragraphs

    def notifyNewTestSelection(self, tests, *args):
        if len(tests) == 0:
            self.currentTest = None
            self.preambleText = ""
            self.text = "No test currently selected"
            self.updateView()
        elif self.currentTest not in tests:
            self.currentTest = tests[0]
            self.resetText(self.currentTest, self.currentTest.stateInGui)
            self.updateView()

    def notifyDescriptionChange(self, *args):
        self.resetText(self.currentTest, self.currentTest.stateInGui)
        self.notifyNewFileSelection(self.currFileSelection)
        self.updateView()

    def notifyLifecycleChange(self, test, state, *args):
        if not test is self.currentTest:
            return
        self.resetText(test, state)
        self.updateView()

    def notifyRefreshFilePreviews(self, test, fileName):
        if self.isSelected(fileName):
            self.notifyNewFileSelection(self.currFileSelection)

    def isSelected(self, fileName):
        return any((currFile == fileName for currFile, _ in self.currFileSelection))

    def makeSubText(self, files):
        newText = self.preambleText
        showComparisonPreviews = self.dynamic and not all((comp and comp.hasSucceeded() for _, comp in files))
        for fileName, comp in files:
            if showComparisonPreviews:
                if comp and not comp.hasSucceeded():
                    newText += comp.getFreeText()
            elif os.path.isfile(fileName):
                newText += self.getPreview(fileName)
        return newText, newText != self.text and newText != self.preambleText

    def getPreview(self, fileName):
        baseName = os.path.basename(fileName)
        stem = baseName.split(".")[0]
        text = "\n\nPreview of " + baseName + ":\n"
        if self.currentTest.configValueMatches("binary_file", stem):
            text += "Contents of file are marked as binary via the 'binary_file' setting."
        else:
            maxLength = self.currentTest.getConfigValue("lines_of_text_difference")
            maxWidth = self.currentTest.getConfigValue("max_width_text_difference")
            previewGenerator = plugins.PreviewGenerator(maxWidth, maxLength)
            text += previewGenerator.getPreview(open(fileName, errors="ignore"))
        return text

    def notifyNameChange(self, test, *args):
        if test is self.currentTest:
            self.resetText(self.currentTest, self.currentTest.stateInGui)
            self.notifyNewFileSelection(self.currFileSelection)
            self.updateView()

    def notifyNewFileSelection(self, files):
        self.currFileSelection = files
        if len(files) == 0:
            if self.showingSubText:
                self.showingSubText = False
                self.updateViewFromText(self.text)
        elif self.preambleText:
            newText, changed = self.makeSubText(files)
            if changed:
                self.showingSubText = True
                self.updateViewFromText(newText)
            elif self.showingSubText:
                self.showingSubText = False
                self.updateViewFromText(self.text)

    def getEnvironmentLookup(self):
        if self.currentTest:
            return self.currentTest.environment.get
