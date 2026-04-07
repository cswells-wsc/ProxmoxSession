"""
Entry point for the ProxmoxSession Configuration Editor.
Run as: python -m proxmox_session.config_editor
"""
import sys
from .ui.config_window import main

if __name__ == "__main__":
    sys.exit(main())
