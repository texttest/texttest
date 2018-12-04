#!/usr/bin/env python

from gi.repository import Gtk

# We register our own stock items here.
# The code is inspired by the example
# in the pygtk FAQ, item 9.5.
def register(window):
    items = [('texttest-stock-load', '_Load', Gdk.ModifierType.CONTROL_MASK, Gdk.keyval_from_name('L'), None),
             ('texttest-stock-credits', 'C_redits', 0, 0, None)]
    
    # We're too lazy to make our own icons, 
    # so we use regular stock icons.
    aliases = [('texttest-stock-load', Gtk.STOCK_OPEN),
               ('texttest-stock-credits', Gtk.STOCK_ABOUT)]
    
    Gtk.stock_add(items)
    factory = Gtk.IconFactory()
    factory.add_default()
    style= window.get_style()
    for new_stock, alias in aliases:
        icon_set = style.lookup_icon_set(alias)
        factory.add(new_stock, icon_set)
