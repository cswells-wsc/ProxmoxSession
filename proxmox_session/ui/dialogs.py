"""
Reusable Qt dialogs — replaces win_popup() and win_popup_button() from PVE-VDIClient.
"""

from typing import Optional

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
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
