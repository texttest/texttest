from gi.repository import Gtk, Gdk

# We register our own stock items here.
# The code is inspired by the example
# in the pygtk FAQ, item 9.5.


def register(window):
    # needs review, StockItems are deprecated MB 2018-12-05
    loadItem = Gtk.StockItem()
    loadItem.stock_id = 'texttest-stock-load'
    loadItem.label = '_Load'
    loadItem.modifier = Gdk.ModifierType.CONTROL_MASK
    loadItem.keyval = Gdk.keyval_from_name('L')
    creditsItem = Gtk.StockItem()
    creditsItem.stock_id = 'texttest-stock-credits'
    creditsItem.label = 'C_redits'

    # We're too lazy to make our own icons,
    # so we use regular stock icons.
    aliases = [('texttest-stock-load', Gtk.STOCK_OPEN),
               ('texttest-stock-credits', Gtk.STOCK_ABOUT)]

    Gtk.stock_add([loadItem, creditsItem])
    factory = Gtk.IconFactory()
    factory.add_default()
    style = window.get_style()
    for new_stock, alias in aliases:
        icon_set = style.lookup_icon_set(alias)
        factory.add(new_stock, icon_set)
