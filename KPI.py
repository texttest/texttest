#!/usr/local/bin/python
#
# $Header: /carm/2_CVS/Testing/TextTest/Attic/KPI.py,v 1.2 2003/03/04 11:06:51 henrike Exp $
#
# Script to calculate the KPI (Key Performance Indicator)
#
# Created 2003-02-03 /Henrik
#

import sys, os, re, string, time, shutil
from encodings import raw_unicode_escape
# Test suite imports
import default, carmen, lsf, stat, optimization, plugins


class KPIHandler:
    def __init__(self):
	self.listKPIs = []
	self.intCurrentId = 0
    def addKPI(self, KPI):
	if not self.listKPIs.count(KPI):
	    if not KPI.getId():
		KPI.setId(self._getNextId())
	    self.listKPIs.append(KPI)
	else:
	    raise KPIAlreadyExistError('<Name: %s, Id: %d>' %(KPI.getName(), KPI.getId()))
    def _getNextId(self):
	self.intCurrentId += 1
	return self.intCurrentId
    def removeKPI(self, KPI):
	try:
	    self.listKPIs.remove(KPI)
	except ValueError:
	    raise RemovalOfNonexistingKPIError('<Name: %s>' %(KPI.getName()))
    def getKPIAverage(self):
	"""Returns a tuple (<KPI Average>, <Nr of Valid KPIs>, <Nr of Failed KPIs>)"""
	intNofKPIs = 0
	floatTotalKPI = 0.0
	for aKPI in self.listKPIs:
	    floatCurrKPI = aKPI.getFloatKPI()
	    if floatCurrKPI:
		intNofKPIs += 1
		floatTotalKPI += floatCurrKPI
	if intNofKPIs > 0:
	    return (floatTotalKPI / float(intNofKPIs), intNofKPIs, self.getNrOfKPIs() - intNofKPIs)
	else:
	    return (None, 0, self.getNrOfKPIs())
    def getNrOfKPIs(self):
	return len(self.listKPIs)



class KPI:
    def __init__(self):
	self.iBasics = Basics()
	self.strName = 'KPI'
	self.intId = None
    def getId(self):
	return self.intId
    def setId(self, intId):
	self.intId = intId
    def getName(self):
	return self.strName
    def getFloatKPI(self):
	raise NotImplementedError()


class CurveKPI(KPI):
    def __init__(self, strRefStatusFile, strNowStatusFile):
	KPI.__init__(self)
	self.strName = 'Curve KPI'
	self.cStrRefStatusFile = strRefStatusFile
	self.cStrNowStatusFile = strNowStatusFile

	self.cReCPUTimeParts = re.compile(r'^(?P<hours>\d+):(?P<minutes>\d\d):(?P<seconds>\d\d)$')

    def _setListRegExps(self, listRegExps):
	self.listRegExps = listRegExps
    def _setKeyPoints(self, listKeyPoints):
	self.listKeyPoints = listKeyPoints

    def _convertCPUtoSecs(self, strCPUTime):
	matchCPUTime = self.cReCPUTimeParts.match(strCPUTime)
	if matchCPUTime:
	    return string.atoi(matchCPUTime.group('hours')) * 3600 + string.atoi(matchCPUTime.group('minutes')) * 60 + string.atoi(matchCPUTime.group('seconds'))
	else:
	    #return int(string.atof(strCPUTime)/1000.0)
	    return -1

    def _getKeyPointComponent(self, tupKeyPoint, mapSeriesRef, mapSeriesNow):
	return float(tupKeyPoint[2]) * apply(tupKeyPoint[1], (mapSeriesRef, mapSeriesNow))

    def _getTotalTime(self, listKeyPoints, mapSeriesRef, mapSeriesNow):
	floatTotalTime = 0.0
	for aKeyPoint in listKeyPoints:
	    floatTotalTime += self._getKeyPointComponent(aKeyPoint, mapSeriesRef, mapSeriesNow)
	return floatTotalTime

    def _getIndex(self, listKeyPoints, mapSeriesRef, mapSeriesNow):
	floatNowTime = self._getTotalTime(listKeyPoints, mapSeriesRef, mapSeriesNow)
	floatRefTime  = self._getTotalTime(listKeyPoints, mapSeriesRef, mapSeriesRef)
	return 100.0 * (floatNowTime / floatRefTime)

    def getFloatKPI(self):
	mapSeriesRef = self.iBasics.statusFileToMapOfSeries(self.cStrRefStatusFile, self.listRegExps)
	mapSeriesNow = self.iBasics.statusFileToMapOfSeries(self.cStrNowStatusFile, self.listRegExps)
	try:
	    floatIndex = self._getIndex(self.listKeyPoints, mapSeriesRef, mapSeriesNow)
	    return floatIndex
	except KPIQualityNotReachedError, e:
	    self.iBasics.printWarning(e)
	    return None


class InvertableCurveKPI(CurveKPI):
    def __init__(self, strStatusFile, strUniqueTestString):
	CurveKPI.__init__(self, strStatusFile, strStatusFile)
	self.strUniqueTestString = strUniqueTestString
	self.fCompareMarginPercent = 0.0
    def getUniqueTestString():
	return self.strUniqueTestString
    def setcompareMarginPercent(floatPercent):
	self.fCompareMarginPercent = floatPercent
    def isComparableTo(otherInvertableKPI):
	#!!!Not finished yet!!!
	return self.getUniqueTestString() == otherInvertableKPI.getUniqueTestString()


class RosteringKPI(CurveKPI):
    def __init__(self, strRefStatusFile, strNowStatusFile):
	CurveKPI.__init__(self, strRefStatusFile, strNowStatusFile)
	self.strName = 'Rostering KPI'

	self.cReRosterCost = self.iBasics.getStatusRegExpFromLabel('Total cost of rosters|')
	self.cReUnassignedCost = self.iBasics.getStatusRegExpFromLabel('Total cost of unassigned slots|unassigned rotations')
	self.cReTotalCost = self.iBasics.getStatusRegExpFromLabel('Total cost of plan|APC total rule cost')
	self.cReCPUTime = re.compile(r'^Total time:\D*([\d:]+)\W*cpu time:\D*(?P<value>[\d:]+)$')

	listRegExps = [
	    ('CPU time',        self.cReCPUTime,        self._convertCPUtoSecs),
	    ('Total cost',      self.cReTotalCost,      string.atoi),
	    ('Unassigned cost',  self.cReUnassignedCost, string.atoi),
	    ('Cost of rosters',  self.cReRosterCost,     string.atoi)
	    ]
	self._setListRegExps(listRegExps)

    def _getInitialSolutionTime(self, mapSeriesRef, mapSeriesNow):
	return mapSeriesNow['CPU time'][0]

    def _getFirstReasonableTime(self, mapSeriesRef, mapSeriesNow):
	return 0

    def _getProductionQualityTime(self, mapSeriesRef, mapSeriesNow):
	return 0

    def _getFinalQualityTime(self, mapSeriesRef, mapSeriesNow):
	intFinalQuality = min(mapSeriesRef['Total cost'])
	listSeriesNow = mapSeriesNow['Total cost']
	ixSeriesNow = 0
	while listSeriesNow[ixSeriesNow] > intFinalQuality and ixSeriesNow < len(listSeriesNow) - 1:
	    ixSeriesNow += 1
	if listSeriesNow[ixSeriesNow] <= intFinalQuality:
	    return mapSeriesNow['CPU time'][ixSeriesNow]
	else:
	    #return gVeryLargeInt
	    raise KPIQualityNotReachedError('Final quality')


class FullRosteringOptTimeKPI(RosteringKPI):
    def __init__(self, strRefStatusFile, strNowStatusFile):
	RosteringKPI.__init__(self, strRefStatusFile, strNowStatusFile)
	self.strName = 'Full Rostering Optimization Time KPI'
	listKeyPoints = [
	    ('Initial solution',         self._getInitialSolutionTime,   2),
	    ('First reasonable solution', self._getFirstReasonableTime,   1),
	    ('Production quality',       self._getProductionQualityTime, 2),
	    ('Final quality',           self._getFinalQualityTime,      3),
	    ]
	self._setKeyPoints(listKeyPoints)


class InvertableFullRosteringOptTimeKPI(FullRosteringOptTimeKPI):
    def __init__(self, strStatusFile):
	FullRosteringOptTimeKPI.__init__(self, strStatusFile, strStatusFile)


## class TestInvertableRosteringKPI(InvertableCurveKPI, RosteringKPI):
##     def __init__(self, strStatusFile, strUniqueTestString):
## 	InvertableCurveKPI.__init__(self, strStatusFile, strStatusFile)


class SimpleRosteringOptTimeKPI(RosteringKPI):
    def __init__(self, strRefStatusFile, strNowStatusFile):
	RosteringKPI.__init__(self, strRefStatusFile, strNowStatusFile)
	self.strName = 'Simple Rostering Optimization Time KPI'
	listKeyPoints = [
	    ('Final quality',           self._getFinalQualityTime,      1),
	    ]
	self._setKeyPoints(listKeyPoints)


class Basics:
    def __init__(self):
	self.rawCodec = raw_unicode_escape.Codec
	self.cReStatusSolution = re.compile(r'^(SECTION apc_status|SOLUTION ANALYSIS for) Solution_(?P<nr>\d+).*$')

    # read a file into a buffer and return the buffer
    def readFile(self, filename):
	f = open(filename)
	buffer = map(lambda line: line.strip(), f.readlines())
	f.close()
	return buffer

    # write a file from a list of lines
    def writeFile(self, filename, lines):
	outFile = open(filename, 'w')
	for line in lines:
	    outFile.write(line + '\n')
	outFile.close

    # print warning
    def printWarning(self, strWarning):
	print '  *** Warning: %s\n' %(strWarning)

    #listRegExps = [('CPU time', REGEXP, convertFunc), ...]
    #mapSeries example: {'Total cost': [28692758, 27888892, 27044010], 'CPU time': [2087, 2229, 2405]}
    def statusFileToMapOfSeries(self, strStatusFile, listRegExps):
	listLines = self.readFile(strStatusFile)
	currentSolution = ''
	ixSection = -1
	listValues = []
	for aRegExp in listRegExps:
	    listValues.append([])
	boolFirstSolutionFound = 0
	for aLine in listLines:
	    matchStatusSection = self.cReStatusSolution.match(aLine)
	    if matchStatusSection:
		#listValues.append([-1,] * len(listRegExps))
		map((lambda list: list.append(-1)), listValues)
		ixSection += 1
		boolFirstSolutionFound = 1
	    elif boolFirstSolutionFound:
		for ixRegExp in range(len(listRegExps)):
		    matchRegExp = listRegExps[ixRegExp][1].match(aLine)
		    if matchRegExp:
			#print 'matchRegExp.group(\'value\'): %s' %(matchRegExp.group('value'))
			#print 'ixRegExp: %d, ixSection: %d' %(ixRegExp, ixSection)
			listValues[ixRegExp][ixSection] = apply(listRegExps[ixRegExp][2], (matchRegExp.group('value'),))
	mapSeries = {}
	for ixRegExp in range(len(listRegExps)):
	    mapSeries[listRegExps[ixRegExp][0]] = listValues[ixRegExp][:]
	self._removeNegatives(mapSeries)
	return mapSeries

    def _removeNegatives(self, mapSeries):
	for ixSolution in range(len(mapSeries[mapSeries.keys()[0]])):
	    boolRemoveSolution = 0
	    for keySeries in mapSeries.keys():
		if mapSeries[keySeries][ixSolution] < 0:
		    boolRemoveSolution = 1
	    if boolRemoveSolution:
		for keySeries in mapSeries.keys():
		    del mapSeries[keySeries][ixSolution]

    def getStatusRegExpFromLabel(self, strLabel):
	strRegExp = self.rawCodec.encode('^\W*(%s)[^\d]*(?P<value>\d+).*$' %(strLabel))[0]
	return re.compile(strRegExp)


class KPIQualityNotReachedError(Exception):
    def __init__(self, args=None):
	self.args = args
    def __str__(self):
	return 'KPI could not be calculated since acceptable result for "%s" was not reached.' %(self.args)


class KPIAlreadyExistError(Exception):
    pass

class RemovalOfNonexistingKPIError(Exception):
    pass


class MeasureKPI(plugins.Action):
    def __repr__(self):
        return "Porting old"
    def __call__(self, test):
        testInfo = ApcTestCaseInformation(self.suite, test.name)
        hasPorted = 0
        if test.options[0] == "-":
            hasPorted = 1
            subPlanDirectory = test.options.split()[3]
            carmUsrSubPlanDirectory = testInfo.replaceCarmUsr(subPlanDirectory)
            ruleSetName = testInfo.getRuleSetName(subPlanDirectory)
            newOptions = testInfo.buildOptions(carmUsrSubPlanDirectory, ruleSetName)
            fileName = test.makeFileName("options")
            shutil.copyfile(fileName, fileName + ".oldts")
            os.remove(fileName)
            optionFile = open(fileName,"w")
            optionFile.write(newOptions + "\n")
        else:
            subPlanDirectory = test.options.split()[0]
            carmUsrSubPlanDirectory = testInfo.replaceCarmUsr(subPlanDirectory)
        envFileName = test.makeFileName("environment")
        if not os.path.isfile(envFileName):
            hasPorted = 1
            envContent = testInfo.buildEnvironment(carmUsrSubPlanDirectory)
            open(envFileName,"w").write(envContent + os.linesep)
        perfFileName = test.makeFileName("performance")
        if not os.path.isfile(perfFileName):
            hasPorted = 1
            perfContent = testInfo.buildPerformance(carmUsrSubPlanDirectory)
            open(envFileName,"w").write(perfContent + os.linesep)
        else:
            lines = open(perfFileName).readlines()
            if len(lines) > 1:
                line1 = lines[0]
                line2 = lines[1]
                if line1[0:4] == "real" and line2[0:4] == "user":
                    sec = line2.split(" ")[1]
                    perfContent = "CPU time   :     " + str(float(sec)) + " sec. on heathlands"
                    open(perfFileName,"w").write(perfContent + os.linesep)
                    hasPorted = 1
        if hasPorted != 0:
            self.describe(test, " in " + testInfo.suiteDescription())
    def setUpSuite(self, suite):
        self.suite = suite


def calculate(file1, file2):
    iKPI = SimpleRosteringOptTimeKPI(file1, file2)
    return iKPI.getFloatKPI()

if __name__ == '__main__':
    cStrFlag = sys.argv[1]
    if cStrFlag == '-simple' and len(sys.argv) == 4:
	iKPI = SimpleRosteringOptTimeKPI(sys.argv[2], sys.argv[3])
    elif cStrFlag == '-full' and len(sys.argv) == 4:
	iKPI = FullRosteringOptTimeKPI(sys.argv[2], sys.argv[3])
    elif cStrFlag == '-testHandler' and len(sys.argv) == 4:
	iKPIHandler = KPIHandler()
	iKPIHandler.addKPI(SimpleRosteringOptTimeKPI(sys.argv[2], sys.argv[3]))
	iKPI = FullRosteringOptTimeKPI(sys.argv[2], sys.argv[3])
	iKPIHandler.addKPI(iKPI)
	#iKPIHandler.addKPI(iKPI)
	iKPIHandler.removeKPI(iKPI)
	iKPIHandler.addKPI(iKPI)
	print iKPIHandler.getKPIAverage()
    else:
	# print usage
	print '\n   Usage: %s refStatusFile thisStatusFile' %(os.path.basename(sys.argv[0]))
	print """   This is a script to calculate the KPI (Key Performance Indicator)\n"""
	sys.exit(1)

    print '%s: %s' %(iKPI.getName(), iKPI.getFloatKPI())
