#!/usr/local/bin/python

# Text only relevant to using the LSF configuration directly
helpDescription = """
The UNIX configuration is designed to run on a UNIX system. It therefore makes use of some
UNIX tools, such as tkdiff, diff and /usr/lib/sendmail. The difference tools are used in preference
to Python's ndiff, and sendmail is used to implement an email-sending batch mode (see options)

The default behaviour is to run all tests locally.
"""

import default, batch, respond, comparetest, predict

def getConfig(optionMap):
    return UNIXConfig(optionMap)

class UNIXConfig(default.Config):
    def getOptionString(self):
        return "b:" + default.Config.getOptionString(self)
    def getFilterList(self):
        filters = default.Config.getFilterList(self)
        self.addFilter(filters, "b", batch.BatchFilter)
        return filters
    def getTestResponder(self):
        diffLines = 30
        # If running multiple times, batch mode is assumed
        if self.optionMap.has_key("b") or self.optionMap.has_key("m"):
            return batch.BatchResponder(diffLines, self.optionValue("b"))
        elif self.optionMap.has_key("o"):
            return default.Config.getTestResponder(self)
        else:
            return respond.UNIXInteractiveResponder(diffLines)
    def printHelpDescription(self):
        print helpDescription, predict.helpDescription, comparetest.helpDescription, respond.helpDescription 
    def printHelpOptions(self, builtInOptions):
        print batch.helpOptions
        default.Config.printHelpOptions(self, builtInOptions)


