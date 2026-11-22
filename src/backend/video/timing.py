"""Slide-range selection and timing plan for video generation.

Pure logic (no Qt, no subprocesses) so it is easy to test.

Timing priority (when a target duration is set):
  1. Respect the selected slide range.
  2./3. Never shorten, drop or summarise narration text.
  4. Adjust slide display time (extra hold after narration).
  5. Adjust narration speed, only within the configured limits.
  6. Otherwise report the target as not feasible, with the reachable range.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from src.models.narration import SlideNarration
from src.models.slide import Slide


def count_words(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


@dataclass
class RenderSettings:
    start: int = 1                       # 1-based, inclusive
    end: int = 1                         # 1-based, inclusive
    target_seconds: Optional[float] = None   # None = natural length
    base_wpm: int = 150                  # estimate for slides without generated audio
    speed: float = 1.0                   # tempo applied to narration audio (1.0 = as generated)
    allow_speed_adjust: bool = True      # may change speed to hit target
    min_speed: float = 0.85
    max_speed: float = 1.20
    auto_sync: bool = True               # slide time follows narration
    fixed_slide_seconds: float = 20.0    # used when auto_sync is off
    min_slide_seconds: float = 3.0
    reading_seconds: float = 1.0         # extra hold after narration
    max_extra_hold: float = 20.0         # cap of added hold per slide when stretching
    transition_seconds: float = 0.5
    regenerate_outdated: bool = False    # re-synthesize audio whose text/voice changed
    name: str = ""                       # optional output name

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "RenderSettings":
        return cls(**{k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__})


def validate_range(start: int, end: int, total: int) -> Optional[str]:
    """Return an error message, or None if the range is valid."""
    if total <= 0:
        return "The presentation has no slides."
    if start < 1 or end < 1:
        return "Slide numbers start at 1."
    if start > total or end > total:
        return f"The presentation only has {total} slides."
    if start > end:
        return f"'From' ({start}) must not be greater than 'To' ({end})."
    return None


@dataclass
class SlideTiming:
    slide_id: str
    slide_number: int
    title: str
    words: int
    narration_seconds: float   # speech length at the planned speed (estimate or measured)
    hold_seconds: float        # silent display after speech
    transition_seconds: float  # incoming transition (silent, before the narration starts)
    transition_type: str = "none"

    @property
    def display_seconds(self) -> float:
        return self.narration_seconds + self.hold_seconds + self.transition_seconds


@dataclass
class TimingPlan:
    slides: List[SlideTiming]
    speed: float
    wpm: int
    target_seconds: Optional[float]
    min_achievable: float
    max_achievable: Optional[float]
    feasible: bool
    warnings: List[str] = field(default_factory=list)

    @property
    def total_seconds(self) -> float:
        return sum(s.display_seconds for s in self.slides)

    @property
    def narration_seconds(self) -> float:
        return sum(s.narration_seconds for s in self.slides)


def fmt_duration(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _base_hold(narr: float, cfg: RenderSettings) -> float:
    """Hold time before any target fitting."""
    if cfg.auto_sync:
        return max(cfg.reading_seconds, cfg.min_slide_seconds - narr, 0.0)
    return max(cfg.fixed_slide_seconds - narr, 0.0)


def _min_hold(narr: float, cfg: RenderSettings) -> float:
    """Shortest allowed hold: honours the minimum display time, drops reading time."""
    return max(cfg.min_slide_seconds - narr, 0.0)


def plan_timing(
    slides: Sequence[Slide],
    narrations: Sequence[SlideNarration],
    cfg: RenderSettings,
    measured: Optional[Dict[str, float]] = None,
    transitions: Optional[Dict[str, Tuple[str, float]]] = None,
) -> TimingPlan:
    """Build the timing plan for the selected range.

    `measured` maps slide_id -> real narration audio seconds at tempo 1.0.
    Slides without a measurement are estimated from word count and `base_wpm`.
    `transitions` maps slide_id -> (type, seconds) of its incoming transition (see transitions.incoming).
    Without it, every slide except the first enters with a crossfade of `cfg.transition_seconds`.
    """
    err = validate_range(cfg.start, cfg.end, len(slides))
    if err:
        raise ValueError(err)
    narr_by_id = {n.slide_id: n for n in narrations}
    chosen = [s for s in slides if cfg.start <= s.slide_number <= cfg.end]
    words = {s.slide_id: count_words(narr_by_id[s.slide_id].script) if s.slide_id in narr_by_id else 0
             for s in chosen}
    warnings: List[str] = []
    missing = [s.slide_number for s in chosen if words[s.slide_id] == 0]
    if missing:
        warnings.append(f"Slides without narration (shown silently): {missing}")

    def narr_secs(sid: str, speed: float) -> float:
        if measured is not None and sid in measured:
            return measured[sid] / speed
        return words[sid] / (cfg.base_wpm * speed) * 60.0

    if transitions is None:
        t0 = ("crossfade", cfg.transition_seconds) if cfg.transition_seconds > 0 else ("none", 0.0)
        transitions = {s.slide_id: (("none", 0.0) if i == 0 else t0) for i, s in enumerate(chosen)}
    trans_of = {s.slide_id: transitions.get(s.slide_id, ("none", 0.0)) for s in chosen}
    trans_of[chosen[0].slide_id] = ("none", 0.0)          # the video starts on the first slide
    trans_total = sum(d for _, d in trans_of.values())

    def total(speed: float, hold_fn) -> float:
        return trans_total + sum(narr_secs(s.slide_id, speed) + hold_fn(narr_secs(s.slide_id, speed)) for s in chosen)

    speed = cfg.speed
    can_tune_speed = cfg.allow_speed_adjust
    lo_speed = min(cfg.min_speed, speed) if can_tune_speed else speed
    hi_speed = max(cfg.max_speed, speed) if can_tune_speed else speed

    base = lambda n: _base_hold(n, cfg)
    minh = lambda n: _min_hold(n, cfg)
    maxh = lambda n: _base_hold(n, cfg) + cfg.max_extra_hold

    min_achievable = total(hi_speed, minh)
    max_achievable = total(lo_speed, maxh)
    target = cfg.target_seconds
    hold_scale: Tuple[str, float] = ("base", 0.0)   # how holds are derived
    feasible = True

    if target:
        natural = total(speed, base)
        if natural > target:
            # Too long: first shrink holds toward the minimum (priority 4) ...
            shortest = total(speed, minh)
            if shortest <= target:
                hold_scale = ("shrink", _solve(lambda f: total(speed, lambda n: base(n) - f * (base(n) - minh(n))), target, decreasing=True))
            elif can_tune_speed and min_achievable <= target:
                # ... then speed up narration (priority 5), holds at minimum.
                speed = _solve(lambda sp: total(sp, minh), target, lo=speed, hi=hi_speed, decreasing=True)
                hold_scale = ("shrink", 1.0)
            else:
                speed, hold_scale, feasible = hi_speed, ("shrink", 1.0), False
                warnings.append(
                    f"Target {fmt_duration(target)} is too short for slides {cfg.start}–{cfg.end}: the shortest "
                    f"possible length without cutting narration is {fmt_duration(min_achievable)}. "
                    "Choose fewer slides, a longer target, or shorten scripts in Narration Studio.")
        elif natural < target:
            # Too short: first add display time (priority 4) ...
            longest = total(speed, maxh)
            if longest >= target:
                hold_scale = ("grow", _solve(lambda f: total(speed, lambda n: base(n) + f * cfg.max_extra_hold), target, decreasing=False))
            elif can_tune_speed and max_achievable >= target:
                # ... then slow narration down within limits (priority 5).
                speed = _solve(lambda sp: total(sp, maxh), target, lo=lo_speed, hi=speed, decreasing=True)
                hold_scale = ("grow", 1.0)
            else:
                speed, hold_scale, feasible = lo_speed, ("grow", 1.0), False
                warnings.append(
                    f"Target {fmt_duration(target)} is too long for slides {cfg.start}–{cfg.end}: at most "
                    f"{fmt_duration(max_achievable)} is reasonable (max {cfg.max_extra_hold:.0f}s extra per slide). "
                    "Choose more slides or a shorter target.")
        if feasible and abs(speed - cfg.speed) > 0.005:
            warnings.append(f"Narration speed adjusted from {cfg.speed:.2f}× to {speed:.2f}× to fit the target.")

    mode, f = hold_scale
    timings = []
    for s in chosen:
        n = narr_secs(s.slide_id, speed)
        if mode == "shrink":
            hold = base(n) - f * (base(n) - minh(n))
        elif mode == "grow":
            hold = base(n) + f * cfg.max_extra_hold
        else:
            hold = base(n)
        timings.append(SlideTiming(s.slide_id, s.slide_number, s.title, words[s.slide_id],
                                   round(n, 3), round(max(hold, 0.0), 3), trans_of[s.slide_id][1],
                                   trans_of[s.slide_id][0]))

    if not cfg.auto_sync:
        longer = [t.slide_number for t in timings if t.narration_seconds > cfg.fixed_slide_seconds]
        if longer:
            warnings.append(f"Narration is longer than the fixed slide time on slides {longer[:10]}"
                            f"{'…' if len(longer) > 10 else ''}; those slides stay up until narration ends.")
    return TimingPlan(timings, round(speed, 3), int(round(cfg.base_wpm * speed)), target,
                      min_achievable, max_achievable, feasible, warnings)


def _solve(fn, target: float, lo: float = 0.0, hi: float = 1.0, decreasing: bool = True) -> float:
    """Bisection for fn(x) == target on [lo, hi]; fn monotonic."""
    for _ in range(60):
        mid = (lo + hi) / 2
        val = fn(mid)
        if (val > target) == decreasing:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
