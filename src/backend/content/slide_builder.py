"""ContentDocument -> video-sized slide specs (topic-neutral).

Rules: one idea per slide, limited text per slide, long content is split across
continuation slides instead of shrinking fonts. All source text is kept, either
on a slide or in its narration — nothing is silently dropped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from src.backend.content.model import (BULLETS, CODE, HEADING, IMAGE, PARAGRAPH, QUOTE, TABLE, Block,
                                       ContentDocument, Section)

MAX_BULLETS = 6
MAX_WORDS = 60          # prose words per slide
MAX_CODE_LINES = 14
MAX_TABLE_ROWS = 7      # excluding header
MAX_TABLE_COLS = 5


@dataclass
class SlideSpec:
    kind: str                     # title | content | code | image | table
    title: str
    kicker: str = ""              # section / document label
    elements: List[Block] = field(default_factory=list)
    narration: str = ""
    source_ref: str = ""
    section: str = ""


def _words(t: str) -> int:
    return len(t.split())


def _sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def _split_paragraph(text: str, limit: int = MAX_WORDS) -> List[str]:
    out, cur = [], []
    for s in _sentences(text):
        if cur and _words(" ".join(cur + [s])) > limit:
            out.append(" ".join(cur)); cur = []
        cur.append(s)
    if cur:
        out.append(" ".join(cur))
    return out


def _speak(block: Block) -> str:
    """Narration drafted from a block, keeping source wording."""
    if block.kind in (PARAGRAPH, QUOTE):
        return block.text
    if block.kind == HEADING:
        return f"{block.text}."
    if block.kind == BULLETS:
        return " ".join(i.strip().rstrip(".") + "." for i in block.items if i.strip())
    if block.kind == CODE:
        lang = f"{block.language} " if block.language else ""
        n = len(block.text.splitlines())
        decl = _declarations(block.text)
        what = f" It defines {', '.join(decl[:-1]) + ' and ' + decl[-1] if len(decl) > 1 else decl[0]}." if decl else ""
        return f"Here is the {lang}code, {n} line{'s' if n != 1 else ''}.{what} Let's walk through what it does."
    if block.kind == TABLE and block.rows:
        head = ", ".join(c for c in block.rows[0] if c)
        return f"This table lists {head}." if head else "This table summarises the details."
    if block.kind == IMAGE:
        return block.text or "Take a look at this diagram."
    return ""


_DECL = re.compile(
    r"^\s*(?:export\s+|public\s+|private\s+|protected\s+|internal\s+|static\s+|abstract\s+|open\s+|async\s+|data\s+|suspend\s+)*"
    r"(class|interface|object|enum|struct|trait|def|fun|func|fn|function|type)\s+([A-Za-z_][\w]*)")


def _declarations(code: str) -> List[str]:
    """Names of classes/functions declared in a code chunk, any common language."""
    kinds = {"def": "function", "fun": "function", "func": "function", "fn": "function", "function": "function"}
    out = []
    for line in code.splitlines():
        m = _DECL.match(line)
        if m:
            out.append(f"{kinds.get(m.group(1), m.group(1))} {m.group(2)}")
    return out[:6]


class _Packer:
    def __init__(self, doc: ContentDocument, sec: Section):
        self.doc, self.sec = doc, sec
        self.slides: List[SlideSpec] = []
        self.cur: Optional[SlideSpec] = None

    def _open(self, kind: str = "content") -> SlideSpec:
        s = SlideSpec(kind, self.sec.title, self.doc.title if self.sec.level <= 1 else self.doc.title,
                      source_ref=self.sec.source_ref, section=self.sec.title)
        self.slides.append(s)
        return s

    def _text_load(self, s: SlideSpec) -> tuple:
        bullets = sum(len(b.items) for b in s.elements if b.kind == BULLETS)
        words = sum(_words(b.text) for b in s.elements if b.kind in (PARAGRAPH, QUOTE, HEADING))
        return bullets, words

    def add_text(self, block: Block) -> None:
        if self.cur is None or self.cur.kind != "content":
            self.cur = self._open()
        bullets, words = self._text_load(self.cur)
        if block.kind == BULLETS:
            items = list(block.items)
            while items:
                room = MAX_BULLETS - bullets - (1 if words else 0) - words // 25
                if room <= 0:
                    self.cur = self._open(); bullets, words = 0, 0
                    continue
                take, items = items[:room], items[room:]
                self.cur.elements.append(Block(BULLETS, items=take, numbered=block.numbered))
                bullets += len(take)
                if items:
                    self.cur = self._open(); bullets, words = 0, 0
            return
        # prose: split long paragraphs into slide-sized chunks
        for chunk in _split_paragraph(block.text):
            if words + _words(chunk) + bullets * 8 > MAX_WORDS and (words or bullets):
                self.cur = self._open(); bullets, words = 0, 0
            self.cur.elements.append(Block(block.kind, chunk, level=block.level))
            words += _words(chunk)

    def add_code(self, block: Block, caption: Optional[Block]) -> None:
        lines = block.text.splitlines() or [""]
        parts = [lines[i:i + MAX_CODE_LINES] for i in range(0, len(lines), MAX_CODE_LINES)]
        for n, part in enumerate(parts, 1):
            s = self._open("code")
            if caption is not None and n == 1:
                s.elements.append(caption)
            s.elements.append(Block(CODE, "\n".join(part), language=block.language))
            if len(parts) > 1:
                s.title = f"{self.sec.title} ({n}/{len(parts)})"
        self.cur = None

    def add_image(self, block: Block) -> None:
        s = self._open("image")
        s.elements.append(block)
        self.cur = None

    def add_table(self, block: Block) -> None:
        rows = block.rows
        if not rows:
            return
        header, body = rows[0], rows[1:]
        col_groups = [list(range(i, min(i + MAX_TABLE_COLS, len(header))))
                      for i in range(0, max(len(header), 1), MAX_TABLE_COLS)]
        chunks = [body[i:i + MAX_TABLE_ROWS] for i in range(0, len(body), MAX_TABLE_ROWS)] or [[]]
        total = len(col_groups) * len(chunks)
        n = 0
        for cols in col_groups:
            for chunk in chunks:
                n += 1
                s = self._open("table")
                pick = lambda r: [r[c] if c < len(r) else "" for c in cols]
                s.elements.append(Block(TABLE, rows=[pick(header)] + [pick(r) for r in chunk]))
                if total > 1:
                    s.title = f"{self.sec.title} ({n}/{total})"
        self.cur = None


def build_slides(doc: ContentDocument) -> List[SlideSpec]:
    slides: List[SlideSpec] = []
    intro = Block(PARAGRAPH, doc.subtitle) if doc.subtitle else None
    t = SlideSpec("title", doc.title, kicker=doc.source_type.upper() if doc.source_type else "",
                  elements=[intro] if intro else [], section="Intro", source_ref="document")
    t.narration = f"Welcome. In this video we cover {doc.title}." + (f" {doc.subtitle}." if doc.subtitle else "")
    slides.append(t)

    for sec in doc.sections:
        if not sec.blocks and not sec.notes:
            continue
        pk = _Packer(doc, sec)
        blocks = list(sec.blocks)
        i = 0
        while i < len(blocks):
            b = blocks[i]
            nxt = blocks[i + 1] if i + 1 < len(blocks) else None
            if b.kind == CODE:
                pk.add_code(b, None)
            elif b.kind == IMAGE:
                pk.add_image(b)
            elif b.kind == TABLE:
                pk.add_table(b)
            elif (b.kind == PARAGRAPH and nxt is not None and nxt.kind == CODE and _words(b.text) <= 35):
                pk.add_code(nxt, b)          # short intro sentence becomes the code caption
                i += 1
            else:
                pk.add_text(b)
            i += 1
        if not pk.slides:                    # notes-only section
            pk._open()
        content = [s for s in pk.slides if s.kind == "content"]
        for n, s in enumerate(content, 1):        # number text continuations only
            if len(content) > 1:
                s.title = f"{sec.title} ({n}/{len(content)})"
        for s in pk.slides:
            s.narration = " ".join(x for x in (_speak(e) for e in s.elements) if x).strip()
        if sec.notes:
            if doc.source_type == "code":        # code comments add to the drafted walkthrough
                pk.slides[0].narration = f"{pk.slides[0].narration} {sec.notes.strip()}".strip()
            else:                                # author notes win, on the section's first slide
                pk.slides[0].narration = sec.notes.strip()
        slides.extend(pk.slides)
    return slides
