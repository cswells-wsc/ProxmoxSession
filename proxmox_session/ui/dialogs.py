"""
Reusable Qt dialogs — replaces win_popup() and win_popup_button() from PVE-VDIClient.
"""

from PyQt6.QtWidgets import QMessageBox, QWidget


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
