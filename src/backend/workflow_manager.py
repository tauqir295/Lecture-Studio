"""Backend-enforced workflow state machine and approval gating."""
from typing import Tuple, List, Optional
from src.models.project import Project, WorkflowStage
from src.models.slide import SlideReviewStatus
from src.models.narration import NarrationStatus


class WorkflowError(Exception):
    """Raised when an illegal workflow state transition or gate violation is attempted."""
    pass


class WorkflowManager:
    """Tracks review status and workflow stage for a Project. Approvals are informational only; nothing is blocked."""

    VALID_TRANSITIONS = {
        WorkflowStage.IMPORTED: [WorkflowStage.SLIDE_PREPARATION, WorkflowStage.SLIDE_REVIEW],
        WorkflowStage.SLIDE_PREPARATION: [WorkflowStage.SLIDE_REVIEW],
        WorkflowStage.SLIDE_REVIEW: [WorkflowStage.SLIDES_APPROVED],
        WorkflowStage.SLIDES_APPROVED: [WorkflowStage.NARRATION_PREPARATION, WorkflowStage.NARRATION_REVIEW, WorkflowStage.SLIDE_REVIEW],
        WorkflowStage.NARRATION_PREPARATION: [WorkflowStage.NARRATION_REVIEW],
        WorkflowStage.NARRATION_REVIEW: [WorkflowStage.NARRATION_APPROVED, WorkflowStage.SLIDE_REVIEW],
        WorkflowStage.NARRATION_APPROVED: [WorkflowStage.AUDIO_GENERATION, WorkflowStage.NARRATION_REVIEW],
        WorkflowStage.AUDIO_GENERATION: [WorkflowStage.VIDEO_PREVIEW, WorkflowStage.NARRATION_APPROVED],
        WorkflowStage.VIDEO_PREVIEW: [WorkflowStage.VIDEO_EXPORT, WorkflowStage.AUDIO_GENERATION],
        WorkflowStage.VIDEO_EXPORT: [WorkflowStage.COMPLETED, WorkflowStage.VIDEO_PREVIEW],
        WorkflowStage.COMPLETED: [WorkflowStage.VIDEO_PREVIEW, WorkflowStage.VIDEO_EXPORT],
    }

    def __init__(self, project: Project):
        self.project = project

    def can_transition_to(self, target_stage: WorkflowStage) -> Tuple[bool, str]:
        """Approval gates are disabled: every stage can be reached at any time."""
        return True, "Transition allowed."

    def transition_to(self, target_stage: WorkflowStage) -> None:
        """Perform transition to target stage or raise WorkflowError."""
        can_proceed, reason = self.can_transition_to(target_stage)
        if not can_proceed:
            raise WorkflowError(reason)

        self.project.workflow_stage = target_stage

        if target_stage == WorkflowStage.SLIDES_APPROVED:
            self.project.slides_approved = True
        elif target_stage == WorkflowStage.NARRATION_APPROVED:
            self.project.narration_approved = True

    def approve_slide(self, slide_id: str) -> None:
        """Approve an individual slide."""
        slide = self.project.get_slide_by_id(slide_id)
        if not slide:
            raise ValueError(f"Slide not found: {slide_id}")
        slide.review_status = SlideReviewStatus.APPROVED

    def reject_slide(self, slide_id: str, reason: str = "") -> None:
        """Reject an individual slide requiring revision."""
        slide = self.project.get_slide_by_id(slide_id)
        if not slide:
            raise ValueError(f"Slide not found: {slide_id}")
        slide.review_status = SlideReviewStatus.REJECTED
        if reason:
            slide.revision_notes = reason
        # Invalidates whole presentation approval
        self.invalidate_slide_approval()

    def approve_entire_presentation(self) -> Tuple[bool, str]:
        """Mark every slide and the presentation as approved (no preconditions)."""
        for s in self.project.slides:
            s.review_status = SlideReviewStatus.APPROVED
        self.project.slides_approved = True
        self.project.workflow_stage = WorkflowStage.SLIDES_APPROVED
        return True, "Presentation approved."

    def invalidate_slide_approval(self) -> None:
        """Call whenever a slide is modified or rejected, resetting presentation approval."""
        self.project.slides_approved = False
        # Roll stage back to slide review if it has progressed past it
        stages_past_slide_review = [
            WorkflowStage.SLIDES_APPROVED,
            WorkflowStage.NARRATION_PREPARATION,
            WorkflowStage.NARRATION_REVIEW,
            WorkflowStage.NARRATION_APPROVED,
            WorkflowStage.AUDIO_GENERATION,
            WorkflowStage.VIDEO_PREVIEW,
            WorkflowStage.VIDEO_EXPORT,
        ]
        if self.project.workflow_stage in stages_past_slide_review:
            self.project.workflow_stage = WorkflowStage.SLIDE_REVIEW

    def approve_narration(self, slide_id: str) -> None:
        """Approve a narration script for a slide."""
        narration = self.project.get_narration_by_id(slide_id)
        if not narration:
            raise ValueError(f"Narration not found for slide {slide_id}")
        narration.status = NarrationStatus.APPROVED

    def approve_all_narrations(self) -> Tuple[bool, str]:
        """Mark every narration script approved (no preconditions)."""
        for n in self.project.narrations:
            n.status = NarrationStatus.APPROVED
        self.project.narration_approved = True
        self.project.workflow_stage = WorkflowStage.NARRATION_APPROVED
        return True, "All narration scripts approved."

    def invalidate_narration_script(self, slide_id: str) -> None:
        """When narration for a slide is edited, invalidate its audio and overall narration approval."""
        narration = self.project.get_narration_by_id(slide_id)
        if narration:
            narration.status = NarrationStatus.EDITED
            # Audio is preserved until explicitly regenerated (it shows as "outdated").

        self.project.narration_approved = False
        self.project.audio_generated = False
        if self.project.workflow_stage in (
            WorkflowStage.NARRATION_APPROVED,
            WorkflowStage.AUDIO_GENERATION,
            WorkflowStage.VIDEO_PREVIEW,
            WorkflowStage.VIDEO_EXPORT,
        ):
            self.project.workflow_stage = WorkflowStage.NARRATION_REVIEW
