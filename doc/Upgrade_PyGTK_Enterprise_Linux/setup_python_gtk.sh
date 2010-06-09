#!/bin/sh

# Pick out a compatible Python and/or PyGTK that are installed in non-standard places.
# Uncomment and modify the two lines below to identify the places correctly

# (Jeppesen-Göteborg values)
# PYTHONBIN=/usr/bin/python2.6
# PYGTK_INSTALL_DIR=/usr/local/tt-env/gtk2.18

get_python()
{
    if [ -f "$PYTHONBIN" ]; then
        eval "$1=$PYTHONBIN"
    else
        eval "$1=python"
    fi
}

prepend_path_element()
{
    echo $3 | grep -q $1
    if [ $? = 1 ]; then
        eval $2=$1:$3
    fi
}

get_python PYTHON_TO_RUN
prepend_path_element $PYGTK_INSTALL_DIR/lib LD_LIBRARY_PATH $LD_LIBRARY_PATH
prepend_path_element $PYGTK_INSTALL_DIR/lib64/python2.6/site-packages/gtk-2.0:$PYGTK_INSTALL_DIR/lib64/python2.6/site-packages PYTHONPATH $PYTHONPATH
export LD_LIBRARY_PATH PYTHONPATH

export GDK_PIXBUF_MODULE_FILE=$PYGTK_INSTALL_DIR/etc/gtk-2.0/gdk-pixbuf.loaders
export GTK2_RC_FILES=$PYGTK_INSTALL_DIR/etc/gtk-2.0/gtkrc:$HOME/.gtkrc-2.0
export GTK_PATH=$PYGTK_INSTALL_DIR/lib/gtk-2.0
export GTK_DATA_PREFIX=$PYGTK_INSTALL_DIR
export XDG_DATA_DIRS=$PYGTK_INSTALL_DIR/share/:/usr/share
export PYTHON_TO_RUN

