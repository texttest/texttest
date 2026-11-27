#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [ -n "${MSYSTEM:-}" ] && [ -d "/${MSYSTEM,,}/bin" ]; then
    export PATH="/${MSYSTEM,,}/bin:/usr/bin:$PATH"
fi

MSYS2_ARCH="${MSYS2_ARCH:-ucrt-x86_64}"
PKG_PREFIX="${MINGW_PACKAGE_PREFIX:-mingw-w64-${MSYS2_ARCH}}"
MELD_DIR="${MELD_DIR:-meld}"
ADWAITA_DIR="${ADWAITA_DIR:-adwaita-icon-theme}"
ICONS_DEST="${ICONS_DEST:-/usr/share/icons}"

pacman --noconfirm -S --refresh --needed --overwrite '*' \
    git \
    patch \
    glib2-devel \
    intltool \
    "${PKG_PREFIX}-diffutils" \
    "${PKG_PREFIX}-python-setuptools" \
    "${PKG_PREFIX}-python-cx-freeze" \
    "${PKG_PREFIX}-python-gobject" \
    "${PKG_PREFIX}-python-pytest" \
    "${PKG_PREFIX}-python-distro" \
    "${PKG_PREFIX}-python-matplotlib" \
    "${PKG_PREFIX}-python-certifi" \
    "${PKG_PREFIX}-python-psutil" \
    "${PKG_PREFIX}-python-yaml" \
    "${PKG_PREFIX}-gtksourceview4" \
    "${PKG_PREFIX}-gsettings-desktop-schemas"

if [ ! -d "$MELD_DIR" ]; then
    git clone -b 3.22.0 --depth 1 https://gitlab.gnome.org/GNOME/meld.git "$MELD_DIR"
fi

if [ ! -d "$ADWAITA_DIR" ]; then
    git clone -b 41.0 --depth 1 https://github.com/GNOME/adwaita-icon-theme.git "$ADWAITA_DIR"
fi

mkdir -p "$ICONS_DEST"
cp -aL "$ADWAITA_DIR/Adwaita" "$ICONS_DEST"

patch -p0 -R < meld_build_helpers.patch
# Fix Python 3.13+ compatibility: pipes module was removed in Python 3.13
sed -i 's/^import pipes$/import shlex  # pipes was removed in Python 3.13/' "$MELD_DIR/meld/melddoc.py"
sed -i 's/pipes\.quote/shlex.quote/g' "$MELD_DIR/meld/melddoc.py"

cp -a bin texttestlib setup_win32.py "$MELD_DIR"
cp wininstall/*.ico "$MELD_DIR/data/icons"

gdk-pixbuf-query-loaders --update-cache

(
    cd "$MELD_DIR"
    glib-compile-schemas data
    python3 setup_win32.py bdist_dumb bdist_msi
)

rm -rf dist
mv "$MELD_DIR/dist" dist
