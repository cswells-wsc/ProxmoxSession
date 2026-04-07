#!/bin/bash
# Proxmox VDI Session — system installer
# Run as root: sudo ./install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# ── System dependencies ────────────────────────────────────────────────────────

echo "==> Installing system dependencies..."

if command -v apt-get &>/dev/null; then
    apt-get update -q
    # python3-pyqt6 may be split into separate packages on some releases
    PYQT_PKG="python3-pyqt6"
    apt-cache show "$PYQT_PKG" &>/dev/null || PYQT_PKG="python3-pyqt6.qtwidgets python3-pyqt6.qtgui python3-pyqt6.qtcore"
    apt-get install -y python3-pip "$PYQT_PKG" virt-viewer openbox

elif command -v dnf &>/dev/null; then
    dnf install -y python3-pip python3-qt6 virt-viewer openbox

else
    echo "WARNING: Unknown package manager."
    echo "Please install: python3-pyqt6 (or python3-qt6), virt-viewer, openbox"
fi

# ── Python package ─────────────────────────────────────────────────────────────

echo "==> Installing Python package..."

# Try editable install (preferred — live code updates without reinstall)
# --break-system-packages needed on Debian 12+ / Ubuntu 23.04+
if pip3 install --break-system-packages -e "$REPO_DIR" 2>/dev/null; then
    echo "    Installed as editable package."
elif pip3 install -e "$REPO_DIR" 2>/dev/null; then
    echo "    Installed as editable package."
else
    echo "    pip3 editable install failed, trying regular install..."
    pip3 install --break-system-packages "$REPO_DIR" || pip3 install "$REPO_DIR"
fi

# ── Session launcher ───────────────────────────────────────────────────────────

echo "==> Installing session launcher..."
install -m 755 "$SCRIPT_DIR/proxmox-session.sh" /usr/local/bin/proxmox-session.sh

# ── X session entry ────────────────────────────────────────────────────────────

echo "==> Installing X session entry..."
mkdir -p /usr/share/xsessions
install -m 644 "$SCRIPT_DIR/proxmox-session.desktop" /usr/share/xsessions/proxmox-session.desktop

# ── Default config ─────────────────────────────────────────────────────────────

echo "==> Creating default config directory..."
mkdir -p /etc/vdiclient
if [ ! -f /etc/vdiclient/vdiclient.ini ]; then
    install -m 644 "$REPO_DIR/vdiclient.ini.example" /etc/vdiclient/vdiclient.ini
    echo "    Default config written to /etc/vdiclient/vdiclient.ini"
    echo "    Edit this file with your Proxmox server details before logging in!"
else
    echo "    /etc/vdiclient/vdiclient.ini already exists, skipping."
fi

# ── Verify ─────────────────────────────────────────────────────────────────────

echo ""
echo "==> Verifying installation..."
if python3 -c "import proxmox_session; print('    proxmox_session module: OK')" 2>/dev/null; then
    true
else
    echo "    WARNING: proxmox_session module not importable — check pip install output above."
fi

if python3 -c "from PyQt6.QtWidgets import QApplication; print('    PyQt6: OK')" 2>/dev/null; then
    true
else
    echo "    WARNING: PyQt6 not importable — install python3-pyqt6 manually."
fi

VIEWER=$(command -v remote-viewer 2>/dev/null || true)
if [ -n "$VIEWER" ]; then
    echo "    remote-viewer: $VIEWER"
else
    echo "    WARNING: remote-viewer not found — install virt-viewer manually."
fi

echo ""
echo "============================================"
echo " Installation complete."
echo ""
echo " Next steps:"
echo "   1. Edit /etc/vdiclient/vdiclient.ini"
echo "      with your Proxmox server details"
echo ""
echo "   2. Log out and select"
echo "      'Proxmox VDI Session' at the login screen"
echo "============================================"
