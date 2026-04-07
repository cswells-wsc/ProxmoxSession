"""
System utilities — detect the remote-viewer binary path.
"""

import subprocess
import sys


def find_remote_viewer() -> str:
    """
    Return the path to remote-viewer/virt-viewer.
    Raises SystemExit with a user-friendly message if not found.
    """
    if sys.platform == "win32":
        try:
            result = subprocess.check_output("ftype VirtViewer.vvfile", shell=True)
            cmdresult = result.decode("utf-8")
            parts = cmdresult.split("=", 1)
            if len(parts) == 2:
                import csv
                for row in csv.reader([parts[1]], delimiter=" ", quotechar='"'):
                    return row[0]
        except subprocess.CalledProcessError:
            pass
        raise SystemExit(
            "virt-viewer not found. Download from https://virt-manager.org/download/"
        )
    else:
        try:
            subprocess.check_output(["which", "remote-viewer"], stderr=subprocess.DEVNULL)
            return "remote-viewer"
        except subprocess.CalledProcessError:
            raise SystemExit(
                "remote-viewer not found. Install with: apt install virt-viewer"
            )
