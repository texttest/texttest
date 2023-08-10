import threading
import functools
import time

from threading import Timer
from inspect import signature

def debounce(wait):
    def decorator(fn):
        sig = signature(fn)
        caller = {}

        @functools.wraps(fn)
        def debounced(*args, **kwargs):
            nonlocal caller

            try:
                bound_args = sig.bind(*args, **kwargs)
                bound_args.apply_defaults()
                called_args = fn.__name__ + str(dict(bound_args.arguments))
            except:
                called_args = ''

            t_ = time.time()

            def call_it(key):
                try:
                    caller.pop(key)
                except:
                    pass

                fn(*args, **kwargs)

            try:
                caller[called_args].cancel()
            except:
                pass

            caller[called_args] = Timer(wait, call_it, [called_args])
            caller[called_args].start()

        return debounced

    return decorator


class StoppableThread(threading.Thread):
    def __init__(self, *args, **kwargs):
        threading.Thread.__init__(self, *args, **kwargs)
        self.exit_flag = threading.Event()

    def should_keep_running(self):
        return not self.exit_flag.is_set()

    def stop(self):
        self.exit_flag.set()

