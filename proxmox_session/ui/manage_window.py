"""
ProxmoxSession Management Window — superadmin UI for managing groups and users.

Accessible from the VM list window header. Requires the user to be a member of
proxmoxsession_superadmin (login prompted on open). Only proxmoxsession_* groups and
their members are shown — root@pam and system users never appear.
"""

import logging
from typing import Optional

import proxmoxer
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QComboBox,
)

from ..access import (
    POOL_NAME,
    PREFIX,
    STANDARD_GROUPS,
    assign_custom_group_permissions,
    assign_vm_to_user,
    create_proxmoxsession_group,
    create_user,
    group_name,
    is_protected,
    list_proxmoxsession_groups,
    list_proxmoxsession_users,
    list_vmids_for_user,
    unassign_vm_from_user,
)
from ..api import VMInfo, get_vms
from ..config import HostConfig

log = logging.getLogger(__name__)


# ── Login dialog ──────────────────────────────────────────────────────────────

class _LoginDialog(QDialog):
    """Prompt for superadmin credentials (not root)."""

    def __init__(
        self,
        host_config: HostConfig,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ProxmoxSession — Management Login")
        self.setMinimumWidth(400)
        self._proxmox: Optional[proxmoxer.ProxmoxAPI] = None
        self._host_config = host_config

        layout = QVBoxLayout(self)

        info = QLabel(
            "Log in as a member of <b>proxmoxsession_superadmin</b> to manage groups and users."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        # Host selector — use first host from pool
        first_host = host_config.hostpool[0] if host_config.hostpool else {"host": "", "port": 8006}
        self._host = QLineEdit(str(first_host["host"]))
        self._port = QLineEdit(str(first_host["port"]))
        self._port.setFixedWidth(70)
        host_row = QHBoxLayout()
        host_row.addWidget(self._host)
        host_row.addWidget(QLabel(":"))
        host_row.addWidget(self._port)
        form.addRow("Host:", host_row)

        self._username = QLineEdit()
        self._username.setPlaceholderText("e.g. admin@pve")
        form.addRow("Username:", self._username)

        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password:", self._password)

        layout.addLayout(form)

        self._status = QLabel("")
        self._status.setStyleSheet("color: red;")
        layout.addWidget(self._status)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_login)
        btns.rejected.connect(self.reject)
        self._ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
        if self._ok_btn:
            self._ok_btn.setText("Connect")
        layout.addWidget(btns)

        self._username.returnPressed.connect(self._password.setFocus)
        self._password.returnPressed.connect(self._on_login)

    def _on_login(self) -> None:
        host = self._host.text().strip()
        password = self._password.text()
        username = self._username.text().strip()
        if not host or not username or not password:
            self._status.setText("All fields are required.")
            return
        try:
            port = int(self._port.text())
        except ValueError:
            port = 8006

        if self._ok_btn:
            self._ok_btn.setEnabled(False)
        self._status.setText("Connecting…")
        self.repaint()

        # Split user@realm
        if "@" in username:
            user_part, realm = username.rsplit("@", 1)
        else:
            user_part, realm = username, self._host_config.backend

        try:
            px = proxmoxer.ProxmoxAPI(
                host,
                port=port,
                user=f"{user_part}@{realm}",
                password=password,
                verify_ssl=self._host_config.verify_ssl,
                timeout=15,
            )
            px.version.get()  # validate connection

            # Verify user is actually in superadmin group
            uid = f"{user_part}@{realm}"
            superadmin_gid = group_name("superadmin")
            users = px.access.users.get(full=1)
            user_data = next((u for u in users if u.get("userid") == uid), None)
            if user_data:
                groups = set(user_data.get("groups", "").split(",")) if user_data.get("groups") else set()
                if superadmin_gid not in groups:
                    self._status.setText("This user is not a member of proxmoxsession_superadmin.")
                    if self._ok_btn:
                        self._ok_btn.setEnabled(True)
                    return

            self._proxmox = px
            self.accept()
        except proxmoxer.AuthenticationError:
            self._status.setText("Authentication failed — check username/password.")
        except Exception as e:
            self._status.setText(f"Connection error: {e}")
        finally:
            if self._ok_btn:
                self._ok_btn.setEnabled(True)

    @property
    def proxmox(self) -> Optional[proxmoxer.ProxmoxAPI]:
        return self._proxmox


# ── Groups tab ────────────────────────────────────────────────────────────────

class _GroupsTab(QWidget):
    """List, create, and delete proxmoxsession_* groups; manage membership."""

    def __init__(
        self,
        proxmox: proxmoxer.ProxmoxAPI,
        vm_path: str = "/vms",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._proxmox = proxmox
        self._vm_path = vm_path
        self._selected_group: Optional[str] = None

        layout = QHBoxLayout(self)

        # ── Left: group list ──
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Groups</b>"))
        self._group_list = QListWidget()
        self._group_list.currentItemChanged.connect(self._on_group_selected)
        left.addWidget(self._group_list)

        group_btns = QHBoxLayout()
        add_grp_btn = QPushButton("Add Group")
        add_grp_btn.clicked.connect(self._on_add_group)
        del_grp_btn = QPushButton("Delete Group")
        del_grp_btn.clicked.connect(self._on_delete_group)
        group_btns.addWidget(add_grp_btn)
        group_btns.addWidget(del_grp_btn)
        left.addLayout(group_btns)
        layout.addLayout(left, 1)

        # ── Right: members of selected group ──
        right = QVBoxLayout()
        self._members_label = QLabel("<b>Members</b>")
        right.addWidget(self._members_label)
        self._members_list = QListWidget()
        right.addWidget(self._members_list)

        member_btns = QHBoxLayout()
        add_mem_btn = QPushButton("Add Member…")
        add_mem_btn.clicked.connect(self._on_add_member)
        remove_mem_btn = QPushButton("Remove Member")
        remove_mem_btn.clicked.connect(self._on_remove_member)
        member_btns.addWidget(add_mem_btn)
        member_btns.addWidget(remove_mem_btn)
        right.addLayout(member_btns)
        layout.addLayout(right, 1)

        self._refresh_groups()

    def _refresh_groups(self) -> None:
        self._group_list.clear()
        for g in list_proxmoxsession_groups(self._proxmox):
            self._group_list.addItem(g["groupid"])
        self._members_list.clear()
        self._selected_group = None

    def _on_group_selected(self, current: Optional[QListWidgetItem], _prev: object) -> None:
        if current is None:
            self._members_list.clear()
            self._selected_group = None
            return
        gid = current.text()
        self._selected_group = gid
        self._members_label.setText(f"<b>Members of {gid}</b>")
        self._refresh_members(gid)

    def _refresh_members(self, gid: str) -> None:
        self._members_list.clear()
        try:
            group_data = self._proxmox.access.groups(gid).get()
            members_str = group_data.get("members", "")
            if members_str:
                for uid in members_str.split(","):
                    uid = uid.strip()
                    if uid and not is_protected(uid):
                        self._members_list.addItem(uid)
        except Exception as e:
            log.warning("Could not load members for %s: %s", gid, e)

    def _on_add_group(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Add Group", "Short group name (will be prefixed proxmoxsession_):"
        )
        name = name.strip().lower().replace(" ", "_")
        if not ok or not name:
            return
        if name in STANDARD_GROUPS:
            QMessageBox.warning(self, "Reserved", f"'{name}' is a reserved group name.")
            return

        role, ok2 = QInputDialog.getItem(
            self,
            "Assign Role",
            "Select role for this group:",
            ["VDIUser", "Admin", "SuperAdmin"],
            0,
            False,
        )
        if not ok2:
            return

        try:
            create_proxmoxsession_group(self._proxmox, name)
            assign_custom_group_permissions(self._proxmox, name, role, self._vm_path)
            self._refresh_groups()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not create group:\n{e}")

    def _on_delete_group(self) -> None:
        if not self._selected_group:
            return
        gid = self._selected_group
        # Protect standard groups
        short = gid[len(PREFIX):] if gid.startswith(PREFIX) else gid
        if short in STANDARD_GROUPS:
            QMessageBox.warning(
                self, "Protected",
                f"'{gid}' is a standard ProxmoxSession group and cannot be deleted here.\n"
                "Remove it manually in the Proxmox web UI if needed."
            )
            return
        reply = QMessageBox.question(
            self, "Delete Group",
            f"Delete group '{gid}'?\n\nThis will remove the group from Proxmox. "
            "Members will lose access.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._proxmox.access.groups(gid).delete()
            self._refresh_groups()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not delete group:\n{e}")

    def _on_add_member(self) -> None:
        if not self._selected_group:
            QMessageBox.information(self, "No Group", "Select a group first.")
            return
        gid = self._selected_group
        # Build list of proxmoxsession users not already in this group
        try:
            ps_users = list_proxmoxsession_users(self._proxmox)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not list users:\n{e}")
            return

        group_data = {}
        try:
            group_data = self._proxmox.access.groups(gid).get()
        except Exception:
            pass
        current_members = set()
        members_str = group_data.get("members", "")
        if members_str:
            current_members = {u.strip() for u in members_str.split(",") if u.strip()}

        available = [u["userid"] for u in ps_users if u["userid"] not in current_members]
        if not available:
            QMessageBox.information(self, "No Users", "No additional ProxmoxSession users to add.")
            return

        uid, ok = QInputDialog.getItem(
            self, "Add Member", f"Select user to add to {gid}:", available, 0, False
        )
        if not ok or not uid:
            return
        try:
            # Add user to group by updating their groups list
            user_data = self._proxmox.access.users(uid).get()
            existing_groups = user_data.get("groups", "")
            existing_list = [g.strip() for g in existing_groups.split(",") if g.strip()] if existing_groups else []
            if gid not in existing_list:
                existing_list.append(gid)
            self._proxmox.access.users(uid).put(groups=",".join(existing_list))
            self._refresh_members(gid)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not add member:\n{e}")

    def _on_remove_member(self) -> None:
        if not self._selected_group:
            return
        gid = self._selected_group
        item = self._members_list.currentItem()
        if not item:
            return
        uid = item.text()
        try:
            user_data = self._proxmox.access.users(uid).get()
            existing_groups = user_data.get("groups", "")
            existing_list = [g.strip() for g in existing_groups.split(",") if g.strip()] if existing_groups else []
            if gid in existing_list:
                existing_list.remove(gid)
            self._proxmox.access.users(uid).put(groups=",".join(existing_list))
            self._refresh_members(gid)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not remove member:\n{e}")


# ── Users tab ─────────────────────────────────────────────────────────────────

class _UsersTab(QWidget):
    """List, create, and delete users in proxmoxsession_* groups."""

    def __init__(
        self,
        proxmox: proxmoxer.ProxmoxAPI,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._proxmox = proxmox

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<b>ProxmoxSession Users</b> (root@pam and system users are never shown)"))

        self._user_list = QListWidget()
        layout.addWidget(self._user_list)

        btns = QHBoxLayout()
        add_btn = QPushButton("Add User…")
        add_btn.clicked.connect(self._on_add_user)
        del_btn = QPushButton("Delete User")
        del_btn.clicked.connect(self._on_delete_user)
        reset_btn = QPushButton("Reset Password…")
        reset_btn.clicked.connect(self._on_reset_password)
        btns.addWidget(add_btn)
        btns.addWidget(del_btn)
        btns.addWidget(reset_btn)
        btns.addStretch()
        layout.addLayout(btns)

        self._refresh_users()

    def _refresh_users(self) -> None:
        self._user_list.clear()
        try:
            for u in list_proxmoxsession_users(self._proxmox):
                uid = u.get("userid", "")
                groups = u.get("groups", "")
                item = QListWidgetItem(f"{uid}   [{groups}]")
                item.setData(Qt.ItemDataRole.UserRole, uid)
                self._user_list.addItem(item)
        except Exception as e:
            log.warning("Could not list users: %s", e)

    def _on_add_user(self) -> None:
        dlg = _AddUserDialog(self._proxmox, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh_users()

    def _on_delete_user(self) -> None:
        item = self._user_list.currentItem()
        if not item:
            return
        uid = item.data(Qt.ItemDataRole.UserRole)
        if is_protected(uid):
            return
        reply = QMessageBox.question(
            self, "Delete User",
            f"Delete user '{uid}'?\n\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._proxmox.access.users(uid).delete()
            self._refresh_users()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not delete user:\n{e}")

    def _on_reset_password(self) -> None:
        item = self._user_list.currentItem()
        if not item:
            return
        uid = item.data(Qt.ItemDataRole.UserRole)
        if is_protected(uid):
            return
        new_pw, ok = QInputDialog.getText(
            self, "Reset Password",
            f"Enter new password for {uid}:",
            QLineEdit.EchoMode.Password,
        )
        if not ok or not new_pw:
            return
        if len(new_pw) < 8:
            QMessageBox.warning(self, "Too Short", "Password must be at least 8 characters.")
            return
        try:
            self._proxmox.access.users(uid).put(password=new_pw)
            QMessageBox.information(self, "Done", f"Password updated for {uid}.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not reset password:\n{e}")


# ── Add user dialog ───────────────────────────────────────────────────────────

class _AddUserDialog(QDialog):
    def __init__(self, proxmox: proxmoxer.ProxmoxAPI, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add User")
        self.setMinimumWidth(380)
        self._proxmox = proxmox

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._username = QLineEdit()
        self._username.setPlaceholderText("e.g. jsmith")
        form.addRow("Username:", self._username)

        self._realm = QComboBox()
        self._realm.addItems(["pve", "pam"])
        self._realm.setEditable(True)
        form.addRow("Realm:", self._realm)

        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password:", self._password)

        self._confirm = QLineEdit()
        self._confirm.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Confirm Password:", self._confirm)

        # Group selector
        self._group = QComboBox()
        try:
            for g in list_proxmoxsession_groups(proxmox):
                self._group.addItem(g["groupid"])
        except Exception:
            pass
        form.addRow("Group:", self._group)

        self._email = QLineEdit()
        self._email.setPlaceholderText("optional")
        form.addRow("Email:", self._email)

        self._firstname = QLineEdit()
        form.addRow("First Name:", self._firstname)

        self._lastname = QLineEdit()
        form.addRow("Last Name:", self._lastname)

        layout.addLayout(form)

        self._status = QLabel("")
        self._status.setStyleSheet("color: red;")
        layout.addWidget(self._status)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_accept(self) -> None:
        username = self._username.text().strip()
        password = self._password.text()
        confirm = self._confirm.text()
        realm = self._realm.currentText().strip() or "pve"
        group_full = self._group.currentText()

        if not username:
            self._status.setText("Username is required.")
            return
        if not password:
            self._status.setText("Password is required.")
            return
        if password != confirm:
            self._status.setText("Passwords do not match.")
            return
        if len(password) < 8:
            self._status.setText("Password must be at least 8 characters.")
            return
        if not group_full:
            self._status.setText("Select a group.")
            return

        # group_full is already the full groupid like proxmoxsession_vdiuser
        # create_user wants the short name — strip PREFIX
        short_group = group_full[len(PREFIX):] if group_full.startswith(PREFIX) else group_full

        try:
            create_user(
                self._proxmox,
                username,
                password,
                short_group,
                realm=realm,
                email=self._email.text().strip(),
                firstname=self._firstname.text().strip(),
                lastname=self._lastname.text().strip(),
            )
            self.accept()
        except ValueError as e:
            self._status.setText(str(e))
        except proxmoxer.core.ResourceException as e:
            if e.status_code == 409:
                self._status.setText(f"User {username}@{realm} already exists.")
            else:
                self._status.setText(f"Error: {e}")
        except Exception as e:
            self._status.setText(f"Error: {e}")


# ── VM Assignments tab ────────────────────────────────────────────────────────

class _VMAssignmentsTab(QWidget):
    """
    Assign and unassign VMs and templates to individual VDI users.

    Left panel: VMs/templates in the proxmoxsession_resources pool (unassigned to selected user).
    Right panel: VMs/templates already assigned to the selected user.
    Top: user selector dropdown.
    """

    def __init__(
        self,
        proxmox: proxmoxer.ProxmoxAPI,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._proxmox = proxmox
        self._pool_vms: list[VMInfo] = []   # all VMs in pool
        self._selected_user: str = ""

        layout = QVBoxLayout(self)

        # User selector
        user_row = QHBoxLayout()
        user_row.addWidget(QLabel("User:"))
        self._user_combo = QComboBox()
        self._user_combo.setMinimumWidth(200)
        self._user_combo.currentIndexChanged.connect(self._on_user_changed)
        user_row.addWidget(self._user_combo)
        refresh_users_btn = QPushButton("Refresh Users")
        refresh_users_btn.clicked.connect(self._refresh_users)
        user_row.addWidget(refresh_users_btn)
        user_row.addStretch()
        layout.addLayout(user_row)

        # Two-panel layout: pool VMs (left) ↔ assigned to user (right)
        panels = QHBoxLayout()

        # Left: available in pool
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Pool VMs &amp; Templates</b><br><small>(not yet assigned to user)</small>"))
        self._pool_list = QListWidget()
        left.addWidget(self._pool_list)
        assign_btn = QPushButton("Assign →")
        assign_btn.clicked.connect(self._on_assign)
        left.addWidget(assign_btn)
        panels.addLayout(left)

        # Right: assigned to this user
        right = QVBoxLayout()
        right.addWidget(QLabel("<b>Assigned to User</b>"))
        self._assigned_list = QListWidget()
        right.addWidget(self._assigned_list)
        unassign_btn = QPushButton("← Unassign")
        unassign_btn.clicked.connect(self._on_unassign)
        right.addWidget(unassign_btn)
        panels.addLayout(right)

        layout.addLayout(panels, 1)

        note = QLabel(
            "Assigning a VM grants the user <b>ProxmoxSession.VDIUser</b> role on that specific VM only. "
            "Unassigning removes that ACL. Changes take effect immediately."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(note)

        self._refresh_users()
        self._refresh_pool_vms()

    def _refresh_users(self) -> None:
        current = self._user_combo.currentText()
        self._user_combo.blockSignals(True)
        self._user_combo.clear()
        try:
            for u in list_proxmoxsession_users(self._proxmox):
                uid = u.get("userid", "")
                if uid:
                    self._user_combo.addItem(uid)
        except Exception as e:
            log.warning("Could not list users: %s", e)
        # Restore previous selection
        idx = self._user_combo.findText(current)
        if idx >= 0:
            self._user_combo.setCurrentIndex(idx)
        self._user_combo.blockSignals(False)
        self._on_user_changed()

    def _refresh_pool_vms(self) -> None:
        """Fetch all VMs/templates from the pool."""
        try:
            all_vms = get_vms(self._proxmox, guest_type="both", include_templates=True)
            # Filter to pool only — check if VM is in proxmoxsession_resources pool
            pool_vmids = self._get_pool_vmids()
            self._pool_vms = [v for v in all_vms if v.vmid in pool_vmids]
        except Exception as e:
            log.warning("Could not list pool VMs: %s", e)
            self._pool_vms = []
        self._refresh_panels()

    def _get_pool_vmids(self) -> set[int]:
        """Return set of VMIDs that are members of the resource pool."""
        try:
            pool_data = self._proxmox.pools(POOL_NAME).get()
            members = pool_data.get("members", [])
            return {int(m["vmid"]) for m in members if "vmid" in m}
        except Exception:
            return set()

    def _on_user_changed(self) -> None:
        self._selected_user = self._user_combo.currentText()
        self._refresh_panels()

    def _refresh_panels(self) -> None:
        if not self._selected_user:
            self._pool_list.clear()
            self._assigned_list.clear()
            return

        try:
            assigned_ids = set(list_vmids_for_user(self._proxmox, self._selected_user))
        except Exception:
            assigned_ids = set()

        self._pool_list.clear()
        self._assigned_list.clear()

        for vm in sorted(self._pool_vms, key=lambda v: (not v.is_template, v.name.lower())):
            tag = " [Template]" if vm.is_template else f" [{vm.status}]"
            label = f"{vm.name}{tag} (ID {vm.vmid})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, vm.vmid)
            if vm.vmid in assigned_ids:
                self._assigned_list.addItem(item)
            else:
                self._pool_list.addItem(item)

    def _on_assign(self) -> None:
        item = self._pool_list.currentItem()
        if not item or not self._selected_user:
            return
        vmid = int(item.data(Qt.ItemDataRole.UserRole))
        try:
            assign_vm_to_user(self._proxmox, self._selected_user, vmid)
            self._refresh_panels()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not assign VM:\n{e}")

    def _on_unassign(self) -> None:
        item = self._assigned_list.currentItem()
        if not item or not self._selected_user:
            return
        vmid = int(item.data(Qt.ItemDataRole.UserRole))
        try:
            unassign_vm_from_user(self._proxmox, self._selected_user, vmid)
            self._refresh_panels()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not unassign VM:\n{e}")


# ── Main management window ────────────────────────────────────────────────────

class ManageWindow(QDialog):
    """
    Post-setup management window for proxmoxsession_superadmin members.

    Opens with a login prompt. On success shows Groups and Users tabs, both
    scoped to proxmoxsession_* resources only.
    """

    def __init__(
        self,
        host_config: HostConfig,
        vm_path: str = "/vms",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ProxmoxSession — Manage Groups & Users")
        self.setMinimumSize(700, 500)
        self._host_config = host_config
        self._vm_path = vm_path
        self._proxmox: Optional[proxmoxer.ProxmoxAPI] = None

        layout = QVBoxLayout(self)

        # Placeholder shown before login
        self._login_placeholder = QLabel(
            "Connect as a proxmoxsession_superadmin member to manage groups and users."
        )
        self._login_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._login_placeholder)

        # Tabs (hidden until login succeeds)
        self._tabs = QTabWidget()
        self._tabs.setVisible(False)
        layout.addWidget(self._tabs, 1)

        # Bottom buttons
        btn_row = QHBoxLayout()
        self._login_btn = QPushButton("Connect…")
        self._login_btn.clicked.connect(self._on_login)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._on_refresh)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(self._login_btn)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _on_login(self) -> None:
        dlg = _LoginDialog(self._host_config, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._proxmox = dlg.proxmox
        if self._proxmox is None:
            return
        self._login_placeholder.setVisible(False)
        self._login_btn.setText("Re-connect")
        self._build_tabs()
        self._tabs.setVisible(True)

    def _build_tabs(self) -> None:
        self._tabs.clear()
        if self._proxmox is None:
            return
        groups_tab = _GroupsTab(self._proxmox, self._vm_path, self)
        self._tabs.addTab(groups_tab, "Groups")
        users_tab = _UsersTab(self._proxmox, self)
        self._tabs.addTab(users_tab, "Users")
        assignments_tab = _VMAssignmentsTab(self._proxmox, self)
        self._tabs.addTab(assignments_tab, "VM Assignments")

    def _on_refresh(self) -> None:
        if self._proxmox is None:
            return
        self._build_tabs()
