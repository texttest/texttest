import carmen, os

def getConfig(optionMap):
    return StudioConfig(optionMap)

class StudioConfig(carmen.CarmenConfig):
    def __init__(self, eh):
	print "Hello, This is the studio plug-in for the test framework"
	carmen.CarmenConfig.__init__(self, eh)
    def getActionSequence(self):
        return [ self.getTestSetup() ] + carmen.CarmenConfig.getActionSequence(self)
    def getTestCollator(self):
        return carmen.CarmenConfig.getTestCollator(self) + [ self.getTestCleanup() ] 
    def getTestSetup(self):
	return SetupTest(self)
    def getTestCleanup(self):
	return CleanupTest(self)

class SetupTest:
    def __repr__(self):
        return "Setup"
    def __init__(self, studio):
	self.studio = studio
	self.studio.origScreen = os.getenv("DISPLAY")
    def __call__(self, test, description):
        print description
	#self.studio.testScreen = ???????
	self.studio.testScreen = os.getenv("DISPLAY")
	os.putenv("DISPLAY", self.studio.testScreen)
    def setUpSuite(self, suite, description):
	print description


class CleanupTest:
    def __repr__(self):
        return "Cleanup"
    def __init__(self, studio):
	self.studio = studio
    def __call__(self, test, description):
        print description
	self.studio.screen = ""
	os.putenv("DISPLAY", self.studio.origScreen)
    def setUpSuite(self, suite, description):
	print description

