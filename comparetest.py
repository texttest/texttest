#!/usr/local/bin/python


import os, filecmp, string, plugins
from ndict import seqdict
from tempfile import mktemp
from comparefile import FileComparison
from performance import PerformanceFileComparison

plugins.addCategory("success", "succeeded")
plugins.addCategory("failure", "FAILED")

class TestComparison(plugins.TestState):
    def __init__(self, previousInfo, app, lifecycleChange=""):
        plugins.TestState.__init__(self, "failure", "", started=1, completed=1, \
                                   lifecycleChange=lifecycleChange, executionHosts=previousInfo.executionHosts)
        self.allResults = []
        self.changedResults = []
        self.newResults = []
        self.missingResults = []
        self.correctResults = []
        self.failedPrediction = None
        if previousInfo.category == "killed":
            self.setFailedPrediction(previousInfo)
        self.diag = plugins.getDiagnostics("TestComparison")
        # Cache these only so it gets output when we pickle, so we can re-interpret if needed... data may be moved
        self.appAbsPath = app.getDirectory()
        self.appWriteDir = app.writeDirectory
    def __repr__(self):    
        if self.failedPrediction:
            briefDescription, longDescription = self.categoryDescriptions[self.category]
            return longDescription + " (" + self.failedPrediction.briefText + ")" + self.hostRepr()
        else:
            return plugins.TestState.__repr__(self)
    def ensureCompatible(self):
        # If loaded from old pickle files, can get out of date objects...
        if not hasattr(self, "missingResults"):
            self.missingResults = []
        for fileComparison in self.allResults:
            fileComparison.ensureCompatible()
    def updatePaths(self, newAbsPath, newWriteDir):
        self.diag = plugins.getDiagnostics("TestComparison")
        self.diag.info("Updating abspath " + self.appAbsPath + " to " + newAbsPath)
        self.diag.info("Updating writedir " + self.appWriteDir + " to " + newWriteDir)
        for comparison in self.allResults:
            comparison.updatePaths(self.appAbsPath, newAbsPath)
            comparison.updatePaths(self.appWriteDir, newWriteDir)
        self.appAbsPath = newAbsPath
        self.appWriteDir = newWriteDir
    def setFailedPrediction(self, prediction):
        self.failedPrediction = prediction
        self.freeText = str(prediction)
        self.briefText = prediction.briefText
        self.category = prediction.category
    def hasSucceeded(self):
        return self.category == "success"
    def isSaveable(self):
        if self.failedPrediction:
            return self.failedPrediction.isSaveable()
        else:
            return plugins.TestState.isSaveable(self)
    def hasDifferences(self):
        return len(self.changedResults) > 0
    def needsRecalculation(self):
        for comparison in self.allResults:
            self.diag.info(comparison.stem + " dates " + comparison.modifiedDates())
            if comparison.needsRecalculation():
                self.diag.info("Recalculation needed for file " + comparison.stem)
                return 1
        self.diag.info("All file comparisons up to date")
        return 0
    def getMostSevereFileComparison(self):
        worstSeverity = None
        worstResult = None
        for result in self.getComparisons():
            severity = result.severity
            if not worstSeverity or severity < worstSeverity:
                worstSeverity = severity
                worstResult = result
        return worstResult
    def getTypeBreakdown(self):
        if self.hasSucceeded():
            return self.category, ""
        if self.failedPrediction:
            return self.failedPrediction.getTypeBreakdown()

        worstResult = self.getMostSevereFileComparison()
        worstSeverity = worstResult.severity
        self.diag.info("Severity " + str(worstSeverity) + " for failing test")
        details = self.getSummary(worstResult)
        if len(self.getComparisons()) > 1:
            details += "(+)"
        if worstSeverity == 1:
            return "failure", details
        else:
            return "success", details
    def getSummary(self, worstResult):
        # Don't call worstResult.newResult() - we want the right answer
        # even if all the files are gone, for the sake of testoverview etc.
        if worstResult in self.newResults:
            return worstResult.stem + " new"
        elif worstResult in self.missingResults:
            return worstResult.stem + " missing"
        else:
            return worstResult.getSummary()
    def hasResults(self):
        return len(self.allResults) > 0
    def getComparisons(self):
        return self.changedResults + self.newResults + self.missingResults    
    def _comparisonsString(self, comparisons):
        return string.join([repr(x) for x in comparisons], ",")
    # Sort according to failure_display_priority. Lower means show earlier,
    # files with the same prio should be not be shuffled. 
    def getSortedComparisons(self):
        # sort() sorts in-place, so we want to copy first ...
        changed = self.changedResults[:]
        changed.sort(self.lessDisplayPriority)        
        new = self.newResults[:]
        new.sort(self.lessDisplayPriority)
        missing = self.missingResults[:]
        missing.sort(self.lessDisplayPriority)
        return changed + new + missing
    def lessDisplayPriority(self, first, second):
        if first.displayPriority == second.displayPriority:
            return cmp(first.stem, second.stem)
        else:
            return cmp(first.displayPriority, second.displayPriority)
    def getDifferenceSummary(self):
        return repr(self) + self._getDifferenceSummary()
    def _getDifferenceSummary(self):
        if len(self.getComparisons()) == 0:
            return ""
        texts = []
        if len(self.newResults) > 0:
            texts.append("new results in " + self._comparisonsString(self.newResults))
        if len(self.missingResults) > 0:
            texts.append("missing results for " + self._comparisonsString(self.missingResults))
        if len(self.changedResults) > 0:
            texts.append("differences in " + self._comparisonsString(self.changedResults))
        return " " + string.join(texts, ", ")
    def getPostText(self):
        if not self.hasResults():
            return " - NONE!"
        if len(self.getComparisons()) == 0:
            return " - SUCCESS! (on " + self.attemptedComparisonsOutput() + ")"
        return " (on " + self.attemptedComparisonsOutput() + ")"
    def attemptedComparisonsOutput(self):
        baseNames = []
        for comparison in self.allResults:
            if comparison.newResult():
                baseNames.append(os.path.basename(comparison.tmpFile))
            else:
                baseNames.append(os.path.basename(comparison.stdFile))
        return string.join(baseNames, ",")
    def addComparison(self, comparison):
        info = "Making comparison for " + comparison.stem + " "
        if comparison.isDefunct():
            # typically "missing file" that got "saved" and removed
            info += "(defunct)"
        else:
            self.allResults.append(comparison)
            if comparison.newResult():
                self.newResults.append(comparison)
                info += "(new)"
            elif comparison.missingResult():
                self.missingResults.append(comparison)
                info += "(missing)"
            elif comparison.hasDifferences():
                self.changedResults.append(comparison)
                info += "(diff)"
            else:
                self.correctResults.append(comparison)
                info += "(correct)"
        self.diag.info(info)
    def makeStemDict(self, files):
        stemDict = seqdict()
        for file in files:
            stem = os.path.basename(file).split(".")[0]
            stemDict[stem] = file
        return stemDict
    def makeComparisons(self, test, testInProgress=0):
        tmpFiles = self.makeStemDict(test.listTmpFiles())
        resultFiles, defFiles = test.listStandardFiles(allVersions=False)
        stdFiles = self.makeStemDict(resultFiles + defFiles)
        for tmpStem, tmpFile in tmpFiles.items():
            stdFile = stdFiles.get(tmpStem)
            self.diag.info("Comparing " + repr(stdFile) + "\nwith " + tmpFile) 
            comparison = self.createFileComparison(test, tmpStem, stdFile, tmpFile, testInProgress)
            if comparison:
                self.addComparison(comparison)
        if not testInProgress: # not interested in missing files here
            for stdStem, stdFile in stdFiles.items():
                if not tmpFiles.has_key(stdStem) and not stdFile in defFiles:
                    comparison = self.createFileComparison(test, stdStem, stdFile, None, testInProgress)
                    if comparison:
                        self.addComparison(comparison)
    def getPerformanceStems(self, test):
        return [ "performance" ] + test.getConfigValue("performance_logfile_extractor").keys()
    def createFileComparison(self, test, stem, standardFile, tmpFile, testInProgress=0):
        if stem in self.getPerformanceStems(test):
            if tmpFile:
                return PerformanceFileComparison(test, stem, standardFile, tmpFile, testInProgress)
            else:
                # Don't care if performance is missing
                return None
        else:
            return FileComparison(test, stem, standardFile, tmpFile, testInProgress)
    def categorise(self):
        if self.failedPrediction:
            # Keep the category we had before
            self.freeText += self.getFreeTextInfo()
            return
        if not self.hasResults():
            raise plugins.TextTestError, "No output files at all produced, presuming problems running test " + self.hostString() 
        worstResult = self.getMostSevereFileComparison()
        if not worstResult:
            self.category = "success"
        else:
            self.category = worstResult.getType()
            self.freeText = self.getFreeTextInfo()
    def getFreeTextInfo(self):
        texts = [ fileComp.getFreeText() for fileComp in self.getSortedComparisons() ] 
        return string.join(texts, "")
    def savePartial(self, fileNames, saveDir, exact = 1, versionString = ""):
        for fileName in fileNames:
            stem = fileName.split(".")[0]
            comparison, storageList = self.findComparison(stem)
            if comparison:
                self.diag.info("Saving single file for stem " + stem)
                comparison.overwrite(saveDir, exact, versionString)
    def findComparison(self, stem):
        lists = [ self.changedResults, self.newResults, self.missingResults ]
        self.diag.info("Finding comparison for stem " + stem)
        for list in lists:
            for comparison in list:
                if comparison.stem == stem:
                    return comparison, list
        return None, None
    def save(self, test, exact = 1, versionString = "", overwriteSuccessFiles = 0):
        # Force exactness unless there is only one difference : otherwise
        # performance is averaged when results have changed as well
        resultCount = len(self.changedResults) + len(self.newResults)
        if resultCount > 1:
            exact = 1
        for comparison in self.changedResults:
            comparison.overwrite(test, exact, versionString)
        for comparison in self.newResults + self.missingResults:
            comparison.overwrite(test, 1, versionString)
        if overwriteSuccessFiles:
            for comparison in self.correctResults:
                comparison.overwrite(test, exact, versionString)
    def makeNewState(self, app):
        newState = TestComparison(self, app, "be saved")
        for comparison in self.allResults:
            newState.addComparison(comparison)
        newState.categorise()
        return newState

class MakeComparisons(plugins.Action):
    defaultComparisonClass = TestComparison
    def __init__(self, testComparisonClass=None):
        if testComparisonClass:
            self.testComparisonClass = testComparisonClass
            MakeComparisons.defaultComparisonClass = testComparisonClass
        else:
            self.testComparisonClass = MakeComparisons.defaultComparisonClass
    def __repr__(self):
        return "Comparing differences for"
    def __call__(self, test):
        testComparison = self.testComparisonClass(test.state, test.app)
        testComparison.makeComparisons(test)
        testComparison.categorise()
        self.describe(test, testComparison.getPostText())
        test.changeState(testComparison)
    def setUpSuite(self, suite):
        self.describe(suite)
    
class RemoveObsoleteVersions(plugins.Action):
    scriptDoc = "Removes (from CVS) all files with version IDs that are equivalent to a non-versioned file"
    def __init__(self):
        self.filesToRemove = []
    def __repr__(self):
        return "Removing obsolete versions for"
    def __call__(self, test):
        self.describe(test)
        compFiles = {}
        for file in test.ownFiles():
            stem = file.split(".")[0]
            compFile = self.filterFile(test, file)
            if compFiles.has_key(stem):
                compFiles[stem].append(compFile)
            else:
                compFiles[stem] = [ compFile ]
        for compFilesMatchingStem in compFiles.values():
            for index1 in range(len(compFilesMatchingStem)):
                for index2 in range(index1 + 1, len(compFilesMatchingStem)):
                    self.compareFiles(test, compFilesMatchingStem[index1], compFilesMatchingStem[index2])
                os.remove(compFilesMatchingStem[index1])
        for file in self.filesToRemove:
            os.system("cvs rm -f " + file)
        self.filesToRemove = []
    def cmpFile(self, test, file):
        basename = os.path.basename(file)
        return mktemp(basename + "cmp")
    def origFile(self, test, file):
        if file.endswith("cmp"):
            return test.getFileName(os.path.basename(file)[:-3])
        else:
            return file
    def filterFile(self, test, file):
        newFile = self.cmpFile(test, file)
        filter = RunDependentTextFilter(test, os.path.basename(file).split(".")[0])
        return filter.filterFile(file, newFile)
    def compareFiles(self, test, file1, file2):
        origFile1 = self.origFile(test, file1)
        origFile2 = self.origFile(test, file2)
        if origFile1 in self.filesToRemove or origFile2 in self.filesToRemove:
            return
        if filecmp.cmp(file1, file2, 0):
            local1 = os.path.basename(origFile1)
            local2 = os.path.basename(origFile2)
            if local1.find(local2) != -1:
                print test.getIndent() + local1, "obsolete due to", local2
                self.filesToRemove.append(origFile1)
            elif local2.find(local1) != -1:
                print test.getIndent() + local2, "obsolete due to", local1
                self.filesToRemove.append(origFile2)
            else:
                print test.getIndent() + local1, "equivalent to", local2
    def setUpSuite(self, suite):
        self.describe(suite)
