"""Project data model and workflow stages."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional

from src.models.slide import Slide
from src.models.narration import SlideNarration
from src.models.video_config import VideoConfig


class WorkflowStage(str, Enum):
    IMPORTED = "imported"
    SLIDE_PREPARATION = "slide_preparation"
    SLIDE_REVIEW = "slide_review"
    SLIDES_APPROVED = "slides_approved"
    NARRATION_PREPARATION = "narration_preparation"
    NARRATION_REVIEW = "narration_review"
    NARRATION_APPROVED = "narration_approved"
    AUDIO_GENERATION = "audio_generation"
    VIDEO_PREVIEW = "video_preview"
    VIDEO_EXPORT = "video_export"
    COMPLETED = "completed"


@dataclass
class Project:
    project_id: str
    project_name: str
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    source_file: str = ""  # relative to project directory: source/...
    source_type: str = "pdf"  # "pdf" or "pptx"
    slide_count: int = 0
    workflow_stage: WorkflowStage = WorkflowStage.IMPORTED
    slides_approved: bool = False
    narration_approved: bool = False
    audio_generated: bool = False
    video_exported: bool = False
    slides: List[Slide] = field(default_factory=list)
    narrations: List[SlideNarration] = field(default_factory=list)
    settings: VideoConfig = field(default_factory=VideoConfig)
    project_dir: str = ""  # Absolute path to project root
    notes: str = ""
    companion: Dict[str, Any] = field(default_factory=dict)  # imported lecture package info
    content_profile: str = "generic"     # optional topic profile id (src/backend/content/profiles)
    original_source: str = ""            # original file when the source was converted (e.g. source/original.md)

    def get_slide_by_id(self, slide_id: str) -> Optional[Slide]:
        for s in self.slides:
            if s.slide_id == slide_id:
                return s
        return None

    def get_narration_by_id(self, slide_id: str) -> Optional[SlideNarration]:
        for n in self.narrations:
            if n.slide_id == slide_id:
                return n
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": datetime.now().isoformat(),
            "source_file": self.source_file,
            "source_type": self.source_type,
            "slide_count": len(self.slides),
            "workflow_stage": self.workflow_stage.value,
            "slides_approved": self.slides_approved,
            "narration_approved": self.narration_approved,
            "audio_generated": self.audio_generated,
            "video_exported": self.video_exported,
            "settings": self.settings.to_dict(),
            "slides": [s.to_dict() for s in self.slides],
            "narrations": [n.to_dict() for n in self.narrations],
            "notes": self.notes,
            "companion": self.companion,
            "content_profile": self.content_profile,
            "original_source": self.original_source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], project_dir: str = "") -> "Project":
        stage_val = data.get("workflow_stage", WorkflowStage.IMPORTED.value)
        try:
            stage = WorkflowStage(stage_val)
        except ValueError:
            stage = WorkflowStage.IMPORTED

        slides = [Slide.from_dict(s) for s in data.get("slides", [])]
        narrations = [SlideNarration.from_dict(n) for n in data.get("narrations", [])]
        settings_data = data.get("settings", {})
        settings = VideoConfig.from_dict(settings_data) if settings_data else VideoConfig()

        return cls(
            project_id=data.get("project_id", "project"),
            project_name=data.get("project_name", "Untitled Project"),
            version=data.get("version", 1),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            source_file=data.get("source_file", ""),
            source_type=data.get("source_type", "pdf"),
            slide_count=len(slides),
            workflow_stage=stage,
            slides_approved=data.get("slides_approved", False),
            narration_approved=data.get("narration_approved", False),
            audio_generated=data.get("audio_generated", False),
            video_exported=data.get("video_exported", False),
            slides=slides,
            narrations=narrations,
            settings=settings,
            project_dir=project_dir,
            notes=data.get("notes", ""),
            companion=data.get("companion", {}) or {},
            content_profile=data.get("content_profile", "generic") or "generic",
            original_source=data.get("original_source", ""),
        )
