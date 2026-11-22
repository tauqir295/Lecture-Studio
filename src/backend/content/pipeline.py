"""Turn any supported source file into a 16:9 slide PDF + companion manifest.

The output plugs into the existing PDF import path (render → narration → TTS →
video), so the rest of the studio stays format- and topic-agnostic.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from src.backend.content.deck_renderer import render_pdf
from src.backend.content.importers import detect_type, import_document
from src.backend.content.model import ContentDocument
from src.backend.content.slide_builder import SlideSpec, build_slides
from src.backend.companion import FORMAT, MANIFEST_SUFFIX
from src.utils.process_utils import find_tool, no_window_kwargs


@dataclass
class ConversionResult:
    pdf: Path
    manifest: Path
    document: Optional[ContentDocument]
    slides: List[SlideSpec] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    method: str = ""


def _write_manifest(out_dir: Path, pdf: Path, title: str, entries: List[dict]) -> Path:
    manifest = out_dir / (pdf.stem + MANIFEST_SUFFIX)
    manifest.write_text(json.dumps({"format": FORMAT, "deck_title": title, "pdf": pdf.name, "files": {},
                                    "slides": entries}, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _pptx_via_libreoffice(src: Path, out_dir: Path) -> Optional[Path]:
    soffice = find_tool("soffice") or find_tool("libreoffice")
    if not soffice:
        return None
    try:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(src)],
                       capture_output=True, timeout=300, check=True, **no_window_kwargs())
    except Exception:
        return None
    pdf = out_dir / (src.stem + ".pdf")
    return pdf if pdf.is_file() else None


def convert_source(src: Path, out_dir: Path) -> ConversionResult:
    """Convert `src` (Markdown, text, code, DOCX, PPTX) into out_dir/deck.pdf + deck.json."""
    src = Path(src).resolve()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kind = detect_type(src)
    if kind == "pdf":
        raise ValueError("PDF needs no conversion.")
    doc = import_document(src, out_dir / "assets")
    pdf = out_dir / "deck.pdf"

    if kind == "pptx":
        # Faithful rendering when LibreOffice is installed; slides stay 1:1 with the original.
        lo_pdf = _pptx_via_libreoffice(src, out_dir)
        if lo_pdf:
            lo_pdf.replace(pdf)
            entries = []
            for i, sec in enumerate(doc.sections, 1):
                drafted = " ".join(b.plain_text().replace("\n", ". ") for b in sec.blocks if b.kind != "image")
                entries.append({"slide_number": i, "title": sec.title, "section": sec.title,
                                "source_page": sec.source_ref, "narration": sec.notes or drafted})
            return ConversionResult(pdf, _write_manifest(out_dir, pdf, doc.title, entries), doc, [], [],
                                    "libreoffice")

    slides = build_slides(doc)
    footer = doc.title if len(doc.title) < 80 else doc.title[:77] + "…"
    warnings = render_pdf(slides, pdf, footer)
    entries = [{"slide_number": i, "title": s.title, "section": s.section, "source_page": s.source_ref,
                "narration": s.narration} for i, s in enumerate(slides, 1)]
    return ConversionResult(pdf, _write_manifest(out_dir, pdf, doc.title, entries), doc, slides, warnings,
                            "rebuilt")
