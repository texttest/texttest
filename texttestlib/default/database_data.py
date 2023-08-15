
import os, shutil
from texttestlib import plugins

class SaveDatabase(plugins.Action):

    def __init__(self, dirName):
        self.dbSetupDirName = dirName

    def __call__(self, test):
        tmpDir = os.path.join(test.getDirectory(temporary=True), self.dbSetupDirName)
        dstDir = os.path.join(test.getDirectory(), self.dbSetupDirName)
        if os.path.isdir(dstDir):
            self.mergeDirs(tmpDir, dstDir)
        elif os.path.isdir(tmpDir):
            shutil.copytree(tmpDir, dstDir)

    def mergeDirs(self, src, dst):
        for srcRoot, dirs, files in os.walk(src):
            dstRoot = srcRoot.replace(src, dst)
            for d in dirs:
                dstDir = os.path.join(dstRoot, d)
                if not os.path.isdir(dstDir):
                    os.mkdir(dstDir)
            for f in files:
                dstFile = os.path.join(dstRoot, f)
                srcFile = os.path.join(srcRoot, f)
                if os.path.isfile(dstFile):
                    # if PrepareWriteDirectoryMergeTables.is_db_table_addition(dstFile) and \
                    #    PrepareWriteDirectoryMergeTables.is_db_table_addition(srcFile):
                    #     with open(dstFile, "a") as f:
                    #         f.write(open(srcFile).read())
                    #     continue
                    # else:
                    os.remove(dstFile)
                shutil.copyfile(srcFile, dstFile)