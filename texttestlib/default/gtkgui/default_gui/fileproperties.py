from gi.repository import Gtk, Gdk
import os
import time
import stat
from texttestlib import plugins
from .. import guiplugins
from collections import OrderedDict

# pwd and grp doesn't exist on windows ...
try:
    import pwd
    import grp
except ImportError:
    pass


class FileProperties:
    def __init__(self, path):
        self.abspath = path
        self.filename = os.path.basename(self.abspath)
        self.dir = os.path.dirname(self.abspath)
        self.status = os.lstat(self.abspath)
        self.now = int(time.time())
        self.recent = self.now - (6 * 30 * 24 * 60 * 60)  # 6 months ago

    def inqType(self):
        mode = self.status[stat.ST_MODE]
        if stat.S_ISLNK(mode):
            return "l"
        elif stat.S_ISDIR(mode):
            return "d"
        else:
            return "-"

    def inqMode(self):
        permissions = ""
        for who in "USR", "GRP", "OTH":
            for what in "R", "W", "X":
                # lookup attribute at runtime using getattr
                if self.status[stat.ST_MODE] & getattr(stat, "S_I" + what + who):
                    permissions = permissions + what.lower()
                else:
                    permissions = permissions + "-"
        return permissions

    def inqLinks(self):
        return self.status[stat.ST_NLINK]

    def inqOwner(self):
        try:
            uid = self.status[stat.ST_UID]
            return str(pwd.getpwuid(uid)[0])
        except Exception:  # KeyError, AttributeError (on Windows) possible
            return "?"

    def inqGroup(self):
        try:
            gid = self.status[stat.ST_GID]
            return str(grp.getgrgid(gid)[0])
        except Exception:  # KeyError, AttributeError (on Windows) possible
            return "?"

    def inqSize(self):
        return self.status[stat.ST_SIZE]

    def formatTime(self, timeStamp):
        # %e is more appropriate than %d below, as it fills with space
        # rather than 0, but it is not supported on Windows, it seems.
        if timeStamp < self.recent or timeStamp > self.now:
            timeFormat = "%b %d  %Y"
        else:
            timeFormat = "%b %d %H:%M"
        return time.strftime(timeFormat, time.localtime(timeStamp))

    def inqModificationTime(self):
        return self.formatTime(self.status[stat.ST_MTIME])

    # Return the *nix type format:
    # -rwxr--r--    1 mattias carm       1675 Nov 16  1998 .xinitrc_old
    def getUnixRepresentation(self):
        return (self.inqType(), self.inqMode(),
                self.inqLinks(), self.inqOwner(),
                self.inqGroup(), self.inqSize(),
                self.inqModificationTime(), self.filename)


class ShowFileProperties(guiplugins.ActionResultDialogGUI):
    def __init__(self, allApps, dynamic, *args):
        self.dynamic = dynamic
        guiplugins.ActionResultDialogGUI.__init__(self, allApps)

    def _getStockId(self):
        return "properties"

    def isActiveOnCurrent(self, *args):
        return ((not self.dynamic) or len(self.currTestSelection) == 1) and \
            len(self.currFileSelection) > 0

    def _getTitle(self):
        return "_File Properties"

    def getTooltip(self):
        return "Show properties of selected files"

    def describeTests(self):
        return str(len(self.currFileSelection)) + " files"

    def getAllProperties(self):
        errors, properties = [], []
        for file, comp in self.currFileSelection:
            if self.dynamic and comp:
                self.processFile(comp.tmpFile, properties, errors)
                self.processFile(comp.stdFile, properties, errors)
            else:
                self.processFile(file, properties, errors)

        if len(errors):
            raise plugins.TextTestError("Failed to get file properties:\n" + "\n".join(errors))

        return properties

    def processFile(self, file, properties, errors):
        if file:
            try:
                prop = FileProperties(file)
                properties.append(prop)
            except Exception as e:
                errors.append(str(e))

    # xalign = 1.0 means right aligned, 0.0 means left aligned
    def justify(self, text, xalign=0.0):
        alignment = Gtk.Alignment.new(xalign, 0.0, 0.0, 0.0)
        label = Gtk.Label(label=text)
        alignment.add(label)
        return alignment

    def addContents(self):
        dirToProperties = OrderedDict()
        props = self.getAllProperties()
        for prop in props:
            dirToProperties.setdefault(prop.dir, []).append(prop)
        vbox = self.createVBox(dirToProperties)
        self.dialog.vbox.pack_start(vbox, True, True, 0)

    def createVBox(self, dirToProperties):
        vbox = Gtk.VBox()
        for dir, properties in list(dirToProperties.items()):
            expander = Gtk.Expander()
            expander.set_label_widget(self.justify(dir))
            table = Gtk.Table(len(properties), 7)
            table.set_col_spacings(5)
            row = 0
            for prop in properties:
                values = prop.getUnixRepresentation()
                table.attach(self.justify(values[0] + values[1], 1.0), 0, 1, row, row + 1)
                table.attach(self.justify(values[2], 1.0), 1, 2, row, row + 1)
                table.attach(self.justify(values[3], 0.0), 2, 3, row, row + 1)
                table.attach(self.justify(values[4], 0.0), 3, 4, row, row + 1)
                table.attach(self.justify(values[5], 1.0), 4, 5, row, row + 1)
                table.attach(self.justify(values[6], 1.0), 5, 6, row, row + 1)
                table.attach(self.justify(prop.filename, 0.0), 6, 7, row, row + 1)
                row += 1
            hbox = Gtk.HBox()
            hbox.pack_start(table, False, False, 0)
            innerBorder = Gtk.Alignment.new(0.0, 0.0, 0.0, 0.0)
            innerBorder.set_padding(5, 0, 0, 0)
            innerBorder.add(hbox)
            expander.add(innerBorder)
            expander.set_expanded(True)
            border = Gtk.Alignment.new(0.0, 0.0, 0.0, 0.0)
            border.set_padding(5, 5, 5, 5)
            border.add(expander)
            vbox.pack_start(border, False, False, 0)
        return vbox


class CopyPathToClipboard(guiplugins.ActionGUI):
    def _getTitle(self):
        return "Copy Path To Clipboard"

    def messageAfterPerform(self):
        return "Copied full path of selected file to clipboard."

    def isActiveOnCurrent(self, *args):
        return len(self.currFileSelection) == 1

    def performOnCurrent(self):
        fileName, comp = self.currFileSelection[0]
        if comp and hasattr(comp, "tmpFile"):
            fileName = comp.tmpFile
        # Copy to both, for good measure, avoid problems with e.g. Exceed configuration
        for clipboard in [Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD), Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY)]:
            clipboard.set_text(fileName, -1)


def getInteractiveActionClasses():
    return [ShowFileProperties, CopyPathToClipboard]
