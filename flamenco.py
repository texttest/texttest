helpDescription = """
The Flamenco configuration is based on the Carmen configuration. It is set up to replace the string "ARCHITECTURE"
with the running architecture in the name of the binary given in the config file. It will also collect the
file "sqlnet.log", and compare it as the test suite file sqlerr.<app>."""

import carmen, os, plugins, unixConfig

def getConfig(optionMap):
    return FlamencoConfig(optionMap)

class FlamencoConfig(carmen.CarmenConfig):
    def __init__(self, optionMap):
        carmen.CarmenConfig.__init__(self,optionMap)
        global debugLog
	debugLog = plugins.getDiagnostics("flamenco")
    def getExecuteCommand(self, binary, test):
	prog = binary.replace("ARCHITECTURE", carmen.getArchitecture(test.app))
	testext = " " + test.app.name + " "
	fullprog = prog + " " + test.options
	if prog == binary:#not architecture dependent, probably is a script
	    debugLog.info("binary is a script: set cmd to '" + fullprog + "'" )
	    return fullprog
	rootdir = test.app.abspath
	script = os.path.join(rootdir ,"RunTest")
	debugLog.info("search for script '" + script + "'")
	if os.path.isfile(script ):
	    fullprog = script  + " " + prog + testext + test.options
	    debugLog.info( "found RunTest script: set cmd to '" + fullprog + "'")
	    return fullprog
	script = os.path.join(rootdir ,"../Flamenco/RunTest")
	debugLog.info( "search for script '" + script + "'")
	if os.path.isfile(script):
	    fullprog = script  + " " + prog + testext + test.options
	    debugLog.info( "found RunTest script: set cmd to '" + fullprog + "'")
	    return fullprog
	debugLog.info( "NO RunTest script: set cmd to '" + fullprog + "'" )
	return fullprog
    def getFileCollator(self):
        return CollateFiles()
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
    def findReqFiles(self):
	try:
	    return app.getConfigList("required_file")
	except:
	    #value not set
	    debugLog.info(nameslist + " not set")
	return None

class CollateFiles(unixConfig.CollateUNIXFiles):
    def __init__(self):
	unixConfig.CollateUNIXFiles.__init__(self)
        self.collations.append(("sqlnet.log", "sqlerr"))
    def setUpApplication(self, app):
        unixConfig.CollateUNIXFiles.setUpApplication(self, app)
        for stem in app.getConfigList("required_file"):
            debugLog.info("collect output file " + stem)
            self.collations.append((stem + "*", "resultfile_" + stem))
    def getErrorText(self, sourcePattern):
        if sourcePattern == "sqlnet.log":
            return "NO ERROR"
        else:
            return unixConfig.CollateUNIXFiles.getErrorText(self, sourcePattern)
    def extract(self, sourcePath, targetFile):
        os.rename(sourcePath, targetFile)

