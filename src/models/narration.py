"""Narration data model and status enumeration."""
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import field


class NarrationStatus(str, Enum):
    DRAFT = "draft"
    EDITED = "edited"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class SlideNarration:
    slide_id: str
    slide_number: int
    script: str = ""
    word_count: int = 0
    estimated_duration: float = 0.0  # seconds
    status: NarrationStatus = NarrationStatus.DRAFT
    audio_path: Optional[str] = None  # relative: audio/slide_001.wav
    audio_duration: Optional[float] = None  # actual duration in seconds
    audio_status: str = "none"  # "none", "generating", "ready", "failed"
    error_message: Optional[str] = None
    speaker: Optional[str] = None  # per-slide speaker (used in "per_slide" mode)
    emotion: Optional[str] = None  # per-slide delivery style; None = project default (src/backend/tts/emotion.py)
    audio_meta: Dict[str, Any] = field(default_factory=dict)  # what the audio was generated from

    def calculate_metrics(self, words_per_minute: int = 140) -> None:
        words = self.script.strip().split()
        self.word_count = len(words)
        self.estimated_duration = round((self.word_count / max(words_per_minute, 60)) * 60, 2)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SlideNarration":
        status_val = data.get("status", NarrationStatus.DRAFT.value)
        try:
            status = NarrationStatus(status_val)
        except ValueError:
            status = NarrationStatus.DRAFT
        data_copy = dict(data)
        data_copy["status"] = status
        return cls(**data_copy)
