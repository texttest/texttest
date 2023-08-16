import os
import time
import threading
import multiprocessing

from threading import Thread

from . import filewatchers
from .utils import debounce


class FileCache:
    def __init__(self, files_to_cache):
        self.files_to_cache = files_to_cache
        self._cache = Cache()
        self.directory_to_watch = os.path.commonpath(self.files_to_cache)
        self.file_watcher = filewatchers.generate_file_watcher(self.directory_to_watch, self._update_cache)

    def _read_file(self, file_path):
        with open(file_path, 'r') as file:
            content = file.read()
        return content

    @debounce(wait=2)
    def _update_cache(self, file_path):
        if file_path in self.files_to_cache:
            content = self._read_file(file_path)
            self._cache[file_path] = content

    def _populate_cache(self):
        for file_path in self.files_to_cache:
            content = self._read_file(file_path)
            self._cache[file_path] = content

    def init(self):
        self.file_watcher.set_on_start(self._populate_cache)
        self.file_watcher.start()
    
    def clear(self):
        self.file_watcher.stop()
    
    def get_file_content(self, file_path):
        if self._cache.has_key(file_path):
            return self._cache[file_path]
        return self._read_file(file_path)

    

class Cache:
    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()

    def __getitem__(self, key):
        with self._lock:
            return self._cache.get(key)

    def __setitem__(self, key, value):
        with self._lock:
            self._cache[key] = value       

    def has_key(self, key): 
        with self._lock:
            return key in self._cache
    
    def size(self):
        return len(self._cache)






