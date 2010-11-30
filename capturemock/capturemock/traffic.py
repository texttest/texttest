
""" Defining the base traffic class which the useful traffic classes inherit """

import socket

class Traffic(object):
    def __init__(self, text, responseFile, *args):
        self.text = text
        self.responseFile = responseFile

    def findPossibleFileEdits(self):
        return []
    
    def hasInfo(self):
        return len(self.text) > 0

    def isMarkedForReplay(self, replayItems):
        return True # Some things can't be disabled and hence can't be added on piecemeal afterwards

    def getDescription(self):
        return self.direction + self.typeId + ":" + self.text

    def makesAsynchronousEdits(self):
        return False
    
    def enquiryOnly(self, responses=[]):
        return False
    
    def write(self, message):
        if self.responseFile:
            try:
                self.responseFile.write(message)
            except socket.error:
                # The system under test has died or is otherwise unresponsive
                # Should handle this, probably. For now, ignoring it is better than stack dumps
                pass
                
    def forwardToDestination(self):
        self.write(self.text)
        if self.responseFile:
            self.responseFile.close()
        return []

    def record(self, recordFileHandler, reqNo):
        if not self.hasInfo():
            return
        desc = self.getDescription()
        if not desc.endswith("\n"):
            desc += "\n"
        recordFileHandler.record(desc, reqNo)

    def filterReplay(self, trafficList):
        return trafficList

    
class ResponseTraffic(Traffic):
    direction = "->"

