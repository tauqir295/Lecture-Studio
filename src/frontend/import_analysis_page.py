"""Import Analysis Page displaying presentation diagnostics."""
from typing import Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox, QFrame
)
from PySide6.QtCore import Qt, Signal

from src.models.project import Project


class ImportAnalysisPage(QWidget):
    """Displays slide statistics, text extraction count, image counts, and import warnings."""

    proceed_to_slide_studio = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Optional[Project] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QLabel("Presentation Analysis")
        header.setStyleSheet("font-size: 20px; font-weight: bold; color: #93c5fd;")
        layout.addWidget(header)

        # Metrics cards row
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)

        self.card_slides = self._create_card("Total Slides", "0", "#2563eb")
        self.card_words = self._create_card("Extracted Words", "0", "#059669")
        self.card_warnings = self._create_card("Warnings Detected", "0", "#d97706")
        self.card_empty = self._create_card("Empty / Image Slides", "0", "#8b5cf6")

        cards_row.addWidget(self.card_slides)
        cards_row.addWidget(self.card_words)
        cards_row.addWidget(self.card_warnings)
        cards_row.addWidget(self.card_empty)
        layout.addLayout(cards_row)

        # Slide Overview Table
        table_group = QGroupBox("Slide Breakdown")
        tg_layout = QVBoxLayout(table_group)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Slide #", "Detected Title", "Words", "Images", "Warnings"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        tg_layout.addWidget(self.table)
        layout.addWidget(table_group, 1)

        # Action bar
        actions_bar = QHBoxLayout()
        actions_bar.addStretch()

        self.btn_proceed = QPushButton("Proceed to Slide Review Studio ▶")
        self.btn_proceed.setObjectName("primaryBtn")
        self.btn_proceed.setFixedHeight(42)
        self.btn_proceed.clicked.connect(self.proceed_to_slide_studio.emit)
        actions_bar.addWidget(self.btn_proceed)

        layout.addLayout(actions_bar)

    def _create_card(self, title: str, value: str, color: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: #202028;
                border-left: 4px solid {color};
                border-radius: 8px;
                padding: 12px;
            }}
        """)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(8, 8, 8, 8)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #9ca3af; font-size: 12px; font-weight: 500;")
        c_layout.addWidget(lbl_title)

        lbl_val = QLabel(value)
        lbl_val.setStyleSheet("font-size: 22px; font-weight: bold; color: #f3f4f6;")
        c_layout.addWidget(lbl_val)
        card.lbl_val = lbl_val
        return card

    def load_project(self, project: Project) -> None:
        self.project = project
        if not project or not project.slides:
            return

        total_slides = len(project.slides)
        total_words = sum(s.word_count for s in project.slides)
        total_warnings = sum(len(s.warnings) for s in project.slides)
        empty_count = sum(1 for s in project.slides if s.is_empty or s.is_image_only)

        self.card_slides.lbl_val.setText(str(total_slides))
        self.card_words.lbl_val.setText(f"{total_words:,}")
        self.card_warnings.lbl_val.setText(str(total_warnings))
        self.card_empty.lbl_val.setText(str(empty_count))

        self.table.setRowCount(total_slides)
        for i, s in enumerate(project.slides):
            self.table.setItem(i, 0, QTableWidgetItem(f"#{s.slide_number}"))
            self.table.setItem(i, 1, QTableWidgetItem(s.title))
            self.table.setItem(i, 2, QTableWidgetItem(str(s.word_count)))
            num_img = s.metadata.get("num_images", 0)
            self.table.setItem(i, 3, QTableWidgetItem(str(num_img)))
            warn_text = "; ".join(s.warnings) if s.warnings else "None"
            self.table.setItem(i, 4, QTableWidgetItem(warn_text))
