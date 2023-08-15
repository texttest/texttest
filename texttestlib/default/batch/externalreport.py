
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
    return fmt if fmt == "trx" else "xml"

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
        self.appData[test.app].storeResult(test, extFormat, self.startTimes.get(test))

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

    def storeResult(self, test, extFormat, startTime):
        perfStem = test.getConfigValue("default_performance_stem")
        perfFile = test.makeTmpFileName(perfStem)
        t = getPerformance(perfFile) if os.path.isfile(perfFile) else 0
        if startTime is not None:
            endTime = datetime.now()
        else:
            startTime = datetime.utcfromtimestamp(0)
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
                      duration=self.formatDuration(endTime - startTime, extFormat),
                      host=",".join(test.state.executionHosts),
                      short_message=self._shortMessage(test))
        long_message = self._longMessage(test, extFormat)
        if not test.state.hasResults():
            self._error(result, long_message)
        elif test.state.hasSucceeded():
            self._success(result)
        else:
            stack_trace = self.getStackTrace(test.state)
            self._failure(result, long_message, stack_trace)
        if extFormat == "jetbrains":
            result["outcome"] = result["outcome"].lower()

        self.testResults[test.getRelPath().replace(os.sep, ".")] = result

    def formatDuration(self, duration, extFormat):
        if extFormat == "jetbrains":
            return str(duration.seconds)
        else:
            return str(duration)

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
        result["stack_trace"] = ""

    def _success(self, result):
        result["error"] = 0
        result["success"] = 1
        result["failure"] = 0
        result["outcome"] = "Passed"
        result["error_message"] = ""
        result["long_message"] = ""
        result["stack_trace"] = ""
        
    def _failure(self, result, long_message, stack_trace):
        result["error"] = 0
        result["success"] = 0
        result["failure"] = 1
        result["outcome"] = "Failed"
        result["error_message"] = ""
        result["long_message"] = long_message
        result["stack_trace"] = stack_trace

    def getStackTrace(self, state):
        fns = state.findComparisonsMatching("*stacktrace*")
        if len(fns) > 0:
            return escape(open(fns[0].tmpFile).read())
        else:
            return ""
                    
    def _shortMessage(self, test):
        return escape(test.state.getTypeBreakdown()[1])

    def _longMessage(self, test, extFormat):
        if extFormat == "junit":
            message = test.state.freeText.replace("]]>", "END_MARKER")
            return self._char_filter(message)
        else:
            message = escape(test.state.freeText)
            if extFormat == "trx":
                message = message.replace("\n", "&#xA;&#xD;\n")
            return message

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
  <ResultSummary outcome="$outcome">
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

jetbrains_template = """\
<?xml version="1.0" encoding="UTF-8"?>
<testrun footerText="Generated by TextTest" name="$run_name">
  <count name="total" value="1"/>
  <count name="failed" value="$failure"/>
  <count name="passed" value="$success"/>
  <test duration="$duration" name="$full_test_name" metainfo="" status="$outcome">
    <output type="stderr">
$long_message
    </output>
  </test>
</testrun>
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
            currFiles.sort()
            writeFile = os.path.join(resultsDir, "all_tests." + fileExt)
            filesSoFar = allFiles.setdefault((writeFile, extFormat), [])
            filesSoFar += currFiles
            
        for (targetFn, extFormat), sourceFns in allFiles.items():
            plugins.log.info("Creating " + targetFn + " in " + extFormat + " format from " + repr(len(sourceFns)) + " source files.")
            if len(sourceFns) > 0:
                self.combineFiles(sourceFns, targetFn, extFormat)
                
    @classmethod
    def getFormatTagInfo(cls, extFormat):
        if extFormat == "trx":
            return {"Counters" : {}, "ResultSummary" : {}}, ("GenericTestResult", "GenericTest", "TestEntry")
        elif extFormat == "jetbrains":
            return {'count name="total"' : {}, 'count name="failed"': {}, 'count name="passed"': {}}, ("test",)
                
    @classmethod     
    def combineFiles(cls, sourceFns, targetFn, extFormat):
        entries = {}
        summaryTags, entryTags = cls.getFormatTagInfo(extFormat)
        for fn in sourceFns:
            with open(fn) as f:
                currTag = None
                for rawline in f:
                    line = rawline.strip()
                    tagClosed = False
                    if line.startswith("<"):
                        lineContent = line.lstrip("<").rstrip("/> ")
                        summaryTag, summaryDict = cls.getSummaryInfo(lineContent, summaryTags)
                        if summaryDict is not None:
                            remainingLine = lineContent.replace(summaryTag + " ", "")
                            cls.updateSummary(summaryDict, remainingLine.split())
                        else:
                            entryTag, tagClosed = cls.getEntryTag(line, entryTags)
                            if entryTag:
                                currTag = entryTag                         
                    if currTag:
                        entries[currTag] = entries.get(currTag, "") + rawline
                    if tagClosed:
                        currTag = None

        templateFn = sourceFns[0]
        with open(targetFn, "w") as wf:
            with open(templateFn) as f:
                currTag = None
                for rawline in f:
                    line = rawline.lstrip(" <").rstrip("/> \n")
                    summaryTag, summaryDict = cls.getSummaryInfo(line, summaryTags)
                    if summaryDict is not None:
                        summaryLine = summaryTag + " " + cls.getSummaryLine(summaryDict)
                        wf.write(rawline.replace(line, summaryLine))
                        continue
                    
                    entryTag, closed = cls.getEntryTag(rawline.strip(), entryTags)
                    if entryTag:
                        currTag = None if closed else entryTag
                        if entryTag in entries:
                            entry = entries.pop(entryTag)
                            wf.write(entry)
                    elif currTag is None:
                        wf.write(rawline)
                   
    @classmethod
    def getEntryTag(cls, line, entryTags):
        for entryTag in entryTags:
            if line.startswith("<" + entryTag + " ") or line.startswith("<" + entryTag + ">"):
                return entryTag, "/>" in line
            elif line.startswith("</" + entryTag + ">"):
                return entryTag, True
        return None, False
                        
    @classmethod
    def getSummaryInfo(cls, line, summaryTags):
        for summaryTag, summaryDict in summaryTags.items():
            if line.startswith(summaryTag):
                return summaryTag, summaryDict
        return None, None
             
    @classmethod           
    def updateSummary(cls, summary, words):
        for word in words:
            key, rawValue = word.split("=")
            value = eval(rawValue)
            numeric = value.isdigit()
            if numeric:
                value = int(value)
            oldValue = summary.get(key)
            if oldValue is None:
                summary[key] = value
            elif numeric:
                summary[key] = oldValue + value
            else:
                # prefer error to failure to success, happens to be alphabetic
                summary[key] = min(oldValue, value)
                            
    @classmethod
    def getSummaryLine(cls, data):
        texts = [ key + '="' + str(value) + '"' for key, value in data.items() ]
        return " ".join(texts)
            