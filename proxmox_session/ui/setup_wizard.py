"""
ProxmoxSession Setup Wizard — 7-page QWizard for first-time Proxmox configuration.

Launched from the config editor's Host tab. Logs in as root (one time), creates
ProxmoxSession groups/roles/ACLs, and creates the initial superadmin and VDI users.
"""

import logging
from typing import Optional

import proxmoxer
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from ..access import (
    PREFIX,
    STANDARD_GROUPS,
    run_full_setup,
    wizard_already_run,
)
from ..config import HostConfig

log = logging.getLogger(__name__)

# Wizard field keys
F_PROXMOX = "proxmox"
F_HOST_CONFIG = "host_config"
F_USERNAME = "root_username"
F_PASSWORD = "root_password"
F_GROUPS = "groups"          # list[dict] of {short_name, comment, role}
F_VM_PATH = "vm_path"
F_SA_USER = "sa_username"
F_SA_PASS = "sa_password"
F_SA_REALM = "sa_realm"
F_SA_EMAIL = "sa_email"
F_SA_FIRST = "sa_firstname"
F_SA_LAST = "sa_lastname"
F_EXTRA_USERS = "extra_users"  # list[dict]
F_RESULTS = "results"


# ─────────────────────────────────────────────────────────────────────────────
# Page 1 — Welcome
# ─────────────────────────────────────────────────────────────────────────────

class WelcomePage(QWizardPage):
    def __init__(self, host_name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setTitle("Proxmox Setup Wizard")
        self.setSubTitle(f"Configure Proxmox VE for ProxmoxSession — {host_name}")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(QLabel(
            "This wizard will configure your Proxmox server to work with ProxmoxSession.\n\n"
            "It will:"
        ))

        steps = QLabel(
            "  • Create ProxmoxSession groups (superadmin, admin, vdiuser)\n"
            "  • Create ProxmoxSession roles with appropriate VM permissions\n"
            "  • Assign group permissions on your VMs\n"
            "  • Create a superadmin account for ongoing management\n"
            "  • Optionally create initial VDI user accounts"
        )
        steps.setStyleSheet("font-family: monospace;")
        layout.addWidget(steps)

        note = QLabel(
            "Root credentials are used only during this wizard and are not stored.\n"
            "After the wizard completes, use the superadmin account for all management."
        )
        note.setStyleSheet("color: gray; font-style: italic;")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()


# ─────────────────────────────────────────────────────────────────────────────
# Page 2 — Root Login
# ─────────────────────────────────────────────────────────────────────────────

class RootLoginPage(QWizardPage):
    def __init__(self, host_config: HostConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setTitle("Connect as Root")
        self.setSubTitle("Enter root credentials to configure the Proxmox server.")
        self._host_config = host_config
        self._proxmox: Optional[proxmoxer.ProxmoxAPI] = None

        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.setSpacing(8)

        # Pre-fill first host from config
        first_host = host_config.hostpool[0]["host"] if host_config.hostpool else ""
        first_port = host_config.hostpool[0].get("port", 8006) if host_config.hostpool else 8006

        self._host = QLineEdit(first_host)
        form.addRow("Host:", self._host)

        self._port = QLineEdit(str(first_port))
        self._port.setFixedWidth(80)
        form.addRow("Port:", self._port)

        self._realm = QComboBox()
        self._realm.addItems(["pam", "pve"])
        form.addRow("Realm:", self._realm)

        self._username = QLineEdit("root")
        form.addRow("Username:", self._username)

        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText("root password")
        form.addRow("Password:", self._password)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self._connect_btn = QPushButton("Test Connection")
        self._connect_btn.clicked.connect(self._on_connect)
        btn_row.addWidget(self._connect_btn)
        self._status = QLabel("")
        btn_row.addWidget(self._status)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        already_run_note = QLabel("")
        already_run_note.setObjectName("already_run_note")
        already_run_note.setWordWrap(True)
        layout.addWidget(already_run_note)
        self._already_run_note = already_run_note
        layout.addStretch()

        # Register fields so wizard can read them
        self.registerField(F_USERNAME, self._username)
        self.registerField(F_PASSWORD + "*", self._password)  # * = mandatory

    def _on_connect(self) -> None:
        self._connect_btn.setEnabled(False)
        self._status.setText("Connecting…")
        self._proxmox = None
        self.completeChanged.emit()

        host = self._host.text().strip()
        port = int(self._port.text().strip() or "8006")
        realm = self._realm.currentText()
        username = self._username.text().strip()
        password = self._password.text()
        user_at_realm = f"{username}@{realm}"

        try:
            px = proxmoxer.ProxmoxAPI(
                host,
                user=user_at_realm,
                password=password,
                verify_ssl=self._host_config.verify_ssl,
                port=port,
            )
            px.version.get()
            self._proxmox = px

            # Warn if wizard already ran
            if wizard_already_run(px):
                self._already_run_note.setText(
                    "Note: ProxmoxSession groups already exist on this server. "
                    "Re-running the wizard is safe — existing objects will be skipped."
                )
                self._already_run_note.setStyleSheet("color: orange;")
            else:
                self._already_run_note.setText("")

            self._status.setText("Connected")
            self._status.setStyleSheet("color: green;")
        except Exception as e:
            self._status.setText(f"Failed: {e}")
            self._status.setStyleSheet("color: red;")

        self._connect_btn.setEnabled(True)
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._proxmox is not None

    def validatePage(self) -> bool:
        if self._proxmox is None:
            return False
        # Store proxmox handle in wizard for subsequent pages
        wiz = self.wizard()
        if wiz:
            wiz.setProperty(F_PROXMOX, self._proxmox)
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Page 3 — Groups
# ─────────────────────────────────────────────────────────────────────────────

class GroupsPage(QWizardPage):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setTitle("Groups")
        self.setSubTitle(
            "Choose which ProxmoxSession groups to create. "
            "superadmin and vdiuser are required."
        )

        layout = QVBoxLayout(self)

        # Table: name, description, role
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Group Name", "Description", "Role"])
        h = self._table.horizontalHeader()
        if h:
            h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        v = self._table.verticalHeader()
        if v:
            v.setVisible(False)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Custom Group")
        add_btn.clicked.connect(self._on_add_custom)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._on_remove)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Pre-populate standard groups
        for short, info in STANDARD_GROUPS.items():
            self._add_row(short, info["comment"], info["role"], locked=short in ("superadmin", "vdiuser"))

    def _add_row(self, short_name: str, comment: str, role: str, locked: bool = False) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        name_item = QTableWidgetItem(f"{PREFIX}{short_name}")
        if locked:
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setForeground(self._table.palette().color(self._table.palette().ColorRole.Mid))
        self._table.setItem(row, 0, name_item)

        desc_item = QTableWidgetItem(comment)
        if locked:
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, 1, desc_item)

        role_combo = QComboBox()
        role_combo.addItems(["ProxmoxSession.VDIUser", "ProxmoxSession.Admin", "ProxmoxSession.SuperAdmin"])
        role_combo.setCurrentText(role)
        if locked:
            role_combo.setEnabled(False)
        self._table.setCellWidget(row, 2, role_combo)

    def _on_add_custom(self) -> None:
        name, ok = QInputDialog.getText(self, "Custom Group", "Group name (will be prefixed with proxmoxsession_):")
        name = name.strip().lower().replace(" ", "_")
        if not ok or not name:
            return
        if name in STANDARD_GROUPS:
            return
        self._add_row(name, f"Custom group: {name}", "ProxmoxSession.VDIUser", locked=False)

    def _on_remove(self) -> None:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()}, reverse=True)
        for row in rows:
            name_item = self._table.item(row, 0)
            if name_item:
                full_name = name_item.text().removeprefix(PREFIX)
                if full_name in ("superadmin", "vdiuser"):
                    continue  # locked
            self._table.removeRow(row)

    def get_groups(self) -> list[dict]:
        groups = []
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, 0)
            desc_item = self._table.item(row, 1)
            role_widget = self._table.cellWidget(row, 2)
            if not name_item:
                continue
            full_name = name_item.text()
            short = full_name.removeprefix(PREFIX)
            role = role_widget.currentText() if isinstance(role_widget, QComboBox) else "ProxmoxSession.VDIUser"
            role_short = role.removeprefix("ProxmoxSession.")
            groups.append({
                "short_name": short,
                "comment": desc_item.text() if desc_item else "",
                "role": role_short,
            })
        return groups


# ─────────────────────────────────────────────────────────────────────────────
# Page 4 — Permissions
# ─────────────────────────────────────────────────────────────────────────────

class PermissionsPage(QWizardPage):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setTitle("VM Permissions")
        self.setSubTitle("Choose which VMs the ProxmoxSession groups can access.")
        self._pools: list[str] = []

        layout = QVBoxLayout(self)

        self._all_radio = QRadioButton("All VMs  (/vms)")
        self._all_radio.setChecked(True)
        self._pool_radio = QRadioButton("Specific resource pool:")
        self._vmid_radio = QRadioButton("Specific VMIDs:")

        self._pool_combo = QComboBox()
        self._pool_combo.setEnabled(False)
        self._vmid_edit = QLineEdit()
        self._vmid_edit.setPlaceholderText("e.g. 100,101,102")
        self._vmid_edit.setEnabled(False)

        self._all_radio.toggled.connect(self._update_state)
        self._pool_radio.toggled.connect(self._update_state)
        self._vmid_radio.toggled.connect(self._update_state)

        layout.addWidget(self._all_radio)
        layout.addWidget(self._pool_radio)
        layout.addWidget(self._pool_combo)
        layout.addWidget(self._vmid_radio)
        layout.addWidget(self._vmid_edit)
        layout.addStretch()

    def initializePage(self) -> None:
        """Load pools from Proxmox when the page is shown."""
        wiz = self.wizard()
        proxmox = wiz.property(F_PROXMOX) if wiz else None
        if proxmox:
            try:
                pools = proxmox.pools.get()
                self._pool_combo.clear()
                for p in pools:
                    self._pool_combo.addItem(p["poolid"])
            except Exception:
                pass

    def _update_state(self) -> None:
        self._pool_combo.setEnabled(self._pool_radio.isChecked())
        self._vmid_edit.setEnabled(self._vmid_radio.isChecked())

    def get_vm_path(self) -> str:
        if self._pool_radio.isChecked() and self._pool_combo.currentText():
            return f"/pool/{self._pool_combo.currentText()}"
        if self._vmid_radio.isChecked():
            # For multiple VMIDs we use /vms as root — individual ACLs applied in access.py
            return "/vms"
        return "/vms"


# ─────────────────────────────────────────────────────────────────────────────
# Page 5 — SuperAdmin User
# ─────────────────────────────────────────────────────────────────────────────

class SuperAdminPage(QWizardPage):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setTitle("Create SuperAdmin Account")
        self.setSubTitle(
            "This account manages ProxmoxSession groups and users. "
            "Use it instead of root for ongoing management."
        )

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)

        self._username = QLineEdit()
        self._username.setPlaceholderText("e.g. ps-admin")
        form.addRow("Username:", self._username)

        self._realm = QComboBox()
        self._realm.addItems(["pve", "pam"])
        form.addRow("Realm:", self._realm)

        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText("Password")
        form.addRow("Password:", self._password)

        self._confirm = QLineEdit()
        self._confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self._confirm.setPlaceholderText("Confirm password")
        form.addRow("Confirm:", self._confirm)

        self._email = QLineEdit()
        self._email.setPlaceholderText("admin@example.com (optional)")
        form.addRow("Email:", self._email)

        name_row = QHBoxLayout()
        self._firstname = QLineEdit()
        self._firstname.setPlaceholderText("First")
        self._lastname = QLineEdit()
        self._lastname.setPlaceholderText("Last")
        name_row.addWidget(self._firstname)
        name_row.addWidget(self._lastname)
        form.addRow("Name:", name_row)

        layout.addLayout(form)

        self._error = QLabel("")
        self._error.setStyleSheet("color: red;")
        layout.addWidget(self._error)
        layout.addStretch()

        self.registerField(F_SA_USER + "*", self._username)
        self.registerField(F_SA_PASS + "*", self._password)
        self.registerField(F_SA_REALM, self._realm, "currentText")
        self.registerField(F_SA_EMAIL, self._email)
        self.registerField(F_SA_FIRST, self._firstname)
        self.registerField(F_SA_LAST, self._lastname)

    def validatePage(self) -> bool:
        if self._password.text() != self._confirm.text():
            self._error.setText("Passwords do not match.")
            return False
        if len(self._password.text()) < 8:
            self._error.setText("Password must be at least 8 characters.")
            return False
        self._error.setText("")
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Page 6 — VDI Users
# ─────────────────────────────────────────────────────────────────────────────

class VDIUsersPage(QWizardPage):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setTitle("Create VDI Users (Optional)")
        self.setSubTitle("Add initial user accounts. You can skip this and add users later.")

        layout = QVBoxLayout(self)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Username", "Password", "Group", "Email"])
        h = self._table.horizontalHeader()
        if h:
            h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        v = self._table.verticalHeader()
        if v:
            v.setVisible(False)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add User")
        add_btn.clicked.connect(self._add_row)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def initializePage(self) -> None:
        """Refresh group list from the groups page."""
        wiz = self.wizard()
        if isinstance(wiz, SetupWizard):
            self._groups = [g["short_name"] for g in wiz.groups_page.get_groups()]
        else:
            self._groups = list(STANDARD_GROUPS.keys())

    def _add_row(self) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(""))

        pw_item = QTableWidgetItem("")
        self._table.setItem(row, 1, pw_item)

        group_combo = QComboBox()
        groups = getattr(self, "_groups", list(STANDARD_GROUPS.keys()))
        group_combo.addItems([f"proxmoxsession_{g}" for g in groups])
        self._table.setCellWidget(row, 2, group_combo)
        self._table.setItem(row, 3, QTableWidgetItem(""))

    def _remove_selected(self) -> None:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()}, reverse=True)
        for row in rows:
            self._table.removeRow(row)

    def get_users(self) -> list[dict]:
        users = []
        for row in range(self._table.rowCount()):
            username_item = self._table.item(row, 0)
            password_item = self._table.item(row, 1)
            group_widget = self._table.cellWidget(row, 2)
            email_item = self._table.item(row, 3)
            username = username_item.text().strip() if username_item else ""
            if not username:
                continue
            group_full = group_widget.currentText() if isinstance(group_widget, QComboBox) else "proxmoxsession_vdiuser"
            short_group = group_full.removeprefix(PREFIX)
            users.append({
                "username": username,
                "password": password_item.text() if password_item else "",
                "short_group": short_group,
                "email": email_item.text().strip() if email_item else "",
                "realm": "pve",
            })
        return users


# ─────────────────────────────────────────────────────────────────────────────
# Page 7 — Summary
# ─────────────────────────────────────────────────────────────────────────────

class SummaryPage(QWizardPage):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setTitle("Setup Complete")
        self.setSubTitle("Review what was created on the Proxmox server.")
        self._complete = False

        layout = QVBoxLayout(self)

        self._status_label = QLabel("Running setup…")
        layout.addWidget(self._status_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._results_label = QLabel("")
        self._results_label.setWordWrap(True)
        self._results_label.setTextFormat(Qt.TextFormat.RichText)
        self._results_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._results_label)
        layout.addWidget(scroll)

    def initializePage(self) -> None:
        """Execute the wizard setup when this page is shown."""
        self._complete = False
        self.completeChanged.emit()
        self._status_label.setText("Running setup on Proxmox server…")
        self._results_label.setText("")

        wiz = self.wizard()
        if not isinstance(wiz, SetupWizard):
            return

        proxmox = wiz.property(F_PROXMOX)
        if not proxmox:
            self._status_label.setText("Error: no Proxmox connection.")
            return

        groups = wiz.groups_page.get_groups()
        vm_path = wiz.permissions_page.get_vm_path()
        extra_users = wiz.users_page.get_users()

        try:
            results = run_full_setup(
                proxmox=proxmox,
                groups_to_create=groups,
                vm_path=vm_path,
                superadmin_username=wiz.field(F_SA_USER),
                superadmin_password=wiz.field(F_SA_PASS),
                superadmin_realm=wiz.field(F_SA_REALM) or "pve",
                superadmin_email=wiz.field(F_SA_EMAIL) or "",
                superadmin_firstname=wiz.field(F_SA_FIRST) or "",
                superadmin_lastname=wiz.field(F_SA_LAST) or "",
                extra_users=extra_users,
            )
            wiz.setProperty(F_RESULTS, results)
            self._render_results(results)
        except Exception as e:
            self._status_label.setText(f"Setup failed: {e}")
            log.exception("Setup wizard failed")

    def _render_results(self, results: dict) -> None:
        lines = []
        created = results.get("created", [])
        skipped = results.get("skipped", [])
        failed = results.get("failed", [])

        if created:
            lines.append("<b>Created:</b>")
            for item in created:
                lines.append(f"  ✓ {item['item']}")
        if skipped:
            lines.append("<br><b>Already existed (skipped):</b>")
            for item in skipped:
                lines.append(f"  · {item['item']}")
        if failed:
            lines.append("<br><b style='color:red'>Failed:</b>")
            for item in failed:
                lines.append(f"  <span style='color:red'>✗ {item['item']}: {item['detail']}</span>")

        self._results_label.setText("<br>".join(lines))

        if failed:
            self._status_label.setText(f"Setup completed with {len(failed)} error(s). See details below.")
            self._status_label.setStyleSheet("color: orange;")
        else:
            self._status_label.setText("Setup completed successfully.")
            self._status_label.setStyleSheet("color: green;")

        self._complete = True
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._complete


# ─────────────────────────────────────────────────────────────────────────────
# SetupWizard — main QWizard
# ─────────────────────────────────────────────────────────────────────────────

class SetupWizard(QWizard):
    def __init__(self, host_config: HostConfig, host_name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(f"ProxmoxSession Setup — {host_name}")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(620, 520)

        self.addPage(WelcomePage(host_name))
        self.addPage(RootLoginPage(host_config))
        self.groups_page = GroupsPage()
        self.addPage(self.groups_page)
        self.permissions_page = PermissionsPage()
        self.addPage(self.permissions_page)
        self.addPage(SuperAdminPage())
        self.users_page = VDIUsersPage()
        self.addPage(self.users_page)
        self.addPage(SummaryPage())
