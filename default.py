#!/usr/local/bin/python
import os, localrun, respond, comparetest

def getConfig(optionMap):
    return Config(optionMap)

class Config:
    def __init__(self, optionMap):
        self.optionMap = optionMap
    def getOptionString(self):
        return "iot:"
    def optionValue(self, option):
        if self.optionMap.has_key(option):
            return self.optionMap[option]
        else:
            return ""
    def getActionSequence(self):
        if self.optionMap.has_key("i"):
            return [ [ self.getTestRunner() ] + self.getTestEvaluator() ]
        else:
            return [ self.getTestRunner(), self.getTestEvaluator() ]
    def getFilterList(self):
        filters = []
        self.addFilter(filters, "t", TestNameFilter)
        return filters
    def addFilter(self, list, optionName, filterObj):
        if self.optionMap.has_key(optionName):
            list.append(filterObj(self.optionMap[optionName]))
    def getTestRunner(self):
        return localrun.RunTest()
    def getTestEvaluator(self):
        return self.getTestCollator() + self.getTestComparator() + self.getTestResponder()
    def getTestCollator(self):
        return []
    def getTestComparator(self):
        return [ comparetest.MakeComparisons() ]
    def getTestResponder(self):
        if self.optionMap.has_key("o"):
            return [ respond.OverwriteOnFailures(self.optionValue("v")) ]
        else:
            return [ respond.InteractiveResponder() ]

class TextFilter:
    def __init__(self, filterText):
        self.text = filterText
    def acceptsTestCase(self, test):
        return 1
    def acceptsTestSuite(self, suite):
        return 1
    def containsText(self, test):
        return test.name.find(self.text) != -1
    def equalsText(self, test):
        return test.name == self.text
    
class TestNameFilter(TextFilter):
    def acceptsTestCase(self, test):
        return self.containsText(test)
    
