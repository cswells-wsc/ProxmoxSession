"""
QApplication setup and QSS theme loading.
"""

import os
import sys

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QComboBox


class _NoScrollComboFilter(QObject):
    """
    Application-level event filter that prevents the scroll wheel from
    changing QComboBox values unless the widget has keyboard focus.
    This stops accidental value changes when scrolling past a dropdown.
    """

    def eventFilter(self, obj: QObject | None, event: QEvent | None) -> bool:
        if isinstance(obj, QComboBox) and event is not None:
            if event.type() == QEvent.Type.Wheel and not obj.hasFocus():
                return True  # swallow the event
        return False

# Dark and light QSS stylesheets
_DARK_QSS = """
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Segoe UI", "Ubuntu", sans-serif;
    font-size: 13px;
}
QLineEdit, QComboBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
    color: #cdd6f4;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #89b4fa;
}
QPushButton {
    background-color: #89b4fa;
    color: #1e1e2e;
    border: none;
    border-radius: 4px;
    padding: 6px 18px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #b4befe;
}
QPushButton:pressed {
    background-color: #74c7ec;
}
QPushButton:disabled {
    background-color: #45475a;
    color: #6c7086;
}
QLabel {
    color: #cdd6f4;
}
QTableWidget {
    background-color: #181825;
    gridline-color: #313244;
    border: none;
}
QTableWidget::item:selected {
    background-color: #45475a;
}
QHeaderView::section {
    background-color: #313244;
    color: #bac2de;
    padding: 4px;
    border: none;
}
QScrollBar:vertical {
    background: #1e1e2e;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 4px;
}
"""

_LIGHT_QSS = """
QWidget {
    background-color: #eff1f5;
    color: #4c4f69;
    font-family: "Segoe UI", "Ubuntu", sans-serif;
    font-size: 13px;
}
QLineEdit, QComboBox {
    background-color: #ffffff;
    border: 1px solid #bcc0cc;
    border-radius: 4px;
    padding: 4px 8px;
    color: #4c4f69;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #1e66f5;
}
QPushButton {
    background-color: #1e66f5;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 6px 18px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #04a5e5;
}
QPushButton:pressed {
    background-color: #7287fd;
}
QPushButton:disabled {
    background-color: #bcc0cc;
    color: #9ca0b0;
}
QTableWidget {
    background-color: #ffffff;
    gridline-color: #dce0e8;
    border: none;
}
QTableWidget::item:selected {
    background-color: #ccd0da;
}
QHeaderView::section {
    background-color: #e6e9ef;
    color: #4c4f69;
    padding: 4px;
    border: none;
}
"""


def create_app(theme: str = "system", icon_path: str | None = None) -> QApplication:
    """
    Create and configure the QApplication.
    theme: "dark", "light", or "system" (follows OS preference).
    """
    existing = QApplication.instance()
    app: QApplication = existing if isinstance(existing, QApplication) else QApplication(sys.argv)

    # Prevent scroll wheel from changing combo box values unless focused
    _filter = _NoScrollComboFilter(app)
    app.installEventFilter(_filter)

    resolved = theme.lower()
    if resolved == "system":
        # Detect system preference via palette lightness
        palette = app.palette()
        bg = palette.window().color()
        resolved = "dark" if bg.lightness() < 128 else "light"

    if resolved == "dark":
        app.setStyleSheet(_DARK_QSS)
    else:
        app.setStyleSheet(_LIGHT_QSS)

    if icon_path and os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    return app
