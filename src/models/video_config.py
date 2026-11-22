"""Video and audio configuration model."""
from dataclasses import dataclass, asdict, field
from typing import Dict, Any


@dataclass
class VideoConfig:
    resolution: str = "1920x1080"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    format: str = "mp4"
    video_codec: str = "h264"
    audio_codec: str = "aac"
    aspect_ratio: str = "16:9"
    transition: str = "fade"                # default slide transition (src/backend/video/transitions.py)
    transition_duration: float = 0.5
    # slide_id -> {"type": str, "duration": float}; overrides the default for that slide's entry
    slide_transitions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    slide_pause: float = 0.8  # seconds pause after slide speech
    burn_subtitles: bool = False
    subtitle_font_size: int = 24
    subtitle_position: str = "bottom"
    tts_engine: str = "kokoro-82m"          # see src/backend/tts/registry.py
    voice_id: str = "af_heart"              # global speaker (single-speaker mode)
    speech_speed: float = 1.0
    speech_volume: float = 1.0
    speaker_mode: str = "single"            # "single" | "per_slide"
    sentence_pause: float = 0.3             # seconds, engines with pause support
    clause_pause: float = 0.1
    # term -> spoken form; seeded from the project's content profile (see src/backend/content/profiles/)
    pronunciations: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
