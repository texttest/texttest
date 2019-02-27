
import os
import sys


def findLoggerNames(fileName, keyText="Logger"):
    result = []
    for line in open(fileName):
        if keyText in line:
            words = line.split('"')
            for i, word in enumerate(words):
                if word not in result and i % 2 == 1:  # Only take odd ones, between the quotes!
                    result.append(word)
    result.sort()
    return result


def findLoggerNamesUnder(location, **kwargs):
    result = set()
    for root, _, files in os.walk(location):
        for file in files:
            # Don't allow generation from ourselves...
            if file.endswith(".py") and file != "logconfiggen.py" and file != os.path.basename(sys.argv[0]):
                fileName = os.path.join(root, file)
                result.update(findLoggerNames(fileName, **kwargs))
    return sorted(result)


class PythonLoggingGenerator:
    def __init__(self, fileName, postfix="", prefix=""):
        self.file = open(fileName, "w")
        self.postfix = "." + postfix
        self.prefix = prefix
        self.handlers = {"stdout": "stdout"}

    def write(self, line):
        self.file.write(line + "\n")

    def parseInput(self, enabledLoggerNames, allLoggerNames):
        enabled, all = [], []
        for loggerInfo in enabledLoggerNames:
            try:
                loggerName, fileStem = loggerInfo
            except ValueError:
                loggerName = loggerInfo
                fileStem = loggerInfo
            enabled.append((loggerName, fileStem))
            all.append(loggerName)
        disabled = [l for l in allLoggerNames if l not in all]
        all += disabled
        return enabled, disabled, all

    def generate(self, enabledLoggerNames=[], allLoggerNames=[], debugLevelLoggers=[],
                 timeStdout=False, useDebug=True, defaultLevel="INFO"):
        enabled, disabled, all = self.parseInput(enabledLoggerNames, allLoggerNames)
        self.writeHeaderSections(timed=timeStdout)
        if len(enabled):
            self.write("# ====== The following are enabled by default ======")
            for loggerName, fileStem in enabled:
                self.writeLoggerSection(loggerName, True, fileStem, useDebug, defaultLevel)

        if len(disabled):
            self.write("# ====== The following are disabled by default ======")
            for loggerName in disabled:
                if loggerName in debugLevelLoggers:
                    level = "DEBUG"
                else:
                    level = defaultLevel
                self.writeLoggerSection(loggerName, False, loggerName, useDebug, level)
        self.writeFooterSections(all)

    def writeLoggerSection(self, loggerName, enable, fileStem, useDebug, level):
        self.write("# ======= Section for " + loggerName + " ======")
        self.write("[logger_" + loggerName + "]")
        handler = self.handlers.get(fileStem, loggerName)
        self.write("handlers=" + handler)
        self.write("qualname=" + loggerName)
        if enable:
            self.write("level=" + level + "\n")
        else:
            self.write("#level=" + level + "\n")

        if handler == loggerName:
            self.handlers[fileStem] = handler
            self.write("[handler_" + handler + "]")
            self.write("class=FileHandler")
            if enable or not useDebug:
                self.write("#formatter=timed")
            else:
                self.write("formatter=debug")
            fileName = self.prefix + fileStem.lower().replace(" ", "") + self.postfix
            if enable:
                self.write("#args=(os.devnull, 'a')")
                self.write("args=('" + fileName + "', 'a')\n")
            else:
                self.write("args=(os.devnull, 'a')")
                self.write("#args=('" + fileName + "', 'a')\n")

    def writeHeaderSections(self, timed=False):
        if timed:
            commentStr = ""
        else:
            commentStr = "#"
        self.write("""
[logger_root]
handlers=root
level=ERROR

[handler_root]
class=StreamHandler
level=ERROR
args=(sys.stdout,)

[handler_stdout]
class=StreamHandler
args=(sys.stdout,)
%sformatter=timed

[formatter_timed]
format=%%(asctime)s - %%(message)s

[formatter_debug]
format=%%(name)s %%(levelname)s - %%(message)s
""" % (commentStr))

    def writeFooterSections(self, loggerNames):
        loggerStr = ",".join(loggerNames)
        handlerStr = ",".join(sorted(set(self.handlers.values())))
        self.write("""# ====== Cruft that python logging module needs ======
[loggers]
keys=root,%s

[handlers]
keys=root,%s

[formatters]
keys=timed,debug
""" % (loggerStr, handlerStr))
