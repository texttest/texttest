import time

from ..utils import StoppableThread
from ..filewatchers import FileWatcher

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, modification_callback):
        self.modification_callback = modification_callback

    def on_modified(self, event):
        src_path = event.src_path
        if not event.is_directory:
            self.modification_callback(src_path)

class GeneralFileWatcher(FileWatcher):
    def __init__(self, directory_path, modification_callback):
        super().__init__(directory_path, modification_callback)
        self.timeout = 1
        self.watcher_thread = StoppableThread(target=self._start)

    def _start(self):
        event_handler = FileChangeHandler(self.modification_callback)

        observer = Observer()
        observer.schedule(event_handler, path=self.directory_path, recursive=True)
        observer.start()
        try: 
            while self.watcher_thread.should_keep_running():
                time.sleep(1)            
        finally:
            observer.stop()
            observer.join()

    def start(self):
        self.watcher_thread.start()

    def stop(self):
        self.watcher_thread.stop()
        self.watcher_thread.join()
