"""Narration script generator and manager."""
import re
from typing import List, Optional, Tuple
from src.models.slide import Slide
from src.models.narration import SlideNarration, NarrationStatus
from src.models.project import Project
from src.backend.narration.script_validator import ScriptValidator


class ScriptManager:
    """Creates conversational teaching narration scripts from slide content and notes."""

    @staticmethod
    def draft_narration_from_slide(slide: Slide) -> str:
        """Transform slide bullet points and notes into conversational teaching narration."""
        # If notes exist, notes take priority for narration
        if slide.notes and len(slide.notes.strip()) > 15:
            return slide.notes.strip()

        # Build natural spoken explanation from title and content
        title = slide.title.strip()
        lines = [line.strip() for line in slide.original_text.splitlines() if line.strip()]

        intro = f"In this slide, we explore {title}." if title else "Welcome to this slide."

        bullet_points = []
        for line in lines:
            # Skip repeating the exact title
            if line.lower() == title.lower():
                continue
            # Remove leading bullet symbols (-, *, •, numbers)
            cleaned = re.sub(r"^[\s\-\*•\d\.\)]+", "", line).strip()
            if cleaned and len(cleaned) > 2:
                bullet_points.append(cleaned)

        if not bullet_points:
            return f"{intro} Here we examine the key architectural concepts and foundational components."

        body_sentences = []
        for bp in bullet_points[:6]:  # Keep to main points
            # Ensure proper capitalization and punctuation
            sentence = bp[0].upper() + bp[1:]
            if not sentence.endswith((".", "!", "?")):
                sentence += "."
            body_sentences.append(sentence)

        explanation = " Specifically, " + " Furthermore, ".join(body_sentences[:2])
        if len(body_sentences) > 2:
            explanation += " In addition, " + " ".join(body_sentences[2:])

        return f"{intro}{explanation}"


class NarrationManager:
    """Manages project slide narrations, editing, and approvals."""

    def __init__(self, project: Project):
        self.project = project

    def generate_initial_narrations(self) -> List[SlideNarration]:
        """Generate initial draft narration scripts for all slides if not already created."""
        existing_map = {n.slide_id: n for n in self.project.narrations}
        narrations: List[SlideNarration] = []

        for slide in self.project.slides:
            if slide.slide_id in existing_map:
                narrations.append(existing_map[slide.slide_id])
                continue

            script = ScriptManager.draft_narration_from_slide(slide)
            narration = SlideNarration(
                slide_id=slide.slide_id,
                slide_number=slide.slide_number,
                script=script,
                status=NarrationStatus.DRAFT,
            )
            narration.calculate_metrics()
            narrations.append(narration)

        self.project.narrations = narrations
        return narrations

    def update_script(self, slide_id: str, new_script: str) -> SlideNarration:
        """Update script content, calculate metrics, and mark as EDITED."""
        narration = self.project.get_narration_by_id(slide_id)
        if not narration:
            raise ValueError(f"Narration for slide {slide_id} not found.")

        narration.script = new_script
        narration.status = NarrationStatus.EDITED
        narration.calculate_metrics()

        # Existing audio is preserved until the user explicitly regenerates it;
        # it is reported as "outdated" because the text no longer matches.

        # Reset presentation-level narration approval
        self.project.narration_approved = False
        return narration

    def approve_narration(self, slide_id: str) -> SlideNarration:
        """Approve an individual slide narration."""
        narration = self.project.get_narration_by_id(slide_id)
        if not narration:
            raise ValueError(f"Narration for slide {slide_id} not found.")

        narration.status = NarrationStatus.APPROVED
        return narration

    def approve_all(self) -> Tuple[bool, str]:
        """Approve all narration scripts if valid."""
        for n in self.project.narrations:
            n.status = NarrationStatus.APPROVED
        self.project.narration_approved = True
        return True, "All narration scripts approved."
