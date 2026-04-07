#!/bin/bash
# Proxmox VDI Session — system installer
# Run as root: sudo ./install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo "==> Installing system dependencies..."
if command -v apt-get &>/dev/null; then
    apt-get install -y python3-pip python3-pyqt6 virt-viewer openbox
elif command -v dnf &>/dev/null; then
    dnf install -y python3-pip python3-qt6 virt-viewer openbox
else
    echo "WARNING: Unknown package manager — install python3-pyqt6, virt-viewer, and openbox manually."
fi

echo "==> Installing Python package..."
pip3 install --break-system-packages "$REPO_DIR"

echo "==> Installing session launcher..."
install -m 755 "$SCRIPT_DIR/proxmox-session.sh" /usr/local/bin/proxmox-session.sh

echo "==> Installing X session entry..."
install -m 644 "$SCRIPT_DIR/proxmox-session.desktop" /usr/share/xsessions/proxmox-session.desktop

echo "==> Creating default config directory..."
mkdir -p /etc/vdiclient
if [ ! -f /etc/vdiclient/vdiclient.ini ]; then
    install -m 644 "$REPO_DIR/vdiclient.ini.example" /etc/vdiclient/vdiclient.ini
    echo "    Default config written to /etc/vdiclient/vdiclient.ini — edit before use!"
else
    echo "    /etc/vdiclient/vdiclient.ini already exists, skipping."
fi

echo ""
echo "Installation complete."
echo "Edit /etc/vdiclient/vdiclient.ini, then log out and select 'Proxmox VDI Session' at the login screen."
