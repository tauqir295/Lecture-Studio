"""Parse narration text with emotion/style tags into segments.

Syntax
  [happy] text…        style from here to the next tag or the end of the paragraph
  [/happy] or [/]      back to the paragraph's starting style
  [pause] / [pause 2s] silence (default 1 s; up to 10 s)
  blank line           new paragraph (style resets to the document default unless the
                       paragraph starts with a tag)
  *word*               emphasis markers are removed (no local model supports emphasis yet)

Tags are case-insensitive. Any style key from src/backend/tts/emotion.py works, plus a few aliases.
Bracketed text that is not a tag (e.g. "[1]", "[see figure]") is left in the text.
Each sentence is its own segment, so it can be regenerated on its own.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from src.backend.audio import tag_registry
from src.backend.tts import emotion

ALIASES = {
    "joyful": "happy", "cheerful": "happy", "scared": "fearful", "afraid": "fearful",
    "whisper": "whispering", "story": "storytelling", "narrator": "storytelling",
    "content": "satisfied", "mad": "angry", "upset": "sad", "enthusiastic": "enthusiastic",
}
MAX_PAUSE = 10.0

_TAG = re.compile(r"\[\s*(/?)\s*([^\[\]]*?)\s*\]")
_SENT_END = re.compile(r"(?<=[.!?…])[\"')\]]*\s+")


@dataclass
class Segment:
    index: int
    text: str                 # text to speak (tags removed)
    emotion: str
    paragraph: int
    pause_before: float = 0.0  # explicit [pause] seconds before this segment

    @property
    def label(self) -> str:
        return emotion.get(self.emotion).label


@dataclass
class ParseResult:
    segments: List[Segment] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    trailing_pause: float = 0.0


def resolve_tag(name: str) -> str:
    """Style key for a tag name, or '' if it is not a style."""
    n = (name or "").strip().lower()
    n = ALIASES.get(n, n)
    all_keys = {s.key for s in emotion.styles()}
    if n in all_keys:
        return n
    t = tag_registry.get_tag(n)
    if t and t.tag in all_keys:
        return t.tag
    return ""


def known_tags() -> List[str]:
    return [t.tag for t in tag_registry.all_tags()]


def _split_sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENT_END.split(text) if s and s.strip()]


def parse(text: str, default: str = emotion.NEUTRAL, model_id: Optional[str] = None) -> ParseResult:
    out = ParseResult()
    default_key = resolve_tag(default) or emotion.NEUTRAL
    pending_pause = 0.0
    paragraphs = [p for p in re.split(r"\n\s*\n", text or "")]
    pi = -1
    for para in paragraphs:
        if not para.strip():
            continue
        pi += 1
        para = re.sub(r"\s+", " ", para).strip()
        start_style, current, buf = default_key, default_key, ""
        seen_text = False                              # any text before the current tag in this paragraph

        def flush():
            nonlocal buf, pending_pause
            for s in _split_sentences(buf):
                clean = re.sub(r"\*+([^*]+)\*+", r"\1", s).strip()
                if re.search(r"\w", clean):
                    out.segments.append(Segment(len(out.segments), clean, current, pi, pending_pause))
                    pending_pause = 0.0
            buf = ""

        pos = 0
        for m in _TAG.finditer(para):
            closing = m.group(1)
            raw = (m.group(2) or "").strip()
            lower = raw.lower()

            # 1. Generic closing [/]
            if closing and not raw:
                chunk = para[pos:m.start()]
                seen_text = seen_text or bool(re.search(r"\w", chunk))
                buf += chunk
                pos = m.end()
                flush()
                current = start_style
                continue

            # 2. Pause tags: [pause], [pause 2s], [pause 1.5 s]
            is_pause = lower == "pause" or lower.startswith("pause ") or lower.startswith("pause-") or (
                lower.startswith("pause") and len(lower) > 5 and lower[5] in "0123456789."
            )
            if is_pause:
                chunk = para[pos:m.start()]
                seen_text = seen_text or bool(re.search(r"\w", chunk))
                buf += chunk
                pos = m.end()
                flush()
                secs = 1.0
                dur_match = re.search(r"[\d.]+\s*s?", lower[5:]) if len(lower) > 5 else None
                if dur_match:
                    num_str = dur_match.group(0).rstrip("s").strip()
                    try:
                        secs = float(num_str)
                    except ValueError:
                        out.warnings.append(f"Bad pause length '{num_str}'; using 1 s.")
                pending_pause += min(max(secs, 0.0), MAX_PAUSE)
                continue

            # 3. Known tag in tag_registry or resolve_tag
            tag_def = tag_registry.get_tag(lower)
            resolved = resolve_tag(lower)
            key = resolved or (tag_def.tag if tag_def else "")

            # Specific closing [/happy] or [/deep and loud shouting]
            if closing and key:
                chunk = para[pos:m.start()]
                seen_text = seen_text or bool(re.search(r"\w", chunk))
                buf += chunk
                pos = m.end()
                flush()
                current = start_style
                continue

            if key and not closing:
                # Valid style/tag
                if tag_def and not tag_def.is_supported_by(model_id):
                    model_name = model_id or "the selected TTS model"
                    out.warnings.append(
                        f"Tag [{tag_def.tag}] in paragraph {pi + 1} is not supported by {model_name} (requires Qwen3-TTS)."
                    )
                chunk = para[pos:m.start()]
                seen_text = seen_text or bool(re.search(r"\w", chunk))
                buf += chunk
                pos = m.end()
                flush()
                current = key
                if not seen_text:
                    start_style = key
                continue

            # 4. Not a recognized tag: distinguish citations from unknown tags
            has_digits = bool(re.search(r"\d", raw))
            is_citation_word = lower.startswith(("fig", "see ", "ref", "table", "note", "cf", "p."))
            if not has_digits and not is_citation_word:
                if re.fullmatch(r"[A-Za-z_-]+", raw) and len(raw) <= 30:
                    out.warnings.append(f"Unknown tag [{raw}] in paragraph {pi + 1}; it is read as text.")
            # Leave non-tag bracket in buffer and continue scanning
            continue

        buf += para[pos:]
        flush()
    out.trailing_pause = pending_pause
    return out
