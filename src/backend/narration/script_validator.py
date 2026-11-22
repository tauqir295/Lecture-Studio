"""Narration script validation and metric calculations."""
from typing import Tuple, List
from src.models.narration import SlideNarration, NarrationStatus


class ScriptValidator:
    """Validates narration script quality, length, and approval conditions."""

    @staticmethod
    def validate_script(narration: SlideNarration) -> Tuple[bool, List[str]]:
        """Validate script text and return (is_valid, warnings)."""
        warnings = []
        text = narration.script.strip()

        if not text:
            warnings.append("Narration script is empty.")
            return False, warnings

        narration.calculate_metrics()

        if narration.word_count < 10:
            warnings.append("Very short narration (under 10 words).")
        elif narration.word_count > 350:
            warnings.append(f"Long narration ({narration.word_count} words). Estimated duration exceeds 2.5 minutes.")

        return True, warnings

    @staticmethod
    def can_approve_all(narrations: List[SlideNarration]) -> Tuple[bool, str]:
        if not narrations:
            return False, "Project has no narration scripts."

        unapproved = [n.slide_number for n in narrations if n.status != NarrationStatus.APPROVED]
        if unapproved:
            return False, f"Narration scripts for slides {unapproved} have not been approved."

        return True, "All narration scripts approved."
