import time
import os

from ..utils import StoppableThread
from ..filewatchers import FileWatcher

class Poller:
    def __init__(self, timeout=1):
        super().__init__()
        self.timeout = timeout
        self.poller_thread = StoppableThread(target=self._start)
        self.on_start = None

    def _start(self):
        if self.on_start:
            self.on_start()
        while self.poller_thread.should_keep_running():
            self.poll()
            time.sleep(self.timeout)

    def set_on_start(self, callback):
        self.on_start = callback

    def start(self):
        self.poller_thread.start()
    
    def stop(self):
        self.poller_thread.stop()
        self.poller_thread.join()

    def poll(self):
        """Implement in sub class."""
        pass


class DirectoryObserver(Poller):
    def __init__(self, directory_path, modification_callback, timeout=1):
        super().__init__(timeout)
        self.file_paths = self._get_files_in_directory(directory_path)
        self.modification_callback = modification_callback
    
    def _get_files_in_directory(self, directory_path):
        return [os.path.join(root, file) for root, _, files in os.walk(directory_path) for file in files]

    def _get_file_modification_times(self):
        return {file_path: os.path.getmtime(file_path) for file_path in self.file_paths}

    def _get_updated_files(self):
        file_modification_times = self._get_file_modification_times()
        updated_files = []
        for file_path, modification_time in file_modification_times.items():
            if modification_time > self.timestamp:
                updated_files.append(file_path)
        return updated_files
    
    def start(self):
        self.timestamp = time.time()
        super().start()

    def poll(self):
        updated_files = self._get_updated_files()
        for file_path in updated_files:
            self.modification_callback(file_path)
        self.timestamp = time.time()


class BasicFileWatcher(FileWatcher):
    """
    A file watcher which implements python methods for getting the modification times of each file. 
    Updates once every 15 minutes. Should only be used as a fallback file watcher. 
    """
    def __init__(self, directory_path, modification_callback):
        super().__init__(directory_path, modification_callback)
        self.directory_observer = DirectoryObserver(directory_path, modification_callback, timeout=5)

    def set_on_start(self, callback):
        self.directory_observer.set_on_start(callback)

    def start(self):
        self.directory_observer.start()
    
    def stop(self):
        self.directory_observer.stop()