"""
Reusable Qt dialogs — replaces win_popup() and win_popup_button() from PVE-VDIClient.
"""

from typing import Optional

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)


def show_error(parent: QWidget | None, message: str, title: str = "Error") -> None:
    """Show a modal error dialog and wait for the user to dismiss it."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def show_info(parent: QWidget | None, message: str, title: str = "Information") -> None:
    """Show a modal info dialog."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(QMessageBox.Icon.Information)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def ask_yes_no(parent: QWidget | None, message: str, title: str = "Confirm") -> bool:
    """Show a Yes/No dialog. Returns True if Yes was clicked."""
    result = QMessageBox.question(
        parent,
        title,
        message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return result == QMessageBox.StandardButton.Yes


class ConnectDialog(QDialog):
    """
    Pre-connection dialog shown before launching remote-viewer.
    Lets the user enable USB redirection for this session.

    Usage:
        dlg = ConnectDialog(parent, vm_name="web-server", usb_default=False)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            use dlg.usb_enabled
    """

    def __init__(
        self,
        parent: Optional[QWidget],
        vm_name: str,
        usb_default: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Connect — {vm_name}")
        self.setMinimumWidth(340)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 16)

        layout.addWidget(QLabel(f"<b>{vm_name}</b>"))

        self._usb = QCheckBox("Enable USB Redirection")
        self._usb.setChecked(usb_default)
        layout.addWidget(self._usb)

        note = QLabel(
            "Allows attaching USB devices from this machine to the VM\n"
            "via the remote-viewer toolbar. Requires USB redirection\n"
            "devices configured in the VM's Proxmox hardware settings."
        )
        note.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn:
            ok_btn.setText("Connect")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def usb_enabled(self) -> bool:
        return self._usb.isChecked()


class DeployVMDialog(QDialog):
    """
    Dialog shown when a user wants to clone a template into a new VM.

    Usage:
        dlg = DeployVMDialog(parent, template_name="win11-template")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name = dlg.vm_name
            full_clone = dlg.full_clone
    """

    def __init__(
        self,
        parent: Optional[QWidget],
        template_name: str,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Deploy VM — {template_name}")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 16)

        layout.addWidget(QLabel(f"Create a new VM from template <b>{template_name}</b>"))

        form = QFormLayout()
        form.setSpacing(8)

        self._name = QLineEdit(f"vm-from-{template_name.lower().replace(' ', '-')[:30]}")
        self._name.setPlaceholderText("VM name")
        self._name.selectAll()
        form.addRow("New VM name:", self._name)

        self._full_clone = QCheckBox("Full clone (independent copy — recommended)")
        self._full_clone.setChecked(True)
        form.addRow("", self._full_clone)

        layout.addLayout(form)

        note = QLabel(
            "The VM will be placed in the proxmoxsession_resources pool.\n"
            "An administrator may need to activate it before you can connect."
        )
        note.setStyleSheet("color: gray; font-size: 11px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._status = QLabel("")
        self._status.setStyleSheet("color: red;")
        layout.addWidget(self._status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn:
            ok_btn.setText("Deploy")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        name = self._name.text().strip()
        if not name:
            self._status.setText("VM name is required.")
            return
        # Basic name validation (Proxmox allows alphanumeric, dash, dot)
        import re
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-\.]{0,62}$", name):
            self._status.setText("Name must start with a letter/digit and contain only letters, digits, dashes, and dots.")
            return
        self.accept()

    @property
    def vm_name(self) -> str:
        return self._name.text().strip()

    @property
    def full_clone(self) -> bool:
        return self._full_clone.isChecked()
