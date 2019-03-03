#!/usr/bin/env python

import optparse, os, sys, StringIO

def fixSysPath(fileName):
    install_root = os.path.dirname(os.path.dirname(fileName))
    # We pick up the basic libraries.
    # or a "generic" directory containing the TextTest core with local modules in the root
    for subdir in [ "", "lib", "site/lib", "generic" ]:
        libDir = os.path.abspath(os.path.join(install_root, subdir))
        if os.path.isdir(libDir):
            sys.path.insert(0, libDir)


def main():
    fixSysPath(os.path.abspath(__file__))
    from texttestlib.default.fpdiff import fpfilter
    parser = optparse.OptionParser("usage: %prog [options] fromfile tofile")
    parser.add_option("-t", "--tolerance", type="float",
                      help='Set absolute floating point tolerance')
    parser.add_option("-r", "--relative", type="float",
                      help='Set relative floating point tolerance')
    parser.add_option("-o", "--output",
                      help='Write filtered tofile to use external diff')
    (options, args) = parser.parse_args()
    if len(args) == 0: # pragma: no cover - not production code
        parser.print_help()
        sys.exit(1)
    if len(args) != 2: # pragma: no cover - not production code
        parser.error("need to specify both a fromfile and tofile")
    fromfile, tofile = args
    fromlines = open(fromfile, 'U').readlines()
    tolines = open(tofile, 'U').readlines()
    if options.output:
        out = open(options.output, 'w')
        fpfilter(fromlines, tolines, out, options.tolerance, options.relative)
        out.close()
    else: # pragma: no cover - not production code
        out = StringIO.StringIO()
        fpfilter(fromlines, tolines, out, options.tolerance, options.relative)
        out.seek(0)
        tolines = out.readlines()
        sys.stdout.writelines(difflib.unified_diff(fromlines, tolines, fromfile, tofile))

if __name__ == '__main__':
    main()
