#!/usr/bin/env python

import logconfiggen, os

def generateForSelfTests(selftestDir, loggers, extraEnabled=[]):
    if selftestDir:
        consoleGen = logconfiggen.PythonLoggingGenerator(os.path.join(selftestDir, "logging.console"), postfix="texttest")
        enabledLoggerNames = stdInfo + [ ("usecase replay log", "stdout"), ("kill processes", "stdout") ] + extraEnabled
        consoleGen.generate(enabledLoggerNames, loggers)
        
        staticGen = logconfiggen.PythonLoggingGenerator(os.path.join(selftestDir, "logging.static_gui"), postfix="texttest")
        enabledLoggerNames = stdInfo + [ ("gui log", "gui_log"), ("usecase replay log", "gui_log") ] + extraEnabled
        staticGen.generate(enabledLoggerNames, loggers)

        dynamicGen = logconfiggen.PythonLoggingGenerator(os.path.join(selftestDir, "logging.dynamic_gui"), postfix="texttest")
        enabledLoggerNames = stdInfo + [ ("gui log", "dynamic_gui_log"), ("usecase replay log", "dynamic_gui_log"),
                                         ("kill processes", "dynamic_gui_log") ] + extraEnabled
        dynamicGen.generate(enabledLoggerNames, loggers)

def getSelfTestDir(subdir):
    selftestDir = os.path.join(os.getenv("TEXTTEST_HOME"), "texttest", subdir)
    if os.path.isdir(selftestDir):
        return selftestDir
    selftestDir = os.path.join(os.getenv("TEXTTEST_HOME"), subdir)
    if os.path.isdir(selftestDir):
        return selftestDir
    
if __name__ == "__main__":
    consoleGen = logconfiggen.PythonLoggingGenerator("logging.console")
    stdInfo = [ ("standard log", "stdout") ]
    killInfo = [ ("kill processes", "stdout") ]
    consoleGen.generate(stdInfo + killInfo)
    
    batchGen = logconfiggen.PythonLoggingGenerator("logging.batch")
    batchGen.generate(stdInfo + killInfo, timeStdout=True)

    installationRoot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    coreLib = os.path.join(installationRoot, "lib")
    coreLoggers = logconfiggen.findLoggerNamesUnder(coreLib)
    
    debugGen = logconfiggen.PythonLoggingGenerator("logging.debug", postfix="diag", prefix="%(TEXTTEST_PERSONAL_LOG)s/")
    debugGen.generate(enabledLoggerNames=[], allLoggerNames=coreLoggers)
    
    generateForSelfTests(getSelfTestDir("log"), coreLoggers)
    
    # Site-specific
    siteDiagFile = os.path.join(installationRoot, "site/log/logging.debug")
    if os.path.isfile(siteDiagFile):
        siteLib = os.path.join(installationRoot, "site", "lib")
        siteLoggers = logconfiggen.findLoggerNamesUnder(siteLib)
        allLoggers = sorted(coreLoggers + siteLoggers)
        debugGen = logconfiggen.PythonLoggingGenerator(siteDiagFile, postfix="diag", prefix="%(TEXTTEST_PERSONAL_LOG)s/")
        debugGen.generate(enabledLoggerNames=[], allLoggerNames=allLoggers)

        generateForSelfTests(getSelfTestDir("site/log"), allLoggers)
        
