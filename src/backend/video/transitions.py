"""Slideshow-style transitions between slides (PowerPoint semantics).

A slide's transition describes how it *enters* from the previous slide. It is rendered as a
separate, silent clip between two still images, so narration and subtitles are never overlapped:

    [slide 1 body] [transition 1->2] [slide 2 body] [transition 2->3] [slide 3 body] ...

The first slide of a rendered range has no incoming transition (the video starts on it) and the
last slide simply ends. Transition time is added to the total duration.

Pure logic + ffmpeg filter strings (no Qt). New effects are added with `register()`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

NONE = "none"
DURATIONS: List[float] = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0]
MIN_DURATION, MAX_DURATION = 0.1, 5.0

# builder(a_label, b_label, duration_s, frames, width, height) -> filter chain ending in "[v]"
Builder = Callable[[str, str, float, int, int, int], str]


@dataclass(frozen=True)
class TransitionType:
    key: str
    label: str
    builder: Optional[Builder]          # None only for "none"


_REGISTRY: Dict[str, TransitionType] = {}


def register(key: str, label: str, builder: Optional[Builder]) -> None:
    """Add (or replace) a transition effect. Order of registration = order in the UI."""
    _REGISTRY[key] = TransitionType(key, label, builder)


def _xfade(name: str) -> Builder:
    return lambda a, b, d, n, w, h: f"[{a}][{b}]xfade=transition={name}:duration={d:.3f}:offset=0[v]"


def _zoom_out(a: str, b: str, d: float, n: int, w: int, h: int) -> str:
    # Next slide grows from the centre over the previous one (cheap: per-frame scale + overlay).
    f = f"(n+1)/{max(n, 1)}"
    return (f"[{b}]scale=w='max(2,trunc({w}*{f}/2)*2)':h='max(2,trunc({h}*{f}/2)*2)':eval=frame[zb];"
            f"[{a}][zb]overlay=x='(W-w)/2':y='(H-h)/2':eval=frame:shortest=1,format=yuv420p[v]")


register(NONE, "None / Cut", None)
register("fade", "Fade (through black)", _xfade("fadeblack"))
register("crossfade", "Crossfade", _xfade("fade"))
register("dissolve", "Dissolve", _xfade("dissolve"))
for _d in ("left", "right", "up", "down"):
    register(f"slide_{_d}", f"Slide {_d.title()}", _xfade(f"slide{_d}"))
for _d in ("left", "right", "up", "down"):
    register(f"wipe_{_d}", f"Wipe {_d.title()}", _xfade(f"wipe{_d}"))
register("zoom_in", "Zoom In", _xfade("zoomin"))
register("zoom_out", "Zoom Out", _zoom_out)

# Cycle used by "Vary transitions" (deterministic, so re-applying gives the same result).
VARY_CYCLE = ["crossfade", "slide_left", "wipe_right", "zoom_in", "slide_up", "fade", "wipe_down", "zoom_out"]


def types() -> List[TransitionType]:
    return list(_REGISTRY.values())


def get(key: str) -> TransitionType:
    return _REGISTRY.get(key) or _REGISTRY[NONE]


def label(key: str) -> str:
    return get(key).label


def clamp_duration(d: float) -> float:
    return round(min(max(float(d), MIN_DURATION), MAX_DURATION), 3)


def resolve(settings, slide_id: str) -> Tuple[str, float]:
    """(type, duration) a slide enters with: its own override, else the project default.

    `settings` is a VideoConfig (transition, transition_duration, slide_transitions).
    """
    o = (getattr(settings, "slide_transitions", None) or {}).get(slide_id) or {}
    key = o.get("type", settings.transition)
    if key not in _REGISTRY:
        key = NONE
    dur = clamp_duration(o.get("duration", settings.transition_duration))
    return key, (0.0 if key == NONE else dur)


def incoming(settings, slide_ids: List[str]) -> Dict[str, Tuple[str, float]]:
    """Incoming transition per slide of a rendered range; the first slide gets none."""
    out = {}
    for i, sid in enumerate(slide_ids):
        out[sid] = (NONE, 0.0) if i == 0 else resolve(settings, sid)
    return out


def filter_graph(key: str, duration: float, frames: int, width: int, height: int,
                 a: str = "a", b: str = "b") -> str:
    t = get(key)
    if t.builder is None:
        raise ValueError("'none' has no transition clip")
    return t.builder(a, b, duration, frames, width, height)


def frames_for(duration: float, fps: float) -> int:
    return max(int(round(duration * fps)), 0)
