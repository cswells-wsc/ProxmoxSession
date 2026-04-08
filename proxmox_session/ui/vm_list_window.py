"""
VM list window — shows all accessible VMs with status badges, search filter,
Connect / Reset buttons, and 5-second auto-refresh via QTimer.
"""

import json
import logging
import os
import sys
from typing import Optional

import proxmoxer
from PyQt6.QtCore import QThread, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..api import ProxmoxAPIError, VMInfo, get_spice_config, get_vms, start_vm, stop_vm, wait_for_task
from ..config import AppConfig
from ..spice import build_spice_ini, get_vv_path_for_debug, launch_viewer
from ..utils.system import find_remote_viewer
from .dialogs import ConnectDialog, ask_yes_no, show_error, show_info

log = logging.getLogger(__name__)


def _prefs_path() -> str:
    if sys.platform == "win32":
        base = os.path.join(os.getenv("APPDATA", ""), "VDIClient")
    else:
        base = os.path.expanduser("~/.local/share/VDIClient")
    return os.path.join(base, "connection_prefs.json")


def _load_prefs() -> dict:
    path = _prefs_path()
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_prefs(prefs: dict) -> None:
    path = _prefs_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(prefs, fh, indent=2)
    except OSError as e:
        log.warning("Could not save connection prefs: %s", e)


# Status → display label + badge color
_STATUS_COLORS = {
    "running":    ("#a6e3a1", "Running"),
    "stopped":    ("#f38ba8", "Stopped"),
    "suspended":  ("#fab387", "Suspended"),
    "suspending": ("#fab387", "Suspending"),
    "paused":     ("#f9e2af", "Paused"),
}


class _VMRefreshWorker(QThread):
    """Background thread that fetches the VM list without blocking the UI."""
    refreshed = pyqtSignal(list)   # emits list[VMInfo]
    error = pyqtSignal(str)

    def __init__(self, proxmox, guest_type):
        super().__init__()
        self.proxmox = proxmox
        self.guest_type = guest_type

    def run(self):
        try:
            vms = get_vms(self.proxmox, self.guest_type)
            self.refreshed.emit(vms)
        except ProxmoxAPIError as e:
            self.error.emit(str(e))


class VMListWindow(QMainWindow):
    logged_out = pyqtSignal()   # emitted when user clicks Logout

    def __init__(
        self,
        config: AppConfig,
        proxmox: proxmoxer.ProxmoxAPI,
        hostset: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.config = config
        self.proxmox = proxmox
        self.hostset = hostset
        self._vms: list[VMInfo] = []
        self._vvcmd: Optional[str] = None
        self._prefs: dict = _load_prefs()

        self.setWindowTitle(config.title)

        if sys.platform == "win32":
            # Windows: normal window with title bar, close, and minimize buttons.
            # Fullscreen is still respected if the user explicitly sets it in config,
            # but kiosk (frameless) mode is never applied.
            if config.fullscreen:
                self.showMaximized()
            else:
                self.show()
        else:
            # Linux session: support kiosk (frameless) and true fullscreen.
            if config.kiosk:
                self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            if config.fullscreen or config.kiosk:
                self.showFullScreen()

        try:
            self._vvcmd = find_remote_viewer()
        except SystemExit as e:
            show_error(self, str(e))

        self._build_ui()
        self._refresh_vms()

        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._refresh_vms)
        self._timer.start()

    def _build_ui(self):
        cfg = self.config
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QHBoxLayout()
        if cfg.logo:
            logo = QLabel()
            logo.setPixmap(QPixmap(cfg.logo).scaledToHeight(40, Qt.TransformationMode.SmoothTransformation))
            header.addWidget(logo)
        title = QLabel(cfg.title)
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        header.addWidget(title, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()

        logout_btn = QPushButton("Logout")
        logout_btn.clicked.connect(self._on_logout)
        if cfg.kiosk:
            logout_btn.setVisible(False)
        header.addWidget(logout_btn)
        root.addLayout(header)

        # Search bar
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search VMs…")
        self._search.textChanged.connect(self._apply_filter)
        root.addWidget(self._search)

        # VM table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Name", "Status", "", ""])
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(0, self._table.horizontalHeader().ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        root.addWidget(self._table)

        if cfg.width and cfg.height:
            self.resize(cfg.width, cfg.height)
        else:
            self.resize(820, 500)

    def _refresh_vms(self):
        worker = _VMRefreshWorker(self.proxmox, self.config.guest_type)
        worker.refreshed.connect(self._on_vms_refreshed)
        worker.error.connect(lambda msg: show_error(self, msg))
        worker.start()
        self._worker = worker  # keep reference alive

    def _on_vms_refreshed(self, vms: list[VMInfo]):
        self._vms = vms
        self._apply_filter(self._search.text())

    def _apply_filter(self, text: str):
        query = text.strip().lower()
        filtered = [v for v in self._vms if query in v.name.lower() or query in str(v.vmid)]
        self._populate_table(filtered)

    def _populate_table(self, vms: list[VMInfo]):
        self._table.setRowCount(0)
        for vm in vms:
            row = self._table.rowCount()
            self._table.insertRow(row)

            # Name
            name_item = QTableWidgetItem(f"{vm.name}  (ID {vm.vmid})")
            self._table.setItem(row, 0, name_item)

            # Status badge
            status_key = vm.lock if vm.lock else vm.status
            color, label = _STATUS_COLORS.get(status_key, ("#cdd6f4", status_key.capitalize()))
            badge = QLabel(f"  {label}  ")
            badge.setStyleSheet(
                f"background-color: {color}; color: #1e1e2e; border-radius: 8px; "
                f"font-weight: bold; padding: 2px 6px;"
            )
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setCellWidget(row, 1, badge)

            # Connect button
            conn_btn = QPushButton("Connect")
            conn_btn.setProperty("vmid", vm.vmid)
            is_suspended = status_key in ("suspended", "suspending")
            conn_btn.setEnabled(not is_suspended)
            conn_btn.clicked.connect(lambda _, v=vm: self._on_connect(v))
            self._table.setCellWidget(row, 2, conn_btn)

            # Reset button (optional)
            if self.config.show_reset:
                reset_btn = QPushButton("Reset")
                reset_btn.clicked.connect(lambda _, v=vm: self._on_reset(v))
                self._table.setCellWidget(row, 3, reset_btn)

        self._table.resizeRowsToContents()

    def _on_connect(self, vm: VMInfo):
        if not self._vvcmd:
            show_error(self, "remote-viewer not found. Install virt-viewer.")
            return

        # Pre-connection dialog — USB redirection opt-in
        vm_prefs = self._prefs.get(str(vm.vmid), {})
        dlg = ConnectDialog(self, vm_name=vm.name, usb_default=vm_prefs.get("usb", False))
        if dlg.exec() != ConnectDialog.DialogCode.Accepted:
            return

        # Save USB preference for this VM
        self._prefs[str(vm.vmid)] = {"usb": dlg.usb_enabled}
        _save_prefs(self._prefs)

        # Start VM if stopped
        if vm.status != "running":
            if not self._start_and_wait(vm):
                return

        try:
            spice_data = get_spice_config(self.proxmox, vm)
        except ProxmoxAPIError as e:
            show_error(self, str(e))
            return

        safe_data = {k: ("***" if k == "password" else v) for k, v in spice_data.items()}
        log.debug("SPICE config received from Proxmox for VM %s: %s", vm.vmid, safe_data)

        addl = dict(self.config.addl_params or {})
        if dlg.usb_enabled:
            addl.setdefault("enable-usbredir", "true")
            addl.setdefault("enable-usb-autoshare", "true")

        ini = build_spice_ini(
            spice_data,
            self.config.spiceproxy_conv,
            addl,
        )

        import re
        safe_ini = re.sub(r"(?im)^(password\s*=\s*).*$", r"\1***", ini)
        log.debug("Built .vv file contents:\n%s", safe_ini)

        if self.config.inidebug:
            import os
            vv_path = get_vv_path_for_debug(ini)
            show_info(
                self,
                f"SPICE .vv file written to:\n{vv_path}\n\n{ini}",
                title="SPICE Debug — .vv file",
            )
            try:
                os.unlink(vv_path)
            except OSError:
                pass

        launch_viewer(
            self._vvcmd,
            ini,
            kiosk=self.config.kiosk,
            viewer_kiosk=self.config.viewer_kiosk,
            fullscreen=self.config.fullscreen,
        )
        # After viewer exits, refresh VM list
        self._refresh_vms()

    def _on_reset(self, vm: VMInfo):
        if not ask_yes_no(self, f"Reset VM '{vm.name}'? This will force-stop and restart it."):
            return
        self._start_and_wait(vm, force_restart=True)

    def _start_and_wait(self, vm: VMInfo, force_restart: bool = False) -> bool:
        try:
            if force_restart and vm.status == "running":
                job = stop_vm(self.proxmox, vm)
                if not wait_for_task(self.proxmox, vm.node, job):
                    show_error(self, f"Failed to stop VM '{vm.name}'.")
                    return False
            job = start_vm(self.proxmox, vm)
            if not wait_for_task(self.proxmox, vm.node, job):
                show_error(self, f"Failed to start VM '{vm.name}'.")
                return False
            return True
        except ProxmoxAPIError as e:
            show_error(self, str(e))
            return False

    def _on_logout(self):
        self._timer.stop()
        self.logged_out.emit()
        self.close()
