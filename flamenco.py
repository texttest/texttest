helpDescription = """
The Flamenco configuration is based on the Carmen configuration. It is set up to replace the string "ARCHITECTURE"
with the running architecture in the name of the binary given in the config file. It will also collect the
file "sqlnet.log", and compare it as the test suite file sqlerr.<app>."""

import carmen, os, plugins

def getConfig(optionMap):
    return FlamencoConfig(optionMap)

class FlamencoConfig(carmen.CarmenConfig):
    def getExecuteCommand(self, binary, test):
	prog = binary.replace("ARCHITECTURE", carmen.architecture)
	if prog == binary:#not architecture dependent, probably is a script
	    #print "binary is a script: set binary to '" + prog + " " + test.options + "'" 
	    return prog + " " + test.options
	rootdir = test.app.abspath
	script = os.path.join(rootdir ,"RunTest")
	bla, tmpExt = test.getTmpFileName("bla", "r").split(".", 1)
	tmpExt = " " + tmpExt + " "
	#print "search for script '" + script + "'"
	if os.path.isfile(script ):
	    #print "found RunTest script: set cmd to '" + script  + " " + prog + tmpExt + test.options + "'"
	    return script  + " " + prog + tmpExt + test.options
	script = os.path.join(rootdir ,"../Flamenco/RunTest")
	#print "search for script '" + script + "'"
	if os.path.isfile(script):
	    #print "found RunTest script: set cmd to '" + script + " " + prog + tmpExt + test.options + "'"
	    return script  + " " + prog + tmpExt + test.options
	#print "NO RunTest script: set binary to '" + prog + " " + test.options + "'" 
	return prog + " " + test.options
    def getTestCollator(self):
        return plugins.CompositeAction([ carmen.CarmenConfig.getTestCollator(self), MakeResultFiles() ])
    def printHelpDescription(self):
        print helpDescription
        carmen.CarmenConfig.printHelpDescription(self)

class MakeResultFiles(plugins.Action):
    def __call__(self, test):
	self.collectSqlErr
	reqList = []
	for file in os.listdir(test.abspath):
	    #print " check file " + file
	    stem = file
	    ext = ""
	    if file.find(".") != -1:
		stem, ext = file.split(".", 1)
	    if stem.endswith("log") or stem.endswith("Output"):
		if stem not in reqList:
		    #print "requireFile " + stem
		    reqList.append(stem) #is a required file
	for stem in reqList:
	    self.collectFile(test,stem)
    def collectFile(self,test,stem):
	temp = test.getTmpFileName(stem, "r")
	if os.path.isfile(temp):#was produced by program directly, need to cleanup
	    #print "collectFile(" + stem + ") exists: " + temp
	    ttemp = test.getTmpFileName(stem + "_clean", "w")
	    os.rename(temp, ttemp)
	    temp = test.getTmpFileName(stem, "w")#this deletes old such files
	    os.rename(ttemp, temp)
	    return
	else: #was not created, check if a file for collection exists
	    temp = test.getTmpFileName(stem, "w")#this deletes old tempfiles
	    bla, tmpExt = test.getTmpFileName("bla", "r").split(".", 1)
	    for file in os.listdir(test.abspath):
		if file.startswith(stem + ".") and file.find(tmpExt) != -1:
		    #print "collectFile(" + stem + "," + file + ") as " + temp
		    os.rename(file, temp)#this is a run-dependent file, use it
		    return
		if file.startswith(stem + ".") and file.find("." + test.app.name) == -1:
		    #print "collectFile(" + stem + "," + file + ") as " + temp
		    os.rename(file, temp)#this is a test-independent file, use it
		    return
	    #print "requireFile(" + stem + ") create dummy " + temp
	    file = open(temp, "w")
	    file.write("NOT FOUND" + os.linesep)
    def collectSqlErr(self):
	sqlfile = test.getTmpFileName("sqlerr", "w")
        if os.path.isfile("sqlnet.log"):
            os.rename("sqlnet.log", sqlfile)
        else:
            file = open(sqlfile, "w")
            file.write("NO ERROR" + os.linesep)
	
    
