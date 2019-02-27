
# Support for our custom widgets for StoryText, which needs to know how to handle them

from gi.repository import Gtk
from storytext.gtktoolkit.simulator.treeviewevents import TreeColumnHelper
from storytext.gtktoolkit.simulator.baseevents import RightClickEvent


class TreeColumnRightClickEvent(RightClickEvent):
    def __init__(self, name, widget, argumentParseData):
        column = TreeColumnHelper.findColumn(widget, argumentParseData)
        RightClickEvent.__init__(self, name, column.get_button())

    @classmethod
    def canHandleEvent(cls, widget, signalName, argumentParseData):
        return argumentParseData and RightClickEvent.canHandleEvent(widget, signalName)

    @classmethod
    def getAssociatedSignatures(cls, widget):
        signatures = []
        for column in widget.get_columns():
            if hasattr(column, "get_button"):
                signatures.append(cls.signalName + "." + TreeColumnHelper.getColumnName(column))
        return signatures


customEventTypes = [(Gtk.TreeView, [TreeColumnRightClickEvent])]
