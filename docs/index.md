# ProxmoxSession Documentation

Proxmox VDI Session is a modern, PyQt6-based VDI client that connects to Proxmox VE clusters and launches SPICE desktop sessions. It is designed to be installed as a **Linux desktop session type** — users select it at the GDM/LightDM login screen and boot directly into their virtual desktop, with no full desktop environment required.

---

## Documentation Index

| Document | Description |
|---|---|
| [Installation Guide](installation.md) | Full installation instructions for Debian/Ubuntu and Fedora/RHEL |
| [Configuration Reference](configuration.md) | All config file options explained with examples |
| [Managing the Application](management.md) | User management, Proxmox permissions, updates, and uninstalling |
| [USB Redirection](usb-redirection.md) | Proxmox VM setup, guest drivers, and per-session USB toggle |
| [Troubleshooting](troubleshooting.md) | Common problems and how to fix them |

---

## Quick Start

```bash
# 1. Clone / copy the project
cd /opt
git clone https://github.com/cswells-wsc/ProxmoxSession.git ProxmoxSession
cd ProxmoxSession

# 2. Install
sudo ./install/install.sh

# 3. Configure
sudo nano /etc/vdiclient/vdiclient.ini

# 4. Log out → select "Proxmox VDI Session" at login screen
```

---

## Architecture Overview

```
Login Screen (GDM/LightDM)
        │
        ▼  user selects "Proxmox VDI Session"
proxmox-session.sh
        │  starts openbox (minimal WM)
        │  starts python3 -m proxmox_session
        ▼
┌─────────────────────────────┐
│       Login Window          │  ← username / password / TOTP
│  (proxmox_session/ui/)      │
└────────────┬────────────────┘
             │  authenticated via Proxmox API (proxmoxer)
             ▼
┌─────────────────────────────┐
│       VM List Window        │  ← search, status badges, connect
│  (proxmox_session/ui/)      │
└────────────┬────────────────┘
             │  user clicks Connect
             ▼
      remote-viewer (virt-viewer)
      launches SPICE session
             │
             │  user disconnects
             ▼
       VM List Window
       (auto-reconnect)
```
