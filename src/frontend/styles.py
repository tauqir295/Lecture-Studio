"""Theme stylesheets (Dark and Light) for PPT Lecture Studio."""

DARK_THEME = """
QWidget {
    background-color: #1e1e24;
    color: #f0f0f5;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
}

QMainWindow, QDialog {
    background-color: #18181c;
}

QListWidget {
    background-color: #24242c;
    border: 1px solid #32323e;
    border-radius: 8px;
    padding: 6px;
    outline: none;
}

QListWidget::item {
    border-radius: 6px;
    padding: 10px 12px;
    margin-bottom: 4px;
    color: #c4c4d4;
}

QListWidget::item:hover {
    background-color: #2e2e3a;
    color: #ffffff;
}

QListWidget::item:selected {
    background-color: #2563eb;
    color: #ffffff;
    font-weight: bold;
}

QPushButton {
    background-color: #2b2b36;
    color: #f0f0f5;
    border: 1px solid #3c3c4c;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #383848;
    border-color: #4f4f66;
}

QPushButton:pressed {
    background-color: #20202a;
}

QPushButton:disabled {
    background-color: #1a1a20;
    color: #606070;
    border-color: #262630;
}

QPushButton#primaryBtn {
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #1d4ed8;
    font-weight: bold;
}

QPushButton#primaryBtn:hover {
    background-color: #1d4ed8;
}

QPushButton#successBtn {
    background-color: #059669;
    color: #ffffff;
    border: 1px solid #047857;
    font-weight: bold;
}

QPushButton#successBtn:hover {
    background-color: #047857;
}

QPushButton#dangerBtn {
    background-color: #dc2626;
    color: #ffffff;
    border: 1px solid #b91c1c;
}

QPushButton#dangerBtn:hover {
    background-color: #b91c1c;
}

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background-color: #252530;
    border: 1px solid #3c3c4e;
    border-radius: 6px;
    padding: 8px;
    color: #f0f0f5;
    selection-background-color: #2563eb;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1px solid #3b82f6;
    background-color: #282836;
}

QTableWidget {
    background-color: #22222a;
    border: 1px solid #323240;
    border-radius: 8px;
    gridline-color: #2e2e3c;
}

QTableWidget::item {
    padding: 10px;
}

QTableWidget::item:selected {
    background-color: #1e3a8a;
    color: #ffffff;
}

QHeaderView::section {
    background-color: #1c1c24;
    color: #9ca3af;
    padding: 8px;
    border: none;
    font-weight: bold;
}

QProgressBar {
    background-color: #262632;
    border: 1px solid #383848;
    border-radius: 6px;
    text-align: center;
    color: #ffffff;
    height: 18px;
}

QProgressBar::chunk {
    background-color: #2563eb;
    border-radius: 5px;
}

QScrollBar:vertical {
    background: #1e1e24;
    width: 10px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #3b3b4c;
    min-height: 20px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #505068;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QSplitter::handle {
    background-color: #2c2c38;
}

QGroupBox {
    border: 1px solid #343444;
    border-radius: 8px;
    margin-top: 18px;
    padding-top: 14px;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 10px;
    color: #93c5fd;
}
"""

LIGHT_THEME = """
QWidget {
    background-color: #f8fafc;
    color: #0f172a;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
}

QMainWindow, QDialog {
    background-color: #ffffff;
}

QListWidget {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 6px;
    outline: none;
}

QListWidget::item {
    border-radius: 6px;
    padding: 10px 12px;
    margin-bottom: 4px;
    color: #334155;
}

QListWidget::item:hover {
    background-color: #f1f5f9;
    color: #0f172a;
}

QListWidget::item:selected {
    background-color: #2563eb;
    color: #ffffff;
    font-weight: bold;
}

QPushButton {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #f8fafc;
    border-color: #94a3b8;
}

QPushButton#primaryBtn {
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #1d4ed8;
    font-weight: bold;
}

QPushButton#primaryBtn:hover {
    background-color: #1d4ed8;
}

QPushButton#successBtn {
    background-color: #059669;
    color: #ffffff;
    border: 1px solid #047857;
    font-weight: bold;
}

QPushButton#dangerBtn {
    background-color: #dc2626;
    color: #ffffff;
    border: 1px solid #b91c1c;
}

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 8px;
    color: #0f172a;
}

QTableWidget {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    gridline-color: #f1f5f9;
}

QHeaderView::section {
    background-color: #f1f5f9;
    color: #475569;
    padding: 8px;
    border: none;
    font-weight: bold;
}

QProgressBar {
    background-color: #e2e8f0;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    text-align: center;
    color: #0f172a;
    height: 18px;
}

QProgressBar::chunk {
    background-color: #2563eb;
    border-radius: 5px;
}
"""
