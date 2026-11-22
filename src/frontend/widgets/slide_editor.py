"""Right-hand slide details and review editor panel."""
from typing import Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QComboBox, QGroupBox, QScrollArea, QFrame,
    QMessageBox
)
from PySide6.QtCore import Qt, Signal

from src.models.slide import Slide, SlideReviewStatus
from src.frontend.widgets.status_badge import StatusBadge


class SlideEditor(QWidget):
    """Right-hand panel for inspecting slide text, notes, mode, and conducting slide reviews."""

    slide_approved = Signal(str)  # slide_id
    slide_rejected = Signal(str, str)  # slide_id, reason
    slide_updated = Signal(str, dict)  # slide_id, changed fields
    presentation_approval_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_slide: Optional[Slide] = None
        self._is_populating = False
        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(12)

        # Header with status badge
        header_layout = QHBoxLayout()
        self.title_heading = QLabel("Slide Details & Review")
        self.title_heading.setStyleSheet("font-size: 15px; font-weight: bold; color: #93c5fd;")
        header_layout.addWidget(self.title_heading)
        header_layout.addStretch()

        self.status_badge = StatusBadge()
        header_layout.addWidget(self.status_badge)
        layout.addLayout(header_layout)

        # Warnings Banner
        self.warning_box = QLabel()
        self.warning_box.setWordWrap(True)
        self.warning_box.setStyleSheet("""
            QLabel {
                background-color: #451a03;
                color: #fbbf24;
                border: 1px solid #d97706;
                border-radius: 6px;
                padding: 8px;
                font-weight: 500;
            }
        """)
        self.warning_box.setVisible(False)
        layout.addWidget(self.warning_box)

        # Slide Title
        layout.addWidget(QLabel("Slide Title:"))
        self.title_edit = QLineEdit()
        self.title_edit.textChanged.connect(self._on_content_changed)
        layout.addWidget(self.title_edit)

        # Slide Mode
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Slide Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Mode A — Original Preservation",
            "Mode B — Enhanced Lecture Slide",
        ])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_layout.addWidget(self.mode_combo, 1)
        layout.addLayout(mode_layout)

        # Extracted Slide Content
        content_group = QGroupBox("Extracted Slide Content")
        cg_layout = QVBoxLayout(content_group)
        self.content_edit = QTextEdit()
        self.content_edit.setPlaceholderText("Raw text content extracted from slide...")
        self.content_edit.textChanged.connect(self._on_content_changed)
        cg_layout.addWidget(self.content_edit)
        layout.addWidget(content_group)

        # Speaker & Teaching Notes
        notes_group = QGroupBox("Teaching & Speaker Notes")
        ng_layout = QVBoxLayout(notes_group)
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Enter teaching notes or speaking pointers for this slide...")
        self.notes_edit.textChanged.connect(self._on_content_changed)
        ng_layout.addWidget(self.notes_edit)
        layout.addWidget(notes_group)

        # Revision Feedback / Rejection Notes
        self.revision_group = QGroupBox("Revision / Feedback Notes")
        rg_layout = QVBoxLayout(self.revision_group)
        self.revision_edit = QTextEdit()
        self.revision_edit.setPlaceholderText("Notes explaining why slide needs revision...")
        self.revision_edit.textChanged.connect(self._on_content_changed)
        rg_layout.addWidget(self.revision_edit)
        layout.addWidget(self.revision_group)

        # Slide Review Action Buttons
        actions_group = QGroupBox("Slide Review Decision")
        ag_layout = QVBoxLayout(actions_group)

        btn_row = QHBoxLayout()
        self.btn_approve = QPushButton("✓ Approve Slide")
        self.btn_approve.setObjectName("successBtn")
        self.btn_approve.clicked.connect(self._on_approve)
        btn_row.addWidget(self.btn_approve)

        self.btn_reject = QPushButton("✗ Request Revision")
        self.btn_reject.setObjectName("dangerBtn")
        self.btn_reject.clicked.connect(self._on_reject)
        btn_row.addWidget(self.btn_reject)
        ag_layout.addLayout(btn_row)

        layout.addWidget(actions_group)

        # Presentation-level Approval Gate Button
        pres_group = QGroupBox("Presentation Approval")
        pg_layout = QVBoxLayout(pres_group)
        self.gate_info_label = QLabel("Optional. Marks every slide as approved in one click.")
        self.gate_info_label.setWordWrap(True)
        self.gate_info_label.setStyleSheet("color: #9ca3af; font-size: 11px;")
        pg_layout.addWidget(self.gate_info_label)

        self.btn_approve_presentation = QPushButton("★ Approve Entire Presentation")
        self.btn_approve_presentation.setObjectName("primaryBtn")
        self.btn_approve_presentation.clicked.connect(self.presentation_approval_requested.emit)
        pg_layout.addWidget(self.btn_approve_presentation)

        layout.addWidget(pres_group)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def set_slide(self, slide: Optional[Slide]) -> None:
        self.current_slide = slide
        self._is_populating = True

        if not slide:
            self.title_heading.setText("No Slide Selected")
            self.title_edit.clear()
            self.content_edit.clear()
            self.notes_edit.clear()
            self.revision_edit.clear()
            self.warning_box.setVisible(False)
            self._is_populating = False
            return

        self.title_heading.setText(f"Slide #{slide.slide_number} Review")
        self.status_badge.set_status(slide.review_status.value)
        self.title_edit.setText(slide.title)
        self.content_edit.setText(slide.original_text)
        self.notes_edit.setText(slide.notes)
        self.revision_edit.setText(slide.revision_notes)

        mode_idx = 1 if slide.mode == "enhanced" else 0
        self.mode_combo.setCurrentIndex(mode_idx)

        # Warnings
        if slide.warnings:
            self.warning_box.setText("⚠️ Warnings:\n• " + "\n• ".join(slide.warnings))
            self.warning_box.setVisible(True)
        else:
            self.warning_box.setVisible(False)

        self._is_populating = False

    def _on_content_changed(self) -> None:
        if self._is_populating or not self.current_slide:
            return

        changed_data = {
            "title": self.title_edit.text(),
            "original_text": self.content_edit.toPlainText(),
            "notes": self.notes_edit.toPlainText(),
            "revision_notes": self.revision_edit.toPlainText(),
        }
        self.slide_updated.emit(self.current_slide.slide_id, changed_data)

    def _on_mode_changed(self, idx: int) -> None:
        if self._is_populating or not self.current_slide:
            return
        mode = "enhanced" if idx == 1 else "original"
        self.slide_updated.emit(self.current_slide.slide_id, {"mode": mode})

    def _on_approve(self) -> None:
        if self.current_slide:
            self.slide_approved.emit(self.current_slide.slide_id)

    def _on_reject(self) -> None:
        if self.current_slide:
            reason = self.revision_edit.toPlainText().strip() or "Requires revision."
            self.slide_rejected.emit(self.current_slide.slide_id, reason)
