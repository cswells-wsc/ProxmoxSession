# USB Redirection

USB redirection lets you plug a USB device into the **client machine** (the PC running ProxmoxSession) and have it appear inside the **VM** — as if it were physically connected there. This works over the SPICE protocol and requires configuration on both the Proxmox side and the client side.

Common use cases: USB storage drives, webcams, headsets, smartcard readers, hardware security keys (YubiKey, etc.).

---

## How It Works

```
Client machine (USB device plugged in)
        │
        │  SPICE + usbredir protocol
        ▼
remote-viewer (virt-viewer)
        │
        │  USB device forwarded over network
        ▼
VM on Proxmox (device appears as local USB)
```

The `usbredir` protocol forwards USB traffic over the SPICE connection. remote-viewer handles the redirection — it intercepts the USB device on the client and presents it to the VM guest OS.

---

## Requirements

### 1. Proxmox VM — SPICE Display

The VM must use a **SPICE display**, not VNC or the default display.

In the Proxmox web UI:

1. Select the VM → **Hardware** tab
2. Find the **Display** entry
3. Click **Edit** and set **Graphic card** to **SPICE**
4. Click **OK**

> If the VM is running, it must be shut down before changing the display type.

---

### 2. Proxmox VM — USB Redirection Devices

USB redirection slots must be explicitly added to the VM hardware. Each slot allows one USB device to be redirected at a time. Add 2–4 slots to allow multiple devices.

In the Proxmox web UI:

1. Select the VM → **Hardware** tab
2. Click **Add** → **USB Device**
3. Set **Use USB Vendor/Device ID** to **Spice Port** (not a specific device)
4. Click **Add**
5. Repeat steps 2–4 to add more slots (recommended: add 3–4 total)

The VM config will show entries like:
```
usb0: spice
usb1: spice
usb2: spice
```

> These slots are what remote-viewer uses to forward USB devices. Without them, the USB redirection option in remote-viewer will be greyed out even if enabled in the client.

---

### 3. VM Guest — Drivers

**Linux guests:** USB redirection works automatically with the kernel's built-in USB drivers. No additional software needed.

**Windows guests:** Requires the **VirtIO USB** driver.

Install from the VirtIO ISO:
1. Download the [VirtIO drivers ISO](https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso)
2. Attach it to the VM as a CD-ROM
3. Inside the VM, open the ISO and run `virtio-win-guest-tools.exe`
4. Reboot the VM

Alternatively, install via Windows Update — search for **Red Hat VirtIO** in optional updates.

---

## Enabling USB Redirection in ProxmoxSession

When you click **Connect** on a VM, a pre-connection dialog appears:

```
┌─ Connect — web-server ───────────────────┐
│                                           │
│  web-server                               │
│                                           │
│  [x] Enable USB Redirection               │
│      Allows attaching USB devices from    │
│      this machine to the VM via the       │
│      remote-viewer toolbar.               │
│                                           │
│        [ Cancel ]  [ Connect ]            │
└───────────────────────────────────────────┘
```

- **Check** the box to enable USB redirection for this session
- Your choice is **remembered per VM** — the next time you connect to the same VM the checkbox will default to your last setting
- Unchecking does not affect `[AdditionalParameters]` in your config — if you have `enable-usbredir = true` set globally there, it always applies

---

## Using USB Redirection in remote-viewer

Once connected with USB redirection enabled:

1. In the remote-viewer window, click **File** → **USB device selection**
   (or look for the USB icon in the toolbar)
2. A list of USB devices connected to your client machine appears
3. Check the device(s) you want to redirect to the VM
4. The device disappears from your local machine and appears inside the VM
5. To disconnect: uncheck the device in the same menu, or disconnect the SPICE session

> **Note:** While a USB device is redirected to the VM, it is **not accessible** on the client machine. Safely eject it within the VM before disconnecting.

---

## Global USB Redirection (Always On)

If you want USB redirection enabled for **all** VMs without the per-session dialog prompt, add it to your config:

```ini
[AdditionalParameters]
enable-usbredir = true
enable-usb-autoshare = true
```

With `enable-usb-autoshare = true`, USB devices matching the auto-share filter (removable storage by default) are automatically redirected when plugged in during a session, without needing to use the menu.

---

## Troubleshooting

**USB menu is greyed out in remote-viewer**
- The VM has no SPICE USB redirection slots — add them in Proxmox VM hardware (see step 2 above)

**Device appears in the menu but fails to redirect**
- Windows guest: VirtIO USB driver not installed — install from the VirtIO ISO
- Linux guest: try `lsusb` inside the VM to confirm the device was forwarded

**Device redirects but is not recognized by the VM**
- The guest OS may need a specific driver for that device type (e.g. webcam, smartcard)
- Try reconnecting the device via the USB menu (uncheck then recheck)

**USB redirection option doesn't appear in the Connect dialog**
- Ensure you are running the latest version: `cd /opt/ProxmoxSession && sudo git pull && sudo bash install/install.sh`

**Redirected storage drive is not safely ejectable**
- Use the VM's OS to eject the drive first, then uncheck it in remote-viewer's USB menu
