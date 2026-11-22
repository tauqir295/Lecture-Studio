"""Slide navigator thumbnail list for Slide Studio."""
from pathlib import Path
from typing import List, Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QComboBox, QLineEdit, QAbstractItemView
)
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtCore import Qt, Signal, QSize

from src.models.slide import Slide, SlideReviewStatus
from src.frontend.widgets.status_badge import StatusBadge


class SlideItemWidget(QWidget):
    """Custom widget rendered inside each list item of the navigator."""

    def __init__(self, slide: Slide, project_dir: str, parent=None):
        super().__init__(parent)
        self.slide = slide
        self.project_dir = project_dir

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        # Thumbnail
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(96, 54)
        self.thumb_label.setStyleSheet("background-color: #101014; border-radius: 4px; border: 1px solid #383848;")
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.update_thumbnail()
        layout.addWidget(self.thumb_label)

        # Text & Status
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        top_row = QHBoxLayout()
        self.title_label = QLabel(f"#{slide.slide_number} {slide.title}")
        self.title_label.setStyleSheet("font-weight: bold; color: #f3f4f6;")
        self.title_label.setWordWrap(True)
        top_row.addWidget(self.title_label, 1)

        if slide.warnings:
            warn_label = QLabel("⚠️")
            warn_label.setToolTip("\n".join(slide.warnings))
            top_row.addWidget(warn_label)

        info_layout.addLayout(top_row)

        bottom_row = QHBoxLayout()
        self.badge = StatusBadge(slide.review_status.value)
        bottom_row.addWidget(self.badge)

        self.words_label = QLabel(f"{slide.word_count} words")
        self.words_label.setStyleSheet("color: #9ca3af; font-size: 11px;")
        bottom_row.addWidget(self.words_label)
        bottom_row.addStretch()

        info_layout.addLayout(bottom_row)
        layout.addLayout(info_layout, 1)

    def update_thumbnail(self) -> None:
        if self.slide.thumbnail_path and self.project_dir:
            full_path = Path(self.project_dir) / self.slide.thumbnail_path
            if full_path.is_file():
                pix = QPixmap(str(full_path))
                scaled = pix.scaled(96, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.thumb_label.setPixmap(scaled)
                return
        self.thumb_label.setText(f"Slide {self.slide.slide_number}")


class SlideNavigator(QWidget):
    """Left sidebar list displaying all slides with thumbnails and review statuses."""

    slide_selected = Signal(str)  # emits slide_id
    selection_changed = Signal(int)  # number of selected slides

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project_dir = ""
        self.slides: List[Slide] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # Header and filter
        header = QLabel("Slides")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #93c5fd;")
        layout.addWidget(header)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            "All Slides",
            "Needs Review",
            "Approved",
            "Rejected",
            "Edited",
        ])
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        layout.addWidget(self.filter_combo)

        # Slide List
        self.list_widget = QListWidget()
        self.list_widget.setSpacing(3)
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_widget.setToolTip("Shift/Ctrl/Cmd-click to select several slides; Ctrl/Cmd+A selects all.")
        self.list_widget.currentItemChanged.connect(self._on_item_changed)
        self.list_widget.itemSelectionChanged.connect(
            lambda: self.selection_changed.emit(len(self.list_widget.selectedItems())))
        layout.addWidget(self.list_widget, 1)

        hint = QLabel("Tip: Shift/Ctrl-click to select multiple slides")
        hint.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(hint)

    def set_slides(self, slides: List[Slide], project_dir: str) -> None:
        self.slides = slides
        self.project_dir = project_dir
        self._apply_filter()

    def _apply_filter(self) -> None:
        current_id = self.get_selected_slide_id()
        filter_text = self.filter_combo.currentText()
        self.list_widget.clear()

        for slide in self.slides:
            if filter_text == "Needs Review" and slide.review_status != SlideReviewStatus.REVIEW_REQUIRED:
                continue
            elif filter_text == "Approved" and slide.review_status != SlideReviewStatus.APPROVED:
                continue
            elif filter_text == "Rejected" and slide.review_status != SlideReviewStatus.REJECTED:
                continue
            elif filter_text == "Edited" and slide.review_status != SlideReviewStatus.EDITED:
                continue

            item = QListWidgetItem()
            item.setData(Qt.UserRole, slide.slide_id)
            item.setSizeHint(QSize(240, 72))

            item_widget = SlideItemWidget(slide, self.project_dir)
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, item_widget)

            if current_id and slide.slide_id == current_id:
                self.list_widget.setCurrentItem(item)

        if not self.list_widget.currentItem() and self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _on_item_changed(self, current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem]) -> None:
        if current:
            slide_id = current.data(Qt.UserRole)
            self.slide_selected.emit(slide_id)

    def get_selected_slide_id(self) -> Optional[str]:
        item = self.list_widget.currentItem()
        return item.data(Qt.UserRole) if item else None

    def get_selected_slide_ids(self) -> List[str]:
        """IDs of all selected slides, in presentation order."""
        ids = {it.data(Qt.UserRole) for it in self.list_widget.selectedItems()}
        return [s.slide_id for s in self.slides if s.slide_id in ids]

    def select_slide(self, slide_id: str) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == slide_id:
                self.list_widget.setCurrentItem(item)
                break
