# Troubleshooting

## Diagnostics First

Before digging into specific issues, run the app from a terminal to see the full error output:

```bash
python3 -m proxmox_session --config_location /etc/vdiclient/vdiclient.ini
```

Enable SPICE ini debug to inspect the connection details:

```ini
# /etc/vdiclient/vdiclient.ini
[General]
inidebug = True
```

---

## Installation Issues

### "Session type not appearing at login screen"

**Cause:** The `.desktop` file is not in the right location, or the display manager hasn't reloaded it.

**Fix:**
```bash
# Confirm the file exists
ls /usr/share/xsessions/proxmox-session.desktop

# Restart the display manager
sudo systemctl restart gdm        # GDM
sudo systemctl restart lightdm    # LightDM
sudo systemctl restart sddm       # SDDM
```

---

### "remote-viewer not found"

**Cause:** `virt-viewer` is not installed.

**Fix:**
```bash
sudo apt install virt-viewer      # Debian/Ubuntu
sudo dnf install virt-viewer      # Fedora/RHEL

# Verify
which remote-viewer
```

---

### "No module named 'PyQt6'"

**Cause:** PyQt6 is not installed in the Python environment the session uses.

**Fix:**
```bash
sudo pip3 install PyQt6
# or via system packages:
sudo apt install python3-pyqt6
```

If the session launcher uses a specific Python binary, check which one:
```bash
which python3
python3 -c "import PyQt6; print('OK')"
```

---

### "No module named 'proxmoxer'"

**Fix:**
```bash
sudo pip3 install proxmoxer[https]
# Verify:
python3 -c "import proxmoxer; print('OK')"
```

---

## Login / Authentication Issues

### "Unable to connect to any VDI server"

**Causes & fixes:**

1. **Wrong IP/hostname in config**
   ```ini
   [Hosts.PVE]
   hostpool = { "correct-ip-or-hostname": 8006 }
   ```

2. **Firewall blocking port 8006**
   ```bash
   # Test from the client machine
   curl -k https://pve.example.com:8006/api2/json/version
   ```

3. **TLS certificate error with tls_verify = true**
   ```ini
   tls_verify = false   # temporary — get a valid cert for production
   ```

4. **Wrong port** — Proxmox defaults to `8006` but may be changed.

---

### "Invalid username and/or password"

- Confirm the username format: `username` only (not `user@pve`) — the backend is appended by the app
- Confirm the `auth_backend` value: `pve` for Proxmox VE accounts, `pam` for Linux system accounts
- Test credentials directly in the Proxmox web UI

---

### "Token authentication failed"

- Verify `token_name` matches exactly (case-sensitive)
- Verify `token_value` is the full UUID
- Confirm the token has not expired or been revoked in Proxmox:
  ```bash
  pveum user token list vdi@pve
  ```
- Confirm the token has permission on the target VM:
  ```bash
  pveum acl list | grep vdi
  ```

---

### TOTP / OTP Not Working

- Ensure the system clock on both the client and Proxmox server are in sync (NTP)
- The OTP field accepts the 6-digit code only — do not include spaces

---

## VM List Issues

### "No desktop instances found"

**Causes:**

1. **User has no permissions** — assign `VM.Audit`, `VM.Console`, `VM.PowerMgmt` to the user for the relevant VMs (see [Management](management.md))
2. **guest_type mismatch** — if you set `guest_type = qemu` but the user's VMs are LXC containers, they won't appear
3. **All nodes offline** — the app skips VMs on offline nodes

---

### VM Stuck in "Suspending" State

The Connect button is disabled for suspended/suspending VMs. If the VM is stuck:

1. Log into the Proxmox web UI
2. Manually resume or stop the VM
3. The client will reflect the updated status within 5 seconds (auto-refresh)

---

## SPICE Connection Issues

### "Is SPICE display configured for your VM?"

The VM in Proxmox must have its display set to **SPICE** (not VirtIO or std):

1. Proxmox web UI → select VM → **Hardware** tab
2. Find **Display** → Edit → Set type to **SPICE**
3. Optionally set **SPICE Enhancements** for better performance

---

### Black Screen After Connecting

**Cause:** The VM started but the guest OS hasn't finished booting yet, or the SPICE agent is not installed inside the guest.

**Fix:**
- Install `spice-vdagent` inside the guest VM:
  ```bash
  # Inside the guest
  sudo apt install spice-vdagent     # Debian/Ubuntu
  sudo dnf install spice-vdagent     # Fedora/RHEL
  ```
- Wait a few seconds and reconnect

---

### "SPICE Proxy" Connection Refused

This happens when Proxmox returns a SPICE proxy address that is not reachable from the client.

**Diagnose:**
1. Set `inidebug = True` in `[General]`
2. Click Connect — note the `proxy=` line in the SPICE ini
3. Add a redirect in `[SpiceProxyRedirect]`:

```ini
[SpiceProxyRedirect]
pve-internal.local:3128 = 203.0.113.10:3128
```

---

### remote-viewer Closes Immediately

- Check if the SPICE ticket has expired (Proxmox issues short-lived tickets — this should not normally happen unless there is a clock skew)
- Run `remote-viewer` manually with the ini file to see the error:
  ```bash
  # Enable inidebug, copy the ini contents, save to /tmp/test.ini
  remote-viewer /tmp/test.ini
  ```

---

## Display / UI Issues

### Window Appears Off-Screen or Wrong Size

Override dimensions in the config:

```ini
[General]
window_width = 900
window_height = 600
```

---

### Theme Not Applied / Looks Wrong

- Set `theme = dark` or `theme = light` explicitly in `[General]` instead of `system`
- If running under Wayland, try forcing X11: `QT_QPA_PLATFORM=xcb python3 -m proxmox_session`

---

### High DPI / Blurry Text on 4K Screens

```bash
# Set Qt scale factor before launching
QT_SCALE_FACTOR=1.5 python3 -m proxmox_session
```

Add it to the session launcher to make it permanent:

```bash
# /usr/local/bin/proxmox-session.sh
export QT_SCALE_FACTOR=1.5
exec python3 -m proxmox_session --fullscreen
```

---

## Kiosk Mode Issues

### User Can Still Close the Window

Ensure both settings are set:
```ini
[General]
kiosk = True
viewer_kiosk = True
```

If the window manager (openbox) provides a right-click menu, disable it:
```bash
# Create ~/.config/openbox/rc.xml with an empty menu config
mkdir -p ~/.config/openbox
cat > ~/.config/openbox/rc.xml <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config>
  <menu><file>menu.xml</file></menu>
</openbox_config>
EOF
```

---

### Auto-Login Not Working (LightDM)

```ini
# /etc/lightdm/lightdm.conf
[Seat:*]
autologin-user=vdiuser
autologin-session=proxmox-session
autologin-user-timeout=0
```

```bash
sudo systemctl restart lightdm
```

---

## Getting Help

If you've followed the steps above and the issue persists:

1. Capture the full error output:
   ```bash
   python3 -m proxmox_session 2>&1 | tee /tmp/proxmox-session.log
   ```
2. Note your OS version, Python version, PyQt6 version, and Proxmox VE version:
   ```bash
   python3 --version
   python3 -c "import PyQt6.QtCore; print(PyQt6.QtCore.PYQT_VERSION_STR)"
   python3 -c "import proxmoxer; print(proxmoxer.__version__)"
   ```
3. Open an issue and attach the log and version info.
