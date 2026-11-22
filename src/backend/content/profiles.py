"""Optional topic profiles (data, not code).

A profile carries topic knowledge — detection keywords and TTS pronunciations — and
is kept entirely outside the core pipeline. Built-in profiles live in
`src/backend/content/profiles/*.json`; users can add their own JSON files in
`<workspace>/profiles/` (same schema) without touching code.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

BUILTIN_DIR = Path(__file__).resolve().parent / "profiles"
GENERIC = "generic"


@dataclass
class ContentProfile:
    id: str
    name: str
    description: str = ""
    keywords: List[str] = field(default_factory=list)
    pronunciations: Dict[str, str] = field(default_factory=dict)
    path: Optional[Path] = None


def load_profiles(extra_dirs: Optional[List[Path]] = None) -> Dict[str, ContentProfile]:
    out: Dict[str, ContentProfile] = {}
    for d in [BUILTIN_DIR, *(extra_dirs or [])]:
        if not d or not Path(d).is_dir():
            continue
        for f in sorted(Path(d).glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                prof = ContentProfile(id=data["id"], name=data.get("name", data["id"]),
                                      description=data.get("description", ""),
                                      keywords=list(data.get("keywords", [])),
                                      pronunciations=dict(data.get("pronunciations", {})), path=f)
                out[prof.id] = prof        # user profiles may override built-ins
            except (OSError, ValueError, KeyError):
                continue
    if GENERIC not in out:
        out[GENERIC] = ContentProfile(GENERIC, "General (any topic)")
    return out


def detect_profile(text: str, profiles: Dict[str, ContentProfile], min_hits: int = 4) -> str:
    """Pick the profile whose keywords occur most often; 'generic' when nothing stands out."""
    best, best_score = GENERIC, 0
    for p in profiles.values():
        if not p.keywords:
            continue
        score = sum(len(re.findall(rf"(?<![\w/]){re.escape(k)}(?![\w])", text, flags=re.IGNORECASE))
                    for k in p.keywords)
        distinct = sum(1 for k in p.keywords if re.search(rf"(?<![\w/]){re.escape(k)}(?![\w])", text, re.IGNORECASE))
        if distinct >= 2 and score >= min_hits and score > best_score:
            best, best_score = p.id, score
    return best
