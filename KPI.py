#!/usr/local/bin/python
#
# $Header: /carm/2_CVS/Testing/TextTest/Attic/KPI.py,v 1.4 2003/03/07 07:59:21 henrike Exp $
#
# Classes to calculate the KPI (Key Performance Indicator)
#
# Created 2003-02-03 /Henrik
#
# ../TextTest/texttest.py -a cas -u sia -kpi 9

import sys, os, re, string, time, shutil
from encodings import raw_unicode_escape
# Test suite imports
import default, carmen, lsf, stat, optimization, plugins

# Constants to use in listKPIs for creating the class CalculateKPIs(referenceVersion, listKPIs)
cSimpleRosteringOptTimeKPI    = 0
cFullRosteringOptTimeKPI      = 1
cWorstBestRosteringOptTimeKPI = 2


class KPIHandler:
    def __init__(self):
	self.mapKPIs = {}
	self.mapKPIClasses = {cSimpleRosteringOptTimeKPI    : SimpleRosteringOptTimeKPI,
			      cFullRosteringOptTimeKPI      : FullRosteringOptTimeKPI,
			      cWorstBestRosteringOptTimeKPI : WorstBestRosteringOptTimeKPI}
    def addKPI(self, KPI, strGroupName = None):
	if not strGroupName:
	    strGroupName = self._generateGroupName(KPI)
	if not strGroupName in self.mapKPIs.keys():
	    self.mapKPIs[strGroupName] = []
	listKPIs = self.mapKPIs[strGroupName]
	if not listKPIs.count(KPI):
	    listKPIs.append(KPI)
	else:
	    raise KPIAlreadyExistError('<Name: %s, Id: %d, Group: %s>' %(KPI.getName(), KPI.getId(), strGroupName))
    def _generateGroupName(self, KPI):
	return KPI.getName()
    def removeKPI(self, KPI, strGroupName = None):
	if not strGroupName:
	    strGroupName = self._generateGroupName(KPI)
	try:
	    self.mapKPIs[strGroupName].remove(KPI)
	except ValueError:
	    raise RemovalOfNonexistingKPIError('<Name: %s, Group: %s>' %(KPI.getName(), strGroupName))
    def getAllGroupsKPIAverage(self):
	"""Returns a map of tuples: {<Group name>: (<KPI average>, <Nr of valid KPIs>, <Nr of failed KPIs>), ...}"""
	mapAverage = {}
	for strGroupName in self.getGroupNames():
	    mapAverage[strGroup] = self.getKPIAverage(strGroupName)
	return mapAverage
    def getKPIAverage(self, strGroupName):
	"""Returns the tuple of the specified group: (<KPI average>, <Nr of valid KPIs>, <Nr of failed KPIs>)"""
	if not strGroupName in self.getGroupNames():
	    raise KPIHandlerError('Group "%s" does not exist' %(strGroupName))
	intNofKPIs = 0
	floatTotalKPI = 0.0
	for aKPI in self.mapKPIs[strGroupName]:
	    floatCurrKPI = aKPI.getFloatKPI()
	    if floatCurrKPI:
		intNofKPIs += 1
		floatTotalKPI += floatCurrKPI
	if intNofKPIs > 0:
	    return (floatTotalKPI / float(intNofKPIs), intNofKPIs, self.getNrOfKPIs(strGroupName) - intNofKPIs)
	else:
	    return (None, 0, self.getNrOfKPIs(strGroupName))
    def getAllGroupsKPIAverageText(self):
	strText = ''
	for strGroupName in self.getGroupNames():
	    strText += self.getKPIAverageText(strGroupName) + os.linesep
	return strText
    def getKPIAverageText(self, strGroupName):
	(floatAverage, intValidKPIs, intFailedKPIs) = self.getKPIAverage(strGroupName)
	return '%s: Average = %s (%d valid, %d failed)' %(strGroupName, floatAverage, intValidKPIs, intFailedKPIs)
    def getGroupNames(self):
	return self.mapKPIs.keys()
    def getNrOfKPIs(self, strGroupName = None):
	if strGroupName:
	    return len(self.mapKPIs[strGroupName])
	intNrOfKPIs = 0
	for strGroupName in self.getGroupNames():
	    intNrOfKPIs += len(self.mapKPIs[strGroupName])
	return intNrOfKPIs
    def createKPI(self, intKPIConstant, strRefFile, strNowFile, floatRefScale = 1.0, floatNowScale = 1.0):
	return self.mapKPIClasses[intKPIConstant](strRefFile, strNowFile, floatRefScale, floatNowScale)


class KPI:
    def __init__(self, strRefStatusFile, strNowStatusFile):
	self.iBasics = Basics()
	self.strName = 'KPI'
	self.cStrRefStatusFile = strRefStatusFile
	self.cStrNowStatusFile = strNowStatusFile
    def getId(self):
	return id(self)
    def getName(self):
	return self.strName
    def getFloatKPI(self):
	raise NotImplementedError()
    def getTextKPI(self):
	floatKPI = self.getFloatKPI()
	if floatKPI == None:
	    return 'None'
	return '%0.1f' %(floatKPI)
    def getRefValue(self):
	raise NotImplementedError()
    def getNowValue(self):
	raise NotImplementedError()


class CurveKPI(KPI):
    def __init__(self, strRefStatusFile, strNowStatusFile, floatRefScale = 1.0, floatNowScale = 1.0):
	KPI.__init__(self, strRefStatusFile, strNowStatusFile)
	#print 'ref: %f, now: %f' %(floatRefScale, floatNowScale)
	self.strName = 'Curve KPI'
	self.cReCPUTimeParts = re.compile(r'^(?P<hours>\d+):(?P<minutes>\d\d):(?P<seconds>\d\d)$')
	self.mapSeriesRef = {}
	self.mapSeriesNow = {}
	self.floatRefScale = floatRefScale
	self.floatNowScale = floatNowScale
	self.floatScaleFactor = 1.0
    def _setListRegExps(self, listRegExps):
	self.listRegExps = listRegExps
	self.floatScaleFactor = self.floatRefScale
	self.mapSeriesRef = self.iBasics.statusFileToMapOfSeries(self.cStrRefStatusFile, self.listRegExps)
	self.floatScaleFactor = self.floatNowScale
	self.mapSeriesNow = self.iBasics.statusFileToMapOfSeries(self.cStrNowStatusFile, self.listRegExps)
    def _setKeyPoints(self, listKeyPoints):
	self.listKeyPoints = listKeyPoints

    def _convertCPUtoSecs(self, strCPUTime):
	matchCPUTime = self.cReCPUTimeParts.match(strCPUTime)
	if matchCPUTime:
	    return self.floatScaleFactor * (string.atoi(matchCPUTime.group('hours')) * 3600 + string.atoi(matchCPUTime.group('minutes')) * 60 + string.atoi(matchCPUTime.group('seconds')))
	else:
	    #return int(string.atof(strCPUTime)/1000.0)
	    return None

    def _getKeyPointComponent(self, tupKeyPoint):
	(fRef, fNow) = apply(tupKeyPoint[1], ())
	return (float(tupKeyPoint[2]) * fRef, float(tupKeyPoint[2]) * fNow)

    def _getTotalTime(self, listKeyPoints):
	floatRefTime = 0.0
	floatNowTime = 0.0
	for aKeyPoint in listKeyPoints:
	    (fRef, fNow) = self._getKeyPointComponent(aKeyPoint)
	    floatRefTime += fRef
	    floatNowTime += fNow
	return (floatRefTime, floatNowTime)

    def getRefValue(self):
	pass

    def _getIndex(self, listKeyPoints):
	(floatRefTime, floatNowTime) = self._getTotalTime(listKeyPoints)
	if floatRefTime <= 0.0:
	    return None
	return 100.0 * (floatNowTime / floatRefTime)

    def getFloatKPI(self):
	if len(self.mapSeriesRef.keys()) == 0:
	    return None
	if len(self.mapSeriesRef[self.mapSeriesRef.keys()[0]]) == 0 or len(self.mapSeriesNow[self.mapSeriesNow.keys()[0]]) == 0:
	    return None
	try:
	    floatIndex = self._getIndex(self.listKeyPoints)
	    return floatIndex
	except KPIQualityNotReachedError, e:
	    #self.iBasics.printWarning(e)
	    return None
    def getNofSolutions(self):
	if len(self.mapSeriesRef.keys()) == 0:
	    return 0
	return min(len(self.mapSeriesRef[self.mapSeriesRef.keys()[0]]), len(self.mapSeriesNow[self.mapSeriesNow.keys()[0]]))


class MemoryKPI(CurveKPI):
    def __init__(self, strRefStatusFile, strNowStatusFile, floatRefScale = 1.0, floatNowScale = 1.0):
	CurveKPI.__init__(self, strRefStatusFile, strNowStatusFile, floatRefScale, floatNowScale)
	self.strName = 'Memory KPI'
	self.cReMemory = re.compile(r'^Time:[^d]*d (?P<value>[\d]+) memory$')

class AverageMemoryKPI(MemoryKPI):
    def __init__(self, strRefStatusFile, strNowStatusFile, floatRefScale = 1.0, floatNowScale = 1.0):
	MemoryKPI.__init__(self, strRefStatusFile, strNowStatusFile, floatRefScale, floatNowScale)
	self.strName = 'Average memory KPI'


class MaxMemoryKPI(MemoryKPI):
    def __init__(self, strRefStatusFile, strNowStatusFile, floatRefScale = 1.0, floatNowScale = 1.0):
	MemoryKPI.__init__(self, strRefStatusFile, strNowStatusFile, floatRefScale, floatNowScale)
	self.strName = 'Max memory KPI'


class PairingKPI(CurveKPI):
    def __init__(self, strRefStatusFile, strNowStatusFile, floatRefScale = 1.0, floatNowScale = 1.0):
	CurveKPI.__init__(self, strRefStatusFile, strNowStatusFile, floatRefScale, floatNowScale)
	self.strName = 'Pairing KPI'

	self.cReTotalCost = self.iBasics.getStatusRegExpFromLabel('Total cost of plan|APC total rule cost')
	self.cReCPUTime = re.compile(r'^Total time:\D*([\d:]+)\W*cpu time:\D*(?P<value>[\d:]+)$')

	listRegExps = [
	    ('CPU time',        self.cReCPUTime,        self._convertCPUtoSecs),
	    ('Total cost',      self.cReTotalCost,      string.atoi),
	    ('Unassigned cost',  self.cReUnassignedCost, string.atoi),
	    ('Cost of rosters',  self.cReRosterCost,     string.atoi)
	    ]
	self._setListRegExps(listRegExps)


class RosteringKPI(CurveKPI):
    def __init__(self, strRefStatusFile, strNowStatusFile, floatRefScale = 1.0, floatNowScale = 1.0):
	CurveKPI.__init__(self, strRefStatusFile, strNowStatusFile, floatRefScale, floatNowScale)
	self.strName = 'Rostering KPI'

	self.cReRosterCost = self.iBasics.getStatusRegExpFromLabel('Total cost of rosters')
	self.cReUnassignedCost = self.iBasics.getStatusRegExpFromLabel('Total cost of unassigned slots|unassigned rotations')
	self.cReTotalCost = self.iBasics.getStatusRegExpFromLabel('Total cost of plan|APC total rule cost')
	#Total time:(s) 00:23:37  cpu time:  00:21:35#
	self.cReCPUTime = re.compile(r'^Total time\D*[\d:]+\D*(?P<value>[\d:]+).*')

	listRegExps = [
	    ('CPU time',        self.cReCPUTime,        self._convertCPUtoSecs),
	    ('Total cost',      self.cReTotalCost,      string.atoi),
	    ('Unassigned cost',  self.cReUnassignedCost, string.atoi),
	    ('Cost of rosters',  self.cReRosterCost,     string.atoi)
	    ]
	self._setListRegExps(listRegExps)
    def _getInitialSolutionTime(self):
	return (self.mapSeriesRef['CPU time'][0], self.mapSeriesNow['CPU time'][0])
    def _getFirstReasonableTime(self):
	return (0, 0)
    def _getProductionQualityTime(self):
	return (0, 0)
    def _getFinalQualityTime(self):
	floatFinalQuality = min(self.mapSeriesRef['Total cost'])
	ixFinalQualityRef = self._getFirstLowerIx(self.mapSeriesRef['Total cost'], floatFinalQuality)
	ixFinalQualityNow = self._getFirstLowerIx(self.mapSeriesNow['Total cost'], floatFinalQuality)
	if not ixFinalQualityRef or not ixFinalQualityNow:
	    raise KPIQualityNotReachedError(self.getName(), 'Final quality')
	return (self.mapSeriesRef['CPU time'][ixFinalQualityRef], self.mapSeriesNow['CPU time'][ixFinalQualityNow])
    def _getWorstBestQualityTime(self):
	floatWorstBestQuality = max(min(self.mapSeriesNow['Total cost']), min(self.mapSeriesRef['Total cost']))
	ixWorstBestQualityRef = self._getFirstLowerIx(self.mapSeriesRef['Total cost'], floatWorstBestQuality)
	ixWorstBestQualityNow = self._getFirstLowerIx(self.mapSeriesNow['Total cost'], floatWorstBestQuality)
	return (self.mapSeriesRef['CPU time'][ixWorstBestQualityRef], self.mapSeriesNow['CPU time'][ixWorstBestQualityNow])	
    def _getFirstLowerIx(self, listSeries, floatLimit):
	ixSeries = 0
	while listSeries[ixSeries] > floatLimit and ixSeries < len(listSeries) - 1:
	    ixSeries += 1
	if listSeries[ixSeries] <= floatLimit:
	    return ixSeries
	else:
	    return None
	

class FullRosteringOptTimeKPI(RosteringKPI):
    def __init__(self, strRefStatusFile, strNowStatusFile, floatRefScale = 1.0, floatNowScale = 1.0):
	RosteringKPI.__init__(self, strRefStatusFile, strNowStatusFile, floatRefScale, floatNowScale)
	self.strName = 'Full Rostering Optimization Time KPI'
	listKeyPoints = [
	    ('Initial solution',         self._getInitialSolutionTime,   2),
	    ('First reasonable solution', self._getFirstReasonableTime,   1),
	    ('Production quality',       self._getProductionQualityTime, 2),
	    ('Final quality',           self._getFinalQualityTime,      3),
	    ]
	self._setKeyPoints(listKeyPoints)


class SimpleRosteringOptTimeKPI(RosteringKPI):
    def __init__(self, strRefStatusFile, strNowStatusFile, floatRefScale = 1.0, floatNowScale = 1.0):
	RosteringKPI.__init__(self, strRefStatusFile, strNowStatusFile, floatRefScale, floatNowScale)
	self.strName = 'Simple Rostering Optimization Time KPI'
	listKeyPoints = [
	    ('Final quality',           self._getFinalQualityTime,      1),
	    ]
	self._setKeyPoints(listKeyPoints)


class WorstBestRosteringOptTimeKPI(RosteringKPI):
    def __init__(self, strRefStatusFile, strNowStatusFile, floatRefScale = 1.0, floatNowScale = 1.0):
	RosteringKPI.__init__(self, strRefStatusFile, strNowStatusFile, floatRefScale, floatNowScale)
	self.strName = 'Worst Best Rostering Optimization Time KPI'
	listKeyPoints = [
	    ('Worst best cost',           self._getWorstBestQualityTime,      1),
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
	    outFile.write(line + os.linesep)
	outFile.close

    # print warning
    def printWarning(self, strWarning):
	sys.stderr.write('  *** Warning: %s%s' %(strWarning, os.linesep))

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
			listValues[ixRegExp][ixSection] = apply(listRegExps[ixRegExp][2], (matchRegExp.group('value'),))
	mapSeries = {}
	for ixRegExp in range(len(listRegExps)):
	    mapSeries[listRegExps[ixRegExp][0]] = listValues[ixRegExp][:]
	self._removeNoneValues(mapSeries)
	return mapSeries

    def _removeNoneValues(self, mapSeries):
	if not mapSeries.keys():
	    return
	ixSolution = 0
	while ixSolution < len(mapSeries[mapSeries.keys()[0]]):
	    boolRemoveSolution = 0
	    for keySeries in mapSeries.keys():
		if mapSeries[keySeries][ixSolution] == None:
		    boolRemoveSolution = 1
	    if boolRemoveSolution:
		for keySeries in mapSeries.keys():
		    del mapSeries[keySeries][ixSolution]
	    else:
		ixSolution += 1

    def getStatusRegExpFromLabel(self, strLabel):
	strRegExp = self.rawCodec.encode('^\W*(%s)[^\d]*(?P<value>\d+).*$' %(strLabel))[0]
	return re.compile(strRegExp)


class KPIQualityNotReachedError(Exception):
    def __init__(self, strName, strError):
	self.strName = strName
	self.strError = strError
    def __str__(self):
	return 'KPI %s could not be calculated (%s)' %(self.strName, self.strError)
class KPIAlreadyExistError(Exception):
    pass
class RemovalOfNonexistingKPIError(Exception):
    pass
class KPIHandlerError(Exception):
    pass


##         # Performance file handling
##         perfFileName = test.makeFileName("performance")
##         if not os.path.isfile(perfFileName):
##             perfContent = testInfo.buildPerformance(carmUsrSubPlanDirectory)
##             open(envFileName,"w").write(perfContent + os.linesep)
##         else:
##             lines = open(perfFileName).readlines()
##             if len(lines) > 1:
##                 line1 = lines[0]
##                 line2 = lines[1]
##                 if line1[0:4] == "real" and line2[0:4] == "user":
##                     sec = line2.split(" ")[1]
##                     perfContent = "CPU time   :     " + str(float(sec)) + " sec. on heathlands"
##                     open(perfFileName,"w").write(perfContent + os.linesep)
##                     hasPorted = 1

## class KPIPart:
##     def __init__(self, strStatusFile, strUniqueTestString):
## 	self.strUniqueTestString = strUniqueTestString
## 	self.fCompareMarginPercent = 0.0
##     def getUniqueTestString():
## 	return self.strUniqueTestString
##     def setcompareMarginPercent(floatPercent):
## 	self.fCompareMarginPercent = floatPercent
##     def isComparableTo(otherKPIPart):
## 	#!!!Not finished yet!!!
## 	return self.getUniqueTestString() == otherKPIPart.getUniqueTestString()


if __name__ == '__main__':
    cStrFlag = sys.argv[1]
    if cStrFlag == '-simple' and len(sys.argv) == 4:
	iKPI = SimpleRosteringOptTimeKPI(sys.argv[2], sys.argv[3])
    elif cStrFlag == '-full' and len(sys.argv) == 4:
	iKPI = FullRosteringOptTimeKPI(sys.argv[2], sys.argv[3])
    elif cStrFlag == '-testHandler' and len(sys.argv) == 4:
	iKPIHandler = KPIHandler()
	iKPIHandler.addKPI(SimpleRosteringOptTimeKPI(sys.argv[2], sys.argv[3]))
	iKPIHandler.addKPI(WorstBestRosteringOptTimeKPI(sys.argv[2], sys.argv[3]))
	iKPI = FullRosteringOptTimeKPI(sys.argv[2], sys.argv[3])
	iKPIHandler.addKPI(iKPI)
	#iKPIHandler.addKPI(iKPI)
	iKPIHandler.removeKPI(iKPI)
	iKPIHandler.addKPI(iKPI)
	print iKPIHandler.getAllGroupsKPIAverageText()
    else:
	# print usage
	print '%s   Usage: %s refStatusFile thisStatusFile' %(os.linesep, os.path.basename(sys.argv[0]))
	print """   This is a script to calculate the KPI (Key Performance Indicator)""", os.linesep
	sys.exit(1)

    print '%s: %s' %(iKPI.getName(), iKPI.getFloatKPI())
