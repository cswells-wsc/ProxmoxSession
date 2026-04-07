"""
Login window — cluster selection, username/password/TOTP, and authentication.
"""

import subprocess
import sys
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..auth import authenticate
from ..config import AppConfig
from .dialogs import show_error


class LoginWindow(QDialog):
    """
    Modal login dialog. On successful auth, stores the proxmox handle
    on self.proxmox and self.current_hostset.

    Result codes:
      Accepted      — authenticated successfully
      Rejected      — user cancelled
      ClusterChanged — user switched cluster; re-open with updated current_hostset
    """

    ClusterChanged = 2

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config = config
        self.proxmox = None
        self.current_hostset = config.current_hostset

        self.setWindowTitle(config.title)
        # Kiosk (frameless) only applies on Linux session deployments.
        # On Windows the app is a normal windowed application.
        if config.kiosk and sys.platform != "win32":
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)

        self._build_ui()

    def _build_ui(self):
        cfg = self.config
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(24, 24, 24, 24)

        # Logo + title row
        header = QHBoxLayout()
        if cfg.logo:
            logo_lbl = QLabel()
            logo_lbl.setPixmap(QPixmap(cfg.logo).scaledToHeight(48, Qt.TransformationMode.SmoothTransformation))
            header.addWidget(logo_lbl)
        title_lbl = QLabel(cfg.title)
        title_lbl.setStyleSheet("font-size: 20px; font-weight: bold;")
        header.addWidget(title_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()
        root.addLayout(header)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)

        # Cluster selector (only shown when >1 cluster)
        if len(cfg.hosts) > 1:
            self._cluster_combo = QComboBox()
            for name in cfg.hosts:
                self._cluster_combo.addItem(name)
            self._cluster_combo.setCurrentText(self.current_hostset)
            self._cluster_combo.currentTextChanged.connect(self._on_cluster_changed)
            form.addRow("Server Group:", self._cluster_combo)

        host = cfg.hosts[self.current_hostset]
        readonly = bool(host.user and host.token_name and host.token_value)

        self._username = QLineEdit(host.user)
        self._username.setReadOnly(readonly)
        self._username.setPlaceholderText("username")
        form.addRow("Username:", self._username)

        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setReadOnly(readonly)
        self._password.setPlaceholderText("password")
        form.addRow("Password:", self._password)

        self._totp_row_label = QLabel("OTP Key:")
        self._totp = QLineEdit()
        self._totp.setPlaceholderText("6-digit code")
        form.addRow(self._totp_row_label, self._totp)
        self._set_totp_visible(host.totp)

        root.addLayout(form)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._login_btn = QPushButton("Log In")
        self._login_btn.setDefault(True)
        self._login_btn.clicked.connect(self._on_login)
        btn_row.addWidget(self._login_btn)

        if not cfg.kiosk:
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(self.reject)
            btn_row.addWidget(cancel_btn)

        if host.pwresetcmd:
            pw_reset_btn = QPushButton("Password Reset")
            pw_reset_btn.clicked.connect(self._on_pw_reset)
            btn_row.addWidget(pw_reset_btn)

        root.addLayout(btn_row)
        self.setMinimumWidth(360)

    def _set_totp_visible(self, visible: bool):
        self._totp_row_label.setVisible(visible)
        self._totp.setVisible(visible)

    def _on_cluster_changed(self, name: str):
        self.current_hostset = name
        # Close and reopen: the caller checks current_hostset after rejection
        # to decide whether to re-show the dialog with the new cluster selected.
        self.done(LoginWindow.ClusterChanged)

    def _on_login(self):
        username = self._username.text().strip()
        password = self._password.text()
        totp = self._totp.text().strip() or None

        host = self.config.hosts[self.current_hostset]

        self._login_btn.setEnabled(False)
        self._login_btn.setText("Authenticating…")

        result = authenticate(host, username, password=password, totp=totp)

        self._login_btn.setEnabled(True)
        self._login_btn.setText("Log In")

        if result.success:
            self.proxmox = result.proxmox
            self.accept()
        elif result.connected and not result.success:
            show_error(self, "Invalid username and/or password, please try again.")
        else:
            show_error(
                self,
                f"Unable to connect to any VDI server. Are you on the correct network?\n\n{result.error}",
            )

    def _on_pw_reset(self):
        host = self.config.hosts[self.current_hostset]
        if host.pwresetcmd:
            try:
                subprocess.check_call(host.pwresetcmd, shell=True)
            except Exception as e:
                show_error(self, f"Unable to open password reset:\n{e}")
