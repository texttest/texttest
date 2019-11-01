#!/usr/bin/env python2
import sys, difflib, re


def _getNumberAt(l, pos):
    start = pos
    eSeen = False
    dotSeen = False
    while start > 0 and l[start-1] in "1234567890.eEdD-+":
        if l[start-1] in "eEdD":
            if eSeen:
                break
            eSeen = True
        if l[start-1] == ".":
            if dotSeen:
                break
            dotSeen = True
        start -= 1
    end = pos
    while end < len(l) and l[end] in "1234567890.eEdD-+":
        if l[end] in "eEdD":
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

    equal = _fpTestForTolerance(number1, number2, tolerance, relTolerance)

    return equal, l1, l2


def _fpTestForTolerance(w1, w2, tolerance, relTolerance):
    try:
        equal = False
        w1 = w1.replace("d","e",1)
        w1 = w1.replace("D","e",1)
        w2 = w2.replace("d","e",1)
        w2 = w2.replace("D","e",1)
        deviation = abs(float(w1) - float(w2))
        if tolerance != None and deviation <= tolerance:
            equal = True
        elif relTolerance != None:
            referenceValue = abs(float(w1))
            if referenceValue == 0:
                equal = (deviation == 0)
            elif deviation / referenceValue <= relTolerance:
                equal = True
    except ValueError:
        pass
    return equal


def _fpequal(l1, l2, tolerance, relTolerance, model=0):
    if model == 0:
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
        else:
            return _fpequalAtPos(l1, l2, tolerance, relTolerance, pos)[0]
    elif model == 1:
        regNumber = r'[-+]? (?: (?: \d* \. \d+ ) | (?: \d+ \.? ) )(?: [EeDd] [+-]? \d+ ) ?'
        numbers1 = re.findall(regNumber, l1, re.VERBOSE)
        numbers2 = re.findall(regNumber, l2, re.VERBOSE)
        isEqual = True
        if len(numbers1) != len(numbers2):
            isEqual = False
        else:
            for n1, n2 in zip(numbers1, numbers2):
                isEqual = _fpTestForTolerance(n1, n2, tolerance, relTolerance)
                if not isEqual:
                    break

        return isEqual


def fpfilter(fromlines, tolines, outlines, tolerance, relTolerance=None, model=0):
    if model == 0:
        s = difflib.SequenceMatcher(None, fromlines, tolines)
        for tag, i1, i2, j1, j2 in s.get_opcodes():

            if tag == "replace" and i2 - i1 == j2 - j1:
                for fromline, toline in zip(fromlines[i1:i2], tolines[j1:j2]):
                    if _fpequal(fromline, toline, tolerance, relTolerance, model=0):
                        outlines.write(fromline)
                    else:
                        outlines.write(toline)
            else:
                outlines.writelines(tolines[j1:j2])
    elif model == 1:
        if len(fromlines) == len(tolines):
            for fromline, toline in zip(fromlines, tolines):
                if _fpequal(fromline, toline, tolerance, relTolerance, model=1):
                    outlines.write(fromline)
                else:
                    outlines.write(toline)
        else:
            outlines.writelines(tolines)

