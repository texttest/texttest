
""" Module to manage the information in the file and return appropriate matches """

import logging, difflib, re
from ordereddict import OrderedDict

class ReplayInfo:
    def __init__(self, replayFile, filterReplayFile, rcHandler):
        self.responseMap = OrderedDict()
        self.diag = logging.getLogger("Traffic Replay")
        self.replayItems = []
        if replayFile:
            trafficList = self.readIntoList(replayFile)
            self.parseTrafficList(trafficList)
            if filterReplayFile:
                items = self.makeCommandItems(rcHandler.getIntercepts("command line")) + \
                        self.makePythonItems(rcHandler.getIntercepts("python"))
                self.replayItems = self.filterForReplay(items, trafficList)

    @staticmethod
    def filterForReplay(itemInfo, lines):
        newItems = []
        for line in lines:
            for item, regexp in itemInfo:
                if item not in newItems and regexp.search(line):
                    newItems.append(item)
        return newItems

    @staticmethod
    def makeCommandItems(commands):
        return [ (command, re.compile("<-CMD:([^ ]* )*" + command + "( [^ ]*)*")) for command in commands ]

    @staticmethod
    def makePythonItems(pythonAttrs):
        return [ (attr, re.compile("<-PYT:(import )?" + attr)) for attr in pythonAttrs ]
            
    def isActiveForAll(self):
        return len(self.responseMap) > 0 and len(self.replayItems) == 0
            
    def isActiveFor(self, traffic):
        if len(self.responseMap) == 0:
            return False
        elif len(self.replayItems) == 0:
            return True
        else:
            return traffic.isMarkedForReplay(set(self.replayItems))

    def parseTrafficList(self, trafficList):
        currResponseHandler = None
        for trafficStr in trafficList:
            if trafficStr.startswith("<-"):
                currTrafficIn = trafficStr.strip()
                currResponseHandler = self.responseMap.get(currTrafficIn)
                if currResponseHandler:
                    currResponseHandler.newResponse()
                else:
                    currResponseHandler = ReplayedResponseHandler()
                    self.responseMap[currTrafficIn] = currResponseHandler
            elif currResponseHandler:
                currResponseHandler.addResponse(trafficStr)
        self.diag.info("Replay info " + repr(self.responseMap))

    def readIntoList(self, replayFile):
        trafficList = []
        currTraffic = ""
        for line in open(replayFile, "rU").xreadlines():
            if line.startswith("<-") or line.startswith("->"):
                if currTraffic:
                    trafficList.append(currTraffic)
                currTraffic = ""
            currTraffic += line
        if currTraffic:
            trafficList.append(currTraffic)
        return trafficList
    
    def readReplayResponses(self, traffic, allClasses):
        # We return the response matching the traffic in if we can, otherwise
        # the one that is most similar to it
        if not traffic.hasInfo():
            return []

        responseMapKey = self.getResponseMapKey(traffic)
        if responseMapKey:
            return self.responseMap[responseMapKey].makeResponses(traffic, allClasses)
        else:
            return []

    def getResponseMapKey(self, traffic):
        desc = traffic.getDescription()
        self.diag.info("Trying to match '" + desc + "'")
        if self.responseMap.has_key(desc):
            self.diag.info("Found exact match")
            return desc
        elif not traffic.enquiryOnly():
            return self.findBestMatch(desc)

    def findBestMatch(self, desc):
        descWords = self.getWords(desc)
        bestMatch = None
        bestMatchInfo = set(), 100000
        for currDesc, responseHandler in self.responseMap.items():
            if self.sameType(desc, currDesc):
                descToCompare = currDesc                    
                self.diag.info("Comparing with '" + descToCompare + "'")
                matchInfo = self.getWords(descToCompare), responseHandler.getUnmatchedResponseCount()
                if self.isBetterMatch(matchInfo, bestMatchInfo, descWords):
                    bestMatchInfo = matchInfo
                    bestMatch = currDesc

        if bestMatch is not None:
            self.diag.info("Best match chosen as '" + bestMatch + "'")
            return bestMatch

    def sameType(self, desc1, desc2):
        return desc1[2:5] == desc2[2:5]

    def getWords(self, desc):
        # Heuristic decisions trying to make the best of inexact matches
        separators = [ "/", "(", ")", "\\", None ] # the last means whitespace...
        return self._getWords(desc, separators)

    def _getWords(self, desc, separators):
        if len(separators) == 0:
            return [ desc ]
        
        words = []
        for part in desc.split(separators[0]):
            words += self._getWords(part, separators[1:])
        return words

    def getMatchingBlocks(self, list1, list2):
        matcher = difflib.SequenceMatcher(None, list1, list2)
        return matcher.get_matching_blocks()

    def commonElementCount(self, blocks):
        return sum((block.size for block in blocks))

    def nonMatchingSequenceCount(self, blocks):
        if len(blocks) > 1 and self.lastBlockReachesEnd(blocks):
            return len(blocks) - 2
        else:
            return len(blocks) - 1

    def lastBlockReachesEnd(self, blocks):
        return blocks[-2].a + blocks[-2].size == blocks[-1].a and \
               blocks[-2].b + blocks[-2].size == blocks[-1].b
            
    def isBetterMatch(self, info1, info2, targetWords):
        words1, unmatchedCount1 = info1
        words2, unmatchedCount2 = info2
        blocks1 = self.getMatchingBlocks(words1, targetWords)
        blocks2 = self.getMatchingBlocks(words2, targetWords)
        common1 = self.commonElementCount(blocks1)
        common2 = self.commonElementCount(blocks2)
        self.diag.info("Words in common " + repr(common1) + " vs " + repr(common2))
        if common1 > common2:
            return True
        elif common1 < common2:
            return False

        nonMatchCount1 = self.nonMatchingSequenceCount(blocks1)
        nonMatchCount2 = self.nonMatchingSequenceCount(blocks2)
        self.diag.info("Non matching sequences " + repr(nonMatchCount1) + " vs " + repr(nonMatchCount2))
        if nonMatchCount1 < nonMatchCount2:
            return True
        elif nonMatchCount1 > nonMatchCount2:
            return False

        self.diag.info("Unmatched count difference " + repr(unmatchedCount1) + " vs " + repr(unmatchedCount2))
        return unmatchedCount1 > unmatchedCount2
    

# Need to handle multiple replies to the same question
class ReplayedResponseHandler:
    def __init__(self):
        self.timesChosen = 0
        self.responses = [[]]
    def __repr__(self):
        return repr(self.responses)
    def newResponse(self):
        self.responses.append([])        
    def addResponse(self, trafficStr):
        self.responses[-1].append(trafficStr)
    def getCurrentStrings(self):
        if self.timesChosen < len(self.responses):
            currStrings = self.responses[self.timesChosen]
        else:
            currStrings = self.responses[0]
        return currStrings

    def getUnmatchedResponseCount(self):
        return len(self.responses) - self.timesChosen
    
    def makeResponses(self, traffic, allClasses):
        trafficStrings = self.getCurrentStrings()
        responses = []
        for trafficStr in trafficStrings:
            trafficType = trafficStr[2:5]
            for trafficClass in allClasses:
                if trafficClass.typeId == trafficType:
                    responses.append((trafficClass, trafficStr[6:]))
        self.timesChosen += 1
        return responses


def filterFileForReplay(itemInfo, replayFile):
    with open(replayFile, "rU") as f:
        return ReplayInfo.filterForReplay(itemInfo, f)

def filterCommands(commands, replayFile):
    return filterFileForReplay(ReplayInfo.makeCommandItems(commands), replayFile)

def filterPython(pythonAttrs, replayFile):
    return filterFileForReplay(ReplayInfo.makePythonItems(pythonAttrs), replayFile)
