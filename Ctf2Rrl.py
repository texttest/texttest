#!/usr/local/bin/python
import os, plugins, respond, string, carmen, checkExtensions, shutil

from checkExtensions import COMPRESS, UNCOMPRESS

def getConfig(optionMap):
    return Ctf2RrlConfig(optionMap)

def decompressAndRename(src,dst):
    if checkExtensions.isCompressed(src):
        os.system('zcat ' + src + ' > ' + dst)
        os.unlink(src)
    else:
        try:
            os.rename(src, dst)
        except OSError:
            shutil.copyfile(src, dst)

class Ctf2RrlConfig(checkExtensions.CheckExtConfig):
    def getTestCollator(self):
        return [checkExtensions.HandleCompressedFiles(UNCOMPRESS,'check_extension'),
                                        carmen.CarmenConfig.getTestCollator(self),
                                        RenamePlans(),
                                        checkExtensions.CreateCompareFiles(),
                                        checkExtensions.HandleCompressedFiles(COMPRESS)]


class RenamePlans(plugins.Action):
    def __call__(self, test):
        carmusrDir = os.getenv("CARMUSR")
        if carmusrDir == None:
            return
        # Local plan
        localPlan1 = os.getenv("TESTCASE_LP_1")
        if localPlan1 != None:
	    localPlan2 = os.getenv("TESTCASE_LP_2")
	    localPlan3 = os.getenv("TESTCASE_LP_3")
	    localPlanDir = carmusrDir + "/LOCAL_PLAN/" + localPlan1 + "/" + localPlan2 + "/" + localPlan3
	    localPlan = localPlanDir + "/localplan"
	    if os.path.isfile(localPlan):
		decompressAndRename(localPlan,"./localplan.rrl")
        # Sub plan
        subPlanName = os.getenv("TESTCASE_SP")
        if subPlanName != None:
	    subPlan = localPlanDir + "/" + subPlanName + "/subplan"
	    subPlanHeader = subPlan + "Header"
	    if os.path.isfile(subPlan):
		decompressAndRename(subPlan,"./subplan.rrl")
	    if os.path.isfile(subPlanHeader):
		decompressAndRename(subPlanHeader,"./subplanHeader.rrl")
        # Environment plan
        envPlanName = os.getenv("TESTCASE_EP")
        if envPlanName != None:
	    envPlan = localPlanDir + "/" + envPlanName + "/subplan"
	    envPlanHeader = envPlan + "Header"
	    if os.path.isfile(envPlan):
		decompressAndRename(envPlan,"./envplan.rrl")
	    if os.path.isfile(envPlanHeader):
		decompressAndRename(envPlanHeader,"./envplanHeader.rrl")
