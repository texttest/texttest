
import logging, os
import plugins
from ndict import seqdict
from util import calculateBatchDate, getRootSuite

class JUnitResponder(plugins.Responder):
    """Respond to test results and write out results in format suitable for JUnit
    report writer. Only does anything if the app has batch_junit_format:true in its config file """
    
    def __init__(self, optionMap, *args):
        self.sessionName = optionMap["b"]
        self.runId = optionMap.get("name", calculateBatchDate()) # use the command-line name if given, else the date
        self.allApps = seqdict()
        self.appData = seqdict()

    def useJUnitFormat(self, app):
        return app.getCompositeConfigValue("batch_junit_format", self.sessionName) == "true"
    
    def notifyComplete(self, test):
        if not self.useJUnitFormat(test.app):
            return
        if not self.appData.has_key(test.app):
            self._addApplication(test)
        self.appData[test.app].storeResult(test)
        
    def notifyAllComplete(self):
        # allApps is {appname : [app]}
        for appname, appList in self.allApps.items():
            # batchAppData is {app : data}
            for app in appList:
                if self.useJUnitFormat(app):
                    data = self.appData[app]
                    ReportWriter(self.sessionName, self.runId).writeResults(app, data)


        
    def _addApplication(self, test):
        rootSuite = getRootSuite(test)
        app = test.app
        self.appData[app] = JUnitApplicationData(rootSuite)
        self.allApps.setdefault(app.name, []).append(app)


class JUnitApplicationData:
    """Data class to store test results in a format convenient for conversion to 
    JUnit report format """
    def __init__(self, rootSuite):
        self.rootSuite = rootSuite
        self.suites = []
        
    def storeResult(self, test):
        pass
        


template = """\
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="root.TargetApp.OutDiff" failures="1" tests="1" time="6" errors="0">
  <properties/>
  <testcase name="OutDiff time="5.0" classname=""/>

</testsuite>
"""

class ReportWriter:
    def __init__(self, sessionName, runId):
        self.sessionName = sessionName
        self.runId = runId
        self.diag = logging.getLogger("JUnit Report Writer")
        
    def writeResults(self, app, batchApplicationData):
        self.diag.info("writing results in junit format for app " + app.fullName())
        appResultsDir = self._createResultsDir(app)
        # write fake file for the moment
        testFileName = os.path.join(appResultsDir, "OutDiff.xml")
        testFile = open(testFileName, "w")
        testFile.write(template)
        testFile.close()
        
            
    def _createResultsDir(self, app):
        resultsDir = os.path.join(app.writeDirectory, "junitreport")
        if not os.path.exists(resultsDir):
            os.mkdir(resultsDir)
        appResultsDir = os.path.join(resultsDir, app.name + app.versionSuffix())
        if not os.path.exists(appResultsDir):
            os.mkdir(appResultsDir)
        return appResultsDir
            
            
        