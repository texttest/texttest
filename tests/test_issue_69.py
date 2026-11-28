import importlib
import sys
import unittest
from unittest import mock


class TestIssue69(unittest.TestCase):
    def _load_controller(self):
        fake_gi = mock.MagicMock()
        fake_gtk = mock.MagicMock()
        fake_gtk.get_major_version.return_value = 3
        fake_gtk.get_minor_version.return_value = 24
        fake_gtk.get_micro_version.return_value = 0
        fake_gtk.main_level.return_value = 0
        fake_gobject = mock.MagicMock()

        fake_repo = mock.MagicMock()
        fake_repo.Gtk = fake_gtk
        fake_repo.GObject = fake_gobject

        patched = {
            "gi": fake_gi,
            "gi.repository": fake_repo,
            "gi.repository.Gtk": fake_gtk,
            "gi.repository.GObject": fake_gobject,
        }
        patcher = mock.patch.dict(sys.modules, patched)
        patcher.start()
        self.addCleanup(patcher.stop)

        for mod_name in list(sys.modules):
            if mod_name.startswith("texttestlib.default.gtkgui"):
                sys.modules.pop(mod_name, None)

        controller = importlib.import_module("texttestlib.default.gtkgui.controller")
        return controller, fake_gtk, fake_gobject

    def test_dynamic_gui_does_not_hang_when_exit_fires_before_gtk_main(self):
        controller, fake_gtk, fake_gobject = self._load_controller()
        gui = object.__new__(controller.GUIController)
        gui.dynamic = True
        gui.initialApps = [mock.MagicMock()]
        gui.observers = []
        gui.topWindowGUI = mock.MagicMock()
        gui.topWindowGUI.forceQuit.side_effect = gui.notifyExit

        fake_gtk.main_level.return_value = 0
        gui.notifyAllRead([])

        self.assertTrue(gui.exited)
        gui.topWindowGUI.forceQuit.assert_called_once_with()
        fake_gtk.main_quit.assert_not_called()
        fake_gobject.idle_add.assert_called_once_with(gui.quitMainLoop)

        gui.run()
        fake_gtk.main.assert_not_called()

    def test_dynamic_gui_quits_active_main_loop_and_handles_empty_suites(self):
        controller, fake_gtk, fake_gobject = self._load_controller()
        gui = object.__new__(controller.GUIController)
        gui.dynamic = True
        gui.initialApps = []
        gui.observers = []
        gui.topWindowGUI = mock.MagicMock()
        gui.topWindowGUI.forceQuit.side_effect = gui.notifyExit

        empty_suite = mock.MagicMock()
        empty_suite.isEmpty.return_value = True
        empty_suite.app = object()

        fake_gtk.main_level.return_value = 1
        gui.notifyAllRead([empty_suite])

        self.assertTrue(gui.exited)
        fake_gtk.main_quit.assert_called_once_with()
        fake_gobject.idle_add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
