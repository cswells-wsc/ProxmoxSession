"""
Test: verify the full .vv file flow — build, write to disk, and launch.

Run with:
    python tests/test_spice_vv.py

Tests performed:
  1. build_spice_ini() produces valid .vv content
  2. _write_vv_file() creates a real file on disk with correct content
  3. The file is a valid virt-viewer INI with a [virt-viewer] section
  4. SpiceProxyRedirect rewrites are applied correctly
  5. AdditionalParameters are appended correctly
  6. remote-viewer binary is detectable on this machine
  7. (Optional) launch_viewer() with a real .vv file — only runs if --live is passed
"""

import os
import sys
import tempfile
from configparser import ConfigParser

# Allow running from project root without install
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from proxmox_session.spice import _write_vv_file, build_spice_ini
from proxmox_session.utils.system import find_remote_viewer


SAMPLE_SPICE_DATA = {
    "type": "spice",
    "host": "10.10.10.100",
    "port": "5900",
    "password": "testpassword123",
    "tls-port": "5901",
    "ca": "-----BEGIN CERTIFICATE-----\nMIIBxxx\n-----END CERTIFICATE-----\n",
    "host-subject": "CN=pve.example.com",
    "proxy": "http://pve.example.com:3128",
    "delete-this-file": "1",
}

PASS = "[PASS]"
FAIL = "[FAIL]"
INFO = "    >"

errors = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global errors
    if condition:
        print(f"  {PASS}  {label}")
    else:
        print(f"  {FAIL}  {label}" + (f": {detail}" if detail else ""))
        errors += 1


# ─── Test 1: build_spice_ini basic output ───────────────────────────────────
print("\n[1] build_spice_ini() — basic output")

ini = build_spice_ini(SAMPLE_SPICE_DATA, spiceproxy_conv={})
check("Returns a non-empty string", bool(ini))

cfg = ConfigParser()
cfg.read_string(ini)
check("Parses as valid INI", True)
check("Has [virt-viewer] section", cfg.has_section("virt-viewer"))
check("host field present", cfg.get("virt-viewer", "host", fallback=None) == "10.10.10.100")
check("port field present", cfg.get("virt-viewer", "port", fallback=None) == "5900")
check("password field present", cfg.get("virt-viewer", "password", fallback=None) == "testpassword123")
check("proxy field unchanged (no redirect)", "pve.example.com:3128" in cfg.get("virt-viewer", "proxy", fallback=""))
print(f"  {INFO}  .vv content preview:")
for line in ini.strip().splitlines()[:8]:
    print(f"         {line}")

# ─── Test 2: SpiceProxyRedirect ──────────────────────────────────────────────
print("\n[2] build_spice_ini() — SpiceProxyRedirect rewrite")

proxy_map = {"pve.example.com:3128": "203.0.113.10:3128"}
ini2 = build_spice_ini(SAMPLE_SPICE_DATA, spiceproxy_conv=proxy_map)
cfg2 = ConfigParser()
cfg2.read_string(ini2)
rewritten = cfg2.get("virt-viewer", "proxy", fallback="")
check("Proxy rewritten to redirect target", "203.0.113.10:3128" in rewritten, rewritten)
check("Proxy still has http:// prefix", rewritten.startswith("http://"), rewritten)

# ─── Test 3: AdditionalParameters ────────────────────────────────────────────
print("\n[3] build_spice_ini() — AdditionalParameters")

extra = {"enable-usbredir": "true", "enable-usb-autoshare": "true"}
ini3 = build_spice_ini(SAMPLE_SPICE_DATA, spiceproxy_conv={}, addl_params=extra)
cfg3 = ConfigParser()
cfg3.read_string(ini3)
check("enable-usbredir appended", cfg3.get("virt-viewer", "enable-usbredir", fallback=None) == "true")
check("enable-usb-autoshare appended", cfg3.get("virt-viewer", "enable-usb-autoshare", fallback=None) == "true")

# ─── Test 4: _write_vv_file() — file creation ────────────────────────────────
print("\n[4] _write_vv_file() — temp file creation")

vv_path = _write_vv_file(ini)
check("File was created on disk", os.path.isfile(vv_path), vv_path)
check("File has .vv extension", vv_path.endswith(".vv"), vv_path)
check("File is in temp directory", vv_path.startswith(tempfile.gettempdir()), vv_path)

with open(vv_path, "r", encoding="utf-8") as fh:
    on_disk = fh.read()
check("File content matches built ini", on_disk == ini)

cfg_disk = ConfigParser()
cfg_disk.read_string(on_disk)
check("On-disk file parses as valid INI", cfg_disk.has_section("virt-viewer"))

print(f"  {INFO}  File path: {vv_path}")
print(f"  {INFO}  File size: {os.path.getsize(vv_path)} bytes")

# Cleanup
os.unlink(vv_path)
check("File deleted after test", not os.path.exists(vv_path))

# ─── Test 5: remote-viewer detection ─────────────────────────────────────────
print("\n[5] remote-viewer detection")

try:
    vvcmd = find_remote_viewer()
    check("remote-viewer binary found", True)
    check("Path is non-empty", bool(vvcmd))
    print(f"  {INFO}  Command: {vvcmd}")
    if sys.platform == "win32":
        check("Command exists on disk", os.path.isfile(vvcmd), vvcmd)
except SystemExit as e:
    check("remote-viewer binary found", False, str(e))
    vvcmd = None

# ─── Test 6: live launch (opt-in) ────────────────────────────────────────────
if "--live" in sys.argv and vvcmd:
    print("\n[6] Live launch — remote-viewer with test .vv file")
    print(f"  {INFO}  This will open remote-viewer. It will fail to connect (test data) — that is expected.")
    print(f"  {INFO}  Watch for the window to open and show a connection error.\n")
    from proxmox_session.spice import launch_viewer
    test_ini = build_spice_ini(SAMPLE_SPICE_DATA, spiceproxy_conv={})
    proc = launch_viewer(vvcmd, test_ini, fullscreen=False, timeout=3)
    check("Process was created", proc is not None)
    check("Process has a PID", proc.pid > 0, str(proc.pid))
    print(f"  {INFO}  PID: {proc.pid} — close the viewer window when done")
    proc.wait()
    print(f"  {INFO}  remote-viewer exited with code: {proc.returncode}")
else:
    print("\n[6] Live launch — skipped (pass --live to test actual remote-viewer execution)")

# ─── Summary ─────────────────────────────────────────────────────────────────
print()
if errors == 0:
    print("All tests passed.\n")
else:
    print(f"{errors} test(s) FAILED.\n")
    sys.exit(1)
