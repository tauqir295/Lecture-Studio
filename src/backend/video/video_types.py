"""Video types: presets that adapt frame shape, pacing, transitions, layout and narration style.

A video type only *sets defaults* (all values stay editable afterwards). It never changes narration
text or slide content, so the PDF-to-tutorial workflow behaves exactly as before with "tutorial".

Layouts (how a slide image fills the output frame, see pipeline.body_filter):
  fit        whole slide, letter-/pillar-boxed on black
  fill_blur  whole slide over a blurred, enlarged copy of itself (good for vertical / photos)
  ken_burns  slow zoom across the slide (photos, documentaries, explainers)
Overlays: none | waveform (audio waveform strip, podcast style) | progress (thin progress bar)

New types: call `register(VideoType(...))`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

ASPECTS: Dict[str, Tuple[int, int]] = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080),
                                       "4:5": (1080, 1350)}
LAYOUTS = {"fit": "Fit whole slide (bars)", "fill_blur": "Fill frame (blurred background)",
           "ken_burns": "Slow zoom (Ken Burns)"}
OVERLAYS = {"none": "None", "waveform": "Audio waveform", "progress": "Progress bar"}


@dataclass(frozen=True)
class VideoType:
    key: str
    label: str
    description: str
    aspect: str = "16:9"
    layout: str = "fit"
    overlay: str = "none"
    transition: str = "fade"
    transition_duration: float = 0.5
    emotion: str = "neutral"
    reading_seconds: float = 1.0      # extra hold after narration
    min_slide_seconds: float = 3.0
    speed: float = 1.0                # narration tempo in Video Studio
    tips: str = ""                    # advice on structuring scenes/narration for this type


_TYPES: Dict[str, VideoType] = {}


def register(t: VideoType) -> None:
    _TYPES[t.key] = t


for _t in (
    VideoType("tutorial", "Educational tutorial / slide lesson",
              "Slide-based lesson: full slides, calm fades, time to read.", tips=
              "One idea per slide; narration explains what is on screen."),
    VideoType("explainer", "Explainer / animated concept",
              "Concept explained scene by scene with gentle motion and crossfades.",
              layout="ken_burns", transition="crossfade", transition_duration=0.75, emotion="friendly",
              reading_seconds=0.6, min_slide_seconds=2.5, tips=
              "Short scenes, one visual each; start with the problem, end with the takeaway."),
    VideoType("storytelling", "Storytelling / documentary",
              "Slow zooms over images, long dissolves and an unhurried narrator.",
              layout="ken_burns", transition="dissolve", transition_duration=1.5, emotion="storytelling",
              reading_seconds=1.5, min_slide_seconds=4.0, tips=
              "Use image-led slides; narration carries the story, text on screen stays minimal."),
    VideoType("software", "Software tutorial / walkthrough",
              "Screenshots and code shown in full with quick cuts so steps stay readable.",
              transition="none", emotion="neutral", reading_seconds=1.5, min_slide_seconds=4.0, tips=
              "One step per slide; say exactly what to click or type."),
    VideoType("news", "News / commentary",
              "Brisk pacing, slide transitions and a progress bar.",
              layout="fill_blur", overlay="progress", transition="slide_left", transition_duration=0.5,
              emotion="serious", reading_seconds=0.4, min_slide_seconds=2.5, speed=1.05, tips=
              "Lead with the headline; one fact per slide."),
    VideoType("training", "Training / presentation",
              "Corporate training or talk: full slides, crossfades, steady delivery.",
              transition="crossfade", emotion="serious", reading_seconds=1.2, tips=
              "Agenda first, summary last; keep slides consistent."),
    VideoType("promo", "Promotional / product video",
              "Energetic product video: zooms, wipes, enthusiastic narration.",
              layout="ken_burns", transition="zoom_in", transition_duration=0.5, emotion="enthusiastic",
              reading_seconds=0.3, min_slide_seconds=2.0, speed=1.05, tips=
              "Benefit first, call to action at the end; short punchy lines."),
    VideoType("short", "Short-form vertical (9:16)",
              "Vertical video for phones: slide fills the frame over a blurred background, fast pacing.",
              aspect="9:16", layout="fill_blur", overlay="progress", transition="slide_up",
              transition_duration=0.25, emotion="enthusiastic", reading_seconds=0.2, min_slide_seconds=1.5,
              speed=1.1, tips="Keep the whole video under 60 s: choose a small slide range."),
    VideoType("podcast", "Podcast-style video",
              "Narration-led: static slide with an audio waveform, long crossfades, conversational voice.",
              layout="fill_blur", overlay="waveform", transition="crossfade", transition_duration=1.0,
              emotion="friendly", reading_seconds=0.8, tips="Use one cover slide per topic segment."),
    VideoType("photo", "Narrated photo video",
              "Photos with slow zooms and dissolves (import a PDF of photos, or Markdown with images).",
              layout="ken_burns", transition="dissolve", transition_duration=1.0, emotion="calm",
              reading_seconds=1.0, min_slide_seconds=4.0, tips="One photo per slide; describe what matters in it."),
):
    register(_t)

DEFAULT = "tutorial"


def types() -> List[VideoType]:
    return list(_TYPES.values())


def get(key: str) -> VideoType:
    return _TYPES.get(key) or _TYPES[DEFAULT]


def apply_to_config(vc, key: str) -> VideoType:
    """Set the project's video defaults (frame, layout, overlay, transition, delivery style) for a type.
    Per-slide transitions and per-slide styles are kept."""
    t = get(key)
    vc.video_type = t.key
    vc.aspect_ratio = t.aspect
    vc.width, vc.height = ASPECTS[t.aspect]
    vc.resolution = f"{vc.width}x{vc.height}"
    vc.layout, vc.overlay = t.layout, t.overlay
    vc.transition, vc.transition_duration = t.transition, t.transition_duration
    vc.emotion = t.emotion
    return t


def set_aspect(vc, aspect: str) -> None:
    vc.aspect_ratio = aspect
    vc.width, vc.height = ASPECTS[aspect]
    vc.resolution = f"{vc.width}x{vc.height}"
