#!/usr/local/bin/python


import os, filecmp, string, plugins, time, stat
from ndict import seqdict
from shutil import copyfile
from re import sub

class FileComparison:
    def __init__(self, test, stem, standardFile, tmpFile, testInProgress = 0, observers={}):
        self.stdFile = standardFile
        self.tmpFile = tmpFile
        self.stem = stem
        self.differenceCache = False 
        self.diag = plugins.getDiagnostics("FileComparison")
        filter = RunDependentTextFilter(test, self.stem)
        filter.setObservers(observers)
        filterFileBase = test.makeTmpFileName(stem + "." + test.app.name, forFramework=1)
        self.stdCmpFile = filter.filterFile(standardFile, filterFileBase + "origcmp", makeNew=0)
        tmpCmpFileName = filterFileBase + "cmp"
        if testInProgress:
            tmpCmpFileName = filterFileBase + "partcmp"
        self.tmpCmpFile = filter.filterFile(tmpFile, tmpCmpFileName, makeNew=testInProgress)
        self.diag.info("File comparison std: " + repr(self.stdFile) + " tmp: " + repr(self.tmpFile))
        self.severity = test.getCompositeConfigValue("failure_severity", self.stem)
        self.displayPriority = test.getCompositeConfigValue("failure_display_priority", self.stem)
        maxLength = test.getConfigValue("lines_of_text_difference")
        maxWidth = test.getConfigValue("max_width_text_difference")
        self.previewGenerator = plugins.PreviewGenerator(maxWidth, maxLength)
        self.textDiffTool = test.getConfigValue("text_diff_program")
        self.textDiffToolMaxSize = plugins.parseBytes(test.getConfigValue("text_diff_program_max_file_size"))
        # subclasses may override if they don't want to store in this way
        self.cacheDifferences()
    def __repr__(self):
        return self.stem
    def ensureCompatible(self):
        if not hasattr(self, "differenceCache"):
            self.differenceCache = self.differenceId
    def modifiedDates(self):
        files = [ self.stdFile, self.tmpFile, self.stdCmpFile, self.tmpCmpFile ]
        return string.join(map(self.modifiedDate, files), " : ")
    def modifiedDate(self, file):
        if not file:
            return "---"
        modTime = plugins.modifiedTime(file)
        if modTime:
            return time.strftime("%d%b%H:%M:%S", time.localtime(modTime))
        else:
            return "---"
    def needsRecalculation(self):
        # A test that has been saved doesn't need recalculating
        if self.tmpCmpFile == self.stdCmpFile or self.stdCmpFile == self.stdFile:
            return 0
        
        if self.tmpFile and (plugins.modifiedTime(self.tmpCmpFile) < plugins.modifiedTime(self.tmpFile)):
            return 1
        return not self.newResult() and not self.missingResult() and \
               (plugins.modifiedTime(self.stdCmpFile) <= plugins.modifiedTime(self.stdFile))
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
    def getSummary(self):
        return self.stem + " different"
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
    def cacheDifferences(self):
        if self.stdCmpFile and self.tmpCmpFile:
            self.differenceCache = not filecmp.cmp(self.stdCmpFile, self.tmpCmpFile, 0)
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
        return "------------------ " + titleText + " --------------------"
    def getFreeTextBody(self):
        if self.newResult():
            return self.previewGenerator.getPreview(open(self.tmpCmpFile))
        elif self.missingResult():
            return self.previewGenerator.getPreview(open(self.stdCmpFile))

        if plugins.canExecute(self.textDiffTool):
            stdFileSize = os.stat(self.stdCmpFile)[stat.ST_SIZE]
            tmpFileSize = os.stat(self.tmpCmpFile)[stat.ST_SIZE]
            if self.textDiffToolMaxSize >= 0 and (stdFileSize > self.textDiffToolMaxSize or tmpFileSize > self.textDiffToolMaxSize):
                message = "Warning: The files were too large to compare - " + str(stdFileSize) + " and " + \
                          str(tmpFileSize) + " bytes, compared to the limit of " + str(self.textDiffToolMaxSize) + \
                          " bytes. Double-click on the file to see the difference, or adjust text_diff_program_max_file_size" + \
                          " and re-run to see the difference in this text view.\n"
                return self.previewGenerator.getWrappedLine(message)
            
            cmdLine = self.textDiffTool + " '" + self.stdCmpFile + "' '" + self.tmpCmpFile + "'"
            stdout = os.popen(cmdLine)
            return self.previewGenerator.getPreview(stdout)
        else:
            return "No difference report could be created: could not find textual difference tool '" + self.textDiffTool + "'"
    def updatePaths(self, oldAbsPath, newAbsPath):
        if self.stdFile:
            self.stdFile = self.stdFile.replace(oldAbsPath, newAbsPath)
            self.stdCmpFile = self.stdCmpFile.replace(oldAbsPath, newAbsPath)
        if self.tmpFile:
            self.tmpCmpFile = self.tmpCmpFile.replace(oldAbsPath, newAbsPath)
            self.tmpFile = self.tmpFile.replace(oldAbsPath, newAbsPath)
    def saveTmpFile(self, test, exact, versionString):
        self.stdFile = test.getSaveFileName(self.tmpFile, versionString)
        if os.path.isfile(self.stdFile):
            os.remove(self.stdFile)
        plugins.ensureDirExistsForFile(self.stdFile)
        # Allow for subclasses to differentiate between a literal overwrite and a
        # more intelligent save, e.g. for performance. Default is the same for exact
        # and inexact save
        if exact:
            copyfile(self.tmpFile, self.stdFile)
        else:
            self.saveResults(self.stdFile)
    def overwrite(self, test, exact, versionString = ""):
        if self.missingResult():
            os.remove(self.stdFile)
            self.stdFile = None
        else:
            self.saveTmpFile(test, exact, versionString)
            
        # Try to get everything to behave normally after a save...
        self.differenceCache = False
        self.tmpFile = self.stdFile
        self.tmpCmpFile = self.stdCmpFile
    def saveResults(self, destFile):
        copyfile(self.tmpFile, destFile)
        
class RunDependentTextFilter(plugins.Observable):
    def __init__(self, test, stem):
        plugins.Observable.__init__(self)
        self.diag = plugins.getDiagnostics("Run Dependent Text")
        regexp = self.getWriteDirRegexp(test)
        runDepTexts = test.getCompositeConfigValue("run_dependent_text", stem)
        self.contentFilters = [ LineFilter(text, regexp, self.diag) for text in runDepTexts ]
        self.orderFilters = seqdict()
        for text in test.getCompositeConfigValue("unordered_text", stem):
            orderFilter = LineFilter(text, regexp, self.diag)
            self.orderFilters[orderFilter] = []
        self.osChange = self.changedOs(test.app)
    def changedOs(self, app):
        homeOs = app.getConfigValue("home_operating_system")
        if homeOs == "any":
            return 0
        return os.name != homeOs
    def hasFilters(self):
        return len(self.contentFilters) > 0 or len(self.orderFilters) > 0
    def shouldFilter(self, fileName, newFileName):
        if not fileName:
            return 0
        if self.hasFilters():
            return 1
        # Force recomputation of files that come from other operating systems...
        return self.osChange
    def filterFile(self, fileName, newFileName, makeNew):
        if not self.shouldFilter(fileName, newFileName):
            self.diag.info("No filter for " + repr(fileName))
            return fileName

        # Don't recreate filtered files, unless makeNew is set or they're out of date...
        if os.path.isfile(newFileName):
            newModTime = plugins.modifiedTime(newFileName)
            oldModTime = plugins.modifiedTime(fileName)
            self.diag.info("Filter file exists, modified at " + str(newModTime) + " (original updated at " + str(oldModTime) + ")")
            if makeNew or newModTime <= oldModTime:
                os.remove(newFileName)
            else:
                return newFileName

        self.diag.info("Filtering " + fileName + " to create " + newFileName)
        self.resetFilters()
        newFile = open(newFileName, "w")
        lineNumber = 0
        for line in open(fileName).xreadlines():
            # We don't want to stack up ActionProgreess calls in ThreaderNotificationHandler ...
            self.notifyIfMainThread("ActionProgress", "")
            lineNumber += 1
            filteredLine = self.getFilteredLine(line, lineNumber)
            if filteredLine:
                newFile.write(filteredLine)
        self.writeUnorderedText(newFile)
        return newFileName
    def resetFilters(self):
        for filter in self.contentFilters:
            filter.reset()
        for filter in self.orderFilters.keys():
            filter.reset()
    def getFilteredLine(self, line, lineNumber):
        for contentFilter in self.contentFilters:
            changed, filteredLine = contentFilter.applyTo(line, lineNumber)
            if changed:
                if not filteredLine:
                    return filteredLine
                line = filteredLine
        for orderFilter in self.orderFilters.keys():
            changed, filteredLine = orderFilter.applyTo(line, lineNumber)
            if changed:
                if not filteredLine:
                    filteredLine = line
                self.orderFilters[orderFilter].append(filteredLine)
                return ""
        return line
    def writeUnorderedText(self, newFile):
        for filter, linesFiltered in self.orderFilters.items():
            if len(linesFiltered) == 0:
                continue
            linesFiltered.sort()
            newFile.write("-- Unordered text as found by filter '" + filter.originalText + "' --" + "\n")
            for line in linesFiltered:
                newFile.write(line)
            newFile.write("\n")
            self.orderFilters[filter] = []
    def getWriteDirRegexp(self, test):
        dateRegexp = "[0-3][0-9][A-Za-z][a-z][a-z][0-9][0-9][0-9][0-9][0-9][0-9]"
        return "[^ \"=]*/" + test.app.name + "[^/]*" + dateRegexp + "/" + test.getRelPath()

class LineNumberTrigger:
    def __init__(self, lineNumber):
        self.lineNumber = lineNumber
    def __repr__(self):
        return "Line number trigger for line " + str(self.lineNumber)
    def matches(self, line, lineNumber):
        return lineNumber == self.lineNumber
    def replace(self, line, newText):
        return newText

class LineFilter:
    divider = "{->}"
    # All syntax that affects how a match is found
    matcherStrings = [ "{LINE ", "{INTERNAL " ]
    # All syntax that affects what is done when a match is found
    matchModifierStrings = [ "{WORD ", "{REPLACE ", "{LINES " ]
    def __init__(self, text, writeDirRegexp, diag):
        self.originalText = text
        self.diag = diag
        self.triggers = []
        self.untrigger = None
        self.linesToRemove = 1
        self.autoRemove = 0
        self.wordNumber = None
        self.replaceText = None
        self.removeWordsAfter = 0
        self.internalExpressions = { "writedir" : writeDirRegexp }
        self.parseOriginalText()
    def makeRegexTriggers(self, parameter):
        expression = self.internalExpressions.get(parameter, parameter)
        triggers = [ plugins.TextTrigger(expression) ]
        if parameter == "writedir" and os.name != "posix":
            triggers.append(plugins.TextTrigger(expression.replace("/", "\\\\")))
        return triggers
    def parseOriginalText(self):
        dividerPoint = self.originalText.find(self.divider)
        if dividerPoint != -1:
            beforeText, afterText, parameter = self.extractParameter(self.originalText, dividerPoint, self.divider)
            self.triggers = self.parseText(beforeText)
            self.untrigger = self.parseText(afterText)[0]
        else:
            self.triggers = self.parseText(self.originalText)
        self.diag.info("Created triggers : " + repr(self.triggers))
    def parseText(self, text):
        for matchModifierString in self.matchModifierStrings:
            linePoint = text.find(matchModifierString)
            if linePoint != -1:
                beforeText, afterText, parameter = self.extractParameter(text, linePoint, matchModifierString)
                self.readMatchModifier(matchModifierString, parameter)
                text = beforeText + afterText
        matcherString, parameter = self.findMatcherInfo(text)
        return self.createTriggers(matcherString, parameter)
    def findMatcherInfo(self, text):
        for matcherString in self.matcherStrings:
            linePoint = text.find(matcherString)
            if linePoint != -1:
                beforeText, afterText, parameter = self.extractParameter(text, linePoint, matcherString)
                return matcherString, parameter
        return "", text
    def reset(self):
        self.autoRemove = 0
    def extractParameter(self, textToParse, linePoint, syntaxString):
        beforeText = textToParse[:linePoint]
        afterText = textToParse[linePoint + len(syntaxString):]
        endPos = afterText.find("}")
        parameter = afterText[:endPos]
        afterText = afterText[endPos + 1:]
        return beforeText, afterText, parameter
    def readMatchModifier(self, matchModifierString, parameter):
        if matchModifierString == "{REPLACE ":
            self.replaceText = parameter
        elif matchModifierString == "{WORD ":
            if parameter.endswith("+"):
                self.removeWordsAfter = 1
                self.wordNumber = int(parameter[:-1])
            else:
                self.wordNumber = int(parameter)
            # Somewhat non-intuitive to count from 0...
            if self.wordNumber > 0:
                self.wordNumber -= 1
        elif matchModifierString == "{LINES ":
            self.linesToRemove = int(parameter)
    def createTriggers(self, matcherString, parameter):
        if matcherString == "{LINE ":
            return [ LineNumberTrigger(int(parameter)) ]
        elif matcherString == "{INTERNAL " and self.internalExpressions.has_key(parameter):
            return self.makeRegexTriggers(parameter)
        else:
            return [ plugins.TextTrigger(parameter) ]
    def applyTo(self, line, lineNumber):
        if self.autoRemove:
            return self.applyAutoRemove(line)

        trigger = self.getMatchingTrigger(line, lineNumber)
        if trigger:
            return self.applyMatchingTrigger(line, trigger)
        else:
            return False, line
    def applyAutoRemove(self, line):
        if self.untrigger:
            if self.untrigger.matches(line.strip()):
                self.diag.info(repr(self.untrigger) + " (end) matched " + line) 
                self.autoRemove = 0
                return False, line
        else:
            self.autoRemove -= 1
        return True, self.filterWords(line)
    def applyMatchingTrigger(self, line, trigger):
        if self.untrigger:
            self.autoRemove = 1
            return False, line
        if self.linesToRemove:
            self.autoRemove = self.linesToRemove - 1
        return True, self.filterWords(line, trigger)
    def getMatchingTrigger(self, line, lineNumber):
        for trigger in self.triggers:
            if trigger.matches(line, lineNumber):
                self.diag.info(repr(trigger) + " matched " + line)
                return trigger
    def filterWords(self, line, trigger=None):
        if self.wordNumber != None:
            words = line.rstrip().split(" ")
            self.diag.info("Removing word " + str(self.wordNumber) + " from " + repr(words))
            realNumber = self.findRealWordNumber(words)
            self.diag.info("Real number was " + str(realNumber))
            if realNumber < len(words):
                if self.removeWordsAfter:
                    words = words[:realNumber]
                    if self.replaceText:
                        words.append(self.replaceText)
                else:
                    if self.replaceText:
                        words[realNumber] = self.replaceText
                    else:
                        del words[realNumber]
            return string.join(words).rstrip() + "\n"
        elif trigger and self.replaceText != None:
            return trigger.replace(line, self.replaceText)
        else:
            return None
    def findRealWordNumber(self, words):
        if self.wordNumber < 0:
            return self.findRealWordNumberBackwards(words)
        wordNumber = 0
        for realWordNumber in range(len(words)):
            if len(words[realWordNumber]):
                if wordNumber == self.wordNumber:
                    return realWordNumber
                wordNumber += 1
        return len(words) + 1
    def findRealWordNumberBackwards(self, words):
        wordNumber = -1
        for index in range(len(words)):
            realWordNumber = -1 - index
            word = words[realWordNumber]
            if len(words[realWordNumber]):
                if wordNumber == self.wordNumber:
                    return realWordNumber
                wordNumber -= 1
        return len(words) + 1
