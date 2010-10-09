
import gtk

# Semi-ugly hack to get hold of the button in a treeview header (treeviewcolumn)
# See e.g. http://www.tenslashsix.com/?p=109 or http://piman.livejournal.com/361173.html
# or google on e.g. 'gtk treeview header popup menu' for more info.
class ButtonedTreeViewColumn(gtk.TreeViewColumn):
    def __init__(self, title="", *args, **kwargs):
        super(ButtonedTreeViewColumn, self).__init__(None, *args, **kwargs)
        label = gtk.Label(title)
        self.set_widget(label)
        label.show()

    def get_button(self):
        return self.get_widget().get_ancestor(gtk.Button)

    def get_title(self):
        return self.get_widget().get_text()
