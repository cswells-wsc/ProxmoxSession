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
│   ├── config_editor.py     # Entry point for config editor (python -m proxmox_session.config_editor)
│   ├── auth.py              # Proxmox authentication (user/pass, API token, TOTP)
│   ├── api.py               # Proxmox API helpers (VM list, start/stop, SPICE ticket)
│   ├── spice.py             # SPICE .vv file building, DNS resolution, remote-viewer launch
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── app.py           # QApplication wrapper, QSS dark/light themes
│   │   ├── login_window.py  # Login screen (cluster selector, TOTP, auto-login)
│   │   ├── vm_list_window.py# VM list with search, status badges, auto-refresh
│   │   ├── config_window.py # GUI config editor (tabbed, one tab per host)
│   │   └── dialogs.py       # Reusable message/error/confirm dialogs
│   └── utils/
│       ├── __init__.py
│       └── system.py        # remote-viewer detection (ftype on Windows, which on Linux)
├── install/
│   ├── install.bat          # Windows: pip install, virt-viewer, shortcuts, config
│   ├── check.py             # Windows: health check (install.bat --check)
│   ├── install.sh           # Linux: system install (package + session files)
│   ├── proxmox-session.desktop  # X session definition → /usr/share/xsessions/
│   └── proxmox-session.sh   # Session launcher (openbox + python -m proxmox_session)
├── tests/
│   └── test_spice_vv.py     # 17-test suite for .vv file build/write/cleanup flow
├── docs/
│   ├── index.md
│   ├── installation.md
│   ├── configuration.md
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

**Windows system requirements:**
- Python 3.10+
- virt-viewer (installed via `install.bat` using winget)

**Linux system requirements:**
- `python3-pyqt6` or `pip install PyQt6`
- `virt-viewer` (provides `remote-viewer`)
- `openbox` (minimal WM for session type)

---

## Feature Status

| Feature | PVE-VDIClient | ProxmoxSession | Notes |
|---|---|---|---|
| Proxmox auth — user/pass | ✅ | ✅ | Tested |
| Proxmox auth — API token | ✅ | ✅ | Auto-login when all 3 token fields set |
| Proxmox auth — TOTP | ✅ | ✅ | Basic OTP field at login |
| Multiple cluster support | ✅ | ✅ | Tab per cluster in config editor |
| SPICE via remote-viewer | ✅ | ✅ | Temp .vv file (stdin unreliable on Windows) |
| SpiceProxy redirect | ✅ | ✅ | GUI editor + auto DNS→IP resolution |
| pvespiceproxy: token support | ✅ | ✅ | Token passed through unchanged (not resolved) |
| Kiosk mode | ✅ | ✅ | Linux only (Windows always shows title bar) |
| Linux session type (.desktop) | ❌ | ✅ | Written; not yet tested on Linux |
| Windows installer | ❌ | ✅ | install.bat — tested and working |
| Install health check | ❌ | ✅ | install.bat --check |
| GUI config editor | ❌ | ✅ | Tabbed; Start Menu shortcut installed |
| PyQt6 modern UI | ❌ | ✅ | Dark/light/system themes |
| VM search/filter | ❌ | ✅ | Real-time filter by name or VMID |
| VM status color badges | ❌ | ✅ | Running/Stopped/Suspended/Paused |
| Auto-refresh VM list | ❌ | ✅ | 5-second QTimer |
| Auto-reconnect after session | ❌ | ✅ | Returns to VM list after viewer exits |
| INI debug mode | ❌ | ✅ | Shows .vv contents before launch |
| File logging | ❌ | ✅ | %APPDATA%\VDIClient\proxmox_session.log |
| Dark/light mode (QSS) | ❌ | ✅ | Catppuccin-inspired themes |
| INI backward-compatibility | — | ✅ | Existing vdiclient.ini files work unchanged |
| TOTP countdown timer | ❌ | ❌ | Not yet implemented |
| USB redirection (per-session toggle) | ❌ | ❌ | Workaround: AdditionalParameters in config |
| Multi-monitor / display selector | ❌ | ❌ | Not yet implemented |
| Connection profiles (last VM per user) | ❌ | ❌ | Not yet implemented |

---

## Remaining Work

### Not Yet Implemented
1. **TOTP countdown timer** — show a live 30-second countdown next to the OTP field in the login screen so users know when to request a new code
2. **USB redirection toggle** — per-connection checkbox dialog before launching remote-viewer (currently USB must be enabled globally via `[AdditionalParameters]` in config)
3. **Multi-monitor / display selector** — let the user pick which monitor to use in fullscreen before connecting
4. **Connection profiles** — remember the last connected VMID per username so repeat users skip the VM list

### Not Yet Tested on Linux
5. **Linux session type** — `install/proxmox-session.desktop`, `install/proxmox-session.sh`, and `install/install.sh` are written but the full session type flow (GDM → openbox → app) has not been tested on a real Linux machine

---

## SPICE Connection Notes

Proxmox returns a SPICE ticket with:
- `host` = `pvespiceproxy:<token>:<vmid>:<node>::<hash>` — a routing token, not a DNS name
- `proxy` = `http://<node-fqdn>:3128` — the SPICE proxy address

If the node FQDN doesn't resolve on the client machine (common in LAN setups), add a
`[SpiceProxyRedirect]` entry in the config or via the **SPICE Proxy** tab in the config editor:

```ini
[SpiceProxyRedirect]
node-fqdn.domain.com:3128 = 192.168.1.x:3128
```

---

## Windows Session — Quick Start

```
install\install.bat          # first-time install
install\install.bat --check  # verify health
Start Menu > ProxmoxSession  # launch app
Start Menu > ProxmoxSession Config  # edit config
```

Log file: `%APPDATA%\VDIClient\proxmox_session.log`

---

## Linux Session Type — Quick Start

```bash
sudo ./install/install.sh
sudo cp vdiclient.ini.example /etc/vdiclient/vdiclient.ini
sudo nano /etc/vdiclient/vdiclient.ini
# Log out → select "Proxmox VDI Session" at login screen
```

Config locations (checked in order):
1. `~/.config/VDIClient/vdiclient.ini`
2. `/etc/vdiclient/vdiclient.ini`
3. `/usr/local/etc/vdiclient/vdiclient.ini`
