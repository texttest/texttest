
import gtk, gobject

# Semi-ugly hack to get hold of the button in a treeview header (treeviewcolumn)
# See e.g. http://www.tenslashsix.com/?p=109 or http://piman.livejournal.com/361173.html
# or google on e.g. 'gtk treeview header popup menu' for more info.

# The idea is to make this look like a TreeViewColumn and also a widget that supports
# e.g. right-clicking
class ButtonedTreeViewColumn(gtk.TreeViewColumn):
    def __init__(self, title="", *args, **kwargs):
        super(ButtonedTreeViewColumn, self).__init__(None, *args, **kwargs)
        label = gtk.Label(title)
        self.set_widget(label)
        label.show()
    
    def get_button(self):
        return self.get_widget().get_ancestor(gtk.Button)

    def get_name(self):
        return "GtkButtonedTreeViewColumn"

    def get_title(self):
        return self.get_widget().get_text()

    def connect(self, *args):
        return self.get_button().connect(*args)

    def disconnect(self, *args):
        return self.get_button().disconnect(*args)

    def emit(self, *args):
        return self.get_button().emit(*args)

    def __getattr__(self, name):
        return getattr(self.get_button(), name)

    def get_property(self, *args):
        try:
            return gtk.TreeViewColumn.get_property(self, *args)
        except TypeError:
            return self.get_button().get_property(*args)
        
