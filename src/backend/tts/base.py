"""Pluggable local text-to-speech engine interface.

To add a model: subclass `TTSEngine`, implement the abstract methods, and register
it in `src/backend/tts/registry.py`. Engines must work offline once installed.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import numpy as np

# Engine states shown in the UI
NOT_INSTALLED = "not installed"
INSTALLED = "installed"
LOADING = "loading"
READY = "ready"
UNAVAILABLE = "unavailable"
ERROR = "error"


@dataclass(frozen=True)
class Speaker:
    id: str
    name: str
    language: str = ""          # human readable, e.g. "English (US)"
    gender: str = ""            # presentation as published by the voice author
    style: str = ""             # short description / notes
    recommended: bool = False

    @property
    def label(self) -> str:
        bits = [b for b in (self.language, self.gender) if b]
        star = "★ " if self.recommended else ""
        return f"{star}{self.name}" + (f"  ·  {' · '.join(bits)}" if bits else "")

    @property
    def is_english(self) -> bool:
        return self.language.lower().startswith("english")


@dataclass(frozen=True)
class Capabilities:
    speed_range: Tuple[float, float] = (0.5, 2.0)
    pauses: bool = False          # adjustable sentence / clause pauses
    pronunciation: bool = True    # text-substitution dictionary (engine independent)
    emphasis: bool = False
    expressiveness: bool = False  # adjustable intonation variation (see src/backend/tts/emotion.py)
    styles: Tuple[str, ...] = ()  # delivery styles the model performs natively (emotion keys)
    instructions: bool = False    # genuine instruction-based emotion, tone, speaking style and prosody controls
    voice_design: bool = False    # supports prompt-based voice creation


@dataclass
class EngineStatus:
    state: str
    message: str = ""


class TTSEngine(ABC):
    id: str = ""
    name: str = ""
    description: str = ""
    license_summary: str = ""
    capabilities: Capabilities = Capabilities()
    sample_rate: int = 24000
    downloadable: bool = False    # True when `download()` can fetch the model files
    custom: bool = False          # True for user-imported models (src/backend/tts/custom/)

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state: Optional[str] = None
        self._error = ""
        self._expressiveness = 1.0     # set per call by synthesize(); read by engines that support it
        self._style = ""

    # ---- lifecycle
    @abstractmethod
    def is_installed(self) -> Tuple[bool, str]:
        """(installed?, explanation when not)."""

    def status(self) -> EngineStatus:
        if self._state in (LOADING, READY, ERROR):
            return EngineStatus(self._state, self._error)
        ok, why = self.is_installed()
        return EngineStatus(INSTALLED if ok else NOT_INSTALLED, "" if ok else why)

    def load(self) -> None:
        """Load model into memory (idempotent, thread safe)."""
        with self._lock:
            if self._state == READY:
                return
            ok, why = self.is_installed()
            if not ok:
                raise RuntimeError(why)
            self._state = LOADING
            try:
                self._load()
                self._state, self._error = READY, ""
            except Exception as exc:
                self._state, self._error = ERROR, str(exc)
                raise

    def _load(self) -> None:
        """Override for engines that need an explicit load step."""

    # ---- voices
    @abstractmethod
    def speakers(self) -> List[Speaker]:
        ...

    def default_speaker(self) -> str:
        sp = self.speakers()
        rec = [s for s in sp if s.recommended]
        return (rec or sp)[0].id if sp else ""

    def find_speaker(self, speaker_id: str) -> Optional[Speaker]:
        return next((s for s in self.speakers() if s.id == speaker_id), None)

    # ---- synthesis
    @abstractmethod
    def _synthesize(self, text: str, speaker: str, speed: float,
                    sentence_pause: float, clause_pause: float) -> Tuple[np.ndarray, int]:
        ...

    def synthesize(self, text: str, speaker: str, speed: float = 1.0,
                   sentence_pause: float = 0.3, clause_pause: float = 0.1,
                   expressiveness: float = 1.0, style: str = "") -> Tuple[np.ndarray, int]:
        """`expressiveness` is used only if capabilities.expressiveness; `style` only if it is in
        capabilities.styles. Engines read them from self._expressiveness / self._style."""
        lo, hi = self.capabilities.speed_range
        speed = min(max(speed, lo), hi)
        self.load()
        with self._lock:
            self._expressiveness = expressiveness if self.capabilities.expressiveness else 1.0
            self._style = style if style in self.capabilities.styles else ""
            try:
                return self._synthesize(text, speaker, speed, sentence_pause, clause_pause)
            finally:
                self._expressiveness, self._style = 1.0, ""

    def sample_sentence(self, speaker: str) -> str:
        return ("Hello! This is a sample of my voice. In this tutorial we will explore the topic "
                "step by step, with clear explanations and practical examples.")

    def download(self, progress: Optional[Callable[[int, str], None]] = None,
                 cancel: Callable[[], bool] = lambda: False) -> None:
        raise NotImplementedError("This engine does not support downloading.")

    def verify(self) -> Tuple[bool, str]:
        ok, why = self.is_installed()
        return ok, "Verified and ready for offline inference." if ok else why

    def remove(self) -> bool:
        return False
