"""Visual status badge widget with semantic coloring."""
from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt

from src.models.slide import SlideReviewStatus
from src.models.narration import NarrationStatus
from src.models.project import WorkflowStage


STATUS_COLORS = {
    # Slide review statuses
    SlideReviewStatus.APPROVED.value: ("#059669", "#ecfdf5", "✓ Approved"),
    SlideReviewStatus.REJECTED.value: ("#dc2626", "#fef2f2", "✗ Rejected"),
    SlideReviewStatus.REVIEW_REQUIRED.value: ("#d97706", "#fffbeb", "◷ Needs Review"),
    SlideReviewStatus.EDITED.value: ("#2563eb", "#eff6ff", "✎ Edited"),
    SlideReviewStatus.DRAFT.value: ("#6b7280", "#f9fafb", "Draft"),
    # Workflow stages
    WorkflowStage.IMPORTED.value: ("#6b7280", "#f9fafb", "Imported"),
    WorkflowStage.SLIDE_PREPARATION.value: ("#3b82f6", "#eff6ff", "Slide Prep"),
    WorkflowStage.SLIDE_REVIEW.value: ("#d97706", "#fffbeb", "Slide Review"),
    WorkflowStage.SLIDES_APPROVED.value: ("#059669", "#ecfdf5", "Slides Approved"),
    WorkflowStage.NARRATION_PREPARATION.value: ("#8b5cf6", "#f5f3ff", "Narration Prep"),
    WorkflowStage.NARRATION_REVIEW.value: ("#f59e0b", "#fffbeb", "Narration Review"),
    WorkflowStage.NARRATION_APPROVED.value: ("#10b981", "#ecfdf5", "Narration Approved"),
    WorkflowStage.AUDIO_GENERATION.value: ("#06b6d4", "#ecfeff", "Audio Generating"),
    WorkflowStage.VIDEO_PREVIEW.value: ("#6366f1", "#eef2ff", "Video Preview"),
    WorkflowStage.VIDEO_EXPORT.value: ("#ec4899", "#fdf2f8", "Exporting"),
    WorkflowStage.COMPLETED.value: ("#059669", "#ecfdf5", "Completed"),
}


class StatusBadge(QLabel):
    """Compact rounded badge indicating status with consistent colors."""

    def __init__(self, status: str = "", parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.set_status(status)

    def set_status(self, status: str) -> None:
        status_key = status.lower() if status else "draft"
        color, bg_light, label = STATUS_COLORS.get(status_key, ("#6b7280", "#282834", status.replace("_", " ").title()))

        self.setText(f"  {label}  ")
        self.setStyleSheet(f"""
            QLabel {{
                color: {color};
                background-color: rgba({int(color[1:3], 16)}, {int(color[3:5], 16)}, {int(color[5:7], 16)}, 0.18);
                border: 1px solid {color};
                border-radius: 10px;
                padding: 2px 8px;
                font-weight: bold;
                font-size: 11px;
            }}
        """)
