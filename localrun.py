#!/usr/local/bin/python
import os

class RunTest:
    def __repr__(self):
        return "Running"
    def __call__(self, test, description):
        print description
        stdin, stdout, stderr = os.popen3(test.getExecuteCommand())
        if os.path.isfile(test.inputFile):
            stdin.write(open(test.inputFile).read())
            stdin.close()
        outfile = open(test.getTmpFileName("output", "w"), "w")
        outfile.write(stdout.read())
        errfile = open(test.getTmpFileName("errors", "w"), "w")
        errfile.write(stderr.read())
    def setUpSuite(self, suite, description):
        print description
    
