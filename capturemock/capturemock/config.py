
""" Class to handle the interface with the rc file """
from ConfigParser import ConfigParser
import os

REPLAY_ONLY_MODE = 0
RECORD_ONLY_MODE = 1
REPLAY_OLD_RECORD_NEW_MODE = 2

class RcFileHandler:
    def __init__(self, rcFiles):
        self.parser = ConfigParser()
        if not rcFiles:
            rcFiles = os.path.expanduser("~/.capturemock/config")
        self.parser.read(rcFiles)

    def getIntercepts(self, section):
        return self.getList("intercepts", [ section ])

    def get(self, *args):
        return self._get(self.parser.get, *args)

    def getboolean(self, *args):
        return self._get(self.parser.getboolean, *args)

    def _get(self, getMethod, setting, sections, defaultVal):
        for section in sections:
            if self.parser.has_section(section) and self.parser.has_option(section, setting):
                return getMethod(section, setting)
        return defaultVal

    def getList(self, setting, sections):
        result = []
        for section in sections:
            if self.parser.has_section(section) and self.parser.has_option(section, setting):
                result += self.parser.get(section, setting).split(",")
        return result
