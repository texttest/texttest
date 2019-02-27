#!/usr/bin/env python

from texttestlib import logconfiggen
import os
from copy import copy
from glob import glob


def generateForSelfTests(selftestDir, *args, **kw):
    if selftestDir:
        consoleGen = logconfiggen.PythonLoggingGenerator(os.path.join(
            selftestDir, "logging.console"), prefix="%(TEXTTEST_LOG_DIR)s/", **kw)
        enabledLoggerNames = stdInfo + [("storytext replay log", "stdout"), ("kill processes", "stdout")]
        consoleGen.generate(enabledLoggerNames, *args)

        staticGen = logconfiggen.PythonLoggingGenerator(os.path.join(
            selftestDir, "logging.static_gui"), prefix="%(TEXTTEST_LOG_DIR)s/", **kw)
        enabledLoggerNames = stdInfo + [("gui log", "gui_log"), ("storytext replay log", "gui_log")]
        staticGen.generate(enabledLoggerNames, *args)

        dynamicGen = logconfiggen.PythonLoggingGenerator(os.path.join(
            selftestDir, "logging.dynamic_gui"), prefix="%(TEXTTEST_LOG_DIR)s/", **kw)
        enabledLoggerNames = stdInfo + [("gui log", "dynamic_gui_log"), ("storytext replay log", "dynamic_gui_log"),
                                        ("kill processes", "dynamic_gui_log")]
        dynamicGen.generate(enabledLoggerNames, *args)


def getAppNames(logFileDir):
    rootDir = os.path.dirname(logFileDir)
    configFiles = glob(os.path.join(rootDir, "config.*"))
    return set([os.path.basename(f).split(".")[1] for f in configFiles])


def findSelfTestDirs():
    pattern = os.path.join(os.getenv("TEXTTEST_HOME"), "*", "log", "logging.console")
    files = glob(pattern)
    if len(files) == 0:
        logDir = os.path.join(os.getenv("TEXTTEST_HOME"), "log")
        return (logDir if os.path.isdir(logDir) else None), None

    selfTestDir, otherDir, otherAppName = None, None, None
    for f in files:
        d = os.path.dirname(f)
        appNames = getAppNames(d)
        if "texttest" in appNames:
            selfTestDir = d
        elif len(appNames) == 1:
            otherDir = d
            otherAppName = appNames.pop()
    return selfTestDir, otherDir, otherAppName


def combineLoggers(coreLoggers, storytextLoggers):
    allLoggers = copy(coreLoggers)
    debugLoggers = []
    for logger in storytextLoggers:
        if logger not in coreLoggers:
            allLoggers.append(logger)
            debugLoggers.append(logger)
    return allLoggers, debugLoggers


if __name__ == "__main__":
    consoleGen = logconfiggen.PythonLoggingGenerator("logging.console")
    stdInfo = [("standard log", "stdout")]
    killInfo = [("kill processes", "stdout")]
    consoleGen.generate(stdInfo + killInfo)

    batchGen = logconfiggen.PythonLoggingGenerator("logging.batch")
    batchGen.generate(stdInfo + killInfo, timeStdout=True)

    guiGen = logconfiggen.PythonLoggingGenerator("logging.gui")
    guiGen.generate(stdInfo, defaultLevel="WARNING")

    installationRoot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    coreLoggers = logconfiggen.findLoggerNamesUnder(installationRoot)
    storytextLib = os.path.join(installationRoot, "../storytext", "lib")
    storytextLoggers = logconfiggen.findLoggerNamesUnder(storytextLib)
    allLoggers, debugLoggers = combineLoggers(coreLoggers, storytextLoggers)

    debugGen = logconfiggen.PythonLoggingGenerator("logging.debug", postfix="diag", prefix="%(TEXTTEST_PERSONAL_LOG)s/")
    debugGen.generate(enabledLoggerNames=[], allLoggerNames=allLoggers, debugLevelLoggers=debugLoggers)

    selfTestDir, siteSelfTestDir, siteAppName = findSelfTestDirs()

    generateForSelfTests(selfTestDir, allLoggers, debugLoggers, postfix="texttest")

    # Site-specific
    siteDiagFile = os.path.join(installationRoot, "../site/log/logging.debug")
    if os.path.isfile(siteDiagFile):
        siteLib = os.path.join(installationRoot, "../site", "lib")
        siteLoggers = logconfiggen.findLoggerNamesUnder(siteLib)
        allLoggers = sorted(allLoggers + siteLoggers)
        debugGen = logconfiggen.PythonLoggingGenerator(
            siteDiagFile, postfix="diag", prefix="%(TEXTTEST_PERSONAL_LOG)s/")
        debugGen.generate(enabledLoggerNames=[], allLoggerNames=allLoggers, debugLevelLoggers=debugLoggers)

        generateForSelfTests(siteSelfTestDir, allLoggers, debugLoggers, postfix=siteAppName)
