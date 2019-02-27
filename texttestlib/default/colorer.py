#!/usr/bin/env python
# Majority credit to Sorin Sbarnea @ StackOverflow http://stackoverflow.com/questions/384076/how-can-i-make-the-python-logging-output-to-be-colored
import logging

NORMAL = 0
RED = 1
GREEN = 2

initialEmitter = None

# now we patch Python code to add color support to logging.StreamHandler


def add_coloring_to_emit_windows(fn, desired):
    def _set_color(self, code):
        import ctypes
        # Constants from the Windows API
        self.STD_OUTPUT_HANDLE = -11
        hdl = ctypes.windll.kernel32.GetStdHandle(self.STD_OUTPUT_HANDLE)
        ctypes.windll.kernel32.SetConsoleTextAttribute(hdl, code)

    setattr(logging.StreamHandler, '_set_color', _set_color)

    def new(*args):
        # wincon.h
        FOREGROUND_BLUE = 0x0001  # text color contains blue.
        FOREGROUND_GREEN = 0x0002  # text color contains green.
        FOREGROUND_RED = 0x0004  # text color contains red.
        FOREGROUND_INTENSITY = 0x0008  # text color is intensified.
        FOREGROUND_WHITE = FOREGROUND_BLUE | FOREGROUND_GREEN | FOREGROUND_RED

        if desired == RED:
            color = FOREGROUND_RED | FOREGROUND_INTENSITY
        elif desired == GREEN:
            color = FOREGROUND_GREEN | FOREGROUND_INTENSITY

        args[0]._set_color(color)  # apply color
        ret = fn(*args)  # allow the logger to do it's thing
        args[0]._set_color(FOREGROUND_WHITE)  # remove color

        return ret
    return new


def add_coloring_to_emit_ansi(fn, desired):
    # add methods we need to the class
    def new(*args):
        if desired == RED:
            color = '\x1b[31m'  # red
        elif desired == GREEN:
            color = '\x1b[32m'  # green
        # wrap the message in the color tags
        args[1].msg = color + args[1].msg + '\x1b[0m'  # always end in normal

        return fn(*args)
    return new


import platform


def enableOutputColor(color):
    global initialEmitter
    initialEmitter = logging.StreamHandler.emit
    if platform.system() == 'Windows':
        # Windows does not support ANSI escapes and we are using API calls to set the console color
        logging.StreamHandler.emit = add_coloring_to_emit_windows(logging.StreamHandler.emit, color)
    else:
        # all non-Windows platforms are supporting ANSI escapes so we use them
        logging.StreamHandler.emit = add_coloring_to_emit_ansi(logging.StreamHandler.emit, color)


def disableOutputColor():
    global initialEmitter
    logging.StreamHandler.emit = initialEmitter
