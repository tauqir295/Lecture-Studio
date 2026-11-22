"""Slide validation and quality checks."""
from typing import List, Tuple
from src.models.slide import Slide, SlideReviewStatus


class SlideValidator:
    """Validates slide content, completeness, and review statuses."""

    @staticmethod
    def analyze_slide(slide: Slide) -> List[str]:
        """Inspect a slide and append warnings if quality issues are detected."""
        warnings: List[str] = []

        # Check title
        if not slide.title or not slide.title.strip():
            warnings.append("Slide has no detectable title.")

        # Check content
        words = slide.original_text.strip().split()
        slide.word_count = len(words)

        if len(words) == 0:
            slide.is_empty = True
            warnings.append("Slide appears to be empty or contains no extractable text.")
        elif len(words) < 5 and slide.is_image_only:
            warnings.append("Image-heavy slide with very little text.")

        if not slide.notes or not slide.notes.strip():
            warnings.append("No speaker notes provided.")

        if not slide.image_path:
            warnings.append("Slide preview image has not been rendered.")

        slide.warnings = warnings
        return warnings

    @staticmethod
    def can_approve_all(slides: List[Slide]) -> Tuple[bool, str]:
        """Verify that all slides have been approved."""
        if not slides:
            return False, "Project has no slides."

        unapproved = [s.slide_number for s in slides if s.review_status != SlideReviewStatus.APPROVED]
        if unapproved:
            return False, f"Slides {unapproved} have not been approved."

        return True, "All slides approved."
