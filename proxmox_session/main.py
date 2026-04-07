"""
Entry point — parses CLI args, loads config, and runs the Qt application loop.
"""

import argparse
import logging
import sys

from PyQt6.QtWidgets import QApplication

from .config import load_config
from .ui.app import create_app
from .ui.dialogs import show_error
from .ui.login_window import LoginWindow
from .ui.vm_list_window import VMListWindow


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Proxmox VDI Session Client")
    parser.add_argument("--config_type", choices=["file", "http"], default="file",
                        help="Config source type (default: file)")
    parser.add_argument("--config_location", default=None,
                        help="Path or URL to config file")
    parser.add_argument("--config_username", default=None,
                        help="HTTP basic auth username for --config_type http")
    parser.add_argument("--config_password", default=None,
                        help="HTTP basic auth password for --config_type http")
    parser.add_argument("--ignore_ssl", action="store_false", dest="ssl_verify", default=True,
                        help="Disable SSL certificate verification")
    parser.add_argument("--fullscreen", action="store_true", default=False,
                        help="Force fullscreen mode (overrides config)")
    parser.add_argument("--debug", action="store_true", default=False,
                        help="Enable debug logging (shows .vv file contents and SPICE details)")
    return parser.parse_args()


def _setup_logging(debug: bool) -> None:
    import os
    level = logging.DEBUG if debug else logging.INFO

    handlers: list[logging.Handler] = [logging.StreamHandler()]

    # Always write to a log file so output is available even when launched as a GUI app
    if sys.platform == "win32":
        log_dir = os.path.join(os.getenv("APPDATA", ""), "VDIClient")
    else:
        log_dir = os.path.expanduser("~/.local/share/VDIClient")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "proxmox_session.log")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    # Restrict log file to owner-only on Linux — may contain SPICE tickets in debug mode
    if sys.platform != "win32":
        try:
            os.chmod(log_path, 0o600)
        except OSError:
            pass
    handlers.append(file_handler)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    logging.getLogger(__name__).info("Log file: %s", log_path)


def main() -> int:
    args = _parse_args()
    _setup_logging(args.debug)

    # QApplication must exist before any QWidget
    app: QApplication = create_app()  # theme resolved later after config loads

    try:
        config = load_config(
            config_location=args.config_location,
            config_type=args.config_type,
            config_username=args.config_username,
            config_password=args.config_password,
            ssl_verify=args.ssl_verify,
        )
    except ValueError as e:
        show_error(None, str(e), title="Configuration Error")
        return 1

    if args.fullscreen:
        config.fullscreen = True

    # Re-apply theme now that config is loaded
    from .ui.app import _DARK_QSS, _LIGHT_QSS
    theme = config.theme.lower()
    if theme == "dark":
        app.setStyleSheet(_DARK_QSS)
    elif theme == "light":
        app.setStyleSheet(_LIGHT_QSS)
    # else "system" — already set by create_app()

    # Main application loop: login → VM list → logout → login again
    while True:
        login = LoginWindow(config)

        # Auto-login when token credentials are provided and only one cluster
        host = config.hosts[config.current_hostset]
        if host.user and host.token_name and host.token_value and len(config.hosts) == 1:
            from .auth import authenticate
            result = authenticate(host, host.user)
            if not result.success:
                msg = (
                    "Unable to connect to any VDI server."
                    if not result.connected
                    else "Token authentication failed. Check token_name and token_value in config."
                )
                show_error(None, msg)
                return 1
            proxmox = result.proxmox
            hostset = config.current_hostset
        else:
            result_code = login.exec()
            if result_code == LoginWindow.ClusterChanged:
                # User switched cluster — update config and loop back to show login again
                config.current_hostset = login.current_hostset
                continue
            if result_code != LoginWindow.DialogCode.Accepted:
                return 0
            proxmox = login.proxmox
            hostset = login.current_hostset

        # Handle auto_vmid: connect directly without showing the VM list
        auto_id = config.hosts[hostset].auto_vmid
        if auto_id is not None:
            from .api import ProxmoxAPIError, get_vms
            from .spice import build_spice_ini, launch_viewer
            from .ui.dialogs import show_error as _se
            from .utils.system import find_remote_viewer
            try:
                vms = get_vms(proxmox, config.guest_type)
                target = next((v for v in vms if v.vmid == auto_id), None)
                if target is None:
                    _se(None, f"No VM with ID {auto_id} found.")
                    return 1
                vvcmd = find_remote_viewer()
                from .api import get_spice_config, start_vm, wait_for_task
                if target.status != "running":
                    job = start_vm(proxmox, target)
                    wait_for_task(proxmox, target.node, job)
                spice_data = get_spice_config(proxmox, target)
                ini = build_spice_ini(spice_data, config.spiceproxy_conv, config.addl_params)
                launch_viewer(vvcmd, ini, kiosk=config.kiosk,
                              viewer_kiosk=config.viewer_kiosk, fullscreen=config.fullscreen)
            except (ProxmoxAPIError, SystemExit) as e:
                _se(None, str(e))
            return 0

        vm_window = VMListWindow(config, proxmox, hostset)
        vm_window.show()

        # logged_out signal brings us back to the login loop
        loop_done = False

        def _on_logged_out():
            nonlocal loop_done
            loop_done = True

        vm_window.logged_out.connect(_on_logged_out)
        app.exec()

        if not loop_done:
            # Window was closed without logout (e.g. kiosk session ended)
            break

    return 0


if __name__ == "__main__":
    sys.exit(main())
