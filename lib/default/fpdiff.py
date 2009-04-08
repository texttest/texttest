#!/usr/bin/env python
import sys, difflib, StringIO, optparse

def _getNumberAt(l, pos):
    start = pos
    while start > 0 and l[start-1] in "1234567890.eE-":
        start -= 1
    end = pos
    while end < len(l) and l[end] in "1234567890.eE-":
        end += 1
    return l[start:end], l[end:]

def _fpequal(l1, l2, tolerance):
    pos = 0
    while pos < min(len(l1), len(l2)):
        if l1[pos] != l2[pos]:
            number1, l1 = _getNumberAt(l1, pos)
            number2, l2 = _getNumberAt(l2, pos)
            try:
                if abs(float(number1) - float(number2)) > tolerance:
                    return False
            except ValueError:
                return False
            pos = 0
        else:
            pos += 1
    if len(l1) != len(l2):
        number1, l1 = _getNumberAt(l1, pos)
        number2, l2 = _getNumberAt(l2, pos)
        try:
            if abs(float(number1) - float(number2)) > tolerance:
                return False
        except ValueError:
            return False
    return True

def fpfilter(fromlines, tolines, outlines, tolerance):
    s = difflib.SequenceMatcher(None, fromlines, tolines)
    for tag, i1, i2, j1, j2 in s.get_opcodes():
        if tag == "replace" and i2 - i1 == j2 - j1:
            for fromline, toline in zip(fromlines[i1:i2], tolines[j1:j2]):
                if _fpequal(fromline, toline, tolerance):
                    outlines.write(fromline)
                else:
                    outlines.write(toline)
        else:
            outlines.writelines(tolines[j1:j2])

def main():
    parser = optparse.OptionParser("usage: %prog [options] fromfile tofile")
    parser.add_option("-t", "--tolerance", type="float", default=0.0101,
                      help='Set floating point tolerance (default 0.0101)')
    parser.add_option("-o", "--output",
                      help='Write filtered tofile to use external diff')
    (options, args) = parser.parse_args()
    if len(args) == 0:
        parser.print_help()
        sys.exit(1)
    if len(args) != 2:
        parser.error("need to specify both a fromfile and tofile")
    fromfile, tofile = args
    fromlines = open(fromfile, 'U').readlines()
    tolines = open(tofile, 'U').readlines()
    if options.output:
        out = open(options.output, 'w')
        fpfilter(fromlines, tolines, out, options.tolerance)
        out.close()
    else:
        out = StringIO.StringIO()
        fpfilter(fromlines, tolines, out, options.tolerance)
        out.seek(0)
        tolines = out.readlines()
        sys.stdout.writelines(difflib.unified_diff(fromlines, tolines, fromfile, tofile))

if __name__ == '__main__':
    main()
