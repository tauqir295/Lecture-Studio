"""Progress dialog for background operations."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QHBoxLayout
)
from PySide6.QtCore import Qt, Signal


class ProgressDialog(QDialog):
    """Modal progress dialog for background tasks with cancellation."""

    cancelled = Signal()

    def __init__(self, title: str = "Processing...", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedSize(450, 160)
        self.setWindowModality(Qt.ApplicationModal)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self.label_status = QLabel("Initializing...")
        self.label_status.setStyleSheet("font-weight: 500; font-size: 13px;")
        self.label_status.setWordWrap(True)
        layout.addWidget(self.label_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

    def set_progress(self, percent: int, message: str) -> None:
        self.progress_bar.setValue(percent)
        self.label_status.setText(message)

    def _on_cancel(self) -> None:
        self.label_status.setText("Cancelling...")
        self.btn_cancel.setEnabled(False)
        self.cancelled.emit()
