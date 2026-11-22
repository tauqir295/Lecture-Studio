"""Companion lecture packages.

A companion package is a `<pdf-stem>.json` manifest that sits next to a
presentation PDF (any other `*.json` in the folder also works if its "pdf" field names the PDF). It carries per-slide narration scripts and metadata, plus a
list of related files (narration document, technical review, slide mapping,
HTML deck). When such a PDF is imported, the package is applied to the project
instead of auto-drafting narration from slide text.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.models.narration import NarrationStatus, SlideNarration
from src.models.project import Project
from src.utils.logging_config import setup_logger

logger = setup_logger("companion")

FORMAT = "ppt-lecture-studio/companion@1"
MANIFEST_SUFFIX = ".json"   # manifest = <pdf-stem>.json; only files with FORMAT are used


@dataclass
class CompanionPackage:
    manifest_path: Path
    data: Dict[str, Any]
    slides: List[Dict[str, Any]] = field(default_factory=list)
    files: Dict[str, Path] = field(default_factory=dict)  # role -> existing absolute path

    @property
    def title(self) -> str:
        return self.data.get("deck_title", self.manifest_path.stem)

    def summary(self) -> str:
        return f"{len(self.slides)} narration scripts, {len(self.files)} related files"


def find_companion(pdf_path: str | Path) -> Optional[CompanionPackage]:
    """Return the companion package for a PDF, or None if there is none / it is invalid."""
    pdf = Path(pdf_path).resolve()
    candidates = [pdf.with_name(pdf.stem + MANIFEST_SUFFIX)]
    candidates += sorted(p for p in pdf.parent.glob("*" + MANIFEST_SUFFIX) if p not in candidates)
    for manifest in candidates:
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning(f"Ignoring unreadable companion manifest {manifest}: {exc}")
            continue
        if data.get("format") != FORMAT:
            continue
        # Generic manifests in the folder must name this PDF explicitly.
        if manifest != candidates[0] and data.get("pdf") != pdf.name:
            continue
        files = {}
        for role, rel in (data.get("files") or {}).items():
            p = (manifest.parent / rel).resolve()
            if p.is_file():
                files[role] = p
            else:
                logger.warning(f"Companion file '{rel}' ({role}) listed but missing.")
        slides = [s for s in data.get("slides", []) if isinstance(s.get("slide_number"), int)]
        logger.info(f"Found companion package {manifest.name} for {pdf.name}")
        return CompanionPackage(manifest, data, slides, files)
    return None


def apply_companion(project: Project, pkg: CompanionPackage) -> List[str]:
    """Load narrations / slide metadata into `project` and copy related files.

    Returns a list of warnings. Narrations stay in DRAFT status so the
    review and approval gates still apply.
    """
    warnings: List[str] = []
    root = Path(project.project_dir)
    by_num = {s["slide_number"]: s for s in pkg.slides}

    if len(pkg.slides) != len(project.slides):
        warnings.append(f"Companion package has {len(pkg.slides)} slides but the PDF has "
                        f"{len(project.slides)}; matching by slide number.")

    narrations: List[SlideNarration] = []
    wpm = int(pkg.data.get("words_per_minute") or 140)
    for slide in project.slides:
        entry = by_num.get(slide.slide_number)
        if not entry:
            continue
        if entry.get("title"):
            slide.title = entry["title"]
        slide.metadata.update({k: entry[k] for k in ("section", "source_page", "slide_key") if k in entry})
        slide.metadata["companion"] = True
        n = SlideNarration(slide_id=slide.slide_id, slide_number=slide.slide_number,
                           script=entry.get("narration", "").strip(), status=NarrationStatus.DRAFT)
        n.calculate_metrics(wpm)
        slide.duration_estimate = n.estimated_duration
        narrations.append(n)
    project.narrations = narrations

    # Copy related files into the self-contained project directory.
    copied: Dict[str, str] = {}
    dest_dir = root / "companion"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for role, src in {**pkg.files, "manifest": pkg.manifest_path}.items():
        target = (root / "narration" / src.name) if role == "narration" else (dest_dir / src.name)
        shutil.copy2(src, target)
        copied[role] = str(target.relative_to(root))

    project.companion = {
        "manifest": copied.get("manifest", ""),
        "deck_title": pkg.title,
        "files": copied,
        "slides_with_narration": len(narrations),
        "warnings": warnings,
    }
    logger.info(f"Applied companion package: {len(narrations)} narrations, {len(copied)} files")
    return warnings
