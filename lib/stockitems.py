#!/usr/bin/env python

import gtk

# We register our own stock items here.
# The code is inspired by the example
# in the pygtk FAQ, item 9.5.
def register(window):
    items = [('texttest-stock-load', '_Load', gtk.gdk.CONTROL_MASK, gtk.gdk.keyval_from_name('L'), None),
             ('texttest-stock-credits', 'C_redits', 0, 0, None)]
    
    # We're too lazy to make our own icons, 
    # so we use regular stock icons.
    aliases = [('texttest-stock-load', gtk.STOCK_OPEN),
               ('texttest-stock-credits', gtk.STOCK_ABOUT)]
    
    gtk.stock_add(items)
    factory = gtk.IconFactory()
    factory.add_default()
    style= window.get_style()
    for new_stock, alias in aliases:
        icon_set = style.lookup_icon_set(alias)
        factory.add(new_stock, icon_set)
