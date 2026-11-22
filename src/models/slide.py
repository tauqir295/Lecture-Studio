"""Slide data model and review status enumeration."""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, List, Dict, Any


class SlideReviewStatus(str, Enum):
    DRAFT = "draft"
    EDITED = "edited"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class Slide:
    slide_id: str
    slide_number: int  # 1-based index
    title: str = ""
    original_text: str = ""
    notes: str = ""
    image_path: Optional[str] = None  # relative to project directory: slides/slide_001.png
    thumbnail_path: Optional[str] = None  # preview/slide_001_thumb.png
    review_status: SlideReviewStatus = SlideReviewStatus.DRAFT
    warnings: List[str] = field(default_factory=list)
    revision_notes: str = ""
    duration_estimate: float = 0.0  # seconds
    word_count: int = 0
    mode: str = "original"  # "original" or "enhanced"
    enhanced_text: Optional[str] = None
    enhanced_notes: Optional[str] = None
    is_empty: bool = False
    is_image_only: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["review_status"] = self.review_status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Slide":
        status_val = data.get("review_status", SlideReviewStatus.DRAFT.value)
        try:
            status = SlideReviewStatus(status_val)
        except ValueError:
            status = SlideReviewStatus.DRAFT
        data_copy = dict(data)
        data_copy["review_status"] = status
        return cls(**data_copy)
