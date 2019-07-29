
import logging
import os
from collections import OrderedDict
from .batchutils import getBatchRunName
from string import Template
from locale import getpreferredencoding
from texttestlib import plugins
from texttestlib.default.performance import getPerformance
from xml.sax.saxutils import escape


class JUnitResponder(plugins.Responder):
    """Respond to test results and write out results in format suitable for JUnit
    report writer. Only does anything if the app has batch_junit_format:true in its config file """

    def __init__(self, optionMap, *args):
        plugins.Responder.__init__(self)
        self.runId = getBatchRunName(optionMap)
        self.allApps = OrderedDict()
        self.appData = OrderedDict()

    def useJUnitFormat(self, app):
        return app.getBatchConfigValue("batch_junit_format") == "true"

    def notifyComplete(self, test):
        if not self.useJUnitFormat(test.app):
            return
        if test.app not in self.appData:
            self._addApplication(test)
        self.appData[test.app].storeResult(test)

    def notifyAllComplete(self):
        # allApps is {appname : [app]}
        for appList in list(self.allApps.values()):
            # appData is {app : data}
            for app in appList:
                if self.useJUnitFormat(app):
                    data = self.appData[app]
                    ReportWriter(self.runId).writeResults(app, data)

    def _addApplication(self, test):
        app = test.app
        self.appData[app] = JUnitApplicationData()
        self.allApps.setdefault(app.name, []).append(app)


class JUnitApplicationData:
    """Data class to store test results in a format convenient for conversion to 
    JUnit report format """

    def __init__(self):
        self.testResults = {}

    def storeResult(self, test):
        perfStem = test.getConfigValue("default_performance_stem")
        perfFile = test.makeTmpFileName(perfStem)
        t = getPerformance(perfFile) if os.path.isfile(perfFile) else 0
        result = dict(full_test_name=self._fullTestName(test),
                      test_name=test.name,
                      suite_name=self._suiteName(test),
                      encoding=getpreferredencoding(),
                      time=str(t))
        if not test.state.hasResults():
            self._error(test, result)
        elif test.state.hasSucceeded():
            self._success(result)
        else:
            self._failure(test, result)

        self.testResults[test.getRelPath().replace(os.sep, ".")] = result

    def getResults(self):
        return self.testResults

    def _suiteName(self, test):
        fullName = self._fullTestName(test)
        return ".".join(fullName.split(".")[:-1])

    def _fullTestName(self, test):
        relpath = test.getRelPath()
        return test.app.fullName() + "." + relpath.replace(os.sep, ".")

    def _error(self, test, result):
        result["error"] = True
        result["success"] = False
        result["failure"] = False
        result["short_message"] = self._shortMessage(test)
        result["long_message"] = self._longMessage(test)

    def _success(self, result):
        result["error"] = False
        result["success"] = True
        result["failure"] = False

    def _failure(self, test, result):
        result["error"] = False
        result["success"] = False
        result["failure"] = True
        result["short_message"] = self._shortMessage(test)
        result["long_message"] = self._longMessage(test)

    def _shortMessage(self, test):
        return escape(test.state.getTypeBreakdown()[1])

    def _longMessage(self, test):
        message = test.state.freeText.replace("]]>", "END_MARKER")
        return self._char_filter(message)

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


failure_template = """\
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

error_template = """\
<?xml version="1.0" encoding="$encoding"?>
<testsuite name="$full_test_name" failures="0" tests="1" time="$time" errors="1">
  <properties/>
  <testcase name="$test_name" time="$time" classname="$suite_name">
    <error type="none" message="$short_message">
    <![CDATA[
$long_message
]]>
    </error>
  </testcase>
</testsuite>
"""

success_template = """\
<?xml version="1.0" encoding="$encoding"?>
<testsuite name="$full_test_name" failures="0" tests="1" time="$time" errors="0">
  <properties/>
  <testcase name="$test_name" time="$time" classname="$suite_name"/>
</testsuite>
"""


class ReportWriter:
    def __init__(self, runId):
        self.runId = runId
        self.diag = logging.getLogger("JUnit Report Writer")

    def writeResults(self, app, appData):
        self.diag.info("writing results in junit format for app " + app.fullName())
        appResultsDir = self._createResultsDir(app)
        for testName, result in list(appData.getResults().items()):
            if result["success"]:
                text = Template(success_template).substitute(result)
            elif result["error"]:
                text = Template(error_template).substitute(result)
            else:
                text = Template(failure_template).substitute(result)
            testFileName = os.path.join(appResultsDir, testName + ".xml")
            self._writeTestResult(testFileName, text)

    def _writeTestResult(self, testFileName, text):
        testFile = open(testFileName, "w")
        testFile.write(text)
        testFile.close()

    def _createResultsDir(self, app):
        resultsDir = self.userDefinedFolder(app)
        if (resultsDir is None or resultsDir.strip() == ""):
            resultsDir = os.path.join(app.writeDirectory, "junitreport")

        if not os.path.exists(resultsDir):
            os.mkdir(resultsDir)
        appResultsDir = os.path.join(resultsDir, app.name + app.versionSuffix())
        if not os.path.exists(appResultsDir):
            os.mkdir(appResultsDir)
        return appResultsDir

    def userDefinedFolder(self, app):
        return app.getBatchConfigValue("batch_junit_folder")
