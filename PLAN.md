# ProxmoxSession — Modernized Proxmox VDI Client

A modern, installable VDI client for Proxmox VE. Runs as a normal windowed app on **Windows**
and as a full Linux desktop **session type** (selectable at GDM/LightDM login screen).

Based on [PVE-VDIClient](https://github.com/joshpatten/PVE-VDIClient) — rewritten with PyQt6,
clean multi-module architecture, and new features.

---

## Architecture

```
ProxmoxSession/
├── proxmox_session/
│   ├── __init__.py
│   ├── __main__.py          # Enables: python -m proxmox_session
│   ├── main.py              # Entry point, argparse, logging, app loop
│   ├── config.py            # INI config loader (AppConfig / HostConfig dataclasses)
│   ├── config_editor.py     # Entry point for config editor
│   ├── auth.py              # Proxmox authentication (user/pass, API token, TOTP)
│   ├── api.py               # Proxmox API helpers (VM list, start/stop, SPICE ticket)
│   ├── spice.py             # SPICE .vv file building, DNS resolution, remote-viewer launch
│   ├── access.py            # Proxmox API helpers: groups/roles/ACLs/users
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── app.py           # QApplication wrapper, QSS dark/light themes
│   │   ├── login_window.py  # Login screen (cluster selector, TOTP, auto-login)
│   │   ├── vm_list_window.py# VM list with search, status badges, auto-refresh
│   │   ├── config_window.py # GUI config editor (tabbed, one tab per host)
│   │   ├── dialogs.py       # Dialogs: error, info, confirm, ConnectDialog
│   │   ├── setup_wizard.py  # 7-page QWizard: first-time Proxmox setup
│   │   └── manage_window.py # Superadmin management: groups and users
│   └── utils/
│       ├── __init__.py
│       └── system.py        # remote-viewer detection (ftype on Windows, which on Linux)
├── install/
│   ├── install.bat                      # Windows: pip install, virt-viewer, shortcuts, config
│   ├── check.py                         # Windows: health check (install.bat --check)
│   ├── install.sh                       # Linux: system install (package + session files)
│   ├── proxmox-session.desktop          # X session definition → /usr/share/xsessions/
│   ├── proxmox-session.sh               # Session launcher (network wait + openbox + app)
│   ├── proxmox-session-app.desktop      # App menu shortcut → /usr/share/applications/
│   ├── proxmox-session-config.desktop   # Config editor menu shortcut (runs via pkexec)
│   └── proxmox-session-config-admin.sh  # pkexec elevation wrapper for config editor
├── tests/
│   ├── test_spice_vv.py     # 17-test suite for .vv file build/write/cleanup flow
│   └── test_access.py       # 26-test suite for access.py helpers (mocked API)
├── docs/
│   ├── index.md
│   ├── installation.md
│   ├── configuration.md
│   ├── usb-redirection.md
│   ├── setup-wizard.md
│   ├── management.md
│   └── troubleshooting.md
├── requirements.txt
├── pyproject.toml
└── vdiclient.ini.example    # Config reference (backward-compatible with PVE-VDIClient)
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `proxmoxer[https]` | Proxmox VE REST API |
| `requests` | HTTP config loading |
| `PyQt6` | Modern GUI framework (replaces PySimpleGUI) |

**Windows system requirements:** Python 3.10+, virt-viewer (installed via winget)

**Linux system requirements:** `python3-pyqt6`, `virt-viewer`, `openbox`

---

## Feature Status

| Feature | PVE-VDIClient | ProxmoxSession | Notes |
|---|---|---|---|
| Proxmox auth — user/pass | ✅ | ✅ | Tested |
| Proxmox auth — API token | ✅ | ✅ | Auto-login when all 3 token fields set |
| Proxmox auth — TOTP | ✅ | ✅ | Basic OTP field at login |
| Multiple cluster support | ✅ | ✅ | Tab per cluster in config editor; dropdown when >1 cluster |
| SPICE via remote-viewer | ✅ | ✅ | Temp .vv file — tested on Windows and Linux |
| SpiceProxy redirect | ✅ | ✅ | GUI editor + auto DNS→IP resolution |
| pvespiceproxy: token support | ✅ | ✅ | Token passed through unchanged |
| Kiosk mode | ✅ | ✅ | Linux only |
| Linux session type (.desktop) | ❌ | ✅ | Tested on Debian 13; network wait on boot |
| Linux app menu shortcuts | ❌ | ✅ | ProxmoxSession + ProxmoxSession Config |
| Linux config editor elevation | ❌ | ✅ | pkexec prompt; PermissionError fallback |
| Windows installer | ❌ | ✅ | install.bat — tested |
| Install health check | ❌ | ✅ | install.bat --check |
| GUI config editor | ❌ | ✅ | Tabbed; shortcuts on both platforms |
| PyQt6 modern UI | ❌ | ✅ | Dark/light/system themes |
| VM search/filter | ❌ | ✅ | Real-time filter by name or VMID |
| VM status color badges | ❌ | ✅ | Running/Stopped/Suspended/Paused |
| Auto-refresh VM list | ❌ | ✅ | 5-second QTimer |
| Auto-reconnect after session | ❌ | ✅ | Returns to VM list after viewer exits |
| USB redirection toggle | ❌ | ✅ | Per-session dialog; remembered per VM |
| INI debug mode | ❌ | ✅ | Shows .vv contents before launch |
| File logging | ❌ | ✅ | 0600 permissions on Linux |
| Dark/light mode (QSS) | ❌ | ✅ | Catppuccin-inspired themes |
| Git repo / one-line install | ❌ | ✅ | github.com/cswells-wsc/ProxmoxSession |
| Security hardening | ❌ | ✅ | Credential redaction, file permissions, no shell injection |
| INI backward-compatibility | — | ✅ | Existing vdiclient.ini files work unchanged |
| Proxmox Setup Wizard | ❌ | ✅ | 7-page wizard; groups/roles/ACLs/users; launched from Host tab |
| Superadmin Manage window | ❌ | ✅ | Groups + Users tabs; scoped to proxmoxsession_* only |
| TOTP countdown timer | ❌ | ❌ | Not yet implemented |
| Multi-monitor / display selector | ❌ | ❌ | Not yet implemented |
| Connection profiles (last VM per user) | ❌ | ❌ | Not yet implemented |

---

## Remaining Work

1. **TOTP countdown timer** — live 30-second countdown next to the OTP field at login
2. **Multi-monitor / display selector** — pick which monitor to use before connecting
3. **Connection profiles** — remember the last connected VMID per username

---

## SPICE Connection Notes

Proxmox returns a SPICE ticket with:
- `host` = `pvespiceproxy:<token>:<vmid>:<node>::<hash>` — routing token, not a DNS name
- `proxy` = `http://<node-fqdn>:3128` — the SPICE proxy address

If the node FQDN doesn't resolve on the client (common in LAN setups), add a redirect:

```ini
[SpiceProxyRedirect]
node-fqdn.domain.com:3128 = 192.168.1.x:3128
```

---

## Windows — Quick Start

```
install\install.bat          # first-time install
install\install.bat --check  # verify health
Start Menu > ProxmoxSession  # launch app
Start Menu > ProxmoxSession Config  # edit config
```

Log file: `%APPDATA%\VDIClient\proxmox_session.log`

---

## Linux — Quick Start

```bash
# Install (one line)
sudo apt install -y git && sudo git clone https://github.com/cswells-wsc/ProxmoxSession.git /opt/ProxmoxSession && sudo bash /opt/ProxmoxSession/install/install.sh

# Configure
sudo nano /etc/vdiclient/vdiclient.ini

# Update
cd /opt/ProxmoxSession && sudo git pull && sudo bash install/install.sh
```

Config locations (checked in order):
1. `~/.config/VDIClient/vdiclient.ini`
2. `/etc/vdiclient/vdiclient.ini`
3. `/usr/local/etc/vdiclient/vdiclient.ini`
