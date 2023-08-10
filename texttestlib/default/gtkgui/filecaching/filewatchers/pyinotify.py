import pyinotify

from ..filewatchers import FileWatcher
from ..utils import StoppableThread

class FileModificationHandler(pyinotify.ProcessEvent):
    def __init__(self, modification_callback):
        super().__init__()
        self.modification_callback = modification_callback

    def process_IN_MODIFY(self, event):
        file_path = event.pathname
        self.modification_callback(file_path)


class InotifyWatcher(FileWatcher):
    def __init__(self, directory_path, modification_callback):
        super().__init__(directory_path, modification_callback)
        self.watch_manager = pyinotify.WatchManager()
        self.mask = pyinotify.IN_MODIFY
        self.event_handler = FileModificationHandler(self.modification_callback)
        self.notifier = pyinotify.Notifier(self.watch_manager, self.event_handler)
        self.watch_manager.add_watch(self.directory_path, self.mask, rec=True)
        self.watcher_thread = StoppableThread(target=self._start, daemon=True)
        
    def _start(self):
        while self.watcher_thread.should_keep_running():
            self.notifier.process_events()
            if self.notifier.check_events():
                self.notifier.read_events()

    def start(self):
        self.watcher_thread.start()
    
    def stop(self):
        self.watcher_thread.stop()
        self.watcher_thread.join()

    