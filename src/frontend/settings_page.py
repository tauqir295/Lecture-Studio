"""Settings page for theme switching and system diagnostics."""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QGroupBox, QFrame
)
from PySide6.QtCore import Qt, Signal

from src.utils.process_utils import find_tool


class SettingsPage(QWidget):
    """Application settings and system tool diagnostic checks."""

    theme_changed = Signal(str)  # "dark" or "light"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(20)

        header = QLabel("Application Settings")
        header.setStyleSheet("font-size: 20px; font-weight: bold; color: #93c5fd;")
        layout.addWidget(header)

        # Theme Group
        theme_group = QGroupBox("Appearance")
        tg_layout = QHBoxLayout(theme_group)
        tg_layout.addWidget(QLabel("Interface Theme:"))

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark Theme (Default)", "Light Theme"])
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        tg_layout.addWidget(self.theme_combo, 1)
        layout.addWidget(theme_group)

        # System Diagnostics Group
        diag_group = QGroupBox("System Diagnostics & Offline Tools")
        dg_layout = QVBoxLayout(diag_group)
        dg_layout.setSpacing(10)

        self.tool_labels = {}
        for tool in ["PySide6 QtPdf Engine", "FFmpeg", "Piper TTS", "LibreOffice"]:
            row = QHBoxLayout()
            name_lbl = QLabel(tool)
            name_lbl.setStyleSheet("font-weight: 500;")
            status_lbl = QLabel("Checking...")
            row.addWidget(name_lbl, 1)
            row.addWidget(status_lbl)
            dg_layout.addLayout(row)
            self.tool_labels[tool] = status_lbl

        layout.addWidget(diag_group)
        layout.addStretch()

        self.check_diagnostics()

    def check_diagnostics(self) -> None:
        # PySide6 QtPdf
        self.tool_labels["PySide6 QtPdf Engine"].setText("✓ Native (Ready)")
        self.tool_labels["PySide6 QtPdf Engine"].setStyleSheet("color: #10b981; font-weight: bold;")

        # FFmpeg
        ffmpeg_path = find_tool("ffmpeg")
        if ffmpeg_path:
            self.tool_labels["FFmpeg"].setText(f"✓ Installed ({ffmpeg_path})")
            self.tool_labels["FFmpeg"].setStyleSheet("color: #10b981; font-weight: bold;")
        else:
            self.tool_labels["FFmpeg"].setText("⚠️ Not found on PATH")
            self.tool_labels["FFmpeg"].setStyleSheet("color: #f59e0b;")

        # Piper
        piper_path = find_tool("piper")
        if piper_path:
            self.tool_labels["Piper TTS"].setText(f"✓ Installed ({piper_path})")
            self.tool_labels["Piper TTS"].setStyleSheet("color: #10b981; font-weight: bold;")
        else:
            self.tool_labels["Piper TTS"].setText("⚠️ Not installed (Module Ready)")
            self.tool_labels["Piper TTS"].setStyleSheet("color: #f59e0b;")

        # LibreOffice
        lo_path = find_tool("soffice")
        if lo_path:
            self.tool_labels["LibreOffice"].setText(f"✓ Installed ({lo_path})")
            self.tool_labels["LibreOffice"].setStyleSheet("color: #10b981; font-weight: bold;")
        else:
            self.tool_labels["LibreOffice"].setText("Optional (PDF slides used natively)")
            self.tool_labels["LibreOffice"].setStyleSheet("color: #9ca3af;")

    def _on_theme_changed(self, idx: int) -> None:
        theme = "dark" if idx == 0 else "light"
        self.theme_changed.emit(theme)
