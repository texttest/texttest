helpDescription = """
The Flamenco configuration is based on the Carmen configuration. It is set up to replace the string "ARCHITECTURE"
with the running architecture in the name of the binary given in the config file. It will also collect the
file "sqlnet.log", and compare it as the test suite file sqlerr.<app>."""

import carmen, os, plugins

def getConfig(optionMap):
    return FlamencoConfig(optionMap)

class FlamencoConfig(carmen.CarmenConfig):
    def __init__(self, optionMap):
        carmen.CarmenConfig.__init__(self,optionMap)
        global debugLog
	debugLog = plugins.getDiagnostics("flamenco")
    def getExecuteCommand(self, binary, test):
	prog = binary.replace("ARCHITECTURE", carmen.getArchitecture(test.app))
	if prog == binary:#not architecture dependent, probably is a script
	    debugLog.info("binary is a script: set binary to '" + prog + " " + test.options + "'" )
	    return prog + " " + test.options
	rootdir = test.app.abspath
	script = os.path.join(rootdir ,"RunTest")
	bla, tmpExt = test.makeFileName("bla", temporary=1).split(".", 1)
	tmpExt = " " + tmpExt + " "
	debugLog.info("search for script '" + script + "'")
	if os.path.isfile(script ):
	    debugLog.info( "found RunTest script: set cmd to '" + script  + " " + prog + tmpExt + test.options + "'")
	    return script  + " " + prog + tmpExt + test.options
	script = os.path.join(rootdir ,"../Flamenco/RunTest")
	debugLog.info( "search for script '" + script + "'")
	if os.path.isfile(script):
	    debugLog.info( "found RunTest script: set cmd to '" + script + " " + prog + tmpExt + test.options + "'")
	    return script  + " " + prog + tmpExt + test.options
	debugLog.info( "NO RunTest script: set binary to '" + prog + " " + test.options + "'" )
	return prog + " " + test.options
    def getTestCollator(self):
        return plugins.CompositeAction([ carmen.CarmenConfig.getTestCollator(self), MakeResultFiles() ])
    def printHelpDescription(self):
        print helpDescription
        carmen.CarmenConfig.printHelpDescription(self)
    def _findReqResource(self, app):
        # search for resource requirements in the config
	# named by version, batch or architecture
	versions = app.getVersionFileExtensions()
	if self.optionMap.has_key("b"):
	    #search all subversions for batch
	    res_base = self.optionValue("b")
	    for version in versions:
		version = version.replace(".","_")
		try:
		    res_version = app.getConfigValue(res_base + "_lsfres_" + version)
		    debugLog.info(res_base +"_lsfres_" + version + " = " + res_version )
		    return res_version
		except:
		    #value not set
		    debugLog.info(res_base +"_lsfres_" + version + " not set")
	    #try without version
	    try:
		res_version = app.getConfigValue(res_base + "_lsres")
		debugLog.info(res_base +"_lsfres = " + res_version )
		return res_version
	    except:
		#value not set
		debugLog.info(res_base +"_lsfres not set")
	#now try without a batch_prefix
	for version in versions:
	    version = version.replace(".","_")   
	    try:
		res_version = app.getConfigValue("lsfres_" + version)
		debugLog.info("lsfres_" + version + " = " + res_version )
		return res_version
	    except:
		#value not set
		debugLog.info( "lsfres_" + version + " not set")
	#try without any prefix or version:
	try:
	    res_version = app.getConfigValue("lsfres")
	    debugLog.info("lsfres = " + res_version )
	    return res_version
	except:
	    #value not set
	    debugLog.info( "lsfres not set")
	#no lsfres config value was set
	return ""
    def findResourceList(self, app):
	req_resource = self._findReqResource(app)
	req_resource = req_resource.replace("ARCHITECTURE", carmen.getArchitecture(app))
	resourceList = carmen.CarmenConfig.findResourceList(self, app)
	if req_resource != "":
	    debugLog.info( "adding required resource: " + req_resource )
	    resourceList.append(req_resource)
        return resourceList

class MakeResultFiles(plugins.Action):
    def __call__(self, test):
	self.collectSqlErr
	reqList = []
	for file in os.listdir(os.getcwd()):
	    debugLog.debug( " check file " + file)
	    stem = file
	    ext = ""
	    if file.find(".") != -1:
		stem, ext = file.split(".", 1)
	    if stem.endswith("log") or stem.endswith("Output"):
		# candidate: require if it is NOT a result file (produced by run)
		# or if ext == app
		isReq = 0
		if stem.startswith("resultfile_"):
		    #is a resultfile, use only if it is from my application
		    if ext == test.app.name:
			isReq = 1
			ext, stem = stem.split("_",1)
		else:
		    #not a resultfile, this was produced by the program
		    isReq = 1
		if isReq == 1 and stem not in reqList:
		    debugLog.info( "requireFile " + stem)
		    reqList.append(stem) #is a required file
	for stem in reqList:
	    self.collectFile(test,stem)
    def collectFile(self,test,stem):
	#test if the program has produced a file with run-dependent extension
	search = test.makeFileName(stem, temporary=1)
	temp = test.makeFileName("resultfile_" + stem, temporary=1)#this deletes old tempfiles
	if os.path.isfile(search):
	    # program has written the run-dependent file
	    # to make it a result-file we just prefix it as "resultfile_"
	    debugLog.info( "collectFile(" + stem + ") exists: " + temp)
	    os.rename(search,temp)
	    return
	else: 
            #check if the program has produced some run-independent output...
	    bla, tmpExt = search.split(".", 1)
            for file in os.listdir(os.getcwd()):
		if file.startswith(stem + "."):
		    #candidate: this file has the right filename, lets check the extension
		    if file.find(tmpExt) != -1:
			# file contains the run-dependent extension in its name
			# it is written by the run for sure
			debugLog.info( "collectFile(" + stem + "," + file + ") as " + temp)
			os.rename(file, temp)#this is a run-dependent file, use it
			return
		    else :
			# the file dosent contain the run-extension,
			# it might be ok, if it wasnt produced by another run...
			if file.find("." + test.getTestUser()) == -1:
			    debugLog.info( "collectFile(" + stem + "," + file + ") as " + temp)
			    os.rename(file, temp)
			    return
	    #no file matched the filename and had an accepted extension
	    #create a dummy-file that reports the missing of the result
	    debugLog.info( "requireFile(" + stem + ") create dummy " + temp)
	    file = open(temp, "w")
	    file.write("NOT FOUND" + os.linesep)
    def collectSqlErr(self):
	sqlfile = test.makeFileName("sqlerr", temporary=1)
        if os.path.isfile("sqlnet.log"):
            os.rename("sqlnet.log", sqlfile)
        else:
            file = open(sqlfile, "w")
            file.write("NO ERROR" + os.linesep)
	
    
