"""
SPICE connection handler — builds the virt-viewer .vv file and launches remote-viewer.

On Windows: writes a .vv temp file and passes it as a path argument (required because
            remote-viewer on Windows is a GUI app and stdin is unreliable).
On Linux:   writes a .vv temp file and passes it as a path argument (more reliable
            than stdin and allows inidebug inspection).

The temp file is written to the OS temp directory and cleaned up after launch.
"""

import logging
import os
import socket
import subprocess
import tempfile
from configparser import ConfigParser
from io import StringIO
from typing import Optional

log = logging.getLogger(__name__)


def _resolve_host(hostname: str) -> str:
    """Resolve a hostname to its IP address. Returns the original if resolution fails."""
    try:
        ip = socket.gethostbyname(hostname)
        if ip != hostname:
            log.debug("Resolved %s -> %s", hostname, ip)
        return ip
    except OSError:
        log.warning("Could not resolve hostname %s — using as-is", hostname)
        return hostname


def build_spice_ini(
    spice_config: dict,
    spiceproxy_conv: dict[str, str],
    addl_params: Optional[dict[str, str]] = None,
) -> str:
    """
    Convert the Proxmox SPICE proxy dict into a virt-viewer .vv file string.
    Applies SpiceProxyRedirect rewrites and any AdditionalParameters.
    """
    cfg = ConfigParser()
    cfg["virt-viewer"] = {}

    for key, value in spice_config.items():
        if key == "proxy":
            # Strip leading "http://" for lookup, keep it in the written value
            val = value[7:].lower() if value.lower().startswith("http://") else value.lower()
            if val in spiceproxy_conv:
                target = spiceproxy_conv[val]
            else:
                target = val
            # Resolve hostname to IP: split host:port, resolve host, reassemble
            if ":" in target:
                proxy_host, proxy_port = target.rsplit(":", 1)
                proxy_host = _resolve_host(proxy_host)
                target = f"{proxy_host}:{proxy_port}"
            else:
                target = _resolve_host(target)
            cfg["virt-viewer"][key] = f"http://{target}"
        elif key == "host":
            val = str(value)
            # pvespiceproxy: tokens are not DNS names — pass through unchanged
            if not val.startswith("pvespiceproxy:"):
                val = _resolve_host(val)
            cfg["virt-viewer"][key] = val
        else:
            cfg["virt-viewer"][key] = str(value)

    if addl_params:
        for key, value in addl_params.items():
            cfg["virt-viewer"][key] = str(value)

    buf = StringIO()
    cfg.write(buf)
    buf.seek(0)
    return buf.read()


def _write_vv_file(ini_string: str) -> str:
    """
    Write the .vv content to a named temp file and return its path.
    The caller is responsible for deleting the file after use.
    """
    tmp_dir = tempfile.gettempdir()
    fd, path = tempfile.mkstemp(suffix=".vv", prefix="proxmox_session_", dir=tmp_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(ini_string)
    except Exception:
        os.close(fd)
        raise
    log.debug("Wrote SPICE .vv file: %s", path)
    return path


def launch_viewer(
    vvcmd: str,
    ini_string: str,
    kiosk: bool = False,
    viewer_kiosk: bool = True,
    fullscreen: bool = True,
    timeout: int = 5,
) -> subprocess.Popen:
    """
    Write the SPICE config to a .vv temp file and launch remote-viewer with it.

    The .vv file is deleted after remote-viewer has started and read it
    (we wait up to `timeout` seconds for the process to start, then clean up).

    Returns the running Popen process so callers can wait on it if needed.
    """
    vv_path = _write_vv_file(ini_string)
    log.info("Launching remote-viewer with .vv file: %s", vv_path)

    cmd = [vvcmd]

    if kiosk and viewer_kiosk:
        cmd += ["--kiosk", "--kiosk-quit", "on-disconnect"]
    elif fullscreen:
        cmd.append("--full-screen")
    cmd.append(vv_path)

    # Capture stderr so we can log remote-viewer's error messages
    process = subprocess.Popen(cmd, stderr=subprocess.PIPE)

    # Give remote-viewer a moment to open and read the file before we delete it
    try:
        process.wait(timeout=timeout)
        # Process exited within the timeout window — likely a connection error
        stderr_out = process.stderr.read().decode(errors="replace").strip() if process.stderr else ""
        if process.returncode != 0:
            log.warning(
                "remote-viewer exited with code %d after %.1fs. stderr: %s",
                process.returncode, timeout, stderr_out or "(no output)"
            )
        elif stderr_out:
            log.debug("remote-viewer stderr: %s", stderr_out)
    except subprocess.TimeoutExpired:
        # Expected — remote-viewer is still running (good)
        log.debug("remote-viewer still running after %ds (session active)", timeout)

    # Clean up the temp file now that remote-viewer has read it
    try:
        os.unlink(vv_path)
        log.debug("Deleted temp .vv file: %s", vv_path)
    except OSError as e:
        log.warning("Could not delete temp .vv file %s: %s", vv_path, e)

    return process


def get_vv_path_for_debug(ini_string: str) -> str:
    """
    Write the .vv content to a persistent temp file for inidebug inspection.
    Returns the path. The caller must delete this file when done.
    """
    return _write_vv_file(ini_string)
