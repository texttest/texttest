#
#	Studio plug-in for Texttest framework
#
# This plug-in is derived from CarmenConfig which is derived from LSF.
# The main contribution of this plug-in is being able to allocate a display.
#
# $Header: /carm/2_CVS/Testing/TextTest/Attic/studio.py,v 1.3 2003/04/11 08:30:28 perb Exp $
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

def probeDisplay(s):
    """
    	Check if screen 0 on display s exists
	The function returns the display name if it doesn't exist,
	it throws an exception if the display exists does.
    """
    cmd = "xdpyinfo -display " + s + " 2>&1 | grep 'screen #0' > /dev/null"
    r = os.system(cmd)
    if r:
    	return s
    raise "Display busy"

def findDisplay(host=""):
    """
	Look for an available display on current host
    """
    for i in range(1,10):
    	s = host + ":" + str(i)
    	try:
	    return probeDisplay(s)
	except:
	    pass
    raise "No available display found on " + host

def createDisplay(disp):
    """
    	Start a virtual X-display with a given name
    """
    pid = os.fork()
    os.close(2)
    if not pid:
	os.execlp("Xvfb", "Xvfb", disp, "-ac")
    return pid

class SetupTest(plugins.Action):
    def __repr__(self):
        return "Setup"
    def __init__(self, studio):
	self.studio = studio
	self.studio.origDisplay = os.getenv("DISPLAY")
    def __call__(self, test):
        self.describe(test)
	self.studio.testDisplay = findDisplay(os.getenv("HOST"))
	self.studio.pid = 0
	if self.studio.useLSF():
	    self.studio.pid = createDisplay(self.studio.testDisplay)
	    os.environ["DISPLAY"] = self.studio.testDisplay
    def setUpSuite(self, suite):
	self.describe(suite)


SIGTERM = 15

class CleanupTest(plugins.Action):
    def __repr__(self):
        return "Cleanup"
    def __init__(self, studio):
	self.studio = studio
    def __call__(self, test):
        self.describe(test)
	if self.studio.pid:
	    os.kill(self.studio.pid, SIGTERM)
	    self.studio.pid = 0
	self.studio.testDisplay = ""
	os.environ["DISPLAY"] = self.studio.origDisplay
    def setUpSuite(self, suite):
	self.describe(suite)
