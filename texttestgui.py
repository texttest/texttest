#!/usr/bin/env python

# GUI for TextTest written with PyGTK

import plugins, gtk, gobject, os

class TextTestGUI:
    def __init__(self):
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT)
        self.instructions = []
        self.postponedInstructions = []
        self.postponedTests = []
        self.itermap = {}
    def createTopWindow(self):
        # Create toplevel window to show it all.
        win = gtk.Window(gtk.WINDOW_TOPLEVEL)
        win.set_title("TextTest functional tests")
        win.connect("delete_event", self.quit)
        vbox = self.createWindowContents()
        win.add(vbox)
        win.show()
        win.resize(600, 500)
        return win
    def createIterMap(self):
        iter = self.model.get_iter_root()
        self.createSubIterMap(iter)
    def createSubIterMap(self, iter):
        test = self.model.get_value(iter, 2)
        self.itermap[test] = iter.copy()
        childIter = self.model.iter_children(iter)
        if childIter:
            self.createSubIterMap(childIter)
        nextIter = self.model.iter_next(iter)
        if nextIter:
            self.createSubIterMap(nextIter)
    def addSuite(self, suite, parent=None):
        iter = self.model.insert_before(parent, None)
        self.model.set_value(iter, 0, suite.name)
        self.model.set_value(iter, 2, suite)
        try:
            for test in suite.testcases:
                self.addSuite(test, iter)
            self.model.set_value(iter, 1, "white")
        except:
            self.model.set_value(iter, 1, self.getTestColour(suite))
    def getTestColour(self, test):
        if test.state == test.FAILED or test.state == test.UNRUNNABLE:
            return "red"
        if test.state == test.SUCCEEDED:
            return "green"
        return "white"
    def createWindowContents(self):
        self.contents = gtk.HBox(homogeneous=gtk.TRUE)
        testWins = self.createTestWindows()
        testCaseWin = self.testCaseGUI.getWindow()
        self.contents.pack_start(testWins, expand=gtk.TRUE, fill=gtk.TRUE)
        self.contents.pack_start(testCaseWin, expand=gtk.TRUE, fill=gtk.TRUE)
        self.contents.show()
        return self.contents
    def createTestWindows(self):
        # Create some command buttons.
        buttonbox = self.makeButtons([("Quit", self.quit)])
        window = self.createTreeWindow()

        # Create a vertical box to hold the above stuff.
        vbox = gtk.VBox()
        vbox.pack_start(buttonbox, expand=gtk.FALSE, fill=gtk.FALSE)
        vbox.pack_start(window, expand=gtk.TRUE, fill=gtk.TRUE)
        vbox.show()
        return vbox
    def createDisplayWindows(self):
        hbox = gtk.HBox()
        treeWin = self.createTreeWindow()
        detailWin = self.createDetailWindow()
        hbox.pack_start(treeWin, expand=gtk.TRUE, fill=gtk.TRUE)
        hbox.pack_start(detailWin, expand=gtk.TRUE, fill=gtk.TRUE)
        hbox.show()
        return hbox
    def createTreeWindow(self):
        view = gtk.TreeView(self.model)
        
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn("All Tests", renderer, text=0, background=1)
        view.append_column(column)
        view.expand_all()
        view.connect("row_activated", self.viewTest)
        view.show()

        # Create scrollbars around the view.
        scrolled = gtk.ScrolledWindow()
        scrolled.add(view)
        scrolled.show()    
        return scrolled
    def storeInstructions(self, instructions):
        self.instructions += instructions
    def takeControl(self):
        # We've got everything and are ready to go
        self.createIterMap()
        self.testCaseGUI = TestCaseGUI(None)
        topWindow = self.createTopWindow()
        # Run the Gtk+ main loop.
        idle_handler_id = gtk.idle_add(self.doNextAction)
        gtk.main()
    def doNextAction(self):
        if len(self.instructions) == 0:
            self.instructions = self.postponedInstructions
            self.postponedTests = []
            self.postponedInstructions = []
            if len(self.instructions) == 0:
                return gtk.FALSE
        test, action = self.instructions[0]
        del self.instructions[0]
        
        if test in self.postponedTests:
            self.postponedInstructions.append((test, action))
        else:
            oldState = test.state
            retValue = test.callAction(action)
            if retValue != None:
                self.postponedTests.append(test)
                self.postponedInstructions.append((test, action))
            if test.state != oldState:
                iter = self.itermap[test]
                self.model.set_value(iter, 1, self.getTestColour(test))
                self.model.row_changed(self.model.get_path(iter), iter)
        return gtk.TRUE
    def quit(self, *args):
        gtk.main_quit()
    def viewTest(self, view, start_editing, *args):
        model, iter = view.get_selection().get_selected()
        test = self.model.get_value(iter, 2)
        print "Viewing test", test
        self.contents.remove(self.testCaseGUI.getWindow())
        self.testCaseGUI = TestCaseGUI(test)
        self.contents.pack_start(self.testCaseGUI.getWindow(), expand=gtk.TRUE, fill=gtk.TRUE)
        self.contents.show()
    def makeButtons(self, list):
        buttonbox = gtk.HBox()
        for label, func in list:
            button = gtk.Button()
            button.set_label(label)
            button.connect("clicked", func)
            button.show()
            buttonbox.pack_start(button, expand=gtk.FALSE, fill=gtk.FALSE)
        buttonbox.show()
        return buttonbox
        
class TestCaseGUI:
    def __init__(self, test):
        self.exactButton = None
        self.test = test
        self.model = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT)
        self.addFilesToModel(test)
        view = self.createView(self.createTitle(test))
        buttonbox = self.makeButtons(test)
        radioButtonBox = self.makeRadioButtons(test)
        textview = self.createTextView(test)
        self.window = self.createWindow(buttonbox, radioButtonBox, view, textview)
    def addFilesToModel(self, test):
        compiter = self.model.insert_before(None, None)
        self.model.set_value(compiter, 0, "Comparison Files")
        newiter = self.model.insert_before(None, None)
        self.model.set_value(newiter, 0, "New Files")
        if not test:
            return
        if test.state == test.FAILED:
            os.chdir(test.abspath)
            testComparison = test.stateDetails
            for name in testComparison.attemptedComparisons:
                fileComparison = testComparison.findFileComparison(name)
                if not fileComparison:
                    self.addComparison(compiter, name, fileComparison, "green")
                elif not fileComparison.newResult():
                    self.addComparison(compiter, name, fileComparison, "red")
            for fc in testComparison.newResults:
                self.addComparison(newiter, fc.stdFile, fc, "red")
    def addComparison(self, iter, name, comp, colour):
        fciter = self.model.insert_before(iter, None)
        self.model.set_value(fciter, 0, name)
        self.model.set_value(fciter, 1, colour)
        if comp:
            self.model.set_value(fciter, 2, comp)
    def createWindow(self, buttonbox, radioButtonBox, view, textView):
        fileWin = gtk.ScrolledWindow()
        fileWin.add(view)
        dataWin = gtk.ScrolledWindow()
        if textView:
            dataWin.add(textView)
        vbox = gtk.VBox()
        vbox.pack_start(buttonbox, expand=gtk.FALSE, fill=gtk.FALSE)
        if radioButtonBox:
            vbox.pack_start(radioButtonBox, expand=gtk.FALSE, fill=gtk.FALSE)
        vbox.pack_start(fileWin, expand=gtk.TRUE, fill=gtk.TRUE)
        vbox.pack_start(dataWin, expand=gtk.TRUE, fill=gtk.TRUE)
        fileWin.show()
        dataWin.show()
        vbox.show()    
        return vbox
    def createView(self, title):
        view = gtk.TreeView(self.model)
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn(title, renderer, text=0, background=1)
        view.append_column(column)
        view.expand_all()
        view.connect("row_activated", self.displayDifferences)
        view.show()
        return view
    def createTextView(self, test):
        if not test or test.state != test.UNRUNNABLE:
            return None
        textview = gtk.TextView()
        textview.set_wrap_mode(gtk.WRAP_WORD)
        textbuffer = textview.get_buffer()
        textbuffer.set_text(str(test.stateDetails).split(os.linesep)[0])
        textview.show()
        return textview
    def getWindow(self):
        return self.window
    def createTitle(self, test):
        if not test:
            return "Test-case info"
        return repr(test).replace("_", "__")
    def displayDifferences(self, view, enabled, *args):
        os.chdir(self.test.abspath)
        model, iter = view.get_selection().get_selected()
        comparison = self.model.get_value(iter, 2)
        if comparison:
            if comparison.newResult():
                os.system("xemacs " + comparison.tmpCmpFile + " &")
            else:
                os.system("tkdiff " + comparison.stdCmpFile + " " + comparison.tmpCmpFile + " &")
    def makeButtons(self, test):
        buttonbox = gtk.HBox()
        if not test or test.state != test.FAILED:
            return buttonbox
        options = test.app.getVersionFileExtensions()
        self.addButton(buttonbox, "Save...", "")
        for option in options:     
            self.addButton(buttonbox, option, option)
        buttonbox.show()
        return buttonbox
    def hasPerformance(self, comparisonList):
        for comparison in comparisonList:
            if comparison.getType() != "difference" and comparison.hasDifferences():
                return 1
        return 0
    def makeRadioButtons(self, test):
        if not test or test.state != test.FAILED:
            return None
        comparisonList = test.stateDetails.getComparisons()
        if not self.hasPerformance(comparisonList):
            return None
        buttonbox = gtk.HBox()
        averageButton = gtk.RadioButton(None)
        averageButton.set_label("Average Performance")
        self.exactButton = gtk.RadioButton(averageButton)
        self.exactButton.set_label("Exact Performance")
        if len(comparisonList) != 1:
            self.exactButton.set_active(gtk.TRUE)
        buttonbox.pack_start(averageButton, expand=gtk.FALSE, fill=gtk.TRUE)
        buttonbox.pack_start(self.exactButton, expand=gtk.FALSE, fill=gtk.TRUE)
        averageButton.show()
        self.exactButton.show()
        buttonbox.show()
        return buttonbox
    def addButton(self, buttonbox, label, option):
        button = gtk.Button()
        button.set_label(label)
        button.connect("clicked", self.save, option)
        button.show()
        buttonbox.pack_start(button, expand=gtk.FALSE, fill=gtk.FALSE)
    def getSaveExactness(self):
        if self.exactButton:
            return self.exactButton.get_active() == gtk.TRUE
        else:
            return 1
    def save(self, button, option, *args):
        print "Saving", self.test, "version", option
        testComparison = self.test.stateDetails
        if testComparison:
            testComparison.save(self.getSaveExactness(), option)

    
