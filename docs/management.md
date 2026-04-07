# Managing the Application

## Proxmox Permissions

### Required Permissions Per VM

Each user who accesses a VM through the VDI client needs these Proxmox permissions assigned **on each VM** (or on a pool/folder that contains those VMs):

| Permission | Purpose |
|---|---|
| `VM.PowerMgmt` | Start and stop VMs from the client |
| `VM.Console` | Access the SPICE console |
| `VM.Audit` | Read VM status and configuration |

### Setting Permissions in Proxmox

1. Log into the **Proxmox web UI**
2. Navigate to **Datacenter → Permissions**
3. Click **Add → User Permission**
4. Set:
   - **Path:** `/vms/<vmid>` (per VM) or `/pool/<poolname>` (for a pool of VMs)
   - **User:** the user's Proxmox account (e.g. `alice@pve`)
   - **Role:** You can use the built-in `PVEVMUser` role or create a custom role

### Recommended: Custom VDI Role

Create a minimal role with only the required permissions:

```bash
# On the Proxmox host (via SSH or shell)
pveum role add VDIUser --privs "VM.PowerMgmt VM.Console VM.Audit"
```

Then assign it:

```bash
# Grant alice access to VM 100
pveum acl modify /vms/100 --users alice@pve --roles VDIUser

# Grant alice access to all VMs in pool "VDI"
pveum acl modify /pool/VDI --users alice@pve --roles VDIUser
```

---

## API Token Management

API tokens allow password-less, auto-login authentication. Useful for kiosk deployments.

### Create a Token

```bash
# On Proxmox host
pveum user token add vdi@pve vdi --privsep 0
```

Copy the returned token value (UUID) — it is only shown once.

### Assign the Token Permissions

```bash
pveum acl modify /vms/100 --tokens vdi@pve!vdi --roles VDIUser
```

### Add to Config

```ini
[Hosts.PVE]
user = vdi@pve
token_name = vdi
token_value = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

---

## Updating the Application

### From Source

```bash
cd /opt/ProxmoxSession
git pull
sudo pip3 install --break-system-packages --upgrade .
```

No restart of the display manager is needed — the update takes effect on the next client launch.

### Updating the Config Only

```bash
sudo nano /etc/vdiclient/vdiclient.ini
```

Config is re-read on every launch; no service restart is needed.

---

## Uninstalling

```bash
# Remove session type registration
sudo rm /usr/share/xsessions/proxmox-session.desktop

# Remove session launcher
sudo rm /usr/local/bin/proxmox-session.sh

# Remove Python package
sudo pip3 uninstall proxmox-session

# (Optional) remove config
sudo rm -rf /etc/vdiclient
```

---

## Adding a New Proxmox Cluster

1. Add a new `[Hosts.<name>]` section to `/etc/vdiclient/vdiclient.ini`
2. Set the `hostpool`, `auth_backend`, and TLS options
3. Save — the new cluster appears in the login dropdown on the next launch

---

## Running Multiple Configs

You can deploy different configs to different machines and point the launcher at them:

```bash
# Edit /usr/local/bin/proxmox-session.sh
exec python3 -m proxmox_session \
    --config_location /etc/vdiclient/site-a.ini \
    --fullscreen
```

Or use a per-user config at `~/.config/VDIClient/vdiclient.ini` which takes precedence over `/etc/vdiclient/vdiclient.ini`.

---

## Session Logs

Application output is visible in the display manager's log or by running the app from a terminal:

```bash
# Run manually to see stdout/stderr
python3 -m proxmox_session

# Or check the display manager log
journalctl -u gdm -n 100
journalctl -u lightdm -n 100
```

---

## Keeping virt-viewer Up to Date

SPICE features depend on the `virt-viewer` / `remote-viewer` version:

```bash
sudo apt upgrade virt-viewer        # Debian/Ubuntu
sudo dnf upgrade virt-viewer        # Fedora/RHEL
```

Check the installed version:
```bash
remote-viewer --version
```
