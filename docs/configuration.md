# Configuration Reference

The application reads from an INI file. Config is searched in this order (first match wins):

1. Path passed via `--config_location`
2. `~/.config/VDIClient/vdiclient.ini`
3. `/etc/vdiclient/vdiclient.ini`
4. `/usr/local/etc/vdiclient/vdiclient.ini`

The config can also be served over HTTP — see [HTTP Config](#http-served-config).

---

## [General] Section

| Key | Type | Default | Description |
|---|---|---|---|
| `title` | string | `VDI Login` | Window title shown to users |
| `theme` | string | `system` | UI theme: `dark`, `light`, or `system` |
| `icon` | path | _(none)_ | Path to window icon (.png or .ico) |
| `logo` | path | _(none)_ | Path to logo image shown in header |
| `kiosk` | bool | `False` | Remove window chrome and close buttons |
| `viewer_kiosk` | bool | `True` | Pass `--kiosk` to remote-viewer (only when `kiosk = True`) |
| `fullscreen` | bool | `True` | Launch VM list window fullscreen |
| `inidebug` | bool | `False` | Show the SPICE .ini contents before connecting (for debugging proxy issues) |
| `guest_type` | string | `both` | Which VM types to show: `both`, `qemu`, or `lxc` |
| `show_reset` | bool | `False` | Show a Reset button per VM (force-stop + start) |
| `window_width` | int | _(auto)_ | Override window width in pixels |
| `window_height` | int | _(auto)_ | Override window height in pixels |

### Example

```ini
[General]
title = Acme Corp VDI
theme = dark
logo = /opt/ProxmoxSession/vdiclient.png
icon = /opt/ProxmoxSession/vdiicon.ico
kiosk = True
fullscreen = True
guest_type = qemu
show_reset = False
```

---

## [Hosts.\<Name\>] Sections

Each cluster is a separate `[Hosts.<name>]` section. The `<name>` is shown to users in the cluster dropdown. You can define as many as needed.

| Key | Type | Required | Description |
|---|---|---|---|
| `hostpool` | JSON dict | Yes | Map of `"host": port` pairs. All lines must be indented. |
| `auth_backend` | string | No | Auth realm: `pve` (Proxmox VE) or `pam` (Linux PAM). Default: `pve` |
| `auth_totp` | bool | No | Show OTP field on login. Default: `False` |
| `tls_verify` | bool | No | Verify TLS certificate. Default: `True` — set `False` for self-signed certs. |
| `user` | string | No | Pre-fill username. If combined with `token_name` + `token_value`, auto-login is triggered. |
| `token_name` | string | No | Proxmox API token name (e.g. `vdi`) |
| `token_value` | string | No | Proxmox API token value (UUID format) |
| `pwresetcmd` | string | No | Shell command to open a password reset tool or URL |
| `auto_vmid` | int | No | VMID to connect to automatically after login, skipping the VM list |
| `knock_seq` | JSON array | No | Port-knock sequence before connecting (see below) |

### hostpool Format

```ini
hostpool = {
               "10.10.10.100" : 8006,
               "10.10.10.101" : 8006,
               "pve.example.com" : 8006
           }
```

The client shuffles the pool and tries each host in order. The first successful connection wins (load balancing / failover).

### API Token Authentication

When `user`, `token_name`, and `token_value` are all set **and** there is only one `[Hosts.*]` section, login is automatic — no login window appears.

```ini
[Hosts.PVE]
hostpool = { "pve.example.com": 8006 }
auth_backend = pve
tls_verify = true
user = vdi@pve
token_name = vdi
token_value = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### Port Knock Sequence

```ini
knock_seq = [
    {"host": "10.10.10.100", "port": 1234, "proto": "udp"},
    {"host": "10.10.10.100", "port": 5678, "proto": "tcp"}
]
```

### Multiple Clusters

```ini
[Hosts.Production]
hostpool = { "pve-prod.example.com": 8006 }
auth_backend = pve
tls_verify = true

[Hosts.Dev]
hostpool = { "pve-dev.example.com": 8006 }
auth_backend = pve
tls_verify = false
```

A dropdown appears at login so users can choose which cluster to connect to.

---

## [SpiceProxyRedirect] Section

Proxmox returns a SPICE proxy address in its API response. If that address is not reachable from the client (e.g. it returns a private hostname but the client is on a different network), you can rewrite it here.

**Format:** `original_host:port = reachable_host:port`

```ini
[SpiceProxyRedirect]
pve.internal:3128 = 203.0.113.10:3128
```

**How to find the proxy value:** Set `inidebug = True` in `[General]`, click Connect on a VM, and read the `proxy=` line in the displayed SPICE ini.

---

## [AdditionalParameters] Section

Extra parameters passed directly to `remote-viewer`. See the [remote-viewer man page](https://www.mankier.com/1/remote-viewer) for the full list.

```ini
[AdditionalParameters]
enable-usbredir = true
enable-usb-autoshare = true
spice-color-depth = 32
```

---

## HTTP-Served Config

The config file can be hosted on a web server instead of stored locally. This is useful for centralized config management.

```bash
python3 -m proxmox_session \
    --config_type http \
    --config_location https://config.example.com/vdiclient.ini \
    --config_username admin \
    --config_password secret
```

To set this as the default in the session launcher, edit `/usr/local/bin/proxmox-session.sh`:

```bash
exec python3 -m proxmox_session \
    --config_type http \
    --config_location https://config.example.com/vdiclient.ini \
    --fullscreen
```

---

## Command-Line Options

| Flag | Description |
|---|---|
| `--config_type file\|http` | Config source type (default: `file`) |
| `--config_location PATH\|URL` | Path or URL to config file |
| `--config_username` | HTTP basic auth username |
| `--config_password` | HTTP basic auth password |
| `--ignore_ssl` | Disable SSL verification for HTTP config fetch |
| `--fullscreen` | Force fullscreen (overrides config) |

---

## Per-User vs System-Wide Config

| Scope | Path | Use Case |
|---|---|---|
| System-wide | `/etc/vdiclient/vdiclient.ini` | Shared/thin client deployments |
| Per-user | `~/.config/VDIClient/vdiclient.ini` | Single-user workstations |
| Per-session | `--config_location /path/to/file` | Testing or multiple configs |
