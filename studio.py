#
#	Studio plug-in for Texttest framework
#
# This plug-in is derived from CarmenConfig which is derived from LSF.
# The main contribution of this plug-in is being able to allocate a display.
#
# $Header: /carm/2_CVS/Testing/TextTest/Attic/studio.py,v 1.4 2003/04/14 11:58:50 perb Exp $
#
import carmen, os, plugins

def getConfig(optionMap):
    return StudioConfig(optionMap)

class StudioConfig(carmen.CarmenConfig):
    def __init__(self, eh):
	carmen.CarmenConfig.__init__(self, eh)
    def getActionSequence(self):
        return [ self.getTestSetup() ] + carmen.CarmenConfig.getActionSequence(self)
    def getTestCollator(self):
        return plugins.CompositeAction([ carmen.CarmenConfig.getTestCollator(self), self.getTestCleanup() ])
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
