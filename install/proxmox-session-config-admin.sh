#!/bin/bash
# Launch the ProxmoxSession config editor with elevated privileges.
# pkexec clears the environment so DISPLAY and XAUTHORITY must be passed explicitly.
exec pkexec env DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" python3 -m proxmox_session.config_editor "$@"
