# Installation Guide

## Platform Behavior

| Platform | Window style | Session type | Config location |
|---|---|---|---|
| **Windows** | Normal window with title bar, close & minimize | Run from Start Menu or desktop shortcut | `%APPDATA%\VDIClient\vdiclient.ini` |
| **Linux** | Fullscreen / kiosk session type | Selectable at GDM/LightDM login screen | `/etc/vdiclient/vdiclient.ini` |

Both platforms use the same config file format and connect to Proxmox the same way.

---

## Requirements

### Proxmox Side (both platforms)
- Proxmox VE 7.x or 8.x
- Each VM must have a **SPICE display** configured
- Users need these permissions per VM (see [Managing the Application](management.md)):
  - `VM.PowerMgmt` · `VM.Console` · `VM.Audit`

---

## Windows Installation

### Prerequisites
- Windows 10 or 11
- Python 3.10+ — download from [python.org](https://www.python.org/downloads/)
  - Check **"Add Python to PATH"** during installation
- virt-viewer (SPICE client) — download from [virt-manager.org](https://virt-manager.org/download/)

### Automatic Install

Run the installer as **Administrator**:

```
install\install.bat
```

The installer:
- Installs Python packages (`proxmoxer`, `requests`, `PyQt6`)
- Installs virt-viewer via winget (if not already present)
- Creates `%APPDATA%\VDIClient\vdiclient.ini` from the example
- Creates a Start Menu shortcut

### Manual Windows Install

```bat
pip install proxmoxer[https] requests PyQt6

REM Create config directory
mkdir "%APPDATA%\VDIClient"
copy vdiclient.ini.example "%APPDATA%\VDIClient\vdiclient.ini"
```

### Launching on Windows

- **Start Menu:** ProxmoxSession
- **Command line (no console):** `pythonw -m proxmox_session`
- **Command line (with console for debugging):** `python -m proxmox_session`
- **With custom config:** `python -m proxmox_session --config_location C:\path\to\vdiclient.ini`

> **Note:** Both commands must be run from the `ProxmoxSession\` project folder, or the package must be installed via `pip install .`

### Windows Config Location

The app searches for config in this order:
1. `%APPDATA%\VDIClient\vdiclient.ini` ← recommended
2. `%PROGRAMFILES%\VDIClient\vdiclient.ini`
3. `%PROGRAMFILES(X86)%\VDIClient\vdiclient.ini`

Edit your config:
```bat
notepad "%APPDATA%\VDIClient\vdiclient.ini"
```

---

## Linux Installation

### Software Requirements

| Package | Purpose |
|---|---|
| `python3` (3.10+) | Runtime |
| `python3-pyqt6` | GUI framework |
| `virt-viewer` | Provides `remote-viewer` for SPICE sessions |
| `openbox` | Minimal window manager for the session type |

### Debian / Ubuntu

```bash
# 1. Install system dependencies
sudo apt update
sudo apt install -y python3-pip python3-pyqt6 virt-viewer openbox git

# 2. Get the project
sudo git clone <your-repo-url> /opt/ProxmoxSession

# 3. Run the installer
cd /opt/ProxmoxSession
sudo ./install/install.sh
```

### Fedora / RHEL / CentOS

```bash
sudo dnf install -y python3-pip python3-qt6 virt-viewer openbox git
sudo git clone <your-repo-url> /opt/ProxmoxSession
cd /opt/ProxmoxSession
sudo ./install/install.sh
```

> **Note:** If `python3-qt6` is unavailable via dnf: `pip3 install PyQt6`

### Manual Linux Install

```bash
pip3 install proxmoxer[https] requests PyQt6

sudo cp install/proxmox-session.sh /usr/local/bin/proxmox-session.sh
sudo chmod +x /usr/local/bin/proxmox-session.sh
sudo cp install/proxmox-session.desktop /usr/share/xsessions/proxmox-session.desktop

sudo mkdir -p /etc/vdiclient
sudo cp vdiclient.ini.example /etc/vdiclient/vdiclient.ini
```

The installer registers:
- Session launcher → `/usr/local/bin/proxmox-session.sh`
- X session entry → `/usr/share/xsessions/proxmox-session.desktop`
- Default config → `/etc/vdiclient/vdiclient.ini`

---

## Post-Install: Configure (Both Platforms)

Edit the config file and set at minimum:
- `[Hosts.PVE]` → your Proxmox server IP/hostname in `hostpool`
- `auth_backend` → `pve` for Proxmox VE accounts, `pam` for Linux PAM
- `tls_verify` → `false` for self-signed certs, `true` for valid certs

See [Configuration Reference](configuration.md) for all options.

---

## Verify the Installation

**Windows:**
```bat
python -m proxmox_session
```

**Linux:**
```bash
# Test launch
python3 -m proxmox_session --config_location /etc/vdiclient/vdiclient.ini

# Confirm session type registered
ls /usr/share/xsessions/ | grep proxmox

# Confirm remote-viewer available
which remote-viewer
```

---

## Activating the Linux Session Type

1. Log out of your current desktop session
2. At the login screen, find the **session selector** (gear icon on GDM, session menu on LightDM)
3. Select **"Proxmox VDI Session"**
4. Log in — the VDI client launches fullscreen

> **LightDM tip:** If the session doesn't appear after install:
> ```bash
> sudo systemctl restart lightdm
> ```

---

## Linux Kiosk / Thin Client Deployment

For shared workstations where users should only ever see the VDI client:

1. Create a dedicated local user (e.g. `vdiuser`)
2. Set `kiosk = True` in `/etc/vdiclient/vdiclient.ini`
3. Configure auto-login to that user with the proxmox session

**LightDM auto-login:**
```ini
# /etc/lightdm/lightdm.conf
[Seat:*]
autologin-user=vdiuser
autologin-session=proxmox-session
autologin-user-timeout=0
```

**GDM auto-login:**
```ini
# /etc/gdm3/custom.conf
[daemon]
AutomaticLoginEnable=True
AutomaticLogin=vdiuser
```

Then pin the session for `vdiuser`:
```bash
sudo mkdir -p /var/lib/AccountsService/users/
sudo bash -c 'echo -e "[User]\nXSession=proxmox-session" > /var/lib/AccountsService/users/vdiuser'
sudo systemctl restart lightdm  # or gdm
```

> **Note:** `kiosk = True` has no effect on Windows — the window always shows normal title bar, close, and minimize buttons.
