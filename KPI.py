#!/usr/local/bin/python
#
# $Header: /carm/2_CVS/Testing/TextTest/Attic/KPI.py,v 1.1 2003/02/05 12:55:41 geoff Exp $
#
# Script to calculate the KPI (Key Performance Indicator)
#
# Created 2003-02-03 /Henrik
#


import sys, os, re, string, time, shutil


############################## --------------------- ##############################
##############################  global declarations  ##############################
############################## --------------------- ##############################


gVeryLargeInt = 1000000

gReSolutionFile = re.compile(r'^Solution_(?P<nr>\d+)$')

gReTotalCost = re.compile(r'^\W*(Total cost of plan|APC total rule cost)[^\d]*(?P<value>\d+)[^\d]*$')

#gReCPUTime = re.compile(r'^[^i]*ime:\D*([\d:]+)\W*cpu\D*(?P<value>[\d:]+)[\w ]*$')
gReCPUTime = re.compile(r'^Total time:\D*([\d:]+)\W*cpu time:\D*(?P<value>[\d:]+)$')

gReCPUTimeParts = re.compile(r'^(?P<hours>\d+):(?P<minutes>\d\d):(?P<seconds>\d\d)$')

#gReStatusSection = re.compile(r'^SECTION apc_status (?P<solution>\w+)$')
gReStatusSolution = re.compile(r'^SECTION apc_status Solution_(?P<nr>\d+)$')


############################## --------------------- ##############################
##############################      functions        ##############################
############################## --------------------- ##############################


# print usage
def usage():
    print '\n   Usage: %s refStatusFile thisStatusFile' %(os.path.basename(sys.argv[0]))
    print """
   This is a script to calculate the KPI (Key Performance Indicator)
   """


# read a file into a buffer and return the buffer
def readFile(filename):
    f = open(filename)
    buffer = map(lambda line: line.strip(), f.readlines())
    f.close()
    return buffer


# write a file from a list of lines
def writeFile(filename, lines):
    outFile = open(filename, 'w')
    for line in lines:
	outFile.write(line + '\n')
    outFile.close


# print warning
def printWarning(strWarning):
    print '  *** Warning: %s' %(strWarning)


#listRegExps = [('CPU time', REGEXP, convertFunc), ...]
#mapSeries example: {'Total cost': [28692758, 27888892, 27044010], 'CPU time': [2087, 2229, 2405]}

def statusFileToMapOfSeries(strStatusFile, listRegExps):
    listLines = readFile(strStatusFile)
    currentSolution = ''
    ixSection = -1
    listValues = []
    for aRegExp in listRegExps:
	listValues.append([])
    boolFirstSolutionFound = 0
    for aLine in listLines:
	matchStatusSection = gReStatusSolution.match(aLine)
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
    removeNegatives(mapSeries)
    return mapSeries


def convertCPUtoSecs(strCPUTime):
    matchCPUTime = gReCPUTimeParts.match(strCPUTime)
    if matchCPUTime:
	return string.atoi(matchCPUTime.group('hours')) * 3600 + string.atoi(matchCPUTime.group('minutes')) * 60 + string.atoi(matchCPUTime.group('seconds'))
    else:
	#return int(string.atof(strCPUTime)/1000.0)
	return -1


def removeNegatives(mapSeries):
    for ixSolution in range(len(mapSeries[mapSeries.keys()[0]])):
	boolRemoveSolution = 0
	for keySeries in mapSeries.keys():
	    if mapSeries[keySeries][ixSolution] < 0:
		boolRemoveSolution = 1
	if boolRemoveSolution:
	    for keySeries in mapSeries.keys():
		del mapSeries[keySeries][ixSolution]


def getInitialSolutionTime(mapSeriesRef, mapSeriesThis):
    return mapSeriesThis['CPU time'][0]


def getFirstReasonableTime(mapSeriesRef, mapSeriesThis):
    return 0


def getProductionQualityTime(mapSeriesRef, mapSeriesThis):
    return 0


def getFinalQualityTime(mapSeriesRef, mapSeriesThis):
    intFinalQuality = min(mapSeriesRef['Total cost'])
    listSeriesThis = mapSeriesThis['Total cost']
    ixSeriesThis = 0
    while listSeriesThis[ixSeriesThis] > intFinalQuality and ixSeriesThis < len(listSeriesThis) - 1:
	ixSeriesThis += 1
    if listSeriesThis[ixSeriesThis] <= intFinalQuality:
	return mapSeriesThis['CPU time'][ixSeriesThis]
    else:
	return gVeryLargeInt


def getKeyPointComponent(tupKeyPoint, mapSeriesRef, mapSeriesThis):
    return tupKeyPoint[2] * apply(tupKeyPoint[1], (mapSeriesRef, mapSeriesThis))


def getTotalTime(listKeyPoints, mapSeriesRef, mapSeriesThis):
    intTotalTime = 0
    for aKeyPoint in listKeyPoints:
	intTotalTime += getKeyPointComponent(aKeyPoint, mapSeriesRef, mapSeriesThis)
    return intTotalTime


def getIndex(listKeyPoints, mapSeriesRef, mapSeriesThis):
    intThisTime = getTotalTime(listKeyPoints, mapSeriesRef, mapSeriesThis)
    intRefTime  = getTotalTime(listKeyPoints, mapSeriesRef, mapSeriesRef)
    return 100.0 * (float(intThisTime) / float(intRefTime))


############################## --------------------- ##############################
############################## execution starts here ##############################
############################## --------------------- ##############################


listAllRegExps = [
    ('CPU time',   gReCPUTime,   convertCPUtoSecs),
    ('Total cost', gReTotalCost, string.atoi),
    ]

listKeyPoints = [
    ('Initial solution',         getInitialSolutionTime,   2),
    ('First reasonable solution', getFirstReasonableTime,   1),
    ('Production quality',       getProductionQualityTime, 2),
    ('Final quality',           getFinalQualityTime,      3),
    ]

def calculate(file1, file2):
    mapSeriesRef = statusFileToMapOfSeries(file1, listAllRegExps)
    mapSeriesThis = statusFileToMapOfSeries(file2, listAllRegExps)
    return getIndex(listKeyPoints, mapSeriesRef, mapSeriesThis)



## FLAG = sys.argv[1]



## if FLAG == '-a':
## elif FLAG == '-b':

## else:
##     usage()
##     sys.exit(1)
