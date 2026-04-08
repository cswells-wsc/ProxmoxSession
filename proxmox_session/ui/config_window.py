"""
ProxmoxSession Configuration Editor
A tabbed GUI for editing vdiclient.ini — one tab per host cluster plus
General, SPICE Proxy, and Extra Parameters tabs.

Launch via:  python -m proxmox_session.config_editor
"""

import json
import os
import sys
from configparser import ConfigParser
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import _default_config_paths
from .app import create_app


# ─────────────────────────────────────────────
# Reusable table widgets
# ─────────────────────────────────────────────

class HostpoolTable(QWidget):
    """Editable table of (host, port) pairs for the hostpool setting."""

    def __init__(self, entries: list[dict], parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Host / IP", "Port"])
        h_header = self._table.horizontalHeader()
        if h_header:
            h_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            h_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 80)
        v_header = self._table.verticalHeader()
        if v_header:
            v_header.setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Row")
        add_btn.clicked.connect(self._add_row)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        for entry in entries:
            self._append(entry.get("host", ""), entry.get("port", 8006))

    def _append(self, host: str, port: int) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(host))
        port_item = QTableWidgetItem(str(port))
        port_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, 1, port_item)

    def _add_row(self) -> None:
        self._append("", 8006)
        self._table.scrollToBottom()
        self._table.editItem(self._table.item(self._table.rowCount() - 1, 0))

    def _remove_selected(self) -> None:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()}, reverse=True)
        for row in rows:
            self._table.removeRow(row)

    def get_entries(self) -> list[dict]:
        entries = []
        for row in range(self._table.rowCount()):
            host_item = self._table.item(row, 0)
            port_item = self._table.item(row, 1)
            host = host_item.text().strip() if host_item else ""
            if not host:
                continue
            try:
                port = int(port_item.text()) if port_item else 8006
            except ValueError:
                port = 8006
            entries.append({"host": host, "port": port})
        return entries


class KeyValueTable(QWidget):
    """Generic editable two-column key/value table (SPICE proxy redirects, extra params)."""

    def __init__(
        self,
        col0_label: str,
        col1_label: str,
        entries: dict[str, str],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels([col0_label, col1_label])
        h_header = self._table.horizontalHeader()
        if h_header:
            h_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            h_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        v_header = self._table.verticalHeader()
        if v_header:
            v_header.setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Row")
        add_btn.clicked.connect(self._add_row)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        for key, val in entries.items():
            self._append(key, val)

    def _append(self, key: str, value: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(key))
        self._table.setItem(row, 1, QTableWidgetItem(value))

    def _add_row(self) -> None:
        self._append("", "")
        self._table.scrollToBottom()
        self._table.editItem(self._table.item(self._table.rowCount() - 1, 0))

    def _remove_selected(self) -> None:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()}, reverse=True)
        for row in rows:
            self._table.removeRow(row)

    def get_entries(self) -> dict[str, str]:
        result = {}
        for row in range(self._table.rowCount()):
            k_item = self._table.item(row, 0)
            v_item = self._table.item(row, 1)
            key = k_item.text().strip() if k_item else ""
            val = v_item.text().strip() if v_item else ""
            if key:
                result[key] = val
        return result


# ─────────────────────────────────────────────
# Tab widgets
# ─────────────────────────────────────────────

def _browse_file(parent: QWidget, line_edit: QLineEdit, title: str, filter_str: str) -> None:
    path, _ = QFileDialog.getOpenFileName(parent, title, "", filter_str)
    if path:
        line_edit.setText(path)


class GeneralTab(QWidget):
    """Tab for the [General] config section."""

    def __init__(self, raw: ConfigParser, parent: Optional[QWidget] = None):
        super().__init__(parent)
        g = raw["General"] if "General" in raw else {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form = QFormLayout(inner)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 16)

        # Title
        self._title = QLineEdit(g.get("title", "VDI Login"))
        form.addRow("Window Title:", self._title)

        # Theme
        self._theme = QComboBox()
        self._theme.addItems(["system", "dark", "light"])
        self._theme.setCurrentText(g.get("theme", "system"))
        form.addRow("Theme:", self._theme)

        # Icon
        icon_row = QHBoxLayout()
        self._icon = QLineEdit(g.get("icon", ""))
        icon_btn = QPushButton("Browse…")
        icon_btn.setFixedWidth(80)
        icon_btn.clicked.connect(lambda: _browse_file(self, self._icon, "Select Icon", "Images (*.ico *.png)"))
        icon_row.addWidget(self._icon)
        icon_row.addWidget(icon_btn)
        form.addRow("Icon:", icon_row)

        # Logo
        logo_row = QHBoxLayout()
        self._logo = QLineEdit(g.get("logo", ""))
        logo_btn = QPushButton("Browse…")
        logo_btn.setFixedWidth(80)
        logo_btn.clicked.connect(lambda: _browse_file(self, self._logo, "Select Logo", "Images (*.png *.jpg *.bmp)"))
        logo_row.addWidget(self._logo)
        logo_row.addWidget(logo_btn)
        form.addRow("Logo:", logo_row)

        # Guest type
        self._guest_type = QComboBox()
        self._guest_type.addItems(["both", "qemu", "lxc"])
        self._guest_type.setCurrentText(g.get("guest_type", "both"))
        form.addRow("Show VMs:", self._guest_type)

        # Checkboxes
        self._fullscreen = QCheckBox("Start VM list window fullscreen")
        self._fullscreen.setChecked(g.get("fullscreen", "true").lower() == "true")
        form.addRow("", self._fullscreen)

        self._kiosk = QCheckBox("Kiosk mode (hide title bar and close button — Linux only)")
        self._kiosk.setChecked(g.get("kiosk", "false").lower() == "true")
        form.addRow("", self._kiosk)

        self._viewer_kiosk = QCheckBox("Pass --kiosk to remote-viewer (only applies when Kiosk mode is on)")
        self._viewer_kiosk.setChecked(g.get("viewer_kiosk", "true").lower() == "true")
        form.addRow("", self._viewer_kiosk)

        self._show_reset = QCheckBox("Show Reset button per VM (force-stop + restart)")
        self._show_reset.setChecked(g.get("show_reset", "false").lower() == "true")
        form.addRow("", self._show_reset)

        self._inidebug = QCheckBox("INI debug: show SPICE config before connecting")
        self._inidebug.setChecked(g.get("inidebug", "false").lower() == "true")
        form.addRow("", self._inidebug)

        # Window dimensions
        dims = QHBoxLayout()
        self._width = QSpinBox()
        self._width.setRange(0, 9999)
        self._width.setSpecialValueText("Auto")
        self._width.setValue(int(g.get("window_width", "0")) if g.get("window_width") else 0)
        self._height = QSpinBox()
        self._height.setRange(0, 9999)
        self._height.setSpecialValueText("Auto")
        self._height.setValue(int(g.get("window_height", "0")) if g.get("window_height") else 0)
        dims.addWidget(QLabel("W:"))
        dims.addWidget(self._width)
        dims.addWidget(QLabel("H:"))
        dims.addWidget(self._height)
        dims.addStretch()
        form.addRow("Window Size (0 = auto):", dims)

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def write_to(self, raw: ConfigParser) -> None:
        if "General" not in raw:
            raw.add_section("General")
        g = raw["General"]
        g["title"] = self._title.text().strip() or "VDI Login"
        g["theme"] = self._theme.currentText()
        icon = self._icon.text().strip()
        if icon:
            g["icon"] = icon
        logo = self._logo.text().strip()
        if logo:
            g["logo"] = logo
        g["guest_type"] = self._guest_type.currentText()
        g["fullscreen"] = "true" if self._fullscreen.isChecked() else "false"
        g["kiosk"] = "true" if self._kiosk.isChecked() else "false"
        g["viewer_kiosk"] = "true" if self._viewer_kiosk.isChecked() else "false"
        g["show_reset"] = "true" if self._show_reset.isChecked() else "false"
        g["inidebug"] = "true" if self._inidebug.isChecked() else "false"
        if self._width.value() > 0:
            g["window_width"] = str(self._width.value())
        if self._height.value() > 0:
            g["window_height"] = str(self._height.value())


class HostTab(QWidget):
    """Tab for a single [Hosts.<name>] config section."""

    def __init__(self, name: str, raw: ConfigParser, parent: Optional[QWidget] = None):
        super().__init__(parent)
        section = f"Hosts.{name}"
        g = raw[section] if section in raw else {}

        # Parse existing hostpool JSON
        hostpool: list[dict] = []
        if "hostpool" in g:
            try:
                hp = json.loads(g["hostpool"])
                hostpool = [{"host": h, "port": int(p)} for h, p in hp.items()]
            except (json.JSONDecodeError, ValueError):
                pass

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # ── Host name ──
        name_box = QGroupBox("Cluster Name")
        name_form = QFormLayout(name_box)
        self._name = QLineEdit(name)
        self._name.setPlaceholderText("e.g. PVE, Production, HomeLab")
        name_form.addRow("Name:", self._name)
        layout.addWidget(name_box)

        # ── Hostpool ──
        pool_box = QGroupBox("Proxmox Hosts (load-balanced / failover)")
        pool_layout = QVBoxLayout(pool_box)
        self._hostpool = HostpoolTable(hostpool)
        pool_layout.addWidget(self._hostpool)
        layout.addWidget(pool_box)

        # ── Authentication ──
        auth_box = QGroupBox("Authentication")
        auth_form = QFormLayout(auth_box)
        auth_form.setSpacing(8)

        self._backend = QComboBox()
        self._backend.addItems(["pve", "pam", "ldap", "ad"])
        self._backend.setEditable(True)
        self._backend.setCurrentText(g.get("auth_backend", "pve"))
        auth_form.addRow("Auth Backend:", self._backend)

        self._totp = QCheckBox("Enable TOTP / OTP field at login")
        self._totp.setChecked(g.get("auth_totp", "false").lower() == "true")
        auth_form.addRow("", self._totp)

        self._tls = QCheckBox("Verify TLS certificate (uncheck for self-signed certs)")
        self._tls.setChecked(g.get("tls_verify", "true").lower() == "true")
        auth_form.addRow("", self._tls)

        layout.addWidget(auth_box)

        # ── API Token (optional) ──
        token_box = QGroupBox("API Token (optional — enables auto-login when all three are set)")
        token_form = QFormLayout(token_box)
        token_form.setSpacing(8)

        self._user = QLineEdit(g.get("user", ""))
        self._user.setPlaceholderText("e.g. vdi@pve")
        token_form.addRow("Username:", self._user)

        self._token_name = QLineEdit(g.get("token_name", ""))
        self._token_name.setPlaceholderText("e.g. vdi")
        token_form.addRow("Token Name:", self._token_name)

        self._token_value = QLineEdit(g.get("token_value", ""))
        self._token_value.setPlaceholderText("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
        self._token_value.setEchoMode(QLineEdit.EchoMode.Password)
        show_token_btn = QPushButton("Show")
        show_token_btn.setFixedWidth(60)
        show_token_btn.setCheckable(True)
        show_token_btn.toggled.connect(
            lambda checked: self._token_value.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        token_val_row = QHBoxLayout()
        token_val_row.addWidget(self._token_value)
        token_val_row.addWidget(show_token_btn)
        token_form.addRow("Token Value:", token_val_row)

        layout.addWidget(token_box)

        # ── Options ──
        opts_box = QGroupBox("Options")
        opts_form = QFormLayout(opts_box)
        opts_form.setSpacing(8)

        self._pwreset = QLineEdit(g.get("pwresetcmd", ""))
        self._pwreset.setPlaceholderText("e.g. xdg-open https://pwreset.example.com")
        opts_form.addRow("Password Reset Command:", self._pwreset)

        self._auto_vmid = QSpinBox()
        self._auto_vmid.setRange(0, 999999)
        self._auto_vmid.setSpecialValueText("Disabled (show VM list)")
        self._auto_vmid.setValue(int(g.get("auto_vmid", "0")) if g.get("auto_vmid") else 0)
        opts_form.addRow("Auto-connect VMID:", self._auto_vmid)

        self._knock = QLineEdit(g.get("knock_seq", ""))
        self._knock.setPlaceholderText('[{"host":"10.0.0.1","port":1234,"proto":"udp"}]')
        opts_form.addRow("Port Knock Sequence (JSON):", self._knock)

        layout.addWidget(opts_box)
        layout.addStretch()

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def get_name(self) -> str:
        return self._name.text().strip()

    def write_to(self, raw: ConfigParser) -> None:
        name = self.get_name()
        if not name:
            return
        section = f"Hosts.{name}"
        if section not in raw:
            raw.add_section(section)

        entries = self._hostpool.get_entries()
        if entries:
            hostpool_dict = {e["host"]: e["port"] for e in entries}
            hp_json = json.dumps(hostpool_dict, indent=4)
            lines = hp_json.splitlines()
            # ConfigParser multi-line: continuation lines must start with whitespace
            raw[section]["hostpool"] = lines[0] + "\n" + "\n".join(
                "    " + ln for ln in lines[1:]
            )

        raw[section]["auth_backend"] = self._backend.currentText()
        raw[section]["auth_totp"] = "true" if self._totp.isChecked() else "false"
        raw[section]["tls_verify"] = "true" if self._tls.isChecked() else "false"

        user = self._user.text().strip()
        if user:
            raw[section]["user"] = user
        token_name = self._token_name.text().strip()
        if token_name:
            raw[section]["token_name"] = token_name
        token_value = self._token_value.text().strip()
        if token_value:
            raw[section]["token_value"] = token_value

        pwreset = self._pwreset.text().strip()
        if pwreset:
            raw[section]["pwresetcmd"] = pwreset

        if self._auto_vmid.value() > 0:
            raw[section]["auto_vmid"] = str(self._auto_vmid.value())

        knock = self._knock.text().strip()
        if knock:
            raw[section]["knock_seq"] = knock


# ─────────────────────────────────────────────
# Main config editor window
# ─────────────────────────────────────────────

class ConfigWindow(QMainWindow):
    def __init__(self, config_path: Optional[str] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("ProxmoxSession — Configuration Editor")
        self.resize(760, 640)

        self._config_path = config_path or self._find_config()
        self._raw = self._load(self._config_path)

        self._build_ui()
        self._update_title()

    # ── Config I/O ──────────────────────────────

    def _find_config(self) -> Optional[str]:
        for path in _default_config_paths():
            if os.path.exists(path):
                return path
        return None

    def _load(self, path: Optional[str]) -> ConfigParser:
        raw = ConfigParser(delimiters="=")
        if path and os.path.isfile(path):
            raw.read(path, encoding="utf-8")
        if "General" not in raw:
            raw.add_section("General")
        return raw

    def _update_title(self) -> None:
        label = self._config_path or "(new file — not yet saved)"
        self.setWindowTitle(f"ProxmoxSession Config — {label}")

    # ── UI build ─────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Top bar: current config path + Open button ──
        top_bar = QHBoxLayout()
        self._path_label = QLabel(self._config_path or "No config file loaded")
        self._path_label.setStyleSheet("font-style: italic;")
        top_bar.addWidget(self._path_label, 1)
        open_btn = QPushButton("Open Different File…")
        open_btn.clicked.connect(self._on_open)
        top_bar.addWidget(open_btn)
        root.addLayout(top_bar)

        # ── Tab widget ──
        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._on_tab_close)

        add_host_btn = QPushButton("＋ Add Host")
        add_host_btn.clicked.connect(self._on_add_host)
        self._tabs.setCornerWidget(add_host_btn, Qt.Corner.TopRightCorner)

        root.addWidget(self._tabs, 1)

        self._populate_tabs()

        # ── Bottom buttons ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("Save")
        save_btn.setFixedWidth(100)
        save_btn.clicked.connect(self._on_save)
        save_as_btn = QPushButton("Save As…")
        save_as_btn.setFixedWidth(100)
        save_as_btn.clicked.connect(self._on_save_as)
        cancel_btn = QPushButton("Close")
        cancel_btn.setFixedWidth(100)
        cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(save_as_btn)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

    def _populate_tabs(self) -> None:
        self._tabs.clear()

        # General tab (not closable)
        self._general_tab = GeneralTab(self._raw)
        self._tabs.addTab(self._general_tab, "General")
        tab_bar = self._tabs.tabBar()
        if tab_bar:
            tab_bar.setTabButton(0, QTabBar.ButtonPosition.RightSide, None)

        # One tab per Hosts.* section
        for section in self._raw.sections():
            if section.startswith("Hosts."):
                _, name = section.split(".", 1)
                self._tabs.addTab(HostTab(name, self._raw), name)

        # SPICE Proxy tab (not closable)
        proxy_entries = {}
        if "SpiceProxyRedirect" in self._raw:
            proxy_entries = dict(self._raw["SpiceProxyRedirect"])
        self._spice_tab = KeyValueTable("Original  host:port", "Redirect to  host:port", proxy_entries)
        spice_idx = self._tabs.addTab(self._wrap_in_scroll(self._spice_tab), "SPICE Proxy")

        # Extra Params tab (not closable)
        extra_entries = {}
        if "AdditionalParameters" in self._raw:
            extra_entries = dict(self._raw["AdditionalParameters"])
        self._extra_tab = KeyValueTable("Parameter", "Value", extra_entries)
        extra_idx = self._tabs.addTab(self._wrap_in_scroll(self._extra_tab), "Extra Params")

        # Remove close buttons from non-host tabs
        if tab_bar:
            tab_bar.setTabButton(spice_idx, QTabBar.ButtonPosition.RightSide, None)
            tab_bar.setTabButton(extra_idx, QTabBar.ButtonPosition.RightSide, None)

    def _wrap_in_scroll(self, widget: QWidget) -> QWidget:
        """Wrap a widget in a scrollable container with padding."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(widget)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        return scroll

    # ── Tab management ───────────────────────────

    def _host_tab_indices(self) -> list[int]:
        """Return indices of all host tabs (not General/SPICE/Extra)."""
        fixed = {"General", "SPICE Proxy", "Extra Params"}
        return [i for i in range(self._tabs.count()) if self._tabs.tabText(i) not in fixed]

    def _on_tab_close(self, index: int) -> None:
        tab_text = self._tabs.tabText(index)
        if tab_text in ("General", "SPICE Proxy", "Extra Params"):
            return
        reply = QMessageBox.question(
            self,
            "Remove Host",
            f"Remove host '{tab_text}' from the config?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._tabs.removeTab(index)

    def _on_add_host(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Add Host", "Enter a name for the new host cluster:"
        )
        name = name.strip()
        if not ok or not name:
            return
        if "." in name:
            QMessageBox.warning(self, "Invalid Name", "Host cluster names cannot contain a period.")
            return
        # Check for duplicates
        for idx in self._host_tab_indices():
            if self._tabs.tabText(idx) == name:
                QMessageBox.warning(self, "Duplicate", f"A host named '{name}' already exists.")
                return
        new_tab = HostTab(name, self._raw)
        # Insert before SPICE Proxy tab
        spice_idx = next(
            i for i in range(self._tabs.count()) if self._tabs.tabText(i) == "SPICE Proxy"
        )
        self._tabs.insertTab(spice_idx, new_tab, name)
        self._tabs.setCurrentIndex(spice_idx)

    # ── Save / Open ──────────────────────────────

    def _collect_config(self) -> ConfigParser:
        """Read all tabs and return a fresh ConfigParser ready to write."""
        out = ConfigParser(delimiters="=")

        # General
        self._general_tab.write_to(out)

        # Host tabs
        for idx in self._host_tab_indices():
            widget = self._tabs.widget(idx)
            if isinstance(widget, HostTab):
                widget.write_to(out)

        # SPICE Proxy
        proxy = self._spice_tab.get_entries()
        if proxy:
            out.add_section("SpiceProxyRedirect")
            for k, v in proxy.items():
                out["SpiceProxyRedirect"][k] = v

        # Extra Params
        extra = self._extra_tab.get_entries()
        if extra:
            out.add_section("AdditionalParameters")
            for k, v in extra.items():
                out["AdditionalParameters"][k] = v

        return out

    def _write_config(self, path: str, cfg: ConfigParser) -> bool:
        import subprocess
        from io import StringIO

        buf = StringIO()
        cfg.write(buf)
        content = buf.getvalue()

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            # Restrict config to owner-only on Linux — file contains API tokens
            if sys.platform != "win32":
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
            return True
        except PermissionError:
            if sys.platform != "win32":
                # Try writing via pkexec (prompts user for sudo password via GUI)
                try:
                    result = subprocess.run(
                        ["pkexec", "tee", path],
                        input=content.encode("utf-8"),
                        capture_output=True,
                    )
                    if result.returncode == 0:
                        return True
                    QMessageBox.critical(
                        self, "Save Failed",
                        f"Could not write config (pkexec returned {result.returncode}):\n"
                        f"{result.stderr.decode(errors='replace')}",
                    )
                    return False
                except FileNotFoundError:
                    pass  # pkexec not available
            QMessageBox.critical(
                self, "Save Failed",
                f"Permission denied: {path}\n\nRun the config editor as administrator.",
            )
            return False
        except OSError as e:
            QMessageBox.critical(self, "Save Failed", f"Could not write config:\n{e}")
            return False

    def _on_save(self) -> None:
        if not self._config_path:
            self._on_save_as()
            return
        cfg = self._collect_config()
        if self._write_config(self._config_path, cfg):
            QMessageBox.information(self, "Saved", f"Config saved to:\n{self._config_path}")

    def _on_save_as(self) -> None:
        default = self._config_path or _default_config_paths()[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Config As", default, "INI files (*.ini);;All files (*)"
        )
        if not path:
            return
        cfg = self._collect_config()
        if self._write_config(path, cfg):
            self._config_path = path
            self._path_label.setText(path)
            self._update_title()
            QMessageBox.information(self, "Saved", f"Config saved to:\n{path}")

    def _on_open(self) -> None:
        default = self._config_path or _default_config_paths()[0]
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Config File", os.path.dirname(default), "INI files (*.ini);;All files (*)"
        )
        if not path:
            return
        self._config_path = path
        self._raw = self._load(path)
        self._path_label.setText(path)
        self._update_title()
        self._populate_tabs()


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

def main(config_path: Optional[str] = None) -> int:
    app = create_app()
    window = ConfigWindow(config_path)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
