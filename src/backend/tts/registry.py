"""Registry of available local TTS engines. Kokoro-82M is the default.

To integrate another local model later, implement `TTSEngine` and add it to `_build()`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from src.backend.tts.base import TTSEngine

DEFAULT_ENGINE = "kokoro-82m"
_ENGINES: Optional[Dict[str, TTSEngine]] = None


def user_models_dir() -> Path:
    """Per-user model storage when the application folder is read-only (e.g. installed system-wide)."""
    home = Path.home()
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "LectureStudio"
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support" / "LectureStudio"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "lecture-studio"
    return base / "models"


def models_root() -> Path:
    """Model folder: $LECTURE_STUDIO_MODELS, else <app>/models if usable, else the per-user data folder."""
    env = os.environ.get("LECTURE_STUDIO_MODELS")
    if env:
        return Path(env).expanduser()
    app = Path(__file__).resolve().parents[3] / "models"
    if app.is_dir() or os.access(app.parent, os.W_OK):
        return app
    return user_models_dir()


def _build() -> Dict[str, TTSEngine]:
    from src.backend.tts.kokoro_engine import KokoroEngine
    from src.backend.tts.say_engine import SayEngine
    from src.backend.tts.qwen3_engine import build_qwen3_engines
    tts_root = models_root() / "tts"
    engines: List[TTSEngine] = [KokoroEngine(tts_root / "kokoro-82m")]
    engines += build_qwen3_engines(tts_root)
    engines.append(SayEngine())
    engines += custom_engines()
    return {e.id: e for e in engines}


def custom_engines() -> List[TTSEngine]:
    """Engines for models the user imported (see src/backend/tts/custom/). Broken entries are skipped."""
    from src.backend.tts.custom.formats import FORMATS
    from src.backend.tts.custom.store import CustomModelStore
    out = []
    for entry in CustomModelStore().entries():
        fmt = FORMATS.get(entry["format"])
        if not fmt:
            continue
        try:
            out.append(fmt.create(entry))
        except Exception:
            continue
    return out


def reset() -> None:
    """Completely clear cached engines."""
    global _ENGINES
    _ENGINES = None


def reload() -> None:
    """Rebuild the engine list after models are imported, renamed or removed (keeps loaded engines)."""
    global _ENGINES
    old = _ENGINES or {}
    new = _build()
    for eid, eng in new.items():           # keep already-loaded built-in engines (avoid reloading weights)
        if eid in old and not getattr(eng, "custom", False):
            old_root = getattr(old[eid], "model_dir", getattr(old[eid], "tts_root", None))
            new_root = getattr(eng, "model_dir", getattr(eng, "tts_root", None))
            if old_root == new_root and old[eid]._state == "ready":
                new[eid] = old[eid]
    _ENGINES = new


def has_engine(engine_id: Optional[str]) -> bool:
    engines()
    return bool(engine_id) and engine_id in _ENGINES


def engines() -> List[TTSEngine]:
    global _ENGINES
    if _ENGINES is None:
        _ENGINES = _build()
    return list(_ENGINES.values())


def get_engine(engine_id: Optional[str]) -> TTSEngine:
    engines()
    return _ENGINES.get(engine_id or "") or _ENGINES[DEFAULT_ENGINE]
