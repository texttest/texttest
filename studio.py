#
#	Studio plug-in for Texttest framework
#
# This plug-in is derived from CarmenConfig which is derived from LSF.
# The main contribution of this plug-in is being able to allocate a display.
#
# $Header: /carm/2_CVS/Testing/TextTest/Attic/studio.py,v 1.7 2005/11/28 10:48:01 geoff Exp $
#
import ravebased, os, plugins

def getConfig(optionMap):
    return StudioConfig(optionMap)

class StudioConfig(ravebased.Config):
    def getWriteDirectoryPreparer(self):
        return ravebased.PrepareCarmdataWriteDir()
    def getRuleSetName(self, test):
        # Hack for now, should define from used subplans...
        return "LBA_MTV"
    
