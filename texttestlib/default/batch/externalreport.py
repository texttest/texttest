
import logging
import os
from collections import OrderedDict
from .batchutils import getBatchRunName
from string import Template
from locale import getpreferredencoding
from texttestlib import plugins
from texttestlib.default.performance import getPerformance
from xml.sax.saxutils import escape
import uuid
from datetime import datetime
from glob import glob


def getExternalFormat(app):
    return app.getBatchConfigValue("batch_external_format").replace("true", "junit")

def getFileExtension(fmt):
    return "xml" if fmt == "junit" else fmt

def getBatchExternalFolder(app, extFormat):
    resultsDir = app.getBatchConfigValue("batch_external_folder")
    if (resultsDir is None or resultsDir.strip() == ""):
        resultsDir = os.path.join(app.writeDirectory, extFormat + "report")
    return resultsDir

class ExternalFormatResponder(plugins.Responder):
    """Respond to test results and write out results in format suitable for reading in to external tools 
    like AZ devops or Visual Studio. Only does anything if the app has "batch_external_format" set to the chosen format in its config file """

    def __init__(self, optionMap, *args):
        plugins.Responder.__init__(self)
        self.runId = getBatchRunName(optionMap)
        self.allApps = OrderedDict()
        self.appData = OrderedDict()
        self.startTimes = {}
        self.diag = logging.getLogger("JUnit Report Writer")
        
    def useExternalFormat(self, app):
        return getExternalFormat(app) != "false"
    
    def notifyLifecycleChange(self, test, dummyState, changeDesc):
        if changeDesc == "start" and self.useExternalFormat(test.app):
            self.startTimes[test] = datetime.now()

    def notifyComplete(self, test):
        extFormat = getExternalFormat(test.app)
        if extFormat == "false":
            return
        if test.app not in self.appData:
            self._addApplication(test)
        cdata = extFormat == "junit"
        self.appData[test.app].storeResult(test, cdata, self.startTimes.get(test))

    def notifyAllComplete(self):
        # allApps is {appname : [app]}
        for appList in list(self.allApps.values()):
            # appData is {app : data}
            for app in appList:
                writerFormat = getExternalFormat(app)
                if writerFormat != "false":
                    self.diag.info("writing results in " + writerFormat + " format for app " + app.fullName())
                    self.writeResults(app, writerFormat)
                    
    def writeResults(self, app, writerFormat):
        results = self.appData[app].getResults()
        appResultsDir = self.createResultsDir(app, writerFormat)
        fileExt = getFileExtension(writerFormat)
        for testName, result in results.items():
            if result["success"]:
                text = self.evaluate(result, "success", writerFormat)
            elif result["error"]:
                text = self.evaluate(result, "error", writerFormat)
            else:
                text = self.evaluate(result, "failure", writerFormat)
            testFileName = os.path.join(appResultsDir, testName + "." + fileExt)
            with open(testFileName, "w") as f:
                f.write(text)
                
    def evaluate(self, result, outcome, writerFormat):
        try:
            return Template(eval(writerFormat + "_" + outcome + "_template")).substitute(result)  
        except NameError:
            return Template(eval(writerFormat + "_template")).substitute(result)
              
    def createResultsDir(self, app, extFormat):
        resultsDir = getBatchExternalFolder(app, extFormat)
        if not os.path.exists(resultsDir):
            os.mkdir(resultsDir)
        appResultsDir = os.path.join(resultsDir, app.name + app.versionSuffix())
        if not os.path.exists(appResultsDir):
            os.mkdir(appResultsDir)
        return appResultsDir
                    
    def _addApplication(self, test):
        app = test.app
        self.appData[app] = ExternalFormatApplicationData(self.runId)
        self.allApps.setdefault(app.name, []).append(app)


class ExternalFormatApplicationData:
    """Data class to store test results in a format convenient for conversion to 
    external report formats """

    def __init__(self, runName):
        self.runId = self.make_guid()
        self.runName = runName
        self.testResults = {}
        
    def make_guid(self):
        return str(uuid.uuid4())

    def storeResult(self, test, cdata, startTime):
        perfStem = test.getConfigValue("default_performance_stem")
        perfFile = test.makeTmpFileName(perfStem)
        t = getPerformance(perfFile) if os.path.isfile(perfFile) else 0
        if startTime is not None:
            endTime = datetime.now()
        else:
            startTime = datetime.fromtimestamp(0)
            endTime = startTime
        result = dict(id=self.runId,
                      run_name=self.runName,
                      test_description=test.description,
                      full_test_name=self._fullTestName(test),
                      test_id=self.make_guid(),
                      execution_id=self.make_guid(),
                      test_name=test.name,
                      suite_name=self._suiteName(test),
                      encoding=getpreferredencoding(),
                      time=str(t),
                      start_time=startTime.isoformat(),
                      end_time=endTime.isoformat(),
                      duration=str(endTime - startTime),
                      host=",".join(test.state.executionHosts),
                      short_message=self._shortMessage(test),
                      stack_trace="")
        long_message = self._longMessage(test, cdata)
        if not test.state.hasResults():
            self._error(result, long_message)
        elif test.state.hasSucceeded():
            self._success(result)
        else:
            self._failure(result, long_message)

        self.testResults[test.getRelPath().replace(os.sep, ".")] = result

    def getResults(self):
        return self.testResults

    def _suiteName(self, test):
        fullName = self._fullTestName(test)
        return ".".join(fullName.split(".")[:-1])

    def _fullTestName(self, test):
        relpath = test.getRelPath()
        return test.app.fullName() + "." + relpath.replace(os.sep, ".")

    def _error(self, result, long_message):
        result["error"] = 1
        result["success"] = 0
        result["failure"] = 0
        result["outcome"] = "Error"
        result["error_message"] = long_message
        result["long_message"] = ""

    def _success(self, result):
        result["error"] = 0
        result["success"] = 1
        result["failure"] = 0
        result["outcome"] = "Passed"
        result["error_message"] = ""
        result["long_message"] = ""
        
    def _failure(self, result, long_message):
        result["error"] = 0
        result["success"] = 0
        result["failure"] = 1
        result["outcome"] = "Failed"
        result["error_message"] = ""
        result["long_message"] = long_message
                    
    def _shortMessage(self, test):
        return escape(test.state.getTypeBreakdown()[1])

    def _longMessage(self, test, cdata):
        if cdata:
            message = test.state.freeText.replace("]]>", "END_MARKER")
            return self._char_filter(message)
        else:
            return escape(test.state.freeText).replace("\n", "&#xA;&#xD;\n")

    @classmethod
    def _char_filter(cls, text):
        """
        Replace char with `"\\x%02x" % ord(char)` if char not allowed in CDATA.
        """
        return "".join(("\\x%02x" % ord(char), char)[cls._allowed(ord(char))] for char in text)

    @staticmethod
    def _allowed(num):
        """
        See http://www.w3.org/TR/REC-xml/#NT-Char
        """
        if num < 0x20:
            return num in (0x9, 0xA, 0xD)
        if num <= 0xD7FF:
            return True
        if num < 0xE000:
            return False
        if num <= 0xFFFD:
            return True
        if num < 0x10000:
            return False
        if num <= 0x10FFFF:
            return True
        return False


junit_failure_template = """\
<?xml version="1.0" encoding="$encoding"?>
<testsuite name="$full_test_name" failures="1" tests="1" time="$time" errors="0">
  <properties/>
  <testcase name="$test_name" time="$time" classname="$suite_name">
    <failure type="differences" message="$short_message">
    <![CDATA[
$long_message
]]>
    </failure>
  </testcase>
</testsuite>
"""

junit_error_template = """\
<?xml version="1.0" encoding="$encoding"?>
<testsuite name="$full_test_name" failures="0" tests="1" time="$time" errors="1">
  <properties/>
  <testcase name="$test_name" time="$time" classname="$suite_name">
    <error type="none" message="$short_message">
    <![CDATA[
$error_message
]]>
    </error>
  </testcase>
</testsuite>
"""

junit_success_template = """\
<?xml version="1.0" encoding="$encoding"?>
<testsuite name="$full_test_name" failures="0" tests="1" time="$time" errors="0">
  <properties/>
  <testcase name="$test_name" time="$time" classname="$suite_name"/>
</testsuite>
"""                

trx_template = """\
<?xml version="1.0" encoding="UTF-8"?>
<TestRun id="$id" name="$run_name" xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
  <ResultSummary outcome="Failed">
    <Counters total="1" executed="1" passed="$success" error="$error" failed="$failure" timeout="0" aborted="0" inconclusive="0" passedButRunAborted="0" notRunnable="0" notExecuted="0" disconnected="0" warning="0" completed="0" inProgress="0" pending="0" />
  </ResultSummary>
  <TestDefinitions>
    <GenericTest name="$full_test_name" id="$test_id">
      <Description>$test_description</Description>
      <Execution id="$execution_id" />
    </GenericTest>
  </TestDefinitions>
  <TestLists>
    <TestList name="Results Not in a List" id="8c84fa94-04c1-424b-9868-57a2d4851a1d" />
    <TestList name="All Loaded Results" id="19431567-8539-422a-85d7-44ee4e166bda" />
  </TestLists>
  <TestEntries>
    <TestEntry testId="$test_id" executionId="$execution_id" testListId="8c84fa94-04c1-424b-9868-57a2d4851a1d" />
  </TestEntries>
  <Results>
    <GenericTestResult testId="$test_id" testName="$full_test_name" executionId="$execution_id" computerName="$host" startTime="$start_time" endTime="$end_time" duration="$duration" testType="13cdc9d9-ddb5-4fa4-a97d-d965ccfc6d4b" outcome="$outcome" testListId="8c84fa94-04c1-424b-9868-57a2d4851a1d">
      <Output>
        <StdOut>
$long_message
        </StdOut>
        <ErrorInfo>
          <Message>
$error_message
          </Message>
          <StackTrace>
$stack_trace
          </StackTrace>
        </ErrorInfo>
      </Output>
    </GenericTestResult>
  </Results>
</TestRun>
"""

class ExternalFormatCollector(plugins.Responder):
    def __init__(self, optionMap, allApps):
        plugins.Responder.__init__(self)
        self.diag = logging.getLogger("external format collect")
        self.allApps = allApps

    def notifyAllComplete(self):
        plugins.log.info("Collecting external format files locally...")
        allFiles = {}
        for app in self.allApps:
            extFormat = getExternalFormat(app)
            resultsDir = getBatchExternalFolder(app, extFormat)
            appResultsDir = os.path.join(resultsDir, app.name + app.versionSuffix())
            fileExt = getFileExtension(extFormat)
            currFiles = glob(os.path.join(appResultsDir, "*." + fileExt))
            writeFile = os.path.join(resultsDir, "all_tests." + fileExt)
            filesSoFar = allFiles.setdefault(writeFile, [])
            filesSoFar += currFiles
            
        for targetFn, sourceFns in allFiles.items():
            plugins.log.info("Creating " + targetFn + " from " + repr(len(sourceFns)) + " source files.")
            if len(sourceFns) > 0:
                self.combineFiles(sourceFns, targetFn)
                
    @classmethod     
    def combineFiles(cls, sourceFns, targetFn):
        entries = {}
        counters = {}
        for fnix, fn in enumerate(sourceFns):
            with open(fn) as f:
                currTag = None
                for rawline in f:
                    line = rawline.strip()
                    if line.startswith("<"):
                        words = line.split()
                        if words[0] == "<Counters":
                            cls.updateCounters(counters, words[1:-1])
                        elif words[0].endswith("s>"): # collections
                            if words[0].startswith("</"):
                                currTag = None
                            else:
                                currTag = words[0][1:-1]
                            continue
                    if currTag:
                        if fnix == 0 or currTag != "TestLists":
                            entries[currTag] = entries.get(currTag, "") + rawline

        templateFn = sourceFns[0]
        with open(targetFn, "w") as wf:
            with open(templateFn) as f:
                currTag = None
                for rawline in f:
                    line = rawline.lstrip()
                    if line.startswith("<Counters"):
                        wf.write(rawline.replace(line, ""))
                        cls.writeCountersLine(wf, counters)
                    elif line.endswith("s>\n"): # collections:
                        wf.write(rawline)
                        if line.startswith("</"):
                            currTag = None
                        else:
                            currTag = line.strip()[1:-1]
                            entry = entries.get(currTag)
                            if entry:
                                wf.write(entry)
                    elif currTag is None:
                        wf.write(rawline)

             
    @classmethod           
    def updateCounters(cls, counters, words):
        for word in words:
            key, rawValue = word.split("=")
            value = counters.get(key, 0) + int(eval(rawValue))
            counters[key] = value
            
    @classmethod
    def writeCountersLine(cls, wf, counters):
        wf.write("<Counters ")
        for key, value in counters.items():
            wf.write(key + '="' + str(value) + '" ')
        wf.write("/>\n")
            