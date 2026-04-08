"""
VM list window — shows VMs and templates with status badges, search filter,
Connect / Reboot / Shutdown / Deploy buttons, and 5-second auto-refresh via QTimer.
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

from ..access import POOL_NAME, assign_vm_to_user
from ..api import (
    ProxmoxAPIError,
    VMInfo,
    clone_vm,
    get_spice_config,
    get_vms,
    reboot_vm,
    shutdown_vm,
    start_vm,
    stop_vm,
    wait_for_task,
)
from ..config import AppConfig
from ..spice import build_spice_ini, get_vv_path_for_debug, launch_viewer
from ..utils.system import find_remote_viewer
from .dialogs import ConnectDialog, DeployVMDialog, ask_yes_no, show_error, show_info

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

_TEMPLATE_COLOR = ("#89b4fa", "Template")


class _VMRefreshWorker(QThread):
    """Background thread that fetches VMs and templates without blocking the UI."""
    refreshed = pyqtSignal(list)   # emits list[VMInfo] (includes templates)
    error = pyqtSignal(str)

    def __init__(self, proxmox: proxmoxer.ProxmoxAPI, guest_type: str):
        super().__init__()
        self.proxmox = proxmox
        self.guest_type = guest_type

    def run(self) -> None:
        try:
            vms = get_vms(self.proxmox, self.guest_type, include_templates=True)
            self.refreshed.emit(vms)
        except ProxmoxAPIError as e:
            self.error.emit(str(e))


class _CloneWorker(QThread):
    """Background thread for VM clone operations (can take 10-60+ seconds)."""
    finished = pyqtSignal(int, str)   # (new_vmid, vm_name)
    error = pyqtSignal(str)

    def __init__(
        self,
        proxmox: proxmoxer.ProxmoxAPI,
        vm: VMInfo,
        new_name: str,
        full: bool,
        pool: str,
    ):
        super().__init__()
        self.proxmox = proxmox
        self.vm = vm
        self.new_name = new_name
        self.full = full
        self.pool = pool

    def run(self) -> None:
        try:
            new_vmid, job_id = clone_vm(
                self.proxmox, self.vm, self.new_name,
                pool=self.pool, full=self.full,
            )
            # Wait for clone task to complete (up to 5 minutes for large disks)
            wait_for_task(self.proxmox, self.vm.node, job_id, max_wait=300)
            self.finished.emit(new_vmid, self.new_name)
        except ProxmoxAPIError as e:
            self.error.emit(str(e))


class VMListWindow(QMainWindow):
    logged_out = pyqtSignal()   # emitted when user clicks Logout

    def __init__(
        self,
        config: AppConfig,
        proxmox: proxmoxer.ProxmoxAPI,
        hostset: str,
        current_userid: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.config = config
        self.proxmox = proxmox
        self.hostset = hostset
        self._current_userid = current_userid
        self._vms: list[VMInfo] = []
        self._vvcmd: Optional[str] = None
        self._prefs: dict = _load_prefs()
        self._clone_worker: Optional[_CloneWorker] = None

        self.setWindowTitle(config.title)

        if sys.platform == "win32":
            if config.fullscreen:
                self.showMaximized()
            else:
                self.show()
        else:
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

    def _build_ui(self) -> None:
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
        self._search.setPlaceholderText("Search VMs and templates…")
        self._search.textChanged.connect(self._apply_filter)
        root.addWidget(self._search)

        # VM table — 4 columns: Name | Type/Status | [action buttons]
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Name", "Type", "Status", "Actions"])
        h = self._table.horizontalHeader()
        if h:
            h.setStretchLastSection(False)
            h.setSectionResizeMode(0, h.ResizeMode.Stretch)
            h.setSectionResizeMode(1, h.ResizeMode.Fixed)
            h.setSectionResizeMode(2, h.ResizeMode.Fixed)
            h.setSectionResizeMode(3, h.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(1, 90)
        self._table.setColumnWidth(2, 100)
        v = self._table.verticalHeader()
        if v:
            v.setVisible(False)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        root.addWidget(self._table)

        if cfg.width and cfg.height:
            self.resize(cfg.width, cfg.height)
        else:
            self.resize(900, 520)

    def _refresh_vms(self) -> None:
        worker = _VMRefreshWorker(self.proxmox, self.config.guest_type)
        worker.refreshed.connect(self._on_vms_refreshed)
        worker.error.connect(lambda msg: show_error(self, msg))
        worker.start()
        self._worker = worker  # keep reference alive

    def _on_vms_refreshed(self, vms: list[VMInfo]) -> None:
        self._vms = vms
        self._apply_filter(self._search.text())

    def _apply_filter(self, text: str) -> None:
        query = text.strip().lower()
        filtered = [v for v in self._vms if query in v.name.lower() or query in str(v.vmid)]
        self._populate_table(filtered)

    def _populate_table(self, vms: list[VMInfo]) -> None:
        self._table.setRowCount(0)

        # Sort: templates first, then VMs alphabetically
        sorted_vms = sorted(vms, key=lambda v: (not v.is_template, v.name.lower()))

        for vm in sorted_vms:
            row = self._table.rowCount()
            self._table.insertRow(row)

            # Col 0: Name + VMID
            type_tag = " [Template]" if vm.is_template else ""
            name_item = QTableWidgetItem(f"{vm.name}{type_tag}  (ID {vm.vmid})")
            self._table.setItem(row, 0, name_item)

            # Col 1: Type badge (QEMU / LXC / Template)
            if vm.is_template:
                type_color, type_label = _TEMPLATE_COLOR
            elif vm.vmtype == "qemu":
                type_color, type_label = ("#cba6f7", "QEMU")
            else:
                type_color, type_label = ("#89dceb", "LXC")
            type_badge = _make_badge(f"  {type_label}  ", type_color)
            self._table.setCellWidget(row, 1, type_badge)

            # Col 2: Status badge (templates show a dash)
            if vm.is_template:
                status_badge = _make_badge("  —  ", "#585b70")
            else:
                status_key = vm.lock if vm.lock else vm.status
                color, label = _STATUS_COLORS.get(status_key, ("#cdd6f4", status_key.capitalize()))
                status_badge = _make_badge(f"  {label}  ", color)
            self._table.setCellWidget(row, 2, status_badge)

            # Col 3: Action buttons
            actions = self._make_actions_widget(vm)
            self._table.setCellWidget(row, 3, actions)

        self._table.resizeRowsToContents()

    def _make_actions_widget(self, vm: VMInfo) -> QWidget:
        """Build the actions cell for a VM or template row."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        if vm.is_template:
            # Templates: Deploy VM button only
            deploy_btn = QPushButton("Deploy VM…")
            deploy_btn.setFixedWidth(100)
            deploy_btn.setToolTip(f"Create a new VM from template '{vm.name}'")
            deploy_btn.clicked.connect(lambda _, v=vm: self._on_deploy(v))
            layout.addWidget(deploy_btn)
        else:
            is_running = vm.status == "running"
            is_suspended = vm.status in ("suspended", "suspending")

            # Connect button
            conn_btn = QPushButton("Connect")
            conn_btn.setFixedWidth(80)
            conn_btn.setEnabled(not is_suspended)
            conn_btn.setToolTip("Start VM if needed, then open SPICE session")
            conn_btn.clicked.connect(lambda _, v=vm: self._on_connect(v))
            layout.addWidget(conn_btn)

            # Reboot button (only useful when running)
            reboot_btn = QPushButton("Reboot")
            reboot_btn.setFixedWidth(68)
            reboot_btn.setEnabled(is_running)
            reboot_btn.setToolTip("Graceful reboot (ACPI signal)")
            reboot_btn.clicked.connect(lambda _, v=vm: self._on_reboot(v))
            layout.addWidget(reboot_btn)

            # Shutdown button (only useful when running)
            shutdown_btn = QPushButton("Shutdown")
            shutdown_btn.setFixedWidth(78)
            shutdown_btn.setEnabled(is_running)
            shutdown_btn.setToolTip("Graceful shutdown (ACPI signal)")
            shutdown_btn.clicked.connect(lambda _, v=vm: self._on_shutdown(v))
            layout.addWidget(shutdown_btn)

            # Optional Reset button
            if self.config.show_reset:
                reset_btn = QPushButton("Reset")
                reset_btn.setFixedWidth(60)
                reset_btn.setToolTip("Force stop and restart")
                reset_btn.clicked.connect(lambda _, v=vm: self._on_reset(v))
                layout.addWidget(reset_btn)

        layout.addStretch()
        return container

    # ── VM actions ────────────────────────────────────────────────────────────

    def _on_connect(self, vm: VMInfo) -> None:
        if not self._vvcmd:
            show_error(self, "remote-viewer not found. Install virt-viewer.")
            return

        vm_prefs = self._prefs.get(str(vm.vmid), {})
        dlg = ConnectDialog(self, vm_name=vm.name, usb_default=vm_prefs.get("usb", False))
        if dlg.exec() != ConnectDialog.DialogCode.Accepted:
            return

        self._prefs[str(vm.vmid)] = {"usb": dlg.usb_enabled}
        _save_prefs(self._prefs)

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

        ini = build_spice_ini(spice_data, self.config.spiceproxy_conv, addl)

        import re
        safe_ini = re.sub(r"(?im)^(password\s*=\s*).*$", r"\1***", ini)
        log.debug("Built .vv file contents:\n%s", safe_ini)

        if self.config.inidebug:
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
        self._refresh_vms()

    def _on_reboot(self, vm: VMInfo) -> None:
        if not ask_yes_no(self, f"Reboot VM '{vm.name}'?\n\nThis sends an ACPI reboot signal."):
            return
        try:
            reboot_vm(self.proxmox, vm)
            log.info("Reboot requested for VM %s", vm.vmid)
            self._refresh_vms()
        except ProxmoxAPIError as e:
            show_error(self, str(e))

    def _on_shutdown(self, vm: VMInfo) -> None:
        if not ask_yes_no(self, f"Shut down VM '{vm.name}'?\n\nThis sends an ACPI shutdown signal. "
                           "The VM will force-stop after 60 seconds if the guest does not respond."):
            return
        try:
            shutdown_vm(self.proxmox, vm)
            log.info("Shutdown requested for VM %s", vm.vmid)
            self._refresh_vms()
        except ProxmoxAPIError as e:
            show_error(self, str(e))

    def _on_reset(self, vm: VMInfo) -> None:
        if not ask_yes_no(self, f"Reset VM '{vm.name}'? This will force-stop and restart it."):
            return
        self._start_and_wait(vm, force_restart=True)

    def _on_deploy(self, vm: VMInfo) -> None:
        """Clone a template to a new VM."""
        dlg = DeployVMDialog(self, template_name=vm.name)
        if dlg.exec() != DeployVMDialog.DialogCode.Accepted:
            return

        if self._clone_worker and self._clone_worker.isRunning():
            show_error(self, "A deploy operation is already in progress. Please wait.")
            return

        self._clone_worker = _CloneWorker(
            self.proxmox, vm, dlg.vm_name, dlg.full_clone, POOL_NAME
        )
        self._clone_worker.finished.connect(self._on_clone_done)
        self._clone_worker.error.connect(lambda msg: show_error(self, f"Deploy failed:\n{msg}"))
        self._clone_worker.start()

        show_info(
            self,
            f"Deploying '{dlg.vm_name}' from template '{vm.name}'…\n\n"
            "This may take a minute for large disks. The VM list will refresh automatically.",
            title="Deploying VM",
        )

    def _on_clone_done(self, new_vmid: int, new_name: str) -> None:
        # Auto-assign the new VM to the user who deployed it
        if self._current_userid:
            try:
                assign_vm_to_user(self.proxmox, self._current_userid, new_vmid)
                log.info("Auto-assigned VM %s to %s after deploy", new_vmid, self._current_userid)
                msg = (
                    f"VM '{new_name}' (ID {new_vmid}) has been created and assigned to your account.\n\n"
                    "It will appear in your VM list once the server finishes provisioning it."
                )
            except Exception as e:
                log.warning("Could not auto-assign VM %s to %s: %s", new_vmid, self._current_userid, e)
                msg = (
                    f"VM '{new_name}' (ID {new_vmid}) was created in the proxmoxsession_resources pool,\n"
                    f"but could not be automatically assigned to your account:\n{e}\n\n"
                    "Ask an administrator to assign it."
                )
        else:
            msg = (
                f"VM '{new_name}' (ID {new_vmid}) has been created in the "
                f"proxmoxsession_resources pool."
            )
        show_info(self, msg, title="Deploy Complete")
        self._refresh_vms()

    # ── Helpers ───────────────────────────────────────────────────────────────

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

    def _on_logout(self) -> None:
        self._timer.stop()
        self.logged_out.emit()
        self.close()


def _make_badge(text: str, bg_color: str) -> QLabel:
    """Create a small colored badge label for use in table cells."""
    badge = QLabel(text)
    badge.setStyleSheet(
        f"background-color: {bg_color}; color: #1e1e2e; border-radius: 8px; "
        f"font-weight: bold; padding: 2px 6px;"
    )
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return badge
