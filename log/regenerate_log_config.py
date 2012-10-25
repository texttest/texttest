#!/usr/bin/env python

import logconfiggen, os
from copy import copy

def generateForSelfTests(selftestDir, trafficLoggers, *args):
    if selftestDir:
        consoleGen = logconfiggen.PythonLoggingGenerator(os.path.join(selftestDir, "logging.console"), prefix="%(TEXTTEST_LOG_DIR)s/", postfix="texttest")
        enabledLoggerNames = stdInfo + [ ("storytext replay log", "stdout"), ("kill processes", "stdout") ]
        consoleGen.generate(enabledLoggerNames, *args)
        
        staticGen = logconfiggen.PythonLoggingGenerator(os.path.join(selftestDir, "logging.static_gui"), prefix="%(TEXTTEST_LOG_DIR)s/", postfix="texttest")
        enabledLoggerNames = stdInfo + [ ("gui log", "gui_log"), ("storytext replay log", "gui_log") ]
        staticGen.generate(enabledLoggerNames, *args)

        dynamicGen = logconfiggen.PythonLoggingGenerator(os.path.join(selftestDir, "logging.dynamic_gui"), prefix="%(TEXTTEST_LOG_DIR)s/", postfix="texttest")
        enabledLoggerNames = stdInfo + [ ("gui log", "dynamic_gui_log"), ("storytext replay log", "dynamic_gui_log"),
                                         ("kill processes", "dynamic_gui_log") ]
        dynamicGen.generate(enabledLoggerNames, *args)

        trafficGen = logconfiggen.PythonLoggingGenerator(os.path.join(selftestDir, "logging.traffic"),
                                                         prefix="%(TEXTTEST_CWD)s/", postfix="texttest")
        trafficGen.generate([], trafficLoggers)

def getSelfTestDir(subdir):
    selftestDir = os.path.join(os.getenv("TEXTTEST_HOME"), "texttest", subdir)
    if os.path.isdir(selftestDir):
        return selftestDir
    selftestDir = os.path.join(os.getenv("TEXTTEST_HOME"), subdir)
    if os.path.isdir(selftestDir):
        return selftestDir

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
    stdInfo = [ ("standard log", "stdout") ]
    killInfo = [ ("kill processes", "stdout") ]
    consoleGen.generate(stdInfo + killInfo)
    
    batchGen = logconfiggen.PythonLoggingGenerator("logging.batch")
    batchGen.generate(stdInfo + killInfo, timeStdout=True)

    guiGen = logconfiggen.PythonLoggingGenerator("logging.gui")
    guiGen.generate(stdInfo, defaultLevel="WARNING")

    installationRoot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    coreLib = os.path.join(installationRoot, "lib")
    coreLoggers = logconfiggen.findLoggerNamesUnder(coreLib)
    storytextLib = os.path.join(installationRoot, "storytext", "lib")
    storytextLoggers = logconfiggen.findLoggerNamesUnder(storytextLib)
    trafficLib = os.path.join(installationRoot, "libexec")
    trafficLoggers = logconfiggen.findLoggerNamesUnder(trafficLib)
    allLoggers, debugLoggers = combineLoggers(coreLoggers, storytextLoggers)
    trafficGen = logconfiggen.PythonLoggingGenerator("logging.traffic", postfix="diag", prefix="%(TEXTTEST_PERSONAL_LOG)s/")
    trafficGen.generate(enabledLoggerNames=[], allLoggerNames=trafficLoggers)
    
    debugGen = logconfiggen.PythonLoggingGenerator("logging.debug", postfix="diag", prefix="%(TEXTTEST_PERSONAL_LOG)s/")
    debugGen.generate(enabledLoggerNames=[], allLoggerNames=allLoggers, debugLevelLoggers=debugLoggers)
    
    generateForSelfTests(getSelfTestDir("log"), trafficLoggers, allLoggers, debugLoggers)
    
    # Site-specific
    siteDiagFile = os.path.join(installationRoot, "site/log/logging.debug")
    if os.path.isfile(siteDiagFile):
        siteLib = os.path.join(installationRoot, "site", "lib")
        siteLoggers = logconfiggen.findLoggerNamesUnder(siteLib)
        allLoggers = sorted(allLoggers + siteLoggers)
        debugGen = logconfiggen.PythonLoggingGenerator(siteDiagFile, postfix="diag", prefix="%(TEXTTEST_PERSONAL_LOG)s/")
        debugGen.generate(enabledLoggerNames=[], allLoggerNames=allLoggers, debugLevelLoggers=debugLoggers)

        generateForSelfTests(getSelfTestDir("site/log"), trafficLoggers, allLoggers, debugLoggers)
        
