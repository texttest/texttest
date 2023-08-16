import sys
import importlib.util

class FileWatcher:
    def __init__(self, directory_path, modification_callback):
        self.directory_path = directory_path
        self.modification_callback = modification_callback
        self.on_start = None

    def set_on_start(self, callback):
        self.on_start = callback

    def start(self):
        pass

    def stop(self):
        pass        


def generate_file_watcher(directory_path, modification_callback):
    if importlib.util.find_spec("watchdog"):
        from .watchdog import GeneralFileWatcher
        return GeneralFileWatcher(directory_path, modification_callback)
    if sys.platform.startswith("linux") and importlib.util.find_spec("pyinotify"):
        from .pyinotify import InotifyWatcher
        return InotifyWatcher(directory_path, modification_callback)
    else:
        from .basic import BasicFileWatcher
        return BasicFileWatcher(directory_path, modification_callback)