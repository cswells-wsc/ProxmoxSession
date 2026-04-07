# ProxmoxSession

A modern Proxmox VE VDI client with a PyQt6 GUI. Connects to your Proxmox cluster, lists VMs, and launches SPICE sessions via `remote-viewer`.

- **Windows** — runs as a normal desktop app with a Start Menu shortcut
- **Linux** — installs as a login-screen session type (select "Proxmox VDI Session" at GDM/LightDM)

Based on [PVE-VDIClient](https://github.com/joshpatten/PVE-VDIClient), rewritten with PyQt6 and a clean multi-module architecture.

---

## Features

- Multi-cluster support with per-cluster authentication settings
- SPICE sessions via `remote-viewer` (temp `.vv` file — reliable on both Windows and Linux)
- SpiceProxy redirect — rewrite unresolvable node FQDNs to IPs
- Auto DNS resolution of proxy hostnames
- VM search/filter, color-coded status badges, 5-second auto-refresh
- Dark / light / system themes (QSS)
- GUI config editor with one tab per host cluster
- API token auto-login
- TOTP / OTP support
- Kiosk mode (Linux only)
- File logging to `%APPDATA%\VDIClient\proxmox_session.log` (Windows) or `~/.local/share/VDIClient/` (Linux)

---

## Windows — Quick Start

**Requirements:** Python 3.10+, internet access (winget installs virt-viewer)

```
git clone https://github.com/cswells-wsc/ProxmoxSession.git
cd ProxmoxSession
install\install.bat
```

The installer will:
1. Install the Python package (`pip install -e .`)
2. Install virt-viewer via winget
3. Copy `vdiclient.ini.example` → `%APPDATA%\VDIClient\vdiclient.ini`
4. Create Start Menu shortcuts for the app and config editor

Edit `%APPDATA%\VDIClient\vdiclient.ini` with your Proxmox server details, then launch from **Start Menu → ProxmoxSession**.

**Verify the installation at any time:**
```
install\install.bat --check
```

---

## Linux — Quick Start

**Requirements:** Python 3.10+, `python3-pyqt6`, `virt-viewer`, `openbox`

```bash
git clone https://github.com/cswells-wsc/ProxmoxSession.git
cd ProxmoxSession
sudo ./install/install.sh
```

The installer will:
1. Install system dependencies (`apt`/`dnf`)
2. Install the Python package
3. Register `proxmox-session.desktop` in `/usr/share/xsessions/`
4. Copy `vdiclient.ini.example` → `/etc/vdiclient/vdiclient.ini`

Edit `/etc/vdiclient/vdiclient.ini`, log out, and select **Proxmox VDI Session** at the login screen.

---

## Configuration

Copy `vdiclient.ini.example` to the appropriate location and edit it:

| Platform | Config path |
|---|---|
| Windows | `%APPDATA%\VDIClient\vdiclient.ini` |
| Linux (user) | `~/.config/VDIClient/vdiclient.ini` |
| Linux (system) | `/etc/vdiclient/vdiclient.ini` |

**Minimal config:**

```ini
[General]
title = VDI Login
theme = system

[Hosts.MyCluster]
hostpool = {
    "192.168.1.50" : 8006
}
auth_backend = pve
tls_verify = false
```

**If your SPICE proxy uses a hostname that doesn't resolve on the client**, add a redirect:

```ini
[SpiceProxyRedirect]
node.internal.domain:3128 = 192.168.1.50:3128
```

See [`vdiclient.ini.example`](vdiclient.ini.example) and [`docs/configuration.md`](docs/configuration.md) for the full reference.

---

## Running

```bash
# Main app
python -m proxmox_session

# Config editor
python -m proxmox_session.config_editor

# Debug mode (verbose logging)
python -m proxmox_session --debug
```

---

## Project Layout

```
proxmox_session/       # Python package
├── main.py            # Entry point
├── config.py          # INI config loader
├── auth.py            # Proxmox authentication
├── api.py             # API helpers (VM list, SPICE ticket)
├── spice.py           # .vv file builder + remote-viewer launcher
├── ui/                # PyQt6 windows and dialogs
└── utils/             # remote-viewer detection

install/
├── install.bat        # Windows installer
├── check.py           # Windows health checker (--check)
├── install.sh         # Linux system installer
├── proxmox-session.desktop   # X session definition
└── proxmox-session.sh        # Session launcher script

docs/                  # Full documentation
tests/                 # Test suite
```

---

## Docs

- [Installation](docs/installation.md)
- [Configuration](docs/configuration.md)
- [Management](docs/management.md)
- [Troubleshooting](docs/troubleshooting.md)
