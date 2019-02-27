#!/usr/bin/env python3


import os
import sys
from optparse import OptionParser


def fixSysPath(fileName):
    install_root = os.path.dirname(os.path.dirname(fileName))
    # We pick up the basic libraries.
    # or a "generic" directory containing the TextTest core with local modules in the root
    for subdir in ["", "lib", "site/lib", "generic"]:
        libDir = os.path.abspath(os.path.join(install_root, subdir))
        if os.path.isdir(libDir):
            sys.path.insert(0, libDir)


if __name__ == "__main__":
    fixSysPath(os.path.abspath(__file__))
    from texttestlib import plugins, default
    parser = OptionParser("usage: %prog [options] filter1 filter2 ...")
    parser.add_option("-m", "--module",
                      help="also import module MODULE", metavar="MODULE")
    parser.add_option("-u", "--unordered", action="store_true",
                      help='Use unordered filter instead of standard one')
    parser.add_option("-t", "--testrelpath",
                      help="use test relative path RELPATH", metavar="RELPATH")
    (options, args) = parser.parse_args()
    if options.module:
        exec("import " + options.module)
    allPaths = plugins.findDataPaths(["logging.console"], dataDirName="log", includePersonal=True)
    plugins.configureLogging(allPaths[-1])  # Won't have any effect if we've already got a log file
    if options.unordered:
        runDepFilter = default.rundependent.UnorderedTextFilter(args, options.testrelpath)
    else:
        runDepFilter = default.rundependent.RunDependentTextFilter(args, options.testrelpath)
    runDepFilter.filterFile(sys.stdin, sys.stdout)
