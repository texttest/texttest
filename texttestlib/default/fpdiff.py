import sys
import difflib


def _getNumberAt(l, pos):
    start = pos
    eSeen = False
    dotSeen = False
    while start > 0 and l[start-1] in "1234567890.eE-+":
        if l[start-1] in "eE":
            if eSeen:
                break
            eSeen = True
        if l[start-1] == ".":
            if dotSeen:
                break
            dotSeen = True
        start -= 1
    end = pos
    while end < len(l) and l[end] in "1234567890.eE-+":
        if l[end] in "eE":
            if eSeen:
                break
            eSeen = True
        if l[end] == ".":
            if dotSeen:
                break
            dotSeen = True
        end += 1
    return l[start:end], l[end:]


def _fpequalAtPos(l1, l2, tolerance, relTolerance, pos):
    number1, l1 = _getNumberAt(l1, pos)
    number2, l2 = _getNumberAt(l2, pos)
    try:
        equal = False
        deviation = abs(float(number1) - float(number2))
        if tolerance != None and deviation <= tolerance:
            equal = True
        elif relTolerance != None:
            referenceValue = abs(float(number1))
            if referenceValue == 0:
                equal = (deviation == 0)
            elif deviation / referenceValue <= relTolerance:
                equal = True
    except ValueError:
        pass
    return equal, l1, l2


def _fpequal(l1, l2, tolerance, relTolerance):
    pos = 0
    while pos < min(len(l1), len(l2)):
        if l1[pos] != l2[pos]:
            equal, l1, l2 = _fpequalAtPos(l1, l2, tolerance, relTolerance, pos)
            if not equal:
                return False
            pos = 0
        else:
            pos += 1
    if len(l1) == len(l2):
        return True
    equal, l1, l2 = _fpequalAtPos(l1, l2, tolerance, relTolerance, pos)
    return equal and l1 == "" and l2 == ""


def _cmpLines(fromlines, tolines, outlines, tolerance, relTolerance, split):
    for fromline, toline in zip(fromlines, tolines):
        equal = True
        if fromline != toline:
            if split != '':
                fromSplit = fromline.split(split)
                toSplit = toline.split(split)
                if len(fromSplit) == len(toSplit):
                    for f, t in zip(fromSplit, toSplit):
                        f, t = f.strip(), t.strip()
                        if f != t and not _fpequal(f, t, tolerance, relTolerance):
                            equal = False
                            break
                else:
                    equal = False
            elif not _fpequal(fromline, toline, tolerance, relTolerance):
                equal = False
        if equal:
            outlines.write(fromline)
        else:
            outlines.write(toline)


def fpfilter(fromlines, tolines, outlines, tolerance, relTolerance=None, useDifflib=False, split=''):
    if split == 'None':
        split = None
    if not useDifflib:
        _cmpLines(fromlines, tolines, outlines, tolerance, relTolerance, split)
        outlines.writelines(tolines[len(fromlines):])
        return
    s = difflib.SequenceMatcher(None, fromlines, tolines)
    for tag, i1, i2, j1, j2 in s.get_opcodes():
        if tag == "replace" and i2 - i1 == j2 - j1:
            _cmpLines(fromlines[i1:i2], tolines[j1:j2], outlines, tolerance, relTolerance, split)
        else:
            outlines.writelines(tolines[j1:j2])
