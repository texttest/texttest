#!/usr/local/bin/python


import os, filecmp, plugins, time, stat, subprocess
from ndict import seqdict
from shutil import copyfile
from fnmatch import fnmatch

class FileComparison:
    def __init__(self, test, stem, standardFile, tmpFile, testInProgress=False, observers={}):
        self.stdFile = standardFile
        self.stdCmpFile = self.stdFile
        self.tmpFile = tmpFile
        self.tmpCmpFile = tmpFile
        self.stem = stem
        self.differenceCache = False
        self.recalculationTime = None
        self.diag = plugins.getDiagnostics("FileComparison")
        self.severity = test.getCompositeConfigValue("failure_severity", self.stem)
        self.displayPriority = test.getCompositeConfigValue("failure_display_priority", self.stem)
        maxLength = test.getConfigValue("lines_of_text_difference")
        maxWidth = test.getConfigValue("max_width_text_difference")
        # It would be nice if this could be replaced by some automagic file type detection
        # mechanism, such as the *nix 'file' command, but as the first implementation I've
        # chosen to use a manually created list instead.
        self.binaryFile = self.checkIfBinaryFile(test)
        self.previewGenerator = plugins.PreviewGenerator(maxWidth, maxLength)
        self.textDiffTool = test.getConfigValue("text_diff_program")
        self.textDiffToolMaxSize = plugins.parseBytes(test.getConfigValue("text_diff_program_max_file_size"))
        self.freeTextBody = None
        self.findAndCompare(test, standardFile, testInProgress)
    def findAndCompare(self, test, standardFile, testInProgress=False):
        self.stdFile = standardFile
        self.stdCmpFile = self.stdFile
        self.diag.info("File comparison std: " + repr(self.stdFile) + " tmp: " + repr(self.tmpFile))
        # subclasses may override if they don't want to store in this way
        self.cacheDifferences(test, testInProgress)
    def recompute(self, test, stdFile):
        if self.needsRecalculation():
            self.recalculationTime = time.time()
            self.freeTextBody = None
        if os.path.isfile(self.tmpFile):
            self.findAndCompare(test, stdFile)
    def __getstate__(self):
        # don't pickle the diagnostics
        state = {}
        for var, value in self.__dict__.items():
            if var != "diag" and var != "recalculationTime":
                state[var] = value
        return state
    def __setstate__(self, state):
        self.__dict__ = state
        self.diag = plugins.getDiagnostics("TestComparison")
        self.recalculationTime = None
        if not hasattr(self, "differenceCache"):
            self.differenceCache = self.differenceId
        
    def __repr__(self):
        return self.stem
    def checkIfBinaryFile(self, test):
        for binPattern in test.getConfigValue("binary_file"):
            if fnmatch(self.stem, binPattern):
                return True
        return False
    def modifiedDates(self):
        files = [ self.stdFile, self.tmpFile, self.stdCmpFile, self.tmpCmpFile ]
        return " : ".join(map(self.modifiedDate, files))
    def modifiedDate(self, file):
        if not file:
            return "---"
        modTime = plugins.modifiedTime(file)
        if modTime:
            return time.strftime("%d%b%H:%M:%S", time.localtime(modTime))
        else:
            return "---"
    def needsRecalculation(self):
        if not self.stdFile or not self.tmpFile:
            self.diag.info("No comparison, no recalculation")
            return False

        # A test that has been saved doesn't need recalculating
        if self.tmpFile == self.stdFile:
            self.diag.info("Saved file, no recalculation")
            return False

        stdModTime = plugins.modifiedTime(self.stdFile)
        if self.recalculationTime:
            self.diag.info("Already recalculated, checking if file updated since then : " + self.stdFile)
            # If we're already recalculated, only do it again if standard file changes since then
            return stdModTime > self.recalculationTime
        
        tmpModTime = plugins.modifiedTime(self.tmpFile)
        if stdModTime is not None and tmpModTime is not None and stdModTime >= tmpModTime:
            self.diag.info("Standard result newer than generated result at " + self.stdFile)
            return True

        if self.stdFile == self.stdCmpFile: # no filters
            return False
        
        stdCmpModTime = plugins.modifiedTime(self.stdCmpFile)
        self.diag.info("Comparing timestamps for standard files")
        return stdCmpModTime is not None and stdModTime is not None and stdModTime >= stdCmpModTime
    def getType(self):
        return "failure"
    def getDisplayFileName(self):
        if self.newResult():
            return self.tmpFile
        else:
            return self.stdFile
    def getDetails(self):
        # Nothing to report above what is already known
        return ""
    def newResult(self):
        return not self.stdFile and self.tmpFile
    def missingResult(self):
        return self.stdFile and not self.tmpFile
    def isDefunct(self):
        return not self.stdFile and not self.tmpFile
    def hasSucceeded(self):
        return self.stdFile and self.tmpFile and not self.hasDifferences()
    def hasDifferences(self):
        return self.differenceCache
    def getStdFile(self, filtered):
        if filtered:
            return self.stdCmpFile
        else:
            return self.stdFile
    def getTmpFile(self, filtered):
        if filtered:
            return self.tmpCmpFile
        else:
            return self.tmpFile
    def existingFile(self, filtered):
        if self.missingResult():
            return self.getStdFile(filtered)
        else:
            return self.getTmpFile(filtered)
    def cacheDifferences(self, test, testInProgress):
        filterFileBase = test.makeTmpFileName(self.stem + "." + test.app.name, forFramework=1)
        origCmp = filterFileBase + "origcmp"
        if os.path.isfile(origCmp):
            self.stdCmpFile = origCmp
        tmpCmpFileName = filterFileBase + "cmp"
        if testInProgress:
            tmpCmpFileName = filterFileBase + "partcmp"
        if os.path.isfile(tmpCmpFileName):
            self.tmpCmpFile = tmpCmpFileName

        if self.stdCmpFile and self.tmpCmpFile:
            self.differenceCache = not filecmp.cmp(self.stdCmpFile, self.tmpCmpFile, 0)
    def getSummary(self, includeNumbers=True):
        if self.newResult():
            return self.stem + " new"
        elif self.missingResult():
            return self.stem + " missing"
        else:
            return self.getDifferencesSummary(includeNumbers)
    def getDifferencesSummary(self, includeNumbers=True):
        return self.stem + " different"
    def getFreeText(self):
        return self.getFreeTextTitle() + "\n" + self.getFreeTextBody()
    def getFreeTextTitle(self):
        if self.missingResult():
            titleText = "Missing result in"
        elif self.newResult():
            titleText = "New result in"
        else:
            titleText = "Differences in"
        titleText += " " + repr(self)
        return "-" * 10 + " " + titleText + " " + "-" * 10
    def getFreeTextBody(self):
        if self.freeTextBody is None:
            self.freeTextBody = self._getFreeTextBody()
        return self.freeTextBody
    def _getFreeTextBody(self):
        if self.binaryFile and \
               (self.newResult() or self.missingResult()):
            message = "Binary file, not showing any preview. " + \
                      "Edit the configuration entry 'binary_file' and re-run if you suspect that this file contains only text.\n"
            return self.previewGenerator.getWrappedLine(message)
        elif self.newResult():
            return self.previewGenerator.getPreview(open(self.tmpCmpFile))
        elif self.missingResult():
            return self.previewGenerator.getPreview(open(self.stdCmpFile))

        try:
            stdFileSize = os.stat(self.stdCmpFile)[stat.ST_SIZE]
            tmpFileSize = os.stat(self.tmpCmpFile)[stat.ST_SIZE]
            if self.textDiffToolMaxSize >= 0 and \
                   (stdFileSize > self.textDiffToolMaxSize or \
                    tmpFileSize > self.textDiffToolMaxSize):
                message = "The result files were too large to compare - " + str(stdFileSize) + " and " + \
                          str(tmpFileSize) + " bytes, compared to the limit of " + str(self.textDiffToolMaxSize) + \
                          " bytes. Double-click on the file to see the difference, or adjust the configuration entry 'text_diff_program_max_file_size'" + \
                          " and re-run to see the difference in this text view.\n"
                return self.previewGenerator.getWrappedLine(message)

            cmdArgs = plugins.splitcmd(self.textDiffTool) + [ self.stdCmpFile, self.tmpCmpFile ]
            proc = subprocess.Popen(cmdArgs, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            return self.previewGenerator.getPreview(proc.stdout)
        except OSError:
            return "No difference report could be created: could not find textual difference tool '" + self.textDiffTool + "'"
    def updatePaths(self, oldAbsPath, newAbsPath):
        if self.stdFile:
            self.stdFile = self.stdFile.replace(oldAbsPath, newAbsPath)
            self.stdCmpFile = self.stdCmpFile.replace(oldAbsPath, newAbsPath)
        if self.tmpFile:
            self.tmpCmpFile = self.tmpCmpFile.replace(oldAbsPath, newAbsPath)
            self.tmpFile = self.tmpFile.replace(oldAbsPath, newAbsPath)
    def versionise(self, fileName, versionString):
        if len(versionString):
            return fileName + "." + versionString
        else:
            return fileName
    def getStdRootVersionFile(self):
        # drop version identifiers
        dirname, local = os.path.split(self.stdFile)
        localRoot = ".".join(local.split(".")[:2])
        return os.path.join(dirname, localRoot)
    def overwrite(self, test, exact, versionString):
        self.diag.info("save file from " + self.tmpFile)
        stdRoot = self.getStdRootVersionFile()
        self.stdFile = self.versionise(stdRoot, versionString)
        if os.path.isfile(self.stdFile):
            os.remove(self.stdFile)

        self.saveTmpFile(exact)
    def saveNew(self, test, versionString, diags):
        self.stdFile = os.path.join(test.getDirectory(), self.versionise(self.stem + "." + test.app.name, versionString))
        self.saveTmpFile()
    def saveTmpFile(self, exact=True):
        self.diag.info("Saving tmp file to " + self.stdFile)
        plugins.ensureDirExistsForFile(self.stdFile)
        # Allow for subclasses to differentiate between a literal overwrite and a
        # more intelligent save, e.g. for performance. Default is the same for exact
        # and inexact save
        if exact:
            copyfile(self.tmpFile, self.stdFile)
        else:
            self.saveResults(self.stdFile)
        # Try to get everything to behave normally after a save...
        self.differenceCache = False
        self.tmpFile = self.stdFile
        self.tmpCmpFile = self.stdFile
    def saveMissing(self, versionString, autoGenText):
        stdRoot = self.getStdRootVersionFile()
        targetFile = self.versionise(stdRoot, versionString)
        if os.path.isfile(targetFile):
            os.remove(targetFile)

        self.stdFile = None
        self.stdCmpFile = None
        if stdRoot != targetFile and os.path.isfile(stdRoot):
            # Create a "versioned-missing" file
            newFile = open(targetFile, "w")
            newFile.write(autoGenText)
            newFile.close()
    def saveResults(self, destFile):
        copyfile(self.tmpFile, destFile)
        
