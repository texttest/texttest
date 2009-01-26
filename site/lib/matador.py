helpDescription = """
The Matador configuration is based on the Rave-based configuration. It will compile all static rulesets in the test
suite before running any tests, if the library file "matador.o" has changed since the static ruleset was last built.""" 

helpScripts = """matador.ImportTest         - Import new test cases and test users.
                             The general principle is to add entries to the "testsuite.<app>" file and then
                             run this action, typcally 'texttest -a <app> -s matador.ImportTest'. The action
                             will then find the new entries (as they have no corresponding subdirs) and
                             ask you for either new CARMUSR and CARMTMP (for new user) or new subplan
                             directory (for new tests). Also for new tests it is neccessary to have an
                             'APC_FILES' subdirectory created by Studio which is to be used as the
                             'template' for temporary subplandirs as created when the test is run.
                             The action will look for available subplandirectories under
                             CARMUSR and present them to you.
matador.TimeSummary         - Show a summary of 'useful' time in generation solutions.
                            The idea is that generation time and optimization time is considered useful and
                            compared to the total time. Output is like:
                               52% 14:45 RD_klm_cabin::index_groups_test
                            First item is how much time in percent was generation and optimization.
                            Second item is total runtime in hours:minutes of the test
                            Third item is the name of the test

                            Currently supports these options:
                             - sd
                               Display the solution details, ie useful percent for each solution
                             - v=version
                               Print result for specific version
matador.MigrateApcTest      - Take a test present in APC and migrate it to Matador/Picador. Before running
                            the script, make sure that the test is fully present for APC (use apc.ImportTest first if
                            it wasn't there yet) and that an entry is added for it in the testsuite file for Matador/Picador.
                            Also make sure that the file remap_rulesets.etab (under Testing/Automatic/<dirname>) is up to
                            date with the corresponding ruleset that you are migrating, and that the parameter transform table
                            remap_<app>.etab (installed into carmusr_default) is up to date with the latest parameter
                            settings.
                            The script will then replace the ruleset in the subplanHeader and problems
                            files, showing you the differences locally. Press ^C if anything is wrong. It will also
                            transform the module parameters in subplanRules and rules, again showing you the differences
                            as above. When all this has been accepted, it will commit the changes, copying the subplan,
                            making the changes it has shown, and writing an options.<app> file.
"""

import matador_basic, ravebased, os, shutil, optimization, plugins, sys

def getConfig(optionMap):
    return Config(optionMap)

class Config(matador_basic.Config):
    def _getRuleSetNames(self, test):
        rulesets = []
        basicRuleSet = self.getBasicRuleSet(test)
        if basicRuleSet:
            rulesets.append(basicRuleSet)
        for extra in self.getExtraRollingStockRulesets(test):
            if not extra in rulesets:
                rulesets.append(extra)
        return rulesets
    def getExtraRollingStockRulesets(self, test):
        extras = []
        compRules = test.getEnvironment("COMPOSITION_OPTIMIZATION_RULESET")
        if compRules:
            extras.append(compRules)
        rotRules = test.getEnvironment("ROTATION_OPTIMIZATION_RULESET")
        if rotRules:
            extras.append(rotRules)
        depotRules = test.getEnvironment("DEPOT_OPTIMIZATION_RULESET")
        if depotRules:
            extras.append(depotRules)
        return extras
    def getRuleBuildFilterer(self):
        return FilterRuleBuilds()
    def printHelpDescription(self):
        print helpDescription
        matador_basic.Config.printHelpDescription(self)
    def printHelpScripts(self):
        matador_basic.Config.printHelpScripts(self)
        print helpScripts
    def getCarmenEnvironment(self, app):
        envVars = matador_basic.Config.getCarmenEnvironment(self, app)
        envVars += [ ("CARMEN_PRODUCT", self.getProductName(app)) ]
        return envVars
    def getProductName(self, app):
        if app.name in [ "rso", "rot", "depot" ]:
            return "RailFleet"
        else:
            return "standard_gpc"
        
def staticLinkageInCustomerFile(carmUsr):
    resourceFile = os.path.join(carmUsr, "Resources", "CarmResources", "Customer.etab")
    if not os.path.isfile(resourceFile):
        return 0
    for line in open(resourceFile).xreadlines():
        if line.find("UseStaticLinking") != -1 and line.find("matador") != -1:
            parts = plugins.commasplit(line.strip())
            if parts[4].find("true") != -1:
                return 1
    return 0

class FilterRuleBuilds(ravebased.FilterRuleBuilds):
    def assumeDynamicLinkage(self, libFile, carmUsr):
        return not staticLinkageInCustomerFile(carmUsr)

class PrintRuleValue(plugins.Action):
    def __init__(self, args = []):
        self.variable = args[0]
    def __repr__(self):
        return "Printing rule values for"
    def __call__(self, test):
        rulesFile = os.path.join(test.getEnvironment("CARMUSR"), "LOCAL_PLAN", getOption(test, "-s"), "APC_FILES", "rules")
        for line in open(rulesFile).xreadlines():
            if line.find(self.variable + " TRUE") != -1:
                print test.getIndent() + self.variable + " in " + repr(test)   
    def setUpSuite(self, suite):
        self.describe(suite)

class UpdateXpressVersion(plugins.Action):
    def __repr__(self):
        return "Updating XPRESS version for"
    def __call__(self, test):
        self.describe(test)
        errFile = test.getFileName("errors")
        newErrFile = test.getFileName("new_errors")
        writeFile = open(newErrFile, "w")
        for line in open(errFile).xreadlines():
            writeFile.write(line.replace("15.10.04", "15.10.06"))
        writeFile.close()
        os.rename(newErrFile, errFile)
        os.system("cvs diff " + errFile)
                  
class CopyEnvironment(plugins.Action):
    def __repr__(self):
        return "Making environment.ARCH for"
    def setUpSuite(self, suite):
        versions = [ "", ".10", ".9" ]
        if ravebased.isUserSuite(suite):
            self.describe(suite)
            for version in versions:
                oldFile = os.path.join(suite.abspath, "environment.cas" + version)
                if not os.path.isfile(oldFile):
                    return

                if len(version) == 0:
                    oldcarmtmp = self.getCarmtmp(oldFile)
                    root, locals = os.path.split(os.path.normpath(oldcarmtmp))
                    newcarmtmp = self.getNewCarmtmp(oldcarmtmp, local)
                    self.replaceInFile(oldFile, oldcarmtmp, newcarmtmp)
                else:
                    os.system("cvs rm -f " + oldFile)
                archs = self.getArchs(version)
                for arch in archs:
                    targetFile = oldFile + "." + arch
                    if os.path.isfile(targetFile):
                        os.system("cvs rm -f " + targetFile)
    def getArchs(self, version):
        archs = [ "sparc", "parisc_2_0", "powerpc" ]
        if len(version) == 0:
            archs.append("sparc_64")
        return archs
    def getNewCarmtmp(self, oldcarmtmp, local):
        basePath = "${CARMSYS}"
        if oldcarmtmp.find("CARMSYS") == -1:
            basePath = "/carm/proj/matador/carmtmps/${MAJOR_RELEASE_ID}"
        return os.path.join(basePath, "${ARCHITECTURE}", local)
    def makeCarmtmpFile(self, targetFile, carmtmp):
        file = open(targetFile, "w")
        print carmtmp
        file.write("CARMTMP:" + carmtmp + os.linesep)
        file.close()
        os.system("cvs add " + targetFile)
    def getCarmtmp(self, file):
        for line in open(file).xreadlines():
            if line.startswith("CARMTMP"):
                name, carmtmp = line.strip().split(":")
                return carmtmp
    def replaceInFile(self, oldFile, oldVal, newVal):
        newFileName = oldFile + ".new"
        newFile = open(newFileName, "w")
        for line in open(oldFile).xreadlines():
            newFile.write(line.replace(oldVal, newVal))
        newFile.close()
        os.rename(newFileName, oldFile)
        os.system("cvs diff " + oldFile)
        
class TimeSummary(plugins.Action):
    def __init__(self, args = []):
        self.timeVersions = [ "" ]
        self.timeStates = [ "" ]
        self.scaleTime = 0
        self.useTmpStatus = 0
        self.suite = ""
        self.solutionDetail = 0
        self.genTime = 1
        self.optTime = 1
        # Must be last in the constructor
        self.interpretOptions(args)
    def __repr__(self):
        return "Timing statistics"
    def interpretOptions(self, args):
        for ar in args:
            arr = ar.split("=")
            if arr[0]=="v":
                self.timeVersions = arr[1].split(",")
            elif arr[0]=="sd":
                self.solutionDetail = 1
            elif arr[0]=="opt":
                self.genTime = 0
                self.optTime = 1
            elif arr[0]=="gen":
                self.optTime = 0
                self.genTime = 1
            else:
                print "Unknown option " + arr[0]
    def setUpSuite(self, suite):
        self.suite = suite.name
    # Interactive stuff
    def getTitle(self):
        return "Time statistics"
    def getArgumentOptions(self):
        options = {}
        options["v"] = "Versions to plot"
        return options
    def getSwitches(self):
        switches = {}
        switches["sd"] = "Solution detail(%)"
        return switches
    def __call__(self, test):
        totTime = optimization.timeEntryName
        genTime = "Generation time"
        optTime = "Optimization time"
        entries = [ genTime, optTime ]
        for version in self.timeVersions:
            try:
                optRun = optimization.OptimizationRun(test, version, [ totTime ], entries, self.scaleTime, self.useTmpStatus, self.timeStates[0])
            except plugins.TextTestError:
                print "No status file does exist for test " + test.app.name + "::" + test.name + "(" + version + ")"
                continue
            sumTot = 0
            sumGen = 0
            sumOpt = 0
            lastTotTime = 0;
            usePercent = []
            hasTimes = 0
            for solution in optRun.solutions:
                if solution.has_key(genTime) and solution.has_key(optTime):
                    hasTimes = 1
                    totalTime = int(solution[totTime] * 60) - lastTotTime
                    if totalTime > 0:
                        sumTot += totalTime
                        useFul = 0
                        if self.genTime:
                            sumGen += solution[genTime]
                            useFul = solution[genTime] + solution[optTime]
                        if self.optTime:
                            sumOpt += solution[optTime]
                            useFul += solution[optTime]
                        usePercent.append(str(int(100.0* useFul / totalTime)))
                    else:
                        usePercent.append("--")
                lastTotTime = int(solution[totTime] * 60)
            if sumTot > 0:
                sumUse = int(100.0 * (sumGen + sumOpt) / sumTot)
            else:
                sumUse = 100
            hrs = sumTot / 3600
            mins = (sumTot - hrs * 3600) / 60
            if sumTot > 60 and hasTimes:
                print str(sumUse)+"%", str(hrs) + ":" + str(mins), self.suite + "::" + test.name
                if self.solutionDetail:
                    print "   ", " ".join(usePercent)

class CleanSubplans(plugins.Action):
    def __init__(self):
        self.config = Config(None)
        from sets import Set
        self.preservePaths = Set([])
        self.preserveNames = [ "APC_FILES", "etable" ]
        self.preserveUsers = [ "/carm/proj/matador/carmusrs/master/RD_dl_cbs_v13", \
                               "/carm/proj/matador/carmusrs/carmen_10/RD_song_cas_v10_user", \
                               "/carm/proj/matador/carmusrs/carmen_12/RD_strict_seniority_user" ]
    def __repr__(self):
        return "Cleaning subplans for"
    def __call__(self, test):
        subplan = self.config._getSubPlanDirName(test)
        self.addAll(subplan)
        realpath = self.realpath(subplan)
        if realpath != subplan and realpath.find("LOCAL_PLAN") != -1:
            self.addAll(realpath)
    def addAll(self, path):
        self.preservePaths.add(path)
        dir, local = os.path.split(path)
        if not dir.endswith("LOCAL_PLAN"):
            self.addAll(dir)
    def setUpSuite(self, suite):
        self.describe(suite)
        if ravebased.isUserSuite(suite):
            carmdataVar, carmdata = ravebased.getCarmdata(suite)
            print suite.getIndent() + "Collecting subplans for " + carmdataVar + "=" + carmdata
            self.preservePaths.clear()
    def realpath(self, path):
        return os.path.normpath(os.path.realpath(path).replace("/nfs/vm", "/carm/proj"))
    def tearDownSuite(self, suite):
        if ravebased.isUserSuite(suite):
            if suite.getEnvironment("CARMUSR") in self.preserveUsers:
                print "Ignoring for Curt", suite
            else:
                self.removeUnused()
    def removeUnused(self):
        localplanPath = self.config._getLocalPlanPath(None)
        before = self.getDiskUsage(localplanPath)
        print "Disk usage before", before, "MB"
        self.removeUnder(localplanPath)
        after = self.getDiskUsage(localplanPath)
        print "Removed", before - after, "MB of the original", before
    def removeUnder(self, path):
        for file in os.listdir(path):
            if file in self.preserveNames or file.lower().find("env") != -1:
                continue
            fullPath = os.path.join(path, file)
            if os.path.isdir(fullPath) and not os.path.islink(fullPath):
                if fullPath in self.preservePaths:
                    self.removeUnder(fullPath)
                else:
                    print "Removing unused directory", fullPath, "..."
                    try:
                        shutil.rmtree(fullPath)
                    except:
                        print "FAILED!", str(sys.exc_value)
    def getDiskUsage(self, dir):
        output = os.popen("du -s " + dir).read()
        return int(output.split()[0]) / 1000

class PrintStrings(plugins.Action):
    def __init__(self):
        self.strings = []
    def __call__(self, test):
        logFile = test.getFileName("output")
        for line in open(logFile).readlines():
            line = line.strip()
            if len(line) == 0:
                continue
            pos = line.find(".:")
            if pos != -1:
                line = line[:pos + 2]
            if line in self.strings:
                continue
            self.strings.append(line)
            print line


class MigrateFeatures(plugins.Action):
    def __call__(self, test):
        logFile = test.getFileName("output")
        if not logFile:
            return

        testDir = test.getDirectory()
        featuresFileName = os.path.join(testDir, "features." + test.app.name)
        if os.path.isfile(featuresFileName):
            return
        featuresFile = open(featuresFileName, "w")
        self.migrateFile(logFile, featuresFile)
        featuresFile.close()
        os.system("cvs add " + featuresFileName)
        import glob
        for versionFile in glob.glob(os.path.join(testDir, "output." + test.app.name + ".*")):
            self.migrateFile(versionFile)
    def migrateFile(self, logFile, featuresFile=None):
        newLogFileName = "output.new" 
        newLogFile = open(newLogFileName, "w")
        inSection = False
        for line in open(logFile).readlines():
            if line.find("---------Features") != -1:
                inSection = not inSection
            elif inSection:
                if featuresFile:
                    featuresFile.write(line)
            else:
                newLogFile.write(line)
        newLogFile.close()
        os.rename(newLogFileName, logFile)


class CollectFeatures(plugins.Action):
    def __init__(self):
        self.allFeatures = []
        self.fileToWrite = None
    def __call__(self, test):
        logFile = test.getFileName("features")
        if not logFile:
            return
        for feature in plugins.readList(logFile):
            if feature not in self.allFeatures:
                self.allFeatures.append(feature)
    def setUpApplication(self, app):
        if not self.fileToWrite:
            self.fileToWrite = os.path.join(app.getDirectory(), "features." + app.name)
    def __del__(self):
        self.allFeatures.sort()
        file = open(self.fileToWrite, "w")
        for feature in self.allFeatures:
            file.write(feature + "\n")
    
