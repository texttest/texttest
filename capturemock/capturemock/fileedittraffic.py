
""" Capturing edits for files, currently only from command line traffic """

import traffic, os, logging, shutil

class FileEditTraffic(traffic.ResponseTraffic):
    typeId = "FIL"
    linkSuffix = ".TEXTTEST_SYMLINK"
    deleteSuffix = ".TEXTTEST_DELETION"
    replayFileEditDir = None
    recordFileEditDir = None
    fileRequestCount = {} # also only for recording
    diag = None
    @classmethod
    def configure(cls, options):
        cls.diag = logging.getLogger("Traffic Server")
        cls.replayFileEditDir = options.replay_file_edits
        cls.recordFileEditDir = options.record_file_edits
        
    def __init__(self, fileName, activeFile, storedFile, changedPaths, reproduce):
        self.activeFile = activeFile
        self.storedFile = storedFile
        self.changedPaths = changedPaths
        self.reproduce = reproduce
        traffic.ResponseTraffic.__init__(self, fileName, None)

    @classmethod
    def getFileWithType(cls, fileName):
        if cls.replayFileEditDir:
            for name in [ fileName, fileName + cls.linkSuffix, fileName + cls.deleteSuffix ]:
                candidate = os.path.join(cls.replayFileEditDir, name)
                if os.path.exists(candidate):
                    return candidate, cls.getFileType(candidate)
        return None, "unknown"

    @classmethod
    def getFileType(cls, fileName):
        if fileName.endswith(cls.deleteSuffix):
            return "unknown"
        elif os.path.isdir(fileName):
            return "directory"
        else:
            return "file"

    @classmethod
    def makeRecordedTraffic(cls, file, changedPaths):
        storedFile = os.path.join(cls.recordFileEditDir, cls.getFileEditName(os.path.basename(file)))
        fileName = os.path.basename(storedFile)
        cls.diag.info("File being edited for '" + fileName + "' : will store " + str(file) + " as " + str(storedFile))
        for path in changedPaths:
            cls.diag.info("- changed " + path)
        return cls(fileName, file, storedFile, changedPaths, reproduce=False)

    @classmethod
    def getFileEditName(cls, name):
        timesUsed = cls.fileRequestCount.setdefault(name, 0) + 1
        cls.fileRequestCount[name] = timesUsed
        if timesUsed > 1:
            name += ".edit_" + str(timesUsed)
        return name

    def removePath(self, path):
        if os.path.isfile(path) or os.path.islink(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)

    def copy(self, srcRoot, dstRoot):
        for srcPath in self.changedPaths:
            dstPath = srcPath.replace(srcRoot, dstRoot)
            try:
                dstParent = os.path.dirname(dstPath)
                if not os.path.isdir(dstParent):
                    os.makedirs(dstParent)
                if srcPath.endswith(self.linkSuffix):
                    self.restoreLink(srcPath, dstPath.replace(self.linkSuffix, ""))
                elif os.path.islink(srcPath):
                    self.storeLinkAsFile(srcPath, dstPath + self.linkSuffix)
                elif srcPath.endswith(self.deleteSuffix):
                    self.removePath(dstPath.replace(self.deleteSuffix, ""))
                elif not os.path.exists(srcPath):
                    open(dstPath + self.deleteSuffix, "w").close()
                else:
                    shutil.copyfile(srcPath, dstPath)
            except IOError:
                print "Could not transfer", srcPath, "to", dstPath

    def restoreLink(self, srcPath, dstPath):
        linkTo = open(srcPath).read().strip()
        if not os.path.islink(dstPath):
            os.symlink(linkTo, dstPath)

    def storeLinkAsFile(self, srcPath, dstPath):
        writeFile = open(dstPath, "w")
        # Record relative links as such
        writeFile.write(os.readlink(srcPath).replace(os.path.dirname(srcPath) + "/", "") + "\n")
        writeFile.close()

    def forwardToDestination(self):
        self.write(self.text)
        if self.reproduce:
            self.copy(self.storedFile, self.activeFile)
        return []
        
    def record(self, *args):
        # Copy the file, as well as the fact it has been stored
        traffic.ResponseTraffic.record(self, *args)
        if not self.reproduce:
            self.copy(self.activeFile, self.storedFile)
