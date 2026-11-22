"""Center slide preview panel with zoom and aspect ratio preservation."""
from pathlib import Path
from typing import Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame
)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt, Signal

from src.models.slide import Slide


class SlidePreview(QWidget):
    """Large center preview displaying rendered 1080p slide images with zoom controls."""

    prev_clicked = Signal()
    next_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project_dir = ""
        self.current_slide: Optional[Slide] = None
        self.zoom_factor = 1.0
        self._pixmap: Optional[QPixmap] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Top Control Toolbar
        toolbar = QHBoxLayout()

        self.info_label = QLabel("Slide Preview")
        self.info_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #93c5fd;")
        toolbar.addWidget(self.info_label)
        toolbar.addStretch()

        self.btn_prev = QPushButton("◀ Prev")
        self.btn_prev.clicked.connect(self.prev_clicked.emit)
        toolbar.addWidget(self.btn_prev)

        self.btn_next = QPushButton("Next ▶")
        self.btn_next.clicked.connect(self.next_clicked.emit)
        toolbar.addWidget(self.btn_next)

        toolbar.addSpacing(12)

        self.btn_zoom_out = QPushButton("− Zoom")
        self.btn_zoom_out.clicked.connect(self._zoom_out)
        toolbar.addWidget(self.btn_zoom_out)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setStyleSheet("color: #9ca3af; min-width: 45px; text-align: center;")
        toolbar.addWidget(self.zoom_label)

        self.btn_zoom_in = QPushButton("+ Zoom")
        self.btn_zoom_in.clicked.connect(self._zoom_in)
        toolbar.addWidget(self.btn_zoom_in)

        self.btn_fit = QPushButton("Fit")
        self.btn_fit.clicked.connect(self._fit_to_screen)
        toolbar.addWidget(self.btn_fit)

        layout.addLayout(toolbar)

        # Scrollable image display
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("background-color: #121216; border-radius: 8px;")

        self.image_container = QWidget()
        self.image_container.setStyleSheet("background-color: #121216;")
        container_layout = QVBoxLayout(self.image_container)
        container_layout.setAlignment(Qt.AlignCenter)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: transparent;")
        container_layout.addWidget(self.image_label)

        self.scroll_area.setWidget(self.image_container)
        layout.addWidget(self.scroll_area, 1)

    def set_slide(self, slide: Optional[Slide], project_dir: str) -> None:
        self.current_slide = slide
        self.project_dir = project_dir

        if not slide:
            self.image_label.clear()
            self.image_label.setText("No slide selected")
            self.info_label.setText("Slide Preview")
            return

        self.info_label.setText(f"Slide {slide.slide_number}: {slide.title}")

        if slide.image_path and self.project_dir:
            full_path = Path(self.project_dir) / slide.image_path
            if full_path.is_file():
                self._pixmap = QPixmap(str(full_path))
                self._update_display()
                return

        self.image_label.clear()
        self.image_label.setText(f"[Slide image not rendered: {slide.slide_id}]")

    def _update_display(self) -> None:
        if not self._pixmap or self._pixmap.isNull():
            return

        # Base width from viewport or 100%
        viewport_w = max(400, self.scroll_area.viewport().width() - 30)
        target_w = int(viewport_w * self.zoom_factor)

        scaled = self._pixmap.scaledToWidth(target_w, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.zoom_label.setText(f"{int(self.zoom_factor * 100)}%")

    def _zoom_in(self) -> None:
        self.zoom_factor = min(2.5, self.zoom_factor + 0.15)
        self._update_display()

    def _zoom_out(self) -> None:
        self.zoom_factor = max(0.4, self.zoom_factor - 0.15)
        self._update_display()

    def _fit_to_screen(self) -> None:
        self.zoom_factor = 1.0
        self._update_display()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.zoom_factor == 1.0:
            self._update_display()
