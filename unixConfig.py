#!/usr/local/bin/python

# Text only relevant to using the LSF configuration directly
helpDescription = """
The UNIX configuration is designed to run on a UNIX system. It therefore makes use of some
UNIX tools, such as tkdiff, diff and /usr/lib/sendmail. The difference tools are used in preference
to Python's ndiff, and sendmail is used to implement an email-sending batch mode (see options)

The default behaviour is to run all tests locally.
"""

import default, batch, respond, comparetest, predict, os, shutil

def getConfig(optionMap):
    return UNIXConfig(optionMap)

class UNIXConfig(default.Config):
    def getArgumentOptions(self):
        options = default.Config.getArgumentOptions(self)
        options["b"] = "Run batch mode with identifier"
        return options
    def getFilterList(self):
        filters = default.Config.getFilterList(self)
        self.addFilter(filters, "b", batch.BatchFilter)
        return filters
    def getActionSequence(self):
        seq = default.Config.getActionSequence(self)
        if self.optionMap.has_key("b"):
            seq.append(batch.MailSender(self.optionValue("b")))
        return seq
    def getTestCollator(self):
        return CollateCore("core*", "stacktrace")
    def getTestResponder(self):
        diffLines = 30
        # If running multiple times, batch mode is assumed
        if self.optionMap.has_key("b") or self.optionMap.has_key("m"):
            return batch.BatchResponder(diffLines)
        elif self.optionMap.has_key("o"):
            return default.Config.getTestResponder(self)
        else:
            return respond.UNIXInteractiveResponder(diffLines)
    def printHelpDescription(self):
        print helpDescription, predict.helpDescription, comparetest.helpDescription, respond.helpDescription 
    def printHelpOptions(self, builtInOptions):
        print batch.helpOptions
        default.Config.printHelpOptions(self, builtInOptions)

def isCompressed(path):
    if os.path.getsize(path) == 0:
        return 0
    magic = open(path).read(2)
    if magic[0] == chr(0x1f) and magic[1] == chr(0x9d):
        return 1
    else:
        return 0

# Deal with UNIX-compressed files as well as straight text
class CollateFile(default.CollateFile):
    def transformToText(self, path):
        if not isCompressed(path):
            return        
        toUse = path + ".Z"
        os.rename(path, toUse)
        os.system("uncompress " + toUse)

# Extract just the stack trace rather than the whole core
class CollateCore(CollateFile):
    def transformToText(self, path):
        CollateFile.transformToText(self, path)
        if os.path.getsize(path) == 0:
            os.remove(path)
            file = open(path, "w")
            file.write("Core file of zero size written - no stack trace for crash\nCheck your coredumpsize limit" + os.linesep)
            file.close()
            return
        fileName = "coreCommands.gdb"
        file = open(fileName, "w")
        file.write("bt\nq\n")
        file.close()
        # Yes, we know this is horrible. Does anyone know a better way of getting the binary out of a core file???
        # Unfortunately running gdb is not the answer, because it truncates the data...
        binary = os.popen("csh -c 'echo `tail -c 1024 " + path + "`' 2> /dev/null").read().split(" ")[-1].strip()
        newPath = path + "tmp" 
        writeFile = open(newPath, "w")
        if os.path.isfile(binary):
            gdbData = os.popen("gdb -q -x " + fileName + " " + binary + " " + path)
            prevLine = ""
            for line in gdbData.xreadlines():
                if line.find("Program terminated") != -1:
                    writeFile.write(line)
                    writeFile.write("Stack trace from gdb :" + os.linesep)
                if line[0] == "#" and line != prevLine:
                    startPos = line.find("in ") + 3
                    endPos = line.rfind("(")
                    writeFile.write(line[startPos:endPos] + os.linesep)
                prevLine = line
        else:
            writeFile.write("Could not find binary name from core file - no stack trace for crash" + os.linesep)
        os.remove(path)
        os.remove(fileName)
        os.rename(newPath, path)
    def extract(self, sourcePath, targetFile):
        try:
            os.rename(sourcePath, targetFile)
        except:
            print "Failed to rename '" + sourcePath + "' to '" + targetFile + "', using copy-delete"
            shutil.copyfile(sourcePath, targetFile)
            os.remove(sourcePath)
