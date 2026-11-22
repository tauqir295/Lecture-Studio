"""Topic-neutral content model shared by every importer.

Importers (Markdown, text, code, DOCX, PPTX, ...) turn a source file into a
`ContentDocument`; the slide builder turns that into slides. Nothing here knows
about any particular subject; topic knowledge lives in optional profiles.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Block kinds
HEADING, PARAGRAPH, BULLETS, CODE, IMAGE, TABLE, QUOTE = (
    "heading", "paragraph", "bullets", "code", "image", "table", "quote")


@dataclass
class Block:
    kind: str
    text: str = ""                                  # paragraph / quote / heading / code / image caption
    items: List[str] = field(default_factory=list)  # bullets
    rows: List[List[str]] = field(default_factory=list)  # table (first row = header)
    language: str = ""                              # code language
    image_path: Optional[Path] = None               # extracted image file
    numbered: bool = False
    level: int = 1                                  # heading level

    def plain_text(self) -> str:
        if self.kind == BULLETS:
            return "\n".join(self.items)
        if self.kind == TABLE:
            return "\n".join(" | ".join(r) for r in self.rows)
        return self.text


@dataclass
class Section:
    title: str
    blocks: List[Block] = field(default_factory=list)
    notes: str = ""          # author narration / speaker notes (preferred over drafted narration)
    level: int = 1
    source_ref: str = ""     # e.g. "slide 3", "heading 'Setup'", "lines 10–24"


@dataclass
class ContentDocument:
    title: str
    sections: List[Section] = field(default_factory=list)
    source_type: str = ""    # markdown | text | code | docx | pptx | pdf
    source_path: Optional[Path] = None
    subtitle: str = ""

    def all_text(self) -> str:
        parts = [self.title, self.subtitle]
        for s in self.sections:
            parts.append(s.title)
            parts.extend(b.plain_text() for b in s.blocks)
            parts.append(s.notes)
        return "\n".join(p for p in parts if p)
