#!/usr/bin/env python


import os

if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0]))))

import plugins, fpdiff, logging, shutil
from ndict import seqdict
from re import sub
from optparse import OptionParser

# Generic base class for filtering standard and temporary files
class FilterAction(plugins.Action):
    def __init__(self):
        self.diag = logging.getLogger("Filter Actions")
    def __call__(self, test):
        for fileName, postfix in self.filesToFilter(test):
            self.diag.info("Considering for filtering : " + fileName)
            stem = os.path.basename(fileName).split(".")[0]
            newFileName = test.makeTmpFileName(stem + "." + test.app.name + postfix, forFramework=1)
            self.performAllFilterings(test, stem, fileName, newFileName)

    def performAllFilterings(self, test, stem, fileName, newFileName):
        currFile = fileName
        filters = self.makeAllFilters(test, stem)
        for fileFilter, extraPostfix in filters:
            writeFile = newFileName + extraPostfix
            self.diag.info("Applying " + fileFilter.__class__.__name__ + " to make\n" + writeFile + " from\n " + currFile) 
            if os.path.isfile(writeFile):
                self.diag.info("Removing previous file at " + writeFile)
                os.remove(writeFile)
            fileFilter.filterFile(currFile, writeFile)
            currFile = writeFile
        if len(filters) > 0 and currFile != newFileName:
            shutil.move(currFile, newFileName)

    def makeAllFilters(self, test, stem):
        filters = self._makeAllFilters(test, stem)
        if len(filters) == 0 and self.changedOs(test.app):
            return  [ (RunDependentTextFilter([], ""), "") ]
        else:
            return filters

    def _makeAllFilters(self, test, stem):                    
        filters = []
        runDepTexts = test.getCompositeConfigValue("run_dependent_text", stem)
        if runDepTexts:
            filters.append((RunDependentTextFilter(runDepTexts, test.getRelPath()), ".normal"))

        unorderedTexts = test.getCompositeConfigValue("unordered_text", stem)
        if unorderedTexts:
            filters.append((UnorderedTextFilter(unorderedTexts, test.getRelPath()), ".sorted"))
        return filters
            
    def changedOs(self, app):
        homeOs = app.getConfigValue("home_operating_system")
        return homeOs != "any" and os.name != homeOs

    def constantPostfix(self, files, postfix):
        return [ (file, postfix) for file in files ]
        

class FilterOriginal(FilterAction):
    def filesToFilter(self, test):
        resultFiles, defFiles = test.listStandardFiles(allVersions=False)
        return self.constantPostfix(resultFiles + defFiles, "origcmp")

class FilterTemporary(FilterAction):
    def filesToFilter(self, test):
        return self.constantPostfix(test.listTmpFiles(), "cmp")

    def _makeAllFilters(self, test, stem):
        filters = FilterAction._makeAllFilters(self, test, stem)
        floatTolerance = test.getCompositeConfigValue("floating_point_tolerance", stem)
        if floatTolerance:
            origFile = test.makeTmpFileName(stem + "." + test.app.name + "origcmp", forFramework=1)
            if not os.path.isfile(origFile):
                origFile = test.getFileName(stem)
            if origFile and os.path.isfile(origFile):
                filters.append((FloatingPointFilter(origFile, floatTolerance), ".fpdiff"))
        return filters
    

class FilterProgressRecompute(FilterAction):
    def filesToFilter(self, test):
        return self.constantPostfix(test.listTmpFiles(), "partcmp")


class FilterResultRecompute(FilterAction):
    def filesToFilter(self, test):
        result = []
        for fileComp in test.state.allResults:
            # Either of these files might have disappeared
            if fileComp.stdFile and os.path.isfile(fileComp.stdFile):
                result.append((fileComp.stdFile, "origcmp"))
            if fileComp.tmpFile and os.path.isfile(fileComp.tmpFile):
                result.append((fileComp.tmpFile, "cmp"))
        return result

class FloatingPointFilter:
    def __init__(self, origFileName, tolerance):
        self.origFileName = origFileName
        self.tolerance = tolerance

    def filterFile(self, fileName, newFileName):
        fromlines = open(self.origFileName, "rU").readlines()
        tolines = open(fileName).readlines()
        newFile = plugins.openForWrite(newFileName)
        fpdiff.fpfilter(fromlines, tolines, newFile, self.tolerance)


class RunDependentTextFilter(plugins.Observable):
    def __init__(self, filterTexts, testId=""):
        plugins.Observable.__init__(self)
        self.diag = logging.getLogger("Run Dependent Text")
        self.lineFilters = [ LineFilter(text, testId, self.diag) for text in filterTexts ]

    def filterFile(self, fileName, newFileName):
        self.diag.info("Filtering " + fileName + " to create " + newFileName)
        file = open(fileName, "rU") # use universal newlines to simplify
        newFile = plugins.openForWrite(newFileName)
        self.filterFileObject(file, newFile)

    def filterFileObject(self, file, newFile, filteredAway=None):
        lineNumber = 0
        for line in file.xreadlines():
            # We don't want to stack up ActionProgreess calls in ThreaderNotificationHandler ...
            self.notifyIfMainThread("ActionProgress", "")
            lineNumber += 1
            lineFilter, filteredLine = self.getFilteredLine(line, lineNumber)
            if filteredLine:
                newFile.write(filteredLine)
            elif filteredAway is not None and lineFilter is not None:
                filteredAway.setdefault(lineFilter, []).append(line)

    def getFilteredLine(self, line, lineNumber):
        for lineFilter in self.lineFilters:
            changed, filteredLine = lineFilter.applyTo(line, lineNumber)
            if changed:
                if not filteredLine:
                    return lineFilter, filteredLine
                line = filteredLine
        return None, line


class UnorderedTextFilter(RunDependentTextFilter):
    def filterFileObject(self, file, newFile):
        unorderedLines = {}
        RunDependentTextFilter.filterFileObject(self, file, newFile, unorderedLines)
        self.writeUnorderedText(newFile, unorderedLines)

    def writeUnorderedText(self, newFile, lines):
        for filter in self.lineFilters:
            unordered = lines.get(filter, [])
            if len(unordered) == 0:
                continue
            unordered.sort()
            newFile.write("-- Unordered text as found by filter '" + filter.originalText + "' --" + "\n")
            for line in unordered:
                newFile.write(line)
            newFile.write("\n")
  

class LineNumberTrigger:
    def __init__(self, lineNumber):
        self.lineNumber = lineNumber
    def __repr__(self):
        return "Line number trigger for line " + str(self.lineNumber)
    def matches(self, line, lineNumber):
        return lineNumber == self.lineNumber
    def replace(self, line, newText):
        return newText + "\n"

def getWriteDirRegexp(testId):
    # Some stuff, a date, and the testId (ignore the appId as we don't know when or where)
    return "[^ \"=]*/[^ \"=]*[0-3][0-9][A-Za-z][a-z][a-z][0-9]{6}[^ \"=]*/" + testId

class LineFilter:
    divider = "{->}"
    # All syntax that affects how a match is found
    matcherStrings = [ "{LINE ", "{INTERNAL " ]
    # All syntax that affects what is done when a match is found
    matchModifierStrings = [ "{WORD ", "{REPLACE ", "{LINES " ]
    internalExpressions = { "writedir" : getWriteDirRegexp }
    def __init__(self, text, testId, diag):
        self.originalText = text
        self.testId = testId
        self.diag = diag
        self.triggers = []
        self.untrigger = None
        self.linesToRemove = 1
        self.autoRemove = 0
        self.wordNumber = None
        self.replaceText = None
        self.removeWordsAfter = 0
        self.parseOriginalText()

    def getInternalExpression(self, parameter):
        method = self.internalExpressions.get(parameter)
        return method(self.testId)
    
    def makeRegexTriggers(self, parameter):
        expression = self.getInternalExpression(parameter)
        triggers = [ plugins.TextTrigger(expression) ]
        if parameter == "writedir":
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
    def applyTo(self, line, lineNumber=0):
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
            return " ".join(words).rstrip() + "\n"
        elif trigger and self.replaceText != None:
            return trigger.replace(line, self.replaceText)

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
            if len(word):
                if wordNumber == self.wordNumber:
                    return realWordNumber
                wordNumber -= 1
        return len(words) + 1

if __name__ == "__main__":
    parser = OptionParser("usage: %prog [options] filter1 filter2 ...")
    parser.add_option("-u", "--unordered", action="store_true", 
                      help='Use unordered filter instead of standard one')
    parser.add_option("-t", "--testrelpath", 
                      help="use test relative path RELPATH", metavar="RELPATH")
    (options, args) = parser.parse_args()
    allPaths = plugins.findDataPaths([ "logging.console" ], dataDirName="log", includePersonal=True)
    plugins.configureLogging(allPaths[-1]) # Won't have any effect if we've already got a log file
    if options.unordered:
        runDepFilter = UnorderedTextFilter(args, options.testrelpath)
    else:
        runDepFilter = RunDependentTextFilter(args, options.testrelpath)
    runDepFilter.filterFileObject(sys.stdin, sys.stdout)
