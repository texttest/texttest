#
#	Studio plug-in for Texttest framework
#
# This plug-in is derived from CarmenConfig which is derived from LSF.
# The main contribution of this plug-in is being able to allocate a display.
#
# $Header: /carm/2_CVS/Testing/TextTest/Attic/studio.py,v 1.5 2004/01/26 15:21:22 geoff Exp $
#
import carmen, os, plugins

def getConfig(optionMap):
    return StudioConfig(optionMap)

class StudioConfig(carmen.CarmenConfig):
    def __init__(self, eh):
	carmen.CarmenConfig.__init__(self, eh)
    def getActionSequence(self, useGui):
        return [ self.getTestSetup() ] + carmen.CarmenConfig.getActionSequence(self, useGui)
    def getTestCollator(self):
        return [ carmen.CarmenConfig.getTestCollator(self), self.getTestCleanup() ]
    def getTestSetup(self):
	return SetupTest(self)
    def getTestCleanup(self):
	return CleanupTest(self)

class SetupTest(plugins.Action):
    def __repr__(self):
        return "Setup"
    def __init__(self, studio):
	self.studio = studio
    def __call__(self, test):
        self.describe(test)
    def setUpSuite(self, suite):
	self.describe(suite)


class CleanupTest(plugins.Action):
    def __repr__(self):
        return "Cleanup"
    def __init__(self, studio):
	self.studio = studio
    def __call__(self, test):
        self.describe(test)
    def setUpSuite(self, suite):
	self.describe(suite)
