"""Slide manager for managing slide lifecycle, updates, and mode switching."""
from typing import Optional, List
from src.models.slide import Slide, SlideReviewStatus
from src.models.project import Project
from src.backend.slides.slide_validator import SlideValidator


class SlideManager:
    """Handles slide state mutations, text updates, enhancement modes, and approvals."""

    def __init__(self, project: Project):
        self.project = project

    def get_slides(self) -> List[Slide]:
        return self.project.slides

    def get_slide(self, slide_id: str) -> Optional[Slide]:
        return self.project.get_slide_by_id(slide_id)

    def update_slide(
        self,
        slide_id: str,
        title: Optional[str] = None,
        notes: Optional[str] = None,
        enhanced_text: Optional[str] = None,
        revision_notes: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> Slide:
        """Update slide metadata or edited content and mark as EDITED."""
        slide = self.project.get_slide_by_id(slide_id)
        if not slide:
            raise ValueError(f"Slide {slide_id} not found.")

        if title is not None:
            slide.title = title
        if notes is not None:
            slide.notes = notes
        if enhanced_text is not None:
            slide.enhanced_text = enhanced_text
        if revision_notes is not None:
            slide.revision_notes = revision_notes
        if mode is not None:
            slide.mode = mode

        # Any content edit resets the status to EDITED and invalidates presentation approval
        slide.review_status = SlideReviewStatus.EDITED
        SlideValidator.analyze_slide(slide)

        # Invalidate presentation approval gate
        self.project.slides_approved = False
        return slide

    def set_status(self, slide_id: str, status: SlideReviewStatus, revision_notes: str = "") -> Slide:
        """Set review status for an individual slide."""
        slide = self.project.get_slide_by_id(slide_id)
        if not slide:
            raise ValueError(f"Slide {slide_id} not found.")

        slide.review_status = status
        if revision_notes:
            slide.revision_notes = revision_notes

        if status != SlideReviewStatus.APPROVED:
            self.project.slides_approved = False

        return slide

    def approve_slide(self, slide_id: str) -> Slide:
        return self.set_status(slide_id, SlideReviewStatus.APPROVED)

    def approve_slides(self, slide_ids: Optional[List[str]] = None) -> List[Slide]:
        """Approve several slides at once (all slides when slide_ids is None).

        Unknown IDs are ignored. The presentation-level gate is NOT approved here;
        that still needs an explicit "Approve Entire Presentation".
        """
        wanted = None if slide_ids is None else set(slide_ids)
        approved = []
        for slide in self.project.slides:
            if wanted is None or slide.slide_id in wanted:
                slide.review_status = SlideReviewStatus.APPROVED
                approved.append(slide)
        return approved

    def reject_slide(self, slide_id: str, reason: str = "") -> Slide:
        return self.set_status(slide_id, SlideReviewStatus.REJECTED, reason)
