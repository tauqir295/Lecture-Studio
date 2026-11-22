"""Three-panel Slide Studio workspace for slide inspection and approval."""
from typing import Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QLabel, QPushButton,
    QMessageBox, QFrame
)
from PySide6.QtCore import Qt, Signal

from src.models.project import Project, WorkflowStage
from src.models.slide import Slide, SlideReviewStatus
from src.backend.slides.slide_manager import SlideManager
from src.backend.workflow_manager import WorkflowManager
from src.backend.project_manager import ProjectManager
from src.frontend.widgets.slide_navigator import SlideNavigator
from src.frontend.widgets.slide_preview import SlidePreview
from src.frontend.widgets.slide_editor import SlideEditor
from src.frontend.widgets.status_badge import StatusBadge


class SlideStudio(QWidget):
    """Complete 3-panel workspace for slide review, editing, and presentation approval."""

    presentation_approved = Signal()  # Emitted when presentation approval gate succeeds

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Optional[Project] = None
        self.current_slide_idx = 0
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Top Bar: Project title & overall workflow status
        top_bar = QHBoxLayout()
        self.lbl_project_title = QLabel("Slide Studio — No Project Loaded")
        self.lbl_project_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #f3f4f6;")
        top_bar.addWidget(self.lbl_project_title)
        top_bar.addStretch()

        self.lbl_gate_status = QLabel("Status: In review")
        self.lbl_gate_status.setStyleSheet("color: #fbbf24; font-weight: 500;")
        top_bar.addWidget(self.lbl_gate_status)

        self.overall_badge = StatusBadge("slide_review")
        top_bar.addWidget(self.overall_badge)
        layout.addLayout(top_bar)

        # 3-Panel Splitter
        self.splitter = QSplitter(Qt.Horizontal)

        # Left: Navigator
        self.navigator = SlideNavigator()
        self.navigator.slide_selected.connect(self._on_slide_selected)
        self.navigator.selection_changed.connect(self._on_selection_changed)
        self.splitter.addWidget(self.navigator)

        # Center: Large Slide Preview
        self.preview = SlidePreview()
        self.preview.prev_clicked.connect(self._prev_slide)
        self.preview.next_clicked.connect(self._next_slide)
        self.splitter.addWidget(self.preview)

        # Right: Slide Editor & Review Controls
        self.editor = SlideEditor()
        self.editor.slide_approved.connect(self._approve_slide)
        self.editor.slide_rejected.connect(self._reject_slide)
        self.editor.slide_updated.connect(self._update_slide)
        self.editor.presentation_approval_requested.connect(self._approve_presentation)
        self.splitter.addWidget(self.editor)

        # Set initial splitter proportions: 22% left, 48% center, 30% right
        self.splitter.setSizes([260, 580, 360])
        layout.addWidget(self.splitter, 1)

        # Bottom Bar: Summary & Navigation
        bottom_bar = QFrame()
        bottom_bar.setStyleSheet("background-color: #181820; border-radius: 6px; padding: 4px;")
        bb_layout = QHBoxLayout(bottom_bar)
        bb_layout.setContentsMargins(12, 6, 12, 6)

        self.lbl_slide_counter = QLabel("Slide 0 of 0")
        self.lbl_slide_counter.setStyleSheet("font-weight: bold; color: #9ca3af;")
        bb_layout.addWidget(self.lbl_slide_counter)

        self.lbl_approval_summary = QLabel("0 / 0 Approved")
        self.lbl_approval_summary.setStyleSheet("color: #34d399; font-weight: bold;")
        bb_layout.addWidget(self.lbl_approval_summary)
        bb_layout.addStretch()

        self.btn_approve_selected = QPushButton("✓ Approve Selected (0)")
        self.btn_approve_selected.setToolTip("Approve every slide selected in the list on the left.")
        self.btn_approve_selected.setEnabled(False)
        self.btn_approve_selected.clicked.connect(self._approve_selected_slides)
        bb_layout.addWidget(self.btn_approve_selected)

        self.btn_approve_all_slides = QPushButton("✓✓ Approve All Slides")
        self.btn_approve_all_slides.setToolTip("Mark every slide as approved in one step.")
        self.btn_approve_all_slides.clicked.connect(self._approve_all_slides)
        bb_layout.addWidget(self.btn_approve_all_slides)

        self.btn_bottom_approve_all = QPushButton("★ Approve Entire Presentation")
        self.btn_bottom_approve_all.setObjectName("primaryBtn")
        self.btn_bottom_approve_all.clicked.connect(self._approve_presentation)
        bb_layout.addWidget(self.btn_bottom_approve_all)

        layout.addWidget(bottom_bar)

    def load_project(self, project: Project) -> None:
        self.project = project
        self.lbl_project_title.setText(f"Slide Studio — {project.project_name}")
        self._update_gate_status()

        self.navigator.set_slides(project.slides, project.project_dir)

        if project.slides:
            self.current_slide_idx = 0
            self._display_slide(project.slides[0])
        else:
            self.preview.set_slide(None, "")
            self.editor.set_slide(None)

        self._update_summary_counts()

    def _display_slide(self, slide: Slide) -> None:
        if not self.project:
            return
        self.preview.set_slide(slide, self.project.project_dir)
        self.editor.set_slide(slide)
        total = len(self.project.slides)
        self.lbl_slide_counter.setText(f"Slide {slide.slide_number} of {total}")

    def _on_slide_selected(self, slide_id: str) -> None:
        if not self.project:
            return
        for i, s in enumerate(self.project.slides):
            if s.slide_id == slide_id:
                self.current_slide_idx = i
                self._display_slide(s)
                break

    def _prev_slide(self) -> None:
        if not self.project or not self.project.slides:
            return
        if self.current_slide_idx > 0:
            self.current_slide_idx -= 1
            slide = self.project.slides[self.current_slide_idx]
            self.navigator.select_slide(slide.slide_id)

    def _next_slide(self) -> None:
        if not self.project or not self.project.slides:
            return
        if self.current_slide_idx < len(self.project.slides) - 1:
            self.current_slide_idx += 1
            slide = self.project.slides[self.current_slide_idx]
            self.navigator.select_slide(slide.slide_id)

    def _approve_slide(self, slide_id: str) -> None:
        if not self.project:
            return
        sm = SlideManager(self.project)
        slide = sm.approve_slide(slide_id)
        self._save_project()
        self.editor.set_slide(slide)
        self.navigator.set_slides(self.project.slides, self.project.project_dir)
        self.navigator.select_slide(slide_id)
        self._update_summary_counts()

        # Automatically advance to next unapproved slide if available
        unapproved = [s for s in self.project.slides if s.review_status != SlideReviewStatus.APPROVED]
        if unapproved and self.current_slide_idx < len(self.project.slides) - 1:
            self._next_slide()

    def _on_selection_changed(self, count: int) -> None:
        self.btn_approve_selected.setText(f"✓ Approve Selected ({count})")
        self.btn_approve_selected.setEnabled(count > 0)

    def _approve_selected_slides(self) -> None:
        if not self.project:
            return
        ids = self.navigator.get_selected_slide_ids()
        if ids:
            self._bulk_approve(ids)

    def _approve_all_slides(self) -> None:
        if self.project and self.project.slides:
            self._approve_presentation()

    def _bulk_approve(self, slide_ids) -> None:
        """Approve the given slides (None = all), persist, and refresh the UI."""
        current_id = self.project.slides[self.current_slide_idx].slide_id if self.project.slides else None
        SlideManager(self.project).approve_slides(slide_ids)
        self._save_project()
        self.navigator.set_slides(self.project.slides, self.project.project_dir)
        if current_id:
            self.navigator.select_slide(current_id)
            current = self.project.get_slide_by_id(current_id)
            if current:
                self.editor.set_slide(current)
        self._update_summary_counts()

    def _reject_slide(self, slide_id: str, reason: str) -> None:
        if not self.project:
            return
        sm = SlideManager(self.project)
        slide = sm.reject_slide(slide_id, reason)
        self._save_project()
        self.editor.set_slide(slide)
        self.navigator.set_slides(self.project.slides, self.project.project_dir)
        self.navigator.select_slide(slide_id)
        self._update_summary_counts()

    def _update_slide(self, slide_id: str, changed_data: dict) -> None:
        if not self.project:
            return
        sm = SlideManager(self.project)
        slide = sm.update_slide(
            slide_id=slide_id,
            title=changed_data.get("title"),
            notes=changed_data.get("notes"),
            revision_notes=changed_data.get("revision_notes"),
            mode=changed_data.get("mode"),
        )
        self._save_project()
        self.editor.status_badge.set_status(slide.review_status.value)
        self._update_summary_counts()

    def _approve_presentation(self) -> None:
        if not self.project:
            return

        WorkflowManager(self.project).approve_entire_presentation()
        self._save_project()
        self.navigator.set_slides(self.project.slides, self.project.project_dir)
        if self.project.slides:
            self.editor.set_slide(self.project.slides[self.current_slide_idx])
        self._update_summary_counts()
        self.presentation_approved.emit()

    def _update_gate_status(self) -> None:
        if not self.project:
            return
        if self.project.slides_approved:
            self.lbl_gate_status.setText("Status: All slides approved ✓")
            self.lbl_gate_status.setStyleSheet("color: #10b981; font-weight: bold;")
            self.overall_badge.set_status("slides_approved")
            self.btn_bottom_approve_all.setText("✓ Presentation Approved")
            self.btn_bottom_approve_all.setEnabled(False)
            self.btn_approve_all_slides.setEnabled(False)
        else:
            self.lbl_gate_status.setText("Status: In review (optional)")
            self.lbl_gate_status.setStyleSheet("color: #fbbf24; font-weight: 500;")
            self.overall_badge.set_status("slide_review")
            self.btn_bottom_approve_all.setText("★ Approve Entire Presentation")
            self.btn_bottom_approve_all.setEnabled(True)
            self.btn_approve_all_slides.setEnabled(True)

    def _update_summary_counts(self) -> None:
        if not self.project or not self.project.slides:
            return
        total = len(self.project.slides)
        approved = sum(1 for s in self.project.slides if s.review_status == SlideReviewStatus.APPROVED)
        self.lbl_approval_summary.setText(f"{approved} / {total} Slides Approved")
        self._update_gate_status()

    def _save_project(self) -> None:
        if self.project:
            pm = ProjectManager(self.project.project_dir)
            pm.save_project(self.project)
