#!/bin/bash
# Proxmox VDI Session launcher
# Starts a minimal window manager, waits for network, then launches the VDI client.
# When the VDI client exits, the session ends and the user is returned to the login screen.

# ── Window manager ─────────────────────────────────────────────────────────────

if command -v openbox &>/dev/null; then
    openbox &
elif command -v xfwm4 &>/dev/null; then
    xfwm4 &
fi

# Give the WM a moment to initialize
sleep 0.5

# ── Wait for network ───────────────────────────────────────────────────────────
# The Proxmox API is contacted immediately on startup, so we need a working
# network connection before launching. Normal desktop sessions (GNOME/KDE) do
# this internally; our minimal session has to do it explicitly.

NETWORK_TIMEOUT=30

if command -v nm-online &>/dev/null; then
    # NetworkManager: wait up to 30s for a connected state
    nm-online -t "$NETWORK_TIMEOUT" -q || true

elif command -v systemd-networkd-wait-online &>/dev/null; then
    # systemd-networkd: wait up to 30s
    systemd-networkd-wait-online --timeout="$NETWORK_TIMEOUT" --any || true

else
    # Fallback: poll until any non-loopback interface has an IP
    echo "Waiting for network..."
    for i in $(seq 1 "$NETWORK_TIMEOUT"); do
        if ip route show default 2>/dev/null | grep -q default; then
            break
        fi
        sleep 1
    done
fi

# ── Launch VDI client ──────────────────────────────────────────────────────────

exec python3 -m proxmox_session --fullscreen
