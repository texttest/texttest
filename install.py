#!/usr/bin/env python
import sys, os, shutil

def osName():
    if os.environ.has_key("INSTALL_FAKE_OS"):
        return os.environ["INSTALL_FAKE_OS"]
    else:
        return os.name

def findPathsMatching(dir, stem):
    paths = []
    for file in os.listdir(dir):
        fullPath = os.path.join(dir, file)
        if file.startswith(stem):
            paths.append(fullPath)
        elif os.path.isdir(fullPath):
            paths += findPathsMatching(fullPath, stem)
    return paths

def commentLine(file, text):
    return transformFile(file, commentMatching, text)

def transformFile(file, function, *args):
    newFile = open(file + "new", "w")
    for line in open(file).xreadlines():
        newLine = function(line, *args)
        if newLine != line:
            print newLine + "-> inserted into " + file
        newFile.write(newLine)
    newFile.close()
    os.remove(file)
    os.rename(file + "new", file)

def insertSourceDir(line, sourceDir):
    if line.startswith("binary:"):
        return line + "\ncheckout_location:" + sourceDir + "\n"
    else:
        return line

def commentMatching(line, text):
    if line.strip() == text:
        return "# " + line
    else:
        return line

# DOS shells have $ as a special character, need to double it up
def replaceDollarForWindows(line):
    if line.rstrip().endswith("$") or line.find("$ ") != -1:
        return line.replace("$", "$$")
    else:
        return line

# Default viewing tools are different for windows
def replaceToolsForWindows(line):
    if line.find("'tail") != -1 or line.find("\"tail") != -1:
        return line.replace("tail -f", "baretail").replace("'tail'", "'baretail'")
    return line.replace("emacs", "notepad")

def replaceCmdToolsForWindows(line):
    return line.replace("emacs window", "notepad window")
    
# Windows needs ; as path separator instead of :
def replacePathForWindows(line):
    if line.find("PATH:") != -1:
        return line.replace(":", ";").replace("PATH;", "PATH:")
    else:
        return line
 
def isInstalled(cmdName):
    if os.environ.has_key("INSTALL_FAKE_QUEUESYSTEM"):
        return os.environ["INSTALL_FAKE_QUEUESYSTEM"].find(cmdName) != -1
    else:
        return os.system("which " + cmdName + " > /dev/null 2>&1") == 0

def checkInstall(queueSystem, cmdName):
    if isInstalled(cmdName):
        print queueSystem.upper(), "installed locally - consider using the", queueSystem, "configuration!" 
    else:
        print queueSystem.upper(), "not installed - commented self-tests for", queueSystem, "configuration."
        commentLine(os.path.join(texttestHome, "texttest", "config.texttest"), "extra_version:" + queueSystem)

def pythonHasUnsetenv():
    return "unsetenv" in dir(os)

def installSource(sourceDir):
    if not os.path.isdir(sourceDir):
        os.makedirs(sourceDir)
    
    for file in os.listdir("source"):
        print "Installing file", file, "to", sourceDir
        fullPath = os.path.join("source", file)
        if os.path.isdir(fullPath):
            targetPath = os.path.join(sourceDir, file)
            if os.path.isdir(targetPath):
                shutil.rmtree(targetPath)
            shutil.copytree(fullPath, targetPath)
        else:
            shutil.copy(fullPath, sourceDir)

def installTests(texttestHome, sourceDir):
    if not os.path.isdir(texttestHome):
        os.makedirs(texttestHome)

    texttestTests = os.path.join(texttestHome, "texttest")
    if os.path.isdir(texttestTests):
        print "TextTest self-tests already exist: removing and replacing them"
        shutil.rmtree(texttestTests)
    else:
        print "Installing TextTest self-tests to ", texttestTests
    shutil.copytree(os.path.join("tests", "texttest"), texttestTests)

    texttestDiags = os.path.join(texttestHome, "Diagnostics")
    if not os.path.isdir(texttestDiags):
        os.mkdir(texttestDiags)
    diagFile = os.path.join(texttestDiags, "log4py.conf")
    fromDiagFile = os.path.join("tests", "Diagnostics", "log4py.conf")
    if os.path.isfile(diagFile):
        print "Diagnostics file already exists: installing new file as log4py.conf.new for manual merging"
        diagFile += ".new"
    else:
        print "Installing TextTest diagnostics file to", diagFile

    shutil.copyfile(fromDiagFile, diagFile)

    testSuiteFiles = findPathsMatching(texttestTests, "testsuite")
    if osName() == "posix":
        checkInstall("lsf", "bsub")
        checkInstall("sge", "qsub")
    else:
        print "Disabling UNIX-specific test elements..."
        testFile = os.path.join(texttestTests, "config.texttest")
        commentLine(testFile, "view_program:emacs")
        commentLine(testFile, "extra_version:lsf")
        commentLine(testFile, "extra_version:sge")
        for testSuiteFile in testSuiteFiles:
            commentLine(testSuiteFile, "UnixOnly")
        print "Replacing PATH settings in environment files ':' -> ';'"
        for envFile in findPathsMatching(texttestTests, "environment"):
            transformFile(envFile, replacePathForWindows)
        print "Replacing for MS-DOS syntax in options and config files '$' -> '$$'"
        filesWithDollars = findPathsMatching(texttestTests, "options") + findPathsMatching(texttestTests, "config")
        for fileWithDollars in filesWithDollars:
            transformFile(fileWithDollars, replaceDollarForWindows)
        guiLogs = findPathsMatching(texttestTests, "gui_log") + \
                  findPathsMatching(texttestTests, "dynamic_gui_log")
        for guifile in guiLogs:
            transformFile(guifile, replaceToolsForWindows)

        for outputFile in findPathsMatching(texttestTests, "output"):
            transformFile(outputFile, replaceCmdToolsForWindows)

    os.chdir(texttestTests)
    transformFile("config.texttest", insertSourceDir, sourceDir)

    try:
        import gtk
    except:
        print "PyGTK is not installed locally, so you will not be able to run the TextTest GUI."
        print "See the README for downloading instructions."
        for testSuiteFile in testSuiteFiles:
            commentLine(testSuiteFile, "GUI")

    if not pythonHasUnsetenv():
        print "Your version of python and/or your system does not support unsetting environment variables from Python."
        print "This will mean you need to take care when using TextTest environment files. See README file"
        

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))
    print "Running TextTest installation from", os.getcwd()
    print "Please enter a directory where the Python source files for TextTest should be installed"
    line = sys.stdin.readline()
    sourceDir = os.path.expanduser(line.strip())
    installSource(sourceDir)
        
    print """Please enter a directory where the tests for TextTest should be installed. This should be the main root
    of your test suite, and it is recommended to set the environment variable TEXTTEST_HOME to this value."""
    texttestHome = os.path.expanduser(sys.stdin.readline().strip())
    installTests(texttestHome, sourceDir)
