#!/bin/bash
# Proxmox VDI Session launcher
# Starts a minimal window manager, then the VDI client.
# When the VDI client exits, the session ends and the user is returned to the login screen.

# Use openbox as a minimal WM if available, fall back to xfwm4 or none
if command -v openbox &>/dev/null; then
    openbox &
elif command -v xfwm4 &>/dev/null; then
    xfwm4 &
fi

# Give the WM a moment to initialize
sleep 0.5

# Launch the VDI client
exec python3 -m proxmox_session --fullscreen
