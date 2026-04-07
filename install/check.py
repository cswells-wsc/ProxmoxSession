"""
ProxmoxSession installation checker.
Called by install.bat --check

Exit codes:
  0 — everything is up to date
  1 — one or more checks failed or need attention
"""

import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # fallback
    except ImportError:
        tomllib = None  # type: ignore[assignment]

# ── Paths ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
PYPROJECT_PATH = os.path.join(PROJECT_DIR, "pyproject.toml")
STATE_FILE = os.path.join(PROJECT_DIR, ".install_state.json")

PASS = "[OK]  "
WARN = "[WARN]"
FAIL = "[FAIL]"
INFO = "      "

issues = 0


def ok(msg: str) -> None:
    print(f"  {PASS} {msg}")


def warn(msg: str) -> None:
    global issues
    issues += 1
    print(f"  {WARN} {msg}")


def fail(msg: str) -> None:
    global issues
    issues += 1
    print(f"  {FAIL} {msg}")


def info(msg: str) -> None:
    print(f"  {INFO} {msg}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def pyproject_hash() -> str:
    """SHA-256 of pyproject.toml — changes when deps or version bump."""
    with open(PYPROJECT_PATH, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def read_pyproject() -> dict:
    """Read pyproject.toml. Returns empty dict if tomllib unavailable."""
    if tomllib is None:
        return {}
    with open(PYPROJECT_PATH, "rb") as fh:
        return tomllib.load(fh)


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as fh:
            return json.load(fh)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as fh:
        json.dump(state, fh, indent=2)


def pip_show(package: str) -> dict:
    """Return dict of pip show output for a package, or {} if not installed."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", package],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return {}
        out = {}
        for line in result.stdout.splitlines():
            if ": " in line:
                k, _, v = line.partition(": ")
                out[k.strip().lower()] = v.strip()
        return out
    except Exception:
        return {}


def installed_version(package: str) -> str | None:
    """Get installed version via importlib.metadata."""
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def compare_versions(installed: str, required: str) -> bool:
    """
    Simple check: does installed satisfy the required spec (>=x.y.z)?
    Returns True if installed >= required minimum.
    """
    import re
    match = re.search(r"[\d.]+", required)
    if not match:
        return True
    req_parts = [int(x) for x in match.group().split(".")]
    try:
        inst_parts = [int(x) for x in installed.split(".")[:len(req_parts)]]
    except ValueError:
        return True
    return inst_parts >= req_parts


# ── Check sections ────────────────────────────────────────────────────────────

def check_package(pyproject: dict) -> None:
    print("\n[1] ProxmoxSession package")

    current_version = pyproject.get("project", {}).get("version", "unknown")
    info(f"Current version in pyproject.toml:  {current_version}")

    installed_ver = installed_version("proxmox-session")
    if installed_ver is None:
        fail("proxmox-session is NOT installed. Run install.bat to install.")
        return
    info(f"Installed version (pip):            {installed_ver}")

    if installed_ver == current_version:
        ok(f"Version matches ({installed_ver})")
    else:
        warn(f"Version mismatch — installed {installed_ver}, pyproject.toml says {current_version}. Re-run install.bat.")

    # Check editable install location
    show = pip_show("proxmox-session")
    location = show.get("location", "")
    editable_project = show.get("editable project location", "")
    if editable_project:
        if os.path.normcase(editable_project) == os.path.normcase(PROJECT_DIR):
            ok(f"Editable install points to correct directory")
        else:
            warn(f"Editable install points to wrong directory:\n{INFO}   installed: {editable_project}\n{INFO}   expected:  {PROJECT_DIR}")
    elif location:
        info(f"Installed as regular package at: {location}")

    # Check pyproject.toml hash for dependency drift
    current_hash = pyproject_hash()
    state = load_state()
    stored_hash = state.get("pyproject_hash")
    if stored_hash is None:
        warn("No install state recorded. Re-run install.bat to record baseline.")
    elif stored_hash == current_hash:
        ok("pyproject.toml unchanged since last install (no dependency drift)")
    else:
        warn("pyproject.toml has changed since last install — re-run install.bat to update dependencies.")


def check_dependencies(pyproject: dict) -> None:
    print("\n[2] Python dependencies")

    deps: list[str] = pyproject.get("project", {}).get("dependencies", [])
    if not deps:
        if tomllib is None:
            warn("Cannot parse pyproject.toml (tomllib not available on Python < 3.11 without tomli installed).")
        else:
            info("No dependencies listed in pyproject.toml.")
        return

    for dep in deps:
        # Strip extras like proxmoxer[https]
        import re
        match = re.match(r"([A-Za-z0-9_\-]+)(?:\[.*?\])?(.*)$", dep)
        if not match:
            continue
        pkg_name = match.group(1).lower()
        version_spec = match.group(2).strip()

        ver = installed_version(pkg_name)
        if ver is None:
            fail(f"{pkg_name}: NOT INSTALLED")
        elif version_spec and not compare_versions(ver, version_spec):
            warn(f"{pkg_name}: installed {ver} may not satisfy {version_spec}")
        else:
            ok(f"{pkg_name}: {ver}{(' (required ' + version_spec + ')') if version_spec else ''}")


def check_virtviewer() -> None:
    print("\n[3] virt-viewer (SPICE client)")

    # Check file type association
    try:
        result = subprocess.run(
            ["cmd", "/c", "ftype VirtViewer.vvfile"],
            capture_output=True, text=True
        )
        if result.returncode != 0 or "not found" in result.stdout.lower():
            fail("VirtViewer.vvfile file type NOT registered. Install virt-viewer and re-run install.bat.")
            return
        ftype_line = result.stdout.strip()
        ok(f"File type registered: {ftype_line}")

        # Extract binary path from ftype output
        # Format: VirtViewer.vvfile="C:\path\remote-viewer.exe" "%1"
        import shlex
        rhs = ftype_line.split("=", 1)[1].strip()
        # Handle quoted path
        if rhs.startswith('"'):
            binary = rhs.split('"')[1]
        else:
            binary = rhs.split()[0]

        if os.path.isfile(binary):
            ok(f"Binary exists: {binary}")
        else:
            fail(f"Binary NOT found at registered path: {binary}")
            return

        # Get version
        try:
            ver_result = subprocess.run(
                [binary, "--version"],
                capture_output=True, text=True, timeout=5
            )
            ver_output = (ver_result.stdout + ver_result.stderr).strip().splitlines()
            ver_line = ver_output[0] if ver_output else "unknown"
            ok(f"Version: {ver_line}")
        except Exception:
            info("Could not determine virt-viewer version.")

    except Exception as e:
        fail(f"Could not check virt-viewer: {e}")


def check_shortcuts() -> None:
    print("\n[4] Start Menu shortcuts")

    shortcut_dir = os.path.join(
        os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"
    )
    shortcuts = {
        "ProxmoxSession.lnk": "-m proxmox_session",
        "ProxmoxSession Config.lnk": "-m proxmox_session.config_editor",
    }

    for name, expected_args in shortcuts.items():
        path = os.path.join(shortcut_dir, name)
        if not os.path.exists(path):
            fail(f"{name}: NOT FOUND — re-run install.bat")
            continue

        # Read shortcut via PowerShell
        try:
            ps = subprocess.run(
                [
                    "powershell", "-Command",
                    f"$ws = New-Object -ComObject WScript.Shell; "
                    f"$sc = $ws.CreateShortcut('{path}'); "
                    f"Write-Output ($sc.TargetPath + '|' + $sc.Arguments + '|' + $sc.WorkingDirectory)"
                ],
                capture_output=True, text=True, timeout=10
            )
            parts = ps.stdout.strip().split("|")
            target = parts[0] if len(parts) > 0 else ""
            args = parts[1] if len(parts) > 1 else ""
            workdir = parts[2] if len(parts) > 2 else ""

            target_exists = os.path.isfile(target) if target else False
            workdir_ok = os.path.isdir(workdir) if workdir else False

            if not target_exists:
                warn(f"{name}: target missing or invalid: {target}")
            elif expected_args not in args:
                warn(f"{name}: unexpected arguments: {args}")
            elif not workdir_ok:
                warn(f"{name}: working directory missing: {workdir}")
            else:
                ok(f"{name}: target={os.path.basename(target)}, args={args}")
        except Exception as e:
            warn(f"{name}: could not inspect shortcut: {e}")


def check_config() -> None:
    print("\n[5] Config file")

    appdata = os.environ.get("APPDATA", "")
    config_path = os.path.join(appdata, "VDIClient", "vdiclient.ini")

    if not os.path.exists(config_path):
        warn(f"No config file found at: {config_path}")
        info("Run install.bat or copy vdiclient.ini.example to create one.")
        return

    ok(f"Config file exists: {config_path}")

    # Quick sanity check — must have [General] and at least one [Hosts.*]
    import configparser
    cfg = configparser.ConfigParser(delimiters="=")
    cfg.read(config_path, encoding="utf-8")

    if "General" not in cfg:
        fail("Config is missing [General] section.")
    else:
        ok("[General] section present")

    host_sections = [s for s in cfg.sections() if s.startswith("Hosts.")]
    if not host_sections:
        warn("No [Hosts.*] sections found — app will fail to start. Edit the config.")
    else:
        ok(f"{len(host_sections)} host section(s): {', '.join(host_sections)}")

        # Warn if still using example placeholder IPs
        for section in host_sections:
            hostpool = cfg.get(section, "hostpool", fallback="")
            if "10.10.10.100" in hostpool or "pve1.example.com" in hostpool:
                warn(f"[{section}] still contains example/placeholder host values.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 52)
    print("  ProxmoxSession — Installation Check")
    print("=" * 52)

    pyproject = read_pyproject()

    check_package(pyproject)
    check_dependencies(pyproject)
    check_virtviewer()
    check_shortcuts()
    check_config()

    print("\n" + "=" * 52)
    if issues == 0:
        print("  All checks passed. Installation is healthy.")
    else:
        print(f"  {issues} issue(s) found. See details above.")
    print("=" * 52 + "\n")

    return 0 if issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
